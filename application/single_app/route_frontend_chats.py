# route_frontend_chats.py

import logging
from config import *
from functions_authentication import *
from functions_content import *
from functions_settings import *
from functions_agent_catalog import build_accessible_agent_catalog
from functions_collaboration import (
    assert_user_can_participate_in_collaboration_conversation,
    create_collaboration_message_notifications,
    ensure_collaboration_source_conversation,
    get_collaboration_conversation,
    is_personal_collaboration_conversation,
    is_group_collaboration_conversation,
    mirror_source_message_to_collaboration,
    publish_collaboration_event,
    serialize_collaboration_conversation,
    serialize_collaboration_message,
)
from functions_source_review import get_deep_research_config, is_source_review_enabled_for_user, is_url_access_enabled_for_user
from functions_documents import *
from functions_group import (
    assert_group_role,
    check_group_status_allows_operation,
    find_group_by_id,
    get_group_model_endpoints,
    get_user_groups,
    get_user_role_in_group,
    require_active_group,
)
from functions_governance import ensure_governance_access
from functions_image_messages import build_image_message_documents
from functions_prompts import list_all_prompts_for_scope
from functions_public_workspaces import find_public_workspace_by_id, get_user_visible_public_workspace_ids_from_settings
from functions_simplechat_operations import upload_chat_image_bytes_for_user
from functions_appinsights import log_event
from swagger_wrapper import swagger_route, get_auth_security
from functions_debug import debug_print
from utils_cache import invalidate_group_search_cache, invalidate_personal_search_cache

logger = logging.getLogger(__name__)


CHAT_WORKSPACE_UPLOAD_EXTENSIONS = (
    DOCUMENT_EXTENSIONS
    | IMAGE_EXTENSIONS
    | TABULAR_EXTENSIONS
    | EMAIL_EXTENSIONS
    | {'doc', 'docm', 'html', 'txt', 'md', 'json', 'xml', 'yaml', 'yml', 'log'}
)

GROUP_CHAT_UPLOAD_ROLES = ('Owner', 'Admin', 'DocumentManager')
GROUP_WORKFLOW_ACTIVITY_ROLES = ('Owner', 'Admin', 'DocumentManager', 'User')


def _is_setting_enabled(value):
    return value is True or str(value).strip().lower() == 'true'


def _normalize_workflow_activity_scope(value):
    normalized_scope = str(value or '').strip().lower()
    return 'group' if normalized_scope == 'group' else 'personal'


def _resolve_workflow_activity_group_id(user_id):
    requested_group_id = str(request.args.get('group_id') or request.args.get('groupId') or '').strip()
    if requested_group_id:
        assert_group_role(user_id, requested_group_id, allowed_roles=GROUP_WORKFLOW_ACTIVITY_ROLES)
        return requested_group_id
    return require_active_group(user_id, allowed_roles=GROUP_WORKFLOW_ACTIVITY_ROLES)


def _authorize_workflow_activity_view(user_id, settings):
    scope = _normalize_workflow_activity_scope(request.args.get('scope'))
    if scope == 'group':
        if not settings.get('enable_group_workspaces', False):
            return 'Group workspaces are disabled.', 400
        if not settings.get('allow_group_workflows', False):
            return 'Group workflows are disabled.', 400

        group_id = _resolve_workflow_activity_group_id(user_id)
        if not is_group_workflows_enabled_for_group(settings, group_id):
            return 'This group is not assigned to use workflows.', 403
        return None

    user_roles = (session.get('user') or {}).get('roles', [])
    if is_user_workflows_enabled_for_user(settings, user_roles=user_roles):
        return None

    if not settings.get('allow_user_workflows', False):
        return 'Personal workflows are disabled.', 400
    return 'Forbidden: Personal workflows require the WorkflowUser app role.', 403


def _build_new_chat_conversation(user_id):
    conversation_id = str(uuid.uuid4())
    conversation_item = {
        'id': conversation_id,
        'user_id': user_id,
        'last_updated': datetime.utcnow().isoformat(),
        'title': 'New Conversation',
        'context': [],
        'tags': [],
        'strict': False,
    }
    cosmos_conversations_container.upsert_item(conversation_item)
    return conversation_item


def _append_unique(values, value):
    normalized_value = str(value or '').strip()
    if normalized_value and normalized_value not in values:
        values.append(normalized_value)


def _normalize_upload_group_ids(raw_values):
    normalized_ids = []
    if not raw_values:
        return normalized_ids

    values = raw_values if isinstance(raw_values, (list, tuple, set)) else [raw_values]
    for raw_value in values:
        if raw_value is None:
            continue
        for group_id in str(raw_value).split(','):
            _append_unique(normalized_ids, group_id)
    return normalized_ids


def _extract_group_context_ids_from_doc(doc):
    group_ids = []
    if not isinstance(doc, dict):
        return group_ids

    _append_unique(group_ids, doc.get('group_id'))

    scope = doc.get('scope') if isinstance(doc.get('scope'), dict) else {}
    if str(scope.get('type') or '').strip().lower() == 'group':
        _append_unique(group_ids, scope.get('group_id') or scope.get('id'))

    for context_item in list(doc.get('context', []) or []):
        if not isinstance(context_item, dict):
            continue
        if str(context_item.get('scope') or '').strip().lower() == 'group':
            _append_unique(group_ids, context_item.get('id') or context_item.get('group_id'))

    for locked_context in list(doc.get('locked_contexts', []) or []):
        if not isinstance(locked_context, dict):
            continue
        if str(locked_context.get('scope') or '').strip().lower() == 'group':
            _append_unique(group_ids, locked_context.get('id') or locked_context.get('group_id'))

    return group_ids


def _get_trusted_group_upload_scope_ids(conversation_item, collaboration_conversation=None):
    group_ids = []
    for group_id in _extract_group_context_ids_from_doc(conversation_item):
        _append_unique(group_ids, group_id)
    for group_id in _extract_group_context_ids_from_doc(collaboration_conversation):
        _append_unique(group_ids, group_id)
    return group_ids


def _is_group_chat_upload_context(conversation_item, collaboration_conversation=None, requested_group_ids=None):
    if collaboration_conversation is not None:
        return is_group_collaboration_conversation(collaboration_conversation)

    chat_type = str((conversation_item or {}).get('chat_type') or '').strip().lower()
    if chat_type in ('group', 'group-single-user', 'group_single_user', 'group_multi_user'):
        return True

    if _get_trusted_group_upload_scope_ids(conversation_item):
        return True

    return bool(requested_group_ids)


def _build_group_upload_target_option(group_id, user_id):
    normalized_group_id = str(group_id or '').strip()
    if not normalized_group_id:
        return None

    group_doc = find_group_by_id(normalized_group_id)
    if not group_doc:
        return {
            'id': normalized_group_id,
            'name': 'Unknown group',
            'role': None,
            'can_upload': False,
            'reason': 'Group not found',
        }

    role = get_user_role_in_group(group_doc, user_id)
    status_allowed, status_reason = check_group_status_allows_operation(group_doc, 'upload')
    role_allowed = role in GROUP_CHAT_UPLOAD_ROLES
    reason = None
    if not role:
        reason = 'You are not a member of this group'
    elif not role_allowed:
        reason = 'Your group role can chat but cannot upload documents'
    elif not status_allowed:
        reason = status_reason or 'Uploads are disabled for this group'

    return {
        'id': normalized_group_id,
        'name': group_doc.get('name') or 'Group Workspace',
        'role': role,
        'can_upload': bool(role_allowed and status_allowed),
        'reason': reason,
    }


def _resolve_group_upload_targets(conversation_item, collaboration_conversation, requested_group_ids, user_id):
    trusted_group_ids = _get_trusted_group_upload_scope_ids(conversation_item, collaboration_conversation)
    candidate_group_ids = list(trusted_group_ids)

    if not candidate_group_ids:
        candidate_group_ids = list(requested_group_ids or [])
    elif requested_group_ids:
        candidate_group_ids = [group_id for group_id in trusted_group_ids if group_id in set(requested_group_ids)]

    targets = []
    for group_id in candidate_group_ids:
        target = _build_group_upload_target_option(group_id, user_id)
        if target:
            targets.append(target)
    return targets, trusted_group_ids


