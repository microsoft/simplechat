# functions_action_credentials.py
"""Authorize, acquire and inject the invoking actor's private action credentials."""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
import time
from typing import Callable

from flask import g, has_request_context

from action_credential_contracts import (
    ADAPTERS, ActionCredentialError, ActionCredentialsRequired, credential_fingerprint,
    credential_slots, destination_label,
)
from agent_execution_context import current_agent_execution
from functions_action_manifest import get_action_origin, resolve_action_type
import functions_action_credential_state as state


_continuation = ContextVar("action_credential_continuation", default=None)
_services = None


@dataclass(frozen=True)
class CredentialServices:
    current_user_id: Callable
    authorize_conversation: Callable
    resolve_manifest: Callable
    read_identity: Callable
    list_identities: Callable
    identity_supports_usage: Callable
    read_identity_auth: Callable
    create_identity: Callable
    update_identity: Callable
    authorize_request_context: Callable | None = None
    capture_chat_origin: Callable | None = None
    publish_chat_result: Callable | None = None


def configure_action_credential_services(services):
    global _services
    _services = services


def credential_services():
    if _services is None:
        raise ActionCredentialError("credential_runtime_unavailable", 503)
    return _services


@contextmanager
def credential_continuation(value):
    token = _continuation.set(deepcopy(value))
    try:
        yield
    finally:
        _continuation.reset(token)


def actor_context():
    frame = current_agent_execution()
    if frame:
        user_id, conversation_id = frame.identity.user_id, frame.identity.conversation_id
    elif has_request_context():
        user_id, conversation_id = credential_services().current_user_id(), getattr(g, "conversation_id", None)
    else:
        raise ActionCredentialError("credentials_need_user_action")
    if not user_id or not conversation_id:
        raise ActionCredentialError("credentials_need_user_action")
    authorize_conversation(user_id, conversation_id)
    return user_id, conversation_id, frame


def authorize_conversation(user_id, conversation_id):
    return credential_services().authorize_conversation(user_id, conversation_id)


def capture_chat_origin(user_id, conversation_id):
    callback = _services.capture_chat_origin if _services is not None else None
    return callback(user_id, conversation_id) if callback else {}


def request_conversation(item):
    callback = credential_services().authorize_request_context
    return callback(item["user_id"], item) if callback else authorize_conversation(item["user_id"], item["conversation_id"])


def pending_execution_ids(context, conversation_id):
    return context.get("credential_execution_ids", (conversation_id,))


def authorized_manifest(user_id, action_ref):
    return credential_services().resolve_manifest(user_id, action_ref)


def manifest_reference(manifest):
    origin = get_action_origin(manifest)
    if origin is None or not origin.action_id:
        raise ActionCredentialError("trusted_origin_required")
    return f"{origin.scope_type}:{origin.scope_id}:{origin.action_id}"


def identity_metadata(user_id, identity_id, auth_type):
    services = credential_services()
    identity = services.read_identity("personal", user_id, identity_id)
    if not services.identity_supports_usage(identity, "action", source_type="action", auth_types={auth_type}):
        raise ActionCredentialError("identity_incompatible", 400)
    return identity


def safe_identities(user_id, requirements):
    services = credential_services()
    types = {item["auth_type"] for item in requirements}
    return [
        {"id": item["id"], "name": item.get("name") or "Personal identity",
         "auth_type": (item.get("auth") or {}).get("auth_type"), "etag": item.get("_etag")}
        for item in services.list_identities("personal", user_id)
        if services.identity_supports_usage(item, "action", source_type="action", auth_types=types)
    ]


def safe_request(item, manifest):
    user_id = item["user_id"]
    context = request_conversation(item)
    requirements = [
        {"slot": slot, "auth_type": auth_type,
         "label": "Proxy sign-in" if slot == "proxy" else "YAMCS sign-in"}
        for slot, auth_type in item["requirements"].items()
    ]
    result = {
        "id": item["id"], "etag": item["_etag"],
        "conversation_id": context.get("credential_visible_conversation_id", item["conversation_id"]),
        "action_name": manifest.get("displayName") or manifest.get("name") or "YAMCS",
        "destination_label": destination_label(manifest), "reason": item["reason"],
        "requirements": requirements, "identities": safe_identities(user_id, requirements),
        "status": "pending" if item["status"] == "saving" else item["status"],
    }
    if context.get("credential_conversation_kind") == "collaborative":
        result["conversation_kind"] = "collaborative"
    if item["status"] == "saving":
        result["etag"] = item["submission_etag"]
    for key in ("run_id", "turn_id"):
        if item.get("continuation", {}).get(key):
            result[key] = item["continuation"][key]
    return result


