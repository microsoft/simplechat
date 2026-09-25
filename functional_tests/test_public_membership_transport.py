# test_public_membership_transport.py
"""
Ensure immutable-target public membership routes cannot match a legacy public route.

Version: 0.261.179
Implemented in: 0.261.179

A mixed deployment must reject an unsupported workspace-bound public membership URL
rather than silently mutating whatever workspace the account currently has selected
through a legacy active-scoped classic route. The classic membership family lives
under ``/api/public_workspaces/<ws_id>/...`` (underscore, no ``/membership`` segment),
so no new immutable-target path may fall through to it.
"""

import re

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


PUBLIC_MEMBERSHIP_PREFIX = re.compile(r"^/api/public-workspaces/<[^>]+>/membership(?:/|$)")
MEMBERSHIP_REQUESTS = [
    ("GET", "/api/public-workspaces/requested-workspace/membership/members"),
    ("POST", "/api/public-workspaces/requested-workspace/membership/members"),
    ("PATCH", "/api/public-workspaces/requested-workspace/membership/members/member-id"),
    ("DELETE", "/api/public-workspaces/requested-workspace/membership/members/member-id"),
    ("GET", "/api/public-workspaces/requested-workspace/membership/requests"),
    ("POST", "/api/public-workspaces/requested-workspace/membership/requests/member-id/approve"),
    ("POST", "/api/public-workspaces/requested-workspace/membership/requests/member-id/reject"),
    ("PUT", "/api/public-workspaces/requested-workspace/membership/owner"),
]
MEMBERSHIP_TEMPLATES = {
    "/api/public-workspaces/<workspace_id>/membership/members",
    "/api/public-workspaces/<workspace_id>/membership/members/<user_id>",
    "/api/public-workspaces/<workspace_id>/membership/requests",
    "/api/public-workspaces/<workspace_id>/membership/requests/<user_id>/approve",
    "/api/public-workspaces/<workspace_id>/membership/requests/<user_id>/reject",
    "/api/public-workspaces/<workspace_id>/membership/owner",
}


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not PUBLIC_MEMBERSHIP_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    assert "/api/public_workspaces/<ws_id>/members" in paths
    assert "/api/public_workspaces/<ws_id>/transferOwnership" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", MEMBERSHIP_REQUESTS)
def test_new_membership_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises(NotFound):
        legacy_routes.match(path, method=method)


def test_new_membership_paths_are_registered_under_the_immutable_prefix():
    new_paths = {
        route.path for route in iter_route_functions()
        if PUBLIC_MEMBERSHIP_PREFIX.match(route.path)
    }
    assert MEMBERSHIP_TEMPLATES <= new_paths


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
