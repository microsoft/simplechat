# test_workflow_durable_analysis.py
"""
Functional tests for durable workflow and Analyze checkpoint interoperability.
Version: 0.261.111
Implemented in: 0.261.111

Actual runner preparation and both conditional-write fences survive recreated
workers. Interrupted Analyze claims require the precise recovery decision.
"""

import copy
import uuid
from contextvars import Context

import pytest

from test_analyze_backend_saved_integration import load_functions
from test_workflow_durable_execution import Clock, RuntimeContainer
from functions_document_analysis_checkpoints import analysis_checkpoints_for_workflow
from functions_workflow_execution import (
    DurableWorkflowExecution, WorkflowSuspended, current_workflow_execution, workflow_execution_scope,
)
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_runtime_store import WorkflowRuntimeConflict, WorkflowRuntimeLease, WorkflowRuntimeStore


WORKFLOW = {"id": "workflow-analysis", "user_id": "owner", "durable_execution": True}
RUN_ID = "run-analysis"
SOURCE = {"document_id": "source", "scope": "personal", "scope_id": "owner", "source_version": 1}
UNIT = {"work_unit_id": "source-window-1", "source": SOURCE, "status": "completed"}


@pytest.fixture
def analysis_runtime(monkeypatch):
    container = RuntimeContainer()
    store = WorkflowRuntimeStore(container, WORKFLOW, RUN_ID, clock=Clock())
    results = WorkflowResultStore(container)
    snapshot = results.save(WORKFLOW, RUN_ID, "runtime:definition", WORKFLOW)
    store.initialize(snapshot_ref=snapshot, definition_revision="a" * 64, actor_user_id="owner", request_id="submit")

    def factory(*args, **kwargs):
        return analysis_checkpoints_for_workflow(
            *args, **kwargs, store=WorkflowResultStore(container), source_authorizer=lambda *args, **kwargs: True,
        )

    monkeypatch.setattr("functions_document_analysis_checkpoints.analysis_checkpoints_for_workflow", factory)
    namespace = {
        "uuid": uuid, "current_workflow_execution": current_workflow_execution,
        "_get_current_workflow_runtime": lambda wf: copy.deepcopy(wf),
        "_get_workflow_run_record": lambda *args: {"workflow_id": WORKFLOW["id"], "status": "running"},
        "_get_workflow_group_id": lambda wf: None,
        "_raise_if_workflow_run_cancelled": lambda *args: current_workflow_execution().check(),
    }
    load_functions("functions_workflow_runner.py", {"_prepare_workflow_analysis_checkpoints"}, namespace)

    def controller(lease):
        return DurableWorkflowExecution(
            store, lease, WORKFLOW, RUN_ID,
            save_result=lambda wf, run, task, value, **kwargs: results.save(wf, run, task, value),
            load_result=results.load,
        )

    def prepare():
        return namespace["_prepare_workflow_analysis_checkpoints"](WORKFLOW, RUN_ID, "analyze", "owner", {})

    return store, container, controller, prepare


def test_real_runner_reuses_private_analyze_token_after_approval(analysis_runtime):
    store, container, controller, prepare = analysis_runtime
    with WorkflowRuntimeLease(store, owner_id="worker-one") as lease, workflow_execution_scope(controller(lease)):
        first = prepare()
        first.initialize({"instructions": "Extract all records."}, [SOURCE])
        claim = first.claim_unit(UNIT)
        first.commit_unit(claim, UNIT, {"findings": [{"id": "one"}]}, "Final finding.")
        with pytest.raises(WorkflowSuspended):
            current_workflow_execution().run_unit(
                "task:review", lambda: {}, inputs={"source": SOURCE}, approval={"required": True},
            )
    waiting = store.read()
    store.decide(
        expected_version=waiting["version"], gate_id=waiting["gate"]["id"], choice="approve",
        actor_user_id="owner", request_id="approval",
    )
    with WorkflowRuntimeLease(store, owner_id="worker-two") as lease, workflow_execution_scope(controller(lease)):
        restored = prepare()
        assert restored.token == first.token
        restored.initialize({"instructions": "Extract all records."}, [SOURCE])
        assert restored.load_unit(UNIT)["analysis_text"] == "Final finding."


