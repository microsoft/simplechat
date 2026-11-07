# test_group_prompt_transport.py
"""
Ensure new explicit-group prompt operations cannot match legacy active-scoped routes.

Version: 0.261.136
Implemented in: 0.261.136

A mixed deployment must reject an unsupported group-bound prompt URL rather than
silently execute an old route against the user's active group. Every new
/api/groups/<group_id>/prompts URL/method pair must fail to match any legacy
/api/group_prompts route pattern.
"""

import re

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


GROUP_PROMPT_PREFIX = re.compile(r"^/api/groups/<[^>]+>/prompts(?:/|$)")
OPERATION_REQUESTS = [
    ("GET", "/api/groups/requested-group/prompts"),
    ("POST", "/api/groups/requested-group/prompts"),
    ("GET", "/api/groups/requested-group/prompts/prompt-id"),
    ("PATCH", "/api/groups/requested-group/prompts/prompt-id"),
    ("DELETE", "/api/groups/requested-group/prompts/prompt-id"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not GROUP_PROMPT_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    # The legacy active-scoped prompt routes must still be present so that this
    # test proves separation rather than accidentally testing an empty map.
    assert "/api/group_prompts" in paths
    assert "/api/group_prompts/<prompt_id>" in paths
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
