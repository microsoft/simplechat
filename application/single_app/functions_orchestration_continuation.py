# functions_orchestration_continuation.py
"""Same-attempt recovery for saved V2 work, using the existing owning lease.

Version: 0.261.127
Initialized callers import this module after application bootstrap. It neither
admits plans nor creates retry attempts, and never starts or cancels native jobs.
Valid native waits use the existing recovery claim and native restore engine.
Other scheduler states share its stable producer token and fresh claim_id fences.
Saved native and generic result waits retain their original core dispatch data.
"""

import logging
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

from azure.core import MatchConditions
from azure.core.exceptions import AzureError
from azure.cosmos import exceptions

from content_screening.access import assert_current_request_sources_available, strict_source_authority
from functions_appinsights import log_event
from functions_orchestration_checkpoints import (
    CHECKPOINT_VERSION,
    LIFECYCLE_ID,
    CheckpointError,
    context_binding,
    context_state,
    fingerprint,
    restore_context,
    step_input_fingerprint,
)
from functions_orchestration_plan_revisions import read_revision_run
from functions_orchestration_recovery import (
    HEARTBEAT_SECONDS,
    ExecutionCheckpoints,
    ExecutionLease,
    RecoveryError,
    _completed_checkpoint,
    _execution_steps,
    _replace,
    _validate_payload_sources,
    claim_waiting_continuation,
    checkpoint_store,
    lease_fields,
    reconcile_checkpoints,
)
from functions_orchestration_rendering import raise_output_read_infrastructure_failure
from functions_orchestration_result_contracts import TaskResult
from functions_orchestration_result_runtime import decode_step_result, validate_task_outputs
from functions_orchestration_schema import PLAN_HARD_MAX_STEPS, build_failure, build_step_result, safe_failure


CONTINUATION_VERSION = "orchestration-continuation-v1"
_MODES = frozenset({"execute", "outputs", "delivery"})
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_COMPLETE = frozenset({"completed", "partial"})
_TRANSIENT = (AzureError, TimeoutError, ConnectionError)