def test_interrupted_analyze_claim_requires_and_honors_recovery(analysis_runtime):
    store, container, controller, prepare = analysis_runtime
    with WorkflowRuntimeLease(store, owner_id="worker-one") as lease, workflow_execution_scope(controller(lease)):
        checkpoints = prepare()

        def interrupted():
            checkpoints.initialize({"instructions": "Extract."}, [SOURCE])
            checkpoints.claim_unit(UNIT)
            raise SystemExit("Worker stopped.")

        with pytest.raises(SystemExit):
            current_workflow_execution().run_unit("task:analyze", interrupted, inputs={"source": SOURCE})
    with WorkflowRuntimeLease(store, owner_id="worker-two") as lease, workflow_execution_scope(controller(lease)):
        prepare()
        with pytest.raises(WorkflowSuspended, match="waiting_recovery"):
            current_workflow_execution().run_unit(
                "task:analyze", lambda: pytest.fail("Replay needs confirmation."), inputs={"source": SOURCE},
            )
    waiting = store.read()
    store.decide(
        expected_version=waiting["version"], gate_id=waiting["gate"]["id"], choice="retry",
        actor_user_id="owner", request_id="confirmed",
    )
    with WorkflowRuntimeLease(store, owner_id="worker-three") as lease, workflow_execution_scope(controller(lease)):
        checkpoints = prepare()

        def recovered():
            checkpoints.initialize({"instructions": "Extract."}, [SOURCE])
            assert checkpoints.load_unit(UNIT) is None
            claim = checkpoints.claim_unit(UNIT)
            checkpoints.commit_unit(claim, UNIT, {"findings": []}, "No findings.")
            return {"reply": "No findings."}

        current_workflow_execution().run_unit("task:analyze", recovered, inputs={"source": SOURCE})
        assert checkpoints.load_unit(UNIT)["analysis_text"] == "No findings."


@pytest.mark.parametrize("operation", ["first_guard", "request", "checkpoint"])
def test_run_deletion_fences_never_prepared_and_existing_analyze_work(analysis_runtime, monkeypatch, operation):
    store, container, controller, prepare = analysis_runtime
    with WorkflowRuntimeLease(store, owner_id="worker") as lease, workflow_execution_scope(controller(lease)):
        execution = current_workflow_execution()
        if operation == "first_guard":
            execution.cache("analysis-token:analyze", {"token": "stable-token"})
            write = prepare
        else:
            checkpoints = prepare()
            if operation == "request":
                write = lambda: checkpoints.initialize({"instructions": "Extract."}, [SOURCE])
            else:
                checkpoints.initialize({"instructions": "Extract."}, [SOURCE])
                write = lambda: checkpoints.claim_unit(UNIT)
        original = container.execute_item_batch
        attempted = []

        def race(batch_operations, partition_key):
            if not attempted:
                store.tombstone()
                attempted.append(copy.deepcopy(container.items))
            return original(batch_operations, partition_key)

        monkeypatch.setattr(container, "execute_item_batch", race)
        with pytest.raises(WorkflowRuntimeConflict):
            write()
        assert container.items == attempted[0]


def test_analyze_store_keeps_run_fence_outside_the_request_context(analysis_runtime):
    store, container, controller, prepare = analysis_runtime
    with WorkflowRuntimeLease(store, owner_id="worker") as lease, workflow_execution_scope(controller(lease)):
        checkpoints = prepare()
        checkpoints.initialize({"instructions": "Extract."}, [SOURCE])
        store.tombstone()
        with pytest.raises(WorkflowRuntimeConflict):
            Context().run(checkpoints.store.claim_analysis_unit, checkpoints.binding, UNIT["work_unit_id"],
                          token=checkpoints.token)
