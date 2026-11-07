# test_v2_chat_picker_search.py
"""
Browser regressions for Documents-style search in V2 chat catalog pickers.
Version: 0.261.395
Implemented in: 0.261.395

Runs the real Composer, Dropdown, stores, and production theme CSS; only HTTP is
synthetic. Reuses local Chromium or configured Azure Playwright through the shared
DefaultAzureCredential connection fixture, without provisioning cloud resources.

Run: python -m pytest .\\ui_tests\\test_v2_chat_picker_search.py -q
"""

import copy
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_v2_composer_picker_overlays import check_hit, check_panel
from test_v2_chat_context_selection import ContextApi
from test_v2_orchestration_model_picker import (  # noqa: F401
    AUTO, CHAT_PATH, PLAN_PATH, approval_assets, approval_browser, approval_ui,
    catalog_model, configure, connect_options, message_box, mount, open_manual,
    picker, send,
)


pytestmark = pytest.mark.ui
ARTIFACTS = Path(__file__).parent / "artifacts" / "chat-picker-search"
MODEL_SEARCH = "Search models by name or vendor"


def model(key, label, name, publisher, provider):
    entry = catalog_model(key, label, name, key.split(":")[0])
    entry.update(model_name=name, provider=provider)
    entry["profile"].update(displayName=name, publisher=publisher)
    return entry


MODELS = (
    model("east:writer", "Daily writer", "gpt-4.1", "openai", "aoai"),
    model("west:review", "Review model", "claude-sonnet-4-5", "anthropic", "custom"),
    model("east:quick", "Quick answers", "grok-4", "xai", "new_foundry"),
    model("local:reason", "Local reasoning", "llama-4", "meta", "custom"),
)
AGENTS = (
    {"id": "analyst", "name": "analyst", "display_name": "Briefing analyst",
     "description": "Forecast analysis for leadership", "scope_type": "personal"},
    {"id": "guide", "name": "guide", "display_name": "Response guide",
     "description": "Incident triage and escalation", "scope_type": "group"},
    {"id": "sparse", "name": "sparse", "display_name": "Sparse agent", "scope_type": "public"},
)
PROMPTS = (
    {"id": "brief", "name": "Weekly brief", "description": "Forecast narrative for leadership",
     "content": "Write a concise update.", "scope_type": "personal"},
    {"id": "plan", "name": "Response plan", "description": "Incident triage checklist",
     "content": "Draft the next steps.", "scope_type": "group"},
    {"id": "sparse", "name": "Sparse prompt", "content": "Unlisted body sentinel.", "scope_type": "public"},
)


def prepare(approval_ui, *, width=1280, height=800, orchestrating=False, agents=AGENTS,
            prompts=PROMPTS, models=MODELS, theme="light"):
    open_page, api = approval_ui
    configure(api, models=models, orchestration=orchestrating)
    api.bootstrap["catalogs"].update(agents=copy.deepcopy(agents), prompts=copy.deepcopy(prompts))
    page = open_page(width)
    page.set_viewport_size({"width": width, "height": height})
    mount(page, api)
    page.evaluate(
        "theme => document.documentElement.classList.toggle('dark', theme === 'dark')", theme,
    )
    if orchestrating:
        open_manual(page)
    return page, api


def search_box(page, name=MODEL_SEARCH):
    return page.get_by_role("searchbox", name=name, exact=True)


def flush_settings(page):
    page.evaluate("async () => await window.OrchHarness.stores.userSettings.useUserSettingsStore.getState().flush()")


@pytest.mark.parametrize("orchestrating", [False, True])
def test_model_names_vendors_families_and_selection_identity(approval_ui, orchestrating):
    page, api = prepare(approval_ui, orchestrating=orchestrating)
    trigger = picker(page) if orchestrating else page.get_by_role("button", name="Daily writer", exact=True)
    original_label = trigger.inner_text()
    trigger.click()
    search = search_box(page)
    expect(search).to_be_focused()
    listbox = page.get_by_role("listbox", name="Orchestration model options" if orchestrating else "Model options")
    all_labels = ([AUTO] if orchestrating else []) + [entry["display_name"] for entry in MODELS]
    expect(listbox.get_by_role("option")).to_have_text(all_labels)
    flush_settings(page)
    before_writes = len(api.writes)
    for query, label in [
        ("  OPENAI  ", "Daily writer"), ("anthropic", "Review model"),
        ("GROK", "Quick answers"), ("llama", "Local reasoning"),
        ("gpt-4.1", "Daily writer"), ("xAI", "Quick answers"),
    ]:
        search.fill(query)
        expect(listbox.get_by_role("option")).to_have_text([label])
        expect(trigger).to_have_text(original_label)
    search.fill("no matching model")
    expect(listbox.get_by_role("option")).to_have_count(0)
    expect(listbox.get_by_role("status")).to_have_text("Nothing matches that.")
    flush_settings(page)
    assert len(api.writes) == before_writes
    search.fill(" ")
    expect(listbox.get_by_role("option")).to_have_text(all_labels)
    if orchestrating:
        search.fill("auto")
        expect(listbox.get_by_role("option")).to_have_text([AUTO])
        search.fill("")
    search.fill("anthropic")
    listbox.get_by_role("option", name="Review model", exact=True).click()
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    flush_settings(page)
    setting = "orchestrationPreferredModelId" if orchestrating else "preferredModelId"
    assert api.settings[setting] == MODELS[1]["selection_key"]
    send(page, PLAN_PATH if orchestrating else CHAT_PATH, "Use the model I selected through search.")
    request = api.plans[-1] if orchestrating else api.chats[-1]
    assert request["model_id"] == MODELS[1]["model_id"]
    assert request["model_endpoint_id"] == MODELS[1]["endpoint_id"]
    assert request["model_provider"] == MODELS[1]["provider"]