def _now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CheckpointError("checkpoint_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CheckpointError("checkpoint_invalid")
    return parsed.astimezone(timezone.utc)


def _saved_v2(record):
    plan = record.get("plan")
    if (
        type(plan) is not dict
        or type(record.get("planner_contract_version")) is not int
        or record["planner_contract_version"] != 2
        or type(plan.get("planner_contract_version")) is not int
        or plan["planner_contract_version"] != 2
        or any(plan.get(key) != record.get(key) for key in ("run_id", "user_id", "conversation_id"))
        or type(plan.get("steps")) is not list or not 1 <= len(plan["steps"]) <= PLAN_HARD_MAX_STEPS
        or any(type(step) is not dict for step in plan["steps"])
        or type(record.get("attempt_index", 1)) is not int or record.get("attempt_index", 1) < 1
        or record.get("checkpoints_deleted") or record.get("outputs_deleted")
        or record.get("superseded_by_run_id") or record.get("status") in {"deleted", "superseded"}
        or record.get("latest_attempt_run_id")
    ):
        raise CheckpointError("recovery_changed")
    if not record.get("started_at") or not record.get("execution_deadline_at"):
        raise CheckpointError("checkpoint_unavailable")
    _timestamp(record["started_at"])
    _timestamp(record["execution_deadline_at"])


def _read_owned(run_id, user_id, conversation_id, authorize):
    if not callable(authorize) or authorize() is False:
        raise CheckpointError("context_unavailable")
    record = read_revision_run(run_id, user_id, conversation_id)
    _saved_v2(record)
    return record


def _lease_live(record):
    lease = record.get("execution_lease")
    if lease is None:
        return False
    if type(lease) is not dict or not lease.get("token"):
        raise CheckpointError("checkpoint_invalid")
    return _timestamp(lease.get("expires_at")) > _now()


def _native_wait_claimable(record, authorize):
    if (
        record.get("cancellation_requested_at") or not record.get("execution_binding")
        or _timestamp(record["execution_deadline_at"]) <= _now()
        or any(row.get("status") == "running" for row in record.get("execution_steps") or [])
    ):
        return False
    planned = {step["step_id"]: step for step in record["plan"]["steps"]}
    store = checkpoint_store(record, authorize)
    for row in record.get("execution_steps") or []:
        step = planned.get(row.get("step_id")) or {}
        if (
            row.get("status") != "waiting" or step.get("capability_id") != "tabular_analyze"
            or step.get("optional") or not store.has_manifest(row["step_id"], waiting=True)
            or store.has_manifest(row["step_id"])
        ):
            continue
        payload = store.load(row["step_id"], waiting=True)
        if (payload.get("result", {}).get("wait") or {}).get("kind") == "native_tabular_compute":
            return True
    return False


def _continuation_guards(record, authorize, message_container):
    store = checkpoint_store(record, authorize)
    try:
        checkpoint = store._read(LIFECYCLE_ID)
    except CheckpointError as exc:
        if (
            not isinstance(exc.__cause__, exceptions.CosmosResourceNotFoundError)
            or record.get("execution_binding")
        ):
            raise
        checkpoint = None
    if checkpoint is not None and checkpoint.get("deleted"):
        raise CheckpointError("ownership_lost")
    guard_id = f"orchestration_guard_{fingerprint(record['id'])[:40]}"
    try:
        publication = message_container.read_item(item=guard_id, partition_key=record["conversation_id"])
    except exceptions.CosmosResourceNotFoundError:
        publication = None
    if publication is not None and (
        any(publication.get(key) != record.get(key) for key in ("user_id", "conversation_id", "run_id"))
        or publication.get("role") != "assistant_artifact"
        or (publication.get("metadata") or {}).get("orchestration_publication_guard") is not True
    ):
        raise CheckpointError("ownership_lost")
    return checkpoint, publication


def claim_run_continuation(
    run_id, user_id, conversation_id, *, authorize, message_container, mode="execute",
):
    """CAS-claim one existing attempt; a live or no-longer-due run returns None.

    Selectors confer no authority. The owner callback and exact run identity are
    rechecked before each write. No start time, deadline, result, binding, message
    identity, producer, or attempt number is changed.
    """
    if type(mode) is not str or mode not in _MODES or message_container is None:
        raise RecoveryError(code="invalid_request", status_code=400)
    record = _read_owned(run_id, user_id, conversation_id, authorize)
    if _lease_live(record):
        return None
    status = record.get("status")
    allowed = {"waiting", "running"} if mode == "execute" else {"waiting", "running", *_TERMINAL}
    if status not in allowed:
        return None
    if mode == "delivery" and status in _TERMINAL and record.get("finalization_status") != "pending":
        return None
    if mode == "execute" and _native_wait_claimable(record, authorize):
        request = {
            "conversation_id": conversation_id,
            "submission_id": f"scheduler_{fingerprint([run_id, record['recovery_version']])[:40]}",
            "expected_version": record["recovery_version"],
        }
        try:
            claimed = claim_waiting_continuation(
                run_id, user_id, request, authorize=authorize, message_container=message_container,
            )
        except RecoveryError as exc:
            if exc.code == "execution_live":
                return None
            if exc.code in {"run_timeout", "user_cancelled"}:
                # The existing claim can observe a stop during its authoritative I/O.
                # Reconcile and finalize that durable outcome without entering an executor.
                return claim_run_continuation(
                    run_id, user_id, conversation_id, authorize=authorize,
                    message_container=message_container, mode="outputs",
                )
            raise
        if not claimed["acquired"]:
            return None
        lease = ExecutionLease(claimed["record"], authorize, message_container=message_container)
        return lease.read(), lease
    previous = record.get("continuation") or {}
    generation = previous.get("generation", 0)
    if type(generation) is not int or generation < 0 or (
        previous and previous.get("version") != CONTINUATION_VERSION
    ):
        raise CheckpointError("checkpoint_invalid")
    checkpoint, publication = _continuation_guards(record, authorize, message_container)
    fields = lease_fields()
    original_token = (checkpoint or {}).get("token") or (record.get("execution_lease") or {}).get("token")
    if original_token:
        if type(original_token) is not str or original_token != original_token.strip():
            raise CheckpointError("checkpoint_invalid")
        fields["token"] = original_token
    fields["claim_id"] = uuid.uuid4().hex
    continuation = {
        "version": CONTINUATION_VERSION,
        "generation": generation + 1,
        "mode": mode,
        "previous_status": status,
        "previous_outcome": record.get("outcome"),
        "claimed_at": _now().isoformat(),
    }
    updates = {
        "execution_lease": fields, "continuation": continuation,
        "recovery_version": uuid.uuid4().hex,
        "continuation_submission": {
            "submission_id": f"scheduler_{fields['claim_id']}",
            "fingerprint": fingerprint([run_id, record.get("recovery_version"), mode]),
            "claim_id": fields["claim_id"], "waiting_step_ids": [],
            "checkpoint_claim_id": (checkpoint or {}).get("claim_id"),
            "publication_guard": {
                "present": publication is not None, "claim_id": (publication or {}).get("claim_id"),
            },
        },
    }
    if mode != "delivery":
        updates["status"] = "running"
    if authorize() is False:
        raise CheckpointError("context_unavailable")
    try:
        claimed = _replace(record, updates)
    except exceptions.CosmosAccessConditionFailedError:
        return None
    except _TRANSIENT:
        claimed = _read_owned(run_id, user_id, conversation_id, authorize)
        if (
            claimed.get("execution_lease") != fields
            or claimed.get("continuation") != continuation
        ):
            raise
    lease = ContinuationExecutionLease(claimed, authorize, message_container=message_container)
    return lease.read(), lease


class ContinuationExecutionLease(ExecutionLease):
    """The real run lease for states outside the native waiting-claim admission."""

    def __init__(self, record, authorize, *, message_container):
        super().__init__(record, authorize, message_container=message_container)
        self.original = {
            key: deepcopy(record.get(key))
            for key in (
                "plan", "attempt_index", "started_at", "execution_deadline_at",
                "execution_binding", "turn_id", "continuation", "continuation_submission",
            )
        }
        self.message_identity = {
            key: record[key] for key in ("assistant_message_id", "assistant_message_created_at")
            if record.get(key) is not None
        }

    def read(self):
        record = super().read()
        _saved_v2(record)
        if any(record.get(key) != value for key, value in self.original.items()) or any(
            record.get(key) != value for key, value in self.message_identity.items()
        ):
            raise CheckpointError("ownership_lost")
        return record

    def _roll_guard(self, container, expected, partition, *, allow_missing):
        for _ in range(8):
            self.read()
            try:
                previous = container.read_item(item=expected["id"], partition_key=partition)
            except exceptions.CosmosResourceNotFoundError:
                if not allow_missing:
                    raise CheckpointError("checkpoint_unavailable") from None
                self.read()
                try:
                    container.create_item(body=expected)
                except exceptions.CosmosResourceExistsError:
                    continue
                except _TRANSIENT:
                    self.read()
                    saved = container.read_item(item=expected["id"], partition_key=partition)
                    if any(saved.get(key) != value for key, value in expected.items()):
                        raise
                self.read()
                return
            if (
                previous.get("deleted") or previous.get("stopped") or previous.get("successor")
                or any(
                    previous.get(key) != value for key, value in expected.items()
                    if key not in {"token", "claim_id"}
                )
            ):
                raise CheckpointError("ownership_lost")
            if previous.get("token") == self.token and previous.get("claim_id") == self.claim_id:
                self.read()
                return
            replacement = {key: deepcopy(value) for key, value in previous.items() if not key.startswith("_")}
            replacement.update(token=self.token, claim_id=self.claim_id)
            self.read()
            try:
                container.replace_item(
                    item=expected["id"], body=replacement, etag=previous["_etag"],
                    match_condition=MatchConditions.IfNotModified,
                )
            except exceptions.CosmosAccessConditionFailedError:
                continue
            except _TRANSIENT:
                self.read()
                saved = container.read_item(item=expected["id"], partition_key=partition)
                if any(saved.get(key) != value for key, value in expected.items()):
                    raise
            self.read()
            return
        raise CheckpointError("ownership_lost")

    def start(self):
        with self.lock:
            if self.stopped.is_set():
                raise CheckpointError("ownership_lost")
            if self.thread is not None:
                self.read()
                return self
            record = self.update({"finalization_status": "pending", "message_saved": False})
            self._roll_guard(self.message_container, {
                "id": f"orchestration_guard_{fingerprint(self.run_id)[:40]}",
                "conversation_id": self.conversation_id, "user_id": self.user_id,
                "run_id": self.run_id, "token": self.token, "role": "assistant_artifact", "content": "",
                "claim_id": self.claim_id,
                "metadata": {"is_generated_chat_artifact": True, "orchestration_publication_guard": True},
            }, self.conversation_id, allow_missing=True)
            store = checkpoint_store(record, self.read, token=self.token, claim_id=self.claim_id)
            self._roll_guard(store.container, {
                **store.identity, "id": LIFECYCLE_ID, "record_type": "checkpoint_lifecycle",
                "token": self.token, "claim_id": self.claim_id, "deleted": False,
            }, self.run_id, allow_missing=not bool(record.get("execution_binding")))

            def heartbeat():
                while not self.stopped.wait(HEARTBEAT_SECONDS):
                    try:
                        self.renew()
                    except Exception as exc:
                        self.failed = CheckpointError("ownership_lost")
                        log_event(
                            "[ORCHESTRATION_RUNS] Continuation heartbeat failed closed.",
                            extra={"run_id": self.run_id, "error_type": type(exc).__name__},
                            level=logging.ERROR,
                        )
                        return

            self.thread = threading.Thread(
                target=heartbeat, name=f"orchestration-lease-{self.run_id}", daemon=True,
            )
            self.thread.start()
            return self


def bind_orchestration_result_store(record, *, store, lease):
    """Bind initial or resumed parent claims without changing native guard identity."""
    if not isinstance(lease, ExecutionLease):
        raise CheckpointError("ownership_lost")
    current = lease.read()
    if any(current.get(key) != record.get(key) for key in ("id", "user_id", "conversation_id", "attempt_index")):
        raise CheckpointError("ownership_lost")
    return store.bind_orchestration_execution(
        current["user_id"], current["conversation_id"], current["id"],
        guard_token=lease.token, check_execution=lease.read,
    )


def bind_continuation_result_store(record, *, store, lease):
    """Compatibility name for the shared initial/continuation result binding."""
    return bind_orchestration_result_store(record, store=store, lease=lease)


class ContinuationCheckpoints(ExecutionCheckpoints):
    """Restore retained work for the core-owned saved-wait dispatcher."""

    def __init__(self, record, context, settings, lease):
        if not isinstance(lease, ExecutionLease):
            raise CheckpointError("ownership_lost")
        self.record = lease.read()
        self.context, self.settings, self.lease = context, settings, lease
        self.binding = context_binding(context, self.record["plan"], settings)
        if self.binding != self.record.get("execution_binding"):
            raise CheckpointError("recovery_changed")
        context.execution_deadline_at = self.record["execution_deadline_at"]
        self.store = checkpoint_store(self.record, lease.read, token=lease.token, claim_id=lease.claim_id)
        source = reconcile_checkpoints(self.record, lease.read)
        self.records = _execution_steps(source)
        self.continuing = True
        self.reused, self.waiting = {}, {}
        for saved in self.records:
            step_id = saved["step_id"]
            if saved.get("status") in _COMPLETE and (
                step_id in (source.get("inherited_checkpoints") or {}) or self.store.has_manifest(step_id)
            ):
                self.reused[step_id] = _completed_checkpoint(source, step_id, lease.read)
            elif saved.get("status") == "waiting" and self.store.has_manifest(step_id, waiting=True):
                self.waiting[step_id] = self.store.load(step_id, waiting=True)
        self.terminal_results = {
            row["step_id"]: build_step_result(
                status=row["status"], failure=safe_failure(row.get("failure") or build_failure("step_failed")),
                **({"task_result": TaskResult.from_dict(row["task_result"])}
                   if row.get("task_result") is not None and row["status"] == "failed" else {}),
            )
            for row in self.records
            if row["step_id"] not in self.reused and row.get("status") in {"failed", "cancelled"}
        }
        context.token_usage = deepcopy(record.get("harness_step_token_usage") or {})
        checkpoint_usage = {}
        for payload in (*self.reused.values(), *self.waiting.values()):
            if payload.get("provenance", {}).get("run_id") != record["id"]:
                continue
            for name, value in (payload.get("usage") or {}).items():
                if type(value) is int and value >= 0:
                    checkpoint_usage[name] = checkpoint_usage.get(name, 0) + value
        planning = record.get("planning_token_usage") or {}
        prompts = record.get("harness_prompt_token_usage", planning) or {}
        for name, value in checkpoint_usage.items():
            persisted = context.token_usage.get(name, 0) + prompts.get(name, 0) - planning.get(name, 0)
            if value > persisted:
                context.token_usage[name] = context.token_usage.get(name, 0) + value - persisted

    def initialize(self):
        self.lease.read()
        self.store.initialize()
        self.context.result_service.store = bind_continuation_result_store(
            self.record, store=self.context.result_service.store, lease=self.lease,
        )
        self.lease.update({
            "checkpoint_version": CHECKPOINT_VERSION,
            "execution_steps": deepcopy(self.records),
        })

    def _validate_payload(self, step, payload):
        self.lease.read()
        if (
            payload.get("binding") != self.binding
            or payload.get("step_id") != step["step_id"]
            or (
                payload.get("provenance", {}).get("run_id") == self.record["id"]
                and (payload.get("state") or {}).get("execution_deadline_at") != self.context.execution_deadline_at
            )
            or payload.get("input_fingerprint") != step_input_fingerprint(
                step, self.context, self.binding, settings=self.settings,
            )
        ):
            raise CheckpointError("recovery_changed")
        try:
            _validate_payload_sources(payload, self.context, self.settings, self.record["user_id"])
            assert_current_request_sources_available(self.record["user_id"])
        except Exception as exc:
            raise_output_read_infrastructure_failure(exc)
            raise

    def _retained_view(self, step, payload):
        result = decode_step_result(payload["result"])
        task = result.get("task_result")
        if step["role"] != "render":
            validate_task_outputs(step, self.context, task, reused=True)
            self.context.task_results[step["step_id"]] = task
        if result["status"] == "waiting":
            self.context.pending_results[step["step_id"]] = deepcopy(result["wait"])
        else:
            self.context.pending_results.pop(step["step_id"], None)
        # Cumulative old snapshots may contain an earlier pending version of an
        # independent task. Restore the verified result into current monotonic state.
        view = deepcopy(payload)
        view["state"] = context_state(self.context)
        return view

    @strict_source_authority()
    def before_step(self, step):
        self.lease.read()
        revalidate = self.context.revalidate_conversation_context
        if callable(revalidate):
            revalidate()
        assert_current_request_sources_available(self.record["user_id"])
        step_id = step["step_id"]
        payload = self.reused.get(step_id)
        if payload is not None:
            self._validate_payload(step, payload)
            return self._retained_view(step, payload)
        payload = self.waiting.get(step_id)
        if payload is not None:
            self._validate_payload(step, payload)
            if step["role"] == "render":
                return self._retained_view(step, payload)
            pending = decode_step_result(payload["result"])
            task = pending.get("task_result")
            validate_task_outputs(step, self.context, task)
            if task.status != "pending":
                raise CheckpointError("result_not_ready")
            # Core validates and resumes the retained native or generic wait exactly once.
            return self._retained_view(step, payload)
        saved = next((row for row in self.records if row["step_id"] == step_id), {})
        if saved.get("status") in {"running", *_COMPLETE} and step["role"] != "render":
            stamp = step_input_fingerprint(step, self.context, self.binding, settings=self.settings)
            task = self.context.result_service.recover_task_result(
                producer=self.context.result_producer(step), input_fingerprint=stamp,
            )
            if task is None:
                raise CheckpointError("result_commit_unconfirmed")
            validate_task_outputs(step, self.context, task)
            self.context.task_results[step_id] = task
            self.context.pending_results.pop(step_id, None)
            result = build_step_result(
                status="completed" if task.status == "complete" else "partial", task_result=task,
                summary="Recovered the committed result without repeating its producer.",
            )
            payload = self.store.commit(step, result, self.context, input_fingerprint=stamp, binding=self.binding)
            self.reused[step_id] = payload
            return self._retained_view(step, payload)
        if saved.get("status") in {"failed", "cancelled"}:
            raise CheckpointError((saved.get("failure") or {}).get("code", "step_failed"))
        return None

    def commit(self, step, result, input_fingerprint, *, reused=None):
        if reused is None:
            return super().commit(step, result, input_fingerprint)
        self.lease.read()
        waiting = result["status"] == "waiting"
        original = (self.waiting if waiting else self.reused).get(step["step_id"])
        if original is not None and not waiting and not self.store.has_manifest(step["step_id"]):
            if original.get("provenance", {}).get("run_id") == self.record["id"]:
                raise CheckpointError("checkpoint_unavailable")
            self.reused[step["step_id"]] = self.store.commit(
                step, result, self.context, input_fingerprint=original["input_fingerprint"],
                binding=original["binding"], provenance=original["provenance"],
                artifact_versions=original.get("artifact_versions"),
            )
            return
        current = self.store.load(step["step_id"], waiting=waiting)
        if original is None or fingerprint(original) != fingerprint(current):
            raise CheckpointError("recovery_changed")
        if waiting:
            self.context.pending_results[step["step_id"]] = deepcopy(result["wait"])


def reconcile_run_checkpoints(record, *, lease):
    """Repair a lost run-row acknowledgement from verified private manifests."""
    if not isinstance(lease, ExecutionLease):
        raise CheckpointError("ownership_lost")
    current = lease.read()
    if any(current.get(key) != record.get(key) for key in ("id", "user_id", "conversation_id", "attempt_index")):
        raise CheckpointError("ownership_lost")
    reconciled = reconcile_checkpoints(current, lease.read)
    tasks = deepcopy(current.get("task_results") or {})
    pending = deepcopy(current.get("pending_results") or {})
    store = checkpoint_store(current, lease.read, token=lease.token, claim_id=lease.claim_id)
    for row in reconciled.get("execution_steps") or []:
        step_id = row["step_id"]
        waiting = row.get("status") == "waiting"
        inherited = (current.get("inherited_checkpoints") or {}).get(step_id)
        if row.get("status") not in {*_COMPLETE, "waiting"} or (
            not inherited and not store.has_manifest(step_id, waiting=waiting)
        ):
            continue
        payload = store.load(step_id, waiting=True) if waiting else _completed_checkpoint(
            reconciled, step_id, lease.read,
        )
        provenance = (
            inherited.get("provenance") if inherited is not None
            else {"run_id": current["id"], "step_id": step_id}
        )
        if (
            payload.get("binding") != current.get("execution_binding")
            or payload.get("provenance") != provenance
            or (
                inherited is None
                and (payload.get("state") or {}).get("execution_deadline_at") != current["execution_deadline_at"]
            )
        ):
            raise CheckpointError("recovery_changed")
        result = decode_step_result(payload["result"])
        task = result.get("task_result")
        if task is not None:
            if type(task) is not TaskResult or (
                task.producer.user_id != current["user_id"]
                or task.producer.conversation_id != current["conversation_id"]
                or task.producer.step_id != step_id
                or (inherited is None and (
                    task.producer.run_id != current["id"]
                    or task.producer.attempt_index != current.get("attempt_index", 1)
                ))
            ):
                raise CheckpointError("recovery_changed")
            previous = TaskResult.from_dict(tasks[step_id]) if step_id in tasks else None
            if previous is not None and previous != task and (
                previous.producer != task.producer or previous.status != "pending"
                or task.status not in {"complete", "partial"}
            ):
                raise CheckpointError("recovery_changed")
            tasks[step_id] = task.to_dict()
        if waiting:
            if type(result.get("wait")) is not dict or not result["wait"]:
                raise CheckpointError("checkpoint_invalid")
            pending[step_id] = deepcopy(result["wait"])
        else:
            pending.pop(step_id, None)
    updates = {
        "execution_steps": reconciled.get("execution_steps") or [],
        "task_results": tasks, "pending_results": pending,
    }
    if any(current.get(key) != value for key, value in updates.items()):
        return lease.update(updates)
    return current


def reconcile_run_outputs(record, *, services, lease):
    """Reconcile only file facts; unfinished native/non-render work stays unfinished."""
    if (
        not isinstance(lease, ExecutionLease)
        or services.user_id != lease.user_id or services.conversation_id != lease.conversation_id
    ):
        raise CheckpointError("ownership_lost")
    current = reconcile_run_checkpoints(record, lease=lease)
    if any(current.get(key) != record.get(key) for key in ("id", "user_id", "conversation_id", "attempt_index")):
        raise CheckpointError("ownership_lost")
    public = {value["output_id"]: value for value in services.rendering.list_public_outputs(current["id"])}
    rows = services.outputs.list_outputs(current["id"])
    lease.read()
    planned = {step["step_id"]: step for step in current["plan"]["steps"]}
    execution = {row["step_id"]: deepcopy(row) for row in current.get("execution_steps") or []}
    pending = deepcopy(current.get("pending_results") or {})
    failures = deepcopy(current.get("failures") or [])
    touched = set()
    store = checkpoint_store(current, lease.read, token=lease.token, claim_id=lease.claim_id)
    for output in rows:
        producer = output["producer"]
        step_id = producer["step_id"]
        step = planned.get(step_id)
        if (
            step is None or step.get("role") != "render" or not step["enabled"]
            or producer["run_id"] != current["id"] or producer["attempt_index"] != current.get("attempt_index", 1)
            or step_id in touched or output["id"] not in public
        ):
            raise CheckpointError("recovery_changed")
        touched.add(step_id)
        fact = public[output["id"]]
        state = fact["state"]
        status = (
            "completed" if state == "completed" and fact["available"]
            else "waiting" if state in {"waiting", "rendering", "retry_scheduled"} and fact["available"]
            else "cancelled" if state == "cancelled" else "failed"
        )
        row = execution.get(step_id, {
            "run_id": current["id"], "step_id": step_id, "step_index": list(planned).index(step_id),
            "capability_id": "render_file", "role": "render", "started_at": None,
            "duration_ms": 0, "token_usage": {}, "checkpoint_available": False,
        })
        wait = {"kind": "orchestration_output", "output_id": output["id"]}
        if status == "waiting":
            pending[step_id] = deepcopy(row.get("wait") or wait)
        else:
            pending.pop(step_id, None)
        failure = build_failure("step_failed", step_id=step_id, capability_id="render_file") if status == "failed" else None
        failures = [value for value in failures if value.get("step_id") != step_id]
        if failure is not None:
            failures.append(failure)
        row.update({
            "status": status, "summary": fact["message"], "failure": failure,
            "error": failure["message"] if failure is not None else None,
            "completed_at": None if status == "waiting" else output.get("committed_at") or _now().isoformat(),
            "wait": deepcopy(pending.get(step_id)), "outputs": [deepcopy(fact)], "effects_uncertain": False,
        })
        if status == "completed" and not store.has_manifest(step_id) and store.has_manifest(step_id, waiting=True):
            payload = store.load(step_id, waiting=True)
            if payload.get("binding") != current.get("execution_binding"):
                raise CheckpointError("recovery_changed")
            # Reuse the real saved state and input fingerprint, not a model-built context.
            context = SimpleNamespace(
                plan_contract_version=2, task_results={}, result_aliases={},
                pending_results={}, execution_deadline_at=current["execution_deadline_at"],
            )
            restore_context(context, payload)
            context.pending_results.pop(step_id, None)
            result = build_step_result(status="completed", summary=fact["message"])
            result["outputs"] = [deepcopy(fact)]
            store.commit(
                step, result, context, input_fingerprint=payload["input_fingerprint"],
                binding=payload["binding"], provenance=payload["provenance"],
            )
            row["checkpoint_available"] = True
        store.save_step(row)
        execution[step_id] = row
    enabled = [step for step in planned.values() if step["enabled"]]
    required = [step for step in enabled if not step["optional"]] or enabled
    stopped = bool(current.get("cancellation_requested_at")) or (
        current.get("continuation", {}).get("previous_status") == "cancelled"
    )
    unfinished = bool(pending) or any(
        execution.get(step["step_id"], {}).get("status", "pending") in {"pending", "running", "waiting"}
        for step in enabled
    )
    complete = bool(required) and all(
        execution.get(step["step_id"], {}).get("status") == "completed" for step in required
    )
    status = "cancelled" if stopped else "waiting" if unfinished else "completed" if complete else "failed"
    partial = any(row.get("status") in _COMPLETE for row in execution.values())
    if status == "completed":
        failures = []
    return lease.update({
        "execution_steps": [execution[key] for key in planned if key in execution],
        "pending_results": pending, "status": status,
        "outcome": "partial" if status == "failed" and partial else status,
        "failures": failures, "failure": failures[0] if failures else None,
        "error": failures[0]["message"] if failures else None,
        "completed_at": None if status == "waiting" else _now().isoformat(),
        "finalization_status": "pending", "message_saved": False,
    })
