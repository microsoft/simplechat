# functions_public_file_source_access.py
"""Authorization, projection and orchestration for immutable-target public file sources.

Version: 0.261.179
Implemented in: 0.261.179

The active-scoped legacy routes (``/api/file-sync/public/sources``) resolve
whatever public workspace the account has selected and are left exactly as they
are. This module backs the new ``/api/public-workspaces/<workspace_id>/file-sources``
family, where the workspace is named in the path and every request reauthorizes
role and status independently. An older server lacking this family 404s rather
than silently editing the account's selected workspace.

Public file sources are a manager-only surface for reads and writes. There is one
availability predicate, :func:`public_file_sources_available`, and one management
projection, both computed fresh on every request so a stored ``source_actions``
can never be served. Writes are conditional on the caller's
``expected_config_revision`` so a stale editor cannot overwrite a concurrent
manager edit, and a delete refuses while a run is queued or running.

This mirrors ``functions_group_file_source_access.py`` with public-scope
differences: role and status resolve from the public workspace document (via
``assert_public_workspace_role``) rather than group membership, and the readable
status gate is an **explicit** allowlist so an unrecognized status is denied
rather than treated as active (never through
``check_public_workspace_status_allows_operation``). The delete drives the same
shared File Sync deletion path, which for public scope removes each synced
document through the public document deletion path and its conversation-linked
guard, never a raw container delete.
"""

import re

from werkzeug.exceptions import HTTPException

from functions_file_sync import (
    FILE_SYNC_SCOPE_PUBLIC,
    FileSyncConfigConflict,
    FileSyncDeleteIncomplete,
    FileSyncPublicValidationError,
    FileSyncSourceBusy,
    FileSyncWriteConflict,
    assert_public_workspace_role,
    browse_file_sync_source_path,
    build_file_sync_source_options,
    compute_file_sync_config_revision,
    create_file_sync_source,
    delete_file_sync_source,
    get_authorized_sync_source,
    is_file_sync_source_type_visible,
    list_file_sync_runs,
    list_file_sync_sources,
    queue_file_sync_source_run,
    sanitize_file_sync_run,
    sanitize_file_sync_source,
    set_file_sync_path_ignored,
    test_file_sync_source_connection,
    update_file_sync_source,
)
from functions_public_file_source_policy import (
    PUBLIC_FILE_SOURCE_MANAGER_ROLES,
    PUBLIC_FILE_SOURCE_READ_STATUSES,
    public_file_source_actions,
    public_file_source_management_operations,
    public_file_sources_available,
)
from functions_public_workspaces import (
    find_public_workspace_by_id,
    get_user_role_in_public_workspace,
)
from functions_settings import get_settings


INVALID_PUBLIC_FILE_SOURCE_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")


