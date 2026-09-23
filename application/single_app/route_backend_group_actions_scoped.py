# route_backend_group_actions_scoped.py
"""Immutable-target group action routes: the group is named in the path.

These sit beside the legacy active-scoped ``/api/group/plugins`` routes, which
fall back to the account's selected group when ``?group_id`` is omitted and are
left exactly as they are. An older server lacking this family 404s rather than
silently editing whatever group the account has selected.

Group actions reuse the personal editor contract verbatim: reads answer with
``{record, revision, secret_paths, read_only}`` and writes accept
``{updates, expected_revision, clear_secret_paths, removed_paths}``. Every
mutation is conditional on ``expected_revision`` so a stale editor cannot
overwrite a concurrent manager edit — a mismatch is a 409 with nothing written.
Writes are limited to Owner/Admin (Owner only when
``require_owner_for_group_agent_management`` is set) and only while the group is
``active``; the projection layer advertises this through ``action_actions``.
"""

import json
from functools import wraps

from flask import jsonify, request

from functions_authentication import login_required, user_required, get_current_user_id
from functions_settings import enabled_required
from functions_group_action_access import (
    GroupActionError,
    create_group_action,
    delete_group_action,
    get_group_action,
    group_action_error_response,
    list_group_actions,
    require_group_action_types_context,
    update_group_action,
)
from route_backend_plugins import (
    _prepare_group_action_payload,
    build_action_editor_types,
    get_plugin_types,
    is_action_type_access_allowed,
)
from swagger_wrapper import swagger_route, get_auth_security


def _group_action_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return group_action_error_response(error)
    return guarded


def _reject_query_parameters():
    """These immutable-target routes take no query parameters; a stray one is a
    400 rather than being silently ignored (e.g. ``?expected_etag=`` on DELETE)."""
    if request.args:
        raise GroupActionError("This request does not accept query parameters.", 400)


def _reject_request_body():
    if request.get_data():
        raise GroupActionError("This read does not accept a request body.", 400)


def _read_json_body():
    """Parse a JSON object body, rejecting duplicate keys so a smuggled second
    value cannot shadow a validated one."""
    def unique_fields(pairs):
        payload = {}
        for key, value in pairs:
            if key in payload:
                raise GroupActionError("Duplicate fields are not supported.", 400)
            payload[key] = value
        return payload

    if not request.is_json:
        raise GroupActionError("A JSON object is required for this action.", 400)
    try:
        body = json.loads(request.get_data(), object_pairs_hook=unique_fields)
    except (ValueError, UnicodeDecodeError) as error:
        raise GroupActionError("Provide valid JSON with no duplicate fields.", 400) from error
    if not isinstance(body, dict):
        raise GroupActionError("A JSON object is required for this action.", 400)
    return body


def register_route_backend_group_actions_scoped(bp):
    """Register the immutable-target group action routes.

    - GET    /api/groups/<group_id>/actions
    - POST   /api/groups/<group_id>/actions
    - GET    /api/groups/<group_id>/actions/types
    - GET    /api/groups/<group_id>/actions/<action_id>
    - PATCH  /api/groups/<group_id>/actions/<action_id>
    - DELETE /api/groups/<group_id>/actions/<action_id>
    """

    @bp.route('/api/groups/<group_id>/actions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_action_boundary
    def api_scoped_group_actions_list(group_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = list_group_actions(get_current_user_id(), group_id)
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/actions', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_action_boundary
    def api_scoped_group_actions_create(group_id):
        _reject_query_parameters()
        payload, status = create_group_action(
            get_current_user_id(), group_id, _read_json_body(), _prepare_group_action_payload,
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/actions/types', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_action_boundary
    def api_scoped_group_actions_types(group_id):
        _reject_query_parameters()
        _reject_request_body()
        user_id = get_current_user_id()
        require_group_action_types_context(user_id, group_id)
        # Mirror the personal ?view=editor branch: enrich governed discovery into
        # the editor catalogue the V2 editor renders (auth types and field schemas),
        # never the raw discovery Response, and keep it out of shared caches.
        discovered = get_plugin_types(
            allowed_type_filter=lambda action_type: is_action_type_access_allowed(
                'governance_group_actions', user_id, action_type, 'group',
            ),
        )
        response = jsonify({"types": build_action_editor_types(discovered.get_json())})
        response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.route('/api/groups/<group_id>/actions/<action_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_action_boundary
    def api_scoped_group_action_read(group_id, action_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = get_group_action(get_current_user_id(), group_id, action_id)
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/actions/<action_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_action_boundary
    def api_scoped_group_action_update(group_id, action_id):
        _reject_query_parameters()
        payload, status = update_group_action(
            get_current_user_id(), group_id, action_id, _read_json_body(), _prepare_group_action_payload,
        )
        return jsonify(payload), status

    @bp.route('/api/groups/<group_id>/actions/<action_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    @_group_action_boundary
    def api_scoped_group_action_delete(group_id, action_id):
        _reject_query_parameters()
        _reject_request_body()
        payload, status = delete_group_action(get_current_user_id(), group_id, action_id)
        return jsonify(payload), status
