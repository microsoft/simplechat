# functions_group_endpoint_access.py
"""Authorization, projection and orchestration for immutable-target group model endpoints.

The active-scoped legacy routes in ``route_backend_models.py``
(``/api/group/model-endpoints`` and ``/api/group/models/*``) keep their own contract;
only the legacy bulk save borrows the credential rules below, through the public
helpers in the "legacy bulk save" section. Everything else here backs the
``/api/groups/<group_id>/model-endpoints`` family and the
named-group discovery routes, where the group is named in the path and every
request reauthorizes membership, role and status independently of whatever
workspace the account has selected.

Group endpoints live on the group document, which also holds membership and
status. A write therefore never replaces the stored collection wholesale: it
applies exactly one endpoint change to the copy it has just read, re-normalizes
and re-validates the whole collection as the legacy save does, and replaces the
document conditionally through ``update_group_document_with_etag_guard``. A
membership or status change that lands in between is re-read and kept, and a group
deleted mid-write is reported as missing, never recreated.

Each endpoint is projected as the sanitized admin shape plus two per-request
fields: ``revision`` (see :func:`endpoint_revision`) and ``endpoint_actions`` (from
the policy module). PATCH and DELETE carry ``expected_revision`` and are refused
with ``endpoint_conflict`` when the stored endpoint has changed, with nothing
written. A secret-only change by another writer does not change ``revision``; that
is acceptable because PATCH replaces only a credential the client supplies.

Clearing works as in the admin and personal APIs: the server-side merge skips blank
values, so a stripped credential or an omitted field keeps its stored value. A
field is cleared by replacing it with another value, or, for a credential, by
switching the authentication type, which drops the credentials the new type does
not use.

Credentials follow the admin path's staging rule. A new secret is written to a
fresh Key Vault name (``stage_new_secrets=True``) so a write that loses its race
cannot overwrite a credential another writer committed. Superseded and removed
credentials are deleted only after the document write commits. Staged credentials
of a write that ends definitively without committing (a conflict, a missing group,
a refused change) are deleted, but a credential the stored document references is
never deleted, and after an uncertain failure (a transport error on the replace)
staged credentials are kept rather than risk deleting one a committed write uses.
A client can never supply a Key Vault reference itself: the reference names are
keyed by endpoint id only, so accepting one would let an endpoint borrow a
credential stored for another group's endpoint with the same id.

The native surface manages the providers the endpoint editor offers
(``is_frontend_visible_model_endpoint_provider``). Any other provider stored on the
group is not listed or addressable here, and every write preserves it.

An endpoint that would use the application's own identity follows the one rule in
``functions_model_endpoint_app_identity``: an Azure AI host of the configured cloud,
no token audience or authority override and no identity selection. A new or changed
endpoint that breaks it is refused before anything is staged.

Native writes log a tagged ``[MODELS]`` diagnostic for create, update and delete
with ``group_id`` and ``endpoint_id``, and no activity event, matching the personal
and admin per-item APIs.
"""

import copy
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from config import cosmos_group_agents_container, cosmos_group_workflows_container
from functions_ai_connections import AIConnectionError
from functions_appinsights import log_event
from functions_group import (
    GROUP_WRITE_CONFLICT_CODE,
    GROUP_WRITE_CONFLICT_MESSAGE,
    GroupDocumentWriteConflict,
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_user_role_in_group,
    update_group_document_with_etag_guard,
)
from functions_group_endpoint_policy import (
    GROUP_ENDPOINT_READER_ROLES,
    GROUP_ENDPOINT_READ_STATUSES,
    GROUP_ENDPOINT_WRITE_ROLES,
    group_endpoint_actions,
    group_endpoint_management_operations,
    group_endpoints_available,
)
from functions_keyvault import (
    MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS,
    keyvault_model_endpoint_cleanup_helper,
    keyvault_model_endpoint_delete_helper,
    keyvault_model_endpoint_save_helper,
    ui_trigger_word,
    validate_secret_name_dynamic,
)
from functions_keyvault_errors import KeyVaultSecretStorageError
from functions_model_capabilities import ModelTokenBudgetError
from functions_model_endpoint_app_identity import check_application_identity_save
from functions_model_endpoint_providers import get_model_endpoint_provider_ui_options
from functions_model_endpoint_validation import ModelEndpointValidationError, validate_custom_model_endpoints
from functions_settings import (
    get_settings,
    is_admin_settings_redacted_secret,
    is_frontend_visible_model_endpoint_provider,
    merge_model_endpoint_payload,
    normalize_model_endpoints,
    sanitize_model_endpoints_for_frontend,
)


