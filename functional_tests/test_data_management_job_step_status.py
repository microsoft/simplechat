#!/usr/bin/env python3
# test_data_management_job_step_status.py
"""
Functional test for Data Management per-step timeline status.
Version: 0.260.003
Implemented in: 0.260.003

This test ensures finished job steps are recorded as completed instead of
inheriting the running job status, and that terminal jobs stop rendering
live-only telemetry such as "Current container: Waiting".
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
ADMIN_JS_PATH = APP_ROOT / "static" / "js" / "admin" / "admin_data_management.js"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


class StubContainer:
    """Accept the container calls made during module import without storing state."""

    def create_item(self, body):
        return copy.deepcopy(body)

    def upsert_item(self, body):
        return copy.deepcopy(body)

    def query_items(self, *_args, **_kwargs):
        return []


def load_data_management_module(monkeypatch):
    """Load production job-progress helpers with inert Cosmos dependencies."""
    container = StubContainer()
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.260.003"
    config_module.cosmos_data_management_jobs_container = container
    config_module.cosmos_data_management_job_items_container = container
    config_module.cosmos_settings_container = container
    config_module.cosmos_data_management_backup_item_states_container = container
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

    module_name = "data_management_step_status_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def capture_progress_events(monkeypatch, module):
    """Bypass lease/persistence plumbing and record emitted timeline events."""
    recorded = []
    monkeypatch.setattr(module, "_assert_data_management_job_lease", lambda *_a, **_k: None)
    monkeypatch.setattr(module, "_save_data_management_job", lambda job: copy.deepcopy(job))

    def record_event(job_id, step_name, job, status=None, message=None, details=None):
        recorded.append({
            "job_id": job_id,
            "step_name": step_name,
            "status": status,
            "message": message,
            "job_status": job.get("status"),
        })

    monkeypatch.setattr(module, "_record_data_management_job_event", record_event)
    return recorded


def build_job():
    return {"id": "job-1", "operation": "backup", "status": "running"}


def test_finished_step_is_completed_while_job_keeps_running(monkeypatch):
    """Record a finished step as completed without ending the job."""
    module = load_data_management_module(monkeypatch)
    recorded = capture_progress_events(monkeypatch, module)
    job = build_job()

    saved = module._complete_job_step(job, "Cosmos DB export step completed", 1, 4, "cosmos")

    assert len(recorded) == 1
    assert recorded[0]["step_name"] == "cosmos"
    assert recorded[0]["status"] == "completed"
    assert recorded[0]["job_status"] == "running", "Completing a step must not end the job."
    assert saved["status"] == "running"
    assert saved["progress"]["completed_steps"] == 1


def test_in_progress_step_still_reports_running(monkeypatch):
    """Keep the running badge for steps that have only started."""
    module = load_data_management_module(monkeypatch)
    recorded = capture_progress_events(monkeypatch, module)
    job = build_job()

    module._set_job_progress(job, "Migrating Cosmos records", 4, 10, current_step="cosmos")

    assert recorded[0]["status"] == "running"
    assert recorded[0]["job_status"] == "running"


def test_terminal_job_progress_stamps_terminal_step_status(monkeypatch):
    """Let an explicit terminal job status flow through to the final event."""
    module = load_data_management_module(monkeypatch)
    recorded = capture_progress_events(monkeypatch, module)
    job = build_job()

    module._set_job_progress(
        job,
        "Restore completed",
        4,
        4,
        current_step="completed",
        status=module.DATA_MANAGEMENT_STATUS_COMPLETED_WITH_WARNINGS,
    )

    assert recorded[0]["status"] == "completed_with_warnings"
    assert recorded[0]["job_status"] == "completed_with_warnings"


@pytest.mark.parametrize("message", [
    "Cosmos DB export step completed",
    "AI Search export step completed",
    "Source blob export step completed",
    "Cosmos restore step completed",
    "AI Search restore step completed",
    "Source blob restore step completed",
    "Cosmos migration completed",
    "AI Search migration completed",
    "Source blob migration completed",
    "Migration inventory completed",
    "Migration reconciliation completed",
    "Destination migration preflight completed",
])
def test_step_completions_use_the_completed_step_helper(message):
    """Keep every step-completion call site on the completed-status helper."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    call_index = source.index(f'"{message}"')
    call_start = source.rindex("\n", 0, source.rindex("(", 0, call_index))
    call = source[call_start:call_index]
    assert "_complete_job_step" in call, (
        f"'{message}' must be recorded with _complete_job_step, got: {call.strip()}"
    )


def test_migration_outcome_events_are_not_stamped_running():
    """Stop labeling finished migration outcomes with the running job status."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    outcome_events = [
        '"migration-plan"',
        '"migration-preflight"',
        '"migration-reconciliation"',
        'f"migration-cosmos-{target_type}"',
    ]
    for event in outcome_events:
        event_index = source.index(event)
        block = source[event_index:event_index + 260]
        assert "DATA_MANAGEMENT_STATUS_COMPLETED" in block, (
            f"{event} records finished work and must not use the running status."
        )
        assert "status=DATA_MANAGEMENT_STATUS_RUNNING" not in block


def test_terminal_jobs_hide_live_current_container():
    """Stop showing 'Current container: Waiting' once a job has finished."""
    source = ADMIN_JS_PATH.read_text(encoding="utf-8")
    assert "function isTerminalJobStatus(status)" in source
    for status in ("completed", "completed_with_warnings", "failed", "canceled"):
        assert f'"{status}"' in source

    metrics_index = source.index("function getBackupLiveMetrics(job)")
    metrics_block = source[metrics_index:metrics_index + 1400]
    guard_index = metrics_block.index("isTerminalJobStatus(job?.status)")
    current_container_index = metrics_block.index('label: "Current container"')
    assert guard_index < current_container_index, (
        "Current container must be gated behind the terminal-status guard."
    )
    assert "if (!isTerminalJobStatus(job?.status))" in metrics_block


def test_step_status_fix_ships_in_supported_version():
    """Keep the fix traceable to the version that introduced it."""
    assert_app_version_at_least("0.260.003")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
