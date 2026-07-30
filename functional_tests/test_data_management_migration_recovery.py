# test_data_management_migration_recovery.py
"""
Functional test for Data Management migration recovery scheduling.
Version: 0.250.078
Implemented in: 0.250.076

This test ensures delayed queued and stale migration jobs are resubmitted to
the executor, including when scheduled backup processing is disabled.
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
BACKGROUND_TASKS_PATH = APP_ROOT / "background_tasks.py"
APP_PATH = APP_ROOT / "app.py"
sys.path.insert(0, str(APP_ROOT))


class FakeJobContainer:
    """Store multiple job records through Cosmos-like query and write methods."""

    def __init__(self, jobs):
        self.jobs = {job["id"]: copy.deepcopy(job) for job in jobs}

    def query_items(self, **_kwargs):
        return iter(copy.deepcopy(list(self.jobs.values())))

    def read_item(self, item, partition_key):
        assert item == partition_key
        return copy.deepcopy(self.jobs[item])

    def upsert_item(self, body):
        self.jobs[body["id"]] = copy.deepcopy(body)
        return copy.deepcopy(body)


class FakeExecutor:
    """Record executor submissions without starting worker code."""

    def __init__(self):
        self.submissions = []

    def submit_stored(self, name, function, **kwargs):
        self.submissions.append((name, function.__name__, kwargs))


class FakeApp:
    """Expose the Flask executor extension used by recovery submission."""

    def __init__(self, executor):
        self.extensions = {"executor": executor}


def load_data_management_module(monkeypatch, job_container):
    """Load production recovery helpers with in-memory Cosmos dependencies."""
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

    module_name = "data_management_migration_recovery_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def migration_job(job_id, status, updated_at, heartbeat_at=None):
    """Build a minimal durable migration job candidate."""
    return {
        "id": job_id,
        "type": "data_management_job",
        "operation": "migration",
        "status": status,
        "created_at": updated_at,
        "updated_at": updated_at,
        "last_heartbeat_at": heartbeat_at,
        "progress": {},
    }


def test_recovery_resubmits_delayed_queued_and_stale_migrations(monkeypatch):
    """Validate automatic recovery is executor-backed and leaves checkpoints durable."""
    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    queued_job = migration_job(
        "11111111-1111-1111-1111-111111111111",
        "queued",
        "2026-07-24T11:58:00+00:00",
    )
    stale_job = migration_job(
        "22222222-2222-2222-2222-222222222222",
        "running",
        "2026-07-24T11:00:00+00:00",
        heartbeat_at="2026-07-24T11:00:00+00:00",
    )
    job_container = FakeJobContainer([queued_job, stale_job])
    module = load_data_management_module(monkeypatch, job_container)
    monkeypatch.setattr(module, "_record_data_management_job_event", lambda *_args, **_kwargs: None)
    executor = FakeExecutor()

    recovery = module.recover_data_management_migration_jobs(
        app=FakeApp(executor),
        current_time=now,
    )

    assert {(item["job_id"], item["reason"]) for item in recovery} == {
        (queued_job["id"], "queued_recovery"),
        (stale_job["id"], "stale_recovery"),
    }
    assert len(executor.submissions) == 2
    assert all(item["submitted"] is True for item in recovery)
    assert job_container.jobs[queued_job["id"]]["recovery_attempt_count"] == 1
    assert job_container.jobs[stale_job["id"]]["recovery_attempt_count"] == 1


def test_recovery_runs_when_scheduled_backups_are_disabled(monkeypatch):
    """Validate disabled backup schedules do not suppress migration recovery."""
    module = load_data_management_module(monkeypatch, FakeJobContainer([]))
    expected_recovery = [{"job_id": "recovered-job", "reason": "stale_recovery", "submitted": True}]
    monkeypatch.setattr(module, "get_data_management_settings", lambda: {"enabled": False})
    monkeypatch.setattr(
        module,
        "recover_data_management_migration_jobs",
        lambda **_kwargs: expected_recovery,
    )

    result = module.check_due_data_management_jobs_once(app=FakeApp(FakeExecutor()))

    assert result == expected_recovery


def test_background_scheduler_receives_flask_app_for_executor_recovery():
    """Validate the scheduler loop receives the app rather than running migrations inline."""
    background_source = BACKGROUND_TASKS_PATH.read_text(encoding="utf-8")
    app_source = APP_PATH.read_text(encoding="utf-8")

    assert "def run_data_management_scheduler_loop(app=None):" in background_source
    assert "check_due_data_management_jobs_once(app=app)" in background_source
    assert "lambda: run_data_management_scheduler_loop(app=app)" in background_source
    assert "start_background_task_threads(app=app)" in app_source