INVALID_GROUP_ENDPOINT_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
# A client-chosen id must leave room for a staged Key Vault name
# (``{id}--model-endpoint--group--s-<hex>`` within 127 characters).
GROUP_ENDPOINT_MAX_CLIENT_ID_LENGTH = 64

# Stored ``auth`` fields that hold credentials. They never reach a client and never
# contribute to a revision.
GROUP_ENDPOINT_SECRET_FIELDS = ("api_key", "client_secret", "bearer_token", "access_token", "refresh_token")
# Per-request projection fields. A client may send them back, but they are never stored.
GROUP_ENDPOINT_PROJECTION_FIELDS = ("revision", "endpoint_actions")
# The agent types that bind a Foundry connection, and where each keeps its endpoint id.
GROUP_ENDPOINT_FOUNDRY_AGENT_SETTINGS = {
    "aifoundry": "azure_ai_foundry",
    "new_foundry": "new_foundry",
    "foundry_workflow": "foundry_workflow",
}

GROUP_ENDPOINT_CACHE_REASON = "group_model_endpoints_updated"
GROUP_ENDPOINT_NOT_FOUND_MESSAGE = "Model endpoint not found."
GROUP_ENDPOINT_CONFLICT_MESSAGE = "This model endpoint changed. Reload it before saving."
# The one group write conflict sentence, functions_group's (GROUP_WRITE_CONFLICT_MESSAGE).
GROUP_ENDPOINT_WRITE_CONFLICT_MESSAGE = GROUP_WRITE_CONFLICT_MESSAGE
GROUP_ENDPOINT_IN_USE_MESSAGE = (
    "This model endpoint is used by group agents or workflows. "
    "Change them to another endpoint, or disable this endpoint instead."
)
GROUP_ENDPOINT_WRITE_PERMISSION_MESSAGE = "You do not have permission to manage this group's model endpoints."
GROUP_ENDPOINT_OPERATION_UNAVAILABLE_MESSAGE = "This operation is unavailable for the selected group."
GROUP_ENDPOINT_CREDENTIAL_MESSAGE = "A model endpoint credential could not be stored. Re-enter it and save again."


class GroupEndpointError(HTTPException):
    """A stable, non-sensitive failure at a group model endpoint boundary.

    ``fields`` are extra, equally safe response members (``error_code``,
    ``references``) returned beside ``error``.
    """

    def __init__(self, message, status_code, **fields):
        super().__init__(description=message)
        self.code = status_code
        self.fields = fields


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_GROUP_ENDPOINT_ID.search(value)
    ):
        raise GroupEndpointError(f"Invalid {label}.", 400)


# ---------------------------------------------------------------------------
# Strict request parsing, shared with the named-group discovery routes.
# ---------------------------------------------------------------------------

def reject_query_parameters():
    """These immutable-target routes take no query parameters; a stray one is a 400."""
    if request.args:
        raise GroupEndpointError("This request does not accept query parameters.", 400)


def reject_request_body():
    if request.get_data():
        raise GroupEndpointError("This request does not accept a request body.", 400)


def read_strict_json_object():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second
    value cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise GroupEndpointError("Duplicate fields are not supported.", 400)
            payload[key] = value
        return payload

    if not request.is_json:
        raise GroupEndpointError("A JSON object is required for this request.", 400)
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise GroupEndpointError("Provide valid JSON with no duplicate fields.", 400) from error
    if not isinstance(body, dict):
        raise GroupEndpointError("A JSON object is required for this request.", 400)
    return body


# ---------------------------------------------------------------------------
# Authorization boundary
# ---------------------------------------------------------------------------

def require_group_endpoint_read_context(user_id, group_id):
    """Resolve ``(group, role, settings)`` for a reader, or raise a boundary error.

    Reads are open to all four member roles on a browsable status. Unknown group is
    404, ineligible role is 403, and a status outside the browsable set is 403: an
    unrecognized status is treated as unavailable, never as active. The one
    availability predicate gates the whole surface, including the reads.
    """
    _validate_identifier(group_id, "group identifier")
    if not user_id:
        raise GroupEndpointError("User not authenticated.", 401)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_ENDPOINT_READER_ROLES)
    except LookupError as error:
        raise GroupEndpointError("The selected group was not found.", 404) from error
    except PermissionError as error:
        raise GroupEndpointError("You do not have access to the selected group.", 403) from error
    group = find_group_by_id(group_id)
    if not group:
        raise GroupEndpointError("The selected group was not found.", 404)
    role = get_user_role_in_group(group, user_id)
    if role not in GROUP_ENDPOINT_READER_ROLES:
        raise GroupEndpointError("You do not have access to the selected group.", 403)
    allowed, _reason = check_group_status_allows_operation(group, "view")
    if not allowed or group.get("status", "active") not in GROUP_ENDPOINT_READ_STATUSES:
        raise GroupEndpointError("Model endpoints are unavailable for this group's current status.", 403)
    settings = get_settings()
    available, reason = group_endpoints_available(user_id, settings)
    if not available:
        raise GroupEndpointError(reason, 403)
    return group, role, settings


