# functions_personal_identity_access.py
"""Session-owned identity authoring with conditional writes for the V2 workspace."""

import logging
import re

from flask import jsonify
from werkzeug.exceptions import HTTPException

from functions_appinsights import log_event
from functions_file_sync import list_file_sync_sources
from functions_settings import get_settings
from functions_workspace_sections import build_workspace_section_availability
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_PERSONAL,
    WORKSPACE_IDENTITY_USAGE_SOURCE_TYPES,
    WorkspaceIdentityConflict,
    WorkspaceIdentityValidationError,
    create_workspace_identity,
    delete_workspace_identity_conditional,
    get_action_identity_reference_id,
    get_action_proxy_identity_reference_id,
    get_workspace_identity,
    list_workspace_identities,
    log_workspace_identity_reference_block,
    normalize_identity_supported_source_types,
    normalize_identity_usage_contexts,
    sanitize_workspace_identity,
    update_workspace_identity_conditional,
)


_INVALID_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
_WRITE_FIELDS = frozenset({
    "name", "description", "provider", "source_type", "usage_contexts",
    "supported_source_types", "metadata", "credentials",
})
_CREDENTIAL_FIELDS = frozenset({
    "auth_type", "username", "domain", "identity", "client_id", "tenant_id",
    "managed_identity_client_id", "password", "secret", "key", "token", "connection_string",
})


