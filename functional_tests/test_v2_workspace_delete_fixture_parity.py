# test_v2_workspace_delete_fixture_parity.py
"""
Parity between the V2 browser fixtures' owner-delete answers and the real delete routes.
Version: 0.261.448
Implemented in: 0.261.448

The V2 group and public workspace Settings danger zones delete the workspace natively: they read the
document count, confirm, and send the owner's `DELETE /api/groups/<id>` or
`DELETE /api/public_workspaces/<id>` -- the routes classic's manage pages call. The browser suites mock
the network with `ui_tests/fixtures/group_workspace.py` and `ui_tests/fixtures/public_settings.py`, so a
fixture whose answers drift from the server would let a passing browser test hide a real regression.

This test runs the real route functions -- their bodies taken from `route_backend_groups.py` and
`route_backend_public_workspaces.py`, with the real `create_group_role_required` decorator from
`functions_authentication.py` in front of the group one, and only the storage calls replaced -- through
a Flask test client, drives the fixtures through the same `_dispatch` entry their Playwright route
handlers use, and requires the status and JSON to agree for the owner, a non-owner, a missing
workspace and the CreateGroups-role refusal.

It also pins the premise the V2 flow is built on: the server itself checks neither the workspace's
status, its documents (the page checks the count, as classic's script does) nor creates an approval
request, so the delete is immediate. If a route ever starts refusing a locked or inactive workspace,
or one that still holds documents, this test fails and the V2 danger zone must follow.
"""

import ast
import sys
from functools import wraps
from pathlib import Path

import pytest
from flask import Flask, jsonify, request, session

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from test_support.agent_delegation import execute_functions  # noqa: E402
from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture, group_context  # noqa: E402
from ui_tests.fixtures.public_settings import PublicSettingsFixture  # noqa: E402
from ui_tests.fixtures.workspace_authoring import ApiRequest, ORIGIN  # noqa: E402


FIXTURE_GROUP = "group-a"
FIXTURE_WORKSPACE = "pub-a"
REAL_ID = "ws-1"
OWNER = "owner-1"
CREATE_GROUPS_REFUSAL = {"error": "Forbidden", "message": "Insufficient permissions (CreateGroups role required)"}


# --------------------------------------------------------------------------
# Fixture driving: a fake page and route that capture the fulfilled response.
# --------------------------------------------------------------------------

class _FakeContext:
    def route(self, *args, **kwargs):
        pass

    def on(self, *args, **kwargs):
        pass


class _FakePage:
    def __init__(self):
        self.context = _FakeContext()
        self.url = "about:blank"

    def on(self, *args, **kwargs):
        pass


class _FakeRequest:
    def __init__(self, url, method):
        self.url = url
        self.method = method
        self.headers = {}
        self.post_data_buffer = None


class _FakeRoute:
    def __init__(self, url, method):
        self.request = _FakeRequest(url, method)
        self.status = 200
        self.payload = None

    def fulfill(self, status=200, json=None, **kwargs):
        self.status = status
        self.payload = json


def drive(fixture, method, path):
    route = _FakeRoute(f"{ORIGIN}{path}", method)
    fixture._dispatch(route, ApiRequest(method=method, path=path, query={}, body=None))
    return route.status, route.payload


# --------------------------------------------------------------------------
# The real routes: their own function bodies, run behind the real decorator.
# --------------------------------------------------------------------------

def real_route(file_name, function_name, namespace):
    """Compile the real route function, without its blueprint and auth decorators, into `namespace`."""
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            node.decorator_list = []
            exec(compile(ast.Module(body=[node], type_ignores=[]), file_name, "exec"), namespace)
            return namespace[function_name], ast.get_source_segment(
                (APP_ROOT / file_name).read_text(encoding="utf-8"), node,
            )
    raise LookupError(f"{file_name} defines no {function_name}")


