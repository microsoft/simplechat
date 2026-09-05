# test_agent_delegation_v2.py
"""
Real V2 Call agent create/edit/attach workflows for personal, group and global scopes.
Version: 0.261.093
Implemented in: 0.261.093

Deterministic local Playwright coverage using the existing orchestration harness pattern.
No deployed service, model calls, credentials or remote browser workspace is needed.
The real components and API client run against scoped response fixtures. Browser errors
fail tests, and desktop/mobile runs load the real production V2 CSS.
"""

import copy
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.orchestration.harness_build import start_static_server


HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "agent_delegation"
ROOT = HERE.parent
SPEC = importlib.util.spec_from_file_location("delegation_harness", FIXTURE / "harness_build.py")
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


def target(agent_id="target", scope="personal", scope_id="user-1", agent_type="local"):
    return {
        "id": agent_id, "scope_type": scope, "scope_id": scope_id,
        "name": f"{scope}-{agent_id}", "display_name": f"{scope} {agent_id}",
        "description": "Delegation target", "agent_type": agent_type,
    }


def action(action_id="call-1", target_ref=None):
    reference = target_ref or target()
    return {
        "id": action_id, "name": action_id, "displayName": f"Call {action_id}",
        "type": "agent", "description": "Delegate a task", "endpoint": "internal://agent",
        "auth": {"type": "user"}, "metadata": {"keep": "metadata"},
        "additionalFields": {"target_agent": {
            key: reference[key] for key in ("id", "scope_type", "scope_id")
        }},
    }


class ApiFixture:
    """Scoped endpoint fixture that records exact writes without simulating UI behavior."""

    def __init__(self, page):
        self.writes = []
        self.reads = []
        self.manage = True
        self.denied = False
        self.conflict = False
        self.actions = {
            "personal": [action(), action("self", target("caller"))],
            "group": [action("group-call", target(scope="group", scope_id="group-1"))],
            "global": [action("global-call", target(scope="global", scope_id="global"))],
        }
        self.agents = {}
        self.targets = {}
        for scope, scope_id in (("personal", "user-1"), ("group", "group-1"), ("global", "global")):
            self.targets[scope] = [
                target("target", scope, scope_id),
                target("caller", scope, scope_id),
                target("remote", scope, scope_id, "new_foundry"),
            ]
            if scope != "global":
                self.targets[scope].append(target("shared", "global", "global", "foundry_workflow"))
            self.agents[scope] = [
                {
                    "id": "caller", "name": "caller", "display_name": "Local caller",
                    "agent_type": "local", "actions_to_load": ["legacy-name", "unknown-id"],
                    "other_settings": {"action_capabilities": {"legacy-name": ["read"]}},
                    "model_connection": "keep-model", "assigned_knowledge": ["keep-document"],
                    "is_global": scope == "global", "is_group": scope == "group",
                },
                {"id": "remote", "display_name": "Remote target", "agent_type": "new_foundry",
                 "is_global": scope == "global", "is_group": scope == "group"},
            ]
        page.route("**/api/**", self.handle)

    def handle(self, route):
        request = route.request
        parsed = urlparse(request.url)
        query = parse_qs(parsed.query)
        path = unquote(parsed.path)

        def respond(payload, status=200):
            route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

        if request.method != "GET":
            payload = request.post_data_json if request.post_data else None
            self.writes.append((request.method, path, query, payload))
            scope = "group" if "/group/" in path else "global" if "/admin/" in path else "personal"
            if request.method == "DELETE" and "/plugins/" in path:
                identifier = path.rsplit("/", 1)[-1]
                field = "name" if scope == "global" else "id"
                self.actions[scope] = [item for item in self.actions[scope] if item.get(field) != identifier]
                respond({"success": True})
                return
            if path.endswith("/agent-actions"):
                if self.conflict:
                    respond({"error": "Changed by another editor"}, 409)
                    return
                self.agents[scope][0]["actions_to_load"] = ["legacy-name", "unknown-id", *payload["action_ids"]]
            elif "/plugins" in path:
                updated = {**payload, "id": payload.get("id", "new-action")}
                if scope == "global":
                    updated["is_global"] = True
                if scope == "group":
                    updated["is_group"] = True
                self.actions[scope] = [item for item in self.actions[scope] if item["id"] != updated["id"]] + [updated]
            elif path == "/api/user/agents":
                self.agents["personal"].append(payload)
            respond({"success": True})
            return

        self.reads.append((path, query))
        if path == "/api/plugins/agent-targets":
            if self.denied:
                respond({"error": "Unavailable scope"}, 403)
                return
            scope = query["scope"][0]
            respond({
                "targets": self.targets[scope], "can_manage": self.manage,
                "scope_type": scope, "scope_id": query.get("group_id", ["global" if scope == "global" else "user-1"])[0],
            })
        elif path == "/api/groups":
            respond({"groups": [
                {"id": "group-1", "name": "Research group", "userRole": "Owner"},
                {"id": "group-2", "name": "Read-only group", "userRole": "User"},
            ], "total_count": 2})
        elif path == "/api/v2/admin/settings":
            respond({
                "settings": {}, "field_schema": {}, "admin_nav": [
                    {"id": "general", "label": "General", "tabs": []},
                    {"id": "agents-actions", "label": "Agents & Actions", "tabs": []},
                ],
            })
        elif path == "/api/agents/generate_id":
            respond({"id": "new-agent"})
        elif path.endswith("/plugins") or path.endswith("/agents"):
            scope = "group" if "/group/" in path else "global" if "/admin/" in path else "personal"
            resources = self.actions[scope] if path.endswith("/plugins") else self.agents[scope]
            if scope == "group":
                respond({"actions" if path.endswith("/plugins") else "agents": resources})
            else:
                respond(resources)
        else:
            respond({"error": f"Unexpected test endpoint {path}"}, 500)


