# test_excel_inventory_persistence.py
"""
Functional tests for private, complete, revision-bound Excel inventories.
Version: 0.261.407
Implemented in: 0.261.407

The real private artifact store runs against the existing Azure-like blob double.
Tests prove paging, full-text continuations, source binding, publication failures,
fresh authorization, screening capture, and revision-confined cleanup.
"""

import json
import ast
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import Workbook
from openpyxl.comments import Comment
from azure.core.exceptions import ResourceNotFoundError

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

import functions_excel_accessibility as excel  # noqa: E402
from content_screening.contracts import Subject  # noqa: E402
from content_screening.extraction import ExtractionCapture  # noqa: E402
from content_screening.storage import ScreeningStorage, revision_prefix  # noqa: E402
from functions_excel_inventory import (  # noqa: E402
    EXCEL_INVENTORY_FIELD,
    ExcelInventoryPersistenceError,
    clear_excel_inventory_cache,
    open_excel_inventory,
    open_stored_excel_inventory,
    persist_excel_inventory,
)
from test_content_screening_persistence import FakeBlobService, FakeSdkError  # noqa: E402
from test_excel_native_inspection_chat_evidence import review_workbook  # noqa: E402
from test_document_accessibility_report_action import _load_payload_namespace  # noqa: E402
from excel_workbook_reader import ExcelWorkbookReader, bounded_range  # noqa: E402
from openpyxl.utils.cell import get_column_letter  # noqa: E402


__all__ = ["review_workbook"]


@pytest.fixture(autouse=True)
def isolate_inventory_cache():
    clear_excel_inventory_cache()
    yield
    clear_excel_inventory_cache()


@pytest.fixture
def inventory_store():
    service = FakeBlobService()
    return ScreeningStorage(service), service


