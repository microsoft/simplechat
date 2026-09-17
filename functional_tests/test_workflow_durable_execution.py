# test_workflow_durable_execution.py
"""
Functional tests for restart-safe workflow operation boundaries.
Version: 0.261.111
Implemented in: 0.261.111

The real execution controller and runtime journal use JSON-copying storage.
Completed units are not invoked again; ambiguous external actions and approvals
require persisted, version-bound decisions.
"""

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceExistsError, CosmosResourceNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Application imports follow worktree module-path setup.
from functions_workflow_execution import (
    DurableWorkflowExecution, WorkflowSuspended, workflow_checkpoint_scope_guard, workflow_execution_scope,
)
from functions_workflow_runtime_store import WorkflowRuntimeConflict, WorkflowRuntimeLease, WorkflowRuntimeStore
from test_workflow_result_contract import SerializedSections


WORKFLOW = {"id": "durable-workflow", "user_id": "owner", "durable_execution": True}
RUN_ID = "durable-run"


class RuntimeContainer:
    def __init__(self):
        self.items = {}
        self.version = 0

    def create_item(self, body):
        key = (body["run_id"], body["id"])
        if key in self.items:
            raise CosmosResourceExistsError(status_code=409)
        return self._store(key, body)

    def read_item(self, item, partition_key):
        if (partition_key, item) not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        return copy.deepcopy(self.items[(partition_key, item)])

    def replace_item(self, item, body, etag=None, match_condition=None):
        key = (body["run_id"], item)
        if key not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        if etag != self.items[key]["_etag"] or match_condition != MatchConditions.IfNotModified:
            raise CosmosHttpResponseError(status_code=412)
        return self._store(key, body)

    def _store(self, key, value):
        self.version += 1
        self.items[key] = {**copy.deepcopy(value), "_etag": str(self.version)}
        return copy.deepcopy(self.items[key])

    def execute_item_batch(self, batch_operations, partition_key):
        before = copy.deepcopy(self.items)
        results = []
        try:
            for operation in batch_operations:
                name, arguments = operation[:2]
                options = operation[2] if len(operation) > 2 else {}
                if name == "replace":
                    identifier, body = arguments
                    result = self.replace_item(
                        identifier, body, etag=options.get("if_match_etag"),
                        match_condition=MatchConditions.IfNotModified,
                    )
                elif name == "create":
                    result = self.create_item(arguments[0])
                elif name == "upsert":
                    body = arguments[0]
                    result = self._store((partition_key, body["id"]), body)
                else:
                    raise AssertionError(f"Unexpected batch operation {name}.")
                results.append({"statusCode": 200, "resourceBody": result})
        except (CosmosHttpResponseError, AssertionError):
            self.items = before
            raise
        return results


class Clock:
    def __init__(self):
        self.now = datetime(2026, 9, 17, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self):
        self.now += timedelta(minutes=5)


@pytest.fixture
def durable():
    container = RuntimeContainer()
    clock = Clock()
    sections = SerializedSections()

    def new_store():
        return WorkflowRuntimeStore(container, WORKFLOW, RUN_ID, clock=clock)

    store = new_store()
    store.initialize(
        snapshot_ref={"storage": "cosmos", "schema_version": 1, "sha256": "a" * 64,
                      "size_bytes": 100, "chunk_count": 1},
        definition_revision="b" * 64, actor_user_id="owner", request_id="request-one",
    )
    return new_store, sections, clock


def controller(store, lease, sections):
    return DurableWorkflowExecution(
        store, lease, WORKFLOW, RUN_ID, save_result=sections.save, load_result=sections.load,
    )


def test_completed_units_survive_recreated_controller_without_reinvocation(durable):
    new_store, sections, clock = durable
    calls = []
    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-one") as lease:
        execution = controller(store, lease, sections)
        assert execution.run_unit(
            "task:extract", lambda: calls.append("extract") or {"records": [{"id": 1}]},
            inputs={"prompt": "Extract all records."}, replay_safe=True,
        ) == {"records": [{"id": 1}]}
    clock.advance()
    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-two") as lease:
        execution = controller(store, lease, sections)
        assert execution.run_unit(
            "task:extract", lambda: pytest.fail("Completed task must not run again."),
            inputs={"prompt": "Extract all records."}, replay_safe=True,
        ) == {"records": [{"id": 1}]}
        execution.run_unit("task:synthesize", lambda: calls.append("synthesize") or {"reply": "One record."},
                           inputs={"producer": "extract"}, replay_safe=True)
    assert calls == ["extract", "synthesize"]


def test_large_run_progress_is_referenced_not_embedded_in_the_control_row(durable):
    new_store, sections, clock = durable
    store = new_store()
    run_record = {"id": RUN_ID, "workflow_id": WORKFLOW["id"], "coverage": "full evidence " * 60000}
    with WorkflowRuntimeLease(store, owner_id="worker") as lease:
        execution = controller(store, lease, sections)
        with workflow_execution_scope(execution):
            workflow_checkpoint_scope_guard(run_record)
        control = store.read()
        assert "run_record" not in control
        assert len(json.dumps(control)) < 16000
        restored = sections.load(WORKFLOW, RUN_ID, "runtime:run-record", control["run_record_ref"])
        assert restored["run_record"] == run_record


