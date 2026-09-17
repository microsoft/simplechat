# test_content_screening_backup.py
"""
Functional tests for unused content-screening storage in source-blob backups.
Version: 0.261.106
Implemented in: 0.261.106

Runs the production backup resource/export and restore-manifest preflight with
the existing in-memory backup clients. No Azure resources or files are created.
"""

import copy
import json
import sys
import types

import pytest

from test_data_management_blob_backup_transfers import (
    FakeBlobError,
    FakeSourceBlobClient,
    FakeSourceContainer,
    FakeTargetContainer,
    build_job,
    build_plan,
    load_module,
)


DOCUMENT_CONTAINERS = (
    "cosmos_user_documents_container",
    "cosmos_group_documents_container",
    "cosmos_public_documents_container",
)
SCREENING_CONTAINER = "cosmos_content_screening_container"
REFERENCE_FIELDS = ("source_ref", "units_ref", "result_ref", "canonical_ref", "evidence_ref")


class PresenceContainer:
    """Evaluate the bounded dependency-presence queries without exposing rows."""

    def __init__(self, records=None, error=None):
        self.records = copy.deepcopy(records or [])
        self.error = error
        self.queries = []

    def query_items(self, query, parameters, **kwargs):
        self.queries.append((query, copy.deepcopy(parameters), kwargs))
        assert query.startswith("SELECT TOP 1 c.id FROM c WHERE ")
        assert kwargs == {"enable_cross_partition_query": True, "max_item_count": 1}
        if self.error:
            raise self.error
        if "IS_DEFINED(c.content_screening)" in query:
            matches = [record for record in self.records if "content_screening" in record]
        else:
            values = {entry["name"]: entry["value"] for entry in parameters}
            assert values == {"@scan_kind": "scan", "@deleted_state": "deleted"}
            assert "NOT IS_STRING(c.state)" in query and "c.state != @deleted_state" in query
            assert all(f"IS_DEFINED(c.{field}) AND NOT IS_NULL(c.{field})" in query for field in REFERENCE_FIELDS)
            matches = [
                record for record in self.records
                if record.get("kind") == "scan" and record.get("state") != "deleted"
                or any(record.get(field) is not None for field in REFERENCE_FIELDS)
            ]
        return iter([{"id": record["id"]} for record in matches[:1]])


class MissingSourceContainer:
    def __init__(self, status_code=404):
        self.status_code = status_code
        self.enumerations = 0

    def list_blobs(self):
        self.enumerations += 1
        raise FakeBlobError(self.status_code, "Source container is unavailable.")

    def create_container(self):
        raise AssertionError("Backups must not provision the source screening container.")


class BackupTarget(FakeTargetContainer):
    def upload_blob(self, name, data, **kwargs):
        blob = self.get_blob_client(name)
        blob.upload_blob(data, **kwargs)
        blob._finish_transfer()


