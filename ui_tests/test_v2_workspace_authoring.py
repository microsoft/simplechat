# test_v2_workspace_authoring.py
"""
Real-SPA browser workflows for native V2 My Workspace Agents and Actions.
Version: 0.261.096
Implemented in: 0.261.096

Run against a fresh production V2 build with the existing pytest-playwright
runner. The imported connect_options fixture supports an authenticated Azure
Playwright workspace and the existing local fallback. No live application,
model calls, credentials, isolated component harness, or extra dependencies are
needed. Failed requests are explicit fixtures; other browser errors and all
unexpected requests fail the test.

Personal delegation regressions formerly in test_agent_delegation_v2.py are
covered here through the unified collection and full-page editors. The original
group/admin wrapper coverage remains in that suite.
"""

import copy
import json
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.workspace_authoring import (
    ACTION_ID,
    AGENT_ID,
    CALL_ACTION_ID,
    CHART_ACTION_ID,
    CREATED_ACTION_ID,
    CREATED_AGENT_ID,
    GLOBAL_ACTION_ID,
    GLOBAL_AGENT_ID,
    MCP_ACTION_ID,
    ORIGIN,
    OWNER_ID,
    SECRET_MASK,
    STORED_HEADER,
    STORED_KEY,
    TARGET_ID,
    connect_options,  # noqa: F401
    workspace_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui
LAYOUTS = [
    pytest.param("light", 1440, 900, id="desktop-light"),
    pytest.param("dark", 1440, 900, id="desktop-dark"),
    pytest.param("light", 390, 844, id="mobile-light"),
    pytest.param("dark", 390, 844, id="mobile-dark"),
]


def editor_section(page, label):
    """Use the real section navigation in either supported responsive layout."""
    mobile_sections = page.get_by_role("combobox", name=re.compile("^Jump to section"))
    if page.viewport_size and page.viewport_size["width"] < 1024:
        expect(mobile_sections).to_be_visible()
        mobile_sections.select_option(label=label)
    else:
        page.get_by_role("navigation", name="Editor sections", exact=True).get_by_role(
            "button", name=label, exact=True
        ).click()


def save_resource(ui, resource, *, identifier=None):
    return_to = parse_qs(urlsplit(ui.page.url).query).get("returnTo", [None])[0]
    method = "PATCH" if identifier else "POST"
    path = f"/api/user/{'agents' if resource == 'agent' else 'plugins'}"
    if identifier:
        path += f"/{identifier}"
    with ui.page.expect_response(
        lambda response: response.request.method == method and urlsplit(response.url).path == path
    ) as response:
        ui.page.get_by_role("button", name=f"Save {resource}", exact=True).click()
    result = response.value
    if result.ok:
        destination = "/workspace/agents" if resource == "agent" else "/workspace/actions"
        if resource == "action" and return_to and re.fullmatch(r"/workspace/agents/[^/?#]+", return_to):
            destination = return_to
        expect(ui.page).to_have_url(f"{ORIGIN}/v2{destination}")
    return result


def assert_patch(ui, path, revision, updates, *, clear=(), removed=()):
    write = ui.editor_writes[-1]
    assert (write.method, write.path, write.query, write.body) == (
        "PATCH",
        path,
        {"view": ["editor"]},
        {
            "updates": updates,
            "expected_revision": revision,
            "clear_secret_paths": list(clear),
            "removed_paths": list(removed),
        },
    )


def assert_action_save_blocked(ui):
    """Disabled Save and visible submit-time validation must both prevent writes."""
    count = len(ui.editor_writes)
    save = ui.page.get_by_role("button", name="Save action", exact=True)
    if save.is_enabled():
        save.click()
        expect(ui.page.get_by_role("alert").and_(ui.page.locator('[tabindex="-1"]'))).to_be_visible()
    else:
        expect(save).to_be_disabled()
    assert len(ui.editor_writes) == count


def select_call_target(page, label="Target reviewer"):
    page.get_by_label("Search target agents", exact=True).fill(label)
    target = action_field(page, "Target agent")
    option = target.get_by_role("option").filter(has_text=label)
    expect(option).to_have_count(1)
    target.select_option(option.get_attribute("value"))


def assigned_action(page, name):
    return page.get_by_role("checkbox", name=f"Assign {name}", exact=True)


def collection_item(page, identifier):
    return page.get_by_role("listitem").filter(has_text=identifier)


def action_field(page, label):
    return page.get_by_label(re.compile(rf"^{re.escape(label)}(?:\s*\*)?\s*$"))


def name_field(page, resource):
    if resource in ("action", "actions"):
        return action_field(page, "Action name")
    return page.get_by_label("Display name", exact=True)


def seed_array_credentials(ui):
    ui.agents[AGENT_ID]["other_settings"]["custom_credentials"] = [
        {
            "label": "first", "token": STORED_KEY, "legacy": "remove first",
            "nested": {"retained": False, "obsolete": 9},
        },
        {
            "label": "second", "token": STORED_HEADER, "legacy": "remove second",
            "nested": {"retained": 0, "obsolete": 8},
        },
    ]
    ui.secret_paths[AGENT_ID] = [
        "/other_settings/custom_credentials/0/token",
        "/other_settings/custom_credentials/1/token",
    ]


def configure_agent(page, agent_type, name):
    labels = {
        "local": "Local agent", "aifoundry": "Azure AI Foundry",
        "new_foundry": "New Foundry", "foundry_workflow": "Foundry Workflow",
    }
    page.get_by_label("Display name", exact=True).fill(name)
    page.get_by_label("Description", exact=True).fill(f"Authoring coverage for {agent_type}.")
    page.get_by_role("radio", name=labels[agent_type], exact=True).check()
    editor_section(page, "Model & connection")
    if agent_type == "local":
        page.get_by_label("Model", exact=True).select_option(
            label="Workspace GPT · Workspace model endpoint"
        )
        editor_section(page, "Instructions")
        page.get_by_role("textbox", name="Instructions", exact=True).fill("Review the supplied evidence carefully.")
    else:
        page.get_by_label("Foundry project endpoint", exact=True).fill(
            "https://foundry.example.test/api/projects/review"
        )
        if agent_type == "aifoundry":
            page.get_by_label("Foundry agent ID", exact=True).fill("foundry-reviewer")
            page.get_by_label("Foundry API version", exact=True).fill("v1")
        else:
            page.get_by_label("Responses API version", exact=True).fill("2025-11-15-preview")
            label = "Application ID" if agent_type == "new_foundry" else "Workflow name"
            page.get_by_label(label, exact=True).fill("review-workflow")


def begin_action(page, action_type, name):
    action_field(page, "Action type").select_option(action_type)
    name_field(page, "action").fill(name)
    page.get_by_label("Description", exact=True).fill("A browser-authored workspace action.")
    if action_type == "agent":
        editor_section(page, "Configuration")
        select_call_target(page)
    else:
        editor_section(page, "Configuration")
        action_field(page, "Endpoint").fill("https://service.example.test/api")
        expect(page.get_by_label("Region", exact=True)).to_have_value("")
        page.get_by_label("Region", exact=True).select_option(label="east")
        page.get_by_label("Result limit", exact=True).fill("3")
        page.get_by_label("Result limit", exact=True).fill("0")
        page.get_by_label("Include archived", exact=True).select_option("true")
        page.get_by_label("Include archived", exact=True).select_option("false")


def keep_editing(page):
    dialog = page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("button", name="Keep editing", exact=True)).to_be_focused()
    dialog.get_by_role("button", name="Keep editing", exact=True).click()
    expect(dialog).not_to_be_visible()


def discard_changes(page):
    dialog = page.get_by_role("dialog", name="Discard unsaved changes?", exact=True)
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Discard changes", exact=True).click()
    expect(dialog).not_to_be_visible()


