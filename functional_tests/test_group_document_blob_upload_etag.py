# test_group_document_blob_upload_etag.py
"""
Functional test for group document blob uploads with Enhanced Citations.
Version: 0.261.217
Implemented in: 0.261.217

Runs the real upload_to_blob and _upsert_document_and_sync_access_index definitions against
an etag-tracking container. The "Uploading..." status update rewrites the document record, so
the etag-guarded final write must read the record after that update. Before the fix, every
group upload with Enhanced Citations failed with ScreeningConflictError. The guard must still
reject a change made by anyone else while the blob uploads.
"""

import ast
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
SCREENING_FIELD = "content_screening"


class ScreeningConflictError(Exception):
    pass


class NotFoundError(Exception):
    pass


class EtagContainer:
    """Cosmos-like container whose every write issues a new etag."""

    def __init__(self, *items):
        self.items = {}
        for item in items:
            self._store(dict(item))

    def _store(self, item):
        item["_etag"] = uuid.uuid4().hex
        self.items[item["id"]] = item
        return dict(item)

    def read_item(self, item, partition_key):
        if item not in self.items:
            raise NotFoundError(item)
        return dict(self.items[item])

    def replace_item(self, item, body, etag=None, match_condition=None):
        if etag is not None and self.items[item]["_etag"] != etag:
            raise ScreeningConflictError("The record changed since it was read.")
        return self._store(dict(body))

    def upsert_item(self, body):
        return self._store(dict(body))

    def create_item(self, body):
        return self._store(dict(body))


class BlobStore:
    def __init__(self, on_upload=None):
        self.uploads = {}
        self.on_upload = on_upload

    def get_blob_client(self, path):
        store = self

        class BlobClient:
            def upload_blob(self, data, overwrite, metadata):
                store.uploads[path] = (data.read(), metadata)
                if store.on_upload:
                    store.on_upload()

        return BlobClient()


def _blob_service_client_factory():
    return object()


def load_upload(container, blobs):
    namespace = {
        "logging": logging,
        "current_extraction": lambda document_id: None,
        "_get_documents_container": lambda group_id=None, public_workspace_id=None: container,
        "_get_blob_container_name": lambda **kwargs: "group-documents" if kwargs.get("group_id") else "user-documents",
        "build_current_blob_path": lambda filename, **kwargs: f"{kwargs.get('group_id') or kwargs.get('user_id')}/{filename}",
        "_get_document_family_items_from_document": lambda document, **kwargs: [document],
        "_document_revision_sort_key": lambda document: document.get("version", 0),
        "_archive_previous_document_blob": lambda *args, **kwargs: None,
        "_get_blob_service_client": _blob_service_client_factory,
        "_ensure_blob_container_ready": lambda client, name: blobs,
        "CURRENT_ALIAS_BLOB_PATH_MODE": "current_alias",
        "log_event": lambda *args, **kwargs: None,
        "CosmosResourceNotFoundError": NotFoundError,
        "assert_group_document_source_writable": lambda document: None,
        "ScreeningConflictError": ScreeningConflictError,
        "SCREENING_FIELD": SCREENING_FIELD,
        "MatchConditions": SimpleNamespace(IfNotModified="if-not-modified"),
        "sync_document_access_index_for_document_fail_open": lambda document, operation: {"success": True},
        "DocumentMutationPropagationError": RuntimeError,
    }
    names = {"upload_to_blob", "_upsert_document_and_sync_access_index"}
    tree = ast.parse((APP_ROOT / "functions_documents.py").read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in nodes} == names
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP_ROOT / "functions_documents.py"), "exec"), namespace)
    return namespace["upload_to_blob"]


def status_writer(container, document_id):
    """Mirror update_document: each status change rewrites the record."""

    def update_callback(**changes):
        current = container.read_item(item=document_id, partition_key=document_id)
        current.update(changes)
        container.upsert_item(current)

    return update_callback


@pytest.fixture
def source_file(tmp_path):
    path = tmp_path / "guide.md"
    path.write_text("# Guide\n\nExercise content.\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("scope", ["group", "personal"])
def test_upload_completes_after_its_own_status_update(source_file, scope):
    document = {"id": "document", "user_id": "owner", "version": 1, "file_name": "guide.md", "status": "Queued for processing"}
    group_id = "group-1" if scope == "group" else None
    if group_id:
        document["group_id"] = group_id
    container = EtagContainer(document)
    blobs = BlobStore()
    upload_to_blob = load_upload(container, blobs)

    blob_path = upload_to_blob(str(source_file), "owner", "document", "guide.md", status_writer(container, "document"), group_id=group_id)

    saved = container.items["document"]
    assert blob_path == f"{group_id or 'owner'}/guide.md"
    assert saved["blob_path"] == blob_path and saved["source_file_available"] is True
    assert saved["status"] == "Uploading guide.md to Blob Storage..."
    assert blobs.uploads[blob_path][0].startswith(b"# Guide")


def test_group_upload_still_rejects_a_concurrent_change(source_file):
    document = {"id": "document", "user_id": "owner", "group_id": "group-1", "version": 1, "file_name": "guide.md", "status": "Queued for processing"}
    container = EtagContainer(document)

    def foreign_write():
        current = container.read_item(item="document", partition_key="document")
        current["title"] = "Changed by another writer"
        container.upsert_item(current)

    upload_to_blob = load_upload(container, BlobStore(on_upload=foreign_write))
    with pytest.raises(RuntimeError) as raised:
        upload_to_blob(str(source_file), "owner", "document", "guide.md", status_writer(container, "document"), group_id="group-1")
    assert isinstance(raised.value.__cause__, ScreeningConflictError)
    assert "blob_path" not in container.items["document"]
