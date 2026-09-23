# functions_group_action_access.py
"""Authorization, projection and orchestration for immutable-target group actions.

The active-scoped legacy routes in ``route_backend_plugins.py`` (``/api/group/plugins``)
are left untouched. Everything here backs the new ``/api/groups/<group_id>/actions``
family, where the group is named in the path and every request reauthorizes
membership, role and status independently of whatever workspace the account has
selected.

Group actions reuse the personal editor engine in ``functions_workspace_authoring``;
this module only resolves the group boundary (role and status), then delegates
persistence, secret handling and conditional writes to that engine. There is
exactly one management projection, ``group_action_management_operations``, and one
per-item projection, ``group_action_actions`` — both computed fresh on every
request so a stored ``action_actions`` can never be served.
"""

import re

from werkzeug.exceptions import HTTPException

from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_user_role_in_group,
)
from functions_group_action_policy import (
    GROUP_ACTION_READER_ROLES,
    GROUP_ACTION_READ_STATUSES,
    group_action_actions,
    group_action_management_operations,
    group_actions_available,
    group_action_write_roles,
)
from functions_settings import get_settings
from functions_workspace_authoring import (
    apply_group_action_write,
    delete_group_editor_record,
    editor_error_response,
    editor_resource,
    list_group_editor_records,
    project_editor_record,
    read_group_editor_record,
    read_group_merged_global_record,
)


INVALID_GROUP_ACTION_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")


