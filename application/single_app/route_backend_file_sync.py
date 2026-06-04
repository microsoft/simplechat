# route_backend_file_sync.py

from flask import jsonify, request

from functions_authentication import admin_required, enabled_required, get_current_user_id, get_current_user_info, login_required, user_required
from functions_file_sync import (
    FILE_SYNC_MANAGER_ROLES,
    FILE_SYNC_SCOPE_GROUP,
    FILE_SYNC_SCOPE_PERSONAL,
    FILE_SYNC_SCOPE_PUBLIC,
    FILE_SYNC_SOURCE_TYPE_SMB,
    assert_public_workspace_role,
    browse_file_sync_source_path,
    create_file_sync_source,
    delete_file_sync_source,
    get_authorized_sync_source,
    is_file_sync_enabled_for_group,
    is_file_sync_enabled_for_public_workspace,
    is_file_sync_enabled_for_user,
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
from functions_group import find_group_by_id, require_active_group
from functions_group import search_all_groups
from functions_public_workspaces import find_public_workspace_by_id, search_all_public_workspaces
from functions_settings import get_settings
from functions_simplechat_operations import search_directory_users
from swagger_wrapper import get_auth_security, swagger_route


def register_route_backend_file_sync(app):
    def _error(message, status=400):
        return jsonify({"error": message}), status

    def _payload():
        return request.get_json(silent=True) or {}

    def _current_user():
        user_id = get_current_user_id()
        if not user_id:
            return None, None
        return user_id, get_current_user_info() or {}

    def _require_personal_context():
        user_id, user_info = _current_user()
        if not user_id:
            raise PermissionError("User not authenticated")
        settings = get_settings()
        if not is_file_sync_enabled_for_user(settings, user_id, user_info.get("email"), user_info=user_info):
            raise PermissionError("File Sync is not enabled for this user")
        return user_id

    def _require_group_context():
        user_id, user_info = _current_user()
        if not user_id:
            raise PermissionError("User not authenticated")
        group_id = require_active_group(user_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
        if not is_file_sync_enabled_for_group(get_settings(), group_id, user_info=user_info):
            raise PermissionError("File Sync is not enabled for this group")
        return user_id, group_id

    def _require_public_context(public_workspace_id):
        user_id, user_info = _current_user()
        if not user_id:
            raise PermissionError("User not authenticated")
        assert_public_workspace_role(user_id, public_workspace_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
        if not is_file_sync_enabled_for_public_workspace(get_settings(), public_workspace_id, user_info=user_info):
            raise PermissionError("File Sync is not enabled for this public workspace")
        return user_id, public_workspace_id

    def _require_admin_target_context(scope_type, scope_id):
        admin_user_id, _ = _current_user()
        if not admin_user_id:
            raise PermissionError("User not authenticated")

        settings = get_settings()
        if scope_type == FILE_SYNC_SCOPE_PERSONAL:
            enabled = is_file_sync_enabled_for_user(settings, scope_id, admin_management=True)
            target_name = "target user"
        elif scope_type == FILE_SYNC_SCOPE_GROUP:
            if not find_group_by_id(scope_id):
                raise LookupError("File Sync target group not found")
            enabled = is_file_sync_enabled_for_group(settings, scope_id, admin_management=True)
            target_name = "target group"
        elif scope_type == FILE_SYNC_SCOPE_PUBLIC:
            if not find_public_workspace_by_id(scope_id):
                raise LookupError("File Sync target public workspace not found")
            enabled = is_file_sync_enabled_for_public_workspace(settings, scope_id, admin_management=True)
            target_name = "target public workspace"
        else:
            raise ValueError("Unsupported File Sync scope")

        if not enabled:
            raise PermissionError(f"File Sync is not enabled for this {target_name}")
        return admin_user_id, scope_id

    def _serialize_group_target(group):
        return {
            "id": str(group.get("id") or ""),
            "name": str(group.get("name") or group.get("id") or ""),
            "description": str(group.get("description") or ""),
        }

    def _serialize_public_workspace_target(workspace):
        return {
            "id": str(workspace.get("id") or ""),
            "name": str(workspace.get("name") or workspace.get("id") or ""),
            "description": str(workspace.get("description") or ""),
        }

    def _map_exception(error):
        if isinstance(error, PermissionError):
            return _error(str(error), 403)
        if isinstance(error, LookupError):
            return _error(str(error), 404)
        if isinstance(error, ValueError):
            return _error(str(error), 400)
        return _error(str(error), 500)

    def _list_sources(scope_type, scope_id):
        sources = [sanitize_file_sync_source(source) for source in list_file_sync_sources(scope_type, scope_id)]
        return jsonify({"sources": sources}), 200

    def _assert_new_source_type_visible(payload):
        source_type = str(payload.get("source_type") or FILE_SYNC_SOURCE_TYPE_SMB).strip().lower()
        if not is_file_sync_source_type_visible(get_settings(), source_type):
            raise PermissionError("This File Sync source type is not available")

    def _create_source(scope_type, scope_id, user_id):
        payload = _payload()
        _assert_new_source_type_visible(payload)
        source = create_file_sync_source(scope_type, scope_id, payload, user_id)
        return jsonify({"source": sanitize_file_sync_source(source)}), 201

    def _update_source(scope_type, scope_id, source_id, user_id):
        source = update_file_sync_source(scope_type, scope_id, source_id, _payload(), user_id)
        return jsonify({"source": sanitize_file_sync_source(source)}), 200

    def _delete_source(scope_type, scope_id, source_id, user_id):
        payload = _payload()
        delete_result = delete_file_sync_source(
            scope_type,
            scope_id,
            source_id,
            user_id,
            delete_associated_files=bool(payload.get("delete_associated_files")),
        )
        return jsonify({"message": "File Sync source deleted", "delete_result": delete_result}), 200

    def _sync_now(scope_type, scope_id, source_id, user_id):
        source = get_authorized_sync_source(scope_type, source_id, user_id, scope_id=scope_id)
        run = queue_file_sync_source_run(source, triggered_by=user_id, trigger="manual")
        return jsonify({"run": sanitize_file_sync_run(run)}), 202

    def _list_runs(scope_type, scope_id, source_id, user_id):
        get_authorized_sync_source(scope_type, source_id, user_id, scope_id=scope_id)
        runs = [sanitize_file_sync_run(run) for run in list_file_sync_runs(scope_type, source_id)]
        return jsonify({"runs": runs}), 200

    def _ignore_path(scope_type, scope_id, source_id, user_id):
        source = get_authorized_sync_source(scope_type, source_id, user_id, scope_id=scope_id)
        payload = _payload()
        item = set_file_sync_path_ignored(source, payload.get("remote_path"), payload.get("ignored", True), user_id)
        return jsonify({"item": item}), 200

    def _test_connection(scope_type, scope_id, user_id, source_id=None):
        payload = _payload()
        if not source_id:
            _assert_new_source_type_visible(payload)
        result = test_file_sync_source_connection(scope_type, scope_id, payload, user_id, source_id=source_id)
        return jsonify({"connection": result}), 200

    def _browse_source(scope_type, scope_id, user_id, source_id=None):
        payload = _payload()
        if not source_id:
            _assert_new_source_type_visible(payload)
        result = browse_file_sync_source_path(scope_type, scope_id, payload, user_id, source_id=source_id)
        return jsonify({"browse": result}), 200

    @app.route('/api/admin/file-sync/users/search', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_file_sync_user_search():
        try:
            query = str(request.args.get("q") or request.args.get("query") or "").strip()
            if len(query) < 2:
                return jsonify({"users": []}), 200
            users = search_directory_users(query, limit=10)
            return jsonify({"users": users}), 200
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/groups/search', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_file_sync_group_search():
        try:
            query = str(request.args.get("q") or request.args.get("query") or "").strip()
            if len(query) < 2:
                return jsonify({"groups": []}), 200
            groups = [_serialize_group_target(group) for group in search_all_groups(query, limit=10)]
            return jsonify({"groups": groups}), 200
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/public-workspaces/search', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def api_admin_file_sync_public_workspace_search():
        try:
            query = str(request.args.get("q") or request.args.get("query") or "").strip()
            if len(query) < 2:
                return jsonify({"workspaces": []}), 200
            workspaces = [_serialize_public_workspace_target(workspace) for workspace in search_all_public_workspaces(query)[:10]]
            return jsonify({"workspaces": workspaces}), 200
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/<scope_type>/<scope_id>/sources/browse', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_source_browse_new(scope_type, scope_id):
        try:
            admin_user_id, target_scope_id = _require_admin_target_context(scope_type, scope_id)
            return _browse_source(scope_type, target_scope_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/<scope_type>/<scope_id>/sources/<source_id>/browse', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_source_browse_existing(scope_type, scope_id, source_id):
        try:
            admin_user_id, target_scope_id = _require_admin_target_context(scope_type, scope_id)
            return _browse_source(scope_type, target_scope_id, admin_user_id, source_id=source_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/personal/<target_user_id>/sources', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_personal_sources_list(target_user_id):
        try:
            _, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PERSONAL, target_user_id)
            return _list_sources(FILE_SYNC_SCOPE_PERSONAL, scope_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/personal/<target_user_id>/sources', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_personal_sources_create(target_user_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PERSONAL, target_user_id)
            return _create_source(FILE_SYNC_SCOPE_PERSONAL, scope_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/personal/<target_user_id>/sources/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_personal_source_test_connection_new(target_user_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PERSONAL, target_user_id)
            return _test_connection(FILE_SYNC_SCOPE_PERSONAL, scope_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/personal/<target_user_id>/sources/<source_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_personal_source_update(target_user_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PERSONAL, target_user_id)
            return _update_source(FILE_SYNC_SCOPE_PERSONAL, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/personal/<target_user_id>/sources/<source_id>/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_personal_source_test_connection_existing(target_user_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PERSONAL, target_user_id)
            return _test_connection(FILE_SYNC_SCOPE_PERSONAL, scope_id, admin_user_id, source_id=source_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/personal/<target_user_id>/sources/<source_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_personal_source_delete(target_user_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PERSONAL, target_user_id)
            return _delete_source(FILE_SYNC_SCOPE_PERSONAL, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/personal/<target_user_id>/sources/<source_id>/sync', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_personal_source_sync(target_user_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PERSONAL, target_user_id)
            return _sync_now(FILE_SYNC_SCOPE_PERSONAL, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/personal/<target_user_id>/sources/<source_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_personal_source_runs(target_user_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PERSONAL, target_user_id)
            return _list_runs(FILE_SYNC_SCOPE_PERSONAL, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/group/<group_id>/sources', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_group_sources_list(group_id):
        try:
            _, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_GROUP, group_id)
            return _list_sources(FILE_SYNC_SCOPE_GROUP, scope_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/group/<group_id>/sources', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_group_sources_create(group_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_GROUP, group_id)
            return _create_source(FILE_SYNC_SCOPE_GROUP, scope_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/group/<group_id>/sources/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_group_source_test_connection_new(group_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_GROUP, group_id)
            return _test_connection(FILE_SYNC_SCOPE_GROUP, scope_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/group/<group_id>/sources/<source_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_group_source_update(group_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_GROUP, group_id)
            return _update_source(FILE_SYNC_SCOPE_GROUP, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/group/<group_id>/sources/<source_id>/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_group_source_test_connection_existing(group_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_GROUP, group_id)
            return _test_connection(FILE_SYNC_SCOPE_GROUP, scope_id, admin_user_id, source_id=source_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/group/<group_id>/sources/<source_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_group_source_delete(group_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_GROUP, group_id)
            return _delete_source(FILE_SYNC_SCOPE_GROUP, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/group/<group_id>/sources/<source_id>/sync', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_group_source_sync(group_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_GROUP, group_id)
            return _sync_now(FILE_SYNC_SCOPE_GROUP, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/group/<group_id>/sources/<source_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_group_source_runs(group_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_GROUP, group_id)
            return _list_runs(FILE_SYNC_SCOPE_GROUP, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/public/<public_workspace_id>/sources', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_public_sources_list(public_workspace_id):
        try:
            _, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            return _list_sources(FILE_SYNC_SCOPE_PUBLIC, scope_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/public/<public_workspace_id>/sources', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_public_sources_create(public_workspace_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            return _create_source(FILE_SYNC_SCOPE_PUBLIC, scope_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/public/<public_workspace_id>/sources/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_public_source_test_connection_new(public_workspace_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            return _test_connection(FILE_SYNC_SCOPE_PUBLIC, scope_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/public/<public_workspace_id>/sources/<source_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_public_source_update(public_workspace_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            return _update_source(FILE_SYNC_SCOPE_PUBLIC, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/public/<public_workspace_id>/sources/<source_id>/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_public_source_test_connection_existing(public_workspace_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            return _test_connection(FILE_SYNC_SCOPE_PUBLIC, scope_id, admin_user_id, source_id=source_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/public/<public_workspace_id>/sources/<source_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_public_source_delete(public_workspace_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            return _delete_source(FILE_SYNC_SCOPE_PUBLIC, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/public/<public_workspace_id>/sources/<source_id>/sync', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_public_source_sync(public_workspace_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            return _sync_now(FILE_SYNC_SCOPE_PUBLIC, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/admin/file-sync/public/<public_workspace_id>/sources/<source_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    @enabled_required("enable_file_sync")
    def api_admin_file_sync_public_source_runs(public_workspace_id, source_id):
        try:
            admin_user_id, scope_id = _require_admin_target_context(FILE_SYNC_SCOPE_PUBLIC, public_workspace_id)
            return _list_runs(FILE_SYNC_SCOPE_PUBLIC, scope_id, source_id, admin_user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/personal/sources', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_personal_sources_list():
        try:
            user_id = _require_personal_context()
            return _list_sources(FILE_SYNC_SCOPE_PERSONAL, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/<scope_type>/sources/browse', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_source_browse_new(scope_type):
        try:
            if scope_type == FILE_SYNC_SCOPE_PERSONAL:
                user_id = _require_personal_context()
                return _browse_source(FILE_SYNC_SCOPE_PERSONAL, user_id, user_id)
            if scope_type == FILE_SYNC_SCOPE_GROUP:
                user_id, group_id = _require_group_context()
                return _browse_source(FILE_SYNC_SCOPE_GROUP, group_id, user_id)
            raise ValueError("Unsupported File Sync browse scope")
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/<scope_type>/sources/<source_id>/browse', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_source_browse_existing(scope_type, source_id):
        try:
            if scope_type == FILE_SYNC_SCOPE_PERSONAL:
                user_id = _require_personal_context()
                return _browse_source(FILE_SYNC_SCOPE_PERSONAL, user_id, user_id, source_id=source_id)
            if scope_type == FILE_SYNC_SCOPE_GROUP:
                user_id, group_id = _require_group_context()
                return _browse_source(FILE_SYNC_SCOPE_GROUP, group_id, user_id, source_id=source_id)
            raise ValueError("Unsupported File Sync browse scope")
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources/browse', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_source_browse_new(public_workspace_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _browse_source(FILE_SYNC_SCOPE_PUBLIC, workspace_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources/<source_id>/browse', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_source_browse_existing(public_workspace_id, source_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _browse_source(FILE_SYNC_SCOPE_PUBLIC, workspace_id, user_id, source_id=source_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/personal/sources', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_personal_sources_create():
        try:
            user_id = _require_personal_context()
            return _create_source(FILE_SYNC_SCOPE_PERSONAL, user_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/personal/sources/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_personal_source_test_connection_new():
        try:
            user_id = _require_personal_context()
            return _test_connection(FILE_SYNC_SCOPE_PERSONAL, user_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/personal/sources/<source_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_personal_source_update(source_id):
        try:
            user_id = _require_personal_context()
            return _update_source(FILE_SYNC_SCOPE_PERSONAL, user_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/personal/sources/<source_id>/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_personal_source_test_connection_existing(source_id):
        try:
            user_id = _require_personal_context()
            return _test_connection(FILE_SYNC_SCOPE_PERSONAL, user_id, user_id, source_id=source_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/personal/sources/<source_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_personal_source_delete(source_id):
        try:
            user_id = _require_personal_context()
            return _delete_source(FILE_SYNC_SCOPE_PERSONAL, user_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/personal/sources/<source_id>/sync', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_personal_source_sync(source_id):
        try:
            user_id = _require_personal_context()
            return _sync_now(FILE_SYNC_SCOPE_PERSONAL, user_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/personal/sources/<source_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_personal_source_runs(source_id):
        try:
            user_id = _require_personal_context()
            return _list_runs(FILE_SYNC_SCOPE_PERSONAL, user_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/personal/sources/<source_id>/ignore-path', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_personal_source_ignore_path(source_id):
        try:
            user_id = _require_personal_context()
            return _ignore_path(FILE_SYNC_SCOPE_PERSONAL, user_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/group/sources', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_group_sources_list():
        try:
            _, group_id = _require_group_context()
            return _list_sources(FILE_SYNC_SCOPE_GROUP, group_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/group/sources', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_group_sources_create():
        try:
            user_id, group_id = _require_group_context()
            return _create_source(FILE_SYNC_SCOPE_GROUP, group_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/group/sources/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_group_source_test_connection_new():
        try:
            user_id, group_id = _require_group_context()
            return _test_connection(FILE_SYNC_SCOPE_GROUP, group_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/group/sources/<source_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_group_source_update(source_id):
        try:
            user_id, group_id = _require_group_context()
            return _update_source(FILE_SYNC_SCOPE_GROUP, group_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/group/sources/<source_id>/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_group_source_test_connection_existing(source_id):
        try:
            user_id, group_id = _require_group_context()
            return _test_connection(FILE_SYNC_SCOPE_GROUP, group_id, user_id, source_id=source_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/group/sources/<source_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_group_source_delete(source_id):
        try:
            user_id, group_id = _require_group_context()
            return _delete_source(FILE_SYNC_SCOPE_GROUP, group_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/group/sources/<source_id>/sync', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_group_source_sync(source_id):
        try:
            user_id, group_id = _require_group_context()
            return _sync_now(FILE_SYNC_SCOPE_GROUP, group_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/group/sources/<source_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_group_source_runs(source_id):
        try:
            user_id, group_id = _require_group_context()
            return _list_runs(FILE_SYNC_SCOPE_GROUP, group_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/group/sources/<source_id>/ignore-path', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_group_source_ignore_path(source_id):
        try:
            user_id, group_id = _require_group_context()
            return _ignore_path(FILE_SYNC_SCOPE_GROUP, group_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_sources_list(public_workspace_id):
        try:
            _, workspace_id = _require_public_context(public_workspace_id)
            return _list_sources(FILE_SYNC_SCOPE_PUBLIC, workspace_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_sources_create(public_workspace_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _create_source(FILE_SYNC_SCOPE_PUBLIC, workspace_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_source_test_connection_new(public_workspace_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _test_connection(FILE_SYNC_SCOPE_PUBLIC, workspace_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources/<source_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_source_update(public_workspace_id, source_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _update_source(FILE_SYNC_SCOPE_PUBLIC, workspace_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources/<source_id>/test-connection', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_source_test_connection_existing(public_workspace_id, source_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _test_connection(FILE_SYNC_SCOPE_PUBLIC, workspace_id, user_id, source_id=source_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources/<source_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_source_delete(public_workspace_id, source_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _delete_source(FILE_SYNC_SCOPE_PUBLIC, workspace_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources/<source_id>/sync', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_source_sync(public_workspace_id, source_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _sync_now(FILE_SYNC_SCOPE_PUBLIC, workspace_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources/<source_id>/runs', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_source_runs(public_workspace_id, source_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _list_runs(FILE_SYNC_SCOPE_PUBLIC, workspace_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)

    @app.route('/api/file-sync/public/<public_workspace_id>/sources/<source_id>/ignore-path', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_file_sync")
    def api_file_sync_public_source_ignore_path(public_workspace_id, source_id):
        try:
            user_id, workspace_id = _require_public_context(public_workspace_id)
            return _ignore_path(FILE_SYNC_SCOPE_PUBLIC, workspace_id, source_id, user_id)
        except Exception as error:
            return _map_exception(error)