@pytest.fixture
def backup_runtime(monkeypatch):
    module, _jobs, _latest = load_module(monkeypatch)
    app_settings = {"enable_content_screening": False, "enable_enhanced_citations": True}
    monkeypatch.setitem(sys.modules, "functions_settings", types.SimpleNamespace(get_settings=lambda: app_settings))
    target = BackupTarget()
    names = {
        "storage_account_user_documents_container_name": "user-documents",
        "storage_account_group_documents_container_name": "group-documents",
        "storage_account_public_documents_container_name": "public-documents",
        "storage_account_personal_chat_container_name": "personal-chat",
        "storage_account_group_chat_container_name": "group-chat",
        "storage_account_content_screening_container_name": "content-screening",
    }
    for attribute, name in names.items():
        setattr(module.app_config, attribute, name)
    metadata = {attribute: PresenceContainer() for attribute in (*DOCUMENT_CONTAINERS, SCREENING_CONTAINER)}
    metadata[DOCUMENT_CONTAINERS[0]].records.append({"id": "legacy-document", "user_id": "owner"})
    metadata[SCREENING_CONTAINER].records.extend([
        {"id": "configured-policy", "kind": "policy"},
        {"id": "queued-job", "kind": "job"},
        {"id": "runner-lease", "kind": "checkpoint"},
    ])
    for attribute, container in metadata.items():
        setattr(module.app_config, attribute, container)
    sources = {name: FakeSourceContainer({}) for name in names.values()}
    sources["user-documents"] = FakeSourceContainer({
        "ordinary.txt": FakeSourceBlobClient(b"ordinary backup bytes", '"source-etag"'),
    })
    sources["content-screening"] = MissingSourceContainer()
    source_service = types.SimpleNamespace(get_container_client=lambda name: sources[name])
    monkeypatch.setattr(module, "_get_source_blob_service_client", lambda: source_service)
    monkeypatch.setattr(module, "_get_backup_container_client", lambda settings: target)
    monkeypatch.setattr(module, "_get_backup_base_prefix", lambda settings, job: "backups/job")
    monkeypatch.setattr(module, "_assert_backup_execution_settings", lambda *args: None)
    monkeypatch.setattr(module, "_assert_backup_job_lease", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_save_data_management_job", lambda job: job)
    monkeypatch.setattr(module, "_set_job_progress", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_complete_job_step", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "_get_backup_retry_delay", lambda *args: 0)
    plan = build_plan(parallel_operations=1, retry_count=1)
    return types.SimpleNamespace(
        module=module, target=target, sources=sources, metadata=metadata,
        job=build_job(module, plan), settings={}, app_settings=app_settings,
    )


def export_and_review(runtime):
    result = runtime.module.execute_backup_job(runtime.job, runtime.settings)
    manifest = json.loads(runtime.target.get_blob_client(result["manifest_path"]).content)
    review = runtime.module._run_data_management_restore_preflight(
        {}, {
            "restore_policy": "create_only", "differential_mode": "latest_item_state",
            "include_cosmos": False, "include_ai_search": False, "include_source_blobs": False,
        },
        runtime.job, manifest,
    )
    return result, manifest, review


@pytest.mark.parametrize("enabled", [False, True])
def test_unused_missing_screening_container_does_not_break_backup_or_restore(backup_runtime, enabled):
    runtime = backup_runtime
    runtime.app_settings["enable_content_screening"] = enabled
    result, manifest, review = export_and_review(runtime)
    assert result["failed_resource_names"] == manifest["failed_resource_names"] == []
    assert review["ready"]
    resource = runtime.module.get_backup_resource(result["backup_state"], "source_blobs:content-screening")
    assert resource["status"] == "completed"
    assert resource["result"]["blob_count"] == resource["result"]["failed_count"] == 0
    assert runtime.target.get_blob_client("backups/job/source_blobs/user-documents/ordinary.txt").content == b"ordinary backup bytes"
    assert all(len(container.queries) == 1 for container in runtime.metadata.values())
    assert runtime.sources["content-screening"].enumerations == 1


def test_unused_screening_check_uses_the_configured_private_container_name(backup_runtime):
    runtime = backup_runtime
    runtime.module.app_config.storage_account_content_screening_container_name = "private-screening-evidence"
    runtime.sources["private-screening-evidence"] = runtime.sources.pop("content-screening")
    result, _manifest, review = export_and_review(runtime)
    assert result["failed_resource_names"] == [] and review["ready"]
    resource = runtime.module.get_backup_resource(result["backup_state"], "source_blobs:private-screening-evidence")
    assert resource["status"] == "completed" and resource["result"]["blob_count"] == 0


def test_retry_clears_a_previously_failed_unused_source_resource(backup_runtime):
    runtime = backup_runtime
    runtime.module.app_config.cosmos_content_screening_container = None
    first, _manifest, review = export_and_review(runtime)
    assert first["failed_resource_names"] == ["source_blobs:content-screening"] and not review["ready"]
    runtime.module.app_config.cosmos_content_screening_container = runtime.metadata[SCREENING_CONTAINER]
    runtime.job.update(backup_attempt_id="attempt-2", lease_generation=2)
    recovered, manifest, review = export_and_review(runtime)
    assert recovered["failed_resource_names"] == manifest["failed_resource_names"] == []
    assert review["ready"] and runtime.sources["content-screening"].enumerations == 2


@pytest.mark.parametrize("attribute,record", [
    (DOCUMENT_CONTAINERS[0], {"id": "held", "content_screening": {"state": "cleared"}}),
    (DOCUMENT_CONTAINERS[1], {"id": "held", "content_screening": {"state": "pending_review"}}),
    (DOCUMENT_CONTAINERS[2], {"id": "held", "content_screening": {"state": "incomplete"}}),
    (DOCUMENT_CONTAINERS[0], {"id": "unknown-marker", "content_screening": None}),
    (SCREENING_CONTAINER, {"id": "pending-scan", "kind": "scan", "state": "pending_scan"}),
    (SCREENING_CONTAINER, {"id": "unknown-scan", "kind": "scan"}),
    (SCREENING_CONTAINER, {"id": "model-window", "kind": "model_window", "result_ref": {"protected": "result"}}),
    (SCREENING_CONTAINER, {"id": "deleted-with-source", "kind": "scan", "state": "deleted", "source_ref": {}}),
])
def test_missing_required_screening_storage_remains_restore_blocking(backup_runtime, attribute, record):
    runtime = backup_runtime
    runtime.metadata[attribute].records.append(record)
    result, manifest, review = export_and_review(runtime)
    assert result["failed_resource_names"] == manifest["failed_resource_names"] == ["source_blobs:content-screening"]
    assert not review["ready"]
    assert any(check["id"] == "manifest_integrity" and check["status"] == "block" for check in review["checks"])
    assert runtime.target.get_blob_client("backups/job/source_blobs/user-documents/ordinary.txt").content == b"ordinary backup bytes"


@pytest.mark.parametrize("status_code", [403, 429, 500])
def test_non_missing_storage_errors_are_never_treated_as_unused(backup_runtime, status_code):
    runtime = backup_runtime
    runtime.sources["content-screening"] = MissingSourceContainer(status_code)
    result, _manifest, review = export_and_review(runtime)
    assert result["failed_resource_names"] == ["source_blobs:content-screening"]
    assert not review["ready"]
    assert not any(container.queries for container in runtime.metadata.values())


def test_explicit_permission_status_is_not_overridden_by_not_found_exception_type(backup_runtime):
    runtime = backup_runtime
    error = runtime.module.ResourceNotFoundError("Access is denied.")
    error.status_code = 403
    assert not runtime.module._can_skip_unused_screening_container(
        runtime.job, "content-screening", 0, error,
    )
    assert not any(container.queries for container in runtime.metadata.values())


@pytest.mark.parametrize("failure", [None, 403, 404, 500])
def test_unverifiable_screening_dependencies_fail_closed(backup_runtime, failure):
    runtime = backup_runtime
    if failure is None:
        runtime.module.app_config.cosmos_content_screening_container = None
    else:
        runtime.metadata[SCREENING_CONTAINER].error = FakeBlobError(failure, "private-metadata-provider-canary")
    result, manifest, review = export_and_review(runtime)
    assert result["failed_resource_names"] == ["source_blobs:content-screening"]
    assert not review["ready"]
    assert "private-metadata-provider-canary" not in repr(manifest)


def test_completed_deletion_tombstones_without_evidence_do_not_require_storage(backup_runtime):
    runtime = backup_runtime
    runtime.metadata[SCREENING_CONTAINER].records.extend([
        {"id": "deleted-scan", "kind": "scan", "state": "deleted", "source_ref": None, "units_ref": None, "result_ref": None},
        {"id": "deleted-window", "kind": "model_window", "result_ref": None, "payload_fingerprint": None},
    ])
    result, _manifest, review = export_and_review(runtime)
    assert result["failed_resource_names"] == [] and review["ready"]


def test_missing_ordinary_container_is_not_optional(backup_runtime):
    runtime = backup_runtime
    runtime.sources["user-documents"] = MissingSourceContainer()
    result, _manifest, review = export_and_review(runtime)
    assert result["failed_resource_names"] == ["source_blobs:user-documents"]
    assert not review["ready"]


def test_disappearing_screening_container_after_enumeration_is_not_empty(backup_runtime):
    runtime = backup_runtime

    class DisappearingContainer(FakeSourceContainer):
        def list_blobs(self):
            yield from super().list_blobs()
            raise FakeBlobError(404, "Container disappeared during enumeration.")

    runtime.sources["content-screening"] = DisappearingContainer({
        "already-seen.bin": FakeSourceBlobClient(b"existing evidence", '"evidence-etag"'),
    })
    result, _manifest, review = export_and_review(runtime)
    assert result["failed_resource_names"] == ["source_blobs:content-screening"]
    assert not review["ready"]
    assert not any(container.queries for container in runtime.metadata.values())


def test_missing_individual_evidence_blob_is_never_skipped(backup_runtime):
    runtime = backup_runtime
    runtime.sources["content-screening"] = FakeSourceContainer({
        "missing.bin": FakeSourceBlobClient(b"missing evidence", '"evidence-etag"', permanent_error=FakeBlobError(404)),
    })
    result, _manifest, review = export_and_review(runtime)
    assert result["failed_resource_names"] == ["source_blobs:content-screening"]
    assert not review["ready"]
    assert not any(container.queries for container in runtime.metadata.values())


@pytest.mark.parametrize("error_name", ["DataManagementBackupCanceledError", "DataManagementBackupLeaseLostError"])
def test_unused_container_checks_respect_backup_fences(backup_runtime, monkeypatch, error_name):
    runtime = backup_runtime
    error_type = getattr(runtime.module, error_name)

    def stopped(job):
        raise error_type("Backup execution stopped.")

    monkeypatch.setattr(runtime.module, "_assert_backup_job_lease", stopped)
    with pytest.raises(error_type):
        runtime.module._can_skip_unused_screening_container(
            runtime.job, "content-screening", 0, FakeBlobError(404),
        )
