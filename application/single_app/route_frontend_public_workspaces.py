# route_frontend_public_workspaces.py

from config import *
from functions_authentication import *
from functions_settings import *

def register_route_frontend_public_workspaces(app):
    @app.route("/my_public_workspaces", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def my_public_workspaces():
        user = session.get('user', {})
        settings = get_settings()
        require_member_of_create_public_workspace = settings.get("require_member_of_create_public_workspace", False)
        
        # Check if user can create public workspaces
        can_create_public_workspaces = True
        if require_member_of_create_public_workspace:
            can_create_public_workspaces = 'roles' in user and 'CreatePublicWorkspaces' in user['roles']
        
        public_settings = sanitize_settings_for_user(settings)
        return render_template(
            "my_public_workspaces.html",
            settings=public_settings,
            app_settings=public_settings,
            can_create_public_workspaces=can_create_public_workspaces
        )

    @app.route("/public_workspaces/<workspace_id>", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
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

        # Build allowed extensions string as in workspace.html
        allowed_extensions = [
            "txt", "pdf", "docx", "xlsx", "xls", "csv", "pptx", "html",
            "jpg", "jpeg", "png", "bmp", "tiff", "tif", "heif", "md", "json"
        ]
        if enable_video_file_support in [True, 'True', 'true']:
            allowed_extensions += ["mp4", "mov", "avi", "wmv", "mkv", "webm"]
        if enable_audio_file_support in [True, 'True', 'true']:
            allowed_extensions += ["mp3", "wav", "ogg", "aac", "flac", "m4a"]
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
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def set_active_public_workspace():
        user_id = get_current_user_id()
        workspace_id = request.form.get("workspace_id")
        if not user_id or not workspace_id:
            return "Missing user or workspace id", 400
        success = update_user_settings(user_id, {"activePublicWorkspaceOid": workspace_id})
        if not success:
            return "Failed to update user settings", 500
        return redirect(url_for('public_workspaces'))