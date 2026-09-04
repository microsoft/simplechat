# route_backend_workspace_identities.py

from flask import jsonify, request

from functions_authentication import admin_required, get_current_user_id, login_required, user_required
from functions_file_sync import list_file_sync_sources
from functions_group import assert_group_role, find_group_by_id, require_active_group
from functions_public_workspaces import find_public_workspace_by_id, get_user_role_in_public_workspace
from functions_workspace_identities import (
    WORKSPACE_IDENTITY_SCOPE_GLOBAL,
    WORKSPACE_IDENTITY_SCOPE_GROUP,
    WORKSPACE_IDENTITY_SCOPE_PERSONAL,
    WORKSPACE_IDENTITY_SCOPE_PUBLIC,
    create_workspace_identity,
    delete_workspace_identity,
    get_action_identity_reference_id,
    list_workspace_identities,
    log_workspace_identity_reference_block,
    sanitize_workspace_identity,
    update_workspace_identity,
)
from swagger_wrapper import get_auth_security, swagger_route


WORKSPACE_IDENTITY_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")


def register_route_backend_workspace_identities(bp):
    def _error(message, status=400):
        return jsonify({"error": message}), status

    def _payload():
        return request.get_json(silent=True) or {}

    def _current_user_id():
        user_id = get_current_user_id()
        if not user_id:
            raise PermissionError("User not authenticated")
        return user_id

    def _map_exception(error):
        if isinstance(error, PermissionError):
            return _error(str(error), 403)
        if isinstance(error, LookupError):
            return _error(str(error), 404)
        if isinstance(error, ValueError):
            return _error(str(error), 400)
        return _error(str(error), 500)

    def _require_personal_context():
        return _current_user_id()

    def _require_group_context():
        user_id = _current_user_id()
        group_id = require_active_group(user_id, allowed_roles=WORKSPACE_IDENTITY_MANAGER_ROLES)
        assert_group_role(user_id, group_id, allowed_roles=WORKSPACE_IDENTITY_MANAGER_ROLES)
        return user_id, group_id

    def _require_public_context(public_workspace_id):
        user_id = _current_user_id()
        workspace = find_public_workspace_by_id(public_workspace_id)
        if not workspace:
            raise LookupError("Public workspace not found")
        role = get_user_role_in_public_workspace(workspace, user_id)
        if role not in WORKSPACE_IDENTITY_MANAGER_ROLES:
            raise PermissionError("Access denied")
        return user_id, public_workspace_id

    def _require_admin_target_context(scope_type, scope_id):
        admin_user_id = _current_user_id()
        if scope_type == WORKSPACE_IDENTITY_SCOPE_GROUP and not find_group_by_id(scope_id):
            raise LookupError("Target group not found")
        if scope_type == WORKSPACE_IDENTITY_SCOPE_PUBLIC and not find_public_workspace_by_id(scope_id):
            raise LookupError("Target public workspace not found")
        if scope_type == WORKSPACE_IDENTITY_SCOPE_GLOBAL:
            if scope_id != WORKSPACE_IDENTITY_SCOPE_GLOBAL:
                raise ValueError("Unsupported global identity scope id")
            return admin_user_id, WORKSPACE_IDENTITY_SCOPE_GLOBAL
        if scope_type not in {WORKSPACE_IDENTITY_SCOPE_PERSONAL, WORKSPACE_IDENTITY_SCOPE_GROUP, WORKSPACE_IDENTITY_SCOPE_PUBLIC}:
            raise ValueError("Unsupported identity scope")
        return admin_user_id, scope_id

    def _list(scope_type, scope_id):
        identities = [sanitize_workspace_identity(identity) for identity in list_workspace_identities(scope_type, scope_id)]
        return jsonify({"identities": identities}), 200

    def _create(scope_type, scope_id, user_id):
        identity = create_workspace_identity(scope_type, scope_id, _payload(), user_id)
        return jsonify({"identity": sanitize_workspace_identity(identity)}), 201

    def _update(scope_type, scope_id, identity_id, user_id):
        identity = update_workspace_identity(scope_type, scope_id, identity_id, _payload(), user_id)
        return jsonify({"identity": sanitize_workspace_identity(identity)}), 200

    def _assert_not_referenced(scope_type, scope_id, identity_id):
        referenced_sources = []
        if scope_type != WORKSPACE_IDENTITY_SCOPE_GLOBAL:
            referenced_sources = [source for source in list_file_sync_sources(scope_type, scope_id) if source.get("identity_id") == identity_id]

        referenced_actions = _list_action_references(scope_type, scope_id, identity_id)
        reference_count = len(referenced_sources) + len(referenced_actions)
        if reference_count:
            log_workspace_identity_reference_block(scope_type, scope_id, identity_id, reference_count)
            raise ValueError("This workspace identity is still used by one or more File Sync sources or actions")

    def _list_action_references(scope_type, scope_id, identity_id):
        # Local imports avoid a route/action import cycle during application startup.
        if scope_type == WORKSPACE_IDENTITY_SCOPE_PERSONAL:
            from functions_personal_actions import get_personal_actions

            actions = get_personal_actions(scope_id)
        elif scope_type == WORKSPACE_IDENTITY_SCOPE_GROUP:
            from functions_group_actions import get_group_actions

            actions = get_group_actions(scope_id)
        elif scope_type == WORKSPACE_IDENTITY_SCOPE_GLOBAL:
            from functions_global_actions import get_global_actions

            actions = get_global_actions(include_disabled=True)
        else:
            actions = []

        return [action for action in actions if get_action_identity_reference_id(action) == identity_id]

    def _delete(scope_type, scope_id, identity_id, user_id):
        _assert_not_referenced(scope_type, scope_id, identity_id)
        delete_result = delete_workspace_identity(scope_type, scope_id, identity_id, user_id)
        return jsonify({"message": "Workspace identity deleted", "delete_result": delete_result}), 200

    @bp.route('/api/admin/workspace-identities/global/identities', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_workspace_identities_global_list():
        try:
            _, target_scope_id = _require_admin_target_context(WORKSPACE_IDENTITY_SCOPE_GLOBAL, WORKSPACE_IDENTITY_SCOPE_GLOBAL)
            return _list(WORKSPACE_IDENTITY_SCOPE_GLOBAL, target_scope_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/admin/workspace-identities/global/identities', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_workspace_identities_global_create():
        try:
            admin_user_id, target_scope_id = _require_admin_target_context(WORKSPACE_IDENTITY_SCOPE_GLOBAL, WORKSPACE_IDENTITY_SCOPE_GLOBAL)
            return _create(WORKSPACE_IDENTITY_SCOPE_GLOBAL, target_scope_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/admin/workspace-identities/global/identities/<identity_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_workspace_identities_global_update(identity_id):
        try:
            admin_user_id, target_scope_id = _require_admin_target_context(WORKSPACE_IDENTITY_SCOPE_GLOBAL, WORKSPACE_IDENTITY_SCOPE_GLOBAL)
            return _update(WORKSPACE_IDENTITY_SCOPE_GLOBAL, target_scope_id, identity_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/admin/workspace-identities/global/identities/<identity_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_workspace_identities_global_delete(identity_id):
        try:
            admin_user_id, target_scope_id = _require_admin_target_context(WORKSPACE_IDENTITY_SCOPE_GLOBAL, WORKSPACE_IDENTITY_SCOPE_GLOBAL)
            return _delete(WORKSPACE_IDENTITY_SCOPE_GLOBAL, target_scope_id, identity_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/personal/identities', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_personal_list():
        try:
            user_id = _require_personal_context()
            return _list(WORKSPACE_IDENTITY_SCOPE_PERSONAL, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/personal/identities', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_personal_create():
        try:
            user_id = _require_personal_context()
            return _create(WORKSPACE_IDENTITY_SCOPE_PERSONAL, user_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/personal/identities/<identity_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_personal_update(identity_id):
        try:
            user_id = _require_personal_context()
            return _update(WORKSPACE_IDENTITY_SCOPE_PERSONAL, user_id, identity_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/personal/identities/<identity_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_personal_delete(identity_id):
        try:
            user_id = _require_personal_context()
            return _delete(WORKSPACE_IDENTITY_SCOPE_PERSONAL, user_id, identity_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/group/identities', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_group_list():
        try:
            _, group_id = _require_group_context()
            return _list(WORKSPACE_IDENTITY_SCOPE_GROUP, group_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/group/identities', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_group_create():
        try:
            user_id, group_id = _require_group_context()
            return _create(WORKSPACE_IDENTITY_SCOPE_GROUP, group_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/group/identities/<identity_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_group_update(identity_id):
        try:
            user_id, group_id = _require_group_context()
            return _update(WORKSPACE_IDENTITY_SCOPE_GROUP, group_id, identity_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/group/identities/<identity_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_group_delete(identity_id):
        try:
            user_id, group_id = _require_group_context()
            return _delete(WORKSPACE_IDENTITY_SCOPE_GROUP, group_id, identity_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/public/<public_workspace_id>/identities', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_public_list(public_workspace_id):
        try:
            _, workspace_id = _require_public_context(public_workspace_id)
            return _list(WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/public/<public_workspace_id>/identities', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_public_create(public_workspace_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _create(WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/public/<public_workspace_id>/identities/<identity_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_public_update(public_workspace_id, identity_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _update(WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id, identity_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/workspace-identities/public/<public_workspace_id>/identities/<identity_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_workspace_identities_public_delete(public_workspace_id, identity_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _delete(WORKSPACE_IDENTITY_SCOPE_PUBLIC, workspace_id, identity_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/admin/workspace-identities/<scope_type>/<scope_id>/identities', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_workspace_identities_list(scope_type, scope_id):
        try:
            _, target_scope_id = _require_admin_target_context(scope_type, scope_id)
            return _list(scope_type, target_scope_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/admin/workspace-identities/<scope_type>/<scope_id>/identities', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_workspace_identities_create(scope_type, scope_id):
        try:
            admin_user_id, target_scope_id = _require_admin_target_context(scope_type, scope_id)
            return _create(scope_type, target_scope_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/admin/workspace-identities/<scope_type>/<scope_id>/identities/<identity_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_workspace_identities_update(scope_type, scope_id, identity_id):
        try:
            admin_user_id, target_scope_id = _require_admin_target_context(scope_type, scope_id)
            return _update(scope_type, target_scope_id, identity_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @bp.route('/api/admin/workspace-identities/<scope_type>/<scope_id>/identities/<identity_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_workspace_identities_delete(scope_type, scope_id, identity_id):
        try:
            admin_user_id, target_scope_id = _require_admin_target_context(scope_type, scope_id)
            return _delete(scope_type, target_scope_id, identity_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)
