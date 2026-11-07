# functions_group_file_source_access.py
"""Authorization, projection and orchestration for immutable-target group file sources.

The active-scoped legacy routes (``/api/file-sync/group/sources``) resolve
whatever group the account has selected and are left exactly as they are. This
module backs the new ``/api/groups/<group_id>/file-sources`` family, where the
group is named in the path and every request reauthorizes membership, role and
group status independently. An older server lacking this family 404s rather than
silently editing the account's selected group.

Group file sources are a manager-only surface for reads and writes. There is one
availability predicate, :func:`group_file_sources_available`, and one management
projection, both computed fresh on every request so a stored ``source_actions``
can never be served. Writes are conditional on the caller's
``expected_config_revision`` so a stale editor cannot overwrite a concurrent
manager edit, and a delete refuses while a run is queued or running.
"""

import re

from werkzeug.exceptions import HTTPException

from functions_file_sync import (
    FILE_SYNC_SCOPE_GROUP,
    FileSyncConfigConflict,
    FileSyncDeleteIncomplete,
    FileSyncPublicValidationError,
    FileSyncSourceBusy,
    FileSyncWriteConflict,
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
from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_user_role_in_group,
)
from functions_group_file_source_policy import (
    GROUP_FILE_SOURCE_MANAGER_ROLES,
    GROUP_FILE_SOURCE_READ_STATUSES,
    group_file_source_actions,
    group_file_source_management_operations,
    group_file_sources_available,
)
from functions_settings import get_settings


INVALID_GROUP_FILE_SOURCE_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")


