# functions_workflow_runner.py

"""
Workflow execution helpers for personal workflows.
"""

import asyncio
import logging
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from azure.identity import (
    AzureAuthorityHosts,
    ClientSecretCredential,
    DefaultAzureCredential,
    get_bearer_token_provider,
)
from flask import Flask, g, has_request_context, session
from openai import AzureOpenAI
from semantic_kernel import Kernel
from semantic_kernel.contents.chat_message_content import ChatMessageContent

from config import (
    SECRET_KEY,
    cognitive_services_scope,
    cosmos_conversations_container,
    cosmos_messages_container,
)
from functions_activity_logging import log_conversation_creation, log_workflow_run
from functions_appinsights import log_event
from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
from functions_notifications import create_workflow_priority_notification
from functions_personal_workflows import save_personal_workflow_run
from functions_settings import get_settings, get_user_settings, normalize_model_endpoints
from functions_thoughts import ThoughtTracker
from semantic_kernel_loader import load_user_semantic_kernel
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
from semantic_kernel_plugins.plugin_invocation_thoughts import register_plugin_invocation_thought_callback


_workflow_runner_app = None


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_now_iso():
    return _utc_now().isoformat()


def _build_response_preview(text, max_length=220):
    normalized = str(text or '').strip()
    if len(normalized) <= max_length:
        return normalized
    return f'{normalized[:max_length].rstrip()}...'


def _normalize_workflow_alert_text(text):
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def _summarize_workflow_alert_text(text, max_length=140):
    normalized = _normalize_workflow_alert_text(text)
    if not normalized:
        return ''

    sentence_match = re.search(r'(.+?[.!?])(?:\s|$)', normalized)
    if sentence_match:
        sentence = sentence_match.group(1).strip()
        if 24 <= len(sentence) <= max_length:
            return sentence

    numbered_split = re.split(r'\s+\d+\.\s+', normalized, maxsplit=1)[0].strip()
    if 24 <= len(numbered_split) <= max_length:
        return numbered_split

    dash_split = re.split(r'\s+-\s+', normalized, maxsplit=1)[0].strip()
    if 24 <= len(dash_split) <= max_length:
        return dash_split

    if len(normalized) <= max_length:
        return normalized

    return f'{normalized[:max_length - 3].rstrip()}...'


def _extract_message_text(message_content):
    if isinstance(message_content, str):
        return message_content
    if isinstance(message_content, list):
        parts = []
        for item in message_content:
            if isinstance(item, dict):
                text_value = item.get('text') or item.get('content') or ''
                if text_value:
                    parts.append(str(text_value))
            elif item:
                parts.append(str(item))
        return ''.join(parts)
    return str(message_content or '')


WORKFLOW_ALERT_PRIORITIES = {'low', 'medium', 'high'}


def _normalize_workflow_alert_priority(priority):
    normalized = str(priority or '').strip().lower()
    if normalized not in WORKFLOW_ALERT_PRIORITIES:
        return 'none'
    return normalized


def _dedupe_workflow_alert_targets(targets):
    deduped_targets = []
    seen_keys = set()

    for target in targets or []:
        if not isinstance(target, dict):
            continue

        link_context = target.get('link_context') if isinstance(target.get('link_context'), dict) else {}
        conversation_id = str(target.get('conversation_id') or link_context.get('conversation_id') or '').strip()
        link_url = str(target.get('link_url') or '').strip()
        dedupe_key = conversation_id or link_url
        if not dedupe_key or dedupe_key in seen_keys:
            continue

        seen_keys.add(dedupe_key)
        deduped_targets.append(target)

    return deduped_targets


def _normalize_workflow_alert_target_label(label):
    normalized_label = str(label or '').strip()
    lowered_label = normalized_label.lower()
    if lowered_label.startswith('open workflow'):
        return 'Open workflow'
    if lowered_label.startswith('open created'):
        return 'Open created conversation'
    if lowered_label.startswith('open updated'):
        return 'Open conversation'
    return normalized_label or 'Open conversation'


def _is_workflow_alert_workflow_target(target):
    return str((target or {}).get('label') or '').strip().lower() == 'open workflow'


def _get_workflow_alert_target_priority(target):
    target = target if isinstance(target, dict) else {}
    label = str(target.get('label') or '').strip().lower()
    link_context = target.get('link_context') if isinstance(target.get('link_context'), dict) else {}
    workspace_type = str(link_context.get('workspace_type') or '').strip().lower()
    chat_type = str(link_context.get('chat_type') or '').strip().lower()
    conversation_kind = str(link_context.get('conversation_kind') or '').strip().lower()

    priority = 0
    if label.startswith('open created'):
        priority += 100
    elif label.startswith('open conversation'):
        priority += 60
    else:
        priority += 20

    if workspace_type == 'group' or chat_type.startswith('group'):
        priority += 40
    elif workspace_type == 'personal' and (chat_type == 'personal_multi_user' or conversation_kind == 'collaboration'):
        priority += 20
    elif workspace_type == 'personal':
        priority += 10

    return priority


