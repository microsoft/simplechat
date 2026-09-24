# test_v2_group_agents.py
"""
Production-SPA coverage for the native scope-aware V2 group agents workbench.
Version: 0.261.145
Implemented in: 0.261.138

Exercises the real agent collection and full-page editor against closed synthetic
HTTP. The fixture serves only the immutable `/api/groups/<id>/agents` family, its
`/agent-options` and `/agent-knowledge` companions, and never a personal
`/api/user/*` read, so a group scope that leaked into personal authoring would fail
the run rather than be answered. A manager creates through the group route with no
`expected_revision`, edits with a conditional write, deletes with a no-body DELETE,
and keeps a draft on a stale-revision 409; an inline `agent_actions` gate hides
edit, delete and use-in-chat per agent beside an editable positive control; a
member gets a read-only workbench; a provided global agent opens read-only; the
group Use-in-chat link targets the named group; a group whose agent capability is
off keeps the classic view; and a new group action authored from the agent editor
returns into the retained group agent draft. Cross-scope draft isolation itself is
proven decisively by the shared runtime check in test_v2_group_action_drafts.ts.
"""

import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import ORIGIN, STORED_KEY
from ui_tests.fixtures.group_agents import (  # noqa: F401
    GroupAgentsFixture, connect_options, group_agents_ui,
    EDITABLE_AGENT_ID, WITHHELD_AGENT_ID, FOUNDRY_AGENT_ID, MEMBER_AGENT_ID, PROVIDED_AGENT_ID,
)
from ui_tests.fixtures.group_workspace import GROUP_FOUNDRY_ENDPOINT_ID  # noqa: F401
from ui_tests.test_v2_workspace_authoring import (
    begin_action, collection_item, configure_agent, editor_section, name_field,
)


pytestmark = pytest.mark.ui

LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]

EDITABLE_NAME = "Weekly reviewer"
WITHHELD_NAME = "Withheld reviewer"
FOUNDRY_NAME = "Foundry reviewer"
MEMBER_NAME = "Team charter agent"
PROVIDED_NAME = "Shared platform agent"


def open_agents(ui, group="group-a", **options):
    ui.open(f"/groups/{group}/agents", **options)
    expect(ui.page.get_by_role("heading", name="Agents", exact=True)).to_be_visible()


def open_editor(ui, identifier, group="group-a", **options):
    ui.open(f"/groups/{group}/agents/{identifier}", **options)


def item(ui, identifier):
    return ui.page.get_by_role("listitem").filter(has_text=identifier)


def agents_get(ui, group="group-a"):
    return [
        entry for entry in ui.requests
        if entry.path == f"/api/groups/{group}/agents" and entry.method == "GET"
    ]


def last_write(ui, path, method):
    matches = [entry for entry in ui.writes if entry.path == path and entry.method == method]
    assert matches, f"Expected a {method} to {path}; recorded writes: {[(w.method, w.path) for w in ui.writes]}"
    return matches[-1]


def save_agent(ui, group_id, *, identifier=None):
    method = "PATCH" if identifier else "POST"
    base = f"/api/groups/{group_id}/agents"
    path = f"{base}/{identifier}" if identifier else base
    with ui.page.expect_response(
        lambda response: response.request.method == method and urlsplit(response.url).path == path
    ) as response:
        ui.page.get_by_role("button", name="Save agent", exact=True).click()
    result = response.value
    if result.ok:
        expect(ui.page).to_have_url(f"{ORIGIN}/v2/groups/{group_id}/agents")
    return result


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_group_agent_layout(group_agents_ui, theme, width, height):
    """The manager collection matches the shell in both themes and both breakpoints."""
    ui = group_agents_ui
    open_agents(ui, theme=theme, width=width, height=height)
    expect(ui.page.get_by_role("button", name="New agent", exact=True)).to_be_enabled()
    expect(item(ui, EDITABLE_AGENT_ID)).to_be_visible()
    # The native collection renders, not the classic handoff.
    expect(ui.page.get_by_role("button", name="Open classic group workspace", exact=True)).to_have_count(0)
    ui.assert_no_overflow()


def test_group_agents_read_from_the_group_route_only(group_agents_ui):
    """Every list is a group read; no personal /api/user/agents request is ever made."""
    ui = group_agents_ui
    open_agents(ui)
    expect(item(ui, EDITABLE_AGENT_ID)).to_be_visible()
    assert agents_get(ui), "The collection must load from the group agents route."
    assert not [entry for entry in ui.requests if entry.path == "/api/user/agents"], (
        "A group workbench must never read personal agents."
    )


