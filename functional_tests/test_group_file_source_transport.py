# test_group_file_source_transport.py
"""
Ensure new explicit-group file-source operations cannot match legacy routes.
Version: 0.261.142
Implemented in: 0.261.142

The immutable-target family names the group in the path. A mixed deployment must
reject an unsupported ``/api/groups/<group_id>/file-sources`` URL rather than
silently execute a legacy active-scoped file-sync route in the account's selected
group.
"""

import re

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


GROUP_FILE_SOURCE_PREFIX = re.compile(r"^/api/groups/<[^>]+>/file-source")
OPERATION_REQUESTS = [
    ("GET", "/api/groups/requested-group/file-sources"),
    ("POST", "/api/groups/requested-group/file-sources"),
    ("GET", "/api/groups/requested-group/file-sources/source-id"),
    ("PATCH", "/api/groups/requested-group/file-sources/source-id"),
    ("DELETE", "/api/groups/requested-group/file-sources/source-id"),
    ("POST", "/api/groups/requested-group/file-sources/test-connection"),
    ("POST", "/api/groups/requested-group/file-sources/source-id/test-connection"),
    ("POST", "/api/groups/requested-group/file-sources/browse"),
    ("POST", "/api/groups/requested-group/file-sources/source-id/browse"),
    ("POST", "/api/groups/requested-group/file-sources/source-id/sync"),
    ("GET", "/api/groups/requested-group/file-sources/source-id/runs"),
    ("POST", "/api/groups/requested-group/file-sources/source-id/ignore-path"),
    ("GET", "/api/groups/requested-group/file-source-options"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not GROUP_FILE_SOURCE_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    # The legacy active-scoped group file-sync routes must still be present so this
    # test proves the new URLs cannot fall through to them.
    assert "/api/file-sync/group/sources" in paths
    assert "/api/file-sync/group/sources/<source_id>" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}")
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", OPERATION_REQUESTS)
def test_new_group_file_source_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises(NotFound):
        legacy_routes.match(path, method=method)


def test_every_new_route_path_is_covered_by_a_transport_probe():
    """Each registered new URL has an explicit fall-through probe."""
    registered = {
        route.path
        for route in iter_route_functions()
        if GROUP_FILE_SOURCE_PREFIX.match(route.path)
    }
    probed = {
        re.sub(r"source-id", "<source_id>", re.sub(r"requested-group", "<group_id>", path))
        for _, path in OPERATION_REQUESTS
    }
    assert registered == probed, registered.symmetric_difference(probed)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