def _select_preferred_workflow_alert_targets(targets):
    normalized_targets = []
    for raw_target in _dedupe_workflow_alert_targets(targets):
        normalized_target = dict(raw_target)
        normalized_target['label'] = _normalize_workflow_alert_target_label(normalized_target.get('label'))
        normalized_targets.append(normalized_target)

    workflow_target = next(
        (target for target in normalized_targets if _is_workflow_alert_workflow_target(target)),
        None,
    )
    non_workflow_targets = [
        target for target in normalized_targets
        if not _is_workflow_alert_workflow_target(target)
    ]

    selected_targets = []
    if non_workflow_targets:
        selected_targets.append(max(non_workflow_targets, key=_get_workflow_alert_target_priority))

    if workflow_target:
        if not selected_targets or selected_targets[0].get('conversation_id') != workflow_target.get('conversation_id'):
            selected_targets.append(workflow_target)

    if not selected_targets and normalized_targets:
        selected_targets.append(normalized_targets[0])

    return selected_targets


def _build_workflow_alert_target_from_conversation(conversation_doc, default_label='Open conversation'):
    conversation_doc = conversation_doc if isinstance(conversation_doc, dict) else {}
    conversation_id = str(conversation_doc.get('id') or '').strip()
    if not conversation_id:
        return None

    chat_type = str(conversation_doc.get('chat_type') or '').strip().lower()
    conversation_kind = str(conversation_doc.get('conversation_kind') or '').strip()
    scope = conversation_doc.get('scope') if isinstance(conversation_doc.get('scope'), dict) else {}
    group_id = str(scope.get('group_id') or conversation_doc.get('group_id') or '').strip()
    workspace_type = 'group' if chat_type.startswith('group') or group_id else 'personal'
    label = str(default_label or conversation_doc.get('title') or 'Open conversation').strip() or 'Open conversation'

    link_context = {
        'workspace_type': workspace_type,
        'conversation_id': conversation_id,
        'chat_type': chat_type,
    }
    if group_id:
        link_context['group_id'] = group_id
    if conversation_kind:
        link_context['conversation_kind'] = conversation_kind

    return {
        'label': label,
        'link_url': f'/chats?conversationId={conversation_id}',
        'link_context': link_context,
        'conversation_id': conversation_id,
    }


def _get_simplechat_alert_target_label(function_name):
    target_labels = {
        'create_group_conversation': 'Open created conversation',
        'create_personal_collaboration_conversation': 'Open created conversation',
        'create_personal_conversation': 'Open created conversation',
        'add_conversation_message': 'Open conversation',
    }
    return target_labels.get(str(function_name or '').strip(), 'Open related conversation')


def _collect_agent_alert_targets(user_id, conversation_id):
    if not user_id or not conversation_id:
        return []

    plugin_logger = get_plugin_logger()
    invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=100)
    alert_targets = []

    for invocation in invocations:
        if invocation.plugin_name != 'SimpleChatPlugin' or not invocation.success:
            continue

        invocation_result = invocation.result
        if not isinstance(invocation_result, dict):
            continue

        conversation_doc = invocation_result.get('conversation') if isinstance(invocation_result.get('conversation'), dict) else {}
        alert_target = _build_workflow_alert_target_from_conversation(
            conversation_doc,
            default_label=_get_simplechat_alert_target_label(invocation.function_name),
        )
        if alert_target:
            alert_targets.append(alert_target)

    return _select_preferred_workflow_alert_targets(alert_targets)


