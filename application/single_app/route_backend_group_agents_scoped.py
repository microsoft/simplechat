# route_backend_group_agents_scoped.py
"""Immutable-target group agent routes: the group is named in the path.

These sit beside the legacy active-scoped ``/api/group/agents`` routes, which
fall back to the account's selected group and are left exactly as they are. An
older server lacking this family 404s rather than silently editing whatever group
the account has selected.

Group agents reuse the personal editor contract verbatim: reads answer with
``{record, revision, secret_paths, read_only}`` and writes accept
``{updates, expected_revision, clear_secret_paths, removed_paths}``. Every
mutation is conditional on ``expected_revision`` so a stale editor cannot
overwrite a concurrent manager edit — a mismatch is a 409 with nothing written.
Writes are limited to Owner/Admin (Owner only when
``require_owner_for_group_agent_management`` is set) and only while the group is
``active``; the projection layer advertises this through ``agent_actions``.
"""

import json
from functools import wraps

from flask import jsonify, request

from functions_authentication import login_required, user_required, get_current_user_id
from functions_settings import enabled_required
from functions_group_agent_access import (
    GroupAgentError,
    create_group_agent,
    delete_group_agent_record,
    get_group_agent,
    get_group_agent_knowledge,
    get_group_agent_options,
    group_agent_error_response,
    list_group_agents,
    update_group_agent,
)
from route_backend_agents import _prepare_group_agent_payload
from swagger_wrapper import swagger_route, get_auth_security


def _group_agent_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return group_agent_error_response(error)
    return guarded


def _reject_query_parameters():
    """These immutable-target routes take no query parameters; a stray one is a
    400 rather than being silently ignored (e.g. ``?expected_etag=`` on DELETE)."""
    if request.args:
        raise GroupAgentError("This request does not accept query parameters.", 400)


def _reject_request_body():
    if request.get_data():
        raise GroupAgentError("This read does not accept a request body.", 400)


def _read_json_body():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second
    value cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise GroupAgentError("Duplicate fields are not supported.", 400)
            payload[key] = value
        return payload

    if not request.is_json:
        raise GroupAgentError("A JSON object is required for this action.", 400)
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise GroupAgentError("Provide valid JSON with no duplicate fields.", 400) from error
    if not isinstance(body, dict):
        raise GroupAgentError("A JSON object is required for this action.", 400)
    return body


def register_route_backend_group_agents_scoped(bp):
    """Register the immutable-target group agent routes.

    - GET    /api/groups/<group_id>/agents
    - POST   /api/groups/<group_id>/agents
    - GET    /api/groups/<group_id>/agent-options
    - GET    /api/groups/<group_id>/agent-knowledge
    - GET    /api/groups/<group_id>/agents/<agent_id>
    - PATCH  /api/groups/<group_id>/agents/<agent_id>
    - DELETE /api/groups/<group_id>/agents/<agent_id>
    """

    @bp.route('/api/groups/<group_id>/agents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_agent_boundary
    def api_scoped_group_agents_list(group_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = list_group_agents(get_current_user_id(), group_id)
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/agents', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_agent_boundary
    def api_scoped_group_agents_create(group_id):
        _reject_query_parameters()
        payload, status = create_group_agent(
            get_current_user_id(), group_id, _read_json_body(), _prepare_group_agent_payload,
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/agent-options', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_agent_boundary
    def api_scoped_group_agent_options(group_id):
        # Its own path segment so it can never collide with /agents/<agent_id>.
        # A read capability: the group editor reads its type, endpoint and builtin
        # options here rather than the personal agent-settings editor.
        _reject_query_parameters()
        _reject_request_body()
        payload, status = get_group_agent_options(get_current_user_id(), group_id)
        response = jsonify(payload)
        response.headers['Cache-Control'] = 'no-store'
        return response, status

    @bp.route('/api/groups/<group_id>/agent-knowledge', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_agent_boundary
    def api_scoped_group_agent_knowledge(group_id):
        # Its own path segment so it can never collide with /agents/<agent_id>.
        # A read capability: the assigned-knowledge catalogue for this named group.
        _reject_query_parameters()
        _reject_request_body()
        payload, status = get_group_agent_knowledge(get_current_user_id(), group_id)
        response = jsonify(payload)
        response.headers['Cache-Control'] = 'no-store'
        return response, status

    @bp.route('/api/groups/<group_id>/agents/<agent_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_agent_boundary
    def api_scoped_group_agent_read(group_id, agent_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = get_group_agent(get_current_user_id(), group_id, agent_id)
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/agents/<agent_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_agent_boundary
    def api_scoped_group_agent_update(group_id, agent_id):
        _reject_query_parameters()
        payload, status = update_group_agent(
            get_current_user_id(), group_id, agent_id, _read_json_body(), _prepare_group_agent_payload,
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/agents/<agent_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_agent_boundary
    def api_scoped_group_agent_delete(group_id, agent_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = delete_group_agent_record(get_current_user_id(), group_id, agent_id)
        return jsonify(payload), status