@pytest.fixture(scope="module")
def harness_url():
    HARNESS.ensure_bundle()
    with start_static_server() as origin:
        yield origin
    HARNESS.BUNDLE.unlink(missing_ok=True)


@pytest.fixture
def ui(page, harness_url):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    api = ApiFixture(page)
    page.goto(f"{harness_url}/ui_tests/fixtures/agent_delegation/harness.html")
    css_files = sorted((ROOT / "application" / "single_app" / "static" / "v2" / "assets").glob("*.css"))
    assert css_files, "Run npm run build in application/v2_ui before UI tests."
    page.add_style_tag(url=f"{harness_url}/{css_files[0].relative_to(ROOT).as_posix()}")
    yield page, api
    assert not errors, errors


def mount(page, view, admin=True):
    page.evaluate("([view, admin]) => window.AgentDelegationHarness.mount(view, admin)", [view, admin])


def create_call(page, name, label):
    page.get_by_role("button", name="New Call agent action", exact=True).click()
    page.get_by_label("Action name", exact=True).fill(name)
    page.get_by_label("Search target agents").fill(label.split(" · ")[0])
    page.get_by_label("Target agent", exact=True).select_option(label=label)
    page.get_by_role("button", name="Save Call agent action", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Call agent action saved.")).to_be_visible()


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 900}, {"width": 390, "height": 844}])
def test_personal_create_edit_and_safe_rendering(ui, viewport):
    page, api = ui
    page.set_viewport_size(viewport)
    mount(page, "actions")
    create_call(page, "<img src=x onerror=alert(1)>", "global shared · global · foundry_workflow")
    first = api.writes[-1]
    assert first[:2] == ("POST", "/api/user/plugins")
    assert first[3]["endpoint"] == "internal://agent"
    assert first[3]["auth"] == {"type": "user"}
    assert first[3]["additionalFields"]["target_agent"] == {
        "id": "shared", "scope_type": "global", "scope_id": "global",
    }
    expect(page.locator("img")).to_have_count(0)
    page.get_by_role("button", name="Edit Call agent action <img src=x onerror=alert(1)>").click()
    page.get_by_label("Action name", exact=True).fill("Renamed action")
    page.get_by_role("button", name="Save Call agent action", exact=True).click()
    expect(page.get_by_text("Renamed action", exact=True)).to_be_visible()
    assert api.writes[-1][:2] == ("PATCH", "/api/user/plugins/new-action")
    assert api.writes[-1][3]["id"] == "new-action"
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_personal_bindings_preserve_unknown_refs_and_conflict(ui):
    page, api = ui
    before = copy.deepcopy(api.agents["personal"][0])
    mount(page, "agents")
    page.get_by_role("button", name="Attach Call agent actions to Local caller").click()
    expect(page.get_by_role("checkbox", name="Call self")).to_be_disabled()
    expect(page.get_by_text("Target only — configure tools in Foundry")).to_be_visible()
    page.get_by_role("checkbox", name="Call call-1").check()
    api.conflict = True
    page.get_by_role("button", name="Save bindings", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="changed in another session")).to_be_visible()
    expect(page.get_by_role("button", name="Save bindings", exact=True)).to_be_disabled()
    assert api.writes[-1][3] == {
        "action_ids": ["call-1"], "expected_actions_to_load": ["legacy-name", "unknown-id"],
    }
    page.get_by_role("button", name="Reload Call agent resources").click()
    page.get_by_role("button", name="Discard changes and reload").click()
    api.conflict = False
    page.get_by_role("button", name="Attach Call agent actions to Local caller").click()
    page.get_by_role("checkbox", name="Call call-1").check()
    page.get_by_role("button", name="Save bindings", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="bindings saved")).to_be_visible()
    assert api.agents["personal"][0] == {**before, "actions_to_load": ["legacy-name", "unknown-id", "call-1"]}


