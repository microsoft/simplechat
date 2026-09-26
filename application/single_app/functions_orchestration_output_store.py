# functions_orchestration_output_store.py
"""Per-file admission, leases, and visibility in the existing runs partition.

The owner supplies initialized Cosmos and conversation readers. Every write
compares both the run and output ETags in one partition batch. Neither a blob
nor a file message is a visibility authority. Tombstones are never recreated.
"""

import math
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import islice

from azure.core.exceptions import AzureError
from azure.cosmos import exceptions

from functions_orchestration_result_contracts import (
    ProducerIdentity,
    ResultRef,
    canonical_bytes,
    canonical_digest,
)


OUTPUT_RECORD_TYPE = "orchestration_output_v1"
OUTPUT_CONTRACT_VERSION = "orchestration-output-v1"
OUTPUT_CLEANUP_VERSION = 1
MAX_AUTOMATIC_ATTEMPTS = 3
MAX_MANUAL_ATTEMPTS = 16
MAX_OUTPUTS_PER_RUN = 32
MAX_OUTPUT_DOCUMENT_BYTES = 384 * 1024
MAX_STAGING_GUARDS = 2 * (MAX_AUTOMATIC_ATTEMPTS + MAX_MANUAL_ATTEMPTS)
OUTPUT_STATES = frozenset({
    "waiting", "rendering", "retry_scheduled", "completed", "failed", "cancelled",
})
OUTPUT_UNAVAILABLE_MESSAGES = {
    "output_access_denied": "This file is unavailable because current source access could not be confirmed.",
    "output_screening_hold": "This file is unavailable while its source is under review.",
    "output_source_unavailable": "This file is unavailable because its retained source is missing or no longer readable.",
    "output_source_changed": "This file is unavailable because its source no longer matches the retained version.",
    "output_capability_disabled": "This file is unavailable under the current capability settings.",
    "output_deleted": "This file was deleted.",
    "output_cancelled": "This file was cancelled.",
    "output_superseded": "This file is unavailable because its approved work was superseded.",
    "output_plan_changed": "This file is unavailable because its approved work changed.",
    "output_artifact_missing": "This file is unavailable because its committed artifact is missing.",
    "output_artifact_mismatch": "This file is unavailable because its artifact binding could not be verified.",
    "output_intent_invalid": "This file is unavailable because its artifact binding could not be verified.",
}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_OUTPUT_ID = re.compile(r"orender_[a-f0-9]{64}\Z")
_STORAGE_ERRORS = (AzureError, TimeoutError, ConnectionError)
_STOPPED = frozenset({"cancelled", "canceled", "deleted", "superseded"})
_SYSTEM_FIELDS = frozenset({"_etag", "_rid", "_self", "_attachments", "_ts"})


class OutputError(ValueError):
    """Only stable codes and this fixed message may cross the owner boundary."""

    retryable = False

    def __init__(self, code="output_invalid"):
        self.code = code
        super().__init__("The requested generated file is unavailable.")


class OutputUnavailableError(PermissionError):
    retryable = False

    def __init__(self, code="output_access_denied"):
        self.code = code
        super().__init__("The requested generated file is unavailable under current access.")


class OutputConflictError(RuntimeError):
    retryable = False
    code = "output_ownership_lost"

    def __init__(self):
        super().__init__("Another worker owns the generated file attempt.")


class OutputStorageError(RuntimeError):
    retryable = True
    code = "output_storage_unavailable"

    def __init__(self):
        super().__init__("Generated file storage is temporarily unavailable.")


def utc_now():
    return datetime.now(timezone.utc)


