# test_v2_composer_picker_overlays.py
"""
Real-component regressions for anchored composer picker overlays.
Version: 0.261.327
Implemented in: 0.261.327

Production Composer, Dropdown, stores and theme CSS; only HTTP is synthetic.
Local Chromium by default, Azure Playwright through the shared connection fixture.
Real Safari keyboard and safe-area behavior require a physical device.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from test_v2_sidebar_conversation_scroll import mount
from test_v2_orchestration_approval_persistence import ApprovalApi, mount as mount_approval
from test_v2_orchestration_model_picker import configure as configure_models, WRITER, SUMMARY
from test_v2_chat_context_selection import ContextApi

pytest_plugins = (
    "test_v2_sidebar_conversation_scroll",
    "test_v2_orchestration_plan_editor",
    "test_v2_orchestration_approval_persistence",
)
pytestmark = pytest.mark.ui
ARTIFACTS = Path(__file__).parent / "artifacts" / "composer-picker-overlays"


@pytest.fixture
def picker_approval_ui(editor_browser, approval_assets):
    # Reuse the running Playwright connection rather than nesting a second sync loop.
    api = ApprovalApi(approval_assets)
    contexts = []
    errors = []

    def make_page(width):
        context = editor_browser.new_context(viewport={"width": width, "height": 900})
        contexts.append(context)
        page = context.new_page()
        page.route("**/*", api.handle)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        return page

    yield make_page, api
    for context in contexts:
        context.close()
    assert not api.unexpected, api.unexpected
    assert not errors, errors


def populate(page):
    page.evaluate("""() => {
        const H = window.OrchHarness;
        const models = [{
            selection_key: 'global::test:writer', model_id: 'writer', endpoint_id: 'test',
            deployment_name: 'writer', provider: 'aoai', display_name: 'Writer',
            reasoning_capabilities: {status: 'supported', efforts: ['low', 'medium', 'high'], default_effort: 'low'},
        }, {selection_key: 'global::test:summary', model_id: 'summary', endpoint_id: 'test',
            deployment_name: 'summary', provider: 'aoai', display_name: 'Summary'}];
        const grouped = (kind) => Array.from({length: 36}, (_, i) => ({
            id: `${kind}-${i}`, name: `${kind} ${String(i).padStart(2, '0')}`,
            display_name: `${kind} ${String(i).padStart(2, '0')}`,
            description: 'A detailed synthetic catalog entry for geometry and selection checks.',
            scope_type: i < 12 ? 'personal' : i < 24 ? 'group' : 'public',
            content: 'Write a short synthetic summary without variables.',
        }));
        H.stores.bootstrap.useBootstrapStore.setState(state => ({data: {
            ...state.data, features: {...state.data.features, enable_chat_orchestration: true,
                enable_web_search: true, enable_deep_source_review: true, enable_image_generation: true},
            catalogs: {models, initial_model_selection: models[0], agents: grouped('Agent'), prompts: grouped('Prompt')},
            orchestration: {enabled: true, capabilities: [], default_approval_mode: 'manual',
                allow_user_approval_override: true, show_manual_controls: true, timed_approval_seconds: 8},
        }}));
    }""")


def open_tools(page, width):
    if width < 768:
        tools = page.get_by_role("button", name="Chat tools", exact=True)
        if tools.get_attribute("aria-expanded") == "false":
            tools.click()


def check_panel(page, width, height):
    panel = page.locator(".composer-picker-panel")
    expect(panel).to_have_count(1)
    expect(panel).to_be_visible()
    box = panel.bounding_box()
    assert box and box["x"] >= 11 and box["y"] >= 11, box
    assert box["x"] + box["width"] <= width - 11, box
    assert box["y"] + box["height"] <= height - 11, box
    if width < 768:
        heights = panel.locator("button").evaluate_all("buttons => buttons.map(button => button.getBoundingClientRect().height)")
        assert all(height >= 44 for height in heights), heights
    overflow = page.evaluate("document.documentElement.scrollWidth > innerWidth")
    assert not overflow
    return panel, box


def check_hit(option):
    option.scroll_into_view_if_needed()
    expect(option).to_be_visible()
    hit = option.evaluate("""element => {
        const r = element.getBoundingClientRect();
        return element.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2));
    }""")
    assert hit, "Option is clipped or covered at its actual click point"


def test_first_agent_option_is_hit_testable_above_tools_boundary(open_page):
    """Also runs against the original Dropdown to reproduce the real overflow defect."""
    page, api = open_page({"width": 360, "height": 740})
    mount(page, api, rows=0)
    populate(page)
    open_tools(page, 360)
    page.get_by_role("button", name="Orchestrate", exact=True).click()
    page.get_by_role("button", name="Agent", exact=True).click()
    first = page.get_by_role("listbox", name="Agent options").get_by_role("option").first
    bounds = first.bounding_box()
    tools = page.locator("#composer-secondary-tools").bounding_box()
    assert bounds and bounds["y"] + bounds["height"] < tools["y"], (bounds, tools)
    hit = first.evaluate("""element => {
        const r = element.getBoundingClientRect();
        return element.contains(document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2));
    }""")
    assert hit, f"First Agent option is clipped above the tools boundary: {bounds}, tools: {tools}"
    first.click()
    expect(page.get_by_role("button", name="Agent 00", exact=True)).to_be_visible()


@pytest.mark.parametrize("width,height,theme,large", [
    (320, 740, "light", False), (360, 740, "dark", False),
    (393, 852, "light", True), (430, 932, "dark", False),
    (852, 393, "dark", False), (1280, 800, "light", False),
])
def test_grouped_agent_and_prompt_options_escape_tools_and_remain_clickable(open_page, width, height, theme, large):
    page, api = open_page({"width": width, "height": height})
    mount(page, api, rows=0)
    populate(page)
    page.evaluate("""({theme, large}) => {
        document.documentElement.classList.toggle('dark', theme === 'dark');
        if (large) document.documentElement.dataset.fontSize = 'xl';
    }""", {"theme": theme, "large": large})
    open_tools(page, width)
    # Enable manual selection, leaving the existing primary actions and layout unchanged.
    page.get_by_role("button", name="Orchestrate", exact=True).click()
    send_before = page.get_by_role("button", name="Send message", exact=True).bounding_box()
    for kind in ("Agent", "Prompt"):
        trigger = page.get_by_role("button", name=kind, exact=True)
        trigger.click()
        panel, box = check_panel(page, width, height)
        if width < 768:
            tools_box = page.locator("#composer-secondary-tools").bounding_box()
            assert box["y"] < tools_box["y"], (box, tools_box)
            assert panel.evaluate("element => !element.closest('#composer-secondary-tools')")
        options = page.get_by_role("listbox", name=f"{kind} options").get_by_role("option")
        expect(options).to_have_count(36)
        check_hit(options.first)
        if kind == "Agent":
            ARTIFACTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(ARTIFACTS / f"agent-{width}-{theme}.png"))
        check_hit(options.last)
        if kind == "Prompt":
            hint = panel.get_by_text("Tip: type / in your message to choose a prompt.", exact=True)
            hint.scroll_into_view_if_needed()
            hint_bounds = hint.bounding_box()
            panel_bounds = panel.bounding_box()
            assert hint_bounds["y"] + hint_bounds["height"] <= panel_bounds["y"] + panel_bounds["height"], hint_bounds
        options.last.click()
        expect(panel).to_have_count(0)
        chosen = page.get_by_role("button", name=f"{kind} 35", exact=True)
        chosen.click()
        expect(page.get_by_role("option", name=f"{kind} 35", exact=False)).to_have_attribute("aria-selected", "true")
        clear = page.get_by_role("button", name="Clear selection", exact=True)
        check_hit(clear)
        clear.click()
        expect(panel).to_have_count(0)
        expect(trigger).to_be_visible()
    send_after = page.get_by_role("button", name="Send message", exact=True).bounding_box()
    assert send_before == send_after


def test_model_reasoning_keyboard_switching_and_disclosure_lifetime(open_page):
    page, api = open_page({"width": 360, "height": 740})
    mount(page, api, rows=0)
    populate(page)
    open_tools(page, 360)
    page.get_by_role("button", name="Orchestrate", exact=True).click()
    model = page.get_by_role("button", name="Writer", exact=True)
    model.focus()
    page.keyboard.press("ArrowDown")
    check_panel(page, 360, 740)
    expect(page.get_by_role("option", name="Writer", exact=True)).to_be_focused()
    page.keyboard.press("End")
    expect(page.get_by_role("option", name="Summary", exact=True)).to_be_focused()
    page.keyboard.press("Home")
    page.keyboard.press("Enter")
    model.click()
    page.keyboard.press("Escape")
    expect(model).to_be_focused()
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    model.click()
    page.get_by_role("button", name="Agent", exact=True).click()
    expect(page.get_by_role("listbox", name="Model options")).to_have_count(0)
    expect(page.get_by_role("listbox", name="Agent options")).to_be_visible()
    # Upward menus can cover another row; collapse remains accessible by keyboard.
    page.get_by_role("button", name="Chat tools", exact=True).focus()
    page.keyboard.press("Enter")
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    open_tools(page, 360)
    reasoning = page.get_by_role("button", name="Low", exact=True)
    reasoning.click()
    check_panel(page, 360, 740)
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    expect(page.get_by_role("button", name="High", exact=True)).to_be_focused()
    page.get_by_role("button", name="High", exact=True).click()
    page.get_by_role("textbox", name="Message", exact=True).click()
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    expect(page.get_by_role("textbox", name="Message", exact=True)).to_be_focused()
    model.click()
    page.keyboard.press("Tab")
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    model.click()
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({activeConversationId: 'conv-01'})")
    expect(page.locator(".composer-picker-panel")).to_have_count(0)


def test_scroll_resize_and_modal_layers(open_page):
    page, api = open_page({"width": 320, "height": 450})
    mount(page, api, rows=0)
    populate(page)
    open_tools(page, 320)
    page.get_by_role("button", name="Orchestrate", exact=True).click()
    page.get_by_role("button", name="Prompt", exact=True).click()
    panel, before = check_panel(page, 320, 450)
    scroll = page.locator("#composer-secondary-tools").evaluate("""element => {
        const before = element.scrollTop;
        element.scrollTop = before > 0 ? 0 : element.scrollHeight;
        return {before, after: element.scrollTop};
    }""")
    assert scroll["before"] != scroll["after"], scroll
    page.wait_for_function("""before => {
        const panel = document.querySelector('.composer-picker-panel');
        return !panel || Math.abs(panel.getBoundingClientRect().top - before) > 2;
    }""", arg=before["y"])
    if panel.count():
        check_panel(page, 320, 450)
    page.set_viewport_size({"width": 430, "height": 320})
    if panel.count():
        check_panel(page, 430, 320)
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 393, "height": 852})
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({activeConversationId: 'conv-01'})")
    page.get_by_role("button", name="Agent", exact=True).click()
    # Opening the real details tour dialog moves focus outside and removes the picker.
    page.evaluate("""() => window.OrchHarness.stores.userSettings.useUserSettingsStore.setState({
        settings: {showTutorialButtons: true},
    })""")
    page.get_by_role("button", name="Conversation actions", exact=True).click()
    page.get_by_role("button", name="Take the chat tour", exact=True).click()
    expect(page.get_by_role("dialog")).to_be_visible()
    expect(panel).to_have_count(0)


def test_approval_and_orchestration_model_preserve_persistence_and_manual_collapse(picker_approval_ui):
    make_page, api = picker_approval_ui
    configure_models(api)
    page = make_page(393)
    mount_approval(page, api)
    open_tools(page, 393)
    approval = page.get_by_title("Approval mode", exact=True)
    approval.click()
    check_panel(page, 393, 900)
    page.get_by_role("option", name="After 8s", exact=False).click()
    page.evaluate("async () => await window.OrchHarness.stores.userSettings.useUserSettingsStore.getState().flush()")
    assert api.settings["orchestrationApprovalMode"] == "timed"
    page.get_by_title("Manual controls", exact=True).click()
    model = page.get_by_title("Auto chooses by task, then admin priority and favorites. A specific model stays pinned.")
    model.click()
    check_panel(page, 393, 900)
    page.get_by_role("option", name="Summary", exact=True).click()
    page.evaluate("async () => await window.OrchHarness.stores.userSettings.useUserSettingsStore.getState().flush()")
    assert api.settings["orchestrationPreferredModelId"] == SUMMARY["selection_key"]
    model.click()
    page.get_by_title("Manual controls", exact=True).click()
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    page.get_by_title("Manual controls", exact=True).click()
    expect(model).to_contain_text("Summary")
    model.click()
    page.get_by_role("option", name="Writer", exact=True).click()
    page.evaluate("async () => await window.OrchHarness.stores.userSettings.useUserSettingsStore.getState().flush()")
    assert api.settings["orchestrationPreferredModelId"] == WRITER["selection_key"]


def test_empty_disabled_and_non_composer_defaults(open_page):
    page, api = open_page({"width": 320, "height": 450})
    mount(page, api, rows=0, experience="Dropdown",
          props={"options": [], "placeholder": "Empty", "floating": True, "disabled": True})
    expect(page.get_by_role("button", name="Empty", exact=True)).to_be_disabled()
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    mount(page, api, rows=0, experience="Dropdown", props={"options": [], "placeholder": "Empty", "floating": True})
    page.get_by_role("button", name="Empty", exact=True).click()
    expect(page.get_by_text("Nothing available", exact=True)).to_be_visible()
    check_panel(page, 320, 450)
    mount(page, api, rows=0, experience="Dropdown", props={"options": [], "placeholder": "Default"})
    expect(page.locator(".composer-picker-panel")).to_have_count(0)
    page.get_by_role("button", name="Default", exact=True).click()
    expect(page.get_by_role("listbox", name="Default options")).to_be_visible()
    assert page.get_by_role("listbox").evaluate("element => Boolean(element.closest('#mount-a'))")


@pytest.mark.parametrize("width,height", [(320, 740), (1280, 800)])
def test_separate_document_picker_is_not_clipped_by_tools(open_page, width, height):
    page, api = open_page({"width": width, "height": height})
    context_api = ContextApi()
    page.route(re.compile(r"https://simplechat\.test/api/documents(?:/[^?]+)?(?:\?.*)?$"), context_api.handle)
    mount(page, api, rows=0)
    populate(page)
    open_tools(page, width)
    page.get_by_title("Orchestrate", exact=True).click()
    page.get_by_title("Documents", exact=True).click()
    panel = page.locator("[data-context-picker]")
    expect(panel).to_be_visible()
    document = panel.get_by_role("button", name=re.compile("^Quarterly brief"))
    expect(document).to_be_visible()
    check_hit(document)
    assert panel.evaluate("element => !element.closest('#composer-secondary-tools')")
    box = panel.bounding_box()
    assert box and box["y"] >= 0 and box["x"] >= 0, box
    assert box["x"] + box["width"] <= width and box["y"] + box["height"] <= height, box
    document.click()
    expect(document).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("Escape")
    expect(panel).to_have_count(0)
    assert not context_api.unexpected, context_api.unexpected
