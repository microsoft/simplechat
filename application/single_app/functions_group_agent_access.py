# functions_group_agent_access.py
"""Authorization, projection and orchestration for immutable-target group agents.

The active-scoped legacy routes (``/api/group/agents``) are left untouched. This
module backs the new ``/api/groups/<group_id>/agents`` family, where the group is
named in the path and every request reauthorizes membership, role and status
independently of whatever workspace the account has selected.

Group agents reuse the personal editor engine in ``functions_workspace_authoring``;
this module only resolves the group boundary (role and status), then delegates
persistence, secret handling and conditional writes to that engine. There is
exactly one management projection, ``group_agent_management_operations``, and one
per-item projection, ``group_agent_actions`` — both computed fresh on every
request so a stored ``agent_actions`` can never be served.
"""

import re
from importlib import import_module

from werkzeug.exceptions import HTTPException

from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_user_role_in_group,
)
from functions_group_agent_policy import (
    GROUP_AGENT_READER_ROLES,
    GROUP_AGENT_READ_STATUSES,
    group_agent_actions,
    group_agent_chat_available,
    group_agent_management_operations,
    group_agents_available,
    group_agent_write_roles,
)
from functions_settings import get_settings
from functions_workspace_authoring import (
    apply_group_agent_write,
    delete_group_editor_record,
    editor_error_response,
    editor_resource,
    list_group_editor_records,
    log_committed_group_editor_change,
    project_editor_record,
    read_group_editor_record,
    read_group_merged_global_record,
)


INVALID_GROUP_AGENT_ID = re.compile(r"[/\\?#,\x00-\x1f\x7f]")


class GroupAgentError(HTTPException):
    """A stable, non-sensitive failure at a group agent boundary."""

    def __init__(self, message, status_code):
        super().__init__(description=message)
        self.code = status_code


def _validate_identifier(value, label):
    if (
        not isinstance(value, str) or not value or len(value) > 512
        or value != value.strip() or value in (".", "..")
        or INVALID_GROUP_AGENT_ID.search(value)
    ):
        raise GroupAgentError(f"Invalid {label}.", 400)


def require_group_agent_read_context(user_id, group_id):
    """Resolve (group, role) for a reader, or raise a boundary error.

    Reads are open to all four member roles. Unknown group is 404, ineligible
    role is 403, and a status outside the browsable set is 403 — an unrecognized
    status is treated as unavailable, never as active. The one availability
    predicate gates the whole surface, so a tenant with group agents off (or a
    governance-denied user) sees every route refuse, including the reads.
    """
    _validate_identifier(group_id, "group identifier")
    if not user_id:
        raise GroupAgentError("User not authenticated.", 401)
    try:
        assert_group_role(user_id, group_id, allowed_roles=GROUP_AGENT_READER_ROLES)
    except LookupError as error:
        raise GroupAgentError("The selected group was not found.", 404) from error
    except PermissionError as error:
        raise GroupAgentError("You do not have access to the selected group.", 403) from error
    group = find_group_by_id(group_id)
    if not group:
        raise GroupAgentError("The selected group was not found.", 404)
    role = get_user_role_in_group(group, user_id)
    if role not in GROUP_AGENT_READER_ROLES:
        raise GroupAgentError("You do not have access to the selected group.", 403)
    allowed, _reason = check_group_status_allows_operation(group, "view")
    if not allowed or group.get("status", "active") not in GROUP_AGENT_READ_STATUSES:
        raise GroupAgentError("Agents are unavailable for this group's current status.", 403)
    available, reason = group_agents_available(user_id, get_settings())
    if not available:
        raise GroupAgentError(reason, 403)
    return group, role


def require_group_agent_write_context(user_id, group_id, operation):
    """Resolve (group, role, settings) for a writer, or raise a boundary error.

    Writes are limited to the group agent write roles (Owner and Admin, or Owner
    alone when ``require_owner_for_group_agent_management`` is on). ``User`` and
    ``DocumentManager`` reach the write-role assertion and are refused with 403.
    The operation must also be offered by the group's current status (active only).
    """
    group, role = require_group_agent_read_context(user_id, group_id)
    settings = get_settings()
    try:
        assert_group_role(user_id, group_id, allowed_roles=group_agent_write_roles(settings))
    except (LookupError, PermissionError) as error:
        raise GroupAgentError("You do not have permission to manage this group's agents.", 403) from error
    if operation not in group_agent_management_operations(user_id, group, role, settings):
        raise GroupAgentError("This operation is unavailable for the selected group.", 403)
    return group, role, settings


def get_group_agent_options(user_id, group_id):
    """The group agent editor's options: agent types, model endpoints, builtins.

    A *read* capability gated on the same context as the list. Model endpoints are
    resolved for this group — globals filtered by governance, group endpoints
    included only when custom group endpoints are allowed, secrets masked — so a
    group editor never reaches into the personal agent-settings editor. A caller
    without the write roles gets no models, matching the personal builder.
    """
    group, role = require_group_agent_read_context(user_id, group_id)
    settings = get_settings()
    can_manage = bool(
        group_agent_management_operations(user_id, group, role, settings, available=True)
    )
    # Lazily bound to avoid importing the agent route blueprint at module load, so
    # this module stays importable for standalone tests.
    route_agents = import_module("route_backend_agents")
    authoring = import_module("functions_workspace_authoring")
    endpoints = route_agents.build_combined_model_endpoints(settings, user_id, group_id=group_id)
    options = authoring.build_group_agent_editor_options(
        user_id, group_id, settings, endpoints, can_manage,
    )
    return options, 200


