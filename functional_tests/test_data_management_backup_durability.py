#!/usr/bin/env python3
# test_data_management_backup_durability.py
"""
Functional test for durable Data Management backup jobs.
Version: 0.250.074
Implemented in: 0.250.073
Updated in: 0.250.074

This test ensures full and partial backups persist immutable plans and
cutoffs, enforce source fencing, honor cancellation at durable boundaries,
recover stale work, keep latest item state outside source records, and expose
only bounded sanitized progress.
"""

import copy
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys
import types


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))

from functions_data_management_backup_state import initialize_backup_state


class FakeCosmosError(Exception):
    """Provide the subset of Cosmos error metadata used by production helpers."""

    def __init__(self, status_code):
        super().__init__(f"Cosmos status {status_code}")
        self.status_code = status_code


class FakeJobContainer:
    """Store data-management jobs and lock documents with Cosmos-like semantics."""

    def __init__(self, documents=None):
        self.documents = {
            document["id"]: copy.deepcopy(document)
            for document in (documents or [])
        }

    def create_item(self, body):
        if body["id"] in self.documents:
            raise FakeCosmosError(409)
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{len(self.documents) + 1}"
        self.documents[saved["id"]] = saved
        return copy.deepcopy(saved)

    def read_item(self, item, partition_key):
        assert item == partition_key
        if item not in self.documents:
            raise FakeCosmosError(404)
        return copy.deepcopy(self.documents[item])

    def replace_item(self, item, body, etag=None, match_condition=None):
        if item not in self.documents:
            raise FakeCosmosError(404)
        existing = self.documents[item]
        if etag and existing.get("_etag") and etag != existing.get("_etag"):
            raise FakeCosmosError(412)
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{len(self.documents) + 1}"
        self.documents[item] = saved
        return copy.deepcopy(saved)

    def upsert_item(self, body):
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{len(self.documents) + 1}"
        self.documents[saved["id"]] = saved
        return copy.deepcopy(saved)

    def delete_item(self, item, partition_key, etag=None, match_condition=None):
        assert item == partition_key
        self.documents.pop(item, None)

    def query_items(self, **_kwargs):
        return iter(copy.deepcopy(list(self.documents.values())))


class FakeItemStateContainer:
    """Store latest-only sidecar state independently from source fixtures."""

    def __init__(self):
        self.documents = {}

    def read_item(self, item, partition_key):
        document = self.documents.get((partition_key, item))
        if document is None:
            raise FakeCosmosError(404)
        return copy.deepcopy(document)

    def upsert_item(self, body):
        saved = copy.deepcopy(body)
        self.documents[(saved["source_scope"], saved["id"])] = saved
        return copy.deepcopy(saved)


class FakeExecutor:
    """Record recovery submissions without executing workers."""

    def __init__(self):
        self.submissions = []

    def submit_stored(self, name, function, **kwargs):
        self.submissions.append((name, function.__name__, kwargs))


class FakeApp:
    """Expose the executor extension used by recovery submission."""

    def __init__(self, executor):
        self.extensions = {"executor": executor}