def require_group_endpoint_write_context(user_id, group_id, operation):
    """Resolve ``(group, role, settings)`` for a writer, or raise a boundary error.

    Writes, discovery and tests need Owner or Admin in an ``active`` group, and the
    operation must be one the policy offers. ``User`` and ``DocumentManager`` reach
    the write-role assertion and are refused with 403.
    """
    group, role, settings = require_group_endpoint_read_context(user_id, group_id)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_ENDPOINT_WRITE_ROLES)
    except (LookupError, PermissionError) as error:
        raise GroupEndpointError(GROUP_ENDPOINT_WRITE_PERMISSION_MESSAGE, 403) from error
    if operation not in group_endpoint_management_operations(user_id, group, role, settings, available=True):
        raise GroupEndpointError(GROUP_ENDPOINT_OPERATION_UNAVAILABLE_MESSAGE, 403)
    return group, role, settings


def require_group_endpoint_discovery_context(user_id, group_id):
    """Authorize model discovery, the model test or Foundry discovery for the path group.

    All three hydrate the stored endpoint's credentials, so they need the write roles
    in an ``active`` group: the ``test`` operation.
    """
    return require_group_endpoint_write_context(user_id, group_id, "test")


def _authorize_stored_writer(document, user_id):
    """Recheck the writer against the exact group document version being replaced.

    Membership and status live on the same document the write replaces, so checking
    them inside the conditional write means a demotion or a status change that lands
    after the request was authorized refuses the write instead of racing it.
    """
    if get_user_role_in_group(document, user_id) not in GROUP_ENDPOINT_WRITE_ROLES:
        raise GroupEndpointError(GROUP_ENDPOINT_WRITE_PERMISSION_MESSAGE, 403)
    if document.get("status", "active") != "active":
        raise GroupEndpointError(GROUP_ENDPOINT_OPERATION_UNAVAILABLE_MESSAGE, 403)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------

def endpoint_revision(endpoint):
    """The conflict token for one stored endpoint.

    SHA-256 over the canonical JSON (``sort_keys=True``, ``separators=(",", ":")``)
    of the endpoint as stored, with every credential field removed from ``auth``. It
    never hashes a secret, even when Key Vault is off and secrets are stored inline,
    and it does not move when catalogue settings change, because it reads the stored
    record rather than the settings-dependent projection.
    """
    material = copy.deepcopy(endpoint) if isinstance(endpoint, dict) else {}
    auth = material.get("auth")
    if isinstance(auth, dict):
        for field in GROUP_ENDPOINT_SECRET_FIELDS:
            auth.pop(field, None)
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stored_endpoints(document):
    endpoints = (document or {}).get("model_endpoints")
    if not isinstance(endpoints, list):
        return []
    return [endpoint for endpoint in endpoints if isinstance(endpoint, dict)]


def _find_endpoint(endpoints, endpoint_id):
    reference = str(endpoint_id or "")
    for endpoint in endpoints:
        if isinstance(endpoint, dict) and str(endpoint.get("id") or "") == reference:
            return endpoint
    return None


def _is_managed_provider(endpoint):
    return is_frontend_visible_model_endpoint_provider((endpoint or {}).get("provider"))


def _find_managed_endpoint(endpoints, endpoint_id):
    endpoint = _find_endpoint(endpoints, endpoint_id)
    if endpoint is None or not _is_managed_provider(endpoint):
        raise GroupEndpointError(GROUP_ENDPOINT_NOT_FOUND_MESSAGE, 404)
    return endpoint


def _project_group_endpoint(stored, sanitized, user_id, group, role, settings, *, available=None):
    """One endpoint for a client: the sanitized admin shape plus fresh per-request fields."""
    projected = dict(sanitized)
    projected["revision"] = endpoint_revision(stored)
    projected["endpoint_actions"] = group_endpoint_actions(
        stored, user_id, group, role, settings, available=available,
    )
    return projected


