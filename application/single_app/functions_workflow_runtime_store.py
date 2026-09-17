# functions_workflow_runtime_store.py
"""Durable workflow runtime control and schema-2 paged execution journal.

Version: 0.261.116
Implemented in: 0.261.111

The single private control row retains the existing lease/CAS identity.
Schema 1 keeps legacy unit maps; schema 2 keeps cursor/counters and stores
execution, attempt, unit and decision records separately in the same partition.
Schedulers/runners still own execution, authorization and task replay policy.
"""

import json
import math
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions
from functions_workflow_journal import WorkflowJournalMixin
from functions_workflow_identity import workflow_execution_id


CONTROL_ID = "workflow-runtime:v1"
CONTROL_TYPE = "workflow_runtime_control"
SCHEMA_VERSION = 1
MAX_CONTROL_BYTES = 512 * 1024
MAX_GATE_BYTES = 16 * 1024
MAX_DECISIONS = 1000
MAX_CAS_RETRIES = 8
DEFAULT_LEASE_SECONDS = 45
DEFAULT_HEARTBEAT_SECONDS = 10
NO_WRITE = object()

CLAIM_STATES = frozenset({"queued", "running"})
WAITING_STATES = frozenset({"waiting_approval", "waiting_output", "waiting_recovery", "paused"})
TERMINAL_STATES = frozenset({"completed", "completed_partial", "failed", "invalid", "incomplete", "cancelled", "skipped"})
RESUMABLE_STATES = frozenset({"failed", "invalid", "incomplete"})
ALL_STATES = CLAIM_STATES | WAITING_STATES | TERMINAL_STATES | frozenset({"cancelling"})

ALLOWED_UPDATE_KEYS = frozenset({
    "units",
    "memory",
    "context_ref",
    "completion_ref",
    "progress",
    "phase",
    "usage",
    "run_record",
    "run_record_ref",
    "reference_snapshot_ref",
    "metadata",
})
IDENTITY_KEYS = frozenset({"workflow_id", "user_id", "group_id", "scope_type", "scope_id", "run_id"})
FORBIDDEN_PAYLOAD_KEY_PARTS = ("token", "secret", "password", "connection")
FORBIDDEN_GATE_KEY_PARTS = FORBIDDEN_PAYLOAD_KEY_PARTS + ("prompt", "result", "payload", "content", "raw")
GATE_ALLOWED_KEYS = frozenset({
    "execution_id", "node_id", "iteration_path", "definition_revision",
    "id",
    "kind",
    "unit_id",
    "input_digest",
    "attempt",
    "reason",
    "choices",
    "references",
    "title",
    "summary",
    "created_at",
    "expires_at",
    "output_ref",
    "output_status",
    "correlation_id",
    "provider",
    "retryable",
    "metadata",
})
GATE_KIND_BY_STATE = {
    "waiting_approval": "approval",
    "waiting_output": "output",
    "waiting_recovery": "recovery",
    "paused": "pause",
}
CHOICES_BY_GATE_KIND = {
    "approval": frozenset({"approve", "reject"}),
    "recovery": frozenset({"retry", "cancel"}),
    "pause": frozenset({"resume", "cancel"}),
    "output": frozenset(),
}
NEXT_STATE_BY_DECISION = {
    ("approval", "approve"): "queued",
    ("approval", "reject"): "cancelled",
    ("recovery", "retry"): "queued",
    ("recovery", "cancel"): "cancelled",
    ("pause", "resume"): "queued",
    ("pause", "cancel"): "cancelled",
}


class WorkflowRuntimeConflict(RuntimeError):
    """A safe, expected conflict caused by stale state, ownership, or input."""

    def __init__(self, code, public_message="Workflow runtime changed. Reload and try again."):
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


RuntimeConflict = WorkflowRuntimeConflict


class RuntimeUnavailable(RuntimeError):
    """A safe storage availability wrapper which does not expose provider text."""

    def __init__(self, code="runtime_unavailable", public_message="Workflow runtime storage is unavailable."):
        self.code = code
        self.public_message = public_message
        super().__init__(public_message)


def _now():
    return datetime.now(timezone.utc)


def _as_utc(value):
    if not isinstance(value, datetime):
        raise RuntimeConflict("invalid_clock", "Workflow runtime clock is invalid.")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value):
    return _as_utc(value).isoformat()


def _valid_id(value, *, max_length=256):
    return (
        isinstance(value, str)
        and 0 < len(value) <= max_length
        and value == value.strip()
        and not any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
    )


def _require_id(value, name, *, max_length=256):
    if not _valid_id(value, max_length=max_length):
        raise RuntimeConflict("invalid_identity", f"{name} is required.")
    return value


def _identity(workflow, run_id):
    if not isinstance(workflow, dict):
        raise RuntimeConflict("invalid_identity", "Workflow identity is required.")
    workflow_id = _require_id(workflow.get("id"), "workflow_id")
    user_id = _require_id(workflow.get("user_id"), "user_id")
    normalized_run_id = _require_id(run_id, "run_id")
    group_id = workflow.get("group_id")
    if group_id is None:
        return {
            "workflow_id": workflow_id,
            "user_id": user_id,
            "group_id": None,
            "scope_type": "personal",
            "scope_id": user_id,
            "run_id": normalized_run_id,
        }
    group_id = _require_id(group_id, "group_id")
    return {
        "workflow_id": workflow_id,
        "user_id": user_id,
        "group_id": group_id,
        "scope_type": "group",
        "scope_id": group_id,
        "run_id": normalized_run_id,
    }


def _json_check(value, *, depth=0):
    if depth > 64:
        raise RuntimeConflict("invalid_payload", "Workflow runtime payload is too deeply nested.")
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float and math.isfinite(value):
        return
    if isinstance(value, list):
        for item in value:
            _json_check(item, depth=depth + 1)
        return
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _json_check(item, depth=depth + 1)
        return
    raise RuntimeConflict("invalid_payload", "Workflow runtime payload must be finite JSON.")


