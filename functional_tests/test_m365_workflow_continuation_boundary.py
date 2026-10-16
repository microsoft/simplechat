# test_m365_workflow_continuation_boundary.py
"""
Functional regressions for authoritative workflow deletion and scheduler isolation.
Version: 0.261.341
Implemented in: 0.261.341

Real Cosmos SDK point reads exercise the loader; real continuation dispatch exercises
the scheduler callbacks with closed workflow execution and connection boundaries.
"""

import ast
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
import uuid

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError
import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Standalone tests install application paths before loading the runtime owners.
from functions_m365_context import M365PolicyError
from functions_m365_continuations import M365ContinuationNotStarted, resume_pending_workflows
from functions_m365_workflow_binding import M365_ACTIVE_STATES
from test_m365_continuations import Approvals, PendingJobs
from test_m365_cosmos_sdk_contract import cosmos_factory, load_runtime


def workflow_config(container):
    config = ModuleType("config")
    config.cosmos_group_workflows_container = container
    config.cosmos_personal_workflows_container = container
    return config


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_authoritative_workflow_loader_uses_scoped_sdk_read_and_preserves_projection(cosmos_factory, scope):
    partition_field = "group_id" if scope == "group" else "user_id"
    http, container = cosmos_factory(partition_field)
    record = {"id": "workflow", "user_id": "owner", "status": "awaiting_approval", "tasks": []}
    if scope == "group":
        record["group_id"] = "group"
    http.seed(record)
    runtime = load_runtime("functions_m365_runtime", container)
    with patch.dict(sys.modules, {"config": workflow_config(container)}):
        current = runtime.load_current_workflow(record)
    assert type(current) is dict
    assert current["id"] == record["id"]
    assert current["status"] == "awaiting_approval"
    assert current["definition_revision"]
    assert not any(key.startswith("_") for key in current)
    method, _path, headers = http.calls[-1]
    assert method == "GET"
    assert headers["x-ms-documentdb-partitionkey"] == f'["{record[partition_field]}"]'


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("deleted", ["not_found", "deleting_flag", "deleting_status"])
def test_only_authoritative_absence_or_tombstone_reports_workflow_missing(cosmos_factory, scope, deleted):
    http, container = cosmos_factory("group_id" if scope == "group" else "user_id")
    reference = {"id": "workflow", "user_id": "owner"}
    if scope == "group":
        reference["group_id"] = "group"
    if deleted != "not_found":
        http.seed({
            **reference, "deleting": deleted == "deleting_flag",
            "status": "deleting" if deleted == "deleting_status" else "awaiting_approval",
        })
    runtime = load_runtime("functions_m365_runtime", container)
    with patch.dict(sys.modules, {"config": workflow_config(container)}):
        with pytest.raises(M365PolicyError) as failure:
            runtime.load_current_workflow(reference)
    assert failure.value.code == "m365_workflow_missing"


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("error", [
    PermissionError("The workflow no longer exists."),
    CosmosHttpResponseError(status_code=403, message="access denied"),
    CosmosHttpResponseError(status_code=429, message="throttled"),
    CosmosHttpResponseError(status_code=503, message="storage unavailable"),
])
def test_loader_does_not_translate_authorization_or_storage_failure_into_deletion(cosmos_factory, scope, error):
    _http, container = cosmos_factory("group_id" if scope == "group" else "user_id")
    runtime = load_runtime("functions_m365_runtime", container)
    reference = {"id": "workflow", "user_id": "owner"}
    if scope == "group":
        reference["group_id"] = "group"
    with patch.dict(sys.modules, {"config": workflow_config(container)}):
        with patch.object(container, "read_item", side_effect=error):
            with pytest.raises(type(error)) as failure:
                runtime.load_current_workflow(reference)
    assert failure.value is error


def test_loader_rejects_invalid_sdk_response_instead_of_classifying_it_as_missing(cosmos_factory):
    _http, container = cosmos_factory("user_id")
    runtime = load_runtime("functions_m365_runtime", container)
    with patch.dict(sys.modules, {"config": workflow_config(container)}):
        with patch.object(container, "read_item", return_value=None):
            with pytest.raises(TypeError):
                runtime.load_current_workflow({"id": "workflow", "user_id": "owner"})

@pytest.mark.parametrize("scope", ["personal", "group"])
def test_loader_rejects_a_response_for_a_different_scope(cosmos_factory, scope):
    _http, container = cosmos_factory("group_id" if scope == "group" else "user_id")
    runtime = load_runtime("functions_m365_runtime", container)
    reference = {"id": "workflow", "user_id": "owner"}
    if scope == "group":
        reference["group_id"] = "group"
    response = {**reference, "group_id" if scope == "group" else "user_id": "another-scope"}
    with patch.dict(sys.modules, {"config": workflow_config(container)}):
        with patch.object(container, "read_item", return_value=response):
            with pytest.raises(PermissionError):
                runtime.load_current_workflow(reference)