def _single_endpoint(stored, user_id, group, role, settings, *, available=None):
    sanitized = sanitize_model_endpoints_for_frontend([stored]) if stored else []
    if not sanitized:
        raise GroupEndpointError(GROUP_ENDPOINT_NOT_FOUND_MESSAGE, 404)
    return _project_group_endpoint(stored, sanitized[0], user_id, group, role, settings, available=available)


# ---------------------------------------------------------------------------
# Request payloads
# ---------------------------------------------------------------------------

def _is_stored_value_placeholder(value):
    return value == ui_trigger_word or is_admin_settings_redacted_secret(value)


def _check_client_credentials(payload, stored):
    """Refuse credentials a client must never send.

    A Key Vault reference is refused outright. A placeholder (the stored-secret
    trigger word or the redaction mask) is accepted only as "keep the stored
    secret", which the merge implements, so it is refused where nothing is stored.
    """
    if "auth" not in payload or payload["auth"] is None:
        return
    auth = payload["auth"]
    if not isinstance(auth, dict):
        raise GroupEndpointError("Authentication configuration must be an object.", 400)
    stored_auth = (stored or {}).get("auth") if isinstance((stored or {}).get("auth"), dict) else {}
    for field in GROUP_ENDPOINT_SECRET_FIELDS:
        value = auth.get(field)
        if value in (None, ""):
            continue
        if not isinstance(value, str):
            raise GroupEndpointError("Credentials must be text values.", 400)
        if validate_secret_name_dynamic(value):
            raise GroupEndpointError("Stored credential references cannot be supplied in a request.", 400)
        if _is_stored_value_placeholder(value) and not stored_auth.get(field):
            raise GroupEndpointError("A stored credential is unavailable. Re-enter its value.", 400)


def _endpoint_changes(body):
    """The endpoint fields of a create or update body, without projection-only fields."""
    return {key: value for key, value in body.items() if key not in GROUP_ENDPOINT_PROJECTION_FIELDS}


def _require_managed_provider(endpoint):
    if not _is_managed_provider(endpoint):
        raise GroupEndpointError(
            "This model endpoint provider is not supported for group connections.",
            400,
            code="invalid_custom_endpoint",
        )


def _read_expected_revision(body):
    expected = body.get("expected_revision")
    if not isinstance(expected, str) or not expected.strip():
        raise GroupEndpointError("A non-empty 'expected_revision' is required.", 400)
    return expected


# ---------------------------------------------------------------------------
# References
# ---------------------------------------------------------------------------

def _same_endpoint(value, endpoint_id):
    return isinstance(value, str) and bool(value.strip()) and value.strip() == str(endpoint_id)


def _agent_uses_endpoint(agent, endpoint_id):
    """Whether a group agent resolves ``endpoint_id``, exactly as the agent runtime does.

    Every agent binds through ``model_endpoint_id``; a Foundry agent may instead keep
    the id in the ``other_settings`` section for its type.
    """
    if _same_endpoint(agent.get("model_endpoint_id"), endpoint_id):
        return True
    section = GROUP_ENDPOINT_FOUNDRY_AGENT_SETTINGS.get(str(agent.get("agent_type") or "local").strip().lower())
    other_settings = agent.get("other_settings") if isinstance(agent.get("other_settings"), dict) else {}
    foundry = other_settings.get(section) if section else None
    return isinstance(foundry, dict) and _same_endpoint(foundry.get("endpoint_id"), endpoint_id)


def _workflow_uses_endpoint(workflow, endpoint_id):
    """Whether a group workflow binds ``endpoint_id``, at the top level or in any task runner."""
    if _same_endpoint(workflow.get("model_endpoint_id"), endpoint_id):
        return True
    for task in workflow.get("tasks") or []:
        runner = task.get("runner") if isinstance(task, dict) else None
        if isinstance(runner, dict) and _same_endpoint(runner.get("model_endpoint_id"), endpoint_id):
            return True
    return False


