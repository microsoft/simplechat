# test_data_management_migration_orchestration.py
"""
Functional test for Data Management migration orchestration.
Version: 0.250.071
Implemented in: 0.250.075
Updated in: 0.250.071

This test ensures a migration job uses one provenance ID through preflight,
capacity preparation, all copy surfaces, and destination capacity restoration.
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
    """Persist migration state as the production job container would."""

    def __init__(self):
        self.job = None

    def upsert_item(self, body):
        self.job = copy.deepcopy(body)
        return copy.deepcopy(body)

    def read_item(self, item, partition_key):
        assert item == partition_key == self.job["id"]
        return copy.deepcopy(self.job)


def load_data_management_module(monkeypatch, job_container):
    """Load the production module with job-only fake dependencies."""
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

    module_name = "data_management_migration_orchestration_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_data_management_migration_uses_one_provenance_context_across_surfaces(monkeypatch):
    """Verify job orchestration hands the same durable context to each surface."""
    migration_id = "11111111-1111-1111-1111-111111111111"
    module = load_data_management_module(monkeypatch, FakeJobContainer())
    call_order = []
    received_contexts = []
    progress_updates = []

    def preflight(job, state, _settings, _plan):
        call_order.append("preflight")
        state["preflight"] = {"status": "completed"}
        return state

    def preview(_settings, _options, **_kwargs):
        call_order.append("preview")
        return {
            "estimated_outcomes": {
                "create_count": 0,
                "update_count": 0,
                "unchanged_count": 0,
                "delete_count": 0,
                "not_applicable_count": 0,
                "missing_count": 0,
                "conflict_count": 0,
                "failed_count": 0,
            },
        }

    def capacity(job, state, _settings, _plan):
        call_order.append("capacity")
        state["capacity"] = {"status": "boosted", "restore_pending": True}
        return state

    def copy_cosmos(_database, target_type, _selection, job, state, context, _settings):
        call_order.append(f"cosmos:{target_type}")
        received_contexts.append(context["migration_id"])
        job["migration_state"] = state
        return [{"name": "user_settings", "type": "cosmos_container", "item_count": 1}]

    def copy_search(_settings, _plan, job, state, context, target_search_write_fence=None):
        call_order.append("search")
        received_contexts.append(context["migration_id"])
        assert target_search_write_fence == ("target-search-gate", {"fence_token": "fence-token"})
        job["migration_state"] = state
        return [{"name": "personal_ai_search", "type": "ai_search_documents", "item_count": 1}]

    def copy_blobs(_settings, _plan, job, state, context):
        call_order.append("blobs")
        received_contexts.append(context["migration_id"])
        job["migration_state"] = state
        return [{"name": "source_blobs", "type": "source_blobs", "blob_count": 1, "bytes": 10}]

    def reconcile(_settings, _plan, job, state, context, _database, **_kwargs):
        call_order.append("reconciliation")
        received_contexts.append(context["migration_id"])
        job["migration_state"] = state
        return {
            "name": "migration_reconciliation",
            "type": "migration_reconciliation",
            "readiness": "ready",
        }

    def restore(job, state, _settings, **_kwargs):
        call_order.append("restore")
        state["capacity"] = {"status": "restored", "restore_pending": False}
        job["migration_state"] = state
        return [], state

    monkeypatch.setattr(module, "_run_data_management_migration_preflight", preflight)
    monkeypatch.setattr(module, "preview_data_management_migration_plan", preview)
    monkeypatch.setattr(module, "_apply_temporary_destination_capacity", capacity)
    monkeypatch.setattr(module, "_get_target_cosmos_database", lambda _settings: object())
    monkeypatch.setattr(
        module,
        "_acquire_target_migration_coordinator",
        lambda job, _database, _settings: call_order.append("target-coordinator-acquire") or job.update({
            "target_migration_coordinator": {"lock_token": "target-token"},
        }),
    )
    monkeypatch.setattr(
        module,
        "_release_target_migration_coordinator",
        lambda _job: call_order.append("target-coordinator-release") or True,
    )
    monkeypatch.setattr(
        module,
        "_get_target_data_management_search_write_gate_container",
        lambda _database: "target-search-gate",
    )
    monkeypatch.setattr(
        module,
        "acquire_data_management_search_write_fence",
        lambda *_args, **_kwargs: call_order.append("search-fence-acquire") or {"fence_token": "fence-token"},
    )
    monkeypatch.setattr(
        module,
        "release_data_management_search_write_fence",
        lambda *_args, **_kwargs: call_order.append("search-fence-release") or True,
    )
    monkeypatch.setattr(module, "_copy_cosmos_records_to_target", copy_cosmos)
    monkeypatch.setattr(module, "_copy_ai_search_to_target", copy_search)
    monkeypatch.setattr(module, "_copy_source_blobs_to_target", copy_blobs)
    monkeypatch.setattr(module, "_run_data_management_migration_reconciliation", reconcile)
    monkeypatch.setattr(module, "_restore_temporary_destination_capacity", restore)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    def capture_progress(job, message, completed_steps, total_steps, current_step=None, **_kwargs):
        progress_updates.append((completed_steps, total_steps, current_step, message))
        job["progress"] = {
            "completed_steps": completed_steps,
            "total_steps": total_steps,
            "current_step": current_step,
            "percent_complete": int((completed_steps / total_steps) * 100),
        }
        return job

    monkeypatch.setattr(module, "_set_job_progress", capture_progress)

    job = {
        "id": migration_id,
        "options": {
            "migration_plan": {
                "users": {"mode": "selected", "ids": ["user-1"], "include_documents": True},
                "groups": {"mode": "none", "ids": [], "include_documents": False},
                "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
                "include_ai_search": True,
                "target_ai_search_writes_frozen": True,
                "include_source_blobs": True,
            },
        },
    }
    settings = {
        "migration_max_parallel_operations": 8,
        "migration_retry_count": 5,
        "migration_skip_recent_within_hours": 0,
        "data_management_job_lease_seconds": 900,
    }

    result = module.execute_migration_job(job, settings)

    assert result["migration_id"] == migration_id
    assert received_contexts == [migration_id, migration_id, migration_id, migration_id]
    assert call_order == [
        "target-coordinator-acquire",
        "preview",
        "preflight",
        "capacity",
        "cosmos:users",
        "search-fence-acquire",
        "search",
        "search-fence-release",
        "blobs",
        "reconciliation",
        "restore",
    ]
    assert result["migration_state"]["status"] == "completed"
    assert result["migration_state"]["capacity"]["status"] == "restored"
    assert progress_updates[0][:3] == (0, 10, "plan")
    assert progress_updates[-1][:3] == (10, 10, "complete")
    assert (8, 10, "capacity_restore") in [update[:3] for update in progress_updates]
    assert [update[0] for update in progress_updates] == sorted(
        update[0] for update in progress_updates
    )


def test_lightweight_progress_retains_last_progress_and_capacity_restore(monkeypatch):
    """Expose liveness/progress clocks and the active capacity restoration stage."""
    migration_id = "22222222-2222-2222-2222-222222222222"
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, job_container)
    job_container.job = {
        "id": migration_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": "running",
        "updated_at": "2026-07-29T12:00:02+00:00",
        "last_heartbeat_at": "2026-07-29T12:00:02+00:00",
        "last_progress_at": "2026-07-29T12:00:01+00:00",
        "progress": {
            "total_steps": 10,
            "completed_steps": 8,
            "current_step": "capacity_restore",
            "percent_complete": 80,
        },
        "migration_state": initialize_migration_state(
            None,
            migration_id,
            {"test": "progress"},
        ),
    }

    progress = module.get_data_management_job_progress(migration_id)

    assert progress["last_progress_at"] == "2026-07-29T12:00:01+00:00"
    assert progress["progress"]["current_step"] == "capacity_restore"
    assert progress["progress"]["completed_steps"] == 8
    assert progress["progress"]["total_steps"] == 10


def test_process_migration_preserves_ten_stage_completion(monkeypatch):
    """Keep 10/10 migration progress after the generic job wrapper completes."""
    migration_id = "33333333-3333-3333-3333-333333333333"
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, job_container)
    claimed_job = {
        "id": migration_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": "running",
        "warnings": [],
        "progress": {
            "total_steps": 10,
            "completed_steps": 8,
            "current_step": "capacity_restore",
            "percent_complete": 80,
        },
    }

    def execute_migration(job, _settings):
        job["progress"] = {
            "total_steps": 10,
            "completed_steps": 10,
            "current_step": "complete",
            "percent_complete": 100,
        }
        return {"warnings": [], "artifacts": []}

    monkeypatch.setattr(module, "get_data_management_settings", lambda: {})
    monkeypatch.setattr(module, "_try_claim_data_management_job", lambda *_args, **_kwargs: claimed_job)
    monkeypatch.setattr(module, "execute_migration_job", execute_migration)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    released_target_coordinators = []
    monkeypatch.setattr(
        module,
        "_release_target_migration_coordinator",
        lambda job: released_target_coordinators.append(job["id"]) or True,
    )

    completed = module.process_data_management_job(migration_id)

    assert completed["progress"] == {
        "total_steps": 10,
        "completed_steps": 10,
        "current_step": "complete",
        "percent_complete": 100,
    }
    assert released_target_coordinators == [migration_id]


def test_process_migration_retains_lock_after_uncertain_failure(monkeypatch):
    """Keep the coordinator quarantine when a migration exits unexpectedly."""
    migration_id = "44444444-4444-4444-4444-444444444444"
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, job_container)
    claimed_job = {
        "id": migration_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": "running",
        "warnings": [],
        "progress": {},
        "migration_coordinator_lock": {
            "id": "data_management_migration_lock_global",
            "lock_token": "lock-token",
        },
    }
    released_jobs = []

    monkeypatch.setattr(module, "get_data_management_settings", lambda: {})
    monkeypatch.setattr(module, "_try_claim_data_management_job", lambda *_args, **_kwargs: claimed_job)
    monkeypatch.setattr(
        module,
        "execute_migration_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("uncertain request")),
    )
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "_release_migration_destination_lock",
        lambda job: released_jobs.append(job["id"]),
    )
    released_target_coordinators = []
    monkeypatch.setattr(
        module,
        "_release_target_migration_coordinator",
        lambda job: released_target_coordinators.append(job["id"]) or True,
    )

    failed_job = module.process_data_management_job(migration_id)

    assert failed_job["status"] == "failed"
    assert released_jobs == []
    assert released_target_coordinators == []