def _resolve_group_workspace_upload_target(
    *,
    conversation_item,
    collaboration_conversation,
    requested_group_ids,
    selected_group_id,
    user_id,
):
    targets, trusted_group_ids = _resolve_group_upload_targets(
        conversation_item,
        collaboration_conversation,
        requested_group_ids,
        user_id,
    )
    eligible_targets = [target for target in targets if target.get('can_upload')]
    normalized_selected_group_id = str(selected_group_id or '').strip()

    if trusted_group_ids and normalized_selected_group_id and normalized_selected_group_id not in trusted_group_ids:
        raise PermissionError('Selected group does not match the conversation scope')

    if normalized_selected_group_id:
        selected_target = next(
            (target for target in targets if target.get('id') == normalized_selected_group_id),
            None,
        )
        if not selected_target:
            raise PermissionError('Selected group is not available for this upload')
        if not selected_target.get('can_upload'):
            raise PermissionError(selected_target.get('reason') or 'You cannot upload documents to this group')
        assert_group_role(user_id, normalized_selected_group_id, allowed_roles=GROUP_CHAT_UPLOAD_ROLES)
        group_doc = find_group_by_id(normalized_selected_group_id)
        status_allowed, status_reason = check_group_status_allows_operation(group_doc, 'upload')
        if not status_allowed:
            raise PermissionError(status_reason or 'Uploads are disabled for this group')
        return selected_target

    if len(eligible_targets) == 1:
        selected_target = eligible_targets[0]
        assert_group_role(user_id, selected_target.get('id'), allowed_roles=GROUP_CHAT_UPLOAD_ROLES)
        group_doc = find_group_by_id(selected_target.get('id'))
        status_allowed, status_reason = check_group_status_allows_operation(group_doc, 'upload')
        if not status_allowed:
            raise PermissionError(status_reason or 'Uploads are disabled for this group')
        return selected_target

    if not eligible_targets:
        raise PermissionError('You do not have permission to upload documents to the selected group scope')

    raise ValueError('Multiple group upload targets are available. Select one group workspace for this file.')


def _apply_group_context_to_new_upload_conversation(conversation_item, group_target):
    if not conversation_item or not group_target:
        return
    if conversation_item.get('context'):
        return

    group_id = group_target.get('id')
    group_name = group_target.get('name') or 'Group Workspace'
    conversation_item['chat_type'] = 'group-single-user'
    conversation_item['context'] = [
        {
            'type': 'primary',
            'scope': 'group',
            'id': group_id,
            'name': group_name,
        }
    ]
    conversation_item['scope_locked'] = True
    conversation_item['locked_contexts'] = [{'scope': 'group', 'id': group_id}]


def _resolve_collaboration_upload_context(conversation_id, user_id, current_user_info):
    collaboration_conversation = get_collaboration_conversation(conversation_id)
    assert_user_can_participate_in_collaboration_conversation(user_id, collaboration_conversation)
    if not (
        is_personal_collaboration_conversation(collaboration_conversation)
        or is_group_collaboration_conversation(collaboration_conversation)
    ):
        raise PermissionError('Chat file uploads are not supported for this collaborative conversation')

    source_conversation_item, collaboration_conversation = ensure_collaboration_source_conversation(
        collaboration_conversation,
        current_user_info,
    )
    return {
        'conversation_item': source_conversation_item,
        'conversation_id': source_conversation_item.get('id'),
        'response_conversation_id': collaboration_conversation.get('id'),
        'collaboration_conversation': collaboration_conversation,
    }


def _resolve_chat_upload_context(conversation_id, user_id, current_user_info):
    normalized_conversation_id = str(conversation_id or '').strip()
    if not normalized_conversation_id:
        conversation_item = _build_new_chat_conversation(user_id)
        return {
            'conversation_item': conversation_item,
            'conversation_id': conversation_item.get('id'),
            'response_conversation_id': conversation_item.get('id'),
            'collaboration_conversation': None,
        }

    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=normalized_conversation_id,
            partition_key=normalized_conversation_id,
        )
    except CosmosResourceNotFoundError:
        try:
            return _resolve_collaboration_upload_context(
                normalized_conversation_id,
                user_id,
                current_user_info,
            )
        except CosmosResourceNotFoundError:
            conversation_item = _build_new_chat_conversation(user_id)
            return {
                'conversation_item': conversation_item,
                'conversation_id': conversation_item.get('id'),
                'response_conversation_id': conversation_item.get('id'),
                'collaboration_conversation': None,
            }

    collaboration_conversation_id = str(conversation_item.get('collaboration_conversation_id') or '').strip()
    if collaboration_conversation_id:
        collaboration_conversation = get_collaboration_conversation(collaboration_conversation_id)
        assert_user_can_participate_in_collaboration_conversation(user_id, collaboration_conversation)
        if not (
            is_personal_collaboration_conversation(collaboration_conversation)
            or is_group_collaboration_conversation(collaboration_conversation)
        ):
            raise PermissionError('Chat file uploads are not supported for this collaborative conversation')
        return {
            'conversation_item': conversation_item,
            'conversation_id': conversation_item.get('id'),
            'response_conversation_id': collaboration_conversation.get('id'),
            'collaboration_conversation': collaboration_conversation,
        }

    if str(conversation_item.get('user_id') or '').strip() != str(user_id or '').strip():
        raise PermissionError('You do not have access to this conversation')

    return {
        'conversation_item': conversation_item,
        'conversation_id': conversation_item.get('id'),
        'response_conversation_id': conversation_item.get('id'),
        'collaboration_conversation': None,
    }


def _serialize_chat_prompt_option(prompt, *, scope_type, scope_id=None, scope_name=None):
    return {
        'id': prompt.get('id'),
        'name': prompt.get('name', ''),
        'content': prompt.get('content', ''),
        'scope_type': scope_type,
        'scope_id': scope_id,
        'scope_name': scope_name,
    }


def _normalize_chat_model_value(value):
    return str(value or '').strip()


def _is_chat_agent_allowed_by_governance(user_id, agent, scope_type):
    try:
        if scope_type == 'global':
            ensure_governance_access(
                'governance_global_agents_usage',
                user_id,
                item_entity_type='global_agent',
                item_id=str(agent.get('id') or agent.get('name') or ''),
            )
        elif scope_type == 'group':
            ensure_governance_access('governance_group_agents', user_id)
        else:
            ensure_governance_access('governance_user_agents', user_id)
        return True
    except PermissionError:
        return False


def _filter_chat_model_endpoints_by_governance(user_id, endpoints, feature_key):
    try:
        ensure_governance_access(feature_key, user_id)
    except PermissionError:
        return []

    allowed_endpoints = []
    for endpoint in endpoints or []:
        if not isinstance(endpoint, dict):
            continue
        endpoint_id = str(endpoint.get('id') or '').strip()
        if endpoint_id:
            try:
                ensure_governance_access(
                    feature_key,
                    user_id,
                    item_entity_type='global_endpoint',
                    item_id=endpoint_id,
                )
            except PermissionError:
                continue
        allowed_endpoints.append(endpoint)
    return allowed_endpoints


def _build_initial_chat_model_selection(*, chat_model_options, preferred_model_id=None, preferred_model_deployment=None):
    scope_order = {
        'global': 0,
        'personal': 1,
        'group': 2,
    }

    def serialize_option(option):
        if not isinstance(option, dict):
            return None

        selection_key = _normalize_chat_model_value(option.get('selection_key'))
        model_id = _normalize_chat_model_value(option.get('model_id'))
        display_name = _normalize_chat_model_value(
            option.get('display_name') or option.get('deployment_name') or option.get('model_id')
        ) or 'Select a Model'
        deployment_name = _normalize_chat_model_value(option.get('deployment_name'))
        scope_type = _normalize_chat_model_value(option.get('scope_type'))
        scope_name = _normalize_chat_model_value(option.get('scope_name'))

        search_parts = [
            display_name,
            model_id,
            deployment_name,
            scope_name or scope_type,
        ]
        return {
            'selection_key': selection_key,
            'model_id': model_id,
            'display_name': display_name,
            'deployment_name': deployment_name,
            'endpoint_id': _normalize_chat_model_value(option.get('endpoint_id')),
            'provider': _normalize_chat_model_value(option.get('provider')),
            'scope_type': scope_type,
            'scope_id': _normalize_chat_model_value(option.get('scope_id')),
            'scope_name': scope_name,
            'icon': option.get('icon') if isinstance(option.get('icon'), dict) else {},
            'option_value': deployment_name or model_id or selection_key,
            'search_text': ' '.join(part for part in search_parts if part),
        }

    def sort_key(option):
        scope_type = _normalize_chat_model_value(option.get('scope_type'))
        display_name = _normalize_chat_model_value(
            option.get('display_name') or option.get('deployment_name') or option.get('model_id')
        ).lower()
        scope_name = _normalize_chat_model_value(option.get('scope_name')).lower()
        model_id = _normalize_chat_model_value(option.get('model_id')).lower()
        deployment_name = _normalize_chat_model_value(option.get('deployment_name')).lower()
        return (
            scope_order.get(scope_type, 99),
            scope_name,
            display_name,
            model_id,
            deployment_name,
        )

    valid_options = [option for option in (chat_model_options or []) if isinstance(option, dict)]
    if not valid_options:
        return None

    sorted_options = sorted(valid_options, key=sort_key)
    normalized_preferred_model_id = _normalize_chat_model_value(preferred_model_id)
    normalized_preferred_model_deployment = _normalize_chat_model_value(preferred_model_deployment)

    if normalized_preferred_model_id:
        for option in sorted_options:
            selection_key = _normalize_chat_model_value(option.get('selection_key'))
            model_id = _normalize_chat_model_value(option.get('model_id'))
            if selection_key == normalized_preferred_model_id or model_id == normalized_preferred_model_id:
                return serialize_option(option)

    if normalized_preferred_model_deployment:
        for option in sorted_options:
            deployment_name = _normalize_chat_model_value(option.get('deployment_name'))
            if deployment_name == normalized_preferred_model_deployment:
                return serialize_option(option)

    return serialize_option(sorted_options[0])