def find_group_endpoint_references(group_id, endpoint_id):
    """Every group agent and workflow that refers to ``endpoint_id``.

    Returns ``[{"kind": "agent" | "workflow", "id", "name"}]``. A failed scan raises
    rather than returning an empty list, so a delete can never pass on a scan that
    did not run.
    """
    parameters = [{"name": "@group_id", "value": group_id}]
    references = []
    try:
        agents = cosmos_group_agents_container.query_items(
            query=(
                "SELECT c.id, c.name, c.display_name, c.agent_type, c.model_endpoint_id, c.other_settings "
                "FROM c WHERE c.group_id = @group_id"
            ),
            parameters=parameters,
            partition_key=group_id,
        )
        for agent in agents:
            if isinstance(agent, dict) and _agent_uses_endpoint(agent, endpoint_id):
                references.append({
                    "kind": "agent",
                    "id": str(agent.get("id") or ""),
                    "name": str(agent.get("display_name") or agent.get("name") or ""),
                })
        workflows = cosmos_group_workflows_container.query_items(
            query="SELECT c.id, c.name, c.model_endpoint_id, c.tasks FROM c WHERE c.group_id = @group_id",
            parameters=parameters,
            partition_key=group_id,
        )
        for workflow in workflows:
            if isinstance(workflow, dict) and _workflow_uses_endpoint(workflow, endpoint_id):
                references.append({
                    "kind": "workflow",
                    "id": str(workflow.get("id") or ""),
                    "name": str(workflow.get("name") or ""),
                })
    except Exception as exc:
        log_event(
            "[MODELS] Unable to check group model endpoint references.",
            extra={"group_id": group_id, "endpoint_id": endpoint_id, "error_type": type(exc).__name__},
            level=logging.ERROR,
        )
        raise GroupEndpointError("Unable to confirm this model endpoint is unused. Try again.", 503) from exc
    return references


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

def _credential_references(endpoint):
    """``{field: reference}`` for each Key Vault reference an endpoint stores."""
    auth = (endpoint or {}).get("auth")
    if not isinstance(auth, dict):
        return {}
    return {
        field: auth[field] for field in MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS
        if isinstance(auth.get(field), str) and validate_secret_name_dynamic(auth[field])
    }


def _document_credentials(document):
    """Every credential value the stored endpoints of a group document refer to."""
    values = set()
    for endpoint in _stored_endpoints(document):
        auth = endpoint.get("auth")
        if isinstance(auth, dict):
            values.update(
                auth[field] for field in GROUP_ENDPOINT_SECRET_FIELDS
                if isinstance(auth.get(field), str) and auth[field]
            )
    return values


def _without_live_credentials(endpoint, live):
    """A copy of ``endpoint`` without the credentials a committed document still uses."""
    auth = endpoint.get("auth")
    if not isinstance(auth, dict):
        return endpoint
    return {
        **endpoint,
        "auth": {
            field: value for field, value in auth.items()
            if not (field in MODEL_ENDPOINT_SENSITIVE_AUTH_FIELDS and value in live)
        },
    }


def _log_credential_cleanup_failure(group_id, endpoint_id, exc):
    log_event(
        "[KEY_VAULT] Unable to remove an unused group model endpoint credential.",
        extra={"group_id": group_id, "endpoint_id": endpoint_id, "error_type": type(exc).__name__},
        level=logging.WARNING,
    )


def _log_kept_staged_credentials(group_id, staged):
    log_event(
        "[KEY_VAULT] Kept staged group model endpoint credentials after an uncertain write.",
        extra={"group_id": group_id, "count": len(staged)},
        level=logging.WARNING,
    )


def _discard_staged_credentials(group_id, staged):
    """Delete credentials a write staged but never committed.

    Called only when a write ends definitively without committing. The stored
    document is read again first and any credential it refers to is kept: an earlier
    attempt of the same write may have committed before a transport retry lost its
    response. When that read fails, nothing is deleted.
    """
    if not staged:
        return
    try:
        live = _document_credentials(find_group_by_id(group_id))
    except Exception as exc:
        log_event(
            "[KEY_VAULT] Kept staged group model endpoint credentials after an unconfirmed write.",
            extra={"group_id": group_id, "count": len(staged), "error_type": type(exc).__name__},
            level=logging.WARNING,
        )
        return
    for endpoint_id, field, reference in staged:
        if reference in live:
            continue
        try:
            keyvault_model_endpoint_delete_helper({"auth": {field: reference}}, endpoint_id, scope="group")
        except Exception as exc:
            _log_credential_cleanup_failure(group_id, endpoint_id, exc)


