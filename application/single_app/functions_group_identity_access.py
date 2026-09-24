# functions_group_identity_access.py
"""Authorization, projection and orchestration for immutable-target group identities.

The active-scoped legacy routes (``/api/workspace-identities/group/identities``)
resolve whatever group the account has selected and are left exactly as they are.
This module backs the new ``/api/groups/<group_id>/identities`` family, where the
group is named in the path and every request reauthorizes membership, role and
group status independently. An older server lacking this family 404s rather than
silently editing the account's selected group.

Group identities are a manager-only surface for reads and writes. There is one
availability predicate, :func:`group_identities_available`, and one management
projection, both computed fresh on every request so a stored ``identity_actions``
can never be served. Writes are conditional on the caller's ``expected_etag`` so a
stale editor cannot overwrite a concurrent manager edit, and a delete refuses
while the identity is still in use, listing the references.
"""

import re

from werkzeug.exceptions import HTTPException

from functions_file_sync import list_file_sync_sources
from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_user_role_in_group,
)
from functions_group_identity_policy import (
    GROUP_IDENTITY_MANAGER_ROLES,
    GROUP_IDENTITY_READ_STATUSES,
    group_identities_available,
    group_identity_actions,
    group_identity_management_operations,
)
from functions_settings import get_settings
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_GROUP,
    WorkspaceIdentityConflict,
    create_workspace_identity,
    delete_workspace_identity_conditional,
    get_action_identity_reference_id,
    get_workspace_identity,
    list_workspace_identities,
    log_workspace_identity_reference_block,
    normalize_identity_usage_contexts,
    sanitize_workspace_identity,
    update_workspace_identity_conditional,
)


INVALID_GROUP_IDENTITY_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
# A client sends only these top-level fields. ``auth`` is refused so a caller can
# never smuggle a Key Vault reference; credentials arrive under ``credentials``.
_ALLOWED_IDENTITY_FIELDS = frozenset(
    {"name", "description", "provider", "source_type", "usage_contexts", "supported_source_types", "metadata", "credentials"}
)


