# test_public_file_source_transport.py
"""
Ensure new explicit public-workspace file-source operations cannot match legacy routes.
Version: 0.261.179
Implemented in: 0.261.179

The immutable-target family names the public workspace in the path. A mixed
deployment must reject an unsupported ``/api/public-workspaces/<workspace_id>/file-sources``
URL rather than silently execute a legacy active-scoped file-sync route
(``/api/file-sync/public/<id>/...``) in the account's selected workspace.
"""

import re

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


PUBLIC_FILE_SOURCE_PREFIX = re.compile(r"^/api/public-workspaces/<[^>]+>/file-source")
OPERATION_REQUESTS = [
    ("GET", "/api/public-workspaces/requested-ws/file-sources"),
    ("POST", "/api/public-workspaces/requested-ws/file-sources"),
    ("GET", "/api/public-workspaces/requested-ws/file-sources/source-id"),
    ("PATCH", "/api/public-workspaces/requested-ws/file-sources/source-id"),
    ("DELETE", "/api/public-workspaces/requested-ws/file-sources/source-id"),
    ("POST", "/api/public-workspaces/requested-ws/file-sources/test-connection"),
    ("POST", "/api/public-workspaces/requested-ws/file-sources/source-id/test-connection"),
    ("POST", "/api/public-workspaces/requested-ws/file-sources/browse"),
    ("POST", "/api/public-workspaces/requested-ws/file-sources/source-id/browse"),
    ("POST", "/api/public-workspaces/requested-ws/file-sources/source-id/sync"),
    ("GET", "/api/public-workspaces/requested-ws/file-sources/source-id/runs"),
    ("POST", "/api/public-workspaces/requested-ws/file-sources/source-id/ignore-path"),
    ("GET", "/api/public-workspaces/requested-ws/file-source-options"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not PUBLIC_FILE_SOURCE_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    # The legacy active-scoped public file-sync routes must still be present so this
    # test proves the new URLs cannot fall through to them.
    assert "/api/file-sync/public/<public_workspace_id>/sources" in paths
    assert "/api/file-sync/public/<public_workspace_id>/sources/<source_id>" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}")
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", OPERATION_REQUESTS)
def test_new_public_file_source_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises(NotFound):
        legacy_routes.match(path, method=method)


def test_every_new_route_path_is_covered_by_a_transport_probe():
    """Each registered new URL has an explicit fall-through probe."""
    registered = {
        route.path
        for route in iter_route_functions()
        if PUBLIC_FILE_SOURCE_PREFIX.match(route.path)
    }
    probed = {
        re.sub(r"source-id", "<source_id>", re.sub(r"requested-ws", "<workspace_id>", path))
        for _, path in OPERATION_REQUESTS
    }
    assert registered == probed, registered.symmetric_difference(probed)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
