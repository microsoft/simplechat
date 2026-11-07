# test_workflow_durable_entrypoints.py
"""
Functional tests for scheduled and inbound-MCP durable workflow admission.
Version: 0.261.122
Implemented in: 0.261.111

Existing entrypoints queue instead of executing synchronously. Active waits and
queue races never reset another run's progress or claim a completed result.
"""

import logging
from datetime import datetime, timezone

import pytest

from test_analyze_backend_saved_integration import load_functions
from functions_m365_workflow_binding import M365_ACTIVE_STATES
from functions_workflow_runtime_store import WorkflowRuntimeConflict
import functions_workflow_runtime as runtime


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("trigger", ["interval", "file_sync"])
@pytest.mark.parametrize("scenario", ["queue", "waiting", "race", "schedule_write_failure"])
def test_scheduler_respects_durable_admission_and_active_runs(scope, trigger, scenario):
    workflow = {
        "id": "workflow", "user_id": "owner", "durable_execution": True,
        "trigger_type": trigger, "is_enabled": True,
    }
    if scope == "group":
        workflow["group_id"] = "group"
    if scenario == "waiting":
        workflow.update(active_run_id="waiting-run", status="waiting_approval")
    queued, updates, released = [], [], []

    def queue(value, **kwargs):
        queued.append(kwargs)
        workflow.update(active_run_id="active-run", status="queued")
        if scenario == "race":
            raise WorkflowRuntimeConflict("workflow_already_running")
        return {"success": True}

    def update(*args):
        updates.append(args[-1])
        if scenario == "schedule_write_failure":
            raise RuntimeError("Scheduling metadata unavailable.")

    namespace = {
        "M365_ACTIVE_STATES": M365_ACTIVE_STATES,
        "check_m365_workflow_continuations_once": lambda: [],
        "datetime": datetime, "timezone": timezone, "logging": logging,
        "get_settings": lambda: {"allow_user_workflows": True, "allow_group_workflows": True},
        "get_due_personal_workflows": lambda **kwargs: [workflow] if scope == "personal" else [],
        "get_due_group_workflows": lambda **kwargs: [workflow] if scope == "group" else [],
        "get_personal_workflow": lambda *args: workflow,
        "get_group_workflow": lambda *args: workflow,
        "is_group_workflows_enabled_for_group": lambda *args: True,
        "acquire_distributed_task_lock": lambda *args, **kwargs: {"id": "lock"},
        "release_distributed_task_lock": lambda lock: released.append(lock),
        "queue_durable_workflow_run": queue,
        "update_personal_workflow_runtime_fields": update,
        "update_group_workflow_runtime_fields": update,
        "compute_next_run_at": lambda *args, **kwargs: "2026-09-18T00:00:00Z",
        "log_event": lambda *args, **kwargs: None,
        "run_personal_workflow": lambda *args, **kwargs: pytest.fail("Durable execution must not run inline."),
        "run_group_workflow": lambda *args, **kwargs: pytest.fail("Durable execution must not run inline."),
    }
    load_functions("background_tasks.py", {"check_due_workflows_once"}, namespace)
    namespace["check_due_workflows_once"]()
    assert len(queued) == (0 if scenario == "waiting" else 1)
    assert workflow["active_run_id"] == ("waiting-run" if scenario == "waiting" else "active-run")
    assert all(set(value) == {"next_run_at"} for value in updates)
    assert released == [{"id": "lock"}]
    if queued:
        assert queued[0]["actor_user_id"] == "owner"
        assert queued[0]["trigger_source"] == ("file_sync_monitor" if trigger == "file_sync" else "scheduled")


def test_inbound_mcp_reports_accepted_queue_not_completed_execution(monkeypatch):
    workflow = {"id": "workflow", "user_id": "owner", "durable_execution": True}
    calls = []

    def queue(value, **kwargs):
        calls.append((value, kwargs))
        return {"run": {"id": "run", "status": "queued", "success": False}}

    monkeypatch.setattr(runtime, "queue_durable_workflow_run", queue)
    namespace = {
        "_require_delegated_user_id": lambda auth: "owner",
        "_require_personal_workflow_execution_enabled": lambda auth: None,
        "_coerce_workflow_id": lambda args: args["workflow_id"],
        "get_personal_workflow": lambda owner, identifier: workflow,
        "_build_mcp_workflow_invocation_metadata": lambda auth: {"client_id": "trusted-client"},
        "_truncate_workflow_error": lambda value: value or "",
    }
    load_functions(
        "functions_mcp_server_tools.py", {"execute_workflow", "_serialize_workflow_execution_result"}, namespace,
    )
    result = namespace["execute_workflow"]({}, {"workflow_id": "workflow"})
    assert result["accepted"] is True
    assert result["durable_execution"] is True
    assert result["run"]["status"] == "queued"
    assert result["run"]["success"] is False
    assert calls[0][1] == {
        "actor_user_id": "owner", "trigger_source": "inbound_mcp",
        "invocation_metadata": {"client_id": "trusted-client"},
    }
