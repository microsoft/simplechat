# test_data_management_search_write_fence_authorization.py
"""
Functional test for Data Management Search fence authorization safety.
Version: 0.261.268
Implemented in: 0.250.071
Updated in: 0.261.268

This test ensures an AI Search migration fence cannot make a document-unshare
request report success while stale Search chunks still grant access, and that
share approvals and group sharing changes surface search projection failures
as safe, retryable errors instead of saving access the index does not enforce.
"""

import ast
import copy
import logging
from contextlib import nullcontext
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_PATH = REPO_ROOT / "application" / "single_app" / "functions_documents.py"
DOCUMENTS_ROUTE_PATH = REPO_ROOT / "application" / "single_app" / "route_backend_documents.py"
ACL_MESSAGE_CONSTANTS = {
    "DOCUMENT_SEARCH_ACL_DEFERRED_MESSAGE",
    "DOCUMENT_SEARCH_ACL_FAILED_MESSAGE",
}


def load_unshare_function():
    """Load the unshare function and its ACL projection helper with test dependencies."""
    source = DOCUMENTS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DOCUMENTS_PATH))
    loaded_nodes = [
        node for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name in {"unshare_document_from_user", "project_document_acl_to_chunks"}
        ) or (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in ACL_MESSAGE_CONSTANTS for target in node.targets)
        )
    ]
    isolated_module = ast.Module(body=loaded_nodes, type_ignores=[])
    ast.fix_missing_locations(isolated_module)

    class FakeNotFoundError(Exception):
        pass

    class FakeSearchWritesFrozenError(Exception):
        pass

    class FakeAclProjectionDeferredError(Exception):
        pass

    class FakeAclProjectionError(Exception):
        pass

    namespace = {
        "CosmosResourceNotFoundError": FakeNotFoundError,
        "DataManagementSearchWritesFrozenError": FakeSearchWritesFrozenError,
        "DocumentSearchAclProjectionDeferredError": FakeAclProjectionDeferredError,
        "DocumentSearchAclProjectionError": FakeAclProjectionError,
        "log_event": lambda *_args, **_kwargs: None,
        "logging": logging,
        "datetime": __import__("datetime").datetime,
        "timezone": __import__("datetime").timezone,
    }
    exec(compile(isolated_module, str(DOCUMENTS_PATH), "exec"), namespace)
    return (
        namespace["unshare_document_from_user"],
        namespace,
        FakeSearchWritesFrozenError,
        FakeAclProjectionDeferredError,
    )


def load_search_write_helpers():
    """Load only the indexing result checker and gated write helper with fake dependencies."""
    source = DOCUMENTS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DOCUMENTS_PATH))
    helper_names = {
        "_search_indexing_results_succeeded",
        "_execute_document_search_write",
    }
    helper_nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]
    isolated_module = ast.Module(body=helper_nodes, type_ignores=[])
    ast.fix_missing_locations(isolated_module)

    class FakeSlot:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    namespace = {
        "hold_data_management_search_write_slot": lambda *_args, **_kwargs: FakeSlot(),
        "cosmos_data_management_jobs_container": object(),
        # A non-group write holds no projection fence: `nullcontext(None)` stands in for it.
        "nullcontext": nullcontext,
    }
    exec(compile(isolated_module, str(DOCUMENTS_PATH), "exec"), namespace)
    return namespace["_execute_document_search_write"]


class FakeDocumentContainer:
    """Persist the personal document ACL record in-memory."""

    def __init__(self, document):
        self.document = copy.deepcopy(document)
        self.upserts = []

    def read_item(self, item, partition_key):
        assert item == partition_key == self.document["id"]
        return copy.deepcopy(self.document)


def _exception_names(handler):
    if isinstance(handler.type, ast.Name):
        return {handler.type.id}
    if isinstance(handler.type, ast.Tuple):
        return {element.id for element in handler.type.elts if isinstance(element, ast.Name)}
    return set()


def _route(tree, name):
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


def test_unshare_preserves_cosmos_acl_when_search_projection_is_frozen():
    """A fenced Search ACL update must not report a revocation or commit Cosmos first."""
    (
        unshare_document,
        namespace,
        frozen_error,
        deferred_error,
    ) = load_unshare_function()
    container = FakeDocumentContainer({
        "id": "document-1",
        "user_id": "owner-1",
        "shared_user_ids": ["viewer-1,approved"],
    })
    namespace["cosmos_user_documents_container"] = container
    namespace["_upsert_document_and_sync_access_index"] = lambda *_args, **_kwargs: container.upserts.append(True)
    namespace["project_fields_to_document_chunks"] = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        frozen_error("AI Search writes are temporarily frozen while a Data Management migration is running.")
    )

    with pytest.raises(deferred_error, match="temporarily frozen"):
        unshare_document("document-1", "owner-1", "viewer-1")
    assert container.document["shared_user_ids"] == ["viewer-1,approved"]
    assert container.upserts == []


def test_unshare_reports_a_failed_search_projection_without_saving():
    """Any other Search failure is raised with a fixed message, not hidden as a generic failure."""
    unshare_document, namespace, _frozen_error, _deferred_error = load_unshare_function()
    container = FakeDocumentContainer({
        "id": "document-1",
        "user_id": "owner-1",
        "shared_user_ids": ["viewer-1,approved"],
    })
    namespace["cosmos_user_documents_container"] = container
    namespace["_upsert_document_and_sync_access_index"] = lambda *_args, **_kwargs: container.upserts.append(True)
    namespace["project_fields_to_document_chunks"] = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("PRIVATE-PROVIDER detail")
    )

    with pytest.raises(namespace["DocumentSearchAclProjectionError"]) as failure:
        unshare_document("document-1", "owner-1", "viewer-1")
    assert "PRIVATE-PROVIDER" not in str(failure.value)
    assert container.document["shared_user_ids"] == ["viewer-1,approved"]
    assert container.upserts == []


