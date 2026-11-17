#!/usr/bin/env python3
# test_v2_workflow_activity_gates.py
"""
Functional test that the V2 Workflow Activity page is behind the same gates as the classic page.
Version: 0.261.445
Implemented in: 0.261.445

The V2 page at /v2/workflow-activity has no page route of its own to gate. It is served as part of
the SPA, and everything it shows comes from GET /api/{user|group}/workflows/activity and the event
stream beside it. So whoever those routes let in is whoever the V2 page lets in, and they must let in
exactly the people the classic /workflow-activity page does: scope personal needs workflows switched
on and, when the app requires it, the WorkflowUser role; scope group needs group workspaces and group
workflows switched on, the group to be assigned, and the reader to hold a member role in it.

This test runs the real classic page gate (`_authorize_workflow_activity_view`) and the real API
route functions with their real gate decorators (`enabled_required`, `workflow_user_required`) and
group helpers over every combination of the settings, the app roles and the group membership, and
fails when the two ever disagree about who is let in or why they are refused. It also checks the
event stream is gated exactly as the snapshot beside it. Nothing here touches Cosmos DB, a group
directory, a model or the network: the context loaders and the directory are fakes that both gates
ask the same questions of.
"""

import ast
import itertools
import sys
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Imported after the path is set up, as the other route policy tests do.
from functions_group_assignment_ids import normalize_group_workflow_allowed_group_ids  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


PAGE_ROUTES = APP / "route_frontend_chats.py"
API_ROUTES = APP / "route_backend_workflows.py"
SETTINGS_MODULE = APP / "functions_settings.py"
GROUP_POLICY = APP / "functions_group_workflow_policy.py"

ROLE_FUNCTIONS = (
    "normalize_app_role_claims", "has_workflow_user_app_role", "is_user_workflows_enabled_for_user",
    "is_group_workflows_enabled_for_group",
)
GATE_FUNCTIONS = (*ROLE_FUNCTIONS, "_is_api_request", "workflow_user_required", "enabled_required")
PAGE_FUNCTIONS = (
    "_normalize_workflow_activity_scope", "_resolve_workflow_activity_group_id", "_authorize_workflow_activity_view",
)
GROUP_HELPERS = (
    "_normalize_identifier", "_assert_group_workflow_feature_enabled", "_resolve_active_group_for_workflows",
    "_resolve_group_workflow_request_group",
)
PERSONAL = "/api/user/workflows/activity"
GROUP = "/api/group/workflows/activity"
USER_ID = "user-1"
OK = {"ok": True}


def parsed_module(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def top_level_functions(path, names):
    found = {
        node.name: node for node in parsed_module(path).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    }
    missing = sorted(set(names) - set(found))
    assert missing == [], f"{path.name} no longer defines {missing}"
    return [found[name] for name in names]


def top_level_constant(path, name):
    for node in parsed_module(path).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name} no longer defines {name}")


def route_functions(path):
    """The routes registered inside `register_route_backend_workflows`, by their path."""
    registrar = next(
        node for node in parsed_module(API_ROUTES).body
        if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_workflows"
    )
    found = {}
    for node in registrar.body:
        if not (isinstance(node, ast.FunctionDef) and node.decorator_list):
            continue
        first = node.decorator_list[0]
        if isinstance(first, ast.Call) and first.args and isinstance(first.args[0], ast.Constant):
            found.setdefault(first.args[0].value, []).append(node)
    return found.get(path, [])


def one_route(path):
    matches = route_functions(path)
    assert len(matches) == 1, f"expected one route for {path}, found {len(matches)}"
    return matches[0]


def run_source(nodes, filename, namespace):
    exec(compile(ast.Module(body=list(nodes), type_ignores=[]), str(filename), "exec"), namespace)
    return namespace


