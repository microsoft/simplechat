# test_data_management_migration_coordinator.py
"""
Functional test for Data Management migration destination coordination.
Version: 0.250.078
Implemented in: 0.250.075
Updated in: 0.250.078

This test ensures only one migration can hold a destination coordinator lease
at a time and that release permits a later migration to acquire it safely.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))


class ConflictError(Exception):
    """Minimal Cosmos conflict used by the lock fake."""

    status_code = 409


class FakeCoordinatorContainer:
    """Store job and coordinator documents keyed by their ID."""

    def __init__(self):
        self.items = {}
        self.etag_counter = 0

    def _save(self, body):
        self.etag_counter += 1
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{self.etag_counter}"
        self.items[saved["id"]] = saved
        return copy.deepcopy(saved)

    def create_item(self, body):
        if body["id"] in self.items:
            raise ConflictError("already exists")
        return self._save(body)

    def read_item(self, item, partition_key):
        assert item == partition_key
        return copy.deepcopy(self.items[item])

    def replace_item(self, item, body, **_kwargs):
        assert item in self.items
        return self._save(body)

    def delete_item(self, item, partition_key, **_kwargs):
        assert item == partition_key
        self.items.pop(item, None)

    def upsert_item(self, body):
        return self._save(body)


class FakeTargetCoordinatorDatabase:
    """Expose one shared target jobs container to otherwise independent source deployments."""

    def __init__(self, container):
        self.container = container

    def create_container_if_not_exists(self, **_kwargs):
        return self.container


def load_data_management_module(monkeypatch, job_container):
    """Load the production module with the coordinator storage fake."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.075"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
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

    module_name = "data_management_migration_coordinator_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_destination_coordinator_blocks_overlapping_migrations(monkeypatch):
    """Validate migrations to the same destination cannot overlap."""
    container = FakeCoordinatorContainer()
    module = load_data_management_module(monkeypatch, container)
    settings = {
        "target_cosmos_endpoint": "https://target.documents.azure.com",
        "target_ai_search_endpoint": "https://target.search.windows.net",
        "target_enhanced_citations_storage_blob_endpoint": "https://target.blob.core.windows.net",
        "data_management_job_lease_seconds": 900,
    }
    migration_plan = {
        "include_ai_search": True,
        "include_source_blobs": True,
    }
    first_job = {"id": "11111111-1111-1111-1111-111111111111", "operation": "migration"}
    second_job = {"id": "22222222-2222-2222-2222-222222222222", "operation": "migration"}

    first_lock = module._acquire_migration_destination_lock(first_job, settings, migration_plan)
    assert first_lock["id"] in container.items
    assert first_lock["lease_seconds"] >= (
        module.DATA_MANAGEMENT_MIGRATION_REMOTE_REQUEST_TIMEOUT_SECONDS +
        module.DATA_MANAGEMENT_MIGRATION_LOCK_RECOVERY_GRACE_SECONDS
    )
    assert first_lock["lease_seconds"] < module.DATA_MANAGEMENT_DEFAULT_STALE_SECONDS

    try:
        module._acquire_migration_destination_lock(second_job, settings, migration_plan)
    except module.DataManagementSettingsValidationError as exc:
        assert "active" in str(exc).lower()
    else:
        raise AssertionError("A second migration acquired the same destination coordinator lease.")

    module._release_migration_destination_lock(first_job)
    second_lock = module._acquire_migration_destination_lock(second_job, settings, migration_plan)
    assert second_lock["id"] in container.items
    assert second_lock["lock_token"] != first_lock["lock_token"]


def test_coordinator_blocks_partially_overlapping_destination_plans(monkeypatch):
    """Block concurrent jobs even when optional Search or Blob selections differ."""
    container = FakeCoordinatorContainer()
    module = load_data_management_module(monkeypatch, container)
    settings = {
        "target_cosmos_endpoint": "https://target.documents.azure.com",
        "target_ai_search_endpoint": "https://target.search.windows.net",
        "target_enhanced_citations_storage_blob_endpoint": "https://target.blob.core.windows.net",
        "data_management_job_lease_seconds": 900,
    }
    cosmos_only_job = {
        "id": "33333333-3333-3333-3333-333333333333",
        "operation": "migration",
    }
    full_job = {
        "id": "44444444-4444-4444-4444-444444444444",
        "operation": "migration",
    }

    first_lock = module._acquire_migration_destination_lock(
        cosmos_only_job,
        settings,
        {"include_ai_search": False, "include_source_blobs": False},
    )

    try:
        module._acquire_migration_destination_lock(
            full_job,
            settings,
            {"include_ai_search": True, "include_source_blobs": True},
        )
    except module.DataManagementSettingsValidationError as exc:
        assert "active" in str(exc).lower()
    else:
        raise AssertionError("A partially overlapping migration bypassed the global coordinator.")

    assert first_lock["id"].endswith("_global")