def _build_chat_model_catalog(*, user_id, settings, user_settings_dict, user_groups_raw):
    if not settings.get('enable_multi_model_endpoints', False):
        return []

    catalog = []

    def append_models(endpoints, scope_type, scope_id=None, scope_name=None):
        sanitized_endpoints = sanitize_model_endpoints_for_frontend(endpoints)
        normalized_endpoints, _ = normalize_model_endpoints(sanitized_endpoints)

        for endpoint in normalized_endpoints:
            if not endpoint.get('enabled', True):
                continue

            endpoint_id = endpoint.get('id') or ''
            provider = endpoint.get('provider') or 'aoai'
            models = endpoint.get('models') or []

            for model in models:
                if not isinstance(model, dict) or not model.get('enabled', True):
                    continue

                model_id = model.get('id') or model.get('deploymentName') or model.get('deployment') or model.get('modelName') or model.get('name') or ''
                deployment_name = model.get('deploymentName') or model.get('deployment') or ''
                display_name = model.get('displayName') or model.get('modelName') or deployment_name or model.get('name') or model_id
                selection_key = f"{scope_type}:{scope_id or ''}:{endpoint_id}:{model_id or deployment_name}"

                catalog.append({
                    'selection_key': selection_key,
                    'model_id': model_id,
                    'display_name': display_name,
                    'deployment_name': deployment_name,
                    'endpoint_id': endpoint_id,
                    'provider': provider,
                    'scope_type': scope_type,
                    'scope_id': scope_id,
                    'scope_name': scope_name,
                    'icon': model.get('icon') if isinstance(model.get('icon'), dict) else {},
                })

    append_models(
        _filter_chat_model_endpoints_by_governance(user_id, settings.get('model_endpoints', []) or [], 'governance_global_endpoints'),
        'global',
        None,
        'Global'
    )

    if settings.get('allow_user_custom_endpoints', False):
        append_models(
            _filter_chat_model_endpoints_by_governance(user_id, user_settings_dict.get('personal_model_endpoints', []) or [], 'governance_user_endpoints'),
            'personal',
            user_id,
            'Personal'
        )

    if settings.get('enable_group_workspaces', False) and settings.get('allow_group_custom_endpoints', False):
        for group_doc in user_groups_raw:
            group_id = group_doc.get('id')
            if not group_id:
                continue
            append_models(
                _filter_chat_model_endpoints_by_governance(user_id, get_group_model_endpoints(group_id), 'governance_group_endpoints'),
                'group',
                group_id,
                group_doc.get('name', 'Unnamed Group')
            )

    return catalog


def _build_chat_prompt_catalog(*, user_id, settings, user_groups_raw, user_visible_public_workspaces):
    catalog = []

    if settings.get('enable_user_workspace', False):
        for prompt in list_all_prompts_for_scope(user_id, 'user_prompt'):
            catalog.append(
                _serialize_chat_prompt_option(
                    prompt,
                    scope_type='personal',
                    scope_id=user_id,
                    scope_name='Personal',
                )
            )

    if settings.get('enable_group_workspaces', False):
        for group_doc in user_groups_raw:
            group_id = group_doc.get('id')
            if not group_id:
                continue

            group_name = group_doc.get('name', 'Unnamed Group')
            for prompt in list_all_prompts_for_scope(
                user_id,
                'group_prompt',
                group_id=group_id,
            ):
                catalog.append(
                    _serialize_chat_prompt_option(
                        prompt,
                        scope_type='group',
                        scope_id=group_id,
                        scope_name=group_name,
                    )
                )

    if settings.get('enable_public_workspaces', False):
        for workspace in user_visible_public_workspaces:
            workspace_id = workspace.get('id')
            if not workspace_id:
                continue

            for prompt in list_all_prompts_for_scope(
                user_id,
                'public_prompt',
                public_workspace_id=workspace_id,
            ):
                catalog.append(
                    _serialize_chat_prompt_option(
                        prompt,
                        scope_type='public',
                        scope_id=workspace_id,
                        scope_name=workspace.get('name', 'Unknown Workspace'),
                    )
                )

    return catalog