def _create_workflow_priority_alert(workflow, run_record, conversation, execution_result=None):
    execution_result = execution_result if isinstance(execution_result, dict) else {}
    priority = _normalize_workflow_alert_priority(workflow.get('alert_priority'))
    if priority == 'none':
        return None

    try:
        user_id = str(workflow.get('user_id') or '').strip()
        workflow_id = str(workflow.get('id') or '').strip()
        workflow_name = str(workflow.get('name') or 'Workflow').strip() or 'Workflow'
        trigger_source = str(run_record.get('trigger_source') or 'manual').strip() or 'manual'
        workflow_targets = list(execution_result.get('alert_targets') or [])
        workflow_conversation_target = _build_workflow_alert_target_from_conversation(
            conversation,
            default_label='Open workflow',
        )
        if workflow_conversation_target:
            workflow_targets.append(workflow_conversation_target)

        workflow_targets = _select_preferred_workflow_alert_targets(workflow_targets)
        primary_target = workflow_targets[0] if workflow_targets else None
        success = bool(run_record.get('success'))
        title_prefix = f'{priority.capitalize()} priority workflow alert'
        response_preview = str(run_record.get('response_preview') or '').strip()
        error_text = str(run_record.get('error') or '').strip()

        if success:
            title = f'{title_prefix}: {workflow_name}'
            message = _summarize_workflow_alert_text(
                response_preview or f'{workflow_name} completed from the {trigger_source} trigger.'
            )
        else:
            title = f'{title_prefix}: {workflow_name} failed'
            message = _summarize_workflow_alert_text(
                error_text or f'{workflow_name} failed from the {trigger_source} trigger.'
            )

        metadata = {
            'workflow_id': workflow_id,
            'workflow_name': workflow_name,
            'priority': priority,
            'trigger_source': trigger_source,
            'run_id': str(run_record.get('id') or '').strip(),
            'runner_type': str(workflow.get('runner_type') or '').strip(),
            'status': str(run_record.get('status') or '').strip(),
            'conversation_id': str((conversation or {}).get('id') or run_record.get('conversation_id') or '').strip(),
            'assistant_message_id': str(run_record.get('assistant_message_id') or '').strip(),
            'response_preview': response_preview,
            'error': error_text,
            'link_targets': workflow_targets,
        }
        if execution_result.get('agent_name'):
            metadata['agent_name'] = execution_result.get('agent_name')
        if execution_result.get('agent_display_name'):
            metadata['agent_display_name'] = execution_result.get('agent_display_name')

        return create_workflow_priority_notification(
            user_id=user_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            priority=priority,
            title=title,
            message=message,
            link_url=primary_target.get('link_url') if primary_target else '',
            link_context=primary_target.get('link_context') if primary_target else {},
            metadata=metadata,
        )
    except Exception as exc:
        log_event(
            f'[WorkflowRunner] Failed to create workflow alert: {exc}',
            extra={
                'workflow_id': str(workflow.get('id') or '').strip(),
                'user_id': str(workflow.get('user_id') or '').strip(),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def _resolve_authority(auth_settings):
    management_cloud = (auth_settings.get('management_cloud') or 'public').lower()
    if management_cloud in ('government', 'usgovernment', 'usgov'):
        return AzureAuthorityHosts.AZURE_GOVERNMENT
    custom_authority = auth_settings.get('custom_authority') or ''
    if custom_authority:
        return custom_authority
    return AzureAuthorityHosts.AZURE_PUBLIC_CLOUD


def _resolve_foundry_scope(auth_settings, endpoint=None):
    custom_scope = (auth_settings.get('foundry_scope') or '').strip()
    if custom_scope:
        return custom_scope

    management_cloud = (auth_settings.get('management_cloud') or 'public').lower()
    if management_cloud in ('government', 'usgovernment', 'usgov'):
        return 'https://ai.azure.us/.default'
    if management_cloud == 'china':
        return 'https://ai.azure.cn/.default'
    if management_cloud == 'germany':
        return 'https://ai.azure.de/.default'

    endpoint_value = (endpoint or '').lower()
    if 'azure.us' in endpoint_value:
        return 'https://ai.azure.us/.default'
    if 'azure.cn' in endpoint_value:
        return 'https://ai.azure.cn/.default'
    if 'azure.de' in endpoint_value:
        return 'https://ai.azure.de/.default'
    return 'https://ai.azure.com/.default'


def _build_token_provider(auth_settings, provider='aoai', endpoint=None):
    auth_type = (auth_settings.get('type') or 'managed_identity').lower()
    authority = _resolve_authority(auth_settings)

    if auth_type == 'service_principal':
        credential = ClientSecretCredential(
            tenant_id=auth_settings.get('tenant_id'),
            client_id=auth_settings.get('client_id'),
            client_secret=auth_settings.get('client_secret'),
            authority=authority,
        )
    else:
        credential = DefaultAzureCredential(
            managed_identity_client_id=auth_settings.get('managed_identity_client_id') or None,
            authority=authority,
        )

    scope = cognitive_services_scope
    if provider in ('aifoundry', 'new_foundry'):
        scope = _resolve_foundry_scope(auth_settings, endpoint=endpoint)

    return get_bearer_token_provider(credential, scope)


def _get_workflow_runner_app():
    global _workflow_runner_app
    if _workflow_runner_app is None:
        workflow_app = Flask('simplechat_workflow_runner')
        workflow_app.secret_key = SECRET_KEY
        _workflow_runner_app = workflow_app
    return _workflow_runner_app


@contextmanager
def _ensure_execution_context(user_id):
    created_context = None
    reuse_existing = False

    if has_request_context():
        session_user = session.get('user') if isinstance(session.get('user'), dict) else {}
        session_user_id = str(session_user.get('oid') or '').strip()
        reuse_existing = session_user_id == str(user_id or '').strip()

    if not reuse_existing:
        created_context = _get_workflow_runner_app().test_request_context('/api/internal/workflows/run')
        created_context.push()
        session['user'] = {
            'oid': user_id,
            'roles': ['User'],
            'preferred_username': '',
            'name': user_id,
        }

    try:
        yield
    finally:
        if created_context is not None:
            created_context.pop()


def _ensure_workflow_conversation(workflow):
    conversation_id = str(workflow.get('conversation_id') or '').strip()
    user_id = str(workflow.get('user_id') or '').strip()
    title = f"Workflow: {workflow.get('name') or 'Untitled Workflow'}"

    if conversation_id:
        try:
            conversation = cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
            cleaned = {key: value for key, value in conversation.items() if not str(key).startswith('_')}
            if cleaned.get('title') != title:
                cleaned['title'] = title
                cleaned['last_updated'] = _utc_now_iso()
                cosmos_conversations_container.upsert_item(cleaned)
            return cleaned
        except Exception:
            pass

    conversation_id = str(uuid.uuid4())
    conversation = {
        'id': conversation_id,
        'user_id': user_id,
        'last_updated': _utc_now_iso(),
        'title': title,
        'context': [],
        'tags': ['workflow'],
        'strict': False,
        'is_pinned': False,
        'is_hidden': False,
        'chat_type': 'workflow',
        'workflow_id': workflow.get('id'),
        'has_unread_assistant_response': False,
        'last_unread_assistant_message_id': None,
        'last_unread_assistant_at': None,
    }
    cosmos_conversations_container.upsert_item(conversation)
    log_conversation_creation(
        user_id=user_id,
        conversation_id=conversation_id,
        title=title,
        workspace_type='personal',
    )
    conversation['added_to_activity_log'] = True
    cosmos_conversations_container.upsert_item(conversation)
    return conversation


def _get_latest_thread_id(conversation_id):
    try:
        rows = list(cosmos_messages_container.query_items(
            query=(
                'SELECT TOP 1 c.metadata.thread_info.thread_id as thread_id '
                'FROM c WHERE c.conversation_id = @conversation_id '
                'ORDER BY c.timestamp DESC'
            ),
            parameters=[{'name': '@conversation_id', 'value': conversation_id}],
            partition_key=conversation_id,
        ))
        return rows[0].get('thread_id') if rows else None
    except Exception:
        return None


def _create_user_message(conversation_id, workflow, trigger_source, run_id):
    previous_thread_id = _get_latest_thread_id(conversation_id)
    current_thread_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    metadata = {
        'source': 'workflow',
        'workflow': {
            'workflow_id': workflow.get('id'),
            'workflow_name': workflow.get('name'),
            'runner_type': workflow.get('runner_type'),
            'trigger_source': trigger_source,
            'run_id': run_id,
        },
        'thread_info': {
            'thread_id': current_thread_id,
            'previous_thread_id': previous_thread_id,
            'active_thread': True,
            'thread_attempt': 1,
        },
    }
    message_doc = {
        'id': message_id,
        'conversation_id': conversation_id,
        'role': 'user',
        'content': workflow.get('task_prompt', ''),
        'timestamp': _utc_now_iso(),
        'model_deployment_name': None,
        'metadata': metadata,
    }
    cosmos_messages_container.upsert_item(message_doc)
    return message_doc


def _initialize_workflow_assistant_tracking(conversation_id, user_id, user_message_doc):
    assistant_message_id = str(uuid.uuid4())
    user_thread_info = (user_message_doc.get('metadata') or {}).get('thread_info') or {}
    thought_tracker = ThoughtTracker(
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        thread_id=user_thread_info.get('thread_id'),
        user_id=user_id,
        force_enabled=True,
    )
    return assistant_message_id, thought_tracker


def _build_workflow_activity_payload(workflow, run_id, activity_key, kind, title, status, lane_key='main', lane_label='Main'):
    return {
        'activity_key': activity_key,
        'workflow_id': workflow.get('id'),
        'run_id': run_id,
        'kind': kind,
        'title': title,
        'status': status,
        'state': status,
        'lane_key': lane_key,
        'lane_label': lane_label,
    }


def _add_workflow_activity_thought(
    thought_tracker,
    workflow,
    run_id,
    *,
    step_type,
    content,
    detail=None,
    activity_key,
    kind,
    title,
    status,
    lane_key='main',
    lane_label='Main',
):
    if not thought_tracker:
        return None

    return thought_tracker.add_thought(
        step_type,
        content,
        detail=detail,
        activity=_build_workflow_activity_payload(
            workflow,
            run_id,
            activity_key,
            kind,
            title,
            status,
            lane_key=lane_key,
            lane_label=lane_label,
        ),
    )


def _create_assistant_message(conversation, workflow, result, trigger_source, run_id, user_message_doc, assistant_message_id=None):
    assistant_message_id = assistant_message_id or str(uuid.uuid4())
    timestamp = _utc_now_iso()
    user_thread_info = (user_message_doc.get('metadata') or {}).get('thread_info') or {}
    assistant_doc = {
        'id': assistant_message_id,
        'conversation_id': conversation.get('id'),
        'role': 'assistant',
        'content': result.get('reply', ''),
        'timestamp': timestamp,
        'model_deployment_name': result.get('model_deployment_name'),
        'metadata': {
            'source': 'workflow',
            'workflow': {
                'workflow_id': workflow.get('id'),
                'workflow_name': workflow.get('name'),
                'runner_type': workflow.get('runner_type'),
                'trigger_source': trigger_source,
                'run_id': run_id,
                'selected_agent': workflow.get('selected_agent') or {},
                'model_binding_summary': workflow.get('model_binding_summary') or {},
            },
            'thread_info': {
                'thread_id': str(uuid.uuid4()),
                'previous_thread_id': user_thread_info.get('thread_id'),
                'active_thread': True,
                'thread_attempt': 1,
            },
        },
    }
    cosmos_messages_container.upsert_item(assistant_doc)

    conversation['last_updated'] = timestamp
    conversation['workflow_id'] = workflow.get('id')
    conversation['chat_type'] = 'workflow'
    conversation['has_unread_assistant_response'] = True
    conversation['last_unread_assistant_message_id'] = assistant_message_id
    conversation['last_unread_assistant_at'] = timestamp
    cosmos_conversations_container.upsert_item(conversation)

    return assistant_doc


def _build_multi_endpoint_client(user_id, endpoint_id, model_id, settings):
    candidates = []
    user_settings = get_user_settings(user_id)
    if settings.get('allow_user_custom_endpoints', False):
        personal_endpoints, _ = normalize_model_endpoints(
            user_settings.get('settings', {}).get('personal_model_endpoints', []) or []
        )
        for endpoint in personal_endpoints:
            item = dict(endpoint)
            item['scope'] = 'user'
            candidates.append(item)

    global_endpoints, _ = normalize_model_endpoints(settings.get('model_endpoints', []) or [])
    for endpoint in global_endpoints:
        item = dict(endpoint)
        item['scope'] = 'global'
        candidates.append(item)

    endpoint_cfg = next((candidate for candidate in candidates if candidate.get('id') == endpoint_id), None)
    if not endpoint_cfg:
        raise ValueError('Selected model endpoint was not found.')

    model_cfg = next((model for model in endpoint_cfg.get('models', []) if model.get('id') == model_id), None)
    if not model_cfg:
        raise ValueError('Selected model was not found on the endpoint.')

    scope = endpoint_cfg.get('scope', 'global')
    resolved_endpoint = keyvault_model_endpoint_get_helper(
        endpoint_cfg,
        endpoint_cfg.get('id'),
        scope=scope,
        return_type=SecretReturnType.VALUE,
    )
    connection = resolved_endpoint.get('connection', {}) if isinstance(resolved_endpoint, dict) else {}
    auth = resolved_endpoint.get('auth', {}) if isinstance(resolved_endpoint, dict) else {}
    provider = str(resolved_endpoint.get('provider') or endpoint_cfg.get('provider') or 'aoai').strip().lower()
    deployment_name = (
        model_cfg.get('deploymentName')
        or model_cfg.get('deployment')
        or model_cfg.get('displayName')
        or model_id
    )
    api_version = connection.get('api_version') or connection.get('openai_api_version') or settings.get('azure_openai_gpt_api_version')
    endpoint = connection.get('endpoint')
    auth_type = str(auth.get('type') or 'api_key').strip().lower()

    if auth_type in ('key', 'api_key'):
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=auth.get('api_key'),
            api_version=api_version,
        )
    else:
        auth_settings = {
            'type': auth_type,
            'tenant_id': auth.get('tenant_id'),
            'client_id': auth.get('client_id'),
            'client_secret': auth.get('client_secret'),
            'managed_identity_client_id': auth.get('managed_identity_client_id'),
            'management_cloud': auth.get('management_cloud') or settings.get('management_cloud') or 'public',
            'custom_authority': auth.get('custom_authority') or settings.get('custom_authority') or '',
            'foundry_scope': auth.get('foundry_scope') or '',
        }
        token_provider = _build_token_provider(auth_settings, provider=provider, endpoint=endpoint)
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            azure_ad_token_provider=token_provider,
            api_version=api_version,
        )

    return client, deployment_name, provider