@pytest.mark.parametrize("kind", ["Agent", "Prompt"])
def test_description_matching_groups_preserved_selection_and_clear(approval_ui, kind):
    page, _api = prepare(approval_ui)
    trigger = page.get_by_role("button", name=kind, exact=True)
    trigger.click()
    search = search_box(page, f"Search {kind.lower()}s")
    expect(search).to_be_focused()
    listbox = page.get_by_role("listbox", name=f"{kind} options")
    search.fill("  FORECAST  ")
    label = "Briefing analyst" if kind == "Agent" else "Weekly brief"
    expect(listbox.get_by_role("option")).to_have_count(1)
    expect(listbox.get_by_role("option").first).to_contain_text(label)
    expect(listbox.get_by_text("personal", exact=True)).to_be_visible()
    expect(listbox.get_by_text("group", exact=True)).to_have_count(0)
    listbox.get_by_role("option").first.click()
    chosen = page.get_by_role("button", name=label, exact=True)
    expect(chosen).to_be_visible()
    chosen.click()
    expect(search).to_have_value("")
    expect(listbox.get_by_role("option")).to_have_count(3)
    expect(listbox.get_by_role("option", name=re.compile(f"^{label}"))).to_have_attribute("aria-selected", "true")
    search.fill("triage")
    expect(listbox.get_by_role("option")).to_have_count(1)
    expect(chosen).to_be_visible()
    search.fill("unlisted body sentinel")
    expect(listbox.get_by_role("option")).to_have_count(0)
    expect(listbox.get_by_role("status")).to_have_text("Nothing matches that.")
    clear = page.get_by_role("button", name="Clear selection", exact=True)
    expect(clear).to_be_visible()
    clear.click()
    expect(trigger).to_be_visible()
    trigger.click()
    expect(search).to_have_value("")
    search.fill(f"Sparse {kind.lower()}")
    expect(listbox.get_by_role("option")).to_have_count(1)


def test_search_keyboard_editing_navigation_and_no_accidental_send(approval_ui):
    page, api = prepare(approval_ui)
    message_box(page).fill("Keep this draft unsent.")
    trigger = page.get_by_role("button", name="Daily writer", exact=True)
    trigger.focus()
    page.keyboard.press("ArrowDown")
    search = search_box(page)
    expect(search).to_be_focused()
    search.fill("writer")
    search.press("Home")
    assert search.evaluate("element => element.selectionStart") == 0
    search.press("End")
    assert search.evaluate("element => element.selectionStart") == len("writer")
    expect(search).to_be_focused()
    search.press("Enter")
    expect(search).to_be_focused()
    expect(page.locator(".composer-picker-panel")).to_be_visible()
    assert not api.chats and not api.plans
    search.press("ArrowDown")
    expect(page.get_by_role("option", name="Daily writer", exact=True)).to_be_focused()
    page.keyboard.press("ArrowUp")
    expect(search).to_be_focused()
    search.fill("anthropic")
    search.press("ArrowUp")
    expect(page.get_by_role("option", name="Review model", exact=True)).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.get_by_role("button", name="Review model", exact=True)).to_be_focused()
    page.get_by_role("button", name="Review model", exact=True).click()
    expect(search).to_have_value("")
    search.press("Escape")
    expect(page.get_by_role("button", name="Review model", exact=True)).to_be_focused()
    page.get_by_role("button", name="Review model", exact=True).click()
    search.press("Tab")
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    assert not api.chats and not api.plans


