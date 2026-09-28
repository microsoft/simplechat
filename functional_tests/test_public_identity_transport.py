# test_public_identity_transport.py
"""
Ensure new explicit public-workspace identity operations cannot match legacy routes.
Version: 0.261.182
Implemented in: 0.261.182

The immutable-target family names the public workspace in the path. A mixed
deployment must reject an unsupported ``/api/public-workspaces/<workspace_id>/identities``
URL rather than silently execute a legacy active-scoped identity route
(``/api/workspace-identities/public/<id>/...``) in the account's selected
workspace.
"""

import re

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


PUBLIC_IDENTITY_PREFIX = re.compile(r"^/api/public-workspaces/<[^>]+>/identities(?:/|$)")
OPERATION_REQUESTS = [
    ("GET", "/api/public-workspaces/requested-ws/identities"),
    ("POST", "/api/public-workspaces/requested-ws/identities"),
    ("GET", "/api/public-workspaces/requested-ws/identities/identity-id"),
    ("PATCH", "/api/public-workspaces/requested-ws/identities/identity-id"),
    ("DELETE", "/api/public-workspaces/requested-ws/identities/identity-id"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not PUBLIC_IDENTITY_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    # The legacy active-scoped public identity routes must still be present so this
    # test proves the new URLs cannot fall through to them.
    assert "/api/workspace-identities/public/<public_workspace_id>/identities" in paths
    assert "/api/workspace-identities/public/<public_workspace_id>/identities/<identity_id>" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}")
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", OPERATION_REQUESTS)
def test_new_public_identity_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises(NotFound):
        legacy_routes.match(path, method=method)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
