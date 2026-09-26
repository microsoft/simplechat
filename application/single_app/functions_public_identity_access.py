# functions_public_identity_access.py
"""Authorization, projection and orchestration for immutable-target public identities.

Version: 0.261.182
Implemented in: 0.261.182

The active-scoped legacy routes (``/api/workspace-identities/public/<id>/...``)
resolve the workspace named in their path and are left exactly as they are. This
module backs the new ``/api/public-workspaces/<workspace_id>/identities`` family,
which matches the group ``/api/groups/<group_id>/identities`` pattern: the
workspace is named in the path and every request reauthorizes role and status
independently. An older server lacking this family 404s rather than editing an
unexpected workspace.

Public identities are a manager-only surface for reads and writes. There is one
availability predicate, :func:`public_identities_available`, and one management
projection, both computed fresh on every request so a stored ``identity_actions``
can never be served. Writes are conditional on the caller's ``expected_etag`` so
a stale editor cannot overwrite a concurrent manager edit, and a delete refuses
while the identity is still in use, listing the File Sync references.

This mirrors ``functions_group_identity_access.py`` with three public-scope
differences: role and status are resolved from the public workspace document (via
``assert_public_workspace_role``) rather than group membership; the readable
status gate is an **explicit** allowlist so an unrecognized status is denied
rather than treated as active (never through
``check_public_workspace_status_allows_operation``); and a public workspace has
no Semantic Kernel actions, so the only references that can block a delete are
File Sync sources.
"""

import re

from werkzeug.exceptions import HTTPException

from functions_file_sync import (
    assert_public_workspace_role,
    list_file_sync_sources,
)
from functions_public_identity_policy import (
    PUBLIC_IDENTITY_MANAGER_ROLES,
    PUBLIC_IDENTITY_READ_STATUSES,
    public_identities_available,
    public_identity_actions,
    public_identity_management_operations,
)
from functions_public_workspaces import (
    find_public_workspace_by_id,
    get_user_role_in_public_workspace,
)
from functions_settings import get_settings
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_PUBLIC,
    WorkspaceIdentityConflict,
    WorkspaceIdentityValidationError,
    create_workspace_identity,
    delete_workspace_identity_conditional,
    get_workspace_identity,
    list_workspace_identities,
    log_workspace_identity_reference_block,
    normalize_identity_supported_source_types,
    normalize_identity_usage_contexts,
    sanitize_workspace_identity,
    update_workspace_identity_conditional,
)


INVALID_PUBLIC_IDENTITY_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")
# A client sends only these top-level fields. ``auth`` is refused so a caller can
# never smuggle a Key Vault reference; credentials arrive under ``credentials``.
_ALLOWED_IDENTITY_FIELDS = frozenset(
    {"name", "description", "provider", "source_type", "usage_contexts", "supported_source_types", "metadata", "credentials"}
)