def test_queries_are_isolated_and_model_choice_exits_agent_mode(approval_ui):
    page, _api = prepare(approval_ui)
    page.get_by_role("button", name="Daily writer", exact=True).click()
    search_box(page).fill("anthropic")
    agent = page.get_by_role("button", name="Agent", exact=True)
    agent.focus()
    page.keyboard.press("Enter")
    search = search_box(page, "Search agents")
    expect(search).to_have_value("")
    search.fill("forecast")
    page.get_by_role("option", name=re.compile("^Briefing analyst")).click()
    page.get_by_role("button", name="Model", exact=True).click()
    expect(search_box(page)).to_have_value("")
    search_box(page).fill("anthropic")
    page.get_by_role("option", name="Review model", exact=True).click()
    expect(agent).to_be_visible()
    expect(page.get_by_role("button", name="Briefing analyst", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Review model", exact=True).click()
    search_box(page).fill("grok")
    message_box(page).click()
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    expect(message_box(page)).to_be_focused()
    page.get_by_role("button", name="Review model", exact=True).click()
    expect(search_box(page)).to_have_value("")


def test_single_entry_search_and_the_prompt_slash_shortcut(approval_ui):
    page, _api = prepare(approval_ui, models=MODELS[:1], agents=AGENTS[:1], prompts=PROMPTS[:1])
    for kind, name in [("Daily writer", MODEL_SEARCH), ("Agent", "Search agents"), ("Prompt", "Search prompts")]:
        page.get_by_role("button", name=kind, exact=True).click()
        expect(search_box(page, name)).to_be_visible()
        expect(page.get_by_role("option")).to_have_count(1)
        page.keyboard.press("Escape")
    message_box(page).fill("/forecast")
    suggestions = page.get_by_role("listbox", name="Prompt suggestions", exact=True)
    expect(suggestions.get_by_role("option")).to_have_count(1)
    expect(suggestions.get_by_role("option")).to_contain_text("Weekly brief")
    page.keyboard.press("Enter")
    expect(suggestions).to_have_count(0)
    expect(page.get_by_role("button", name="Weekly brief", exact=True)).to_be_visible()
    expect(page.get_by_text("Write a concise update.", exact=True)).to_have_count(0)
    expect(message_box(page)).to_have_value("")


@pytest.mark.parametrize("width,theme", [(360, "light"), (360, "dark"), (1280, "light"), (1280, "dark")])
def test_search_stays_visible_during_scrolling_and_matches_legacy_documents_style(approval_ui, width, theme):
    agents = [dict(AGENTS[0], id=f"agent-{index}", display_name=f"Agent {index:02d}") for index in range(40)]
    page, _api = prepare(approval_ui, width=width, agents=agents, theme=theme)
    page.get_by_role("button", name="Agent", exact=True).click()
    panel, _box = check_panel(page, width, 800)
    search = search_box(page, "Search agents")
    before = search.bounding_box()
    listbox = page.get_by_role("listbox", name="Agent options")
    listbox.evaluate("element => { element.scrollTop = element.scrollHeight; }")
    assert listbox.evaluate("element => element.scrollTop") > 0
    assert search.bounding_box() == before
    check_hit(listbox.get_by_role("option").last)
    expect(search).to_be_visible()
    search.fill("Agent 39")
    expect(listbox.get_by_role("option")).to_have_count(1)
    check_hit(listbox.get_by_role("option").first)
    style = """element => {
        const style = getComputedStyle(element);
        return Object.fromEntries(['backgroundColor', 'borderColor', 'borderRadius',
            'fontSize', 'paddingTop', 'paddingBottom', 'paddingLeft', 'paddingRight', 'color']
            .map(key => [key, style[key]]));
    }"""
    search_style = search.evaluate(style)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACTS / f"search-{width}-{theme}.png"))
    page.keyboard.press("Escape")
    context_api = ContextApi()
    page.route(re.compile(r"https://simplechat\.test/api/documents(?:/[^?]+)?(?:\?.*)?$"), context_api.handle)
    # Restricted/inline editors retain the compact Documents field this picker mirrors.
    # The main composer intentionally uses the independently approved workspace sidebar.
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.unmount('mount-a');
        H.mount('mount-a', 'ComposerEditor', {
            id: 'legacy-picker-reference', label: 'Answer', conversationId: null,
            draft: {text: '', contextItems: [], attachedPrompt: null, promptValues: {}, uploads: [], imageReferences: []},
            onChange: () => {}, pickerOpen: true, allowContext: true,
        });
    }""")
    documents_search = page.locator("[data-context-picker]").get_by_role("searchbox")
    expect(documents_search).to_be_focused()
    assert documents_search.evaluate(style) == search_style
    page.keyboard.press("Escape")
    assert not context_api.unexpected, context_api.unexpected


def test_non_searchable_dropdowns_keep_their_keyboard_behavior(approval_ui):
    page, _api = prepare(approval_ui, orchestrating=True)
    page.get_by_title("Approval mode", exact=True).click()
    panel = page.locator(".composer-picker-panel")
    expect(panel.get_by_role("searchbox")).to_have_count(0)
    expect(page.get_by_role("option", name=re.compile("^Review"))).to_be_focused()
    page.keyboard.press("End")
    expect(page.get_by_role("option", name=re.compile("^Review"))).to_be_focused()
    page.keyboard.press("Home")
    expect(page.get_by_role("option", name=re.compile("^Auto"))).to_be_focused()