def scheduler_callbacks(jobs, load_workflow, runner, events):
    names = (
        "configure_m365_execution", "configure_m365_connection_authorization",
        "configure_m365_file_runtime", "configure_m365_pending_delivery_runtime",
        "dispatch_due_m365_deliveries", "validate_m365_approval_decision",
        "validate_m365_workflow_execution", "resolve_m365_action_config",
        "resolve_m365_workflow_binding", "resolve_m365_action_selection",
        "validate_m365_workflow_context",
    )
    namespace = {name: Mock() for name in names}
    namespace.update(
        M365PolicyError=M365PolicyError, M365ContinuationNotStarted=M365ContinuationNotStarted,
        M365_ACTIVE_STATES=M365_ACTIVE_STATES,
        get_m365_approval_service=Approvals,
        _get_workflow_runner_app=lambda: SimpleNamespace(test_request_context=nullcontext),
        load_current_workflow=load_workflow,
        get_settings=lambda: {"allow_user_workflows": True},
        acquire_distributed_task_lock=Mock(return_value={"id": "workflow-lock"}),
        release_distributed_task_lock=Mock(),
        resume_m365_durable_workflow_run=runner,
        run_group_workflow=runner, run_personal_workflow=runner,
        update_group_workflow_runtime_fields=Mock(), update_personal_workflow_runtime_fields=Mock(),
        workflow_result_runtime_status=lambda result: "idle",
        workflow_result_is_waiting=lambda result: True,
        resume_pending_workflows=resume_pending_workflows,
        cosmos_m365_execution_runs_container=jobs,
        log_event=lambda *args, **kwargs: events.append((args, kwargs)),
    )
    path = APP / "background_tasks.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    entrypoint = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                      and node.name == "check_m365_workflow_continuations_once")
    exec(compile(ast.Module(body=[entrypoint], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[entrypoint.name], namespace


@pytest.mark.parametrize("after_execution_started", [False, True])
def test_scheduler_delete_race_distinguishes_no_effects_from_uncertain_execution(after_execution_started):
    jobs = PendingJobs(partition_field="user_id")
    workflows = {}
    for workflow_id in ("deleted-workflow", "valid-workflow"):
        workflow = {
            "id": workflow_id, "user_id": "owner", "m365_run_as_user_id": "reader",
            "active_run_id": f"run-{workflow_id}", "status": "awaiting_approval",
        }
        workflows[workflow_id] = workflow
        jobs.create_item(body={
            "id": f"request-{workflow_id}", "user_id": "reader", "actor_user_id": "owner",
            "workflow_id": workflow_id, "run_id": workflow["active_run_id"],
            "workflow_ref": {"id": workflow_id, "user_id": "owner"},
            "type": "m365_execution_request", "approval_id": "approval",
            "status": "awaiting_approval",
        })
    reads, effects, events = {}, [], []

    def load_workflow(reference):
        workflow_id = reference["id"]
        reads[workflow_id] = reads.get(workflow_id, 0) + 1
        if workflow_id == "deleted-workflow" and not after_execution_started and reads[workflow_id] == 3:
            raise M365PolicyError("m365_workflow_missing", "The workflow no longer exists.")
        return workflows[workflow_id]

    def runner(workflow, **kwargs):
        effects.append(workflow["id"])
        if workflow["id"] == "deleted-workflow":
            raise M365PolicyError("m365_workflow_missing", "The workflow no longer exists.")
        return {"success": True}

    tick, namespace = scheduler_callbacks(jobs, load_workflow, runner, events)
    first = tick()
    repeated = tick()
    stopped = jobs.read_item("request-deleted-workflow", "reader")
    assert stopped["status"] == ("recovery_required" if after_execution_started else "failed")
    assert stopped.get("failure_code") == (None if after_execution_started else "workflow_deleted")
    assert effects == (["deleted-workflow", "valid-workflow"] if after_execution_started else ["valid-workflow"])
    assert [outcome["request_id"] for outcome in first] == ["request-valid-workflow"]
    assert repeated == []
    assert namespace["release_distributed_task_lock"].call_count == (2 if after_execution_started else 1)


def test_scheduler_locks_consume_sdk_mappings_and_keep_conditional_ownership(cosmos_factory):
    http, container = cosmos_factory("id")
    path = APP / "background_tasks.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    names = {"_is_expired_timestamp", "acquire_distributed_task_lock", "release_distributed_task_lock"}
    functions = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = {
        "datetime": datetime, "timedelta": timedelta, "timezone": timezone,
        "uuid": uuid, "logging": logging, "MatchConditions": MatchConditions,
        "_get_lock_holder_id": lambda: "this-worker",
        "cosmos_settings_container": container, "log_event": Mock(),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    lock_id = "background_task_lock_workflow"
    http.seed({
        "id": lock_id, "holder_id": "old-worker",
        "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    })
    acquire = namespace["acquire_distributed_task_lock"]
    release = namespace["release_distributed_task_lock"]
    lock = acquire("workflow", 900)
    blocked = acquire("workflow", 900)
    assert lock["holder_id"] == "this-worker"
    assert blocked is None
    current_etag = http.records[(lock_id, lock_id)]["_etag"]
    release({**lock, "holder_id": "different-worker"})
    assert http.records[(lock_id, lock_id)]["_etag"] == current_etag
    release(lock)
    assert (lock_id, lock_id) not in http.records
    method, _path, headers = http.calls[-1]
    assert method == "DELETE"
    assert headers["If-Match"] == current_etag
    assert headers["x-ms-documentdb-partitionkey"] == f'["{lock_id}"]'


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-p", "no:cacheprovider"]))
