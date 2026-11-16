# test_content_screening_persistence_lifecycle.py
"""
Behavioral tests for screening migration, restore, and scheduler integration.
Version: 0.261.106
Implemented in: 0.261.106

Uses the existing Data Management test loader and private in-memory blob/Cosmos
clients. No deployment, application startup, or live resource access is needed.
"""

import ast
import copy
import logging
import sys
import types
from contextlib import nullcontext
from pathlib import Path

import pytest
from azure.core.exceptions import ResourceNotFoundError


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from content_screening.contracts import Subject, document_is_available
from content_screening.repository import preserve_screening_on_transfer
from content_screening.storage import ScreeningStorage
from functions_migration_provenance import create_migration_provenance_context
from test_content_screening_persistence import FakeBlobService, FakeCosmos, FakeSdkError
from test_data_management_restore_workflow import FakeJobContainer, load_data_management_module


class TransferCosmos(FakeCosmos):
    def create_item(self, body, **kwargs):
        return super().create_item(body)

    def read_item(self, item, partition_key):
        try:
            return super().read_item(item, partition_key)
        except FakeSdkError as exc:
            if exc.status_code == 404:
                raise ResourceNotFoundError() from None
            raise

    def upsert_item(self, body):
        raise AssertionError("A screened document must not be restored with an unconditional upsert.")


@pytest.fixture
def data_management(monkeypatch):
    module = load_data_management_module(monkeypatch, FakeJobContainer())
    module.app_config.cosmos_content_screening_container_name = "content_screening"
    module.app_config.storage_account_content_screening_container_name = "content-screening"
    return module


def screened_document(state="cleared"):
    return {
        "id": "document", "user_id": "owner", "version": 2,
        "content_screening": {
            "state": state, "source_revision": "2", "scan_id": "scan",
            "content_fingerprint": "sha256", "generation": 3,
            "review_required": state == "pending_review",
            "canonical_ref": {"protected": "source-revision"},
        },
    }


def test_backup_inventory_carries_private_metadata_and_blobs_without_editor_exposure(data_management):
    module = data_management
    artifacts = [artifact for artifact in module.DATA_MANAGEMENT_COSMOS_ARTIFACTS if artifact["name"] == "content_screening"]
    assert len(artifacts) == 1
    assert artifacts[0]["partition_key_path"] == "/partition_key"
    assert "content-screening" in module._source_blob_container_names()
    assert all(entry[0] != "content_screening" for entry in module.DATA_MANAGEMENT_COSMOS_EDITOR_CONTAINER_DEFINITIONS)
    for target_type in module.DATA_MANAGEMENT_MIGRATION_TARGET_TYPE_ORDER:
        definitions = [item for item in module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS[target_type] if item.get("screening_scope_type")]
        assert len(definitions) == 1 and definitions[0]["documents"] is True


def test_scoped_migration_includes_baseline_without_other_scopes(data_management):
    module = data_management
    records = [
        {"id": "baseline", "scope_key": "global:global", "_ts": 1},
        {"id": "own", "scope_key": "personal:owner", "_ts": 1},
        {"id": "other", "scope_key": "personal:other", "_ts": 1},
        {"id": "group", "scope_key": "group:owner", "_ts": 1},
        {"id": "later", "scope_key": "personal:owner", "_ts": 100},
    ]
    calls = []

    def query_items(query, parameters, **kwargs):
        calls.append((query, parameters))
        values = {entry["name"]: entry["value"] for entry in parameters}
        for record in records:
            if record["_ts"] > values.get("@source_cutoff_epoch", 9999):
                continue
            if record["scope_key"] == values["@baseline_scope"] or record["scope_key"] in values.get("@screening_scopes", []):
                yield copy.deepcopy(record)

    module.app_config.cosmos_content_screening_container = types.SimpleNamespace(query_items=query_items)
    definition = next(item for item in module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS["users"] if item.get("screening_scope_type"))
    copied = list(module._iter_selected_cosmos_records(
        definition, {"mode": "selected", "ids": ["owner"], "include_documents": True}, source_cutoff_epoch=10,
    ))
    assert {item["id"] for item in copied} == {"baseline", "own"}
    assert "personal:owner" not in calls[0][0]
    assert all("_ts" not in record for record in copied)
    assert list(module._iter_selected_cosmos_records(
        definition, {"mode": "selected", "ids": ["owner"], "include_documents": False},
    )) == []


def test_migration_discovers_only_exact_revision_private_artifacts(data_management, monkeypatch):
    module = data_management
    service = FakeBlobService()
    storage = ScreeningStorage(service)
    subject = Subject("personal", "owner", "document", "2")
    storage.write_bytes(subject, "scan", "original", b"retained-original")
    storage.write_bytes(Subject("personal", "other", "document", "2"), "scan", "original", b"other-owner")
    storage.write_bytes(Subject("personal", "owner", "document", "1"), "scan", "original", b"other-revision")
    monkeypatch.setattr(module, "_get_source_blob_service_client", lambda: service)
    records = list(module._iter_screening_blob_migration_records(screened_document()))
    assert len(records) == 2
    assert all(record["blob_container"] == "content-screening" for record in records)
    assert all(subject.key in record["blob_path"] for record in records)
    assert all(record["content_screening"]["canonical_ref"] == {"protected": "source-revision"} for record in records)