class RealRoutes:
    """The two delete routes over in-memory stores, called through a Flask test client."""

    def __init__(self):
        self.settings = {}
        self.groups = {}
        self.workspaces = {}
        self.user_id = OWNER
        self.roles = ["User"]
        self.deleted_groups = []
        self.deleted_workspaces = []

        auth = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "get_settings": lambda: self.settings,
        }
        execute_functions("functions_authentication.py", ["create_group_role_required"], auth)
        who = lambda: {"userId": self.user_id}  # noqa: E731

        group_route, self.group_source = real_route("route_backend_groups.py", "api_delete_group", {
            "jsonify": jsonify, "get_current_user_info": who,
            "find_group_by_id": lambda group_id: self.groups.get(group_id),
            "delete_group": self.deleted_groups.append,
        })
        public_route, self.public_source = real_route(
            "route_backend_public_workspaces.py", "api_delete_public_workspace", {
                "jsonify": jsonify, "get_current_user_info": who,
                "find_public_workspace_by_id": lambda workspace_id: self.workspaces.get(workspace_id),
                "delete_public_workspace": self.deleted_workspaces.append,
            })

        self.app = Flask("workspace_delete_parity")
        self.app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        self.app.add_url_rule(
            "/api/groups/<group_id>", "delete_group", auth["create_group_role_required"](group_route),
            methods=["DELETE"],
        )
        self.app.add_url_rule(
            "/api/public_workspaces/<ws_id>", "delete_public_workspace", public_route, methods=["DELETE"],
        )

    def delete(self, path):
        client = self.app.test_client()
        with client.session_transaction() as state:
            state["user"] = {"oid": self.user_id, "roles": self.roles}
        response = client.delete(path)
        return response.status_code, response.get_json()


@pytest.fixture
def real():
    routes = RealRoutes()
    routes.groups[REAL_ID] = {"id": REAL_ID, "status": "active", "owner": {"id": OWNER}}
    routes.workspaces[REAL_ID] = {"id": REAL_ID, "status": "active", "owner": {"userId": OWNER}}
    return routes


def group_fixture(role="Owner", status="active", **flags):
    fixture = GroupWorkspaceFixture(_FakePage())
    fixture.groups[FIXTURE_GROUP] = group_context(
        FIXTURE_GROUP, "Research group", role=role, status=status, viewer=fixture.viewer_id,
    )
    if flags:
        fixture.apply_group_settings_flags(FIXTURE_GROUP, **flags)
    return fixture


def public_fixture(role="Owner", status="active"):
    fixture = PublicSettingsFixture(_FakePage())
    fixture.configure(FIXTURE_WORKSPACE, role=role, status=status)
    return fixture


# --------------------------------------------------------------------------
# Group: the same answers for every caller.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role,expected", [
    ("Owner", (200, {"message": "Group deleted successfully"})),
    ("Admin", (403, {"error": "Only the owner can delete the group"})),
    ("DocumentManager", (403, {"error": "Only the owner can delete the group"})),
    ("User", (403, {"error": "Only the owner can delete the group"})),
])
def test_group_delete_answers_match_the_real_route_for_every_role(real, role, expected):
    real.user_id = OWNER if role == "Owner" else "someone-else"
    real_answer = real.delete(f"/api/groups/{REAL_ID}")
    fixture = group_fixture(role=role)
    fixture_answer = drive(fixture, "DELETE", f"/api/groups/{FIXTURE_GROUP}")
    assert real_answer == expected
    assert fixture_answer == expected
    # Only the owner's delete reaches the storage call, on both sides.
    assert real.deleted_groups == ([REAL_ID] if role == "Owner" else [])
    assert fixture.deleted_groups == ([FIXTURE_GROUP] if role == "Owner" else [])


def test_group_delete_of_a_missing_group_is_a_404_on_both_sides(real):
    fixture = group_fixture()
    expected = (404, {"error": "Group not found"})
    assert real.delete("/api/groups/missing") == expected
    assert drive(fixture, "DELETE", "/api/groups/missing") == expected
    assert not real.deleted_groups and not fixture.deleted_groups


@pytest.mark.parametrize("holds_role,expected", [
    (False, (403, CREATE_GROUPS_REFUSAL)),
    (True, (200, {"message": "Group deleted successfully"})),
])
def test_the_create_groups_role_gates_the_group_delete_on_both_sides(real, holds_role, expected):
    # The classic decorator reads the session's roles, and only when the deployment requires the role.
    real.settings["require_member_of_create_group"] = True
    real.roles = ["User", "CreateGroups"] if holds_role else ["User"]
    fixture = group_fixture(create_role_required=True, has_create_role=holds_role)
    assert real.delete(f"/api/groups/{REAL_ID}") == expected
    assert drive(fixture, "DELETE", f"/api/groups/{FIXTURE_GROUP}") == expected
    assert bool(real.deleted_groups) == bool(fixture.deleted_groups) == holds_role


def test_the_create_groups_gate_is_off_unless_the_deployment_requires_it(real):
    real.settings["require_member_of_create_group"] = False
    fixture = group_fixture(create_role_required=False, has_create_role=False)
    expected = (200, {"message": "Group deleted successfully"})
    assert real.delete(f"/api/groups/{REAL_ID}") == expected
    assert drive(fixture, "DELETE", f"/api/groups/{FIXTURE_GROUP}") == expected


