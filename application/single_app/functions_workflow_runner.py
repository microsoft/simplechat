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

from collaboration_models import (
    COLLABORATION_KIND,
    GROUP_MULTI_USER_CHAT_TYPE,
    PERSONAL_MULTI_USER_CHAT_TYPE,
    normalize_collaboration_user,
)
from config import (
    SECRET_KEY,
    cognitive_services_scope,
    cosmos_conversations_container,
    cosmos_messages_container,
)
from functions_activity_logging import log_conversation_creation, log_workflow_run
from functions_appinsights import log_event
from functions_collaboration import (
    create_collaboration_message_notifications,
    get_collaboration_conversation,
    mirror_source_message_to_collaboration,
)
from functions_document_actions import (
    DOCUMENT_ACTION_CONTEXT_WORKFLOW,
    DOCUMENT_ACTION_TYPE_COMPARISON,
    DOCUMENT_ACTION_TYPE_EXHAUSTIVE_REVIEW,
    DOCUMENT_ACTION_TYPE_NONE,
    get_document_action_config,
    get_document_action_max_documents,
    get_document_action_max_documents_by_type,
    get_enabled_document_action_types,
)
from functions_document_comparison import run_document_comparison
from functions_debug import debug_print
from functions_exhaustive_document_review import run_exhaustive_document_review
from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
from functions_message_artifacts import (
    build_agent_citation_tool_label,
    build_agent_citation_artifact_documents,
    make_json_serializable,
)
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


def _strip_agent_citation_artifact_refs(agent_citations):
    compact_citations = []
    for citation in agent_citations or []:
        if not isinstance(citation, dict):
            compact_citations.append(citation)
            continue

        compact_citation = dict(citation)
        compact_citation.pop('artifact_id', None)
        compact_citation.pop('raw_payload_externalized', None)
        compact_citations.append(compact_citation)

    return compact_citations


