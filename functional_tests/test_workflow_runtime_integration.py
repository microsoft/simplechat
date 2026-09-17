# test_workflow_runtime_integration.py
"""
Functional tests for durable submission and the actual workflow runner.
Version: 0.261.111
Implemented in: 0.261.111

Queue, recreated worker, task checkpoint, approval, and projections run through
production functions with isolated service boundaries and deterministic data.
"""

import copy
import sys
import types

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceExistsError, CosmosResourceNotFoundError

from test_workflow_durable_execution import RuntimeContainer, Clock
from test_workflow_task_result_handoff import build_inventory_run
from functions_workflow_execution import (
    assert_workflow_execution_owned,
    current_workflow_execution,
    workflow_checkpoint_scope_guard,
)
from functions_workflow_runtime_store import WorkflowRuntimeConflict, WorkflowRuntimeStore
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_results import (
    authorize_workflow_task_result_read,
    load_workflow_task_input,
    persist_workflow_task_result,
)
import functions_workflow_runtime as runtime


class ServiceContainer(RuntimeContainer):
    def __init__(self, partition_field="user_id"):
        super().__init__()
        self.partition_field = partition_field

    def create_item(self, body):
        key = (body[self.partition_field], body["id"])
        if key in self.items:
            raise CosmosResourceExistsError(status_code=409)
        return self._store(key, body)

    def replace_item(self, item, body, **kwargs):
        key = (body[self.partition_field], item)
        if key not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        if self.items[key]["_etag"] != kwargs.get("etag"):
            raise CosmosHttpResponseError(status_code=412)
        return self._store(key, body)

    def upsert_item(self, body):
        return self._store((body[self.partition_field], body["id"]), body)


class SynchronousLease:
    """Drive the real journal synchronously; renewable heartbeat has its own tests."""

    def __init__(self, store, owner_id):
        self.store = store
        self.owner_id = owner_id
        self.token = None

    def __enter__(self):
        self.token = self.store.claim(owner_id=self.owner_id)
        return self

    def check(self):
        return self.store.assert_owned(self.token)

    def __exit__(self, *args):
        if self.token:
            try:
                self.store.release(self.token)
            except WorkflowRuntimeConflict:
                # The production owner was already released by a wait/terminal
                # transition. No application work is recovered by this fixture.
                return False
        return False


