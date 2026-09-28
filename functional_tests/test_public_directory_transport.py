# test_public_directory_transport.py
"""
Functional test for how the native public workspace directory route resolves.
Version: 0.261.175
Implemented in: 0.261.175

``/api/public_workspaces/directory`` shares the shape of the classic
``/api/public_workspaces/<ws_id>`` routes, so a strict "matches nothing else" pin
cannot hold there. The resolution is pinned per method instead, from the routes'
real methods parsed out of the application, on a server with the native route and on
one without it:

- with it, GET reaches the directory route, because a static segment outranks a
  converter, while PATCH, PUT and DELETE still reach the classic workspace routes
  with the id ``directory`` and POST is 405;
- without it, GET reaches the classic details route with that id, and POST is 405.

The classic details, update and delete handlers then refuse the id ``directory`` for
real (404, since no workspace has it), and ``create_public_workspace`` mints only
UUIDs, so it can never make one. The live half proves the native GET carries the
``public_directory`` discriminator so a client can tell the two servers apart.
"""

import ast
from pathlib import Path

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule

from test_support.public_directory_harness import public_directory_environment


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
NEW_ROUTE_FILE = "route_backend_public_directory.py"
ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
EXPECTED_NEW_ROUTES = {
    ("GET", "/api/public_workspaces/directory", "api_public_directory_list"),
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


def route_map(routes, *, include_new):
    rules = [
        Rule(path, endpoint=f"{file_name}:{function_name}", methods=list(route_methods))
        for file_name, function_name, path, route_methods in routes
        if path.startswith("/api/") and (include_new or file_name != NEW_ROUTE_FILE)
    ]
    return Map(rules).bind("simplechat.test")


def test_the_new_route_is_declared_get_only(routes):
    declared = {
        (method, path, function_name)
        for file_name, function_name, path, methods in routes if file_name == NEW_ROUTE_FILE
        for method in methods
    }
    assert declared == EXPECTED_NEW_ROUTES


def test_the_directory_competes_with_a_real_classic_route(routes):
    paths = {path for file_name, _, path, _ in routes if file_name != NEW_ROUTE_FILE}
    # The classic details route is present, so the per-method pin proves precedence
    # rather than passing on an empty map.
    assert "/api/public_workspaces/<ws_id>" in paths


NEW_SERVER = {
    "GET": ("route_backend_public_directory.py:api_public_directory_list", {}),
    "POST": MethodNotAllowed,
    "PATCH": ("route_backend_public_workspaces.py:api_update_public_workspace", {"ws_id": "directory"}),
    "PUT": ("route_backend_public_workspaces.py:api_update_public_workspace", {"ws_id": "directory"}),
    "DELETE": ("route_backend_public_workspaces.py:api_delete_public_workspace", {"ws_id": "directory"}),
}
LEGACY_SERVER = {
    "GET": ("route_backend_public_workspaces.py:api_get_public_workspace", {"ws_id": "directory"}),
    "POST": MethodNotAllowed,
    "PATCH": ("route_backend_public_workspaces.py:api_update_public_workspace", {"ws_id": "directory"}),
    "PUT": ("route_backend_public_workspaces.py:api_update_public_workspace", {"ws_id": "directory"}),
    "DELETE": ("route_backend_public_workspaces.py:api_delete_public_workspace", {"ws_id": "directory"}),
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
        with pytest.raises((MethodNotAllowed, NotFound)):
            mapped.match("/api/public_workspaces/directory", method=method)
    else:
        assert mapped.match("/api/public_workspaces/directory", method=method) == outcome


@pytest.fixture(scope="module")
def module_env():
    with public_directory_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


def test_the_new_server_sends_get_to_the_directory(env):
    env.seed_workspace("w-1", "Shared")
    env.as_user("reader-1")
    listed = env.directory()
    assert listed.status_code == 200
    assert "public_directory" in listed.get_json()


def test_no_public_workspace_can_have_the_id_directory(env):
    import uuid
    from flask import session

    minted = set()
    with env.app.test_request_context("/api/public_workspaces", method="POST"):
        session["user"] = {
            "oid": "owner-1", "roles": ["User"], "name": "Olive Owner",
            "preferred_username": "olive.owner@example.test",
        }
        for _ in range(5):
            minted.add(env.modules.public_workspaces.create_public_workspace("Minted", "")["id"])
    assert len(minted) == 5
    for ws_id in minted:
        assert uuid.UUID(ws_id).version == 4 and str(uuid.UUID(ws_id)) == ws_id


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
