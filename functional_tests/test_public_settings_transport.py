# test_public_settings_transport.py
"""
Functional test for how the native public workspace settings routes resolve.
Version: 0.261.185
Implemented in: 0.261.185

The native paths under ``/api/public-workspaces/<workspace_id>/settings`` and
``/api/public-workspaces/<workspace_id>/insights`` share no pattern with any other route.
This test pins, from every route the application declares:

- that ``route_backend_public_settings`` declares exactly the native routes;
- that on a server without that file every native path, with every method, matches no
  other route (404 or 405), so an older server never runs some other handler for a
  newer client's request;
- the same through the real classic public workspace routes, which answer 404 for each
  native path.
"""

import ast
from pathlib import Path

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule

from test_support.public_settings_harness import public_settings_environment


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
NEW_ROUTE_FILE = "route_backend_public_settings.py"
ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
EXPECTED_NEW_ROUTES = {
    ("GET", "/api/public-workspaces/<workspace_id>/settings", "api_public_settings_read"),
    ("PATCH", "/api/public-workspaces/<workspace_id>/settings/profile", "api_public_settings_profile_update"),
    ("PUT", "/api/public-workspaces/<workspace_id>/settings/logo", "api_public_settings_logo_replace"),
    ("DELETE", "/api/public-workspaces/<workspace_id>/settings/logo", "api_public_settings_logo_remove"),
    ("PATCH", "/api/public-workspaces/<workspace_id>/settings/downloads", "api_public_settings_downloads_update"),
    ("PATCH", "/api/public-workspaces/<workspace_id>/settings/retention", "api_public_settings_retention_update"),
    ("GET", "/api/public-workspaces/<workspace_id>/insights/activity", "api_public_insights_activity"),
    ("GET", "/api/public-workspaces/<workspace_id>/insights/stats", "api_public_insights_stats"),
    ("GET", "/api/public-workspaces/<workspace_id>/insights/file-count", "api_public_insights_file_count"),
}
NEW_PATHS = sorted({path.replace("<workspace_id>", "public-1") for _, path, _ in EXPECTED_NEW_ROUTES})


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


def other_routes_map(routes):
    rules = [
        Rule(path, endpoint=f"{file_name}:{function_name}", methods=ALL_METHODS)
        for file_name, function_name, path, _ in routes
        if file_name != NEW_ROUTE_FILE
    ]
    return Map(rules).bind("simplechat.test")


def test_the_new_routes_are_declared(routes):
    declared = {
        (method, path, function_name)
        for file_name, function_name, path, methods in routes if file_name == NEW_ROUTE_FILE
        for method in methods
    }
    assert declared == EXPECTED_NEW_ROUTES


def test_the_new_routes_are_declared_nowhere_else(routes):
    new_patterns = {path for _, path, _ in EXPECTED_NEW_ROUTES}
    assert [route for route in routes if route[2] in new_patterns and route[0] != NEW_ROUTE_FILE] == []


@pytest.mark.parametrize("path", NEW_PATHS)
@pytest.mark.parametrize("method", ALL_METHODS)
def test_a_native_path_matches_no_other_route(routes, path, method):
    others = other_routes_map(routes)
    patterns = {pattern for file_name, _, pattern, _ in routes if file_name != NEW_ROUTE_FILE}
    # The classic public workspace routes and the native public document routes beside
    # them are present, so this proves separation rather than passing on an empty map.
    assert {"/api/public_workspaces/<ws_id>", "/api/public_workspaces/<ws_id>/logo",
            "/api/public_workspaces/<ws_id>/stats", "/api/public_workspaces/<ws_id>/activity",
            "/api/public_workspaces/<ws_id>/fileCount", "/api/public_workspaces/<ws_id>/download-settings",
            "/api/public-workspaces/<workspace_id>/documents"} <= patterns
    with pytest.raises((NotFound, MethodNotAllowed)):
        others.match(path, method=method)


@pytest.fixture(scope="module")
def module_env():
    with public_settings_environment() as env:
        yield env


@pytest.mark.parametrize("path", NEW_PATHS)
def test_an_older_server_answers_every_native_path_with_a_404(module_env, path):
    module_env.reset()
    module_env.seed_workspace("public-1", status="active")
    module_env.as_user("owner-1")
    for method in ALL_METHODS:
        response = module_env.call(method, path, legacy=True)
        assert response.status_code == 404, (method, path)
    assert module_env.write_calls() == []
    module_env.reset()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
