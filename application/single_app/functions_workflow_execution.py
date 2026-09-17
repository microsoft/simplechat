# functions_workflow_execution.py
"""Step-boundary durable execution for the existing workflow runner."""

import hashlib
import json
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy

from functions_workflow_result_store import load_workflow_task_result, save_workflow_task_result
from functions_workflow_runtime_store import WorkflowRuntimeConflict


_execution = ContextVar("durable_workflow_execution", default=None)


class WorkflowSuspended(BaseException):
    """A durable wait releases the worker; ordinary task retries must not catch it."""

    def __init__(self, state):
        self.state = state
        super().__init__(state)


def current_workflow_execution():
    return _execution.get()


@contextmanager
def workflow_execution_scope(execution):
    token = _execution.set(execution)
    try:
        yield execution
    finally:
        _execution.reset(token)


def execution_fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def durable_workflow_enabled(workflow):
    return workflow.get("durable_execution") is True


def workflow_unit(key, operation, *, inputs=None, replay_safe=False, approval=None):
    execution = current_workflow_execution()
    if execution is None:
        return operation()
    return execution.run_unit(
        key, operation, inputs=inputs or {}, replay_safe=replay_safe, approval=approval,
    )


def assert_workflow_execution_owned():
    execution = current_workflow_execution()
    if execution is not None:
        execution.check()


def workflow_checkpoint_scope_guard(record):
    """Mirror existing projections only while the authoritative journal is owned."""
    execution = current_workflow_execution()
    if execution is not None:
        execution.check()
        reference = execution.save_result(
            execution.workflow, execution.run_id, "runtime:run-record",
            {"run_record": record}, settings=execution.settings,
        )
        execution._update(execution.check(), {"run_record_ref": reference})