def test_complete_inventory_survives_parent_record_limits_and_restart(review_workbook, inventory_store, monkeypatch):
    store, service = inventory_store
    subject = Subject("personal", "owner", "workbook", "1")
    monkeypatch.setattr(excel, "EXCEL_MAX_RECORDS", 2)
    metadata, _, reference = persist_excel_inventory(review_workbook, ".xlsx", subject=subject, storage=store)
    assert metadata["comments"] == []
    assert len(json.dumps(metadata, ensure_ascii=True).encode()) <= 500000
    clear_excel_inventory_cache()
    checks = []
    reader = open_stored_excel_inventory(
        {"id": "workbook", "user_id": "owner", "version": 1, EXCEL_INVENTORY_FIELD: reference},
        storage=ScreeningStorage(service), authorize=lambda: checks.append("checked"),
    )
    records, cursor = [], None
    while True:
        page = reader.page("comments", cursor=cursor, page_size=2)
        records.extend(page["records"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(records) == 5
    assert any(record["text"] == "Set cap to 19500." for record in records)
    assert any(record["kind"] == "note" for record in records)
    assert len(checks) >= 8
    assert reader.metadata["comment_summary"]["compatibility_copies"] == 3


def test_long_unicode_text_continues_without_loss_or_oversized_responses(tmp_path, inventory_store):
    store, _ = inventory_store
    path = tmp_path / "long.xlsx"
    workbook = Workbook()
    workbook.active["A1"] = "Amount"
    workbook.active["A2"] = 0
    text = ('review "\\\\ quote ' + chr(0x03B1) + "\n") * 1800 + "TAIL"
    workbook.active["A2"].comment = Comment(text, "Reviewer")
    workbook.save(path)
    subject = Subject("personal", "owner", "long", "1")
    _, _, reference = persist_excel_inventory(path, ".xlsx", subject=subject, storage=store)
    reader = open_stored_excel_inventory(
        {"id": "long", "user_id": "owner", EXCEL_INVENTORY_FIELD: reference},
        storage=store, authorize=lambda: None,
    )
    fragments, cursor = [], None
    while True:
        page = reader.page("comments", cursor=cursor, max_bytes=4096)
        assert len(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode()) <= 4096
        assert page["records"][0]["record_fragment"] is True
        fragments.append(page["records"][0]["record_json_fragment"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    record = json.loads("".join(fragments))
    assert record["text"] == text and record["cell_value"] == 0


def test_source_and_section_bound_cursors_cannot_be_replayed(review_workbook, inventory_store):
    store, _ = inventory_store
    document = {"id": "workbook", "user_id": "owner", "version": 1}
    original = review_workbook.read_bytes()
    reader = open_excel_inventory(document, original, ".xlsx", storage=store, authorize=lambda: None)
    page = reader.page("comments", page_size=1)
    with pytest.raises(ValueError, match="different source or section"):
        reader.page("objects", cursor=page["next_cursor"])
    updated = open_excel_inventory(document, original + b"new-revision", ".xlsx", storage=store, authorize=lambda: None)
    with pytest.raises(ValueError, match="different source or section"):
        updated.page("comments", cursor=page["next_cursor"])


def test_every_page_rechecks_authorization(review_workbook, inventory_store):
    store, _ = inventory_store
    allowed = [True]

    def authorize():
        if not allowed[0]:
            raise PermissionError("Source access revoked.")

    reader = open_excel_inventory(
        {"id": "workbook", "user_id": "owner"},
        review_workbook.read_bytes(), ".xlsx", storage=store, authorize=authorize,
    )
    first = reader.page("comments", page_size=1)
    allowed[0] = False
    with pytest.raises(PermissionError, match="revoked"):
        reader.page("comments", cursor=first["next_cursor"])
    with pytest.raises(PermissionError, match="revoked"):
        _ = reader.metadata


def test_native_text_is_included_in_private_screening_capture(review_workbook, inventory_store):
    store, _ = inventory_store
    subject = Subject("personal", "owner", "workbook", "1")
    capture = ExtractionCapture(subject, "scan", "review.xlsx", artifact_storage=store)
    capture.mode = "table"
    persist_excel_inventory(review_workbook, ".xlsx", subject=subject, storage=store, capture=capture)
    capture.completed = True
    units = capture.finish({})
    text = "\n".join(unit.text for unit in units)
    assert "Set cap to 19500." in text and "Hold approval." in text
    assert all(unit.locator["kind"] == "excel_native" for unit in units)


def test_storage_failure_is_not_a_ready_inventory(review_workbook, inventory_store):
    store, service = inventory_store
    service.get_container_client("content-screening").fail_upload_name = "part-0000"
    with pytest.raises(ExcelInventoryPersistenceError) as error:
        persist_excel_inventory(
            review_workbook, ".xlsx", subject=Subject("personal", "owner", "workbook", "1"), storage=store,
        )
    assert "private-provider-error-canary" not in str(error.value)


def test_revision_cleanup_does_not_remove_another_workbook(review_workbook, inventory_store):
    store, service = inventory_store
    first, second = Subject("personal", "owner", "one", "1"), Subject("personal", "owner", "two", "1")
    persist_excel_inventory(review_workbook, ".xlsx", subject=first, storage=store)
    persist_excel_inventory(review_workbook, ".xlsx", subject=second, storage=store)
    container = service.get_container_client("content-screening")
    store.delete_revision(first)
    assert not any(name.startswith(revision_prefix(first)) for name in container.blobs)
    assert any(name.startswith(revision_prefix(second)) for name in container.blobs)


def test_real_report_backfills_existing_original_without_reupload(review_workbook, inventory_store):
    store, service = inventory_store
    document = {"id": "workbook", "user_id": "owner", "version": 1,
                "file_name": "review.xlsx", "source_file_available": True}
    namespace = _load_payload_namespace(document, chunks=[{
        "id": "workbook_2", "document_id": "workbook", "page_number": 2,
        "chunk_text": excel.EXCEL_EVIDENCE_MARKER + "\nNative comments",
    }])
    source_reads, checks = [], []

    def available_bytes(doc, **kwargs):
        source_reads.append(kwargs)
        return document, review_workbook.read_bytes()

    namespace.update({
        "CLIENTS": {"storage_account_office_docs_client": service},
        "ScreeningStorage": lambda **kwargs: store,
        "storage_account_content_screening_container_name": "content-screening",
        "screening_access": SimpleNamespace(read_available_document_bytes=available_bytes),
        "open_excel_inventory": open_excel_inventory,
        "open_stored_excel_inventory": open_stored_excel_inventory,
        "EXCEL_INVENTORY_SECTIONS": {"comments"},
        "ExcelWorkbookReader": ExcelWorkbookReader, "bounded_range": bounded_range,
        "get_column_letter": get_column_letter,
        "ResourceNotFoundError": ResourceNotFoundError,
        "assert_evidence_available": lambda *args, **kwargs: checks.append("fresh"),
        "_serialize_document": lambda doc, scope: {"id": doc["id"], "file_name": doc["file_name"]},
    })
    tree = ast.parse((APP / "functions_search_service.py").read_text(encoding="utf-8"))
    node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_read_excel_inspection")
    exec(compile(ast.Module(body=[node], type_ignores=[]), "functions_search_service.py", "exec"), namespace)
    payload = namespace["get_document_accessibility_payload"](
        "workbook", "owner", sheet_name="Budget", cell_range="B4:B4",
    )
    assert payload["schema_version"] == "2.0"
    assert payload["accessibility_metadata"]["comment_summary"]["thread_roots"] == 3
    assert any(item["text"] == "Set cap to 19500." for item in payload["excel_inspection"]["page"]["records"])
    assert payload["excel_inspection"]["cells"][0]["value"] == 15000
    assert payload["citation_chunk"]["id"] == "workbook_2"
    assert len(source_reads) == 1 and len(checks) >= 3
    assert "accessibility_metadata" not in document, "A read must not rewrite the original metadata/clearance."