@pytest.mark.parametrize("scope,view,action_id", [
    ("personal", "actions", "call-1"),
    ("group", "groups", "group-call"),
    ("global", "admin", "global-call"),
])
def test_native_call_action_deletion_requires_confirmation_and_preserves_callers(ui, scope, view, action_id):
    page, api = ui
    original_agents = copy.deepcopy(api.agents)
    mount(page, view)
    if scope == "group":
        page.get_by_label("Group workspace", exact=True).select_option("group-1")
    elif scope == "global":
        page.get_by_role("button", name="Agents & Actions", exact=True).click()
    page.get_by_role("button", name=f"Delete Call agent action Call {action_id}", exact=True).click()
    assert not api.writes
    page.get_by_role("button", name="Confirm delete", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Call agent action deleted.")).to_be_visible()
    expect(page.get_by_role("button", name=f"Edit Call agent action Call {action_id}", exact=True)).to_have_count(0)
    owner = "user" if scope == "personal" else "admin" if scope == "global" else "group"
    assert api.writes[-1][:2] == ("DELETE", f"/api/{owner}/plugins/{action_id}")
    assert api.writes[-1][2] == ({"group_id": ["group-1"]} if scope == "group" else {})
    assert api.agents == original_agents


def test_personal_new_agent_then_attach(ui):
    page, api = ui
    mount(page, "agents")
    page.get_by_role("button", name="New agent", exact=True).click()
    page.get_by_label("Name", exact=True).fill("New caller")
    page.get_by_label("Instructions", exact=True).fill("Delegate careful reviews.")
    page.get_by_role("button", name="Create agent", exact=True).click()
    page.get_by_role("button", name="Attach Call agent actions to New caller").click()
    page.get_by_role("checkbox", name="Call call-1").check()
    page.get_by_role("button", name="Save bindings", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="bindings saved")).to_be_visible()
    assert api.writes[-1][:2] == ("PATCH", "/api/user/agents/new-agent/agent-actions")
    assert api.writes[-1][3]["expected_actions_to_load"] == []