class DurableWorkflowExecution:
    """Journal operation results without replacing the workflow's task dispatcher."""

    def __init__(self, store, lease, workflow, run_id, *, settings=None,
                 save_result=save_workflow_task_result, load_result=load_workflow_task_result):
        self.store = store
        self.lease = lease
        self.workflow = workflow
        self.run_id = run_id
        self.settings = settings or {}
        self.save_result = save_result
        self.load_result = load_result

    def check(self):
        return self.lease.check()

    def _update(self, record, updates):
        return self.store.update(self.lease.token, updates, expected_version=record["version"])

    def fence_batch(self, operations):
        """Compose the workflow fence with a producer's own same-partition CAS."""
        record = self.check()
        replacement = {key: value for key, value in record.items() if not key.startswith("_")}
        replacement["write_nonce"] = uuid.uuid4().hex
        return [
            ("replace", (record["id"], replacement), {"if_match_etag": record["_etag"]}),
            *operations,
        ]

    def _saved(self, unit, key):
        payload = self.load_result(self.workflow, self.run_id, f"runtime:{key}", unit["result_ref"])
        if (
            payload.get("unit_id") != key or payload.get("input_digest") != unit.get("input_digest")
            or payload.get("attempt") != unit.get("attempt")
        ):
            raise WorkflowRuntimeConflict("workflow_checkpoint_invalid")
        return payload["value"]

    def _approval(self, record, key, digest, approval):
        if not approval or approval.get("required") is not True:
            return
        decisions = (record.get("memory") or {}).get("decisions") or []
        if any(
            decision.get("unit_id") == key and decision.get("input_digest") == digest
            and decision.get("choice") == "approve" for decision in decisions
        ):
            return
        gate = {
            "id": uuid.uuid4().hex, "kind": "approval", "unit_id": key,
            "input_digest": digest,
            "reason": str(approval.get("message") or "Review this task before allowing it to execute.")[:1000],
            "choices": ["approve", "reject"],
        }
        self.store.wait(self.lease.token, state="waiting_approval", gate=gate)
        raise WorkflowSuspended("waiting_approval")

    def _recovery(self, record, key, digest, reason):
        decisions = (record.get("memory") or {}).get("decisions") or []
        unit = (record.get("units") or {}).get(key) or {}
        attempt = int(unit.get("attempt") or 0)
        if any(
            decision.get("unit_id") == key and decision.get("input_digest") == digest
            and decision.get("choice") == "retry" and decision.get("attempt") == attempt
            for decision in decisions
        ):
            return
        self.store.wait(self.lease.token, state="waiting_recovery", gate={
            "id": uuid.uuid4().hex, "kind": "recovery", "unit_id": key,
            "input_digest": digest, "attempt": attempt, "reason": reason,
            "choices": ["retry", "cancel"],
        })
        raise WorkflowSuspended("waiting_recovery")

    def may_recover_analysis_unit(self, task_id):
        record = self.check()
        key = f"task:{task_id}"
        unit = (record.get("units") or {}).get(key) or {}
        return unit.get("state") == "running" and any(
            decision.get("unit_id") == key
            and decision.get("input_digest") == unit.get("input_digest")
            and decision.get("attempt") == int(unit.get("attempt") or 0) - 1
            and decision.get("choice") == "retry"
            for decision in (record.get("memory") or {}).get("decisions") or []
        )

    def run_unit(self, key, operation, *, inputs, replay_safe=False, approval=None):
        record = self.check()
        digest = execution_fingerprint(inputs)
        units = deepcopy(record.get("units") or {})
        unit = units.get(key)
        if unit and unit.get("input_digest") != digest:
            self.store.wait(self.lease.token, state="paused", gate={
                "id": uuid.uuid4().hex, "kind": "pause", "unit_id": key,
                "input_digest": digest, "reason": "The saved task inputs changed. Cancel this run and start a new one.",
                "choices": ["cancel"],
            })
            raise WorkflowSuspended("paused")
        if unit and unit.get("state") == "completed":
            result = self._saved(unit, key)
            self.check()
            return result
        if unit and unit.get("state") in {"running", "failed"}:
            if not unit.get("replay_safe") or int(unit.get("attempt", 0)) >= 3:
                self._recovery(
                    record, key, digest,
                    "The previous attempt did not save a completion checkpoint. External actions may have occurred. "
                    "Review their outcome before explicitly retrying this task.",
                )
                record = self.check()
                units = deepcopy(record.get("units") or {})
        self._approval(record, key, digest, approval)
        attempt = int((units.get(key) or {}).get("attempt") or 0) + 1
        units[key] = {
            "state": "running", "attempt": attempt, "input_digest": digest,
            "replay_safe": bool(replay_safe),
        }
        self._update(record, {"units": units, "phase": key})
        try:
            result = operation()
        except Exception:
            # The exception remains visible to the existing runner. Only a
            # durable explicit decision can replay a possibly side-effecting unit.
            record = self.check()
            units = deepcopy(record.get("units") or {})
            units[key]["state"] = "failed"
            self._update(record, {"units": units})
            if not replay_safe:
                self._recovery(
                    self.check(), key, digest,
                    "This task failed after it started. Review any external actions before retrying.",
                )
            raise
        self.check()
        payload = {"unit_id": key, "input_digest": digest, "attempt": attempt, "value": result}
        reference = self.save_result(
            self.workflow, self.run_id, f"runtime:{key}", payload, settings=self.settings,
        )
        record = self.check()
        units = deepcopy(record.get("units") or {})
        if units[key].get("attempt") != attempt:
            raise WorkflowRuntimeConflict("workflow_ownership_lost")
        units[key].update(state="completed", result_ref=reference)
        self._update(record, {"units": units})
        return result

    def cache(self, key, value):
        """Persist deterministic preparation data under the same ownership boundary."""
        return self.run_unit(key, lambda: value, inputs={}, replay_safe=True)

    def snapshot(self, key):
        record = self.check()
        unit = (record.get("units") or {}).get(key)
        if not unit or unit.get("state") != "completed":
            return None
        return self._saved(unit, key)

    def invalidate_task(self, key):
        """Keep its prior payload but require an explicit new attempt on resume."""
        record = self.check()
        units = deepcopy(record.get("units") or {})
        if key in units:
            units[key]["state"] = "failed"
            self._update(record, {"units": units})

    def prepared(self, key, operation):
        value = self.snapshot(key)
        return value if value is not None else self.run_unit(key, operation, inputs={}, replay_safe=True)

    def replace_unit_result(self, key, value):
        """Reconcile an already-submitted child result without repeating submission."""
        record = self.check()
        units = deepcopy(record.get("units") or {})
        unit = units.get(key)
        if not unit or unit.get("state") != "completed":
            raise WorkflowRuntimeConflict("workflow_checkpoint_unavailable")
        reference = self.save_result(
            self.workflow, self.run_id, f"runtime:{key}",
            {"unit_id": key, "input_digest": unit["input_digest"], "attempt": unit["attempt"], "value": value},
            settings=self.settings,
        )
        record = self.check()
        units = deepcopy(record.get("units") or {})
        units[key]["result_ref"] = reference
        self._update(record, {"units": units})

    def wait_for_output(self, key, references):
        record = self.check()
        self.store.wait(self.lease.token, state="waiting_output", gate={
            "id": uuid.uuid4().hex, "kind": "output", "unit_id": key,
            "input_digest": (record.get("units") or {}).get(key, {}).get("input_digest", ""),
            "reason": "Waiting for the required background output to finish.",
            "choices": [], "references": references,
        })
        raise WorkflowSuspended("waiting_output")