def _clean_up_committed_credentials(group_id, committed, outcome, staged):
    """After a committed write, remove the credentials the stored document no longer uses.

    The legacy save's second and third Key Vault passes, run only after the write:
    credentials an endpoint replaced, credentials of a removed endpoint, and
    credentials an earlier attempt of this write staged before losing its race. A
    failure here never fails the committed write.
    """
    live = _document_credentials(committed)
    saved_by_id = {str(endpoint.get("id") or ""): endpoint for endpoint in outcome.get("saved", [])}
    for previous in outcome.get("previous", []):
        endpoint_id = str(previous.get("id") or "")
        if not endpoint_id:
            continue
        remaining = _without_live_credentials(previous, live)
        try:
            if endpoint_id in saved_by_id:
                keyvault_model_endpoint_cleanup_helper(remaining, saved_by_id[endpoint_id], endpoint_id, scope="group")
            else:
                keyvault_model_endpoint_delete_helper(remaining, endpoint_id, scope="group")
        except Exception as exc:
            _log_credential_cleanup_failure(group_id, endpoint_id, exc)
    for endpoint_id, field, reference in staged:
        if reference in live:
            continue
        try:
            keyvault_model_endpoint_delete_helper({"auth": {field: reference}}, endpoint_id, scope="group")
        except Exception as exc:
            _log_credential_cleanup_failure(group_id, endpoint_id, exc)


# ---------------------------------------------------------------------------
# The legacy bulk save's credentials
# ---------------------------------------------------------------------------
# ``POST /api/group/model-endpoints`` in ``route_backend_models`` writes the whole
# list through ``update_group_model_endpoints`` and settles its Key Vault
# credentials with the same rules as the one-endpoint write below.

def staged_group_endpoint_credentials(requested, previous_by_id, secured):
    """``(endpoint_id, field, reference)`` for each credential a Key Vault save pass stored afresh.

    ``requested`` and ``secured`` are the endpoints before and after the pass, in the
    same order, and ``previous_by_id`` the stored endpoints by id. A reference either
    of them already held is not staged.
    """
    staged = []
    for endpoint, saved in zip(requested, secured):
        if not isinstance(saved, dict):
            continue
        previous = previous_by_id.get(saved.get("id"))
        known = set(_credential_references(endpoint).values()) | set(_credential_references(previous).values())
        staged.extend(
            (str(saved.get("id") or ""), field, reference)
            for field, reference in _credential_references(saved).items()
            if reference not in known
        )
    return staged


def discard_staged_group_endpoint_credentials(group_id, staged):
    """After a save that ended definitively without committing, delete what it staged.

    A credential the stored document refers to is kept.
    """
    _discard_staged_credentials(group_id, staged)


def keep_staged_group_endpoint_credentials(group_id, staged):
    """After an uncertain failure, keep what the save staged rather than risk deleting a committed one."""
    if staged:
        _log_kept_staged_credentials(group_id, staged)


def clean_up_committed_group_endpoint_credentials(group_id, committed, outcome, staged):
    """After a committed save, delete the credentials the committed endpoints no longer use.

    ``outcome`` holds the endpoints the write replaced (``previous``) and wrote
    (``saved``). A credential the committed document still refers to is never deleted.
    """
    _clean_up_committed_credentials(group_id, committed, outcome, staged)


# ---------------------------------------------------------------------------
# The one-endpoint write
# ---------------------------------------------------------------------------

