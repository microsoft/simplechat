# test_group_document_persisted_source_cleanup.py
"""
Functional test for persisted-source-only document cleanup.
Version: 0.261.130
Implemented in: 0.261.130

A never-processed publication shell records no current blob. Its cleanup must
delete only the paths that document actually persisted, never a fabricated
current-filename alias that can belong to a different revision.
"""

import ast
import sys
from pathlib import Path

import pytest


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"


def load_delete_from_blob_storage(blob_service, container, targets):
    """Execute the real helper with isolated storage and no application bootstrap."""
    names = {"delete_from_blob_storage"}
    tree = ast.parse((APP_DIR / "functions_documents.py").read_text(encoding="utf-8"))
    module = ast.Module(
        body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names],
        type_ignores=[],
    )
    scope = {
        "get_document_blob_delete_targets": lambda document_item, **kwargs: list(targets),
        "CLIENTS": {"storage_account_office_docs_client": blob_service},
        "SCREENING_FIELD": "content_screening",
        "ScreeningError": type("ScreeningError", (Exception,), {}),
        "ScreeningConflictError": type("ScreeningConflictError", (Exception,), {}),
        "_has_persisted_blob_reference": lambda item: bool(
            item.get("blob_path") or item.get("archived_blob_path")
        ),
        "_get_documents_container": lambda group_id, public_workspace_id: container,
        "MatchConditions": None,
        "log_event": lambda *args, **kwargs: None,
        "logging": __import__("logging"),
    }
    exec(compile(module, "functions_documents.py", "exec"), scope)
    return scope["delete_from_blob_storage"]


class BlobStore:
    def __init__(self, paths):
        self.paths = dict(paths)
        self.deleted = []

    def get_blob_client(self, container, blob):
        store = self

        class Client:
            def exists(self):
                return (container, blob) in store.paths

            def delete_blob(self, **kwargs):
                store.paths.pop((container, blob))
                store.deleted.append((container, blob))

        return Client()


ARCHIVED_ONLY_SHELL = {
    "id": "pending-shell",
    "group_id": "group-a",
    "file_name": "shared-report.pdf",
    "archived_blob_path": "group-a/family/pending-shell/shared-report.pdf",
}


def test_archive_only_cleanup_never_invents_an_unrecorded_current_alias():
    other_revision_alias = ("group-documents", "group-a/shared-report.pdf")
    archived = ("group-documents", ARCHIVED_ONLY_SHELL["archived_blob_path"])
    blobs = BlobStore({other_revision_alias: b"another revision", archived: b"pending shell"})
    delete_from_blob_storage = load_delete_from_blob_storage(
        blobs, container=None, targets=[other_revision_alias, archived],
    )

    delete_from_blob_storage(
        dict(ARCHIVED_ONLY_SHELL), group_id="group-a", persisted_sources_only=True,
    )

    assert blobs.deleted == [archived]
    assert other_revision_alias in blobs.paths


def test_cleanup_without_any_persisted_reference_deletes_nothing():
    fabricated = ("group-documents", "group-a/shared-report.pdf")
    blobs = BlobStore({fabricated: b"another revision"})
    delete_from_blob_storage = load_delete_from_blob_storage(
        blobs, container=None, targets=[fabricated],
    )

    delete_from_blob_storage(
        {"id": "pending-shell", "group_id": "group-a", "file_name": "shared-report.pdf"},
        group_id="group-a", persisted_sources_only=True,
    )

    assert blobs.deleted == []
    assert fabricated in blobs.paths


def test_ordinary_cleanup_still_removes_every_resolved_target():
    current = ("group-documents", "group-a/shared-report.pdf")
    archived = ("group-documents", ARCHIVED_ONLY_SHELL["archived_blob_path"])
    blobs = BlobStore({current: b"current", archived: b"archived"})
    delete_from_blob_storage = load_delete_from_blob_storage(
        blobs, container=None, targets=[current, archived],
    )

    delete_from_blob_storage(
        {**ARCHIVED_ONLY_SHELL, "blob_path": "group-a/shared-report.pdf"}, group_id="group-a",
    )

    assert sorted(blobs.deleted) == sorted([current, archived])
    assert not blobs.paths


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
