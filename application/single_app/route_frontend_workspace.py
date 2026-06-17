# route_frontend_workspace.py

import logging

from config import *
from functions_authentication import *
from functions_group import get_user_groups
from functions_governance import filter_governed_model_endpoints, is_action_scope_access_allowed, is_governance_access_allowed
from functions_public_workspaces import get_user_visible_public_workspace_docs
from functions_settings import *
from functions_file_sync import is_file_sync_enabled_for_user
from functions_source_review import is_url_access_enabled_for_user
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_workspace(app):
    @app.route('/workspace', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def workspace():
        user_id = get_current_user_id()
        settings = get_settings()
        user_settings = get_user_settings(user_id)
        public_settings = sanitize_settings_for_user(settings)
        enable_document_classification = settings.get('enable_document_classification', False)
        enable_file_sharing = settings.get('enable_file_sharing', False)
        enable_extract_meta_data = settings.get('enable_extract_meta_data', False)
        enable_video_file_support = settings.get('enable_video_file_support', False)
        enable_audio_file_support = settings.get('enable_audio_file_support', False)
        user_info = get_current_user_info() or {}
        current_user_roles = (session.get('user') or {}).get('roles', [])
        public_settings['allow_user_workflows'] = is_user_workflows_enabled_for_user(
            settings,
            user_roles=current_user_roles,
        )
        public_settings['enable_url_access'] = is_url_access_enabled_for_user(
            settings,
            user_roles=current_user_roles,
        )
        file_sync_enabled = is_file_sync_enabled_for_user(settings, user_id, user_info.get('email'), user_info=user_info) if user_id else False
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
        
        # Get allowed extensions from central function and build allowed extensions string
        allowed_extensions = sorted(get_allowed_extensions(
            enable_video=enable_video_file_support in [True, 'True', 'true'],
            enable_audio=enable_audio_file_support in [True, 'True', 'true']
        ))
        allowed_extensions_str = "Allowed: " + ", ".join(allowed_extensions)
        
        workspace_governance = {
            "user_agents": is_governance_access_allowed("governance_user_agents", user_id),
            "user_actions": is_action_scope_access_allowed("governance_user_actions", user_id, "personal"),
            "user_endpoints": is_governance_access_allowed("governance_user_endpoints", user_id),
            "global_endpoints": is_governance_access_allowed("governance_global_endpoints", user_id),
        }

        personal_endpoints = user_settings.get("settings", {}).get("personal_model_endpoints", [])
        personal_model_endpoints = sanitize_model_endpoints_for_frontend(
            filter_governed_model_endpoints(user_id, personal_endpoints, "governance_user_endpoints")
        )
        global_model_endpoints = sanitize_model_endpoints_for_frontend(
            filter_governed_model_endpoints(user_id, settings.get("model_endpoints", []), "governance_global_endpoints")
        )
        user_groups_simple = []
        try:
            user_groups_simple = [
                {
                    'id': str(group.get('id') or ''),
                    'name': str(group.get('name') or group.get('id') or ''),
                }
                for group in get_user_groups(user_id)
                if group.get('id')
            ]
        except Exception as exc:
            log_event(
                f'[WorkspaceRoute] Failed to load workflow group picker options: {exc}',
                extra={'user_id': user_id},
                level=logging.WARNING,
                exceptionTraceback=True,
            )

        user_visible_public_workspaces = []
        try:
            user_visible_public_workspaces = [
                {
                    'id': str(workspace.get('id') or ''),
                    'name': str(workspace.get('name') or workspace.get('id') or ''),
                }
                for workspace in get_user_visible_public_workspace_docs(user_id)
                if workspace.get('id')
            ]
        except Exception as exc:
            log_event(
                f'[WorkspaceRoute] Failed to load workflow public picker options: {exc}',
                extra={'user_id': user_id},
                level=logging.WARNING,
                exceptionTraceback=True,
            )

        return render_template(
            'workspace.html', 
            settings=public_settings, 
            enable_document_classification=enable_document_classification, 
            enable_extract_meta_data=enable_extract_meta_data,
            enable_video_file_support=enable_video_file_support,
            enable_audio_file_support=enable_audio_file_support,
            enable_file_sharing=enable_file_sharing,
            legacy_docs_count=legacy_count,
            allowed_extensions=allowed_extensions_str,
            personal_model_endpoints=personal_model_endpoints,
            global_model_endpoints=global_model_endpoints,
            file_sync_enabled=file_sync_enabled,
            user_groups=user_groups_simple,
                user_visible_public_workspaces=user_visible_public_workspaces,
            workspace_governance=workspace_governance
        )

    