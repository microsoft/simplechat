# route_frontend_workspace.py

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_workspace(app):
    @app.route('/workspace', methods=['GET'])
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def workspace():
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
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
            WHERE c.user_id = @user_id
                AND NOT IS_DEFINED(c.percentage_complete)
        """
        parameters = [
            {"name": "@user_id", "value": user_id}
        ]

        legacy_docs_from_cosmos = list(
            cosmos_user_documents_container.query_items(
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
            'workspace.html', 
            settings=public_settings, 
            enable_document_classification=enable_document_classification, 
            enable_extract_meta_data=enable_extract_meta_data,
            enable_video_file_support=enable_video_file_support,
            enable_audio_file_support=enable_audio_file_support,
            enable_file_sharing=enable_file_sharing,
            legacy_docs_count=legacy_count,
            allowed_extensions=allowed_extensions_str
        )

    