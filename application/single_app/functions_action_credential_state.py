# functions_action_credential_state.py
"""Private, conditional credential bindings and expiring interaction checkpoints.

Storage is supplied by application bootstrap. Neither secrets nor principals are
accepted by this owner. Requests are transient and are never backup resources.
"""

from copy import deepcopy
import hashlib
import json
import time
import uuid

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

from action_credential_contracts import ActionCredentialError
from cosmos_document_utils import normalize_cosmos_document


_container = None
REQUEST_TTL = 86400
MAX_CHECKPOINT_BYTES = 1500000


def configure_action_credential_state(container):
    global _container
    _container = container


def is_configured():
    return _container is not None


def container():
    if _container is None:
        raise ActionCredentialError("credential_storage_unavailable", 503)
    return _container


def key_for(*values):
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def read(user_id, item_id, *, record_type=None):
    try:
        item = normalize_cosmos_document(container().read_item(item_id, partition_key=user_id))
    except CosmosResourceNotFoundError:
        raise LookupError("Credential request not found.") from None
    if item.get("user_id") != user_id or (record_type and item.get("record_type") != record_type):
        raise LookupError("Credential request not found.")
    if item.get("expires_at") is not None and item["expires_at"] <= time.time():
        raise ActionCredentialError("credential_request_expired", 410)
    return item


def create(user_id, body):
    body = {**deepcopy(body), "user_id": user_id}
    return normalize_cosmos_document(container().create_item(body=body))


def replace(user_id, item, updates, expected_etag):
    if item.get("user_id") != user_id or not expected_etag or item.get("_etag") != expected_etag:
        raise ActionCredentialError("credential_request_changed")
    body = {**deepcopy(item), **deepcopy(updates)}
    if body.get("id") != item["id"] or body.get("user_id") != user_id:
        raise ActionCredentialError("credential_request_changed")
    try:
        response = container().replace_item(
            item["id"], body=body, etag=expected_etag, match_condition=MatchConditions.IfNotModified,
        )
    except CosmosHttpResponseError as error:
        if error.status_code in {409, 412}:
            raise ActionCredentialError("credential_request_changed") from None
        raise
    return normalize_cosmos_document(response)


def request_for(user_id, conversation_id, action_ref, fingerprint, requirements, *, reason, continuation):
    item_id = "request_" + key_for(conversation_id, action_ref, fingerprint, continuation, reason, requirements)
    try:
        existing = read(user_id, item_id, record_type="credential_request")
        if existing["status"] == "continuing":
            return replace(user_id, existing, {
                "status": "pending", "submission_etag": None,
            }, existing["_etag"])
        return existing
    except LookupError:
        pass
    now = time.time()
    body = {
        "id": item_id, "record_type": "credential_request", "conversation_id": conversation_id,
        "action_ref": action_ref, "fingerprint": fingerprint, "requirements": requirements,
        "reason": reason, "status": "pending", "continuation": deepcopy(continuation),
        "created_at": now, "expires_at": now + REQUEST_TTL, "ttl": REQUEST_TTL,
    }
    try:
        return create(user_id, body)
    except CosmosHttpResponseError as error:
        if error.status_code != 409:
            raise
        return read(user_id, item_id, record_type="credential_request")


def pending(user_id, conversation_id):
    return [
        dict(item) for item in container().query_items(
            query="SELECT * FROM c WHERE c.user_id = @user AND c.conversation_id = @conversation "
                  "AND c.record_type = 'credential_request' AND c.status IN ('pending', 'ready', 'saving') "
                  "AND c.expires_at > @now",
            parameters=[
                {"name": "@user", "value": user_id}, {"name": "@conversation", "value": conversation_id},
                {"name": "@now", "value": time.time()},
            ], partition_key=user_id,
        )
    ]


def binding(user_id, action_ref, slot):
    try:
        return read(user_id, "binding_" + key_for(action_ref, slot), record_type="credential_binding")
    except LookupError:
        return None


def save_binding(user_id, action_ref, slot, identity_id, identity_etag, fingerprint):
    prior = binding(user_id, action_ref, slot)
    fields = {
        "action_ref": action_ref, "slot": slot, "identity_id": identity_id,
        "identity_etag": identity_etag, "fingerprint": fingerprint, "confirmed": True,
    }
    if prior:
        if all(prior.get(key) == value for key, value in fields.items()):
            return prior
        return replace(user_id, prior, fields, prior["_etag"])
    return create(user_id, {
        "id": "binding_" + key_for(action_ref, slot), "record_type": "credential_binding", **fields,
    })


def invalidate_identity(user_id, identity_id):
    """Invalidate private bindings without revealing action names to identity management."""
    rows = list(container().query_items(
        query="SELECT * FROM c WHERE c.user_id = @user AND c.record_type = 'credential_binding' "
              "AND c.identity_id = @identity",
        parameters=[{"name": "@user", "value": user_id}, {"name": "@identity", "value": identity_id}],
        partition_key=user_id,
    ))
    for row in rows:
        current = read(user_id, row["id"], record_type="credential_binding")
        replace(user_id, current, {"confirmed": False}, current["_etag"])


def checkpoint(user_id, checkpoint_id, conversation_id, value, *, expected_etag=None):
    if len(json.dumps(value, separators=(",", ":")).encode()) > MAX_CHECKPOINT_BYTES:
        raise ActionCredentialError("credential_checkpoint_too_large")
    try:
        current = read(user_id, checkpoint_id, record_type="credential_checkpoint")
    except LookupError:
        return create(user_id, {
            "id": checkpoint_id, "record_type": "credential_checkpoint", "conversation_id": conversation_id,
            "value": deepcopy(value), "ttl": REQUEST_TTL, "expires_at": time.time() + REQUEST_TTL,
        })
    if current.get("conversation_id") != conversation_id:
        raise ActionCredentialError("credential_checkpoint_changed")
    return replace(user_id, current, {"value": deepcopy(value)}, expected_etag or current["_etag"])


def claim_request(user_id, item, expected_etag):
    if item["status"] != "ready":
        raise ActionCredentialError("credential_request_not_ready")
    return replace(user_id, item, {
        "status": "continuing", "continuation_claim": uuid.uuid4().hex,
    }, expected_etag)


def delete_private_state(user_id, *, conversation_id=None):
    """The authorized lifecycle owner supplies the actor; queries never span partitions."""
    if not is_configured():
        return
    parameters = [{"name": "@user", "value": user_id}]
    query = "SELECT * FROM c WHERE c.user_id = @user"
    if conversation_id is not None:
        query += " AND c.conversation_id = @conversation"
        parameters.append({"name": "@conversation", "value": conversation_id})
    for row in container().query_items(query=query, parameters=parameters, partition_key=user_id):
        if row.get("user_id") != user_id or (
            conversation_id is not None and row.get("conversation_id") != conversation_id
        ):
            raise ActionCredentialError("credential_request_changed")
        try:
            container().delete_item(
                row["id"], partition_key=user_id, etag=row["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except CosmosResourceNotFoundError:
            pass