def _json_bytes(value):
    _json_check(value)
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RuntimeConflict("invalid_payload", "Workflow runtime payload must be finite JSON.") from exc


def _bounded_json_copy(value, *, max_bytes=MAX_CONTROL_BYTES):
    copied = deepcopy(value)
    if len(_json_bytes(copied)) > max_bytes:
        raise RuntimeConflict("payload_too_large", "Workflow runtime payload is too large.")
    return copied


def _strip_cosmos_metadata(record):
    return {key: deepcopy(value) for key, value in record.items() if not key.startswith("_")}


def _has_forbidden_key(value, forbidden_parts, *, allow_ref_suffix=False):
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = key.lower()
            safe_reference_key = allow_ref_suffix and (lowered.endswith("_ref") or lowered.endswith("_refs"))
            if any(part in lowered for part in forbidden_parts) and not safe_reference_key:
                return True
            if _has_forbidden_key(item, forbidden_parts, allow_ref_suffix=allow_ref_suffix):
                return True
    if isinstance(value, list):
        return any(_has_forbidden_key(item, forbidden_parts, allow_ref_suffix=allow_ref_suffix) for item in value)
    return False


def _parse_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_live_lease(control, now_value):
    lease = control.get("lease")
    if not isinstance(lease, dict) or not lease.get("token"):
        return False
    expires_at = _parse_timestamp(lease.get("expires_at"))
    if expires_at is None:
        return True
    return expires_at > now_value


def _is_condition_failed(exc):
    return getattr(exc, "status_code", None) == 412


def _is_not_found(exc):
    return getattr(exc, "status_code", None) == 404


def _validate_state(state, allowed_states=ALL_STATES):
    if state not in allowed_states:
        raise RuntimeConflict("invalid_state", "Workflow runtime state is invalid.")
    return state


def _validate_gate(gate, state):
    expected_kind = GATE_KIND_BY_STATE[state]
    if not isinstance(gate, dict):
        raise RuntimeConflict("invalid_gate", "Workflow runtime gate is invalid.")
    if set(gate) - GATE_ALLOWED_KEYS:
        raise RuntimeConflict("invalid_gate", "Workflow runtime gate contains unsupported fields.")
    if _has_forbidden_key(gate, FORBIDDEN_GATE_KEY_PARTS, allow_ref_suffix=True):
        raise RuntimeConflict("invalid_gate", "Workflow runtime gate contains unsafe fields.")
    gate_id = _require_id(gate.get("id"), "gate_id")
    kind = gate.get("kind")
    if kind != expected_kind:
        raise RuntimeConflict("invalid_gate", "Workflow runtime gate kind does not match state.")
    choices = gate.get("choices")
    allowed_choices = CHOICES_BY_GATE_KIND[kind]
    if choices is None:
        choices = sorted(allowed_choices)
    if not isinstance(choices, list) or any(not _valid_id(choice, max_length=64) for choice in choices):
        raise RuntimeConflict("invalid_gate", "Workflow runtime gate choices are invalid.")
    if set(choices) - allowed_choices:
        raise RuntimeConflict("invalid_gate", "Workflow runtime gate choices are not allowed.")
    if kind != "output" and not choices:
        raise RuntimeConflict("invalid_gate", "Workflow runtime gate choices are required.")
    if kind == "output" and choices:
        raise RuntimeConflict("invalid_gate", "Output gates cannot declare human approval choices.")
    normalized = _bounded_json_copy({**gate, "id": gate_id, "kind": kind, "choices": choices}, max_bytes=MAX_GATE_BYTES)
    return normalized


def _decision_history(memory):
    if not isinstance(memory, dict):
        raise RuntimeConflict("invalid_payload", "Workflow runtime memory is invalid.")
    decisions = memory.get("decisions", [])
    if not isinstance(decisions, list):
        raise RuntimeConflict("invalid_payload", "Workflow runtime decisions are invalid.")
    return decisions


def _append_decision(memory, decision):
    next_memory = deepcopy(memory) if isinstance(memory, dict) else {}
    decisions = list(_decision_history(next_memory))
    if len(decisions) >= MAX_DECISIONS:
        raise RuntimeConflict("decision_history_full", "Workflow runtime decision history is full.")
    decisions.append(_bounded_json_copy(decision, max_bytes=MAX_GATE_BYTES))
    next_memory["decisions"] = decisions
    return next_memory


def _find_request_marker(memory, request_id, collection_name):
    if not isinstance(memory, dict):
        return None
    markers = memory.get(collection_name, [])
    if not isinstance(markers, list):
        raise RuntimeConflict("invalid_payload", "Workflow runtime request history is invalid.")
    for marker in markers:
        if isinstance(marker, dict) and marker.get("request_id") == request_id:
            return marker
    return None


def _append_request_marker(memory, collection_name, marker):
    next_memory = deepcopy(memory) if isinstance(memory, dict) else {}
    markers = next_memory.get(collection_name, [])
    if not isinstance(markers, list):
        raise RuntimeConflict("invalid_payload", "Workflow runtime request history is invalid.")
    if len(markers) >= MAX_DECISIONS:
        raise RuntimeConflict("request_history_full", "Workflow runtime request history is full.")
    markers = list(markers)
    markers.append(_bounded_json_copy(marker, max_bytes=MAX_GATE_BYTES))
    next_memory[collection_name] = markers
    return next_memory


