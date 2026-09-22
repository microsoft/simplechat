# test_public_document_read_transport.py
"""
Ensure immutable-target public read routes cannot match a legacy public route.

Version: 0.261.132
Implemented in: 0.261.132

A mixed deployment must reject an unsupported workspace-bound public read URL
rather than silently serving whatever workspace the account currently has
selected through a legacy active-scoped route.
"""

import re

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


PUBLIC_READ_PREFIX = re.compile(r"^/api/public-workspaces/<[^>]+>/documents(?:/|$)")
READ_REQUESTS = [
    ("GET", "/api/public-workspaces/requested-workspace/documents"),
    ("GET", "/api/public-workspaces/requested-workspace/documents/facets"),
    ("GET", "/api/public-workspaces/requested-workspace/documents/tags"),
    ("GET", "/api/public-workspaces/requested-workspace/documents/document-id"),
    ("GET", "/api/public-workspaces/requested-workspace/documents/document-id/versions"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not PUBLIC_READ_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    assert "/api/public_documents/<doc_id>" in paths
    assert "/api/public_workspace_documents" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}", methods=["GET", "POST", "PATCH", "DELETE"])
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", READ_REQUESTS)
def test_new_public_read_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises(NotFound):
        legacy_routes.match(path, method=method)


def test_new_public_read_paths_are_registered_under_the_immutable_prefix():
    routes = iter_route_functions()
    new_paths = {
        route.path for route in routes
        if PUBLIC_READ_PREFIX.match(route.path)
    }
    for _method, path in READ_REQUESTS:
        template = re.sub(r"requested-workspace", "<workspace_id>", path)
        template = re.sub(r"document-id", "<document_id>", template)
        assert template in new_paths


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