def _stored_timestamp():
    """The ``modifiedDate`` format the legacy group writers store."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _write_endpoint_change(user_id, group_id, settings, change):
    """Apply one endpoint change to the group document and return ``(committed, outcome)``.

    ``change(stored_endpoints)`` receives a private copy of the stored endpoints of
    the document version being replaced and returns ``(endpoints, endpoint_id)``; it
    runs once per attempt and may raise ``GroupEndpointError`` to refuse the change.
    """
    staged = []
    outcome = {}

    def apply(document):
        _authorize_stored_writer(document, user_id)
        stored = _stored_endpoints(document)
        endpoints, endpoint_id = change(copy.deepcopy(stored))
        normalized, _changed = normalize_model_endpoints(endpoints)
        validate_custom_model_endpoints(normalized, settings)
        previous_by_id = {str(endpoint.get("id") or ""): endpoint for endpoint in stored}
        # The application identity rule, judged before anything is staged. Only a new
        # or changed endpoint is judged here; an unchanged stored one is judged when used.
        for endpoint in normalized:
            check_application_identity_save(endpoint, previous_by_id.get(str(endpoint.get("id") or "")), "group")
        saved = []
        for endpoint in normalized:
            key = str(endpoint.get("id") or "")
            previous = previous_by_id.get(key)
            known = set(_credential_references(endpoint).values()) | set(_credential_references(previous).values())
            try:
                secured = keyvault_model_endpoint_save_helper(
                    endpoint, key, scope="group", existing_endpoint=previous, stage_new_secrets=True,
                )
            except ValueError as exc:
                raise GroupEndpointError(GROUP_ENDPOINT_CREDENTIAL_MESSAGE, 400) from exc
            staged.extend(
                (key, field, reference)
                for field, reference in _credential_references(secured).items()
                if reference not in known
            )
            saved.append(secured)
        document["model_endpoints"] = saved
        document["modifiedDate"] = _stored_timestamp()
        outcome.update(previous=stored, saved=saved, endpoint_id=endpoint_id)
        return document

    definitive = (
        GroupEndpointError, GroupDocumentWriteConflict, ModelTokenBudgetError,
        ModelEndpointValidationError, AIConnectionError, KeyVaultSecretStorageError,
    )
    try:
        committed = update_group_document_with_etag_guard(group_id, apply, cache_reason=GROUP_ENDPOINT_CACHE_REASON)
    except definitive as exc:
        _discard_staged_credentials(group_id, staged)
        if isinstance(exc, GroupDocumentWriteConflict):
            raise GroupEndpointError(
                GROUP_ENDPOINT_WRITE_CONFLICT_MESSAGE, 409, error_code=GROUP_WRITE_CONFLICT_CODE,
            ) from exc
        raise
    except Exception:
        keep_staged_group_endpoint_credentials(group_id, staged)
        raise
    if committed is None:
        _discard_staged_credentials(group_id, staged)
        raise GroupEndpointError("The selected group was not found.", 404)
    _clean_up_committed_credentials(group_id, committed, outcome, staged)
    return committed, outcome


def _committed_endpoint(committed, outcome, user_id, settings):
    """Project the endpoint a write saved, against the committed group document."""
    stored = _find_endpoint(_stored_endpoints(committed), outcome.get("endpoint_id"))
    role = get_user_role_in_group(committed, user_id)
    return _single_endpoint(stored, user_id, committed, role, settings)


def _log_committed_change(action, user_id, group_id, endpoint_id):
    log_event(
        f"[MODELS] Group model endpoint {action}.",
        extra={"user_id": user_id, "group_id": group_id, "endpoint_id": endpoint_id},
        level=logging.INFO,
    )


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def list_group_model_endpoints(user_id, group_id):
    group, role, settings = require_group_endpoint_read_context(user_id, group_id)
    stored = _stored_endpoints(group)
    stored_by_id = {str(endpoint.get("id")): endpoint for endpoint in stored if endpoint.get("id")}
    endpoints = []
    for sanitized in sanitize_model_endpoints_for_frontend(stored):
        record = stored_by_id.get(str(sanitized.get("id") or ""))
        if record is None:
            continue
        endpoints.append(
            _project_group_endpoint(record, sanitized, user_id, group, role, settings, available=True)
        )
    return {
        "endpoints": endpoints,
        "multi_endpoint_enabled": bool(settings.get("enable_multi_model_endpoints", False)),
        "custom_api_types": get_model_endpoint_provider_ui_options(),
    }, 200


def get_group_model_endpoint(user_id, group_id, endpoint_id):
    _validate_identifier(endpoint_id, "model endpoint identifier")
    group, role, settings = require_group_endpoint_read_context(user_id, group_id)
    stored = _find_managed_endpoint(_stored_endpoints(group), endpoint_id)
    return {"endpoint": _single_endpoint(stored, user_id, group, role, settings, available=True)}, 200


def create_group_model_endpoint(user_id, group_id, body):
    if "expected_revision" in body:
        raise GroupEndpointError("'expected_revision' is not used when creating a model endpoint.", 400)
    _group, _role, settings = require_group_endpoint_write_context(user_id, group_id, "create")
    candidate = _endpoint_changes(body)
    if not candidate:
        raise GroupEndpointError("Model endpoint payload must be an object.", 400)
    requested_id = candidate.get("id")
    if requested_id in (None, ""):
        endpoint_id = str(uuid.uuid4())
    else:
        _validate_identifier(requested_id, "model endpoint identifier")
        if len(requested_id) > GROUP_ENDPOINT_MAX_CLIENT_ID_LENGTH:
            raise GroupEndpointError("Invalid model endpoint identifier.", 400)
        endpoint_id = requested_id
    candidate["id"] = endpoint_id
    _check_client_credentials(candidate, None)
    _require_managed_provider(candidate)

    def change(stored):
        if _find_endpoint(stored, endpoint_id) is not None:
            raise GroupEndpointError("A model endpoint with that id already exists.", 409)
        return stored + [copy.deepcopy(candidate)], endpoint_id

    committed, outcome = _write_endpoint_change(user_id, group_id, settings, change)
    _log_committed_change("created", user_id, group_id, endpoint_id)
    return {"endpoint": _committed_endpoint(committed, outcome, user_id, settings)}, 201


def update_group_model_endpoint(user_id, group_id, endpoint_id, body):
    _validate_identifier(endpoint_id, "model endpoint identifier")
    expected_revision = _read_expected_revision(body)
    updates = _endpoint_changes({key: value for key, value in body.items() if key != "expected_revision"})
    if not updates:
        raise GroupEndpointError("No fields provided for update.", 400)
    operation = "enable" if set(updates) == {"enabled"} else "edit"
    _group, _role, settings = require_group_endpoint_write_context(user_id, group_id, operation)

    def change(stored):
        current = _find_managed_endpoint(stored, endpoint_id)
        if endpoint_revision(current) != expected_revision:
            raise GroupEndpointError(GROUP_ENDPOINT_CONFLICT_MESSAGE, 409, error_code="endpoint_conflict")
        _check_client_credentials(updates, current)
        merged = merge_model_endpoint_payload(current, {**updates, "id": current.get("id")})
        _require_managed_provider(merged)
        return [
            merged if str(endpoint.get("id") or "") == str(current.get("id") or "") else endpoint
            for endpoint in stored
        ], current.get("id")

    committed, outcome = _write_endpoint_change(user_id, group_id, settings, change)
    _log_committed_change("updated", user_id, group_id, outcome.get("endpoint_id"))
    return {"endpoint": _committed_endpoint(committed, outcome, user_id, settings)}, 200


def delete_group_model_endpoint(user_id, group_id, endpoint_id, body):
    _validate_identifier(endpoint_id, "model endpoint identifier")
    unknown = set(body) - {"expected_revision"}
    if unknown:
        raise GroupEndpointError(f"Unsupported field(s): {', '.join(sorted(unknown))}.", 400)
    expected_revision = _read_expected_revision(body)
    _group, _role, settings = require_group_endpoint_write_context(user_id, group_id, "delete")

    def change(stored):
        current = _find_managed_endpoint(stored, endpoint_id)
        if endpoint_revision(current) != expected_revision:
            raise GroupEndpointError(GROUP_ENDPOINT_CONFLICT_MESSAGE, 409, error_code="endpoint_conflict")
        references = find_group_endpoint_references(group_id, current.get("id"))
        if references:
            raise GroupEndpointError(
                GROUP_ENDPOINT_IN_USE_MESSAGE, 409, error_code="endpoint_in_use", references=references,
            )
        return [
            endpoint for endpoint in stored
            if str(endpoint.get("id") or "") != str(current.get("id") or "")
        ], current.get("id")

    _committed, outcome = _write_endpoint_change(user_id, group_id, settings, change)
    _log_committed_change("deleted", user_id, group_id, outcome.get("endpoint_id"))
    return {"success": True}, 200


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

def group_endpoint_error_response(exc):
    """Map boundary, validation and storage errors to stable HTTP responses."""
    if isinstance(exc, GroupEndpointError):
        payload, status = {"error": exc.description, **exc.fields}, exc.code
    elif isinstance(exc, ModelTokenBudgetError):
        payload, status = {"error": exc.public_message, "error_code": exc.code}, 400
    elif isinstance(exc, ModelEndpointValidationError):
        payload, status = {"error": exc.public_message, "code": "invalid_custom_endpoint"}, 400
    elif isinstance(exc, AIConnectionError):
        payload, status = {"error": exc.public_message, "code": exc.code}, 400
    elif isinstance(exc, KeyVaultSecretStorageError):
        payload, status = {"error": exc.public_message, "code": exc.code}, 500
    else:
        log_event(
            "[MODELS] Group model endpoint request failed.",
            extra={"error_type": type(exc).__name__},
            level=logging.ERROR,
        )
        payload, status = {"error": "Unable to complete the model endpoint request."}, 500
    if status == 400 and not isinstance(exc, GroupEndpointError):
        log_event(
            "[MODELS] Group model endpoint validation failed.",
            extra={"error_type": type(exc).__name__, "code": payload.get("code") or payload.get("error_code")},
            level=logging.WARNING,
        )
    response = jsonify(payload)
    response.headers["Cache-Control"] = "no-store"
    return response, status