def test_group_native_scoping_permissions_and_unsaved_changes(ui):
    page, api = ui
    mount(page, "groups")
    page.get_by_label("Group workspace", exact=True).select_option("group-1")
    create_call(page, "Group delegate", "group target · group · local")
    assert api.writes[-1][2] == {"group_id": ["group-1"]}
    page.get_by_role("button", name="Edit Call agent action Group delegate").click()
    expect(page.get_by_label("Group workspace", exact=True)).to_be_disabled()
    page.get_by_label("Action name", exact=True).fill("Group renamed")
    page.get_by_role("button", name="Save Call agent action", exact=True).click()
    expect(page.get_by_text("Group renamed", exact=True)).to_be_visible()
    assert api.writes[-1][:3] == ("PATCH", "/api/group/plugins/new-action", {"group_id": ["group-1"]})
    page.get_by_role("button", name="Attach Call agent actions to Local caller").click()
    page.get_by_role("checkbox", name="Group renamed").check()
    page.get_by_role("button", name="Save bindings", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="bindings saved")).to_be_visible()
    assert api.writes[-1][:3] == ("PATCH", "/api/group/agents/caller/agent-actions", {"group_id": ["group-1"]})
    assert not any("setActive" in item[1] for item in api.writes)
    assert all(query.get("group_id") for path, query in api.reads if path.startswith("/api/group/"))
    page.get_by_label("Group workspace", exact=True).select_option("group-2")
    expect(page.get_by_text("Read-only access.", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)


def test_group_owner_only_catalog_can_deny_management(ui):
    page, api = ui
    api.manage = False
    mount(page, "groups")
    page.get_by_label("Group workspace", exact=True).select_option("group-1")
    expect(page.get_by_text("Read-only access.", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)
    assert not api.writes


@pytest.mark.parametrize("mobile", [False, True])
def test_admin_fetches_only_visible_group_and_uses_resource_apis(ui, mobile):
    page, api = ui
    page.set_viewport_size({"width": 390, "height": 844} if mobile else {"width": 1440, "height": 900})
    mount(page, "admin")
    if mobile:
        expect(page.get_by_label("Settings category", exact=True)).to_be_visible()
    else:
        expect(page.get_by_role("button", name="Agents & Actions", exact=True)).to_be_visible()
    assert not any(path in ("/api/admin/agents", "/api/admin/plugins", "/api/plugins/agent-targets") for path, _ in api.reads)
    if mobile:
        page.get_by_label("Settings category", exact=True).select_option("agents-actions")
    else:
        page.get_by_role("button", name="Agents & Actions", exact=True).click()
    create_call(page, "Global delegate", "global remote · global · new_foundry")
    page.get_by_role("button", name="Edit Call agent action Global delegate").click()
    page.get_by_label("Action name", exact=True).fill("Global renamed")
    page.get_by_role("button", name="Save Call agent action", exact=True).click()
    expect(page.get_by_text("Global renamed", exact=True)).to_be_visible()
    assert api.writes[-1][:2] == ("PUT", "/api/admin/plugins/Global-delegate")
    assert api.writes[-1][3]["id"] == "new-action"
    page.get_by_role("button", name="Attach Call agent actions to Local caller").click()
    page.get_by_role("checkbox", name="Global renamed").check()
    page.get_by_role("button", name="Save bindings", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="bindings saved")).to_be_visible()
    assert api.writes[-1][:2] == ("PATCH", "/api/admin/agents/caller/agent-actions")
    assert not any("/v2/admin/settings" in path for _, path, _, _ in api.writes)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_non_admin_does_not_fetch_global_resources(ui):
    page, api = ui
    mount(page, "admin", admin=False)
    expect(page.get_by_text("Administrator access required")).to_be_visible()
    assert not api.reads


def test_unavailable_target_empty_catalog_denial_and_keyboard(ui):
    page, api = ui
    api.targets["personal"] = []
    mount(page, "actions")
    page.get_by_role("button", name="Edit Call agent action Call call-1").click()
    expect(page.get_by_role("alert").filter(has_text="saved target is unavailable")).to_be_visible()
    expect(page.get_by_role("button", name="Save Call agent action", exact=True)).to_be_disabled()
    expect(page.get_by_role("status").filter(has_text="No permitted target")).to_be_visible()
    page.get_by_role("button", name="Cancel", exact=True).click()
    api.targets["personal"] = [target()]
    page.get_by_role("button", name="Reload Call agent resources").click()
    page.get_by_role("button", name="New Call agent action", exact=True).click()
    expect(page.get_by_label("Action name", exact=True)).to_be_focused()
    page.get_by_label("Action name", exact=True).fill("Keyboard action")
    page.get_by_label("Target agent", exact=True).focus()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(page.get_by_role("button", name="Save Call agent action", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Cancel", exact=True).click()
    api.denied = True
    page.get_by_role("button", name="Reload Call agent resources").click()
    expect(page.get_by_role("alert").filter(has_text="Access denied")).to_be_visible()
    expect(page.get_by_role("button", name="New Call agent action", exact=True)).to_have_count(0)


@pytest.mark.parametrize("agent_type", ["local", "aifoundry", "new_foundry", "foundry_workflow"])
def test_all_supported_target_types_can_be_selected(ui, agent_type):
    page, api = ui
    api.targets["personal"] = [target(agent_type=agent_type)]
    mount(page, "actions")
    create_call(page, f"Delegate {agent_type}", f"personal target · personal · {agent_type}")
    assert api.writes[-1][3]["additionalFields"]["target_agent"]["id"] == "target"


def test_existing_unavailable_binding_can_be_detached(ui):
    page, api = ui
    api.agents["personal"][0]["actions_to_load"].append("call-1")
    api.targets["personal"] = []
    mount(page, "agents")
    page.get_by_role("button", name="Attach Call agent actions to Local caller").click()
    selected = page.get_by_role("checkbox", name="Call call-1")
    expect(selected).to_be_checked()
    expect(selected).to_be_enabled()
    selected.uncheck()
    page.get_by_role("button", name="Save bindings", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="bindings saved")).to_be_visible()
    assert api.writes[-1][3] == {
        "action_ids": [], "expected_actions_to_load": ["legacy-name", "unknown-id", "call-1"],
    }