def _safe_ref(value):
    blocked = ("payload", "content", "raw", "token", "secret", "password", "connection", "snapshot_values", "run_record")
    if isinstance(value, dict):
        return {
            key: _safe_ref(item)
            for key, item in value.items()
            if isinstance(key, str) and not any(part in key.lower() for part in blocked)
        }
    if isinstance(value, list):
        return [_safe_ref(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return deepcopy(value)
    if type(value) is float and math.isfinite(value):
        return value
    return None


def _unit_projection(unit):
    if not isinstance(unit, dict):
        return None
    allowed = {
        "id",
        "unit_id",
        "state",
        "status",
        "phase",
        "progress",
        "replay_safe",
        "effects_uncertain",
        "result_ref",
        "completion_ref",
        "output_ref",
        "error_ref",
        "started_at",
        "completed_at",
        "attempt",
        "input_digest",
    }
    projected = {}
    for key in allowed:
        if key not in unit:
            continue
        projected[key] = _safe_ref(unit[key]) if key.endswith("_ref") else deepcopy(unit[key])
    return projected


def public_projection(control):
    """Return a safe browser/API projection of a runtime control row.

    The projection intentionally excludes leases, claim tokens, raw snapshots,
    execution context, run records, and private provider payloads.
    """
    if not isinstance(control, dict):
        raise RuntimeConflict("not_found", "Workflow runtime control was not found.")
    memory = control.get("memory") if isinstance(control.get("memory"), dict) else {}
    units = control.get("units") if isinstance(control.get("units"), dict) else {}
    unit_items = {
        key: projected
        for key, unit in units.items()
        for projected in (_unit_projection(unit),)
        if isinstance(key, str) and projected is not None
    }
    decisions = [
        {
            key: deepcopy(decision.get(key))
            for key in (
                "gate_id", "gate_kind", "choice", "actor_user_id", "request_id",
                "decided_at", "unit_id", "input_digest", "attempt",
            )
            if key in decision
        }
        for decision in memory.get("decisions", [])
        if isinstance(decision, dict)
    ]
    gate = control.get("gate") if isinstance(control.get("gate"), dict) else None
    safe_gate = None
    if gate:
        safe_gate = {}
        for key in GATE_ALLOWED_KEYS:
            if key not in gate or key == "metadata":
                continue
            if key == "references":
                references = gate[key] if isinstance(gate[key], list) else []
                safe_gate[key] = {"count": len(references)}
            elif key.endswith("_ref"):
                safe_gate[key] = _safe_ref(gate[key])
            else:
                safe_gate[key] = deepcopy(gate[key])
        if isinstance(gate.get("metadata"), dict):
            safe_gate["metadata"] = _safe_ref(gate["metadata"])
    return {
        "schema_version": control.get("schema_version", 1),
        "version": control.get("version"),
        "state": control.get("state"),
        "control_state": control.get("state"),
        "created_at": control.get("created_at"),
        "actor_user_id": control.get("actor_user_id"),
        "snapshot_ref": _safe_ref(control.get("snapshot_ref")),
        "phase": control.get("phase"),
        "progress": control.get("progress"),
        **({
            "limits": {
                "max_executions": control["max_executions"],
                "admitted_count": int(control.get("admitted_count") or 0),
                "deadline_at": control["deadline_at"],
                "deadline_seconds": control["deadline_seconds"],
                "waits_count": True,
            },
        } if control.get("schema_version") == 2 else {}),
        "deleted": bool(control.get("deleted")),
        "gate": safe_gate,
        "memory": {
            "unit_count": int((control.get("journal_counts") or {}).get("unit") or 0) if control.get("schema_version") == 2 else len(units),
            "completed_unit_count": int(control.get("completed_unit_count") or 0) if control.get("schema_version") == 2 else sum(
                1 for unit in units.values()
                if isinstance(unit, dict) and (unit.get("state") or unit.get("status")) == "completed"
            ),
            "units": [
                {"key": key, **unit_items[key]}
                for key in sorted(unit_items)
            ],
            "decisions": decisions[-MAX_DECISIONS:],
            **({
                "execution_count": int((control.get("journal_counts") or {}).get("execution") or 0),
                "decision_count": int((control.get("journal_counts") or {}).get("decision") or 0),
            } if control.get("schema_version") == 2 else {}),
        },
        "can_resume": control.get("state") in RESUMABLE_STATES and not control.get("deleted"),
    }


workflow_runtime_projection = public_projection


class WorkflowRuntimeStore(WorkflowJournalMixin):
    """Dependency-injected durable control journal for one authorized workflow run.

    ``container`` is the existing personal/group workflow_run_items Cosmos
    container partitioned by ``run_id``. Callers must authorize the owning
    workflow and run before constructing the store. Every read and write then
    verifies the stored row still matches the bound workflow/run/scope identity.

    ``update(..., expected_version=control["version"])`` should be used for
    whole-map payloads such as ``units`` so concurrent unit progress is never
    overwritten by stale caller state. Heartbeats intentionally do not increment
    the public decision version; all content/state mutations do.
    """

    def __init__(self, container, workflow, run_id, *, clock=None):
        if container is None:
            raise ValueError("A workflow run-items container is required.")
        self.container = container
        self.identity = _identity(workflow, run_id)
        self.workflow = deepcopy(workflow)
        self.clock = clock or _now

    def _now(self):
        return _as_utc(self.clock())

    def _verify_identity(self, control, *, allow_deleted=False):
        if not isinstance(control, dict):
            raise RuntimeConflict("not_found", "Workflow runtime control was not found.")
        if any(control.get(key) != value for key, value in self.identity.items()):
            raise RuntimeConflict("identity_mismatch", "Workflow runtime identity does not match this run.")
        if control.get("id") != CONTROL_ID or control.get("type") != CONTROL_TYPE or control.get("item_type") != CONTROL_TYPE:
            raise RuntimeConflict("identity_mismatch", "Workflow runtime control row is invalid.")
        if control.get("kind") != "run" or type(control.get("schema_version")) is not int or control.get("schema_version") not in {1, 2}:
            raise RuntimeConflict("identity_mismatch", "Workflow runtime control row version is invalid.")
        if control.get("deleted") and not allow_deleted:
            raise RuntimeConflict("not_found", "Workflow runtime control was deleted.")
        return control

    def _read_control(self, *, allow_deleted=False):
        try:
            current = self.container.read_item(item=CONTROL_ID, partition_key=self.identity["run_id"])
        except cosmos_exceptions.CosmosResourceNotFoundError as exc:
            raise RuntimeConflict("not_found", "Workflow runtime control was not found.") from exc
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            if _is_not_found(exc):
                raise RuntimeConflict("not_found", "Workflow runtime control was not found.") from exc
            raise RuntimeUnavailable() from exc
        return self._verify_identity(current, allow_deleted=allow_deleted)

    def _replace(self, current, replacement):
        try:
            saved = self.container.replace_item(
                item=CONTROL_ID,
                body=replacement,
                etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            if _is_condition_failed(exc):
                raise RuntimeConflict("etag_conflict") from exc
            if _is_not_found(exc):
                raise RuntimeConflict("not_found", "Workflow runtime control was not found.") from exc
            raise RuntimeUnavailable() from exc
        return self._verify_identity(saved, allow_deleted=True)

    def _mutate(self, mutator, *, allow_deleted=False, attempts=MAX_CAS_RETRIES):
        for _attempt in range(attempts):
            current = self._read_control(allow_deleted=allow_deleted)
            replacement = mutator(current)
            if replacement is NO_WRITE:
                return current
            _bounded_json_copy(replacement)
            try:
                return self._replace(current, replacement)
            except RuntimeConflict as exc:
                if exc.code != "etag_conflict":
                    raise
        raise RuntimeConflict("etag_conflict", "Workflow runtime changed concurrently. Retry the operation.")

    def _base_replacement(self, current):
        replacement = _strip_cosmos_metadata(current)
        replacement["updated_at"] = _iso(self._now())
        return replacement

    def _runtime_record(self, record):
        if not isinstance(record, dict):
            raise RuntimeConflict("invalid_payload", "Workflow runtime record is invalid.")
        body = _bounded_json_copy(record)
        if body.get("id") == CONTROL_ID:
            raise RuntimeConflict("invalid_payload", "Workflow runtime record id is reserved.")
        _require_id(body.get("id"), "record_id")
        if body.get("run_id") != self.identity["run_id"]:
            raise RuntimeConflict("identity_mismatch", "Workflow runtime record run does not match this journal.")
        for key, value in self.identity.items():
            if key in body and body[key] != value:
                raise RuntimeConflict("identity_mismatch", "Workflow runtime record identity does not match this journal.")
            body[key] = value
        return body

    def _verify_existing_record(self, body):
        saved = self.container.read_item(item=body["id"], partition_key=self.identity["run_id"])
        if _strip_cosmos_metadata(saved) != body:
            raise RuntimeConflict("immutable_conflict", "Workflow runtime immutable record already exists.")
        return _strip_cosmos_metadata(saved)

    def read(self, *, allow_deleted=False):
        """Return the internal control row after identity and tombstone checks."""
        return self._read_control(allow_deleted=allow_deleted)

    def expire_deadline(self):
        def mutator(current):
            deadline = _parse_timestamp(current.get("deadline_at"))
            if current.get("schema_version") != 2 or deadline is None or self._now() < deadline or current["state"] in TERMINAL_STATES | {"paused"}:
                return NO_WRITE
            return self._limit_pause(current, "deadline_exceeded")

        return self._mutate(mutator)

    def _limit_pause(self, current, code):
        replacement = self._base_replacement(current)
        node_id = (current.get("cursor") or {}).get("node_id")
        replacement.update(state="paused", phase=code, lease=None, version=current["version"] + 1, gate={
            "id": uuid.uuid4().hex, "kind": "pause", "unit_id": node_id or "run-limits",
            "input_digest": current["definition_revision"], "choices": ["cancel"],
            "reason": (
                "The elapsed workflow deadline was reached, including time spent waiting. Cancel and start a new run."
                if code == "deadline_exceeded" else
                "The workflow execution admission limit was reached. Cancel and start a new run with an appropriate limit."
            ),
        })
        return replacement

    def pause_execution_limit(self, token, code):
        if code not in {"deadline_exceeded", "execution_budget_exceeded"}:
            raise RuntimeConflict("invalid_limit")

        def mutator(current):
            self._assert_current_owned(current, token)
            return self._limit_pause(current, code)

        return self._mutate(mutator)

    def run_definition(self):
        from functions_workflow_definitions import workflow_definition_revision
        from functions_workflow_result_store import load_workflow_task_result, load_workflow_runtime_result

        control = self._read_control()
        snapshot = (
            load_workflow_runtime_result(self.workflow, self.identity["run_id"], control, control["snapshot_ref"])
            if control.get("schema_version") == 2 else
            load_workflow_task_result(self.workflow, self.identity["run_id"], "runtime:definition", control["snapshot_ref"])
        )
        if (
            workflow_definition_revision(snapshot) != control["definition_revision"]
            or snapshot.get("id") != self.identity["workflow_id"] or snapshot.get("user_id") != self.identity["user_id"]
            or (snapshot.get("group_id") or None) != self.identity["group_id"]
        ):
            raise RuntimeConflict("workflow_definition_changed")
        return snapshot

    def write_record(self, token, record, *, immutable=False):
        """Fence a run-item payload write behind the live runtime-control lease.

        This writes only in the existing run-items partition. The control row is
        conditionally replaced with a fresh nonce so tombstones, cancellation,
        lease expiry, and lease takeover fence any payload/chunk write. Public
        runtime ``version`` is not incremented because payload writes must not
        invalidate approval or recovery expected-version decisions.
        """
        self._assert_token_shape(token)
        body = self._runtime_record(record)
        operation = "create" if immutable else "upsert"
        for _attempt in range(MAX_CAS_RETRIES):
            control = self._read_control()
            self._assert_current_owned(control, token)
            replacement = self._base_replacement(control)
            replacement["write_nonce"] = uuid.uuid4().hex
            operations = [
                ("replace", (CONTROL_ID, replacement), {"if_match_etag": control["_etag"]}),
                (operation, (body,)),
            ]
            try:
                self.container.execute_item_batch(
                    batch_operations=operations, partition_key=self.identity["run_id"],
                )
                return deepcopy(body)
            except (cosmos_exceptions.CosmosBatchOperationError, cosmos_exceptions.CosmosHttpResponseError) as exc:
                status_code = getattr(exc, "status_code", None)
                if status_code == 412:
                    continue
                if immutable and status_code == 409:
                    self.assert_owned(token)
                    return self._verify_existing_record(body)
                raise
        raise RuntimeConflict("etag_conflict", "Workflow runtime changed concurrently. Retry the operation.")

    def initialize(self, *, snapshot_ref, definition_revision, actor_user_id, request_id):
        actor_user_id = _require_id(actor_user_id, "actor_user_id")
        request_id = _require_id(request_id, "request_id")
        timestamp = _iso(self._now())
        control = {
            "id": CONTROL_ID,
            "type": CONTROL_TYPE,
            "item_type": CONTROL_TYPE,
            "kind": "run",
            "schema_version": SCHEMA_VERSION,
            **self.identity,
            "snapshot_ref": _bounded_json_copy(snapshot_ref, max_bytes=MAX_GATE_BYTES),
            "definition_revision": _bounded_json_copy(definition_revision, max_bytes=MAX_GATE_BYTES),
            "actor_user_id": actor_user_id,
            "request_id": request_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "state": "queued",
            "version": 1,
            "units": {},
            "memory": {},
            "gate": None,
            "lease": None,
            "deleted": False,
        }
        if self.workflow.get("definition_version") == 3:
            from functions_workflow_flow import compile_workflow_flow

            compiled = compile_workflow_flow(self.workflow)
            control.update(
                schema_version=2, cursor={"region_id": compiled["flow"]["id"], "node_id": None},
                snapshot_identity={"node_id": compiled["flow"]["id"],
                                   "execution_id": workflow_execution_id(self.workflow, self.identity["run_id"], compiled["flow"]["id"]),
                                   "attempt": 1, "iteration_path": []},
                admitted_count=0, journal_sequence=0, journal_counts={},
                max_executions=compiled["limits"]["max_executions"],
                deadline_seconds=compiled["limits"]["deadline_seconds"],
                deadline_at=_iso(self._now() + timedelta(seconds=compiled["limits"]["deadline_seconds"])),
            )
        _bounded_json_copy(control)
        try:
            saved = self.container.create_item(body=control)
            return self._verify_identity(saved)
        except cosmos_exceptions.CosmosResourceExistsError:
            existing = self._read_control(allow_deleted=True)
            if existing.get("deleted"):
                raise RuntimeConflict("tombstoned", "Workflow runtime control was deleted.") from None
            same_replay = (
                existing.get("request_id") == request_id
                and existing.get("snapshot_ref") == control["snapshot_ref"]
                and existing.get("definition_revision") == control["definition_revision"]
                and existing.get("actor_user_id") == actor_user_id
                and all(existing.get(key) == value for key, value in self.identity.items())
            )
            if not same_replay:
                raise RuntimeConflict("initialize_conflict", "Workflow runtime was already initialized.") from None
            return existing
        except cosmos_exceptions.CosmosHttpResponseError as exc:
            if getattr(exc, "status_code", None) == 409:
                raise RuntimeConflict("initialize_conflict", "Workflow runtime was already initialized.") from exc
            raise RuntimeUnavailable() from exc

    def _token_from_lease(self, lease):
        return {
            "token": lease["token"],
            "owner_id": lease["owner_id"],
            "epoch": lease.get("epoch", 0),
            "workflow_id": self.identity["workflow_id"],
            "run_id": self.identity["run_id"],
            "scope_type": self.identity["scope_type"],
            "scope_id": self.identity["scope_id"],
        }

    def _assert_token_shape(self, token):
        if not isinstance(token, dict):
            raise RuntimeConflict("ownership_lost", "Workflow runtime ownership was lost.")
        if (
            token.get("workflow_id") != self.identity["workflow_id"]
            or token.get("run_id") != self.identity["run_id"]
            or token.get("scope_type") != self.identity["scope_type"]
            or token.get("scope_id") != self.identity["scope_id"]
            or not _valid_id(token.get("owner_id"), max_length=256)
            or not _valid_id(token.get("token"), max_length=256)
        ):
            raise RuntimeConflict("ownership_lost", "Workflow runtime ownership was lost.")

    def claim(self, *, owner_id, ttl_seconds=DEFAULT_LEASE_SECONDS):
        owner_id = _require_id(owner_id, "owner_id")
        ttl_seconds = self._validate_ttl(ttl_seconds)
        now_value = self._now()
        created = None

        def mutator(current):
            nonlocal created
            if current.get("deleted"):
                raise RuntimeConflict("not_found", "Workflow runtime control was deleted.")
            state = current.get("state")
            if state not in CLAIM_STATES:
                return None
            lease = current.get("lease") if isinstance(current.get("lease"), dict) else None
            if lease and lease.get("token") and _parse_timestamp(lease.get("expires_at")) is None:
                return None
            if _is_live_lease(current, now_value):
                if state == "running" and lease and lease.get("owner_id") == owner_id:
                    created = self._token_from_lease(lease)
                return None
            epoch = (lease.get("epoch", 0) if lease else 0) + 1
            new_lease = {
                "token": uuid.uuid4().hex,
                "owner_id": owner_id,
                "epoch": epoch,
                "claimed_at": _iso(now_value),
                "heartbeat_at": _iso(now_value),
                "expires_at": _iso(now_value + timedelta(seconds=ttl_seconds)),
            }
            replacement = self._base_replacement(current)
            replacement["state"] = "running"
            replacement["lease"] = new_lease
            created = self._token_from_lease(new_lease)
            return replacement

        for _attempt in range(MAX_CAS_RETRIES):
            current = self._read_control()
            replacement = mutator(current)
            if created and replacement is None:
                return created
            if replacement is None:
                return None
            _bounded_json_copy(replacement)
            try:
                self._replace(current, replacement)
                return created
            except RuntimeConflict as exc:
                if exc.code != "etag_conflict":
                    raise
                created = None
        raise RuntimeConflict("etag_conflict", "Workflow runtime changed concurrently. Retry the operation.")

    def _validate_ttl(self, ttl_seconds):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise RuntimeConflict("invalid_ttl", "Workflow runtime lease TTL is invalid.")
        return ttl_seconds

    def assert_owned(self, token):
        self._assert_token_shape(token)
        control = self._read_control()
        lease = control.get("lease")
        expires_at = _parse_timestamp(lease.get("expires_at")) if isinstance(lease, dict) else None
        if (
            control.get("state") != "running"
            or not isinstance(lease, dict)
            or lease.get("token") != token.get("token")
            or lease.get("owner_id") != token.get("owner_id")
            or lease.get("epoch") != token.get("epoch")
            or expires_at is None
            or expires_at <= self._now()
        ):
            raise RuntimeConflict("ownership_lost", "Workflow runtime ownership was lost.")
        return control

    def update(self, token, updates, *, expected_version=None):
        self._assert_token_shape(token)
        if not isinstance(updates, dict) or not updates:
            raise RuntimeConflict("invalid_payload", "Workflow runtime updates are invalid.")
        if set(updates) - ALLOWED_UPDATE_KEYS:
            raise RuntimeConflict("invalid_payload", "Workflow runtime updates contain unsupported fields.")
        if _has_forbidden_key(updates.get("metadata", {}), FORBIDDEN_PAYLOAD_KEY_PARTS):
            raise RuntimeConflict("invalid_payload", "Workflow runtime metadata contains unsafe fields.")
        if "units" in updates and expected_version is None:
            raise RuntimeConflict(
                "expected_version_required",
                "Workflow runtime unit updates require an expected version.",
            )
        copied_updates = _bounded_json_copy(updates)

        def mutator(current):
            self._assert_current_owned(current, token)
            if expected_version is not None and current.get("version") != expected_version:
                raise RuntimeConflict("stale_version", "Workflow runtime version changed. Reload and try again.")
            replacement = self._base_replacement(current)
            for key, value in copied_updates.items():
                replacement[key] = deepcopy(value)
            replacement["version"] = int(current.get("version", 0)) + 1
            return replacement

        attempts = 1 if expected_version is None else MAX_CAS_RETRIES
        return self._mutate(mutator, attempts=attempts)

    def _assert_current_owned(self, control, token):
        self._verify_identity(control)
        lease = control.get("lease")
        expires_at = _parse_timestamp(lease.get("expires_at")) if isinstance(lease, dict) else None
        if (
            control.get("state") != "running"
            or not isinstance(lease, dict)
            or lease.get("token") != token.get("token")
            or lease.get("owner_id") != token.get("owner_id")
            or lease.get("epoch") != token.get("epoch")
            or expires_at is None
            or expires_at <= self._now()
        ):
            raise RuntimeConflict("ownership_lost", "Workflow runtime ownership was lost.")

    def heartbeat(self, token, *, ttl_seconds=DEFAULT_LEASE_SECONDS):
        self._assert_token_shape(token)
        ttl_seconds = self._validate_ttl(ttl_seconds)

        def mutator(current):
            self._assert_current_owned(current, token)
            now_value = self._now()
            replacement = self._base_replacement(current)
            lease = deepcopy(replacement["lease"])
            lease["heartbeat_at"] = _iso(now_value)
            lease["expires_at"] = _iso(now_value + timedelta(seconds=ttl_seconds))
            replacement["lease"] = lease
            return replacement

        return self._mutate(mutator)

    def wait(self, token, *, state, gate=None):
        self._assert_token_shape(token)
        state = _validate_state(state, WAITING_STATES)
        normalized_gate = _validate_gate(gate or {}, state)

        def mutator(current):
            self._assert_current_owned(current, token)
            replacement = self._base_replacement(current)
            replacement["state"] = state
            replacement["gate"] = normalized_gate
            replacement["lease"] = None
            replacement["version"] = int(current.get("version", 0)) + 1
            return replacement

        return self._mutate(mutator)

    def transition(self, token, *, state, completion_ref=None):
        self._assert_token_shape(token)
        state = _validate_state(state, TERMINAL_STATES)
        copied_completion_ref = _bounded_json_copy(completion_ref, max_bytes=MAX_GATE_BYTES) if completion_ref is not None else None

        def mutator(current):
            self._assert_current_owned(current, token)
            replacement = self._base_replacement(current)
            replacement["state"] = state
            replacement["gate"] = None
            replacement["lease"] = None
            if copied_completion_ref is not None:
                replacement["completion_ref"] = copied_completion_ref
            replacement["version"] = int(current.get("version", 0)) + 1
            return replacement

        return self._mutate(mutator)

    def decide(self, *, expected_version, gate_id, choice, actor_user_id, request_id):
        if self._read_control().get("schema_version") == 2:
            return self.journal_decide(
                expected_version=expected_version, gate_id=gate_id, choice=choice,
                actor_user_id=actor_user_id, request_id=request_id,
            )
        if type(expected_version) is not int:
            raise RuntimeConflict("stale_version", "Workflow runtime version is required.")
        gate_id = _require_id(gate_id, "gate_id")
        choice = _require_id(choice, "choice", max_length=64)
        actor_user_id = _require_id(actor_user_id, "actor_user_id")
        request_id = _require_id(request_id, "request_id")

        def mutator(current):
            if current.get("deleted"):
                raise RuntimeConflict("not_found", "Workflow runtime control was deleted.")
            marker = _find_request_marker(current.get("memory") or {}, request_id, "decisions")
            if marker is not None:
                if (
                    marker.get("gate_id") == gate_id
                    and marker.get("choice") == choice
                    and marker.get("actor_user_id") == actor_user_id
                ):
                    return NO_WRITE
                raise RuntimeConflict("request_conflict", "Workflow runtime request id was reused differently.")
            if current.get("version") != expected_version:
                raise RuntimeConflict("stale_version", "Workflow runtime version changed. Reload and try again.")
            gate = current.get("gate")
            if not isinstance(gate, dict) or gate.get("id") != gate_id:
                raise RuntimeConflict("stale_gate", "Workflow runtime gate changed. Reload and try again.")
            kind = gate.get("kind")
            if kind == "output":
                raise RuntimeConflict("unsupported_gate", "Output gates are requeued by the scheduler.")
            if (kind, choice) not in NEXT_STATE_BY_DECISION:
                raise RuntimeConflict("invalid_choice", "Workflow runtime decision is invalid.")
            choices = gate.get("choices")
            if not isinstance(choices, list) or choice not in choices:
                raise RuntimeConflict("invalid_choice", "Workflow runtime decision is not declared by the gate.")
            decision = {
                "request_id": request_id,
                "gate_id": gate_id,
                "gate_kind": kind,
                "choice": choice,
                "actor_user_id": actor_user_id,
                "decided_at": _iso(self._now()),
                "unit_id": gate.get("unit_id"),
                "input_digest": gate.get("input_digest"),
                "attempt": gate.get("attempt"),
            }
            replacement = self._base_replacement(current)
            replacement["state"] = NEXT_STATE_BY_DECISION[(kind, choice)]
            replacement["gate"] = None
            replacement["lease"] = None
            replacement["memory"] = _append_decision(current.get("memory") or {}, decision)
            replacement["version"] = int(current.get("version", 0)) + 1
            return replacement

        return self._mutate(mutator, attempts=MAX_CAS_RETRIES)

    def request_cancel(self, *, actor_user_id, request_id):
        if self._read_control().get("schema_version") == 2:
            return self.journal_request("cancel", actor_user_id=actor_user_id, request_id=request_id)
        actor_user_id = _require_id(actor_user_id, "actor_user_id")
        request_id = _require_id(request_id, "request_id")

        def mutator(current):
            marker = _find_request_marker(current.get("memory") or {}, request_id, "cancel_requests")
            if marker is not None:
                if marker.get("actor_user_id") == actor_user_id:
                    return NO_WRITE
                raise RuntimeConflict("request_conflict", "Workflow runtime request id was reused differently.")
            if current.get("state") in TERMINAL_STATES:
                return NO_WRITE
            replacement = self._base_replacement(current)
            marker = {
                "request_id": request_id,
                "actor_user_id": actor_user_id,
                "requested_at": _iso(self._now()),
                "state_at_request": current.get("state"),
            }
            replacement["memory"] = _append_request_marker(current.get("memory") or {}, "cancel_requests", marker)
            if current.get("state") in {"queued", "running", "cancelling"} | WAITING_STATES:
                replacement["state"] = "cancelled"
                replacement["gate"] = None
                replacement["lease"] = None
            else:
                raise RuntimeConflict("invalid_state", "Workflow runtime state cannot be cancelled.")
            replacement["version"] = int(current.get("version", 0)) + 1
            return replacement

        return self._mutate(mutator, attempts=MAX_CAS_RETRIES)

    def requeue_output(self, *, expected_version, gate_id):
        if type(expected_version) is not int:
            raise RuntimeConflict("stale_version", "Workflow runtime version is required.")
        gate_id = _require_id(gate_id, "gate_id")

        def mutator(current):
            if current.get("version") != expected_version:
                raise RuntimeConflict("stale_version", "Workflow runtime version changed. Reload and try again.")
            gate = current.get("gate")
            if current.get("state") != "waiting_output" or not isinstance(gate, dict):
                raise RuntimeConflict("stale_gate", "Workflow runtime output gate is not active.")
            if gate.get("id") != gate_id or gate.get("kind") != "output":
                raise RuntimeConflict("stale_gate", "Workflow runtime output gate changed.")
            replacement = self._base_replacement(current)
            replacement["state"] = "queued"
            replacement["gate"] = None
            replacement["lease"] = None
            replacement["version"] = int(current.get("version", 0)) + 1
            return replacement

        return self._mutate(mutator, attempts=MAX_CAS_RETRIES)

    def resume(self, *, expected_version, actor_user_id, request_id):
        if self._read_control().get("schema_version") == 2:
            return self.journal_request("resume", actor_user_id=actor_user_id, request_id=request_id, expected_version=expected_version)
        if type(expected_version) is not int:
            raise RuntimeConflict("stale_version", "Workflow runtime version is required.")
        actor_user_id = _require_id(actor_user_id, "actor_user_id")
        request_id = _require_id(request_id, "request_id")

        def mutator(current):
            marker = _find_request_marker(current.get("memory") or {}, request_id, "resume_requests")
            if marker is not None:
                if marker.get("actor_user_id") == actor_user_id:
                    return NO_WRITE
                raise RuntimeConflict("request_conflict", "Workflow runtime request id was reused differently.")
            if current.get("version") != expected_version:
                raise RuntimeConflict("stale_version", "Workflow runtime version changed. Reload and try again.")
            if current.get("state") not in RESUMABLE_STATES:
                raise RuntimeConflict("invalid_state", "Workflow runtime state cannot be resumed.")
            marker = {
                "request_id": request_id,
                "actor_user_id": actor_user_id,
                "requested_at": _iso(self._now()),
                "state_at_request": current.get("state"),
            }
            replacement = self._base_replacement(current)
            replacement["state"] = "queued"
            replacement["gate"] = None
            replacement["lease"] = None
            replacement["memory"] = _append_request_marker(current.get("memory") or {}, "resume_requests", marker)
            replacement["version"] = int(current.get("version", 0)) + 1
            return replacement

        return self._mutate(mutator, attempts=MAX_CAS_RETRIES)

    def release(self, token):
        self._assert_token_shape(token)

        def mutator(current):
            self._verify_identity(current)
            lease = current.get("lease")
            if (
                current.get("state") != "running"
                or not isinstance(lease, dict)
                or lease.get("token") != token.get("token")
                or lease.get("owner_id") != token.get("owner_id")
                or lease.get("epoch") != token.get("epoch")
            ):
                return NO_WRITE
            replacement = self._base_replacement(current)
            next_lease = deepcopy(lease)
            next_lease["expires_at"] = _iso(self._now())
            replacement["lease"] = next_lease
            return replacement

        return self._mutate(mutator, attempts=MAX_CAS_RETRIES)

    def tombstone(self):
        try:
            self._read_control(allow_deleted=True)
        except RuntimeConflict as exc:
            if exc.code != "not_found":
                raise
            timestamp = _iso(self._now())
            barrier = {
                **self.identity, "id": CONTROL_ID, "type": CONTROL_TYPE, "item_type": CONTROL_TYPE,
                "kind": "run", "schema_version": SCHEMA_VERSION, "state": "cancelled", "version": 1,
                "created_at": timestamp, "updated_at": timestamp, "deleted": True,
                "gate": None, "lease": None, "units": {}, "memory": {},
            }
            try:
                return self._verify_identity(self.container.create_item(body=barrier), allow_deleted=True)
            except cosmos_exceptions.CosmosResourceExistsError:
                pass
            except cosmos_exceptions.CosmosHttpResponseError as error:
                raise RuntimeUnavailable() from error

        def mutator(current):
            if current.get("deleted"):
                return NO_WRITE
            replacement = self._base_replacement(current)
            replacement["deleted"] = True
            replacement["state"] = "cancelled"
            replacement["gate"] = None
            replacement["lease"] = None
            replacement["version"] = int(current.get("version", 0)) + 1
            return replacement

        return self._mutate(mutator, allow_deleted=True, attempts=MAX_CAS_RETRIES)


class WorkflowRuntimeLease:
    """Context manager which owns a runtime claim and renews it while active."""

    def __init__(
        self,
        store,
        *,
        owner_id,
        ttl_seconds=DEFAULT_LEASE_SECONDS,
        heartbeat_seconds=DEFAULT_HEARTBEAT_SECONDS,
    ):
        self.store = store
        self.owner_id = owner_id
        self.ttl_seconds = ttl_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.token = None
        self._stop = threading.Event()
        self._thread = None
        self._heartbeat_error = None

    def __enter__(self):
        self.token = self.store.claim(owner_id=self.owner_id, ttl_seconds=self.ttl_seconds)
        if self.token is not None and self.heartbeat_seconds > 0:
            self._thread = threading.Thread(target=self._heartbeat_loop, name="workflow-runtime-heartbeat", daemon=True)
            self._thread.start()
        return self

    def _heartbeat_loop(self):
        while not self._stop.wait(self.heartbeat_seconds):
            try:
                self.store.heartbeat(self.token, ttl_seconds=self.ttl_seconds)
            except (RuntimeConflict, RuntimeUnavailable, cosmos_exceptions.CosmosHttpResponseError) as exc:
                self._heartbeat_error = exc
                self._stop.set()
                return

    def check(self):
        if self._heartbeat_error is not None:
            if isinstance(self._heartbeat_error, (RuntimeConflict, RuntimeUnavailable)):
                raise self._heartbeat_error
            raise RuntimeUnavailable() from self._heartbeat_error
        if self.token is None:
            raise RuntimeConflict("not_claimed", "Workflow runtime was not claimed.")
        return self.store.assert_owned(self.token)

    def __exit__(self, exc_type, exc_value, traceback):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1, min(self.heartbeat_seconds, 5)))
        if self.token is not None:
            try:
                self.store.release(self.token)
            except RuntimeConflict as exc:
                if not self._confirmed_expected_cleanup(exc):
                    raise
        return False

    def _confirmed_expected_cleanup(self, release_error):
        if release_error.code != "not_found":
            return False
        try:
            control = self.store.read(allow_deleted=True)
        except RuntimeConflict:
            return False
        return (
            control.get("deleted") is True
            and control.get("state") == "cancelled"
            and control.get("lease") is None
        )


def workflow_runtime_store(workflow, run_id):
    """Create the configured runtime journal store for a personal or group workflow."""
    # Lazy import keeps isolated runtime-store tests from importing deployed app configuration.
    import config

    container = (
        config.cosmos_group_workflow_run_items_container
        if workflow.get("group_id")
        else config.cosmos_personal_workflow_run_items_container
    )
    return WorkflowRuntimeStore(container, workflow, run_id)
