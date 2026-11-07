# functions_orchestration_planning.py
"""Durable initial planning attempts anchored to their saved user question.

The route owns authorization and supplies the messages container. This module
stays below application bootstrap and never persists settings or runtime objects.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError, CosmosResourceExistsError, CosmosResourceNotFoundError,
)

from cosmos_document_utils import normalize_cosmos_document
from functions_message_deletion import is_soft_deleted_message


PLANNING_METADATA = "_orchestration_planning"
PLANNING_LEASE_SECONDS = 90
PLANNING_HEARTBEAT_SECONDS = 20
PLANNING_STATES = frozenset({
    "planning", "awaiting_clarification", "awaiting_review", "running",
    "completed", "failed", "interrupted", "cancelled",
})
INTERRUPTED_MESSAGE = "Planning was interrupted before completion. Your question was saved. Retry to create a new plan."
_REQUEST_LIMIT = 1024 * 1024
_TRANSIENT_INPUTS = frozenset({
    "approval_mode", "requires_fresh_review", "revision", "planning_submission_id",
})


class PlanningStateError(ValueError):
    """A public-safe refusal to alter or recover an initial planning attempt."""

    def __init__(self, message, *, code="planning_changed", status_code=409):
        super().__init__(message)
        self.public_message = message
        self.code = code
        self.status_code = status_code


def _now():
    return datetime.now(timezone.utc)


def _json(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PlanningStateError("The planning inputs are invalid.", code="invalid_request", status_code=400) from exc
    if len(encoded.encode("utf-8")) > _REQUEST_LIMIT:
        raise PlanningStateError("The planning selections are too large.", code="invalid_request", status_code=400)
    return encoded


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _input_fingerprint(request_body):
    return _hash(_json({key: value for key, value in request_body.items() if key not in _TRANSIENT_INPUTS}))


def planning_question_id(conversation_id, turn_id):
    return f"user_orchestration_{uuid.uuid5(uuid.NAMESPACE_URL, f'{conversation_id}:{turn_id}').hex}"


def new_planning_attempt(request_body, turn_id, submission_id, *, revision=0):
    """Prepare metadata that can be created atomically with a new question."""
    if (
        type(request_body) is not dict or not isinstance(request_body.get("message"), str)
        or not isinstance(request_body.get("conversation_id"), str) or not request_body["conversation_id"]
    ):
        raise PlanningStateError("The planning inputs are invalid.", code="invalid_request", status_code=400)
    if not isinstance(submission_id, str) or not submission_id or len(submission_id) > 256:
        raise PlanningStateError("The planning submission id is invalid.", code="invalid_request", status_code=400)
    if not isinstance(turn_id, str) or not turn_id or len(turn_id) > 256:
        raise PlanningStateError("The planning turn id is invalid.", code="invalid_request", status_code=400)
    stored_request = deepcopy(request_body)
    message = stored_request.pop("message")
    _json(stored_request)
    now = _now()
    return {
        "version": 1,
        "conversation_id": request_body["conversation_id"],
        "turn_id": turn_id,
        "submission_id": submission_id,
        "claim_id": uuid.uuid4().hex,
        "revision": revision,
        "question_hash": _hash(message),
        "input_fingerprint": _input_fingerprint(request_body),
        "request": stored_request,
        "status": "planning",
        "updated_at": now.isoformat(),
        "lease_until": (now + timedelta(seconds=PLANNING_LEASE_SECONDS)).isoformat(),
    }


def _read_question(messages, conversation_id, message_id, turn_id):
    try:
        question = normalize_cosmos_document(messages.read_item(item=message_id, partition_key=conversation_id))
    except CosmosResourceNotFoundError:
        raise PlanningStateError("The saved question is unavailable.", code="planning_unavailable", status_code=404) from None
    metadata = question.get("metadata")
    if metadata is None:
        metadata = {}
    if type(metadata) is not dict:
        raise PlanningStateError("Saved planning metadata is unavailable.", code="planning_unavailable", status_code=503)
    if (
        question.get("conversation_id") != conversation_id or question.get("role") != "user"
        or metadata.get("orchestration_turn_id") != turn_id
        or is_soft_deleted_message(question) or metadata.get("masked") or metadata.get("masked_ranges")
    ):
        raise PlanningStateError("The saved question is unavailable.", code="planning_unavailable", status_code=404)
    state = metadata.get(PLANNING_METADATA)
    if state is not None and (
        type(state) is not dict or state.get("version") != 1
        or state.get("conversation_id") != conversation_id or state.get("turn_id") != turn_id
        or state.get("question_hash") != _hash(question.get("content") or "")
        or state.get("status") not in PLANNING_STATES
    ):
        raise PlanningStateError("The saved planning inputs changed. Review a new request.")
    return question, state


def _replace(messages, question, state):
    updated = deepcopy(question)
    updated.setdefault("metadata", {})[PLANNING_METADATA] = state
    return normalize_cosmos_document(messages.replace_item(
        item=question["id"], body=updated, etag=question["_etag"],
        match_condition=MatchConditions.IfNotModified,
    ))


def _expired(state):
    try:
        return datetime.fromisoformat(state["lease_until"]) <= _now()
    except (KeyError, TypeError, ValueError):
        raise PlanningStateError("The saved planning lease is invalid.") from None


def read_planning_attempt(messages, conversation_id, message_id, turn_id):
    """Reconcile a dead planning worker without restarting model or tool work."""
    for _attempt in range(5):
        question, state = _read_question(messages, conversation_id, message_id, turn_id)
        if state is None:
            raise PlanningStateError("This question has no saved planning attempt.", code="planning_unavailable", status_code=404)
        if state["status"] != "planning" or not _expired(state):
            return question, state
        updated = {
            **state, "status": "interrupted", "error": INTERRUPTED_MESSAGE,
            "error_code": "planning_interrupted", "updated_at": _now().isoformat(),
        }
        try:
            saved = _replace(messages, question, updated)
            return saved, saved["metadata"][PLANNING_METADATA]
        except CosmosAccessConditionFailedError:
            continue
    raise PlanningStateError("Planning status changed. Reload to check its saved state.")


def claim_planning_attempt(
    messages, conversation_id, message_id, prepared, *,
    retry=False, continuation=False, retry_failed_submission=False,
):
    """Claim once, observe the same submission, or fence an explicit new attempt."""
    for _attempt in range(5):
        question, state = _read_question(messages, conversation_id, message_id, prepared["turn_id"])
        if state and state.get("claim_id") == prepared["claim_id"]:
            return state, True
        if state and state.get("submission_id") == prepared["submission_id"]:
            if state["input_fingerprint"] != prepared["input_fingerprint"]:
                raise PlanningStateError("This submission id was already used for different planning inputs.")
            _question, current = read_planning_attempt(
                messages, conversation_id, message_id, prepared["turn_id"],
            )
            if not (
                retry_failed_submission and current["status"] in {"failed", "interrupted"}
                and not current.get("run_started")
            ):
                return current, False
            state = current
        if state:
            if state["status"] == "planning":
                _question, state = read_planning_attempt(
                    messages, conversation_id, message_id, prepared["turn_id"],
                )
            allowed = (
                continuation
                or (retry and state["status"] in {"failed", "interrupted", "cancelled"})
                or (retry_failed_submission and state["status"] in {"failed", "interrupted"})
                or (
                    state["status"] == "awaiting_review"
                    and prepared["revision"] > state.get("revision", 0)
                )
            )
            if not allowed or state["status"] in {"planning", "running"} or state.get("run_started"):
                raise PlanningStateError("This question already has an active or saved plan. Reload its saved state.")
            canonical = {**state["request"], "message": question["content"]}
            proposed = {**prepared["request"], "message": question["content"]}
            if not continuation and (
                _input_fingerprint(canonical) != _input_fingerprint(proposed)
                and state["input_fingerprint"] != prepared["input_fingerprint"]
            ):
                raise PlanningStateError("The original planning selections changed. Review a new request.")
            if not continuation:
                prepared = {
                    **prepared, "request": {
                        **deepcopy(state["request"]),
                        **{
                            key: prepared["request"][key]
                            for key in _TRANSIENT_INPUTS if key in prepared["request"]
                        },
                    },
                }
        try:
            saved = _replace(messages, question, deepcopy(prepared))
            return saved["metadata"][PLANNING_METADATA], True
        except CosmosAccessConditionFailedError:
            continue
    raise PlanningStateError("This planning attempt changed. Reload its saved state.")


def update_planning_attempt(messages, conversation_id, message_id, turn_id, updates, *, claim_id=None):
    """Apply a conditional state transition; cancellation fences a late worker."""
    for _attempt in range(5):
        question, state = _read_question(messages, conversation_id, message_id, turn_id)
        if state is None or (
            claim_id is not None and (
                state.get("claim_id") != claim_id
                or state["status"] in {"cancelled", "interrupted", "failed", "completed"}
            )
        ):
            raise PlanningStateError("This planning attempt is no longer active.")
        if updates.get("status", state["status"]) not in PLANNING_STATES:
            raise ValueError("Invalid planning status.")
        updated = {**state, **deepcopy(updates), "updated_at": _now().isoformat()}
        try:
            saved = _replace(messages, question, updated)
            return saved["metadata"][PLANNING_METADATA]
        except CosmosAccessConditionFailedError:
            continue
    raise PlanningStateError("This planning attempt changed. Reload its saved state.")


def require_planning_claim(messages, conversation_id, message_id, turn_id, claim_id):
    _question, state = read_planning_attempt(messages, conversation_id, message_id, turn_id)
    if state.get("claim_id") != claim_id or state["status"] not in {"planning", "running"}:
        raise PlanningStateError("This planning attempt is no longer active.")
    return state


def heartbeat_planning_attempt(messages, conversation_id, message_id, turn_id, claim_id):
    require_planning_claim(messages, conversation_id, message_id, turn_id, claim_id)
    return update_planning_attempt(
        messages, conversation_id, message_id, turn_id,
        {"lease_until": (_now() + timedelta(seconds=PLANNING_LEASE_SECONDS)).isoformat()},
        claim_id=claim_id,
    )


def cancel_planning_attempt(
    messages, conversation_id, message_id, turn_id, *, submission_id, claim_id=None,
):
    for _attempt in range(5):
        question, state = read_planning_attempt(messages, conversation_id, message_id, turn_id)
        if state["submission_id"] != submission_id or (
            claim_id is not None and state["claim_id"] != claim_id
        ):
            raise PlanningStateError("This planning submission changed. Reload its saved state.")
        if state["status"] in {"completed", "failed", "interrupted", "cancelled"}:
            return state
        updated = {**state, "status": "cancelled", "updated_at": _now().isoformat()}
        try:
            saved = _replace(messages, question, updated)
            return saved["metadata"][PLANNING_METADATA]
        except CosmosAccessConditionFailedError:
            continue
    raise PlanningStateError("Stop could not be confirmed. Retry Stop or check saved status.")


def _cancellation_id(conversation_id, user_id, turn_id, submission_id):
    return "planning_stop_" + _hash(_json([conversation_id, user_id, turn_id, submission_id]))


def planning_was_cancelled(cancellations, conversation_id, user_id, turn_id, submission_id):
    try:
        marker = normalize_cosmos_document(cancellations.read_item(
            item=_cancellation_id(conversation_id, user_id, turn_id, submission_id),
            partition_key=conversation_id,
        ))
    except CosmosResourceNotFoundError:
        return False
    expected = {
        "record_type": "planning_cancellation", "conversation_id": conversation_id,
        "user_id": user_id, "turn_id": turn_id, "submission_id": submission_id,
    }
    if any(marker.get(key) != value for key, value in expected.items()):
        raise PlanningStateError("The saved stop request is unavailable.", code="planning_unavailable", status_code=503)
    return True


def record_planning_cancellation(cancellations, conversation_id, user_id, turn_id, submission_id):
    """An immutable typed record cannot be erased by unrelated conversation writes."""
    marker = {
        "id": _cancellation_id(conversation_id, user_id, turn_id, submission_id),
        "record_type": "planning_cancellation", "conversation_id": conversation_id,
        "user_id": user_id, "turn_id": turn_id, "submission_id": submission_id,
        "created_at": _now().isoformat(),
    }
    try:
        cancellations.create_item(marker)
    except CosmosResourceExistsError:
        if not planning_was_cancelled(cancellations, conversation_id, user_id, turn_id, submission_id):
            raise PlanningStateError("Stop could not be confirmed. Retry Stop or check saved status.") from None


def planning_projection(question, state, *, include_request=False):
    result = {
        "conversation_id": question["conversation_id"], "user_message_id": question["id"],
        "turn_id": state["turn_id"], "submission_id": state["submission_id"],
        "status": state["status"], "updated_at": state["updated_at"],
    }
    for field in ("run_id", "error", "error_code"):
        if state.get(field):
            result[field] = state[field]
    if include_request:
        result["request"] = {**deepcopy(state["request"]), "message": question["content"]}
    if "run_started" in state:
        result["run_started"] = state["run_started"]
    return result


def public_planning_message(message):
    """Private claims and replay inputs never ride along with normal history."""
    result = normalize_cosmos_document(message)
    incoming = result.get("metadata")
    if incoming is not None and type(incoming) is not dict:
        raise PlanningStateError("Saved message metadata is unavailable.", code="planning_unavailable", status_code=503)
    metadata = dict(incoming or {})
    state = metadata.pop(PLANNING_METADATA, None)
    if state is not None and type(state) is not dict:
        raise PlanningStateError("Saved planning metadata is unavailable.", code="planning_unavailable", status_code=503)
    if state and (
        state.get("conversation_id") != message.get("conversation_id")
        or metadata.get("masked") or metadata.get("masked_ranges") or is_soft_deleted_message(message)
    ):
        orchestration = dict(metadata.get("orchestration") or {})
        for field in ("planning_status", "planning_submission_id", "planning_error", "planning_run_started"):
            orchestration.pop(field, None)
        metadata["orchestration"] = orchestration
    elif state:
        if state.get("status") not in PLANNING_STATES or not state.get("turn_id") or not state.get("submission_id"):
            raise PlanningStateError("Saved planning metadata is unavailable.", code="planning_unavailable", status_code=503)
        metadata["orchestration"] = {
            **(metadata.get("orchestration") or {}),
            "turn_id": state["turn_id"], "planning_status": state["status"],
            "planning_submission_id": state["submission_id"],
            **({"run_id": state["run_id"]} if state.get("run_id") else {}),
            **({"planning_error": state["error"]} if state.get("error") else {}),
            **({"planning_run_started": state["run_started"]} if "run_started" in state else {}),
        }
    if metadata or "metadata" in result:
        result["metadata"] = metadata
    return result