class Blueprint:
    """Registers a view the way `bp.route` does, on a closed Flask app."""

    def __init__(self, app):
        self.app = app

    def route(self, path, methods):
        def register(view):
            self.app.add_url_rule(path, endpoint=f"{view.__name__}:{path}", view_func=view, methods=methods)
            return view
        return register


def unchanged(view):
    return view


class Directory:
    """Who belongs to which group, answered the way the group helpers answer it."""

    def __init__(self, known, memberships, active):
        self.known = known
        self.memberships = memberships
        self.active = active
        self.asked_roles = set()

    def assert_group_role(self, user_id, group_id, allowed_roles=("Owner", "Admin")):
        self.asked_roles.add(tuple(allowed_roles))
        if group_id not in self.known:
            raise LookupError("Group not found")
        role = self.memberships.get(group_id)
        if not role:
            raise PermissionError("User is not a member of this group")
        if role.lower() not in {allowed.lower() for allowed in allowed_roles}:
            raise PermissionError("Insufficient permissions for this group")
        return role

    def require_active_group(self, user_id, allowed_roles=("Owner", "Admin", "DocumentManager", "User")):
        if not self.active:
            raise ValueError("No active group selected")
        self.assert_group_role(user_id, self.active, allowed_roles=allowed_roles)
        return self.active


class Gates:
    """The classic page's gate and the API routes' gates, side by side, over one world."""

    def __init__(self):
        self.settings = {}
        self.session = {"user": {"roles": []}}
        self.directory = Directory(set(), {}, None)

        gates = run_source(top_level_functions(SETTINGS_MODULE, GATE_FUNCTIONS), SETTINGS_MODULE, {
            "wraps": wraps, "request": request, "session": self.session, "jsonify": jsonify,
            "get_settings": lambda: self.settings,
            "WORKFLOW_USER_APP_ROLE": top_level_constant(SETTINGS_MODULE, "WORKFLOW_USER_APP_ROLE"),
            "normalize_group_workflow_allowed_group_ids": normalize_group_workflow_allowed_group_ids,
        })

        self.page_roles = top_level_constant(PAGE_ROUTES, "GROUP_WORKFLOW_ACTIVITY_ROLES")
        self.api_roles = top_level_constant(GROUP_POLICY, "GROUP_WORKFLOW_MEMBER_ROLES")
        page = run_source(top_level_functions(PAGE_ROUTES, PAGE_FUNCTIONS), PAGE_ROUTES, {
            "request": request, "session": self.session,
            "GROUP_WORKFLOW_ACTIVITY_ROLES": self.page_roles,
            "assert_group_role": lambda *args, **kwargs: self.directory.assert_group_role(*args, **kwargs),
            "require_active_group": lambda *args, **kwargs: self.directory.require_active_group(*args, **kwargs),
            "is_group_workflows_enabled_for_group": gates["is_group_workflows_enabled_for_group"],
            "is_user_workflows_enabled_for_user": gates["is_user_workflows_enabled_for_user"],
        })
        self.authorize_page = page["_authorize_workflow_activity_view"]

        app = Flask("workflow-activity-gates")
        self.app = app
        namespace = {
            "bp": Blueprint(app),
            "swagger_route": lambda **_security: unchanged,
            "get_auth_security": lambda: [{"bearerAuth": []}],
            "login_required": unchanged,
            "user_required": unchanged,
            "enabled_required": gates["enabled_required"],
            "workflow_user_required": gates["workflow_user_required"],
            "request": request,
            "jsonify": jsonify,
            "logging": __import__("logging"),
            "get_settings": lambda: self.settings,
            "get_current_user_id": lambda: USER_ID,
            "log_event": lambda *args, **kwargs: None,
            "GROUP_WORKFLOW_MEMBER_ROLES": self.api_roles,
            "assert_group_role": lambda *args, **kwargs: self.directory.assert_group_role(*args, **kwargs),
            "require_active_group": lambda *args, **kwargs: self.directory.require_active_group(*args, **kwargs),
            "is_group_workflows_enabled_for_group": gates["is_group_workflows_enabled_for_group"],
            # What happens after the gates is not what is compared: a context that loads is `OK`.
            "_resolve_workflow_activity_context": lambda *args, **kwargs: dict(OK),
            "_resolve_group_workflow_activity_context": lambda *args, **kwargs: dict(OK),
        }
        run_source(top_level_functions(API_ROUTES, GROUP_HELPERS), API_ROUTES, namespace)
        run_source([one_route(PERSONAL), one_route(GROUP)], API_ROUTES, namespace)
        self.client = app.test_client()

    def world(self, *, settings, roles=None, known=(), memberships=None, active=None):
        self.settings.clear()
        self.settings.update(settings)
        self.session["user"] = {"roles": list(roles or [])}
        self.directory = Directory(set(known), dict(memberships or {}), active)

    def page(self, query):
        """What the classic page answers: None when it renders, else the status it refuses with."""
        with self.app.test_request_context("/workflow-activity", query_string=query):
            try:
                refused = self.authorize_page(USER_ID, self.settings)
            except PermissionError:
                return 403
            except LookupError:
                return 404
            except ValueError:
                return 400
        return 200 if refused is None else refused[1]

    def api(self, path, query):
        response = self.client.get(path, query_string=query)
        return response.status_code, response.get_json()


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.445")