def test_legacy_cleanup_can_fence_a_run_without_a_preexisting_journal():
    store = WorkflowRuntimeStore(RuntimeContainer(), WORKFLOW, RUN_ID)
    barrier = store.tombstone()
    assert barrier["deleted"] is True
    assert store.tombstone() == barrier
    with pytest.raises(WorkflowRuntimeConflict) as error:
        store.initialize(
            snapshot_ref={"sha256": "a" * 64}, definition_revision="b" * 64,
            actor_user_id="owner", request_id="late-submission",
        )
    assert error.value.code == "tombstoned"


def test_approval_is_persisted_and_bound_to_the_exact_input(durable):
    new_store, sections, clock = durable
    store = new_store()
    calls = []
    with WorkflowRuntimeLease(store, owner_id="worker-one") as lease:
        with pytest.raises(WorkflowSuspended, match="waiting_approval"):
            controller(store, lease, sections).run_unit(
                "task:send", lambda: calls.append("send") or {"sent": True},
                inputs={"destination": "approved-target"}, approval={"required": True},
            )
    waiting = new_store().read()
    assert calls == []
    assert waiting["state"] == "waiting_approval"
    new_store().decide(
        expected_version=waiting["version"], gate_id=waiting["gate"]["id"], choice="approve",
        actor_user_id="owner", request_id="approve-one",
    )
    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-two") as lease:
        controller(store, lease, sections).run_unit(
            "task:send", lambda: calls.append("send") or {"sent": True},
            inputs={"destination": "approved-target"}, approval={"required": True},
        )
    assert calls == ["send"]
    assert new_store().read()["memory"]["decisions"][0]["unit_id"] == "task:send"


def test_crashed_external_action_requires_recovery_confirmation(durable):
    new_store, sections, clock = durable
    calls = []

    def external_action():
        calls.append("external")
        raise SystemExit("Worker terminated before its checkpoint.")

    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-one") as lease:
        with pytest.raises(SystemExit):
            controller(store, lease, sections).run_unit(
                "task:external", external_action, inputs={"request": "stable"}, replay_safe=False,
            )
    clock.advance()
    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-two") as lease:
        with pytest.raises(WorkflowSuspended, match="waiting_recovery"):
            controller(store, lease, sections).run_unit(
                "task:external", lambda: pytest.fail("Unconfirmed action must not repeat."),
                inputs={"request": "stable"}, replay_safe=False,
            )
    waiting = new_store().read()
    new_store().decide(
        expected_version=waiting["version"], gate_id=waiting["gate"]["id"], choice="retry",
        actor_user_id="owner", request_id="confirmed-retry",
    )
    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-three") as lease:
        controller(store, lease, sections).run_unit(
            "task:external", lambda: calls.append("confirmed") or {"done": True},
            inputs={"request": "stable"}, replay_safe=False,
        )
    assert calls == ["external", "confirmed"]


def test_changed_inputs_cannot_reuse_an_approved_or_completed_checkpoint(durable):
    new_store, sections, clock = durable
    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-one") as lease:
        execution = controller(store, lease, sections)
        execution.run_unit("task:one", lambda: {"done": True}, inputs={"source_version": 1}, replay_safe=True)
        with pytest.raises(WorkflowSuspended, match="paused"):
            execution.run_unit("task:one", lambda: pytest.fail("Changed inputs require a new run."),
                               inputs={"source_version": 2}, replay_safe=True)
    assert new_store().read()["gate"]["choices"] == ["cancel"]


def test_child_output_wait_does_not_replay_its_submission(durable):
    new_store, sections, clock = durable
    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-one") as lease:
        execution = controller(store, lease, sections)
        execution.run_unit("task:analyze", lambda: {"child": "native-run"}, inputs={}, replay_safe=False)
        with pytest.raises(WorkflowSuspended, match="waiting_output"):
            execution.wait_for_output("task:analyze", [{"kind": "tabular", "run_id": "native-run"}])
    waiting = new_store().read()
    new_store().requeue_output(expected_version=waiting["version"], gate_id=waiting["gate"]["id"])
    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-two") as lease:
        execution = controller(store, lease, sections)
        assert execution.run_unit(
            "task:analyze", lambda: pytest.fail("The child must not be submitted twice."), inputs={},
        ) == {"child": "native-run"}
        execution.replace_unit_result("task:analyze", {"records": [{"id": "finished"}]})
    clock.advance()
    store = new_store()
    with WorkflowRuntimeLease(store, owner_id="worker-three") as lease:
        execution = controller(store, lease, sections)
        assert execution.run_unit("task:analyze", lambda: None, inputs={}) == {"records": [{"id": "finished"}]}
