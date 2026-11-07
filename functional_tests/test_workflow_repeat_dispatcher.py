# test_workflow_repeat_dispatcher.py
"""
Functional tests for post-body Repeat in the production task dispatcher.
Version: 0.261.120
Implemented in: 0.261.120

Exercises real journal, result transport, typed state, and dispatch checkpoints
using a closed model client. Recovery interrupts after the task unit commits but
before its result checkpoint, not merely after a completed flow traversal.
"""

import copy
import json
from types import SimpleNamespace

import pytest

from test_workflow_repeat_execution import repeat_runtime
from test_workflow_repeat_schema import repeat_definition
from test_workflow_result_store import FakeBlobService
from test_workflow_task_result_handoff import build_inventory_run
from functions_workflow_definitions import workflow_definition_revision
from functions_workflow_execution import WorkflowSuspended, current_workflow_execution, workflow_execution_scope
from functions_workflow_results import authorize_workflow_task_result_read, persist_workflow_task_result
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_runtime_store import WorkflowRuntimeLease, WorkflowRuntimeStore
from functions_workflow_structured_execution import StructuredWorkflowExecution


def production_dispatcher(reply):
    runner, _, _, _, _, _ = build_inventory_run()
    calls = []

    def completion(**_kwargs):
        execution = current_workflow_execution()
        selectors = copy.deepcopy(execution.selectors())
        calls.append(selectors)
        content = json.dumps(reply(selectors))
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None,
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    runner.update({
        "get_workflow_alert_signals": lambda: [],
        "_resolve_model_workflow_client": lambda *args, **kwargs: (
            runner["WorkflowModelClient"](client, "gpt-4.1", "aoai"), "gpt-4.1", "aoai",
        ),
        "persist_workflow_task_result": lambda envelope, **kwargs: persist_workflow_task_result(
            envelope, **{**kwargs, "settings": {"max_file_size_mb": 10}},
        ),
        "authorize_workflow_task_result_read": authorize_workflow_task_result_read,
    })
    return runner, calls


def dispatch(runner, workflow, store):
    with WorkflowRuntimeLease(store, owner_id="repeat-dispatcher") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run", settings={})
        with workflow_execution_scope(execution):
            return runner["_execute_workflow_task_sequence"](
                workflow, {}, "conversation", "run", None, {}, actor_user_id="owner",
            )


@pytest.mark.parametrize("initial_ready", [False, True])
@pytest.mark.parametrize("export_final", [False, True])
def test_dispatcher_always_runs_one_body_before_testing_until(monkeypatch, initial_ready, export_final):
    definition = repeat_definition(maximum=1)
    definition["limits"]["max_executions"] = 4
    if not export_final:
        definition["flow"]["nodes"][1]["exports"] = []
        definition["flow"]["outputs"] = []
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=definition)
    runner, calls = production_dispatcher(
        lambda producer: {"ready": True if producer["iteration_path"] else initial_ready},
    )
    result = dispatch(runner, workflow, store)
    assert [entry["iteration_path"] for entry in calls] == [[], [{"loop_id": "repeat", "iteration": 0}]]
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert store.read()["admitted_count"] == 4
    if export_final:
        assert result["workflow_outputs"][0]["producer"]["node_id"] == "repeat"
        assert not result["workflow_outputs"][0]["producer"].get("task_id")
    else:
        assert result["workflow_outputs"] == []


@pytest.mark.parametrize("storage", ["cosmos", "blob"])
def test_dispatcher_crash_gap_preserves_task_ordinal_and_does_not_reinvoke(monkeypatch, storage):
    definition = repeat_definition(maximum=3)
    definition["limits"]["max_executions"] = 6
    workflow, store, container, clock, _ = repeat_runtime(monkeypatch, definition=definition)
    if storage == "blob":
        blobs = FakeBlobService()
        configured = lambda *args, **kwargs: WorkflowResultStore(container, blobs, "private-workflow-results")
        monkeypatch.setattr("functions_workflow_result_store._configured_store", configured)
        monkeypatch.setattr("functions_workflow_result_store._configured_result_store", configured)
    runner, calls = production_dispatcher(lambda producer: {
        "ready": bool(producer["iteration_path"] and producer["iteration_path"][-1]["iteration"] == 1),
    })
    original_persist = runner["persist_workflow_task_result"]
    original_cache = StructuredWorkflowExecution.cache
    interruptions, orders = [], []

    def persist(envelope, **kwargs):
        execution = current_workflow_execution()
        if (
            execution.iteration_path and execution.iteration_path[-1]["iteration"] == 1
            and not interruptions
        ):
            assert execution.unit("task:body")["state"] == "completed"
            assert execution.snapshot("task-result:body") is None
            interruptions.append(execution.execution_id())
            raise SystemExit("Closed worker loss after task-unit commit.")
        return original_persist(envelope, **kwargs)

    def observe_order(execution, key, value):
        retained = original_cache(execution, key, value)
        if key == "task-order:body":
            orders.append((execution.iteration_path[-1]["iteration"], value["order"], retained["order"]))
        return retained

    runner["persist_workflow_task_result"] = persist
    monkeypatch.setattr(StructuredWorkflowExecution, "cache", observe_order)
    with pytest.raises(SystemExit, match="after task-unit commit"):
        dispatch(runner, workflow, store)
    assert len(calls) == 3
    clock.advance()
    result = dispatch(runner, workflow, store)
    assert len(calls) == 3
    assert (1, 2, 3) in orders
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert store.read()["admitted_count"] == 6
    assert store.read()["gate"] is None


def test_cancel_uses_frozen_repeat_identity_after_live_definition_changes(monkeypatch):
    definition = repeat_definition(maximum=2)
    definition["tasks"][1]["approval"] = {"required": True}
    workflow, store, container, clock, _ = repeat_runtime(monkeypatch, definition=definition)
    runner, calls = production_dispatcher(lambda _: {"ready": True})
    with pytest.raises(WorkflowSuspended):
        dispatch(runner, workflow, store)
    assert store.read()["state"] == "waiting_approval" and len(calls) == 1

    edited = copy.deepcopy(workflow)
    edited["flow"]["nodes"] = edited["flow"]["nodes"][:1]
    edited["flow"]["outputs"] = []
    edited["tasks"] = edited["tasks"][:1]
    edited["definition_revision"] = workflow_definition_revision(edited)
    current_store = WorkflowRuntimeStore(container, edited, "run", clock=clock)
    cancelled = current_store.request_cancel(actor_user_id="owner", request_id="cancel-edited-definition")
    assert cancelled["state"] == "cancelled"
    repeat_id = store.read()["repeat_progress"]["execution_id"]
    assert store.journal_read("loop", repeat_id)["payload"]["state"] == "cancelled"
    assert store.journal_read("iteration", [repeat_id, 0])["payload"]["state"] == "cancelled"
