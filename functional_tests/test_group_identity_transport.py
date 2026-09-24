# test_group_identity_transport.py
"""
Ensure new explicit-group identity operations cannot match legacy routes.
Version: 0.261.139
Implemented in: 0.261.139

The immutable-target family names the group in the path. A mixed deployment must
reject an unsupported ``/api/groups/<group_id>/identities`` URL rather than
silently execute a legacy active-scoped identity route in the account's selected
group.
"""

import re

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


GROUP_IDENTITY_PREFIX = re.compile(r"^/api/groups/<[^>]+>/identities(?:/|$)")
OPERATION_REQUESTS = [
    ("GET", "/api/groups/requested-group/identities"),
    ("POST", "/api/groups/requested-group/identities"),
    ("GET", "/api/groups/requested-group/identities/identity-id"),
    ("PATCH", "/api/groups/requested-group/identities/identity-id"),
    ("DELETE", "/api/groups/requested-group/identities/identity-id"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not GROUP_IDENTITY_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    # The legacy active-scoped group identity routes must still be present so this
    # test proves the new URLs cannot fall through to them.
    assert "/api/workspace-identities/group/identities" in paths
    assert "/api/workspace-identities/group/identities/<identity_id>" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}")
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", OPERATION_REQUESTS)
def test_new_group_identity_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises(NotFound):
        legacy_routes.match(path, method=method)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
