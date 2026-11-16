# route_backend_v2_admin_agents_actions.py
"""V2 Admin Settings routes for the global agent and action editors.

These serve the same V2 agent and action editors personal and group workspaces use,
for the organisation's global agents and actions. Every route requires the Admin
role; the shared editor contract, conditional writes and secret handling are
described in ``functions_global_editor_access``.
"""

from functools import wraps

from flask import jsonify

from functions_authentication import admin_required, get_current_user_id, login_required
from functions_global_editor_access import (
    create_global_action,
    create_global_agent,
    delete_global_action_record,
    delete_global_agent_record,
    get_global_action,
    get_global_action_options,
    get_global_agent,
    get_global_agent_options,
    global_editor_error_response,
    list_global_actions,
    list_global_agents,
    read_json_body,
    reject_query_parameters,
    reject_request_body,
    update_global_action,
    update_global_agent,
)
from functions_workspace_authoring import build_action_editor_types
from route_backend_agents import _prepare_global_agent_payload
from route_backend_plugins import _prepare_global_action_payload, get_plugin_types
from swagger_wrapper import swagger_route, get_auth_security


def _global_editor_boundary(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - all mapped to stable HTTP responses
            return global_editor_error_response(error)
    return guarded


def _no_store(payload, status):
    # Editor reads carry configuration, so they stay out of shared caches.
    response = jsonify(payload)
    response.headers['Cache-Control'] = 'no-store'
    return response, status


def register_route_backend_v2_admin_agents_actions(bp):
    """Register the global agent and action editor routes.

    - GET    /api/v2/admin/agents
    - POST   /api/v2/admin/agents
    - GET    /api/v2/admin/agent-options
    - GET    /api/v2/admin/agents/<agent_id>
    - PATCH  /api/v2/admin/agents/<agent_id>
    - DELETE /api/v2/admin/agents/<agent_id>
    - GET    /api/v2/admin/actions
    - POST   /api/v2/admin/actions
    - GET    /api/v2/admin/actions/types
    - GET    /api/v2/admin/action-options
    - GET    /api/v2/admin/actions/<action_id>
    - PATCH  /api/v2/admin/actions/<action_id>
    - DELETE /api/v2/admin/actions/<action_id>
    """

    @bp.route('/api/v2/admin/agents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_agents_list():
        reject_query_parameters()
        reject_request_body()
        return _no_store(*list_global_agents())

    @bp.route('/api/v2/admin/agents', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_agents_create():
        reject_query_parameters()
        return _no_store(*create_global_agent(
            get_current_user_id(), read_json_body(), _prepare_global_agent_payload,
        ))

    @bp.route('/api/v2/admin/agent-options', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_agent_options():
        # Its own path segment so it can never collide with /agents/<agent_id>.
        reject_query_parameters()
        reject_request_body()
        return _no_store(*get_global_agent_options())

    @bp.route('/api/v2/admin/agents/<agent_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_agent_read(agent_id):
        reject_query_parameters()
        reject_request_body()
        return _no_store(*get_global_agent(agent_id))

    @bp.route('/api/v2/admin/agents/<agent_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_agent_update(agent_id):
        reject_query_parameters()
        return _no_store(*update_global_agent(
            get_current_user_id(), agent_id, read_json_body(), _prepare_global_agent_payload,
        ))

    @bp.route('/api/v2/admin/agents/<agent_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_agent_delete(agent_id):
        reject_query_parameters()
        reject_request_body()
        return _no_store(*delete_global_agent_record(get_current_user_id(), agent_id))

    @bp.route('/api/v2/admin/actions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_actions_list():
        reject_query_parameters()
        reject_request_body()
        return _no_store(*list_global_actions())

    @bp.route('/api/v2/admin/actions', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_actions_create():
        reject_query_parameters()
        return _no_store(*create_global_action(
            get_current_user_id(), read_json_body(), _prepare_global_action_payload,
        ))

    @bp.route('/api/v2/admin/actions/types', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_action_types():
        # Every type the deployment provides, as the classic admin catalogue offers:
        # per-type workspace governance applies to people's own actions, not to the
        # organisation's.
        reject_query_parameters()
        reject_request_body()
        discovered = get_plugin_types()
        return _no_store({'types': build_action_editor_types(discovered.get_json())}, 200)

    @bp.route('/api/v2/admin/action-options', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_action_options():
        # Its own path segment so it can never collide with /actions/<action_id>.
        reject_query_parameters()
        reject_request_body()
        return _no_store(*get_global_action_options())

    @bp.route('/api/v2/admin/actions/<action_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_action_read(action_id):
        reject_query_parameters()
        reject_request_body()
        return _no_store(*get_global_action(action_id))

    @bp.route('/api/v2/admin/actions/<action_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_action_update(action_id):
        reject_query_parameters()
        return _no_store(*update_global_action(
            get_current_user_id(), action_id, read_json_body(), _prepare_global_action_payload,
        ))

    @bp.route('/api/v2/admin/actions/<action_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @_global_editor_boundary
    def v2_admin_global_action_delete(action_id):
        reject_query_parameters()
        reject_request_body()
        return _no_store(*delete_global_action_record(get_current_user_id(), action_id))
