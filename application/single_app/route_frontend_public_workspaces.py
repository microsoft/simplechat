# route_frontend_public_workspaces.py

from config import *
from functions_authentication import *
from functions_settings import *

def register_route_frontend_public_workspaces(app):
    @app.route("/my_public_workspaces", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @create_public_workspace_role_required
    def my_public_workspaces():
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        return render_template(
            "my_public_workspaces.html",
            settings=public_settings,
            app_settings=public_settings
        )

    @app.route("/public_workspaces/<workspace_id>", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    @create_public_workspace_role_required
    def manage_public_workspace(workspace_id):
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        return render_template(
            "manage_public_workspace.html",
            settings=public_settings,
            app_settings=public_settings,
            workspace_id=workspace_id
        )
    
    @app.route("/public_workspaces", methods=["GET"])
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

        return render_template(
            'public_workspaces.html',
            settings=public_settings,
            app_settings=public_settings,
            enable_document_classification=enable_document_classification,
            enable_extract_meta_data=enable_extract_meta_data,
            enable_video_file_support=enable_video_file_support,
            enable_audio_file_support=enable_audio_file_support
        )

    @app.route("/public_directory", methods=["GET"])
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