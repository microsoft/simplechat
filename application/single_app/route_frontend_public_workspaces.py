# route_frontend_public_workspaces.py

from config import *
from functions_authentication import *
from functions_settings import *

def register_route_frontend_public_workspaces(app):
    @app.route('/public_workspaces', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def public_workspaces():
        """Render the Public workspaces discovery page."""
        user_id = get_current_user_id()
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        enable_document_classification = settings.get('enable_document_classification', False)
        enable_extract_meta_data = settings.get('enable_extract_meta_data', False)
        enable_video_file_support = settings.get('enable_video_file_support', False)
        enable_audio_file_support = settings.get('enable_audio_file_support', False)
        if not user_id:
            print("User not authenticated.")
            return redirect(url_for('login'))
        
        # Count available public documents
        query = """
            SELECT VALUE COUNT(1)
            FROM c 
            WHERE NOT IS_DEFINED(c.percentage_complete)
        """
        
        legacy_docs_from_cosmos = list(
            cosmos_public_documents_container.query_items(
                query=query,
                parameters=[],
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