class PublicFileSourceError(HTTPException):
    """A stable, non-sensitive failure at a public file source boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_PUBLIC_FILE_SOURCE_ID.search(value)
    ):
        raise PublicFileSourceError(f"Invalid {label}.", 400)


def require_public_file_source_read_context(user_id, workspace_id, *, user_info=None):
    """Resolve (workspace, role, settings, available) for a reader, or raise.

    Reads are manager-only: an ordinary ``User`` cannot list public file sources.
    Unknown workspace is 404, ineligible role is 403, and a status outside the
    browsable allowlist is 403 -- an unrecognized status is treated as
    unavailable, never as active. The one availability predicate gates the whole
    surface (File Sync enabled for this workspace), so a tenant with it off offers
    nothing and every route refuses, reads included.
    """
    _validate_identifier(workspace_id, "public workspace identifier")
    if not user_id:
        raise PublicFileSourceError("User not authenticated.", 401)
    try:
        assert_public_workspace_role(
            user_id, workspace_id, allowed_roles=PUBLIC_FILE_SOURCE_MANAGER_ROLES
        )
    except LookupError as error:
        raise PublicFileSourceError("The selected public workspace was not found.", 404) from error
    except PermissionError as error:
        raise PublicFileSourceError("You do not have access to the selected public workspace.", 403) from error
    workspace = find_public_workspace_by_id(workspace_id)
    if not workspace:
        raise PublicFileSourceError("The selected public workspace was not found.", 404)
    role = get_user_role_in_public_workspace(workspace, user_id)
    if role not in PUBLIC_FILE_SOURCE_MANAGER_ROLES:
        raise PublicFileSourceError("You do not have access to the selected public workspace.", 403)
    if workspace.get("status", "active") not in PUBLIC_FILE_SOURCE_READ_STATUSES:
        raise PublicFileSourceError("File sources are unavailable for this workspace's current status.", 403)
    settings = get_settings()
    available, reason = public_file_sources_available(settings, workspace_id, user_info=user_info)
    if not available:
        raise PublicFileSourceError(reason, 403)
    return workspace, role, settings, available


def require_public_file_source_write_context(user_id, workspace_id, operation, *, user_info=None):
    """Resolve (workspace, role, settings, available) for a writer, or raise.

    Reuses the read context (manager-only, browsable status, surface available)
    then requires the operation to be offered by the workspace's current status,
    which the management projection permits only while the workspace is
    ``active``. A saved or unsaved test and a browse both take this path with
    ``test``, so a caller who is not a manager of an active workspace can never
    pair a destination with a stored identity's credentials.
    """
    workspace, role, settings, available = require_public_file_source_read_context(
        user_id, workspace_id, user_info=user_info
    )
    if operation not in public_file_source_management_operations(role, workspace, settings, available=available):
        raise PublicFileSourceError("This operation is unavailable for the selected public workspace.", 403)
    return workspace, role, settings, available


def _project_source(source, role, workspace, settings, *, available):
    """Sanitize one stored source and attach its config revision and per-item actions.

    :func:`sanitize_file_sync_source` drops the ``auth`` secrets. ``config_revision``
    is computed fresh over the editable projection, and ``source_actions`` fresh
    from policy, so a stored value can never be served and a client always sees
    exactly what the current caller and workspace status allow.
    """
    projected = sanitize_file_sync_source(source)
    for internal_field in ("_etag", "_rid", "_self", "_attachments", "_ts"):
        projected.pop(internal_field, None)
    projected["config_revision"] = compute_file_sync_config_revision(source)
    projected["source_actions"] = public_file_source_actions(role, workspace, settings, available=available)
    return projected


def _require_body(body):
    if not isinstance(body, dict):
        raise PublicFileSourceError("A JSON object is required for this action.", 400)
    return body


def _require_expected_config_revision(body):
    _require_body(body)
    expected = body.get("expected_config_revision")
    if not isinstance(expected, str) or not expected.strip():
        raise PublicFileSourceError("An expected_config_revision is required for this action.", 400)
    return expected.strip()


def _assert_source_type_visible(payload, settings):
    """Refuse a create, unsaved test or unsaved browse of a hidden source type.

    Mirrors the group ``_assert_source_type_visible`` so the native routes honour
    the same admin visibility gate.
    """
    source_type = str((payload or {}).get("source_type") or "").strip().lower() or "smb"
    if not is_file_sync_source_type_visible(settings, source_type):
        raise PermissionError("This File Sync source type is not available")


def public_file_source_error_response(exc):
    """Map public-boundary and storage-layer errors to stable HTTP responses.

    Following the group file source mapping but never returning ``str(exc)``: a
    500 in particular carries only a generic message so a raw exception can never
    reach a client. The M5B conflicts carry their reviewed text and stable
    ``error_code`` so the frontend can keep the draft.
    """
    from flask import jsonify

    def _json(payload, status):
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        return response, status

    def _partial_fields(error):
        # A delete that already removed some associated documents attaches the
        # counts, so a refusal after that point reports the partial outcome honestly.
        result = getattr(error, "delete_result", None)
        if result is None:
            return {}
        return {"partial": bool(getattr(error, "partial", False)), "delete_result": dict(result)}

    if isinstance(exc, PublicFileSourceError):
        return _json({"error": exc.description}, exc.code)
    if isinstance(exc, FileSyncDeleteIncomplete):
        return _json(
            {
                "error": exc.public_message,
                "error_code": "delete_incomplete",
                "partial": exc.delete_result.get("documents_deleted", 0) > 0,
                "delete_result": dict(exc.delete_result),
            },
            409,
        )
    if isinstance(exc, FileSyncSourceBusy):
        partial = _partial_fields(exc)
        message = (
            "The source's documents were deleted, but a sync started before the source could be removed. "
            "Wait for it to finish, then delete the source again."
            if partial
            else "Wait for the running sync to finish, then delete the source."
        )
        return _json({"error": message, "error_code": "source_busy", **partial}, 409)
    if isinstance(exc, FileSyncConfigConflict):
        partial = _partial_fields(exc)
        message = (
            "The source's documents were deleted, but the source changed before it could be removed. "
            "Reload it and try again."
            if partial
            else "This file source changed while it was being saved. Reload it and try again."
        )
        return _json({"error": message, "error_code": "config_conflict", **partial}, 409)
    if isinstance(exc, FileSyncWriteConflict):
        partial = _partial_fields(exc)
        return _json(
            {"error": "This file source changed while it was being saved. Reload it and try again.", "error_code": "write_conflict", **partial},
            409,
        )
    if isinstance(exc, FileSyncPublicValidationError):
        return _json({"error": exc.public_message}, 400)
    if isinstance(exc, LookupError):
        partial = _partial_fields(exc)
        message = (
            "The source was already removed. Its documents were deleted."
            if partial
            else "The requested File Sync resource was not found."
        )
        return _json({"error": message, **partial}, 404)
    if isinstance(exc, PermissionError):
        return _json({"error": "You do not have permission to perform this File Sync operation."}, 403)
    if isinstance(exc, ValueError):
        return _json(
            {"error": "The File Sync request could not be completed. Verify the source configuration and try again."},
            400,
        )
    return _json({"error": "An unexpected error occurred while processing the File Sync request."}, 500)


def list_public_file_sources(user_id, workspace_id, *, user_info=None):
    workspace, role, settings, available = require_public_file_source_read_context(
        user_id, workspace_id, user_info=user_info
    )
    sources = [
        _project_source(source, role, workspace, settings, available=available)
        for source in list_file_sync_sources(FILE_SYNC_SCOPE_PUBLIC, workspace_id)
    ]
    return {
        "file_sources": sources,
        "file_source_management": {
            "schema_version": 1,
            "operations": public_file_source_management_operations(role, workspace, settings, available=available),
        },
    }, 200


def get_public_file_source(user_id, workspace_id, source_id, *, user_info=None):
    workspace, role, settings, available = require_public_file_source_read_context(
        user_id, workspace_id, user_info=user_info
    )
    _validate_identifier(source_id, "source identifier")
    source = get_authorized_sync_source(FILE_SYNC_SCOPE_PUBLIC, source_id, user_id, scope_id=workspace_id)
    return {"file_source": _project_source(source, role, workspace, settings, available=available)}, 200


def create_public_file_source(user_id, workspace_id, body, *, user_info=None):
    workspace, role, settings, available = require_public_file_source_write_context(
        user_id, workspace_id, "create", user_info=user_info
    )
    payload = _require_body(body)
    _assert_source_type_visible(payload, settings)
    source = create_file_sync_source(
        FILE_SYNC_SCOPE_PUBLIC, workspace_id, payload, user_id, stage_secrets=True
    )
    return {"file_source": _project_source(source, role, workspace, settings, available=available)}, 201


def update_public_file_source(user_id, workspace_id, source_id, body, *, user_info=None):
    workspace, role, settings, available = require_public_file_source_write_context(
        user_id, workspace_id, "edit", user_info=user_info
    )
    _validate_identifier(source_id, "source identifier")
    payload = dict(_require_body(body))
    expected_config_revision = _require_expected_config_revision(payload)
    payload.pop("expected_config_revision", None)
    source = update_file_sync_source(
        FILE_SYNC_SCOPE_PUBLIC,
        workspace_id,
        source_id,
        payload,
        user_id,
        expected_config_revision=expected_config_revision,
        stage_secrets=True,
    )
    return {"file_source": _project_source(source, role, workspace, settings, available=available)}, 200


def delete_public_file_source(user_id, workspace_id, source_id, body, *, user_info=None):
    require_public_file_source_write_context(user_id, workspace_id, "delete", user_info=user_info)
    _validate_identifier(source_id, "source identifier")
    body = _require_body(body)
    expected_config_revision = _require_expected_config_revision(body)
    if "delete_associated_files" not in body or not isinstance(body.get("delete_associated_files"), bool):
        raise PublicFileSourceError("delete_associated_files must be provided as true or false.", 400)
    if set(body) - {"expected_config_revision", "delete_associated_files"}:
        raise PublicFileSourceError("Unknown fields are not supported.", 400)
    delete_result = delete_file_sync_source(
        FILE_SYNC_SCOPE_PUBLIC,
        workspace_id,
        source_id,
        user_id,
        delete_associated_files=bool(body["delete_associated_files"]),
        expected_config_revision=expected_config_revision,
        refuse_active_run=True,
    )
    return {"success": True, "delete_result": delete_result}, 200


def sync_public_file_source(user_id, workspace_id, source_id, *, user_info=None):
    require_public_file_source_write_context(user_id, workspace_id, "sync", user_info=user_info)
    _validate_identifier(source_id, "source identifier")
    source = get_authorized_sync_source(FILE_SYNC_SCOPE_PUBLIC, source_id, user_id, scope_id=workspace_id)
    run = queue_file_sync_source_run(source, triggered_by=user_id, trigger="manual")
    return {"run": sanitize_file_sync_run(run)}, 202


def list_public_file_source_runs(user_id, workspace_id, source_id, *, user_info=None):
    require_public_file_source_read_context(user_id, workspace_id, user_info=user_info)
    _validate_identifier(source_id, "source identifier")
    get_authorized_sync_source(FILE_SYNC_SCOPE_PUBLIC, source_id, user_id, scope_id=workspace_id)
    runs = [sanitize_file_sync_run(run) for run in list_file_sync_runs(FILE_SYNC_SCOPE_PUBLIC, source_id)]
    return {"runs": runs}, 200


def ignore_public_file_source_path(user_id, workspace_id, source_id, body, *, user_info=None):
    require_public_file_source_write_context(user_id, workspace_id, "edit", user_info=user_info)
    _validate_identifier(source_id, "source identifier")
    payload = _require_body(body)
    source = get_authorized_sync_source(FILE_SYNC_SCOPE_PUBLIC, source_id, user_id, scope_id=workspace_id)
    item = set_file_sync_path_ignored(
        source, payload.get("remote_path"), payload.get("ignored", True), user_id
    )
    return {"item": item}, 200


def test_public_file_source_connection(user_id, workspace_id, body, *, source_id=None, user_info=None):
    workspace, role, settings, available = require_public_file_source_write_context(
        user_id, workspace_id, "test", user_info=user_info
    )
    payload = _require_body(body)
    if source_id:
        _validate_identifier(source_id, "source identifier")
    else:
        _assert_source_type_visible(payload, settings)
    result = test_file_sync_source_connection(
        FILE_SYNC_SCOPE_PUBLIC, workspace_id, payload, user_id, source_id=source_id
    )
    return {"connection": result}, 200


def browse_public_file_source(user_id, workspace_id, body, *, source_id=None, user_info=None):
    workspace, role, settings, available = require_public_file_source_write_context(
        user_id, workspace_id, "test", user_info=user_info
    )
    payload = _require_body(body)
    if source_id:
        _validate_identifier(source_id, "source identifier")
    else:
        _assert_source_type_visible(payload, settings)
    result = browse_file_sync_source_path(
        FILE_SYNC_SCOPE_PUBLIC, workspace_id, payload, user_id, source_id=source_id
    )
    return {"browse": result}, 200


def get_public_file_source_options(user_id, workspace_id, *, user_info=None):
    workspace, role, settings, available = require_public_file_source_read_context(
        user_id, workspace_id, user_info=user_info
    )
    return build_file_sync_source_options(FILE_SYNC_SCOPE_PUBLIC, workspace_id, settings), 200