def register_route_frontend_chats(app):
    @app.route('/chats', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chats():
        user_id = get_current_user_id()
        if not user_id:
            return redirect(url_for('login'))

        settings = get_settings()
        user_settings = get_user_settings(user_id)
        user_settings_dict = user_settings.get("settings", {}) if isinstance(user_settings, dict) else {}
        public_settings = sanitize_settings_for_user(settings)
        current_user_info = get_current_user_info() or {}
        current_user_roles = (session.get('user') or {}).get('roles', [])
        user_workflows_enabled_for_user = is_user_workflows_enabled_for_user(
            settings,
            user_roles=current_user_roles,
        )
        chat_file_upload_enabled_for_user = is_chat_file_upload_enabled_for_user(settings, current_user_roles)
        source_review_enabled_for_user = is_source_review_enabled_for_user(
            settings,
            user_id,
            user_email=current_user_info.get('email'),
            user_roles=current_user_roles,
        )
        url_access_enabled_for_user = is_url_access_enabled_for_user(
            settings,
            user_roles=current_user_roles,
        )
        for source_review_key in list(public_settings.keys()):
            if source_review_key.startswith('source_review_') or source_review_key == 'enable_deep_source_review':
                public_settings.pop(source_review_key, None)
        public_settings['enable_source_review'] = source_review_enabled_for_user
        public_settings['enable_url_access'] = url_access_enabled_for_user
        public_settings['enable_chat_file_uploads'] = chat_file_upload_enabled_for_user
        public_settings['allow_user_workflows'] = user_workflows_enabled_for_user
        public_settings['enable_deep_source_review'] = bool(
            source_review_enabled_for_user and settings.get('enable_deep_source_review', False)
        )
        deep_research_config = get_deep_research_config(settings)
        public_settings['deep_research_max_user_urls_per_turn'] = deep_research_config.get('deep_research_max_user_urls_per_turn')
        public_settings['deep_research_max_search_queries_per_turn'] = deep_research_config.get('deep_research_max_search_queries_per_turn')
        enable_user_feedback = public_settings.get("enable_user_feedback", False)
        enable_enhanced_citations = public_settings.get("enable_enhanced_citations", False)
        enable_document_classification = public_settings.get("enable_document_classification", False)
        enable_extract_meta_data = public_settings.get("enable_extract_meta_data", False)
        enable_multi_model_endpoints = public_settings.get("enable_multi_model_endpoints", False)
        active_group_id = user_settings_dict.get("activeGroupOid", "")
        active_group_name = ""
        if active_group_id:
            group_doc = find_group_by_id(active_group_id)
            if group_doc:
                active_group_name = group_doc.get("name", "")
        
        # Get active public workspace ID from user settings
        active_public_workspace_id = user_settings_dict.get("activePublicWorkspaceOid", "")
        
        categories_list = public_settings.get("document_classification_categories","")

        multi_endpoint_models = []
        if enable_multi_model_endpoints:
            endpoints = _filter_chat_model_endpoints_by_governance(user_id, settings.get("model_endpoints", []) or [], 'governance_global_endpoints')
            endpoints = sanitize_model_endpoints_for_frontend(endpoints)
            for endpoint in endpoints:
                if not endpoint.get("enabled", True):
                    continue
                for model in endpoint.get("models", []) or []:
                    if not model.get("enabled", True):
                        continue
                    multi_endpoint_models.append({
                        "id": model.get("id"),
                        "display_name": model.get("displayName") or model.get("deploymentName") or model.get("modelName") or "",
                        "deployment_name": model.get("deploymentName") or "",
                        "endpoint_id": endpoint.get("id"),
                        "provider": endpoint.get("provider"),
                        "icon": model.get("icon") if isinstance(model.get("icon"), dict) else {}
                    })

        if not user_id:
            return redirect(url_for('login'))
        
        # Get user display name from user settings
        user_display_name = user_settings.get('display_name', '')

        # Get all groups the user belongs to (for multi-scope selector)
        user_groups_simple = []
        user_groups_raw = []
        try:
            user_groups_raw = get_user_groups(user_id)
            user_groups_simple = [{'id': g['id'], 'name': g.get('name', 'Unnamed')} for g in user_groups_raw]
        except Exception as e:
            logger.warning(f"Failed to load user groups for chats page: {e}")

        # Get visible public workspaces with names (for multi-scope selector)
        user_visible_public_workspaces = []
        try:
            visible_ws_ids = get_user_visible_public_workspace_ids_from_settings(user_id)
            for ws_id in visible_ws_ids:
                ws_doc = find_public_workspace_by_id(ws_id)
                if ws_doc:
                    user_visible_public_workspaces.append({'id': ws_id, 'name': ws_doc.get('name', 'Unknown')})
        except Exception as e:
            logger.warning(f"Failed to load visible public workspaces for chats page: {e}")

        chat_agent_options = []
        try:
            all_chat_agent_options = build_accessible_agent_catalog(
                user_id,
                settings=settings,
                user_groups=user_groups_raw,
            )
            chat_agent_options = [
                agent for agent in all_chat_agent_options
                if _is_chat_agent_allowed_by_governance(
                    user_id,
                    agent,
                    str(agent.get('scope_type') or '').strip().lower() or 'personal',
                )
            ]
        except Exception as e:
            logger.warning(f"Failed to load chat agent options: {e}")

        chat_model_options = []
        try:
            chat_model_options = _build_chat_model_catalog(
                user_id=user_id,
                settings=settings,
                user_settings_dict=user_settings_dict,
                user_groups_raw=user_groups_raw,
            )
        except Exception as e:
            logger.warning(f"Failed to load chat model options: {e}")

        initial_chat_model_selection = _build_initial_chat_model_selection(
            chat_model_options=chat_model_options,
            preferred_model_id=user_settings_dict.get('preferredModelId'),
            preferred_model_deployment=user_settings_dict.get('preferredModelDeployment'),
        )

        chat_prompt_options = []
        try:
            chat_prompt_options = _build_chat_prompt_catalog(
                user_id=user_id,
                settings=settings,
                user_groups_raw=user_groups_raw,
                user_visible_public_workspaces=user_visible_public_workspaces,
            )
        except Exception as e:
            logger.warning(f"Failed to load chat prompt options: {e}")

        return render_template(
            'chats.html',
            settings=public_settings,
            enable_user_feedback=enable_user_feedback,
            active_group_id=active_group_id,
            active_group_name=active_group_name,
            active_public_workspace_id=active_public_workspace_id,
            enable_enhanced_citations=enable_enhanced_citations,
            enable_document_classification=enable_document_classification,
            document_classification_categories=categories_list,
            enable_extract_meta_data=enable_extract_meta_data,
            enable_multi_model_endpoints=enable_multi_model_endpoints,
            multi_endpoint_models=multi_endpoint_models,
            user_id=user_id,
            user_display_name=user_display_name,
            user_groups=user_groups_simple,
            user_visible_public_workspaces=user_visible_public_workspaces,
            chat_prompt_options=chat_prompt_options,
            chat_agent_options=chat_agent_options,
            chat_model_options=chat_model_options,
            initial_chat_model_selection=initial_chat_model_selection,
        )

    @app.route('/workflow-activity', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def workflow_activity():
        user_id = get_current_user_id()
        if not user_id:
            return redirect(url_for('login'))

        settings = get_settings()
        try:
            authorization_error = _authorize_workflow_activity_view(user_id, settings)
            if authorization_error:
                message, status_code = authorization_error
                return message, status_code
        except PermissionError as exc:
            return str(exc), 403
        except LookupError as exc:
            return str(exc), 404
        except ValueError as exc:
            return str(exc), 400

        public_settings = sanitize_settings_for_user(settings)

        return render_template(
            'workflow_activity.html',
            settings=public_settings,
        )
    
    @app.route('/upload', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @file_upload_required
    def upload_file():
        settings = get_settings()
        current_user_roles = (session.get('user') or {}).get('roles', [])
        if not settings.get('enable_chat_file_uploads', True):
            return jsonify({'error': 'Chat file uploads are disabled.'}), 403
        if (
            settings.get('require_member_of_chat_file_upload_user', False)
            and not has_chat_file_upload_app_role(current_user_roles)
        ):
            return jsonify({'error': 'Chat file uploads require the ChatFileUploadUser app role.'}), 403

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        file = request.files['file']
        requested_conversation_id = request.form.get('conversation_id')
        requested_group_ids = _normalize_upload_group_ids(request.form.getlist('upload_scope_group_ids'))
        selected_group_upload_target_id = str(request.form.get('group_upload_target_id') or '').strip()

        if not file.filename:
            return jsonify({'error': 'No selected file'}), 400

        current_user_info = get_current_user_info() or {'userId': user_id}
        try:
            upload_context = _resolve_chat_upload_context(
                requested_conversation_id,
                user_id,
                current_user_info,
            )
        except PermissionError as access_error:
            return jsonify({'error': str(access_error)}), 403
        except Exception as read_error:
            return jsonify({'error': f'Error reading conversation: {str(read_error)}'}), 500

        conversation_item = upload_context['conversation_item']
        conversation_id = upload_context['conversation_id']
        response_conversation_id = upload_context['response_conversation_id']
        collaboration_conversation = upload_context.get('collaboration_conversation')
        is_collaboration_upload = collaboration_conversation is not None
        is_personal_collaboration_upload = bool(
            collaboration_conversation and is_personal_collaboration_conversation(collaboration_conversation)
        )
        is_group_collaboration_upload = bool(
            collaboration_conversation and is_group_collaboration_conversation(collaboration_conversation)
        )
        is_group_workspace_upload_context = _is_group_chat_upload_context(
            conversation_item,
            collaboration_conversation,
            requested_group_ids=requested_group_ids,
        )
        group_upload_target = None
        if is_group_workspace_upload_context:
            targets = []
            try:
                group_upload_target = _resolve_group_workspace_upload_target(
                    conversation_item=conversation_item,
                    collaboration_conversation=collaboration_conversation,
                    requested_group_ids=requested_group_ids,
                    selected_group_id=selected_group_upload_target_id,
                    user_id=user_id,
                )
            except ValueError as selection_error:
                targets, _ = _resolve_group_upload_targets(
                    conversation_item,
                    collaboration_conversation,
                    requested_group_ids,
                    user_id,
                )
                return jsonify({
                    'error': str(selection_error),
                    'requires_group_upload_target': True,
                    'group_upload_targets': targets,
                }), 400
            except PermissionError as target_error:
                return jsonify({'error': str(target_error)}), 403
        
        file.seek(0, os.SEEK_END)
        file_length = file.tell()
        max_file_size_bytes = settings.get('max_file_size_mb') * 1024 * 1024
        if file_length > max_file_size_bytes:
            return jsonify({'error': 'File size exceeds maximum allowed size'}), 400
        file.seek(0)

        filename = secure_filename(file.filename)
        file_ext = os.path.splitext(filename)[1].lower()  # e.g., '.png'
        file_ext_nodot = file_ext.lstrip('.')              # e.g., 'png'
        original_filename = file.filename
        file_message_id = f"{conversation_id}_file_{int(time.time())}_{random.randint(1000,9999)}"

        with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
            file.save(tmp_file.name)
            temp_file_path = tmp_file.name

        workspace_document_info = None
        workspace_upload_scope = 'group' if group_upload_target else 'personal'
        workspace_upload_enabled = _is_setting_enabled(settings.get('enable_group_workspaces', False)) if group_upload_target else _is_setting_enabled(settings.get('enable_user_workspace', False))
        workspace_upload_supported = file_ext_nodot in CHAT_WORKSPACE_UPLOAD_EXTENSIONS and allowed_file(original_filename)

        if group_upload_target and not workspace_upload_enabled:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            return jsonify({'error': 'Group workspace uploads are disabled.'}), 403

        if group_upload_target and not workspace_upload_supported:
            if temp_file_path and os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            return jsonify({'error': 'This file type is not supported for group workspace chat uploads.'}), 400

        if workspace_upload_enabled and workspace_upload_supported:
            try:
                if group_upload_target:
                    _apply_group_context_to_new_upload_conversation(conversation_item, group_upload_target)
                    source_metadata = {
                        'source_type': 'chat_upload',
                        'source_subtype': 'group_collaboration_conversation_attachment' if is_group_collaboration_upload else 'group_conversation_attachment',
                        'created_from_chat_upload': True,
                        'chat_upload_delete_with_conversation': True,
                        'chat_upload_link_state': 'linked',
                        'chat_upload_linked_at': datetime.utcnow().isoformat(),
                        'conversation_id': conversation_id,
                        'conversation_title_at_upload': collaboration_conversation.get('title') if is_collaboration_upload else conversation_item.get('title', 'New Conversation'),
                        'conversation_url': f"/chats?conversation_id={response_conversation_id}",
                        'chat_message_id': file_message_id,
                        'chat_upload_original_filename': original_filename,
                        'chat_upload_sanitized_filename': filename,
                        'chat_upload_group_id': group_upload_target.get('id'),
                        'chat_upload_group_name': group_upload_target.get('name'),
                    }
                    if is_group_collaboration_upload:
                        source_metadata.update({
                            'chat_upload_collaboration_conversation_id': collaboration_conversation.get('id'),
                            'chat_upload_collaboration_source_conversation_id': conversation_id,
                            'collaboration_conversation_id': collaboration_conversation.get('id'),
                        })

                    workspace_document_info = queue_group_workspace_upload_from_temp_file(
                        user_id=user_id,
                        group_id=group_upload_target.get('id'),
                        temp_file_path=temp_file_path,
                        original_filename=original_filename,
                        tags=build_chat_upload_workspace_tags(conversation_id),
                        source_metadata=source_metadata,
                        copy_source_file=True,
                        ensure_unique_file_name=True,
                        unique_file_name_suffix=file_message_id.rsplit('_file_', 1)[-1],
                    )
                    workspace_document_info['scope'] = 'group'
                    workspace_document_info['group_name'] = group_upload_target.get('name')
                    invalidate_group_search_cache(group_upload_target.get('id'))
                else:
                    source_metadata = {
                        'source_type': 'chat_upload',
                        'source_subtype': 'personal_collaboration_conversation_attachment' if is_personal_collaboration_upload else 'personal_conversation_attachment',
                        'created_from_chat_upload': True,
                        'chat_upload_delete_with_conversation': True,
                        'chat_upload_link_state': 'linked',
                        'chat_upload_linked_at': datetime.utcnow().isoformat(),
                        'conversation_id': conversation_id,
                        'conversation_title_at_upload': collaboration_conversation.get('title') if is_collaboration_upload else conversation_item.get('title', 'New Conversation'),
                        'conversation_url': f"/chats?conversation_id={response_conversation_id}",
                        'chat_message_id': file_message_id,
                        'chat_upload_original_filename': original_filename,
                        'chat_upload_sanitized_filename': filename,
                    }
                    if is_personal_collaboration_upload:
                        source_metadata.update({
                            'chat_upload_collaboration_conversation_id': collaboration_conversation.get('id'),
                            'chat_upload_collaboration_source_conversation_id': conversation_id,
                            'collaboration_conversation_id': collaboration_conversation.get('id'),
                        })

                    workspace_document_info = queue_personal_workspace_upload_from_temp_file(
                        user_id=user_id,
                        temp_file_path=temp_file_path,
                        original_filename=original_filename,
                        tags=build_chat_upload_workspace_tags(conversation_id),
                        source_metadata=source_metadata,
                        copy_source_file=True,
                        ensure_unique_file_name=True,
                        unique_file_name_suffix=file_message_id.rsplit('_file_', 1)[-1],
                    )
                    workspace_document_info['scope'] = 'personal'
                    invalidate_personal_search_cache(user_id)
                    if is_personal_collaboration_upload:
                        sharing_result = sync_chat_upload_workspace_document_sharing_for_collaboration(collaboration_conversation)
                        for affected_user_id in sharing_result.get('affected_user_ids', []):
                            invalidate_personal_search_cache(affected_user_id)
            except Exception as workspace_error:
                log_event(
                    f"[ChatUpload] Failed to queue workspace document for {filename}: {workspace_error}",
                    {
                        'conversation_id': response_conversation_id,
                        'source_conversation_id': conversation_id,
                        'filename': filename,
                    },
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )
                if temp_file_path and os.path.exists(temp_file_path):
                    try:
                        os.remove(temp_file_path)
                    except Exception as cleanup_error:
                        debug_print(f"Unable to clean up chat upload temp file after workspace queue failure: {cleanup_error}")
                return jsonify({
                    'error': f"File could not be queued in the {workspace_upload_scope} workspace. Please try again."
                }), 500

        if workspace_document_info:
            try:
                workspace_file_name = workspace_document_info.get('file_name') or filename
                workspace_scope = workspace_document_info.get('scope') or workspace_upload_scope
                workspace_label = 'group workspace' if workspace_scope == 'group' else 'personal workspace'
                workspace_url = f"/workspace?document_id={workspace_document_info.get('document_id')}"
                if workspace_scope == 'group':
                    workspace_url = (
                        f"/group_workspaces?document_id={workspace_document_info.get('document_id')}"
                        f"&group_id={workspace_document_info.get('group_id') or ''}"
                    )
                workspace_attachment = {
                    'document_id': workspace_document_info.get('document_id'),
                    'file_name': workspace_file_name,
                    'status': workspace_document_info.get('status', 'Queued for processing'),
                    'percentage_complete': workspace_document_info.get('percentage_complete', 0),
                    'tags': workspace_document_info.get('tags', []),
                    'workspace_url': workspace_url,
                    'conversation_url': f"/chats?conversation_id={response_conversation_id}",
                    'scope': workspace_scope,
                    'group_id': workspace_document_info.get('group_id'),
                    'group_name': workspace_document_info.get('group_name'),
                    'link_state': 'linked',
                }

                previous_thread_id = None
                try:
                    last_msg_query = f"SELECT TOP 1 c.metadata.thread_info.thread_id as thread_id FROM c WHERE c.conversation_id = '{conversation_id}' ORDER BY c.timestamp DESC"
                    last_msgs = list(cosmos_messages_container.query_items(query=last_msg_query, partition_key=conversation_id))
                    if last_msgs:
                        previous_thread_id = last_msgs[0].get('thread_id')
                except Exception as thread_error:
                    debug_print(f"Unable to resolve previous thread for workspace-backed upload: {thread_error}")

                current_thread_id = str(uuid.uuid4())
                timestamp = datetime.utcnow().isoformat()
                file_message = {
                    'id': file_message_id,
                    'conversation_id': conversation_id,
                    'role': 'file',
                    'filename': workspace_file_name,
                    'content': f"Uploaded {workspace_file_name} to the {workspace_label}.",
                    'file_content_source': 'workspace',
                    'workspace_document_id': workspace_document_info.get('document_id'),
                    'is_table': file_ext_nodot in TABULAR_EXTENSIONS,
                    'timestamp': timestamp,
                    'created_at': timestamp,
                    'model_deployment_name': None,
                    'metadata': {
                        'is_user_upload': True,
                        'upload_source': f'{workspace_scope}_workspace',
                        'user_info': current_user_info,
                        'workspace_attachment': workspace_attachment,
                        'thread_info': {
                            'thread_id': current_thread_id,
                            'previous_thread_id': previous_thread_id,
                            'active_thread': True,
                            'thread_attempt': 1
                        }
                    }
                }
                cosmos_messages_container.upsert_item(file_message)

                if is_collaboration_upload:
                    try:
                        mirrored_message, collaboration_conversation, _ = mirror_source_message_to_collaboration(
                            collaboration_conversation,
                            file_message,
                            current_user_info,
                            extra_metadata={
                                'source_conversation_id': conversation_id,
                                'source_thought_user_id': user_id,
                            },
                        )
                        if mirrored_message:
                            create_collaboration_message_notifications(collaboration_conversation, mirrored_message)
                            serialized_message = serialize_collaboration_message(mirrored_message)
                            serialized_conversation = serialize_collaboration_conversation(
                                collaboration_conversation,
                                current_user_id=user_id,
                            )
                            publish_collaboration_event(
                                response_conversation_id,
                                {
                                    'conversation_id': response_conversation_id,
                                    'event_type': 'collaboration.message.created',
                                    'occurred_at': datetime.utcnow().isoformat(),
                                    'payload': {
                                        'conversation': serialized_conversation,
                                        'message': serialized_message,
                                    },
                                },
                            )
                    except Exception as mirror_error:
                        log_event(
                            f"[ChatUpload] Failed to mirror workspace upload into collaboration {response_conversation_id}: {mirror_error}",
                            {
                                'conversation_id': response_conversation_id,
                                'source_conversation_id': conversation_id,
                                'file_message_id': file_message_id,
                            },
                            level=logging.WARNING,
                            exceptionTraceback=True,
                        )

                conversation_item['last_updated'] = timestamp
                try:
                    if conversation_item.get('title') == 'New Conversation':
                        count_query = f"SELECT VALUE COUNT(1) FROM c WHERE c.conversation_id = '{conversation_id}'"
                        message_counts = list(cosmos_messages_container.query_items(query=count_query, partition_key=conversation_id))
                        message_count = message_counts[0] if message_counts else 0

                        if message_count <= 1:
                            base_filename = os.path.splitext(workspace_file_name)[0]
                            conversation_item['title'] = base_filename[:50] if len(base_filename) > 50 else base_filename
                except Exception as title_error:
                    debug_print(f"Unable to auto-generate conversation title from workspace-backed upload: {title_error}")

                cosmos_conversations_container.upsert_item(conversation_item)

            except Exception as e:
                return jsonify({
                    'error': f'Error adding workspace-backed file to conversation: {str(e)}'
                }), 500
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    os.remove(temp_file_path)

            return jsonify({
                'message': f"File uploaded to the {workspace_label} and added to the conversation successfully",
                'conversation_id': response_conversation_id,
                'source_conversation_id': conversation_id if is_collaboration_upload else None,
                'collaboration_conversation_id': collaboration_conversation.get('id') if is_collaboration_upload else None,
                'is_collaboration_upload': is_collaboration_upload,
                'workspace_scope': workspace_scope,
                'group_upload_target': group_upload_target,
                'title': collaboration_conversation.get('title') if is_collaboration_upload else conversation_item.get('title', 'New Conversation'),
                'workspace_document': workspace_document_info,
                'workspace_document_id': workspace_document_info.get('document_id')
            }), 200

        extracted_content  = ''
        is_table = False 
        vision_analysis = None
        image_base64_url = None  # For storing base64-encoded images
        image_bytes = None
        image_mime_type = None

        try:
            # Check if this is an image file
            is_image_file = file_ext_nodot in IMAGE_EXTENSIONS
            
            if file_ext_nodot in (DOCUMENT_EXTENSIONS | {'html'}) or is_image_file:
                extraction_mode = 'read'
                if file_ext == '.pdf' or is_image_file:
                    extraction_mode = get_document_intelligence_pdf_image_extraction_mode(settings)
                    if extraction_mode == 'auto':
                        extraction_mode = 'layout' if is_image_file else 'read'
                extracted_content_raw  = extract_content_with_azure_di(
                    temp_file_path,
                    extraction_mode=extraction_mode
                )
                
                # Convert pages_data list to string
                if isinstance(extracted_content_raw, list):
                    extracted_content = "\n\n".join([
                        f"[Page {page.get('page_number', 'N/A')}]\n{page.get('content', '')}"
                        for page in extracted_content_raw
                    ])
                else:
                    extracted_content = str(extracted_content_raw)
                
                # For images, either store blob-backed bytes or convert to base64 for legacy inline display.
                if is_image_file:
                    try:
                        image_mime_type = mimetypes.guess_type(filename)[0] or 'image/png'
                        with open(temp_file_path, 'rb') as img_file:
                            image_bytes = img_file.read()

                        if settings.get('enable_enhanced_citations', False):
                            log_event(
                                "[ChatUpload] Prepared image bytes for blob-backed chat storage",
                                {
                                    "conversation_id": conversation_id,
                                    "filename": filename,
                                    "content_type": image_mime_type,
                                    "image_size": len(image_bytes),
                                },
                                debug_only=True,
                            )
                        else:
                            base64_image = base64.b64encode(image_bytes).decode('utf-8')
                            image_base64_url = f"data:{image_mime_type};base64,{base64_image}"
                            print(f"Converted image to base64: {filename}, size: {len(image_base64_url)} bytes")
                    except Exception as b64_error:
                        print(f"Warning: Failed to convert image to base64: {b64_error}")
                
                # Perform vision analysis for images if enabled
                if is_image_file and settings.get('enable_multimodal_vision', False):
                    try:
                        from functions_documents import analyze_image_with_vision_model
                        
                        vision_analysis = analyze_image_with_vision_model(
                            temp_file_path,
                            user_id,
                            f"chat_upload_{int(time.time())}",
                            settings
                        )
                        
                        if vision_analysis:
                            # Combine DI OCR with vision analysis
                            vision_description = vision_analysis.get('description', '')
                            vision_objects = vision_analysis.get('objects', [])
                            vision_text = vision_analysis.get('text', '')
                            
                            extracted_content += f"\n\n=== AI Vision Analysis ===\n"
                            extracted_content += f"Description: {vision_description}\n"
                            if vision_objects:
                                extracted_content += f"Objects detected: {', '.join(vision_objects)}\n"
                            if vision_text:
                                extracted_content += f"Text visible in image: {vision_text}\n"
                            
                            print(f"Vision analysis added to chat upload: {filename}")
                    except Exception as vision_error:
                        print(f"Warning: Vision analysis failed for chat upload: {vision_error}")
                        # Continue without vision analysis
                
            elif file_ext_nodot in {'doc', 'docm'}:
                # Use OLE parsing for legacy .doc files and docx2txt for .docm files
                try:
                    extracted_content = extract_word_text(temp_file_path, f'.{file_ext_nodot}')
                except Exception as e:
                    return jsonify({'error': f'Error extracting text from {filename}: {e}'}), 500
            elif file_ext_nodot == 'msg':
                try:
                    extracted_content = extract_outlook_msg_text(temp_file_path)
                except Exception as e:
                    return jsonify({'error': f'Error extracting text from {filename}: {e}'}), 500
            elif file_ext_nodot == 'txt':
                extracted_content  = extract_text_file(temp_file_path)
            elif file_ext_nodot == 'md':
                extracted_content  = extract_markdown_file(temp_file_path)
            elif file_ext_nodot == 'json':
                with open(temp_file_path, 'r', encoding='utf-8') as f:
                    parsed_json = json.load(f)
                    extracted_content  = json.dumps(parsed_json, indent=2)
            elif file_ext_nodot in {'xml', 'yaml', 'yml', 'log'}:
                # Handle XML, YAML, and LOG files as text for inline chat
                extracted_content  = extract_text_file(temp_file_path)
            elif file_ext_nodot in TABULAR_EXTENSIONS:
                is_table = True

                # Upload tabular file to blob storage for tabular processing plugin access
                if settings.get('enable_enhanced_citations', False):
                    try:
                        blob_service_client = CLIENTS.get("storage_account_office_docs_client")
                        if blob_service_client:
                            blob_path = f"{user_id}/{conversation_id}/{filename}"
                            blob_client = blob_service_client.get_blob_client(
                                container=storage_account_personal_chat_container_name,
                                blob=blob_path
                            )
                            metadata = {
                                "conversation_id": str(conversation_id),
                                "user_id": str(user_id)
                            }
                            with open(temp_file_path, "rb") as blob_f:
                                blob_client.upload_blob(blob_f, overwrite=True, metadata=metadata)
                            log_event(f"Uploaded chat tabular file to blob storage: {blob_path}")
                    except Exception as blob_err:
                        log_event(
                            f"Warning: Failed to upload chat tabular file to blob storage: {blob_err}",
                            level=logging.WARNING
                        )
                else:
                    # Only extract content for Cosmos storage when enhanced citations is disabled
                    extracted_content = extract_table_file(temp_file_path, file_ext)
            else:
                return jsonify({'error': 'Unsupported file type'}), 400

        except Exception as e:
            return jsonify({'error': f'Error processing file: {str(e)}'}), 500
        finally:
            os.remove(temp_file_path)

        try:
            workspace_attachment = None
            if workspace_document_info:
                workspace_attachment = {
                    'document_id': workspace_document_info.get('document_id'),
                    'file_name': workspace_document_info.get('file_name'),
                    'status': workspace_document_info.get('status', 'Queued for processing'),
                    'percentage_complete': workspace_document_info.get('percentage_complete', 0),
                    'tags': workspace_document_info.get('tags', []),
                    'workspace_url': f"/workspace?document_id={workspace_document_info.get('document_id')}",
                    'conversation_url': f"/chats?conversation_id={conversation_id}",
                }

            # For images, store blob-backed references when enhanced citations is enabled.
            if image_base64_url or image_bytes:
                previous_thread_id = None
                try:
                    last_msg_query = f"SELECT TOP 1 c.metadata.thread_info.thread_id as thread_id FROM c WHERE c.conversation_id = '{conversation_id}' ORDER BY c.timestamp DESC"
                    last_msgs = list(cosmos_messages_container.query_items(query=last_msg_query, partition_key=conversation_id))
                    if last_msgs:
                        previous_thread_id = last_msgs[0].get('thread_id')
                except Exception:
                    pass

                current_thread_id = str(uuid.uuid4())
                image_message = {
                    'id': file_message_id,
                    'conversation_id': conversation_id,
                    'filename': filename,
                    'prompt': f"User uploaded: {filename}",
                    'created_at': datetime.utcnow().isoformat(),
                    'timestamp': datetime.utcnow().isoformat(),
                    'model_deployment_name': None,
                    'metadata': {
                        'is_user_upload': True,
                        'thread_info': {
                            'thread_id': current_thread_id,
                            'previous_thread_id': previous_thread_id,
                            'active_thread': True,
                            'thread_attempt': 1
                        }
                    }
                }
                if workspace_attachment:
                    image_message['metadata']['workspace_attachment'] = workspace_attachment

                if vision_analysis:
                    image_message['vision_analysis'] = vision_analysis
                if extracted_content:
                    image_message['extracted_text'] = extracted_content

                if image_bytes and settings.get('enable_enhanced_citations', False):
                    blob_image_info = upload_chat_image_bytes_for_user(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_id=file_message_id,
                        file_name=filename,
                        image_bytes=image_bytes,
                        content_type=image_mime_type or 'image/png',
                        image_source='upload',
                    )
                    image_message.update({
                        'role': 'image',
                        'content': blob_image_info['content'],
                        'filename': blob_image_info['filename'],
                        'file_content_source': blob_image_info['file_content_source'],
                        'blob_container': blob_image_info['blob_container'],
                        'blob_path': blob_image_info['blob_path'],
                        'mime_type': blob_image_info['mime_type'],
                    })
                    image_message['metadata']['is_chunked'] = False
                    image_message['metadata']['is_blob_backed'] = True
                    image_message['metadata']['original_size'] = blob_image_info['image_size']
                    cosmos_messages_container.upsert_item(image_message)
                    log_event(
                        "[ChatUpload] Created blob-backed image message",
                        {
                            "conversation_id": conversation_id,
                            "message_id": file_message_id,
                            "filename": blob_image_info['filename'],
                        },
                        debug_only=True,
                    )
                else:
                    image_message['content'] = image_base64_url
                    image_documents = build_image_message_documents(image_message)
                    for image_document in image_documents:
                        cosmos_messages_container.upsert_item(image_document)

                    if image_documents[0].get('metadata', {}).get('is_chunked'):
                        print(f"Created {len(image_documents)} chunked image documents for {filename}")
                    else:
                        print(f"Created single image document for {filename}")
            else:
                # Non-image file or failed to convert to base64, store as 'file' role
                # Threading logic for file upload
                previous_thread_id = None
                try:
                    last_msg_query = f"SELECT TOP 1 c.metadata.thread_info.thread_id as thread_id FROM c WHERE c.conversation_id = '{conversation_id}' ORDER BY c.timestamp DESC"
                    last_msgs = list(cosmos_messages_container.query_items(query=last_msg_query, partition_key=conversation_id))
                    if last_msgs:
                        previous_thread_id = last_msgs[0].get('thread_id')
                except Exception as ex:
                    pass

                current_thread_id = str(uuid.uuid4())
                
                # When enhanced citations is enabled and file is tabular, store a lightweight
                # reference without file_content to avoid Cosmos DB size limits.
                # The tabular data lives in blob storage and is served from there.
                if is_table and settings.get('enable_enhanced_citations', False):
                    file_message = {
                        'id': file_message_id,
                        'conversation_id': conversation_id,
                        'role': 'file',
                        'filename': filename,
                        'is_table': is_table,
                        'file_content_source': 'blob',
                        'blob_container': storage_account_personal_chat_container_name,
                        'blob_path': f"{user_id}/{conversation_id}/{filename}",
                        'timestamp': datetime.utcnow().isoformat(),
                        'model_deployment_name': None,
                        'metadata': {
                            'thread_info': {
                                'thread_id': current_thread_id,
                                'previous_thread_id': previous_thread_id,
                                'active_thread': True,
                                'thread_attempt': 1
                            }
                        }
                    }
                    if workspace_attachment:
                        file_message['metadata']['workspace_attachment'] = workspace_attachment
                else:
                    file_message = {
                        'id': file_message_id,
                        'conversation_id': conversation_id,
                        'role': 'file',
                        'filename': filename,
                        'file_content': extracted_content,
                        'is_table': is_table,
                        'timestamp': datetime.utcnow().isoformat(),
                        'model_deployment_name': None,
                        'metadata': {
                            'thread_info': {
                                'thread_id': current_thread_id,
                                'previous_thread_id': previous_thread_id,
                                'active_thread': True,
                                'thread_attempt': 1
                            }
                        }
                    }
                    if workspace_attachment:
                        file_message['metadata']['workspace_attachment'] = workspace_attachment

                # Add vision analysis if available
                if vision_analysis:
                    file_message['vision_analysis'] = vision_analysis

                cosmos_messages_container.upsert_item(file_message)

            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            
            # Check if this is the first message in the conversation (excluding the current file upload)
            # and update conversation title based on filename if it's still "New Conversation"
            try:
                if conversation_item.get('title') == 'New Conversation':
                    # Query to count existing messages (excluding the one we just created)
                    count_query = f"SELECT VALUE COUNT(1) FROM c WHERE c.conversation_id = '{conversation_id}'"
                    message_counts = list(cosmos_messages_container.query_items(query=count_query, partition_key=conversation_id))
                    message_count = message_counts[0] if message_counts else 0
                    
                    # If this is the first or only message, set title based on filename
                    if message_count <= 1:
                        # Remove file extension and create a clean title
                        base_filename = os.path.splitext(filename)[0]
                        # Limit title length to 50 characters
                        new_title = base_filename[:50] if len(base_filename) > 50 else base_filename
                        conversation_item['title'] = new_title
                        print(f"Auto-generated conversation title from filename: {new_title}")
            except Exception as title_error:
                # Don't fail the upload if title generation fails
                print(f"Warning: Failed to auto-generate conversation title: {title_error}")
            
            cosmos_conversations_container.upsert_item(conversation_item)

        except Exception as e:
            return jsonify({
                'error': f'Error adding file to conversation: {str(e)}'
            }), 500

        return jsonify({
            'message': 'File added to the conversation successfully',
            'conversation_id': conversation_id,
            'title': conversation_item.get('title', 'New Conversation'),
            'workspace_document': workspace_document_info,
            'workspace_document_id': workspace_document_info.get('document_id') if workspace_document_info else None
        }), 200
    
    # THIS IS THE OLD ROUTE, KEEPING IT FOR REFERENCE, WILL DELETE LATER
    @app.route("/view_pdf", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def view_pdf():
        """
        1) Grab 'doc_id' and 'page' from query params.
        2) Validate user and doc_id ownership.
        3) Generate SAS URL for the PDF in Azure Blob Storage.
        4) Download the file to a temp location or memory.
        5) (Optional) Use PyMuPDF to do further operations (like extracting a single page).
        6) Return the PDF file via send_file.
        """

        # 1) Get query params
        doc_id = request.args.get("doc_id")
        page_number = request.args.get("page", default=1, type=int)

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        # 2) Validate doc_id -> get the blob name
        #    For example, doc_id references the DB row that includes user_id & file_name
        doc_response, status_code = get_document(user_id, doc_id)
        if status_code != 200:
            return doc_response, status_code

        raw_doc = doc_response.get_json()
        
        # Determine workspace type and appropriate container
        settings = get_settings()
        if raw_doc.get('public_workspace_id'):
            if not settings.get('enable_public_workspaces', False):
                return jsonify({"error": "Public workspaces are not enabled"}), 403
            container_name = storage_account_public_documents_container_name
            blob_name = f"{raw_doc['public_workspace_id']}/{raw_doc['file_name']}"
        elif raw_doc.get('group_id'):
            if not settings.get('enable_group_workspaces', False):
                return jsonify({"error": "Group workspaces are not enabled"}), 403
            container_name = storage_account_group_documents_container_name
            blob_name = f"{raw_doc['group_id']}/{raw_doc['file_name']}"
        else:
            if not settings.get('enable_user_workspace', False):
                return jsonify({"error": "User workspaces are not enabled"}), 403
            container_name = storage_account_user_documents_container_name
            blob_name = f"{raw_doc['user_id']}/{raw_doc['file_name']}"

        # 3) Generate the SAS URL (short-lived, read-only)
        blob_service_client = CLIENTS.get("storage_account_office_docs_client")
        container_client = blob_service_client.get_container_client(container_name)

        sas_token = generate_blob_sas(
            account_name=blob_service_client.account_name,
            container_name=container_client.container_name,
            blob_name=blob_name,
            account_key=settings.get("office_docs_key"),
            permission=BlobSasPermissions(read=True),
            expiry=datetime.utcnow() + timedelta(minutes=60)  # 60-minute expiry
        )

        signed_url = (
            f"https://{blob_service_client.account_name}.blob.core.windows.net"
            f"/{container_client.container_name}/{blob_name}?{sas_token}"
        )

        if AZURE_ENVIRONMENT == "usgovernment":
            signed_url = (
                f"https://{blob_service_client.account_name}.blob.core.usgovcloudapi.net"
                f"/{container_client.container_name}/{blob_name}?{sas_token}"
            )

        if AZURE_ENVIRONMENT == "custom":
            signed_url = (
                f"https://{blob_service_client.account_name}.{CUSTOM_BLOB_STORAGE_URL_VALUE}"
                f"/{container_client.container_name}/{blob_name}?{sas_token}"
            )

        # 4) Download the PDF from Azure to a temp file (or you can use in-memory BytesIO)
        random_uuid = str(uuid.uuid4())
        temp_pdf_path = f"temp_file_{random_uuid}.pdf"

        try:
            # Download the PDF
            r = requests.get(signed_url, timeout=30)
            r.raise_for_status()
            with open(temp_pdf_path, "wb") as f:
                f.write(r.content)

            # 3) Extract up to three pages: (page-1, page, page+1)
            pdf_document = fitz.open(temp_pdf_path)
            total_pages = pdf_document.page_count
            current_idx = page_number - 1  # zero-based

            if current_idx < 0 or current_idx >= total_pages:
                pdf_document.close()
                os.remove(temp_pdf_path)
                return jsonify({"error": "Requested page out of range"}), 400

            # Default to just the current page
            start_idx = current_idx
            end_idx = current_idx

            # If a previous page exists, include it
            if current_idx > 0:
                start_idx = current_idx - 1

            # If a next page exists, include it
            if current_idx < total_pages - 1:
                end_idx = current_idx + 1

            # 4) Create new PDF with only start_idx..end_idx
            extracted_pdf = fitz.open()
            extracted_pdf.insert_pdf(pdf_document, from_page=start_idx, to_page=end_idx)
            extracted_pdf.save(temp_pdf_path, garbage=4, deflate=True)
            extracted_pdf.close()
            pdf_document.close()

            # 5) Determine new_page_number (within the sub-document)
            extracted_count = end_idx - start_idx + 1
            
            if extracted_count == 1:
                # Only current page
                new_page_number = 1
            elif extracted_count == 3:
                # current page is in the middle
                new_page_number = 2
            else:
                # Exactly 2 pages
                # If start_idx == current_idx, the user is on the first page
                # If current_idx == end_idx, the user is on the second page
                if start_idx == current_idx:
                    # e.g. pages = [current, next]
                    new_page_number = 1
                else:
                    # e.g. pages = [previous, current]
                    new_page_number = 2

            # 6) Return the sub-PDF, attaching a custom header with new_page_number
            response = send_file(temp_pdf_path, as_attachment=False)
            response.headers["X-Sub-PDF-Page"] = str(new_page_number)
            return response

        except Exception as e:
            # Clean up on error
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)
            return jsonify({"error": str(e)}), 500
        finally:
            # Clean up the temp file after the request finishes
            # (You can also do this in an after_request or teardown block.)
            if os.path.exists(temp_pdf_path):
                os.remove(temp_pdf_path)

    # --- Updated route ---
    @app.route('/view_document')
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def view_document():
        settings = get_settings()
        download_location = tempfile.gettempdir()


        doc_id = request.args.get("doc_id")
        page_number = request.args.get("page", default=1, type=int) # Keep page, useful for PDFs

        if not doc_id:
            return jsonify({'error': 'doc_id parameter is required'}), 400

        user_id = get_current_user_id()
        if not user_id:
             return jsonify({"error": "User not authenticated"}), 401 # Should be caught by @login_required anyway

        # Fetch Document Metadata (assuming get_user_document handles user auth checks implicitly)
        doc_response, status_code = get_document(user_id, doc_id)
        if status_code != 200:
            # Pass through the error response from get_user_document
            return doc_response, status_code

        raw_doc = doc_response.get_json() # Assuming get_user_document returns jsonify response
        file_name = raw_doc.get('file_name')
        owner_user_id = raw_doc.get('user_id') # Get owner user_id from doc metadata

        if not file_name:
             return jsonify({"error": "Internal server error: Document metadata incomplete."}), 500

        # Determine workspace type and appropriate container
        if raw_doc.get('public_workspace_id'):
            if not settings.get('enable_public_workspaces', False):
                return jsonify({"error": "Public workspaces are not enabled"}), 403
            container_name = storage_account_public_documents_container_name
            blob_name = f"{raw_doc['public_workspace_id']}/{file_name}"
        elif raw_doc.get('group_id'):
            if not settings.get('enable_group_workspaces', False):
                return jsonify({"error": "Group workspaces are not enabled"}), 403
            container_name = storage_account_group_documents_container_name
            blob_name = f"{raw_doc['group_id']}/{file_name}"
        else:
            if not settings.get('enable_user_workspace', False):
                return jsonify({"error": "User workspaces are not enabled"}), 403
            container_name = storage_account_user_documents_container_name
            blob_name = f"{owner_user_id}/{file_name}"
        file_ext = os.path.splitext(file_name)[-1].lower()

        # Ensure download location exists (good practice, especially if using mount)
        try:
            os.makedirs(download_location, exist_ok=True)
        except OSError as e:
             return jsonify({"error": "Internal server error: Cannot access storage location."}), 500

        # Generate the SAS URL
        try:
            # Ensure CLIENTS dictionary and keys are correctly configured
            blob_service_client = CLIENTS.get("storage_account_office_docs_client")
            storage_account_key = settings.get("office_docs_key")
            storage_account_name = blob_service_client.account_name # Get from client

            if not all([blob_service_client, storage_account_key, container_name]):
                return jsonify({"error": "Internal server error: Storage access not configured."}), 500

            sas_token = generate_blob_sas(
                account_name=storage_account_name,
                container_name=container_name,
                blob_name=blob_name,
                account_key=storage_account_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.utcnow() + timedelta(minutes=10) # Short expiry for view access
            )

            # Construct signed URL based on Azure environment
            endpoint_suffix = "blob.core.windows.net"
            if AZURE_ENVIRONMENT == "usgovernment":
                 endpoint_suffix = "blob.core.usgovcloudapi.net"
            if AZURE_ENVIRONMENT == "custom":
                endpoint_suffix = CUSTOM_BLOB_STORAGE_URL_VALUE

            signed_url = (
                f"https://{storage_account_name}.{endpoint_suffix}"
                f"/{container_name}/{blob_name}?{sas_token}"
            )

        except Exception as e:
            return jsonify({"error": "Internal server error: Could not authorize document access."}), 500

        # Define the target path within the download location
        random_uuid = str(uuid.uuid4())
        # Use a unique filename within the download location to avoid collisions
        local_file_name = f"{random_uuid}_{secure_filename(file_name)}" # Use secure_filename here too
        local_file_path = os.path.join(download_location, local_file_name)

        # Define supported types for direct viewing/handling
        is_pdf = file_ext == '.pdf'
        is_word = file_ext in ('.docx', '.doc', '.docm')
        is_ppt = file_ext in ('.pptx', '.ppt')
        is_image = file_ext.lstrip('.') in (IMAGE_EXTENSIONS | {'gif', 'webp'}) # Added more image types
        is_text = file_ext.lstrip('.') in (BASE_ALLOWED_EXTENSIONS - {'doc', 'docm'}) # Common text-based types

        try:
            # Download the file to the specified location
            r = requests.get(signed_url, timeout=60)
            r.raise_for_status() # Raises HTTPError for bad responses (4xx or 5xx)
            with open(local_file_path, "wb") as f:
                f.write(r.content)

            # --- PDF Handling ---
            if is_pdf:
                pdf_document = None # Initialize
                extracted_pdf = None # Initialize
                try:
                    pdf_document = fitz.open(local_file_path)
                    total_pages = pdf_document.page_count
                    current_idx = page_number - 1 # PyMuPDF uses 0-based index

                    if current_idx < 0 or current_idx >= total_pages:
                        return jsonify({"error": f"Requested page ({page_number}) out of range (Total: {total_pages})"}), 400

                    # Determine pages to extract (+/- 1 page)
                    start_idx = max(0, current_idx - 1)
                    end_idx = min(total_pages - 1, current_idx + 1)

                    # Create new PDF with extracted pages
                    extracted_pdf = fitz.open() # Create a new empty PDF
                    extracted_pdf.insert_pdf(pdf_document, from_page=start_idx, to_page=end_idx)

                    # Save the extracted PDF back to the *same path*, overwriting original download
                    extracted_pdf.save(local_file_path, garbage=3, deflate=True) # garbage=3 is often sufficient

                    # Determine new page number within the sub-document (1-based for URL fragment)
                    # New index = original index - start index. Convert back to 1-based.
                    new_page_number = (current_idx - start_idx) + 1

                    # Send the processed (sub-)PDF from the download_location
                    response = send_file(local_file_path, as_attachment=False, mimetype='application/pdf')
                    response.headers["X-Sub-PDF-Page"] = str(new_page_number)
                    # File will be cleaned up in 'finally' block after response is sent
                    return response

                except Exception as pdf_error:
                     return jsonify({"error": "Failed to process PDF document"}), 500
                finally:
                    # Close PDF documents if they were opened
                    if extracted_pdf:
                        extracted_pdf.close()
                    if pdf_document:
                        pdf_document.close()
                    # Cleanup handled in the outer finally block


            # --- Image Handling (Send file directly) ---
            elif is_image:
                mimetype, _ = mimetypes.guess_type(local_file_path)
                if not mimetype:
                    mimetype = 'application/octet-stream' # Fallback generic type
                # File will be cleaned up in 'finally' block after response is sent
                return send_file(local_file_path, as_attachment=False, mimetype=mimetype)

            # --- Fallback for unsupported types, PPTX, DOCX, etc. ---
            elif is_word or is_ppt:
                # For Word/PPT, you might want to convert to PDF first or handle differently
                return jsonify({"error": f"Unsupported file type for viewing: {file_ext}"}), 415
            else:
                # Cleanup already downloaded file before returning error
                # (Cleanup is handled in finally, no need to remove here explicitly)
                return jsonify({"error": f"Unsupported file type for viewing: {file_ext}"}), 415


        except requests.exceptions.RequestException as e:
            # Handle download errors
            # No need to clean up here, 'finally' will handle it if file exists
            return jsonify({"error": "Failed to download document from storage"}), 500
        except fitz.fitz.FileNotFoundError: # More specific exception name
            # Specific error if fitz can't find the file (maybe deleted between download and open)
            return jsonify({"error": "Internal processing error: File access issue"}), 500
        except Exception as e:
            # General error handling
            # No need to clean up here, 'finally' will handle it
            return jsonify({"error": f"An internal error occurred processing the document."}), 500
        finally:
            # --- CRITICAL CLEANUP ---
            # Ensure the downloaded/processed file is removed after the request,
            # regardless of success or failure, unless send_file is streaming it
            # and handles cleanup itself (which it should for non-temporary files).
            # Double-check existence before removing.
            if os.path.exists(local_file_path):
                try:
                    os.remove(local_file_path)
                except OSError as e:
                    # Log error but don't prevent response from being sent
                    print(f"Error cleaning up file {local_file_path}: {e}")