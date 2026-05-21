# route_frontend_public_workspaces.py

from config import *
from functions_authentication import *
from functions_public_workspaces import update_active_public_workspace_for_user
from functions_settings import *
from functions_file_sync import FILE_SYNC_MANAGER_ROLES, assert_public_workspace_role, is_file_sync_enabled_for_public_workspace
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_public_workspaces(app):
    @app.route("/my_public_workspaces", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def my_public_workspaces():
        return redirect(url_for('profile', tab='public-workspaces'))

    @app.route("/public_workspaces/<workspace_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def manage_public_workspace(workspace_id):
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        try:
            assert_public_workspace_role(user_id, workspace_id, allowed_roles=FILE_SYNC_MANAGER_ROLES)
            user_info = get_current_user_info() or {}
            file_sync_enabled = is_file_sync_enabled_for_public_workspace(settings, workspace_id, user_info=user_info)
        except (LookupError, PermissionError):
            file_sync_enabled = False
        return render_template(
            "manage_public_workspace.html",
            settings=public_settings,
            app_settings=public_settings,
            workspace_id=workspace_id,
            file_sync_enabled=file_sync_enabled
        )
    
    @app.route("/public_workspaces", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def public_workspaces():
        """
        Renders the Public Workspaces directory page (templates/public_workspaces.html).
        """
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)

        # Feature flags
        enable_document_classification = settings.get('enable_document_classification', False)
        enable_extract_meta_data = settings.get('enable_extract_meta_data', False)
        enable_video_file_support = settings.get('enable_video_file_support', False)
        enable_audio_file_support = settings.get('enable_audio_file_support', False)

        # Get allowed extensions from central function and build allowed extensions string
        allowed_extensions = sorted(get_allowed_extensions(
            enable_video=enable_video_file_support in [True, 'True', 'true'],
            enable_audio=enable_audio_file_support in [True, 'True', 'true']
        ))
        allowed_extensions_str = "Allowed: " + ", ".join(allowed_extensions)
        
        return render_template(
            'public_workspaces.html',
            settings=public_settings,
            app_settings=public_settings,
            enable_document_classification=enable_document_classification,
            enable_extract_meta_data=enable_extract_meta_data,
            enable_video_file_support=enable_video_file_support,
            enable_audio_file_support=enable_audio_file_support,
            allowed_extensions=allowed_extensions_str
        )

    @app.route("/public_directory", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def public_directory():
        """
        Renders the Public Directory page (templates/public_directory.html).
        This page shows all public workspaces in a table format with search functionality.
        """
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        
        return render_template(
            'public_directory.html',
            settings=public_settings,
            app_settings=public_settings
        )

    @app.route('/set_active_public_workspace', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def set_active_public_workspace():
        user_id = get_current_user_id()
        workspace_id = request.form.get("workspace_id")
        if not user_id or not workspace_id:
            return "Missing user or workspace id", 400

        try:
            update_active_public_workspace_for_user(user_id, workspace_id)
        except LookupError:
            return "Workspace not found", 404

        return redirect(url_for('public_workspaces'))