class GroupFileSourceError(HTTPException):
    """A stable, non-sensitive failure at a group file source boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_GROUP_FILE_SOURCE_ID.search(value)
    ):
        raise GroupFileSourceError(f"Invalid {label}.", 400)


def require_group_file_source_read_context(user_id, group_id, *, user_info=None):
    """Resolve (group, role, settings, available) for a reader, or raise.

    Reads are manager-only: ordinary members cannot list group file sources.
    Unknown group is 404, ineligible role is 403, and a status outside the
    browsable set is 403 — an unrecognized status is treated as unavailable,
    never as active. The one availability predicate gates the whole surface
    (File Sync enabled for this group), so a tenant with it off offers nothing
    and every route refuses, reads included.
    """
    _validate_identifier(group_id, "group identifier")
    if not user_id:
        raise GroupFileSourceError("User not authenticated.", 401)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_FILE_SOURCE_MANAGER_ROLES)
    except LookupError as error:
        raise GroupFileSourceError("The selected group was not found.", 404) from error
    except PermissionError as error:
        raise GroupFileSourceError("You do not have access to the selected group.", 403) from error
    group = find_group_by_id(group_id)
    if not group:
        raise GroupFileSourceError("The selected group was not found.", 404)
    role = get_user_role_in_group(group, user_id)
    if role not in GROUP_FILE_SOURCE_MANAGER_ROLES:
        raise GroupFileSourceError("You do not have access to the selected group.", 403)
    allowed, _reason = check_group_status_allows_operation(group, "view")
    if not allowed or group.get("status", "active") not in GROUP_FILE_SOURCE_READ_STATUSES:
        raise GroupFileSourceError("File sources are unavailable for this group's current status.", 403)
    settings = get_settings()
    available, reason = group_file_sources_available(settings, group_id, user_info=user_info)
    if not available:
        raise GroupFileSourceError(reason, 403)
    return group, role, settings, available


def require_group_file_source_write_context(user_id, group_id, operation, *, user_info=None):
    """Resolve (group, role, settings, available) for a writer, or raise.

    Reuses the read context (manager-only, browsable status, surface available)
    then requires the operation to be offered by the group's current status,
    which the management projection permits only while the group is ``active``.
    A saved or unsaved test and a browse both take this path with ``test``, so a
    caller who is not a manager of an active group can never pair a destination
    with a stored identity's credentials (the M4 §9.1 lesson).
    """
    group, role, settings, available = require_group_file_source_read_context(
        user_id, group_id, user_info=user_info
    )
    if operation not in group_file_source_management_operations(role, group, settings, available=available):
        raise GroupFileSourceError("This operation is unavailable for the selected group.", 403)
    return group, role, settings, available


def _project_source(source, role, group, settings, *, available):
    """Sanitize one stored source and attach its config revision and per-item actions.

    :func:`sanitize_file_sync_source` drops the ``auth`` secrets. ``config_revision``
    is computed fresh over the editable projection, and ``source_actions`` fresh
    from policy, so a stored value can never be served and a client always sees
    exactly what the current caller and group status allow.
    """
    projected = sanitize_file_sync_source(source)
    for internal_field in ("_etag", "_rid", "_self", "_attachments", "_ts"):
        projected.pop(internal_field, None)
    projected["config_revision"] = compute_file_sync_config_revision(source)
    projected["source_actions"] = group_file_source_actions(role, group, settings, available=available)
    return projected


def _require_body(body):
    if not isinstance(body, dict):
        raise GroupFileSourceError("A JSON object is required for this action.", 400)
    return body


def _require_expected_config_revision(body):
    _require_body(body)
    expected = body.get("expected_config_revision")
    if not isinstance(expected, str) or not expected.strip():
        raise GroupFileSourceError("An expected_config_revision is required for this action.", 400)
    return expected.strip()


def _assert_source_type_visible(payload, settings):
    """Refuse a create, unsaved test or unsaved browse of a hidden source type.

    Mirrors the legacy ``_assert_new_source_type_visible`` so the native routes
    honour the same admin visibility gate.
    """
    source_type = str((payload or {}).get("source_type") or "").strip().lower() or "smb"
    if not is_file_sync_source_type_visible(settings, source_type):
        raise PermissionError("This File Sync source type is not available")


def group_file_source_error_response(exc):
    """Map group-boundary and storage-layer errors to stable HTTP responses.

    Following ``route_backend_file_sync._map_exception`` semantics but never
    returning ``str(exc)``: a 500 in particular carries only a generic message so
    a raw exception can never reach a client. The two M5B conflicts carry their
    reviewed text and stable ``error_code`` so the frontend can keep the draft.
    """
    from flask import jsonify

    def _json(payload, status):
        response = jsonify(payload)
        response.headers["Cache-Control"] = "no-store"
        return response, status

    def _partial_fields(error):
        # A native delete that already removed some associated documents attaches the
        # counts, so a refusal after that point reports the partial outcome honestly.
        result = getattr(error, "delete_result", None)
        if result is None:
            return {}
        return {"partial": bool(getattr(error, "partial", False)), "delete_result": dict(result)}

    if isinstance(exc, GroupFileSourceError):
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


def list_group_file_sources(user_id, group_id, *, user_info=None):
    group, role, settings, available = require_group_file_source_read_context(
        user_id, group_id, user_info=user_info
    )
    sources = [
        _project_source(source, role, group, settings, available=available)
        for source in list_file_sync_sources(FILE_SYNC_SCOPE_GROUP, group_id)
    ]
    return {
        "file_sources": sources,
        "file_source_management": {
            "schema_version": 1,
            "operations": group_file_source_management_operations(role, group, settings, available=available),
        },
    }, 200


def get_group_file_source(user_id, group_id, source_id, *, user_info=None):
    group, role, settings, available = require_group_file_source_read_context(
        user_id, group_id, user_info=user_info
    )
    _validate_identifier(source_id, "source identifier")
    source = get_authorized_sync_source(FILE_SYNC_SCOPE_GROUP, source_id, user_id, scope_id=group_id)
    return {"file_source": _project_source(source, role, group, settings, available=available)}, 200


def create_group_file_source(user_id, group_id, body, *, user_info=None):
    group, role, settings, available = require_group_file_source_write_context(
        user_id, group_id, "create", user_info=user_info
    )
    payload = _require_body(body)
    _assert_source_type_visible(payload, settings)
    source = create_file_sync_source(
        FILE_SYNC_SCOPE_GROUP, group_id, payload, user_id, stage_secrets=True
    )
    return {"file_source": _project_source(source, role, group, settings, available=available)}, 201


def update_group_file_source(user_id, group_id, source_id, body, *, user_info=None):
    group, role, settings, available = require_group_file_source_write_context(
        user_id, group_id, "edit", user_info=user_info
    )
    _validate_identifier(source_id, "source identifier")
    payload = dict(_require_body(body))
    expected_config_revision = _require_expected_config_revision(payload)
    payload.pop("expected_config_revision", None)
    source = update_file_sync_source(
        FILE_SYNC_SCOPE_GROUP,
        group_id,
        source_id,
        payload,
        user_id,
        expected_config_revision=expected_config_revision,
        stage_secrets=True,
    )
    return {"file_source": _project_source(source, role, group, settings, available=available)}, 200


def delete_group_file_source(user_id, group_id, source_id, body, *, user_info=None):
    require_group_file_source_write_context(user_id, group_id, "delete", user_info=user_info)
    _validate_identifier(source_id, "source identifier")
    body = _require_body(body)
    expected_config_revision = _require_expected_config_revision(body)
    if "delete_associated_files" not in body or not isinstance(body.get("delete_associated_files"), bool):
        raise GroupFileSourceError("delete_associated_files must be provided as true or false.", 400)
    if set(body) - {"expected_config_revision", "delete_associated_files"}:
        raise GroupFileSourceError("Unknown fields are not supported.", 400)
    delete_result = delete_file_sync_source(
        FILE_SYNC_SCOPE_GROUP,
        group_id,
        source_id,
        user_id,
        delete_associated_files=bool(body["delete_associated_files"]),
        expected_config_revision=expected_config_revision,
        refuse_active_run=True,
    )
    return {"success": True, "delete_result": delete_result}, 200


def sync_group_file_source(user_id, group_id, source_id, *, user_info=None):
    require_group_file_source_write_context(user_id, group_id, "sync", user_info=user_info)
    _validate_identifier(source_id, "source identifier")
    source = get_authorized_sync_source(FILE_SYNC_SCOPE_GROUP, source_id, user_id, scope_id=group_id)
    run = queue_file_sync_source_run(source, triggered_by=user_id, trigger="manual")
    return {"run": sanitize_file_sync_run(run)}, 202


def list_group_file_source_runs(user_id, group_id, source_id, *, user_info=None):
    require_group_file_source_read_context(user_id, group_id, user_info=user_info)
    _validate_identifier(source_id, "source identifier")
    get_authorized_sync_source(FILE_SYNC_SCOPE_GROUP, source_id, user_id, scope_id=group_id)
    runs = [sanitize_file_sync_run(run) for run in list_file_sync_runs(FILE_SYNC_SCOPE_GROUP, source_id)]
    return {"runs": runs}, 200


def ignore_group_file_source_path(user_id, group_id, source_id, body, *, user_info=None):
    require_group_file_source_write_context(user_id, group_id, "edit", user_info=user_info)
    _validate_identifier(source_id, "source identifier")
    payload = _require_body(body)
    source = get_authorized_sync_source(FILE_SYNC_SCOPE_GROUP, source_id, user_id, scope_id=group_id)
    item = set_file_sync_path_ignored(
        source, payload.get("remote_path"), payload.get("ignored", True), user_id
    )
    return {"item": item}, 200


def test_group_file_source_connection(user_id, group_id, body, *, source_id=None, user_info=None):
    group, role, settings, available = require_group_file_source_write_context(
        user_id, group_id, "test", user_info=user_info
    )
    payload = _require_body(body)
    if source_id:
        _validate_identifier(source_id, "source identifier")
    else:
        _assert_source_type_visible(payload, settings)
    result = test_file_sync_source_connection(
        FILE_SYNC_SCOPE_GROUP, group_id, payload, user_id, source_id=source_id
    )
    return {"connection": result}, 200


def browse_group_file_source(user_id, group_id, body, *, source_id=None, user_info=None):
    group, role, settings, available = require_group_file_source_write_context(
        user_id, group_id, "test", user_info=user_info
    )
    payload = _require_body(body)
    if source_id:
        _validate_identifier(source_id, "source identifier")
    else:
        _assert_source_type_visible(payload, settings)
    result = browse_file_sync_source_path(
        FILE_SYNC_SCOPE_GROUP, group_id, payload, user_id, source_id=source_id
    )
    return {"browse": result}, 200


def get_group_file_source_options(user_id, group_id, *, user_info=None):
    group, role, settings, available = require_group_file_source_read_context(
        user_id, group_id, user_info=user_info
    )
    return build_file_sync_source_options(FILE_SYNC_SCOPE_GROUP, group_id, settings), 200
