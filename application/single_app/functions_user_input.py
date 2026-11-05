# functions_user_input.py
"""Actor-private questions on the existing expiring interaction checkpoint store."""

from copy import deepcopy
from dataclasses import dataclass
import json
import time
from typing import Callable

from azure.cosmos.exceptions import CosmosHttpResponseError

from agent_interaction_contracts import UserInputRequired, UserInputError
from agent_execution_context import current_agent_execution, current_workflow_identity
from functions_action_credentials import _continuation, request_conversation
import functions_action_credential_state as state


@dataclass(frozen=True)
class UserInputServices:
    normalize_question: Callable
    normalize_answer: Callable
    capture_citations: Callable | None = None


_services = None


def configure_user_input(services):
    global _services
    _services = services


def services():
    if _services is None:
        raise UserInputError("input_unavailable", 503)
    return _services


def safe_request(item):
    context = request_conversation(item)
    return {
        "id": item["id"], "revision": 1,
        "actor_id": item["user_id"],
        "conversation_id": context.get("credential_visible_conversation_id", item["conversation_id"]),
        "conversation_kind": context.get("credential_conversation_kind", "personal"),
        "question": deepcopy(item["question"]), "status": item["status"],
        "cancel_requested": bool(item.get("cancel_requested")),
        "agent_name": item["agent_name"],
        **({"submission_id": item["submission_id"], "response": deepcopy(item["response"])}
           if item.get("submission_id") else {}),
        **{key: item["continuation"][key] for key in ("run_id", "turn_id", "step_id")
           if item["continuation"].get(key)},
    }


def read_request(user_id, request_id):
    item = state.read(user_id, request_id, record_type="user_input_request")
    request_conversation(item)
    return item


def pending_requests(user_id, conversation_ids):
    result = []
    for conversation_id in conversation_ids:
        rows = state.container().query_items(
            query="SELECT c.id FROM c WHERE c.user_id = @user AND c.conversation_id = @conversation "
                  "AND c.record_type = 'user_input_request' AND c.status IN ('pending', 'answered', 'continuing') "
                  "AND c.expires_at > @now",
            parameters=[
                {"name": "@user", "value": user_id}, {"name": "@conversation", "value": conversation_id},
                {"name": "@now", "value": time.time()},
            ], partition_key=user_id,
        )
        for row in rows:
            result.append(safe_request(read_request(user_id, row["id"])))
    return result


def request_user_input(specification, call_id):
    frame, descriptor = current_agent_execution(), _continuation.get()
    if (
        not frame or not descriptor or not descriptor.get("user_input_enabled") or not call_id
        or descriptor.get("mode") not in {"chat", "orchestration"}
    ):
        raise UserInputError("input_not_interactive")
    if current_workflow_identity(frame.identity.user_id, frame.identity.conversation_id) is not None:
        raise UserInputError("input_not_interactive")
    if not isinstance(specification, str) or len(specification.encode("utf-8")) > 32768:
        raise UserInputError("input_invalid", 400)
    try:
        spec = json.loads(specification)
    except (ValueError, TypeError) as error:
        raise UserInputError("input_invalid", 400) from error
    if type(spec) is not dict:
        raise UserInputError("input_invalid", 400)
    user_id, conversation_id = frame.identity.user_id, frame.identity.conversation_id
    item_id = f"input_{state.key_for(descriptor['checkpoint_id'], call_id)}"
    fingerprint = state.key_for(spec)
    try:
        item = read_request(user_id, item_id)
    except LookupError:
        question = services().normalize_question(spec, descriptor["checkpoint_id"])
        question.update(elicitation_id=item_id, turn_id=descriptor.get("turn_id", item_id), revision=1)
        now = time.time()
        item = {
            "id": item_id, "record_type": "user_input_request",
            "conversation_id": conversation_id, "fingerprint": fingerprint,
            "question": question, "status": "pending", "continuation": deepcopy(descriptor),
            "agent_name": frame.caller.get("display_name") or frame.caller.get("name") or "Agent",
            "budget": {
                "attempts": frame.budget.attempts, "maximum": frame.budget.maximum,
                "root_id": frame.budget.root_id, "records": frame.budget.snapshot(),
            },
            "retained_agent_citations": [
                *descriptor.get("retained_agent_citations", []),
                *(services().capture_citations(frame) if services().capture_citations else []),
            ],
            "created_at": now, "expires_at": now + state.REQUEST_TTL, "ttl": state.REQUEST_TTL,
        }
        try:
            item = state.create(user_id, item)
        except CosmosHttpResponseError as error:
            if error.status_code != 409:
                raise
            item = read_request(user_id, item_id)
    if item["conversation_id"] != conversation_id or item["fingerprint"] != fingerprint:
        raise UserInputError("input_changed")
    if item["status"] in {"answered", "continuing", "completed"}:
        response, context = services().normalize_answer(
            item["question"], item["response"], item.get("answer_context"), user_id, conversation_id,
        )
        return json.dumps({"response": response, "context": context}, ensure_ascii=True)
    if item["status"] != "pending":
        raise UserInputError("input_closed")
    raise UserInputRequired(safe_request(item))


def answer_request(user_id, request_id, body):
    item = read_request(user_id, request_id)
    if (
        type(body) is not dict or set(body) != {"revision", "submission_id", "response", "context"}
        or type(body["revision"]) is not int or body["revision"] != 1
        or not isinstance(body["submission_id"], str) or not 1 <= len(body["submission_id"]) <= 200
    ):
        raise UserInputError("input_invalid", 400)
    response, context = services().normalize_answer(
        item["question"], body["response"], body["context"], user_id, item["conversation_id"],
    )
    fingerprint = state.key_for(response, context)
    if item["status"] != "pending":
        if item.get("submission_id") == body["submission_id"] and item.get("answer_fingerprint") == fingerprint:
            return item
        raise UserInputError("input_changed")
    return state.replace(user_id, item, {
        "response": response, "answer_context": context,
        "submission_id": body["submission_id"], "answer_fingerprint": fingerprint,
        "status": "cancelled" if response["action"] == "cancel" else "answered",
    }, item["_etag"])


def finish_request(user_id, request_id, claim, status, outcome=None):
    current = read_request(user_id, request_id)
    if current["status"] != "continuing" or current.get("continuation_claim") != claim:
        raise UserInputError("input_changed")
    return state.replace(user_id, current, {
        "status": status, **({"outcome": outcome} if outcome is not None else {}),
    }, current["_etag"])


def stop_request(user_id, request_id, submission_id):
    """The owner can stop their interaction without reopening a revoked source."""
    item = state.read(user_id, request_id, record_type="user_input_request")
    if not isinstance(submission_id, str) or not submission_id or item.get("submission_id") != submission_id:
        raise UserInputError("input_changed")
    if item["continuation"].get("mode") != "chat":
        raise UserInputError("input_invalid", 400)
    if item["status"] in {"completed", "failed", "cancelled", "superseded"} or item.get("cancel_requested"):
        return item
    if item["status"] not in {"answered", "continuing"}:
        raise UserInputError("input_changed")
    return state.replace(user_id, item, {
        "cancel_requested": True,
        "status": "cancelled" if item["status"] == "answered" else "continuing",
    }, item["_etag"])
