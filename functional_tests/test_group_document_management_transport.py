# test_group_document_management_transport.py
"""
Ensure new explicit-group operations cannot match legacy active-scoped routes.

Version: 0.261.130
Implemented in: 0.261.129
Collaboration paths added in: 0.261.130

A mixed deployment must reject an unsupported group-bound URL rather than
silently execute an old route in the user's active group.
"""

import re

import pytest
from werkzeug.exceptions import NotFound
from werkzeug.routing import Map, Rule

from route_tests.test_route_blueprint_policy_inventory import iter_route_functions


GROUP_OPERATION_PREFIX = re.compile(r"^/api/groups/<[^>]+>/documents(?:/|$)")
OPERATION_REQUESTS = [
    ("POST", "/api/groups/requested-group/documents/upload"),
    ("PATCH", "/api/groups/requested-group/documents/document-id"),
    ("DELETE", "/api/groups/requested-group/documents/document-id"),
    ("POST", "/api/groups/requested-group/documents/bulk-delete"),
    ("GET", "/api/groups/requested-group/documents/document-id/download"),
    ("POST", "/api/groups/requested-group/documents/download"),
    ("POST", "/api/groups/requested-group/documents/extract_metadata"),
    ("POST", "/api/groups/requested-group/documents/reprocess_extraction"),
    ("POST", "/api/groups/requested-group/documents/tags"),
    ("PATCH", "/api/groups/requested-group/documents/tags/finance"),
    ("DELETE", "/api/groups/requested-group/documents/tags/finance"),
    ("POST", "/api/groups/requested-group/documents/bulk-tag"),
    ("GET", "/api/groups/requested-group/documents/document-id/sharing"),
    ("GET", "/api/groups/requested-group/documents/document-id/sharing/targets"),
    ("POST", "/api/groups/requested-group/documents/document-id/share"),
    ("DELETE", "/api/groups/requested-group/documents/document-id/share/recipient"),
    ("POST", "/api/groups/requested-group/documents/document-id/approve-share"),
    ("DELETE", "/api/groups/requested-group/documents/document-id/received-share"),
    ("POST", "/api/groups/requested-group/documents/document-id/artifact/approve"),
    ("POST", "/api/groups/requested-group/documents/document-id/artifact/reject"),
    ("POST", "/api/groups/requested-group/documents/document-id/artifact/cancel"),
]


@pytest.fixture(scope="module")
def legacy_routes():
    routes = iter_route_functions()
    legacy = [
        route for route in routes
        if route.path.startswith("/api/") and not GROUP_OPERATION_PREFIX.match(route.path)
    ]
    paths = {route.path for route in legacy}
    assert "/api/group_documents/<document_id>" in paths
    assert "/api/groups/<group_id>" in paths
    return Map([
        Rule(route.path, endpoint=f"legacy-{index}")
        for index, route in enumerate(legacy)
    ]).bind("simplechat.test")


@pytest.mark.parametrize("method,path", OPERATION_REQUESTS)
def test_new_group_path_cannot_fall_through_to_a_legacy_route(legacy_routes, method, path):
    with pytest.raises(NotFound):
        legacy_routes.match(path, method=method)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
