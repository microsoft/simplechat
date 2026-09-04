# test_data_management_migration_retry.py
"""
Functional test for Data Management migration retry.
Version: 0.250.071
Implemented in: 0.250.075

This test ensures a failed migration retry keeps its original migration GUID
and completed resource checkpoints while returning the job to the queue.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import types


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))

from functions_data_management_migration_state import (
    complete_migration_resource,
    initialize_migration_state,
    start_migration_resource,
)


class FakeJobContainer:
    """Store one job using Cosmos-like read and upsert methods."""

    def __init__(self, job):
        self.job = copy.deepcopy(job)

    def read_item(self, item, partition_key):
        assert item == partition_key == self.job["id"]
        return copy.deepcopy(self.job)

    def upsert_item(self, body):
        self.job = copy.deepcopy(body)
        return copy.deepcopy(self.job)


class FakeConditionalJobContainer:
    """Capture ETag-protected job replacement requests."""

    def __init__(self):
        self.replace_calls = []

    def replace_item(self, **kwargs):
        self.replace_calls.append(copy.deepcopy(kwargs))
        saved = copy.deepcopy(kwargs["body"])
        saved["_etag"] = "next-etag"
        return saved

    def upsert_item(self, _body):
        raise AssertionError("An ETag-protected migration job must use replace_item.")


def load_data_management_module(monkeypatch, job_container):
    """Load the production helper with only its direct storage dependencies."""
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

    module_name = "data_management_migration_retry_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_failed_migration_retry_preserves_guid_and_completed_resources(monkeypatch):
    """Validate restart state remains tied to the same durable migration identity."""
    migration_id = "11111111-1111-1111-1111-111111111111"
    migration_state = initialize_migration_state(None, migration_id, {"plan": "stable"})
    start_migration_resource(migration_state, "cosmos:users:user_settings")
    complete_migration_resource(
        migration_state,
        "cosmos:users:user_settings",
        result={"copied_count": 3},
    )
    migration_state.update({"status": "failed", "last_error": "interrupted"})
    job = {
        "id": migration_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": "failed",
        "completed_at": "2026-07-24T12:00:00+00:00",
        "last_error": "interrupted",
        "migration_state": migration_state,
        "result": {"artifacts": [{"name": "partial"}]},
    }
    job_container = FakeJobContainer(job)
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)

    retried = module.retry_data_management_migration_job(migration_id)

    assert retried["status"] == "queued"
    assert retried["last_error"] is None
    assert retried["completed_at"] is None
    assert retried["result"] == {}
    assert retried["migration_state"]["migration_id"] == migration_id
    assert retried["migration_state"]["status"] == "queued"
    assert retried["migration_state"]["resources"]["cosmos:users:user_settings"]["status"] == "completed"


def test_stale_running_migration_is_eligible_for_safe_resume(monkeypatch):
    """Validate only a stale running migration is exposed as resumable."""
    migration_id = "22222222-2222-2222-2222-222222222222"
    migration_state = initialize_migration_state(None, migration_id, {"plan": "stable"})
    stale_job = {
        "id": migration_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": "running",
        "updated_at": "2026-07-24T00:00:00+00:00",
        "last_heartbeat_at": "2026-07-24T00:00:00+00:00",
        "migration_state": migration_state,
        "result": {},
    }
    job_container = FakeJobContainer(stale_job)
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)

    public_job = module.sanitize_data_management_job_for_admin(stale_job)
    resumed = module.retry_data_management_migration_job(migration_id)

    assert public_job["can_retry"] is True
    assert resumed["status"] == "queued"
    assert resumed["migration_state"]["migration_id"] == migration_id


def test_canceled_migration_retry_clears_active_cancellation(monkeypatch):
    """Preserve cancellation audit history without immediately canceling the retry."""
    migration_id = "55555555-5555-5555-5555-555555555555"
    migration_state = initialize_migration_state(None, migration_id, {"plan": "stable"})
    migration_state.update({
        "status": "canceled",
        "cancel_requested_at": "2026-07-29T12:00:00+00:00",
        "cancel_requested_by": "admin-1",
        "cancel_reason": "maintenance",
    })
    canceled_job = {
        "id": migration_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": "canceled",
        "cancel_requested_at": "2026-07-29T12:00:00+00:00",
        "cancel_requested_by": "admin-1",
        "cancel_requested_by_email": "admin@example.com",
        "cancel_reason": "maintenance",
        "migration_state": migration_state,
        "result": {},
    }
    module = load_data_management_module(monkeypatch, FakeJobContainer(canceled_job))
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)

    retried = module.retry_data_management_migration_job(migration_id)

    assert retried["status"] == "queued"
    assert retried["cancel_requested_at"] is None
    assert retried["migration_state"]["cancel_requested_at"] is None
    assert retried["last_cancellation"]["reason"] == "maintenance"
    assert retried["migration_state"]["last_cancellation"]["reason"] == "maintenance"


def test_prestart_canceled_migration_can_be_requeued(monkeypatch):
    """Restart a queued migration canceled before durable state initialization."""
    migration_id = "66666666-6666-6666-6666-666666666666"
    canceled_job = {
        "id": migration_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": "canceled",
        "cancel_requested_at": "2026-07-29T12:00:00+00:00",
        "migration_state": None,
        "options": {"migration_plan": {"users": {"mode": "all"}}},
        "result": {},
    }
    module = load_data_management_module(monkeypatch, FakeJobContainer(canceled_job))
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)

    retried = module.retry_data_management_migration_job(migration_id)

    assert retried["status"] == "queued"
    assert retried["migration_state"] is None
    assert retried["cancel_requested_at"] is None


def test_migration_job_save_uses_etag_replacement_when_available(monkeypatch):
    """Validate stale workers cannot silently overwrite a newer job checkpoint."""
    job_container = FakeConditionalJobContainer()
    module = load_data_management_module(monkeypatch, job_container)
    job = {
        "id": "33333333-3333-3333-3333-333333333333",
        "_etag": "original-etag",
        "status": "running",
    }

    saved = module._save_data_management_job(job)

    assert len(job_container.replace_calls) == 1
    replace_call = job_container.replace_calls[0]
    assert replace_call["item"] == saved["id"]
    assert replace_call["etag"] == "original-etag"
    assert saved["_etag"] == "next-etag"


def test_superseded_migration_worker_lease_is_rejected(monkeypatch):
    """Validate a stale worker cannot continue after another lease holder takes over."""
    migration_id = "44444444-4444-4444-4444-444444444444"
    persisted_job = {
        "id": migration_id,
        "operation": "migration",
        "status": "running",
        "lease_holder_id": "new-worker",
        "lease_expires_at": "2099-01-01T00:00:00+00:00",
        "_etag": "new-etag",
    }
    module = load_data_management_module(monkeypatch, FakeJobContainer(persisted_job))
    stale_job = {
        "id": migration_id,
        "operation": "migration",
        "lease_holder_id": "old-worker",
        "_etag": "old-etag",
    }

    try:
        module._assert_migration_job_lease(stale_job)
    except module.DataManagementMigrationLeaseLostError as exc:
        assert "superseded" in str(exc).lower()
    else:
        raise AssertionError("A superseded migration worker lease was accepted.")