def authorize_request(user_id, request_id):
    item = state.read(user_id, request_id, record_type="credential_request")
    request_conversation(item)
    manifest = authorized_manifest(user_id, item["action_ref"])
    if credential_fingerprint(manifest) != item["fingerprint"]:
        raise ActionCredentialError("action_destination_changed")
    return item, manifest


def require_credentials(manifest, slots, *, reason="setup_required"):
    user_id, conversation_id, frame = actor_context()
    continuation = _continuation.get()
    if not continuation:
        raise ActionCredentialError("credentials_need_user_action")
    current = authorized_manifest(user_id, manifest_reference(manifest))
    if credential_fingerprint(current) != credential_fingerprint(manifest):
        raise ActionCredentialError("action_destination_changed")
    item = state.request_for(
        user_id, conversation_id, manifest_reference(manifest), credential_fingerprint(manifest),
        {slot: credential_slots(manifest)[slot]["auth_type"] for slot in slots},
        reason=reason, continuation=continuation,
    )
    if item["status"] in {"cancelled", "completed"}:
        raise ActionCredentialError("credential_request_closed")
    error = ActionCredentialsRequired(safe_request(item, current))
    # The SK journal must persist its real tool history before the stop reaches
    # the outer worker; publishing through the polling budget here would cancel it early.
    raise error from None


def resolve_personal_credentials(manifest, *, rejected_slots=()):
    slots = credential_slots(manifest)
    if not slots:
        return deepcopy(manifest)
    user_id, _conversation_id, _frame = actor_context()
    reference = manifest_reference(manifest)
    current = authorized_manifest(user_id, reference)
    fingerprint = credential_fingerprint(manifest)
    if credential_fingerprint(current) != fingerprint:
        raise ActionCredentialError("action_destination_changed")
    if rejected_slots:
        require_credentials(manifest, rejected_slots, reason="credentials_rejected")
    missing, identities = [], {}
    reason = "setup_required"
    for slot, requirement in slots.items():
        binding = state.binding(user_id, reference, slot)
        if not binding:
            missing.append(slot)
            continue
        if binding.get("fingerprint") != fingerprint or not binding.get("confirmed"):
            missing.append(slot)
            reason = "binding_changed"
            continue
        try:
            identity = identity_metadata(user_id, binding["identity_id"], requirement["auth_type"])
        except LookupError:
            missing.append(slot)
            reason = "identity_removed"
            continue
        if identity.get("_etag") != binding.get("identity_etag"):
            missing.append(slot)
            reason = "identity_changed"
            continue
        identities[slot] = identity
    if missing:
        require_credentials(manifest, missing, reason=reason)
    services = credential_services()
    prepared = deepcopy(manifest)
    for slot, identity in identities.items():
        auth = services.read_identity_auth("personal", user_id, identity["id"])
        latest = identity_metadata(user_id, identity["id"], slots[slot]["auth_type"])
        if latest.get("_etag") != identity.get("_etag"):
            raise ActionCredentialError("identity_changed")
        auth_type = slots[slot]["auth_type"]
        required = ("username", "password") if auth_type == "username_password" else ("secret",)
        if auth.get("auth_type") != auth_type or any(not auth.get(key) for key in required):
            # Secret storage failures are not evidence of provider rejection.
            raise ActionCredentialError("credential_storage_unavailable", 503)
        ADAPTERS[resolve_action_type(manifest).lower()].inject(prepared, slot, auth)
    return prepared


