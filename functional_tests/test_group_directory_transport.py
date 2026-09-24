# test_group_directory_transport.py
"""
Functional test for how the native group directory routes resolve.
Version: 0.261.146
Implemented in: 0.261.146

``/api/groups/<group_id>/join-request`` shares no pattern with any other route, so
every method there must fail to match anything else: a server without the native
routes answers 404 or 405 rather than running some other handler.

``/api/groups/directory`` does share the shape of the classic
``/api/groups/<group_id>`` routes. The strict pin cannot hold there, so the actual
resolution is pinned per method, on a server with the native routes and on one
without them, from the routes' real methods:

- with them, GET and POST reach the directory routes (a static segment outranks a
  converter) and PATCH, PUT and DELETE still reach the classic group routes with
  the id ``directory``;
- without them, GET reaches the classic details route with that id and POST is 405.

The classic handlers then refuse the id ``directory`` for real (404, or their
``CreateGroups`` 403 first), and ``create_group`` can never mint it.
"""

import ast
import uuid
from pathlib import Path

import pytest
from flask import session
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule

from test_support.group_directory_harness import group_directory_environment


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
NEW_ROUTE_FILE = "route_backend_group_directory.py"
ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
EXPECTED_NEW_ROUTES = {
    ("GET", "/api/groups/directory", "api_group_directory_list"),
    ("POST", "/api/groups/directory", "api_group_directory_create"),
    ("POST", "/api/groups/<group_id>/join-request", "api_group_join_request_create"),
    ("DELETE", "/api/groups/<group_id>/join-request", "api_group_join_request_cancel"),
}


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def declared_routes():
    """``(file, function, path, methods)`` for every route decorator in the application."""
    routes = []
    for path in sorted(APP_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and _dotted(decorator.func).endswith(".route")):
                    continue
                if not (decorator.args and isinstance(decorator.args[0], ast.Constant)):
                    continue
                methods = ["GET"]
                for keyword in decorator.keywords:
                    if keyword.arg == "methods":
                        methods = [element.value for element in keyword.value.elts]
                routes.append((path.name, node.name, decorator.args[0].value, tuple(methods)))
    return routes


@pytest.fixture(scope="module")
def routes():
    return declared_routes()


def route_map(routes, *, include_new, methods=None):
    rules = [
        Rule(path, endpoint=f"{file_name}:{function_name}", methods=list(methods or route_methods))
        for file_name, function_name, path, route_methods in routes
        if path.startswith("/api/") and (include_new or file_name != NEW_ROUTE_FILE)
    ]
    return Map(rules).bind("simplechat.test")


def test_the_new_routes_are_declared(routes):
    declared = {
        (method, path, function_name)
        for file_name, function_name, path, methods in routes if file_name == NEW_ROUTE_FILE
        for method in methods
    }
    assert declared == EXPECTED_NEW_ROUTES


@pytest.mark.parametrize("method", ALL_METHODS)
def test_a_join_request_path_matches_no_other_route(routes, method):
    others = route_map(routes, include_new=False, methods=ALL_METHODS)
    paths = {path for file_name, _, path, _ in routes if file_name != NEW_ROUTE_FILE}
    # The classic request routes are present, so this proves separation rather than
    # passing on an empty map.
    assert {"/api/groups/<group_id>/requests", "/api/groups/<group_id>"} <= paths
    with pytest.raises((NotFound, MethodNotAllowed)):
        others.match("/api/groups/requested-group/join-request", method=method)


NEW_SERVER = {
    "GET": ("route_backend_group_directory.py:api_group_directory_list", {}),
    "POST": ("route_backend_group_directory.py:api_group_directory_create", {}),
    "PATCH": ("route_backend_groups.py:api_update_group", {"group_id": "directory"}),
    "PUT": ("route_backend_groups.py:api_update_group", {"group_id": "directory"}),
    "DELETE": ("route_backend_groups.py:api_delete_group", {"group_id": "directory"}),
}
LEGACY_SERVER = {
    "GET": ("route_backend_groups.py:api_get_group_details", {"group_id": "directory"}),
    "POST": MethodNotAllowed,
    "PATCH": ("route_backend_groups.py:api_update_group", {"group_id": "directory"}),
    "PUT": ("route_backend_groups.py:api_update_group", {"group_id": "directory"}),
    "DELETE": ("route_backend_groups.py:api_delete_group", {"group_id": "directory"}),
}


@pytest.mark.parametrize("server,include_new,expected", [
    ("new", True, NEW_SERVER),
    ("legacy", False, LEGACY_SERVER),
])
@pytest.mark.parametrize("method", ALL_METHODS)
def test_the_directory_path_resolves_per_method(routes, server, include_new, expected, method):
    mapped = route_map(routes, include_new=include_new)
    outcome = expected[method]
    if outcome is MethodNotAllowed:
        with pytest.raises(MethodNotAllowed):
            mapped.match("/api/groups/directory", method=method)
    else:
        assert mapped.match("/api/groups/directory", method=method) == outcome


@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


GROUP_NOT_FOUND = {"error": "Group not found"}
ROLE_REQUIRED = {"error": "Forbidden", "message": "Insufficient permissions (CreateGroups role required)"}


@pytest.mark.parametrize("method", ["PATCH", "PUT", "DELETE"])
@pytest.mark.parametrize("legacy", [False, True])
def test_the_classic_routes_refuse_the_directory_id(env, method, legacy):
    env.seed_group("g-1")
    env.as_user("owner-1")
    response = env.call(method, "/api/groups/directory", {"name": "Renamed"}, legacy=legacy)
    assert (response.status_code, response.get_json()) == (404, GROUP_NOT_FOUND)

    env.settings["require_member_of_create_group"] = True
    response = env.call(method, "/api/groups/directory", {"name": "Renamed"}, legacy=legacy)
    assert (response.status_code, response.get_json()) == (403, ROLE_REQUIRED)
    assert env.write_calls() == []


def test_an_older_server_answers_the_directory_safely(env):
    env.seed_group("g-1")
    env.as_user("member-1")
    listed = env.call("GET", "/api/groups/directory", legacy=True)
    assert (listed.status_code, listed.get_json()) == (404, GROUP_NOT_FOUND)
    created = env.call("POST", "/api/groups/directory", {"name": "Older"}, legacy=True)
    assert created.status_code == 405
    for method in ("POST", "DELETE"):
        assert env.call(method, "/api/groups/g-1/join-request", legacy=True).status_code == 404
    assert env.write_calls() == [] and env.groups.queries == []


def test_the_new_server_sends_get_and_post_to_the_directory(env):
    env.as_user("member-1")
    listed = env.directory()
    assert listed.status_code == 200 and "group_directory" in listed.get_json()
    created = env.create({"name": "Newer"})
    assert created.status_code == 201 and created.get_json()["group"]["name"] == "Newer"


def test_no_group_can_have_the_id_directory(env):
    minted = set()
    with env.app.test_request_context("/api/groups", method="POST"):
        session["user"] = {"oid": "owner-1", "roles": ["User"], "name": "Olive Owner", "preferred_username": "o@example.test"}
        for _ in range(5):
            minted.add(env.modules.group.create_group("Minted", "")["id"])
    assert len(minted) == 5
    for group_id in minted:
        assert uuid.UUID(group_id).version == 4 and str(uuid.UUID(group_id)) == group_id


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
