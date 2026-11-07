# test_workflow_repeat_execution.py
"""
Production-backed post-body Repeat state, batching and mixed-path regressions.
Version: 0.261.120
Implemented in: 0.261.120

The real compiler, journal, execution units and result store use closed fictional
fixtures. No model, credentials, Azure service, or publication destination is used.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Production imports follow the isolated worktree import setup.
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_execution import WorkflowSuspended, workflow_execution_scope
from functions_workflow_flow_runner import WorkflowFlowRunner
from functions_workflow_identity import workflow_execution_id
from functions_workflow_iterations import authorize_iteration_path
from functions_workflow_node_results import load_workflow_node_input, open_workflow_record_input
from functions_workflow_repeat_history import workflow_repeat_iterations_page, workflow_repeat_state_page
from functions_workflow_results import build_workflow_task_result, persist_workflow_task_result, workflow_result_summary
from functions_workflow_runtime import queue_durable_workflow_run
from functions_workflow_runtime_store import WorkflowRuntimeConflict, WorkflowRuntimeLease, WorkflowRuntimeStore
from functions_workflow_structured_execution import StructuredWorkflowExecution
from functions_workflow_validation import validate_workflow_task_output
from test_workflow_for_each_execution import LoopJournalContainer
from test_workflow_runtime_integration import integration  # noqa: F401
from test_workflow_structured_flow import binding, create_structured_runtime, task


def state_binding(name="state", loop_id="repeat", *, slot="state", kind="json", allow_partial=False):
    return {
        "name": name, "source": {"kind": "repeat_state", "loop_id": loop_id, "state_name": slot, "scope": "current"},
        "required": True, "expected_kind": kind, "allow_partial": allow_partial,
    }


def repeat_definition(maximum=25):
    contract = {"kind": "json", "schema": {
        "type": "object", "required": ["count", "ready"],
        "properties": {"count": {"type": "integer"}, "ready": {"type": "boolean"}},
    }}
    return {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "runner_type": "model", "chat_capabilities_enabled": False,
        "limits": {"max_executions": 5000, "deadline_seconds": 86400},
        "error_handling": {"strategy": "halt", "retry_count": 0},
        "tasks": [task("source", contract=contract), task("body", inputs=[state_binding()], contract=contract)],
        "flow": {"id": "root", "nodes": [
            {"id": "source-node", "kind": "task", "task_id": "source"},
            {"id": "repeat", "kind": "repeat_until", "max_iterations": maximum,
             "state": [{"name": "state", "initial": {"kind": "node_output", "node_id": "source-node",
                                                   "output": "json", "scope": "current"},
                        "next": "next", "output_contract": contract}],
             "body": {"id": "body-region", "nodes": [{"id": "body-node", "kind": "task", "task_id": "body"}],
                      "outputs": [binding("body-node", "next", "json")]},
             "until": {"op": "eq", "left": {"input": "state", "path": "/ready"}, "right": {"literal": True}},
             "exports": [{"name": "state", "output": "next"}]},
        ], "outputs": [binding("repeat", "answer", "state")]},
    }


def repeat_runtime(monkeypatch, *, definition=None, maximum=25, policy=25):
    monkeypatch.setattr("test_workflow_structured_flow.JournalContainer", LoopJournalContainer)
    original = WorkflowRuntimeStore.initialize

    def initialize(self, **options):
        return original(self, **{**options, "repeat_policy": {"max_iterations": policy}})

    monkeypatch.setattr(WorkflowRuntimeStore, "initialize", initialize)
    workflow, store, container, clock = create_structured_runtime(definition or repeat_definition(maximum), monkeypatch)
    for module in (
        "functions_workflow_iterations", "functions_workflow_repeat_state", "functions_workflow_loop_history",
        "functions_workflow_execution_history", "functions_workflow_repeat_history",
    ):
        monkeypatch.setattr(f"{module}.workflow_runtime_store", lambda *args: store)
    events = []
    monkeypatch.setattr("functions_workflow_repeat_execution.log_repeat_event", lambda _, value: events.append(copy.deepcopy(value)))
    monkeypatch.setattr("functions_workflow_repeat_state.log_repeat_event", lambda _, value: events.append(copy.deepcopy(value)))
    return workflow, store, container, clock, events


def execute_repeat(workflow, store, *, target=1, initial_ready=False, calls=None, result_for_task=None,
                   interrupt_at=None, stream_collections=False, replay_safe=True, envelope_transform=None):
    calls = calls if calls is not None else []
    outcomes = []
    with WorkflowRuntimeLease(store, owner_id="repeat-worker") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run", settings={})
        with workflow_execution_scope(execution):
            flow = WorkflowFlowRunner(workflow, "run", execution, outcomes, actor_user_id="owner", settings={})
            for current in flow.tasks():
                if current["id"] == "body" and execution.iteration_path[-1].get("iteration") == interrupt_at:
                    raise SystemExit("Fictional worker interruption.")
                resolved = flow.resolve(current["inputs"], stream_collections=stream_collections)

                def invoke():
                    calls.append((current["id"], copy.deepcopy(execution.iteration_path), execution.execution_id()))
                    if result_for_task is not None:
                        return result_for_task(current, resolved, execution)
                    if current["id"] == "source":
                        value = {"count": 0, "ready": initial_ready}
                    else:
                        count = resolved["values"]["state"]["count"] + 1
                        value = {"count": count, "ready": count >= target}
                    return {"reply": "", "authoritative_result": {"kind": "json", "value": value}}

                result = execution.run_unit(
                    f"task:{current['id']}", invoke,
                    inputs={"task": current, "consumed_inputs": resolved["consumed_inputs"],
                            "iteration_inputs": resolved["iteration_inputs"]},
                    replay_safe=replay_safe, approval=current.get("approval"),
                )
                attempt = execution.unit(f"task:{current['id']}")["attempt"]
                envelope = build_workflow_task_result(result, workflow=workflow, run_id="run", task=current, attempt_count=attempt)
                envelope["consumed_inputs"] = resolved["consumed_inputs"]
                envelope["workflow_validation"] = validate_workflow_task_output(envelope, current["output_contract"])
                if envelope_transform:
                    envelope_transform(current, envelope)
                manifest, reference = persist_workflow_task_result(
                    envelope, workflow=workflow, run_id="run", task_id=current["id"], settings={},
                )
                summary = workflow_result_summary(manifest, reference)
                outcomes.append({
                    "task": current, "status": "succeeded", "attempt_count": attempt,
                    "execution_id": execution.execution_id(), "iteration_path": copy.deepcopy(execution.iteration_path),
                    "consumed_inputs": resolved["consumed_inputs"],
                    "result": {**result, "workflow_result": summary, "workflow_validation": envelope["workflow_validation"]},
                })
            return flow, calls


def repeat_head(workflow, store):
    return store.journal_read("loop", workflow_execution_id(workflow, "run", "repeat"))["payload"]


def continue_repeat(store, request_id="manual-batch"):
    control = store.read()
    return store.decide(
        expected_version=control["version"], gate_id=control["gate"]["id"], choice="continue_repeat",
        actor_user_id="owner", request_id=request_id,
    )


@pytest.mark.parametrize("target,initial_ready", [(1, True), (1, False), (2, True), (3, False), (25, False)])
def test_repeat_runs_post_body_and_exports_only_last_exact_producer(monkeypatch, target, initial_ready):
    workflow, store, _, _, events = repeat_runtime(monkeypatch)
    flow, calls = execute_repeat(workflow, store, target=target, initial_ready=initial_ready)
    assert flow.finished and not flow.failed and not events
    body = [call for call in calls if call[0] == "body"]
    assert len(body) == target and [call[1][-1]["iteration"] for call in body] == list(range(target))
    receipt = flow.final_outputs[0]
    assert "task_id" not in receipt["producer"]
    payload, _ = load_workflow_node_input(
        workflow, "run", receipt["producer"], receipt["result_ref"], output_name="state",
    )
    assert json.loads(payload)["value"] == {"count": target, "ready": True}
    head = repeat_head(workflow, store)
    assert head["completed_count"] == target and head["state"] == "completed"
    assert store.read()["admitted_count"] == 2 + target * 2
    assert len(json.dumps(store.read())) < 16384 and len(json.dumps(head)) < 8192


def test_exhausted_batch_requires_explicit_idempotent_grant(monkeypatch):
    workflow, store, _, clock, events = repeat_runtime(monkeypatch, maximum=2)
    calls = []
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=3, calls=calls)
    control = store.read()
    assert control["state"] == "paused" and control["gate"]["reason_code"] == "repeat_iteration_limit"
    assert control["gate"]["choices"] == ["continue_repeat", "cancel"]
    head = repeat_head(workflow, store)
    assert head["completed_count"] == 2 and head["exhaustion_count"] == 1
    assert store.journal_read("execution", head["execution_id"])["payload"].get("workflow_result") is None
    with pytest.raises(WorkflowRuntimeConflict):
        store.decide(expected_version=control["version"], gate_id=control["gate"]["id"],
                     choice="resume", actor_user_id="owner", request_id="not-a-grant")
    queued = continue_repeat(store)
    duplicate = store.decide(
        expected_version=control["version"], gate_id=control["gate"]["id"], choice="continue_repeat",
        actor_user_id="owner", request_id="manual-batch",
    )
    assert duplicate["version"] == queued["version"]
    with pytest.raises(WorkflowRuntimeConflict):
        store.decide(expected_version=control["version"], gate_id=control["gate"]["id"],
                     choice="continue_repeat", actor_user_id="owner", request_id="stale-tab")
    clock.advance()
    flow, _ = execute_repeat(workflow, store, target=3, calls=calls)
    assert flow.finished and len([call for call in calls if call[0] == "body"]) == 3
    assert [call[1][-1]["iteration"] for call in calls if call[0] == "body"] == [0, 1, 2]
    assert repeat_head(workflow, store)["continuation_count"] == 1
    assert store.read()["repeat_counts"] == {"exhaustion_count": 1, "continuation_count": 1}
    assert len(events) == 2 and events[0]["event_id"] != events[1]["event_id"]


def test_unsealed_or_substituted_repeat_path_is_not_authorized(monkeypatch):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch)
    flow, _ = execute_repeat(workflow, store, target=2)
    receipt = flow.final_outputs[0]
    boundary = store.journal_read("execution", receipt["producer"]["execution_id"])["payload"]["workflow_result"]
    source = boundary["outputs"]["state"]["selected_producer"]["producer"]
    for forged in (
        {**source, "iteration_path": [{"loop_id": "repeat", "iteration": 1001}]},
        {**source, "iteration_path": [{"loop_id": "repeat", "iteration": 0}]},
        {
            **source, "iteration_path": [{"loop_id": "repeat", "iteration": 1001}],
            "execution_id": workflow_execution_id(workflow, "run", source["node_id"], [{"loop_id": "repeat", "iteration": 1001}]),
        },
    ):
        with pytest.raises(AnalysisResultUnavailable):
            authorize_iteration_path(workflow, "run", forged, reader_user_id="owner", store=store)


def test_admin_policy_rejects_authored_maximum_without_clamping(monkeypatch):
    with pytest.raises(WorkflowRuntimeConflict) as error:
        repeat_runtime(monkeypatch, maximum=26, policy=25)
    assert error.value.code == "repeat_policy_exceeded"


def test_queue_rejects_above_policy_before_writing_a_definition_snapshot(integration, monkeypatch):
    workflow, _, services, _, _, requests = integration
    workflow.clear()
    workflow.update(repeat_definition(26))
    services["definitions"].upsert_item(workflow)
    writes = []

    def unexpected_snapshot(*args, **kwargs):
        writes.append(True)
        raise AssertionError("An unadmitted Repeat must not create result-store data.")

    monkeypatch.setattr("functions_workflow_runtime.save_workflow_runtime_result", unexpected_snapshot)
    with pytest.raises(WorkflowRuntimeConflict) as error:
        queue_durable_workflow_run(workflow, actor_user_id="owner")
    assert error.value.code == "repeat_policy_exceeded" and writes == [] and requests == []
    assert services["runs"].items == {}


def test_real_thousand_round_batch_then_lifetime_round_1001(monkeypatch):
    workflow, store, _, clock, _ = repeat_runtime(monkeypatch, maximum=1000, policy=1000)
    calls = []
    with pytest.raises(WorkflowSuspended):
        execute_repeat(workflow, store, target=1001, calls=calls)
    first = [call for call in calls if call[0] == "body"]
    assert len(first) == 1000 and first[-1][1][-1]["iteration"] == 999
    before = store.read()
    assert before["admitted_count"] == 2002 and repeat_head(workflow, store)["next_iteration"] == 1000
    continue_repeat(store)
    assert store.read()["deadline_at"] == before["deadline_at"]
    clock.advance()
    flow, _ = execute_repeat(workflow, store, target=1001, calls=calls)
    last = [call for call in calls if call[0] == "body"]
    assert flow.finished and len(last) == 1001 and last[-1][1][-1]["iteration"] == 1000
    assert last[-1][2] not in {call[2] for call in first}
    assert store.read()["admitted_count"] == 2004
    assert store.read()["journal_counts"]["execution"] > 1000
    repeat_id = repeat_head(workflow, store)["execution_id"]
    page = workflow_repeat_iterations_page(workflow, "run", repeat_id, reader_user_id="owner", limit=2)
    assert len(page["iterations"]) == 2 and page["total_count"] == 1001 and page["next_cursor"]
    state = workflow_repeat_state_page(workflow, "run", repeat_id, 1000, reader_user_id="owner", phase="after")
    assert state["available"] and state["states"][0]["source"]["iteration_path"][-1]["iteration"] == 1000