def load_data_management_module(monkeypatch, job_container, item_state_container=None):
    """Load production backup helpers with in-memory Cosmos dependencies."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.074"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.cosmos_data_management_backup_item_states_container = (
        item_state_container or FakeItemStateContainer()
    )
    monkeypatch.setitem(sys.modules, "config", config_module)

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "functions_appinsights", appinsights_module)

    throughput_module = types.ModuleType("functions_cosmos_throughput")

    class FakeCosmosThroughputError(Exception):
        pass

    throughput_module.CosmosThroughputError = FakeCosmosThroughputError
    throughput_module.get_container_throughput = lambda *_args, **_kwargs: {}
    throughput_module.get_database_throughput = lambda *_args, **_kwargs: {}
    throughput_module.set_database_throughput = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, "functions_cosmos_throughput", throughput_module)

    module_name = "data_management_backup_durability_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def backup_plan(backup_type="partial"):
    """Build an immutable backup plan fixture with non-destructive semantics."""
    return {
        "backup_type": backup_type,
        "source_scope": "simplechat-primary",
        "source_cutoff_at": "2026-07-30T12:00:00+00:00",
        "source_lower_bound_at": "2026-07-29T12:00:00+00:00",
        "differential_mode": "latest_item_state" if backup_type == "partial" else "full_snapshot",
        "source_cutoff_semantics": {
            "upper_bound": "inclusive",
            "lower_bound": "inclusive",
            "deletion_policy": "none",
            "deleted_source_behavior": "non_destructive_not_recorded_as_delete",
        },
        "include_cosmos": True,
        "include_ai_search": False,
        "include_source_blobs": False,
        "backup_storage_container_name": "simplechat-backups",
        "backup_storage_path_prefix": "simplechat-backups",
        "storage_identity": "test-storage-identity",
        "encryption_enabled": False,
        "encryption_key_fingerprint": "",
        "resource_contract": ["cosmos", "ai_search", "source_blobs"],
    }


def backup_job(job_id, status="queued", lease_holder_id=None):
    """Build a minimal durable backup job fixture."""
    plan = backup_plan()
    state = initialize_backup_state(
        None,
        job_id,
        plan,
        plan["source_scope"],
        plan["source_cutoff_at"],
    )
    return {
        "id": job_id,
        "type": "data_management_job",
        "operation": "backup",
        "backup_type": "partial",
        "status": status,
        "created_at": "2026-07-30T11:00:00+00:00",
        "updated_at": "2026-07-30T11:00:00+00:00",
        "last_heartbeat_at": "2026-07-30T11:00:00+00:00",
        "lease_holder_id": lease_holder_id,
        "lease_expires_at": "2099-01-01T00:00:00+00:00" if lease_holder_id else None,
        "lease_generation": 1 if lease_holder_id else 0,
        "backup_attempt_id": "attempt-1" if lease_holder_id else None,
        "backup_plan": plan,
        "backup_state": state,
        "progress": {},
        "result": {},
        "warnings": [],
        "cancel_requested_at": None,
    }


def test_backup_plan_is_immutable_and_has_explicit_non_destructive_cutoff(monkeypatch):
    """Verify source cutoff and differential deletion policy cannot drift after queueing."""
    module = load_data_management_module(monkeypatch, FakeJobContainer())
    plan = backup_plan()
    state = initialize_backup_state(
        None,
        "11111111-1111-1111-1111-111111111111",
        plan,
        plan["source_scope"],
        plan["source_cutoff_at"],
    )

    assert state["source_cutoff_at"] == "2026-07-30T12:00:00+00:00"
    assert state["normalized_plan"]["source_cutoff_semantics"]["deletion_policy"] == "none"
    assert state["normalized_plan"]["differential_mode"] == "latest_item_state"
    assert module._normalize_data_management_backup_plan(
        {"include_cosmos": False, "include_ai_search": True, "include_source_blobs": False},
        "partial",
        {"include_cosmos": True},
        source_cutoff_at="2026-07-30T12:00:00+00:00",
    )["include_cosmos"] is True

    try:
        initialize_backup_state(
            state,
            "11111111-1111-1111-1111-111111111111",
            {**plan, "include_cosmos": False},
            plan["source_scope"],
            plan["source_cutoff_at"],
        )
    except ValueError as exc:
        assert "plan changed" in str(exc).lower()
    else:
        raise AssertionError("A changed backup plan was accepted on resume.")


def test_backup_source_lock_defers_overlap_and_fences_stale_worker(monkeypatch):
    """Verify only one full or partial backup can own the shared source scope."""
    first_job = backup_job("22222222-2222-2222-2222-222222222222", "queued")
    second_job = backup_job("33333333-3333-3333-3333-333333333333", "queued")
    job_container = FakeJobContainer([first_job, second_job])
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)

    settings = {"data_management_job_lease_seconds": 900}
    claimed_first = module._try_claim_data_management_job(first_job["id"], settings=settings)
    assert claimed_first is not None
    assert claimed_first["backup_source_lock"]["source_scope"] == "simplechat-primary"

    claimed_second = module._try_claim_data_management_job(second_job["id"], settings=settings)
    assert claimed_second is None
    deferred_second = job_container.documents[second_job["id"]]
    assert deferred_second["status"] == "queued"
    assert deferred_second["deferred_due_to_active_backup"] is True

    stale_job = copy.deepcopy(claimed_first)
    stale_job["lease_holder_id"] = "different-worker"
    try:
        module._assert_backup_job_lease(stale_job)
    except module.DataManagementBackupLeaseLostError:
        pass
    else:
        raise AssertionError("A stale backup worker lease was accepted.")


def test_queued_and_running_backup_cancellation_is_durable(monkeypatch):
    """Verify queued backup cancels immediately and a running backup fences next work."""
    queued_job = backup_job("44444444-4444-4444-4444-444444444444", "queued")
    queued_container = FakeJobContainer([queued_job])
    module = load_data_management_module(monkeypatch, queued_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)

    canceled = module.request_data_management_job_cancellation(queued_job["id"], reason="maintenance")
    assert canceled["status"] == "canceled"
    assert canceled["backup_state"]["status"] == "canceled"
    assert canceled["backup_state"]["phase"] == "canceled"

    running_job = backup_job("55555555-5555-5555-5555-555555555555", "running", "worker-1")
    running_container = FakeJobContainer([running_job])
    module = load_data_management_module(monkeypatch, running_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    running_job["backup_source_lock"] = {
        "id": module._get_backup_source_lock_id("simplechat-primary"),
        "lock_token": "lock-1",
        "lease_generation": 1,
        "lease_seconds": 900,
    }
    running_container.documents[running_job["backup_source_lock"]["id"]] = {
        "id": running_job["backup_source_lock"]["id"],
        "type": module.DATA_MANAGEMENT_BACKUP_LOCK_TYPE,
        "backup_job_id": running_job["id"],
        "lock_token": "lock-1",
        "lease_generation": 1,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "_etag": "lock-etag",
    }
    running_container.documents[running_job["id"]] = copy.deepcopy(running_job)

    requested = module.request_data_management_job_cancellation(running_job["id"])
    assert requested["status"] == "running"
    try:
        module._assert_backup_job_lease(running_job)
    except module.DataManagementBackupCanceledError:
        pass
    else:
        raise AssertionError("Backup cancellation did not fence the next durable boundary.")


def test_latest_item_state_is_sidecar_and_partial_only_exports_changed_versions(monkeypatch):
    """Verify differential state is external to source records and tracks only latest version."""
    job = backup_job("66666666-6666-6666-6666-666666666666", "running", "worker-1")
    state_container = FakeItemStateContainer()
    job_container = FakeJobContainer([job])
    module = load_data_management_module(monkeypatch, job_container, state_container)
    source_lock_id = module._get_backup_source_lock_id("simplechat-primary")
    job["backup_source_lock"] = {
        "id": source_lock_id,
        "lock_token": "lock-1",
        "lease_generation": 1,
        "lease_seconds": 900,
    }
    job_container.documents[job["id"]] = copy.deepcopy(job)
    job_container.documents[source_lock_id] = {
        "id": source_lock_id,
        "type": module.DATA_MANAGEMENT_BACKUP_LOCK_TYPE,
        "backup_job_id": job["id"],
        "lock_token": "lock-1",
        "lease_generation": 1,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "_etag": "lock-etag",
    }
    source_record = {"id": "source-record", "title": "Unchanged source"}
    source_snapshot = copy.deepcopy(source_record)
    source_identity = module._build_backup_source_identity("cosmos", "settings", "source-record", "source-record")
    source_version = module._build_backup_source_version(source_record)

    module._record_backup_latest_item_state(
        job,
        "cosmos",
        "cosmos:settings",
        source_identity,
        source_version,
        "succeeded",
        checkpoint_id="checkpoint-1",
        artifact_path="backup/path.jsonl",
    )
    latest_state = module._read_backup_latest_item_state(
        "simplechat-primary",
        module._build_backup_lineage_id(job["backup_plan"]),
        "cosmos",
        "cosmos:settings",
        source_identity,
    )

    assert source_record == source_snapshot
    assert latest_state["job_id"] == job["id"]
    assert latest_state["source_version"] == source_version
    assert module._is_backup_item_due_for_export(job["backup_plan"], latest_state, source_version, job["id"]) is False
    module._write_backup_manifest_batch(
        job["id"],
        "cosmos:settings",
        [module._build_backup_manifest_entry(
            job,
            "cosmos",
            "cosmos:settings",
            {"source_identity": source_identity, "source_version": source_version},
            "skipped",
            artifact_checkpoint_id="checkpoint-1",
            artifact_path="backup/path.jsonl",
            skip_summary="Latest successful backup state matches the source version.",
        )],
    )
    module._sync_backup_latest_item_state_from_manifest(job, "cosmos:settings")
    skipped_state = module._read_backup_latest_item_state(
        "simplechat-primary",
        module._build_backup_lineage_id(job["backup_plan"]),
        "cosmos",
        "cosmos:settings",
        source_identity,
    )
    assert skipped_state["status"] == "skipped"
    assert skipped_state["artifact_checkpoint_id"] == "checkpoint-1"
    assert module._is_backup_item_due_for_export(
        job["backup_plan"],
        latest_state,
        "changed-version",
        job["id"],
    ) is True


def test_changed_backup_lineage_does_not_reuse_prior_differential_state(monkeypatch):
    """Verify a new artifact destination or key lineage requires a fresh item baseline."""
    job = backup_job("99999999-9999-9999-9999-999999999999", "running", "worker-1")
    state_container = FakeItemStateContainer()
    job_container = FakeJobContainer([job])
    module = load_data_management_module(monkeypatch, job_container, state_container)
    source_lock_id = module._get_backup_source_lock_id("simplechat-primary")
    job["backup_source_lock"] = {
        "id": source_lock_id,
        "lock_token": "lock-1",
        "lease_generation": 1,
        "lease_seconds": 900,
    }
    job_container.documents[job["id"]] = copy.deepcopy(job)
    job_container.documents[source_lock_id] = {
        "id": source_lock_id,
        "type": module.DATA_MANAGEMENT_BACKUP_LOCK_TYPE,
        "backup_job_id": job["id"],
        "lock_token": "lock-1",
        "lease_generation": 1,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "_etag": "lock-etag",
    }
    source_identity = module._build_backup_source_identity("cosmos", "settings", "record", "record")
    source_version = "version-1"
    module._record_backup_latest_item_state(
        job,
        "cosmos",
        "cosmos:settings",
        source_identity,
        source_version,
        "succeeded",
        checkpoint_id="checkpoint-1",
        artifact_path="old-prefix/batch.jsonl",
    )
    changed_plan = copy.deepcopy(job["backup_plan"])
    changed_plan["backup_storage_path_prefix"] = "new-prefix"
    changed_lineage = module._build_backup_lineage_id(changed_plan)
    prior_state = module._read_backup_latest_item_state(
        "simplechat-primary",
        changed_lineage,
        "cosmos",
        "cosmos:settings",
        source_identity,
    )

    assert prior_state is None
    assert module._is_backup_item_due_for_export(changed_plan, prior_state, source_version) is True


def test_version_pinned_key_vault_plan_survives_current_key_rotation(monkeypatch):
    """Verify a retry keeps its original Key Vault secret version and lineage."""
    module = load_data_management_module(monkeypatch, FakeJobContainer())
    version_one_reference = "https://vault.vault.azure.net/secrets/backup-key/version-one"
    settings = {
        "encryption_enabled": True,
        "encryption_key_storage": "key_vault",
        "encryption_key_reference": "backup-key",
        "backup_storage_container_name": "simplechat-backups",
        "backup_storage_path_prefix": "simplechat-backups",
        "backup_storage_authentication_type": "managed_identity",
        "backup_storage_blob_endpoint": "https://account.blob.core.windows.net",
    }
    monkeypatch.setattr(module, "_resolve_backup_encryption_reference", lambda _settings: version_one_reference)

    plan = module._normalize_data_management_backup_plan(
        settings,
        "partial",
        source_cutoff_at="2026-07-30T12:00:00+00:00",
    )
    rotated_settings = {
        **settings,
        "encryption_key_reference": "backup-key-rotated",
    }

    assert plan["encryption_key_reference"] == version_one_reference
    assert module._build_backup_lineage_id(plan)
    module._assert_backup_execution_settings(rotated_settings, plan)


def test_key_vault_backup_plan_rejects_unversioned_reference(monkeypatch):
    """Verify a Key Vault backup does not proceed without an immutable key version."""
    module = load_data_management_module(monkeypatch, FakeJobContainer())
    keyvault_module = types.ModuleType("functions_keyvault")
    keyvault_module.resolve_secret_reference_version = lambda _reference: "backup-key"
    monkeypatch.setitem(sys.modules, "functions_keyvault", keyvault_module)
    settings = {
        "encryption_enabled": True,
        "encryption_key_storage": "key_vault",
        "encryption_key_reference": "backup-key",
        "backup_storage_container_name": "simplechat-backups",
        "backup_storage_path_prefix": "simplechat-backups",
        "backup_storage_authentication_type": "managed_identity",
        "backup_storage_blob_endpoint": "https://account.blob.core.windows.net",
    }

    try:
        module._normalize_data_management_backup_plan(settings, "full")
    except module.DataManagementSettingsValidationError as exc:
        assert "version" in str(exc).lower()
    else:
        raise AssertionError("An unversioned Key Vault encryption reference was accepted.")


def test_cosmos_cutoff_excludes_changes_in_captured_second(monkeypatch):
    """Verify second-resolution Cosmos versions use a conservative immutable cutoff."""
    module = load_data_management_module(monkeypatch, FakeJobContainer())
    plan = module._normalize_data_management_backup_plan(
        {"include_cosmos": True, "include_ai_search": False, "include_source_blobs": False},
        "full",
        source_cutoff_at="2026-07-30T12:00:00.500000+00:00",
    )

    assert plan["cosmos_source_cutoff_epoch"] == 1785412799
    assert plan["source_cutoff_semantics"]["cosmos_upper_bound"] == "strictly_before_captured_second"


def test_ai_search_schema_failure_marks_schema_checkpoint(monkeypatch):
    """Verify a schema upload failure remains attributable to the schema resource."""
    job = backup_job("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "running", "worker-1")
    job_container = FakeJobContainer([job])
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    source_lock_id = module._get_backup_source_lock_id("simplechat-primary")
    job["backup_source_lock"] = {
        "id": source_lock_id,
        "lock_token": "lock-1",
        "lease_generation": 1,
        "lease_seconds": 900,
    }
    job_container.documents[job["id"]] = copy.deepcopy(job)
    job_container.documents[source_lock_id] = {
        "id": source_lock_id,
        "type": module.DATA_MANAGEMENT_BACKUP_LOCK_TYPE,
        "backup_job_id": job["id"],
        "lock_token": "lock-1",
        "lease_generation": 1,
        "expires_at": "2099-01-01T00:00:00+00:00",
        "_etag": "lock-etag",
    }
    state = job["backup_state"]
    module.start_backup_resource(state, "ai_search_schema:test-index", "ai_search_schema")
    module._fail_backup_resource_checkpoint(
        job,
        state,
        {"data_management_job_lease_seconds": 900},
        "ai_search_schema:test-index",
        "schema upload failed",
        "Recorded failed AI Search schema backup resource test-index",
    )

    assert state["resources"]["ai_search_schema:test-index"]["status"] == "failed"
    assert "ai_search:test-index" not in state["resources"]


def test_backup_transfer_heartbeat_failure_fences_worker(monkeypatch):
    """Verify a long-transfer heartbeat failure prevents the worker from continuing."""
    module = load_data_management_module(monkeypatch, FakeJobContainer())
    monkeypatch.setattr(module, "DATA_MANAGEMENT_BACKUP_HEARTBEAT_INTERVAL_SECONDS", 0.001)
    heartbeat_calls = []
    heartbeat_started = module.Event()
    monkeypatch.setattr(
        module,
        "_persist_backup_heartbeat",
        lambda *_args, **_kwargs: (
            heartbeat_calls.append(True),
            heartbeat_started.set(),
            (_ for _ in ()).throw(module.DataManagementBackupLeaseLostError("lease lost")),
        )[-1],
    )
    monkeypatch.setattr(module, "_assert_backup_job_lease", lambda *_args, **_kwargs: None)

    def transfer():
        assert heartbeat_started.wait(1.0)
        return "completed"

    try:
        module._run_backup_transfer_with_heartbeat(
            {"operation": "backup"},
            {},
            "test transfer",
            transfer,
        )
    except module.DataManagementBackupLeaseLostError:
        pass
    else:
        raise AssertionError("A failed transfer heartbeat did not fence the backup worker.")

    assert heartbeat_calls


def test_job_timeline_redacts_signed_urls_and_credentials(monkeypatch):
    """Verify persisted and returned timeline event detail never leaks sensitive strings."""
    job = backup_job("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "queued")
    job_container = FakeJobContainer([job])
    module = load_data_management_module(monkeypatch, job_container)
    captured_items = []
    monkeypatch.setattr(
        module,
        "create_data_management_job_item",
        lambda *_args, **kwargs: captured_items.append(kwargs) or {},
    )

    module._record_data_management_job_event(
        job["id"],
        "backup-failed",
        job,
        message="Upload failed at https://account.blob.core.windows.net/a?sig=secret-value",
        details={
            "error": "token=not-for-browser",
            "nested": {"connection_string": "AccountKey=secret-value"},
        },
    )
    public_item = module.sanitize_data_management_job_item_for_admin({
        "id": "timeline-1",
        "job_id": job["id"],
        "step_name": "backup-failed",
        "status": "failed",
        "message": "https://account.blob.core.windows.net/a?sig=secret-value",
        "details": {"error": "token=not-for-browser"},
    })
    serialized = str(captured_items) + str(public_item)

    assert "secret-value" not in serialized
    assert "token=not-for-browser" not in serialized


def test_backup_recovery_and_admin_progress_are_bounded_and_sanitized(monkeypatch):
    """Verify stale backup recovery and public progress omit secrets, SAS URLs, and content."""
    stale_job = backup_job("77777777-7777-7777-7777-777777777777", "running", "worker-1")
    stale_job["updated_at"] = "2026-07-30T00:00:00+00:00"
    stale_job["last_heartbeat_at"] = "2026-07-30T00:00:00+00:00"
    stale_job["backup_state"].update({
        "warnings": ["https://account.blob.core.windows.net/a?sig=secret-value"],
        "failed_items": [{"source_identity": "sha256:abc", "failure_summary": "token=not-for-browser"}],
        "resources": {
            "cosmos:settings": {
                "status": "failed",
                "progress": {"processed_count": 1, "failed_count": 1},
                "checkpoint": {"next_batch_number": 2, "completed_batch_count": 1},
                "result": {"path": "https://account.blob.core.windows.net/a?sig=secret-value"},
            },
        },
    })
    stale_job["result"] = {
        "backup_state": stale_job["backup_state"],
        "artifacts": [{"path": "https://account.blob.core.windows.net/a?sig=secret-value"}],
    }
    job_container = FakeJobContainer([stale_job])
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    executor = FakeExecutor()

    recovery = module.recover_data_management_jobs(
        app=FakeApp(executor),
        current_time=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
    )
    progress = module.get_data_management_job_progress(stale_job["id"])
    serialized = str(progress)

    assert recovery == [{
        "job_id": stale_job["id"],
        "operation": "backup",
        "reason": "stale_recovery",
        "submitted": True,
    }]
    assert len(executor.submissions) == 1
    assert progress["backup_state"]["source_cutoff_at"] == "2026-07-30T12:00:00+00:00"
    assert "secret-value" not in serialized
    assert "token=not-for-browser" not in serialized


def test_migration_recovery_wrapper_does_not_resubmit_backup_jobs(monkeypatch):
    """Verify compatibility migration recovery remains scoped to migration jobs."""
    backup = backup_job("88888888-8888-8888-8888-888888888888", "running", "worker-1")
    backup["updated_at"] = "2026-07-30T00:00:00+00:00"
    backup["last_heartbeat_at"] = "2026-07-30T00:00:00+00:00"
    job_container = FakeJobContainer([backup])
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    executor = FakeExecutor()

    recovery = module.recover_data_management_migration_jobs(
        app=FakeApp(executor),
        current_time=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert recovery == []
    assert executor.submissions == []