def test_group_agent_response_identity_is_validated(group_agents_ui):
    """A returned agent scoped to another group is refused rather than rendered."""
    ui = group_agents_ui
    # A foreign record carrying no stored credential: its id has no registered secret path, so the
    # projector will not echo a real key across the boundary while the identity guard trips.
    ui.native_agents["group-a"].append({
        **ui.record_agent("group-a", EDITABLE_AGENT_ID),
        "id": "foreign", "group_id": "group-z", "display_name": "Foreign agent",
        "agent_actions": [], "other_settings": {},
    })
    open_agents(ui)
    expect(ui.page.get_by_text(re.compile("does not match this group"))).to_be_visible()
    expect(ui.page.get_by_text("Foreign agent", exact=True)).to_have_count(0)


def test_inline_agent_actions_gate_edit_delete_and_chat(group_agents_ui):
    """The editable agent shows Edit, Delete and Use in chat; the withheld agent shows none."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_agents(ui)
    editable = item(ui, EDITABLE_AGENT_ID)
    expect(editable.get_by_role("button", name="Edit", exact=True)).to_be_visible()
    expect(editable.get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True)).to_be_visible()
    expect(editable.get_by_role("link", name="Use in chat", exact=True)).to_be_visible()

    withheld = item(ui, WITHHELD_AGENT_ID)
    expect(withheld.get_by_role("button", name="View details", exact=True)).to_be_visible()
    expect(withheld.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("button", name=f"Delete {WITHHELD_NAME}", exact=True)).to_have_count(0)
    expect(withheld.get_by_role("link", name="Use in chat", exact=True)).to_have_count(0)


def test_group_manager_creates_an_agent(group_agents_ui):
    """A manager authors a new agent through the group route with no expected_revision."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_agents(ui)
    page.get_by_role("button", name="New agent", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/groups/group-a/agents/new")
    configure_agent(page, "local", "Ledger reviewer")
    result = save_agent(ui, "group-a")
    assert result.status == 201
    write = last_write(ui, "/api/groups/group-a/agents", "POST")
    assert set(write.body) == {"updates", "clear_secret_paths", "removed_paths"}
    assert "expected_revision" not in write.body
    # The client-allocated id rides in updates exactly as the personal editor keeps it.
    assert isinstance(write.body["updates"].get("id"), str) and write.body["updates"]["id"]
    assert write.body["updates"]["display_name"] == "Ledger reviewer"
    assert not {"user_id", "is_global", "is_group", "group_id"} & set(write.body["updates"])
    created = next(a for a in ui.native_agents["group-a"] if a.get("display_name") == "Ledger reviewer")
    assert created["group_id"] == "group-a" and created["is_group"] is True and created["is_global"] is False


def test_group_manager_edits_with_a_conditional_write(group_agents_ui):
    """Editing an agent sends expected_revision and only the changed field."""
    ui, page = group_agents_ui, group_agents_ui.page
    revision = ui._agent_revision("group-a", EDITABLE_AGENT_ID)
    open_editor(ui, EDITABLE_AGENT_ID)
    name = name_field(page, "agent")
    expect(name).to_have_value(EDITABLE_NAME)
    name.fill("Weekly reviewer refreshed")
    result = save_agent(ui, "group-a", identifier=EDITABLE_AGENT_ID)
    assert result.ok
    write = last_write(ui, f"/api/groups/group-a/agents/{EDITABLE_AGENT_ID}", "PATCH")
    assert write.body["expected_revision"] == revision
    assert write.body["updates"] == {"display_name": "Weekly reviewer refreshed"}
    assert ui.record_agent("group-a", EDITABLE_AGENT_ID)["display_name"] == "Weekly reviewer refreshed"


def test_edit_preserves_the_stored_secret(group_agents_ui):
    """Renaming an agent without touching its connection key keeps the stored credential masked."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, EDITABLE_AGENT_ID)
    name_field(page, "agent").fill("Weekly reviewer renamed")
    result = save_agent(ui, "group-a", identifier=EDITABLE_AGENT_ID)
    assert result.ok
    stored = ui.record_agent("group-a", EDITABLE_AGENT_ID)["other_settings"]["connection"]["api_key"]
    assert stored == STORED_KEY
    ui.assert_no_secret_storage("Weekly reviewer renamed")


def test_group_manager_deletes_an_agent(group_agents_ui):
    """Deleting an agent confirms, calls DELETE with no body, and removes the row."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_agents(ui)
    item(ui, EDITABLE_AGENT_ID).get_by_role("button", name=f"Delete {EDITABLE_NAME}", exact=True).click()
    with page.expect_response(
        lambda response: response.request.method == "DELETE"
        and urlsplit(response.url).path == f"/api/groups/group-a/agents/{EDITABLE_AGENT_ID}"
    ):
        page.get_by_role("button", name="Delete agent", exact=True).click()
    expect(item(ui, EDITABLE_AGENT_ID)).to_have_count(0)
    write = last_write(ui, f"/api/groups/group-a/agents/{EDITABLE_AGENT_ID}", "DELETE")
    assert write.body is None
    assert ui.record_agent("group-a", EDITABLE_AGENT_ID) is None


def test_conflict_keeps_the_draft_and_offers_a_reload(group_agents_ui):
    """A stale revision keeps the editor and its draft and offers to load the saved agent."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, EDITABLE_AGENT_ID)
    name_field(page, "agent").fill("Draft in flight")
    ui.touch_agent("group-a", EDITABLE_AGENT_ID)
    result = save_agent(ui, "group-a", identifier=EDITABLE_AGENT_ID)
    assert result.status == 409
    expect(page.get_by_text(re.compile("changed in another session"))).to_be_visible()
    expect(name_field(page, "agent")).to_have_value("Draft in flight")


def test_group_agent_editor_makes_no_personal_scope_read(group_agents_ui):
    """Every side resource the editor loads is group-scoped; no personal read reaches the fixture."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, EDITABLE_AGENT_ID)
    # Visit every section that resolves a side resource so their loaders all fire.
    editor_section(page, "Model & connection")
    editor_section(page, "Actions")
    editor_section(page, "Assigned knowledge")
    expect(name_field(page, "agent")).to_have_value(EDITABLE_NAME)
    options_reads = [e for e in ui.requests if e.path == "/api/groups/group-a/agent-options"]
    knowledge_reads = [e for e in ui.requests if e.path == "/api/groups/group-a/agent-knowledge"]
    assert options_reads and all(not e.query for e in options_reads), (
        "Editor options must load from the group agent-options route with no query."
    )
    assert knowledge_reads and all(not e.query for e in knowledge_reads), (
        "Assigned knowledge must load from the group agent-knowledge route with no query."
    )
    assert not [e for e in ui.requests if e.path.startswith("/api/user/") and e.path != "/api/user/settings"], (
        "A group agent editor must not read any personal /api/user resource."
    )
    assert not [e for e in ui.requests if e.path.startswith("/api/workspace-identities/personal/")], (
        "A group agent editor must not read personal reusable identities."
    )
    assert not [e for e in ui.requests if e.query.get("agent_scope") == ["personal"]], (
        "A group agent editor must never request a personal agent scope."
    )
    assert not [e for e in ui.requests if e.path == "/api/plugins/mcp/preconfigurations"], (
        "A group agent editor must not read personal MCP preconfigurations."
    )


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
def test_member_gets_a_read_only_workbench(group_agents_ui, theme, width, height):
    """An ordinary member can read a group agent and launch it in chat, but cannot create, edit or delete."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_agents(ui, group="group-b", theme=theme, width=width, height=height)
    expect(page.get_by_role("button", name="New agent", exact=True)).to_be_disabled()
    member = item(ui, MEMBER_AGENT_ID)
    expect(member.get_by_role("button", name="View details", exact=True)).to_be_visible()
    expect(member.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    expect(member.get_by_role("button", name=f"Delete {MEMBER_NAME}", exact=True)).to_have_count(0)
    # Every served group agent row carries chat, members included, so a member can still launch it.
    chat_link = member.get_by_role("link", name="Use in chat", exact=True)
    expect(chat_link).to_be_visible()
    expect(chat_link).to_have_attribute(
        "href",
        f"/v2/chat?agent_id={MEMBER_AGENT_ID}&agent_scope=group&agent_scope_id=group-b&new=1",
    )
    ui.assert_no_overflow()


def test_member_editor_is_read_only(group_agents_ui):
    """A member who deep-links the editor sees details with a disabled name field and no Save."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, MEMBER_AGENT_ID, group="group-b")
    expect(name_field(page, "agent")).to_be_disabled()
    expect(page.get_by_role("button", name="Save agent", exact=True)).to_have_count(0)
    assert not [entry for entry in ui.writes if "/agents" in entry.path and entry.method != "GET"]


def test_member_editor_shows_neutral_model_copy(group_agents_ui):
    """A member gets no model endpoints, so the read-only editor shows neutral group copy, not personal guidance."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, MEMBER_AGENT_ID, group="group-b")
    editor_section(page, "Model & connection")
    expect(page.get_by_text("Uses a configured model.", exact=True)).to_be_visible()
    # The personal authoring guidance must never surface in a group scope.
    expect(page.get_by_text("No enabled models are listed.", exact=False)).to_have_count(0)


def test_manager_with_no_models_keeps_authoring_guidance(group_agents_ui):
    """A manager on a legacy-default-model tenant keeps actionable guidance, not the member's neutral copy."""
    ui, page = group_agents_ui, group_agents_ui.page
    # group-a manager options carry no model endpoints, exactly like a multi-model-off tenant.
    ui.empty_model_groups.add("group-a")
    open_editor(ui, EDITABLE_AGENT_ID)
    editor_section(page, "Model & connection")
    # The editor is writable, so the actionable custom-connection guidance is shown, not neutral copy.
    expect(page.get_by_text("No enabled models are listed.", exact=False)).to_be_visible()
    expect(page.get_by_text("Uses a configured model.", exact=True)).to_have_count(0)


def test_group_scoped_foundry_endpoint_discovers_via_named_group_route(group_agents_ui):
    """A group-scoped Foundry connection discovers through the named-group route, not the active-group one."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, FOUNDRY_AGENT_ID)
    editor_section(page, "Model & connection")
    # M5C re-enables discovery for a group-scoped connection through the named-group route, which
    # resolves the page's group from the path rather than the caller's active group.
    discover = page.get_by_role("button", name="Discover agents", exact=True)
    expect(discover).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/groups/group-a/models/foundry/agents"
    ) as response:
        discover.click()
    assert response.value.ok, "A group-scoped Foundry connection must discover through the named-group route."
    body = response.value.request.post_data_json
    assert body.get("endpoint_id") == GROUP_FOUNDRY_ENDPOINT_ID
    # The path scopes the group, so no scope field rides the named-group route.
    assert "scope" not in body, "The named-group Foundry route takes no scope field."
    assert not [entry for entry in ui.requests if entry.path == "/api/models/foundry/agents"], (
        "A group-scoped Foundry endpoint must not fall back to the active-group discovery route."
    )
    assert not ui.unexpected_requests, ui.unexpected_requests


def test_global_foundry_endpoint_keeps_discovery(group_agents_ui):
    """Selecting a global Foundry connection keeps discovery; its POST resolves without an active group."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, FOUNDRY_AGENT_ID)
    editor_section(page, "Model & connection")
    page.locator("#agent-foundry-connection").select_option(label="Global Foundry connection · global")
    discover = page.get_by_role("button", name="Discover agents", exact=True)
    expect(discover).to_be_visible()
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/models/foundry/agents"
    ) as response:
        discover.click()
    assert response.value.ok, "A global Foundry connection must discover without touching an active group."
    assert response.value.request.post_data_json.get("scope") == "global"
    # The global path resolves with no group dependency, so nothing is recorded as a cross-scope hazard.
    assert not ui.unexpected_requests, ui.unexpected_requests