def get_group_agent_knowledge(user_id, group_id):
    """The group's assigned-knowledge catalogue for the agent editor.

    A *read* capability gated on the same context as the list, resolved for the
    named group so it never reads the account's active group or personal
    knowledge.
    """
    require_group_agent_read_context(user_id, group_id)
    knowledge = import_module("functions_assigned_knowledge")
    catalog = knowledge.build_assigned_knowledge_catalog(
        user_id=user_id, agent_scope="group", group_id=group_id, is_admin=False,
    )
    return catalog, 200


def group_agent_error_response(exc):
    """Map both group-boundary and shared editor-engine errors to HTTP responses."""
    if isinstance(exc, GroupAgentError):
        from flask import jsonify

        response = jsonify({"error": exc.description})
        response.headers["Cache-Control"] = "no-store"
        return response, exc.code
    return editor_error_response(exc)


def _writer_can_manage(user_id, group, role, settings):
    return bool(group_agent_management_operations(user_id, group, role, settings))


def _project_group_agent(record, user_id, group, role, settings, *, is_global, available=None, chat_available=None):
    """Project one stored record for the group list, with fresh per-item actions.

    ``available`` and ``chat_available`` carry the read context's already-resolved
    surface state so a list projection resolves each once rather than per row.
    """
    projected = project_editor_record(
        record, "agents", global_scope=is_global, group_scope=not is_global,
    )
    projected["agent_actions"] = (
        [] if is_global
        else group_agent_actions(
            projected, user_id, group, role, settings,
            available=available, chat_available=chat_available,
        )
    )
    return projected


def _group_agent_resource(record, user_id, group, role, settings, *, read_only):
    """Wrap one stored record in the editor resource envelope with fresh actions."""
    resource = editor_resource(record, "agents", group_scope=True, read_only=read_only)
    resource["record"]["agent_actions"] = group_agent_actions(
        resource["record"], user_id, group, role, settings,
    )
    return resource


def _global_group_agent_resource(record):
    """Wrap one merged global agent as a read-only row of the group view.

    A provided (global) agent a member sees in a merged list opens onto this
    read-only detail: it is not a group agent, so it advertises no per-item
    operations and can never be edited or deleted through the group route.
    """
    resource = editor_resource(record, "agents", global_scope=True, read_only=True)
    resource["record"]["agent_actions"] = []
    return resource


def list_group_agents(user_id, group_id):
    group, role = require_group_agent_read_context(user_id, group_id)
    settings = get_settings()
    # The read context established the surface is available; resolve chat
    # availability once and thread both through so the projection does not repeat
    # the per-user governance checks for every row.
    chat_available = group_agent_chat_available(user_id, settings)
    resources = [
        _project_group_agent(
            record, user_id, group, role, settings,
            is_global=is_global, available=True, chat_available=chat_available,
        )
        for record, is_global in list_group_editor_records("agents", user_id, group_id, settings)
    ]
    return {"agents": resources}, 200


def get_group_agent(user_id, group_id, agent_id):
    group, role = require_group_agent_read_context(user_id, group_id)
    settings = get_settings()
    try:
        record = read_group_editor_record("agents", user_id, group_id, agent_id, settings)
    except LookupError:
        # A provided (global) row from a merged list opens read-only through the
        # group route; when the id is not a merged global agent this re-raises
        # LookupError, which the boundary maps to 404.
        global_record = read_group_merged_global_record("agents", user_id, group_id, agent_id, settings)
        return _global_group_agent_resource(global_record), 200
    read_only = not _writer_can_manage(user_id, group, role, settings)
    return _group_agent_resource(record, user_id, group, role, settings, read_only=read_only), 200


def create_group_agent(user_id, group_id, body, prepare):
    group, role, settings = require_group_agent_write_context(user_id, group_id, "create")
    saved = apply_group_agent_write(user_id, group_id, None, body, prepare, settings)
    log_committed_group_editor_change("agents", user_id, group_id, saved, "creation")
    return _group_agent_resource(saved, user_id, group, role, settings, read_only=False), 201


def update_group_agent(user_id, group_id, agent_id, body, prepare):
    group, role, settings = require_group_agent_write_context(user_id, group_id, "edit")
    existing = read_group_editor_record("agents", user_id, group_id, agent_id, settings)
    saved = apply_group_agent_write(user_id, group_id, existing, body, prepare, settings)
    log_committed_group_editor_change("agents", user_id, group_id, saved, "update")
    return _group_agent_resource(saved, user_id, group, role, settings, read_only=False), 200


def delete_group_agent_record(user_id, group_id, agent_id):
    _group, _role, settings = require_group_agent_write_context(user_id, group_id, "delete")
    existing = read_group_editor_record("agents", user_id, group_id, agent_id, settings)
    delete_group_editor_record("agents", user_id, group_id, existing, settings)
    log_committed_group_editor_change("agents", user_id, group_id, existing, "deletion")
    return {"success": True}, 200