def test_personal_activity_is_gated_by_the_same_rules_on_the_page_and_in_the_api():
    gates = Gates()
    mismatches = []
    for allow, require_role, roles in itertools.product(
        [False, True], [False, True], [[], ["WorkflowUser"], ["Reader"], None],
    ):
        gates.world(
            settings={"allow_user_workflows": allow, "require_member_of_workflow_user": require_role},
            roles=roles,
        )
        page_status = gates.page({"scope": "personal"})
        api_status, body = gates.api(PERSONAL, {})
        assert body is not None
        if page_status != api_status:
            mismatches.append((allow, require_role, roles, page_status, api_status))
        # A reader who is let in is let in to the snapshot, not to an error.
        if api_status == 200:
            assert body == OK
    assert mismatches == [], f"The page and the API disagree about personal workflows: {mismatches}"

    # A scope the page does not know is the personal page, as the V2 page's own refusal of it is a
    # question about a link, not about who may read.
    gates.world(settings={"allow_user_workflows": True, "require_member_of_workflow_user": False})
    assert gates.page({"scope": "anything"}) == 200 == gates.page({})


def test_group_activity_is_gated_by_the_same_rules_on_the_page_and_in_the_api():
    gates = Gates()
    mismatches = []
    checked = 0
    for enable, allow, assigned_only, allowed_ids, requested, active in itertools.product(
        [False, True], [False, True], [False, True], [[], ["g1"]], ["g1", "g2", "missing", ""], ["g1", "g2", None],
    ):
        gates.world(
            settings={
                "enable_group_workspaces": enable,
                "allow_group_workflows": allow,
                "require_group_assignment_for_group_workflows": assigned_only,
                "group_workflow_allowed_group_ids": allowed_ids,
                # Group access does not depend on personal workflows, in either direction.
                "allow_user_workflows": False,
            },
            known={"g1", "g2"},
            memberships={"g1": "User"},
            active=active,
        )
        page_query = {"scope": "group", **({"group_id": requested} if requested else {})}
        page_status = gates.page(page_query)
        api_status, body = gates.api(GROUP, {"group_id": requested} if requested else {})
        checked += 1
        if page_status != api_status:
            mismatches.append((enable, allow, assigned_only, allowed_ids, requested, active, page_status, api_status))
        if api_status == 200:
            assert body == OK
    assert checked == 2 * 2 * 2 * 2 * 4 * 3
    assert mismatches == [], f"The page and the API disagree about group workflows: {mismatches}"


