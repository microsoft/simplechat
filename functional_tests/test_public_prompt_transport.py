# test_public_prompt_transport.py
"""
Ensure new explicit-workspace public prompt operations cannot match legacy routes.

Version: 0.261.178
Implemented in: 0.261.178

A mixed deployment must reject an unsupported workspace-bound prompt URL rather
than silently execute an old route against the user's active public workspace.
Every new /api/public-workspaces/<workspace_id>/prompts URL/method pair must fail
to match any legacy /api/public_prompts route pattern.
"""

import re

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


PUBLIC_PROMPT_PREFIX = re.compile(r"^/api/public-workspaces/<[^>]+>/prompts(?:/|$)")
OPERATION_REQUESTS = [
    ("GET", "/api/public-workspaces/requested-workspace/prompts"),
    ("POST", "/api/public-workspaces/requested-workspace/prompts"),
    ("GET", "/api/public-workspaces/requested-workspace/prompts/prompt-id"),
    ("PATCH", "/api/public-workspaces/requested-workspace/prompts/prompt-id"),
    ("DELETE", "/api/public-workspaces/requested-workspace/prompts/prompt-id"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not PUBLIC_PROMPT_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    # The legacy active-scoped prompt routes must still be present so that this
    # test proves separation rather than accidentally testing an empty map.
    assert "/api/public_prompts" in paths
    assert "/api/public_prompts/<prompt_id>" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}")
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", OPERATION_REQUESTS)
def test_new_prompt_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises(NotFound):
        legacy_routes.match(path, method=method)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
