# test_data_management_search_write_fence_authorization.py
"""
Functional test for Data Management Search fence authorization safety.
Version: 0.250.071
Implemented in: 0.250.071

This test ensures an AI Search migration fence cannot make a document-unshare
request report success while stale Search chunks still grant access.
"""

import ast
import copy
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS_PATH = REPO_ROOT / "application" / "single_app" / "functions_documents.py"
DOCUMENTS_ROUTE_PATH = REPO_ROOT / "application" / "single_app" / "route_backend_documents.py"


def load_unshare_function():
    """Load only the unshare function from the production module with test dependencies."""
    source = DOCUMENTS_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(DOCUMENTS_PATH))
    function_node = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "unshare_document_from_user"
    )
    isolated_module = ast.Module(body=[function_node], type_ignores=[])
    ast.fix_missing_locations(isolated_module)

    class FakeNotFoundError(Exception):
        pass

    class FakeSearchWritesFrozenError(Exception):
        pass

    class FakeAclProjectionDeferredError(Exception):
        pass

    namespace = {
        "CosmosResourceNotFoundError": FakeNotFoundError,
        "DataManagementSearchWritesFrozenError": FakeSearchWritesFrozenError,
        "DocumentSearchAclProjectionDeferredError": FakeAclProjectionDeferredError,
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
    namespace["get_all_chunks"] = lambda *_args, **_kwargs: [{"id": "chunk-1"}]
    namespace["_upsert_document_and_sync_access_index"] = lambda *_args, **_kwargs: container.upserts.append(True)
    namespace["update_chunk_metadata"] = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        frozen_error("AI Search writes are temporarily frozen while a Data Management migration is running.")
    )

    with pytest.raises(deferred_error, match="temporarily frozen"):
        unshare_document("document-1", "owner-1", "viewer-1")
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
    projected_shared_ids = []
    namespace["cosmos_user_documents_container"] = container
    namespace["get_all_chunks"] = lambda *_args, **_kwargs: [{"id": "chunk-1"}]
    namespace["update_chunk_metadata"] = lambda **kwargs: projected_shared_ids.append(
        kwargs["shared_user_ids"]
    )

    def upsert(_container, document, **_kwargs):
        container.document = copy.deepcopy(document)
        return copy.deepcopy(document)

    namespace["_upsert_document_and_sync_access_index"] = upsert

    assert unshare_document("document-1", "owner-1", "viewer-1") is True
    assert projected_shared_ids == [[]]
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
    unshare_route = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "api_unshare_document"
    )
    deferred_handler = next(
        handler for handler in ast.walk(unshare_route)
        if isinstance(handler, ast.ExceptHandler) and
        isinstance(handler.type, ast.Name) and
        handler.type.id == "DocumentSearchAclProjectionDeferredError"
    )
    handler_source = ast.get_source_segment(source, deferred_handler) or ""

    assert "Retry-After" in handler_source
    assert "503" in handler_source