@pytest.mark.parametrize("theme,width,height", LAYOUTS)
@pytest.mark.parametrize("action_type", ["fixture_custom", "agent"])
def test_unified_actions_create_reload_edit_delete(workspace_ui, theme, width, height, action_type):
    """Ordinary and Call-agent actions have exactly the same collection/editor lifecycle."""
    ui, page = workspace_ui, workspace_ui.page
    ui.open(theme=theme, width=width, height=height)
    expect(page.get_by_role("heading", name="Actions", exact=True)).to_be_visible()
    expect(page.get_by_text("Other actions", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="New action", exact=True)).to_be_visible()
    expect(page.get_by_text("Workspace API", exact=True)).to_be_visible()
    expect(page.get_by_text("Call reviewer", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    original_agents = copy.deepcopy(ui.agents)
    original_actions = copy.deepcopy(ui.actions)

    page.get_by_role("button", name="New action", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/actions/new")
    expect(page.get_by_role("dialog")).to_have_count(0)
    name = "<img src=x onerror=alert(1)> Workspace action"
    begin_action(page, action_type, name)
    if action_type == "agent":
        expect(action_field(page, "Endpoint")).to_have_count(0)
        authentication = page.get_by_role("region", name="Authentication", exact=True)
        expect(authentication.get_by_role("combobox")).to_have_count(0)
        expect(authentication.locator('input[type="password"]')).to_have_count(0)
        expect(page.get_by_role("button", name="Test connection", exact=True)).to_have_count(0)
    else:
        expect(page.get_by_label("Region", exact=True).get_by_role(
            "option", selected=True
        )).to_have_text("east")
    ui.assert_no_overflow()
    assert not ui.editor_writes
    assert save_resource(ui, "action").status == 201
    created = copy.deepcopy(ui.actions[CREATED_ACTION_ID])
    assert created["displayName"] == name
    assert re.fullmatch(r"[A-Za-z0-9_-]+", created["name"])
    assert created["type"] == action_type
    assert ui.editor_writes[-1].body["clear_secret_paths"] == []
    assert ui.editor_writes[-1].body["removed_paths"] == []
    assert "expected_revision" not in ui.editor_writes[-1].body
    if action_type == "agent":
        assert created["endpoint"] == "internal://agent"
        assert created["auth"] == {"type": "user"}
        assert created["additionalFields"]["target_agent"] == {
            "id": TARGET_ID, "scope_type": "personal", "scope_id": OWNER_ID,
        }
    else:
        assert created["auth"] == {"type": "NoAuth"}
        assert created["additionalFields"] == {"region": "east", "limit": 0, "enabled": False}
        assert "east|west" not in json.dumps(created)
    assert not any("/test" in request.path or "/discover" in request.path for request in ui.writes)

    page.goto(f"{ORIGIN}/v2/workspace/actions/{CREATED_ACTION_ID}", wait_until="networkidle")
    expect(name_field(page, "action")).to_have_value(name)
    expect(page.locator("img[src='x']")).to_have_count(0)
    revision = ui.revision(CREATED_ACTION_ID)
    name_field(page, "action").fill("Renamed workspace action")
    assert save_resource(ui, "action", identifier=CREATED_ACTION_ID).status == 200
    assert_patch(
        ui, f"/api/user/plugins/{CREATED_ACTION_ID}", revision,
        {"displayName": "Renamed workspace action"},
    )
    assert ui.actions[CREATED_ACTION_ID] == {**created, "displayName": "Renamed workspace action"}
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/actions")
    page.get_by_role("button", name="Delete Renamed workspace action", exact=True).click()
    writes_before_confirmation = len(ui.editor_writes)
    expect(page.get_by_role("button", name="Delete action", exact=True)).to_be_visible()
    assert CREATED_ACTION_ID in ui.actions
    page.get_by_role("button", name="Delete action", exact=True).click()
    expect(page.get_by_text("Renamed workspace action", exact=True)).to_have_count(0)
    assert len(ui.editor_writes) == writes_before_confirmation + 1
    assert ui.editor_writes[-1].method == "DELETE"
    assert ui.editor_writes[-1].path == f"/api/user/plugins/{CREATED_ACTION_ID}"
    assert ui.actions == original_actions
    assert ui.agents == original_agents
    ui.assert_no_secret_storage(name)
    ui.assert_no_overflow()


@pytest.mark.parametrize("agent_type,scope", [
    ("local", "personal"), ("aifoundry", "personal"), ("new_foundry", "personal"),
    ("foundry_workflow", "personal"), ("foundry_workflow", "global"),
])
def test_every_supported_call_target_type_uses_ordinary_editor(workspace_ui, agent_type, scope):
    ui, page = workspace_ui, workspace_ui.page
    identifier = GLOBAL_AGENT_ID if scope == "global" else TARGET_ID
    target = next(item for item in ui.targets if item["id"] == identifier)
    ui.targets = [{**target, "display_name": "Target reviewer", "agent_type": agent_type}]
    ui.agents[identifier].update({"display_name": "Target reviewer", "agent_type": agent_type})
    ui.open("/workspace/actions/new")
    begin_action(page, "agent", f"Delegate {agent_type}")
    target = action_field(page, "Target agent")
    expect(target.get_by_role("option", selected=True)).to_contain_text(agent_type)
    target.focus()
    expect(target).to_be_focused()
    page.keyboard.press("ArrowUp")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    assert save_resource(ui, "action").status == 201
    assert ui.actions[CREATED_ACTION_ID]["additionalFields"]["target_agent"] == {
        "id": identifier, "scope_type": scope, "scope_id": "global" if scope == "global" else OWNER_ID,
    }


def test_action_rename_preserves_credentials_and_nested_unknown_values(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.actions[MCP_ACTION_ID])
    revision = ui.revision(MCP_ACTION_ID)
    ui.open(f"/workspace/actions/{MCP_ACTION_ID}")
    name_field(page, "action").fill("Renamed MCP")
    assert save_resource(ui, "action", identifier=MCP_ACTION_ID).status == 200
    assert_patch(ui, f"/api/user/plugins/{MCP_ACTION_ID}", revision, {"displayName": "Renamed MCP"})
    assert ui.actions[MCP_ACTION_ID] == {**before, "displayName": "Renamed MCP"}
    assert ui.actions[MCP_ACTION_ID]["auth"]["key"] == STORED_KEY
    assert ui.actions[MCP_ACTION_ID]["additionalFields"]["custom_headers"]["X-Workspace"] == STORED_HEADER
    page.goto(f"{ORIGIN}/v2/workspace/actions/{MCP_ACTION_ID}", wait_until="networkidle")
    page.reload(wait_until="networkidle")
    expect(name_field(page, "action")).to_have_value("Renamed MCP")
    assert STORED_KEY not in page.content()
    assert STORED_HEADER not in page.content()
    ui.assert_no_secret_storage()


def test_mixed_bindings_preserve_legacy_unknown_references_and_self_call_protection(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Actions")
    expect(assigned_action(page, "Workspace API")).to_be_checked()
    expect(assigned_action(page, "Call self")).to_be_disabled()
    expect(page.get_by_text("unavailable-action", exact=True)).to_be_visible()
    assigned_action(page, "Call reviewer").check()
    assigned_action(page, "Workspace MCP").check()
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    expected_refs = ["legacy-tool", "unavailable-action", CALL_ACTION_ID, MCP_ACTION_ID]
    assert_patch(ui, f"/api/user/agents/{AGENT_ID}", revision, {"actions_to_load": expected_refs})
    assert ui.agents[AGENT_ID] == {**before, "actions_to_load": expected_refs}
    assert not any(request.path.endswith("/agent-actions") for request in ui.writes)


def test_existing_unavailable_call_binding_can_be_detached(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.agents[AGENT_ID]["actions_to_load"].append(CALL_ACTION_ID)
    ui.targets = []
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Actions")
    checkbox = assigned_action(page, "Call reviewer")
    expect(checkbox).to_be_checked()
    expect(checkbox).to_be_enabled()
    checkbox.uncheck()
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", revision,
        {"actions_to_load": ["legacy-tool", "unavailable-action"]},
    )
    assert ui.agents[AGENT_ID] == {**before, "actions_to_load": ["legacy-tool", "unavailable-action"]}


def test_denied_action_catalog_does_not_block_unrelated_agent_edit(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    ui.reject_next(
        "GET", "/api/user/plugins", status=403,
        error="Actions cannot be listed in this workspace.",
    )
    ui.open(f"/workspace/agents/{AGENT_ID}")
    expect(page.get_by_label("Display name", exact=True)).to_be_enabled()
    editor_section(page, "Actions")
    expect(page.get_by_role("alert").filter(has_text="Actions cannot be listed")).to_be_visible()
    expect(page.get_by_role("checkbox", name=re.compile("^Assign "))).to_have_count(0)
    expect(page.get_by_text("legacy-tool", exact=True)).to_be_visible()
    expect(page.get_by_text("unavailable-action", exact=True)).to_be_visible()
    editor_section(page, "Instructions")
    instructions = page.get_by_role("textbox", name="Instructions", exact=True)
    expect(instructions).to_be_enabled()
    instructions.fill("Edited safely even though actions are unavailable.")
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", revision,
        {"instructions": "Edited safely even though actions are unavailable."},
    )
    assert ui.agents[AGENT_ID] == {
        **before, "instructions": "Edited safely even though actions are unavailable.",
    }


def test_disabled_action_management_still_allows_authorized_bindings_and_capabilities(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.disabled_sections["actions"] = "Action management is disabled."
    ui.options["settings"]["allow_user_plugins"] = False
    ui.can_manage = False
    ui.actions[CALL_ACTION_ID]["additionalFields"]["target_agent"] = {
        "id": GLOBAL_AGENT_ID, "scope_type": "global", "scope_id": "global",
    }
    personal_call_id = "10000000-0000-4000-8000-000000000010"
    ui.actions[personal_call_id] = {
        **copy.deepcopy(ui.actions[CALL_ACTION_ID]),
        "id": personal_call_id, "name": "personal-reviewer",
        "displayName": "Personal reviewer", "is_global": False,
    }
    ui.revisions[personal_call_id] = 1
    ui.actions[CALL_ACTION_ID]["is_global"] = True
    ui.agents[AGENT_ID]["actions_to_load"].append(MCP_ACTION_ID)
    before = copy.deepcopy(ui.agents[AGENT_ID])
    original_actions = copy.deepcopy(ui.actions)
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Actions")
    assert any(request.path == "/api/user/plugins" for request in ui.requests)
    expect(page.get_by_role("button", name="New action", exact=True)).to_have_count(0)
    expect(assigned_action(page, "Workspace API")).to_be_checked()
    expect(assigned_action(page, "Provided API")).to_be_enabled()
    expect(assigned_action(page, "Call reviewer")).to_be_enabled()
    expect(assigned_action(page, "Personal reviewer")).to_be_disabled()
    expect(assigned_action(page, "Call self")).to_be_disabled()
    ui.defer_next("GET", "/api/user/plugins")
    with page.expect_request(
        lambda request: request.method == "GET" and urlsplit(request.url).path == "/api/user/plugins"
    ):
        page.get_by_role("button", name="Refresh actions", exact=True).click()
    expect(assigned_action(page, "Provided API")).to_be_disabled()
    expect(assigned_action(page, "Workspace MCP")).to_be_enabled()
    assigned_action(page, "Workspace MCP").uncheck()
    ui.release_responses()
    expect(assigned_action(page, "Provided API")).to_be_enabled()
    expect(assigned_action(page, "Workspace MCP")).not_to_be_checked()
    assigned_action(page, "Provided API").check()
    assigned_action(page, "Call reviewer").check()
    assigned_action(page, "Workspace charts").check()
    page.get_by_role("checkbox", name=re.compile("^Line charts")).check()
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    references = ["legacy-tool", "unavailable-action", GLOBAL_ACTION_ID, CALL_ACTION_ID, CHART_ACTION_ID]
    capabilities = {
        key: True for key in (
            "line", "bar", "pie", "doughnut", "scatter", "area", "bubble", "radar", "stacked_bar", "stacked_line"
        )
    }
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", revision,
        {"actions_to_load": references, "other_settings": {"action_capabilities": {CHART_ACTION_ID: capabilities}}},
    )
    expected = copy.deepcopy(before)
    expected["actions_to_load"] = references
    expected["other_settings"]["action_capabilities"][CHART_ACTION_ID] = capabilities
    assert ui.agents[AGENT_ID] == expected
    assert ui.actions == original_actions
    assert [(request.method, request.path) for request in ui.editor_writes] == [
        ("PATCH", f"/api/user/agents/{AGENT_ID}"),
    ]


@pytest.mark.parametrize("status", [400, 403, 409, 503])
@pytest.mark.parametrize("resource,identifier", [("action", ACTION_ID), ("agent", AGENT_ID)])
def test_failed_or_conflicting_save_keeps_draft_and_stored_resource(workspace_ui, status, resource, identifier):
    ui, page = workspace_ui, workspace_ui.page
    collection = "actions" if resource == "action" else "agents"
    api_collection = "plugins" if resource == "action" else "agents"
    records = ui.actions if resource == "action" else ui.agents
    before = copy.deepcopy(records[identifier])
    ui.open(f"/workspace/{collection}/{identifier}")
    name_field(page, resource).fill("Unsaved review draft")
    error = {
        400: "Please correct the highlighted display name.",
        403: "You no longer have permission to save this resource.",
        409: "This resource changed in another session. Reload before saving.",
        503: "The workspace is temporarily unavailable. Try again.",
    }[status]
    ui.reject_next(
        "PATCH", f"/api/user/{api_collection}/{identifier}", status=status, error=error,
        **({"field_errors": {"displayName" if resource == "action" else "display_name": error}} if status == 400 else {}),
    )
    assert save_resource(ui, resource, identifier=identifier).status == status
    visible_error = "changed in another session" if status == 409 else error
    alert = page.get_by_role("alert").and_(page.locator('[tabindex="-1"]')).filter(has_text=visible_error)
    expect(alert).to_be_visible()
    expect(alert).to_be_focused()
    expect(name_field(page, resource)).to_have_value("Unsaved review draft")
    expect(page.get_by_role("status").filter(has_text="Unsaved changes")).to_be_visible()
    assert records[identifier] == before
    assert len(ui.editor_writes) == 1
    ui.assert_no_secret_storage("Unsaved review draft")


@pytest.mark.parametrize("collection,identifier", [("actions", GLOBAL_ACTION_ID), ("agents", GLOBAL_AGENT_ID)])
@pytest.mark.parametrize("revision_state", ["opaque", "empty", "missing"])
def test_provided_resources_remain_read_only_on_direct_routes(workspace_ui, collection, identifier, revision_state):
    ui, page = workspace_ui, workspace_ui.page
    if revision_state == "empty":
        ui.empty_revisions.add(identifier)
    elif revision_state == "missing":
        ui.missing_revisions.add(identifier)
    before = copy.deepcopy((ui.actions, ui.agents))
    ui.open(f"/workspace/{collection}/{identifier}?scope=global", theme="dark", width=390, height=844)
    expect(page.get_by_text("Provided - read only", exact=True)).to_be_visible()
    expect(name_field(page, collection)).to_be_disabled()
    expect(page.get_by_role("button", name=re.compile(r"^Save (agent|action)$"))).to_have_count(0)
    assert not ui.editor_writes
    assert (ui.actions, ui.agents) == before
    ui.assert_no_overflow()


@pytest.mark.parametrize("collection,identifier", [("actions", ACTION_ID), ("agents", AGENT_ID)])
def test_denied_or_disabled_deep_links_do_not_offer_an_editor(workspace_ui, collection, identifier):
    ui, page = workspace_ui, workspace_ui.page
    ui.disabled_sections[collection] = "Your administrator has disabled authoring."
    ui.open(f"/workspace/{collection}/{identifier}")
    expect(page.get_by_text(f"{collection.title()} is not available", exact=True)).to_be_visible()
    expect(page.get_by_text("Your administrator has disabled authoring.", exact=True)).to_be_visible()
    assert not any(request.path.startswith(f"/api/user/{'plugins' if collection == 'actions' else 'agents'}") for request in ui.requests)
    assert not ui.editor_writes


def test_unavailable_target_and_failed_target_catalog_are_not_empty_success(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.actions[CALL_ACTION_ID])
    target = before["additionalFields"]["target_agent"]
    target_value = json.dumps(
        [target["scope_type"], target["scope_id"], target["id"]], separators=(",", ":")
    )
    ui.targets = []
    ui.open(f"/workspace/actions/{CALL_ACTION_ID}")
    editor_section(page, "Configuration")
    expect(page.get_by_role("status").filter(has_text="The saved target is unavailable")).to_be_visible()
    assert_action_save_blocked(ui)
    expect(action_field(page, "Target agent")).to_have_value(target_value)
    assert ui.actions[CALL_ACTION_ID] == before
    assert not ui.editor_writes

    ui.reject_next(
        "GET", "/api/plugins/agent-targets", status=403,
        error="Access denied to target agents.",
    )
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("alert").filter(has_text="Access denied")).to_be_visible()
    assert_action_save_blocked(ui)
    expect(action_field(page, "Target agent")).to_have_value(target_value)
    assert ui.actions[CALL_ACTION_ID] == before
    assert not ui.editor_writes


@pytest.mark.parametrize("existing", [False, True])
def test_new_action_roundtrip_retains_agent_draft_without_premature_save(workspace_ui, existing):
    ui, page = workspace_ui, workspace_ui.page
    identifier = AGENT_ID if existing else "new"
    ui.open(f"/workspace/agents/{identifier}")
    page.get_by_label("Display name", exact=True).fill("Retained authoring draft")
    if not existing:
        page.get_by_label("Description", exact=True).fill("An unsaved agent and its new action.")
    editor_section(page, "Instructions")
    instructions = "Keep this unpublished instruction draft through the action editor."
    page.get_by_role("textbox", name="Instructions", exact=True).fill(instructions)
    editor_section(page, "Actions")
    assigned_action(page, "Call reviewer").check()
    page.get_by_role("button", name="New action", exact=True).click()
    expect(page).to_have_url(re.compile(r"/v2/workspace/actions/new\?"))
    assert parse_qs(urlsplit(page.url).query)["returnTo"] == [f"/workspace/agents/{identifier}"]
    assert not ui.editor_writes
    begin_action(page, "agent", "Draft companion action")
    assert save_resource(ui, "action").status == 201
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents/{identifier}")
    expect(page.get_by_label("Display name", exact=True)).to_have_value("Retained authoring draft")
    editor_section(page, "Instructions")
    expect(page.get_by_role("textbox", name="Instructions", exact=True)).to_have_value(instructions)
    editor_section(page, "Actions")
    expect(assigned_action(page, "Call reviewer")).to_be_checked()
    expect(assigned_action(page, "Draft companion action")).to_be_checked()
    assert [(write.method, write.path) for write in ui.editor_writes] == [("POST", "/api/user/plugins")]
    ui.assert_no_secret_storage("Retained authoring draft", instructions)

    assert save_resource(ui, "agent", identifier=AGENT_ID if existing else None).ok
    saved_id = AGENT_ID if existing else CREATED_AGENT_ID
    expected_refs = (
        ["legacy-tool", "unavailable-action", CALL_ACTION_ID, CREATED_ACTION_ID]
        if existing else [CALL_ACTION_ID, CREATED_ACTION_ID]
    )
    assert ui.agents[saved_id]["actions_to_load"] == expected_refs
    assert ui.agents[saved_id]["instructions"] == instructions
    assert ui.agents[saved_id]["display_name"] == "Retained authoring draft"
    assert len(ui.editor_writes) == 2


@pytest.mark.parametrize("action_type", ["fixture_custom", "agent"])
def test_clean_agent_action_return_waits_for_detail_and_uses_hydrated_revision(workspace_ui, action_type):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.agents[AGENT_ID])
    ui.open(f"/workspace/agents/{AGENT_ID}")
    expect(page.get_by_role("status").filter(has_text="No unsaved changes")).to_be_visible()
    editor_section(page, "Actions")
    page.get_by_role("button", name="New action", exact=True).click()
    begin_action(page, action_type, "Clean context companion")
    ui.revisions[AGENT_ID] += 1
    hydrated_revision = ui.revision(AGENT_ID)
    ui.defer_next("GET", f"/api/user/agents/{AGENT_ID}")
    with page.expect_request(
        lambda request: request.method == "GET" and urlsplit(request.url).path == f"/api/user/agents/{AGENT_ID}"
    ):
        assert save_resource(ui, "action").status == 201
    expect(page.get_by_role("status").filter(has_text="Loading agent editor")).to_be_visible()
    assert [(write.method, write.path) for write in ui.editor_writes] == [("POST", "/api/user/plugins")]
    assert ui.agents[AGENT_ID] == before
    assert page.evaluate("""() => {
        const event = new Event('beforeunload', {cancelable: true});
        window.dispatchEvent(event);
        return event.defaultPrevented;
    }""")
    ui.release_responses()
    expect(page.get_by_label("Display name", exact=True)).to_have_value(before["display_name"])
    editor_section(page, "Instructions")
    expect(page.get_by_role("textbox", name="Instructions", exact=True)).to_have_value(before["instructions"])
    editor_section(page, "Actions")
    expect(assigned_action(page, "Clean context companion")).to_be_checked()
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    references = [*before["actions_to_load"], CREATED_ACTION_ID]
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", hydrated_revision,
        {"actions_to_load": references},
    )
    assert ui.agents[AGENT_ID] == {**before, "actions_to_load": references}
    assert len(ui.editor_writes) == 2


def test_cancelled_new_action_returns_unchanged_unsaved_agent(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/agents/new")
    page.get_by_label("Display name", exact=True).fill("Agent draft before cancellation")
    editor_section(page, "Actions")
    page.get_by_role("button", name="New action", exact=True).click()
    begin_action(page, "agent", "Discard this action")
    page.get_by_role("button", name="Cancel", exact=True).click()
    discard_changes(page)
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents/new")
    expect(page.get_by_label("Display name", exact=True)).to_have_value("Agent draft before cancellation")
    expect(assigned_action(page, "Discard this action")).to_have_count(0)
    assert not ui.editor_writes


def test_dirty_cancel_workspace_navigation_back_forward_and_reload(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/actions")
    page.get_by_role("button", name="New action", exact=True).click()
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/actions")
    page.go_back()
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/actions/new")
    begin_action(page, "agent", "Keep my navigation draft")
    page.go_forward()
    keep_editing(page)
    expect(name_field(page, "action")).to_have_value("Keep my navigation draft")
    page.go_back()
    keep_editing(page)
    page.get_by_role("button", name="Cancel", exact=True).click()
    page.get_by_role("dialog").press("Escape")
    expect(page.get_by_role("dialog")).not_to_be_visible()
    expect(name_field(page, "action")).to_have_value("Keep my navigation draft")

    reload_dialogs = []

    def cancel_reload(dialog):
        reload_dialogs.append(dialog.type)
        dialog.dismiss()

    page.once("dialog", cancel_reload)
    with page.expect_event("dialog"):
        page.evaluate("() => window.location.reload()")
    assert reload_dialogs == ["beforeunload"]
    expect(name_field(page, "action")).to_have_value("Keep my navigation draft")
    page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role(
        "link", name="Agents", exact=True
    ).click()
    discard_changes(page)
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents")
    assert not ui.editor_writes


def test_unsafe_action_return_path_stays_inside_workspace(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/actions/new?returnTo=https%3A%2F%2Fexternal.example.test%2Fsteal")
    page.get_by_role("button", name="Cancel", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/actions")
    assert not ui.editor_writes


@pytest.mark.parametrize("agent_type", ["local", "aifoundry", "new_foundry", "foundry_workflow"])
def test_create_reload_edit_each_agent_type_with_applicable_controls(workspace_ui, agent_type):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/agents")
    page.get_by_role("button", name="New agent", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents/new")
    name = f"Native {agent_type} reviewer"
    configure_agent(page, agent_type, name)
    if agent_type == "local":
        expect(page.get_by_label("Foundry project endpoint", exact=True)).to_have_count(0)
    else:
        expect(page.get_by_label("Model", exact=True)).to_have_count(0)
        editor_section(page, "Actions")
        expect(assigned_action(page, "Call reviewer")).to_have_count(0)
        expect(page.get_by_text("Foundry manages this agent’s tools.", exact=False)).to_be_visible()
        expect(page.get_by_role("button", name="Draft instructions", exact=True)).to_have_count(0)
    assert not ui.editor_writes
    assert save_resource(ui, "agent").status == 201
    record = copy.deepcopy(ui.agents[CREATED_AGENT_ID])
    assert record["display_name"] == name
    assert record["agent_type"] == agent_type
    assert record["actions_to_load"] == []
    assert record["max_completion_tokens"] == -1
    if agent_type == "local":
        assert record["model_endpoint_id"] == "workspace-model-endpoint"
        assert record["model_id"] == "workspace-model"
        assert record["model_provider"] == "aoai"
        assert record["azure_openai_gpt_deployment"] == "workspace-gpt"
    else:
        key = "azure_ai_foundry" if agent_type == "aifoundry" else agent_type
        settings = record["other_settings"][key]
        assert settings["endpoint"] == "https://foundry.example.test/api/projects/review"
        identity_key = {
            "aifoundry": "agent_id", "new_foundry": "application_id",
            "foundry_workflow": "workflow_name",
        }[agent_type]
        assert settings[identity_key] == ("foundry-reviewer" if agent_type == "aifoundry" else "review-workflow")

    page.goto(f"{ORIGIN}/v2/workspace/agents/{CREATED_AGENT_ID}", wait_until="networkidle")
    expect(page.get_by_label("Display name", exact=True)).to_have_value(name)
    revision = ui.revision(CREATED_AGENT_ID)
    page.get_by_label("Description", exact=True).fill("Revised without dropping provider settings.")
    assert save_resource(ui, "agent", identifier=CREATED_AGENT_ID).status == 200
    assert_patch(
        ui, f"/api/user/agents/{CREATED_AGENT_ID}", revision,
        {"description": "Revised without dropping provider settings."},
    )
    assert ui.agents[CREATED_AGENT_ID] == {
        **record, "description": "Revised without dropping provider settings.",
    }
    ui.assert_no_overflow()


def test_agent_type_change_requires_explicit_detachment_of_local_actions(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    original = copy.deepcopy(ui.agents[AGENT_ID])
    ui.open(f"/workspace/agents/{AGENT_ID}")
    page.get_by_role("radio", name="Azure AI Foundry", exact=True).check()
    editor_section(page, "Actions")
    expect(page.get_by_text("Workspace API", exact=True)).to_be_visible()
    assert ui.agents[AGENT_ID] == original
    page.get_by_role("button", name="Detach local actions", exact=True).click()
    page.get_by_role("button", name="Keep actions", exact=True).click()
    expect(page.get_by_text("Workspace API", exact=True)).to_be_visible()
    page.get_by_role("button", name="Detach local actions", exact=True).click()
    page.get_by_role("button", name="Confirm detach", exact=True).click()
    editor_section(page, "Identity")
    page.get_by_role("radio", name="Local agent", exact=True).check()
    editor_section(page, "Actions")
    expect(assigned_action(page, "Workspace API")).not_to_be_checked()
    assert not ui.editor_writes
    assert ui.agents[AGENT_ID] == original


def test_agent_knowledge_sources_tags_documents_urls_and_user_context(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Assigned knowledge")
    restrict = page.get_by_role("checkbox", name=re.compile("^Restrict to assigned knowledge"))
    restrict.focus()
    page.keyboard.press("Space")
    expect(restrict).to_be_checked()
    page.get_by_role("checkbox", name=re.compile("^Published handbook")).check()
    expect(page.get_by_text("Active documents (2)", exact=True)).to_be_visible()
    page.get_by_role("checkbox", name=re.compile(r"^Finance\s+\(")).check()
    page.get_by_role("checkbox", name=re.compile(r"^Operations\s+\(")).check()
    expect(page.get_by_text("Active documents (1)", exact=True)).to_be_visible()
    page.get_by_role("checkbox", name=re.compile("^Public finance checklist")).check()
    expect(page.get_by_text("Active documents (2)", exact=True)).to_be_visible()
    user_context = page.get_by_role("checkbox", name=re.compile("^Allow user-added workspace context"))
    user_context.focus()
    page.keyboard.press("Space")
    expect(user_context).to_be_checked()
    page.get_by_role("checkbox", name="Compare", exact=True).uncheck()
    page.get_by_label("Assigned URL", exact=True).fill("https://docs.example.test/review#overview")
    page.get_by_label("URL mode", exact=True).select_option("deep_research")
    page.get_by_role("button", name="Add URL", exact=True).click()
    expect(page.get_by_text("https://docs.example.test/review", exact=True)).to_be_visible()
    assigned_knowledge = {
        "enabled": True,
        "scopes": {"personal": False, "group_ids": [], "public_workspace_ids": ["public-handbook"]},
        "document_ids": ["public-checklist"],
        "tags": ["Finance", "Operations"],
        "web_sources": [{"url": "https://docs.example.test/review", "mode": "deep_research"}],
        "allow_user_workspace_context": True,
        "allowed_user_workspace_actions": ["search", "analyze"],
    }
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", revision,
        {"other_settings": {"assigned_knowledge": assigned_knowledge}},
    )
    assert ui.agents[AGENT_ID] == {
        **before, "other_settings": {**before["other_settings"], "assigned_knowledge": assigned_knowledge},
    }
    ui.assert_no_secret_storage()


@pytest.mark.parametrize("collection,identifier", [("actions", ACTION_ID), ("agents", AGENT_ID)])
def test_direct_resource_permission_denial_never_exposes_configuration(workspace_ui, collection, identifier):
    ui, page = workspace_ui, workspace_ui.page
    ui.denied_resources.add(identifier)
    ui.open(f"/workspace/{collection}/{identifier}")
    expect(page.get_by_role("alert").filter(has_text="You no longer have permission")).to_be_visible()
    expect(name_field(page, collection)).to_have_count(0)
    expect(page.get_by_role("button", name=re.compile(r"^Save (agent|action)$"))).to_have_count(0)
    assert not ui.editor_writes


def test_real_revision_conflict_preserves_concurrent_edit_and_requires_reload(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open(f"/workspace/agents/{AGENT_ID}")
    revision = ui.revision(AGENT_ID)
    page.get_by_label("Display name", exact=True).fill("My conflicting edit")
    ui.agents[AGENT_ID]["description"] = "Concurrent server-side description."
    ui.revisions[AGENT_ID] += 1
    concurrent = copy.deepcopy(ui.agents[AGENT_ID])
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 409
    expect(page.get_by_role("alert").filter(has_text="changed in another session")).to_be_visible()
    expect(page.get_by_label("Display name", exact=True)).to_have_value("My conflicting edit")
    assert_patch(ui, f"/api/user/agents/{AGENT_ID}", revision, {"display_name": "My conflicting edit"})
    assert ui.agents[AGENT_ID] == concurrent
    latest_link = page.get_by_role("link", name="Open latest in a new tab", exact=True)
    expect(latest_link).to_have_attribute("target", "_blank")
    expect(latest_link).to_have_attribute("rel", re.compile(r"\bnoopener\b"))
    with page.expect_popup() as popup:
        latest_link.click()
    latest = popup.value
    expect(latest.get_by_label("Description", exact=True)).to_have_value("Concurrent server-side description.")
    expect(latest.get_by_label("Display name", exact=True)).to_have_value(concurrent["display_name"])
    expect(page.get_by_label("Display name", exact=True)).to_have_value("My conflicting edit")
    assert len(ui.editor_writes) == 1
    ui.assert_no_secret_storage("My conflicting edit", page=latest)
    latest.close()
    page.get_by_role("button", name="Back", exact=True).click()
    discard_changes(page)
    page.goto(f"{ORIGIN}/v2/workspace/agents/{AGENT_ID}", wait_until="networkidle")
    expect(page.get_by_label("Description", exact=True)).to_have_value("Concurrent server-side description.")
    refreshed_revision = ui.revision(AGENT_ID)
    page.get_by_label("Display name", exact=True).fill("My explicit post-reload edit")
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", refreshed_revision,
        {"display_name": "My explicit post-reload edit"},
    )
    assert ui.agents[AGENT_ID] == {**concurrent, "display_name": "My explicit post-reload edit"}


def test_capability_change_preserves_legacy_key_and_unrelated_capabilities(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.agents[AGENT_ID]["actions_to_load"].append("legacy-chart")
    ui.agents[AGENT_ID]["other_settings"]["action_capabilities"]["legacy-chart"] = {
        "line": False, "bar": True, "custom": {"retained": 0},
    }
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Actions")
    expect(assigned_action(page, "Workspace charts")).to_be_checked()
    line = page.get_by_role("checkbox", name=re.compile("^Line charts"))
    expect(line).not_to_be_checked()
    line.check()
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    updates = {
        key: True for key in (
            "line", "pie", "doughnut", "scatter", "area", "bubble", "radar", "stacked_bar", "stacked_line"
        )
    }
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", revision,
        {"other_settings": {"action_capabilities": {"legacy-chart": updates}}},
    )
    expected = copy.deepcopy(before)
    expected["other_settings"]["action_capabilities"]["legacy-chart"].update(updates)
    assert ui.agents[AGENT_ID] == expected
    assert CHART_ACTION_ID not in ui.agents[AGENT_ID]["other_settings"]["action_capabilities"]


def test_agent_advanced_json_validation_nested_changes_false_zero_and_default_tokens(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.agents[AGENT_ID]["max_completion_tokens"] = 64
    ui.agents[AGENT_ID]["other_settings"]["custom_policy"].update({"enabled": True, "limit": 7})
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Advanced")
    settings_input = page.get_by_label("Additional settings JSON", exact=True)
    settings_input.fill('{"custom_policy":')
    expect(settings_input).to_have_attribute("aria-invalid", "true")
    expect(page.get_by_role("button", name="Save agent", exact=True)).to_be_disabled()
    expect(page.get_by_role("alert").filter(has_text="Fix the JSON")).to_be_visible()
    assert not ui.editor_writes
    settings_input.fill("[]")
    expect(page.get_by_role("alert").filter(has_text="JSON object")).to_be_visible()
    page.get_by_role("button", name="Reset JSON text to current settings", exact=True).click()
    assert json.loads(settings_input.input_value()) == before["other_settings"]
    edited_settings = copy.deepcopy(before["other_settings"])
    edited_settings["custom_policy"].update({"enabled": False, "limit": 0, "items": []})
    settings_input.fill(json.dumps(edited_settings))
    page.get_by_label("Completion token limit", exact=True).fill("0")
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", revision,
        {"max_completion_tokens": 0, "other_settings": {"custom_policy": {"enabled": False, "limit": 0, "items": []}}},
    )
    assert ui.agents[AGENT_ID] == {
        **before, "other_settings": edited_settings, "max_completion_tokens": 0,
    }
    page.goto(f"{ORIGIN}/v2/workspace/agents/{AGENT_ID}", wait_until="networkidle")
    editor_section(page, "Advanced")
    expect(page.get_by_label("Completion token limit", exact=True)).to_have_value("0")
    revision = ui.revision(AGENT_ID)
    page.get_by_label("Completion token limit", exact=True).fill("-1")
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(ui, f"/api/user/agents/{AGENT_ID}", revision, {"max_completion_tokens": -1})


def test_agent_credentials_have_distinct_keep_replace_clear_intent(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.agents[AGENT_ID]["azure_openai_gpt_key"] = STORED_KEY
    ui.secret_paths[AGENT_ID] = ["/azure_openai_gpt_key"]
    original = copy.deepcopy(ui.agents[AGENT_ID])
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Model & connection")
    page.get_by_text("Custom / legacy connection and APIM", exact=True).click()
    intent = page.get_by_label("Azure OpenAI API key", exact=True)
    expect(intent).to_have_value("keep")
    revision = ui.revision(AGENT_ID)
    editor_section(page, "Identity")
    page.get_by_label("Display name", exact=True).fill("Credential-preserving rename")
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(ui, f"/api/user/agents/{AGENT_ID}", revision, {"display_name": "Credential-preserving rename"})
    assert ui.agents[AGENT_ID]["azure_openai_gpt_key"] == STORED_KEY

    page.goto(f"{ORIGIN}/v2/workspace/agents/{AGENT_ID}", wait_until="networkidle")
    editor_section(page, "Model & connection")
    page.get_by_text("Custom / legacy connection and APIM", exact=True).click()
    page.get_by_label("Azure OpenAI API key", exact=True).select_option("replace")
    replacement = "fixture-only-replacement-credential"
    page.get_by_label("Replacement azure openai api key", exact=True).fill(replacement)
    ui.assert_no_secret_storage(replacement)
    revision = ui.revision(AGENT_ID)
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(ui, f"/api/user/agents/{AGENT_ID}", revision, {"azure_openai_gpt_key": replacement})
    assert ui.agents[AGENT_ID]["azure_openai_gpt_key"] == replacement
    assert all(replacement not in json.dumps(payload) for _, payload in ui.responses)

    page.goto(f"{ORIGIN}/v2/workspace/agents/{AGENT_ID}", wait_until="networkidle")
    editor_section(page, "Model & connection")
    page.get_by_text("Custom / legacy connection and APIM", exact=True).click()
    page.get_by_label("Azure OpenAI API key", exact=True).select_option("clear")
    expect(page.get_by_role("status").filter(has_text="will be cleared")).to_be_visible()
    revision = ui.revision(AGENT_ID)
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(ui, f"/api/user/agents/{AGENT_ID}", revision, {}, clear=["/azure_openai_gpt_key"])
    expected = {**original, "display_name": "Credential-preserving rename"}
    del expected["azure_openai_gpt_key"]
    assert ui.agents[AGENT_ID] == expected


def test_array_replacement_keeps_secrets_by_position_and_removes_omitted_fields(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    seed_array_credentials(ui)
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Advanced")
    field = page.get_by_label("Additional settings JSON", exact=True)
    settings = json.loads(field.input_value())
    safe_settings = copy.deepcopy(settings)
    replacement = [
        {"label": "second", "token": SECRET_MASK, "nested": {"retained": 0}},
        {"label": "first", "token": SECRET_MASK, "nested": {"retained": False}},
    ]
    settings["custom_credentials"] = replacement
    field.fill(json.dumps(settings))
    expect(page.get_by_role("button", name="Save agent", exact=True)).to_be_disabled()
    expect(field).to_have_attribute("aria-invalid", "true")
    expect(page.get_by_role("status").filter(has_text="Review stored array credentials before saving.")).to_be_visible()
    assert not ui.editor_writes
    assert ui.agents[AGENT_ID] == before
    assert json.loads(field.input_value()) == settings
    page.get_by_role("button", name="Reset JSON text to current settings", exact=True).click()
    assert json.loads(field.input_value()) == safe_settings
    expect(field).to_have_attribute("aria-invalid", "false")
    assert not ui.editor_writes
    # Re-associating entries is explicit only after every affected credential is replaced.
    replacement[0]["token"] = "replacement-second-array-credential"
    replacement[1]["token"] = "replacement-first-array-credential"
    field.fill(json.dumps(settings))
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", revision,
        {"other_settings": {"custom_credentials": replacement}},
    )
    expected = copy.deepcopy(before)
    expected["other_settings"]["custom_credentials"] = replacement
    assert ui.agents[AGENT_ID] == expected
    page.goto(f"{ORIGIN}/v2/workspace/agents/{AGENT_ID}", wait_until="networkidle")
    editor_section(page, "Advanced")
    assert json.loads(field.input_value())["custom_credentials"] == [
        {**entry, "token": SECRET_MASK} for entry in replacement
    ]
    ui.assert_no_secret_storage()


@pytest.mark.parametrize("clear_mode", ["empty", "null", "omitted", "entry-removed", "control"])
def test_array_credentials_require_explicit_clear_pointers(workspace_ui, clear_mode):
    ui, page = workspace_ui, workspace_ui.page
    seed_array_credentials(ui)
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    clear_path = "/other_settings/custom_credentials/1/token"
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Advanced")
    field = page.get_by_label("Additional settings JSON", exact=True)
    settings = json.loads(field.input_value())
    replacement = settings["custom_credentials"]
    if clear_mode == "entry-removed":
        replacement.pop()
    elif clear_mode == "omitted":
        del replacement[1]["token"]
    else:
        replacement[1]["token"] = None if clear_mode == "null" else ""
    if clear_mode == "control":
        page.get_by_text("Stored credentials and custom secret fields", exact=True).click()
        intent = page.get_by_label(clear_path, exact=True)
        expect(intent).to_have_value("keep")
        intent.select_option("clear")
    else:
        field.fill(json.dumps(settings))
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(
        ui, f"/api/user/agents/{AGENT_ID}", revision,
        {"other_settings": {"custom_credentials": replacement}},
        clear=[clear_path],
    )
    expected = copy.deepcopy(before)
    if clear_mode == "entry-removed":
        expected["other_settings"]["custom_credentials"].pop()
    else:
        del expected["other_settings"]["custom_credentials"][1]["token"]
    assert ui.agents[AGENT_ID] == expected
    assert ui.secret_paths[AGENT_ID] == ["/other_settings/custom_credentials/0/token"]
    assert SECRET_MASK not in json.dumps(ui.agents[AGENT_ID])


def test_new_array_mask_is_rejected_without_writing_or_dropping_the_draft(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    seed_array_credentials(ui)
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Advanced")
    field = page.get_by_label("Additional settings JSON", exact=True)
    settings = json.loads(field.input_value())
    settings["custom_credentials"].append({"label": "unowned position", "token": SECRET_MASK})
    field.fill(json.dumps(settings))
    expect(page.get_by_role("button", name="Save agent", exact=True)).to_be_disabled()
    expect(field).to_have_attribute("aria-invalid", "true")
    expect(page.get_by_role("alert").filter(has_text="credentials").first).to_be_visible()
    assert json.loads(field.input_value()) == settings
    assert ui.agents[AGENT_ID] == before
    assert ui.revision(AGENT_ID) == revision
    assert len(ui.editor_writes) == 0


def test_instruction_references_and_generation_never_overwrite_newer_draft(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.agents[AGENT_ID]["other_settings"]["assigned_knowledge"] = {
        "enabled": True, "scopes": {"personal": True}, "document_ids": ["personal-brief"],
    }
    before = copy.deepcopy(ui.agents[AGENT_ID])
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(page, "Instructions")
    instructions = page.get_by_role("textbox", name="Instructions", exact=True)
    instructions.fill("Use #action:Workspace")
    suggestions = page.get_by_role("listbox", name="Instruction references", exact=True)
    expect(suggestions).to_be_visible()
    instructions.press("Enter")
    expect(instructions).to_have_value('Use #action:"Workspace API" ')
    instructions.press("End")
    instructions.press_sequentially("#knowledge:doc:")
    expect(suggestions.get_by_role("option")).to_have_count(1)
    instructions.press("Tab")
    expected_instructions = 'Use #action:"Workspace API" #knowledge:doc:"Private review brief" '
    expect(instructions).to_have_value(expected_instructions)
    expect(instructions).to_be_focused()
    page.get_by_label("Instruction brief", exact=True).fill("Write a careful evidence review.")
    ui.defer_next("POST", "/api/agents/draft-instructions")
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == "/api/agents/draft-instructions"
    ):
        page.get_by_role("button", name="Draft instructions", exact=True).click()
    assert not ui.editor_writes
    request = ui.writes[-1]
    assert request.body == {
        "agent_scope": "user",
        "display_name": before["display_name"],
        "description": before["description"],
        "brief": "Write a careful evidence review.",
        "existing_instructions": expected_instructions,
        "selected_actions": [
            {
                "id": ACTION_ID, "name": "legacy-tool", "display_name": "Workspace API",
                "description": ui.actions[ACTION_ID]["description"], "type": "openapi",
                "is_global": False, "capabilities": [],
            },
            {
                "id": "unavailable-action", "name": "unavailable-action",
                "display_name": "unavailable-action", "type": "unavailable",
                "description": "Unresolved saved reference", "capabilities": [],
            },
        ],
        "assigned_knowledge": {
            "enabled": True,
            "sources": [{"scope": "personal", "id": "personal", "name": "Personal workspace"}],
            "documents": [{**ui.knowledge_catalog["documents"][0], "is_explicit": True}],
            "tags": [], "web_sources": [],
        },
    }
    instructions.fill("These are newer user instructions.")
    ui.release_responses()
    proposal = page.get_by_label("Generated instructions — not yet applied", exact=True)
    expect(proposal).to_have_value(ui.extra_posts["/api/agents/draft-instructions"]["instructions"])
    expect(instructions).to_have_value("These are newer user instructions.")
    expect(page.get_by_role("status").filter(has_text="They have not been overwritten.")).to_be_visible()
    page.get_by_role("button", name="Use generated instructions", exact=True).click()
    expect(instructions).to_have_value("These are newer user instructions.")
    page.get_by_role("button", name="Replace edited instructions", exact=True).click()
    generated = ui.extra_posts["/api/agents/draft-instructions"]["instructions"]
    expect(instructions).to_have_value(generated)
    assert not ui.editor_writes
    assert ui.agents[AGENT_ID] == before
    ui.assert_no_secret_storage(generated, "Write a careful evidence review.")
    assert save_resource(ui, "agent", identifier=AGENT_ID).status == 200
    assert_patch(ui, f"/api/user/agents/{AGENT_ID}", revision, {"instructions": generated})


def test_templates_preview_confirm_apply_and_submit_without_saving_agent(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/agents/new")
    page.get_by_label("Display name", exact=True).fill("Keep my existing draft")
    editor_section(page, "Examples & templates")
    page.get_by_text("Preview template", exact=True).click()
    expect(page.get_by_text(ui.templates[0]["instructions"], exact=True)).to_be_visible()
    page.get_by_role("button", name="Use template", exact=True).click()
    page.get_by_role("button", name="Keep current draft", exact=True).click()
    expect(page.get_by_label("Display name", exact=True)).to_have_value("Keep my existing draft")
    page.get_by_role("button", name="Use template", exact=True).click()
    page.get_by_role("button", name="Replace draft with template", exact=True).click()
    expect(page.get_by_label("Display name", exact=True)).to_have_value("Approved review example")
    assert not ui.editor_writes
    editor_section(page, "Actions")
    expect(page.get_by_text("missing-template-tool", exact=True)).to_be_visible()
    editor_section(page, "Advanced")
    template_settings = json.loads(page.get_by_label("Additional settings JSON", exact=True).input_value())
    assert template_settings == {"custom_policy": {"enabled": False, "limit": 0}, "private": {}}
    editor_section(page, "Examples & templates")
    with page.expect_response(
        lambda response: response.request.method == "POST" and urlsplit(response.url).path == "/api/agent-templates"
    ):
        page.get_by_role("button", name="Submit personal template", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Personal template submitted for review.")).to_be_visible()
    assert ui.writes[-1].body == {"template": {
        "title": "Approved review example", "display_name": "Approved review example",
        "description": ui.templates[0]["description"], "helper_text": ui.templates[0]["description"],
        "instructions": ui.templates[0]["instructions"],
        "additional_settings": json.dumps(template_settings, separators=(",", ":")),
        "actions_to_load": ["missing-template-tool"], "tags": ["review"], "source_scope": "personal",
    }}
    assert not ui.editor_writes
    editor_section(page, "Actions")
    page.get_by_role("button", name="Remove action reference missing-template-tool", exact=True).click()
    assert save_resource(ui, "agent").status == 201
    assert ui.agents[CREATED_AGENT_ID]["actions_to_load"] == []
    assert SECRET_MASK not in json.dumps(ui.agents[CREATED_AGENT_ID])
    assert "api_key" not in json.dumps(ui.agents[CREATED_AGENT_ID])


def test_agent_filters_and_browsing_view_survive_cancelled_edit(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/agents", theme="dark", width=390, height=844)
    search = page.get_by_placeholder("Search agents by name, description or type", exact=True)
    search.fill("reviewer")
    page.get_by_label("Filter agent scope", exact=True).select_option("personal")
    page.get_by_label("Filter agent type", exact=True).select_option("local")
    page.get_by_role("button", name="Card view", exact=True).click()
    collection_item(page, AGENT_ID).get_by_role("button", name="Edit", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents/{AGENT_ID}")
    page.get_by_label("Description", exact=True).fill("Discard this collection-navigation draft.")
    page.get_by_role("button", name="Cancel", exact=True).click()
    keep_editing(page)
    page.get_by_role("button", name="Cancel", exact=True).click()
    discard_changes(page)
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents")
    expect(search).to_have_value("reviewer")
    expect(page.get_by_label("Filter agent scope", exact=True)).to_have_value("personal")
    expect(page.get_by_label("Filter agent type", exact=True)).to_have_value("local")
    expect(page.get_by_role("button", name="Card view", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(collection_item(page, GLOBAL_AGENT_ID)).to_have_count(0)
    assert not ui.editor_writes
    ui.assert_no_overflow()


def test_action_filters_cards_and_scope_identity_survive_cancelled_edit(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.actions[GLOBAL_ACTION_ID]["displayName"] = ui.actions[ACTION_ID]["displayName"]
    ui.open("/workspace/actions", theme="dark", width=390, height=844)
    provided = collection_item(page, GLOBAL_ACTION_ID)
    expect(provided.get_by_role("link", name="Edit Workspace API", exact=True)).to_have_count(0)
    expect(provided.get_by_role("button", name="Delete Workspace API", exact=True)).to_have_count(0)
    expect(provided.get_by_role("link", name="View Workspace API", exact=True)).to_have_attribute(
        "href", f"/v2/workspace/actions/{GLOBAL_ACTION_ID}?scope=global"
    )
    search = page.get_by_placeholder("Search actions", exact=True)
    search.fill("workspace")
    page.get_by_label("Action type filter", exact=True).select_option("openapi")
    page.get_by_label("Action scope filter", exact=True).select_option("personal")
    page.get_by_role("button", name="Card view", exact=True).click()
    expect(provided).to_have_count(0)
    ui.assert_no_overflow()
    collection_item(page, ACTION_ID).get_by_role("link", name="Edit Workspace API", exact=True).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/actions/{ACTION_ID}")
    name_field(page, "action").fill("Discard this filtered action draft")
    ui.assert_no_secret_storage("Discard this filtered action draft")
    page.get_by_role("button", name="Cancel", exact=True).click()
    discard_changes(page)
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/actions")
    expect(search).to_have_value("workspace")
    expect(page.get_by_label("Action type filter", exact=True)).to_have_value("openapi")
    expect(page.get_by_label("Action scope filter", exact=True)).to_have_value("personal")
    expect(page.get_by_role("button", name="Card view", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(collection_item(page, ACTION_ID)).to_contain_text("Workspace API")
    assert not ui.editor_writes
    ui.assert_no_overflow()


def test_same_named_agents_keep_scope_identity_and_read_only_commands(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.agents[GLOBAL_AGENT_ID]["display_name"] = ui.agents[AGENT_ID]["display_name"]
    ui.open("/workspace/agents")
    personal = collection_item(page, AGENT_ID)
    provided = collection_item(page, GLOBAL_AGENT_ID)
    expect(personal.get_by_role("button", name="Edit", exact=True)).to_be_visible()
    expect(provided.get_by_role("button", name="Edit", exact=True)).to_have_count(0)
    expect(provided.get_by_role("button", name="View details", exact=True)).to_be_visible()
    expect(provided.get_by_role("button", name="Delete Workspace reviewer", exact=True)).to_have_count(0)
    expect(provided.get_by_text("Provided · read only", exact=True)).to_be_visible()
    expect(personal.get_by_role("link", name="Use in chat", exact=True)).to_have_attribute(
        "href", f"/v2/chat?agent_id={AGENT_ID}&agent_scope=personal&new=1"
    )
    expect(provided.get_by_role("link", name="Use in chat", exact=True)).to_have_attribute(
        "href", f"/v2/chat?agent_id={GLOBAL_AGENT_ID}&agent_scope=global&new=1"
    )
    provided.get_by_role("button", name="View details", exact=True).click()
    expect(page.get_by_label("Display name", exact=True)).to_be_disabled()
    assert not ui.editor_writes


def test_agent_deletion_requires_confirmation_without_rewriting_call_actions(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.actions)
    ui.open("/workspace/agents")
    item = collection_item(page, AGENT_ID)
    item.get_by_role("button", name="Delete Workspace reviewer", exact=True).click()
    assert not ui.editor_writes
    expect(item.get_by_role("button", name="Delete agent", exact=True)).to_be_visible()
    item.get_by_role("button", name="Delete agent", exact=True).click()
    expect(collection_item(page, AGENT_ID)).to_have_count(0)
    assert [(request.method, request.path, request.query, request.body) for request in ui.editor_writes] == [
        ("DELETE", f"/api/user/agents/{AGENT_ID}", {"view": ["editor"]}, None),
    ]
    assert ui.actions == before


def test_failed_agent_catalog_is_not_reported_as_empty_and_can_be_retried(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.reject_next("GET", "/api/user/agents", error="The agent catalogue is temporarily unavailable.")
    ui.open("/workspace/agents")
    expect(page.get_by_role("alert").filter(has_text="catalogue is temporarily unavailable")).to_be_visible()
    expect(page.get_by_text("No agents yet", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Refresh", exact=True).click()
    expect(collection_item(page, AGENT_ID)).to_be_visible()
    expect(page.get_by_role("alert")).to_have_count(0)
    assert not ui.editor_writes


@pytest.mark.parametrize("identifier,scope", [(AGENT_ID, "personal"), (GLOBAL_AGENT_ID, "global")])
def test_use_in_chat_starts_fresh_with_exact_scoped_agent_and_no_model_override(workspace_ui, identifier, scope):
    ui, page = workspace_ui, workspace_ui.page
    before_messages = copy.deepcopy(ui.messages["existing-workspace-chat"])
    ui.agents[GLOBAL_AGENT_ID]["display_name"] = ui.agents[AGENT_ID]["display_name"]
    ui.open("/chat?conversationId=existing-workspace-chat")
    expect(page.get_by_text("An earlier conversation.", exact=True)).to_be_visible()
    page.get_by_role("link", name="My Workspace", exact=True).click()
    page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role(
        "link", name="Agents", exact=True
    ).click()
    collection_item(page, identifier).get_by_role("link", name="Use in chat", exact=True).click()
    expect(page.get_by_text("An earlier conversation.", exact=True)).to_have_count(0)
    expect(page.locator("#composer-input")).to_be_enabled()
    assert "existing-workspace-chat" not in page.url
    page.locator("#composer-input").fill("Review this evidence with the selected workspace agent.")
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == "/api/chat/stream"
    ) as stream_request:
        page.get_by_role("button", name="Send message", exact=True).click()
    body = stream_request.value.post_data_json
    assert body["agent_info"] == {
        "id": identifier, "name": ui.agents[identifier]["name"],
        "display_name": "Workspace reviewer", "is_global": scope == "global", "is_group": False,
        "group_id": None, "group_name": None,
    }
    assert not {"model_deployment", "model_id", "model_endpoint_id", "model_provider"} & set(body)
    assert body["conversation_id"] != "existing-workspace-chat"
    assert ui.messages["existing-workspace-chat"] == before_messages
    assert len([request for request in ui.writes if request.path == "/api/create_conversation"]) == 1
    expect(page.get_by_text("Workspace review response.", exact=True)).to_be_visible()
    assert not ui.editor_writes


def test_use_in_chat_refreshes_authorization_instead_of_using_stale_catalog(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/agents")
    initial_bootstraps = len([request for request in ui.requests if request.path == "/api/v2/bootstrap"])
    del ui.agents[AGENT_ID]
    collection_item(page, AGENT_ID).get_by_role("link", name="Use in chat", exact=True).click()
    expect(page.get_by_text("That agent is no longer available in this workspace.", exact=True)).to_be_visible()
    assert len([request for request in ui.requests if request.path == "/api/v2/bootstrap"]) > initial_bootstraps
    assert not any(request.path in ("/api/create_conversation", "/api/chat/stream") for request in ui.writes)


def test_failed_agent_authorization_refresh_retains_the_existing_conversation(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    original_messages = copy.deepcopy(ui.messages["existing-workspace-chat"])
    ui.open("/chat?conversationId=existing-workspace-chat")
    expect(page.get_by_text("An earlier conversation.", exact=True)).to_be_visible()
    page.get_by_role("link", name="My Workspace", exact=True).click()
    page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role(
        "link", name="Agents", exact=True
    ).click()
    expect(collection_item(page, AGENT_ID)).to_be_visible()
    ui.reject_next("GET", "/api/v2/bootstrap", error="The authorized catalogue could not be refreshed.")
    collection_item(page, AGENT_ID).get_by_role("link", name="Use in chat", exact=True).click()
    expect(page.get_by_text("Could not refresh available agents. Try again.", exact=True)).to_be_visible()
    expect(page.get_by_text("An earlier conversation.", exact=True)).to_be_visible()
    expect(page).to_have_url(f"{ORIGIN}/v2/chat?conversationId=existing-workspace-chat")
    assert ui.messages["existing-workspace-chat"] == original_messages
    assert not any(request.path in ("/api/create_conversation", "/api/chat/stream") for request in ui.writes)
    assert not ui.editor_writes


@pytest.mark.parametrize("source_mode", ["file", "manual"])
def test_openapi_import_authentication_and_explicit_connection_test(workspace_ui, source_mode):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/actions/new")
    action_field(page, "Action type").select_option("openapi")
    name_field(page, "action").fill("Imported review connector")
    page.get_by_label("Description", exact=True).fill("Access approved review status.")
    editor_section(page, "Configuration")
    source = json.dumps(ui.openapi_import_spec)
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == "/api/openapi/upload"
    ) as upload:
        if source_mode == "file":
            page.get_by_label("OpenAPI specification file", exact=True).set_input_files({
                "name": "review.openapi.json", "mimeType": "application/json", "buffer": source.encode(),
            })
        else:
            page.get_by_role("combobox", name="Specification source", exact=True).select_option("manual")
            page.get_by_role("textbox", name="Specification source", exact=True).fill(source)
            assert_action_save_blocked(ui)
            expect(page.get_by_role("textbox", name="Specification source", exact=True)).to_have_value(source)
            page.get_by_role("button", name="Process specification", exact=True).click()
    assert source in upload.value.post_data
    expect(page.get_by_role("heading", name="Imported review API", exact=True)).to_be_visible()
    expect(action_field(page, "API base URL")).to_have_value("https://review-api.example.test/v1")
    expect(page.get_by_text("1 matching operations.", exact=False)).to_be_visible()
    assert not ui.editor_writes
    assert not any("/test-" in request.path for request in ui.writes)
    editor_section(page, "Authentication")
    page.get_by_label("Authentication method", exact=True).select_option("api_key")
    page.get_by_label("API key location", exact=True).select_option("header")
    action_field(page, "Header name").fill("X-Review-Key")
    new_key = "fixture-only-new-api-credential"
    page.get_by_label("API key", exact=True).fill(new_key)
    ui.assert_no_secret_storage(new_key, source)
    editor_section(page, "Configuration")
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == "/api/plugins/test-openapi-connection"
    ) as connection:
        page.get_by_role("button", name="Test OpenAPI connection", exact=True).click()
    body = connection.value.post_data_json
    assert body["action_scope"] == "personal"
    assert "plugin_context" not in body
    assert body["auth"] == {"type": "key", "key": new_key}
    assert body["additionalFields"]["openapi_spec_content"] == ui.openapi_import_spec
    assert body["additionalFields"]["auth_method"] == "api_key"
    assert body["additionalFields"]["api_key_name"] == "X-Review-Key"
    assert body["additionalFields"]["api_key_location"] == "header"
    assert body["clear_secret_paths"] == []
    expect(page.get_by_role("status").filter(has_text="Fixture OpenAPI connection succeeded.")).to_be_visible()
    assert not ui.editor_writes
    assert save_resource(ui, "action").status == 201
    record = ui.actions[CREATED_ACTION_ID]
    assert record["type"] == "openapi"
    assert record["additionalFields"]["openapi_spec_content"] == ui.openapi_import_spec
    assert record["auth"] == {"type": "key", "key": new_key}
    assert "_openApiSourceDraft" not in record
    assert len([request for request in ui.writes if "/test-" in request.path]) == 1


def test_openapi_remote_specs_require_download_then_file_import(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/actions/new")
    action_field(page, "Action type").select_option("openapi")
    editor_section(page, "Configuration")
    source = page.get_by_role("combobox", name="Specification source", exact=True)
    assert set(source.get_by_role("option").evaluate_all(
        "options => options.map(option => option.value)"
    )) == {"file", "manual"}
    expect(page.get_by_label("OpenAPI specification URL", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Import specification URL", exact=True)).to_have_count(0)
    expect(page.get_by_text(re.compile(r"download.*(?:import|upload)", re.I))).to_be_visible()
    assert not ui.editor_writes
    assert not any(request.path == "/api/openapi/upload" for request in ui.writes)


def test_existing_openapi_connection_uses_owned_stored_credentials(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.actions[ACTION_ID])
    ui.open(f"/workspace/actions/{ACTION_ID}")
    editor_section(page, "Configuration")
    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == "/api/plugins/test-openapi-connection"
    ) as connection:
        page.get_by_role("button", name="Test OpenAPI connection", exact=True).click()
    assert connection.value.post_data_json == {
        "name": before["name"], "displayName": before["displayName"], "type": "openapi",
        "description": before["description"], "endpoint": before["endpoint"],
        "auth": {"type": "key", "key": "Stored_In_KeyVault"},
        "additionalFields": before["additionalFields"], "metadata": before["metadata"],
        "action_scope": "personal",
        "plugin_context": {"scope": "personal", "id": ACTION_ID, "name": before["name"]},
        "clear_secret_paths": [],
    }
    expect(page.get_by_role("status").filter(has_text="Fixture OpenAPI connection succeeded.")).to_be_visible()
    assert ui.actions[ACTION_ID] == before
    assert not ui.editor_writes
    assert STORED_KEY not in connection.value.post_data
    assert SECRET_MASK not in connection.value.post_data


def test_failed_openapi_import_retains_processed_specification_and_pending_source(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.actions[ACTION_ID])
    ui.open(f"/workspace/actions/{ACTION_ID}")
    editor_section(page, "Configuration")
    page.get_by_role("combobox", name="Specification source", exact=True).select_option("manual")
    source = page.get_by_role("textbox", name="Specification source", exact=True)
    source.fill('{"openapi": "unfinished')
    ui.reject_next("POST", "/api/openapi/upload", status=400, error="The specification is not valid JSON.")
    page.get_by_role("button", name="Process specification", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="The specification is not valid JSON.")).to_be_visible()
    expect(source).to_have_value('{"openapi": "unfinished')
    assert_action_save_blocked(ui)
    expect(source).to_have_value('{"openapi": "unfinished')
    expect(action_field(page, "API base URL")).to_have_value(before["endpoint"])
    expect(page.get_by_role("region", name="Authentication", exact=True).get_by_label(
        "API key", exact=True
    )).to_have_attribute("placeholder", re.compile("Stored securely"))
    expect(page.get_by_test_id("openapi-configuration").get_by_role(
        "heading", name="Workspace API", exact=True
    )).to_be_visible()
    page.get_by_role("button", name="Discard unprocessed source changes", exact=True).click()
    assert json.loads(source.input_value()) == before["additionalFields"]["openapi_spec_content"]
    assert ui.actions[ACTION_ID] == before
    assert not ui.editor_writes


def test_mcp_discovery_failure_retry_preserves_credentials_and_unavailable_tools(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    legacy_tool = {
        "original_name": "legacy-tool", "function_name": "legacy-tool",
        "description": "Previously allowed tool.",
        "input_schema": {}, "output_schema": {}, "annotations": {},
    }
    ui.actions[MCP_ACTION_ID]["additionalFields"].update({
        "allowed_tool_names": ["legacy-tool"], "mcp_tools": [legacy_tool],
    })
    before = copy.deepcopy(ui.actions[MCP_ACTION_ID])
    revision = ui.revision(MCP_ACTION_ID)
    ui.open(f"/workspace/actions/{MCP_ACTION_ID}")
    editor_section(page, "Configuration")
    expect(action_field(page, "Transport").get_by_role("option", name=re.compile("Stdio"))).to_have_count(0)
    ui.reject_next("POST", "/api/plugins/mcp/discover", error="MCP discovery is temporarily unavailable.")
    page.get_by_role("button", name="Discover MCP tools", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="MCP discovery is temporarily unavailable.")).to_be_visible()
    expect(page.get_by_label("Allowed tool names", exact=True)).to_have_value("legacy-tool")
    assert ui.actions[MCP_ACTION_ID] == before
    assert not ui.editor_writes

    with page.expect_request(
        lambda request: request.method == "POST" and urlsplit(request.url).path == "/api/plugins/mcp/discover"
    ) as discovery:
        page.get_by_role("button", name="Discover MCP tools", exact=True).click()
    body = discovery.value.post_data_json
    assert body["action_scope"] == "personal"
    assert body["plugin_context"] == {"scope": "personal", "id": MCP_ACTION_ID, "name": before["name"]}
    assert body["auth"] == {"type": "key", "key": "Stored_In_KeyVault"}
    assert body["additionalFields"]["custom_headers"] == {"X-Workspace": "Stored_In_KeyVault"}
    assert body["additionalFields"]["custom"] == before["additionalFields"]["custom"]
    assert body["metadata"] == before["metadata"]
    assert body["clear_secret_paths"] == []
    expect(page.get_by_role("status").filter(has_text="Discovered 2 tools.")).to_be_visible()
    expect(page.get_by_role("checkbox", name=re.compile("^legacy-tool"))).to_be_checked()
    expect(page.get_by_text("Not available in the current tool catalogue.", exact=False)).to_be_visible()
    page.get_by_role("checkbox", name=re.compile("^search ")).check()
    expected_tools = [
        {**tool, "output_schema": {}, "annotations": {}}
        for tool in ui.extra_posts["/api/plugins/mcp/discover"]["tools"]
    ] + [legacy_tool]
    assert ui.actions[MCP_ACTION_ID] == before
    assert not ui.editor_writes
    assert save_resource(ui, "action", identifier=MCP_ACTION_ID).status == 200
    assert_patch(
        ui, f"/api/user/plugins/{MCP_ACTION_ID}", revision,
        {"additionalFields": {"allowed_tool_names": ["legacy-tool", "search"], "mcp_tools": expected_tools}},
    )
    assert ui.actions[MCP_ACTION_ID] == {
        **before,
        "additionalFields": {
            **before["additionalFields"],
            "allowed_tool_names": ["legacy-tool", "search"], "mcp_tools": expected_tools,
        },
    }


def test_mcp_reusable_identity_and_explicit_secret_header_removal(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.actions[MCP_ACTION_ID])
    revision = ui.revision(MCP_ACTION_ID)
    ui.open(f"/workspace/actions/{MCP_ACTION_ID}")
    editor_section(page, "Authentication")
    page.get_by_label("Reusable identity", exact=True).select_option("workspace-identity")
    expect(page.get_by_label("Authentication method", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Remove header X-Workspace", exact=True).click()
    expect(page.get_by_label("X-Workspace", exact=True)).to_have_count(0)
    assert not ui.editor_writes
    assert save_resource(ui, "action", identifier=MCP_ACTION_ID).status == 200
    assert_patch(
        ui, f"/api/user/plugins/{MCP_ACTION_ID}", revision,
        {
            "identity_id": "workspace-identity",
            "auth": {"type": "identity", "identity": "workspace-identity"},
            "additionalFields": {"auth_method": "identity", "identity_auth_type": "managed_identity"},
        },
        clear=["/additionalFields/custom_headers/X-Workspace"],
    )
    assert ui.actions[MCP_ACTION_ID]["auth"]["key"] == before["auth"]["key"]
    assert ui.actions[MCP_ACTION_ID]["additionalFields"]["custom_headers"] == {}
    assert ui.actions[MCP_ACTION_ID]["additionalFields"]["custom"] == before["additionalFields"]["custom"]
    assert not any("/test-" in request.path or "/discover" in request.path for request in ui.writes)
    ui.assert_no_secret_storage()


def test_action_only_author_uses_safe_reminder_defaults_without_agent_access(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.disabled_sections["agents"] = "Agent authoring is disabled."
    ui.options["settings"].update({
        "allow_user_agents": False,
        "allow_user_plugins": True,
        "enable_key_vault_secret_storage": True,
        "enable_key_vault_secret_expiration_reminders": True,
        "key_vault_secret_expiration_default_lead_days": 21,
        "key_vault_secret_expiration_default_contact_email": "rotation-owner@example.test",
        "key_vault_secret_expiration_require_expiration": True,
    })
    ui.options["agent_types"] = [{**entry, "enabled": False} for entry in ui.options["agent_types"]]
    ui.options["model_endpoints"] = []
    ui.options["builtin_actions"] = []
    before = copy.deepcopy(ui.actions[ACTION_ID])
    revision = ui.revision(ACTION_ID)
    ui.open(f"/workspace/actions/{ACTION_ID}")
    expect(name_field(page, "action")).to_be_enabled()
    editor_section(page, "Advanced")
    expect(page.get_by_text("Key Vault storage is enabled; reminder delivery is enabled.", exact=False)).to_be_visible()
    tracking = page.get_by_role("checkbox", name=re.compile("^Track secret expiration"))
    tracking.focus()
    page.keyboard.press("Space")
    expect(tracking).to_be_checked()
    expect(action_field(page, "Reminder lead days")).to_have_value("21")
    expect(action_field(page, "Reminder email")).to_have_value("rotation-owner@example.test")
    expiration = (date.today() + timedelta(days=90)).isoformat()
    action_field(page, "Secret expiration date").fill(expiration)
    assert save_resource(ui, "action", identifier=ACTION_ID).status == 200
    reminder = {
        "enabled": True, "lead_days": 21,
        "contact_email": "rotation-owner@example.test", "expires_on": expiration,
    }
    assert_patch(
        ui, f"/api/user/plugins/{ACTION_ID}", revision,
        {"metadata": {"key_vault_secret_reminders": {"__all__": reminder}}},
    )
    assert ui.actions[ACTION_ID] == {
        **before, "metadata": {**before["metadata"], "key_vault_secret_reminders": {"__all__": reminder}},
    }
    assert any(request.path == "/api/user/agent/settings" for request in ui.requests)
    assert not any(request.path.startswith("/api/user/agents") for request in ui.requests)


def test_failed_mcp_preconfiguration_catalog_preserves_saved_configuration(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    before = copy.deepcopy(ui.actions[MCP_ACTION_ID])
    ui.reject_next("GET", "/api/plugins/mcp/preconfigurations", error="MCP starting points could not be loaded.")
    ui.open(f"/workspace/actions/{MCP_ACTION_ID}")
    editor_section(page, "Configuration")
    expect(page.get_by_role("alert").filter(has_text="MCP starting points could not be loaded.")).to_be_visible()
    expect(action_field(page, "MCP server endpoint")).to_have_value(before["endpoint"])
    page.get_by_role("button", name="Retry catalogues", exact=True).click()
    expect(page.get_by_label("Preconfigured server", exact=True).get_by_role(
        "option", name="Review MCP server", exact=True
    )).to_be_attached()
    assert ui.actions[MCP_ACTION_ID] == before
    assert not ui.editor_writes


def test_action_type_picker_uses_complete_governed_catalog_including_custom_types(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/actions/new")
    chooser = action_field(page, "Action type")
    values = chooser.get_by_role("option").evaluate_all(
        "options => options.map(option => option.value).filter(Boolean)"
    )
    assert set(values) == {definition["type"] for definition in ui.types}
    assert len(values) == len(set(values))
    expect(chooser.get_by_role("option", name="Call agent", exact=True)).to_have_count(1)
    expect(chooser.get_by_role("option", name="Custom governed connector", exact=True)).to_have_count(1)
    assert not ui.editor_writes


def test_keyboard_save_uses_the_same_conditional_per_record_write(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    revision = ui.revision(AGENT_ID)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    name = page.get_by_label("Display name", exact=True)
    name.fill("Keyboard-saved agent")
    with page.expect_response(
        lambda response: response.request.method == "PATCH" and urlsplit(response.url).path == f"/api/user/agents/{AGENT_ID}"
    ) as response:
        name.press("Control+s")
    assert response.value.status == 200
    expect(page).to_have_url(f"{ORIGIN}/v2/workspace/agents")
    assert_patch(ui, f"/api/user/agents/{AGENT_ID}", revision, {"display_name": "Keyboard-saved agent"})


def test_agent_required_fields_focus_the_invalid_control_without_writing(workspace_ui):
    ui, page = workspace_ui, workspace_ui.page
    ui.open("/workspace/agents/new", width=390, height=844)
    save = page.get_by_role("button", name="Save agent", exact=True)
    save.click()
    expect(page.get_by_label("Display name", exact=True)).to_be_focused()
    page.get_by_label("Display name", exact=True).fill("Required-field review")
    save.click()
    expect(page.get_by_label("Description", exact=True)).to_be_focused()
    page.get_by_label("Description", exact=True).fill("Validate required instructions.")
    save.click()
    expect(page.get_by_role("textbox", name="Instructions", exact=True)).to_be_focused()
    assert not ui.editor_writes
    assert not any(request.path == "/api/agents/generate_id" for request in ui.requests)
