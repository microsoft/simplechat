# test_public_document_read_transport.py
"""
Ensure immutable-target public document routes cannot match a legacy public route.

Version: 0.261.134
Implemented in: 0.261.132

A mixed deployment must reject an unsupported workspace-bound public URL rather
than silently serving (M3A reads) or mutating (M3B writes) whatever workspace the
account currently has selected through a legacy active-scoped route.
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
MANAGEMENT_REQUESTS = [
    ("POST", "/api/public-workspaces/requested-workspace/documents/upload"),
    ("PATCH", "/api/public-workspaces/requested-workspace/documents/document-id"),
    ("DELETE", "/api/public-workspaces/requested-workspace/documents/document-id"),
    ("POST", "/api/public-workspaces/requested-workspace/documents/bulk-delete"),
    ("GET", "/api/public-workspaces/requested-workspace/documents/document-id/download"),
    ("POST", "/api/public-workspaces/requested-workspace/documents/download"),
    ("POST", "/api/public-workspaces/requested-workspace/documents/extract_metadata"),
    ("POST", "/api/public-workspaces/requested-workspace/documents/reprocess_extraction"),
    ("POST", "/api/public-workspaces/requested-workspace/documents/tags"),
    ("PATCH", "/api/public-workspaces/requested-workspace/documents/tags/tag-name"),
    ("DELETE", "/api/public-workspaces/requested-workspace/documents/tags/tag-name"),
    ("POST", "/api/public-workspaces/requested-workspace/documents/bulk-tag"),
]
ALL_REQUESTS = READ_REQUESTS + MANAGEMENT_REQUESTS
COLLABORATION_REQUESTS = [
    ("GET", "/api/public-workspaces/requested-workspace/documents/document-id/publication"),
    ("POST", "/api/public-workspaces/requested-workspace/documents/document-id/artifact/approve"),
    ("POST", "/api/public-workspaces/requested-workspace/documents/document-id/artifact/reject"),
    ("POST", "/api/public-workspaces/requested-workspace/documents/document-id/artifact/cancel"),
]
ALL_REQUESTS = ALL_REQUESTS + COLLABORATION_REQUESTS
MANAGEMENT_TEMPLATES = {
    "/api/public-workspaces/<workspace_id>/documents/upload",
    "/api/public-workspaces/<workspace_id>/documents/<document_id>",
    "/api/public-workspaces/<workspace_id>/documents/bulk-delete",
    "/api/public-workspaces/<workspace_id>/documents/<document_id>/download",
    "/api/public-workspaces/<workspace_id>/documents/download",
    "/api/public-workspaces/<workspace_id>/documents/extract_metadata",
    "/api/public-workspaces/<workspace_id>/documents/reprocess_extraction",
    "/api/public-workspaces/<workspace_id>/documents/tags",
    "/api/public-workspaces/<workspace_id>/documents/tags/<path:tag_name>",
    "/api/public-workspaces/<workspace_id>/documents/bulk-tag",
}
COLLABORATION_TEMPLATES = {
    "/api/public-workspaces/<workspace_id>/documents/<document_id>/publication",
    "/api/public-workspaces/<workspace_id>/documents/<document_id>/artifact/approve",
    "/api/public-workspaces/<workspace_id>/documents/<document_id>/artifact/reject",
    "/api/public-workspaces/<workspace_id>/documents/<document_id>/artifact/cancel",
}


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


@pytest.mark.parametrize("method,path", ALL_REQUESTS)
def test_new_public_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
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


def test_new_public_management_paths_are_registered_under_the_immutable_prefix():
    new_paths = {
        route.path for route in iter_route_functions()
        if PUBLIC_READ_PREFIX.match(route.path)
    }
    assert MANAGEMENT_TEMPLATES <= new_paths


def test_new_public_collaboration_paths_are_registered_under_the_immutable_prefix():
    new_paths = {
        route.path for route in iter_route_functions()
        if PUBLIC_READ_PREFIX.match(route.path)
    }
    assert COLLABORATION_TEMPLATES <= new_paths


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