class GroupActionError(HTTPException):
    """A stable, non-sensitive failure at a group action boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_GROUP_ACTION_ID.search(value)
    ):
        raise GroupActionError(f"Invalid {label}.", 400)


def require_group_action_read_context(user_id, group_id):
    """Resolve (group, role) for a reader, or raise a boundary error.

    Reads are open to all four member roles. Unknown group is 404, ineligible
    role is 403, and a status outside the browsable set is 403 — an unrecognized
    status is treated as unavailable, never as active.
    """
    _validate_identifier(group_id, "group identifier")
    if not user_id:
        raise GroupActionError("User not authenticated.", 401)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_ACTION_READER_ROLES)
    except LookupError as error:
        raise GroupActionError("The selected group was not found.", 404) from error
    except PermissionError as error:
        raise GroupActionError("You do not have access to the selected group.", 403) from error
    group = find_group_by_id(group_id)
    if not group:
        raise GroupActionError("The selected group was not found.", 404)
    role = get_user_role_in_group(group, user_id)
    if role not in GROUP_ACTION_READER_ROLES:
        raise GroupActionError("You do not have access to the selected group.", 403)
    allowed, _reason = check_group_status_allows_operation(group, "view")
    if not allowed or group.get("status", "active") not in GROUP_ACTION_READ_STATUSES:
        raise GroupActionError("Actions are unavailable for this group's current status.", 403)
    # One availability predicate gates the whole surface. A tenant with group
    # actions off (or a governance-denied user) must see every route refuse,
    # including the reads, with the shell's own reason text and no data.
    available, reason = group_actions_available(user_id, get_settings())
    if not available:
        raise GroupActionError(reason, 403)
    return group, role


def require_group_action_write_context(user_id, group_id, operation):
    """Resolve (group, role, settings) for a writer, or raise a boundary error.

    Writes are limited to the group action write roles (Owner and Admin, or Owner
    alone when ``require_owner_for_group_agent_management`` is on). ``User`` and
    ``DocumentManager`` reach the write-role assertion and are refused with 403.
    The operation must also be offered by the group's current status (active only).
    """
    group, role = require_group_action_read_context(user_id, group_id)
    settings = get_settings()
    try:
        assert_group_role(user_id, group_id, allowed_roles=group_action_write_roles(settings))
    except (LookupError, PermissionError) as error:
        raise GroupActionError("You do not have permission to manage this group's actions.", 403) from error
    if operation not in group_action_management_operations(user_id, group, role, settings):
        raise GroupActionError("This operation is unavailable for the selected group.", 403)
    return group, role, settings


def require_group_action_types_context(user_id, group_id):
    """Resolve (group, role, settings) for the action-type catalog, or raise.

    Types are a *read* capability: the V2 editor renders type labels for every
    viewer of the collection and the details page, so the catalog is gated on the
    same read context as the list — four member roles, a readable status and the
    one availability predicate — never on a write role. The legacy
    ``/api/group/plugins/types`` keeps its Owner/Admin gate.
    """
    group, role = require_group_action_read_context(user_id, group_id)
    return group, role, get_settings()


def group_action_error_response(exc):
    """Map both group-boundary and shared editor-engine errors to HTTP responses."""
    if isinstance(exc, GroupActionError):
        from flask import jsonify

        response = jsonify({"error": exc.description})
        response.headers["Cache-Control"] = "no-store"
        return response, exc.code
    return editor_error_response(exc)


def _writer_can_manage(user_id, group, role, settings):
    return bool(group_action_management_operations(user_id, group, role, settings))


def _project_group_action(record, user_id, group, role, settings, *, is_global):
    """Project one stored record for the group list, with fresh per-item actions."""
    projected = project_editor_record(
        record, "actions", global_scope=is_global, group_scope=not is_global,
    )
    projected["action_actions"] = (
        [] if is_global else group_action_actions(projected, user_id, group, role, settings)
    )
    return projected


def _group_action_resource(record, user_id, group, role, settings, *, read_only):
    """Wrap one stored record in the editor resource envelope with fresh actions."""
    resource = editor_resource(record, "actions", group_scope=True, read_only=read_only)
    resource["record"]["action_actions"] = group_action_actions(
        resource["record"], user_id, group, role, settings,
    )
    return resource


def _global_group_action_resource(record):
    """Wrap one merged global action as a read-only row of the group view.

    A provided (global) action a member sees in a merged list opens onto this
    read-only detail: it is not a group action, so it advertises no per-item
    operations and can never be edited or deleted through the group route.
    """
    resource = editor_resource(record, "actions", global_scope=True, read_only=True)
    resource["record"]["action_actions"] = []
    return resource


def list_group_actions(user_id, group_id):
    group, role = require_group_action_read_context(user_id, group_id)
    settings = get_settings()
    resources = [
        _project_group_action(record, user_id, group, role, settings, is_global=is_global)
        for record, is_global in list_group_editor_records(user_id, group_id, settings)
    ]
    return {"actions": resources}, 200


def get_group_action(user_id, group_id, action_id):
    group, role = require_group_action_read_context(user_id, group_id)
    settings = get_settings()
    try:
        record = read_group_editor_record(user_id, group_id, action_id, settings)
    except LookupError:
        # A provided (global) row from a merged list opens read-only through the
        # group route; when the id is not a merged global action this re-raises
        # LookupError, which the boundary maps to 404.
        global_record = read_group_merged_global_record(user_id, group_id, action_id, settings)
        return _global_group_action_resource(global_record), 200
    read_only = not _writer_can_manage(user_id, group, role, settings)
    return _group_action_resource(record, user_id, group, role, settings, read_only=read_only), 200


def create_group_action(user_id, group_id, body, prepare):
    group, role, settings = require_group_action_write_context(user_id, group_id, "create")
    saved = apply_group_action_write(user_id, group_id, None, body, prepare, settings)
    return _group_action_resource(saved, user_id, group, role, settings, read_only=False), 201


def update_group_action(user_id, group_id, action_id, body, prepare):
    group, role, settings = require_group_action_write_context(user_id, group_id, "edit")
    existing = read_group_editor_record(user_id, group_id, action_id, settings)
    saved = apply_group_action_write(user_id, group_id, existing, body, prepare, settings)
    return _group_action_resource(saved, user_id, group, role, settings, read_only=False), 200


def delete_group_action(user_id, group_id, action_id):
    _group, _role, settings = require_group_action_write_context(user_id, group_id, "delete")
    existing = read_group_editor_record(user_id, group_id, action_id, settings)
    delete_group_editor_record(user_id, group_id, existing, settings)
    return {"success": True}, 200