def test_unshare_commits_cosmos_acl_after_search_projection_succeeds():
    """A completed Search projection permits the authoritative Cosmos ACL revocation."""
    unshare_document, namespace, _frozen_error, _deferred_error = load_unshare_function()
    container = FakeDocumentContainer({
        "id": "document-1",
        "user_id": "owner-1",
        "shared_user_ids": ["viewer-1,approved"],
    })
    projected_fields = []
    namespace["cosmos_user_documents_container"] = container

    def project_fields(document_id, field_values, user_id, **_kwargs):
        assert container.document["shared_user_ids"] == ["viewer-1,approved"], (
            "Search must be updated before the Cosmos ACL revocation is saved."
        )
        projected_fields.append((document_id, field_values, user_id))
        return 1

    namespace["project_fields_to_document_chunks"] = project_fields

    def upsert(_container, document, **_kwargs):
        container.document = copy.deepcopy(document)
        return copy.deepcopy(document)

    namespace["_upsert_document_and_sync_access_index"] = upsert

    assert unshare_document("document-1", "owner-1", "viewer-1") is True
    assert projected_fields == [("document-1", {"shared_user_ids": []}, "owner-1")]
    assert container.document["shared_user_ids"] == []


def test_search_write_rejects_unsuccessful_indexing_results():
    """Do not treat a non-throwing failed Search indexing result as a completed ACL projection."""
    execute_search_write = load_search_write_helpers()

    class FailedIndexClient:
        def upload_documents(self, documents, **_kwargs):
            assert documents == [{"id": "chunk-1"}]
            return [{"succeeded": False}]

    try:
        execute_search_write(
            FailedIndexClient(),
            "upload_documents",
            documents=[{"id": "chunk-1"}],
        )
    except RuntimeError as exc:
        assert "did not acknowledge" in str(exc)
    else:
        raise AssertionError("A failed AI Search indexing result was treated as successful.")


def test_unshare_route_returns_retryable_response_for_deferred_acl_projection():
    """Keep an active target migration fence visible to callers as a retryable unshare response."""
    source = DOCUMENTS_ROUTE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DOCUMENTS_ROUTE_PATH))
    unshare_route = _route(tree, "api_unshare_document")
    acl_handler = next(
        handler for handler in ast.walk(unshare_route)
        if isinstance(handler, ast.ExceptHandler)
        and {"DocumentSearchAclProjectionDeferredError", "DocumentSearchAclProjectionError"} <= _exception_names(handler)
    )
    handler_source = ast.get_source_segment(source, acl_handler) or ""
    assert "_document_search_acl_error_response(exc)" in handler_source

    helper = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_document_search_acl_error_response"
    )
    helper_source = ast.get_source_segment(source, helper) or ""
    assert "Retry-After" in helper_source and "describe_document_search_acl_error(error)" in helper_source

    documents_source = DOCUMENTS_PATH.read_text(encoding="utf-8")
    describe = ast.get_source_segment(
        documents_source,
        next(node for node in ast.parse(documents_source).body
             if isinstance(node, ast.FunctionDef) and node.name == "describe_document_search_acl_error"),
    ) or ""
    assert "DOCUMENT_SEARCH_ACL_DEFERRED_MESSAGE, 503, DOCUMENT_SEARCH_ACL_RETRY_AFTER_SECONDS" in describe


def test_share_approval_and_group_sharing_routes_surface_acl_projection_failures():
    """Share approvals and group sharing changes return safe, retryable errors instead of saving."""
    documents_source = DOCUMENTS_ROUTE_PATH.read_text(encoding="utf-8")
    documents_tree = ast.parse(documents_source, filename=str(DOCUMENTS_ROUTE_PATH))
    approve_route = _route(documents_tree, "api_approve_shared_document")
    handled_errors = set()
    for handler in ast.walk(approve_route):
        if isinstance(handler, ast.ExceptHandler):
            handled_errors |= _exception_names(handler)
    assert {
        "DocumentSearchAclProjectionDeferredError",
        "DocumentSearchAclProjectionError",
        "DocumentMutationPropagationError",
    } <= handled_errors
    approve_source = ast.get_source_segment(documents_source, approve_route) or ""
    assert approve_source.index("project_document_acl_to_chunks(") < approve_source.index("upsert_item(document_item)"), (
        "A share approval must reach Search before it is saved."
    )
    assert "str(e)" not in approve_source

    group_route_path = DOCUMENTS_ROUTE_PATH.with_name("route_backend_group_documents.py")
    group_source = group_route_path.read_text(encoding="utf-8")
    group_tree = ast.parse(group_source, filename=str(group_route_path))
    for route_name in (
        "api_approve_shared_group_document",
        "api_share_document_with_group",
        "api_unshare_document_with_group",
        "api_remove_self_from_group_document",
    ):
        route_source = ast.get_source_segment(group_source, _route(group_tree, route_name)) or ""
        assert "_group_share_search_acl_error_response(exc)" in route_source, route_name
        assert "str(e)" not in route_source, route_name

    helper = next(
        node for node in group_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_group_share_search_acl_error_response"
    )
    helper_source = ast.get_source_segment(group_source, helper) or ""
    assert "Retry-After" in helper_source and "describe_document_search_acl_error(error)" in helper_source
