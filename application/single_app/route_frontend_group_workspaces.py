# route_frontend_group_workspaces.py

from config import *
from functions_authentication import *
from functions_group import get_group_model_endpoints, require_active_group, update_active_group_for_user
from functions_governance import filter_governed_model_endpoints, is_governance_access_allowed
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_group_workspaces(app):
    @app.route('/group_workspaces', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def group_workspaces():
        """Render the Group workspaces page for the current active group."""
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        try:
            active_group_id = require_active_group(user_id)
        except (ValueError, LookupError, PermissionError):
            active_group_id = None
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
        
        # Get allowed extensions from central function and build allowed extensions string
        allowed_extensions = sorted(get_allowed_extensions(
            enable_video=enable_video_file_support in [True, 'True', 'true'],
            enable_audio=enable_audio_file_support in [True, 'True', 'true']
        ))
        allowed_extensions_str = "Allowed: " + ", ".join(allowed_extensions)

        workspace_governance = {
            "group_agents": is_governance_access_allowed("governance_group_agents", user_id),
            "group_actions": is_governance_access_allowed("governance_group_actions", user_id),
            "group_endpoints": is_governance_access_allowed("governance_group_endpoints", user_id),
            "global_endpoints": is_governance_access_allowed("governance_global_endpoints", user_id),
        }

        group_endpoints = get_group_model_endpoints(active_group_id) if active_group_id else []
        group_model_endpoints = sanitize_model_endpoints_for_frontend(
            filter_governed_model_endpoints(user_id, group_endpoints, "governance_group_endpoints")
        )
        global_model_endpoints = sanitize_model_endpoints_for_frontend(
            filter_governed_model_endpoints(user_id, settings.get("model_endpoints", []), "governance_global_endpoints")
        )

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
            allowed_extensions=allowed_extensions_str,
            group_model_endpoints=group_model_endpoints,
            global_model_endpoints=global_model_endpoints,
            workspace_governance=workspace_governance
        )

    @app.route('/set_active_group', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def set_active_group():
        user_id = get_current_user_id()
        group_id = request.form.get("group_id")
        if not user_id or not group_id:
            return "Missing user or group id", 400

        try:
            update_active_group_for_user(group_id, user_id=user_id)
        except LookupError:
            return "Group not found", 404
        except PermissionError:
            return "You are not a member of this group", 403

        return redirect(url_for('group_workspaces'))
