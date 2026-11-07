# test_group_endpoint_transport.py
"""
Ensure the explicit-group model endpoint operations cannot match a legacy route.

Version: 0.261.140
Implemented in: 0.261.140

A mixed deployment must reject an unsupported group-bound endpoint URL rather than
silently execute an old route against the user's active group. Every new
``/api/groups/<group_id>/model-endpoints`` and ``/api/groups/<group_id>/models/*``
URL/method pair must fail to match any other route pattern, including the legacy
``/api/group/model-endpoints`` and ``/api/group/models/*`` routes (note the
singular ``group``) and every other ``/api/groups/<group_id>/...`` route.
"""

import re

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


NEW_ROUTE = re.compile(r"^/api/groups/<[^>]+>/(?:model-endpoints|models/)")
OPERATION_REQUESTS = [
    ("GET", "/api/groups/requested-group/model-endpoints"),
    ("POST", "/api/groups/requested-group/model-endpoints"),
    ("GET", "/api/groups/requested-group/model-endpoints/endpoint-id"),
    ("PATCH", "/api/groups/requested-group/model-endpoints/endpoint-id"),
    ("DELETE", "/api/groups/requested-group/model-endpoints/endpoint-id"),
    ("POST", "/api/groups/requested-group/models/fetch"),
    ("POST", "/api/groups/requested-group/models/test-model"),
    ("POST", "/api/groups/requested-group/models/foundry/agents"),
]
EXPECTED_NEW_PATHS = {
    "/api/groups/<group_id>/model-endpoints",
    "/api/groups/<group_id>/model-endpoints/<endpoint_id>",
    "/api/groups/<group_id>/models/fetch",
    "/api/groups/<group_id>/models/test-model",
    "/api/groups/<group_id>/models/foundry/agents",
}


@pytest.fixture(scope="module")
def routes():
    return iter_route_functions()


@pytest.fixture(scope="module")
def legacy_routes(routes):
    legacy = [route for route in routes if route.path.startswith("/api/") and not NEW_ROUTE.match(route.path)]
    paths = {route.path for route in legacy}
    # The legacy active-scoped routes must still be present, so this test proves
    # separation rather than accidentally testing an empty map.
    for path in (
        "/api/group/model-endpoints",
        "/api/group/models/fetch",
        "/api/group/models/test-model",
        "/api/models/foundry/agents",
    ):
        assert path in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}", methods=["GET", "POST", "PATCH", "DELETE"])
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


def test_the_new_routes_are_declared(routes):
    declared = {route.path for route in routes if NEW_ROUTE.match(route.path)}
    assert declared == EXPECTED_NEW_PATHS


@pytest.mark.parametrize("method,path", OPERATION_REQUESTS)
def test_new_endpoint_path_cannot_fall_through_to_another_route(legacy_routes, method, path):
    with pytest.raises((NotFound, MethodNotAllowed)):
        legacy_routes.match(path, method=method)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
