# functions_workflow_structured_execution.py
"""Schema-2 operation boundaries using paged units rather than a growing control map."""

from copy import deepcopy

from functions_workflow_execution import DurableWorkflowExecution, WorkflowSuspended, execution_fingerprint
from functions_workflow_identity import workflow_execution_id
from functions_workflow_runtime_store import WorkflowRuntimeConflict
from functions_workflow_result_store import load_workflow_node_result, save_workflow_node_result


class StructuredWorkflowExecution(DurableWorkflowExecution):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("save_result", save_workflow_node_result)
        kwargs.setdefault("load_result", load_workflow_node_result)
        super().__init__(*args, **kwargs)
        self.node = None
        self.region_id = self.workflow["flow"]["id"]
        self.iteration_path = []
        self.iteration_inputs = []

    def set_node(self, node, region_id, *, iteration_path=None, iteration_inputs=None):
        self.node = node
        self.region_id = region_id
        if iteration_path is not None:
            self.iteration_path = deepcopy(iteration_path)
        if iteration_inputs is not None:
            self.iteration_inputs = deepcopy(iteration_inputs)

    def cursor(self):
        return {
            "region_id": self.region_id,
            "node_id": self.node["id"] if self.node else None,
            "execution_id": self.execution_id(),
            "iteration_path": deepcopy(self.iteration_path),
        }

    def check(self):
        record = self.lease.check()
        if self.store._now().isoformat() >= record["deadline_at"]:
            self.store.pause_execution_limit(self.lease.token, "deadline_exceeded")
            raise WorkflowSuspended("paused")
        return record

    def freeze_reference(self, reference, loader):
        key = ["reference", reference["id"]]
        row = self.store.journal_read("unit", key)
        snapshot = None
        if row:
            saved = row["payload"]
            snapshot = self.load_result(
                self.workflow, self.run_id, None, saved["result_ref"], **saved["selectors"],
            )
        value = loader(snapshot=snapshot)
        if row is None:
            root = self.workflow["flow"]["id"]
            selectors = {
                "node_id": root, "execution_id": workflow_execution_id(self.workflow, self.run_id, root),
                "iteration_path": [], "attempt": 1,
            }
            result_ref = self.save_result(self.workflow, self.run_id, None, value, settings=self.settings, **selectors)
            self.store.journal_commit(self.lease.token, "unit", key, {
                "state": "completed", "selectors": selectors, "result_ref": result_ref,
            }, immutable=True)
        return value

    def save_runtime_record(self, record):
        node_id = self.workflow["flow"]["id"]
        selectors = {
            "node_id": node_id, "execution_id": workflow_execution_id(self.workflow, self.run_id, node_id),
            "attempt": 1, "iteration_path": [],
        }
        reference = self.save_result(
            self.workflow, self.run_id, None, {"run_record": record}, settings=self.settings, **selectors,
        )
        return {"result_ref": reference, "selectors": selectors}

    def execution_id(self):
        return workflow_execution_id(
            self.workflow, self.run_id, self.node["id"] if self.node else self.workflow["flow"]["id"],
            self.iteration_path if self.node else [],
        )

    def _key(self, key):
        return [self.execution_id(), key]

    def unit(self, key):
        row = self.store.journal_read("unit", self._key(key))
        return deepcopy(row["payload"]) if row else {}

    def selectors(self, *, attempt=None):
        task_id = self.node.get("task_id") if self.node else None
        unit = self.unit(f"task:{task_id}") if task_id else {}
        return {
            "execution_id": self.execution_id(), "node_id": self.node["id"] if self.node else self.workflow["flow"]["id"],
            "iteration_path": deepcopy(self.iteration_path) if self.node else [],
            "attempt": attempt or unit.get("attempt") or 1,
        }

    def _save_payload(self, key, payload):
        task_id = self.node.get("task_id") if self.node else None
        return self.save_result(
            self.workflow, self.run_id, task_id, payload, settings=self.settings,
            **self.selectors(attempt=payload.get("attempt")),
        )

    def _saved(self, unit, key):
        task_id = self.node.get("task_id") if self.node else None
        payload = self.load_result(
            self.workflow, self.run_id, task_id, unit["result_ref"],
            **{**unit["selectors"]},
        )
        if (
            payload.get("unit_id") != key or payload.get("input_digest") != unit.get("input_digest")
            or payload.get("attempt") != unit.get("attempt")
        ):
            raise WorkflowRuntimeConflict("workflow_checkpoint_invalid")
        return payload["value"]

    def _pause(self, key, digest):
        if self.node:
            self.record_execution(state="paused", reason_code="inputs_changed")
        self.store.wait(self.lease.token, state="paused", gate={
            "id": execution_fingerprint([self.execution_id(), key, digest, "pause"]),
            "kind": "pause", "unit_id": key, "input_digest": digest, **self.selectors(),
            "definition_revision": self.workflow.get("definition_revision"),
            "reason": "Saved inputs changed. Cancel this run and start a new one.", "choices": ["cancel"],
        })
        raise WorkflowSuspended("paused")

    def pause_input(self, reason, *, code="workflow_input_unavailable"):
        if self.node:
            self.record_execution(state="paused", reason_code=code)
        self.store.wait(self.lease.token, state="paused", gate={
            "id": execution_fingerprint([self.execution_id(), code, reason]),
            "kind": "pause", "unit_id": self.node["id"] if self.node else "inputs",
            "input_digest": self.workflow.get("definition_revision") or "",
            **self.selectors(), "definition_revision": self.workflow.get("definition_revision"),
            "reason": reason, "choices": ["cancel"],
        })
        raise WorkflowSuspended("paused")

    def _gate(self, key, digest, attempt, kind, reason, inputs=None):
        gate_id = execution_fingerprint([self.execution_id(), key, digest, attempt, kind])
        row = self.store.journal_read("decision", ["gate", gate_id])
        choice = "approve" if kind == "approval" else "retry"
        if row and all(row["payload"].get(name) == value for name, value in {
            "execution_id": self.execution_id(), "attempt": attempt, "input_digest": digest, "choice": choice,
        }.items()):
            return
        state = "waiting_approval" if kind == "approval" else "waiting_recovery"
        if self.node and self.node["kind"] == "task":
            self.record_execution(
                state=state, attempt=attempt,
                consumed_inputs=(inputs or {}).get("consumed_inputs") or [],
                reference_sources=(inputs or {}).get("references") or [],
            )
            self._attempt(attempt, state=state)
        self.store.wait(self.lease.token, state=state, gate={
            "id": gate_id, "kind": kind, "unit_id": key, "input_digest": digest,
            **self.selectors(attempt=attempt), "reason": reason,
            "definition_revision": self.workflow.get("definition_revision"),
            "choices": ["approve", "reject"] if kind == "approval" else ["retry", "cancel"],
        })
        raise WorkflowSuspended(state)

    def record_execution(self, **fields):
        if self.node is None:
            return None
        previous = self.store.journal_read("execution", self.execution_id())
        if previous and previous["payload"].get("state") in {"succeeded", "completed", "skipped", "failed", "invalid", "incomplete"}:
            prior = previous["payload"]
            if fields.get("attempt", prior.get("attempt")) == prior.get("attempt") and fields.get("state") == prior.get("state"):
                if fields.get("workflow_result", prior.get("workflow_result")) != prior.get("workflow_result"):
                    raise WorkflowRuntimeConflict("immutable_attempt_conflict")
                return previous
        payload = previous["payload"] if previous else {
            "execution_id": self.execution_id(), "node_id": self.node["id"], "node_kind": self.node["kind"],
            "iteration_path": deepcopy(self.iteration_path), "region_id": self.region_id, "attempt": 0,
            **({"task_id": self.node["task_id"]} if self.node.get("task_id") else {}),
        }
        if previous and fields.get("attempt", payload["attempt"]) != payload["attempt"]:
            payload = {key: value for key, value in payload.items() if key not in {
                "workflow_result", "workflow_validation", "consumed_inputs", "completed_at", "started_at", "reason_code",
            }}
        return self.store.journal_commit(
            self.lease.token, "execution", self.execution_id(), {
                **payload, "iteration_inputs": deepcopy(self.iteration_inputs), **fields,
            },
            updates={"cursor": self.cursor()},
        )

    def run_unit(self, key, operation, *, inputs, replay_safe=False, approval=None):
        self.check()
        digest = execution_fingerprint(inputs)
        unit = self.unit(key)
        if unit and unit.get("input_digest") != digest:
            self._pause(key, digest)
        if unit.get("state") == "completed":
            result = self._saved(unit, key)
            self.check()
            return result
        execution_row = self.store.journal_read("execution", self.execution_id()) if self.node else None
        if execution_row and execution_row["payload"].get("state") == "paused" and unit.get("state") != "completed":
            self.record_execution(state="queued", reason_code="")
        previous_attempt = int(unit.get("attempt") or 0)
        task_operation = self.node is not None and key == f"task:{self.node.get('task_id')}"
        if task_operation:
            self.record_execution(
                state="queued", attempt=previous_attempt + 1,
                consumed_inputs=inputs.get("consumed_inputs") or [],
                reference_sources=inputs.get("references") or [],
            )
        if unit and unit.get("state") in {"running", "failed"} and (
            not unit.get("replay_safe") or previous_attempt >= 3
        ):
            self._gate(key, digest, previous_attempt, "recovery",
                       "Review any external effects before retrying the interrupted task.", inputs)
        attempt = previous_attempt + 1
        if approval and approval.get("required") is True:
            self._gate(key, digest, attempt, "approval",
                       str(approval.get("message") or "Review this exact task attempt before execution.")[:1000], inputs)
        selectors = self.selectors(attempt=attempt)
        unit = {
            "state": "running", "attempt": attempt, "input_digest": digest,
            "replay_safe": bool(replay_safe), "selectors": selectors, "execution_id": self.execution_id(),
        }
        if task_operation:
            admitted_by_condition = attempt == 1 and self.store.journal_read(
                "decision", ["control", self.execution_id()],
            ) is not None
            self.store.journal_commit(
                self.lease.token, "admission", [self.execution_id(), attempt],
                {"execution_id": self.execution_id(), "attempt": attempt, "input_digest": digest},
                admission=not admitted_by_condition, immutable=True,
                updates={"cursor": self.cursor(), "phase": self.node["id"]},
            )
            self.record_execution(state="running", attempt=attempt, started_at=self.store._now().isoformat(),
                                  consumed_inputs=inputs.get("consumed_inputs") or [])
            self._attempt(attempt, state="running")
        self.store.journal_commit(self.lease.token, "unit", self._key(key), unit)
        try:
            result = operation()
        except Exception:
            self.check()
            self.store.journal_commit(self.lease.token, "unit", self._key(key), {**unit, "state": "failed"})
            if task_operation:
                self.record_execution(state="failed", attempt=attempt)
                self._attempt(attempt, state="failed")
            if not replay_safe:
                self._gate(key, digest, attempt, "recovery", "Review any external effects before retrying this failed attempt.", inputs)
            raise
        self.check()
        reference = self._save_payload(key, {
            "unit_id": key, "input_digest": digest, "attempt": attempt, "value": result,
        })
        self.store.journal_commit(self.lease.token, "unit", self._key(key), {
            **unit, "state": "completed", "result_ref": reference,
        })
        return result

    def _attempt(self, attempt, **fields):
        row = self.store.journal_read("execution", self.execution_id())
        payload = {**(row["payload"] if row else {}), "attempt": attempt, **fields}
        previous = self.store.journal_read("attempt", [self.execution_id(), attempt])
        if previous and previous["payload"].get("state") not in {"running", "waiting_output", "pending", "waiting_approval", "waiting_recovery", "paused"}:
            if previous["payload"].get("workflow_result") != payload.get("workflow_result"):
                raise WorkflowRuntimeConflict("immutable_attempt_conflict")
            if fields.get("state") not in {previous["payload"]["state"], "waiting_recovery"}:
                raise WorkflowRuntimeConflict("immutable_attempt_conflict")
            return previous
        return self.store.journal_commit(
            self.lease.token, "attempt", [self.execution_id(), attempt], payload,
        )

    def finish_node(self, **fields):
        row = self.record_execution(**fields, completed_at=self.store._now().isoformat())
        if self.node and fields.get("state") != "skipped":
            self._attempt(row["payload"]["attempt"], **{key: value for key, value in fields.items() if key != "attempt"})
        return row

    def snapshot(self, key):
        self.check()
        unit = self.unit(key)
        return self._saved(unit, key) if unit.get("state") == "completed" else None

    def invalidate_task(self, key):
        unit = self.unit(key)
        if unit:
            self.store.journal_commit(self.lease.token, "unit", self._key(key), {**unit, "state": "failed"})

    def replace_unit_result(self, key, value):
        unit = self.unit(key)
        if unit.get("state") != "completed":
            raise WorkflowRuntimeConflict("workflow_checkpoint_unavailable")
        reference = self._save_payload(key, {
            "unit_id": key, "input_digest": unit["input_digest"], "attempt": unit["attempt"], "value": value,
        })
        self.store.journal_commit(self.lease.token, "unit", self._key(key), {**unit, "result_ref": reference})

    def wait_for_publication(self, key, *, reference=None, publication=None, reason, retryable=False):
        control = self.check()
        unit = self.unit(key)
        waiting = publication is not None and publication["state"].startswith("waiting_")
        state = "waiting_output" if waiting else "paused"
        self.record_execution(state=state, reason_code=(publication or {}).get("reason_code") or "publication_unavailable")
        gate = {
            "id": execution_fingerprint([self.execution_id(), unit.get("attempt"), key, state, publication, control["version"]]),
            "kind": "output" if waiting else "pause", "unit_id": key,
            "input_digest": unit.get("input_digest") or "", **self.selectors(),
            "definition_revision": self.workflow.get("definition_revision"),
            "reason": reason, "choices": [] if waiting else ["resume", "cancel"] if retryable else ["cancel"],
        }
        if reference is not None:
            gate["references"] = [deepcopy(reference)]
        if publication is not None:
            gate["publication"] = deepcopy(publication)
        self.store.wait(self.lease.token, state=state, gate=gate)
        raise WorkflowSuspended(state)

    def wait_for_output(self, key, references):
        unit = self.unit(key)
        self.record_execution(state="waiting_output", attempt=int(unit.get("attempt") or 1))
        self.store.wait(self.lease.token, state="waiting_output", gate={
            "id": execution_fingerprint([self.execution_id(), key, unit.get("attempt"), "output"]),
            "kind": "output", "unit_id": key, "input_digest": unit.get("input_digest", ""),
            **self.selectors(), "reason": "Waiting for the submitted output to finish.",
            "choices": [], "references": references,
        })
        raise WorkflowSuspended("waiting_output")

    def may_recover_analysis_unit(self, task_id):
        unit = self.unit(f"task:{task_id}")
        attempt = int(unit.get("attempt") or 0) - 1
        gate_id = execution_fingerprint([
            self.execution_id(), f"task:{task_id}", unit.get("input_digest"), attempt, "recovery",
        ])
        row = self.store.journal_read("decision", ["gate", gate_id])
        return bool(row and row["payload"].get("choice") == "retry")