@pytest.mark.parametrize("state", ["cleared", "approved_with_flags", "pending_review", "rejected"])
def test_transfers_never_clear_or_discard_a_screening_hold(state):
    source = screened_document(state)
    before = copy.deepcopy(source)
    for operation in ("restore", "migration"):
        result = preserve_screening_on_transfer(source, operation=operation)
        assert not document_is_available(result)
        assert result["content_screening"]["canonical_ref"] == source["content_screening"]["canonical_ref"]
        assert result["content_screening"]["dependency_validation_required"]
        if state in {"pending_review", "rejected"}:
            assert result["content_screening"]["state"] == state
    assert source == before


def test_transferred_jobs_require_explicit_resume():
    source = {"id": "job", "partition_key": "job", "kind": "job", "status": "queued", "lease": {"owner": "old-process"}}
    result = preserve_screening_on_transfer(source, operation="restore")
    assert result["status"] == "incomplete" and result["lease"] is None


def test_migration_write_preserves_source_marker_and_destination_provenance(data_management):
    module = data_management
    source = screened_document()
    original = copy.deepcopy(source)
    target = TransferCosmos(partition_field="id")
    provenance = create_migration_provenance_context(
        migration_id="11111111-1111-1111-1111-111111111111",
        migrated_at_utc="2026-09-08T12:00:00+00:00",
    )
    result = module._write_cosmos_migration_record(
        target, source, "/id", provenance, 1, source_hash=module._build_cosmos_source_hash(source), source_version="2",
    )
    assert result["copied"]
    copied = target.read_item("document", "document")
    assert copied["simplechatMigration"]["sourceVersion"] == "2"
    assert copied["content_screening"]["state"] == "incomplete"
    assert source == original


@pytest.mark.parametrize("declared_partition", ["/id", "/user_id"])
def test_restore_cannot_erase_a_newer_hold_with_an_old_legacy_backup(data_management, monkeypatch, declared_partition):
    module = data_management
    target = TransferCosmos([screened_document("pending_review")], partition_field="id")
    legacy = {"id": "document", "user_id": "owner", "version": 2, "description": "restored"}
    artifact = {
        "name": "personal_documents", "container_name_attr": "cosmos_user_documents_container_name",
        "partition_key_path": declared_partition, "category": "documents",
    }
    monkeypatch.setattr(module, "_get_target_cosmos_database", lambda _settings: None)
    monkeypatch.setattr(module, "_get_target_cosmos_container", lambda *_args: target)
    monkeypatch.setattr(module, "_group_restore_entries_by_resource", lambda *_args: {"cosmos:personal_documents": []})
    monkeypatch.setattr(module, "_get_restore_cosmos_artifact_by_resource", lambda _resource: artifact)
    monkeypatch.setattr(module, "_iter_restore_records_from_entries", lambda *_args: iter([copy.deepcopy(legacy)]))
    monkeypatch.setattr(module, "is_restore_resource_completed", lambda *_args: False)
    monkeypatch.setattr(module, "start_restore_resource", lambda *_args: None)
    monkeypatch.setattr(module, "_assert_restore_job_lease", lambda *_args: None)
    monkeypatch.setattr(module, "_complete_restore_resource_checkpoint", lambda *_args, **_kwargs: None)
    result = module._execute_restore_cosmos_resources(
        {"id": "restore"}, {}, {}, {
            "include_cosmos": True, "source_backup_id": "backup", "restore_policy": "overwrite_existing",
        }, None, None,
    )
    assert result[0]["status"] == "completed"
    restored = target.read_item("document", "document")
    assert restored["description"] == "restored"
    assert restored["content_screening"]["review_required"]
    assert not document_is_available(restored)
    assert len(target.replacements) == 1


def _load_scheduler_function(name, namespace):
    parsed = ast.parse((APP_ROOT / "background_tasks.py").read_text(encoding="utf-8"))
    function = next(node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == name)
    code = compile(ast.Module(body=[function], type_ignores=[]), "background_tasks.py", "exec")
    exec(code, namespace)
    return namespace[name]


@pytest.mark.parametrize("enabled,failed", [(False, False), (False, True), (True, False), (True, True)])
def test_scheduler_runs_under_a_lease_and_logs_only_safe_metadata(enabled, failed):
    class TickFinished(Exception):
        pass

    calls, logs = [], []

    def drain(**kwargs):
        calls.append(("drain", kwargs))
        if failed:
            raise RuntimeError("private-source-error-canary")
        return ["job"]

    def sleep(_seconds):
        raise TickFinished()

    namespace = {
        "get_settings": lambda: {"enable_content_screening": enabled},
        "acquire_distributed_task_lock": lambda name, **kwargs: calls.append(("acquire", name)) or {"id": "lock"},
        "release_distributed_task_lock": lambda lock: calls.append(("release", lock["id"])),
        "check_due_scan_jobs_once": drain,
        "log_event": lambda message, **kwargs: logs.append((message, kwargs)),
        "nullcontext": nullcontext, "logging": logging, "time": types.SimpleNamespace(sleep=sleep),
    }
    runner = _load_scheduler_function("run_content_screening_scheduler_loop", namespace)
    with pytest.raises(TickFinished):
        runner()
    assert [call[0] for call in calls] == ["acquire", "drain", "release"]
    assert "[CONTENT_SCREENING]" in logs[0][0]
    assert "private-source-error-canary" not in repr(logs)