class PublicIdentityError(HTTPException):
    """A stable, non-sensitive failure at a public identity boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


class PublicIdentityInUse(Exception):
    """A delete was refused because the identity is still referenced in this workspace."""

    def __init__(self, references):
        super().__init__("Workspace identity is still in use.")
        self.references = references


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_PUBLIC_IDENTITY_ID.search(value)
    ):
        raise PublicIdentityError(f"Invalid {label}.", 400)


def require_public_identity_read_context(user_id, workspace_id, *, user_info=None):
    """Resolve (workspace, role, settings, available) for a reader, or raise.

    Reads are manager-only: an ordinary ``User`` cannot list public identities.
    Unknown workspace is 404, ineligible role is 403, and a status outside the
    browsable allowlist is 403 -- an unrecognized status is treated as
    unavailable, never as active. The one availability predicate (File Sync for
    this workspace) gates the whole surface, so a tenant without File Sync offers
    nothing and every route refuses, reads included.
    """
    _validate_identifier(workspace_id, "public workspace identifier")
    if not user_id:
        raise PublicIdentityError("User not authenticated.", 401)
    try:
        assert_public_workspace_role(
            user_id, workspace_id, allowed_roles=PUBLIC_IDENTITY_MANAGER_ROLES
        )
    except LookupError as error:
        raise PublicIdentityError("The selected public workspace was not found.", 404) from error
    except PermissionError as error:
        raise PublicIdentityError("You do not have access to the selected public workspace.", 403) from error
    workspace = find_public_workspace_by_id(workspace_id)
    if not workspace:
        raise PublicIdentityError("The selected public workspace was not found.", 404)
    role = get_user_role_in_public_workspace(workspace, user_id)
    if role not in PUBLIC_IDENTITY_MANAGER_ROLES:
        raise PublicIdentityError("You do not have access to the selected public workspace.", 403)
    if workspace.get("status", "active") not in PUBLIC_IDENTITY_READ_STATUSES:
        raise PublicIdentityError("Identities are unavailable for this workspace's current status.", 403)
    settings = get_settings()
    available, reason = public_identities_available(settings, workspace_id, user_info=user_info)
    if not available:
        raise PublicIdentityError(reason, 403)
    return workspace, role, settings, available


def require_public_identity_write_context(user_id, workspace_id, operation, *, user_info=None):
    """Resolve (workspace, role, settings, available) for a writer, or raise.

    Reuses the read context (manager-only, browsable status, surface available)
    then requires the operation to be offered by the workspace's current status,
    which the management projection permits only while the workspace is
    ``active``.
    """
    workspace, role, settings, available = require_public_identity_read_context(
        user_id, workspace_id, user_info=user_info
    )
    if operation not in public_identity_management_operations(role, workspace, settings, available=available):
        raise PublicIdentityError("This operation is unavailable for the selected public workspace.", 403)
    return workspace, role, settings, available


def _project_identity(identity, role, workspace, settings, *, available):
    """Sanitize one stored identity and attach the fresh etag and per-item actions.

    ``usage_contexts`` and ``supported_source_types`` are both re-normalized
    through their shared helpers so every response advertises exactly what the
    save-time gate would accept: an older record that omits a field or holds an
    alias still reports its canonical contexts and source types, so a client
    filtering on a source type never hides an identity the server honours.
    """
    projected = sanitize_workspace_identity(identity)
    projected["usage_contexts"] = normalize_identity_usage_contexts(identity)
    projected["supported_source_types"] = normalize_identity_supported_source_types(identity)
    projected["etag"] = identity.get("_etag", "")
    projected["identity_actions"] = public_identity_actions(role, workspace, settings, available=available)
    return projected


def _validate_write_body(body):
    """Reject unknown top-level fields (including ``auth``) on a create or update."""
    if not isinstance(body, dict):
        raise PublicIdentityError("A JSON object is required for this action.", 400)
    unknown = set(body) - _ALLOWED_IDENTITY_FIELDS
    unknown.discard("expected_etag")
    if unknown:
        raise PublicIdentityError("Unknown fields are not supported.", 400)
    return {key: value for key, value in body.items() if key in _ALLOWED_IDENTITY_FIELDS}


def _require_expected_etag(body):
    if not isinstance(body, dict):
        raise PublicIdentityError("A JSON object is required for this action.", 400)
    expected = body.get("expected_etag")
    if not isinstance(expected, str) or not expected.strip():
        raise PublicIdentityError("An expected_etag is required for this action.", 400)
    return expected.strip()


def _identity_references(workspace_id, identity_id):
    """Every File Sync source in this workspace that still references the identity.

    A public workspace has no Semantic Kernel actions, so File Sync sources are
    the only thing that can block a delete.
    """
    references = []
    for source in list_file_sync_sources(WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id):
        if source.get("identity_id") == identity_id:
            references.append({
                "kind": "file_source",
                "id": str(source.get("id") or source.get("source_id") or ""),
                "name": str(source.get("name") or source.get("display_name") or ""),
            })
    return references


def public_identity_error_response(exc):
    """Map public-boundary and storage-layer errors to stable HTTP responses.

    Never returns ``str(exc)``: a 500 in particular carries only a generic
    message so a raw exception can never reach a client. Validation failures
    answer with one stable 400.
    """
    from flask import jsonify

    def _json(payload, status):
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        return response, status

    if isinstance(exc, PublicIdentityInUse):
        return _json(
            {
                "error": "This workspace identity is still in use.",
                "error_code": "identity_in_use",
                "references": exc.references,
            },
            409,
        )
    if isinstance(exc, PublicIdentityError):
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
    if isinstance(exc, WorkspaceIdentityValidationError):
        return _json({"error": exc.public_message}, 400)
    if isinstance(exc, ValueError):
        return _json({"error": "The workspace identity details are not valid."}, 400)
    return _json({"error": "Unable to complete the workspace identity request."}, 500)


def list_public_identities(user_id, workspace_id, *, user_info=None):
    workspace, role, settings, available = require_public_identity_read_context(
        user_id, workspace_id, user_info=user_info
    )
    identities = [
        _project_identity(identity, role, workspace, settings, available=available)
        for identity in list_workspace_identities(WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id)
    ]
    return {
        "identities": identities,
        "identity_management": {
            "schema_version": 1,
            "operations": public_identity_management_operations(role, workspace, settings, available=available),
        },
    }, 200


def get_public_identity(user_id, workspace_id, identity_id, *, user_info=None):
    workspace, role, settings, available = require_public_identity_read_context(
        user_id, workspace_id, user_info=user_info
    )
    _validate_identifier(identity_id, "identity identifier")
    identity = get_workspace_identity(WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id, identity_id)
    return {"identity": _project_identity(identity, role, workspace, settings, available=available)}, 200


def create_public_identity(user_id, workspace_id, body, *, user_info=None):
    workspace, role, settings, available = require_public_identity_write_context(
        user_id, workspace_id, "create", user_info=user_info
    )
    payload = _validate_write_body(body)
    created = create_workspace_identity(
        WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id, payload, user_id, stage_secrets=True
    )
    # create_workspace_identity returns the local document without a Cosmos etag;
    # re-read so the response carries the etag the client needs for conditional edits.
    stored = get_workspace_identity(WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id, created["identity_id"])
    return {"identity": _project_identity(stored, role, workspace, settings, available=available)}, 201


def update_public_identity(user_id, workspace_id, identity_id, body, *, user_info=None):
    workspace, role, settings, available = require_public_identity_write_context(
        user_id, workspace_id, "edit", user_info=user_info
    )
    _validate_identifier(identity_id, "identity identifier")
    expected_etag = _require_expected_etag(body)
    payload = _validate_write_body(body)
    stored = update_workspace_identity_conditional(
        WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id, identity_id, payload, user_id, expected_etag
    )
    return {"identity": _project_identity(stored, role, workspace, settings, available=available)}, 200


def delete_public_identity(user_id, workspace_id, identity_id, body, *, user_info=None):
    require_public_identity_write_context(user_id, workspace_id, "delete", user_info=user_info)
    _validate_identifier(identity_id, "identity identifier")
    expected_etag = _require_expected_etag(body)
    if set(body) - {"expected_etag"}:
        raise PublicIdentityError("Unknown fields are not supported.", 400)
    references = _identity_references(workspace_id, identity_id)
    if references:
        log_workspace_identity_reference_block(
            WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id, identity_id, len(references)
        )
        raise PublicIdentityInUse(references)
    delete_workspace_identity_conditional(
        WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id, identity_id, user_id, expected_etag
    )
    return {"success": True}, 200