def _build_legacy_default_client(settings):
    if settings.get('enable_gpt_apim', False):
        endpoint = settings.get('azure_apim_gpt_endpoint')
        deployment_name = settings.get('azure_apim_gpt_deployment')
        api_key = settings.get('azure_apim_gpt_subscription_key')
        api_version = settings.get('azure_apim_gpt_api_version') or settings.get('azure_openai_gpt_api_version')
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        return client, deployment_name, 'aoai'

    endpoint = settings.get('azure_openai_gpt_endpoint')
    deployment_name = settings.get('azure_openai_gpt_deployment')
    api_version = settings.get('azure_openai_gpt_api_version')
    api_key = settings.get('azure_openai_gpt_key')
    auth_type = str(settings.get('azure_openai_gpt_authentication_type') or 'key').strip().lower()
    if isinstance(deployment_name, str) and ',' in deployment_name:
        deployment_name = deployment_name.split(',')[0].strip()

    if auth_type in ('key', 'api_key') or api_key:
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        return client, deployment_name, 'aoai'

    auth_settings = {
        'type': auth_type,
        'tenant_id': settings.get('azure_openai_gpt_tenant_id') or settings.get('azure_openai_tenant_id'),
        'client_id': settings.get('azure_openai_gpt_client_id') or settings.get('azure_openai_client_id'),
        'client_secret': settings.get('azure_openai_gpt_client_secret') or settings.get('azure_openai_client_secret'),
        'managed_identity_client_id': settings.get('azure_openai_gpt_managed_identity_client_id') or settings.get('azure_openai_managed_identity_client_id'),
        'management_cloud': settings.get('management_cloud') or settings.get('azure_management_cloud') or 'public',
        'custom_authority': settings.get('custom_authority') or settings.get('azure_custom_authority') or '',
    }
    token_provider = _build_token_provider(auth_settings, provider='aoai', endpoint=endpoint)
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=api_version,
    )
    return client, deployment_name, 'aoai'


