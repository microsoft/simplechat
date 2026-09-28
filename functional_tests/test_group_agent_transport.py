# test_group_agent_transport.py
"""
Ensure new explicit-group agent operations cannot match legacy active-scoped routes.

Version: 0.261.138
Implemented in: 0.261.138

A mixed deployment must reject an unsupported group-bound agent URL rather than
silently execute an old route against the user's active group. Every new
/api/groups/<group_id>/agents URL/method pair must fail to match any legacy
/api/group/agents route pattern (note the legacy singular ``group`` prefix).
"""

import re

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


GROUP_AGENT_PREFIX = re.compile(r"^/api/groups/<[^>]+>/agent(?:s|-options|-knowledge)(?:/|$)")
OPERATION_REQUESTS = [
    ("GET", "/api/groups/requested-group/agents"),
    ("POST", "/api/groups/requested-group/agents"),
    ("GET", "/api/groups/requested-group/agent-options"),
    ("GET", "/api/groups/requested-group/agent-knowledge"),
    ("GET", "/api/groups/requested-group/agents/agent-id"),
    ("PATCH", "/api/groups/requested-group/agents/agent-id"),
    ("DELETE", "/api/groups/requested-group/agents/agent-id"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not GROUP_AGENT_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    # The legacy active-scoped agent routes must still be present so that this
    # test proves separation rather than accidentally testing an empty map.
    assert "/api/group/agents" in paths
    assert "/api/group/agents/<agent_id>" in paths
    assert "/api/group/agent/settings" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}", methods=["GET", "POST", "PATCH", "DELETE"])
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", OPERATION_REQUESTS)
def test_new_agent_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises((NotFound, MethodNotAllowed)):
        legacy_routes.match(path, method=method)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
