# test_group_workflow_hint_seam.py
"""
Functional test for the seam between the group workflow hint and the group workflow routes.
Version: 0.261.178
Implemented in: 0.261.178

The V2 group Workflows section offers Run and Cancel, and Create, Edit and Delete, from the group
context's `workflow_management` hint. The hint must be the routes' own rule, or the section offers a
member a control the server refuses or hides one it allows -- which is how V2 once dropped Run and
Cancel for ordinary members, whom the routes have always accepted.

Three layers are pinned:

- Behaviourally, for every role in every status, the real context route's hint equals the routes'
  real role checks -- `assert_group_role` with `GROUP_WORKFLOW_MEMBER_ROLES` for run and cancel, and
  with `get_group_workflow_management_roles(settings)` for create, edit and delete -- narrowed to an
  active group, as the V2 section always has been. The routes check no status themselves.
- Structurally, the run, cancel, run-cancel and resume-failed routes resolve the group with the member
  roles, and save and delete with the management roles; `functions_group_workflows.py` takes the
  member roles from the policy module rather than keeping its own copy.
- The builder reads the policy module's roles at call time: replacing them moves the hint.
"""

import ast
import importlib
from pathlib import Path

import pytest

from test_v2_group_workspace_context import environment as environment, read_as  # noqa: F401 - the real builder's harness

_PYTEST_FIXTURES = (environment,)

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
ROUTES_FILE = APP_ROOT / "route_backend_workflows.py"
ROLE_USERS = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "reader"}
STATUSES = ("active", "locked", "upload_disabled", "inactive", "archived")
MEMBER_ROUTES = {
    ("/api/group/workflows/<workflow_id>/run", "POST"),
    ("/api/group/workflows/<workflow_id>/cancel", "POST"),
    ("/api/group/workflows/<workflow_id>/runs/<run_id>/cancel", "POST"),
    ("/api/group/workflows/<workflow_id>/runs/<run_id>/resume-failed", "POST"),
}
MANAGER_ROUTES = {
    ("/api/group/workflows", "POST"),
    ("/api/group/workflows/<workflow_id>", "DELETE"),
}
MEMBER_RESOLVERS = {"_resolve_active_group_for_workflows", "_resolve_group_workflow_request_group"}
MANAGER_RESOLVER = "_resolve_active_group_for_workflow_management"


def policy():
    return importlib.import_module("functions_group_workflow_policy")


def allows(env, user_id, roles):
    """The routes' check: the real `assert_group_role` against the harness's group record."""
    import sys

    try:
        sys.modules["functions_group"].assert_group_role(user_id, "group-a", allowed_roles=roles)
    except (PermissionError, LookupError):
        return False
    return True


def workflow_hint(env, user_id, status):
    env.records["group-a"]["status"] = status
    response = read_as(env, user_id)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()["workflow_management"]


@pytest.mark.parametrize("status", STATUSES)
@pytest.mark.parametrize("role", list(ROLE_USERS))
def test_the_hint_is_the_routes_role_checks_in_an_active_group(environment, role, status):  # noqa: F811
    import sys

    user_id = ROLE_USERS[role]
    hint = workflow_hint(environment, user_id, status)
    manage_roles = sys.modules["functions_settings"].get_group_workflow_management_roles(environment.settings)
    expected = []
    if status == "active":
        if allows(environment, user_id, policy().GROUP_WORKFLOW_MEMBER_ROLES):
            expected += ["run", "cancel"]
        if allows(environment, user_id, manage_roles):
            expected += ["create", "edit", "delete"]
    assert hint == {"schema_version": 1, "operations": expected}


def test_the_comparison_is_not_vacuous(environment):  # noqa: F811
    """Every member may run, only the managers may manage, and nothing opens outside an active group."""
    by_role = {role: workflow_hint(environment, user_id, "active")["operations"] for role, user_id in ROLE_USERS.items()}
    assert by_role == {
        "Owner": ["run", "cancel", "create", "edit", "delete"],
        "Admin": ["run", "cancel", "create", "edit", "delete"],
        "DocumentManager": ["run", "cancel"],
        "User": ["run", "cancel"],
    }
    assert workflow_hint(environment, "owner", "locked")["operations"] == []


def test_workflows_switched_off_for_the_group_offer_nothing(environment):  # noqa: F811
    environment.settings.update({
        "require_group_assignment_for_group_workflows": True, "group_workflow_allowed_group_ids": [],
    })
    assert workflow_hint(environment, "owner", "active")["operations"] == []


def test_the_builder_reads_the_policy_modules_roles(environment, monkeypatch):  # noqa: F811
    monkeypatch.setattr(policy(), "GROUP_WORKFLOW_MEMBER_ROLES", ("Owner",))
    assert workflow_hint(environment, "reader", "active")["operations"] == []
    assert workflow_hint(environment, "owner", "active")["operations"][:2] == ["run", "cancel"]


def _route_functions():
    """Each group workflow route's handler, keyed by (path, method)."""
    tree = ast.parse(ROUTES_FILE.read_text(encoding="utf-8"))
    routes = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                    and decorator.func.attr == "route" and decorator.args
                    and isinstance(decorator.args[0], ast.Constant)):
                methods = next((keyword.value for keyword in decorator.keywords if keyword.arg == "methods"), None)
                for method in ast.literal_eval(methods) if methods is not None else ["GET"]:
                    routes[(decorator.args[0].value, method)] = node
    return routes


def _resolver_calls(function):
    return [
        node for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in MEMBER_RESOLVERS | {MANAGER_RESOLVER}
    ]


def test_the_member_and_manager_routes_resolve_the_roles_the_hint_names():
    routes = _route_functions()
    for key in MEMBER_ROUTES:
        calls = _resolver_calls(routes[key])
        assert calls and all(call.func.id in MEMBER_RESOLVERS for call in calls), key
        # No narrower roles are passed, so each resolves with its default: the member roles.
        assert all(not call.keywords and len(call.args) == 1 for call in calls), key
    for key in MANAGER_ROUTES:
        calls = _resolver_calls(routes[key])
        assert calls and all(call.func.id == MANAGER_RESOLVER for call in calls), key
    tree = ast.parse(ROUTES_FILE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in MEMBER_RESOLVERS:
            assert [ast.unparse(default) for default in node.args.defaults] == ["GROUP_WORKFLOW_MEMBER_ROLES"], node.name
        if isinstance(node, ast.FunctionDef) and node.name == MANAGER_RESOLVER:
            assert "get_group_workflow_management_roles(settings)" in ast.unparse(node)


def test_the_workflow_store_takes_the_member_roles_from_the_policy_module():
    tree = ast.parse((APP_ROOT / "functions_group_workflows.py").read_text(encoding="utf-8"))
    imports = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "functions_group_workflow_policy"
    ]
    assert any(alias.name == "GROUP_WORKFLOW_MEMBER_ROLES" for node in imports for alias in node.names)
    assert not [
        node for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "GROUP_WORKFLOW_MEMBER_ROLES" for target in node.targets)
    ], "functions_group_workflows.py keeps its own copy of the member roles"