# --------------------------------------------------------------------------
# Public workspace.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role,expected", [
    ("Owner", (200, {"message": "Deleted"})),
    ("Admin", (403, {"error": "Only owner can delete"})),
    ("DocumentManager", (403, {"error": "Only owner can delete"})),
    ("User", (403, {"error": "Only owner can delete"})),
])
def test_public_delete_answers_match_the_real_route_for_every_role(real, role, expected):
    real.user_id = OWNER if role == "Owner" else "someone-else"
    real_answer = real.delete(f"/api/public_workspaces/{REAL_ID}")
    fixture = public_fixture(role=role)
    fixture_answer = drive(fixture, "DELETE", f"/api/public_workspaces/{FIXTURE_WORKSPACE}")
    assert real_answer == expected
    assert fixture_answer == expected
    assert real.deleted_workspaces == ([REAL_ID] if role == "Owner" else [])
    assert fixture.deleted_workspaces == ([FIXTURE_WORKSPACE] if role == "Owner" else [])


def test_public_delete_of_a_missing_workspace_is_a_404_on_both_sides(real):
    fixture = public_fixture()
    expected = (404, {"error": "Workspace not found"})
    assert real.delete("/api/public_workspaces/missing") == expected
    assert drive(fixture, "DELETE", "/api/public_workspaces/missing") == expected
    assert not real.deleted_workspaces and not fixture.deleted_workspaces


def test_the_public_fixture_serves_the_owner_delete_but_still_traps_the_classic_settings_writes():
    fixture = public_fixture()
    status, _ = drive(fixture, "DELETE", f"/api/public_workspaces/{FIXTURE_WORKSPACE}")
    assert status == 200 and not fixture.unexpected_requests
    assert FIXTURE_WORKSPACE not in fixture.workspaces
    assert fixture.active_workspace is None, "A deleted active workspace is no longer the caller's active one."
    fixture = public_fixture()
    status, _ = drive(fixture, "PATCH", f"/api/public_workspaces/{FIXTURE_WORKSPACE}")
    assert status == 500 and len(fixture.unexpected_requests) == 1


def test_a_deleted_group_leaves_the_fixtures_account_and_active_group():
    fixture = group_fixture()
    fixture.active_group = FIXTURE_GROUP
    assert drive(fixture, "DELETE", f"/api/groups/{FIXTURE_GROUP}")[0] == 200
    assert FIXTURE_GROUP not in fixture.groups and fixture.active_group is None
    assert FIXTURE_GROUP not in [group["id"] for group in fixture._bootstrap()["scope"]["groups"]]


# --------------------------------------------------------------------------
# The premise the V2 flow is built on: the server checks no status, no documents, no approval.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["active", "locked", "upload_disabled", "inactive", "frozen"])
def test_the_real_routes_delete_whatever_the_workspace_status(real, status):
    real.groups[REAL_ID]["status"] = status
    real.workspaces[REAL_ID]["status"] = status
    assert real.delete(f"/api/groups/{REAL_ID}")[0] == 200
    assert real.delete(f"/api/public_workspaces/{REAL_ID}")[0] == 200
    assert real.deleted_groups == [REAL_ID] and real.deleted_workspaces == [REAL_ID]


@pytest.mark.parametrize("status", ["active", "locked", "upload_disabled", "inactive", "frozen"])
def test_the_fixtures_delete_whatever_the_workspace_status_too(status):
    assert drive(group_fixture(status=status), "DELETE", f"/api/groups/{FIXTURE_GROUP}")[0] == 200
    assert drive(public_fixture(status=status), "DELETE", f"/api/public_workspaces/{FIXTURE_WORKSPACE}")[0] == 200


def test_the_real_routes_neither_count_documents_nor_create_an_approval_request(real):
    # The document count is the page's gate (classic's script reads /fileCount before it calls), not the
    # route's: a record that says it still holds documents is deleted all the same.
    real.groups[REAL_ID]["document_count"] = 12
    real.workspaces[REAL_ID]["document_count"] = 12
    assert real.delete(f"/api/groups/{REAL_ID}")[0] == 200
    assert real.delete(f"/api/public_workspaces/{REAL_ID}")[0] == 200
    for source in (real.group_source, real.public_source):
        lowered = source.lower()
        assert "approval" not in lowered, "A delete route now creates or checks an approval request."
        assert "filecount" not in lowered and "count_documents" not in lowered
        assert "status" not in lowered, "A delete route now looks at the workspace status."