def _persist_agent_citation_artifacts(
    conversation_id,
    assistant_message_id,
    agent_citations,
    created_timestamp,
    user_info=None,
):
    if not agent_citations:
        return []

    compact_citations, artifact_docs = build_agent_citation_artifact_documents(
        conversation_id=conversation_id,
        assistant_message_id=assistant_message_id,
        agent_citations=agent_citations,
        created_timestamp=created_timestamp,
        user_info=user_info,
    )

    try:
        for artifact_doc in artifact_docs:
            cosmos_messages_container.upsert_item(artifact_doc)
        return compact_citations
    except Exception as exc:
        log_event(
            f'[WorkflowRunner] Failed to persist workflow assistant artifacts: {exc}',
            extra={
                'conversation_id': conversation_id,
                'assistant_message_id': assistant_message_id,
                'artifact_count': len(artifact_docs),
                'citation_count': len(agent_citations),
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return _strip_agent_citation_artifact_refs(compact_citations)


def _normalize_invocation_timestamp(raw_timestamp):
    if not raw_timestamp:
        return None
    if hasattr(raw_timestamp, 'isoformat'):
        return raw_timestamp.isoformat()
    return str(raw_timestamp)


def _build_agent_citations_from_invocations(user_id, conversation_id):
    if not user_id or not conversation_id:
        return []

    plugin_logger = get_plugin_logger()
    plugin_invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
    detailed_citations = []

    for invocation in plugin_invocations:
        tool_name = build_agent_citation_tool_label(
            invocation.plugin_name,
            invocation.function_name,
            invocation.parameters,
            invocation.result,
        )
        detailed_citations.append({
            'tool_name': tool_name,
            'function_name': invocation.function_name,
            'plugin_name': invocation.plugin_name,
            'function_arguments': make_json_serializable(invocation.parameters),
            'function_result': make_json_serializable(invocation.result),
            'duration_ms': invocation.duration_ms,
            'timestamp': _normalize_invocation_timestamp(invocation.timestamp),
            'success': invocation.success,
            'error_message': make_json_serializable(invocation.error_message),
            'user_id': invocation.user_id,
        })

    return detailed_citations


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


def _extract_created_conversation_docs_from_citations(agent_citations):
    created_function_names = {
        'create_group_conversation',
        'create_personal_collaboration_conversation',
        'create_personal_conversation',
    }
    created_conversations = []
    seen_conversation_ids = set()

    for citation in agent_citations or []:
        if not isinstance(citation, dict):
            continue
        if citation.get('plugin_name') != 'SimpleChatPlugin':
            continue
        if citation.get('function_name') not in created_function_names:
            continue

        invocation_result = citation.get('function_result') if isinstance(citation.get('function_result'), dict) else {}
        conversation_doc = invocation_result.get('conversation') if isinstance(invocation_result.get('conversation'), dict) else {}
        conversation_id = str(conversation_doc.get('id') or '').strip()
        if not conversation_id or conversation_id in seen_conversation_ids:
            continue

        seen_conversation_ids.add(conversation_id)
        created_conversations.append(dict(conversation_doc))

    return created_conversations


def _is_visualization_citation(citation):
    if not isinstance(citation, dict):
        return False

    function_result = citation.get('function_result') if isinstance(citation.get('function_result'), dict) else {}
    if function_result.get('success') is False:
        return False

    return bool(
        function_result.get('render_type')
        or function_result.get('chart_markdown')
        or function_result.get('chart_payload')
        or _contains_inline_image_gallery_result(function_result)
        or _contains_inline_video_result(function_result)
    )


def _contains_inline_image_gallery_result(function_result):
    if not isinstance(function_result, dict):
        return False

    image_gallery = function_result.get('image_gallery')
    if isinstance(image_gallery, dict) and list(image_gallery.get('items') or []):
        return True

    for field_name in ('items', 'images', 'image_urls'):
        field_value = function_result.get(field_name)
        if isinstance(field_value, list) and field_value:
            return True

    image_url = function_result.get('image_url')
    if isinstance(image_url, str) and image_url.strip():
        return True
    if isinstance(image_url, dict) and str(image_url.get('url') or '').strip():
        return True

    mime_type = str(function_result.get('mime') or '').strip().lower()
    if mime_type.startswith('image/'):
        return True

    result_type = str(function_result.get('type') or '').strip().lower()
    return result_type == 'image_url'


def _contains_inline_video_result(function_result):
    if not isinstance(function_result, dict):
        return False

    video_gallery = function_result.get('video_gallery')
    if isinstance(video_gallery, dict) and list(video_gallery.get('items') or []):
        return True

    for field_name in ('items', 'videos', 'video_urls'):
        field_value = function_result.get(field_name)
        if isinstance(field_value, list) and field_value:
            return True

    video_url = function_result.get('video_url')
    if isinstance(video_url, str) and video_url.strip():
        return True
    if isinstance(video_url, dict) and str(video_url.get('url') or '').strip():
        return True

    mime_type = str(function_result.get('mime') or '').strip().lower()
    if mime_type.startswith('video/'):
        return True

    result_type = str(function_result.get('type') or '').strip().lower()
    return result_type == 'video_url'


def _filter_visualization_agent_citations(agent_citations):
    return [citation for citation in agent_citations or [] if _is_visualization_citation(citation)]


def _is_collaboration_target_conversation(conversation_doc):
    chat_type = str((conversation_doc or {}).get('chat_type') or '').strip()
    conversation_kind = str((conversation_doc or {}).get('conversation_kind') or '').strip()
    return conversation_kind == COLLABORATION_KIND or chat_type in {
        GROUP_MULTI_USER_CHAT_TYPE,
        PERSONAL_MULTI_USER_CHAT_TYPE,
    }


def _build_workflow_mirror_metadata(workflow, source_assistant_doc, previous_thread_id):
    source_metadata = source_assistant_doc.get('metadata') if isinstance(source_assistant_doc.get('metadata'), dict) else {}
    workflow_metadata = source_metadata.get('workflow') if isinstance(source_metadata.get('workflow'), dict) else {}
    return {
        'source': 'workflow_mirror',
        'workflow': {
            'workflow_id': workflow.get('id'),
            'workflow_name': workflow.get('name'),
            'runner_type': workflow.get('runner_type'),
            'trigger_source': workflow_metadata.get('trigger_source'),
            'run_id': workflow_metadata.get('run_id'),
        },
        'mirrored_from': {
            'conversation_id': source_assistant_doc.get('conversation_id'),
            'message_id': source_assistant_doc.get('id'),
        },
        'thread_info': {
            'thread_id': str(uuid.uuid4()),
            'previous_thread_id': previous_thread_id,
            'active_thread': True,
            'thread_attempt': 1,
        },
    }


def _mirror_assistant_message_to_personal_conversation(
    workflow,
    source_assistant_doc,
    target_conversation_doc,
    mirrored_agent_citations,
):
    conversation_id = str((target_conversation_doc or {}).get('id') or '').strip()
    if not conversation_id:
        return None

    try:
        conversation_doc = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except Exception:
        conversation_doc = dict(target_conversation_doc or {})

    mirrored_message_id = str(uuid.uuid4())
    timestamp = _utc_now_iso()
    previous_thread_id = _get_latest_thread_id(conversation_id)
    prepared_agent_citations = _persist_agent_citation_artifacts(
        conversation_id=conversation_id,
        assistant_message_id=mirrored_message_id,
        agent_citations=mirrored_agent_citations,
        created_timestamp=timestamp,
        user_info={
            'user_id': str(workflow.get('user_id') or '').strip(),
        },
    )

    mirrored_assistant_doc = {
        'id': mirrored_message_id,
        'conversation_id': conversation_id,
        'role': 'assistant',
        'content': source_assistant_doc.get('content', ''),
        'timestamp': timestamp,
        'model_deployment_name': source_assistant_doc.get('model_deployment_name'),
        'augmented': bool(source_assistant_doc.get('augmented', False)),
        'hybrid_citations': list(source_assistant_doc.get('hybrid_citations') or []),
        'web_search_citations': list(source_assistant_doc.get('web_search_citations') or []),
        'agent_citations': prepared_agent_citations,
        'agent_display_name': source_assistant_doc.get('agent_display_name'),
        'agent_name': source_assistant_doc.get('agent_name'),
        'metadata': _build_workflow_mirror_metadata(
            workflow,
            source_assistant_doc,
            previous_thread_id,
        ),
    }
    cosmos_messages_container.upsert_item(mirrored_assistant_doc)

    conversation_doc['last_updated'] = timestamp
    conversation_doc['has_unread_assistant_response'] = True
    conversation_doc['last_unread_assistant_message_id'] = mirrored_message_id
    conversation_doc['last_unread_assistant_at'] = timestamp
    cosmos_conversations_container.upsert_item(conversation_doc)

    return mirrored_assistant_doc


def _mirror_workflow_visualizations_to_created_conversations(workflow, source_assistant_doc, execution_result):
    source_assistant_doc = source_assistant_doc if isinstance(source_assistant_doc, dict) else {}
    execution_result = execution_result if isinstance(execution_result, dict) else {}
    raw_agent_citations = list(execution_result.get('agent_citations') or [])
    mirrored_agent_citations = raw_agent_citations or list(source_assistant_doc.get('agent_citations') or [])
    hybrid_citations = list(source_assistant_doc.get('hybrid_citations') or [])
    web_search_citations = list(source_assistant_doc.get('web_search_citations') or [])
    if not source_assistant_doc or not (mirrored_agent_citations or hybrid_citations or web_search_citations):
        return []

    created_conversations = _extract_created_conversation_docs_from_citations(raw_agent_citations)
    if not created_conversations:
        return []

    source_conversation_id = str(source_assistant_doc.get('conversation_id') or '').strip()
    default_sender_user = normalize_collaboration_user({
        'user_id': str(workflow.get('user_id') or '').strip(),
        'display_name': str(workflow.get('user_id') or '').strip(),
    }) or {
        'user_id': str(workflow.get('user_id') or '').strip(),
        'display_name': str(workflow.get('user_id') or '').strip() or 'Workflow user',
        'email': '',
    }
    collaboration_source_doc = {
        **source_assistant_doc,
        'agent_citations': mirrored_agent_citations,
        'hybrid_citations': hybrid_citations,
        'web_search_citations': web_search_citations,
    }
    mirrored_message_ids = []

    for created_conversation in created_conversations:
        conversation_id = str(created_conversation.get('id') or '').strip()
        if not conversation_id or conversation_id == source_conversation_id:
            continue

        try:
            if _is_collaboration_target_conversation(created_conversation):
                collaboration_conversation = get_collaboration_conversation(conversation_id)
                mirrored_message_doc, updated_conversation, created = mirror_source_message_to_collaboration(
                    collaboration_conversation,
                    collaboration_source_doc,
                    default_sender_user,
                    extra_metadata={
                        'source_conversation_id': source_conversation_id,
                        'source_thought_user_id': str(workflow.get('user_id') or '').strip(),
                        'workflow_mirror': True,
                    },
                )
                if created and mirrored_message_doc:
                    create_collaboration_message_notifications(updated_conversation, mirrored_message_doc)
                    mirrored_message_ids.append(mirrored_message_doc.get('id'))
            else:
                mirrored_message_doc = _mirror_assistant_message_to_personal_conversation(
                    workflow,
                    source_assistant_doc,
                    created_conversation,
                    mirrored_agent_citations,
                )
                if mirrored_message_doc:
                    mirrored_message_ids.append(mirrored_message_doc.get('id'))
        except Exception as exc:
            log_event(
                f'[WorkflowRunner] Failed to mirror workflow visualizations into conversation {conversation_id}: {exc}',
                extra={
                    'workflow_id': str(workflow.get('id') or '').strip(),
                    'source_message_id': str(source_assistant_doc.get('id') or '').strip(),
                    'target_conversation_id': conversation_id,
                },
                level=logging.WARNING,
                exceptionTraceback=True,
            )

    return mirrored_message_ids


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


def _strip_workflow_alert_markdown(text):
    normalized_text = str(text or '').strip()
    if not normalized_text:
        return ''

    normalized_text = re.sub(r'\[([^\]]+)\]\([^\)]*\)', r'\1', normalized_text)
    normalized_text = re.sub(r'[*_`#>~]+', '', normalized_text)
    normalized_text = re.sub(r'\s+', ' ', normalized_text)
    return normalized_text.strip(' \t-:;,')


def _normalize_workflow_alert_title_text(text, max_length=110):
    normalized_text = _strip_workflow_alert_markdown(text)
    if not normalized_text:
        return ''

    normalized_text = re.sub(
        r'^\s*eguardian\s*alert\s*[:,-]?\s*',
        'eGuardian Alert, ',
        normalized_text,
        flags=re.IGNORECASE,
    )
    normalized_text = re.sub(
        r'^\s*eguardian\s*[:,-]\s*',
        'eGuardian Alert, ',
        normalized_text,
        flags=re.IGNORECASE,
    )
    normalized_text = re.sub(r'\s+', ' ', normalized_text).strip(' ,;:-')
    if len(normalized_text) > max_length:
        normalized_text = f"{normalized_text[:max_length - 3].rstrip(' ,;:-')}..."
    return normalized_text


def _extract_workflow_alert_event_title(text, max_length=90):
    normalized_text = _strip_workflow_alert_markdown(text)
    if not normalized_text:
        return ''

    numbered_match = re.search(r'(?:^|\s)\d+\.\s*([^\-:.]{3,90}?)(?=\s+-|\.|:|$)', normalized_text)
    if numbered_match:
        return _normalize_workflow_alert_title_text(numbered_match.group(1), max_length=max_length)

    heading_match = re.search(r"^([A-Z][A-Za-z0-9/&()'\s]{5,90}?)(?=\s+-|:|\.)", normalized_text)
    if heading_match:
        return _normalize_workflow_alert_title_text(heading_match.group(1), max_length=max_length)

    return ''


def _build_workflow_alert_citation_label(citation):
    if not isinstance(citation, dict):
        return ''

    explicit_label = str(citation.get('tool_name') or '').strip()
    if explicit_label:
        return explicit_label

    return build_agent_citation_tool_label(
        citation.get('plugin_name'),
        citation.get('function_name'),
        citation.get('function_arguments'),
        citation.get('function_result'),
    )


def _get_workflow_alert_enrichment_priority(citation):
    function_name = str((citation or {}).get('function_name') or '').strip()
    priority_map = {
        'create_group_conversation': 100,
        'create_personal_collaboration_conversation': 100,
        'create_personal_conversation': 100,
        'create_calendar_invite': 95,
        'create_map_visualization': 90,
        'upload_markdown_document': 85,
        'create_group': 80,
        'invite_group_conversation_members': 75,
        'mark_message_as_read': 70,
        'get_my_messages': 40,
        'search_users': 30,
        'get_user_by_email': 30,
    }
    return priority_map.get(function_name, 10)


def _build_workflow_alert_enrichment_labels(agent_citations):
    ranked_labels = []
    seen_labels = set()

    for index, citation in enumerate(agent_citations or []):
        if not isinstance(citation, dict):
            continue
        if citation.get('success') is False:
            continue

        function_name = str(citation.get('function_name') or '').strip()
        if function_name == 'add_conversation_message':
            continue

        label = _normalize_workflow_alert_text(_build_workflow_alert_citation_label(citation))
        if not label:
            continue

        dedupe_key = label.lower()
        if dedupe_key in seen_labels:
            continue

        seen_labels.add(dedupe_key)
        ranked_labels.append((
            _get_workflow_alert_enrichment_priority(citation),
            index,
            label,
        ))

    ranked_labels.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked_labels]


def _extract_workflow_alert_subject(alert_title):
    normalized_title = _normalize_workflow_alert_title_text(alert_title)
    if not normalized_title:
        return ''

    normalized_title = re.sub(
        r'^\s*eguardian\s*alert,\s*',
        '',
        normalized_title,
        flags=re.IGNORECASE,
    )
    return normalized_title.strip(' ,;:-')


def _build_workflow_alert_action_plan(agent_citations):
    action_plan = {
        'summary_labels': [],
        'ready_lines': [],
        'support_lines': [],
    }
    seen_values = {
        'summary_labels': set(),
        'ready_lines': set(),
        'support_lines': set(),
    }

    for citation in agent_citations or []:
        if not isinstance(citation, dict) or citation.get('success') is False:
            continue

        function_name = str(citation.get('function_name') or '').strip()
        function_result = citation.get('function_result') if isinstance(citation.get('function_result'), dict) else {}
        citation_label = _normalize_workflow_alert_text(_build_workflow_alert_citation_label(citation))
        summary_label = ''
        ready_line = ''
        support_line = ''

        if function_name in {
            'create_group_conversation',
            'create_personal_collaboration_conversation',
            'create_personal_conversation',
        }:
            summary_label = 'coordination conversation'
            ready_line = 'Coordination conversation created'
        elif function_name == 'create_calendar_invite':
            is_teams_briefing = (
                str(function_result.get('meeting_type') or '').strip().lower() == 'teams'
                or 'teams' in citation_label.lower()
            )
            summary_label = 'Teams briefing' if is_teams_briefing else 'briefing invite'
            ready_line = 'Teams briefing prepared' if is_teams_briefing else 'Briefing invite prepared'
        elif function_name == 'create_map_visualization':
            summary_label = 'travel map'
            ready_line = 'Travel map generated'
        elif function_name == 'upload_markdown_document':
            support_line = 'Briefing document saved'
        elif function_name == 'invite_group_conversation_members':
            support_line = 'Participants invited'
        else:
            continue

        if summary_label:
            summary_key = summary_label.lower()
            if summary_key not in seen_values['summary_labels']:
                seen_values['summary_labels'].add(summary_key)
                action_plan['summary_labels'].append(summary_label)
        if ready_line:
            ready_key = ready_line.lower()
            if ready_key not in seen_values['ready_lines']:
                seen_values['ready_lines'].add(ready_key)
                action_plan['ready_lines'].append(ready_line)
        if support_line:
            support_key = support_line.lower()
            if support_key not in seen_values['support_lines']:
                seen_values['support_lines'].add(support_key)
                action_plan['support_lines'].append(support_line)

    return action_plan


def _join_workflow_alert_labels(labels):
    normalized_labels = [str(label or '').strip() for label in labels or [] if str(label or '').strip()]
    if not normalized_labels:
        return ''
    if len(normalized_labels) == 1:
        return normalized_labels[0]
    if len(normalized_labels) == 2:
        return f'{normalized_labels[0]} and {normalized_labels[1]}'
    return f"{', '.join(normalized_labels[:-1])}, and {normalized_labels[-1]}"


def _looks_like_workflow_alert_failure_text(text):
    normalized_text = _normalize_workflow_alert_text(text).lower()
    if not normalized_text:
        return False

    failure_markers = [
        "i can't",
        'i cannot',
        "couldn't",
        'could not',
        'failed to',
        'unable to',
        'not able to',
        'do not have access',
        'permission',
        'not supported',
        'not reliably',
    ]
    return any(marker in normalized_text for marker in failure_markers)


def _extract_workflow_alert_title_from_citations(agent_citations):
    for conversation_doc in _extract_created_conversation_docs_from_citations(agent_citations):
        conversation_title = str(conversation_doc.get('title') or '').strip()
        if conversation_title:
            return _normalize_workflow_alert_title_text(conversation_title)

    for enrichment_label in _build_workflow_alert_enrichment_labels(agent_citations):
        if ': ' not in enrichment_label:
            continue
        label_detail = enrichment_label.split(': ', 1)[1].strip()
        if label_detail:
            return _normalize_workflow_alert_title_text(label_detail)

    return ''


def _build_workflow_alert_action_summary(summary_labels):
    normalized_labels = [str(label or '').strip() for label in summary_labels or [] if str(label or '').strip()]
    if not normalized_labels:
        return ''

    summary_subset = normalized_labels[:3]
    joined_labels = _join_workflow_alert_labels(summary_subset)
    verb = 'is' if len(summary_subset) == 1 else 'are'
    return f'{joined_labels[:1].upper()}{joined_labels[1:]} {verb} ready.'


def _trim_workflow_alert_summary_text(text, max_length=180):
    normalized_text = _normalize_workflow_alert_text(text)
    if not normalized_text:
        return ''
    if len(normalized_text) <= max_length:
        return normalized_text
    return f'{normalized_text[:max_length - 3].rstrip()}...'


def _build_workflow_alert_success_summary(alert_title, action_plan, response_preview, workflow_name, trigger_source):
    alert_subject = _extract_workflow_alert_subject(alert_title)
    action_summary = _build_workflow_alert_action_summary(action_plan.get('summary_labels') or [])

    if alert_subject and action_summary:
        return _trim_workflow_alert_summary_text(f'{alert_subject}. {action_summary}', max_length=180)
    if alert_subject:
        return _trim_workflow_alert_summary_text(alert_subject, max_length=180)
    if action_summary:
        return _trim_workflow_alert_summary_text(action_summary, max_length=180)

    normalized_preview = _strip_workflow_alert_markdown(response_preview)
    if normalized_preview and not _looks_like_workflow_alert_failure_text(normalized_preview):
        return _summarize_workflow_alert_text(normalized_preview)

    return _summarize_workflow_alert_text(
        f'{workflow_name} completed from the {trigger_source} trigger.'
    )


def _build_workflow_alert_success_detail(alert_title, action_plan, response_preview, workflow_name, trigger_source):
    alert_subject = _extract_workflow_alert_subject(alert_title)
    ready_lines = list(action_plan.get('ready_lines') or [])
    support_lines = list(action_plan.get('support_lines') or [])
    detail_sections = []

    if alert_subject:
        detail_sections.append(f'Focus\n{alert_subject}')

    if ready_lines:
        ready_text = '\n- '.join(ready_lines[:4])
        detail_sections.append(f'Ready now\n- {ready_text}')

    if support_lines:
        support_text = '\n- '.join(support_lines[:2])
        detail_sections.append(f'Supporting items\n- {support_text}')

    if detail_sections:
        return '\n\n'.join(detail_sections)

    normalized_preview = _strip_workflow_alert_markdown(response_preview)
    if normalized_preview and not _looks_like_workflow_alert_failure_text(normalized_preview):
        return normalized_preview

    return _normalize_workflow_alert_text(
        f'{workflow_name} completed from the {trigger_source} trigger.'
    )


def _build_workflow_alert_content(workflow, run_record, execution_result, priority):
    execution_result = execution_result if isinstance(execution_result, dict) else {}
    workflow_name = _normalize_workflow_alert_title_text(workflow.get('name') or 'Workflow') or 'Workflow'
    trigger_source = str(run_record.get('trigger_source') or 'manual').strip() or 'manual'
    success = bool(run_record.get('success'))
    response_preview = _strip_workflow_alert_markdown(run_record.get('response_preview') or '')
    reply_text = _strip_workflow_alert_markdown(execution_result.get('reply') or '')
    error_text = _strip_workflow_alert_markdown(run_record.get('error') or '')
    agent_citations = list(execution_result.get('agent_citations') or [])
    enrichment_labels = _build_workflow_alert_enrichment_labels(agent_citations)
    action_plan = _build_workflow_alert_action_plan(agent_citations)

    alert_title = _extract_workflow_alert_title_from_citations(agent_citations)
    if not alert_title:
        alert_title = _extract_workflow_alert_event_title(reply_text or response_preview)
    if not alert_title:
        alert_title = workflow_name

    if success:
        alert_summary = _build_workflow_alert_success_summary(
            alert_title,
            action_plan,
            response_preview or reply_text,
            workflow_name,
            trigger_source,
        )
        alert_detail = _build_workflow_alert_success_detail(
            alert_title,
            action_plan,
            response_preview or reply_text,
            workflow_name,
            trigger_source,
        )
        notification_title = f'{priority.capitalize()} priority workflow alert: {alert_title}'
    else:
        failure_text = error_text or response_preview or reply_text or (
            f'{workflow_name} failed from the {trigger_source} trigger.'
        )
        alert_summary = _summarize_workflow_alert_text(failure_text)
        alert_detail = _normalize_workflow_alert_text(failure_text)
        notification_title = f'{priority.capitalize()} priority workflow alert: {workflow_name} failed'

    return {
        'notification_title': notification_title,
        'notification_message': alert_summary,
        'alert_title': alert_title,
        'alert_summary': alert_summary,
        'alert_detail': alert_detail,
        'event_title': alert_title,
        'enrichment_labels': enrichment_labels,
    }


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
        workflow_name = _normalize_workflow_alert_title_text(workflow.get('name') or 'Workflow') or 'Workflow'
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
        response_preview = str(run_record.get('response_preview') or '').strip()
        error_text = str(run_record.get('error') or '').strip()
        alert_content = _build_workflow_alert_content(
            workflow,
            run_record,
            execution_result,
            priority,
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
            'event_title': alert_content.get('event_title'),
            'alert_title': alert_content.get('alert_title'),
            'alert_summary': alert_content.get('alert_summary'),
            'alert_detail': alert_content.get('alert_detail'),
            'alert_enrichments': alert_content.get('enrichment_labels') or [],
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
            title=alert_content.get('notification_title') or f'{priority.capitalize()} priority workflow alert: {workflow_name}',
            message=alert_content.get('notification_message') or _summarize_workflow_alert_text(response_preview or error_text),
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
    document_action = _get_document_action_config(workflow)
    metadata = {
        'source': 'workflow',
        'workflow': {
            'workflow_id': workflow.get('id'),
            'workflow_name': workflow.get('name'),
            'runner_type': workflow.get('runner_type'),
            'trigger_source': trigger_source,
            'run_id': run_id,
            'document_action': document_action,
            'exhaustive_review': workflow.get('exhaustive_review') or {},
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
    document_action = _get_document_action_config(workflow)
    raw_agent_citations = list(result.get('agent_citations') or [])
    prepared_agent_citations = _persist_agent_citation_artifacts(
        conversation_id=conversation.get('id'),
        assistant_message_id=assistant_message_id,
        agent_citations=raw_agent_citations,
        created_timestamp=timestamp,
        user_info={
            'user_id': str(workflow.get('user_id') or '').strip(),
        },
    )
    assistant_doc = {
        'id': assistant_message_id,
        'conversation_id': conversation.get('id'),
        'role': 'assistant',
        'content': result.get('reply', ''),
        'timestamp': timestamp,
        'model_deployment_name': result.get('model_deployment_name'),
        'agent_citations': prepared_agent_citations,
        'agent_display_name': result.get('agent_display_name'),
        'agent_name': result.get('agent_name'),
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
                'document_action': document_action,
                'exhaustive_review': workflow.get('exhaustive_review') or {},
                'review_coverage': result.get('review_coverage') or {},
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


def _resolve_model_workflow_client(workflow, settings):
    user_id = str(workflow.get('user_id') or '').strip()
    binding_summary = workflow.get('model_binding_summary') if isinstance(workflow.get('model_binding_summary'), dict) else {}
    endpoint_id = str(workflow.get('model_endpoint_id') or binding_summary.get('endpoint_id') or '').strip()
    model_id = str(workflow.get('model_id') or binding_summary.get('model_id') or '').strip()
    legacy_model_deployment = str(workflow.get('legacy_model_deployment') or '').strip()

    if endpoint_id and model_id:
        return _build_multi_endpoint_client(user_id, endpoint_id, model_id, settings)

    if legacy_model_deployment:
        client, _, provider = _build_legacy_default_client(settings)
        return client, legacy_model_deployment, provider

    default_selection = settings.get('default_model_selection', {}) if isinstance(settings, dict) else {}
    default_endpoint_id = str(default_selection.get('endpoint_id') or '').strip()
    default_model_id = str(default_selection.get('model_id') or '').strip()
    if default_endpoint_id and default_model_id:
        return _build_multi_endpoint_client(user_id, default_endpoint_id, default_model_id, settings)

    return _build_legacy_default_client(settings)


def _chain_activity_callbacks(*callbacks):
    active_callbacks = [callback for callback in callbacks if callable(callback)]
    if not active_callbacks:
        return None

    def callback(event):
        for activity_callback in active_callbacks:
            try:
                activity_callback(event)
            except Exception as exc:
                log_event(
                    f'[WorkflowRunner] Exhaustive review activity callback failed: {exc}',
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )

    return callback


def _get_document_action_config(workflow):
    settings = get_settings()
    return get_document_action_config(
        workflow,
        max_documents_by_type=get_document_action_max_documents_by_type(
            DOCUMENT_ACTION_CONTEXT_WORKFLOW,
            settings=settings,
        ),
        allowed_action_types=get_enabled_document_action_types(settings=settings),
    )


def _build_document_action_activity_callback(workflow, run_id, thought_tracker=None):
    if not thought_tracker or not run_id:
        return None

    def callback(event):
        event_type = str((event or {}).get('type') or '').strip().lower()
        document_id = str((event or {}).get('document_id') or '').strip()
        document_name = str((event or {}).get('document_name') or 'Document').strip() or 'Document'
        window_range = (event or {}).get('window_range') if isinstance((event or {}).get('window_range'), dict) else {}
        window_number = window_range.get('window_number')

        if event_type == 'document_started':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Started exhaustive review for {document_name}',
                detail=f"windows={event.get('window_count', 0)}",
                activity_key=f'review:{run_id}:{document_id}',
                kind='document_review',
                title='Document review',
                status='running',
            )
        elif event_type == 'window_started':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Reviewing window {window_number} for {document_name}',
                detail=f"attempt={event.get('attempt_number', 1)}",
                activity_key=f'review:{run_id}:{document_id}:window:{window_number}',
                kind='document_review',
                title='Document review',
                status='running',
            )
        elif event_type == 'window_retry':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Retrying window {window_number} for {document_name}',
                detail=f"attempt={event.get('attempt_number', 1)}",
                activity_key=f'review:{run_id}:{document_id}:window:{window_number}',
                kind='document_review',
                title='Document review',
                status='running',
            )
        elif event_type == 'window_completed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Completed window {window_number} for {document_name}',
                detail=(
                    f"processed={event.get('processed_windows', 0)} | "
                    f"failed={event.get('failed_windows', 0)}"
                ),
                activity_key=f'review:{run_id}:{document_id}:window:{window_number}',
                kind='document_review',
                title='Document review',
                status='completed',
            )
        elif event_type == 'document_completed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Completed exhaustive review for {document_name}',
                detail=(
                    f"processed={event.get('processed_windows', 0)} | "
                    f"failed={event.get('failed_windows', 0)}"
                ),
                activity_key=f'review:{run_id}:{document_id}',
                kind='document_review',
                title='Document review',
                status='completed',
            )
        elif event_type == 'window_failed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Failed review window {window_number} for {document_name}',
                detail=str(event.get('error') or 'Unknown exhaustive review failure'),
                activity_key=f'review:{run_id}:{document_id}:window:{window_number}:failed',
                kind='document_review',
                title='Document review',
                status='failed',
            )
        elif event_type == 'reduction_started':
            reduction_step_index = event.get('reduction_step_index')
            reduction_step_total = event.get('reduction_step_total')
            reduction_detail = None
            if reduction_step_index is not None and reduction_step_total:
                reduction_detail = f'batch={reduction_step_index}/{reduction_step_total}'

            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content='Combining review findings into the final response',
                detail=reduction_detail,
                activity_key=f'review:{run_id}:reduction',
                kind='document_review',
                title='Document review',
                status='running',
            )
        elif event_type == 'reduction_completed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content='Finished combining review findings into the final response',
                detail=f"documents={event.get('document_count', 0)}",
                activity_key=f'review:{run_id}:reduction',
                kind='document_review',
                title='Document review',
                status='completed',
            )
        elif event_type == 'comparison_started':
            right_document_name = str((event or {}).get('right_document_name') or 'Document').strip() or 'Document'
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Comparing {document_name} to {right_document_name}',
                detail=(
                    f"pair={event.get('comparison_index', 0)}/{event.get('comparison_count', 0)}"
                ),
                activity_key=f"compare:{run_id}:{document_id}:{event.get('right_document_id')}",
                kind='document_review',
                title='Document comparison',
                status='running',
            )
        elif event_type == 'comparison_completed':
            right_document_name = str((event or {}).get('right_document_name') or 'Document').strip() or 'Document'
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content=f'Completed comparison of {document_name} to {right_document_name}',
                detail=(
                    f"pair={event.get('comparison_index', 0)}/{event.get('comparison_count', 0)}"
                ),
                activity_key=f"compare:{run_id}:{document_id}:{event.get('right_document_id')}",
                kind='document_review',
                title='Document comparison',
                status='completed',
            )
        elif event_type == 'comparison_reduction_started':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content='Combining comparison findings across the selected documents',
                detail=f"pairs={event.get('comparison_count', 0)}",
                activity_key=f'compare:{run_id}:reduction',
                kind='document_review',
                title='Document comparison',
                status='running',
            )
        elif event_type == 'comparison_reduction_completed':
            _add_workflow_activity_thought(
                thought_tracker,
                workflow,
                run_id,
                step_type='document',
                content='Finished combining comparison findings across the selected documents',
                detail=f"pairs={event.get('comparison_count', 0)}",
                activity_key=f'compare:{run_id}:reduction',
                kind='document_review',
                title='Document comparison',
                status='completed',
            )

    return callback