class PersonalIdentityError(HTTPException):
    """A reviewed, client-safe failure."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


class PersonalIdentityInUse(Exception):
    def __init__(self, references):
        super().__init__("This workspace identity is still in use.")
        self.references = references


def _require_context(user_id, user_info):
    if not isinstance(user_id, str) or not user_id:
        raise PersonalIdentityError("User not authenticated.", 401)
    availability = build_workspace_section_availability(
        get_settings(), user_id, user_info=user_info,
        user_roles=(user_info or {}).get("roles"),
    )
    if not availability["enabled"]:
        raise PersonalIdentityError("Your personal workspace is not enabled.", 403)
    section = availability["sections"]["identities"]
    if not section["enabled"]:
        raise PersonalIdentityError(section["reason"], 403)


def _validate_identifier(identity_id):
    if (
        not isinstance(identity_id, str) or not identity_id or len(identity_id) > 512
        or identity_id != identity_id.strip() or identity_id in (".", "..")
        or _INVALID_ID.search(identity_id)
    ):
        raise PersonalIdentityError("Invalid identity identifier.", 400)


def _write_body(body, *, updating=False):
    if not isinstance(body, dict) or set(body) - (_WRITE_FIELDS | ({"expected_etag"} if updating else set())):
        raise PersonalIdentityError("Unknown fields are not supported.", 400)
    for key, limit in (("name", 120), ("description", 500), ("provider", 80), ("source_type", 80)):
        if key in body and (not isinstance(body[key], str) or len(body[key]) > limit):
            raise PersonalIdentityError("The workspace identity details are not valid.", 400)
    if "name" in body and not body["name"].strip():
        raise PersonalIdentityError("An identity name is required.", 400)
    if not updating and "name" not in body:
        raise PersonalIdentityError("An identity name is required.", 400)
    allowed_sources = set().union(*WORKSPACE_IDENTITY_USAGE_SOURCE_TYPES.values())
    for key, allowed in (("usage_contexts", {"file_sync", "action"}), ("supported_source_types", allowed_sources)):
        if key in body and (
            not isinstance(body[key], list) or not body[key]
            or any(not isinstance(value, str) or value not in allowed for value in body[key])
        ):
            raise PersonalIdentityError("The selected identity uses are not valid.", 400)
    if "metadata" in body and not isinstance(body["metadata"], dict):
        raise PersonalIdentityError("The workspace identity details are not valid.", 400)
    if "credentials" in body:
        credentials = body["credentials"]
        if (
            not isinstance(credentials, dict) or set(credentials) - _CREDENTIAL_FIELDS
            or any(not isinstance(value, str) for value in credentials.values())
        ):
            raise PersonalIdentityError("The identity credentials are not valid.", 400)
    return {key: value for key, value in body.items() if key in _WRITE_FIELDS}


def _expected_etag(body):
    expected = body.get("expected_etag") if isinstance(body, dict) else None
    if not isinstance(expected, str) or not expected.strip():
        raise PersonalIdentityError("An expected_etag is required for this action.", 400)
    return expected.strip()


def _project(identity):
    projected = sanitize_workspace_identity(identity)
    projected["usage_contexts"] = normalize_identity_usage_contexts(identity)
    projected["supported_source_types"] = normalize_identity_supported_source_types(identity)
    projected["etag"] = identity.get("_etag", "")
    projected["identity_actions"] = ["edit", "delete"]
    return projected


def personal_identity_error_response(error):
    status = 500
    payload = {"error": "Unable to complete the workspace identity request."}
    if isinstance(error, PersonalIdentityInUse):
        status = 409
        payload = {
            "error": "This workspace identity is still in use.",
            "error_code": "identity_in_use",
            "references": error.references,
        }
    elif isinstance(error, PersonalIdentityError):
        status, payload = error.code, {"error": error.description}
    elif isinstance(error, WorkspaceIdentityConflict):
        status = 409
        payload = {
            "error": "This workspace identity was modified. Reload and try again.",
            "error_code": "etag_conflict",
        }
    elif isinstance(error, LookupError):
        status, payload = 404, {"error": "The workspace identity was not found."}
    elif isinstance(error, PermissionError):
        status, payload = 403, {"error": "You do not have access to this workspace identity."}
    elif isinstance(error, WorkspaceIdentityValidationError):
        status, payload = 400, {"error": error.public_message}
    elif isinstance(error, ValueError):
        status, payload = 400, {"error": "The workspace identity details are not valid."}
    if status == 500:
        log_event(
            "[WORKSPACE_IDENTITY] Native personal identity request failed.",
            level=logging.ERROR, extra={"error_type": type(error).__name__},
        )
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status


def list_personal_identities(user_id, *, user_info=None):
    _require_context(user_id, user_info)
    return {"identities": [_project(identity) for identity in list_workspace_identities("personal", user_id)]}, 200


def get_personal_identity(user_id, identity_id, *, user_info=None):
    _require_context(user_id, user_info)
    _validate_identifier(identity_id)
    return {"identity": _project(get_workspace_identity("personal", user_id, identity_id))}, 200


def create_personal_identity(user_id, body, *, user_info=None):
    _require_context(user_id, user_info)
    payload = _write_body(body)
    created = create_workspace_identity("personal", user_id, payload, user_id, stage_secrets=True)
    stored = get_workspace_identity("personal", user_id, created["identity_id"])
    return {"identity": _project(stored)}, 201


def update_personal_identity(user_id, identity_id, body, *, user_info=None):
    _require_context(user_id, user_info)
    _validate_identifier(identity_id)
    etag = _expected_etag(body)
    payload = _write_body(body, updating=True)
    stored = update_workspace_identity_conditional("personal", user_id, identity_id, payload, user_id, etag)
    return {"identity": _project(stored)}, 200


def delete_personal_identity(user_id, identity_id, body, *, user_info=None):
    _require_context(user_id, user_info)
    _validate_identifier(identity_id)
    etag = _expected_etag(body)
    if set(body) - {"expected_etag"}:
        raise PersonalIdentityError("Unknown fields are not supported.", 400)
    get_workspace_identity("personal", user_id, identity_id)
    references = []
    for source in list_file_sync_sources(WORKSPACE_IDENTITY_SCOPE_PERSONAL, user_id):
        if source.get("identity_id") == identity_id:
            references.append({
                "kind": "file_source", "id": str(source.get("id") or source.get("source_id") or ""),
                "name": str(source.get("name") or ""),
            })
    # Deferred for the same route/action startup boundary as the existing identity APIs.
    from functions_personal_actions import get_personal_actions

    for action in get_personal_actions(user_id):
        if identity_id in (get_action_identity_reference_id(action), get_action_proxy_identity_reference_id(action)):
            references.append({
                "kind": "action", "id": str(action.get("id") or action.get("name") or ""),
                "name": str(action.get("displayName") or action.get("name") or ""),
            })
    if references:
        log_workspace_identity_reference_block("personal", user_id, identity_id, len(references))
        raise PersonalIdentityInUse(references)
    delete_workspace_identity_conditional("personal", user_id, identity_id, user_id, etag)
    return {"success": True}, 200