def _execute_model_workflow(workflow, settings, run_id=None, thought_tracker=None):
    user_id = str(workflow.get('user_id') or '').strip()
    binding_summary = workflow.get('model_binding_summary') if isinstance(workflow.get('model_binding_summary'), dict) else {}
    endpoint_id = str(workflow.get('model_endpoint_id') or binding_summary.get('endpoint_id') or '').strip()
    model_id = str(workflow.get('model_id') or binding_summary.get('model_id') or '').strip()

    if thought_tracker and run_id:
        _add_workflow_activity_thought(
            thought_tracker,
            workflow,
            run_id,
            step_type='generation',
            content='Starting direct model execution',
            detail=None,
            activity_key=f'generation:{run_id}',
            kind='model_execution',
            title='Model execution',
            status='running',
        )

    if endpoint_id and model_id:
        client, deployment_name, provider = _build_multi_endpoint_client(user_id, endpoint_id, model_id, settings)
    else:
        default_selection = settings.get('default_model_selection', {}) if isinstance(settings, dict) else {}
        default_endpoint_id = str(default_selection.get('endpoint_id') or '').strip()
        default_model_id = str(default_selection.get('model_id') or '').strip()
        if default_endpoint_id and default_model_id:
            client, deployment_name, provider = _build_multi_endpoint_client(user_id, default_endpoint_id, default_model_id, settings)
        else:
            client, deployment_name, provider = _build_legacy_default_client(settings)

    completion = client.chat.completions.create(
        model=deployment_name,
        messages=[{'role': 'user', 'content': workflow.get('task_prompt', '')}],
    )
    reply = ''
    if getattr(completion, 'choices', None):
        reply = _extract_message_text(completion.choices[0].message.content)

    if thought_tracker and run_id:
        _add_workflow_activity_thought(
            thought_tracker,
            workflow,
            run_id,
            step_type='generation',
            content=f'Direct model execution completed with {deployment_name}',
            detail=f'provider={provider}',
            activity_key=f'generation:{run_id}',
            kind='model_execution',
            title='Model execution',
            status='completed',
        )

    return {
        'reply': reply,
        'model_deployment_name': deployment_name,
        'provider': provider,
    }