def _resolve_document_action_reply(result):
    result = result if isinstance(result, dict) else {}
    analysis_reply = str(result.get('analysis_reply') or '').strip()
    if analysis_reply:
        return analysis_reply
    return str(result.get('reply') or '').strip()


def _execute_model_workflow(workflow, settings, run_id=None, thought_tracker=None):
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

    client, deployment_name, provider = _resolve_model_workflow_client(workflow, settings)

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


def _execute_exhaustive_review_workflow(
    workflow,
    settings,
    conversation_id='',
    run_id=None,
    thought_tracker=None,
    external_activity_callback=None,
    action_config=None,
):
    review_config = action_config if isinstance(action_config, dict) else _get_document_action_config(workflow)
    if review_config.get('type') != DOCUMENT_ACTION_TYPE_EXHAUSTIVE_REVIEW:
        raise ValueError('Exhaustive review is not enabled for this workflow.')
    workflow_review_max_documents = get_document_action_max_documents(
        DOCUMENT_ACTION_TYPE_EXHAUSTIVE_REVIEW,
        DOCUMENT_ACTION_CONTEXT_WORKFLOW,
        settings=settings,
    )

    activity_callback = _chain_activity_callbacks(
        _build_document_action_activity_callback(workflow, run_id, thought_tracker=thought_tracker),
        external_activity_callback,
    )
    user_id = str(workflow.get('user_id') or '').strip()
    selected_agent = workflow.get('selected_agent') if isinstance(workflow.get('selected_agent'), dict) else {}
    debug_print(
        '[WorkflowExhaustiveReview] Starting workflow action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f"runner_type={workflow.get('runner_type')} | "
        f'conversation_id={conversation_id} | '
        f"documents={len(review_config.get('document_ids') or [])} | "
        f'max_documents={workflow_review_max_documents}'
    )

    if workflow.get('runner_type') == 'agent':
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

            try:
                kernel = Kernel()
                kernel, agent_objs = load_user_semantic_kernel(kernel, settings, user_id, None)
                if not agent_objs:
                    raise ValueError('The selected agent could not be loaded for exhaustive review.')

                loaded_agent = None
                requested_name = str(selected_agent.get('name') or '').strip()
                if requested_name:
                    loaded_agent = agent_objs.get(requested_name)
                if loaded_agent is None:
                    loaded_agent = next(iter(agent_objs.values()))

                if thought_tracker and run_id and conversation_id:
                    callback_key = register_plugin_invocation_thought_callback(
                        plugin_logger,
                        thought_tracker,
                        user_id,
                        conversation_id,
                        actor_label='Workflow agent',
                    )

                def invoke_prompt(prompt_text, stage='window_review', metadata=None):
                    result = asyncio.run(loaded_agent.invoke([
                        ChatMessageContent(role='user', content=prompt_text),
                    ]))
                    return str(result)

                review_result = run_exhaustive_document_review(
                    user_id=user_id,
                    review_prompt=workflow.get('task_prompt', ''),
                    document_ids=review_config.get('document_ids'),
                    invoke_prompt=invoke_prompt,
                    doc_scope=review_config.get('doc_scope'),
                    active_group_ids=review_config.get('active_group_ids'),
                    active_public_workspace_id=review_config.get('active_public_workspace_id'),
                    window_unit=review_config.get('window_unit'),
                    window_size=review_config.get('window_size'),
                    window_percent=review_config.get('window_percent'),
                    max_retries_per_window=review_config.get('max_retries_per_window'),
                    activity_callback=activity_callback,
                    max_documents=workflow_review_max_documents,
                )
                agent_citations = _build_agent_citations_from_invocations(user_id, conversation_id)
                alert_targets = _collect_agent_alert_targets(user_id, conversation_id)

                return {
                    'reply': _resolve_document_action_reply(review_result),
                    'review_result': review_result,
                    'review_coverage': review_result.get('coverage') or {},
                    'model_deployment_name': getattr(loaded_agent, 'deployment_name', None) or requested_name,
                    'provider': 'agent',
                    'agent_name': getattr(loaded_agent, 'name', None) or requested_name,
                    'agent_display_name': getattr(loaded_agent, 'display_name', None) or selected_agent.get('display_name') or requested_name,
                    'agent_citations': agent_citations,
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

    client, deployment_name, provider = _resolve_model_workflow_client(workflow, settings)

    def invoke_model_prompt(prompt_text, stage='window_review', metadata=None):
        completion = client.chat.completions.create(
            model=deployment_name,
            messages=[{'role': 'user', 'content': prompt_text}],
        )
        if not getattr(completion, 'choices', None):
            return ''
        return _extract_message_text(completion.choices[0].message.content)

    review_result = run_exhaustive_document_review(
        user_id=user_id,
        review_prompt=workflow.get('task_prompt', ''),
        document_ids=review_config.get('document_ids'),
        invoke_prompt=invoke_model_prompt,
        doc_scope=review_config.get('doc_scope'),
        active_group_ids=review_config.get('active_group_ids'),
        active_public_workspace_id=review_config.get('active_public_workspace_id'),
        window_unit=review_config.get('window_unit'),
        window_size=review_config.get('window_size'),
        window_percent=review_config.get('window_percent'),
        max_retries_per_window=review_config.get('max_retries_per_window'),
        activity_callback=activity_callback,
        max_documents=workflow_review_max_documents,
    )
    debug_print(
        '[WorkflowExhaustiveReview] Completed workflow action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f'provider={provider} | '
        f'model={deployment_name} | '
        f"processed_windows={(review_result.get('coverage') or {}).get('processed_windows', 0)} | "
        f"failed_windows={(review_result.get('coverage') or {}).get('failed_windows', 0)}"
    )
    return {
        'reply': _resolve_document_action_reply(review_result),
        'review_result': review_result,
        'review_coverage': review_result.get('coverage') or {},
        'model_deployment_name': deployment_name,
        'provider': provider,
    }


def _execute_document_comparison_workflow(
    workflow,
    settings,
    conversation_id='',
    run_id=None,
    thought_tracker=None,
    external_activity_callback=None,
    action_config=None,
):
    comparison_config = action_config if isinstance(action_config, dict) else _get_document_action_config(workflow)
    if comparison_config.get('type') != DOCUMENT_ACTION_TYPE_COMPARISON:
        raise ValueError('Document comparison is not enabled for this workflow.')

    activity_callback = _chain_activity_callbacks(
        _build_document_action_activity_callback(workflow, run_id, thought_tracker=thought_tracker),
        external_activity_callback,
    )
    user_id = str(workflow.get('user_id') or '').strip()
    selected_agent = workflow.get('selected_agent') if isinstance(workflow.get('selected_agent'), dict) else {}
    debug_print(
        '[WorkflowDocumentComparison] Starting workflow action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f"runner_type={workflow.get('runner_type')} | "
        f'conversation_id={conversation_id} | '
        f"left_document_id={comparison_config.get('left_document_id')} | "
        f"right_count={len(comparison_config.get('right_document_ids') or [])}"
    )

    if workflow.get('runner_type') == 'agent':
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

            try:
                kernel = Kernel()
                kernel, agent_objs = load_user_semantic_kernel(kernel, settings, user_id, None)
                if not agent_objs:
                    raise ValueError('The selected agent could not be loaded for document comparison.')

                loaded_agent = None
                requested_name = str(selected_agent.get('name') or '').strip()
                if requested_name:
                    loaded_agent = agent_objs.get(requested_name)
                if loaded_agent is None:
                    loaded_agent = next(iter(agent_objs.values()))

                if thought_tracker and run_id and conversation_id:
                    callback_key = register_plugin_invocation_thought_callback(
                        plugin_logger,
                        thought_tracker,
                        user_id,
                        conversation_id,
                        actor_label='Workflow agent',
                    )

                def invoke_prompt(prompt_text, stage='window_review', metadata=None):
                    result = asyncio.run(loaded_agent.invoke([
                        ChatMessageContent(role='user', content=prompt_text),
                    ]))
                    return str(result)

                comparison_result = run_document_comparison(
                    user_id=user_id,
                    comparison_prompt=workflow.get('task_prompt', ''),
                    action_config=comparison_config,
                    invoke_prompt=invoke_prompt,
                    activity_callback=activity_callback,
                    conversation_id=conversation_id,
                )
                agent_citations = _build_agent_citations_from_invocations(user_id, conversation_id)
                alert_targets = _collect_agent_alert_targets(user_id, conversation_id)

                return {
                    'reply': _resolve_document_action_reply(comparison_result),
                    'review_result': comparison_result,
                    'review_coverage': comparison_result.get('coverage') or {},
                    'model_deployment_name': getattr(loaded_agent, 'deployment_name', None) or requested_name,
                    'provider': 'agent',
                    'agent_name': getattr(loaded_agent, 'name', None) or requested_name,
                    'agent_display_name': getattr(loaded_agent, 'display_name', None) or selected_agent.get('display_name') or requested_name,
                    'agent_citations': agent_citations,
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

    client, deployment_name, provider = _resolve_model_workflow_client(workflow, settings)

    def invoke_model_prompt(prompt_text, stage='window_review', metadata=None):
        completion = client.chat.completions.create(
            model=deployment_name,
            messages=[{'role': 'user', 'content': prompt_text}],
        )
        if not getattr(completion, 'choices', None):
            return ''
        return _extract_message_text(completion.choices[0].message.content)

    comparison_result = run_document_comparison(
        user_id=user_id,
        comparison_prompt=workflow.get('task_prompt', ''),
        action_config=comparison_config,
        invoke_prompt=invoke_model_prompt,
        activity_callback=activity_callback,
        conversation_id=conversation_id,
    )
    debug_print(
        '[WorkflowDocumentComparison] Completed workflow action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f'provider={provider} | '
        f'model={deployment_name} | '
        f"processed_windows={(comparison_result.get('coverage') or {}).get('processed_windows', 0)} | "
        f"failed_windows={(comparison_result.get('coverage') or {}).get('failed_windows', 0)}"
    )
    return {
        'reply': _resolve_document_action_reply(comparison_result),
        'review_result': comparison_result,
        'review_coverage': comparison_result.get('coverage') or {},
        'model_deployment_name': deployment_name,
        'provider': provider,
    }


def _execute_document_action_workflow(
    workflow,
    settings,
    conversation_id='',
    run_id=None,
    thought_tracker=None,
    external_activity_callback=None,
):
    action_config = _get_document_action_config(workflow)
    action_type = action_config.get('type')
    debug_print(
        '[WorkflowDocumentAction] Dispatching action | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f'action_type={action_type} | '
        f"runner_type={workflow.get('runner_type')} | "
        f'conversation_id={conversation_id}'
    )

    try:
        if action_type == DOCUMENT_ACTION_TYPE_EXHAUSTIVE_REVIEW:
            result = _execute_exhaustive_review_workflow(
                workflow,
                settings,
                conversation_id=conversation_id,
                run_id=run_id,
                thought_tracker=thought_tracker,
                external_activity_callback=external_activity_callback,
                action_config=action_config,
            )
        elif action_type == DOCUMENT_ACTION_TYPE_COMPARISON:
            result = _execute_document_comparison_workflow(
                workflow,
                settings,
                conversation_id=conversation_id,
                run_id=run_id,
                thought_tracker=thought_tracker,
                external_activity_callback=external_activity_callback,
                action_config=action_config,
            )
        else:
            raise ValueError('No document action is enabled for this workflow.')
    except Exception as exc:
        debug_print(
            '[WorkflowDocumentAction] Action failed | '
            f"workflow_id={workflow.get('id')} | "
            f'run_id={run_id} | '
            f'action_type={action_type} | '
            f"runner_type={workflow.get('runner_type')} | "
            f'error={exc}'
        )
        raise

    debug_print(
        '[WorkflowDocumentAction] Action completed | '
        f"workflow_id={workflow.get('id')} | "
        f'run_id={run_id} | '
        f'action_type={action_type} | '
        f"provider={result.get('provider')} | "
        f"model={result.get('model_deployment_name')} | "
        f"processed_windows={(result.get('review_coverage') or {}).get('processed_windows', 0)} | "
        f"failed_windows={(result.get('review_coverage') or {}).get('failed_windows', 0)}"
    )
    return result


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
            agent_citations = _build_agent_citations_from_invocations(user_id, conversation_id)
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
                'agent_citations': agent_citations,
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

        document_action = _get_document_action_config(workflow)
        if document_action.get('type') != DOCUMENT_ACTION_TYPE_NONE:
            execution_result = _execute_document_action_workflow(
                workflow,
                settings,
                conversation_id=conversation.get('id'),
                run_id=run_id,
                thought_tracker=thought_tracker,
            )
        elif workflow.get('runner_type') == 'agent':
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
        _mirror_workflow_visualizations_to_created_conversations(
            workflow,
            assistant_doc,
            execution_result,
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
            'review_coverage': execution_result.get('review_coverage') or {},
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