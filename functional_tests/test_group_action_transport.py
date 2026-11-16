# test_group_action_transport.py
"""
Ensure new explicit-group action operations cannot match legacy active-scoped routes.

Version: 0.261.137
Implemented in: 0.261.137

A mixed deployment must reject an unsupported group-bound action URL rather than
silently execute an old route against the user's active group. Every new
/api/groups/<group_id>/actions URL/method pair must fail to match any legacy
/api/group/plugins route pattern (note the legacy singular ``group`` prefix).
"""

import re

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


GROUP_ACTION_PREFIX = re.compile(r"^/api/groups/<[^>]+>/action(?:s|-options)(?:/|$)")
OPERATION_REQUESTS = [
    ("GET", "/api/groups/requested-group/actions"),
    ("POST", "/api/groups/requested-group/actions"),
    ("GET", "/api/groups/requested-group/actions/types"),
    ("GET", "/api/groups/requested-group/action-options"),
    ("GET", "/api/groups/requested-group/actions/action-id"),
    ("PATCH", "/api/groups/requested-group/actions/action-id"),
    ("DELETE", "/api/groups/requested-group/actions/action-id"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not GROUP_ACTION_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    # The legacy active-scoped plugin routes must still be present so that this
    # test proves separation rather than accidentally testing an empty map.
    assert "/api/group/plugins" in paths
    assert "/api/group/plugins/<action_id>" in paths
    assert "/api/group/plugins/types" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}", methods=["GET", "POST", "PATCH", "DELETE"])
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", OPERATION_REQUESTS)
def test_new_action_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises((NotFound, MethodNotAllowed)):
        legacy_routes.match(path, method=method)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