@pytest.fixture
def integration(monkeypatch):
    runner, workflow, records, requests, artifacts, task_items = build_inventory_run(10)
    workflow.update(definition_version=2, durable_execution=True)
    definitions = ServiceContainer()
    runs = ServiceContainer()
    controls = RuntimeContainer()
    clock = Clock()
    result_store = WorkflowResultStore(controls)

    def save_result(workflow, run_id, task_id, result, **kwargs):
        return result_store.save(workflow, run_id, task_id, result)

    load_result = result_store.load
    definitions.create_item(workflow)
    services = {
        "definitions": definitions, "runs": runs, "partition": "owner",
        "load_workflow": lambda: definitions.read_item(item=workflow["id"], partition_key="owner"),
        "settings": lambda: {"allow_user_workflows": True},
    }
    make_store = lambda wf, run_id: WorkflowRuntimeStore(controls, wf, run_id, clock=clock)
    monkeypatch.setattr(runtime, "_services", lambda wf: services)
    monkeypatch.setattr(runtime, "_authorize_execution", lambda *args: None)
    monkeypatch.setattr(runtime, "workflow_runtime_store", make_store)
    monkeypatch.setattr(runtime, "save_workflow_task_result", save_result)
    monkeypatch.setattr(runtime, "load_workflow_task_result", load_result)
    monkeypatch.setattr(runtime, "WorkflowRuntimeLease", SynchronousLease)
    actual_controller = runtime.DurableWorkflowExecution
    monkeypatch.setattr(runtime, "DurableWorkflowExecution", lambda *args, **kwargs: actual_controller(
        *args, **kwargs, save_result=save_result, load_result=load_result,
    ))
    runner.update({
        "WorkflowRunCancelledError": type("WorkflowRunCancelledError", (BaseException,), {}),
        "_save_workflow_run_record": lambda wf, record: (
            workflow_checkpoint_scope_guard(record), runs.upsert_item(record)
        )[1],
        "_save_workflow_run_item_record": lambda wf, item: (
            assert_workflow_execution_owned(), task_items.update({item["id"]: copy.deepcopy(item)})
        )[1],
        "_execute_workflow_file_sync": lambda *args: None,
        "_ensure_workflow_conversation": lambda wf: {"id": "conversation-inventory", "user_id": "owner"},
        "_create_user_message": lambda *args: {"id": "user-message"},
        "_initialize_workflow_assistant_tracking": lambda *args: ("assistant-message", None),
        "_prepare_workflow_url_access_context": lambda *args, **kwargs: {},
        "_attach_workflow_url_access_result": lambda result, context: result,
        "_create_assistant_message": lambda *args, **kwargs: {"id": "assistant-message"},
        "_mirror_workflow_visualizations_to_created_conversations": lambda *args: None,
        "_add_workflow_activity_thought": lambda *args, **kwargs: None,
        "_create_workflow_priority_alert": lambda *args, **kwargs: None,
        "log_workflow_run": lambda **kwargs: None,
        "get_settings": lambda: {"allow_user_workflows": True},
        "get_personal_workflow_run": lambda user_id, run_id: runs.read_item(item=run_id, partition_key=user_id),
        "get_personal_workflow": lambda user_id, workflow_id: services["load_workflow"](),
        "get_workflow_alert_signals": lambda: [],
        "persist_workflow_task_result": lambda envelope, **kwargs: persist_workflow_task_result(
            envelope, save_result=save_result, **kwargs,
        ),
        "load_workflow_task_input": lambda *args, **kwargs: load_workflow_task_input(
            *args, load_result=load_result, **kwargs,
        ),
        "authorize_workflow_task_result_read": lambda *args, **kwargs: authorize_workflow_task_result_read(
            *args, load_result=load_result, **kwargs,
        ),
    })
    module = types.ModuleType("functions_workflow_runner")
    module.run_personal_workflow = lambda wf, **kwargs: runner["_run_personal_workflow_impl"](wf, **kwargs)
    monkeypatch.setitem(sys.modules, "functions_workflow_runner", module)
    return workflow, runner, services, make_store, clock, requests


def test_submission_is_idempotent_and_does_not_call_the_model(integration):
    workflow, runner, services, make_store, clock, requests = integration
    request_id = "63e581a5-a430-4821-b1f4-1398e214fa53"
    first = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner", request_id=request_id)
    second = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner", request_id=request_id)
    assert first["run"]["id"] == second["run"]["id"]
    assert first["run"]["status"] == "queued"
    assert services["load_workflow"]()["active_run_id"] == first["run"]["id"]
    assert requests == []


def test_background_runner_completes_and_clears_the_active_pointer(integration):
    workflow, runner, services, make_store, clock, requests = integration
    queued = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")
    run_id = queued["run"]["id"]
    runtime.continue_durable_workflow_run(workflow, run_id)
    record = services["runs"].read_item(item=run_id, partition_key="owner")
    assert record["status"] == "completed"
    assert record["durable_execution"] is True
    assert services["load_workflow"]()["active_run_id"] == ""
    assert services["load_workflow"]()["conversation_id"] == "conversation-inventory"
    assert make_store(workflow, run_id).read()["state"] == "completed"
    assert len(requests) == 2


def test_submission_replay_after_completion_retains_the_original_snapshot(integration):
    workflow, runner, services, make_store, clock, requests = integration
    request_id = "442f2e0b-63ad-4347-8e73-1be93b4e6b61"
    queued = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner", request_id=request_id)
    run_id = queued["run"]["id"]
    original = make_store(workflow, run_id).read()["snapshot_ref"]
    runtime.continue_durable_workflow_run(workflow, run_id)
    repeated = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner", request_id=request_id)
    assert repeated["run"]["id"] == run_id
    assert repeated["run"]["status"] == "completed"
    assert make_store(workflow, run_id).read()["snapshot_ref"] == original
    assert len(requests) == 2


