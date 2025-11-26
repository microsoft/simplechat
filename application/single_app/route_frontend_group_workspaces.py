# route_frontend_group_workspaces.py

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_group_workspaces(app):
    @app.route('/group_workspaces', methods=['GET'])
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def group_workspaces():
        """Render the Group workspaces page for the current active group."""
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        active_group_id = settings.get("activeGroupOid")
        enable_document_classification = settings.get('enable_document_classification', False)
        enable_file_sharing = settings.get('enable_file_sharing', False)
        enable_extract_meta_data = settings.get('enable_extract_meta_data', False)
        enable_video_file_support = settings.get('enable_video_file_support', False)
        enable_audio_file_support = settings.get('enable_audio_file_support', False)
        if not user_id:
            print("User not authenticated.")
            return redirect(url_for('login'))
        
        query = """
            SELECT VALUE COUNT(1) 
            FROM c 
            WHERE c.group_id = @group_id 
                AND NOT IS_DEFINED(c.percentage_complete)
        """
        parameters = [
            {"name": "@group_id", "value": active_group_id}
        ]
        
        legacy_docs_from_cosmos = list(
            cosmos_group_documents_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            )
        )
        legacy_count = legacy_docs_from_cosmos[0] if legacy_docs_from_cosmos else 0
        
        # Build allowed extensions string
        allowed_extensions = [
            "txt", "pdf", "doc", "docm", "docx", "xlsx", "xls", "xlsm","csv", "pptx", "html",
            "jpg", "jpeg", "png", "bmp", "tiff", "tif", "heif", "md", "json",
            "xml", "yaml", "yml", "log"
        ]
        if enable_video_file_support in [True, 'True', 'true']:
            allowed_extensions += ["mp4", "mov", "avi", "wmv", "mkv", "webm"]
        if enable_audio_file_support in [True, 'True', 'true']:
            allowed_extensions += ["mp3", "wav", "ogg", "aac", "flac", "m4a"]
        allowed_extensions_str = "Allowed: " + ", ".join(allowed_extensions)

        return render_template(
            'group_workspaces.html', 
            settings=public_settings, 
            enable_document_classification=enable_document_classification, 
            enable_extract_meta_data=enable_extract_meta_data,
            enable_video_file_support=enable_video_file_support,
            enable_audio_file_support=enable_audio_file_support,
            enable_file_sharing=enable_file_sharing,
            legacy_docs_count=legacy_count,
            allowed_extensions=allowed_extensions_str
        )

    @app.route('/set_active_group', methods=['POST'])
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def set_active_group():
        user_id = get_current_user_id()
        group_id = request.form.get("group_id")
        if not user_id or not group_id:
            return "Missing user or group id", 400
        success = update_user_settings(user_id, {"activeGroupOid": group_id})
        if not success:
            return "Failed to update user settings", 500
        return redirect(url_for('group_workspaces'))
