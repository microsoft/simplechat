# test_data_management_migration_cancellation.py
"""
Functional test for Data Management migration cancellation.
Version: 0.250.071
Implemented in: 0.250.071

This test ensures queued migrations cancel immediately, running migrations stop
at a durable checkpoint, and a cooperative cancellation stays canceled rather
than becoming a failed job.
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

from functions_data_management_migration_state import initialize_migration_state


class FakeJobContainer:
    """Store one migration job through Cosmos-like read and upsert operations."""

    def __init__(self, job):
        self.job = copy.deepcopy(job)

    def read_item(self, item, partition_key):
        assert item == partition_key == self.job["id"]
        return copy.deepcopy(self.job)

    def upsert_item(self, body):
        self.job = copy.deepcopy(body)
        return copy.deepcopy(self.job)


def load_data_management_module(monkeypatch, job_container):
    """Load production cancellation helpers with lightweight infrastructure fakes."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.076"
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

    module_name = "data_management_migration_cancellation_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def build_migration_job(job_id, status, lease_holder_id=None):
    """Build a minimal durable migration job fixture."""
    migration_state = initialize_migration_state(None, job_id, {"test": "cancellation"})
    return {
        "id": job_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": status,
        "lease_holder_id": lease_holder_id,
        "lease_expires_at": "2099-01-01T00:00:00+00:00" if lease_holder_id else None,
        "migration_state": migration_state,
        "progress": {},
        "result": {},
    }


def test_queued_migration_cancels_immediately(monkeypatch):
    """A queued job should become terminally canceled without a worker claim."""
    job_id = "11111111-1111-1111-1111-111111111111"
    job_container = FakeJobContainer(build_migration_job(job_id, "queued"))
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)

    canceled_job = module.request_data_management_migration_cancellation(
        job_id,
        requested_by="admin-id",
        requested_by_email="admin@example.com",
        reason="Cutover paused",
    )

    assert canceled_job["status"] == "canceled"
    assert canceled_job["cancel_requested_at"]
    assert canceled_job["migration_state"]["status"] == "canceled"
    public_job = module.sanitize_data_management_job_for_admin(canceled_job)
    assert public_job["can_cancel"] is False
    assert public_job["can_retry"] is True


def test_running_migration_cancellation_fences_next_checkpoint(monkeypatch):
    """A running worker must observe a durable request before new migration work."""
    job_id = "22222222-2222-2222-2222-222222222222"
    job_container = FakeJobContainer(build_migration_job(job_id, "running", "worker-1"))
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)

    requested_job = module.request_data_management_migration_cancellation(job_id)
    assert requested_job["status"] == "running"
    assert requested_job["cancel_requested_at"]

    try:
        module._assert_migration_job_lease(requested_job)
    except module.DataManagementMigrationCanceledError as exc:
        assert "cancellation" in str(exc).lower()
    else:
        raise AssertionError("A cancellation request did not fence the running worker.")


def test_cancellation_exception_finalizes_job_without_failure(monkeypatch):
    """The processor should record canceled rather than failed after safe stop."""
    job_id = "33333333-3333-3333-3333-333333333333"
    job = build_migration_job(job_id, "running", "worker-1")
    job["cancel_requested_at"] = "2026-07-24T12:00:00+00:00"
    job_container = FakeJobContainer(job)
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "get_data_management_settings", lambda: {})
    monkeypatch.setattr(module, "_try_claim_data_management_job", lambda *_args, **_kwargs: job)
    monkeypatch.setattr(
        module,
        "execute_migration_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            module.DataManagementMigrationCanceledError("requested")
        ),
    )
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "_release_migration_destination_lock", lambda *_args, **_kwargs: None)

    canceled_job = module.process_data_management_job(job_id)

    assert canceled_job["status"] == "canceled"
    assert canceled_job["last_error"] is None
    assert canceled_job["progress"]["current_step"] == "canceled"
    assert canceled_job["migration_state"]["status"] == "canceled"


def test_cancellation_before_execution_prevents_preflight_and_copy(monkeypatch):
    """A persisted cancellation request must stop the executor before destination work."""
    job_id = "44444444-4444-4444-4444-444444444444"
    job = build_migration_job(job_id, "running", "worker-1")
    job.update({
        "cancel_requested_at": "2026-07-24T12:00:00+00:00",
        "migration_state": None,
        "options": {
            "migration_plan": {
                "users": {"mode": "selected", "ids": ["user-1"], "include_documents": False},
                "groups": {"mode": "none", "ids": [], "include_documents": False},
                "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
            },
        },
    })
    job_container = FakeJobContainer(job)
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "_run_data_management_migration_preflight",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Cancellation should stop before migration preflight.")
        ),
    )

    try:
        module.execute_migration_job(job, {"data_management_job_lease_seconds": 900})
    except module.DataManagementMigrationCanceledError:
        pass
    else:
        raise AssertionError("A pre-requested cancellation did not stop migration execution.")

    assert job["migration_state"]["status"] == "canceled"