def _execute_agent_workflow(workflow, settings, conversation_id='', run_id=None, thought_tracker=None):
    user_id = str(workflow.get('user_id') or '').strip()
    selected_agent = workflow.get('selected_agent') if isinstance(workflow.get('selected_agent'), dict) else {}
    if not selected_agent:
        raise ValueError('No selected agent is configured for this workflow.')

    with _ensure_execution_context(user_id):
        plugin_logger = get_plugin_logger()
        previous_force_enable_agents = getattr(g, 'force_enable_agents', None) if hasattr(g, 'force_enable_agents') else None
        previous_request_agent_info = getattr(g, 'request_agent_info', None) if hasattr(g, 'request_agent_info') else None
        previous_request_agent_name = getattr(g, 'request_agent_name', None) if hasattr(g, 'request_agent_name') else None
        previous_conversation_id = getattr(g, 'conversation_id', None) if hasattr(g, 'conversation_id') else None

        g.force_enable_agents = True
        g.request_agent_info = dict(selected_agent)
        g.request_agent_name = selected_agent.get('name')
        callback_key = None
        if conversation_id:
            plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)
            g.conversation_id = conversation_id

        if thought_tracker and run_id:
            agent_label = selected_agent.get('display_name') or selected_agent.get('name') or 'Agent'
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='generation',
                content=f'Starting agent workflow with {agent_label}',
                detail=f'agent={agent_label}',
                activity_key=f'agent:{run_id}',
                kind='agent_execution',
                title='Agent execution',
                status='running',
            )

        if thought_tracker and run_id and conversation_id:
            callback_key = register_plugin_invocation_thought_callback(
                plugin_logger,
                thought_tracker,
                user_id,
                conversation_id,
                actor_label='Workflow agent',
            )

        try:
            kernel = Kernel()
            kernel, agent_objs = load_user_semantic_kernel(kernel, settings, user_id, None)
            if not agent_objs:
                raise ValueError('The selected agent could not be loaded for workflow execution.')

            loaded_agent = None
            requested_name = str(selected_agent.get('name') or '').strip()
            if requested_name:
                loaded_agent = agent_objs.get(requested_name)
            if loaded_agent is None:
                loaded_agent = next(iter(agent_objs.values()))

            result = asyncio.run(loaded_agent.invoke([
                ChatMessageContent(role='user', content=workflow.get('task_prompt', '')),
            ]))
            reply = str(result)
            alert_targets = _collect_agent_alert_targets(user_id, conversation_id)

            if thought_tracker and run_id:
                _add_workflow_activity_thought(
                    thought_tracker,
                    workflow,
                    run_id,
                    step_type='generation',
                    content='Agent workflow completed',
                    detail=f"agent={getattr(loaded_agent, 'display_name', None) or getattr(loaded_agent, 'name', None) or requested_name}",
                    activity_key=f'agent:{run_id}',
                    kind='agent_execution',
                    title='Agent execution',
                    status='completed',
                )

            return {
                'reply': reply,
                'model_deployment_name': getattr(loaded_agent, 'deployment_name', None) or requested_name,
                'provider': 'agent',
                'agent_name': getattr(loaded_agent, 'name', None) or requested_name,
                'agent_display_name': getattr(loaded_agent, 'display_name', None) or selected_agent.get('display_name') or requested_name,
                'alert_targets': alert_targets,
            }
        finally:
            if callback_key:
                plugin_logger.deregister_callbacks(callback_key)
            if previous_force_enable_agents is None and hasattr(g, 'force_enable_agents'):
                delattr(g, 'force_enable_agents')
            else:
                g.force_enable_agents = previous_force_enable_agents

            if previous_request_agent_info is None and hasattr(g, 'request_agent_info'):
                delattr(g, 'request_agent_info')
            else:
                g.request_agent_info = previous_request_agent_info

            if previous_request_agent_name is None and hasattr(g, 'request_agent_name'):
                delattr(g, 'request_agent_name')
            else:
                g.request_agent_name = previous_request_agent_name

            if previous_conversation_id is None and hasattr(g, 'conversation_id'):
                delattr(g, 'conversation_id')
            else:
                g.conversation_id = previous_conversation_id


