# route_backend_file_sync.py

from flask import jsonify, request

from functions_authentication import enabled_required, get_current_user_id, get_current_user_info, login_required, user_required
from functions_file_sync import (
    FILE_SYNC_MANAGER_ROLES,
    FILE_SYNC_SCOPE_GROUP,
    FILE_SYNC_SCOPE_PERSONAL,
    FILE_SYNC_SCOPE_PUBLIC,
    assert_public_workspace_role,
    create_file_sync_source,
    delete_file_sync_source,
    get_authorized_sync_source,
    is_file_sync_enabled_for_group,
    is_file_sync_enabled_for_public_workspace,
    is_file_sync_enabled_for_user,
    list_file_sync_runs,
    list_file_sync_sources,
    queue_file_sync_source_run,
    sanitize_file_sync_run,
    sanitize_file_sync_source,
    set_file_sync_path_ignored,
    update_file_sync_source,
)
from functions_group import require_active_group
from functions_settings import get_settings
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
        if not is_file_sync_enabled_for_user(settings, user_id, user_info.get("email")):
            raise PermissionError("File Sync is not enabled for this user")
        return user_id

    def _require_group_context():
        user_id, _ = _current_user()
        if not user_id:
            raise PermissionError("User not authenticated")
        group_id = require_active_group(user_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
        if not is_file_sync_enabled_for_group(get_settings(), group_id):
            raise PermissionError("File Sync is not enabled for this group")
        return user_id, group_id

    def _require_public_context(public_workspace_id):
        user_id, _ = _current_user()
        if not user_id:
            raise PermissionError("User not authenticated")
        assert_public_workspace_role(user_id, public_workspace_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
        if not is_file_sync_enabled_for_public_workspace(get_settings(), public_workspace_id):
            raise PermissionError("File Sync is not enabled for this public workspace")
        return user_id, public_workspace_id

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

    def _create_source(scope_type, scope_id, user_id):
        source = create_file_sync_source(scope_type, scope_id, _payload(), user_id)
        return jsonify({"source": sanitize_file_sync_source(source)}), 201

    def _update_source(scope_type, scope_id, source_id, user_id):
        source = update_file_sync_source(scope_type, scope_id, source_id, _payload(), user_id)
        return jsonify({"source": sanitize_file_sync_source(source)}), 200

    def _delete_source(scope_type, scope_id, source_id, user_id):
        delete_file_sync_source(scope_type, scope_id, source_id, user_id)
        return jsonify({"message": "File Sync source deleted"}), 200

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