def test_both_gates_ask_for_the_same_group_roles_and_the_active_group_fallback():
    gates = Gates()
    assert gates.page_roles == gates.api_roles == ("Owner", "Admin", "DocumentManager", "User")

    # Both name the reader's active group when the link names none, and both ask for the same roles.
    asked = {}
    for name, ask in (
        ("page", lambda: gates.page({"scope": "group"})),
        ("api", lambda: gates.api(GROUP, {})),
    ):
        gates.world(
            settings={"enable_group_workspaces": True, "allow_group_workflows": True},
            known={"g1"}, memberships={"g1": "DocumentManager"}, active="g1",
        )
        ask()
        asked[name] = gates.directory.asked_roles
    assert asked["page"] == asked["api"] == {gates.page_roles}

    # And both refuse a reader whose role is not a member role.
    gates.world(
        settings={"enable_group_workspaces": True, "allow_group_workflows": True},
        known={"g1"}, memberships={"g1": "Guest"}, active="g1",
    )
    assert gates.page({"scope": "group"}) == gates.api(GROUP, {})[0] == 403


def test_the_event_stream_is_gated_exactly_as_the_snapshot_beside_it():
    for snapshot_path, stream_path in ((PERSONAL, f"{PERSONAL}/stream"), (GROUP, f"{GROUP}/stream")):
        snapshot, stream = one_route(snapshot_path), one_route(stream_path)
        # Same decorators after the route itself: the same login, role and settings gates.
        assert [ast.unparse(item) for item in snapshot.decorator_list[1:]] == [
            ast.unparse(item) for item in stream.decorator_list[1:]
        ], (snapshot_path, stream_path)
        assert ast.unparse(snapshot.decorator_list[0]) == ast.unparse(stream.decorator_list[0]).replace("/stream", "")

    # A group's stream resolves the group, with the same helper, before it opens anything.
    for path in (GROUP, f"{GROUP}/stream"):
        calls = [
            node.func.id for node in ast.walk(one_route(path))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "_resolve_group_workflow_request_group" in calls, path
        assert calls.index("_resolve_group_workflow_request_group") < calls.index(
            "_resolve_group_workflow_activity_context"
        ), path


def test_the_activity_routes_the_v2_page_calls_are_the_ones_the_server_serves():
    served = {
        path: {item.value for node in route_functions(path)
               for item in ast.walk(node.decorator_list[0]) if isinstance(item, ast.Constant) and item.value == "GET"}
        for path in (PERSONAL, f"{PERSONAL}/stream", GROUP, f"{GROUP}/stream")
    }
    assert all(methods == {"GET"} for methods in served.values()), served

    source = (ROOT / "application" / "v2_ui" / "src" / "lib" / "workflowActivity.ts").read_text(encoding="utf-8")
    assert "'/api/group/workflows/activity' : '/api/user/workflows/activity'" in source
    assert "`${base}/stream`" in source
    # The query it sends is the query the routes read, and no other name for it.
    for name in ("conversation_id", "workflow_id", "run_id"):
        assert f"request.args.get('{name}', '')" in ast.get_source_segment(
            API_ROUTES.read_text(encoding="utf-8"), one_route(PERSONAL),
        ), name
        assert f"params.set('{name}'" in source, name
    assert "params.set('group_id'" in source
    assert "request.args.get('group_id') or request.args.get('groupId')" in API_ROUTES.read_text(encoding="utf-8")


if __name__ == "__main__":
    tests = [
        test_version_is_at_least_the_implementing_release,
        test_personal_activity_is_gated_by_the_same_rules_on_the_page_and_in_the_api,
        test_group_activity_is_gated_by_the_same_rules_on_the_page_and_in_the_api,
        test_both_gates_ask_for_the_same_group_roles_and_the_active_group_fallback,
        test_the_event_stream_is_gated_exactly_as_the_snapshot_beside_it,
        test_the_activity_routes_the_v2_page_calls_are_the_ones_the_server_serves,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - the runner reports every failure
            failed += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(1 if failed else 0)