def run_personal_workflow(workflow, trigger_source='manual'):
    """Execute a personal workflow and persist a run record."""
    workflow = workflow if isinstance(workflow, dict) else {}
    user_id = str(workflow.get('user_id') or '').strip()
    workflow_id = str(workflow.get('id') or '').strip()
    run_id = str(uuid.uuid4())
    started_at = _utc_now_iso()
    settings = get_settings()

    run_record = {
        'id': run_id,
        'workflow_id': workflow_id,
        'workflow_name': workflow.get('name'),
        'runner_type': workflow.get('runner_type'),
        'trigger_type': workflow.get('trigger_type'),
        'trigger_source': trigger_source,
        'status': 'running',
        'success': False,
        'started_at': started_at,
        'completed_at': None,
        'conversation_id': workflow.get('conversation_id'),
        'response_preview': '',
        'error': '',
    }
    save_personal_workflow_run(user_id, run_record)

    conversation = None
    thought_tracker = None
    try:
        conversation = _ensure_workflow_conversation(workflow)
        run_record['conversation_id'] = conversation.get('id')
        user_message_doc = _create_user_message(conversation.get('id'), workflow, trigger_source, run_id)
        assistant_message_id, thought_tracker = _initialize_workflow_assistant_tracking(
            conversation.get('id'),
            user_id,
            user_message_doc,
        )
        run_record['user_message_id'] = user_message_doc.get('id')
        run_record['assistant_message_id'] = assistant_message_id
        save_personal_workflow_run(user_id, run_record)

        _add_workflow_activity_thought(
            thought_tracker,
            workflow,
            run_id,
            step_type='workflow',
            content='Workflow run started',
            detail=f'trigger_source={trigger_source}',
            activity_key=f'run:{run_id}',
            kind='workflow_run',
            title='Workflow run',
            status='running',
        )

        if workflow.get('runner_type') == 'agent':
            execution_result = _execute_agent_workflow(
                workflow,
                settings,
                conversation_id=conversation.get('id'),
                run_id=run_id,
                thought_tracker=thought_tracker,
            )
        else:
            execution_result = _execute_model_workflow(
                workflow,
                settings,
                run_id=run_id,
                thought_tracker=thought_tracker,
            )

        assistant_doc = _create_assistant_message(
            conversation,
            workflow,
            execution_result,
            trigger_source,
            run_id,
            user_message_doc,
            assistant_message_id=assistant_message_id,
        )

        _add_workflow_activity_thought(
            thought_tracker,
            workflow,
            run_id,
            step_type='workflow',
            content='Workflow run completed',
            detail=f"message_id={assistant_doc.get('id')}",
            activity_key=f'run:{run_id}',
            kind='workflow_run',
            title='Workflow run',
            status='completed',
        )

        completed_at = _utc_now_iso()
        run_record.update({
            'status': 'completed',
            'success': True,
            'completed_at': completed_at,
            'conversation_id': conversation.get('id'),
            'user_message_id': user_message_doc.get('id'),
            'assistant_message_id': assistant_doc.get('id'),
            'model_deployment_name': execution_result.get('model_deployment_name'),
            'agent_name': execution_result.get('agent_name'),
            'agent_display_name': execution_result.get('agent_display_name'),
            'response_preview': _build_response_preview(execution_result.get('reply')),
            'error': '',
        })
        save_personal_workflow_run(user_id, run_record)
        log_workflow_run(
            user_id=user_id,
            workflow_id=workflow_id,
            workflow_name=workflow.get('name', ''),
            status='completed',
            trigger_source=trigger_source,
            run_id=run_id,
            conversation_id=conversation.get('id'),
            runner_type=workflow.get('runner_type'),
        )
        alert_notification = _create_workflow_priority_alert(
            workflow,
            run_record,
            conversation,
            execution_result=execution_result,
        )

        return {
            'success': True,
            'run': run_record,
            'notification': alert_notification,
            'workflow_updates': {
                'conversation_id': conversation.get('id'),
                'last_run_started_at': started_at,
                'last_run_at': completed_at,
                'last_run_status': 'completed',
                'last_run_error': '',
                'last_run_response_preview': run_record.get('response_preview', ''),
                'last_run_trigger_source': trigger_source,
                'run_count': int(workflow.get('run_count') or 0) + 1,
            },
        }
    except Exception as exc:
        if thought_tracker:
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='workflow',
                content='Workflow run failed',
                detail=str(exc),
                activity_key=f'run:{run_id}',
                kind='workflow_run',
                title='Workflow run',
                status='failed',
            )
        completed_at = _utc_now_iso()
        run_record.update({
            'status': 'failed',
            'success': False,
            'completed_at': completed_at,
            'error': str(exc),
            'response_preview': '',
        })
        save_personal_workflow_run(user_id, run_record)
        log_workflow_run(
            user_id=user_id,
            workflow_id=workflow_id,
            workflow_name=workflow.get('name', ''),
            status='failed',
            trigger_source=trigger_source,
            run_id=run_id,
            conversation_id=run_record.get('conversation_id'),
            runner_type=workflow.get('runner_type'),
            error=str(exc),
        )
        log_event(
            f'[WorkflowRunner] Workflow execution failed: {exc}',
            extra={
                'workflow_id': workflow_id,
                'workflow_name': workflow.get('name'),
                'user_id': user_id,
                'trigger_source': trigger_source,
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        alert_notification = _create_workflow_priority_alert(
            workflow,
            run_record,
            conversation,
        )
        return {
            'success': False,
            'run': run_record,
            'notification': alert_notification,
            'workflow_updates': {
                'last_run_started_at': started_at,
                'last_run_at': completed_at,
                'last_run_status': 'failed',
                'last_run_error': str(exc),
                'last_run_response_preview': '',
                'last_run_trigger_source': trigger_source,
                'run_count': int(workflow.get('run_count') or 0) + 1,
                'conversation_id': run_record.get('conversation_id'),
            },
        }