def parse_time(value):
    if type(value) is not str:
        raise OutputError("output_deadline_invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise OutputError("output_deadline_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OutputError("output_deadline_invalid")
    return parsed.astimezone(timezone.utc)


def safe_identity(value):
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise OutputError("output_identity_invalid")
    return value


def _body(value):
    return {key: deepcopy(item) for key, item in value.items() if key not in _SYSTEM_FIELDS}


def _step_signature(step):
    return canonical_digest({
        key: deepcopy(step[key]) for key in (
            "step_id", "capability_id", "role", "arguments", "inputs", "outputs",
            "depends_on", "enabled",
        ) if key in step
    })


def _request_owner(producer):
    return {
        name: producer[name] for name in (
            "user_id", "conversation_id", "step_id", "capability_id", "contract_version",
        )
    }


def _lease_live(record, now):
    lease = record.get("lease")
    return (
        type(lease) is dict and bool(lease.get("token"))
        and parse_time(lease["expires_at"]) > now
    )


@dataclass(frozen=True)
class OutputClaim:
    output_id: str
    token: str
    attempt_number: int
    generation: int
    previous_state: str
    recovering: bool = False


def public_output(record, *, unavailable_code=None, withhold_details=False):
    """The single wire projection; never copy arbitrary stored keys."""
    if type(withhold_details) is not bool or (
        unavailable_code is not None and unavailable_code not in OUTPUT_UNAVAILABLE_MESSAGES
    ):
        raise OutputError("output_projection_invalid")
    available = unavailable_code is None and not record.get("deleted_at") and record["state"] != "cancelled"
    committed = record.get("committed_intent") if record["state"] == "completed" else None
    descriptor = committed or record.get("intent") or {}
    if withhold_details or not available or record.get("error_code") in {
        "output_access_denied", "output_screening_hold", "output_deleted",
        "output_conversation_unavailable", "output_source_unavailable", "output_superseded",
    }:
        descriptor = {}
    projected = {
        "output_id": record["id"],
        "step_id": record["producer"]["step_id"],
        "file_name": record["file_name"],
        "output_format": record["render_spec"]["output_format"],
        "profile": record["render_spec"]["profile"],
        "state": record["state"],
        "available": bool(available),
        "attempt_count": record["attempt_count"],
        "automatic_attempts": record["automatic_attempts"],
        "max_automatic_attempts": MAX_AUTOMATIC_ATTEMPTS,
        "next_retry_at": record.get("next_retry_at"),
        "can_retry": bool(record.get("can_retry")),
        "error_code": record.get("error_code"),
        "message": {
            "waiting": "This file is waiting to be rendered.",
            "rendering": "This file is being prepared.",
            "retry_scheduled": "This file will be retried automatically.",
            "completed": "This file is ready.",
            "failed": "This file could not be created.",
            "cancelled": "This file was cancelled.",
        }[record["state"]],
        "artifact_message_id": committed["artifact"]["artifact_message_id"] if committed and not withhold_details else None,
        "row_count": descriptor.get("record_count"),
        "character_count": descriptor.get("character_count"),
        "size_bytes": descriptor.get("size_bytes"),
    }
    if not available:
        projected.update({
            "artifact_message_id": None, "can_retry": False, "next_retry_at": None,
            "row_count": None, "character_count": None, "size_bytes": None,
        })
    if unavailable_code is not None:
        projected.update({
            "error_code": unavailable_code, "message": OUTPUT_UNAVAILABLE_MESSAGES[unavailable_code],
        })
    return projected


def enumerate_due_outputs(container, *, now=None, limit=64):
    """Private scheduler selectors only; callers rebuild an actor-scoped service."""
    if type(limit) is not int or not 1 <= limit <= 200:
        raise OutputError("output_limit_invalid")
    now = utc_now() if now is None else now
    timestamp = now.astimezone(timezone.utc).isoformat()
    query = (
        f"SELECT TOP {limit} c.id, c.user_id, c.conversation_id, c.run_id "
        "FROM c WHERE c.record_type = @record_type AND ("
        '(c.state IN ("waiting", "retry_scheduled") AND '
        "(IS_NULL(c.next_retry_at) OR c.next_retry_at <= @now)) OR "
        '(c.state = "rendering" AND c.lease.expires_at <= @now) OR '
        '(c.state IN ("cancelled", "failed", "completed") AND '
        'c.cleanup_pending = true AND c.cleanup_after <= @now))'
    )
    try:
        rows = container.query_items(
            query=query, parameters=[
                {"name": "@record_type", "value": OUTPUT_RECORD_TYPE},
                {"name": "@now", "value": timestamp},
            ], enable_cross_partition_query=True, max_item_count=limit,
        )
        selectors = []
        for row in islice(rows, limit):
            if type(row) is not dict or _OUTPUT_ID.fullmatch(str(row.get("id", ""))) is None:
                raise OutputError("output_record_invalid")
            selectors.append({
                "output_id": row["id"], "user_id": safe_identity(row["user_id"]),
                "conversation_id": safe_identity(row["conversation_id"]),
                "run_id": safe_identity(row["run_id"]),
            })
        return selectors
    except _STORAGE_ERRORS as exc:
        raise OutputStorageError() from exc


def _cleanup_admission_index(run):
    if (
        type(run) is not dict or run.get("record_type") not in (None, "run", "orchestration_run")
        or type(run.get("plan")) is not dict
        or type(run["plan"].get("planner_contract_version")) is not int
        or run["plan"]["planner_contract_version"] != 2
    ):
        raise OutputUnavailableError("output_cleanup_intent_invalid")
    for key in ("id", "user_id", "conversation_id"):
        safe_identity(run.get(key))
    output_ids = run.get("render_output_ids", [])
    if (
        type(output_ids) is not list or len(output_ids) > MAX_OUTPUTS_PER_RUN
        or any(type(item) is not str or _OUTPUT_ID.fullmatch(item) is None for item in output_ids)
        or len(set(output_ids)) != len(output_ids)
    ):
        raise OutputUnavailableError("output_cleanup_intent_invalid")
    return list(output_ids)


def _cleanup_enrollment_intent(run):
    output_ids = _cleanup_admission_index(run)
    intent = run.get("output_cleanup")
    if (
        type(intent) is not dict
        or set(intent) != {"version", "state", "retain_committed", "output_ids"}
        or type(intent.get("version")) is not int or intent["version"] != OUTPUT_CLEANUP_VERSION
        or intent.get("state") not in ("pending", "completed")
        or type(intent.get("retain_committed")) is not bool
        or intent.get("output_ids") != output_ids
        or type(intent.get("output_ids")) is not list
    ):
        raise OutputUnavailableError("output_cleanup_intent_invalid")
    return deepcopy(intent)


def build_output_cleanup_intent(run, *, retain_committed=False):
    """Build private enrollment to persist in the owner's parent deletion CAS."""
    output_ids = _cleanup_admission_index(run)
    if type(retain_committed) is not bool:
        raise OutputError("output_cleanup_policy_invalid")
    if "output_cleanup" in run:
        intent = _cleanup_enrollment_intent(run)
        if intent["retain_committed"] != retain_committed:
            raise OutputUnavailableError("output_cleanup_policy_changed")
        return intent
    return {
        "version": OUTPUT_CLEANUP_VERSION, "state": "pending" if output_ids else "completed",
        "retain_committed": retain_committed, "output_ids": output_ids,
    }


def enumerate_output_cleanup_enrollments(container, *, limit=64):
    """Find deletion intents independently of individual output retry readiness."""
    if type(limit) is not int or not 1 <= limit <= 200:
        raise OutputError("output_limit_invalid")
    query = (
        f"SELECT TOP {limit} c.id, c.user_id, c.conversation_id FROM c WHERE "
        '(NOT IS_DEFINED(c.record_type) OR c.record_type IN ("run", "orchestration_run")) '
        "AND c.plan.planner_contract_version = 2 AND c.checkpoints_deleted = true "
        f"AND c.output_cleanup.version = {OUTPUT_CLEANUP_VERSION} "
        'AND c.output_cleanup.state = "pending"'
    )
    try:
        rows = container.query_items(
            query=query, enable_cross_partition_query=True, max_item_count=limit,
        )
        selectors = []
        for row in islice(rows, limit):
            if type(row) is not dict:
                raise OutputError("output_record_invalid")
            selectors.append({
                "run_id": safe_identity(row.get("id")),
                "user_id": safe_identity(row.get("user_id")),
                "conversation_id": safe_identity(row.get("conversation_id")),
            })
        return selectors
    except _STORAGE_ERRORS as exc:
        raise OutputStorageError() from exc


class OrchestrationOutputStore:
    def __init__(
        self, container, *, user_id, conversation_id, read_conversation,
        clock=utc_now, lease_seconds=120, read_run_tombstone=None,
    ):
        if not all(callable(getattr(container, name, None)) for name in (
            "read_item", "execute_item_batch", "query_items",
        )) or not callable(read_conversation) or not callable(clock):
            raise OutputError("output_store_required")
        if read_run_tombstone is not None and not callable(read_run_tombstone):
            raise OutputError("output_store_required")
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 900:
            raise OutputError("output_limit_invalid")
        self.container = container
        self.user_id = safe_identity(user_id)
        self.conversation_id = safe_identity(conversation_id)
        self.read_conversation = read_conversation
        self.read_run_tombstone = read_run_tombstone
        self.clock = clock
        self.lease_seconds = lease_seconds

    def _conversation(self):
        try:
            conversation = self.read_conversation(self.conversation_id)
        except exceptions.CosmosResourceNotFoundError as exc:
            raise OutputUnavailableError("output_conversation_unavailable") from exc
        except _STORAGE_ERRORS as exc:
            raise OutputStorageError() from exc
        if (
            type(conversation) is not dict or conversation.get("id") != self.conversation_id
            or conversation.get("user_id") != self.user_id
            or conversation.get("orchestration_deleted") or conversation.get("deleted")
        ):
            raise OutputUnavailableError("output_conversation_unavailable")
        return conversation

    def _point(self, item_id):
        try:
            record = self.container.read_item(item=item_id, partition_key=self.conversation_id)
        except exceptions.CosmosResourceNotFoundError:
            return None
        except _STORAGE_ERRORS as exc:
            raise OutputStorageError() from exc
        if not isinstance(record, dict):
            raise OutputError("output_record_invalid")
        return dict(record)

    def _validate(self, record):
        if (
            type(record) is not dict or type(record.get("identity")) is not dict
            or set(record["identity"]) != {
                "version", "request_owner", "approved_work_id", "file_name", "source_digest", "spec_digest",
            }
            or type(record.get("producer")) is not dict
            or type(record.get("render_spec")) is not dict
        ):
            raise OutputUnavailableError("output_record_invalid")
        if (
            record.get("record_type") != OUTPUT_RECORD_TYPE
            or record.get("version") != OUTPUT_CONTRACT_VERSION
            or record.get("user_id") != self.user_id
            or record.get("conversation_id") != self.conversation_id
            or record.get("state") not in OUTPUT_STATES
            or record.get("id") != f"orender_{canonical_digest(record.get('identity'))}"
            or canonical_digest(record.get("source_ref")) != record["identity"]["source_digest"]
            or canonical_digest(record.get("render_spec")) != record["identity"]["spec_digest"]
            or _request_owner(record["producer"]) != record["identity"]["request_owner"]
            or record.get("file_name") != record["identity"]["file_name"]
            or record.get("run_id") != record["producer"]["run_id"]
        ):
            raise OutputUnavailableError("output_record_invalid")
        if (
            type(record.get("attempts")) is not list
            or type(record.get("attempt_count")) is not int
            or record.get("attempt_count") != len(record["attempts"])
            or not 1 <= record["attempt_count"] <= MAX_AUTOMATIC_ATTEMPTS + MAX_MANUAL_ATTEMPTS
            or type(record.get("automatic_attempts")) is not int
            or not 1 <= record["automatic_attempts"] <= MAX_AUTOMATIC_ATTEMPTS
            or type(record.get("manual_requests")) is not dict
            or len(record["manual_requests"]) > MAX_MANUAL_ATTEMPTS
            or type(record.get("intents")) is not list or len(record["intents"]) > record["attempt_count"]
        ):
            raise OutputUnavailableError("output_record_invalid")
        automatic = 0
        for index, attempt in enumerate(record["attempts"], 1):
            if type(attempt) is not dict or attempt.get("number") != index:
                raise OutputUnavailableError("output_record_invalid")
            if attempt.get("kind") == "automatic":
                automatic += 1
                if attempt.get("automatic_index") != automatic or attempt.get("request_id") is not None:
                    raise OutputUnavailableError("output_record_invalid")
            elif (
                attempt.get("kind") != "manual"
                or record["manual_requests"].get(attempt.get("request_id")) != index
                or attempt.get("automatic_index") is not None
            ):
                raise OutputUnavailableError("output_record_invalid")
        if automatic != record["automatic_attempts"]:
            raise OutputUnavailableError("output_record_invalid")
        guards = record.get("staging_guards", {})
        if (
            type(guards) is not dict or len(guards) > MAX_STAGING_GUARDS
            or type(record.get("lease_generation")) is not int or record["lease_generation"] < 0
            or type(record.get("cleanup_generation", 0)) is not int
            or record.get("cleanup_generation", 0) < 0
        ):
            raise OutputUnavailableError("output_record_invalid")
        for key, guard in guards.items():
            if (
                type(guard) is not dict
                or set(guard) != {"intent_id", "attempt_number", "generation", "token_digest"}
                or canonical_digest(guard) != key
                or type(guard["intent_id"]) is not str
                or re.fullmatch(r"[a-f0-9]{64}", guard["intent_id"]) is None
                or type(guard["attempt_number"]) is not int
                or not 1 <= guard["attempt_number"] <= record["attempt_count"]
                or type(guard["generation"]) is not int
                or not 1 <= guard["generation"] <= record["lease_generation"]
                or type(guard["token_digest"]) is not str
                or re.fullmatch(r"[a-f0-9]{64}", guard["token_digest"]) is None
                or not any(intent.get("intent_id") == guard["intent_id"] for intent in record["intents"])
            ):
                raise OutputUnavailableError("output_record_invalid")
        if record["state"] == "completed" and (
            not record.get("committed_intent") or record["committed_intent"] != record.get("intent")
            or record["committed_intent"] not in record["intents"] or not record.get("committed_at")
            or type(record.get("committed_attempt_number")) is not int
            or not 1 <= record["committed_attempt_number"] <= record["attempt_count"]
            or record["attempts"][record["committed_attempt_number"] - 1]["state"] != "completed"
        ):
            raise OutputUnavailableError("output_record_invalid")
        if record.get("deleted_at") is not None:
            try:
                parse_time(record["deleted_at"])
            except OutputError as exc:
                raise OutputUnavailableError("output_record_invalid") from exc
            if record["state"] != "cancelled":
                raise OutputUnavailableError("output_record_invalid")
        if record.get("committed_intent") is not None and record["state"] != "completed" and (
            record["state"] != "cancelled" or not record.get("deleted_at")
        ):
            raise OutputUnavailableError("output_record_invalid")
        return record

    def get(self, output_id):
        if type(output_id) is not str or _OUTPUT_ID.fullmatch(output_id) is None:
            raise OutputUnavailableError("output_not_found")
        self._conversation()
        record = self._point(output_id)
        if record is None:
            raise OutputUnavailableError("output_not_found")
        return self._validate(record)

    def current_run(self, record, *, live=False, stopping=False):
        self._conversation()
        run = self._point(record["run_id"])
        producer = record["producer"]
        if (
            type(run) is not dict or run.get("id") != producer["run_id"]
            or run.get("user_id") != self.user_id
            or run.get("conversation_id") != self.conversation_id
            or run.get("record_type") not in (None, "run", "orchestration_run")
        ):
            raise OutputUnavailableError("output_run_unavailable")
        if stopping:
            return run
        if (
            run.get("checkpoints_deleted") or run.get("outputs_deleted")
            or run.get("superseded_by_run_id")
            or run.get("latest_attempt_run_id") not in (None, "", run["id"])
            or run.get("attempt_index", 1) != producer["attempt_index"]
            or run.get("status") in {"deleted", "superseded"}
        ):
            raise OutputUnavailableError("output_superseded")
        steps = (run.get("plan") or {}).get("steps")
        matches = [
            step for step in steps or []
            if type(step) is dict and step.get("step_id") == producer["step_id"]
        ]
        if (
            len(matches) != 1 or matches[0].get("capability_id") != "render_file"
            or matches[0].get("enabled", True) is not True
            or (record.get("step_signature") and _step_signature(matches[0]) != record["step_signature"])
        ):
            raise OutputUnavailableError("output_plan_changed")
        if live:
            if run.get("status") in _STOPPED or run.get("cancellation_requested_at"):
                raise OutputUnavailableError("output_cancelled")
            if run.get("status") not in {"running", "waiting", "completed", "failed", "partial"}:
                raise OutputUnavailableError("output_not_approved")
            if parse_time(record["deadline_at"]) <= self.clock():
                raise OutputUnavailableError("output_deadline_exceeded")
            persisted_deadline = run.get("execution_deadline_at")
            if persisted_deadline and parse_time(persisted_deadline) < parse_time(record["deadline_at"]):
                raise OutputUnavailableError("output_deadline_invalid")
        return run

    def _batch(self, run, record, *, previous=None, run_replacement=None):
        record = _body(record)
        record["write_id"] = uuid.uuid4().hex
        if len(canonical_bytes(record)) > MAX_OUTPUT_DOCUMENT_BYTES:
            raise OutputError("output_limit_exceeded")
        operations = [
            ("replace", (run["id"], _body(run_replacement or run)), {"if_match_etag": run["_etag"]}),
            (
                ("create", (record,)) if previous is None else
                ("replace", (record["id"], record), {"if_match_etag": previous["_etag"]})
            ),
        ]
        try:
            responses = self.container.execute_item_batch(
                batch_operations=operations, partition_key=self.conversation_id,
            )
        except (exceptions.CosmosBatchOperationError, exceptions.CosmosHttpResponseError) as exc:
            if exc.status_code in (409, 412):
                raise OutputConflictError() from exc
            saved = self._point(record["id"])
            if saved is not None and saved.get("write_id") == record["write_id"]:
                return self._validate(saved)
            if exc.status_code == 404:
                raise OutputUnavailableError("output_run_unavailable") from exc
            raise OutputStorageError() from exc
        except _STORAGE_ERRORS as exc:
            saved = self._point(record["id"])
            if saved is not None and saved.get("write_id") == record["write_id"]:
                return self._validate(saved)
            raise OutputStorageError() from exc
        saved = responses[-1].get("resourceBody")
        if saved is None:
            saved = self._point(record["id"])
        if saved is None or saved.get("write_id") != record["write_id"]:
            raise OutputConflictError()
        return self._validate(saved)

    def _attempt(self, number, automatic_index, *, request_id=None):
        return {
            "number": number, "kind": "manual" if request_id else "automatic",
            "automatic_index": automatic_index, "request_id": request_id,
            "admitted_at": self.clock().isoformat(), "started_at": None,
            "finished_at": None, "state": "admitted", "error_code": None,
        }

    def ensure(
        self, *, producer, source_ref, render_spec, file_name, approved_work_id,
        deadline_at, check,
    ):
        if type(producer) is not ProducerIdentity or type(source_ref) is not ResultRef:
            raise OutputError("output_binding_invalid")
        if (
            producer.user_id != self.user_id or producer.conversation_id != self.conversation_id
            or producer.capability_id != "render_file"
            or source_ref.producer.user_id != self.user_id
            or source_ref.producer.conversation_id != self.conversation_id
            or not callable(check)
        ):
            raise OutputUnavailableError("output_binding_invalid")
        for value in (producer.run_id, producer.step_id, approved_work_id):
            safe_identity(value)
        source_ref.completeness.require_readable()
        deadline_at = parse_time(deadline_at).isoformat()
        identity = {
            "version": OUTPUT_CONTRACT_VERSION, "request_owner": _request_owner(producer.to_dict()),
            "approved_work_id": approved_work_id, "file_name": file_name,
            "source_digest": canonical_digest(source_ref.to_dict()),
            "spec_digest": canonical_digest(render_spec),
        }
        output_id = f"orender_{canonical_digest(identity)}"
        now = self.clock().isoformat()
        record = {
            "id": output_id, "record_type": OUTPUT_RECORD_TYPE, "version": OUTPUT_CONTRACT_VERSION,
            "identity": identity, "user_id": self.user_id, "conversation_id": self.conversation_id,
            "run_id": producer.run_id, "producer": producer.to_dict(), "source_ref": source_ref.to_dict(),
            "render_spec": deepcopy(render_spec), "file_name": file_name, "deadline_at": deadline_at,
            "state": "waiting", "attempt_count": 1, "automatic_attempts": 1,
            "attempts": [self._attempt(1, 1)], "manual_requests": {},
            "lease": None, "lease_generation": 0, "next_retry_at": None, "can_retry": False,
            "error_code": None, "retryable": False, "intent": None, "intents": [],
            "committed_intent": None, "committed_at": None, "committed_attempt_number": None,
            "cleanup_pending": False,
            "created_at": now, "updated_at": now, "deleted_at": None,
        }
        for _ in range(8):
            self._conversation()
            existing = self._point(output_id)
            if existing is not None:
                existing = self._validate(existing)
                if existing["deadline_at"] != deadline_at:
                    raise OutputError("output_deadline_invalid")
                if existing["producer"] != producer.to_dict():
                    raise OutputUnavailableError("output_producer_changed")
                if existing.get("deleted_at"):
                    raise OutputUnavailableError("output_deleted")
                check(existing, "read")
                self.current_run(existing)
                return existing
            run = self.current_run(record, live=True)
            step = next(step for step in run["plan"]["steps"] if step["step_id"] == producer.step_id)
            record["step_signature"] = _step_signature(step)
            check(record, "admit")
            replacement = _body(run)
            output_ids = list(replacement.get("render_output_ids") or [])
            if output_id in output_ids:
                # An output removed behind its retained admission is never recreated.
                raise OutputUnavailableError("output_deleted")
            if len(output_ids) >= MAX_OUTPUTS_PER_RUN:
                raise OutputError("output_limit_exceeded")
            replacement["render_output_ids"] = [*output_ids, output_id]
            if not replacement.get("execution_deadline_at"):
                replacement["execution_deadline_at"] = deadline_at
            try:
                return self._batch(run, record, run_replacement=replacement)
            except OutputConflictError:
                continue
        raise OutputConflictError()

    def _owns(self, record, claim):
        lease = record.get("lease") or {}
        if (
            type(claim) is not OutputClaim or record["id"] != claim.output_id
            or record["state"] != "rendering" or lease.get("token") != claim.token
            or lease.get("generation") != claim.generation
            or record["attempt_count"] != claim.attempt_number
            or not _lease_live(record, self.clock())
        ):
            raise OutputConflictError()

    def owned(self, claim):
        record = self.get(claim.output_id)
        self._owns(record, claim)
        self._owns_run(record, self.current_run(record, live=True))
        return record

    def _run_claim_identity(self, run):
        execution_lease = run.get("execution_lease")
        if execution_lease is None:
            execution_lease = {}
        if type(execution_lease) is not dict:
            raise OutputConflictError()
        token = execution_lease.get("token")
        claim_id = execution_lease.get("claim_id")
        if token is None:
            if execution_lease:
                raise OutputConflictError()
            submission = run.get("continuation_submission")
            if submission is not None and type(submission) is not dict:
                raise OutputConflictError()
            # Retain the last claim fence through a parent's acquire/release interval.
            claim_id = (submission or {}).get("claim_id")
        if any(
            value is not None and (type(value) is not str or not value or value != value.strip())
            for value in (token, claim_id)
        ):
            raise OutputConflictError()
        if token is not None:
            try:
                expires_at = parse_time(execution_lease.get("expires_at"))
            except OutputError as exc:
                raise OutputConflictError() from exc
            if expires_at <= self.clock():
                raise OutputConflictError()
        return token, claim_id

    def _owns_run(self, record, run):
        lease = record.get("lease") or {}
        if (lease.get("run_token"), lease.get("run_claim_id")) != self._run_claim_identity(run):
            raise OutputConflictError()

    def _mutate(self, output_id, change, *, claim=None, live=True, stopping=False, check=None):
        for _ in range(8):
            record = self.get(output_id)
            if claim is not None:
                self._owns(record, claim)
            run = self.current_run(record, live=live, stopping=stopping)
            if claim is not None:
                self._owns_run(record, run)
            replacement = change(deepcopy(record))
            if replacement is None:
                return record
            if check is not None:
                check(record)
            replacement["updated_at"] = self.clock().isoformat()
            try:
                return self._batch(run, replacement, previous=record)
            except OutputConflictError:
                continue
        raise OutputConflictError()

    def claim_due(self, output_id, *, worker_id, reconcile_only=False, check=None):
        safe_identity(worker_id)
        claimed = {}

        def change(record):
            now = self.clock()
            if record["state"] in {"completed", "cancelled"} or _lease_live(record, now):
                return None
            state = record["state"]
            if reconcile_only:
                if not record.get("intent"):
                    return None
            elif state == "failed" or (
                record.get("next_retry_at") and parse_time(record["next_retry_at"]) > now
            ):
                return None
            generation = record["lease_generation"] + 1
            token = uuid.uuid4().hex
            run_token, run_claim_id = self._run_claim_identity(self.current_run(record, live=True))
            claimed["claim"] = OutputClaim(
                output_id, token, record["attempt_count"], generation, state,
                recovering=state == "rendering",
            )
            record["lease_generation"] = generation
            record["lease"] = {
                "token": token, "owner_id": worker_id, "generation": generation,
                "run_token": run_token, "run_claim_id": run_claim_id,
                "expires_at": min(
                    now + timedelta(seconds=self.lease_seconds), parse_time(record["deadline_at"]),
                ).isoformat(),
            }
            record["state"] = "rendering"
            if not reconcile_only:
                attempt = record["attempts"][-1]
                attempt["started_at"] = attempt["started_at"] or now.isoformat()
                attempt["state"] = "rendering"
            return record

        saved = self._mutate(output_id, change, check=check)
        claim = claimed.get("claim")
        if claim is None or (saved.get("lease") or {}).get("token") != claim.token:
            return None
        return claim

    def renew(self, claim):
        def change(record):
            record["lease"]["expires_at"] = min(
                self.clock() + timedelta(seconds=self.lease_seconds), parse_time(record["deadline_at"]),
            ).isoformat()
            return record

        return self._mutate(claim.output_id, change, claim=claim)

    def prepare_intent(self, claim, descriptor, *, check):
        def change(record):
            if descriptor["attempt_number"] != claim.attempt_number:
                raise OutputError("output_intent_invalid")
            existing = record.get("intent")
            if existing == descriptor:
                return None
            if existing and existing["attempt_number"] == claim.attempt_number:
                raise OutputError("output_intent_changed")
            record["intent"] = deepcopy(descriptor)
            record["intents"].append(deepcopy(descriptor))
            return record

        return self._mutate(claim.output_id, change, claim=claim, check=check)

    @staticmethod
    def _staging_guard(claim, intent_id):
        if type(claim) is not OutputClaim:
            raise OutputConflictError()
        return {
            "intent_id": intent_id, "attempt_number": claim.attempt_number,
            "generation": claim.generation, "token_digest": canonical_digest(claim.token),
        }

    def register_staging(self, claim, intent_id):
        guard = self._staging_guard(claim, intent_id)
        key = canonical_digest(guard)

        def change(record):
            if not record.get("intent") or record["intent"]["intent_id"] != intent_id:
                raise OutputUnavailableError("output_intent_invalid")
            guards = record.setdefault("staging_guards", {})
            if type(guards) is not dict:
                raise OutputUnavailableError("output_record_invalid")
            if key in guards:
                if guards[key] != guard:
                    raise OutputUnavailableError("output_record_invalid")
                return None
            if len(guards) >= MAX_STAGING_GUARDS:
                raise OutputError("output_limit_exceeded")
            guards[key] = guard
            return record

        return self._mutate(claim.output_id, change, claim=claim)

    def rearm_staging_cleanup(self, claim, intent_id):
        """An admitted writer can report settled I/O, never read or delete bytes."""
        guard = self._staging_guard(claim, intent_id)
        key = canonical_digest(guard)
        for _ in range(8):
            record = self._point(claim.output_id)
            if record is None:
                raise OutputUnavailableError("output_not_found")
            record = self._validate(record)
            run = self._cleanup_parent(record)
            if (
                (record.get("staging_guards") or {}).get(key) != guard
                or not any(intent.get("intent_id") == intent_id for intent in record["intents"])
            ):
                raise OutputConflictError()
            if not self._cleanup_eligible(record) or (
                record["state"] == "completed"
                and record["committed_intent"]["intent_id"] == intent_id
            ):
                return False
            replacement = deepcopy(record)
            now = self.clock().isoformat()
            replacement.update(
                cleanup_pending=True, updated_at=now,
                cleanup_after=max(now, record.get("cleanup_after") or now),
                cleanup_generation=record.get("cleanup_generation", 0) + 1,
            )
            try:
                self._batch(run, replacement, previous=record)
                return True
            except OutputConflictError:
                continue
        raise OutputConflictError()

    def commit(self, claim, *, intent_id, check):
        def change(record):
            intent = record.get("intent")
            if not intent or intent["intent_id"] != intent_id or record.get("deleted_at"):
                raise OutputError("output_intent_invalid")
            now = self.clock().isoformat()
            record.update({
                "state": "completed", "committed_intent": deepcopy(intent), "committed_at": now,
                "committed_attempt_number": claim.attempt_number,
                "lease": None, "next_retry_at": None, "can_retry": False,
                "error_code": None, "retryable": False,
                "cleanup_pending": len(record["intents"]) > 1,
                "cleanup_after": (self.clock() + timedelta(seconds=self.lease_seconds)).isoformat(),
            })
            attempt = record["attempts"][claim.attempt_number - 1]
            attempt.update(state="completed", finished_at=now, error_code=None)
            if intent["attempt_number"] != claim.attempt_number:
                attempt["reused_render_attempt"] = intent["attempt_number"]
            return record

        return self._mutate(claim.output_id, change, claim=claim, check=check)

    def release_reconciliation(self, claim):
        def change(record):
            record["state"] = claim.previous_state
            record["lease"] = None
            return record

        return self._mutate(claim.output_id, change, claim=claim)

    def fail(self, output_id, *, code, retryable, retry_delay=0, claim=None):
        if type(code) is not str or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
            raise OutputError("output_error_invalid")
        if (
            type(retryable) is not bool or type(retry_delay) not in (int, float)
            or not math.isfinite(retry_delay) or not 0 <= retry_delay <= 300
        ):
            raise OutputError("output_retry_invalid")

        def change(record):
            if record["state"] in {"completed", "cancelled"}:
                return None
            if claim is None and _lease_live(record, self.clock()):
                raise OutputConflictError()
            attempt = record["attempts"][-1]
            lease_expiration = (record.get("lease") or {}).get("expires_at", self.clock().isoformat())
            if attempt["state"] != "failed":
                attempt.update(state="failed", finished_at=self.clock().isoformat(), error_code=code)
            record.update({
                "state": "failed", "lease": None, "error_code": code,
                "retryable": retryable, "can_retry": False, "next_retry_at": None,
            })
            now = self.clock()
            next_time = now + timedelta(seconds=retry_delay)
            deadline = parse_time(record["deadline_at"])
            if now >= deadline or (retryable and next_time >= deadline):
                record.update(error_code="output_deadline_exceeded", retryable=False)
            elif retryable and attempt["kind"] == "automatic" and record["automatic_attempts"] < MAX_AUTOMATIC_ATTEMPTS:
                record["attempt_count"] += 1
                record["automatic_attempts"] += 1
                record["attempts"].append(self._attempt(
                    record["attempt_count"], record["automatic_attempts"],
                ))
                record.update(state="retry_scheduled", next_retry_at=next_time.isoformat())
            elif retryable:
                record["can_retry"] = len(record["manual_requests"]) < MAX_MANUAL_ATTEMPTS
            if record["state"] == "failed" and not record["retryable"] and record["intents"]:
                record.update(
                    cleanup_pending=True,
                    cleanup_after=max(self.clock().isoformat(), lease_expiration),
                )
            return record

        return self._mutate(output_id, change, claim=claim, live=False)

    def manual_retry(self, output_id, request_id, *, check):
        safe_identity(request_id)
        key = canonical_digest({"output_id": output_id, "request_id": request_id})

        def change(record):
            if key in record["manual_requests"] or record["state"] == "completed":
                return None
            if (
                record["state"] != "failed" or not record["can_retry"] or not record["retryable"]
                or record["automatic_attempts"] != MAX_AUTOMATIC_ATTEMPTS
                or len(record["manual_requests"]) >= MAX_MANUAL_ATTEMPTS
            ):
                raise OutputError("output_retry_not_available")
            record["attempt_count"] += 1
            record["manual_requests"][key] = record["attempt_count"]
            record["attempts"].append(self._attempt(record["attempt_count"], None, request_id=key))
            record.update(state="waiting", can_retry=False, error_code=None, next_retry_at=None)
            return record

        return self._mutate(output_id, change, check=check)

    def _cancel_record(self, record, *, deleted, code):
        if record["state"] == "completed" and not deleted:
            return None
        if record["state"] == "cancelled" and (not deleted or record.get("deleted_at")):
            return None
        now = self.clock().isoformat()
        lease = record.get("lease") or {}
        record.update({
            "state": "cancelled", "can_retry": False, "retryable": False,
            "error_code": code, "next_retry_at": None, "lease": None,
            "cleanup_pending": bool(record["intents"]),
            "cleanup_after": max(now, lease.get("expires_at", now), record.get("cleanup_after") or now),
        })
        if deleted:
            record["deleted_at"] = now
        if record["attempts"][-1]["state"] != "completed":
            record["attempts"][-1].update(state="cancelled", finished_at=now, error_code=code)
        return record

    def cancel(self, output_id, *, deleted=False, claim=None, code="output_cancelled"):
        change = lambda record: self._cancel_record(record, deleted=deleted, code=code)
        return self._mutate(output_id, change, claim=claim, live=False, stopping=True)

    def _cleanup_parent(self, record):
        run = self._point(record["run_id"])
        if (
            type(run) is not dict or run.get("id") != record["producer"]["run_id"]
            or run.get("user_id") != self.user_id or run.get("conversation_id") != self.conversation_id
            or record["producer"].get("user_id") != self.user_id
            or record["producer"].get("conversation_id") != self.conversation_id
            or run.get("record_type") not in (None, "run", "orchestration_run")
            or type(run.get("render_output_ids")) is not list
            or len(run["render_output_ids"]) > MAX_OUTPUTS_PER_RUN
            or record["id"] not in run["render_output_ids"]
        ):
            raise OutputUnavailableError("output_cleanup_denied")
        return run

    def _run_cleanup_tombstone(self, run):
        """Verify the existing irreversible checkpoint lifecycle deletion guard."""
        if self.read_run_tombstone is None or run.get("checkpoints_deleted") is not True:
            raise OutputUnavailableError("output_cleanup_tombstone_required")
        try:
            guard = self.read_run_tombstone(run["id"])
        except exceptions.CosmosResourceNotFoundError as exc:
            raise OutputUnavailableError("output_cleanup_tombstone_required") from exc
        except _STORAGE_ERRORS as exc:
            raise OutputStorageError() from exc
        turn_id = run.get("turn_id") or (run.get("plan") or {}).get("turn_id")
        if (
            type(guard) is not dict or guard.get("id") != "checkpoint:lifecycle"
            or guard.get("record_type") != "checkpoint_lifecycle"
            or type(guard.get("_etag")) is not str or not guard["_etag"]
            or type(guard.get("schema_version")) is not int or guard["schema_version"] != 1
            or type(run.get("checkpoint_version")) is not int or run["checkpoint_version"] != 1
            or type(turn_id) is not str or not turn_id or guard.get("turn_id") != turn_id
            or guard.get("run_id") != run["id"] or guard.get("user_id") != self.user_id
            or guard.get("conversation_id") != self.conversation_id
            or guard.get("deleted") is not True or "token" not in guard or guard["token"] is not None
        ):
            raise OutputUnavailableError("output_cleanup_tombstone_invalid")
        return canonical_digest(_body(guard))

    def _cleanup_authority(self, run, proof=None):
        conversation_missing = False
        try:
            conversation = self.read_conversation(self.conversation_id)
        except exceptions.CosmosResourceNotFoundError:
            conversation, conversation_missing = None, True
        except _STORAGE_ERRORS as exc:
            raise OutputStorageError() from exc
        if not conversation_missing and (
            type(conversation) is not dict or conversation.get("id") != self.conversation_id
            or conversation.get("user_id") != self.user_id
            or type(conversation.get("_etag")) is not str or not conversation["_etag"]
            or any(
                conversation.get(name) is not None and type(conversation[name]) is not bool
                for name in ("deleted", "orchestration_deleted")
            )
        ):
            raise OutputUnavailableError("output_cleanup_denied")
        if conversation_missing or proof is not None:
            current_proof = self._run_cleanup_tombstone(run)
            if proof is not None and proof != current_proof:
                raise OutputUnavailableError("output_cleanup_tombstone_changed")
            proof = current_proof
        deleted = bool(
            conversation_missing or conversation.get("deleted") is True
            or conversation.get("orchestration_deleted") is True
            or run.get("outputs_deleted") is True or run.get("checkpoints_deleted") is True
            or run.get("status") == "deleted"
        )
        return deleted, proof

    def _cleanup_scope(self, output_id):
        if type(output_id) is not str or _OUTPUT_ID.fullmatch(output_id) is None:
            raise OutputUnavailableError("output_not_found")
        record = self._point(output_id)
        if record is None:
            raise OutputUnavailableError("output_not_found")
        record = self._validate(record)
        run = self._cleanup_parent(record)
        deleted, proof = self._cleanup_authority(run, record.get("cleanup_run_tombstone"))
        return record, run, deleted, proof

    def _cleanup_enrollment_scope(self, run_id, *, proof=None):
        run = self._point(safe_identity(run_id))
        if (
            type(run) is not dict or run.get("id") != run_id
            or run.get("user_id") != self.user_id or run.get("conversation_id") != self.conversation_id
            or type(run.get("_etag")) is not str or not run["_etag"]
            or run.get("checkpoints_deleted") is not True
        ):
            raise OutputUnavailableError("output_cleanup_denied")
        intent = _cleanup_enrollment_intent(run)
        deleted, proof = self._cleanup_authority(run, proof)
        if not deleted:
            raise OutputUnavailableError("output_cleanup_denied")
        return run, intent, proof

    def enroll_run_cleanup(self, run_id):
        """Fence a frozen admission index before retiring its durable enrollment."""
        _, original, proof = self._cleanup_enrollment_scope(run_id)
        expected = {**original, "state": "completed"}
        result = {
            "run_id": run_id, "enrollment_status": "completed",
            "output_count": len(original["output_ids"]),
            "retain_committed": original["retain_committed"],
        }
        for output_id in original["output_ids"]:
            _, current, proof = self._cleanup_enrollment_scope(run_id, proof=proof)
            if {**current, "state": "completed"} != expected:
                raise OutputUnavailableError("output_cleanup_intent_changed")
            self.prepare_cleanup(
                output_id, tombstone=not original["retain_committed"], expected_run_id=run_id,
                expected_cleanup_intent=expected, expected_run_tombstone=proof,
            )
        for _ in range(8):
            run, current, proof = self._cleanup_enrollment_scope(run_id, proof=proof)
            if {**current, "state": "completed"} != expected:
                raise OutputUnavailableError("output_cleanup_intent_changed")
            if current["state"] == "completed":
                return result
            replacement = _body(run)
            replacement["output_cleanup"] = expected
            try:
                self.container.execute_item_batch(
                    batch_operations=[
                        ("replace", (run_id, replacement), {"if_match_etag": run["_etag"]}),
                    ],
                    partition_key=self.conversation_id,
                )
            except (exceptions.CosmosBatchOperationError, exceptions.CosmosHttpResponseError) as exc:
                if exc.status_code in (409, 412):
                    continue
                _, saved, proof = self._cleanup_enrollment_scope(run_id, proof=proof)
                if saved != expected:
                    raise OutputStorageError() from exc
            except _STORAGE_ERRORS as exc:
                _, saved, proof = self._cleanup_enrollment_scope(run_id, proof=proof)
                if saved != expected:
                    raise OutputStorageError() from exc
            _, saved, proof = self._cleanup_enrollment_scope(run_id, proof=proof)
            if saved == expected:
                return result
        raise OutputConflictError()

    @staticmethod
    def _cleanup_eligible(record):
        return record["state"] in {"cancelled", "completed"} or (
            record["state"] == "failed" and not record["retryable"]
        )

    def prepare_cleanup(
        self, output_id, *, tombstone=False, expected_run_id=None, expected_cleanup_intent=None,
        expected_run_tombstone=None,
    ):
        """A missing conversation requires its retained run's deletion guard."""
        if expected_run_id is not None:
            safe_identity(expected_run_id)
        for _ in range(8):
            record, run, owner_deleted, proof = self._cleanup_scope(output_id)
            if expected_run_id is not None and run["id"] != expected_run_id:
                raise OutputUnavailableError("output_cleanup_denied")
            if expected_run_tombstone is not None and proof != expected_run_tombstone:
                raise OutputUnavailableError("output_cleanup_tombstone_changed")
            if expected_cleanup_intent is not None and {
                **_cleanup_enrollment_intent(run), "state": "completed",
            } != expected_cleanup_intent:
                raise OutputUnavailableError("output_cleanup_intent_changed")
            if tombstone and not owner_deleted:
                raise OutputUnavailableError("output_cleanup_denied")
            replacement = None
            if owner_deleted and not record.get("deleted_at") and (
                tombstone or record["state"] != "completed"
            ):
                replacement = self._cancel_record(
                    deepcopy(record), deleted=True, code="output_deleted",
                )
            if proof is not None and record.get("cleanup_run_tombstone") is None:
                replacement = replacement if replacement is not None else deepcopy(record)
                replacement["cleanup_run_tombstone"] = proof
            if replacement is not None:
                replacement["updated_at"] = self.clock().isoformat()
                try:
                    return self._batch(run, replacement, previous=record)
                except OutputConflictError:
                    continue
            if not self._cleanup_eligible(record):
                raise OutputUnavailableError("output_cleanup_denied")
            return record
        raise OutputConflictError()

    def check_cleanup(self, output_id, intent_id):
        record, _, owner_deleted, proof = self._cleanup_scope(output_id)
        if (
            not self._cleanup_eligible(record) or not record.get("cleanup_pending")
            or (owner_deleted and record["state"] != "completed" and not record.get("deleted_at"))
            or proof != record.get("cleanup_run_tombstone")
            or parse_time(record["cleanup_after"]) > self.clock()
        ):
            raise OutputConflictError()
        intents = [intent for intent in record["intents"] if intent.get("intent_id") == intent_id]
        if (
            len(intents) != 1
            or (intents[0] == record.get("committed_intent") and not record.get("deleted_at"))
        ):
            raise OutputUnavailableError("output_cleanup_denied")
        return record, intents[0]

    def finish_cleanup(self, output_id, *, generation):
        if type(generation) is not int or generation < 0:
            raise OutputError("output_cleanup_generation_invalid")
        for _ in range(8):
            record, run, owner_deleted, proof = self._cleanup_scope(output_id)
            if (
                not self._cleanup_eligible(record)
                or (owner_deleted and record["state"] != "completed" and not record.get("deleted_at"))
                or proof != record.get("cleanup_run_tombstone")
            ):
                raise OutputConflictError()
            if (
                not record.get("cleanup_pending") or parse_time(record["cleanup_after"]) > self.clock()
                or record.get("cleanup_generation", 0) != generation
            ):
                return record
            replacement = deepcopy(record)
            replacement.update(cleanup_pending=False, updated_at=self.clock().isoformat())
            try:
                return self._batch(run, replacement, previous=record)
            except OutputConflictError:
                continue
        raise OutputConflictError()

    def cleanup_finished(self, output_id, *, generation=None):
        def change(record):
            if record["state"] not in {"cancelled", "failed", "completed"} or (
                record["state"] == "failed" and record["retryable"]
            ):
                raise OutputConflictError()
            if parse_time(record["cleanup_after"]) > self.clock():
                return None
            if generation is not None and record.get("cleanup_generation", 0) != generation:
                return None
            record["cleanup_pending"] = False
            return record

        return self._mutate(output_id, change, live=False, stopping=True)

    def list_outputs(self, run_id, *, limit=MAX_OUTPUTS_PER_RUN):
        safe_identity(run_id)
        if type(limit) is not int or not 1 <= limit <= MAX_OUTPUTS_PER_RUN:
            raise OutputError("output_limit_invalid")
        self._conversation()
        run = self._point(run_id)
        if not run or run.get("user_id") != self.user_id or run.get("conversation_id") != self.conversation_id:
            raise OutputUnavailableError("output_run_unavailable")
        ids = run.get("render_output_ids") or []
        if type(ids) is not list or len(ids) > MAX_OUTPUTS_PER_RUN:
            raise OutputError("output_record_invalid")
        return [self.get(output_id) for output_id in ids[:limit]]