def test_file_sync_without_changes_remains_skipped_not_failed(integration):
    workflow, runner, services, make_store, clock, requests = integration
    runner["_execute_workflow_file_sync"] = lambda *args: {"enabled": True, "should_continue": False}
    run_id = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")["run"]["id"]
    runtime.continue_durable_workflow_run(workflow, run_id)
    assert make_store(workflow, run_id).read()["state"] == "skipped"
    assert services["runs"].read_item(item=run_id, partition_key="owner")["success"] is True
    assert services["load_workflow"]()["active_run_id"] == ""
    assert not requests


def test_approval_survives_a_worker_restart_without_repeating_first_task(integration):
    workflow, runner, services, make_store, clock, requests = integration
    workflow["tasks"][1]["approval"] = {"required": True, "message": "Review the synthesis inputs."}
    services["definitions"].upsert_item(workflow)
    queued = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")
    run_id = queued["run"]["id"]
    runtime.continue_durable_workflow_run(workflow, run_id)
    waiting = make_store(workflow, run_id).read()
    assert waiting["state"] == "waiting_approval"
    assert len(requests) == 1
    assert services["load_workflow"]()["active_run_id"] == run_id
    make_store(workflow, run_id).decide(
        expected_version=waiting["version"], gate_id=waiting["gate"]["id"],
        choice="approve", actor_user_id="owner", request_id="approval-request",
    )
    clock.advance()
    runtime.continue_durable_workflow_run(workflow, run_id)
    assert len(requests) == 2
    assert make_store(workflow, run_id).read()["state"] == "completed"
    assert services["load_workflow"]()["run_count"] == 1


def test_queue_race_does_not_replace_a_different_active_run(integration):
    workflow, runner, services, make_store, clock, requests = integration
    queued = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")
    with pytest.raises(WorkflowRuntimeConflict):
        runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")
    assert services["load_workflow"]()["active_run_id"] == queued["run"]["id"]
    assert services["load_workflow"]()["status"] == "queued"
    assert len(services["runs"].items) == 1
    assert requests == []


def test_cancel_returns_actual_projected_definition_not_a_synthetic_state(integration):
    workflow, runner, services, make_store, clock, requests = integration
    queued = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")
    result = runtime.cancel_durable_workflow_run(workflow, queued["run"]["id"], actor_user_id="owner")
    assert result["workflow"] == services["load_workflow"]()
    assert result["run"]["status"] == "cancelled"
    assert result["workflow"]["active_run_id"] == ""
    assert requests == []


def test_old_terminal_projection_cannot_clear_a_requeued_run(integration):
    workflow, runner, services, make_store, clock, requests = integration
    run_id = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner")["run"]["id"]
    store = make_store(workflow, run_id)
    token = store.claim(owner_id="failed-worker")
    old = store.transition(token, state="failed")
    resumed = store.resume(expected_version=old["version"], actor_user_id="owner", request_id="resume")
    runtime._bind_active_run(services, workflow, run_id, runtime_version=resumed["version"])
    runtime._project_runtime_run(services, workflow, run_id, old)
    current = services["load_workflow"]()
    assert current["active_run_id"] == run_id
    assert current["status"] == "queued"
    assert current["active_runtime_version"] == resumed["version"]


def test_deletion_marker_blocks_new_run_admission(integration):
    workflow, runner, services, make_store, clock, requests = integration
    services["definitions"].upsert_item({**workflow, "deleting": True})
    with pytest.raises(WorkflowRuntimeConflict, match="being deleted"):
        runtime._bind_active_run(services, workflow, "new-run")
    assert not services["load_workflow"]().get("active_run_id")


@pytest.mark.parametrize("request_id", [False, 12, "", "not-a-uuid"])
def test_invalid_request_ids_do_not_start_a_new_run(integration, request_id):
    workflow, runner, services, make_store, clock, requests = integration
    with pytest.raises(ValueError):
        runtime.queue_durable_workflow_run(workflow, actor_user_id="owner", request_id=request_id)
    assert not services["runs"].items