def test_group_manager_submits_a_template(group_agents_ui):
    """With the group submission gate on, a manager sees 'Submit template' and the POST carries the payload."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, EDITABLE_AGENT_ID)
    editor_section(page, "Examples & templates")
    submit = page.get_by_role("button", name="Submit template", exact=True)
    expect(submit).to_be_visible()
    # The personal label never renders in a group scope.
    expect(page.get_by_role("button", name="Submit personal template", exact=True)).to_have_count(0)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/agent-templates"
    ) as response:
        submit.click()
    assert response.value.ok
    body = response.value.request.post_data_json["template"]
    assert body["display_name"] == EDITABLE_NAME
    # source_scope stays 'personal' to match classic and the templates container partition key.
    assert body["source_scope"] == "personal"
    expect(page.get_by_text("Template submitted for review.", exact=True)).to_be_visible()


def test_group_manager_with_submission_off_sees_no_submit_button(group_agents_ui):
    """When the server gate withholds submission, a manager sees no submit button and no POST fires."""
    ui, page = group_agents_ui, group_agents_ui.page
    ui.template_submission_denied.add("group-a")
    open_editor(ui, EDITABLE_AGENT_ID)
    editor_section(page, "Examples & templates")
    # The gallery still renders, but the submit affordance is gone in either scope's label.
    expect(page.get_by_role("button", name="Refresh templates", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Submit template", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Submit personal template", exact=True)).to_have_count(0)
    assert not [entry for entry in ui.requests if entry.path == "/api/agent-templates" and entry.method == "POST"]


def test_member_never_sees_template_submission(group_agents_ui):
    """A member's read-only editor never offers template submission in either scope's label."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, MEMBER_AGENT_ID, group="group-b")
    editor_section(page, "Examples & templates")
    expect(page.get_by_role("button", name="Submit template", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Submit personal template", exact=True)).to_have_count(0)


def test_provided_global_agent_opens_read_only_from_the_group_route(group_agents_ui):
    """A provided (global) agent lists and opens read-only: no edit, delete or use-in-chat."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_agents(ui)
    provided = item(ui, PROVIDED_AGENT_ID)
    expect(provided.get_by_role("button", name="View details", exact=True)).to_be_visible()
    expect(provided.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    expect(provided.get_by_role("button", name=f"Delete {PROVIDED_NAME}", exact=True)).to_have_count(0)
    expect(provided.get_by_text("Provided · read only", exact=True)).to_be_visible()

    open_editor(ui, PROVIDED_AGENT_ID)
    expect(name_field(page, "agent")).to_be_disabled()
    expect(page.get_by_role("button", name="Save agent", exact=True)).to_have_count(0)


def test_group_use_in_chat_link_targets_the_named_group(group_agents_ui):
    """The group Use-in-chat link carries agent_scope group and the group id, never personal."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_agents(ui)
    link = item(ui, EDITABLE_AGENT_ID).get_by_role("link", name="Use in chat", exact=True)
    expect(link).to_have_attribute(
        "href",
        f"/v2/chat?agent_id={EDITABLE_AGENT_ID}&agent_scope=group&agent_scope_id=group-a&new=1",
    )


def test_group_without_the_agents_capability_does_not_mount_the_native_workbench(group_agents_ui):
    """Agents off: the native workbench never mounts and the group agents route is never read."""
    ui, page = group_agents_ui, group_agents_ui.page
    ui.open("/groups/group-c/agents")
    # The section is unavailable, so the honest reason renders instead of a native collection.
    expect(page.get_by_text("Group agents are not enabled.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="New agent", exact=True)).to_have_count(0)
    assert not [entry for entry in ui.requests if entry.path.startswith("/api/groups/group-c/agents")], (
        "The agents route must not be read when the group agent capability is off."
    )


def test_new_group_action_from_the_agent_editor_returns_into_the_retained_draft(group_agents_ui):
    """Authoring a group action from the agent editor returns into the kept group agent draft."""
    ui, page = group_agents_ui, group_agents_ui.page
    open_editor(ui, EDITABLE_AGENT_ID)
    name_field(page, "agent").fill("Reviewer with a new action")
    editor_section(page, "Actions")
    page.get_by_role("button", name="New action", exact=True).click()
    # The action editor opens in the same group scope, carrying a return path to this agent.
    expect(page).to_have_url(re.compile(r"/v2/groups/group-a/actions/new\?"))
    begin_action(page, "fixture_custom", "Ledger companion")
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path == "/api/groups/group-a/actions"
    ) as created:
        page.get_by_role("button", name="Save action", exact=True).click()
    assert created.value.status == 201
    # Returned to the retained agent draft, not the collection, with the rename still present.
    expect(page).to_have_url(f"{ORIGIN}/v2/groups/group-a/agents/{EDITABLE_AGENT_ID}")
    expect(name_field(page, "agent")).to_have_value("Reviewer with a new action")
    # No agent write happened while authoring the action.
    assert not [entry for entry in ui.writes if entry.path.endswith(f"/agents/{EDITABLE_AGENT_ID}")]
