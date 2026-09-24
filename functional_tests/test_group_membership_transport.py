# test_group_membership_transport.py
"""
Functional test for how the native group membership routes resolve.
Version: 0.261.151
Implemented in: 0.261.151

A mixed deployment must refuse an unsupported native membership URL rather than
run another handler. Every ``/api/groups/<group_id>/membership/...`` URL and method
pair must fail to match every other route in the application, including the
classic membership routes (``/members``, ``/members/<member_id>``, ``/requests``,
``/requests/<request_id>``, ``/transferOwnership``) and the native
``/join-request``.
"""

import ast
from pathlib import Path

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
NEW_ROUTE_FILE = "route_backend_group_membership.py"
ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
EXPECTED_NEW_ROUTES = {
    ("GET", "/api/groups/<group_id>/membership/members", "api_group_membership_list"),
    ("POST", "/api/groups/<group_id>/membership/members", "api_group_membership_add"),
    ("PATCH", "/api/groups/<group_id>/membership/members/<user_id>", "api_group_membership_role"),
    ("DELETE", "/api/groups/<group_id>/membership/members/<user_id>", "api_group_membership_remove"),
    ("GET", "/api/groups/<group_id>/membership/requests", "api_group_membership_requests"),
    ("POST", "/api/groups/<group_id>/membership/requests/<user_id>/approve", "api_group_membership_request_approve"),
    ("POST", "/api/groups/<group_id>/membership/requests/<user_id>/reject", "api_group_membership_request_reject"),
    ("PUT", "/api/groups/<group_id>/membership/owner", "api_group_membership_owner"),
}
CLASSIC_MEMBERSHIP_PATHS = {
    "/api/groups/<group_id>/members",
    "/api/groups/<group_id>/members/<member_id>",
    "/api/groups/<group_id>/requests",
    "/api/groups/<group_id>/requests/<request_id>",
    "/api/groups/<group_id>/transferOwnership",
    "/api/groups/<group_id>/join-request",
    "/api/groups/<group_id>",
}
REQUESTED_URLS = [
    "/api/groups/requested-group/membership/members",
    "/api/groups/requested-group/membership/members/requested-user",
    "/api/groups/requested-group/membership/requests",
    "/api/groups/requested-group/membership/requests/requested-user/approve",
    "/api/groups/requested-group/membership/requests/requested-user/reject",
    "/api/groups/requested-group/membership/owner",
]


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


@pytest.fixture(scope="module")
def other_routes(routes):
    others = [route for route in routes if route[0] != NEW_ROUTE_FILE and route[2].startswith("/api/")]
    paths = {path for _file, _function, path, _methods in others}
    # The classic membership routes are present, so this proves separation rather
    # than passing on an empty map.
    assert CLASSIC_MEMBERSHIP_PATHS <= paths
    return Map([
        Rule(path, endpoint=f"{file_name}:{function_name}", methods=ALL_METHODS)
        for file_name, function_name, path, _methods in others
    ]).bind("simplechat.test")


def test_the_new_routes_are_declared(routes):
    declared = {
        (method, path, function_name)
        for file_name, function_name, path, methods in routes if file_name == NEW_ROUTE_FILE
        for method in methods
    }
    assert declared == EXPECTED_NEW_ROUTES


@pytest.mark.parametrize("url", REQUESTED_URLS)
@pytest.mark.parametrize("method", ALL_METHODS)
def test_a_native_membership_url_matches_no_other_route(other_routes, url, method):
    with pytest.raises((NotFound, MethodNotAllowed)):
        other_routes.match(url, method=method)


def test_every_native_route_is_probed():
    probed = {rule_path for _method, rule_path, _function in EXPECTED_NEW_ROUTES}
    mapped = Map([Rule(path, endpoint=path, methods=ALL_METHODS) for path in probed]).bind("simplechat.test")
    matched = {mapped.match(url, method="GET")[0] for url in REQUESTED_URLS}
    assert matched == probed


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
