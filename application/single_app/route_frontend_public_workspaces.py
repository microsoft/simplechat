# route_frontend_public_workspaces.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_public_workspace import *

def register_route_frontend_public_workspaces(app):
    @app.route('/public_workspaces', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def public_workspaces():
        """Render the Public workspaces page for the current active public workspace."""
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")
        enable_document_classification = settings.get('enable_document_classification', False)
        enable_extract_meta_data = settings.get('enable_extract_meta_data', False)
        enable_video_file_support = settings.get('enable_video_file_support', False)
        enable_audio_file_support = settings.get('enable_audio_file_support', False)
        
        if not user_id:
            print("User not authenticated.")
            return redirect(url_for('login'))
        
        query = """
            SELECT VALUE COUNT(1) 
            FROM c 
            WHERE c.group_id = @public_workspace_id 
                AND NOT IS_DEFINED(c.percentage_complete)
        """
        parameters = [
            {"name": "@public_workspace_id", "value": active_public_workspace_id}
        ]
        
        legacy_docs_from_cosmos = list(
            cosmos_public_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            )
        )
        legacy_count = legacy_docs_from_cosmos[0] if legacy_docs_from_cosmos else 0

        return render_template(
            'public_workspaces.html', 
            settings=public_settings, 
            enable_document_classification=enable_document_classification, 
            enable_extract_meta_data=enable_extract_meta_data,
            enable_video_file_support=enable_video_file_support,
            enable_audio_file_support=enable_audio_file_support,
            legacy_docs_count=legacy_count
        )

    @app.route('/my_public_workspaces', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def my_public_workspaces():
        """Render the My Public Workspaces page."""
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        
        if not user_id:
            print("User not authenticated.")
            return redirect(url_for('login'))
        
        return render_template(
            'my_public_workspaces.html',
            settings=public_settings
        )

    @app.route('/manage_public_workspace/<workspace_id>', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def manage_public_workspace(workspace_id):
        """Render the Manage Public Workspace page."""
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        
        if not user_id:
            print("User not authenticated.")
            return redirect(url_for('login'))
        
        workspace = find_public_workspace_by_id(workspace_id)
        if not workspace:
            return "Public workspace not found", 404
        
        role = get_user_role_in_public_workspace(workspace, user_id)
        if role not in ['Owner', 'Admin']:
            return "You do not have permission to manage this public workspace", 403
        
        return render_template(
            'manage_public_workspace.html',
            workspace_id=workspace_id,
            settings=public_settings
        )

    @app.route('/public_workspace_directory', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def public_workspace_directory():
        """Render the Public Workspaces Directory page."""
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        
        if not user_id:
            print("User not authenticated.")
            return redirect(url_for('login'))
        
        return render_template(
            'public_workspace_directory.html',
            settings=public_settings
        )