def test_retry_claim_waits_for_retained_coordinator_lock_expiry(monkeypatch):
    """Do not claim a retry while an uncertain prior request remains quarantined."""
    container = FakeCoordinatorContainer()
    module = load_data_management_module(monkeypatch, container)
    settings = {"data_management_job_lease_seconds": 900}
    job = {
        "id": "55555555-5555-5555-5555-555555555555",
        "type": "data_management_job",
        "operation": "migration",
        "status": "queued",
    }
    module._acquire_migration_destination_lock(job, settings, {})
    container._save(job)

    assert module._try_claim_data_management_job(job["id"], settings=settings) is None

    lock_id = job["migration_coordinator_lock"]["id"]
    container.items[lock_id]["expires_at"] = "2000-01-01T00:00:00+00:00"
    claimed_job = module._try_claim_data_management_job(job["id"], settings=settings)

    assert claimed_job["status"] == "running"
    assert claimed_job["migration_attempt_id"]


def test_retry_replaces_released_or_expired_coordinator_lock_before_first_lease_check(monkeypatch):
    """A retry must discard stale lock metadata before it verifies its new worker lease."""
    container = FakeCoordinatorContainer()
    module = load_data_management_module(monkeypatch, container)
    settings = {"data_management_job_lease_seconds": 900}

    released_job = {
        "id": "66666666-6666-6666-6666-666666666666",
        "type": "data_management_job",
        "operation": "migration",
        "status": "queued",
    }
    module._acquire_migration_destination_lock(released_job, settings, {})
    module._release_migration_destination_lock(released_job)
    container._save(released_job)

    claimed_released_job = module._try_claim_data_management_job(
        released_job["id"],
        settings=settings,
    )
    assert "migration_coordinator_lock" not in claimed_released_job
    module._assert_migration_job_lease(claimed_released_job)
    replacement_lock = module._acquire_migration_destination_lock(
        claimed_released_job,
        settings,
        {},
    )
    assert container.items[replacement_lock["id"]]["migration_job_id"] == claimed_released_job["id"]

    second_container = FakeCoordinatorContainer()
    second_module = load_data_management_module(monkeypatch, second_container)
    expired_job = {
        "id": "77777777-7777-7777-7777-777777777777",
        "type": "data_management_job",
        "operation": "migration",
        "status": "queued",
    }
    expired_lock = second_module._acquire_migration_destination_lock(expired_job, settings, {})
    second_container.items[expired_lock["id"]]["expires_at"] = "2000-01-01T00:00:00+00:00"
    second_container._save(expired_job)

    claimed_expired_job = second_module._try_claim_data_management_job(
        expired_job["id"],
        settings=settings,
    )
    assert "migration_coordinator_lock" not in claimed_expired_job
    second_module._assert_migration_job_lease(claimed_expired_job)
    replacement_lock = second_module._acquire_migration_destination_lock(
        claimed_expired_job,
        settings,
        {},
    )
    assert second_container.items[replacement_lock["id"]]["migration_job_id"] == claimed_expired_job["id"]


def test_target_coordinator_blocks_independent_source_job_stores(monkeypatch):
    """Two source deployments must share the destination lock before either writes Cosmos data."""
    first_source_jobs = FakeCoordinatorContainer()
    second_source_jobs = FakeCoordinatorContainer()
    target_jobs = FakeCoordinatorContainer()
    first_module = load_data_management_module(monkeypatch, first_source_jobs)
    second_module = load_data_management_module(monkeypatch, second_source_jobs)
    target_database = FakeTargetCoordinatorDatabase(target_jobs)
    settings = {"data_management_job_lease_seconds": 900}
    first_job = {
        "id": "88888888-8888-8888-8888-888888888888",
        "type": "data_management_job",
        "operation": "migration",
    }
    second_job = {
        "id": "99999999-9999-9999-9999-999999999999",
        "type": "data_management_job",
        "operation": "migration",
    }

    first_module._acquire_target_migration_coordinator(
        first_job,
        target_database,
        settings,
    )
    assert "target_migration_coordinator" in first_job
    assert "target_migration_coordinator_container" not in first_job

    with pytest.raises(RuntimeError, match="Another SimpleChat source"):
        second_module._acquire_target_migration_coordinator(
            second_job,
            target_database,
            settings,
        )

    assert first_module._release_target_migration_coordinator(first_job) is True
    second_module._acquire_target_migration_coordinator(
        second_job,
        target_database,
        settings,
    )
    assert second_job["target_migration_coordinator"]["migration_id"] == second_job["id"]