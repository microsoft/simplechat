# test_v2_admin_global_agents_actions.py
"""
Browser coverage for V2 Admin Settings categories and the global agents and actions.
Version: 0.261.268
Implemented in: 0.261.268

Run against the real built SPA with the real Admin Settings field schema and a
closed in-memory API (fixtures/v2_admin_global_editors.py). Check that choosing a
settings category always opens it at its top; that the Global Agents and Global
Actions sections list, enable, disable, delete and choose the default agent, and
create and edit through the same editors workspaces use, on the admin-only routes;
that a Call agent action is an ordinary global action whose targets are global
agents and which a global agent attaches in its editor; that the template gallery
starts and publishes a global agent; that a failed load can be retried and a stale
save keeps the draft; that opening an editor asks before dropping unsaved
settings; and that a non-administrator reaches none of it. This replaces the
MemoryRouter harness coverage of the removed "Global agent delegation" card
(formerly test_agent_delegation_v2.py).
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_global_editors import (  # noqa: E402
    ARCHIVE_AGENT_ID,
    CREATED_ACTION_ID,
    CREATED_AGENT_ID,
    FORECAST_ACTION_ID,
    GLOBAL_SECTIONS,
    MODEL_LABEL,
    ORIGIN,
    POLICY_AGENT_ID,
    RESEARCH_AGENT_ID,
    STORED_KEY,
    TICKET_ACTION_ID,
    GlobalEditorsFixture,
    connect_options,  # noqa: F401
)


pytestmark = pytest.mark.ui
ARTIFACTS = "v2_admin_global_agents_actions"
SCROLL_SECTIONS = {
    "appearance": ("classification-banner-section", "ai-notice-section"),
    **GLOBAL_SECTIONS,
    "knowledge": ("web-search-section",),
}


@pytest.fixture
def global_ui(page):
    fixture = GlobalEditorsFixture(page)
    yield fixture
    fixture.assert_clean()


def _scroll_area(page):
    return page.get_by_test_id("admin-settings-scroll")


def _scroll_to_end(page):
    top = _scroll_area(page).evaluate(
        "element => { element.scrollTop = element.scrollHeight; return element.scrollTop; }"
    )
    assert top > 0, "The category is too short to scroll, so the check would prove nothing."


def _expect_at_top(page):
    page.wait_for_function(
        "() => document.querySelector('[data-testid=\"admin-settings-scroll\"]').scrollTop === 0"
    )


def _category(page, label):
    return page.get_by_role("complementary", name="Settings categories").get_by_role(
        "button", name=label, exact=True
    )


def _editor_section(page, label):
    page.get_by_role("navigation", name="Editor sections", exact=True).get_by_role(
        "button", name=label, exact=True
    ).click()


def _action_field(page, label):
    return page.get_by_label(re.compile(rf"^{re.escape(label)}(?:\s*\*)?\s*$"))


def _save(ui, button, method, path):
    with ui.page.expect_response(
        lambda response: response.request.method == method and urlsplit(response.url).path == path
    ) as response:
        ui.page.get_by_role("button", name=button, exact=True).click()
    return response.value


def _personal_requests(ui):
    return [
        (method, path) for method, path in ui.requests_seen
        if path.startswith(("/api/user/agents", "/api/user/plugins", "/api/group"))
    ]


def test_choosing_a_category_starts_at_its_top(page):
    """Leaving one category scrolled down must not open the next one part-way down."""
    ui = GlobalEditorsFixture(page, sections=SCROLL_SECTIONS)
    ui.settings["classification_banner_enabled"] = True
    page.emulate_media(reduced_motion="reduce")
    ui.open(width=1920, height=700, ready_region="Classification Banner")
    index = page.get_by_role("navigation", name="On this page")

    _category(page, "Agents & Actions").click()
    expect(_category(page, "Agents & Actions")).to_have_attribute("aria-pressed", "true")
    _scroll_to_end(page)
    expect(index.get_by_role("link", name=re.compile("^Agent Runtime"))).not_to_have_attribute(
        "aria-current", "location"
    )

    _category(page, "Knowledge").click()
    _expect_at_top(page)
    expect(page.get_by_role("region", name="Web Search", exact=True)).to_be_in_viewport()

    # Back to a long category: it opens at its first section, which the index marks.
    _category(page, "Agents & Actions").click()
    _expect_at_top(page)
    expect(page.get_by_role("region", name="Agent Runtime", exact=True)).to_be_in_viewport()
    expect(index.get_by_role("link", name=re.compile("^Agent Runtime"))).to_have_attribute(
        "aria-current", "location"
    )

    # Choosing the category already shown returns to its top as well.
    _scroll_to_end(page)
    _category(page, "Agents & Actions").click()
    _expect_at_top(page)

    _scroll_to_end(page)
    _category(page, "All settings").click()
    _expect_at_top(page)
    expect(page.get_by_role("region", name="Classification Banner", exact=True)).to_be_in_viewport()
    ui.assert_clean()


def test_choosing_a_category_on_a_phone_starts_at_its_top(page):
    ui = GlobalEditorsFixture(page, sections=SCROLL_SECTIONS)
    ui.settings["classification_banner_enabled"] = True
    ui.open(width=390, height=844, ready_region="Classification Banner")
    categories = page.get_by_label("Settings category", exact=True)

    categories.select_option("agents-actions")
    _scroll_to_end(page)
    categories.select_option("knowledge")
    _expect_at_top(page)
    expect(page.get_by_role("region", name="Web Search", exact=True)).to_be_in_viewport()

    categories.select_option("agents-actions")
    _expect_at_top(page)
    _scroll_to_end(page)
    categories.select_option("")
    _expect_at_top(page)
    ui.assert_clean()


def test_global_agents_are_listed_and_managed_in_place(global_ui):
    ui, page = global_ui, global_ui.page
    ui.open(ready_region="Global Agents")
    section = page.get_by_role("region", name="Global Agents", exact=True)
    rows = section.get_by_test_id("global-agent-row")
    expect(rows).to_have_count(3)
    expect(rows.nth(0)).to_contain_text("Archive summarizer")
    expect(rows.nth(2)).to_contain_text("Research assistant")
    # The delegation card is gone: a Call agent action is an ordinary global action now.
    expect(page.get_by_text("Global agent delegation")).to_have_count(0)
    expect(page.get_by_role("button", name="New Call agent action")).to_have_count(0)
    expect(section.get_by_role("button", name="Start from a template", exact=True)).to_be_visible()

    research = rows.filter(has_text="Research assistant")
    expect(research.get_by_text("Default agent", exact=True)).to_be_visible()
    expect(research.get_by_text("Choose another default to delete", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Delete Research assistant", exact=True)).to_have_count(0)
    archive = rows.filter(has_text="Archive summarizer")
    expect(archive.get_by_text("Disabled", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Make Archive summarizer the default agent")).to_have_count(0)

    page.get_by_role("button", name="Make Policy advisor the default agent", exact=True).click()
    expect(rows.filter(has_text="Policy advisor").get_by_text("Default agent", exact=True)).to_be_visible()
    expect(research.get_by_text("Default agent", exact=True)).to_have_count(0)
    assert ui.writes_to("POST", "/api/admin/agents/selected_agent")[-1][2] == {"name": "policy-advisor"}

    page.get_by_role("button", name="Delete Research assistant", exact=True).click()
    assert not ui.writes_to("DELETE", f"/api/v2/admin/agents/{RESEARCH_AGENT_ID}")
    page.get_by_role("button", name="Delete agent", exact=True).click()
    expect(rows).to_have_count(2)
    assert RESEARCH_AGENT_ID not in ui.agents
    assert len(ui.writes_to("DELETE", f"/api/v2/admin/agents/{RESEARCH_AGENT_ID}")) == 1

    page.get_by_role("button", name="Enable Archive summarizer", exact=True).click()
    expect(archive.get_by_text("Disabled", exact=True)).to_have_count(0)
    assert ui.writes_to("PATCH", "/api/admin/agents/archive-summarizer/enabled")[-1][2] == {"is_enabled": True}

    # Disabling the default hands it to an enabled agent, as the classic route does.
    page.get_by_role("button", name="Disable Policy advisor", exact=True).click()
    expect(page.get_by_text(
        "Policy advisor disabled. Archive summarizer is now the default agent.", exact=True,
    )).to_be_visible()
    expect(archive.get_by_text("Default agent", exact=True)).to_be_visible()
    expect(rows.filter(has_text="Policy advisor").get_by_text("Disabled", exact=True)).to_be_visible()
    assert ui.selected_agent_name == "archive-summarizer"
    assert not _personal_requests(ui)
    ui.capture("global-agents", ARTIFACTS)


def test_global_actions_are_listed_and_managed_in_place(global_ui):
    ui, page = global_ui, global_ui.page
    ui.open(ready_region="Global Actions")
    section = page.get_by_role("region", name="Global Actions", exact=True)
    rows = section.get_by_test_id("global-action-row")
    expect(rows).to_have_count(2)
    forecast = rows.filter(has_text="Forecast lookup")
    tickets = rows.filter(has_text="Ticket search")
    expect(forecast.get_by_text("Disabled", exact=True)).to_be_visible()

    page.get_by_role("button", name="Enable Forecast lookup", exact=True).click()
    expect(forecast.get_by_text("Disabled", exact=True)).to_have_count(0)
    assert ui.writes_to("PATCH", "/api/admin/plugins/forecast_lookup/enabled")[-1][2] == {"is_enabled": True}

    page.get_by_role("button", name="Disable Ticket search", exact=True).click()
    expect(tickets.get_by_text("Disabled", exact=True)).to_be_visible()
    assert ui.writes_to("PATCH", "/api/admin/plugins/ticket_search/enabled")[-1][2] == {"is_enabled": False}

    agents_before = {key: dict(value) for key, value in ui.agents.items()}
    page.get_by_role("button", name="Delete Forecast lookup", exact=True).click()
    page.get_by_role("button", name="Delete action", exact=True).click()
    expect(rows).to_have_count(1)
    assert FORECAST_ACTION_ID not in ui.actions
    assert ui.agents == agents_before
    assert not _personal_requests(ui)
    ui.capture("global-actions", ARTIFACTS)


def test_a_new_global_agent_is_created_in_the_shared_editor(global_ui):
    ui, page = global_ui, global_ui.page
    ui.open(ready_region="Global Agents")
    page.get_by_role("region", name="Global Agents", exact=True).get_by_role(
        "button", name="New agent", exact=True
    ).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/agents/new")
    expect(page.get_by_text("Global agents", exact=True)).to_be_visible()

    page.get_by_label("Display name", exact=True).fill("Benefits guide")
    page.get_by_label("Description", exact=True).fill("Answers benefits questions for everyone.")
    _editor_section(page, "Model & connection")
    page.get_by_label("Model", exact=True).select_option(label=MODEL_LABEL)

    _editor_section(page, "Actions")
    expect(page.get_by_role("checkbox", name="Assign Ticket search", exact=True)).to_be_visible()
    page.get_by_role("checkbox", name="Assign Ticket search", exact=True).check()

    # A global agent answers everyone, so only public workspaces can ground it.
    _editor_section(page, "Assigned knowledge")
    restrict = page.get_by_role("checkbox", name=re.compile("^Restrict to assigned knowledge"))
    restrict.focus()
    page.keyboard.press("Space")
    expect(restrict).to_be_checked()
    expect(page.get_by_text(
        "Only public workspaces can be assigned, because a global agent answers everyone.", exact=False,
    )).to_be_visible()
    page.get_by_role("checkbox", name=re.compile("^Published handbook")).check()

    _editor_section(page, "Instructions")
    page.get_by_role("textbox", name="Instructions", exact=True).fill("Answer from the approved benefits handbook.")
    assert not ui.writes_to("POST", "/api/v2/admin/agents")
    assert _save(ui, "Save agent", "POST", "/api/v2/admin/agents").status == 201

    write = ui.writes_to("POST", "/api/v2/admin/agents")[-1][2]
    assert write["clear_secret_paths"] == [] and write["removed_paths"] == []
    assert "expected_revision" not in write
    created = ui.agents[CREATED_AGENT_ID]
    assert created["display_name"] == "Benefits guide"
    assert re.fullmatch(r"[A-Za-z0-9_-]+", created["name"])
    assert created["actions_to_load"] == [TICKET_ACTION_ID]
    assert created["model_endpoint_id"] == "org-model-endpoint" and created["model_id"] == "org-model"
    assert created["other_settings"]["assigned_knowledge"]["scopes"]["public_workspace_ids"] == ["public-handbook"]
    assert created["is_global"] is True

    # Saving returns to the list it started from, scrolled to and focused on it.
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/agents")
    expect(page.get_by_role("heading", name="Global Agents", level=2)).to_be_focused()
    expect(page.get_by_role("link", name="Benefits guide", exact=True)).to_be_visible()
    assert not _personal_requests(ui)


def test_a_template_starts_and_publishes_a_global_agent(global_ui):
    ui, page = global_ui, global_ui.page
    ui.open(ready_region="Global Agents")
    page.get_by_role("button", name="Start from a template", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/agents/new?templates=1")
    template = page.get_by_role("heading", name="Onboarding guide", exact=True)
    expect(template).to_be_in_viewport()
    page.get_by_role("button", name="Use template", exact=True).click()
    expect(page.get_by_label("Display name", exact=True)).to_have_value("Onboarding guide")

    # An administrator publishes straight to the approved gallery, as the organisation.
    page.get_by_role("button", name="Publish as template", exact=True).click()
    expect(page.get_by_text("Template published to the approved gallery.", exact=True)).to_be_visible()
    published = ui.writes_to("POST", "/api/agent-templates")[-1][2]["template"]
    assert published["source_scope"] == "global"
    assert published["display_name"] == "Onboarding guide"

    _editor_section(page, "Model & connection")
    page.get_by_label("Model", exact=True).select_option(label=MODEL_LABEL)
    assert _save(ui, "Save agent", "POST", "/api/v2/admin/agents").status == 201
    created = ui.agents[CREATED_AGENT_ID]
    assert created["display_name"] == "Onboarding guide"
    assert created["instructions"] == "Help new colleagues find onboarding answers in the approved handbook."
    assert created["tags"] == ["onboarding"]
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/agents")


def test_a_call_agent_action_is_an_ordinary_global_action(global_ui):
    """Create a Call agent action in Global Actions, then attach it in a global agent's editor."""
    ui, page = global_ui, global_ui.page
    ui.open(ready_region="Global Actions")
    page.get_by_role("region", name="Global Actions", exact=True).get_by_role(
        "button", name="New action", exact=True
    ).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/actions/new")
    _action_field(page, "Action type").select_option("agent")
    # Choosing a type adds the other sections; the rows above them must stay laid out.
    expect(_action_field(page, "Action type")).to_be_visible()
    expect(_action_field(page, "Action type")).to_have_value("agent")
    _action_field(page, "Action name").fill("Ask the policy advisor")
    page.get_by_label("Description", exact=True).fill("Hand policy questions to the policy advisor.")
    _editor_section(page, "Configuration")
    page.get_by_label("Search target agents", exact=True).fill("Policy")
    target = _action_field(page, "Target agent")
    option = target.get_by_role("option").filter(has_text="Policy advisor")
    expect(option).to_have_count(1)
    expect(option).to_contain_text("global")
    target.select_option(option.get_attribute("value"))
    assert _save(ui, "Save action", "POST", "/api/v2/admin/actions").status == 201

    targets_read = [query for method, path, query, _ in ui.global_requests if path == "/api/plugins/agent-targets"]
    assert targets_read and all(query == {"scope": ["global"]} for query in targets_read)
    created = ui.actions[CREATED_ACTION_ID]
    assert created["type"] == "agent"
    assert created["endpoint"] == "internal://agent"
    assert created["auth"] == {"type": "user"}
    assert created["additionalFields"]["target_agent"] == {
        "id": POLICY_AGENT_ID, "scope_type": "global", "scope_id": "global",
    }
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/actions")
    expect(page.get_by_role("heading", name="Global Actions", level=2)).to_be_focused()
    expect(page.get_by_role("link", name="Ask the policy advisor", exact=True)).to_be_visible()

    # A global agent attaches it like any other action, through its own editor.
    _category(page, "Agents & Actions").click()
    page.get_by_role("link", name="Research assistant", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/agents/{RESEARCH_AGENT_ID}")
    _editor_section(page, "Actions")
    attach = page.get_by_role("checkbox", name="Assign Ask the policy advisor", exact=True)
    attach.check()
    revision = ui.revision(RESEARCH_AGENT_ID)
    path = f"/api/v2/admin/agents/{RESEARCH_AGENT_ID}"
    assert _save(ui, "Save agent", "PATCH", path).status == 200
    write = ui.writes_to("PATCH", path)[-1][2]
    assert write["expected_revision"] == revision
    assert write["updates"] == {"actions_to_load": [CREATED_ACTION_ID]}
    assert ui.agents[RESEARCH_AGENT_ID]["actions_to_load"] == [CREATED_ACTION_ID]
    assert not _personal_requests(ui)


def test_editing_a_global_action_keeps_its_stored_credential(global_ui):
    ui, page = global_ui, global_ui.page
    ui.open(ready_region="Global Actions")
    page.get_by_role("link", name="Ticket search", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/actions/{TICKET_ACTION_ID}")
    name = _action_field(page, "Action name")
    expect(name).to_have_value("Ticket search")
    expect(name).to_be_editable()
    revision = ui.revision(TICKET_ACTION_ID)
    name.fill("Service desk search")
    path = f"/api/v2/admin/actions/{TICKET_ACTION_ID}"
    assert _save(ui, "Save action", "PATCH", path).status == 200
    assert ui.writes_to("PATCH", path)[-1][2] == {
        "updates": {"displayName": "Service desk search"},
        "expected_revision": revision,
        "clear_secret_paths": [],
        "removed_paths": [],
    }
    saved = ui.actions[TICKET_ACTION_ID]
    assert saved["displayName"] == "Service desk search"
    assert saved["auth"] == {"type": "key", "key": STORED_KEY}
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/actions")
    expect(page.get_by_role("link", name="Service desk search", exact=True)).to_be_visible()


def test_failures_are_shown_and_a_conflicting_draft_is_kept(global_ui):
    """A failed list load can be retried, and a stale save keeps the draft instead of overwriting."""
    ui, page = global_ui, global_ui.page
    ui.fail_next("GET", "/api/v2/admin/actions", error="Global actions are unavailable right now.")
    ui.open(ready_region="Global Actions")
    section = page.get_by_role("region", name="Global Actions", exact=True)
    expect(section.get_by_role("alert")).to_have_text("Global actions are unavailable right now.")
    expect(section.get_by_test_id("global-action-row")).to_have_count(0)
    section.get_by_role("button", name="Refresh", exact=True).click()
    expect(section.get_by_role("alert")).to_have_count(0)
    expect(section.get_by_test_id("global-action-row")).to_have_count(2)

    page.get_by_role("link", name="Policy advisor", exact=True).click()
    description = page.get_by_label("Description", exact=True)
    expect(description).to_have_value("Policy advisor for everyone in the organisation.")
    # Another administrator saves first.
    ui.agents[POLICY_AGENT_ID]["description"] = "Changed by another administrator."
    ui.revisions[POLICY_AGENT_ID] += 1
    description.fill("My edit to the policy advisor.")
    path = f"/api/v2/admin/agents/{POLICY_AGENT_ID}"
    assert _save(ui, "Save agent", "PATCH", path).status == 409
    expect(page.get_by_text("This agent changed in another session.", exact=False)).to_be_visible()
    expect(page.get_by_role("link", name="Open latest in a new tab", exact=True)).to_be_visible()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/agents/{POLICY_AGENT_ID}")
    expect(description).to_have_value("My edit to the policy advisor.")
    assert ui.agents[POLICY_AGENT_ID]["description"] == "Changed by another administrator."


def test_unsaved_settings_are_kept_unless_discarded_before_opening_an_editor(global_ui):
    """Opening a global editor replaces the page, so it asks before dropping unsaved settings."""
    ui, page = global_ui, global_ui.page
    ui.open(ready_region="Global Agents")
    page.get_by_text("Allow Group Agents", exact=True).click()
    expect(page.get_by_text("1 unsaved change", exact=True)).to_be_visible()
    dialog = page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)

    page.get_by_role("region", name="Global Agents", exact=True).get_by_role(
        "button", name="New agent", exact=True
    ).click()
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Keep editing", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(page).to_have_url(f"{ORIGIN}/v2/admin")
    expect(page.get_by_text("1 unsaved change", exact=True)).to_be_visible()

    # The approvals queue opens in a new tab, so it never takes the draft with it.
    approvals = page.get_by_role("link", name=re.compile("^Open the approvals queue"))
    expect(approvals).to_have_attribute("target", "_blank")
    expect(approvals).to_have_attribute("rel", "noopener noreferrer")

    # An editor link asks as well, and discarding leaves without saving anything.
    page.get_by_role("link", name="Policy advisor", exact=True).click()
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Discard changes", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/agents/{POLICY_AGENT_ID}")
    expect(page.get_by_label("Display name", exact=True)).to_have_value("Policy advisor")
    assert not ui.patches


@pytest.mark.parametrize("path", ["/admin", "/admin/agents/new", f"/admin/actions/{TICKET_ACTION_ID}"])
def test_a_non_administrator_reaches_no_global_agent_or_action(page, path):
    ui = GlobalEditorsFixture(page, admin=False)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{ORIGIN}/v2{path}", wait_until="networkidle")
    expect(page.get_by_text("Administrator access required", exact=True)).to_be_visible()
    expect(page.get_by_role("textbox", name="Display name")).to_have_count(0)
    assert not ui.admin_reads(), ui.admin_reads()
    assert ARCHIVE_AGENT_ID in ui.agents and not ui.global_writes
    ui.assert_clean()