def _validate_submission(item, slots):
    if type(slots) is not list or not slots or len(slots) > 2:
        raise ActionCredentialError("invalid_credentials", 400)
    seen = set()
    for entry in slots:
        if type(entry) is not dict or set(entry) - {
            "slot", "identity_id", "name", "credentials", "expected_identity_etag",
        }:
            raise ActionCredentialError("invalid_credentials", 400)
        slot = entry.get("slot")
        if type(slot) is not str or slot not in item["requirements"] or slot in seen:
            raise ActionCredentialError("invalid_credentials", 400)
        if entry.get("identity_id") is not None and (
            type(entry["identity_id"]) is not str or not entry["identity_id"] or len(entry["identity_id"]) > 255
        ):
            raise ActionCredentialError("invalid_credentials", 400)
        if entry.get("expected_identity_etag") is not None and type(entry["expected_identity_etag"]) is not str:
            raise ActionCredentialError("invalid_credentials", 400)
        seen.add(slot)
        credentials = entry.get("credentials")
        if not entry.get("identity_id") and not credentials:
            raise ActionCredentialError("invalid_credentials", 400)
        if credentials is not None:
            auth_type = item["requirements"][slot]
            fields = {"auth_type", "username", "password"} if auth_type == "username_password" else {"auth_type", "secret"}
            if (
                type(credentials) is not dict or set(credentials) != fields
                or credentials["auth_type"] != auth_type
                or any(type(credentials[key]) is not str or not credentials[key] or len(credentials[key]) > 8192
                       for key in fields)
            ):
                raise ActionCredentialError("invalid_credentials", 400)
            if entry.get("identity_id") and not entry.get("expected_identity_etag"):
                raise ActionCredentialError("identity_etag_required", 400)
        if not entry.get("identity_id") and (
            type(entry.get("name")) is not str or not entry["name"].strip() or len(entry["name"]) > 255
        ):
            raise ActionCredentialError("identity_name_required", 400)
    if seen != set(item["requirements"]):
        raise ActionCredentialError("incomplete_credentials", 400)


def submit_credentials(user_id, request_id, expected_etag, slots):
    item, manifest = authorize_request(user_id, request_id)
    if item["status"] == "ready" and item.get("submission_etag") == expected_etag:
        return safe_request(item, manifest)
    _validate_submission(item, slots)
    selection = sorted([
        {key: entry[key] for key in ("slot", "identity_id", "name", "expected_identity_etag") if key in entry}
        for entry in slots
    ], key=lambda entry: entry["slot"])
    if item["status"] == "saving":
        if item.get("submission_etag") != expected_etag or item.get("saving_until", 0) > time.time():
            raise ActionCredentialError("credential_request_changed")
        def targets(value):
            return [{key: field for key, field in row.items() if key != "expected_identity_etag"} for row in value]

        if targets(item.get("submission_selection") or []) != targets(selection):
            raise ActionCredentialError("credential_request_changed")
        # A failed response/write can be recovered using the same deterministic identity IDs.
        expected_etag = item["_etag"]
    elif item["status"] != "pending":
        raise ActionCredentialError("credential_request_closed")
    submission_etag = item.get("submission_etag") or expected_etag
    item = state.replace(user_id, item, {
        "status": "saving", "submission_etag": submission_etag, "saving_until": time.time() + 60,
        "submission_selection": selection,
    }, expected_etag)
    services = credential_services()
    for entry in slots:
        slot = entry["slot"]
        auth_type = item["requirements"][slot]
        identity_id = entry.get("identity_id")
        operation_id = state.key_for(request_id, submission_etag, slot)
        if identity_id:
            identity = identity_metadata(user_id, identity_id, auth_type)
            if entry.get("credentials"):
                identity = services.update_identity(
                    "personal", user_id, identity_id, {"credentials": entry["credentials"]}, user_id,
                    entry["expected_identity_etag"], operation_id=operation_id,
                )
        else:
            identity_id = "action_" + operation_id
            try:
                identity = services.read_identity("personal", user_id, identity_id)
            except LookupError:
                services.create_identity(
                    "personal", user_id, {
                        "name": entry["name"], "provider": "generic", "usage_contexts": ["action"],
                        "supported_source_types": ["action"], "credentials": entry["credentials"],
                    }, user_id, stage_secrets=True, identity_id=identity_id,
                )
                identity = services.read_identity("personal", user_id, identity_id)
            identity_metadata(user_id, identity_id, auth_type)
        # Access/destination can change during secret storage; never commit a binding to the old target.
        authorize_request(user_id, request_id)
        state.save_binding(user_id, item["action_ref"], slot, identity_id, identity["_etag"], item["fingerprint"])
    item = state.replace(user_id, item, {"status": "ready"}, item["_etag"])
    return safe_request(item, manifest)