class GroupIdentityError(HTTPException):
    """A stable, non-sensitive failure at a group identity boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


class GroupIdentityInUse(Exception):
    """A delete was refused because the identity is still referenced in this group."""

    def __init__(self, references):
        super().__init__("Workspace identity is still in use.")
        self.references = references


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_GROUP_IDENTITY_ID.search(value)
    ):
        raise GroupIdentityError(f"Invalid {label}.", 400)


def require_group_identity_read_context(user_id, group_id, *, user_info=None):
    """Resolve (group, role, settings, available) for a reader, or raise.

    Reads are manager-only: ordinary members cannot list group identities. Unknown
    group is 404, ineligible role is 403, and a status outside the browsable set is
    403 — an unrecognized status is treated as unavailable, never as active. The
    one availability predicate gates the whole surface (Semantic Kernel or File
    Sync for this group), so a tenant with neither offers nothing and every route
    refuses, reads included.
    """
    _validate_identifier(group_id, "group identifier")
    if not user_id:
        raise GroupIdentityError("User not authenticated.", 401)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_IDENTITY_MANAGER_ROLES)
    except LookupError as error:
        raise GroupIdentityError("The selected group was not found.", 404) from error
    except PermissionError as error:
        raise GroupIdentityError("You do not have access to the selected group.", 403) from error
    group = find_group_by_id(group_id)
    if not group:
        raise GroupIdentityError("The selected group was not found.", 404)
    role = get_user_role_in_group(group, user_id)
    if role not in GROUP_IDENTITY_MANAGER_ROLES:
        raise GroupIdentityError("You do not have access to the selected group.", 403)
    allowed, _reason = check_group_status_allows_operation(group, "view")
    if not allowed or group.get("status", "active") not in GROUP_IDENTITY_READ_STATUSES:
        raise GroupIdentityError("Identities are unavailable for this group's current status.", 403)
    settings = get_settings()
    available, reason = group_identities_available(settings, group_id, user_info=user_info)
    if not available:
        raise GroupIdentityError(reason, 403)
    return group, role, settings, available


def require_group_identity_write_context(user_id, group_id, operation, *, user_info=None):
    """Resolve (group, role, settings, available) for a writer, or raise.

    Reuses the read context (manager-only, browsable status, surface available)
    then requires the operation to be offered by the group's current status, which
    the management projection permits only while the group is ``active``.
    """
    group, role, settings, available = require_group_identity_read_context(
        user_id, group_id, user_info=user_info
    )
    if operation not in group_identity_management_operations(role, group, settings, available=available):
        raise GroupIdentityError("This operation is unavailable for the selected group.", 403)
    return group, role, settings, available


def _project_identity(identity, role, group, settings, *, available):
    """Sanitize one stored identity and attach the fresh etag and per-item actions.

    ``usage_contexts`` is re-normalized through the shared
    :func:`normalize_identity_usage_contexts` so every response advertises exactly
    what the save-time gate (``identity_supports_usage``) would accept: an older
    record that omits the field or holds an alias still reports its canonical
    contexts, so a client filtering on ``action`` never hides an identity the
    server honours.
    """
    projected = sanitize_workspace_identity(identity)
    projected["usage_contexts"] = normalize_identity_usage_contexts(identity)
    projected["etag"] = identity.get("_etag", "")
    projected["identity_actions"] = group_identity_actions(role, group, settings, available=available)
    return projected


def _validate_write_body(body):
    """Reject unknown top-level fields (including ``auth``) on a create or update."""
    if not isinstance(body, dict):
        raise GroupIdentityError("A JSON object is required for this action.", 400)
    unknown = set(body) - _ALLOWED_IDENTITY_FIELDS
    unknown.discard("expected_etag")
    if unknown:
        raise GroupIdentityError("Unknown fields are not supported.", 400)
    return {key: value for key, value in body.items() if key in _ALLOWED_IDENTITY_FIELDS}


def _require_expected_etag(body):
    if not isinstance(body, dict):
        raise GroupIdentityError("A JSON object is required for this action.", 400)
    expected = body.get("expected_etag")
    if not isinstance(expected, str) or not expected.strip():
        raise GroupIdentityError("An expected_etag is required for this action.", 400)
    return expected.strip()


def _identity_references(group_id, identity_id):
    """Every File Sync source or action in this group that still references the identity."""
    references = []
    for source in list_file_sync_sources(WORKSPACE_IDENTITY_SCOPE_GROUP, group_id):
        if source.get("identity_id") == identity_id:
            references.append({
                "kind": "file_source",
                "id": str(source.get("id") or source.get("source_id") or ""),
                "name": str(source.get("name") or source.get("display_name") or ""),
            })
    # Local import avoids a route/action import cycle during application startup.
    from functions_group_actions import get_group_actions

    for action in get_group_actions(group_id):
        if get_action_identity_reference_id(action) == identity_id:
            references.append({
                "kind": "action",
                "id": str(action.get("id") or action.get("name") or ""),
                "name": str(action.get("displayName") or action.get("display_name") or action.get("name") or ""),
            })
    return references


def group_identity_error_response(exc):
    """Map group-boundary and storage-layer errors to stable HTTP responses.

    Unlike the legacy ``_map_exception``, this never returns ``str(exc)``: a 500 in
    particular carries only a generic message so a raw exception can never reach a
    client. Validation failures answer with one stable 400.
    """
    from flask import jsonify

    def _json(payload, status):
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        return response, status

    if isinstance(exc, GroupIdentityInUse):
        return _json(
            {
                "error": "This workspace identity is still in use.",
                "error_code": "identity_in_use",
                "references": exc.references,
            },
            409,
        )
    if isinstance(exc, GroupIdentityError):
        return _json({"error": exc.description}, exc.code)
    if isinstance(exc, WorkspaceIdentityConflict):
        return _json(
            {"error": "This workspace identity was modified. Reload and try again.", "error_code": "etag_conflict"},
            409,
        )
    if isinstance(exc, LookupError):
        return _json({"error": "The workspace identity was not found."}, 404)
    if isinstance(exc, PermissionError):
        return _json({"error": "You do not have access to this workspace identity."}, 403)
    if isinstance(exc, ValueError):
        return _json({"error": "The workspace identity details are not valid."}, 400)
    return _json({"error": "Unable to complete the workspace identity request."}, 500)


def list_group_identities(user_id, group_id, *, user_info=None):
    group, role, settings, available = require_group_identity_read_context(
        user_id, group_id, user_info=user_info
    )
    identities = [
        _project_identity(identity, role, group, settings, available=available)
        for identity in list_workspace_identities(WORKSPACE_IDENTITY_SCOPE_GROUP, group_id)
    ]
    return {
        "identities": identities,
        "identity_management": {
            "schema_version": 1,
            "operations": group_identity_management_operations(role, group, settings, available=available),
        },
    }, 200


def get_group_identity(user_id, group_id, identity_id, *, user_info=None):
    group, role, settings, available = require_group_identity_read_context(
        user_id, group_id, user_info=user_info
    )
    _validate_identifier(identity_id, "identity identifier")
    identity = get_workspace_identity(WORKSPACE_IDENTITY_SCOPE_GROUP, group_id, identity_id)
    return {"identity": _project_identity(identity, role, group, settings, available=available)}, 200


def create_group_identity(user_id, group_id, body, *, user_info=None):
    group, role, settings, available = require_group_identity_write_context(
        user_id, group_id, "create", user_info=user_info
    )
    payload = _validate_write_body(body)
    created = create_workspace_identity(WORKSPACE_IDENTITY_SCOPE_GROUP, group_id, payload, user_id)
    # create_workspace_identity returns the local document without a Cosmos etag;
    # re-read so the response carries the etag the client needs for conditional edits.
    stored = get_workspace_identity(WORKSPACE_IDENTITY_SCOPE_GROUP, group_id, created["identity_id"])
    return {"identity": _project_identity(stored, role, group, settings, available=available)}, 201


def update_group_identity(user_id, group_id, identity_id, body, *, user_info=None):
    group, role, settings, available = require_group_identity_write_context(
        user_id, group_id, "edit", user_info=user_info
    )
    _validate_identifier(identity_id, "identity identifier")
    expected_etag = _require_expected_etag(body)
    payload = _validate_write_body(body)
    stored = update_workspace_identity_conditional(
        WORKSPACE_IDENTITY_SCOPE_GROUP, group_id, identity_id, payload, user_id, expected_etag
    )
    return {"identity": _project_identity(stored, role, group, settings, available=available)}, 200


def delete_group_identity(user_id, group_id, identity_id, body, *, user_info=None):
    require_group_identity_write_context(user_id, group_id, "delete", user_info=user_info)
    _validate_identifier(identity_id, "identity identifier")
    expected_etag = _require_expected_etag(body)
    if set(body) - {"expected_etag"}:
        raise GroupIdentityError("Unknown fields are not supported.", 400)
    references = _identity_references(group_id, identity_id)
    if references:
        log_workspace_identity_reference_block(
            WORKSPACE_IDENTITY_SCOPE_GROUP, group_id, identity_id, len(references)
        )
        raise GroupIdentityInUse(references)
    delete_workspace_identity_conditional(
        WORKSPACE_IDENTITY_SCOPE_GROUP, group_id, identity_id, user_id, expected_etag
    )
    return {"success": True}, 200
