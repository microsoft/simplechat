# route_backend_chats.py
from semantic_kernel import Kernel
from semantic_kernel.agents.runtime import InProcessRuntime
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import AzureChatPromptExecutionSettings
from semantic_kernel_fact_memory_store import FactMemoryStore
from semantic_kernel_loader import initialize_semantic_kernel
from semantic_kernel_plugins.plugin_invocation_thoughts import (
    register_plugin_invocation_thought_callback,
)
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger, sanitize_plugin_invocation_value
from semantic_kernel_plugins.chart_plugin import ChartPlugin
from foundry_agent_runtime import FoundryAgentInvocationError, FoundryAgentUserAuthenticationRequired, execute_foundry_agent, resolve_authority
from model_endpoint_clients import (
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    build_anthropic_chat_client,
    build_openai_style_chat_client,
    infer_model_endpoint_protocol,
)
from functions_model_endpoint_runtime import (
    MODEL_ENDPOINT_PROVIDER_ALLOWLIST,
    build_model_endpoint_context,
    build_semantic_kernel_chat_service_for_model,
)
import builtins
import asyncio, types
import ast
import csv
import io
import inspect
import json
import mimetypes
import os
import app_settings_cache
import queue
import re
import requests
import traceback
from urllib.parse import urlparse
import threading
from typing import Any, Dict, List, Mapping, Optional, Tuple
from config import *
from flask import Response, copy_current_request_context, g, has_request_context, stream_with_context
from functions_authentication import *
from functions_search import *
from functions_service_health import (
    SEMANTIC_SEARCH_QUOTA_WARNING_TYPE,
    SemanticSearchQuotaExceededError,
)
from functions_settings import *
from functions_assigned_knowledge import (
    ASSIGNED_KNOWLEDGE_USER_ACTION_ANALYZE,
    ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE,
    ASSIGNED_KNOWLEDGE_USER_ACTION_SEARCH,
    ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH,
    ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_URL_REVIEW,
    build_assigned_knowledge_runtime_filters,
    resolve_assigned_knowledge_active_documents,
)
from functions_global_agents import get_global_agents
from functions_group_agents import get_group_agents
from functions_personal_agents import get_personal_agents
from functions_source_review import (
    build_deep_research_ledger,
    build_deep_research_ledger_markdown,
    build_deep_research_query_plan,
    build_research_search_prompt,
    compact_deep_research_result_for_metadata,
    compact_source_review_result_for_metadata,
    extract_urls_from_text,
    get_deep_research_config,
    get_url_access_max_urls,
    is_source_review_enabled_for_user,
    is_url_access_enabled_for_user,
    normalize_review_url,
    perform_source_review,
    validate_url_access_request,
    URL_ACCESS_CONTEXT_CHAT,
)
from functions_agents import get_agent_id_by_name
from functions_group import find_group_by_id, get_group_model_endpoints, get_user_role_in_group
from functions_chat import *
from functions_content import generate_embedding, generate_embeddings_batch
from functions_assistant_table_exports import (
    TABLE_EXPORT_REQUEST_MARKERS,
    build_assistant_table_csv_export,
)
from functions_chart_operations import (
    CORE_CHART_PLUGIN_NAME,
    INLINE_CHART_BLOCK_LANGUAGE,
    build_proactive_chart_guidance_message,
    normalize_chart_kind,
    user_request_supports_proactive_charts,
)
from functions_conversation_metadata import collect_conversation_metadata, update_conversation_with_metadata
from functions_conversation_unread import mark_conversation_unread
from functions_image_messages import build_image_message_documents, decode_image_content
from functions_icon_utils import normalize_icon_payload
from functions_image_generation import (
    build_image_proposal_guidance_message,
    generate_chat_image_message,
    image_generation_is_enabled,
    normalize_image_proposal,
    user_request_supports_image_proposals,
)
from functions_appinsights import log_event
from functions_debug import debug_print
from functions_governance import ensure_governance_access
from functions_notifications import create_chat_response_notification
from functions_activity_logging import log_agent_run, log_chat_activity, log_conversation_creation, log_token_usage
from flask import current_app
from swagger_wrapper import swagger_route, get_auth_security
from azure.identity import ClientSecretCredential, DefaultAzureCredential, get_bearer_token_provider
from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
from functions_message_artifacts import (
    build_agent_citation_tool_label,
    build_agent_citation_artifact_documents,
    build_message_artifact_payload_map,
    filter_assistant_artifact_items,
    hydrate_agent_citations_from_artifacts,
    make_json_serializable,
)
from functions_message_masking import (
    SUPPORTED_MESSAGE_MASK_ACTIONS,
    apply_message_mask_action,
    remove_masked_content,
    resolve_mask_display_name,
)
from functions_document_actions import (
    DOCUMENT_ACTION_CONTEXT_CHAT,
    DOCUMENT_ACTION_TYPE_COMPARISON,
    DOCUMENT_ACTION_TYPE_ANALYZE,
    DOCUMENT_ACTION_TYPE_NONE,
    get_document_action_max_documents_by_type,
    get_enabled_document_action_types,
    normalize_document_action_config,
)
from functions_thoughts import ThoughtTracker
from functions_workflow_runner import _execute_document_action_workflow
from functions_simplechat_operations import (
    derive_conversation_title_from_message,
    upload_chat_image_bytes_for_user,
    upload_generated_analysis_artifact_for_current_user,
)
from functions_tabular_generated_exports import (
    build_background_tabular_generated_output_metadata,
    get_tabular_generated_output_run_status,
    queue_tabular_generated_output_run,
    resume_tabular_generated_output_run,
    should_queue_tabular_generated_output_background,
)


DEFAULT_CONVERSATION_TITLE = 'New Conversation'
ASSIGNED_KNOWLEDGE_DOCUMENT_ACTION_MAP = {
    DOCUMENT_ACTION_TYPE_NONE: ASSIGNED_KNOWLEDGE_USER_ACTION_SEARCH,
    DOCUMENT_ACTION_TYPE_ANALYZE: ASSIGNED_KNOWLEDGE_USER_ACTION_ANALYZE,
    DOCUMENT_ACTION_TYPE_COMPARISON: ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE,
}
ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N = 12
ASSIGNED_KNOWLEDGE_CONTEXT_EXCERPT_MAX_CHARS = 1800
FOUNDRY_SELECTED_AGENT_TYPES = {'aifoundry', 'new_foundry', 'foundry_workflow'}
FOUNDRY_AGENT_PLUGIN_NAMES = {
    'aifoundry': 'azure_ai_foundry',
    'new_foundry': 'new_foundry',
    'foundry_workflow': 'foundry_workflow',
}
FOUNDRY_AGENT_LABELS = {
    'aifoundry': 'Azure AI Foundry Agent',
    'new_foundry': 'New Foundry Application',
    'foundry_workflow': 'Foundry Workflow',
}


def _is_foundry_selected_agent_type(agent_type):
    return str(agent_type or '').strip().lower() in FOUNDRY_SELECTED_AGENT_TYPES


def _get_foundry_agent_plugin_name(agent_type):
    return FOUNDRY_AGENT_PLUGIN_NAMES.get(
        str(agent_type or '').strip().lower(),
        'azure_ai_foundry',
    )


def _get_foundry_agent_label(agent_type):
    return FOUNDRY_AGENT_LABELS.get(
        str(agent_type or '').strip().lower(),
        'Azure AI Foundry Agent',
    )


def _build_foundry_runtime_metadata(agent):
    metadata = getattr(agent, 'last_run_metadata', None)
    return metadata if isinstance(metadata, dict) else {}


def _metadata_item_count(value):
    if isinstance(value, (list, tuple, set)):
        return len(value)
    if value in (None, '', 'all'):
        return 0
    return 1


def _safe_metadata_int(value):
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_capability_action(document_action_type):
    normalized_action_type = str(document_action_type or DOCUMENT_ACTION_TYPE_NONE).strip().lower()
    if normalized_action_type == DOCUMENT_ACTION_TYPE_ANALYZE:
        return ASSIGNED_KNOWLEDGE_USER_ACTION_ANALYZE
    if normalized_action_type == DOCUMENT_ACTION_TYPE_COMPARISON:
        return ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE
    return ASSIGNED_KNOWLEDGE_USER_ACTION_SEARCH


def _source_review_metadata_used(source_review_result):
    if not isinstance(source_review_result, dict):
        return False
    coverage = source_review_result.get('coverage') if isinstance(source_review_result.get('coverage'), dict) else {}
    return bool(
        source_review_result.get('system_message')
        or source_review_result.get('citations')
        or coverage.get('pages_reviewed')
        or coverage.get('pages_skipped')
    )


def _deep_research_query_count(query_plan, web_search_runs):
    if isinstance(query_plan, dict) and isinstance(query_plan.get('queries'), list):
        return len(query_plan.get('queries') or [])
    if isinstance(web_search_runs, list):
        return len(web_search_runs)
    return 0


def _build_capability_usage_metadata(
    *,
    workspace_search_enabled=False,
    workspace_search_used=False,
    workspace_search_result_count=0,
    document_action_type=DOCUMENT_ACTION_TYPE_NONE,
    document_scope=None,
    selected_document_ids=None,
    active_group_ids=None,
    active_public_workspace_ids=None,
    web_search_enabled=False,
    web_search_used=False,
    web_search_citation_count=0,
    web_search_run_count=0,
    url_access_enabled=False,
    source_review_enabled=False,
    source_review_used=False,
    deep_research_enabled=False,
    deep_research_used=False,
    deep_research_query_count=0,
):
    action = _normalize_capability_action(document_action_type)
    analyze_used = action == ASSIGNED_KNOWLEDGE_USER_ACTION_ANALYZE
    compare_used = action == ASSIGNED_KNOWLEDGE_USER_ACTION_COMPARE
    search_enabled = bool(workspace_search_enabled)
    search_used = bool(workspace_search_used)
    workspace_used = bool(search_used or analyze_used or compare_used)

    return {
        'actions': {
            'search': search_used,
            'analyze': analyze_used,
            'compare': compare_used,
        },
        'workspace': {
            'enabled': bool(search_enabled or analyze_used or compare_used),
            'used': workspace_used,
            'action': action,
            'document_action_type': str(document_action_type or DOCUMENT_ACTION_TYPE_NONE),
            'search_enabled': search_enabled,
            'search_used': search_used,
            'result_count': _safe_metadata_int(workspace_search_result_count),
            'document_scope': document_scope or 'all',
            'selected_document_count': _metadata_item_count(selected_document_ids),
            'active_group_count': _metadata_item_count(active_group_ids),
            'active_public_workspace_count': _metadata_item_count(active_public_workspace_ids),
        },
        'web_search': {
            'enabled': bool(web_search_enabled),
            'used': bool(web_search_used),
            'citation_count': _safe_metadata_int(web_search_citation_count),
            'run_count': _safe_metadata_int(web_search_run_count),
        },
        'url_access': {
            'enabled': bool(url_access_enabled),
            'used': bool(source_review_used and not deep_research_enabled),
            'source_review_enabled': bool(source_review_enabled),
        },
        'deep_research': {
            'enabled': bool(deep_research_enabled),
            'used': bool(deep_research_used),
            'query_count': _safe_metadata_int(deep_research_query_count),
            'source_review_enabled': bool(source_review_enabled and deep_research_enabled),
        },
    }


def _assigned_knowledge_allows_user_workspace_context(assigned_knowledge_filters):
    return bool(
        isinstance(assigned_knowledge_filters, dict)
        and assigned_knowledge_filters.get('allow_user_workspace_context')
    )


def _assigned_knowledge_allows_document_action(assigned_knowledge_filters, document_action_type):
    if not _assigned_knowledge_allows_user_workspace_context(assigned_knowledge_filters):
        return False
    required_action = ASSIGNED_KNOWLEDGE_DOCUMENT_ACTION_MAP.get(
        document_action_type or DOCUMENT_ACTION_TYPE_NONE,
        ASSIGNED_KNOWLEDGE_USER_ACTION_SEARCH,
    )
    allowed_actions = assigned_knowledge_filters.get('allowed_user_workspace_actions') or []
    return required_action in allowed_actions


def _build_assigned_knowledge_search_args(assigned_knowledge_filters, *, query, user_id, top_n):
    return {
        'query': query,
        'user_id': user_id,
        'top_n': top_n,
        'doc_scope': assigned_knowledge_filters.get('doc_scope') or 'all',
        'document_ids': list(assigned_knowledge_filters.get('document_ids') or []),
        'tags_filter': list(assigned_knowledge_filters.get('tags_filter') or []),
        'active_group_ids': list(assigned_knowledge_filters.get('active_group_ids') or []),
        'active_public_workspace_id': list(assigned_knowledge_filters.get('active_public_workspace_ids') or []),
        'document_filter_mode': assigned_knowledge_filters.get('document_filter_mode') or 'union',
        'enforce_public_workspace_visibility': False,
    }


def _is_search_ready_chat_upload_workspace_document(document_item):
    if not isinstance(document_item, dict):
        return False
    if document_item.get('chat_upload_link_state') == 'unlinked':
        return False
    if document_item.get('search_visibility_state') == 'archived':
        return False

    status = str(document_item.get('status') or '').strip().lower()
    if 'error' in status or 'failed' in status:
        return False

    try:
        indexed_chunk_count = int(document_item.get('number_of_pages') or document_item.get('num_chunks') or 0)
    except (TypeError, ValueError):
        indexed_chunk_count = 0
    if indexed_chunk_count <= 0:
        return False

    try:
        percentage_complete = int(document_item.get('percentage_complete') or 0)
    except (TypeError, ValueError):
        percentage_complete = 0

    return percentage_complete >= 100 or 'processing complete' in status


def _get_chat_upload_workspace_document_scope(document_item):
    if not isinstance(document_item, dict):
        return 'personal'
    if document_item.get('group_id'):
        return 'group'
    if document_item.get('public_workspace_id'):
        return 'public'
    return 'personal'


def _normalize_conversation_task_document_ids(document_ids):
    if document_ids in (None, '', 'all'):
        return []
    if not isinstance(document_ids, (list, tuple, set)):
        document_ids = [document_ids]

    normalized_document_ids = []
    seen_document_ids = set()
    for document_id in document_ids:
        normalized_document_id = str(document_id or '').strip()
        if not normalized_document_id or normalized_document_id in seen_document_ids:
            continue
        seen_document_ids.add(normalized_document_id)
        normalized_document_ids.append(normalized_document_id)
    return normalized_document_ids


def _resolve_conversation_task_documents(
    *,
    user_id,
    conversation_id,
    document_action_type=DOCUMENT_ACTION_TYPE_NONE,
    assigned_knowledge_filters=None,
    candidate_document_ids=None,
):
    result = {
        'document_ids': [],
        'documents': [],
        'scope_set': set(),
        'linked_count': 0,
        'pending_count': 0,
        'pending_document_ids': [],
        'blocked': False,
        'block_reason': None,
    }
    normalized_conversation_id = str(conversation_id or '').strip()
    if not normalized_conversation_id:
        return result

    candidate_id_list = _normalize_conversation_task_document_ids(candidate_document_ids)
    candidate_id_set = set(candidate_id_list)

    try:
        from functions_documents import get_chat_upload_workspace_documents_for_conversation

        linked_documents = get_chat_upload_workspace_documents_for_conversation(user_id, normalized_conversation_id)
    except Exception as exc:
        debug_print(f"[ConversationTaskDocuments] Failed to resolve linked workspace documents: {exc}")
        return result

    action_allowed = not assigned_knowledge_filters or _assigned_knowledge_allows_document_action(
        assigned_knowledge_filters,
        document_action_type,
    )

    seen_document_ids = set()
    for document_item in linked_documents or []:
        document_id = str(document_item.get('id') or '').strip() if isinstance(document_item, dict) else ''
        if not document_id or document_id in seen_document_ids:
            continue
        if candidate_id_set and document_id not in candidate_id_set:
            continue

        result['linked_count'] += 1
        if not action_allowed:
            seen_document_ids.add(document_id)
            continue

        if not _is_search_ready_chat_upload_workspace_document(document_item):
            result['pending_count'] += 1
            result['pending_document_ids'].append(document_id)
            seen_document_ids.add(document_id)
            continue

        document_scope = _get_chat_upload_workspace_document_scope(document_item)
        seen_document_ids.add(document_id)
        result['document_ids'].append(document_id)
        result['documents'].append(document_item)
        result['scope_set'].add(document_scope)

    if not action_allowed and result['linked_count']:
        result['blocked'] = True
        result['block_reason'] = 'assigned_knowledge_action_not_allowed'
        debug_print(
            '[ConversationTaskDocuments] Assigned Knowledge blocked linked chat upload documents | '
            f'conversation_id={normalized_conversation_id} | '
            f'action_type={document_action_type or DOCUMENT_ACTION_TYPE_NONE} | '
            f'linked_count={result["linked_count"]}'
        )

    return result


def _merge_document_scope_with_conversation_task_documents(
    effective_document_scope,
    task_documents,
    *,
    assigned_knowledge_filters=None,
    assigned_knowledge_user_context_active=False,
):
    normalized_scope = str(effective_document_scope or '').strip().lower()
    linked_scopes = {
        _get_chat_upload_workspace_document_scope(document_item)
        for document_item in task_documents or []
        if isinstance(document_item, dict)
    }
    if not linked_scopes:
        return effective_document_scope

    if normalized_scope in ('', 'none', 'null'):
        normalized_scope = 'personal'
    if normalized_scope == 'all' or len(linked_scopes) > 1:
        return 'all'
    if len(linked_scopes) == 1:
        linked_scope = next(iter(linked_scopes))
        return normalized_scope if normalized_scope == linked_scope else 'all'

    return 'all'


def _resolve_chat_upload_workspace_context(
    *,
    user_id,
    conversation_id,
    effective_document_scope,
    effective_selected_document_ids,
    assigned_knowledge_filters=None,
    assigned_knowledge_user_context_active=False,
    candidate_document_ids=None,
):
    task_resolution = _resolve_conversation_task_documents(
        user_id=user_id,
        conversation_id=conversation_id,
        document_action_type=DOCUMENT_ACTION_TYPE_NONE,
        assigned_knowledge_filters=assigned_knowledge_filters,
        candidate_document_ids=candidate_document_ids,
    )
    context_result = {
        'effective_document_scope': effective_document_scope,
        'effective_selected_document_ids': list(effective_selected_document_ids or []),
        'auto_linked_chat_upload_document_ids': [],
        'task_resolution': task_resolution,
    }
    if task_resolution.get('blocked'):
        return context_result

    linked_document_ids = list(task_resolution.get('document_ids') or [])
    if not linked_document_ids:
        return context_result

    base_document_ids = list(effective_selected_document_ids or [])
    if (
        assigned_knowledge_filters
        and assigned_knowledge_filters.get('has_workspace_knowledge')
        and not assigned_knowledge_user_context_active
    ):
        base_document_ids = []

    merged_document_ids = []
    seen_document_ids = set()
    for document_id in base_document_ids + linked_document_ids:
        normalized_document_id = str(document_id or '').strip()
        if not normalized_document_id or normalized_document_id in seen_document_ids:
            continue
        seen_document_ids.add(normalized_document_id)
        merged_document_ids.append(normalized_document_id)

    explicit_document_id_set = {
        str(item or '').strip()
        for item in base_document_ids
        if str(item or '').strip()
    }
    auto_linked_document_ids = [
        document_id
        for document_id in linked_document_ids
        if document_id in seen_document_ids and document_id not in explicit_document_id_set
    ]
    if not auto_linked_document_ids:
        context_result['effective_selected_document_ids'] = merged_document_ids
        return context_result

    merged_scope_source = effective_document_scope
    linked_scope_set = task_resolution.get('scope_set') if isinstance(task_resolution.get('scope_set'), set) else set()
    if (
        assigned_knowledge_filters
        and assigned_knowledge_filters.get('has_workspace_knowledge')
        and not assigned_knowledge_user_context_active
        and len(linked_scope_set) == 1
    ):
        merged_scope_source = next(iter(linked_scope_set))

    merged_scope = _merge_document_scope_with_conversation_task_documents(
        merged_scope_source,
        task_resolution.get('documents') or [],
        assigned_knowledge_filters=assigned_knowledge_filters,
        assigned_knowledge_user_context_active=assigned_knowledge_user_context_active,
    )
    context_result['effective_document_scope'] = merged_scope
    context_result['effective_selected_document_ids'] = merged_document_ids
    context_result['auto_linked_chat_upload_document_ids'] = auto_linked_document_ids
    return context_result


def _merge_chat_upload_workspace_context(
    *,
    user_id,
    conversation_id,
    effective_document_scope,
    effective_selected_document_ids,
    assigned_knowledge_filters=None,
    assigned_knowledge_user_context_active=False,
    candidate_document_ids=None,
):
    context_result = _resolve_chat_upload_workspace_context(
        user_id=user_id,
        conversation_id=conversation_id,
        effective_document_scope=effective_document_scope,
        effective_selected_document_ids=effective_selected_document_ids,
        assigned_knowledge_filters=assigned_knowledge_filters,
        assigned_knowledge_user_context_active=assigned_knowledge_user_context_active,
        candidate_document_ids=candidate_document_ids,
    )
    return (
        context_result.get('effective_document_scope'),
        list(context_result.get('effective_selected_document_ids') or []),
        list(context_result.get('auto_linked_chat_upload_document_ids') or []),
    )


def _build_chat_upload_pending_response_payload(task_resolution):
    return {
        'error': 'Uploaded task documents are still processing. Try again when the upload is ready.',
        'pending': True,
        'pending_count': _safe_metadata_int((task_resolution or {}).get('pending_count')),
        'linked_count': _safe_metadata_int((task_resolution or {}).get('linked_count')),
    }


def _has_nonpending_requested_task_document_selection(data, task_resolution):
    data = data if isinstance(data, dict) else {}
    requested_document_ids = _normalize_conversation_task_document_ids(data.get('selected_document_ids'))
    requested_document_ids.extend(_normalize_conversation_task_document_ids(data.get('selected_document_id')))
    pending_document_ids = {
        str(document_id or '').strip()
        for document_id in (task_resolution or {}).get('pending_document_ids') or []
        if str(document_id or '').strip()
    }
    if not requested_document_ids:
        return False
    return any(document_id not in pending_document_ids for document_id in requested_document_ids)


def _get_assigned_knowledge_web_source_urls(assigned_knowledge_filters, mode=None):
    if not isinstance(assigned_knowledge_filters, dict):
        return []
    urls = []
    seen_urls = set()
    for source in assigned_knowledge_filters.get('web_sources') or []:
        if not isinstance(source, dict):
            continue
        source_url = str(source.get('url') or '').strip()
        source_mode = str(source.get('mode') or ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_URL_REVIEW).strip()
        if not source_url or source_url in seen_urls:
            continue
        if mode and source_mode != mode:
            continue
        seen_urls.add(source_url)
        urls.append(source_url)
    return urls


def _is_assigned_knowledge_inventory_request(user_message):
    normalized_message = re.sub(r"\s+", " ", str(user_message or "").strip().lower())
    if not normalized_message:
        return False

    knowledge_terms = (
        "document",
        "documents",
        "file",
        "files",
        "knowledge",
        "source",
        "sources",
    )
    if not any(term in normalized_message for term in knowledge_terms):
        return False

    inventory_phrases = (
        "what documents",
        "which documents",
        "what files",
        "which files",
        "list documents",
        "list the documents",
        "show documents",
        "show the documents",
        "how many documents",
        "how many files",
        "documents do you have access",
        "documents can you access",
        "files do you have access",
        "files can you access",
        "what knowledge",
        "which knowledge",
        "assigned knowledge",
        "what sources",
        "which sources",
    )
    return any(phrase in normalized_message for phrase in inventory_phrases)


def _build_assigned_knowledge_inventory_aug_message(user_id, assigned_knowledge_filters, user_message):
    active_documents = resolve_assigned_knowledge_active_documents(user_id, assigned_knowledge_filters)
    web_sources = (assigned_knowledge_filters.get('web_sources') or []) if isinstance(assigned_knowledge_filters, dict) else []
    document_lines = []
    for index, document in enumerate(active_documents, start=1):
        title = str(document.get('title') or document.get('file_name') or document.get('id') or 'Untitled document').strip()
        source_name = str(document.get('source_name') or document.get('scope') or 'source').strip()
        scope = str(document.get('scope') or '').strip()
        tags = document.get('tags') or []
        tag_text = f"; Tags: {', '.join(tags)}" if tags else ""
        document_lines.append(f"{index}. {title} (Source workspace: {source_name}; Scope: {scope}{tag_text})")

    if document_lines:
        document_inventory = "\n".join(document_lines)
    else:
        document_inventory = "No indexed workspace documents are active for this agent."

    web_source_lines = []
    for index, source in enumerate(web_sources, start=1):
        url = str(source.get('url') or '').strip()
        if not url:
            continue
        mode = str(source.get('mode') or 'url_review').strip()
        web_source_lines.append(f"{index}. {url} ({mode})")
    web_source_inventory = "\n".join(web_source_lines) if web_source_lines else "No assigned web sources."

    content = (
        "The user is asking what documents, files, sources, or assigned knowledge this agent can access. "
        "Answer deterministically from the inventory below. State the exact active indexed workspace document count. "
        "If the user asks what documents are available, list every active indexed workspace document below; do not list only retrieved citations. "
        "Mention assigned web sources separately because they are reviewed live and are not indexed workspace documents.\n\n"
        f"User question: {user_message}\n\n"
        f"Active indexed workspace documents: {len(active_documents)}\n"
        f"{document_inventory}\n\n"
        f"Assigned web sources: {len(web_source_lines)}\n"
        f"{web_source_inventory}"
    )
    return {
        'role': 'system',
        'content': content,
        'documents': active_documents,
        'assigned_knowledge_inventory': {
            'active_document_count': len(active_documents),
            'web_source_count': len(web_source_lines),
        }
    }


def _merge_search_results_by_identity(*result_sets):
    merged_results = []
    seen_keys = set()
    for result_set in result_sets:
        for result in result_set or []:
            if not isinstance(result, dict):
                continue
            identity = (
                result.get('id')
                or f"{result.get('document_id') or ''}:{result.get('chunk_id') or result.get('chunk_sequence') or ''}"
            )
            if identity in seen_keys:
                continue
            seen_keys.add(identity)
            merged_results.append(result)
    return merged_results


def _get_search_result_identity(result):
    if not isinstance(result, dict):
        return ''
    return (
        result.get('id')
        or f"{result.get('document_id') or ''}:{result.get('chunk_id') or result.get('chunk_sequence') or ''}"
    )


def _is_personal_or_group_search_result(result, user_id=None):
    if not isinstance(result, dict):
        return False

    normalized_user_id = str(user_id or '').strip()
    result_scope = str(result.get('scope') or '').strip().lower()
    result_user_id = str(result.get('user_id') or '').strip()
    if result_scope == 'personal':
        return bool(normalized_user_id and result_user_id == normalized_user_id)
    if result_scope == 'group':
        return bool(result.get('group_id'))
    if result_scope == 'public' or result.get('public_workspace_id'):
        return False
    if result.get('group_id'):
        return True
    if result_user_id:
        return bool(normalized_user_id and result_user_id == normalized_user_id)
    return False


def _merge_assigned_knowledge_user_context_search_results(assigned_results, user_context_results, *, top_n, user_id=None):
    assigned_limit = max(0, int(top_n or 0))
    merged_results = []
    seen_keys = set()

    for result in (assigned_results or [])[:assigned_limit]:
        if not isinstance(result, dict):
            continue
        identity = _get_search_result_identity(result)
        if identity in seen_keys:
            continue
        seen_keys.add(identity)
        merged_results.append(result)

    user_context_appended_count = 0
    for result in user_context_results or []:
        if not _is_personal_or_group_search_result(result, user_id=user_id):
            continue
        identity = _get_search_result_identity(result)
        if identity in seen_keys:
            continue
        seen_keys.add(identity)
        merged_results.append(result)
        user_context_appended_count += 1

    debug_print(
        "[AssignedKnowledge] Merged assigned and user workspace search results | "
        f"assigned_count={min(len(assigned_results or []), assigned_limit)} | "
        f"user_context_appended={user_context_appended_count} | total={len(merged_results)}"
    )
    return merged_results


def _truncate_assigned_knowledge_context_text(value, max_chars=ASSIGNED_KNOWLEDGE_CONTEXT_EXCERPT_MAX_CHARS):
    normalized_text = str(value or '').strip()
    if not normalized_text:
        return ''
    normalized_text = re.sub(r'\n{3,}', '\n\n', normalized_text)
    if len(normalized_text) <= max_chars:
        return normalized_text
    return f'{normalized_text[:max_chars].rstrip()}...'


def _build_workspace_search_citation_from_result(result, *, metadata_type=None, context_label=None):
    result = result if isinstance(result, dict) else {}
    chunk_text = result.get('chunk_text', '')
    file_name = result.get('file_name') or result.get('title') or 'Unknown'
    version = result.get('version', 'N/A')
    chunk_sequence = result.get('chunk_sequence', 0)
    page_number = result.get('page_number') or chunk_sequence or 1
    citation_id = result.get('id', str(uuid.uuid4()))
    document_id = str(result.get('document_id') or '').strip()
    if not document_id:
        document_id = (
            '_'.join(str(citation_id).split('_')[:-1])
            if '_' in str(citation_id)
            else str(citation_id)
        )
    chunk_id = result.get('chunk_id', str(uuid.uuid4()))
    sheet_name = result.get('sheet_name')
    location_label, location_value = get_citation_location(
        file_name,
        page_number=page_number,
        chunk_text=chunk_text,
        sheet_name=sheet_name,
    )

    citation = {
        'file_name': file_name,
        'document_id': document_id,
        'citation_id': citation_id,
        'page_number': page_number,
        'sheet_name': sheet_name,
        'location_label': location_label,
        'location_value': location_value,
        'chunk_id': chunk_id,
        'chunk_sequence': chunk_sequence,
        'score': result.get('score', 0.0),
        'group_id': result.get('group_id'),
        'public_workspace_id': result.get('public_workspace_id'),
        'version': version,
        'classification': result.get('document_classification'),
    }
    if metadata_type:
        citation['metadata_type'] = metadata_type
    if context_label:
        citation['context_label'] = context_label
    return citation


def _build_assigned_knowledge_reference_context(
    assigned_knowledge_filters,
    *,
    query,
    user_id,
    top_n=ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N,
):
    top_n = max(1, min(ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N, _safe_metadata_int(top_n) or ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N))
    enabled = bool(
        isinstance(assigned_knowledge_filters, dict)
        and assigned_knowledge_filters.get('has_workspace_knowledge')
    )
    context_payload = {
        'enabled': enabled,
        'searched': False,
        'top_n': top_n,
        'result_count': 0,
        'results': [],
        'citations': [],
        'context_block': '',
        'metadata': {
            'enabled': enabled,
            'searched': False,
            'top_n': top_n,
            'result_count': 0,
            'document_ids': [],
        },
    }
    if not enabled:
        return context_payload

    assigned_search_args = _build_assigned_knowledge_search_args(
        assigned_knowledge_filters,
        query=query,
        user_id=user_id,
        top_n=top_n,
    )
    search_results = list(hybrid_search(**assigned_search_args) or [])[:top_n]
    citations = []
    context_entries = []
    document_ids = []
    seen_document_ids = set()

    for index, result in enumerate(search_results, start=1):
        if not isinstance(result, dict):
            continue
        citation = _build_workspace_search_citation_from_result(
            result,
            metadata_type='assigned_knowledge_context',
            context_label='Assigned Knowledge',
        )
        citation['assigned_knowledge_context'] = True
        citations.append(citation)

        document_id = str(citation.get('document_id') or '').strip()
        if document_id and document_id not in seen_document_ids:
            seen_document_ids.add(document_id)
            document_ids.append(document_id)

        excerpt = _truncate_assigned_knowledge_context_text(result.get('chunk_text'))
        if not excerpt:
            continue
        context_entries.append(
            '\n'.join([
                f'[{index}] Source: {citation.get("file_name")}, {citation.get("location_label")}: {citation.get("location_value")} [#{citation.get("citation_id")}]',
                excerpt,
            ])
        )

    context_block = ''
    if context_entries:
        context_block = '\n\n'.join([
            'Assigned Knowledge Reference Context',
            'These are the top assigned-knowledge excerpts for the selected agent. Use them as reference context for the agent purpose and the user request.',
            *context_entries,
        ])

    context_payload.update({
        'searched': True,
        'result_count': len(search_results),
        'results': search_results,
        'citations': citations,
        'context_block': context_block,
        'metadata': {
            'enabled': True,
            'searched': True,
            'top_n': top_n,
            'result_count': len(search_results),
            'citation_count': len(citations),
            'document_ids': document_ids,
        },
    })
    return context_payload


def _build_document_action_prompt_with_assigned_knowledge_context(
    user_message,
    assigned_knowledge_context_block,
    document_action_type,
):
    context_block = str(assigned_knowledge_context_block or '').strip()
    if not context_block:
        return user_message

    normalized_action_type = str(document_action_type or DOCUMENT_ACTION_TYPE_NONE).strip().lower()
    if normalized_action_type == DOCUMENT_ACTION_TYPE_COMPARISON:
        action_instruction = 'Use the assigned knowledge as reference context while comparing the selected task documents.'
    elif normalized_action_type == DOCUMENT_ACTION_TYPE_ANALYZE:
        action_instruction = 'Use the assigned knowledge as reference context while analyzing the selected task documents.'
    else:
        action_instruction = 'Use the assigned knowledge as reference context while answering the user request.'

    return (
        f'{user_message}\n\n'
        '<AssignedKnowledgeReferenceContext>\n'
        f'{action_instruction}\n'
        'Do not treat these assigned-knowledge excerpts as task documents being analyzed or compared unless the user explicitly selected them as task documents.\n\n'
        f'{context_block}\n'
        '</AssignedKnowledgeReferenceContext>'
    )


def _conversation_title_is_default(title):
    return str(title or '').strip() in {'', DEFAULT_CONVERSATION_TITLE}


def _set_initial_conversation_title(conversation_item, user_message):
    if not isinstance(conversation_item, dict):
        return False

    if not _conversation_title_is_default(conversation_item.get('title')):
        return False

    derived_title = derive_conversation_title_from_message(user_message)
    if _conversation_title_is_default(derived_title):
        return False

    conversation_item['title'] = derived_title
    return True


def _build_conversation_metadata_stream_payload(conversation_item):
    return make_json_serializable({
        'type': 'conversation_metadata',
        'conversation_id': conversation_item.get('id'),
        'conversation_title': conversation_item.get('title', DEFAULT_CONVERSATION_TITLE),
        'title': conversation_item.get('title', DEFAULT_CONVERSATION_TITLE),
        'last_updated': conversation_item.get('last_updated'),
    })


def _build_conversation_metadata_stream_event(conversation_item):
    return f"data: {json.dumps(_build_conversation_metadata_stream_payload(conversation_item))}\n\n"


def _strip_agent_citation_artifact_refs(agent_citations):
    """Drop artifact references when auxiliary payload persistence fails."""
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


FACT_MEMORY_TYPE_FACT = 'fact'
FACT_MEMORY_TYPE_INSTRUCTION = 'instruction'
FACT_MEMORY_TYPE_LEGACY_DESCRIBER = 'describer'
INLINE_CHART_ID_PATTERN_TEMPLATE = '"chartId":"{}"'
TABULAR_INLINE_CHART_MAX_POINTS = 12
TABULAR_INLINE_CHART_MAX_CHARTS = 2
TABULAR_INLINE_CHARTABLE_FUNCTIONS = {'group_by_aggregate', 'group_by_datetime_component'}
TABULAR_INLINE_CHART_SUPPORTED_GROUP_KINDS = {
    'bar',
    'line',
    'pie',
    'doughnut',
    'area',
    'radar',
    'stacked_bar',
    'stacked_line',
}
STREAM_STATUS_NOT_FOUND = 'not_found'
STREAM_STATUS_STARTED = 'started'
STREAM_STATUS_STREAMING = 'streaming'
STREAM_STATUS_DETACHED_RUNNING = 'detached_running'
STREAM_STATUS_CANCEL_REQUESTED = 'cancel_requested'
STREAM_STATUS_COMPLETED = 'completed'
STREAM_STATUS_ERROR = 'error'
STREAM_STATUS_CANCELED = 'canceled'
TERMINAL_STREAM_STATUSES = {STREAM_STATUS_COMPLETED, STREAM_STATUS_ERROR, STREAM_STATUS_CANCELED}
ALLOWED_STREAM_CLIENT_EVENTS = {
    'stream_aborted',
    'stream_cancel_requested',
    'stream_premature_end',
    'stream_read_error',
    'stream_request_error',
    'stream_response_opened',
    'stream_recovery_attempt',
    'stream_recovery_attached',
    'stream_recovery_unavailable',
}
TABULAR_GENERATED_OUTPUT_PREVIEW_ROWS = 3
TABULAR_STRUCTURED_EXPORT_MAX_BATCH_ROWS = 50
TABULAR_STRUCTURED_EXPORT_MAX_BATCH_CHARS = 60000
TABULAR_STRUCTURED_EXPORT_MIN_BATCH_ROWS = 1
TABULAR_STRUCTURED_EXPORT_MIN_BATCH_CHARS = 6000
TABULAR_STRUCTURED_EXPORT_HARD_MAX_BATCH_ROWS = 100
TABULAR_STRUCTURED_EXPORT_HARD_MAX_BATCH_CHARS = 120000
TABULAR_STRUCTURED_EXPORT_MAX_RETRY_ATTEMPTS = 2
TABULAR_RELATED_DOCUMENT_MAX_MATCHES_PER_ROW = 3
TABULAR_RELATED_DOCUMENT_MAX_SUMMARY_ROWS = 8
TABULAR_RELATED_DOCUMENT_MAX_EXCERPT_CHARS = 500
TABULAR_GENERATED_OUTPUT_INTERNAL_ROW_FIELDS = {
    '_matched_columns',
    '_matched_values',
    '_related_document_reference_values',
}
TABULAR_GENERATED_OUTPUT_REFERENCED_DOCUMENT_FIELDS = (
    'file_name',
    'title',
    'matched_column',
    'matched_reference',
    'page_number',
    'excerpt',
)


def _get_user_message_image_context(conversation_id, user_message_id):
    """Return user and thread metadata from the prompt message for paired image messages."""
    try:
        user_message_doc = cosmos_messages_container.read_item(
            item=user_message_id,
            partition_key=conversation_id,
        )
        user_metadata = user_message_doc.get('metadata', {}) if isinstance(user_message_doc.get('metadata'), dict) else {}
        thread_info = user_metadata.get('thread_info', {}) if isinstance(user_metadata.get('thread_info'), dict) else {}
        return (
            user_metadata.get('user_info'),
            thread_info.get('thread_id'),
            thread_info.get('previous_thread_id'),
        )
    except Exception as exc:
        debug_print(f"[ImageGeneration] Warning: Could not retrieve user message metadata: {exc}")
        return None, None, None


def _resolve_generated_image_bytes(generated_image_url):
    """Resolve generated image output into bytes and a MIME type for blob storage."""
    normalized_image_url = str(generated_image_url or '').strip()
    if not normalized_image_url:
        raise ValueError('Generated image URL is empty')

    if normalized_image_url.startswith('data:image/'):
        return decode_image_content(normalized_image_url)

    parsed_url = urlparse(normalized_image_url)
    if parsed_url.scheme not in {'http', 'https'}:
        raise ValueError('Generated image output is not a supported image source')

    response = requests.get(normalized_image_url, timeout=30)
    response.raise_for_status()
    image_bytes = response.content
    if not image_bytes:
        raise ValueError('Generated image download returned empty content')

    content_type = str(response.headers.get('Content-Type') or '').split(';', 1)[0].strip()
    if not content_type or not content_type.startswith('image/'):
        content_type = mimetypes.guess_type(parsed_url.path)[0] or 'image/png'

    return content_type, image_bytes


def _normalize_generated_analysis_artifact_metadata(raw_artifact, default_capability='analysis'):
    if not isinstance(raw_artifact, dict):
        return None

    artifact_message_id = str(raw_artifact.get('artifact_message_id') or '').strip()
    document_id = str(raw_artifact.get('document_id') or '').strip()
    export_run_id = str(raw_artifact.get('export_run_id') or raw_artifact.get('run_id') or '').strip()
    if not artifact_message_id and not document_id and not export_run_id:
        return None

    normalized_artifact = dict(raw_artifact)
    normalized_artifact['capability'] = (
        str(raw_artifact.get('capability') or default_capability or 'analysis').strip().lower()
        or 'analysis'
    )
    if artifact_message_id:
        normalized_artifact['artifact_message_id'] = artifact_message_id
    if document_id:
        normalized_artifact['document_id'] = document_id
    if export_run_id:
        normalized_artifact['export_run_id'] = export_run_id
        normalized_artifact['background_export'] = bool(raw_artifact.get('background_export', True))

    normalized_output_format = str(raw_artifact.get('output_format') or '').strip().lower()
    if normalized_output_format:
        normalized_artifact['output_format'] = normalized_output_format

    normalized_conversation_id = str(raw_artifact.get('conversation_id') or '').strip()
    if normalized_conversation_id:
        normalized_artifact['conversation_id'] = normalized_conversation_id

    return normalized_artifact


def _build_generated_analysis_metadata(
    generated_analysis_artifacts=None,
    generated_tabular_outputs=None,
):
    normalized_artifacts = []
    normalized_tabular_outputs = []
    seen_artifacts = set()

    def append_artifact(raw_artifact, default_capability='analysis'):
        normalized_artifact = _normalize_generated_analysis_artifact_metadata(
            raw_artifact,
            default_capability=default_capability,
        )
        if not normalized_artifact:
            return

        dedupe_key = (
            normalized_artifact.get('artifact_message_id')
            or normalized_artifact.get('document_id')
            or normalized_artifact.get('export_run_id')
            or f"{normalized_artifact.get('file_name')}:{normalized_artifact.get('output_format')}"
        )
        if dedupe_key in seen_artifacts:
            return

        seen_artifacts.add(dedupe_key)
        normalized_artifacts.append(normalized_artifact)
        if normalized_artifact.get('capability') == 'tabular':
            normalized_tabular_outputs.append(dict(normalized_artifact))

    for artifact in generated_analysis_artifacts or []:
        append_artifact(artifact, default_capability='analysis')

    for artifact in generated_tabular_outputs or []:
        append_artifact(artifact, default_capability='tabular')

    return {
        'generated_analysis_artifacts': normalized_artifacts,
        'generated_tabular_outputs': normalized_tabular_outputs,
    }


def _maybe_create_deep_research_ledger_artifact(settings, conversation_id, ledger):
    """Save a Deep Research ledger as a generated chat artifact when enabled."""
    if not conversation_id or not isinstance(ledger, dict):
        return None

    deep_research_config = get_deep_research_config(settings)
    if not deep_research_config.get('deep_research_enable_ledger_artifact'):
        return None

    created_at = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    file_name = f"deep_research_ledger_{created_at}.md"
    try:
        upload_result = upload_generated_analysis_artifact_for_current_user(
            conversation_id=conversation_id,
            file_name=file_name,
            file_content=build_deep_research_ledger_markdown(ledger),
            capability='deep_research',
            output_format='md',
            summary='Deep Research ledger with search queries, reviewed sources, skipped URLs, and coverage details.',
        )
    except Exception as exc:
        log_event(
            '[DeepResearch] Failed to save Deep Research ledger artifact',
            {
                'conversation_id': conversation_id,
                'file_name': file_name,
                'error': str(exc),
            },
            debug_only=True,
        )
        return None

    uploaded_message = upload_result.get('message') or {}
    artifact_message_id = uploaded_message.get('id')
    if not artifact_message_id:
        return None

    uploaded_file_name = uploaded_message.get('file_name') or file_name
    artifact = {
        'capability': 'deep_research',
        'artifact_message_id': artifact_message_id,
        'conversation_id': conversation_id,
        'storage_scope': 'chat',
        'file_name': uploaded_file_name,
        'output_format': 'md',
        'summary': 'Deep Research ledger with search queries, reviewed sources, skipped URLs, and coverage details.',
    }
    log_event(
        '[DeepResearch] Saved Deep Research ledger artifact',
        {
            'conversation_id': conversation_id,
            'artifact_message_id': artifact_message_id,
            'file_name': uploaded_file_name,
        },
        debug_only=True,
    )
    return artifact


def _has_generated_tabular_csv_output(generated_outputs):
    for generated_output in generated_outputs or []:
        if not isinstance(generated_output, dict):
            continue

        capability = str(generated_output.get('capability') or '').strip().lower()
        output_format = str(generated_output.get('output_format') or '').strip().lower()
        file_name = str(generated_output.get('file_name') or '').strip().lower()
        if output_format == 'csv' or file_name.endswith('.csv'):
            if not capability or capability == 'tabular':
                return True

    return False


def maybe_create_assistant_table_generated_output(
    user_question,
    assistant_content,
    conversation_id,
    existing_outputs=None,
):
    """Save a CSV artifact when a table-request answer contains a parseable table."""
    if _has_generated_tabular_csv_output(existing_outputs):
        return None

    export_payload = build_assistant_table_csv_export(user_question, assistant_content)
    if not export_payload:
        return None

    generated_file_name = export_payload.get('file_name')
    row_count = _safe_int(export_payload.get('row_count'))
    try:
        upload_result = upload_generated_analysis_artifact_for_current_user(
            conversation_id=conversation_id,
            file_name=generated_file_name,
            file_content=export_payload.get('file_content'),
            capability='tabular',
            output_format='csv',
            summary=export_payload.get('summary'),
        )
    except Exception as exc:
        log_event(
            '[Assistant Table Export] Failed to save assistant table CSV artifact',
            {
                'conversation_id': conversation_id,
                'generated_file_name': generated_file_name,
                'row_count': row_count,
                'error': str(exc),
            },
            debug_only=True,
        )
        return None

    artifact_message_id = upload_result.get('message', {}).get('id')
    if not artifact_message_id:
        return None

    uploaded_file_name = upload_result.get('message', {}).get('file_name') or generated_file_name
    log_event(
        '[Assistant Table Export] Saved assistant table CSV artifact',
        {
            'conversation_id': conversation_id,
            'artifact_message_id': artifact_message_id,
            'generated_file_name': uploaded_file_name,
            'row_count': row_count,
        },
        debug_only=True,
    )
    return {
        'capability': 'tabular',
        'artifact_message_id': artifact_message_id,
        'conversation_id': conversation_id,
        'storage_scope': 'chat',
        'file_name': uploaded_file_name,
        'output_format': 'csv',
        'row_count': row_count,
        'preview_rows': export_payload.get('preview_rows') or [],
        'summary': export_payload.get('summary'),
    }


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bounded_int(value, default, minimum=None, maximum=None):
    parsed_value = _safe_int(value, default=default)
    if minimum is not None:
        parsed_value = max(parsed_value, minimum)
    if maximum is not None:
        parsed_value = min(parsed_value, maximum)
    return parsed_value


def _utcnow_iso():
    return datetime.utcnow().isoformat()


def _parse_iso_datetime(value):
    normalized = str(value or '').strip()
    if not normalized:
        return None

    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _truncate_log_text(value, max_length=500):
    normalized = str(value or '').strip()
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[:max_length]}..."


def _build_stream_status_payload(metadata):
    snapshot = dict(metadata or {})
    if not snapshot:
        return {
            'active': False,
            'pending': False,
            'reattachable': False,
            'status': STREAM_STATUS_NOT_FOUND,
        }

    snapshot['active'] = bool(snapshot.get('active'))
    snapshot['pending'] = snapshot['active']
    snapshot['reattachable'] = snapshot['active']
    snapshot['status'] = str(snapshot.get('status') or STREAM_STATUS_STARTED)
    snapshot['consumer_detached'] = bool(snapshot.get('consumer_detached'))
    snapshot['detach_count'] = _safe_int(snapshot.get('detach_count'))
    snapshot['reattach_count'] = _safe_int(snapshot.get('reattach_count'))
    snapshot['event_count'] = _safe_int(snapshot.get('event_count'))
    snapshot['content_event_count'] = _safe_int(snapshot.get('content_event_count'))
    snapshot['content_chars'] = _safe_int(snapshot.get('content_chars'))
    snapshot['queue_backpressure_count'] = _safe_int(snapshot.get('queue_backpressure_count'))

    started_at = _parse_iso_datetime(snapshot.get('started_at'))
    updated_at = _parse_iso_datetime(snapshot.get('updated_at'))
    completed_at = _parse_iso_datetime(snapshot.get('completed_at'))
    reference_time = completed_at if snapshot['status'] in TERMINAL_STREAM_STATUSES and completed_at else datetime.utcnow()
    if started_at:
        snapshot['elapsed_seconds'] = round(max((reference_time - started_at).total_seconds(), 0.0), 1)
    if updated_at:
        snapshot['seconds_since_update'] = round(max((datetime.utcnow() - updated_at).total_seconds(), 0.0), 1)

    return snapshot


def _build_stream_cancel_event(
    conversation_id,
    user_message_id=None,
    message_id=None,
    partial_content='',
    reason='user_requested',
    message_persisted=False,
    extra_payload=None,
):
    normalized_content = str(partial_content or '')
    payload = make_json_serializable({
        'type': 'cancelled',
        'done': True,
        'cancelled': True,
        'canceled': True,
        'conversation_id': conversation_id,
        'user_message_id': user_message_id,
        'message_id': message_id,
        'partial_content': normalized_content,
        'full_content': normalized_content,
        'cancel_reason': _truncate_log_text(reason, max_length=120) or 'user_requested',
        'message_persisted': bool(message_persisted),
        **dict(extra_payload or {}),
    })
    return f"data: {json.dumps(payload)}\n\n"


def _normalize_inline_chart_markdown(chart_markdown):
    block = str(chart_markdown or '').strip()
    if not block.startswith(f'```{INLINE_CHART_BLOCK_LANGUAGE}'):
        return None
    return block


def _collect_inline_chart_blocks(candidate, chart_blocks):
    if isinstance(candidate, dict):
        normalized_chart_markdown = _normalize_inline_chart_markdown(candidate.get('chart_markdown'))
        if normalized_chart_markdown:
            chart_blocks.append({
                'chart_id': candidate.get('chart_payload', {}).get('chartId') if isinstance(candidate.get('chart_payload'), dict) else None,
                'chart_markdown': normalized_chart_markdown,
            })

        for value in candidate.values():
            _collect_inline_chart_blocks(value, chart_blocks)
        return

    if isinstance(candidate, list):
        for item in candidate:
            _collect_inline_chart_blocks(item, chart_blocks)


def _append_inline_chart_blocks_to_message(message_content, agent_citations):
    chart_blocks = []
    _collect_inline_chart_blocks(agent_citations, chart_blocks)

    if not chart_blocks:
        return message_content

    existing_content = str(message_content or '').strip()
    appended_blocks = []
    seen_chart_ids = set()

    for chart_block in chart_blocks:
        chart_id = str(chart_block.get('chart_id') or '').strip()
        chart_markdown = chart_block.get('chart_markdown')
        if not chart_markdown:
            continue

        if chart_id:
            if chart_id in seen_chart_ids:
                continue
            if INLINE_CHART_ID_PATTERN_TEMPLATE.format(chart_id) in existing_content:
                seen_chart_ids.add(chart_id)
                continue
            seen_chart_ids.add(chart_id)

        if chart_markdown in existing_content:
            continue

        appended_blocks.append(chart_markdown)

    if not appended_blocks:
        return message_content

    separator = '\n\n' if existing_content else ''
    return f"{existing_content}{separator}{'\n\n'.join(appended_blocks)}"


def _get_appended_inline_chart_content_delta(original_content, updated_content):
    original_text = str(original_content or '')
    updated_text = str(updated_content or '')
    if not updated_text or updated_text == original_text:
        return ''

    if updated_text.startswith(original_text):
        return updated_text[len(original_text):]

    stripped_original_text = original_text.strip()
    if stripped_original_text and updated_text.startswith(stripped_original_text):
        return updated_text[len(stripped_original_text):]

    if not stripped_original_text:
        return updated_text

    return ''


def _build_plugin_invocation_agent_citation(invocation):
    timestamp_str = None
    invocation_timestamp = getattr(invocation, 'timestamp', None)
    if invocation_timestamp:
        if hasattr(invocation_timestamp, 'isoformat'):
            timestamp_str = invocation_timestamp.isoformat()
        else:
            timestamp_str = str(invocation_timestamp)

    sanitized_parameters = sanitize_plugin_invocation_value(getattr(invocation, 'parameters', None))
    sanitized_result = sanitize_plugin_invocation_value(getattr(invocation, 'result', None))
    sanitized_error = sanitize_plugin_invocation_value(getattr(invocation, 'error_message', None))

    tool_name = build_agent_citation_tool_label(
        getattr(invocation, 'plugin_name', None),
        getattr(invocation, 'function_name', None),
        sanitized_parameters,
        sanitized_result,
    )

    return {
        'tool_name': tool_name,
        'function_name': getattr(invocation, 'function_name', None),
        'plugin_name': getattr(invocation, 'plugin_name', None),
        'function_arguments': make_json_serializable(sanitized_parameters),
        'function_result': make_json_serializable(sanitized_result),
        'duration_ms': getattr(invocation, 'duration_ms', None),
        'timestamp': timestamp_str,
        'success': getattr(invocation, 'success', None),
        'error_message': make_json_serializable(sanitized_error),
        'user_id': getattr(invocation, 'user_id', None),
    }


def _append_new_plugin_invocation_citations(
    agent_citations_list,
    plugin_logger,
    user_id,
    conversation_id,
    baseline_invocation_count,
):
    if not isinstance(agent_citations_list, list) or not plugin_logger or not user_id or not conversation_id:
        return 0

    plugin_invocations = plugin_logger.get_invocations_for_conversation(
        user_id,
        conversation_id,
        limit=1000,
    )
    new_invocations = get_new_plugin_invocations(plugin_invocations, baseline_invocation_count)
    for invocation in new_invocations:
        agent_citations_list.append(_build_plugin_invocation_agent_citation(invocation))

    return len(new_invocations)


def normalize_fact_memory_type(memory_type):
    normalized = str(memory_type or '').strip().lower()
    if normalized == FACT_MEMORY_TYPE_LEGACY_DESCRIBER:
        return FACT_MEMORY_TYPE_FACT
    if normalized in {FACT_MEMORY_TYPE_FACT, FACT_MEMORY_TYPE_INSTRUCTION}:
        return normalized
    return FACT_MEMORY_TYPE_FACT


def _normalize_fact_memory_item(fact_item):
    normalized_item = dict(fact_item or {})
    normalized_item['memory_type'] = normalize_fact_memory_type(normalized_item.get('memory_type'))
    normalized_item['value'] = str(normalized_item.get('value') or '').strip()
    return normalized_item


def _is_embedding_vector(candidate):
    return (
        isinstance(candidate, list)
        and bool(candidate)
        and all(isinstance(value, (int, float)) for value in candidate)
    )


def _coerce_embedding_result(embedding_result):
    if not embedding_result:
        return None, None
    if isinstance(embedding_result, tuple):
        return embedding_result[0], embedding_result[1]
    return embedding_result, None


def _build_fact_memory_fact_payload(matched_facts):
    fact_payload = []
    for fact in matched_facts or []:
        fact_payload.append({
            'id': fact.get('id'),
            'value': fact.get('value'),
            'memory_type': normalize_fact_memory_type(fact.get('memory_type')),
            'updated_at': fact.get('updated_at') or fact.get('created_at'),
            'conversation_id': fact.get('conversation_id'),
            'agent_id': fact.get('agent_id'),
            'similarity': fact.get('similarity'),
        })
    return fact_payload


def _cosine_similarity(left_vector, right_vector):
    if not _is_embedding_vector(left_vector) or not _is_embedding_vector(right_vector):
        return 0.0
    if len(left_vector) != len(right_vector):
        return 0.0

    left_norm = sum(value * value for value in left_vector) ** 0.5
    right_norm = sum(value * value for value in right_vector) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0

    dot_product = sum(left * right for left, right in zip(left_vector, right_vector))
    return float(dot_product / (left_norm * right_norm))


def _backfill_missing_fact_memory_embeddings(fact_store, facts):
    missing_items = []
    for fact in facts or []:
        if fact.get('memory_type') != FACT_MEMORY_TYPE_FACT:
            continue
        if _is_embedding_vector(fact.get('value_embedding')):
            continue
        value = str(fact.get('value') or '').strip()
        if not value:
            continue
        missing_items.append((fact, value))

    if not missing_items:
        return 0

    try:
        embedding_results = generate_embeddings_batch([value for _, value in missing_items])
    except Exception as exc:
        debug_print(f"[Fact Memory] Failed to backfill memory embeddings: {exc}")
        return 0

    updated_count = 0
    for (fact, _), embedding_result in zip(missing_items, embedding_results):
        embedding_vector, token_usage = _coerce_embedding_result(embedding_result)
        if not embedding_vector:
            continue

        updated_fact = fact_store.update_fact_embedding(
            scope_id=fact.get('scope_id'),
            fact_id=fact.get('id'),
            value_embedding=embedding_vector,
            embedding_model=(token_usage or {}).get('model_deployment_name') if isinstance(token_usage, dict) else None,
        )
        if updated_fact:
            fact.update(updated_fact)
        else:
            fact['value_embedding'] = embedding_vector
        updated_count += 1

    return updated_count


def build_instruction_memory_citation(applied_facts):
    fact_payload = _build_fact_memory_fact_payload(applied_facts)
    return {
        'tool_name': 'Instruction Memory',
        'function_name': 'apply_instructions',
        'plugin_name': 'fact_memory',
        'function_arguments': make_json_serializable({
            'memory_type': FACT_MEMORY_TYPE_INSTRUCTION,
            'applied_count': len(fact_payload),
        }),
        'function_result': make_json_serializable({
            'facts': fact_payload,
        }),
        'timestamp': datetime.utcnow().isoformat(),
        'success': True,
    }


def build_fact_memory_citation(query_text, matched_facts, search_mode):
    fact_payload = _build_fact_memory_fact_payload(matched_facts)
    return {
        'tool_name': 'Fact Memory Recall',
        'function_name': 'search_facts',
        'plugin_name': 'fact_memory',
        'function_arguments': make_json_serializable({
            'query': str(query_text or '').strip(),
            'search_mode': search_mode,
            'match_count': len(fact_payload),
            'memory_type': FACT_MEMORY_TYPE_FACT,
        }),
        'function_result': make_json_serializable({
            'facts': fact_payload,
        }),
        'timestamp': datetime.utcnow().isoformat(),
        'success': True,
    }


def _normalize_requested_scope_ids(*scope_values):
    """Normalize single-value and list-based scope ids into a de-duplicated list."""
    normalized_values = []
    for scope_value in scope_values:
        if scope_value is None:
            continue

        if isinstance(scope_value, (list, tuple, set)):
            candidates = list(scope_value)
        else:
            candidates = [scope_value]

        for candidate in candidates:
            normalized_candidate = str(candidate or '').strip()
            if not normalized_candidate or normalized_candidate in normalized_values:
                continue
            normalized_values.append(normalized_candidate)

    return normalized_values


def _get_authorized_chat_scope_context(
    user_id,
    active_group_id=None,
    active_group_ids=None,
    active_public_workspace_id=None,
    active_public_workspace_ids=None,
):
    """Filter request-provided chat scopes down to the caller's current access."""
    requested_group_ids = _normalize_requested_scope_ids(active_group_ids, active_group_id)
    allowed_group_ids = []
    for group_id in requested_group_ids:
        group_doc = find_group_by_id(group_id)
        if group_doc and get_user_role_in_group(group_doc, user_id):
            allowed_group_ids.append(group_id)

    requested_public_workspace_ids = _normalize_requested_scope_ids(
        active_public_workspace_ids,
        active_public_workspace_id,
    )
    visible_public_workspace_ids = set(
        _normalize_requested_scope_ids(get_user_visible_public_workspace_ids_from_settings(user_id) or [])
    )
    allowed_public_workspace_ids = [
        workspace_id
        for workspace_id in requested_public_workspace_ids
        if workspace_id in visible_public_workspace_ids
    ]

    return {
        'active_group_ids': allowed_group_ids,
        'active_group_id': allowed_group_ids[0] if allowed_group_ids else None,
        'active_public_workspace_ids': allowed_public_workspace_ids,
        'active_public_workspace_id': (
            allowed_public_workspace_ids[0] if allowed_public_workspace_ids else None
        ),
    }


def _build_user_accessible_chat_agents(user_id, settings, requested_agent=None):
    """Build canonical agent records the current user may invoke in chat."""
    requested_agent = requested_agent if isinstance(requested_agent, dict) else {}
    candidates = []

    for agent in get_personal_agents(user_id):
        candidate = dict(agent)
        candidate['is_global'] = False
        candidate['is_group'] = False
        candidate['group_id'] = None
        candidate['group_name'] = None
        candidates.append(candidate)

    include_global_agents = (
        bool(requested_agent.get('is_global'))
        or not settings.get('per_user_semantic_kernel', False)
        or (
            settings.get('per_user_semantic_kernel', False)
            and settings.get('merge_global_semantic_kernel_with_workspace', False)
        )
    )
    if include_global_agents:
        for agent in get_global_agents():
            candidate = dict(agent)
            candidate['is_global'] = True
            candidate['is_group'] = False
            candidate['group_id'] = None
            candidate['group_name'] = None
            candidates.append(candidate)

    requested_group_id = str(requested_agent.get('group_id') or '').strip()
    if requested_agent.get('is_group') and not requested_group_id:
        try:
            requested_group_id = require_active_group(user_id)
        except Exception:
            requested_group_id = ''

    if requested_group_id:
        group_doc = find_group_by_id(requested_group_id)
        if group_doc and get_user_role_in_group(group_doc, user_id):
            group_name = requested_agent.get('group_name') or group_doc.get('name')
            for agent in get_group_agents(requested_group_id):
                candidate = dict(agent)
                candidate['is_global'] = False
                candidate['is_group'] = True
                candidate['group_id'] = requested_group_id
                candidate['group_name'] = group_name
                candidates.append(candidate)

    return candidates


def _chat_agent_scope_matches(candidate, requested_agent):
    requested_is_global = bool(requested_agent.get('is_global', False))
    requested_is_group = bool(requested_agent.get('is_group', False))
    requested_group_id = str(requested_agent.get('group_id') or '').strip()
    candidate_is_global = bool(candidate.get('is_global', False))
    candidate_is_group = bool(candidate.get('is_group', False))

    if requested_is_group:
        if not candidate_is_group:
            return False
        return not requested_group_id or str(candidate.get('group_id') or '') == requested_group_id
    if requested_is_global:
        return candidate_is_global and not candidate_is_group
    return not candidate_is_global and not candidate_is_group


def _resolve_canonical_chat_agent(user_id, settings, requested_agent):
    """Resolve a browser-supplied agent selection to a trusted stored agent record."""
    if isinstance(requested_agent, str):
        requested_agent = {'name': requested_agent}
    if not isinstance(requested_agent, dict) or not requested_agent:
        return None

    requested_id = str(requested_agent.get('id') or '').strip()
    requested_name = str(requested_agent.get('name') or '').strip()
    if not requested_id and not requested_name:
        return None

    candidates = _build_user_accessible_chat_agents(user_id, settings, requested_agent=requested_agent)
    if requested_id:
        match = next(
            (
                candidate
                for candidate in candidates
                if str(candidate.get('id') or '') == requested_id
                and _chat_agent_scope_matches(candidate, requested_agent)
            ),
            None,
        )
        if match:
            return match

    if requested_name:
        return next(
            (
                candidate
                for candidate in candidates
                if candidate.get('name') == requested_name
                and _chat_agent_scope_matches(candidate, requested_agent)
            ),
            None,
        )

    return None


def _get_chat_agent_selection_name(agent_selection):
    """Return the selected chat agent name, or an empty string when no agent is selected."""
    if isinstance(agent_selection, dict):
        return str(agent_selection.get('name') or '').strip()
    if isinstance(agent_selection, str):
        return agent_selection.strip()
    return ''


def _has_chat_agent_selection(agent_selection):
    """Determine whether a request payload contains an explicit chat-agent selection."""
    if isinstance(agent_selection, dict):
        selected_id = str(agent_selection.get('id') or '').strip()
        return bool(selected_id or _get_chat_agent_selection_name(agent_selection))
    return bool(_get_chat_agent_selection_name(agent_selection))


def _build_agent_selection_metadata(agent_info, assigned_knowledge_filters=None):
    """Build trusted conversation metadata for a selected chat agent."""
    if not agent_info:
        return None

    if isinstance(agent_info, str):
        agent_name = agent_info.strip()
        if not agent_name:
            return None
        metadata = {
            'selected_agent': agent_name,
            'agent_display_name': None,
            'is_global': False,
            'is_group': False,
            'group_id': None,
            'group_name': None,
            'agent_id': None,
            'agent_icon': None,
            'agent_tags': [],
            'catalog_key': None,
        }
        assigned_knowledge_enabled = bool(assigned_knowledge_filters)
    elif isinstance(agent_info, dict):
        metadata = {
            'selected_agent': agent_info.get('name') or agent_info.get('selected_agent'),
            'agent_display_name': agent_info.get('display_name') or agent_info.get('agent_display_name'),
            'is_global': agent_info.get('is_global', False),
            'is_group': agent_info.get('is_group', False),
            'group_id': agent_info.get('group_id'),
            'group_name': agent_info.get('group_name'),
            'agent_id': agent_info.get('id') or agent_info.get('agent_id'),
            'agent_icon': agent_info.get('icon') or agent_info.get('agent_icon'),
            'agent_tags': agent_info.get('tags') or agent_info.get('agent_tags') or [],
            'catalog_key': agent_info.get('catalog_key'),
        }
        assigned_knowledge_enabled = bool(
            assigned_knowledge_filters
            or agent_info.get('assigned_knowledge_enabled')
        )
    else:
        metadata = {
            'selected_agent': getattr(agent_info, 'name', None),
            'agent_display_name': getattr(agent_info, 'display_name', None),
            'is_global': getattr(agent_info, 'is_global', False),
            'is_group': getattr(agent_info, 'is_group', False),
            'group_id': getattr(agent_info, 'group_id', None),
            'group_name': getattr(agent_info, 'group_name', None),
            'agent_id': getattr(agent_info, 'id', None),
            'agent_icon': getattr(agent_info, 'icon', None),
            'agent_tags': getattr(agent_info, 'tags', []),
            'catalog_key': getattr(agent_info, 'catalog_key', None),
        }
        assigned_knowledge_enabled = bool(assigned_knowledge_filters)

    agent_icon = metadata.get('agent_icon')
    try:
        metadata['agent_icon'] = normalize_icon_payload(agent_icon, field_name='agent_icon') if agent_icon else None
    except ValueError:
        metadata['agent_icon'] = None

    agent_tags = metadata.get('agent_tags')
    if isinstance(agent_tags, list):
        cleaned_tags = []
        seen_tags = set()
        for tag in agent_tags:
            if not isinstance(tag, str):
                continue
            cleaned_tag = tag.strip()
            if not cleaned_tag or len(cleaned_tag) > 40:
                continue
            tag_key = cleaned_tag.lower()
            if tag_key in seen_tags:
                continue
            seen_tags.add(tag_key)
            cleaned_tags.append(cleaned_tag)
            if len(cleaned_tags) >= 20:
                break
        metadata['agent_tags'] = cleaned_tags
    else:
        metadata['agent_tags'] = []

    if assigned_knowledge_enabled:
        metadata['assigned_knowledge_enabled'] = True

    return metadata


def _set_authorized_chat_request_context(user_id, conversation_id, scope_context):
    """Persist the canonical request authorization context for downstream plugin checks."""
    authorized_context = {
        'user_id': user_id,
        'conversation_id': conversation_id,
        'active_group_ids': list(scope_context.get('active_group_ids') or []),
        'active_group_id': scope_context.get('active_group_id'),
        'active_public_workspace_ids': list(scope_context.get('active_public_workspace_ids') or []),
        'active_public_workspace_id': scope_context.get('active_public_workspace_id'),
    }
    authorized_context['fact_memory_scope_id'] = authorized_context['active_group_id'] or user_id
    authorized_context['fact_memory_scope_type'] = (
        'group' if authorized_context['active_group_id'] else 'user'
    )

    g.conversation_id = conversation_id
    g.authorized_chat_context = authorized_context
    return authorized_context


def _resolve_chat_selected_document_metadata(document_id, user_id=None, document_scope='personal',
                                            active_group_id=None, active_group_ids=None,
                                            active_public_workspace_id=None,
                                            active_public_workspace_ids=None):
    """Resolve selected-document metadata using the authorized chat scope model."""
    normalized_document_id = str(document_id or '').strip()
    if not normalized_document_id or normalized_document_id == 'all':
        return None

    normalized_scope = str(document_scope or 'personal').strip().lower()
    authorized_group_ids = _normalize_requested_scope_ids(active_group_ids, active_group_id)
    authorized_public_workspace_ids = _normalize_requested_scope_ids(
        active_public_workspace_ids,
        active_public_workspace_id,
    )

    resolution_queries = []

    if normalized_scope in {'personal', 'workspace', 'all'} and user_id:
        resolution_queries.append({
            'source_hint': 'workspace',
            'cosmos_container': cosmos_user_documents_container,
            'query': """
                SELECT TOP 1 c.id, c.file_name, c.title, c.group_id, c.public_workspace_id
                FROM c
                WHERE c.id = @doc_id
                    AND (
                        c.user_id = @user_id
                        OR ARRAY_CONTAINS(c.shared_user_ids, @user_id)
                        OR EXISTS(SELECT VALUE s FROM s IN c.shared_user_ids WHERE STARTSWITH(s, @user_id_prefix))
                    )
                ORDER BY c.version DESC
            """,
            'parameters': [
                {'name': '@doc_id', 'value': normalized_document_id},
                {'name': '@user_id', 'value': user_id},
                {'name': '@user_id_prefix', 'value': f"{user_id},"},
            ],
        })

    if normalized_scope in {'group', 'all'}:
        for group_id in authorized_group_ids:
            resolution_queries.append({
                'source_hint': 'group',
                'cosmos_container': cosmos_group_documents_container,
                'query': """
                    SELECT TOP 1 c.id, c.file_name, c.title, c.group_id, c.public_workspace_id
                    FROM c
                    WHERE c.id = @doc_id
                        AND (
                            c.group_id = @group_id
                            OR ARRAY_CONTAINS(c.shared_group_ids, @group_id)
                            OR ARRAY_CONTAINS(c.shared_group_ids, @group_id_approved)
                        )
                    ORDER BY c.version DESC
                """,
                'parameters': [
                    {'name': '@doc_id', 'value': normalized_document_id},
                    {'name': '@group_id', 'value': group_id},
                    {'name': '@group_id_approved', 'value': f"{group_id},approved"},
                ],
            })

    if normalized_scope in {'public', 'all'}:
        for public_workspace_id in authorized_public_workspace_ids:
            resolution_queries.append({
                'source_hint': 'public',
                'cosmos_container': cosmos_public_documents_container,
                'query': """
                    SELECT TOP 1 c.id, c.file_name, c.title, c.group_id, c.public_workspace_id
                    FROM c
                    WHERE c.id = @doc_id
                        AND c.public_workspace_id = @public_workspace_id
                    ORDER BY c.version DESC
                """,
                'parameters': [
                    {'name': '@doc_id', 'value': normalized_document_id},
                    {'name': '@public_workspace_id', 'value': public_workspace_id},
                ],
            })

    for resolution_query in resolution_queries:
        doc_results = list(resolution_query['cosmos_container'].query_items(
            query=resolution_query['query'],
            parameters=resolution_query['parameters'],
            enable_cross_partition_query=True,
        ))
        if not doc_results:
            continue

        doc_info = dict(doc_results[0])
        doc_info['source_hint'] = resolution_query['source_hint']
        return doc_info

    return None


def _create_personal_conversation(user_id, conversation_id=None):
    """Create and persist a new personal conversation owned by the current user."""
    resolved_conversation_id = str(conversation_id or uuid.uuid4())
    conversation_item = {
        'id': resolved_conversation_id,
        'user_id': user_id,
        'last_updated': datetime.utcnow().isoformat(),
        'title': 'New Conversation',
        'context': [],
        'tags': [],
        'strict': False,
        'chat_type': 'new'
    }
    cosmos_conversations_container.upsert_item(conversation_item)

    log_conversation_creation(
        user_id=user_id,
        conversation_id=resolved_conversation_id,
        title='New Conversation',
        workspace_type='personal'
    )

    conversation_item['added_to_activity_log'] = True
    cosmos_conversations_container.upsert_item(conversation_item)
    return conversation_item


def _authorize_personal_conversation_access(user_id, conversation_id):
    """Load a personal conversation and ensure the caller owns it."""
    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError(f"Conversation {conversation_id} not found") from exc

    if conversation_item.get('user_id') != user_id:
        raise PermissionError('You can only access your own conversations')

    return conversation_item


def _resolve_or_create_authorized_personal_conversation(user_id, conversation_id):
    """Create new personal conversations server-side or load an authorized existing one."""
    if not conversation_id:
        conversation_item = _create_personal_conversation(user_id)
        return conversation_item, conversation_item['id']

    conversation_item = _authorize_personal_conversation_access(user_id, conversation_id)
    return conversation_item, conversation_id


def build_instruction_memory_payload(
    scope_id,
    scope_type,
    enabled=True,
    result_limit=8,
):
    payload = {
        'context_messages': [],
        'citation': None,
        'thought_content': None,
        'thought_detail': None,
        'matched_facts': [],
        'total_available': 0,
    }
    if not enabled or not scope_id or not scope_type:
        return payload

    fact_store = FactMemoryStore()
    instruction_facts = [
        _normalize_fact_memory_item(fact)
        for fact in fact_store.list_facts(
            scope_type=scope_type,
            scope_id=scope_id,
            memory_type=FACT_MEMORY_TYPE_INSTRUCTION,
        )
    ]
    payload['total_available'] = len(instruction_facts)

    applied_facts = []
    for fact in instruction_facts:
        if not fact.get('value'):
            continue
        applied_facts.append(fact)
        if len(applied_facts) >= max(1, int(result_limit or 8)):
            break

    if not applied_facts:
        return payload

    instruction_lines = [f"- {fact.get('value')}" for fact in applied_facts]
    instruction_block = "\n".join(instruction_lines)
    payload['matched_facts'] = applied_facts
    payload['context_messages'].append({
        'role': 'system',
        'content': (
            'Apply these saved user instruction memories to every response in this conversation. '
            'Treat them like durable user-specific response preferences unless the user overrides them in the current message.\n'
            f"<Instruction Memory>\n{instruction_block}\n</Instruction Memory>"
        )
    })
    payload['citation'] = build_instruction_memory_citation(applied_facts)
    payload['thought_content'] = (
        f"Applied {len(applied_facts)} instruction "
        f"{'memory' if len(applied_facts) == 1 else 'memories'}"
    )
    payload['thought_detail'] = ' | '.join(
        str(fact.get('value') or '').strip()[:80]
        for fact in applied_facts[:3]
        if str(fact.get('value') or '').strip()
    )
    return payload


def retrieve_relevant_fact_memory_entries(
    scope_id,
    scope_type,
    query_text=None,
    conversation_id=None,
    agent_id=None,
    enabled=True,
    result_limit=4,
):
    result = {
        'matched_facts': [],
        'search_mode': 'disabled',
        'total_available': 0,
        'query_text': str(query_text or '').strip(),
        'embedding_backfill_count': 0,
    }
    if not enabled or not scope_id or not scope_type:
        return result

    query_text = result['query_text']
    if not query_text:
        result['search_mode'] = 'missing_query'
        return result

    fact_store = FactMemoryStore()
    query_kwargs = {
        'scope_type': scope_type,
        'scope_id': scope_id,
            'memory_type': FACT_MEMORY_TYPE_FACT,
    }
    if conversation_id:
        query_kwargs['conversation_id'] = conversation_id
    if agent_id:
        query_kwargs['agent_id'] = agent_id

    facts = [
        _normalize_fact_memory_item(fact)
        for fact in fact_store.list_facts(**query_kwargs)
    ]
    result['total_available'] = len(facts)
    if not facts:
        result['search_mode'] = 'empty'
        return result

    result['embedding_backfill_count'] = _backfill_missing_fact_memory_embeddings(fact_store, facts)

    try:
        query_embedding_result = generate_embedding(query_text)
    except Exception as exc:
        debug_print(f"[Fact Memory] Failed to generate query embedding: {exc}")
        result['search_mode'] = 'embedding_unavailable'
        return result

    query_embedding, _ = _coerce_embedding_result(query_embedding_result)
    if not query_embedding:
        result['search_mode'] = 'embedding_unavailable'
        return result

    candidates = []
    for fact in facts:
        value = str(fact.get('value') or '').strip()
        embedding_vector = fact.get('value_embedding')
        if not value or not _is_embedding_vector(embedding_vector):
            continue

        similarity = _cosine_similarity(query_embedding, embedding_vector)
        if similarity <= 0:
            continue

        normalized_fact = dict(fact)
        normalized_fact['similarity'] = round(similarity, 6)
        candidates.append(normalized_fact)

    if not candidates:
        result['search_mode'] = 'embedding'
        return result

    candidates.sort(
        key=lambda fact: (
            float(fact.get('similarity') or 0.0),
            str(fact.get('updated_at') or fact.get('created_at') or ''),
        ),
        reverse=True,
    )
    safe_limit = max(1, int(result_limit or 4))
    result['matched_facts'] = candidates[:safe_limit]
    result['search_mode'] = 'embedding'
    return result


def build_fact_memory_recall_payload(
    scope_id,
    scope_type,
    query_text=None,
    conversation_id=None,
    agent_id=None,
    enabled=True,
    include_metadata=False,
    result_limit=4,
):
    retrieval = retrieve_relevant_fact_memory_entries(
        scope_id=scope_id,
        scope_type=scope_type,
        query_text=query_text,
        conversation_id=conversation_id,
        agent_id=agent_id,
        enabled=enabled,
        result_limit=result_limit,
    )

    payload = {
        'context_messages': [],
        'citation': None,
        'thought_content': None,
        'thought_detail': None,
        **retrieval,
    }
    matched_facts = retrieval.get('matched_facts', [])

    if not matched_facts:
        if retrieval.get('total_available', 0) > 0 and enabled:
            payload['thought_content'] = 'Fact memory search found no relevant facts'
            payload['thought_detail'] = (
                f"mode={retrieval.get('search_mode', 'embedding')}; "
                f"query={str(query_text or '').strip()[:80]}; "
                f"available={retrieval.get('total_available', 0)}"
            )
        return payload

    if include_metadata:
        payload['context_messages'].append({
            'role': 'system',
            'content': (
                f"<Conversation Metadata>\n<Scope ID: {scope_id}>\n<Scope Type: {scope_type}>\n"
                f"<Conversation ID: {conversation_id}>\n<Agent ID: {agent_id}>\n</Conversation Metadata>"
            )
        })

    fact_lines = [f"- {fact.get('value')}" for fact in matched_facts if fact.get('value')]
    if fact_lines:
        fact_block = "\n".join(fact_lines)
        payload['context_messages'].append({
            'role': 'system',
            'content': (
                'Retrieved saved facts relevant to the current request. '
                'Use them only when they directly help answer the user.\n'
                f"<Fact Memory>\n{fact_block}\n</Fact Memory>"
            )
        })

    fact_preview = ' | '.join(
        str(fact.get('value') or '').strip()[:80]
        for fact in matched_facts[:3]
        if str(fact.get('value') or '').strip()
    )
    payload['citation'] = build_fact_memory_citation(
        query_text=query_text,
        matched_facts=matched_facts,
        search_mode=retrieval.get('search_mode', 'embedding'),
    )
    payload['thought_content'] = (
        f"Fact memory search found {len(matched_facts)} relevant "
        f"{'fact' if len(matched_facts) == 1 else 'facts'}"
    )
    payload['thought_detail'] = (
        f"mode={retrieval.get('search_mode', 'embedding')}; "
        f"query={str(query_text or '').strip()[:80]}; "
        f"matched={len(matched_facts)} of {retrieval.get('total_available', 0)}; "
        f"values={fact_preview}"
    )
    return payload


def build_fact_memory_prompt_payload(
    scope_id,
    scope_type,
    query_text=None,
    conversation_id=None,
    agent_id=None,
    enabled=True,
    include_metadata=False,
    instruction_limit=8,
    fact_limit=4,
):
    instruction_payload = build_instruction_memory_payload(
        scope_id=scope_id,
        scope_type=scope_type,
        enabled=enabled,
        result_limit=instruction_limit,
    )
    recall_payload = build_fact_memory_recall_payload(
        scope_id=scope_id,
        scope_type=scope_type,
        query_text=query_text,
        conversation_id=conversation_id,
        agent_id=agent_id,
        enabled=enabled,
        include_metadata=include_metadata,
        result_limit=fact_limit,
    )

    context_messages = []
    thoughts = []
    citations = []

    for payload in (instruction_payload, recall_payload):
        context_messages.extend(payload.get('context_messages', []))
        if payload.get('thought_content'):
            thoughts.append({
                'step_type': 'fact_memory',
                'content': payload['thought_content'],
                'detail': payload.get('thought_detail'),
            })
        if payload.get('citation'):
            citations.append(payload['citation'])

    return {
        'context_messages': context_messages,
        'thoughts': thoughts,
        'citations': citations,
        'instruction_payload': instruction_payload,
        'recall_payload': recall_payload,
    }


def persist_agent_citation_artifacts(
    conversation_id,
    assistant_message_id,
    agent_citations,
    created_timestamp,
    user_info=None,
):
    """Persist raw agent citation payloads outside the primary assistant message doc."""
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
            f"[Agent Citations] Failed to persist assistant artifacts: {exc}",
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


def _load_user_message_response_context(
    conversation_id,
    user_message_id,
    fallback_thread_id=None,
    fallback_previous_thread_id=None,
):
    """Return user/thread metadata for assistant-style responses."""
    response_context = {
        'user_info': None,
        'thread_id': fallback_thread_id,
        'previous_thread_id': fallback_previous_thread_id,
    }

    try:
        user_message_doc = cosmos_messages_container.read_item(
            item=user_message_id,
            partition_key=conversation_id,
        )
        metadata = user_message_doc.get('metadata') or {}
        thread_info = metadata.get('thread_info') or {}

        response_context['user_info'] = metadata.get('user_info')
        response_context['thread_id'] = thread_info.get('thread_id') or fallback_thread_id

        if 'previous_thread_id' in thread_info:
            response_context['previous_thread_id'] = thread_info.get('previous_thread_id')
    except Exception as exc:
        debug_print(
            f"[Threading] Could not load response context for user message {user_message_id}: {exc}"
        )

    return response_context


def _initialize_assistant_response_tracking(
    conversation_id,
    user_message_id,
    current_user_thread_id,
    previous_thread_id,
    retry_thread_attempt,
    is_retry,
    user_id,
):
    """Create assistant response tracking state for both new and retry/edit flows."""
    assistant_message_id = f"{conversation_id}_assistant_{int(time.time())}_{random.randint(1000,9999)}"
    thought_tracker = ThoughtTracker(
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        thread_id=current_user_thread_id,
        user_id=user_id,
    )
    assistant_thread_attempt = retry_thread_attempt if is_retry and retry_thread_attempt is not None else 1
    response_message_context = _load_user_message_response_context(
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        fallback_thread_id=current_user_thread_id,
        fallback_previous_thread_id=previous_thread_id,
    )
    return assistant_message_id, thought_tracker, assistant_thread_attempt, response_message_context


def _build_safety_message_doc(
    conversation_id,
    message_id,
    content,
    response_context,
    thread_attempt,
):
    """Build a persisted safety message aligned with the active conversation thread."""
    return make_json_serializable({
        'id': message_id,
        'conversation_id': conversation_id,
        'role': 'safety',
        'content': content,
        'timestamp': datetime.utcnow().isoformat(),
        'model_deployment_name': None,
        'metadata': {
            'user_info': response_context.get('user_info'),
            'thread_info': {
                'thread_id': response_context.get('thread_id'),
                'previous_thread_id': response_context.get('previous_thread_id'),
                'active_thread': True,
                'thread_attempt': thread_attempt,
            },
        },
    })


def _build_fact_memory_context_lines(
    scope_id,
    scope_type,
    query_text=None,
    conversation_id=None,
    agent_id=None,
    enabled=True,
    result_limit=4,
):
    """Build a flat fact-memory context block for the current scope."""
    prompt_payload = build_fact_memory_prompt_payload(
        scope_id=scope_id,
        scope_type=scope_type,
        query_text=query_text,
        conversation_id=conversation_id,
        agent_id=agent_id,
        enabled=enabled,
        include_metadata=False,
        instruction_limit=8,
        fact_limit=result_limit,
    )

    fact_lines = []
    instruction_facts = prompt_payload.get('instruction_payload', {}).get('matched_facts', [])
    if instruction_facts:
        fact_lines.append('[Instruction Memory]')
        fact_lines.extend(
            f"- {fact.get('value')}"
            for fact in instruction_facts
            if fact.get('value')
        )

    fact_memories = prompt_payload.get('recall_payload', {}).get('matched_facts', [])
    if fact_memories:
        if fact_lines:
            fact_lines.append('')
        fact_lines.append('[Fact Memory]')
        fact_lines.extend(
            f"- {fact.get('value')}"
            for fact in fact_memories
            if fact.get('value')
        )

    if not fact_lines:
        return ""
    return "\n".join(fact_lines)


def build_tabular_fact_memory_messages(
    scope_id,
    scope_type,
    query_text=None,
    conversation_id=None,
    agent_id=None,
    enabled=True,
):
    """Return system-message payloads that expose fact memory to mini SK analysis."""
    prompt_payload = build_fact_memory_prompt_payload(
        scope_id=scope_id,
        scope_type=scope_type,
        query_text=query_text,
        conversation_id=conversation_id,
        agent_id=agent_id,
        enabled=enabled,
        include_metadata=True,
    )
    return prompt_payload.get('context_messages', [])


def get_tabular_discovery_function_names():
    """Return discovery-oriented tabular function names from the plugin."""
    from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

    return TabularProcessingPlugin.get_discovery_function_names()


def get_tabular_analysis_function_names():
    """Return analytical tabular function names from the plugin."""
    from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

    return TabularProcessingPlugin.get_analysis_function_names()


def get_tabular_attachment_search_function_names():
    """Return document-search functions that help resolve attachment-backed rows."""
    return [
        'search_documents',
        'retrieve_document_chunks',
        'summarize_document',
    ]


def get_tabular_thought_excluded_parameter_names():
    """Return tabular parameter names hidden from thought details."""
    from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

    return TabularProcessingPlugin.get_thought_excluded_parameter_names()


def question_requests_attachment_backed_row_follow_up(user_question):
    """Return True when the user likely wants attachment-backed row substance."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().lower())
    if not normalized_question:
        return False

    per_row_markers = (
        'each row',
        'every row',
        'per row',
        'each comment',
        'every comment',
        'per comment',
        'each submission',
        'every submission',
        'summarize each',
        'summarize the comment',
        'one or two sentences per',
        'include the comment id',
        'put that into a table',
        'put this into a table',
        'put it into a table',
    )
    attachment_markers = (
        'attachment',
        'attached file',
        'attached letter',
        'see attached',
        'file somewhere else',
        'get the comment out of that file',
        'use the file',
        'pull them in',
    )

    return (
        any(marker in normalized_question for marker in per_row_markers)
        or any(marker in normalized_question for marker in attachment_markers)
    )


def tabular_invocations_include_attachment_candidates(invocations):
    """Return True when successful tabular rows reference related files or attachments."""
    for invocation in invocations or []:
        if get_tabular_invocation_error_message(invocation):
            continue

        result_payload = get_tabular_invocation_result_payload(invocation)
        if not isinstance(result_payload, dict):
            continue

        source_file_name = result_payload.get('filename')
        for row_payload in result_payload.get('data') or []:
            if not isinstance(row_payload, dict):
                continue
            attachment_names = _extract_tabular_generated_output_attachment_names(
                row_payload,
                source_file_name=source_file_name,
            )
            if attachment_names:
                return True

    return False


def tabular_document_search_invocations_succeeded(invocations):
    """Return True when attachment follow-up used document search successfully."""
    allowed_function_names = set(get_tabular_attachment_search_function_names())
    for invocation in invocations or []:
        plugin_name = str(getattr(invocation, 'plugin_name', '') or '').strip()
        function_name = str(getattr(invocation, 'function_name', '') or '').strip()
        if plugin_name != 'DocumentSearchPlugin':
            continue
        if function_name not in allowed_function_names:
            continue
        if get_tabular_invocation_error_message(invocation):
            continue
        return True

    return False


def is_tabular_schema_summary_question(user_question):
    """Return True for workbook-structure questions that should use schema summary tooling."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().lower())
    if not normalized_question:
        return False

    direct_phrases = (
        'summarize this workbook',
        'summarize the workbook',
        'describe this workbook',
        'describe the workbook',
        'what worksheets',
        'which worksheets',
        'what sheets',
        'which sheets',
        'what tabs',
        'which tabs',
        'what does each worksheet represent',
        'what does each sheet represent',
        'what does each tab represent',
        'what do the worksheets represent',
        'what do the sheets represent',
        'how are they related',
        'how do they relate',
        'workbook schema',
        'worksheet schema',
        'sheet schema',
    )
    if any(phrase in normalized_question for phrase in direct_phrases):
        return True

    structure_patterns = (
        r'\bwhich sheet\b.*\b(contain|contains|has|holds)\b',
        r'\bwhat sheet\b.*\b(contain|contains|has|holds)\b',
        r'\bhow (are|do)\b.*\b(worksheets|sheets|tabs)\b.*\b(relate|related)\b',
    )
    return any(re.search(pattern, normalized_question) for pattern in structure_patterns)


def is_tabular_entity_lookup_question(user_question):
    """Return True for cross-sheet entity lookup questions that need related-record traversal."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().lower())
    if not normalized_question or is_tabular_schema_summary_question(normalized_question):
        return False

    direct_phrases = (
        'find taxpayer',
        'find return',
        'show their profile',
        'related records',
        'full story',
        'case history',
    )
    relationship_keywords = (
        'profile',
        'tax return summary',
        'w-2',
        'w2',
        '1099',
        'payment',
        'refund',
        'notice',
        'audit',
        'installment agreement',
        'installment',
        'related',
    )
    explanatory_keywords = (
        'because',
        'detail',
        'details',
        'explain',
        'reason',
        'summary',
        'why',
    )
    if any(phrase in normalized_question for phrase in direct_phrases) and any(
        keyword in normalized_question for keyword in relationship_keywords + explanatory_keywords
    ):
        return True

    identifier_like_reference = bool(re.search(
        r'\b(?:ret|tp|case|account|acct|payment|pay|notice|audit|w2|1099)[-_]?[a-z0-9]*\d{2,}[a-z0-9_-]*\b',
        normalized_question,
    ))
    anchored_entity_reference = any(
        re.search(pattern, normalized_question)
        for pattern in (
            r'\bfor\s+(?:return|taxpayer|case|account|payment|notice|audit)\b',
            r'\b(?:return|taxpayer|case|account|payment|notice|audit)\s+[`"\']?[a-z0-9_-]*\d{2,}[a-z0-9_-]*[`"\']?\b',
        )
    )
    if anchored_entity_reference and identifier_like_reference and any(
        keyword in normalized_question for keyword in relationship_keywords + explanatory_keywords
    ):
        return True

    entity_lookup_patterns = (
        r'\bfind\b.*\b(show|summarize|explain)\b.*\b(profile|related|record|records)\b',
        r'\b(show|summarize)\b.*\b(profile|related|record|records)\b.*\b(w-2|w2|1099|payment|refund|notice|audit|installment)\b',
    )
    return any(re.search(pattern, normalized_question) for pattern in entity_lookup_patterns)


def is_tabular_distinct_value_question(user_question):
    """Return True for unique-value questions that should start with get_distinct_values."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().lower())
    if not normalized_question or is_tabular_schema_summary_question(normalized_question):
        return False

    distinct_keywords = (
        'different',
        'discrete',
        'distinct',
        'unique',
    )
    count_keywords = (
        'count',
        'counts',
        'how many',
        'number of',
    )
    target_keywords = (
        'link',
        'links',
        'location',
        'locations',
        'sharepoint',
        'site',
        'sites',
        'url',
        'urls',
        'value',
        'values',
    )

    has_distinct_intent = any(keyword in normalized_question for keyword in distinct_keywords)
    has_count_intent = any(keyword in normalized_question for keyword in count_keywords)
    has_target = any(keyword in normalized_question for keyword in target_keywords)
    return (has_distinct_intent or has_count_intent) and has_target


def is_tabular_cross_sheet_bridge_question(user_question):
    """Return True for grouped analytical questions that may need multiple worksheets."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().lower())
    if (
        not normalized_question
        or is_tabular_schema_summary_question(normalized_question)
        or is_tabular_entity_lookup_question(normalized_question)
    ):
        return False

    aggregate_keywords = (
        'how many',
        'count',
        'counts',
        'total',
        'totals',
        'sum',
        'average',
        'avg',
        'minimum',
        'maximum',
        'min',
        'max',
    )
    grouping_patterns = (
        r'\bfor each\b',
        r'\beach\b',
        r'\bper\b',
        r'\bby\b\s+[a-z0-9_\-]+(?:\s+[a-z0-9_\-]+){0,2}',
    )

    return any(keyword in normalized_question for keyword in aggregate_keywords) and any(
        re.search(pattern, normalized_question) for pattern in grouping_patterns
    )


def get_tabular_execution_mode(user_question):
    """Select the tabular orchestration mode for the user's question."""
    if is_tabular_schema_summary_question(user_question):
        return 'schema_summary'
    if is_tabular_entity_lookup_question(user_question):
        return 'entity_lookup'
    return 'analysis'


def build_tabular_fallback_system_message(tabular_filenames_str, execution_mode='analysis'):
    """Build the final GPT fallback guidance after the mini SK pass fails."""
    if execution_mode == 'schema_summary':
        return (
            f"IMPORTANT: The selected workspace tabular file(s) are {tabular_filenames_str}. "
            "The search results include a workbook schema summary with worksheet names, columns, and sample rows, but they do not include the full data. "
            "For workbook-structure questions such as what worksheets exist, what each worksheet represents, and how the sheets relate, answer from the schema summary only. "
            "Do not mention running additional plugin tools or performing calculations that were not completed. "
            "If a relationship is only implied by shared columns or names, describe it as an inferred relationship rather than a confirmed join."
        )

    return (
        f"IMPORTANT: The selected workspace tabular file(s) are {tabular_filenames_str}. "
        "The prior tabular tool pass could not compute tool-backed results. "
        "The search results contain only a schema summary (column names and a few sample rows), NOT the full data. "
        "Answer cautiously using only the schema summary already provided. "
        "Do not invent numeric totals, claim that full-data analysis succeeded, or mention additional plugin calls that were not completed. "
        "If the user's question requires computed values that are not present in the schema summary, say that the computation could not be completed from the available tool results."
    )


def build_search_augmentation_system_prompt(retrieved_content):
    """Build the retrieval augmentation prompt without blocking later tool-backed results."""
    return f"""You are an AI assistant. Use the following retrieved document excerpts to answer the user's question. Cite sources using the format (Source: filename, Page: page number).

                        Retrieved Excerpts:
                        {retrieved_content}

                        Base your answer only on information supported by the retrieved excerpts and any computed tool-backed results included elsewhere in this conversation context. If the answer is not supported by that information, say so.
                        If computed tabular results are provided in another system message, treat them as authoritative for row-level values, calculations, and numeric conclusions. Do not say that you lack direct access to the data when those computed results are present.

                        Example
                        User: What is the policy on double dipping?
                        Assistant: The policy prohibits entities from using federal funds received through one program to apply for additional funds through another program, commonly known as 'double dipping' (Source: PolicyDocument.pdf, Page: 12)
                        """


def _normalize_tabular_related_document_text(value):
    normalized_value = str(value or '').strip().lower()
    if not normalized_value:
        return ''

    return re.sub(r'\s+', ' ', normalized_value).strip()


def _normalize_tabular_related_document_basename(file_name):
    normalized_file_name = str(file_name or '').strip()
    if not normalized_file_name:
        return ''

    return _normalize_tabular_related_document_text(os.path.splitext(normalized_file_name)[0])


def _is_tabular_related_document_candidate(file_name):
    normalized_file_name = str(file_name or '').strip()
    if not normalized_file_name:
        return False

    file_extension = os.path.splitext(normalized_file_name)[1].lower().lstrip('.')
    if not file_extension:
        return False

    return file_extension not in set(TABULAR_EXTENSIONS)


def _tabular_text_mentions_related_document_reference(cell_text, reference_name):
    normalized_text = _normalize_tabular_related_document_text(cell_text)
    normalized_reference = _normalize_tabular_related_document_text(reference_name)
    if not normalized_text or not normalized_reference:
        return False

    reference_pattern = rf'(?<![a-z0-9]){re.escape(normalized_reference)}(?![a-z0-9])'
    return re.search(reference_pattern, normalized_text) is not None


def _select_tabular_related_document_scope_query(source_hint, user_id, group_id=None, public_workspace_id=None):
    normalized_source_hint = str(source_hint or 'workspace').strip().lower() or 'workspace'
    active_visibility_clause = "(NOT IS_DEFINED(c.search_visibility_state) OR c.search_visibility_state = 'active')"
    current_version_clause = "(NOT IS_DEFINED(c.is_current_version) OR c.is_current_version = true)"

    if normalized_source_hint == 'workspace' and user_id:
        return {
            'doc_scope': 'personal',
            'group_id': None,
            'public_workspace_id': None,
            'cosmos_container': cosmos_user_documents_container,
            'query': f"""
                SELECT c.id, c.file_name, c.title
                FROM c
                WHERE {active_visibility_clause}
                    AND {current_version_clause}
                    AND (
                        c.user_id = @user_id
                        OR ARRAY_CONTAINS(c.shared_user_ids, @user_id)
                        OR EXISTS(SELECT VALUE s FROM s IN c.shared_user_ids WHERE STARTSWITH(s, @user_id_prefix))
                    )
            """,
            'parameters': [
                {'name': '@user_id', 'value': user_id},
                {'name': '@user_id_prefix', 'value': f"{user_id},"},
            ],
        }

    if normalized_source_hint == 'group' and group_id:
        return {
            'doc_scope': 'group',
            'group_id': group_id,
            'public_workspace_id': None,
            'cosmos_container': cosmos_group_documents_container,
            'query': f"""
                SELECT c.id, c.file_name, c.title
                FROM c
                WHERE {active_visibility_clause}
                    AND {current_version_clause}
                    AND (
                        c.group_id = @group_id
                        OR ARRAY_CONTAINS(c.shared_group_ids, @group_id)
                        OR ARRAY_CONTAINS(c.shared_group_ids, @group_id_approved)
                    )
            """,
            'parameters': [
                {'name': '@group_id', 'value': group_id},
                {'name': '@group_id_approved', 'value': f"{group_id},approved"},
            ],
        }

    if normalized_source_hint == 'public' and public_workspace_id:
        return {
            'doc_scope': 'public',
            'group_id': None,
            'public_workspace_id': public_workspace_id,
            'cosmos_container': cosmos_public_documents_container,
            'query': f"""
                SELECT c.id, c.file_name, c.title
                FROM c
                WHERE {active_visibility_clause}
                    AND {current_version_clause}
                    AND c.public_workspace_id = @public_workspace_id
            """,
            'parameters': [
                {'name': '@public_workspace_id', 'value': public_workspace_id},
            ],
        }

    return None


def _resolve_tabular_related_document_scope_ids(
    source_hint,
    user_id,
    group_id=None,
    public_workspace_id=None,
    conversation_id=None,
):
    normalized_source_hint = str(source_hint or 'workspace').strip().lower() or 'workspace'
    resolved_group_id = str(group_id or '').strip() or None
    resolved_public_workspace_id = str(public_workspace_id or '').strip() or None

    if normalized_source_hint not in {'group', 'public'}:
        return {
            'group_id': resolved_group_id,
            'public_workspace_id': resolved_public_workspace_id,
        }

    if not has_request_context():
        return {'group_id': None, 'public_workspace_id': None}

    authorized_context = getattr(g, 'authorized_chat_context', None)
    if not isinstance(authorized_context, dict):
        return {'group_id': None, 'public_workspace_id': None}

    authorized_user_id = str(authorized_context.get('user_id') or '').strip()
    if authorized_user_id and authorized_user_id != str(user_id or '').strip():
        return {'group_id': None, 'public_workspace_id': None}

    normalized_conversation_id = str(conversation_id or '').strip()
    authorized_conversation_id = str(authorized_context.get('conversation_id') or '').strip()
    if normalized_conversation_id and authorized_conversation_id and authorized_conversation_id != normalized_conversation_id:
        return {'group_id': None, 'public_workspace_id': None}

    authorized_group_ids = _normalize_requested_scope_ids(authorized_context.get('active_group_ids'))
    authorized_public_workspace_ids = _normalize_requested_scope_ids(
        authorized_context.get('active_public_workspace_ids')
    )

    if normalized_source_hint == 'group' and resolved_group_id:
        if resolved_group_id not in authorized_group_ids:
            return {'group_id': None, 'public_workspace_id': None}
        return {
            'group_id': resolved_group_id,
            'public_workspace_id': None,
        }

    if normalized_source_hint == 'public' and resolved_public_workspace_id:
        if resolved_public_workspace_id not in authorized_public_workspace_ids:
            return {'group_id': None, 'public_workspace_id': None}
        return {
            'group_id': None,
            'public_workspace_id': resolved_public_workspace_id,
        }

    if normalized_source_hint == 'group' and not resolved_group_id:
        resolved_group_id = str(
            authorized_context.get('active_group_id')
            or ((authorized_context.get('active_group_ids') or [None])[0])
            or ''
        ).strip() or None
    elif normalized_source_hint == 'public' and not resolved_public_workspace_id:
        resolved_public_workspace_id = str(
            authorized_context.get('active_public_workspace_id')
            or ((authorized_context.get('active_public_workspace_ids') or [None])[0])
            or ''
        ).strip() or None

    return {
        'group_id': resolved_group_id if resolved_group_id in authorized_group_ids else None,
        'public_workspace_id': (
            resolved_public_workspace_id
            if resolved_public_workspace_id in authorized_public_workspace_ids
            else None
        ),
    }


def _build_tabular_related_document_catalog(user_id, source_hint, group_id=None, public_workspace_id=None):
    scope_query = _select_tabular_related_document_scope_query(
        source_hint,
        user_id,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
    )
    if not scope_query:
        return {
            'doc_scope': None,
            'group_id': None,
            'public_workspace_id': None,
            'documents': [],
        }

    try:
        raw_documents = list(scope_query['cosmos_container'].query_items(
            query=scope_query['query'],
            parameters=scope_query['parameters'],
            enable_cross_partition_query=True,
        ))
    except Exception as exc:
        log_event(
            '[Tabular Related Documents] Failed to build related-document catalog',
            extra={
                'source_hint': source_hint,
                'group_id': group_id,
                'public_workspace_id': public_workspace_id,
                'error_message': str(exc),
            },
            level=logging.WARNING,
        )
        raw_documents = []

    normalized_documents = []
    seen_document_ids = set()
    for raw_document in raw_documents:
        document_id = str(raw_document.get('id') or '').strip()
        file_name = str(raw_document.get('file_name') or '').strip()
        if not document_id or not file_name or document_id in seen_document_ids:
            continue
        if not _is_tabular_related_document_candidate(file_name):
            continue

        seen_document_ids.add(document_id)
        normalized_documents.append({
            'document_id': document_id,
            'file_name': file_name,
            'title': str(raw_document.get('title') or '').strip(),
            'normalized_file_name': _normalize_tabular_related_document_text(file_name),
            'normalized_basename': _normalize_tabular_related_document_basename(file_name),
        })

    return {
        'doc_scope': scope_query['doc_scope'],
        'group_id': scope_query['group_id'],
        'public_workspace_id': scope_query['public_workspace_id'],
        'documents': normalized_documents,
    }


def _extract_tabular_row_related_documents(row, document_catalog, max_matches_per_row=TABULAR_RELATED_DOCUMENT_MAX_MATCHES_PER_ROW):
    if not isinstance(row, dict):
        return []

    catalog_documents = list((document_catalog or {}).get('documents') or [])
    if not catalog_documents:
        return []

    candidate_cells = []
    seen_candidate_cells = set()
    for column_name, cell_value in row.items():
        normalized_column_name = str(column_name or '').strip()
        if normalized_column_name in {'referenced_documents', '_matched_columns', '_matched_values', '_related_document_reference_values'}:
            continue
        if isinstance(cell_value, (dict, list, tuple, set)):
            continue

        candidate_key = (normalized_column_name.casefold(), str(cell_value or '').strip())
        if candidate_key in seen_candidate_cells:
            continue
        seen_candidate_cells.add(candidate_key)
        candidate_cells.append((normalized_column_name, cell_value))

    for extra_column_values in (
        row.get('_matched_values'),
        row.get('_related_document_reference_values'),
    ):
        if not isinstance(extra_column_values, dict):
            continue

        for column_name, cell_value in extra_column_values.items():
            normalized_column_name = str(column_name or '').strip()
            candidate_key = (normalized_column_name.casefold(), str(cell_value or '').strip())
            if candidate_key in seen_candidate_cells:
                continue
            seen_candidate_cells.add(candidate_key)
            candidate_cells.append((normalized_column_name, cell_value))

    related_documents = []
    seen_document_ids = set()
    for column_name, cell_value in candidate_cells:
        normalized_cell_text = _normalize_tabular_related_document_text(cell_value)
        if not normalized_cell_text:
            continue

        for catalog_document in catalog_documents:
            document_id = catalog_document['document_id']
            if document_id in seen_document_ids:
                continue

            matched_reference = None
            if _tabular_text_mentions_related_document_reference(
                normalized_cell_text,
                catalog_document['normalized_file_name'],
            ):
                matched_reference = catalog_document['file_name']
            elif catalog_document['normalized_basename'] and _tabular_text_mentions_related_document_reference(
                normalized_cell_text,
                catalog_document['normalized_basename'],
            ):
                matched_reference = os.path.splitext(catalog_document['file_name'])[0]

            if not matched_reference:
                continue

            related_documents.append({
                'document_id': document_id,
                'file_name': catalog_document['file_name'],
                'title': catalog_document['title'],
                'matched_column': str(column_name or '').strip(),
                'matched_text': str(cell_value or '').strip(),
                'matched_reference': matched_reference,
            })
            seen_document_ids.add(document_id)
            if len(related_documents) >= max_matches_per_row:
                return related_documents

    return related_documents


def _build_tabular_related_document_search_query(user_question, matched_text, file_name):
    query_parts = []
    normalized_user_question = str(user_question or '').strip()
    normalized_matched_text = str(matched_text or '').strip()
    normalized_file_name = str(file_name or '').strip()

    if normalized_user_question:
        query_parts.append(normalized_user_question)
    if normalized_matched_text and normalized_matched_text not in query_parts:
        query_parts.append(normalized_matched_text)
    if normalized_file_name and normalized_file_name not in query_parts:
        query_parts.append(normalized_file_name)

    rendered_query = '\n'.join(query_parts).strip()
    return rendered_query[:800] if rendered_query else normalized_file_name[:800]


def _truncate_tabular_related_document_excerpt(value, max_length=TABULAR_RELATED_DOCUMENT_MAX_EXCERPT_CHARS):
    normalized_value = str(value or '').strip()
    if len(normalized_value) <= max_length:
        return normalized_value
    return f"{normalized_value[:max_length]}..."


def _resolve_tabular_related_document_evidence(document_match, user_question, user_id, document_catalog, conversation_id=None):
    # Import lazily to keep the chat route decoupled from search-service startup paths.
    from functions_search_service import get_document_chunks_payload, search_documents

    doc_scope = (document_catalog or {}).get('doc_scope')
    if not doc_scope:
        return None

    document_id = str((document_match or {}).get('document_id') or '').strip()
    if not document_id:
        return None

    group_id = (document_catalog or {}).get('group_id')
    public_workspace_id = (document_catalog or {}).get('public_workspace_id')
    active_group_ids = [group_id] if group_id else None
    search_query = _build_tabular_related_document_search_query(
        user_question,
        (document_match or {}).get('matched_text'),
        (document_match or {}).get('file_name'),
    )

    excerpt = ''
    page_number = None
    chunk_sequence = None
    try:
        search_payload = search_documents(
            query=search_query,
            user_id=user_id,
            top_n=2,
            doc_scope=doc_scope,
            document_ids=[document_id],
            active_group_ids=active_group_ids,
            active_public_workspace_id=public_workspace_id,
            enable_file_sharing=True,
        )
        for result in search_payload.get('results', []):
            candidate_excerpt = _truncate_tabular_related_document_excerpt(result.get('chunk_text'))
            if not candidate_excerpt:
                continue

            excerpt = candidate_excerpt
            page_number = result.get('page_number')
            chunk_sequence = result.get('chunk_sequence')
            break
    except Exception as exc:
        log_event(
            '[Tabular Related Documents] Search lookup failed for resolved document reference',
            extra={
                'document_id': document_id,
                'file_name': (document_match or {}).get('file_name'),
                'doc_scope': doc_scope,
                'error_message': str(exc),
            },
            level=logging.WARNING,
        )

    if not excerpt:
        try:
            chunk_payload = get_document_chunks_payload(
                document_id=document_id,
                user_id=user_id,
                doc_scope=doc_scope,
                active_group_ids=active_group_ids,
                active_public_workspace_id=public_workspace_id,
                conversation_id=conversation_id,
                window_unit='chunks',
                window_size=1,
                window_number=1,
            )
            first_chunk = ((chunk_payload or {}).get('chunks') or [{}])[0]
            excerpt = _truncate_tabular_related_document_excerpt(first_chunk.get('chunk_text'))
            page_number = page_number if page_number is not None else first_chunk.get('page_number')
            chunk_sequence = chunk_sequence if chunk_sequence is not None else first_chunk.get('chunk_sequence')
        except Exception as exc:
            log_event(
                '[Tabular Related Documents] Chunk fallback failed for resolved document reference',
                extra={
                    'document_id': document_id,
                    'file_name': (document_match or {}).get('file_name'),
                    'doc_scope': doc_scope,
                    'error_message': str(exc),
                },
                level=logging.WARNING,
            )

    if not excerpt:
        return None

    return {
        'excerpt': excerpt,
        'page_number': page_number,
        'chunk_sequence': chunk_sequence,
        'doc_scope': doc_scope,
    }


def augment_tabular_invocations_with_related_document_evidence(invocations, user_question, user_id, conversation_id=None):
    catalog_cache = {}
    evidence_cache = {}
    augmented_row_count = 0
    augmented_document_count = 0

    for invocation in invocations or []:
        if get_tabular_invocation_error_message(invocation):
            continue

        result_payload = get_tabular_invocation_result_payload(invocation)
        if not isinstance(result_payload, dict):
            continue

        row_payloads = result_payload.get('data')
        if not isinstance(row_payloads, list) or not row_payloads:
            continue

        invocation_parameters = getattr(invocation, 'parameters', {}) or {}
        source_hint = str(
            invocation_parameters.get('source')
            or result_payload.get('source')
            or 'workspace'
        ).strip().lower() or 'workspace'
        if source_hint == 'chat':
            continue

        resolved_scope_ids = _resolve_tabular_related_document_scope_ids(
            source_hint,
            user_id,
            group_id=invocation_parameters.get('group_id'),
            public_workspace_id=invocation_parameters.get('public_workspace_id'),
            conversation_id=conversation_id,
        )
        group_id = resolved_scope_ids.get('group_id')
        public_workspace_id = resolved_scope_ids.get('public_workspace_id')
        scope_key = (source_hint, group_id or '', public_workspace_id or '')
        if scope_key not in catalog_cache:
            catalog_cache[scope_key] = _build_tabular_related_document_catalog(
                user_id,
                source_hint,
                group_id=group_id,
                public_workspace_id=public_workspace_id,
            )

        document_catalog = catalog_cache[scope_key]
        if not document_catalog.get('documents'):
            continue

        updated_rows = []
        rows_changed = False
        augmented_rows_for_invocation = 0
        augmented_documents_for_invocation = 0
        matched_document_names = set()
        for row_payload in row_payloads:
            if not isinstance(row_payload, dict):
                updated_rows.append(row_payload)
                continue

            related_documents = _extract_tabular_row_related_documents(row_payload, document_catalog)
            if not related_documents:
                updated_rows.append(row_payload)
                continue

            enriched_documents = []
            for document_match in related_documents:
                evidence_cache_key = (
                    document_match['document_id'],
                    document_match.get('matched_text') or '',
                )
                if evidence_cache_key not in evidence_cache:
                    evidence_cache[evidence_cache_key] = _resolve_tabular_related_document_evidence(
                        document_match,
                        user_question,
                        user_id,
                        document_catalog,
                        conversation_id=conversation_id,
                    )

                document_evidence = evidence_cache[evidence_cache_key]
                if not document_evidence:
                    continue

                enriched_document = dict(document_match)
                enriched_document.update(document_evidence)
                enriched_documents.append(enriched_document)
                matched_document_names.add(str(document_match.get('file_name') or '').strip())

            if not enriched_documents:
                updated_rows.append(row_payload)
                continue

            updated_row_payload = dict(row_payload)
            updated_row_payload['referenced_documents'] = enriched_documents
            updated_rows.append(updated_row_payload)
            rows_changed = True
            augmented_rows_for_invocation += 1
            augmented_documents_for_invocation += len(enriched_documents)

        if not rows_changed:
            continue

        log_event(
            '[Tabular Related Documents] Resolved row-linked document evidence',
            {
                'conversation_id': conversation_id,
                'source_hint': source_hint,
                'source_file_name': result_payload.get('filename'),
                'selected_sheet': result_payload.get('selected_sheet'),
                'augmented_row_count': augmented_rows_for_invocation,
                'augmented_document_count': augmented_documents_for_invocation,
                'matched_document_names': sorted(
                    file_name for file_name in matched_document_names if file_name
                )[:5],
            },
            debug_only=True,
        )
        augmented_row_count += augmented_rows_for_invocation
        augmented_document_count += augmented_documents_for_invocation
        updated_result_payload = dict(result_payload)
        updated_result_payload['data'] = updated_rows
        updated_result_payload['referenced_document_row_count'] = augmented_rows_for_invocation
        updated_result_payload['referenced_document_match_count'] = augmented_documents_for_invocation
        if isinstance(getattr(invocation, 'result', None), dict):
            invocation.result = updated_result_payload
        else:
            invocation.result = json.dumps(updated_result_payload, indent=2, default=str, ensure_ascii=False)

    return {
        'augmented_row_count': augmented_row_count,
        'augmented_document_count': augmented_document_count,
    }


def _extract_tabular_related_row_identity(row_payload):
    if not isinstance(row_payload, dict):
        return {}

    preferred_identity = {}
    for column_name, column_value in row_payload.items():
        if column_name == 'referenced_documents' or isinstance(column_value, (dict, list, tuple)) or column_value in (None, ''):
            continue

        normalized_column_name = str(column_name or '').strip().lower()
        if normalized_column_name == 'id' or normalized_column_name.endswith('id'):
            preferred_identity[str(column_name)] = str(column_value)
            if len(preferred_identity) >= 3:
                return preferred_identity

    fallback_identity = {}
    for column_name, column_value in row_payload.items():
        if column_name == 'referenced_documents' or isinstance(column_value, (dict, list, tuple)) or column_value in (None, ''):
            continue
        fallback_identity[str(column_name)] = _truncate_log_text(column_value, max_length=80)
        if len(fallback_identity) >= 2:
            break

    return preferred_identity or fallback_identity


def build_tabular_related_document_evidence_summary(invocations):
    summary_rows = []
    for invocation in invocations or []:
        if get_tabular_invocation_error_message(invocation):
            continue

        result_payload = get_tabular_invocation_result_payload(invocation) or {}
        for row_payload in result_payload.get('data') or []:
            referenced_documents = row_payload.get('referenced_documents') if isinstance(row_payload, dict) else None
            if not isinstance(referenced_documents, list) or not referenced_documents:
                continue

            rendered_documents = []
            for referenced_document in referenced_documents[:TABULAR_RELATED_DOCUMENT_MAX_MATCHES_PER_ROW]:
                rendered_documents.append({
                    'document_id': referenced_document.get('document_id'),
                    'file_name': referenced_document.get('file_name'),
                    'matched_column': referenced_document.get('matched_column'),
                    'matched_reference': referenced_document.get('matched_reference'),
                    'page_number': referenced_document.get('page_number'),
                    'excerpt': referenced_document.get('excerpt'),
                })

            summary_rows.append({
                'row_identity': _extract_tabular_related_row_identity(row_payload),
                'referenced_documents': rendered_documents,
            })
            if len(summary_rows) >= TABULAR_RELATED_DOCUMENT_MAX_SUMMARY_ROWS:
                break

        if len(summary_rows) >= TABULAR_RELATED_DOCUMENT_MAX_SUMMARY_ROWS:
            break

    if not summary_rows:
        return ''

    return json.dumps(summary_rows, indent=2, default=str, ensure_ascii=False)


def build_tabular_computed_results_system_message(source_label, tabular_analysis, related_document_evidence_summary=''):
    """Build the outer-model handoff message for successful tabular analysis."""
    rendered_analysis = str(tabular_analysis or '').strip()
    max_handoff_chars = 24000
    if len(rendered_analysis) > max_handoff_chars:
        rendered_analysis = (
            rendered_analysis[:max_handoff_chars]
            + "\n[Computed results handoff truncated for prompt budget.]"
        )

    rendered_related_document_evidence = str(related_document_evidence_summary or '').strip()
    related_document_handoff = ''
    if rendered_related_document_evidence:
        related_document_handoff = (
            "\n\nRelated document evidence resolved from explicit document references in the tabular rows:\n\n"
            f"{rendered_related_document_evidence}\n\n"
            "Treat these excerpts as tabular-adjacent source evidence because they were resolved from row-level document references in the source data. "
            "Use them when they materially support the user's request, while preserving the originating row identity. "
            "Do not say the attachment was not searched or that attachment text is unavailable when these row-linked excerpts are present. "
            "If the visible row text is only a cover note such as 'see attached', prefer the referenced document excerpt when summarizing or classifying that row."
        )

    return (
        f"The following tabular results were computed from {source_label} using "
        f"tabular_processing plugin functions:\n\n"
        f"{rendered_analysis}\n\n"
        "These are tool-backed results derived from the full underlying tabular data, not just retrieved schema excerpts. "
        "Treat them as authoritative for row-level facts, calculations, and numeric conclusions. "
        "Do not say that you lack direct access to the data if the answer is present in these computed results. "
        "If a tool summary includes a full scalar value list, you may enumerate those values directly in the final answer. "
        "If a tool summary includes the full matching rows from a row or text search, use the surrounding cell context in those rows when deciding which content is relevant to the user's question."
        f"{related_document_handoff}"
    )


def get_tabular_generated_output_format(user_question):
    """Return the requested generated-output file format when the user asked for one."""
    normalized_question = str(user_question or '').strip().lower()
    if not normalized_question:
        return None

    json_markers = (
        'json array',
        'json file',
        'download json',
        'save json',
        'make a json',
        'create a json',
        'return json',
        'valid json',
    )
    csv_markers = TABLE_EXPORT_REQUEST_MARKERS

    if any(marker in normalized_question for marker in json_markers):
        return 'json'
    if any(marker in normalized_question for marker in csv_markers):
        return 'csv'
    return None


def question_requests_tabular_generated_output(user_question):
    """Return True when the prompt asks for a downloadable structured tabular export."""
    normalized_question = str(user_question or '').strip().lower()
    requested_format = get_tabular_generated_output_format(user_question)
    if not normalized_question or not requested_format:
        return False

    exhaustive_markers = (
        'all rows',
        'every row',
        'full json',
        'full csv',
        'download',
        'save',
        'export',
        'one object per',
        'one row per',
        'each object',
        'each row',
    )
    if requested_format == 'csv' and any(marker in normalized_question for marker in TABLE_EXPORT_REQUEST_MARKERS):
        return True

    return any(marker in normalized_question for marker in exhaustive_markers)


def question_requests_tabular_structured_object_output(user_question):
    """Return True when the prompt wants one structured object per source row."""
    normalized_question = str(user_question or '').strip().lower()
    if not normalized_question or not get_tabular_generated_output_format(user_question):
        return False

    structured_markers = (
        'one object per comment',
        'one json object per comment',
        'one object per row',
        'one row per comment',
        'one object per submission',
        'one object for each row',
        'for each row',
        'each object must contain',
        'exactly these fields',
    )
    return any(marker in normalized_question for marker in structured_markers)


def _clean_tabular_generated_json_code_fence(response_content):
    cleaned = str(response_content or '').strip()
    if not cleaned:
        return ''

    cleaned = re.sub(r'(?is)^```(?:json)?\s*', '', cleaned)
    cleaned = re.sub(r'(?is)\s*```$', '', cleaned)
    return cleaned.strip()


def _parse_tabular_generated_json_entries(response_content):
    cleaned = _clean_tabular_generated_json_code_fence(response_content)
    if not cleaned:
        return None

    decoder = json.JSONDecoder()
    parsed_value = None
    try:
        parsed_value, _ = decoder.raw_decode(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed_value = None

    if parsed_value is None:
        for start_index, character in enumerate(cleaned):
            if character not in '[{':
                continue
            try:
                parsed_value, _ = decoder.raw_decode(cleaned[start_index:])
                break
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

    if isinstance(parsed_value, dict):
        return [parsed_value]
    if isinstance(parsed_value, list) and all(isinstance(item, dict) for item in parsed_value):
        return parsed_value
    return None


def _serialize_tabular_generated_output_value(value):
    if value is None:
        return ''
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, ensure_ascii=False)
    if hasattr(value, 'isoformat') and not isinstance(value, str):
        try:
            return value.isoformat()
        except TypeError:
            pass
    return str(value)


def _build_tabular_generated_output_csv(entries):
    ordered_columns = []
    seen_columns = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        for key in entry.keys():
            normalized_key = str(key or '').strip()
            if not normalized_key or normalized_key in seen_columns:
                continue
            seen_columns.add(normalized_key)
            ordered_columns.append(normalized_key)

    if not ordered_columns:
        ordered_columns = ['value']

    output_buffer = io.StringIO()
    writer = csv.DictWriter(output_buffer, fieldnames=ordered_columns)
    writer.writeheader()
    for entry in entries or []:
        serialized_row = {}
        if isinstance(entry, dict):
            for field_name in ordered_columns:
                serialized_row[field_name] = _serialize_tabular_generated_output_value(entry.get(field_name))
        writer.writerow(serialized_row)
    return output_buffer.getvalue()


def _sanitize_tabular_generated_output_base_name(file_name):
    base_name = os.path.splitext(str(file_name or '').strip())[0]
    normalized_base_name = re.sub(r'[^A-Za-z0-9._-]+', '_', base_name).strip('._')
    return normalized_base_name or 'tabular_output'


def _normalize_tabular_generated_output_field_label(value):
    expanded_value = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', str(value or '').strip())
    return re.sub(r'[^a-z0-9]+', ' ', expanded_value.casefold()).strip()


def _select_tabular_generated_output_scalar_value(row, candidate_labels):
    normalized_candidate_labels = {
        _normalize_tabular_generated_output_field_label(candidate_label)
        for candidate_label in (candidate_labels or [])
        if _normalize_tabular_generated_output_field_label(candidate_label)
    }
    if not normalized_candidate_labels:
        return ''

    for column_name, column_value in (row or {}).items():
        if isinstance(column_value, (dict, list, tuple, set)):
            continue

        rendered_value = str(column_value or '').strip()
        if not rendered_value:
            continue

        normalized_column_name = _normalize_tabular_generated_output_field_label(column_name)
        if normalized_column_name in normalized_candidate_labels:
            return rendered_value

    return ''


def _is_tabular_generated_output_attachment_column_name(column_name):
    normalized_column_name = _normalize_tabular_generated_output_field_label(column_name)
    if not normalized_column_name:
        return False

    column_tokens = set(normalized_column_name.split())
    if column_tokens & {
        'attachment',
        'attachments',
        'appendix',
        'appendices',
        'document',
        'documents',
        'exhibit',
        'exhibits',
        'file',
        'files',
        'filename',
        'filenames',
        'pdf',
        'pdfs',
        'supporting',
    }:
        return True

    condensed_label = normalized_column_name.replace(' ', '')
    return any(
        keyword in condensed_label
        for keyword in (
            'attachedfile',
            'attachedfiles',
            'attachmentname',
            'attachmentnames',
            'documentfile',
            'documentfiles',
            'documentname',
            'documentnames',
            'referencefile',
            'referencefiles',
            'supportingfile',
            'supportingfiles',
            'supportingdocument',
            'supportingdocuments',
        )
    )


def _split_tabular_generated_output_attachment_names(value):
    if isinstance(value, list):
        raw_candidates = value
    else:
        rendered_value = str(value or '').strip()
        if not rendered_value:
            return []

        raw_candidates = None
        if rendered_value.startswith('['):
            try:
                parsed_value = json.loads(rendered_value)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed_value = None
            if isinstance(parsed_value, list):
                raw_candidates = parsed_value

        if raw_candidates is None:
            raw_candidates = re.split(r'[;|\n]+', rendered_value)

    attachment_names = []
    seen_attachment_names = set()
    for raw_candidate in raw_candidates:
        rendered_candidate = str(raw_candidate or '').strip().strip('"').strip("'")
        if not rendered_candidate:
            continue

        lowered_candidate = rendered_candidate.casefold()
        if lowered_candidate in seen_attachment_names:
            continue

        seen_attachment_names.add(lowered_candidate)
        attachment_names.append(rendered_candidate)

    return attachment_names


def _extract_tabular_generated_output_attachment_names(row, source_file_name=None):
    attachment_names = []
    seen_attachment_names = set()

    def add_attachment_name(candidate_name):
        rendered_candidate_name = str(candidate_name or '').strip()
        if not rendered_candidate_name:
            return
        if source_file_name and rendered_candidate_name.casefold() == str(source_file_name).strip().casefold():
            return

        lowered_candidate_name = rendered_candidate_name.casefold()
        if lowered_candidate_name in seen_attachment_names:
            return

        seen_attachment_names.add(lowered_candidate_name)
        attachment_names.append(rendered_candidate_name)

    existing_attachment_names = row.get('attachment_names') if isinstance(row, dict) else None
    for attachment_name in _split_tabular_generated_output_attachment_names(existing_attachment_names or []):
        add_attachment_name(attachment_name)

    if isinstance(row, dict):
        referenced_documents = row.get('referenced_documents')
        if isinstance(referenced_documents, list):
            for referenced_document in referenced_documents:
                if not isinstance(referenced_document, dict):
                    continue
                add_attachment_name(referenced_document.get('file_name'))

        direct_file_name = str(row.get('file_name') or '').strip()
        if direct_file_name and _is_tabular_related_document_candidate(direct_file_name):
            add_attachment_name(direct_file_name)

        related_reference_values = row.get('_related_document_reference_values')
        if isinstance(related_reference_values, dict):
            for column_name, column_value in related_reference_values.items():
                if not _is_tabular_generated_output_attachment_column_name(column_name):
                    continue
                for attachment_name in _split_tabular_generated_output_attachment_names(column_value):
                    add_attachment_name(attachment_name)

        for column_name, column_value in row.items():
            if not _is_tabular_generated_output_attachment_column_name(column_name):
                continue
            if isinstance(column_value, (dict, list, tuple, set)):
                continue
            for attachment_name in _split_tabular_generated_output_attachment_names(column_value):
                add_attachment_name(attachment_name)

    return attachment_names


def _build_tabular_generated_output_attachment_text(row):
    if not isinstance(row, dict):
        return ''

    return _select_tabular_generated_output_scalar_value(
        row,
        candidate_labels=('attachment_text', 'attachment text', 'letter_text', 'letter text'),
    )


def _compact_tabular_generated_output_referenced_documents(referenced_documents):
    compact_documents = []
    for referenced_document in referenced_documents or []:
        if not isinstance(referenced_document, dict):
            continue

        compact_document = {}
        for field_name in TABULAR_GENERATED_OUTPUT_REFERENCED_DOCUMENT_FIELDS:
            field_value = referenced_document.get(field_name)
            if field_value in (None, '', [], {}):
                continue
            if field_name == 'excerpt':
                field_value = _truncate_tabular_related_document_excerpt(field_value)
            compact_document[field_name] = field_value

        if not compact_document.get('file_name') and not compact_document.get('excerpt'):
            continue

        compact_documents.append(compact_document)
        if len(compact_documents) >= TABULAR_RELATED_DOCUMENT_MAX_MATCHES_PER_ROW:
            break

    return compact_documents


def _dump_tabular_generated_output_json(value):
    return json.dumps(value, default=str, ensure_ascii=False, separators=(',', ':'))


def _get_tabular_generated_output_batch_budget(settings=None):
    settings = settings or {}
    return {
        'max_rows': _bounded_int(
            settings.get('tabular_generated_output_max_batch_rows'),
            default=TABULAR_STRUCTURED_EXPORT_MAX_BATCH_ROWS,
            minimum=TABULAR_STRUCTURED_EXPORT_MIN_BATCH_ROWS,
            maximum=TABULAR_STRUCTURED_EXPORT_HARD_MAX_BATCH_ROWS,
        ),
        'max_chars': _bounded_int(
            settings.get('tabular_generated_output_max_batch_chars'),
            default=TABULAR_STRUCTURED_EXPORT_MAX_BATCH_CHARS,
            minimum=TABULAR_STRUCTURED_EXPORT_MIN_BATCH_CHARS,
            maximum=TABULAR_STRUCTURED_EXPORT_HARD_MAX_BATCH_CHARS,
        ),
    }


def _build_tabular_generated_output_input_row(row, source_file_name=None):
    if not isinstance(row, dict):
        return row

    normalized_row = dict(row)
    referenced_documents = row.get('referenced_documents')
    if isinstance(referenced_documents, list):
        compact_referenced_documents = _compact_tabular_generated_output_referenced_documents(referenced_documents)
        if compact_referenced_documents:
            normalized_row['referenced_documents'] = compact_referenced_documents
        else:
            normalized_row.pop('referenced_documents', None)

    comment_id = _select_tabular_generated_output_scalar_value(
        normalized_row,
        candidate_labels=('comment_id', 'comment id', 'id', 'submission_id', 'submission id'),
    )
    if comment_id and not str(normalized_row.get('comment_id') or '').strip():
        normalized_row['comment_id'] = comment_id

    body_text = _select_tabular_generated_output_scalar_value(
        normalized_row,
        candidate_labels=(
            'body_text',
            'body text',
            'comment_text',
            'comment text',
            'comment',
            'submission_text',
            'submission text',
            'public comment',
            'text',
        ),
    )
    if body_text and not str(normalized_row.get('body_text') or '').strip():
        normalized_row['body_text'] = body_text

    source_file = _select_tabular_generated_output_scalar_value(
        normalized_row,
        candidate_labels=('source_file', 'source file', 'source_name', 'source name', 'workbook_name', 'workbook name', 'csv_name', 'csv name'),
    ) or str(source_file_name or '').strip()
    if source_file and not str(normalized_row.get('source_file') or '').strip():
        normalized_row['source_file'] = source_file

    attachment_names = _extract_tabular_generated_output_attachment_names(
        normalized_row,
        source_file_name=source_file_name,
    )
    if attachment_names:
        normalized_row['attachment_names'] = attachment_names
        if not str(normalized_row.get('file_name') or '').strip():
            normalized_row['file_name'] = attachment_names[0]

    attachment_text = _build_tabular_generated_output_attachment_text(normalized_row)
    if attachment_text:
        normalized_row['attachment_text'] = attachment_text

    if attachment_names or attachment_text:
        normalized_row['attachment_present'] = True

    for internal_field in TABULAR_GENERATED_OUTPUT_INTERNAL_ROW_FIELDS:
        normalized_row.pop(internal_field, None)

    return normalized_row


def _build_tabular_generated_output_file_name(source_file_name, output_format):
    timestamp_suffix = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    normalized_base_name = _sanitize_tabular_generated_output_base_name(source_file_name)
    normalized_extension = 'csv' if output_format == 'csv' else 'json'
    return f"{normalized_base_name}_generated_{timestamp_suffix}.{normalized_extension}"


def _build_tabular_generated_output_row_batches(rows, settings=None):
    budget = _get_tabular_generated_output_batch_budget(settings)
    max_batch_rows = budget['max_rows']
    max_batch_chars = budget['max_chars']
    batches = []
    current_batch = []
    current_batch_chars = 0

    for row in rows or []:
        row_text = _dump_tabular_generated_output_json(row)
        if current_batch and (
            len(current_batch) >= max_batch_rows
            or current_batch_chars + len(row_text) > max_batch_chars
        ):
            batches.append(current_batch)
            current_batch = []
            current_batch_chars = 0

        current_batch.append(row)
        current_batch_chars += len(row_text)

    if current_batch:
        batches.append(current_batch)

    return batches


def _build_tabular_generated_output_candidate_diagnostic(invocation):
    function_name = str(getattr(invocation, 'function_name', '') or '').strip()
    plugin_name = str(getattr(invocation, 'plugin_name', '') or '').strip()
    error_message = get_tabular_invocation_error_message(invocation)
    result_payload = get_tabular_invocation_result_payload(invocation)

    data_rows = result_payload.get('data') if isinstance(result_payload, dict) else None
    data_row_count = len(data_rows) if isinstance(data_rows, list) else 0
    returned_rows = _safe_int(result_payload.get('returned_rows')) if isinstance(result_payload, dict) else 0
    total_matches = _safe_int(result_payload.get('total_matches')) if isinstance(result_payload, dict) else 0
    full_result_available = bool(
        returned_rows > 0
        and data_row_count == returned_rows
        and total_matches == returned_rows
    )
    function_rank = {
        'query_tabular_data': 3,
        'filter_rows': 2,
        'search_rows': 1,
    }.get(function_name, 0)

    skip_reason = None
    if error_message:
        skip_reason = 'invocation_error'
    elif not isinstance(result_payload, dict):
        skip_reason = 'missing_result_payload'
    elif not isinstance(data_rows, list) or not data_rows:
        skip_reason = 'no_data_rows'

    return {
        'plugin_name': plugin_name or None,
        'function_name': function_name or None,
        'file_name': result_payload.get('filename') if isinstance(result_payload, dict) else None,
        'selected_sheet': result_payload.get('selected_sheet') if isinstance(result_payload, dict) else None,
        'returned_rows': returned_rows,
        'total_matches': total_matches,
        'data_row_count': data_row_count,
        'full_result_available': full_result_available,
        'function_rank': function_rank,
        'max_rows': result_payload.get('max_rows') if isinstance(result_payload, dict) else None,
        'filter_applied': result_payload.get('filter_applied') if isinstance(result_payload, dict) else None,
        'normalized_match': result_payload.get('normalized_match') if isinstance(result_payload, dict) else None,
        'skip_reason': skip_reason,
        'error_message': error_message,
    }


def _build_tabular_generated_output_candidate_diagnostics(invocations):
    return [
        _build_tabular_generated_output_candidate_diagnostic(invocation)
        for invocation in (invocations or [])
    ]


def _build_tabular_generated_output_source_candidate(invocations):
    best_candidate = None
    best_score = None

    for invocation in invocations or []:
        diagnostic = _build_tabular_generated_output_candidate_diagnostic(invocation)
        if diagnostic.get('skip_reason'):
            continue

        score = (
            1 if diagnostic.get('full_result_available') else 0,
            diagnostic.get('returned_rows') or diagnostic.get('data_row_count') or 0,
            diagnostic.get('function_rank') or 0,
        )
        if best_score is not None and score <= best_score:
            continue

        result_payload = get_tabular_invocation_result_payload(invocation)
        best_candidate = {
            'function_name': diagnostic.get('function_name'),
            'filename': result_payload.get('filename'),
            'selected_sheet': result_payload.get('selected_sheet'),
            'rows': result_payload.get('data'),
            'row_count': diagnostic.get('returned_rows') or diagnostic.get('data_row_count'),
            'total_matches': diagnostic.get('total_matches'),
            'full_result_available': diagnostic.get('full_result_available'),
            'diagnostics': diagnostic,
        }
        best_score = score

    return best_candidate


def _build_tabular_generated_output_batch_prompt(user_question, batch_rows, batch_index, total_batches, source_candidate):
    source_file_name = str(source_candidate.get('filename') or 'unknown file').strip() or 'unknown file'
    selected_sheet = str(source_candidate.get('selected_sheet') or '').strip()
    batch_rows_json = _dump_tabular_generated_output_json(batch_rows)
    selected_sheet_line = f"Worksheet: {selected_sheet}\n" if selected_sheet else ''

    return (
        'Transform the tabular input rows below into structured output for the user.\n\n'
        f'User instructions:\n{user_question}\n\n'
        'Return ONLY a valid JSON array.\n'
        f'Return exactly {len(batch_rows)} JSON object(s), one per input row, in the same order.\n'
        'Do not drop, merge, summarize, or cap rows.\n'
        'Input rows may include normalized helper fields such as comment_id, body_text, source_file, attachment_present, attachment_names, and attachment_text. Use those normalized fields when they are present.\n'
        'Input rows may include a referenced_documents array containing row-linked evidence from explicitly referenced non-tabular documents. Use that evidence as part of the source row context when it is relevant to the requested output.\n'
        'If referenced_documents contains excerpt text or attachment_text is present, treat that excerpt content as available attachment text. Do not say attachment text is unavailable when such excerpts are present.\n'
        'If a requested field cannot be derived, include the field with null or an empty string instead of omitting the row.\n'
        'Do not wrap the JSON in markdown fences.\n\n'
        f'Source file: {source_file_name}\n'
        f'{selected_sheet_line}'
        f'Batch: {batch_index + 1}/{total_batches}\n\n'
        f'Input rows:\n{batch_rows_json}'
    )


def _build_tabular_generated_output_system_message(output_metadata):
    output_format = str(output_metadata.get('output_format') or 'json').upper()
    file_name = str(output_metadata.get('file_name') or 'generated output').strip() or 'generated output'
    row_count = _safe_int(output_metadata.get('row_count'))

    if output_metadata.get('background_export'):
        run_id = str(output_metadata.get('export_run_id') or output_metadata.get('run_id') or '').strip()
        batch_count = _safe_int(output_metadata.get('batch_count'))
        return (
            f'A durable background {output_format} export has been queued for {row_count} row(s) '
            f'across {batch_count} batch(es). '
            'Do not claim the full export is attached yet. Tell the user the export is continuing in the background, '
            'that progress is checkpointed, and that the downloadable file will appear in the chat when the run completes. '
            f'Run id: {run_id}.'
        )

    return (
        f'A full downloadable {output_format} export containing {row_count} row(s) has already been prepared '
        f'for the user and attached to this chat as "{file_name}". '
        'Do not inline the full dataset in the assistant reply. Give a concise summary, mention that the full export is attached in the UI, '
        'and rely on the attached preview/download controls for the exhaustive output.'
    )


def _truncate_tabular_generated_output_response_preview(response_content, max_chars=400):
    cleaned = _clean_tabular_generated_json_code_fence(response_content)
    normalized = re.sub(r'\s+', ' ', cleaned).strip()
    if not normalized:
        return ''
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars]}..."


def _log_tabular_generated_output_handoff(conversation_id, user_question, output_metadata, injection_target):
    log_event(
        '[Tabular Generated Output] Added summary-only handoff system message',
        {
            'conversation_id': conversation_id,
            'injection_target': injection_target,
            'generated_file_name': output_metadata.get('file_name'),
            'output_format': output_metadata.get('output_format'),
            'row_count': output_metadata.get('row_count'),
            'source_file_name': output_metadata.get('source_file_name'),
            'background_export': bool(output_metadata.get('background_export')),
            'export_run_id': output_metadata.get('export_run_id') or output_metadata.get('run_id'),
            'structured_output_requested': question_requests_tabular_structured_object_output(user_question),
        },
        debug_only=True,
    )


async def _generate_tabular_structured_output_entries(
    user_question,
    source_candidate,
    gpt_model,
    settings,
    output_format='json',
    thought_callback=None,
    user_id=None,
    conversation_id=None,
    model_context=None,
):
    from semantic_kernel.contents.chat_history import ChatHistory as SKChatHistory

    rows = [
        _build_tabular_generated_output_input_row(
            row,
            source_file_name=source_candidate.get('filename'),
        )
        for row in (source_candidate.get('rows') or [])
    ]
    if not rows:
        return None

    chat_service, _ = build_semantic_kernel_chat_service_for_model(
        gpt_model,
        settings,
        service_id='tabular-generated-output',
        model_context=model_context,
    )

    normalized_output_format = str(output_format or 'json').strip().lower() or 'json'
    output_format_label = normalized_output_format.upper()
    batch_budget = _get_tabular_generated_output_batch_budget(settings)
    row_batches = _build_tabular_generated_output_row_batches(rows, settings=settings)
    total_batches = len(row_batches)
    log_event(
        '[Tabular Generated Output] Preparing structured export batches',
        {
            'source_file_name': source_candidate.get('filename'),
            'output_format': normalized_output_format,
            'row_count': len(rows),
            'batch_count': total_batches,
            'batch_row_budget': batch_budget['max_rows'],
            'batch_char_budget': batch_budget['max_chars'],
        },
        debug_only=True,
    )
    await emit_tabular_post_processing_thought(
        thought_callback,
        f"Preparing structured {output_format_label} export from tabular results",
        detail=f"rows={len(rows)}; batches={total_batches}",
        activity=build_tabular_post_processing_activity_payload(
            'tabular.generated_output',
            f"Preparing structured {output_format_label} export",
            'running',
            phase='structuring',
            output_format=normalized_output_format,
            file_name=source_candidate.get('filename'),
            batch_index=0,
            batch_count=total_batches,
        ),
    )

    if should_queue_tabular_generated_output_background(len(rows), total_batches, settings):
        if user_id and conversation_id:
            background_run = queue_tabular_generated_output_run(
                user_id=user_id,
                conversation_id=conversation_id,
                user_question=user_question,
                source_candidate=source_candidate,
                output_format=normalized_output_format,
                row_batches=row_batches,
                gpt_model=gpt_model,
                settings=settings,
                model_context=model_context,
            )
            background_metadata = build_background_tabular_generated_output_metadata(background_run)
            await emit_tabular_post_processing_thought(
                thought_callback,
                f"Queued structured {output_format_label} export to continue in the background",
                detail=(
                    f"run_id={background_metadata.get('export_run_id')}; "
                    f"rows={len(rows)}; batches={total_batches}; checkpointed=true"
                ),
                activity=build_tabular_post_processing_activity_payload(
                    'tabular.generated_output',
                    f"Structured {output_format_label} export queued",
                    'running',
                    phase='queued',
                    output_format=normalized_output_format,
                    file_name=source_candidate.get('filename'),
                    batch_index=0,
                    batch_count=total_batches,
                ),
            )
            return background_metadata

        log_event(
            '[Tabular Generated Output] Background export was eligible but lacked user or conversation context',
            {
                'source_file_name': source_candidate.get('filename'),
                'output_format': normalized_output_format,
                'row_count': len(rows),
                'batch_count': total_batches,
                'has_user_id': bool(user_id),
                'has_conversation_id': bool(conversation_id),
            },
            level=logging.WARNING,
        )

    merged_entries = []
    for batch_index, batch_rows in enumerate(row_batches):
        batch_number = batch_index + 1
        log_event(
            '[Tabular Generated Output] Building structured export batch',
            {
                'source_file_name': source_candidate.get('filename'),
                'output_format': normalized_output_format,
                'batch_number': batch_number,
                'batch_count': total_batches,
                'row_count': len(batch_rows),
            },
            debug_only=True,
        )
        await emit_tabular_post_processing_thought(
            thought_callback,
            f"Building structured {output_format_label} export batch {batch_number} of {total_batches}",
            detail=f"batch={batch_number}/{total_batches}; rows={len(batch_rows)}",
            activity=build_tabular_post_processing_activity_payload(
                'tabular.generated_output',
                f"Structured {output_format_label} export (batch {batch_number} of {total_batches})",
                'running',
                phase='structuring',
                output_format=normalized_output_format,
                file_name=source_candidate.get('filename'),
                batch_index=batch_number,
                batch_count=total_batches,
            ),
        )
        batch_prompt = _build_tabular_generated_output_batch_prompt(
            user_question,
            batch_rows,
            batch_index,
            total_batches,
            source_candidate,
        )

        parsed_entries = None
        for attempt_number in range(1, TABULAR_STRUCTURED_EXPORT_MAX_RETRY_ATTEMPTS + 1):
            chat_history = SKChatHistory()
            chat_history.add_system_message(
                'You transform tabular input rows into deterministic structured output. '
                'Return only a valid JSON array with one object per input row. '
                'Never add markdown, explanation text, or omit rows.'
            )
            if attempt_number > 1:
                await emit_tabular_post_processing_thought(
                    thought_callback,
                    f"Retrying structured {output_format_label} export batch {batch_number} of {total_batches}",
                    detail=f"batch={batch_number}/{total_batches}; attempt={attempt_number}",
                    activity=build_tabular_post_processing_activity_payload(
                        'tabular.generated_output',
                        f"Structured {output_format_label} export retry (batch {batch_number} of {total_batches})",
                        'running',
                        phase='structuring',
                        output_format=normalized_output_format,
                        file_name=source_candidate.get('filename'),
                        batch_index=batch_number,
                        batch_count=total_batches,
                    ),
                )
                chat_history.add_system_message(
                    f'The previous attempt did not return the required {len(batch_rows)} JSON object(s). '
                    'Retry now and preserve the input row count exactly.'
                )
            chat_history.add_user_message(batch_prompt)

            execution_settings = AzureChatPromptExecutionSettings(service_id='tabular-generated-output')
            result = await chat_service.get_chat_message_contents(chat_history, execution_settings)
            raw_response_content = result[0].content if result and result[0].content else ''
            if result and result[0].content:
                parsed_entries = _parse_tabular_generated_json_entries(raw_response_content)
            parsed_entry_count = len(parsed_entries) if parsed_entries is not None else 0
            if parsed_entries is None or parsed_entry_count != len(batch_rows):
                log_event(
                    '[Tabular Generated Output] Structured export batch attempt mismatch',
                    {
                        'source_file_name': source_candidate.get('filename'),
                        'output_format': normalized_output_format,
                        'batch_number': batch_number,
                        'batch_count': total_batches,
                        'attempt_number': attempt_number,
                        'expected_row_count': len(batch_rows),
                        'parsed_row_count': parsed_entry_count,
                        'response_char_count': len(raw_response_content),
                        'response_preview': _truncate_tabular_generated_output_response_preview(raw_response_content),
                    },
                    debug_only=True,
                )
            if parsed_entries is not None and len(parsed_entries) == len(batch_rows):
                break

        if parsed_entries is None or len(parsed_entries) != len(batch_rows):
            await emit_tabular_post_processing_thought(
                thought_callback,
                f"Structured {output_format_label} export failed on batch {batch_number} of {total_batches}",
                detail=f"batch={batch_number}/{total_batches}; rows={len(batch_rows)}",
                activity=build_tabular_post_processing_activity_payload(
                    'tabular.generated_output',
                    f"Structured {output_format_label} export failed",
                    'failed',
                    phase='structuring',
                    output_format=normalized_output_format,
                    file_name=source_candidate.get('filename'),
                    batch_index=batch_number,
                    batch_count=total_batches,
                ),
            )
            log_event(
                '[Tabular Generated Output] Structured export batch failed',
                {
                    'source_file_name': source_candidate.get('filename'),
                    'output_format': normalized_output_format,
                    'batch_number': batch_number,
                    'batch_count': total_batches,
                    'row_count': len(batch_rows),
                },
                debug_only=True,
            )
            return None

        merged_entries.extend(parsed_entries)

    return merged_entries


async def maybe_create_tabular_generated_output(
    user_question,
    invocations,
    gpt_model,
    settings,
    conversation_id,
    thought_callback=None,
    user_id=None,
    model_context=None,
):
    """Build, upload, and describe a generated tabular JSON/CSV export when requested."""
    if not question_requests_tabular_generated_output(user_question):
        return None

    output_format = get_tabular_generated_output_format(user_question)
    candidate_diagnostics = _build_tabular_generated_output_candidate_diagnostics(invocations)
    source_candidate = _build_tabular_generated_output_source_candidate(invocations)
    if candidate_diagnostics:
        log_event(
            '[Tabular Generated Output] Evaluated source candidates',
            {
                'conversation_id': conversation_id,
                'output_format': output_format,
                'candidate_count': len(candidate_diagnostics),
                'candidates': candidate_diagnostics,
            },
            debug_only=True,
        )
    if not source_candidate:
        log_event(
            '[Tabular Generated Output] No eligible source candidate selected',
            {
                'conversation_id': conversation_id,
                'output_format': output_format,
                'candidate_count': len(candidate_diagnostics),
                'structured_output_requested': question_requests_tabular_structured_object_output(user_question),
            },
            debug_only=True,
        )
        return None
    if not source_candidate.get('full_result_available'):
        log_event(
            '[Tabular Generated Output] Selected source candidate is incomplete; skipping export',
            {
                'conversation_id': conversation_id,
                'output_format': output_format,
                'selected_candidate': source_candidate.get('diagnostics'),
            },
            debug_only=True,
        )
        return None
    log_event(
        '[Tabular Generated Output] Selected source candidate',
        {
            'conversation_id': conversation_id,
            'output_format': output_format,
            'selected_candidate': source_candidate.get('diagnostics'),
        },
        debug_only=True,
    )
    rows = source_candidate.get('rows') or []
    if not output_format or not rows:
        return None

    if question_requests_tabular_structured_object_output(user_question):
        output_entries = await _generate_tabular_structured_output_entries(
            user_question,
            source_candidate,
            gpt_model,
            settings,
            output_format=output_format,
            thought_callback=thought_callback,
            user_id=user_id,
            conversation_id=conversation_id,
            model_context=model_context,
        )
        if output_entries is None:
            return None
        if isinstance(output_entries, dict) and output_entries.get('background_export'):
            return output_entries
    else:
        output_entries = rows

    if output_format == 'csv':
        serialized_output = _build_tabular_generated_output_csv(output_entries)
    else:
        serialized_output = json.dumps(output_entries, indent=2, default=str, ensure_ascii=False)

    generated_file_name = _build_tabular_generated_output_file_name(
        source_candidate.get('filename'),
        output_format,
    )
    output_format_label = str(output_format or 'json').upper()
    await emit_tabular_post_processing_thought(
        thought_callback,
        f"Uploading generated {output_format_label} export to this chat",
        detail=f"file={generated_file_name}; rows={len(output_entries)}",
        activity=build_tabular_post_processing_activity_payload(
            'tabular.generated_output',
            f"Uploading generated {output_format_label} export",
            'running',
            phase='uploading',
            output_format=output_format,
            file_name=generated_file_name,
        ),
    )
    log_event(
        '[Tabular Generated Output] Uploading generated export artifact',
        {
            'conversation_id': conversation_id,
            'source_file_name': source_candidate.get('filename'),
            'generated_file_name': generated_file_name,
            'output_format': output_format,
            'row_count': len(output_entries),
        },
        debug_only=True,
    )
    upload_result = upload_generated_analysis_artifact_for_current_user(
        conversation_id=conversation_id,
        file_name=generated_file_name,
        file_content=serialized_output,
        capability='tabular',
        output_format=output_format,
        summary=(
            f"Saved {len(output_entries)} row(s) to {generated_file_name} "
            'in this chat as a downloadable export.'
        ),
    )

    preview_rows = output_entries[:TABULAR_GENERATED_OUTPUT_PREVIEW_ROWS]
    uploaded_file_name = upload_result.get('message', {}).get('file_name') or generated_file_name
    await emit_tabular_post_processing_thought(
        thought_callback,
        f"Prepared downloadable {output_format_label} export",
        detail=f"file={uploaded_file_name}; rows={len(output_entries)}",
        activity=build_tabular_post_processing_activity_payload(
            'tabular.generated_output',
            f"Generated {output_format_label} export ready",
            'completed',
            phase='completed',
            output_format=output_format,
            file_name=uploaded_file_name,
        ),
    )
    log_event(
        '[Tabular Generated Output] Generated export ready',
        {
            'conversation_id': conversation_id,
            'source_file_name': source_candidate.get('filename'),
            'generated_file_name': uploaded_file_name,
            'output_format': output_format,
            'row_count': len(output_entries),
        },
        debug_only=True,
    )
    return {
        'capability': 'tabular',
        'artifact_message_id': upload_result.get('message', {}).get('id'),
        'conversation_id': conversation_id,
        'storage_scope': 'chat',
        'file_name': uploaded_file_name,
        'output_format': output_format,
        'row_count': len(output_entries),
        'source_file_name': source_candidate.get('filename'),
        'selected_sheet': source_candidate.get('selected_sheet'),
        'preview_rows': preview_rows,
        'summary': (
            f"Saved {len(output_entries)} row(s) to {uploaded_file_name} "
            'in this chat as a downloadable export.'
        ),
    }


def user_requested_chart_visualization(user_message):
    """Return True when the user is explicitly asking for a plotted visualization."""
    normalized_message = re.sub(r'\s+', ' ', str(user_message or '').strip().lower())
    if not normalized_message:
        return False

    non_visual_patterns = (
        'chart of accounts',
        'org chart',
        'organization chart',
        'organizational chart',
        'chart out ',
    )
    if any(pattern in normalized_message for pattern in non_visual_patterns):
        return False

    if re.search(
        r'\b(?:bar|line|pie|doughnut|scatter|bubble|radar|histogram|heatmap|area|stacked(?:\s+bar|\s+line)?)\s+chart\b',
        normalized_message,
    ):
        return True

    if 'table and chart' in normalized_message or 'chart and table' in normalized_message:
        return True

    if re.search(r'\b(?:graph|plot|visuali[sz]e?|visuali[sz]ation)\b', normalized_message):
        return True

    return bool(
        re.search(
            r'\b(?:include|with|show|create|generate|render|make|build|draw|produce)\b[^.!?\n]{0,80}\bchart\b',
            normalized_message,
        )
    )


def build_chart_tool_usage_system_message():
    """Instruct final generation to create useful inline charts in analytical outputs."""
    return build_proactive_chart_guidance_message()


def build_image_proposal_system_message():
    """Instruct final generation to emit opt-in image proposal cards."""
    return build_image_proposal_guidance_message()


def insert_system_message_after_existing_system_messages(conversation_history, system_message_content):
    """Insert a system message after existing system messages while avoiding duplicates."""
    if not isinstance(conversation_history, list):
        return conversation_history

    normalized_content = str(system_message_content or '').strip()
    if not normalized_content:
        return conversation_history

    for message in conversation_history:
        if (
            isinstance(message, dict)
            and message.get('role') == 'system'
            and str(message.get('content') or '').strip() == normalized_content
        ):
            return conversation_history

    insertion_index = 0
    while insertion_index < len(conversation_history):
        message = conversation_history[insertion_index]
        if not isinstance(message, dict) or message.get('role') != 'system':
            break
        insertion_index += 1

    conversation_history.insert(insertion_index, {
        'role': 'system',
        'content': normalized_content,
    })
    return conversation_history


def maybe_append_chart_tool_system_message(conversation_history, user_message, selected_agent=None):
    """Add chart guidance for explicit chart requests and analytical outputs."""
    del selected_agent
    if not (
        user_requested_chart_visualization(user_message)
        or user_request_supports_proactive_charts(user_message)
    ):
        return conversation_history

    return insert_system_message_after_existing_system_messages(
        conversation_history,
        build_chart_tool_usage_system_message(),
    )


def maybe_append_image_proposal_system_message(conversation_history, user_message, settings, selected_agent=None):
    """Add image proposal guidance when image generation is available and useful."""
    del selected_agent
    if not image_generation_is_enabled(settings):
        return conversation_history

    if not user_request_supports_image_proposals(user_message):
        return conversation_history

    return insert_system_message_after_existing_system_messages(
        conversation_history,
        build_image_proposal_system_message(),
    )


MULTI_FILE_TABULAR_DISTINCT_URL_EXTRACT_PATTERN = (
    r'(?i)https?://[^\s/]+/[^\s]*?(?:sites/|sitecollection/|teams/)[^\s"\']+'
)


def get_multi_file_tabular_analysis_mode(user_question, execution_mode='analysis', analysis_file_contexts=None):
    """Return a deterministic multi-file mode when the question should bypass SK planning."""
    normalized_execution_mode = str(execution_mode or 'analysis').strip().lower()
    normalized_contexts = dedupe_tabular_file_contexts(analysis_file_contexts)
    if normalized_execution_mode != 'analysis' or len(normalized_contexts) <= 1:
        return None

    if is_tabular_distinct_url_question(user_question):
        return 'distinct_url_union'

    return None


def score_tabular_distinct_url_column(column_name):
    """Score likely URL-bearing column names for deterministic multi-file analysis."""
    normalized_column_name = re.sub(r'\s+', ' ', str(column_name or '').strip().lower())
    if not normalized_column_name:
        return None

    exact_priority = {
        'location': 0,
        'locations': 0,
        'url': 1,
        'urls': 1,
        'link': 2,
        'links': 2,
        'site': 3,
        'sites': 3,
        'path': 4,
        'paths': 4,
        'address': 5,
        'addresses': 5,
    }
    if normalized_column_name in exact_priority:
        return exact_priority[normalized_column_name]

    token_priority = {
        'location': 0,
        'locations': 0,
        'url': 1,
        'urls': 1,
        'link': 2,
        'links': 2,
        'site': 3,
        'sites': 3,
        'sharepoint': 4,
        'path': 5,
        'paths': 5,
        'address': 6,
        'addresses': 6,
    }
    token_scores = [
        token_priority[token]
        for token in re.split(r'[^a-z0-9]+', normalized_column_name)
        if token and token in token_priority
    ]
    if not token_scores:
        return None

    return min(token_scores) + 10


def select_tabular_distinct_url_column(column_names):
    """Return the best URL-like column from a list of schema column names."""
    best_column_name = None
    best_comparison_key = None

    for candidate_column in column_names or []:
        rendered_column_name = str(candidate_column or '').strip()
        if not rendered_column_name:
            continue

        column_score = score_tabular_distinct_url_column(rendered_column_name)
        if column_score is None:
            continue

        comparison_key = (column_score, rendered_column_name.casefold())
        if best_comparison_key is None or comparison_key < best_comparison_key:
            best_comparison_key = comparison_key
            best_column_name = rendered_column_name

    return best_column_name


def select_tabular_distinct_url_sheet_and_column(schema_info):
    """Choose the best worksheet and column for deterministic multi-file URL extraction."""
    if not isinstance(schema_info, Mapping):
        return None, None

    per_sheet_schemas = schema_info.get('per_sheet_schemas', {})
    if isinstance(per_sheet_schemas, Mapping) and per_sheet_schemas:
        ranked_sheet_candidates = []
        for raw_sheet_name, raw_sheet_schema in per_sheet_schemas.items():
            if not isinstance(raw_sheet_schema, Mapping):
                continue

            selected_column = select_tabular_distinct_url_column(raw_sheet_schema.get('columns', []))
            if not selected_column:
                continue

            row_count = raw_sheet_schema.get('row_count', 0)
            try:
                normalized_row_count = int(row_count)
            except (TypeError, ValueError):
                normalized_row_count = 0

            ranked_sheet_candidates.append((
                score_tabular_distinct_url_column(selected_column),
                -normalized_row_count,
                str(raw_sheet_name or '').casefold(),
                str(raw_sheet_name or '').strip() or None,
                selected_column,
            ))

        if ranked_sheet_candidates:
            _, _, _, selected_sheet_name, selected_column_name = sorted(ranked_sheet_candidates)[0]
            return selected_sheet_name, selected_column_name

    return None, select_tabular_distinct_url_column(schema_info.get('columns', []))


def normalize_multi_file_tabular_distinct_value(value):
    """Normalize a distinct scalar so multi-file unions remain stable."""
    rendered_value = str(value or '').strip()
    if not rendered_value:
        return None

    return rendered_value.casefold()


def build_multi_file_tabular_distinct_value_analysis(successful_results, failed_results=None):
    """Build a deterministic combined distinct-value payload across multiple tabular files."""
    successful_results = list(successful_results or [])
    failed_results = list(failed_results or [])
    if not successful_results:
        return None

    combined_values_by_key = {}
    per_file_results = []
    any_values_limited = False
    files_with_matches = 0

    for result_payload in successful_results:
        file_values = []
        for raw_value in result_payload.get('values') or []:
            rendered_value = str(raw_value or '').strip()
            if not rendered_value:
                continue

            file_values.append(rendered_value)
            normalized_value_key = normalize_multi_file_tabular_distinct_value(rendered_value)
            if normalized_value_key and normalized_value_key not in combined_values_by_key:
                combined_values_by_key[normalized_value_key] = rendered_value

        distinct_count = parse_tabular_result_count(result_payload.get('distinct_count'))
        returned_values = parse_tabular_result_count(result_payload.get('returned_values'))
        if distinct_count is None:
            distinct_count = len(file_values)
        if returned_values is None:
            returned_values = len(file_values)

        values_limited = bool(result_payload.get('values_limited', False))
        any_values_limited = any_values_limited or values_limited
        if returned_values > 0:
            files_with_matches += 1

        per_file_results.append({
            'filename': result_payload.get('filename'),
            'selected_sheet': result_payload.get('selected_sheet'),
            'column': result_payload.get('column'),
            'distinct_count': distinct_count,
            'returned_values': returned_values,
            'values_limited': values_limited,
            'values': file_values,
        })

    combined_values = sorted(combined_values_by_key.values(), key=lambda item: item.casefold())
    return json.dumps({
        'analysis_type': 'multi_file_distinct_url_union',
        'files_requested': len(successful_results) + len(failed_results),
        'files_analyzed': len(successful_results),
        'files_with_matches': files_with_matches,
        'files_failed': len(failed_results),
        'distinct_count': len(combined_values),
        'returned_values': len(combined_values),
        'values_limited': any_values_limited,
        'values': combined_values,
        'per_file_results': per_file_results,
        'failed_files': failed_results,
    }, indent=2, default=str)


def get_kernel():
    return getattr(g, 'kernel', None) or getattr(builtins, 'kernel', None)


def get_kernel_agents():
    g_agents = getattr(g, 'kernel_agents', None)
    builtins_agents = getattr(builtins, 'kernel_agents', None)
    log_event(f"[SKChat] get_kernel_agents - g.kernel_agents: {type(g_agents)} ({len(g_agents) if g_agents else 0} agents), builtins.kernel_agents: {type(builtins_agents)} ({len(builtins_agents) if builtins_agents else 0} agents)", level=logging.INFO)
    return g_agents or builtins_agents

def is_personal_chat_conversation(conversation_item):
    """Return True when a conversation belongs to personal chat scope."""
    chat_type = str((conversation_item or {}).get('chat_type') or '').strip().lower()
    return not chat_type.startswith('group') and not chat_type.startswith('public')


class BackgroundStreamBridge:
    """Relay SSE events from a background worker to the active HTTP stream."""

    def __init__(self, max_queue_size=200, stream_session=None):
        self._queue = queue.Queue(maxsize=max_queue_size)
        self._sentinel = object()
        self._consumer_attached = True
        self._state_lock = threading.Lock()
        self._stream_session = stream_session
        self._last_backpressure_logged_at = 0.0

    def _record_queue_backpressure(self):
        if not self._stream_session:
            return

        stream_status = self._stream_session.note_queue_backpressure(self._queue.qsize()) or {}
        now = time.time()
        if (now - self._last_backpressure_logged_at) < 30:
            return

        self._last_backpressure_logged_at = now
        log_event(
            '[Streaming] SSE bridge queue backpressure detected',
            extra={
                'conversation_id': stream_status.get('conversation_id'),
                'user_id': stream_status.get('user_id'),
                'status': stream_status.get('status'),
                'queue_backpressure_count': stream_status.get('queue_backpressure_count'),
                'last_queue_depth': stream_status.get('last_queue_depth'),
                'event_count': stream_status.get('event_count'),
                'content_event_count': stream_status.get('content_event_count'),
            },
            level=logging.WARNING,
        )

    def push(self, event):
        """Queue an SSE event unless the consumer has already detached."""
        while True:
            with self._state_lock:
                consumer_attached = self._consumer_attached

            if not consumer_attached:
                return False

            try:
                self._queue.put(event, timeout=0.25)
                return True
            except queue.Full:
                self._record_queue_backpressure()
                continue

    def finish(self):
        """Signal stream completion to the active consumer."""
        while True:
            with self._state_lock:
                consumer_attached = self._consumer_attached

            if not consumer_attached:
                return

            try:
                self._queue.put(self._sentinel, timeout=0.25)
                return
            except queue.Full:
                continue

    def iter_events(self):
        """Yield queued SSE events until the worker finishes."""
        while True:
            try:
                next_item = self._queue.get(timeout=15)
            except queue.Empty:
                with self._state_lock:
                    consumer_attached = self._consumer_attached

                if not consumer_attached:
                    break

                if self._stream_session:
                    self._stream_session.note_keepalive(source='bridge')
                yield ': keep-alive\n\n'
                continue

            if next_item is self._sentinel:
                break
            yield next_item

    def detach_consumer(self, reason='consumer_cleanup', update_session=False):
        """Stop queueing new events once the HTTP consumer disconnects."""
        with self._state_lock:
            already_detached = not self._consumer_attached
            self._consumer_attached = False

        if already_detached:
            return

        if update_session and self._stream_session:
            stream_status = self._stream_session.mark_consumer_detached(reason=reason) or {}
            log_event(
                '[Streaming] Stream consumer detached',
                extra={
                    'conversation_id': stream_status.get('conversation_id'),
                    'user_id': stream_status.get('user_id'),
                    'status': stream_status.get('status'),
                    'detach_reason': stream_status.get('detach_reason'),
                    'detach_count': stream_status.get('detach_count'),
                    'event_count': stream_status.get('event_count'),
                    'content_event_count': stream_status.get('content_event_count'),
                    'content_chars': stream_status.get('content_chars'),
                },
                level=logging.WARNING,
            )

        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break


def _extract_sse_event_payload(event_text):
    """Parse JSON data lines from a raw SSE event string."""
    if not isinstance(event_text, str):
        return None

    data_lines = [
        line[5:].lstrip()
        for line in event_text.splitlines()
        if line.startswith('data:')
    ]
    if not data_lines:
        return None

    try:
        return json.loads('\n'.join(data_lines))
    except (TypeError, ValueError):
        return None


class ActiveConversationStreamSession:
    """Keep an in-flight stream replayable for reconnecting consumers."""

    HEARTBEAT_EVENT = ': keep-alive\n\n'

    def __init__(self, user_id, conversation_id, heartbeat_interval_seconds=15, session_ttl_seconds=600):
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.session_ttl_seconds = session_ttl_seconds
        self.cache_key = f'{user_id}:{conversation_id}'
        self._condition = threading.Condition()
        self._accepting_events = True

    def _build_metadata(self, active, existing=None):
        metadata = dict(existing or {})
        metadata.update({
            'user_id': self.user_id,
            'conversation_id': self.conversation_id,
            'active': bool(active),
            'heartbeat_interval_seconds': self.heartbeat_interval_seconds,
            'updated_at': _utcnow_iso(),
        })
        metadata.setdefault('status', STREAM_STATUS_STARTED)
        metadata.setdefault('started_at', metadata['updated_at'])
        metadata.setdefault('event_count', 0)
        metadata.setdefault('content_event_count', 0)
        metadata.setdefault('content_chars', 0)
        metadata.setdefault('consumer_detached', False)
        metadata.setdefault('detach_count', 0)
        metadata.setdefault('reattach_count', 0)
        metadata.setdefault('cancel_requested', False)
        metadata.setdefault('cancel_reason', None)
        metadata.setdefault('cancel_requested_at', None)
        metadata.setdefault('canceled_at', None)
        metadata.setdefault('queue_backpressure_count', 0)
        metadata.setdefault('last_error', None)
        return metadata

    def _get_metadata(self):
        metadata = app_settings_cache.get_stream_session_meta(self.cache_key)
        if not isinstance(metadata, dict):
            return {}
        return dict(metadata)

    def _persist_metadata(self, metadata):
        app_settings_cache.set_stream_session_meta(
            self.cache_key,
            metadata,
            ttl_seconds=self.session_ttl_seconds,
        )
        return metadata

    def get_status_snapshot(self):
        return _build_stream_status_payload(self._get_metadata())

    def initialize(self):
        """Initialize the stream session cache state for a new live response."""
        initial_metadata = self._build_metadata(active=True)
        app_settings_cache.initialize_stream_session_cache(
            self.cache_key,
            initial_metadata,
            ttl_seconds=self.session_ttl_seconds,
        )
        log_event(
            '[Streaming] Stream session started',
            extra={
                'conversation_id': self.conversation_id,
                'user_id': self.user_id,
                'status': initial_metadata.get('status'),
                'started_at': initial_metadata.get('started_at'),
                'heartbeat_interval_seconds': self.heartbeat_interval_seconds,
                'session_ttl_seconds': self.session_ttl_seconds,
            },
            level=logging.INFO,
        )

    def note_keepalive(self, source='unknown'):
        metadata = self._build_metadata(active=self.is_active(), existing=self._get_metadata())
        metadata['last_keepalive_at'] = _utcnow_iso()
        metadata['last_keepalive_source'] = str(source or 'unknown')
        self._persist_metadata(metadata)
        return self.get_status_snapshot()

    def note_queue_backpressure(self, queue_depth=0):
        metadata = self._build_metadata(active=self.is_active(), existing=self._get_metadata())
        metadata['queue_backpressure_count'] = _safe_int(metadata.get('queue_backpressure_count')) + 1
        metadata['last_queue_backpressure_at'] = _utcnow_iso()
        metadata['last_queue_depth'] = max(_safe_int(queue_depth), 0)
        self._persist_metadata(metadata)
        return self.get_status_snapshot()

    def mark_consumer_detached(self, reason='client_disconnect'):
        metadata = self._build_metadata(active=self.is_active(), existing=self._get_metadata())
        if metadata.get('consumer_detached'):
            return self.get_status_snapshot()

        metadata['consumer_detached'] = True
        metadata['detach_count'] = _safe_int(metadata.get('detach_count')) + 1
        metadata['last_detached_at'] = _utcnow_iso()
        metadata['detach_reason'] = str(reason or 'client_disconnect')
        if metadata.get('active'):
            metadata['status'] = STREAM_STATUS_DETACHED_RUNNING
        self._persist_metadata(metadata)
        return self.get_status_snapshot()

    def mark_reattached(self):
        metadata = self._build_metadata(active=self.is_active(), existing=self._get_metadata())
        metadata['consumer_detached'] = False
        metadata['reattach_count'] = _safe_int(metadata.get('reattach_count')) + 1
        metadata['last_reattach_at'] = _utcnow_iso()
        metadata['detach_reason'] = None
        if metadata.get('active'):
            metadata['status'] = STREAM_STATUS_STREAMING if metadata.get('first_content_at') else STREAM_STATUS_STARTED
        self._persist_metadata(metadata)
        return self.get_status_snapshot()

    def request_cancel(self, reason='user_requested'):
        metadata = self._build_metadata(active=self.is_active(), existing=self._get_metadata())
        if metadata.get('status') in TERMINAL_STREAM_STATUSES:
            return self.get_status_snapshot()

        normalized_reason = _truncate_log_text(reason, max_length=120) or 'user_requested'
        metadata['cancel_requested'] = True
        metadata['cancel_reason'] = normalized_reason
        metadata['cancel_requested_at'] = metadata.get('cancel_requested_at') or _utcnow_iso()
        metadata['status'] = STREAM_STATUS_CANCEL_REQUESTED
        self._persist_metadata(metadata)

        with self._condition:
            self._condition.notify_all()

        log_event(
            '[Streaming] Stream cancellation requested',
            extra={
                'conversation_id': self.conversation_id,
                'user_id': self.user_id,
                'status': metadata.get('status'),
                'cancel_reason': normalized_reason,
                'event_count': metadata.get('event_count'),
                'content_event_count': metadata.get('content_event_count'),
            },
            level=logging.INFO,
        )
        return self.get_status_snapshot()

    def is_cancel_requested(self):
        metadata = self._get_metadata()
        if not metadata or metadata.get('status') in TERMINAL_STREAM_STATUSES:
            return False
        return bool(metadata.get('cancel_requested'))

    def get_cancel_reason(self):
        metadata = self._get_metadata()
        return str(metadata.get('cancel_reason') or 'user_requested')

    def publish(self, event_text):
        """Append an SSE event to the replay history and notify listeners."""
        if event_text is None:
            return False

        with self._condition:
            if not self._accepting_events:
                return False

        payload = _extract_sse_event_payload(event_text)
        is_cancel_event = isinstance(payload, dict) and (
            payload.get('cancelled')
            or payload.get('canceled')
            or str(payload.get('type') or '').strip().lower() in {'cancelled', 'canceled'}
        )
        is_terminal_event = isinstance(payload, dict) and (payload.get('done') or payload.get('error') or is_cancel_event)

        metadata = self._build_metadata(active=not is_terminal_event, existing=self._get_metadata())
        metadata['event_count'] = _safe_int(metadata.get('event_count')) + 1
        metadata['last_event_at'] = _utcnow_iso()

        content_value = payload.get('content') if isinstance(payload, dict) else None
        first_content_emitted = False
        if content_value:
            metadata['content_event_count'] = _safe_int(metadata.get('content_event_count')) + 1
            metadata['content_chars'] = _safe_int(metadata.get('content_chars')) + len(str(content_value))
            if not metadata.get('first_content_at'):
                metadata['first_content_at'] = metadata['last_event_at']
                first_content_emitted = True

        if is_terminal_event:
            metadata['completed_at'] = metadata['last_event_at']
            if is_cancel_event:
                metadata['status'] = STREAM_STATUS_CANCELED
                metadata['canceled_at'] = metadata['last_event_at']
                metadata['cancel_requested'] = True
            else:
                metadata['status'] = STREAM_STATUS_ERROR if payload.get('error') else STREAM_STATUS_COMPLETED
            if payload.get('error'):
                metadata['last_error'] = str(payload.get('error'))
        elif metadata.get('consumer_detached'):
            metadata['status'] = STREAM_STATUS_DETACHED_RUNNING
        elif metadata.get('cancel_requested'):
            metadata['status'] = STREAM_STATUS_CANCEL_REQUESTED
        elif metadata.get('first_content_at'):
            metadata['status'] = STREAM_STATUS_STREAMING
        else:
            metadata['status'] = STREAM_STATUS_STARTED

        app_settings_cache.append_stream_session_event(
            self.cache_key,
            event_text,
            ttl_seconds=self.session_ttl_seconds,
        )
        self._persist_metadata(metadata)

        if first_content_emitted:
            log_event(
                '[Streaming] First stream content emitted',
                extra={
                    'conversation_id': self.conversation_id,
                    'user_id': self.user_id,
                    'status': metadata.get('status'),
                    'first_content_at': metadata.get('first_content_at'),
                    'event_count': metadata.get('event_count'),
                },
                level=logging.INFO,
            )

        if is_terminal_event:
            log_event(
                '[Streaming] Stream session completed' if metadata.get('status') == STREAM_STATUS_COMPLETED else '[Streaming] Stream session failed',
                extra={
                    'conversation_id': self.conversation_id,
                    'user_id': self.user_id,
                    'status': metadata.get('status'),
                    'started_at': metadata.get('started_at'),
                    'completed_at': metadata.get('completed_at'),
                    'event_count': metadata.get('event_count'),
                    'content_event_count': metadata.get('content_event_count'),
                    'content_chars': metadata.get('content_chars'),
                    'detach_count': metadata.get('detach_count'),
                    'reattach_count': metadata.get('reattach_count'),
                    'last_error': metadata.get('last_error'),
                },
                level=logging.INFO if metadata.get('status') == STREAM_STATUS_COMPLETED else logging.ERROR,
            )

        with self._condition:
            self._condition.notify_all()
            return True

    def close(self):
        """Mark the session as closed once the worker has no more events."""
        with self._condition:
            self._accepting_events = False
            self._condition.notify_all()

        metadata = self._build_metadata(active=False, existing=self._get_metadata())
        if metadata.get('status') not in TERMINAL_STREAM_STATUSES:
            metadata['status'] = STREAM_STATUS_CANCELED if metadata.get('cancel_requested') else STREAM_STATUS_COMPLETED
            metadata['completed_at'] = metadata.get('completed_at') or _utcnow_iso()
            if metadata['status'] == STREAM_STATUS_CANCELED:
                metadata['canceled_at'] = metadata.get('canceled_at') or metadata['completed_at']
            self._persist_metadata(metadata)
            log_event(
                '[Streaming] Stream session closed without explicit terminal event',
                extra={
                    'conversation_id': self.conversation_id,
                    'user_id': self.user_id,
                    'status': metadata.get('status'),
                    'started_at': metadata.get('started_at'),
                    'completed_at': metadata.get('completed_at'),
                    'event_count': metadata.get('event_count'),
                    'detach_count': metadata.get('detach_count'),
                },
                level=logging.WARNING,
            )
            return

        self._persist_metadata(metadata)

    def is_active(self):
        metadata = self._get_metadata()
        return bool(metadata.get('active'))

    def is_expired(self, ttl_seconds):
        metadata = app_settings_cache.get_stream_session_meta(self.cache_key)
        return metadata is None

    def iter_events(self, start_index=0):
        """Yield replayed and live SSE events, with heartbeat comments while idle."""
        next_index = max(int(start_index or 0), 0)
        last_heartbeat_at = time.time()

        while True:
            pending_events = app_settings_cache.get_stream_session_events(
                self.cache_key,
                start_index=next_index,
            ) or []
            if pending_events:
                for event_to_yield in pending_events:
                    next_index += 1
                    last_heartbeat_at = time.time()
                    yield event_to_yield
                continue

            metadata = app_settings_cache.get_stream_session_meta(self.cache_key)
            if not metadata:
                return

            heartbeat_interval_seconds = int(
                metadata.get('heartbeat_interval_seconds') or self.heartbeat_interval_seconds
            )
            if not metadata.get('active'):
                return

            remaining_heartbeat_seconds = max(
                heartbeat_interval_seconds - (time.time() - last_heartbeat_at),
                0.25,
            )
            with self._condition:
                self._condition.wait(timeout=min(1.0, remaining_heartbeat_seconds))

            if (time.time() - last_heartbeat_at) >= heartbeat_interval_seconds:
                last_heartbeat_at = time.time()
                self.note_keepalive(source='session')
                yield self.HEARTBEAT_EVENT


class ActiveConversationStreamRegistry:
    """Track live chat streams per user and conversation for reconnect support."""

    def __init__(self, completed_session_ttl_seconds=600, heartbeat_interval_seconds=15):
        self.completed_session_ttl_seconds = completed_session_ttl_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self._sessions = {}
        self._lock = threading.Lock()

    def _cleanup_locked(self):
        expired_keys = [
            key for key, session in self._sessions.items()
            if session.is_expired(self.completed_session_ttl_seconds)
        ]
        for key in expired_keys:
            self._sessions.pop(key, None)

    def start_session(self, user_id, conversation_id):
        if not user_id or not conversation_id:
            return None

        with self._lock:
            self._cleanup_locked()
            key = (user_id, conversation_id)
            existing_session = self._sessions.get(key)
            if existing_session and existing_session.is_active():
                existing_session.close()

            session = ActiveConversationStreamSession(
                user_id=user_id,
                conversation_id=conversation_id,
                heartbeat_interval_seconds=self.heartbeat_interval_seconds,
                session_ttl_seconds=self.completed_session_ttl_seconds,
            )
            self._sessions[key] = session
            session.initialize()
            return session

    def get_session(self, user_id, conversation_id, active_only=False):
        if not user_id or not conversation_id:
            return None

        with self._lock:
            self._cleanup_locked()
            key = (user_id, conversation_id)
            session = self._sessions.get(key)
            if not session:
                metadata = app_settings_cache.get_stream_session_meta(f'{user_id}:{conversation_id}')
                if not metadata:
                    return None
                session = ActiveConversationStreamSession(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    heartbeat_interval_seconds=int(
                        metadata.get('heartbeat_interval_seconds') or self.heartbeat_interval_seconds
                    ),
                    session_ttl_seconds=self.completed_session_ttl_seconds,
                )
                self._sessions[key] = session
            if active_only and not session.is_active():
                return None
            return session


CHAT_STREAM_REGISTRY = ActiveConversationStreamRegistry()


def get_new_plugin_invocations(invocations, baseline_count):
    """Return only the plugin invocations created after the baseline count."""
    if not invocations:
        return []

    if baseline_count <= 0:
        return list(invocations)

    if baseline_count >= len(invocations):
        return []

    return list(invocations[baseline_count:])


def split_tabular_plugin_invocations(invocations):
    """Split tabular plugin invocations into discovery and analytical categories."""
    discovery_invocations = []
    analytical_invocations = []
    other_invocations = []

    for invocation in invocations or []:
        function_name = getattr(invocation, 'function_name', '')

        if function_name in get_tabular_discovery_function_names():
            discovery_invocations.append(invocation)
        elif function_name in get_tabular_analysis_function_names():
            analytical_invocations.append(invocation)
        else:
            other_invocations.append(invocation)

    return discovery_invocations, analytical_invocations, other_invocations


def get_tabular_invocation_result_payload(invocation):
    """Parse a tabular invocation result payload when it is JSON-like."""
    result = getattr(invocation, 'result', None)
    if isinstance(result, dict):
        return result
    if not isinstance(result, str):
        return None

    try:
        payload = json.loads(result)
    except Exception:
        return None

    return payload if isinstance(payload, dict) else None


def get_tabular_invocation_error_message(invocation):
    """Return an error message for a tabular invocation, including JSON error payloads."""
    explicit_error_message = getattr(invocation, 'error_message', None)
    if explicit_error_message:
        return str(explicit_error_message)

    result_payload = get_tabular_invocation_result_payload(invocation)
    if result_payload and result_payload.get('error'):
        return str(result_payload['error'])

    return None


def get_tabular_invocation_candidate_sheets(invocation):
    """Return candidate workbook sheets suggested by a tabular tool error payload."""
    result_payload = get_tabular_invocation_result_payload(invocation)
    candidate_sheets = result_payload.get('candidate_sheets') if result_payload else None
    if not isinstance(candidate_sheets, list):
        return []

    normalized_candidate_sheets = []
    seen_candidate_sheets = set()
    for candidate_sheet in candidate_sheets:
        normalized_candidate_sheet = str(candidate_sheet or '').strip()
        if not normalized_candidate_sheet:
            continue

        lowercase_candidate_sheet = normalized_candidate_sheet.lower()
        if lowercase_candidate_sheet in seen_candidate_sheets:
            continue

        seen_candidate_sheets.add(lowercase_candidate_sheet)
        normalized_candidate_sheets.append(normalized_candidate_sheet)

    return normalized_candidate_sheets


def get_tabular_invocation_selected_sheet(invocation):
    """Return the resolved sheet used by a tabular invocation when available."""
    result_payload = get_tabular_invocation_result_payload(invocation) or {}
    invocation_parameters = getattr(invocation, 'parameters', {}) or {}

    selected_sheet = str(
        result_payload.get('selected_sheet')
        or invocation_parameters.get('sheet_name')
        or ''
    ).strip()
    return selected_sheet or None


def get_tabular_invocation_data_rows(invocation):
    """Return tabular result rows when the invocation payload includes them."""
    result_payload = get_tabular_invocation_result_payload(invocation) or {}
    rows = result_payload.get('data')
    return rows if isinstance(rows, list) else []


def normalize_tabular_overlap_value(value):
    """Normalize row identifier values so they can be intersected reliably."""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str)
    if value is None:
        return None
    return str(value)


def get_tabular_overlap_identifier_column(row_sets):
    """Return a shared identifier column suitable for intersecting row sets."""
    common_columns = None

    for rows in row_sets or []:
        if not rows:
            return None

        row_columns = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_columns.update(str(column_name) for column_name in row.keys())

        if not row_columns:
            return None

        if common_columns is None:
            common_columns = row_columns
        else:
            common_columns &= row_columns

    if not common_columns:
        return None

    identifier_candidates = [
        column_name for column_name in common_columns
        if column_name.lower() == 'id' or column_name.lower().endswith('id')
    ]
    if not identifier_candidates:
        return None

    preferred_order = {
        'flightid': 0,
        'returnid': 1,
        'taxpayerid': 2,
        'paymentid': 3,
        'caseid': 4,
        'accountid': 5,
        'recordid': 6,
        'id': 7,
    }

    return sorted(
        identifier_candidates,
        key=lambda column_name: (
            preferred_order.get(column_name.lower(), 99),
            column_name.lower(),
        ),
    )[0]


def describe_tabular_invocation_conditions(invocation):
    """Render a compact description of the invocation filters for raw fallbacks."""
    parameters = getattr(invocation, 'parameters', {}) or {}

    query_expression = str(parameters.get('query_expression') or '').strip()
    if query_expression:
        return query_expression

    search_value = str(parameters.get('search_value') or '').strip()
    if search_value:
        search_columns = str(parameters.get('search_columns') or '').strip() or 'ALL COLUMNS'
        search_operator = str(parameters.get('search_operator') or 'contains').strip()
        return f"search_value={search_value}; search_operator={search_operator}; search_columns={search_columns}"

    column_name = str(parameters.get('column') or '').strip()
    operator = str(parameters.get('operator') or '').strip()
    value = parameters.get('value')
    if column_name and operator:
        return f"{column_name} {operator} {value}"

    lookup_column = str(parameters.get('lookup_column') or '').strip()
    lookup_value = parameters.get('lookup_value')
    if lookup_column:
        return f"{lookup_column} == {lookup_value}"

    extract_mode = str(parameters.get('extract_mode') or '').strip()
    if extract_mode:
        extraction_bits = [f"extract_mode={extract_mode}"]
        extract_pattern = str(parameters.get('extract_pattern') or '').strip()
        url_path_segments = parameters.get('url_path_segments')
        if extract_pattern:
            extraction_bits.append(f"extract_pattern={extract_pattern}")
        if url_path_segments not in (None, ''):
            extraction_bits.append(f"url_path_segments={url_path_segments}")
        return ', '.join(extraction_bits)

    return None


def compact_tabular_fallback_value(value, depth=0, max_depth=2):
    """Reduce large tabular fallback values to prompt-safe summaries."""
    if value is None or isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, str):
        max_string_length = 400
        if len(value) <= max_string_length:
            return value
        return f"{value[:max_string_length]}... [truncated {len(value) - max_string_length} chars]"

    if depth >= max_depth:
        if isinstance(value, dict):
            return f"<dict with {len(value)} keys>"
        if isinstance(value, list):
            return f"<list with {len(value)} items>"
        return str(value)

    if isinstance(value, list):
        compact_items = [
            compact_tabular_fallback_value(item, depth=depth + 1, max_depth=max_depth)
            for item in value[:5]
        ]
        if len(value) > 5:
            compact_items.append({'remaining_items': len(value) - 5})
        return compact_items

    if isinstance(value, dict):
        compact_mapping = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 12:
                compact_mapping['remaining_keys'] = len(value) - 12
                break
            compact_mapping[str(key)] = compact_tabular_fallback_value(
                item,
                depth=depth + 1,
                max_depth=max_depth,
            )
        return compact_mapping

    return str(value)


def get_tabular_query_overlap_summary(invocations, max_rows=10):
    """Summarize overlap across successful row-returning tabular calls.

    This is a defensive fallback for cases where tool execution succeeded but the
    inner SK synthesis step failed before it could combine the results.
    """
    grouped_invocations = {}

    for invocation in invocations or []:
        function_name = getattr(invocation, 'function_name', '')
        if function_name not in {'query_tabular_data', 'filter_rows', 'search_rows'}:
            continue

        rows = get_tabular_invocation_data_rows(invocation)
        if not rows:
            continue

        result_payload = get_tabular_invocation_result_payload(invocation) or {}
        group_key = (
            str(result_payload.get('filename') or '').strip(),
            str(get_tabular_invocation_selected_sheet(invocation) or '').strip(),
        )
        grouped_invocations.setdefault(group_key, []).append({
            'invocation': invocation,
            'rows': rows,
            'payload': result_payload,
        })

    best_summary = None

    for (filename, selected_sheet), grouped_items in grouped_invocations.items():
        if len(grouped_items) < 2:
            continue

        row_sets = [grouped_item['rows'] for grouped_item in grouped_items]
        identifier_column = get_tabular_overlap_identifier_column(row_sets)
        if not identifier_column:
            continue

        overlapping_keys = None
        for rows in row_sets:
            row_keys = {
                normalize_tabular_overlap_value(row.get(identifier_column))
                for row in rows
                if isinstance(row, dict) and normalize_tabular_overlap_value(row.get(identifier_column)) is not None
            }
            if overlapping_keys is None:
                overlapping_keys = row_keys
            else:
                overlapping_keys &= row_keys

        if not overlapping_keys:
            continue

        ordered_sample_rows = []
        seen_sample_keys = set()
        for row in grouped_items[0]['rows']:
            if not isinstance(row, dict):
                continue

            row_key = normalize_tabular_overlap_value(row.get(identifier_column))
            if row_key not in overlapping_keys or row_key in seen_sample_keys:
                continue

            ordered_sample_rows.append(compact_tabular_fallback_value(row))
            seen_sample_keys.add(row_key)
            if len(ordered_sample_rows) >= max_rows:
                break

        source_queries = []
        for grouped_item in grouped_items:
            rendered_conditions = describe_tabular_invocation_conditions(grouped_item['invocation'])
            if rendered_conditions:
                source_queries.append(compact_tabular_fallback_value(rendered_conditions))

        overlap_summary = {
            'filename': filename or None,
            'selected_sheet': selected_sheet or None,
            'identifier_column': identifier_column,
            'overlap_count': len(overlapping_keys),
            'sample_rows': ordered_sample_rows,
            'sample_rows_limited': len(overlapping_keys) > len(ordered_sample_rows),
            'source_queries': source_queries,
        }

        if best_summary is None or overlap_summary['overlap_count'] > best_summary['overlap_count']:
            best_summary = overlap_summary

    return best_summary


def get_tabular_invocation_compact_payload(invocation, max_rows=5):
    """Return a compact, prompt-safe summary of a successful tabular invocation."""
    result_payload = get_tabular_invocation_result_payload(invocation)
    if not result_payload:
        return None

    function_name = getattr(invocation, 'function_name', '')
    compact_payload = {
        'function': function_name,
        'filename': compact_tabular_fallback_value(result_payload.get('filename')),
        'selected_sheet': compact_tabular_fallback_value(result_payload.get('selected_sheet')),
    }

    if function_name == 'aggregate_column':
        compact_payload.update({
            'column': compact_tabular_fallback_value(result_payload.get('column')),
            'operation': compact_tabular_fallback_value(result_payload.get('operation')),
            'result': compact_tabular_fallback_value(result_payload.get('result')),
        })
    elif function_name == 'get_distinct_values':
        for key_name in (
            'column',
            'filter_applied',
            'normalize_match',
            'extract_mode',
            'extract_pattern',
            'url_path_segments',
            'matched_cell_count',
            'extracted_match_count',
            'distinct_count',
            'returned_values',
            'values_limited',
        ):
            if key_name in result_payload:
                compact_payload[key_name] = compact_tabular_fallback_value(result_payload.get(key_name))

        raw_values = result_payload.get('values')
        if isinstance(raw_values, list):
            compact_values = []
            rendered_values_length = 0
            max_values_in_payload = 200
            max_rendered_values_chars = 14000

            for raw_value in raw_values:
                compact_value = compact_tabular_fallback_value(raw_value)
                rendered_value = json.dumps(compact_value, default=str)
                projected_length = rendered_values_length + len(rendered_value) + 2

                if compact_values and (
                    len(compact_values) >= max_values_in_payload
                    or projected_length > max_rendered_values_chars
                ):
                    break

                compact_values.append(compact_value)
                rendered_values_length = projected_length

            compact_payload['values'] = compact_values
            compact_payload['full_values_included'] = len(compact_values) == len(raw_values)
            if len(compact_values) != len(raw_values):
                compact_payload['values_limited'] = True
                compact_payload['returned_values'] = len(compact_values)
    elif function_name in {'group_by_aggregate', 'group_by_datetime_component'}:
        for key_name in (
            'group_by',
            'date_component',
            'aggregate_column',
            'operation',
            'groups',
            'highest_group',
            'highest_value',
            'lowest_group',
            'lowest_value',
            'top_results',
        ):
            if key_name in result_payload:
                compact_payload[key_name] = compact_tabular_fallback_value(result_payload.get(key_name))
    elif function_name == 'lookup_value':
        for key_name in (
            'lookup_column',
            'lookup_value',
            'target_column',
            'value',
            'total_matches',
            'returned_rows',
        ):
            if key_name in result_payload:
                compact_payload[key_name] = compact_tabular_fallback_value(result_payload.get(key_name))

        data_rows = get_tabular_invocation_data_rows(invocation)
        if data_rows:
            compact_payload['sample_rows'] = [
                compact_tabular_fallback_value(row)
                for row in data_rows[:max_rows]
            ]
            compact_payload['sample_rows_limited'] = len(data_rows) > max_rows
    elif function_name in {'query_tabular_data', 'filter_rows', 'search_rows'}:
        for key_name in ('search_value', 'search_operator', 'searched_columns', 'matched_columns', 'return_columns'):
            if key_name in result_payload:
                compact_payload[key_name] = compact_tabular_fallback_value(result_payload.get(key_name))

        for key_name in ('total_matches', 'returned_rows'):
            if key_name in result_payload:
                compact_payload[key_name] = compact_tabular_fallback_value(result_payload.get(key_name))

        data_rows = get_tabular_invocation_data_rows(invocation)
        if data_rows:
            desired_max_rows = max_rows
            total_matches = result_payload.get('total_matches')
            returned_rows = result_payload.get('returned_rows')
            try:
                total_matches = int(total_matches)
            except (TypeError, ValueError):
                total_matches = None
            try:
                returned_rows = int(returned_rows)
            except (TypeError, ValueError):
                returned_rows = len(data_rows)

            if (
                total_matches is not None
                and returned_rows == total_matches
                and total_matches <= 25
            ):
                desired_max_rows = max(desired_max_rows, total_matches)

            compact_payload['sample_rows'] = [
                compact_tabular_fallback_value(row)
                for row in data_rows[:desired_max_rows]
            ]
            compact_payload['sample_rows_limited'] = len(data_rows) > desired_max_rows
            compact_payload['full_rows_included'] = (
                total_matches is not None
                and total_matches == returned_rows
                and len(compact_payload['sample_rows']) == len(data_rows)
            )

        rendered_conditions = describe_tabular_invocation_conditions(invocation)
        if rendered_conditions:
            compact_payload['conditions'] = compact_tabular_fallback_value(rendered_conditions)
    else:
        compact_payload.update({
            key: compact_tabular_fallback_value(value)
            for key, value in result_payload.items()
        })

    if '[truncated ' in json.dumps(compact_payload, default=str):
        compact_payload['result_summary_truncated'] = True

    return compact_payload


def build_tabular_analysis_fallback_from_invocations(invocations):
    """Build a compact computed-results handoff from successful tool calls.

    Used when the mini SK tabular pass completed tool execution but failed to
    produce a final natural-language synthesis response.
    """
    successful_invocations = [
        invocation for invocation in (invocations or [])
        if not get_tabular_invocation_error_message(invocation)
    ]
    if not successful_invocations:
        return None

    max_fallback_chars = 24000
    coverage_note_reserve = 1200
    overlap_summary = get_tabular_query_overlap_summary(successful_invocations, max_rows=10)
    rendered_sections = [
        "The following structured results come directly from successful tabular tool executions.",
        "Use them as computed evidence even though the inner tabular synthesis step did not complete.",
    ]

    if overlap_summary:
        if overlap_summary.get('sample_rows') and len(json.dumps(overlap_summary, default=str)) > 6000:
            overlap_summary = dict(overlap_summary)
            overlap_summary['sample_rows'] = overlap_summary.get('sample_rows', [])[:5]
            overlap_summary['sample_rows_limited'] = True

        rendered_sections.append(
            "OVERLAP SUMMARY:\n"
            f"{json.dumps(overlap_summary, indent=2, default=str)}"
        )

    base_rendered_text = "\n\n".join(rendered_sections)
    compact_results = []
    invocation_limit = 8
    candidate_invocations = successful_invocations[:invocation_limit]
    for invocation in candidate_invocations:
        compact_payload = get_tabular_invocation_compact_payload(invocation, max_rows=5)
        if compact_payload is None:
            continue

        candidate_results = compact_results + [compact_payload]
        candidate_section = (
            "TOOL RESULT SUMMARIES:\n"
            f"{json.dumps(candidate_results, indent=2, default=str)}"
        )
        candidate_text = base_rendered_text + ("\n\n" if base_rendered_text else "") + candidate_section
        if len(candidate_text) <= (max_fallback_chars - coverage_note_reserve):
            compact_results = candidate_results
            continue

        if compact_results:
            break

        shrunk_payload = dict(compact_payload)
        if 'sample_rows' in shrunk_payload:
            shrunk_payload['sample_rows'] = shrunk_payload['sample_rows'][:2]
            shrunk_payload['sample_rows_limited'] = True
            shrunk_payload['full_rows_included'] = False
        if isinstance(shrunk_payload.get('values'), list) and len(shrunk_payload['values']) > 25:
            shrunk_payload['values'] = shrunk_payload['values'][:25]
            shrunk_payload['values_limited'] = True
            shrunk_payload['full_values_included'] = False
            shrunk_payload['returned_values'] = min(
                int(shrunk_payload.get('returned_values') or len(shrunk_payload['values'])),
                len(shrunk_payload['values']),
            )
        if isinstance(shrunk_payload.get('top_results'), dict):
            shrunk_payload['top_results'] = dict(list(shrunk_payload['top_results'].items())[:3])

        candidate_section = (
            "TOOL RESULT SUMMARIES:\n"
            f"{json.dumps([shrunk_payload], indent=2, default=str)}"
        )
        candidate_text = base_rendered_text + ("\n\n" if base_rendered_text else "") + candidate_section
        if len(candidate_text) > (max_fallback_chars - coverage_note_reserve):
            shrunk_payload.pop('sample_rows', None)
            shrunk_payload['sample_rows_limited'] = True
            shrunk_payload['full_rows_included'] = False
            if isinstance(shrunk_payload.get('values'), list) and len(shrunk_payload['values']) > 10:
                shrunk_payload['values'] = shrunk_payload['values'][:10]
                shrunk_payload['values_limited'] = True
                shrunk_payload['full_values_included'] = False
                shrunk_payload['returned_values'] = min(
                    int(shrunk_payload.get('returned_values') or len(shrunk_payload['values'])),
                    len(shrunk_payload['values']),
                )
            shrunk_payload['result_summary_truncated'] = True
            if isinstance(shrunk_payload.get('top_results'), dict):
                shrunk_payload['top_results'] = dict(list(shrunk_payload['top_results'].items())[:2])

        compact_results = [shrunk_payload]
        break

    if not overlap_summary and not compact_results:
        return None

    if compact_results:
        rendered_sections.append(
            "TOOL RESULT SUMMARIES:\n"
            f"{json.dumps(compact_results, indent=2, default=str)}"
        )

    omitted_invocation_count = len(candidate_invocations) - len(compact_results)
    if len(successful_invocations) > invocation_limit:
        omitted_invocation_count += len(successful_invocations) - invocation_limit
    if omitted_invocation_count > 0:
        rendered_sections.append(
            "RESULT COVERAGE NOTE:\n"
            f"Included {len(compact_results)} compact tool summaries out of {len(successful_invocations)} successful tool executions to stay within the prompt budget. "
            "Use targeted follow-up tool calls if additional raw detail is required."
        )

    return "\n\n".join(rendered_sections)


def build_tabular_schema_summary_fallback_from_invocations(user_question, invocations):
    """Build a compact schema-summary handoff from describe_tabular_file results."""
    del user_question
    schema_results = []
    for invocation in invocations or []:
        if getattr(invocation, 'function_name', '') != 'describe_tabular_file':
            continue
        if get_tabular_invocation_error_message(invocation):
            continue

        result_payload = get_tabular_invocation_result_payload(invocation)
        if not isinstance(result_payload, dict):
            continue

        compact_payload = {
            'filename': result_payload.get('filename'),
            'is_workbook': result_payload.get('is_workbook'),
            'sheet_names': result_payload.get('sheet_names', []),
            'sheet_count': result_payload.get('sheet_count', 0),
            'sheet_role_hints': result_payload.get('sheet_role_hints', {}),
            'relationship_hints': (result_payload.get('relationship_hints') or [])[:8],
        }
        per_sheet_schemas = result_payload.get('per_sheet_schemas') or {}
        sheet_directory = []
        for sheet_name, sheet_info in per_sheet_schemas.items():
            if not isinstance(sheet_info, dict):
                continue
            sheet_directory.append({
                'sheet_name': sheet_name,
                'row_count': sheet_info.get('row_count', 0),
                'columns': sheet_info.get('columns', []),
            })
        if sheet_directory:
            compact_payload['sheet_directory'] = sheet_directory
        else:
            compact_payload['columns'] = result_payload.get('columns', [])
            compact_payload['row_count'] = result_payload.get('row_count', 0)
            compact_payload['sample_rows'] = (result_payload.get('sample_rows') or [])[:3]

        schema_results.append(compact_payload)

    if not schema_results:
        return None

    rendered_schema = json.dumps(schema_results, indent=2, default=str)
    if len(rendered_schema) > 22000:
        for schema_result in schema_results:
            if isinstance(schema_result.get('sheet_directory'), list):
                schema_result['sheet_directory'] = schema_result['sheet_directory'][:20]
                schema_result['sheet_directory_limited'] = True
            if isinstance(schema_result.get('relationship_hints'), list):
                schema_result['relationship_hints'] = schema_result['relationship_hints'][:5]
        rendered_schema = json.dumps(schema_results, indent=2, default=str)

    return (
        'The following workbook schema summary comes directly from describe_tabular_file tool executions. '
        'Use it to answer workbook-structure questions about worksheets, columns, and likely relationships.\n\n'
        f'WORKBOOK_SCHEMA_RESULTS:\n{rendered_schema}'
    )


def get_tabular_invocation_selected_sheets(invocations):
    """Return unique selected-sheet names for a group of tabular invocations."""
    selected_sheets = []
    seen_sheet_names = set()

    for invocation in invocations or []:
        selected_sheet = get_tabular_invocation_selected_sheet(invocation)
        if not selected_sheet:
            continue

        lowered_sheet_name = selected_sheet.lower()
        if lowered_sheet_name in seen_sheet_names:
            continue

        seen_sheet_names.add(lowered_sheet_name)
        selected_sheets.append(selected_sheet)

    return selected_sheets


def get_tabular_retry_sheet_overrides(invocations):
    """Choose workbook sheet overrides for the next retry based on failed tool payloads."""
    candidate_scores_by_filename = {}
    candidate_details_by_filename = {}

    for invocation in invocations or []:
        function_name = getattr(invocation, 'function_name', '')
        if function_name not in get_tabular_analysis_function_names():
            continue

        result_payload = get_tabular_invocation_result_payload(invocation) or {}
        invocation_parameters = getattr(invocation, 'parameters', {}) or {}
        filename = str(
            result_payload.get('filename')
            or invocation_parameters.get('filename')
            or ''
        ).strip()
        if not filename:
            continue

        candidate_sheets = get_tabular_invocation_candidate_sheets(invocation)
        if not candidate_sheets:
            continue

        selected_sheet = str(result_payload.get('selected_sheet') or '').strip().lower()
        missing_column = str(result_payload.get('missing_column') or '').strip()

        filename_scores = candidate_scores_by_filename.setdefault(filename, {})
        filename_details = candidate_details_by_filename.setdefault(filename, [])
        candidate_count = len(candidate_sheets)

        for candidate_index, candidate_sheet in enumerate(candidate_sheets):
            if selected_sheet and candidate_sheet.lower() == selected_sheet:
                continue

            score = max(1, candidate_count - candidate_index)
            filename_scores[candidate_sheet] = filename_scores.get(candidate_sheet, 0) + score

        if missing_column:
            filename_details.append(f"missing column '{missing_column}'")

    retry_sheet_overrides = {}
    for filename, filename_scores in candidate_scores_by_filename.items():
        if not filename_scores:
            continue

        selected_sheet_name = sorted(
            filename_scores.items(),
            key=lambda item: (-item[1], item[0].lower())
        )[0][0]
        detail_messages = candidate_details_by_filename.get(filename, [])
        detail_text = ', '.join(detail_messages[:3]) if detail_messages else None
        retry_sheet_overrides[filename] = {
            'sheet_name': selected_sheet_name,
            'detail': detail_text,
        }

    return retry_sheet_overrides


def split_tabular_analysis_invocations(invocations):
    """Split analytical tabular invocations into successful and failed calls."""
    successful_invocations = []
    failed_invocations = []

    for invocation in invocations or []:
        function_name = getattr(invocation, 'function_name', '')
        if function_name not in get_tabular_analysis_function_names():
            continue

        if get_tabular_invocation_error_message(invocation):
            failed_invocations.append(invocation)
        else:
            successful_invocations.append(invocation)

    return successful_invocations, failed_invocations


def summarize_tabular_invocation_errors(invocations):
    """Return a stable list of unique tabular tool error messages."""
    unique_errors = []
    seen_errors = set()

    for invocation in invocations or []:
        error_message = get_tabular_invocation_error_message(invocation)
        if not error_message:
            continue

        normalized_error_message = error_message.strip()
        if not normalized_error_message or normalized_error_message in seen_errors:
            continue

        seen_errors.add(normalized_error_message)
        unique_errors.append(normalized_error_message)

    return unique_errors


def summarize_tabular_discovery_invocations(invocations, max_sheet_names=6):
    """Return compact workbook-discovery summaries for retry prompts."""
    discovery_summaries = []

    for invocation in invocations or []:
        if getattr(invocation, 'function_name', '') != 'describe_tabular_file':
            continue
        if get_tabular_invocation_error_message(invocation):
            continue

        result_payload = get_tabular_invocation_result_payload(invocation) or {}
        filename = str(result_payload.get('filename') or '').strip()
        if not filename:
            continue

        sheet_names = result_payload.get('sheet_names') or []
        if not isinstance(sheet_names, list):
            sheet_names = []

        relationship_hints = result_payload.get('relationship_hints') or []
        if not isinstance(relationship_hints, list):
            relationship_hints = []

        summary_parts = [filename]
        if result_payload.get('is_workbook'):
            summary_parts.append(f"sheet_count={result_payload.get('sheet_count', len(sheet_names))}")
        if sheet_names:
            rendered_sheet_names = ', '.join(str(sheet_name) for sheet_name in sheet_names[:max_sheet_names])
            if len(sheet_names) > max_sheet_names:
                rendered_sheet_names += f", +{len(sheet_names) - max_sheet_names} more"
            summary_parts.append(f"sheets={rendered_sheet_names}")
        if relationship_hints:
            summary_parts.append(f"relationship_hints={len(relationship_hints)}")

        discovery_summaries.append('; '.join(summary_parts))

    return discovery_summaries


def extract_json_object_from_text(text):
    """Extract the first JSON object embedded in a model response."""
    rendered_text = str(text or '').strip()
    if not rendered_text:
        return None

    json_decoder = json.JSONDecoder()
    for character_index, character in enumerate(rendered_text):
        if character != '{':
            continue

        try:
            payload, _ = json_decoder.raw_decode(rendered_text[character_index:])
        except Exception:
            continue

        if isinstance(payload, dict):
            return payload

    return None


def normalize_tabular_reviewer_function_name(function_name):
    """Normalize reviewer-selected function names to bare plugin function names."""
    normalized_function_name = str(function_name or '').strip()
    if not normalized_function_name:
        return ''

    normalized_function_name = normalized_function_name.replace('tabular_processing-', '')
    if '.' in normalized_function_name:
        normalized_function_name = normalized_function_name.split('.')[-1]

    return normalized_function_name.strip()


def parse_tabular_reviewer_plan(analysis_text):
    """Parse a JSON-only LLM reviewer plan into executable call descriptors."""
    payload = extract_json_object_from_text(analysis_text)
    if not isinstance(payload, dict):
        return []

    raw_calls = payload.get('calls')
    if not isinstance(raw_calls, list):
        raw_call = payload.get('call')
        raw_calls = [raw_call] if isinstance(raw_call, dict) else []

    normalized_calls = []
    for raw_call in raw_calls:
        if not isinstance(raw_call, dict):
            continue

        function_name = normalize_tabular_reviewer_function_name(
            raw_call.get('function') or raw_call.get('function_name')
        )
        arguments = raw_call.get('arguments') or raw_call.get('args') or {}
        if not function_name or not isinstance(arguments, dict):
            continue

        normalized_calls.append({
            'function_name': function_name,
            'arguments': dict(arguments),
        })

    return normalized_calls


def get_tabular_reviewer_function_manifest():
    """Return compact analytical-function guidance for the reviewer LLM."""
    return {
        'lookup_value': {
            'best_for': 'one exact row or entity and one target column value',
            'required_arguments': ['filename', 'lookup_column', 'lookup_value', 'target_column'],
            'optional_arguments': ['match_operator', 'normalize_match', 'sheet_name', 'sheet_index', 'max_rows'],
        },
        'get_distinct_values': {
            'best_for': 'unique values, discrete counts, canonical site lists, embedded URL or regex extraction, and deterministic de-duplication after the relevant text cohort has been narrowed',
            'required_arguments': ['filename', 'column'],
            'optional_arguments': ['query_expression', 'filter_column', 'filter_operator', 'filter_value', 'additional_filter_column', 'additional_filter_operator', 'additional_filter_value', 'extract_mode', 'extract_pattern', 'url_path_segments', 'normalize_match', 'sheet_name', 'sheet_index', 'max_values'],
        },
        'count_rows': {
            'best_for': 'deterministic how-many questions after a filter or query',
            'required_arguments': ['filename'],
            'optional_arguments': ['query_expression', 'filter_column', 'filter_operator', 'filter_value', 'additional_filter_column', 'additional_filter_operator', 'additional_filter_value', 'normalize_match', 'sheet_name', 'sheet_index'],
        },
        'search_rows': {
            'best_for': 'searching one column, several columns, or an entire sheet/workbook for a topic, phrase, path, code, or other value when the relevant column is unclear',
            'required_arguments': ['filename', 'search_value'],
            'optional_arguments': ['search_columns', 'search_operator', 'return_columns', 'query_expression', 'filter_column', 'filter_operator', 'filter_value', 'additional_filter_column', 'additional_filter_operator', 'additional_filter_value', 'normalize_match', 'sheet_name', 'sheet_index', 'max_rows'],
        },
        'filter_rows': {
            'best_for': 'searching a text column for matching cells while preserving full row context before a second analytical step',
            'required_arguments': ['filename', 'column', 'operator', 'value'],
            'optional_arguments': ['additional_filter_column', 'additional_filter_operator', 'additional_filter_value', 'normalize_match', 'sheet_name', 'sheet_index', 'max_rows'],
        },
        'query_tabular_data': {
            'best_for': 'compound boolean filters expressed with pandas DataFrame.query()',
            'required_arguments': ['filename', 'query_expression'],
            'optional_arguments': ['sheet_name', 'sheet_index', 'max_rows'],
        },
        'filter_rows_by_related_values': {
            'best_for': 'joining a cohort from one sheet to matching rows on another sheet',
            'required_arguments': ['filename', 'source_sheet_name', 'source_value_column', 'target_sheet_name', 'target_match_column'],
            'optional_arguments': ['source_query_expression', 'source_filter_column', 'source_filter_operator', 'source_filter_value', 'target_query_expression', 'target_filter_column', 'target_filter_operator', 'target_filter_value', 'normalize_match', 'max_rows'],
        },
        'count_rows_by_related_values': {
            'best_for': 'deterministic counts for cross-sheet cohort membership or related-record questions',
            'required_arguments': ['filename', 'source_sheet_name', 'source_value_column', 'target_sheet_name', 'target_match_column'],
            'optional_arguments': ['source_query_expression', 'source_filter_column', 'source_filter_operator', 'source_filter_value', 'target_query_expression', 'target_filter_column', 'target_filter_operator', 'target_filter_value', 'normalize_match'],
        },
        'aggregate_column': {
            'best_for': 'sum, mean, min, max, median, std, count, nunique, or value_counts on one column',
            'required_arguments': ['filename', 'column', 'operation'],
            'optional_arguments': ['sheet_name', 'sheet_index'],
        },
        'group_by_aggregate': {
            'best_for': 'grouped metrics by category or entity',
            'required_arguments': ['filename', 'group_by', 'aggregate_column', 'operation'],
            'optional_arguments': ['query_expression', 'sheet_name', 'sheet_index', 'top_n'],
        },
        'group_by_datetime_component': {
            'best_for': 'time-based grouped analysis by year, quarter, month, week, day, or hour',
            'required_arguments': ['filename', 'datetime_column', 'date_component', 'aggregate_column', 'operation'],
            'optional_arguments': ['query_expression', 'sheet_name', 'sheet_index', 'top_n'],
        },
    }


def resolve_tabular_reviewer_call_arguments(raw_arguments, analysis_file_contexts,
                                            fallback_source_hint='workspace',
                                            fallback_group_id=None,
                                            fallback_public_workspace_id=None):
    """Inject filename and source context into an LLM reviewer tool plan."""
    raw_arguments = dict(raw_arguments or {})
    normalized_contexts = analysis_file_contexts or []
    file_context_by_exact_name = {
        file_context['file_name']: file_context
        for file_context in normalized_contexts
        if file_context.get('file_name')
    }
    file_context_by_lower_name = {
        str(file_context.get('file_name') or '').strip().lower(): file_context
        for file_context in normalized_contexts
        if file_context.get('file_name')
    }

    requested_filename = str(raw_arguments.get('filename') or '').strip()
    resolved_file_context = None
    if requested_filename:
        resolved_file_context = (
            file_context_by_exact_name.get(requested_filename)
            or file_context_by_lower_name.get(requested_filename.lower())
        )
    elif len(normalized_contexts) == 1:
        resolved_file_context = normalized_contexts[0]

    if not resolved_file_context:
        if requested_filename:
            return None, f"Reviewer selected unknown filename '{requested_filename}'."
        return None, 'Reviewer did not select a filename and multiple files were available.'

    normalized_arguments = dict(raw_arguments)
    normalized_arguments['filename'] = resolved_file_context['file_name']
    normalized_arguments['source'] = (
        resolved_file_context.get('source_hint')
        or fallback_source_hint
        or normalized_arguments.get('source')
        or 'workspace'
    )

    resolved_group_id = resolved_file_context.get('group_id') or fallback_group_id
    resolved_public_workspace_id = (
        resolved_file_context.get('public_workspace_id')
        or fallback_public_workspace_id
    )
    if resolved_group_id:
        normalized_arguments['group_id'] = resolved_group_id
    if resolved_public_workspace_id:
        normalized_arguments['public_workspace_id'] = resolved_public_workspace_id

    if not str(normalized_arguments.get('sheet_name') or '').strip():
        normalized_arguments.pop('sheet_name', None)
    if normalized_arguments.get('sheet_index') in ('', None):
        normalized_arguments.pop('sheet_index', None)

    return normalized_arguments, None


def normalize_tabular_reviewer_argument_value(argument_name, argument_value):
    """Normalize scalar reviewer-planned values to plugin-friendly argument types."""
    if argument_value is None:
        return None

    if isinstance(argument_value, bool):
        return 'true' if argument_value else 'false'

    if argument_name in {'max_rows', 'max_values', 'sheet_index', 'top_n'} and isinstance(argument_value, (int, float)):
        return str(int(argument_value))

    return argument_value


def is_tabular_distinct_url_question(user_question):
    """Return True when the user is asking for unique or counted URL/site values."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().lower())
    if not normalized_question:
        return False

    count_keywords = (
        'count',
        'counts',
        'how many',
        'number of',
        'different',
        'discrete',
        'distinct',
        'unique',
    )
    url_keywords = (
        'http',
        'https',
        'link',
        'links',
        'sharepoint',
        'site',
        'sites',
        'url',
        'urls',
    )
    return any(keyword in normalized_question for keyword in count_keywords) and any(
        keyword in normalized_question for keyword in url_keywords
    )


def question_requests_tabular_row_context(user_question):
    """Return True when the user question implies a need for matching-row context."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().lower())
    if not normalized_question:
        return False

    row_context_keywords = (
        'appear',
        'appears',
        'appearing',
        'find',
        'found',
        'search',
        'show',
        'where',
    )
    return any(keyword in normalized_question for keyword in row_context_keywords)


def question_requests_tabular_exhaustive_results(user_question):
    """Return True when the user explicitly asks for a full list or all matching results."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().lower())
    if not normalized_question:
        return False

    explicit_phrases = (
        'all results',
        'all rows',
        'all values',
        'all of them',
        'complete list',
        'each one',
        'every one',
        'exhaustive',
        'full list',
        'list all',
        'list each',
        'list every',
        'list them all',
        'list them out',
        'return all',
        'show all',
        'show me all',
    )
    if any(phrase in normalized_question for phrase in explicit_phrases):
        return True

    structured_row_patterns = (
        r'\bone object per comment row\b',
        r'\bone object per (?:comment|submission)\b',
        r'\bone object per (?:comment|submission|input )?row\b',
        r'\bone row per (?:comment|submission|input )?row\b',
        r'\bone row per (?:comment|submission)\b',
        r'\bone object for each row\b',
    )
    structured_output_markers = (
        'json array',
        'valid json',
        'return only json',
        'return only valid json',
        'csv file',
        'download csv',
        'save csv',
        'make a csv',
        'create a csv',
        'turn that into a table',
        'turn these into a table',
        'turn this into a table',
        'turn it into a table',
        'convert that to a table',
        'convert these to a table',
        'convert this to a table',
        'convert it to a table',
        'format that as a table',
        'format these as a table',
        'format this as a table',
        'format it as a table',
        'put that into a table',
        'put these into a table',
        'put that in a table',
        'put these in a table',
        'put this into a table',
        'put it into a table',
        'put this in a table',
        'put it in a table',
        'make that a table',
        'make these a table',
        'make this a table',
        'make it a table',
        'make a table',
        'table for me',
        'in table format',
        'download table',
        'spreadsheet',
        'table file',
        'each object must contain',
        'each row must contain',
        'exactly these fields',
        'exactly these columns',
        'these columns',
    )
    if any(re.search(pattern, normalized_question) for pattern in structured_row_patterns) and any(
        marker in normalized_question for marker in structured_output_markers
    ):
        return True

    return (
        'list' in normalized_question
        and any(token in normalized_question for token in (' all ', ' them', ' out', ' each ', ' every '))
    )


def parse_tabular_result_count(value):
    """Parse a numeric count from invocation metadata or payloads."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return None

    return parsed_value if parsed_value >= 0 else None


def determine_tabular_follow_up_limit(total_available, returned_count, max_cap=200):
    """Return a larger result limit when the current tool call returned only a partial slice."""
    total_count = parse_tabular_result_count(total_available)
    current_count = parse_tabular_result_count(returned_count)
    if total_count is None or current_count is None or total_count <= current_count:
        return None

    target_count = min(total_count, max_cap)
    if target_count <= current_count:
        return None

    return str(target_count)


def extract_tabular_high_signal_search_terms(user_question, max_terms=2):
    """Extract a short list of likely literal search terms from the user question."""
    question_text = str(user_question or '').strip()
    if not question_text:
        return []

    normalized_question = re.sub(r'\s+', ' ', question_text)
    lowercase_question = normalized_question.lower()
    prioritized_terms = []
    seen_terms = set()

    def add_term(raw_term):
        rendered_term = str(raw_term or '').strip()
        if not rendered_term:
            return

        normalized_term = rendered_term.casefold()
        if normalized_term in seen_terms:
            return

        seen_terms.add(normalized_term)
        prioritized_terms.append(rendered_term)

    for quoted_term in re.findall(r'["\']([^"\']{2,80})["\']', normalized_question):
        add_term(quoted_term)

    special_terms = (
        ('sharepoint', 'SharePoint'),
        ('onedrive', 'OneDrive'),
        ('teams', 'Teams'),
        ('ccore', 'CCORe'),
        ('o365', 'O365'),
    )
    for token, rendered_term in special_terms:
        if token in lowercase_question:
            add_term(rendered_term)

    ignored_tokens = {
        'all',
        'and',
        'appear',
        'appears',
        'are',
        'cell',
        'cells',
        'column',
        'columns',
        'count',
        'counts',
        'discrete',
        'distinct',
        'document',
        'documents',
        'does',
        'every',
        'file',
        'for',
        'from',
        'get',
        'how',
        'in',
        'is',
        'it',
        'link',
        'links',
        'location',
        'locations',
        'many',
        'number',
        'of',
        'on',
        'or',
        'out',
        'please',
        'reason',
        'row',
        'rows',
        'search',
        'sheet',
        'sheets',
        'show',
        'site',
        'sites',
        'that',
        'the',
        'them',
        'these',
        'they',
        'this',
        'to',
        'topic',
        'unique',
        'url',
        'urls',
        'value',
        'values',
        'what',
        'where',
        'which',
        'word',
        'workbook',
        'list',
        'listed',
        'lists',
        'lsit',
    }

    for raw_token in re.findall(r'[A-Za-z0-9][A-Za-z0-9._\-/]{2,}', normalized_question):
        lowercase_token = raw_token.casefold()
        if lowercase_token in ignored_tokens:
            continue
        add_term(raw_token)
        if len(prioritized_terms) >= max_terms:
            break

    return prioritized_terms[:max_terms]


def extract_tabular_secondary_filter_terms(user_question, primary_terms=None, max_terms=3):
    """Return likely cohort/filter terms after excluding the primary topic terms."""
    excluded_terms = {
        str(term or '').strip().casefold()
        for term in (primary_terms or [])
        if str(term or '').strip()
    }
    secondary_terms = []

    for candidate_term in extract_tabular_high_signal_search_terms(
        user_question,
        max_terms=max_terms + len(excluded_terms) + 3,
    ):
        normalized_candidate_term = str(candidate_term or '').strip().casefold()
        if not normalized_candidate_term or normalized_candidate_term in excluded_terms:
            continue

        secondary_terms.append(candidate_term)
        if len(secondary_terms) >= max_terms:
            break

    return secondary_terms


def normalize_tabular_row_text(value):
    """Normalize a row cell value for lightweight controller-side term matching."""
    if value is None:
        return ''

    return re.sub(r'\s+', ' ', str(value).casefold()).strip()


def parse_tabular_column_candidates(raw_columns):
    """Normalize column arguments from string or list form into a stable list."""
    if isinstance(raw_columns, list):
        candidate_columns = raw_columns
    elif isinstance(raw_columns, str):
        candidate_columns = raw_columns.split(',')
    else:
        return []

    normalized_columns = []
    seen_columns = set()
    for candidate_column in candidate_columns:
        normalized_column = str(candidate_column or '').strip()
        if not normalized_column:
            continue

        lowered_column = normalized_column.casefold()
        if lowered_column in seen_columns:
            continue

        seen_columns.add(lowered_column)
        normalized_columns.append(normalized_column)

    return normalized_columns


def tabular_value_looks_url_like(value):
    """Return True when a scalar cell value looks like a URL or site path."""
    rendered_value = normalize_tabular_row_text(value)
    if not rendered_value:
        return False

    return (
        'http://' in rendered_value
        or 'https://' in rendered_value
        or 'sharepoint.com' in rendered_value
        or '/sites/' in rendered_value
    )


def tabular_result_payload_contains_url_like_content(result_payload):
    """Return True when a result payload contains URL-like strings."""
    if not isinstance(result_payload, dict):
        return False

    candidate_values = []
    raw_values = result_payload.get('values')
    if isinstance(raw_values, list):
        candidate_values.extend(raw_values[:20])

    raw_rows = result_payload.get('data')
    if isinstance(raw_rows, list):
        for raw_row in raw_rows[:10]:
            if not isinstance(raw_row, dict):
                continue
            candidate_values.extend(raw_row.values())

    for candidate_value in candidate_values:
        rendered_candidate = str(candidate_value or '').strip().lower()
        if not rendered_candidate:
            continue
        if (
            'http://' in rendered_candidate
            or 'https://' in rendered_candidate
            or 'sharepoint.com' in rendered_candidate
            or '/sites/' in rendered_candidate
        ):
            return True

    return False


def infer_tabular_url_value_column_from_rows(rows, preferred_columns=None):
    """Infer which returned row column contains URL-like values."""
    preferred_columns = parse_tabular_column_candidates(preferred_columns)
    for preferred_column in preferred_columns:
        if any(
            isinstance(row, dict) and tabular_value_looks_url_like(row.get(preferred_column))
            for row in (rows or [])
        ):
            return preferred_column

    column_scores = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue

        for column_name, cell_value in row.items():
            normalized_column_name = str(column_name or '').strip()
            if not normalized_column_name or normalized_column_name.startswith('_'):
                continue
            if not tabular_value_looks_url_like(cell_value):
                continue

            column_scores[normalized_column_name] = column_scores.get(normalized_column_name, 0) + 1

    if not column_scores:
        return None

    return sorted(
        column_scores.items(),
        key=lambda item: (-item[1], item[0].casefold()),
    )[0][0]


def infer_tabular_secondary_filter_from_rows(rows, filter_terms, excluded_columns=None):
    """Infer a likely cohort column/term pair from returned row context."""
    normalized_excluded_columns = {
        str(column_name or '').strip().casefold()
        for column_name in (excluded_columns or [])
        if str(column_name or '').strip()
    }
    normalized_filter_terms = [
        str(filter_term or '').strip()
        for filter_term in (filter_terms or [])
        if str(filter_term or '').strip()
    ]
    if not normalized_filter_terms:
        return None

    candidate_scores = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue

        for column_name, cell_value in row.items():
            normalized_column_name = str(column_name or '').strip()
            if not normalized_column_name or normalized_column_name.startswith('_'):
                continue
            if normalized_column_name.casefold() in normalized_excluded_columns:
                continue

            rendered_cell_value = normalize_tabular_row_text(cell_value)
            if not rendered_cell_value:
                continue

            for filter_term in normalized_filter_terms:
                if str(filter_term).casefold() not in rendered_cell_value:
                    continue

                score_key = (normalized_column_name, filter_term)
                candidate_scores[score_key] = candidate_scores.get(score_key, 0) + 1

    if not candidate_scores:
        return None

    (selected_column, selected_term), match_count = sorted(
        candidate_scores.items(),
        key=lambda item: (-item[1], item[0][0].casefold(), item[0][1].casefold()),
    )[0]
    return {
        'column': selected_column,
        'term': selected_term,
        'match_count': match_count,
    }


def infer_tabular_url_path_segments(user_question):
    """Infer URL path truncation when the user is asking about site roots."""
    normalized_question = re.sub(r'\s+', ' ', str(user_question or '').strip().lower())
    if not normalized_question:
        return None

    if 'site' in normalized_question or 'sites' in normalized_question or 'sharepoint' in normalized_question:
        return '2'

    return None


def build_tabular_follow_up_call_signature(function_name, arguments):
    """Return a stable signature for a follow-up tool call."""
    normalized_arguments = {}
    for argument_name, argument_value in (arguments or {}).items():
        if argument_value in (None, ''):
            continue
        normalized_arguments[str(argument_name)] = argument_value

    return f"{function_name}:{json.dumps(normalized_arguments, sort_keys=True, default=str)}"


def derive_tabular_follow_up_calls_from_invocations(user_question, invocations):
    """Derive targeted follow-up calls when initial analytical results are only intermediate."""
    successful_invocations = [
        invocation for invocation in (invocations or [])
        if not get_tabular_invocation_error_message(invocation)
    ]
    if not successful_invocations:
        return []

    wants_distinct_urls = is_tabular_distinct_url_question(user_question)
    wants_exhaustive_results = question_requests_tabular_exhaustive_results(user_question)
    wants_row_context = question_requests_tabular_row_context(user_question)
    search_terms = extract_tabular_high_signal_search_terms(user_question, max_terms=4)
    primary_search_term = search_terms[0] if search_terms else None
    secondary_filter_terms = extract_tabular_secondary_filter_terms(
        user_question,
        primary_terms=[primary_search_term] if primary_search_term else None,
        max_terms=3,
    )
    has_row_context_tool = any(
        getattr(invocation, 'function_name', '') in {'search_rows', 'filter_rows', 'query_tabular_data'}
        for invocation in successful_invocations
    )
    has_url_extraction_tool = any(
        getattr(invocation, 'function_name', '') == 'get_distinct_values'
        and str(
            ((getattr(invocation, 'parameters', {}) or {}).get('extract_mode'))
            or ((get_tabular_invocation_result_payload(invocation) or {}).get('extract_mode'))
            or ''
        ).strip().lower() == 'url'
        for invocation in successful_invocations
    )

    existing_signatures = {
        build_tabular_follow_up_call_signature(
            getattr(invocation, 'function_name', ''),
            getattr(invocation, 'parameters', {}) or {},
        )
        for invocation in successful_invocations
    }
    follow_up_calls = []

    for invocation in successful_invocations:
        function_name = getattr(invocation, 'function_name', '')
        invocation_parameters = getattr(invocation, 'parameters', {}) or {}
        result_payload = get_tabular_invocation_result_payload(invocation) or {}
        filename = str(invocation_parameters.get('filename') or result_payload.get('filename') or '').strip()
        if not filename:
            continue

        scope_arguments = {
            'filename': filename,
            'source': invocation_parameters.get('source') or 'workspace',
        }
        if invocation_parameters.get('group_id'):
            scope_arguments['group_id'] = invocation_parameters.get('group_id')
        if invocation_parameters.get('public_workspace_id'):
            scope_arguments['public_workspace_id'] = invocation_parameters.get('public_workspace_id')

        selected_sheet = get_tabular_invocation_selected_sheet(invocation)
        if selected_sheet and 'cross-sheet' not in selected_sheet.lower():
            scope_arguments['sheet_name'] = selected_sheet
        elif invocation_parameters.get('sheet_name'):
            scope_arguments['sheet_name'] = invocation_parameters.get('sheet_name')
        elif invocation_parameters.get('sheet_index') not in (None, ''):
            scope_arguments['sheet_index'] = invocation_parameters.get('sheet_index')

        if wants_exhaustive_results and function_name in {'search_rows', 'filter_rows', 'query_tabular_data'}:
            expanded_row_limit = determine_tabular_follow_up_limit(
                result_payload.get('total_matches'),
                result_payload.get('returned_rows'),
            )
            if expanded_row_limit:
                expanded_arguments = {
                    argument_name: argument_value
                    for argument_name, argument_value in invocation_parameters.items()
                    if argument_name not in {'user_id', 'conversation_id'} and argument_value not in (None, '')
                }
                expanded_arguments.update(scope_arguments)
                expanded_arguments['max_rows'] = expanded_row_limit

                expanded_signature = build_tabular_follow_up_call_signature(function_name, expanded_arguments)
                if expanded_signature not in existing_signatures:
                    follow_up_calls.append({
                        'function_name': function_name,
                        'arguments': expanded_arguments,
                        'reason': 'expand the matching row slice because the user asked for the full result list',
                    })
                    existing_signatures.add(expanded_signature)

        if function_name == 'get_distinct_values':
            target_column = str(invocation_parameters.get('column') or result_payload.get('column') or '').strip()
            if not target_column:
                continue

            current_filter_columns = [
                str(invocation_parameters.get('filter_column') or '').strip(),
                str(invocation_parameters.get('additional_filter_column') or '').strip(),
            ]
            same_column_filter = any(
                filter_column.casefold() == target_column.casefold()
                for filter_column in current_filter_columns
                if filter_column
            )
            distinct_count = parse_tabular_result_count(result_payload.get('distinct_count'))
            returned_values = parse_tabular_result_count(result_payload.get('returned_values'))

            if wants_exhaustive_results:
                expanded_value_limit = determine_tabular_follow_up_limit(distinct_count, returned_values)
                if expanded_value_limit:
                    expanded_arguments = {
                        argument_name: argument_value
                        for argument_name, argument_value in invocation_parameters.items()
                        if argument_name not in {'user_id', 'conversation_id'} and argument_value not in (None, '')
                    }
                    expanded_arguments.update(scope_arguments)
                    expanded_arguments['max_values'] = expanded_value_limit

                    expanded_signature = build_tabular_follow_up_call_signature('get_distinct_values', expanded_arguments)
                    if expanded_signature not in existing_signatures:
                        follow_up_calls.append({
                            'function_name': 'get_distinct_values',
                            'arguments': expanded_arguments,
                            'reason': 'expand the returned value list because the user asked for the full result set',
                        })
                        existing_signatures.add(expanded_signature)

            needs_broad_row_context = bool(
                wants_row_context
                and primary_search_term
                and not has_row_context_tool
                and same_column_filter
                and secondary_filter_terms
                and distinct_count == 0
            )

            if wants_row_context and primary_search_term and not has_row_context_tool:
                row_search_arguments = dict(scope_arguments)
                row_search_arguments['search_value'] = primary_search_term
                row_search_arguments['search_columns'] = target_column

                normalize_match_value = invocation_parameters.get('normalize_match')
                if normalize_match_value not in (None, ''):
                    row_search_arguments['normalize_match'] = normalize_match_value

                if not needs_broad_row_context:
                    for argument_name in (
                        'query_expression',
                        'filter_column',
                        'filter_operator',
                        'filter_value',
                        'additional_filter_column',
                        'additional_filter_operator',
                        'additional_filter_value',
                    ):
                        argument_value = invocation_parameters.get(argument_name)
                        if argument_value in (None, ''):
                            continue
                        row_search_arguments[argument_name] = argument_value

                    return_columns = []
                    for candidate_column in (
                        invocation_parameters.get('filter_column'),
                        invocation_parameters.get('additional_filter_column'),
                        target_column,
                    ):
                        normalized_column = str(candidate_column or '').strip()
                        if not normalized_column or normalized_column in return_columns:
                            continue
                        return_columns.append(normalized_column)

                    if return_columns:
                        row_search_arguments['return_columns'] = ','.join(return_columns)

                row_search_arguments['max_rows'] = '50' if needs_broad_row_context else '25'

                row_search_signature = build_tabular_follow_up_call_signature('search_rows', row_search_arguments)
                if row_search_signature not in existing_signatures:
                    follow_up_calls.append({
                        'function_name': 'search_rows',
                        'arguments': row_search_arguments,
                        'reason': (
                            'collect broad row context for the literal topic before inferring a cohort column'
                            if needs_broad_row_context else
                            'collect matching row context for the literal topic before final reasoning'
                        ),
                    })
                    existing_signatures.add(row_search_signature)
                    has_row_context_tool = True

            if wants_distinct_urls and not str(invocation_parameters.get('extract_mode') or '').strip() and not has_url_extraction_tool:
                if needs_broad_row_context:
                    continue
                if not tabular_result_payload_contains_url_like_content(result_payload):
                    continue

                extraction_arguments = dict(scope_arguments)
                extraction_arguments['column'] = target_column
                for argument_name in (
                    'query_expression',
                    'filter_column',
                    'filter_operator',
                    'filter_value',
                    'additional_filter_column',
                    'additional_filter_operator',
                    'additional_filter_value',
                    'normalize_match',
                    'max_values',
                ):
                    argument_value = invocation_parameters.get(argument_name)
                    if argument_value in (None, ''):
                        continue
                    extraction_arguments[argument_name] = argument_value

                extraction_arguments['extract_mode'] = 'url'
                inferred_path_segments = infer_tabular_url_path_segments(user_question)
                if inferred_path_segments:
                    extraction_arguments['url_path_segments'] = inferred_path_segments

                extraction_signature = build_tabular_follow_up_call_signature('get_distinct_values', extraction_arguments)
                if extraction_signature not in existing_signatures:
                    follow_up_calls.append({
                        'function_name': 'get_distinct_values',
                        'arguments': extraction_arguments,
                        'reason': 'extract canonical URL or site values from composite text cells',
                    })
                    existing_signatures.add(extraction_signature)
                    has_url_extraction_tool = True

        if function_name == 'search_rows' and wants_distinct_urls and not has_url_extraction_tool:
            search_rows_result_rows = get_tabular_invocation_data_rows(invocation)
            if not search_rows_result_rows:
                continue

            target_column = None
            searched_columns = parse_tabular_column_candidates(
                result_payload.get('searched_columns') or invocation_parameters.get('search_columns')
            )
            if len(searched_columns) == 1:
                target_column = searched_columns[0]
            else:
                target_column = infer_tabular_url_value_column_from_rows(
                    search_rows_result_rows,
                    preferred_columns=searched_columns,
                )

            if not target_column:
                continue

            extraction_arguments = dict(scope_arguments)
            extraction_arguments['column'] = target_column

            inferred_filter = infer_tabular_secondary_filter_from_rows(
                search_rows_result_rows,
                secondary_filter_terms,
                excluded_columns=[target_column],
            )
            if inferred_filter:
                extraction_arguments['filter_column'] = inferred_filter['column']
                extraction_arguments['filter_operator'] = 'contains'
                extraction_arguments['filter_value'] = inferred_filter['term']
            elif not secondary_filter_terms:
                for argument_name in (
                    'query_expression',
                    'filter_column',
                    'filter_operator',
                    'filter_value',
                    'additional_filter_column',
                    'additional_filter_operator',
                    'additional_filter_value',
                ):
                    argument_value = invocation_parameters.get(argument_name)
                    if argument_value in (None, ''):
                        continue
                    extraction_arguments[argument_name] = argument_value
            else:
                continue

            normalize_match_value = invocation_parameters.get('normalize_match')
            if normalize_match_value not in (None, ''):
                extraction_arguments['normalize_match'] = normalize_match_value

            extraction_arguments['extract_mode'] = 'url'
            inferred_path_segments = infer_tabular_url_path_segments(user_question)
            if inferred_path_segments:
                extraction_arguments['url_path_segments'] = inferred_path_segments

            expanded_value_limit = None
            if wants_exhaustive_results:
                expanded_value_limit = determine_tabular_follow_up_limit(
                    result_payload.get('total_matches'),
                    result_payload.get('returned_rows'),
                )
            if expanded_value_limit:
                extraction_arguments['max_values'] = expanded_value_limit
            elif invocation_parameters.get('max_rows') not in (None, ''):
                extraction_arguments['max_values'] = invocation_parameters.get('max_rows')

            extraction_signature = build_tabular_follow_up_call_signature('get_distinct_values', extraction_arguments)
            if extraction_signature not in existing_signatures:
                follow_up_calls.append({
                    'function_name': 'get_distinct_values',
                    'arguments': extraction_arguments,
                    'reason': 'extract canonical URL or site values after inferring the cohort column from matching rows',
                })
                existing_signatures.add(extraction_signature)
                has_url_extraction_tool = True

        if len(follow_up_calls) >= 2:
            break

    return follow_up_calls[:2]


async def maybe_recover_tabular_analysis_with_llm_reviewer(chat_service, kernel,
                                                           tabular_plugin, plugin_logger,
                                                           user_question, schema_context,
                                                           source_context,
                                                           analysis_file_contexts,
                                                           user_id, conversation_id,
                                                           execution_mode,
                                                           allowed_function_names,
                                                           workbook_sheet_hints=None,
                                                           workbook_related_sheet_hints=None,
                                                           workbook_cross_sheet_bridge_hints=None,
                                                           tool_error_messages=None,
                                                           execution_gap_messages=None,
                                                           discovery_feedback_messages=None,
                                                           fallback_source_hint='workspace',
                                                           fallback_group_id=None,
                                                           fallback_public_workspace_id=None):
    """Use an LLM reviewer to choose analytical tool calls when the main SK loop stalls."""
    reviewer_allowed_function_names = [
        function_name for function_name in (allowed_function_names or [])
        if function_name in get_tabular_analysis_function_names()
    ]
    if not reviewer_allowed_function_names:
        return None

    reviewer_manifest = {
        function_name: get_tabular_reviewer_function_manifest().get(function_name, {})
        for function_name in reviewer_allowed_function_names
    }

    reviewer_sections = [
        f"QUESTION:\n{user_question}",
        f"EXECUTION_MODE: {execution_mode}",
        f"SOURCE_CONTEXT:\n{source_context}",
        f"FILE_SCHEMAS:\n{schema_context}",
        "FUNCTION_MANIFEST:\n" + json.dumps(reviewer_manifest, indent=2, default=str),
    ]
    if discovery_feedback_messages:
        reviewer_sections.append(
            'WORKBOOK_DISCOVERY_RESULTS:\n' + json.dumps(discovery_feedback_messages, indent=2, default=str)
        )
    if tool_error_messages:
        reviewer_sections.append(
            'PREVIOUS_TOOL_ERRORS:\n' + json.dumps(tool_error_messages, indent=2, default=str)
        )
    if execution_gap_messages:
        reviewer_sections.append(
            'PREVIOUS_EXECUTION_GAPS:\n' + json.dumps(execution_gap_messages, indent=2, default=str)
        )
    if workbook_sheet_hints:
        reviewer_sections.append(
            'LIKELY_WORKSHEET_HINTS:\n' + json.dumps(workbook_sheet_hints, indent=2, default=str)
        )
    if workbook_related_sheet_hints:
        reviewer_sections.append(
            'QUESTION_RELEVANT_WORKSHEETS:\n' + json.dumps(workbook_related_sheet_hints, indent=2, default=str)
        )
    if workbook_cross_sheet_bridge_hints:
        reviewer_sections.append(
            'CROSS_SHEET_BRIDGE_HINTS:\n' + json.dumps(workbook_cross_sheet_bridge_hints, indent=2, default=str)
        )

    review_history = ChatHistory()
    review_history.add_system_message(
        "You are a tabular recovery planner. A previous workbook analysis came close but did not reach computed analytical results. "
        "Choose the next 1-3 analytical tabular calls that should be executed directly. "
        "Return JSON only with this schema: {\"reasoning_summary\": \"...\", \"calls\": [{\"function\": \"get_distinct_values\", \"arguments\": {...}}]}. "
        "Rules: Use only the listed analytical functions. Do not return describe_tabular_file. "
        "Prefer the smallest number of high-confidence calls needed to compute the answer. "
        "For deterministic how-many, discrete, unique, or canonical-list questions, prefer count_rows or get_distinct_values over sampled-row tools when possible. "
        "When the user is asking where a topic, phrase, code, path, identifier, or other value appears and the relevant column is unclear, prefer search_rows. Omit search_columns to search all columns, and use return_columns to surface the fields most relevant to the question. "
        "When the user wants values from a subset or pattern within one column, prefer get_distinct_values with filter_column/filter_operator/filter_value instead of an unfiltered full-column distinct-value call. "
        "When the answer depends on two literal column conditions, prefer count_rows, get_distinct_values, or filter_rows with filter_column/filter_operator/filter_value plus additional_filter_column/additional_filter_operator/additional_filter_value instead of a broad query_expression call. "
        "When the user is asking for URLs, sites, links, or regex-like identifiers embedded inside a text cell, prefer get_distinct_values with extract_mode='url' or extract_mode='regex' rather than counting whole-cell strings. Use url_path_segments when you need canonical higher-level URL roots. "
        "If whether an embedded URL or identifier counts depends on surrounding text in the original cell rather than the extracted value itself, search/filter the original text column first. Prefer filter_rows for that text search when the matching row context matters, and set max_rows high enough to return the full cohort when it is modest. If a prior tool result is limited and the user explicitly asked for the full list, rerun with a higher max_rows or max_values instead of stopping at the preview slice. "
        "Do not classify extracted URLs solely by whether the URL text itself contains the keyword when the original cell text already defines the category. "
        "For URLs, links, paths, and literal identifiers, set normalize_match=false unless normalization is clearly necessary. "
        "Prefer sheet_name when the correct worksheet is evident from the schemas or discovery results. "
        "Omit sheet_name only for a deliberate cross-sheet analytical search. "
        "Use filename exactly as listed in FILE_SCHEMAS. "
        "Do not include user_id or conversation_id in arguments. Do not wrap the JSON in markdown fences."
    )
    review_history.add_user_message("\n\n".join(reviewer_sections))

    reviewer_settings = AzureChatPromptExecutionSettings(service_id="tabular-analysis")

    try:
        reviewer_result = await chat_service.get_chat_message_contents(
            review_history,
            reviewer_settings,
            kernel=kernel,
        )
    except Exception as reviewer_error:
        log_event(
            f"[Tabular SK Analysis] Reviewer recovery call failed: {reviewer_error}",
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None

    reviewer_text = ''
    if reviewer_result and reviewer_result[0].content:
        reviewer_text = reviewer_result[0].content.strip()

    reviewer_calls = parse_tabular_reviewer_plan(reviewer_text)
    if not reviewer_calls:
        log_event(
            '[Tabular SK Analysis] Reviewer recovery did not return an executable analytical plan',
            extra={'reviewer_output_preview': reviewer_text[:500]},
            level=logging.WARNING,
        )
        return None

    baseline_invocation_count = len(plugin_logger.get_invocations_for_conversation(
        user_id,
        conversation_id,
        limit=1000,
    ))
    executed_function_names = []
    reviewer_plan_errors = []

    for reviewer_call in reviewer_calls[:3]:
        function_name = reviewer_call['function_name']
        if function_name not in reviewer_allowed_function_names:
            reviewer_plan_errors.append(
                f"Reviewer selected disallowed function '{function_name}'."
            )
            continue

        call_arguments, argument_error = resolve_tabular_reviewer_call_arguments(
            reviewer_call.get('arguments'),
            analysis_file_contexts,
            fallback_source_hint=fallback_source_hint,
            fallback_group_id=fallback_group_id,
            fallback_public_workspace_id=fallback_public_workspace_id,
        )
        if argument_error:
            reviewer_plan_errors.append(argument_error)
            continue

        plugin_function = getattr(tabular_plugin, function_name, None)
        if plugin_function is None:
            reviewer_plan_errors.append(
                f"Reviewer selected unavailable function '{function_name}'."
            )
            continue

        function_signature = inspect.signature(plugin_function)
        executable_arguments = {
            'user_id': user_id,
            'conversation_id': conversation_id,
        }
        for argument_name, argument_value in call_arguments.items():
            if argument_name not in function_signature.parameters:
                continue

            normalized_argument_value = normalize_tabular_reviewer_argument_value(
                argument_name,
                argument_value,
            )
            if normalized_argument_value is None:
                continue

            executable_arguments[argument_name] = normalized_argument_value

        try:
            await plugin_function(**executable_arguments)
            executed_function_names.append(function_name)
        except Exception as execution_error:
            reviewer_plan_errors.append(f"{function_name}: {execution_error}")

    invocations_after = plugin_logger.get_invocations_for_conversation(
        user_id,
        conversation_id,
        limit=1000,
    )
    reviewer_invocations = get_new_plugin_invocations(invocations_after, baseline_invocation_count)
    successful_analytical_invocations, failed_analytical_invocations = split_tabular_analysis_invocations(
        reviewer_invocations
    )
    for follow_up_round in range(2):
        follow_up_calls = derive_tabular_follow_up_calls_from_invocations(
            user_question,
            successful_analytical_invocations,
        )
        if not follow_up_calls:
            break

        auto_follow_up_names = []
        for follow_up_call in follow_up_calls:
            function_name = follow_up_call.get('function_name')
            if function_name not in reviewer_allowed_function_names:
                reviewer_plan_errors.append(
                    f"Auto follow-up selected disallowed function '{function_name}'."
                )
                continue

            plugin_function = getattr(tabular_plugin, function_name, None)
            if plugin_function is None:
                reviewer_plan_errors.append(
                    f"Auto follow-up selected unavailable function '{function_name}'."
                )
                continue

            function_signature = inspect.signature(plugin_function)
            executable_arguments = {
                'user_id': user_id,
                'conversation_id': conversation_id,
            }
            for argument_name, argument_value in (follow_up_call.get('arguments') or {}).items():
                if argument_name not in function_signature.parameters:
                    continue

                normalized_argument_value = normalize_tabular_reviewer_argument_value(
                    argument_name,
                    argument_value,
                )
                if normalized_argument_value is None:
                    continue

                executable_arguments[argument_name] = normalized_argument_value

            try:
                await plugin_function(**executable_arguments)
                auto_follow_up_names.append(function_name)
            except Exception as execution_error:
                reviewer_plan_errors.append(f"{function_name}: {execution_error}")

        if not auto_follow_up_names:
            break

        log_event(
            '[Tabular SK Analysis] Reviewer recovery executed automatic analytical follow-up calls',
            extra={
                'follow_up_functions': auto_follow_up_names,
                'initial_reviewer_functions': executed_function_names,
                'follow_up_round': follow_up_round + 1,
            },
            level=logging.INFO,
        )
        executed_function_names.extend(auto_follow_up_names)
        invocations_after = plugin_logger.get_invocations_for_conversation(
            user_id,
            conversation_id,
            limit=1000,
        )
        reviewer_invocations = get_new_plugin_invocations(invocations_after, baseline_invocation_count)
        successful_analytical_invocations, failed_analytical_invocations = split_tabular_analysis_invocations(
            reviewer_invocations
        )

    fallback = build_tabular_analysis_fallback_from_invocations(successful_analytical_invocations)
    failed_tool_error_messages = summarize_tabular_invocation_errors(failed_analytical_invocations)

    if fallback:
        log_event(
            '[Tabular SK Analysis] Reviewer recovery produced computed analytical tool results',
            extra={
                'reviewer_functions': executed_function_names,
                'successful_tool_count': len(successful_analytical_invocations),
                'failed_tool_count': len(failed_analytical_invocations),
            },
            level=logging.INFO,
        )
        return {
            'fallback': fallback,
            'tool_error_messages': failed_tool_error_messages,
            'reviewer_plan_errors': reviewer_plan_errors,
        }

    if reviewer_plan_errors or failed_tool_error_messages:
        log_event(
            '[Tabular SK Analysis] Reviewer recovery executed but did not produce usable analytical results',
            extra={
                'reviewer_functions': executed_function_names,
                'reviewer_plan_errors': reviewer_plan_errors[:5],
                'tool_errors': failed_tool_error_messages[:5],
                'reviewer_output_preview': reviewer_text[:500],
            },
            level=logging.WARNING,
        )

    return None


def filter_tabular_citation_invocations(invocations):
    """Hide discovery-only citation noise when analytical tabular calls exist."""
    if not invocations:
        return []

    successful_analytical_invocations, _ = split_tabular_analysis_invocations(invocations)
    if successful_analytical_invocations:
        return successful_analytical_invocations

    successful_schema_summary_invocations = []
    for invocation in invocations or []:
        if getattr(invocation, 'function_name', '') != 'describe_tabular_file':
            continue
        if get_tabular_invocation_error_message(invocation):
            continue
        successful_schema_summary_invocations.append(invocation)

    if successful_schema_summary_invocations:
        return successful_schema_summary_invocations

    return []


def _coerce_tabular_chart_number(value):
    if value in (None, '') or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    candidate = str(value).strip().replace(',', '')
    if not candidate:
        return None

    try:
        return float(candidate)
    except ValueError:
        return None


def _humanize_tabular_chart_label(value, fallback='Value'):
    candidate = str(value or '').strip().replace('_', ' ')
    if not candidate:
        candidate = fallback
    return candidate[:80]


def _get_requested_tabular_chart_kind(user_message):
    normalized_message = re.sub(r'\s+', ' ', str(user_message or '').strip().lower())
    if not normalized_message:
        return ''

    chart_kind_patterns = (
        ('stacked_bar', r'\bstacked\s+bar\s+chart\b'),
        ('stacked_line', r'\bstacked\s+line\s+chart\b'),
        ('doughnut', r'\b(?:doughnut|donut)\s+chart\b|\b(?:doughnut|donut)\b'),
        ('pie', r'\bpie\s+chart\b|\bpie\b'),
        ('area', r'\barea\s+chart\b|\barea\b'),
        ('line', r'\bline\s+chart\b|\btrend\s+chart\b|\bline\b'),
        ('bar', r'\bbar\s+chart\b|\bbar\b'),
        ('radar', r'\bradar\s+chart\b|\bradar\b'),
    )

    for chart_kind, pattern in chart_kind_patterns:
        if re.search(pattern, normalized_message):
            normalized_kind = normalize_chart_kind(chart_kind)
            if normalized_kind in TABULAR_INLINE_CHART_SUPPORTED_GROUP_KINDS:
                return normalized_kind

    if re.search(r'\b(?:histogram|heatmap|scatter|bubble)\s+chart\b', normalized_message):
        return 'bar'

    return ''


def _select_tabular_inline_chart_kind(user_message, invocation_function_name, result_payload, value_items):
    requested_kind = _get_requested_tabular_chart_kind(user_message)
    if requested_kind:
        chart_kind = requested_kind
    elif invocation_function_name == 'group_by_datetime_component':
        chart_kind = 'line'
    else:
        chart_kind = 'bar'

    values = [item[1] for item in value_items]
    if chart_kind in {'pie', 'doughnut'}:
        if any(value < 0 for value in values) or sum(values) <= 0:
            chart_kind = 'bar'

    if chart_kind in {'stacked_bar', 'stacked_line'} and len(value_items) <= 1:
        chart_kind = 'bar' if chart_kind == 'stacked_bar' else 'line'

    if chart_kind not in TABULAR_INLINE_CHART_SUPPORTED_GROUP_KINDS:
        chart_kind = 'bar'

    return chart_kind


def _get_tabular_inline_chart_result_items(function_name, result_payload, chart_kind):
    if not isinstance(result_payload, dict):
        return []

    result_mapping = None
    if function_name == 'group_by_datetime_component' and chart_kind in {'line', 'area', 'stacked_line', 'bar', 'stacked_bar'}:
        result_mapping = result_payload.get('result')
    if not isinstance(result_mapping, dict) or not result_mapping:
        result_mapping = result_payload.get('top_results')
    if not isinstance(result_mapping, dict) or not result_mapping:
        result_mapping = result_payload.get('result')
    if not isinstance(result_mapping, dict) or not result_mapping:
        return []

    value_items = []
    for label, raw_value in result_mapping.items():
        numeric_value = _coerce_tabular_chart_number(raw_value)
        if numeric_value is None:
            continue

        value_items.append((
            _humanize_tabular_chart_label(label, fallback=f'Item {len(value_items) + 1}'),
            numeric_value,
        ))
        if len(value_items) >= TABULAR_INLINE_CHART_MAX_POINTS:
            break

    return value_items


def _build_tabular_inline_chart_title(function_name, result_payload):
    aggregate_column = result_payload.get('aggregate_column') or 'Rows'
    operation = str(result_payload.get('operation') or '').strip().lower()
    if operation and operation != 'count':
        metric_label = f"{operation.title()} {_humanize_tabular_chart_label(aggregate_column)}"
    elif operation == 'count':
        metric_label = 'Count'
    else:
        metric_label = _humanize_tabular_chart_label(aggregate_column)

    if function_name == 'group_by_datetime_component':
        group_label = _humanize_tabular_chart_label(result_payload.get('datetime_component'), fallback='Time')
    else:
        group_label = _humanize_tabular_chart_label(result_payload.get('group_by'), fallback='Group')

    return f'{metric_label} by {group_label}'


def _build_tabular_inline_chart_subtitle(result_payload):
    filename = str(result_payload.get('filename') or '').strip()
    selected_sheet = str(result_payload.get('selected_sheet') or '').strip()
    subtitle_parts = [part for part in (filename, selected_sheet) if part]
    return ' - '.join(subtitle_parts)[:160]


def build_tabular_inline_chart_citations(user_message, invocations, max_charts=TABULAR_INLINE_CHART_MAX_CHARTS):
    """Create SimpleChat inline chart citations from grouped tabular tool results."""
    if max_charts <= 0:
        return []
    if not (user_requested_chart_visualization(user_message) or user_request_supports_proactive_charts(user_message)):
        return []

    chart_plugin = ChartPlugin()
    chart_citations = []
    seen_chart_sources = set()

    for invocation in invocations or []:
        if len(chart_citations) >= max_charts:
            break

        function_name = str(getattr(invocation, 'function_name', '') or '').strip()
        if function_name not in TABULAR_INLINE_CHARTABLE_FUNCTIONS:
            continue
        if get_tabular_invocation_error_message(invocation):
            continue

        result_payload = get_tabular_invocation_result_payload(invocation) or {}
        preliminary_kind = _select_tabular_inline_chart_kind(user_message, function_name, result_payload, [])
        value_items = _get_tabular_inline_chart_result_items(function_name, result_payload, preliminary_kind)
        if len(value_items) < 2:
            continue

        chart_kind = _select_tabular_inline_chart_kind(user_message, function_name, result_payload, value_items)
        source_key = json.dumps({
            'function_name': function_name,
            'filename': result_payload.get('filename'),
            'selected_sheet': result_payload.get('selected_sheet'),
            'group_by': result_payload.get('group_by') or result_payload.get('datetime_component'),
            'aggregate_column': result_payload.get('aggregate_column'),
            'operation': result_payload.get('operation'),
            'chart_kind': chart_kind,
            'items': value_items,
        }, sort_keys=True, default=str)
        if source_key in seen_chart_sources:
            continue
        seen_chart_sources.add(source_key)

        group_label = result_payload.get('group_by') or result_payload.get('datetime_component') or 'Group'
        metric_label = result_payload.get('aggregate_column') or result_payload.get('operation') or 'Value'
        chart_data = {
            'labels': [label for label, _ in value_items],
            'datasets': [{
                'label': _humanize_tabular_chart_label(metric_label),
                'data': [value for _, value in value_items],
            }],
        }
        options = {
            'showDataTable': True,
            'beginAtZero': True,
        }

        chart_result = chart_plugin.create_chart(
            chart_kind,
            json.dumps(chart_data, separators=(',', ':'), default=str),
            title=_build_tabular_inline_chart_title(function_name, result_payload),
            subtitle=_build_tabular_inline_chart_subtitle(result_payload),
            description='Generated from computed tabular analysis results.',
            x_axis_label=_humanize_tabular_chart_label(group_label),
            y_axis_label=_humanize_tabular_chart_label(metric_label),
            options_json=json.dumps(options, separators=(',', ':')),
        )
        if not isinstance(chart_result, dict) or not chart_result.get('success'):
            log_event(
                '[Tabular Charts] Failed to create inline chart from grouped tabular result.',
                extra={
                    'function_name': function_name,
                    'chart_kind': chart_kind,
                    'error': chart_result.get('error') if isinstance(chart_result, dict) else None,
                },
                level=logging.WARNING,
            )
            continue

        chart_citations.append({
            'tool_name': 'Conversation Charts',
            'function_name': 'create_chart',
            'plugin_name': CORE_CHART_PLUGIN_NAME,
            'function_arguments': make_json_serializable({
                'chart_type': chart_kind,
                'chart_data_json': chart_data,
                'title': _build_tabular_inline_chart_title(function_name, result_payload),
                'source_function': function_name,
            }),
            'function_result': make_json_serializable(chart_result),
            'duration_ms': None,
            'timestamp': datetime.utcnow().isoformat(),
            'success': True,
            'error_message': None,
            'user_id': getattr(invocation, 'user_id', None),
        })

    if chart_citations:
        log_event(
            f'[Tabular Charts] Prepared {len(chart_citations)} inline chart(s) from tabular results.',
            level=logging.INFO,
        )

    return chart_citations


def format_tabular_thought_parameter_value(value):
    """Render a concise parameter value for tabular thought details."""
    if value is None:
        return None

    if isinstance(value, (dict, list, tuple)):
        rendered_value = json.dumps(value, default=str)
    else:
        rendered_value = str(value)

    if not rendered_value:
        return None

    if len(rendered_value) > 120:
        rendered_value = rendered_value[:117] + '...'

    return rendered_value


def get_tabular_tool_thought_payloads(invocations):
    """Convert tabular plugin invocations into user-visible thought payloads."""
    thought_payloads = []

    for invocation in invocations or []:
        function_name = getattr(invocation, 'function_name', 'unknown_tool')
        duration_ms = getattr(invocation, 'duration_ms', None)
        error_message = get_tabular_invocation_error_message(invocation)
        success = getattr(invocation, 'success', True) and not error_message
        parameters = getattr(invocation, 'parameters', {}) or {}

        filename = parameters.get('filename')
        sheet_name = parameters.get('sheet_name')
        duration_suffix = f" ({int(duration_ms)}ms)" if duration_ms else ""
        content = f"Tabular tool {function_name}{duration_suffix}"
        if filename:
            content = f"Tabular tool {function_name} on {filename}{duration_suffix}"
        if filename and sheet_name:
            content = f"Tabular tool {function_name} on {filename} [{sheet_name}]{duration_suffix}"
        if not success:
            content = f"{content} failed"

        detail_parts = []
        for parameter_name, parameter_value in parameters.items():
            if parameter_name in get_tabular_thought_excluded_parameter_names():
                continue

            rendered_value = format_tabular_thought_parameter_value(parameter_value)
            if rendered_value is None:
                continue

            detail_parts.append(f"{parameter_name}={rendered_value}")

        rendered_error_message = format_tabular_thought_parameter_value(error_message)
        if rendered_error_message:
            detail_parts.append(f"error={rendered_error_message}")

        detail_parts.append(f"success={success}")
        detail = "; ".join(detail_parts) if detail_parts else None
        thought_payloads.append((content, detail))

    return thought_payloads


def build_tabular_activity_payload(invocation_or_start, state):
    """Build a stable activity payload for live tabular tool progress updates."""
    plugin_name = str(getattr(invocation_or_start, 'plugin_name', '') or 'TabularProcessingPlugin').strip()
    function_name = str(getattr(invocation_or_start, 'function_name', '') or 'tabular_tool').strip()
    parameters = getattr(invocation_or_start, 'parameters', {}) or {}
    sheet_name = str(parameters.get('sheet_name') or '').strip()
    title = function_name
    if sheet_name:
        title = f"{function_name} [{sheet_name}]"

    payload = {
        'activity_key': getattr(invocation_or_start, 'invocation_id', None) or f"tabular.{function_name}",
        'kind': 'tabular_tool_invocation',
        'title': title,
        'status': state,
        'state': state,
        'lane_key': 'tabular',
        'lane_label': 'Tabular',
        'plugin_name': plugin_name,
        'function_name': function_name,
    }

    filename = parameters.get('filename')
    if filename:
        payload['filename'] = filename
    if sheet_name:
        payload['sheet_name'] = sheet_name

    return payload


def build_tabular_post_processing_activity_payload(
    activity_key,
    title,
    state,
    *,
    phase=None,
    output_format=None,
    file_name=None,
    batch_index=None,
    batch_count=None,
):
    """Build a stable activity payload for non-tool tabular post-processing work."""
    payload = {
        'activity_key': str(activity_key or 'tabular.post_processing').strip() or 'tabular.post_processing',
        'kind': 'tabular_post_processing',
        'title': str(title or 'Tabular post-processing').strip() or 'Tabular post-processing',
        'status': str(state or 'running').strip().lower() or 'running',
        'state': str(state or 'running').strip().lower() or 'running',
        'lane_key': 'tabular',
        'lane_label': 'Tabular',
    }

    normalized_phase = str(phase or '').strip().lower()
    if normalized_phase:
        payload['phase'] = normalized_phase

    normalized_output_format = str(output_format or '').strip().lower()
    if normalized_output_format:
        payload['output_format'] = normalized_output_format

    normalized_file_name = str(file_name or '').strip()
    if normalized_file_name:
        payload['file_name'] = normalized_file_name

    if batch_index is not None:
        payload['batch_index'] = int(batch_index)
    if batch_count is not None:
        payload['batch_count'] = int(batch_count)

    return payload


def build_tabular_analysis_lifecycle_activity_payload(
    title,
    state,
    *,
    phase='analysis',
    attempt_number=None,
    attempt_count=None,
):
    """Build a stable activity payload for long-running tabular analysis lifecycle work."""
    payload = {
        'activity_key': 'tabular.analysis.lifecycle',
        'kind': 'tabular_analysis_lifecycle',
        'title': str(title or 'Analyzing workbook evidence').strip() or 'Analyzing workbook evidence',
        'status': str(state or 'running').strip().lower() or 'running',
        'state': str(state or 'running').strip().lower() or 'running',
        'lane_key': 'tabular',
        'lane_label': 'Tabular',
    }

    normalized_phase = str(phase or '').strip().lower()
    if normalized_phase:
        payload['phase'] = normalized_phase

    if attempt_number is not None:
        payload['attempt_number'] = int(attempt_number)
    if attempt_count is not None:
        payload['attempt_count'] = int(attempt_count)

    return payload


async def emit_tabular_post_processing_thought(thought_callback, content, detail=None, activity=None):
    """Emit a tabular post-processing thought through an optional callback."""
    if not callable(thought_callback):
        return

    thought_payload = {
        'step_type': 'tabular_analysis',
        'content': str(content or '').strip(),
    }
    if detail is not None:
        thought_payload['detail'] = detail
    if isinstance(activity, dict) and activity:
        thought_payload['activity'] = activity

    callback_result = thought_callback(thought_payload)
    if inspect.isawaitable(callback_result):
        await callback_result


async def emit_tabular_analysis_lifecycle_thought(
    thought_callback,
    content,
    *,
    detail=None,
    title=None,
    state='running',
    phase='analysis',
    attempt_number=None,
    attempt_count=None,
):
    """Emit a long-running lifecycle thought for tabular analysis progress."""
    await emit_tabular_post_processing_thought(
        thought_callback,
        content,
        detail=detail,
        activity=build_tabular_analysis_lifecycle_activity_payload(
            title or 'Analyzing workbook evidence',
            state,
            phase=phase,
            attempt_number=attempt_number,
            attempt_count=attempt_count,
        ),
    )


def format_live_tabular_invocation_start_thought(invocation_start):
    """Build a live thought payload for an in-flight tabular tool invocation."""
    parameters = getattr(invocation_start, 'parameters', {}) or {}
    function_name = str(getattr(invocation_start, 'function_name', '') or 'tabular_tool').strip()
    filename = parameters.get('filename')
    sheet_name = parameters.get('sheet_name')

    content = f"Starting tabular tool {function_name}"
    if filename:
        content = f"Starting tabular tool {function_name} on {filename}"
    if filename and sheet_name:
        content = f"Starting tabular tool {function_name} on {filename} [{sheet_name}]"

    detail_parts = []
    for parameter_name, parameter_value in parameters.items():
        if parameter_name in get_tabular_thought_excluded_parameter_names():
            continue

        rendered_value = format_tabular_thought_parameter_value(parameter_value)
        if rendered_value is None:
            continue

        detail_parts.append(f"{parameter_name}={rendered_value}")

    detail_parts.append('status=running')
    detail = '; '.join(detail_parts) if detail_parts else None

    return {
        'step_type': 'tabular_analysis',
        'content': content,
        'detail': detail,
        'activity': build_tabular_activity_payload(invocation_start, 'running'),
    }


def format_live_tabular_invocation_thought(invocation):
    """Build a live thought payload from a completed tabular tool invocation."""
    thought_payloads = get_tabular_tool_thought_payloads([invocation])
    if thought_payloads:
        content, detail = thought_payloads[0]
    else:
        function_name = str(getattr(invocation, 'function_name', '') or 'tabular_tool').strip()
        content = f"Tabular tool {function_name}"
        detail = None

    error_message = get_tabular_invocation_error_message(invocation)
    success = getattr(invocation, 'success', True) and not error_message

    return {
        'step_type': 'tabular_analysis',
        'content': content,
        'detail': detail,
        'activity': build_tabular_activity_payload(
            invocation,
            'failed' if not success else 'completed',
        ),
    }


def register_tabular_invocation_thought_callback(
    plugin_logger,
    thought_tracker,
    user_id,
    conversation_id,
    live_thought_callback=None,
):
    """Register a callback that persists and optionally streams tabular tool thoughts."""
    callback_key = f"{user_id}:{conversation_id}"

    def add_and_publish_live_thought(thought_payload):
        thought_tracker.add_thought(
            thought_payload['step_type'],
            thought_payload['content'],
            detail=thought_payload.get('detail'),
            activity=thought_payload.get('activity'),
        )

        if callable(live_thought_callback):
            live_payload = dict(thought_payload)
            live_payload['message_id'] = getattr(thought_tracker, 'message_id', None)
            live_payload['step_index'] = thought_tracker.current_index - 1
            live_thought_callback(live_payload)

    def on_plugin_invocation_start(invocation_start):
        if str(getattr(invocation_start, 'plugin_name', '') or '').strip() != 'TabularProcessingPlugin':
            return

        add_and_publish_live_thought(format_live_tabular_invocation_start_thought(invocation_start))

    def on_plugin_invocation(invocation):
        if str(getattr(invocation, 'plugin_name', '') or '').strip() != 'TabularProcessingPlugin':
            return

        add_and_publish_live_thought(format_live_tabular_invocation_thought(invocation))

    plugin_logger.register_start_callback(callback_key, on_plugin_invocation_start)
    plugin_logger.register_callback(callback_key, on_plugin_invocation)
    return callback_key


def get_tabular_status_thought_payloads(invocations, analysis_succeeded):
    """Return additional tabular status thoughts for retries and fallbacks."""
    successful_analytical_invocations, failed_analytical_invocations = split_tabular_analysis_invocations(invocations)
    if not failed_analytical_invocations:
        return []

    error_messages = summarize_tabular_invocation_errors(failed_analytical_invocations)
    detail = "; ".join(error_messages) if error_messages else None

    if analysis_succeeded and successful_analytical_invocations:
        return [(
            "Tabular analysis recovered after retrying tool errors",
            detail,
        )]

    if analysis_succeeded:
        return [(
            "Tabular analysis recovered via internal fallback after tool errors",
            detail,
        )]

    return [(
        "Tabular analysis encountered tool errors before fallback",
        detail,
    )]


def _normalize_tabular_sheet_token(token):
    """Normalize question and sheet-name tokens for lightweight matching."""
    normalized = re.sub(r'[^a-z0-9]+', '', str(token or '').lower())
    if len(normalized) > 4 and normalized.endswith('ies'):
        return normalized[:-3] + 'y'
    if len(normalized) > 3 and normalized.endswith('s') and not normalized.endswith('ss'):
        return normalized[:-1]
    return normalized


def _tokenize_tabular_sheet_text(text):
    """Tokenize free text into normalized sheet-matching tokens."""
    original_text = re.sub(r'(?i)w[\s\-_]*2', ' w2 ', str(text or ''))
    expanded_text = re.sub(r'([a-z])([A-Z])', r'\1 \2', original_text)
    expanded_text = re.sub(r'([A-Za-z])([0-9])', r'\1 \2', expanded_text)
    expanded_text = re.sub(r'([0-9])([A-Za-z])', r'\1 \2', expanded_text)
    expanded_text = re.sub(r'[_\-]+', ' ', expanded_text)
    tokens = []
    seen_tokens = set()

    for raw_text in (original_text, expanded_text):
        for raw_token in re.split(r'[^a-z0-9]+', raw_text.lower()):
            normalized_token = _normalize_tabular_sheet_token(raw_token)
            if not normalized_token or len(normalized_token) <= 1:
                continue
            if normalized_token in seen_tokens:
                continue
            seen_tokens.add(normalized_token)
            tokens.append(normalized_token)

    return tokens


def _coerce_citation_sort_number(value):
    """Return a numeric citation sort value when possible."""
    if value in (None, '') or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    raw_value = str(value).strip()
    if not raw_value:
        return None

    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def _build_hybrid_citation_sort_key(citation):
    """Sort numeric page citations first, then metadata-style citations safely."""
    if not isinstance(citation, dict):
        return (0, -1.0, -1.0, '', '')

    page_number = citation.get('page_number')
    page_value = _coerce_citation_sort_number(page_number)
    chunk_sequence_value = _coerce_citation_sort_number(citation.get('chunk_sequence'))
    page_label = str(page_number or '').strip().lower()
    metadata_type = str(citation.get('metadata_type') or '').strip().lower()

    if page_value is not None:
        return (
            2,
            page_value,
            chunk_sequence_value if chunk_sequence_value is not None else -1.0,
            page_label,
            metadata_type,
        )

    if chunk_sequence_value is not None:
        return (1, chunk_sequence_value, -1.0, page_label, metadata_type)

    return (0, -1.0, -1.0, page_label, metadata_type)


def _extract_tabular_entity_anchor_terms(question_text):
    """Extract likely primary-entity terms from an entity lookup question."""
    normalized_question = str(question_text or '').strip().lower()
    if not normalized_question:
        return []

    stopwords = {
        'and',
        'any',
        'by',
        'detail',
        'details',
        'exact',
        'explain',
        'find',
        'for',
        'from',
        'full',
        'get',
        'give',
        'lookup',
        'me',
        'of',
        'or',
        'profile',
        'profiles',
        'record',
        'records',
        'related',
        'show',
        'story',
        'summaries',
        'summarize',
        'summary',
        'that',
        'the',
        'their',
        'this',
        'those',
        'these',
        'to',
        'up',
        'with',
    }
    capture_patterns = (
        r'\bfind\s+([^\.;:!?]+)',
        r'\blookup\s+([^\.;:!?]+)',
    )
    anchor_terms = []
    seen_anchor_terms = set()

    for capture_pattern in capture_patterns:
        match = re.search(capture_pattern, normalized_question)
        if not match:
            continue

        captured_text = re.split(
            r'\b(?:and|show|summarize|summary|profile|with|where|which|who|that)\b',
            match.group(1),
            maxsplit=1,
        )[0]
        for token in _tokenize_tabular_sheet_text(captured_text):
            if token in stopwords:
                continue
            if any(character.isdigit() for character in token):
                continue
            if token in seen_anchor_terms:
                continue
            seen_anchor_terms.add(token)
            anchor_terms.append(token)

    return anchor_terms


def _score_tabular_sheet_match(sheet_name, question_text, columns=None):
    """Score how strongly a worksheet name matches the user question.

    When *columns* (a list of column-name strings from the sheet schema) is
    provided, column-name tokens that overlap with the question contribute to
    the score.  This allows sheets whose names are generic (e.g. "Orders") to
    still score highly when the question references column values like
    "sales" or "profit".
    """
    question_tokens = set(_tokenize_tabular_sheet_text(question_text))
    question_phrase = ' '.join(_tokenize_tabular_sheet_text(question_text))
    sheet_tokens = _tokenize_tabular_sheet_text(sheet_name)
    if not sheet_tokens:
        return 0

    sheet_phrase = ' '.join(sheet_tokens)
    score = 0

    if sheet_phrase and sheet_phrase in question_phrase:
        score += 8

    token_matches = sum(1 for token in sheet_tokens if token in question_tokens)
    score += token_matches * 3

    if len(sheet_tokens) == 1 and sheet_tokens[0] in question_tokens:
        score += 4

    # Column-name overlap: each matching column token adds 2 points.
    if columns and question_tokens:
        column_tokens = set()
        for col_name in columns:
            column_tokens.update(_tokenize_tabular_sheet_text(col_name))
        column_matches = sum(1 for token in question_tokens if token in column_tokens)
        score += column_matches * 2

    return score


def _score_tabular_entity_sheet_match(sheet_name, question_text, columns=None):
    """Score worksheets for entity lookups, prioritizing the primary entity sheet."""
    score = _score_tabular_sheet_match(sheet_name, question_text, columns=columns)
    anchor_terms = _extract_tabular_entity_anchor_terms(question_text)
    if not anchor_terms:
        return score

    question_tokens = set(_tokenize_tabular_sheet_text(question_text))
    sheet_tokens = set(_tokenize_tabular_sheet_text(sheet_name))
    column_tokens = set()
    for column_name in columns or []:
        column_tokens.update(_tokenize_tabular_sheet_text(column_name))

    for anchor_term in anchor_terms:
        if anchor_term in sheet_tokens:
            score += 12
        elif anchor_term in column_tokens:
            score += 4

    if 'profile' in question_tokens and column_tokens.intersection({
        'address',
        'city',
        'displayname',
        'dob',
        'email',
        'firstname',
        'fullname',
        'lastname',
        'name',
        'phone',
        'state',
        'status',
    }):
        score += 6

    return score

def _select_relevant_workbook_sheets(sheet_names, question_text, minimum_score=1, per_sheet=None, score_match_fn=None):
    """Return all workbook sheets that appear relevant to the question."""
    score_match_fn = score_match_fn or _score_tabular_sheet_match
    ranked_sheets = []
    for sheet_name in sheet_names or []:
        columns = None
        if per_sheet:
            sheet_info = per_sheet.get(sheet_name, {})
            columns = sheet_info.get('columns', [])
        score = score_match_fn(sheet_name, question_text, columns=columns)
        if score < minimum_score:
            continue
        ranked_sheets.append((score, sheet_name))

    ranked_sheets.sort(key=lambda item: (-item[0], item[1].lower()))
    return [sheet_name for _, sheet_name in ranked_sheets]


def _build_tabular_cross_sheet_bridge_plan(sheet_names, question_text, per_sheet=None):
    """Infer a lightweight reference-sheet to fact-sheet plan for grouped workbook questions."""
    if not per_sheet or not is_tabular_cross_sheet_bridge_question(question_text):
        return None

    ranked_sheets = []
    for sheet_name in sheet_names or []:
        sheet_info = per_sheet.get(sheet_name, {})
        columns = sheet_info.get('columns', [])
        row_count = sheet_info.get('row_count', 0) or 0
        score = _score_tabular_sheet_match(sheet_name, question_text, columns=columns)
        if score <= 0:
            continue
        ranked_sheets.append({
            'sheet_name': sheet_name,
            'score': score,
            'row_count': row_count,
        })

    if len(ranked_sheets) < 2:
        return None

    fact_sheet = max(
        ranked_sheets,
        key=lambda item: (item['row_count'], item['score'], item['sheet_name'].lower()),
    )
    reference_candidates = [
        item for item in ranked_sheets
        if item['sheet_name'] != fact_sheet['sheet_name'] and item['row_count'] > 0
    ]
    if not reference_candidates:
        return None

    reference_sheet = min(
        reference_candidates,
        key=lambda item: (item['row_count'], -item['score'], item['sheet_name'].lower()),
    )

    if fact_sheet['row_count'] <= reference_sheet['row_count']:
        return None

    if fact_sheet['row_count'] < max(25, reference_sheet['row_count'] * 2):
        return None

    relevant_sheets = [reference_sheet['sheet_name'], fact_sheet['sheet_name']]
    for item in sorted(ranked_sheets, key=lambda entry: (-entry['score'], entry['sheet_name'].lower())):
        if item['sheet_name'] in relevant_sheets:
            continue
        relevant_sheets.append(item['sheet_name'])

    return {
        'reference_sheet': reference_sheet['sheet_name'],
        'reference_row_count': reference_sheet['row_count'],
        'fact_sheet': fact_sheet['sheet_name'],
        'fact_row_count': fact_sheet['row_count'],
        'relevant_sheets': relevant_sheets,
    }


def is_tabular_access_limited_analysis(analysis_text):
    """Return True when a tool-backed analysis still claims the data is unavailable."""
    normalized_analysis = re.sub(r'\s+', ' ', str(analysis_text or '').strip().lower())
    if not normalized_analysis:
        return False

    inaccessible_phrases = (
        "don't have direct access",
        'do not have direct access',
        "don't have",
        'do not have',
        "doesn't include the full",
        'does not include the full',
        'only sample rows',
        'only workbook metadata',
        'only sample rows and workbook metadata',
        'cannot accurately list all',
        'cannot accurately list them',
        'from the current evidence',
        'from the evidence provided',
        'visible excerpt you provided',
        'if those tool-backed results exist',
        'allow me to query again',
        'can outline what i would retrieve',
    )
    return any(phrase in normalized_analysis for phrase in inaccessible_phrases)


def get_tabular_result_coverage_summary(invocations):
    """Return whether successful analytical tool calls produced full or partial result coverage."""
    coverage_summary = {
        'has_full_result_coverage': False,
        'has_partial_result_coverage': False,
    }

    for invocation in invocations or []:
        result_payload = get_tabular_invocation_result_payload(invocation) or {}

        total_matches = parse_tabular_result_count(result_payload.get('total_matches'))
        returned_rows = parse_tabular_result_count(result_payload.get('returned_rows'))
        if total_matches is not None and returned_rows is not None:
            if returned_rows >= total_matches:
                coverage_summary['has_full_result_coverage'] = True
            else:
                coverage_summary['has_partial_result_coverage'] = True

        distinct_count = parse_tabular_result_count(result_payload.get('distinct_count'))
        returned_values = parse_tabular_result_count(result_payload.get('returned_values'))
        if distinct_count is not None and returned_values is not None:
            if returned_values >= distinct_count:
                coverage_summary['has_full_result_coverage'] = True
            else:
                coverage_summary['has_partial_result_coverage'] = True

        if result_payload.get('full_rows_included') or result_payload.get('full_values_included'):
            coverage_summary['has_full_result_coverage'] = True
        if result_payload.get('sample_rows_limited') or result_payload.get('values_limited'):
            coverage_summary['has_partial_result_coverage'] = True

        if (
            coverage_summary['has_full_result_coverage']
            and coverage_summary['has_partial_result_coverage']
        ):
            break

    return coverage_summary


def build_tabular_success_execution_gap_messages(user_question, analysis_text, invocations):
    """Return retry guidance when a successful tabular analysis still produced an incomplete answer."""
    coverage_summary = get_tabular_result_coverage_summary(invocations)
    has_full_result_coverage = coverage_summary['has_full_result_coverage']
    has_partial_result_coverage = coverage_summary['has_partial_result_coverage']
    wants_exhaustive_results = question_requests_tabular_exhaustive_results(user_question)
    execution_gap_messages = []

    if is_tabular_access_limited_analysis(analysis_text):
        if wants_exhaustive_results and has_full_result_coverage:
            execution_gap_messages.append(
                'Previous attempt still claimed only sample rows or workbook metadata were available even though successful analytical tool calls returned the full matching result set. Answer directly from those returned rows and list the full results the user asked for.'
            )
        elif has_full_result_coverage:
            execution_gap_messages.append(
                'Previous attempt still claimed the requested data was unavailable even though successful analytical tool calls returned the full matching result set. Use the returned rows and answer directly.'
            )
        else:
            execution_gap_messages.append(
                'Previous attempt still claimed the requested data was unavailable even though analytical tool calls succeeded. Use the returned rows and answer directly.'
            )

    if (
        wants_exhaustive_results
        and has_partial_result_coverage
        and not has_full_result_coverage
    ):
        execution_gap_messages.append(
            'The user asked for a full list, but previous analytical calls returned only a partial slice. Rerun the relevant analytical call with a higher max_rows or max_values before answering.'
        )

    return execution_gap_messages


def _select_likely_workbook_sheet(sheet_names, question_text, per_sheet=None, score_match_fn=None):
    """Return a likely sheet name when the user question strongly matches one sheet."""
    score_match_fn = score_match_fn or _score_tabular_sheet_match
    best_sheet = None
    best_score = 0
    runner_up_score = 0

    for sheet_name in sheet_names or []:
        columns = None
        if per_sheet:
            sheet_info = per_sheet.get(sheet_name, {})
            columns = sheet_info.get('columns', [])
        score = score_match_fn(sheet_name, question_text, columns=columns)

        if score > best_score:
            runner_up_score = best_score
            best_score = score
            best_sheet = sheet_name
        elif score > runner_up_score:
            runner_up_score = score

    if best_score <= 0 or best_score == runner_up_score:
        return None

    return best_sheet


async def run_tabular_sk_analysis(user_question, tabular_filenames, user_id,
                                   conversation_id, gpt_model, settings,
                                   source_hint="workspace", group_id=None,
                                   public_workspace_id=None,
                                   execution_mode='analysis',
                                   tabular_file_contexts=None,
                                   thought_callback=None,
                                   model_context=None):
    """Run lightweight SK with tabular analysis and attachment follow-up support.

    Creates a temporary Kernel with TabularProcessingPlugin plus document-search
    helpers for attachment-backed rows, uses the same chat model as the user's
    session, and returns computed analysis results.
    Returns None on failure for graceful degradation.
    """
    from semantic_kernel import Kernel as SKKernel
    from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
    from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import AzureChatPromptExecutionSettings
    from semantic_kernel.contents.chat_history import ChatHistory as SKChatHistory
    from semantic_kernel_plugins.document_search_plugin import DocumentSearchPlugin
    from semantic_kernel_plugins.fact_memory_plugin import FactMemoryPlugin
    from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

    try:
        plugin_logger = get_plugin_logger()
        execution_mode = execution_mode if execution_mode in {'analysis', 'schema_summary', 'entity_lookup'} else 'analysis'
        schema_summary_mode = execution_mode == 'schema_summary'
        entity_lookup_mode = execution_mode == 'entity_lookup'
        fact_memory_enabled = bool(settings.get('enable_fact_memory_plugin', False))
        fact_memory_scope_id = group_id or user_id
        fact_memory_scope_type = 'group' if group_id else 'user'
        analysis_file_contexts = normalize_tabular_file_contexts_for_analysis(
            tabular_filenames=tabular_filenames,
            tabular_file_contexts=tabular_file_contexts,
            fallback_source_hint=source_hint,
            fallback_group_id=group_id,
            fallback_public_workspace_id=public_workspace_id,
        )
        analysis_filenames = [file_context['file_name'] for file_context in analysis_file_contexts]
        log_event(
            f"[Tabular SK Analysis] Starting {execution_mode} analysis for files: {analysis_filenames}",
            level=logging.INFO,
        )

        # 1. Create lightweight kernel with tabular and document-search plugins
        kernel = SKKernel()
        tabular_plugin = TabularProcessingPlugin()
        document_search_plugin = DocumentSearchPlugin()
        kernel.add_plugin(tabular_plugin, plugin_name="tabular_processing")
        kernel.add_plugin(document_search_plugin, plugin_name="document_search")
        if fact_memory_enabled:
            kernel.add_plugin(FactMemoryPlugin(), plugin_name="fact_memory")

        # 2. Create chat service using same config as main chat.
        chat_service, tabular_model_protocol = build_semantic_kernel_chat_service_for_model(
            gpt_model,
            settings,
            service_id="tabular-analysis",
            model_context=model_context,
        )
        kernel.add_service(chat_service)

        # 3. Pre-dispatch: load file schemas to eliminate discovery LLM rounds
        source_context = build_tabular_analysis_source_context(
            analysis_file_contexts,
            fallback_source_hint=source_hint,
            fallback_group_id=group_id,
            fallback_public_workspace_id=public_workspace_id,
        )
        attachment_search_scope_context = build_tabular_attachment_search_scope_context(
            analysis_file_contexts,
            fallback_source_hint=source_hint,
            fallback_group_id=group_id,
            fallback_public_workspace_id=public_workspace_id,
        )

        schema_parts = []
        workbook_sheet_hints = {}
        workbook_related_sheet_hints = {}
        workbook_cross_sheet_bridge_hints = {}
        workbook_blob_locations = {}
        retry_sheet_overrides = {}
        previous_failed_call_parameters = []  # entity lookup: concrete failed call params for retry hints
        has_multi_sheet_workbook = False
        sheet_score_match_fn = _score_tabular_entity_sheet_match if entity_lookup_mode else _score_tabular_sheet_match
        for file_context in analysis_file_contexts:
            fname = file_context['file_name']
            file_source_hint = file_context.get('source_hint', source_hint)
            file_group_id = file_context.get('group_id')
            file_public_workspace_id = file_context.get('public_workspace_id')
            schema_source_context = {'source': file_source_hint}
            if file_group_id:
                schema_source_context['group_id'] = file_group_id
            if file_public_workspace_id:
                schema_source_context['public_workspace_id'] = file_public_workspace_id
            try:
                container, blob_path = tabular_plugin._resolve_blob_location_with_fallback(
                    user_id, conversation_id, fname, file_source_hint,
                    group_id=file_group_id, public_workspace_id=file_public_workspace_id
                )
                tabular_plugin.remember_resolved_blob_location(
                    file_source_hint,
                    fname,
                    container,
                    blob_path,
                )
                schema_info = tabular_plugin._build_workbook_schema_summary(
                    container,
                    blob_path,
                    fname,
                    preview_rows=2,
                )
                workbook_blob_locations[fname] = (container, blob_path)

                if schema_info.get('is_workbook') and schema_info.get('sheet_count', 0) > 1:
                    has_multi_sheet_workbook = True
                    # Build a compact sheet directory so the model can pick the
                    # relevant sheet itself instead of us guessing.
                    per_sheet = schema_info.get('per_sheet_schemas', {})
                    likely_sheet = _select_likely_workbook_sheet(
                        schema_info.get('sheet_names', []),
                        user_question,
                        per_sheet=per_sheet,
                        score_match_fn=sheet_score_match_fn,
                    )
                    relevant_sheets = _select_relevant_workbook_sheets(
                        schema_info.get('sheet_names', []),
                        user_question,
                        per_sheet=per_sheet,
                        score_match_fn=sheet_score_match_fn,
                    )
                    cross_sheet_bridge_plan = None
                    if not schema_summary_mode and not entity_lookup_mode:
                        cross_sheet_bridge_plan = _build_tabular_cross_sheet_bridge_plan(
                            schema_info.get('sheet_names', []),
                            user_question,
                            per_sheet=per_sheet,
                        )
                    if entity_lookup_mode:
                        workbook_related_sheet_hints[fname] = relevant_sheets or list(schema_info.get('sheet_names', []))
                    elif cross_sheet_bridge_plan:
                        workbook_cross_sheet_bridge_hints[fname] = cross_sheet_bridge_plan
                        workbook_related_sheet_hints[fname] = cross_sheet_bridge_plan.get('relevant_sheets', [])
                        likely_sheet = cross_sheet_bridge_plan.get('fact_sheet') or likely_sheet
                    if likely_sheet:
                        workbook_sheet_hints[fname] = likely_sheet
                        if not entity_lookup_mode and not cross_sheet_bridge_plan:
                            tabular_plugin.set_default_sheet(container, blob_path, likely_sheet)
                    elif not entity_lookup_mode and not cross_sheet_bridge_plan:
                        # Fallback for analysis mode: pick the sheet with the
                        # most rows so that set_default_sheet is always called
                        # and the model can omit sheet_name on tool calls.
                        fallback_sheet = max(
                            schema_info.get('sheet_names', []),
                            key=lambda s: per_sheet.get(s, {}).get('row_count', 0),
                            default=None,
                        )
                        if fallback_sheet:
                            likely_sheet = fallback_sheet
                            workbook_sheet_hints[fname] = likely_sheet
                            tabular_plugin.set_default_sheet(container, blob_path, likely_sheet)

                    sheet_directory = []
                    for sname in schema_info.get('sheet_names', []):
                        sheet_info = per_sheet.get(sname, {})
                        sheet_directory.append({
                            'sheet_name': sname,
                            'row_count': sheet_info.get('row_count', 0),
                            'columns': sheet_info.get('columns', []),
                        })
                    directory_schema = {
                        'filename': fname,
                        'source_context': schema_source_context,
                        'is_workbook': True,
                        'sheet_count': schema_info.get('sheet_count', 0),
                        'likely_sheet': likely_sheet,
                        'sheet_role_hints': schema_info.get('sheet_role_hints', {}),
                        'relationship_hints': schema_info.get('relationship_hints', [])[:5],
                        'sheet_directory': sheet_directory,
                    }
                    schema_parts.append(json.dumps(directory_schema, indent=2, default=str))
                    log_event(
                        f"[Tabular SK Analysis] Pre-loaded workbook {fname} directory "
                        f"({schema_info.get('sheet_count', 0)} sheets available)"
                        + (f"; likely sheet '{likely_sheet}'" if likely_sheet else ''),
                        level=logging.DEBUG,
                    )
                else:
                    schema_with_context = dict(schema_info)
                    schema_with_context['source_context'] = schema_source_context
                    schema_parts.append(json.dumps(schema_with_context, indent=2, default=str))
                    if schema_info.get('is_workbook'):
                        # Single-sheet workbook — set default so the model needs no sheet arg
                        single_sheet = (schema_info.get('sheet_names') or [None])[0]
                        if single_sheet:
                            tabular_plugin.set_default_sheet(container, blob_path, single_sheet)
                    df = tabular_plugin._read_tabular_blob_to_dataframe(container, blob_path)
                    log_event(f"[Tabular SK Analysis] Pre-loaded schema for {fname} ({len(df)} rows)", level=logging.DEBUG)
            except Exception as e:
                log_event(
                    f"[Tabular SK Analysis] Failed to pre-load schema for {fname} "
                    f"(source={file_source_hint}, group_id={file_group_id}, public_workspace_id={file_public_workspace_id}): {e}",
                    level=logging.WARNING,
                )
                schema_parts.append(json.dumps({
                    "filename": fname,
                    "source_context": schema_source_context,
                    "error": f"Could not pre-load: {str(e)}",
                }))

        schema_context = "\n".join(schema_parts)
        allow_multi_sheet_discovery = has_multi_sheet_workbook and not schema_summary_mode
        allowed_function_names = ['describe_tabular_file'] if schema_summary_mode else sorted(get_tabular_analysis_function_names())
        attachment_search_function_names = [] if schema_summary_mode else get_tabular_attachment_search_function_names()
        if allow_multi_sheet_discovery:
            allowed_function_names = ['describe_tabular_file'] + allowed_function_names
        allowed_function_filters = {
            'included_functions': [
                f"tabular_processing-{function_name}"
                for function_name in allowed_function_names
            ] + [
                f"document_search-{function_name}"
                for function_name in attachment_search_function_names
            ]
        }

        def build_system_prompt(force_tool_use=False, tool_error_messages=None,
                                execution_gap_messages=None, discovery_feedback_messages=None):
            if schema_summary_mode:
                retry_prefix = ""
                if force_tool_use:
                    retry_prefix = (
                        "RETRY MODE: Your previous attempt did not execute a usable workbook-schema tool call. "
                        "You MUST call describe_tabular_file before writing any answer text. "
                        "Do not switch to aggregate, filter, query, lookup, or grouped-analysis tools for worksheet-summary questions.\n\n"
                    )

                tool_error_feedback = ""
                if tool_error_messages:
                    rendered_errors = "\n".join(
                        f"- {error_message}" for error_message in tool_error_messages
                    )
                    tool_error_feedback = (
                        "PREVIOUS TOOL ERRORS:\n"
                        f"{rendered_errors}\n"
                        "Correct the function arguments and retry describe_tabular_file immediately.\n\n"
                    )

                return (
                    "You are a workbook schema analyst. The workbook structure is available through the "
                    "tabular_processing plugin and the pre-loaded schema context. You MUST call "
                    "describe_tabular_file before answering. Use the workbook-level response to identify "
                    "worksheet names, what each worksheet represents, and the high-confidence relationships "
                    "visible from shared identifiers, columns, and sheet purposes.\n\n"
                    f"{retry_prefix}"
                    f"{tool_error_feedback}"
                    f"FILE SCHEMAS:\n"
                    f"{schema_context}\n\n"
                    "AVAILABLE FUNCTIONS: describe_tabular_file only.\n\n"
                    "IMPORTANT:\n"
                    "1. Call describe_tabular_file for each workbook you need to summarize.\n"
                    "2. For multi-sheet workbooks, omit sheet_name so the tool returns workbook-level sheet schemas.\n"
                    "3. Summarize the worksheet list, what each worksheet represents, and any cross-sheet relationships visible from shared identifiers or repeated business entities.\n"
                    "4. Do not switch to aggregate, filter, query, lookup, or grouped-analysis tools for workbook-structure questions.\n"
                    "5. If a relationship is not explicit, describe it as an inference from the schema rather than a confirmed join.\n"
                    "6. Do not mention hypothetical follow-up analyses or failed attempts unless the user explicitly asked about failures."
                )

            retry_prefix = ""
            if force_tool_use:
                retry_prefix = (
                    "RETRY MODE: Your previous attempt did not execute a usable analytical tool call. "
                    "You MUST call one or more analytical tabular_processing plugin functions before writing any answer text. "
                    "Do not say the analysis still needs to be run — run it now.\n\n"
                )

            tool_error_feedback = ""
            if tool_error_messages:
                rendered_errors = "\n".join(
                    f"- {error_message}" for error_message in tool_error_messages
                )
                tool_error_feedback = (
                    "PREVIOUS TOOL ERRORS:\n"
                    f"{rendered_errors}\n"
                    "Correct the function arguments and try again. If the operation is not 'count', provide an aggregate_column.\n\n"
                )

            execution_gap_feedback = ""
            if execution_gap_messages:
                rendered_gaps = "\n".join(
                    f"- {gap_message}" for gap_message in execution_gap_messages
                )
                execution_gap_feedback = (
                    "PREVIOUS EXECUTION GAPS:\n"
                    f"{rendered_gaps}\n"
                    "Correct the analysis plan and query the missing related worksheets before answering.\n\n"
                )

            discovery_feedback = ""
            if discovery_feedback_messages:
                rendered_discovery_feedback = "\n".join(
                    f"- {message}" for message in discovery_feedback_messages
                )
                discovery_feedback = (
                    "WORKBOOK DISCOVERY RESULTS:\n"
                    f"{rendered_discovery_feedback}\n"
                    "Use these discovery results to choose the next analytical tool calls. Discovery alone does not answer the question.\n\n"
                )

            attachment_follow_up_feedback = ""
            if attachment_search_function_names:
                attachment_follow_up_feedback = (
                    "ATTACHMENT FOLLOW-UP:\n"
                    "If returned rows reference attachments, PDFs, DOCX files, letters, or other external documents and the user's request needs the substance of those rows, use document_search functions to fetch the referenced document text before answering. "
                    "Search by the exact file name or basename from the row, then use retrieve_document_chunks or summarize_document on the matched document_id. "
                    "Do not stop at cover-note text like 'see attached' when attachment retrieval is available.\n"
                    f"{attachment_search_scope_context}\n\n"
                )

            missing_sheet_feedback = ""
            if tool_error_messages and any(
                'Specify sheet_name or sheet_index on analytical calls.' in error_message
                for error_message in tool_error_messages
            ):
                if entity_lookup_mode:
                    # Entity lookup: generate concrete per-sheet filter_rows examples from the actual failed call parameters
                    call_example_lines = []
                    for failed_params in previous_failed_call_parameters[:2]:
                        fname = failed_params.get('filename', '')
                        col = failed_params.get('column', '')
                        op = failed_params.get('operator', '==')
                        val = failed_params.get('value', '')
                        if not fname or not col or not val:
                            continue
                        related_sheets = workbook_related_sheet_hints.get(fname) or list(workbook_sheet_hints.values())
                        for sheet in related_sheets[:6]:
                            call_example_lines.append(
                                f'  filter_rows(filename="{fname}", sheet_name="{sheet}", column="{col}", operator="{op}", value="{val}")'
                            )
                    if call_example_lines:
                        examples_block = "\n".join(call_example_lines)
                        missing_sheet_feedback = (
                            "MULTI-SHEET RETRY REQUIRED: Your previous calls omitted sheet_name and all failed.\n"
                            "For this multi-sheet workbook, sheet_name is MANDATORY in every analytical call.\n"
                            "Execute ALL of these calls now (copy exactly as written):\n"
                            f"{examples_block}\n\n"
                        )
                    else:
                        related_lines = [
                            "MULTI-SHEET RETRY REQUIRED: Your previous calls omitted sheet_name.",
                            "Add sheet_name to every analytical call. Relevant worksheets per file:",
                        ]
                        for workbook_name, related_sheets in workbook_related_sheet_hints.items():
                            related_lines.append(
                                f"  {workbook_name}: query each of: {', '.join(related_sheets[:6])}"
                            )
                        missing_sheet_feedback = "\n".join(related_lines) + "\n\n"
                else:
                    guidance_lines = [
                        "MULTI-SHEET RETRY: Your previous analytical call omitted sheet_name on a multi-sheet workbook.",
                        "Retry immediately with sheet_name set to the most relevant worksheet from sheet_directory.",
                        "For account/category lookup questions by month, use filter_rows or query_tabular_data on the label column first, then read the requested month column.",
                        "Do not aggregate an entire month column unless the user explicitly asked for a total, sum, average, min, max, or count.",
                    ]
                    for workbook_name, hinted_sheet in workbook_sheet_hints.items():
                        guidance_lines.append(
                            f"Likely worksheet for {workbook_name} based on the question text: {hinted_sheet}."
                        )
                    missing_sheet_feedback = "\n".join(guidance_lines) + "\n\n"

            sheet_hint_feedback = ""
            if workbook_sheet_hints:
                rendered_hints = "\n".join(
                    f"- {workbook_name}: likely worksheet '{hinted_sheet}'"
                    for workbook_name, hinted_sheet in workbook_sheet_hints.items()
                )
                sheet_hint_feedback = (
                    "LIKELY WORKSHEET HINTS:\n"
                    f"{rendered_hints}\n"
                    "Use the likely worksheet unless the question clearly refers to a different sheet or a prior tool error identified a better recovery sheet.\n\n"
                )

            recovery_sheet_feedback = ""
            if retry_sheet_overrides:
                rendered_recovery_hints = "\n".join(
                    (
                        f"- {workbook_name}: retry on worksheet '{override_payload['sheet_name']}'"
                        + (f" ({override_payload['detail']})" if override_payload.get('detail') else '')
                    )
                    for workbook_name, override_payload in retry_sheet_overrides.items()
                )
                recovery_sheet_feedback = (
                    "RECOVERY WORKSHEET HINTS:\n"
                    f"{rendered_recovery_hints}\n"
                    "These recovery hints override the original likely-sheet guess when the previous tool call failed on the wrong worksheet.\n\n"
                )

            discovery_step_feedback = ""
            if allow_multi_sheet_discovery:
                discovery_step_feedback = (
                    "MULTI-SHEET DISCOVERY:\n"
                    "If the right worksheet or columns are unclear, call describe_tabular_file without sheet_name as an exploration step, then continue with one or more analytical tool calls. You may need multiple tool rounds.\n\n"
                )

            related_sheet_feedback = ""
            if workbook_related_sheet_hints:
                rendered_related_sheet_hints = "\n".join(
                    f"- {workbook_name}: {', '.join(related_sheets)}"
                    for workbook_name, related_sheets in workbook_related_sheet_hints.items()
                    if related_sheets
                )
                if rendered_related_sheet_hints:
                    related_sheet_instruction = (
                        'Use these worksheets to satisfy cross-sheet profile and related-record requests.'
                        if entity_lookup_mode else
                        'Use these worksheets together when the answer may require one sheet for entities and another for facts.'
                    )
                    related_sheet_feedback = (
                        "QUESTION-RELEVANT WORKSHEET HINTS:\n"
                        f"{rendered_related_sheet_hints}\n"
                        f"{related_sheet_instruction}\n\n"
                    )

            cross_sheet_bridge_feedback = ""
            if workbook_cross_sheet_bridge_hints:
                rendered_bridge_hints = "\n".join(
                    (
                        f"- {workbook_name}: reference worksheet '{bridge_hint['reference_sheet']}' "
                        f"({bridge_hint['reference_row_count']} rows); fact worksheet '{bridge_hint['fact_sheet']}' "
                        f"({bridge_hint['fact_row_count']} rows)"
                    )
                    for workbook_name, bridge_hint in workbook_cross_sheet_bridge_hints.items()
                )
                cross_sheet_bridge_feedback = (
                    "CROSS-SHEET BRIDGE PLAN:\n"
                    f"{rendered_bridge_hints}\n"
                    "For grouped cross-sheet questions, first use the reference worksheet to identify canonical entity or category names, then compute the requested metric from the fact worksheet. Prefer shared identifier or name columns over yes/no, boolean, or membership-flag columns.\n\n"
                )

            if entity_lookup_mode:
                entity_retry_prefix = retry_prefix
                if force_tool_use:
                    entity_retry_prefix = (
                        "RETRY MODE: Your previous attempt did not complete the related-record lookup. "
                        "You MUST call one or more analytical tabular_processing plugin functions before writing any answer text. "
                        "Query the missing related worksheets explicitly with sheet_name.\n\n"
                    )

                return (
                    "You are a workbook entity lookup analyst. The full dataset is available through the "
                    "tabular_processing plugin functions. The user is asking for one entity and related records across worksheets. "
                    "You MUST use one or more tabular_processing plugin functions before answering. Never answer from the schema preview alone.\n\n"
                    f"{entity_retry_prefix}"
                    f"{tool_error_feedback}"
                    f"{execution_gap_feedback}"
                    f"{discovery_feedback}"
                    f"{recovery_sheet_feedback}"
                    f"{sheet_hint_feedback}"
                    f"{related_sheet_feedback}"
                    f"{discovery_step_feedback}"
                    f"{missing_sheet_feedback}"
                    f"FILE SCHEMAS:\n"
                    f"{schema_context}\n\n"
                    f"AVAILABLE FUNCTIONS: {', '.join(allowed_function_names)}.\n\n"
                    + (
                        "Workbook discovery is available through describe_tabular_file. Discovery-only results do NOT complete the analysis. After exploration, continue with analytical functions before answering.\n\n"
                        if allow_multi_sheet_discovery else
                        "Discovery functions are not available in this analysis run because schema context is already pre-loaded.\n\n"
                    )
                    +
                    "IMPORTANT:\n"
                    "0. Use the source_context listed in FILE SCHEMAS for the matching filename when calling tabular_processing functions.\n"
                    "1. If the right worksheet is unclear on a multi-sheet workbook, you may call describe_tabular_file without sheet_name first, then continue with analytical tool calls.\n"
                    "2. If the question includes an exact identifier, exact entity name, or asks where a topic or value appears and the correct starting worksheet or column is unclear, begin with search_rows, filter_rows, or query_tabular_data without sheet_name so the plugin can perform a cross-sheet discovery search. Omit search_columns on search_rows to search all columns, and use return_columns to surface the fields most relevant to the lookup.\n"
                    "3. After the first discovery step, pass sheet_name='<name>' on follow-up analytical calls for multi-sheet workbooks. Do not rely on a default sheet for cross-sheet entity lookups.\n"
                    "4. Use search_rows, filter_rows, or query_tabular_data first when you need full matching rows. Use lookup_value only when you already know the exact worksheet and target column.\n"
                    "5. Do not start with aggregate_column, group_by_aggregate, or group_by_datetime_component until you have located the relevant entity rows.\n"
                    "6. When using query_tabular_data, use simple DataFrame.query() syntax with backticked column names for columns containing spaces. Avoid method calls such as .str.lower() or .astype(...).\n"
                    "7. Then query other relevant worksheets explicitly to collect related records.\n"
                    "8. When a retrieved row contains a secondary identifier such as ReturnID, CaseID, AccountID, PaymentID, W2ID, or Form1099ID, reuse it to query dependent worksheets.\n"
                    "9. Do not stop after the first successful row if the question asks for related records across sheets.\n"
                    "10. If a requested record type has no corresponding worksheet in the workbook, say that the workbook does not contain that record type.\n"
                    "11. Clearly distinguish between no matching rows and no corresponding worksheet.\n"
                    "12. Summarize concrete found records sheet-by-sheet using the tool results, not schema placeholders.\n"
                    "13. For count or percentage questions involving a cohort defined on one sheet and facts on another, prefer get_distinct_values, count_rows, filter_rows_by_related_values, or count_rows_by_related_values over manually counting sampled rows.\n"
                    "14. Use normalize_match=true when matching names, owners, assignees, engineers, or similar entity-text columns across worksheets.\n"
                    "15. If a successful tool result reports returned_rows == total_matches or returned_values == distinct_count, treat that as the full matching result set. Do not claim that only sample rows or workbook metadata are available in that case.\n"
                    "16. Do not mention hypothetical follow-up analyses, parser errors, or failed attempts unless the user explicitly asked about failures and you have actual tool error output to report."
                )

            return (
                "You are a data analyst. The full dataset is available through the "
                "tabular_processing plugin functions. You MUST use one or more "
                "tabular_processing plugin functions before answering. Never answer from "
                "the schema preview alone. Never say that you would need to run the "
                "analysis later — run it now.\n\n"
                f"{retry_prefix}"
                f"{tool_error_feedback}"
                f"{execution_gap_feedback}"
                f"{discovery_feedback}"
                f"{attachment_follow_up_feedback}"
                f"{recovery_sheet_feedback}"
                f"{sheet_hint_feedback}"
                f"{related_sheet_feedback}"
                f"{cross_sheet_bridge_feedback}"
                f"{discovery_step_feedback}"
                f"{missing_sheet_feedback}"
                f"FILE SCHEMAS:\n"
                f"{schema_context}\n\n"
                f"AVAILABLE FUNCTIONS: {', '.join(allowed_function_names)} for year/quarter/month/week/day/hour trend analysis"
                + (
                    "; document_search search_documents, retrieve_document_chunks, summarize_document for attachment-backed rows.\n\n"
                    if attachment_search_function_names else
                    ".\n\n"
                )
                + (
                    "Workbook discovery is available through describe_tabular_file. Discovery-only results do NOT complete the analysis. After exploration, continue with analytical functions before answering.\n\n"
                    if allow_multi_sheet_discovery else
                    "Discovery functions are not available in this analysis run because schema context is already pre-loaded.\n\n"
                )
                +
                "IMPORTANT:\n"
                "1. Use the pre-loaded schema to pick the correct columns, then call the plugin functions. Use the source_context listed in FILE SCHEMAS for the matching filename.\n"
                "2. For multi-sheet workbooks, review the sheet_directory to find the most relevant sheet for the question. If the right worksheet is still unclear, call describe_tabular_file without sheet_name, then continue with analytical calls. Pass sheet_name='<name>' in follow-up analytical tool calls unless a trustworthy default sheet has already been established or you are intentionally doing an initial cross-sheet discovery step. If a CROSS-SHEET BRIDGE PLAN is provided, query the listed worksheets explicitly and do not rely on a default sheet.\n"
                "3. If the question includes an exact identifier or asks where a topic, phrase, path, code, or other value appears and the correct starting worksheet or column is unclear, begin with search_rows, filter_rows, or query_tabular_data without sheet_name so the plugin can perform a cross-sheet discovery search. Omit search_columns on search_rows to search all columns, and use return_columns to surface the columns most relevant to the question.\n"
                "4. If a previous tool error says a requested column is missing on the current sheet and suggests candidate sheets, switch to one of those candidate sheets immediately.\n"
                "5. For account/category lookup questions at a specific period or metric, use lookup_value first. Provide lookup_column, lookup_value, and target_column.\n"
                "6. If lookup_value is not sufficient, use search_rows, filter_rows, or query_tabular_data on the relevant label or text columns, then read the requested period or target column.\n"
                "7. For deterministic how-many questions, use count_rows instead of estimating counts from partial returned rows. Use get_distinct_values when the answer depends on the unique values present in a column. When the cohort is defined by two literal conditions on different columns, prefer count_rows, get_distinct_values, or filter_rows with filter_column/filter_operator/filter_value plus additional_filter_column/additional_filter_operator/additional_filter_value instead of a broad query_tabular_data call.\n"
                "8. When URLs, links, sites, or regex-like identifiers are embedded inside a text column, prefer get_distinct_values with extract_mode='url' or extract_mode='regex' after filtering the relevant cohort. Use url_path_segments when the question asks for higher-level URL roots rather than full page paths.\n"
                "9. If whether an embedded URL, site, link, or identifier counts depends on surrounding text in the original cell rather than the extracted value itself, search/filter the original text column first. Prefer filter_rows when the matching row context matters, and return the full matching rows when the cohort is modest enough to fit comfortably.\n"
                "10. Do not classify extracted URLs solely by whether the URL text itself contains the keyword when the original cell text already defines the category.\n"
                "11. For cohort, membership, ownership-share, or percentage questions where one sheet defines the group and another sheet contains the fact rows, use get_distinct_values, filter_rows_by_related_values, or count_rows_by_related_values.\n"
                "12. When the question asks for one named member's share within that cohort, prefer count_rows_by_related_values and either read source_value_match_counts from the helper result or rerun count_rows_by_related_values with source_filter_column/source_filter_value on the reference sheet. Do not fall back to query_tabular_data or filter_rows on the fact sheet with a guessed exact text value unless the workbook already exposed that canonical target value.\n"
                "13. Use normalize_match=true when matching names, owners, assignees, engineers, or similar entity-text columns across worksheets.\n"
                "14. Only use aggregate_column when the user explicitly asks for a sum, average, min, max, or count across rows and count_rows is not the simpler deterministic option.\n"
                "15. For time-based questions on datetime columns, use group_by_datetime_component.\n"
                "16. For threshold, ranking, comparison, or correlation-like questions, first filter/query the relevant rows, then compute grouped metrics.\n"
                "17. When the question asks for grouped results for each entity or category and a cross-sheet bridge plan or relationship hint is available, use the reference worksheet to identify the canonical entities or categories and the fact worksheet to compute the metric. Do not answer 'each X' by grouping a yes/no, boolean, or membership-flag column unless the user explicitly asked about that flag.\n"
                "18. When the question asks for rows satisfying multiple conditions, prefer one combined query_expression using and/or instead of separate broad queries that you plan to intersect later.\n"
                "19. Batch multiple independent function calls in a SINGLE response whenever possible.\n"
                "20. Keep max_rows as small as possible. Only increase it when the user explicitly asked for an exhaustive row list or export, or when the full matching row context is required and the cohort is modest; otherwise return total_matches plus representative rows. If a prior result reports total_matches > returned_rows or distinct_count > returned_values for a full-list question, rerun with a higher max_rows or max_values before answering.\n"
                "21. For analytical questions, prefer deterministic counts plus lookup/filter/query/grouped computations over raw row or preview output.\n"
                "22. For identifier-based workbook questions, locate the identifier on the correct sheet before explaining downstream calculations.\n"
                "23. For peak, busiest, highest, or lowest questions, use grouped functions and inspect the highest_group, highest_value, lowest_group, and lowest_value summary fields.\n"
                "24. Return only computed findings and name the strongest drivers clearly.\n"
                "25. If a successful tool result reports returned_rows == total_matches or returned_values == distinct_count, treat that as the full matching result set. Do not claim that only sample rows or workbook metadata are available in that case.\n"
                "26. If returned rows include attachment or file references and the user's task depends on the substantive content of those rows, use document_search to retrieve the referenced document text before answering. Search by exact file name or basename first, then retrieve chunks or summarize the matched document.\n"
                "27. Do not claim that attachment text is unavailable when you have already retrieved row-linked document text through document_search or through related-document excerpts in the prompt context.\n"
                "28. Do not mention hypothetical follow-up analyses, parser errors, or failed attempts unless the user explicitly asked about failures and you have actual tool error output to report.\n"
                "29. When using query_tabular_data, use simple DataFrame.query() syntax with backticked column names for columns containing spaces. Avoid method calls such as .str.lower(), .astype(...), or other Python expressions that DataFrame.query() may reject."
            )

        baseline_invocations = plugin_logger.get_invocations_for_conversation(
            user_id,
            conversation_id,
            limit=1000
        )
        baseline_invocation_count = len(baseline_invocations)
        previous_tool_error_messages = []
        previous_execution_gap_messages = []
        previous_discovery_feedback_messages = []
        analysis_requires_immediate_tool_choice = has_multi_sheet_workbook and not schema_summary_mode

        if tabular_model_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
            if schema_summary_mode:
                for file_context in analysis_file_contexts:
                    describe_arguments = {
                        'user_id': user_id,
                        'conversation_id': conversation_id,
                        'filename': file_context['file_name'],
                        'source': file_context.get('source_hint', source_hint),
                    }
                    if file_context.get('group_id'):
                        describe_arguments['group_id'] = file_context.get('group_id')
                    if file_context.get('public_workspace_id'):
                        describe_arguments['public_workspace_id'] = file_context.get('public_workspace_id')
                    await tabular_plugin.describe_tabular_file(**describe_arguments)

                invocations_after = plugin_logger.get_invocations_for_conversation(
                    user_id,
                    conversation_id,
                    limit=1000,
                )
                schema_invocations = filter_tabular_citation_invocations(
                    get_new_plugin_invocations(invocations_after, baseline_invocation_count)
                )
                if schema_invocations:
                    return build_tabular_schema_summary_fallback_from_invocations(
                        user_question,
                        schema_invocations,
                    )
                return None

            reviewer_recovery = await maybe_recover_tabular_analysis_with_llm_reviewer(
                chat_service=chat_service,
                kernel=kernel,
                tabular_plugin=tabular_plugin,
                plugin_logger=plugin_logger,
                user_question=user_question,
                schema_context=schema_context,
                source_context=source_context,
                analysis_file_contexts=analysis_file_contexts,
                user_id=user_id,
                conversation_id=conversation_id,
                execution_mode=execution_mode,
                allowed_function_names=allowed_function_names,
                workbook_sheet_hints=workbook_sheet_hints,
                workbook_related_sheet_hints=workbook_related_sheet_hints,
                workbook_cross_sheet_bridge_hints=workbook_cross_sheet_bridge_hints,
                tool_error_messages=previous_tool_error_messages,
                execution_gap_messages=previous_execution_gap_messages,
                discovery_feedback_messages=previous_discovery_feedback_messages,
                fallback_source_hint=source_hint,
                fallback_group_id=group_id,
                fallback_public_workspace_id=public_workspace_id,
            )
            if reviewer_recovery and reviewer_recovery.get('fallback'):
                return reviewer_recovery['fallback']

            log_event(
                '[Tabular SK Analysis] Anthropic tabular planner did not produce computed tool results',
                level=logging.WARNING,
            )
            return None

        for attempt_number in range(1, 4):
            force_tool_use = attempt_number > 1 or (attempt_number == 1 and analysis_requires_immediate_tool_choice)
            if callable(thought_callback) and attempt_number > 1:
                await emit_tabular_analysis_lifecycle_thought(
                    thought_callback,
                    f"Retrying workbook analysis (attempt {attempt_number} of 3)",
                    detail='Continuing tabular analysis after the previous pass did not finish with a usable final answer.',
                    title=f"Analyzing workbook evidence (attempt {attempt_number} of 3)",
                    state='running',
                    phase='retry',
                    attempt_number=attempt_number,
                    attempt_count=3,
                )

            # 4. Build chat history with pre-loaded schemas
            chat_history = SKChatHistory()
            chat_history.add_system_message(build_system_prompt(
                force_tool_use=force_tool_use,
                tool_error_messages=previous_tool_error_messages,
                execution_gap_messages=previous_execution_gap_messages,
                discovery_feedback_messages=previous_discovery_feedback_messages,
            ))
            for system_message in build_tabular_fact_memory_messages(
                scope_id=fact_memory_scope_id,
                scope_type=fact_memory_scope_type,
                query_text=user_question,
                conversation_id=conversation_id,
                agent_id=None,
                enabled=fact_memory_enabled,
            ):
                chat_history.add_system_message(system_message['content'])

            chat_history.add_user_message(
                f"Analyze the tabular data to answer: {user_question}\n"
                f"Use user_id='{user_id}', conversation_id='{conversation_id}'.\n"
                f"{source_context}"
            )

            # 5. Execute with auto function calling
            execution_settings = AzureChatPromptExecutionSettings(
                service_id="tabular-analysis",
                function_choice_behavior=(
                    FunctionChoiceBehavior.Required(
                        maximum_auto_invoke_attempts=20,
                        filters=allowed_function_filters,
                    )
                    if force_tool_use else
                    FunctionChoiceBehavior.Auto(
                        maximum_auto_invoke_attempts=20,
                        filters=allowed_function_filters,
                    )
                ),
            )

            result = None
            synthesis_exception = None
            try:
                result = await chat_service.get_chat_message_contents(
                    chat_history, execution_settings, kernel=kernel
                )
            except Exception as exc:
                synthesis_exception = exc
                log_event(
                    f"[Tabular SK Analysis] Attempt {attempt_number} synthesis failed after tool execution setup: {exc}",
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )

            invocations_after = plugin_logger.get_invocations_for_conversation(
                user_id,
                conversation_id,
                limit=1000
            )
            new_invocations = get_new_plugin_invocations(invocations_after, baseline_invocation_count)
            new_invocation_count = len(new_invocations)
            discovery_invocations, analytical_invocations, _ = split_tabular_plugin_invocations(new_invocations)
            successful_analytical_invocations, failed_analytical_invocations = split_tabular_analysis_invocations(new_invocations)
            successful_document_search = tabular_document_search_invocations_succeeded(new_invocations)
            successful_schema_summary_invocations = []
            failed_schema_summary_invocations = []
            for invocation in discovery_invocations:
                if getattr(invocation, 'function_name', '') != 'describe_tabular_file':
                    continue
                if get_tabular_invocation_error_message(invocation):
                    failed_schema_summary_invocations.append(invocation)
                else:
                    successful_schema_summary_invocations.append(invocation)

            if synthesis_exception is not None:
                raw_tool_fallback = None
                if not schema_summary_mode:
                    raw_tool_fallback = build_tabular_analysis_fallback_from_invocations(
                        successful_analytical_invocations,
                    )

                if raw_tool_fallback:
                    log_event(
                        f"[Tabular SK Analysis] Falling back to raw successful tool summaries after attempt {attempt_number} synthesis error",
                        extra={
                            'successful_tool_count': len(successful_analytical_invocations),
                            'attempt_number': attempt_number,
                        },
                        level=logging.WARNING,
                    )
                    return raw_tool_fallback

                log_event(
                    f"[Tabular SK Analysis] Attempt {attempt_number} could not recover from synthesis error",
                    extra={
                        'successful_tool_count': len(successful_analytical_invocations),
                        'failed_tool_count': len(failed_analytical_invocations),
                        'attempt_number': attempt_number,
                    },
                    level=logging.WARNING,
                )
                break

            if result and result[0].content:
                analysis = result[0].content.strip()
                if len(analysis) > 20000:
                    analysis = analysis[:20000] + "\n[Analysis truncated]"

                if schema_summary_mode:
                    if successful_schema_summary_invocations:
                        log_event(
                            f"[Tabular SK Analysis] Schema summary complete via {len(successful_schema_summary_invocations)} workbook tool call(s) on attempt {attempt_number}",
                            level=logging.INFO,
                        )
                        return analysis

                    if failed_schema_summary_invocations:
                        previous_tool_error_messages = summarize_tabular_invocation_errors(failed_schema_summary_invocations)
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} used workbook schema tool(s) but all returned errors; retrying",
                            extra={
                                'tool_errors': previous_tool_error_messages,
                                'failed_tool_count': len(failed_schema_summary_invocations),
                            },
                            level=logging.WARNING,
                        )
                    elif analytical_invocations:
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} used analytical tool(s) during schema-summary mode without usable workbook results; retrying",
                            level=logging.WARNING,
                        )
                    elif discovery_invocations:
                        discovery_function_names = sorted({
                            invocation.function_name for invocation in discovery_invocations
                        })
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} used only discovery tool(s) {discovery_function_names} without usable workbook summary; retrying",
                            level=logging.WARNING,
                        )
                    elif new_invocation_count > 0:
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} used unsupported tool(s) without usable workbook results; retrying",
                            level=logging.WARNING,
                        )
                    else:
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} returned narrative without workbook schema tool use; retrying",
                            level=logging.WARNING,
                        )
                else:
                    if successful_analytical_invocations:
                        previous_tool_error_messages = []
                        previous_failed_call_parameters = []
                        previous_discovery_feedback_messages = []
                        execution_gap_messages = []
                        selected_sheets = []
                        coverage_summary = get_tabular_result_coverage_summary(
                            successful_analytical_invocations
                        )
                        retry_gap_messages = build_tabular_success_execution_gap_messages(
                            user_question,
                            analysis,
                            successful_analytical_invocations,
                        )

                        if entity_lookup_mode:
                            selected_sheets = get_tabular_invocation_selected_sheets(successful_analytical_invocations)

                            # Cross-sheet results ("ALL (cross-sheet search)") already span
                            # the entire workbook — no execution gap for sheet coverage.
                            has_cross_sheet_result = any(
                                'cross-sheet' in (s or '').lower() for s in selected_sheets
                            )

                            if len(selected_sheets) <= 1 and not has_cross_sheet_result:
                                rendered_selected_sheets = ', '.join(selected_sheets) if selected_sheets else 'unknown worksheet'
                                execution_gap_messages.append(
                                    f"Previous attempt only queried worksheet(s): {rendered_selected_sheets}. The question asks for related records across worksheets, so query additional relevant sheets explicitly with sheet_name."
                                )

                        execution_gap_messages.extend(retry_gap_messages)

                        if (
                            attachment_search_function_names
                            and question_requests_attachment_backed_row_follow_up(user_question)
                            and tabular_invocations_include_attachment_candidates(successful_analytical_invocations)
                            and not successful_document_search
                        ):
                            execution_gap_messages.append(
                                'Previous attempt returned rows that reference attachments or external files but did not retrieve the referenced document text. Use document_search to resolve the referenced file names and incorporate that evidence before answering.'
                            )

                        if execution_gap_messages and attempt_number < 3:
                            previous_execution_gap_messages = execution_gap_messages
                            log_event(
                                f"[Tabular SK Analysis] Attempt {attempt_number} analysis was incomplete despite successful tool calls; retrying",
                                extra={
                                    'selected_sheets': selected_sheets,
                                    'execution_gaps': previous_execution_gap_messages,
                                    'successful_tool_count': len(successful_analytical_invocations),
                                    'has_full_result_coverage': coverage_summary.get('has_full_result_coverage', False),
                                    'has_partial_result_coverage': coverage_summary.get('has_partial_result_coverage', False),
                                    'entity_lookup_mode': entity_lookup_mode,
                                },
                                level=logging.WARNING,
                            )
                            baseline_invocation_count = len(invocations_after)
                            continue

                        previous_execution_gap_messages = []
                        log_event(
                            f"[Tabular SK Analysis] Analysis complete via {len(successful_analytical_invocations)} analytical tool call(s) on attempt {attempt_number}",
                            level=logging.INFO
                        )
                        return analysis

                    if failed_analytical_invocations:
                        previous_tool_error_messages = summarize_tabular_invocation_errors(failed_analytical_invocations)
                        previous_execution_gap_messages = []
                        retry_sheet_overrides = get_tabular_retry_sheet_overrides(failed_analytical_invocations)
                        for workbook_name, override_payload in retry_sheet_overrides.items():
                            blob_location = workbook_blob_locations.get(workbook_name)
                            if not blob_location:
                                continue

                            container_name, blob_name = blob_location
                            tabular_plugin.set_default_sheet(
                                container_name,
                                blob_name,
                                override_payload['sheet_name'],
                            )

                        if retry_sheet_overrides:
                            log_event(
                                f"[Tabular SK Analysis] Attempt {attempt_number} selected retry worksheet override(s): {retry_sheet_overrides}",
                                level=logging.INFO,
                            )
                        # For entity_lookup mode, extract and cache concrete call parameters
                        # so the retry prompt can generate per-sheet corrected call examples
                        if entity_lookup_mode:
                            seen_entity_filters = set()
                            entity_call_params = []
                            for invoc in failed_analytical_invocations:
                                error_msg = get_tabular_invocation_error_message(invoc) or ''
                                if 'Specify sheet_name or sheet_index on analytical calls.' not in error_msg:
                                    continue
                                invoc_params = getattr(invoc, 'parameters', {}) or {}
                                fn = getattr(invoc, 'function_name', '')
                                fname = str(invoc_params.get('filename') or '').strip()
                                if fn == 'filter_rows':
                                    col = str(invoc_params.get('column') or '').strip()
                                    op = str(invoc_params.get('operator') or '==').strip()
                                    val = str(invoc_params.get('value') or '').strip()
                                elif fn == 'lookup_value':
                                    col = str(invoc_params.get('lookup_column') or '').strip()
                                    op = '=='
                                    val = str(invoc_params.get('lookup_value') or '').strip()
                                else:
                                    continue
                                if not fname or not col or not val:
                                    continue
                                filter_key = (fname, col, val)
                                if filter_key in seen_entity_filters:
                                    continue
                                seen_entity_filters.add(filter_key)
                                entity_call_params.append({
                                    'filename': fname,
                                    'column': col,
                                    'operator': op,
                                    'value': val,
                                })
                            previous_failed_call_parameters = entity_call_params
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} used analytical tool(s) but all returned errors; retrying",
                            extra={
                                'tool_errors': previous_tool_error_messages,
                                'failed_tool_count': len(failed_analytical_invocations),
                            },
                            level=logging.WARNING
                        )
                    elif analytical_invocations:
                        previous_execution_gap_messages = []
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} used analytical tool(s) without usable computed results; retrying",
                            level=logging.WARNING
                        )
                    elif discovery_invocations:
                        previous_discovery_feedback_messages = summarize_tabular_discovery_invocations(
                            successful_schema_summary_invocations or discovery_invocations,
                        )
                        previous_execution_gap_messages = [
                            'Previous attempt explored workbook structure but did not execute analytical functions. Continue with analytical tool calls now.'
                        ]
                        discovery_function_names = sorted({
                            invocation.function_name for invocation in discovery_invocations
                        })
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} used only discovery tool(s) {discovery_function_names} without computed analysis; retrying",
                            level=logging.WARNING
                        )
                    elif new_invocation_count > 0:
                        previous_discovery_feedback_messages = []
                        previous_execution_gap_messages = []
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} used unsupported tool(s) without computed analysis; retrying",
                            level=logging.WARNING
                        )
                    else:
                        previous_discovery_feedback_messages = []
                        previous_execution_gap_messages = (
                            ['Previous attempt did not use any tools. Start with workbook discovery if the right worksheet is unclear, then continue with analytical tool calls.']
                            if allow_multi_sheet_discovery else
                            []
                        )
                        log_event(
                            f"[Tabular SK Analysis] Attempt {attempt_number} returned narrative without tool use; retrying",
                            level=logging.WARNING
                        )

            else:
                if schema_summary_mode and failed_schema_summary_invocations:
                    previous_tool_error_messages = summarize_tabular_invocation_errors(failed_schema_summary_invocations)
                    log_event(
                        f"[Tabular SK Analysis] Attempt {attempt_number} returned no content after workbook tool errors; retrying",
                        extra={
                            'tool_errors': previous_tool_error_messages,
                            'failed_tool_count': len(failed_schema_summary_invocations),
                        },
                        level=logging.WARNING,
                    )
                elif failed_analytical_invocations:
                    previous_tool_error_messages = summarize_tabular_invocation_errors(failed_analytical_invocations)
                    previous_discovery_feedback_messages = []
                    previous_execution_gap_messages = []
                    log_event(
                        f"[Tabular SK Analysis] Attempt {attempt_number} returned no content after tool errors; retrying",
                        extra={
                            'tool_errors': previous_tool_error_messages,
                            'failed_tool_count': len(failed_analytical_invocations),
                        },
                        level=logging.WARNING
                    )
                else:
                    log_event(
                        f"[Tabular SK Analysis] Attempt {attempt_number} returned no content",
                        level=logging.WARNING
                    )

            baseline_invocation_count = len(invocations_after)

        reviewer_recovery = None
        if has_multi_sheet_workbook and not schema_summary_mode:
            reviewer_recovery = await maybe_recover_tabular_analysis_with_llm_reviewer(
                chat_service=chat_service,
                kernel=kernel,
                tabular_plugin=tabular_plugin,
                plugin_logger=plugin_logger,
                user_question=user_question,
                schema_context=schema_context,
                source_context=source_context,
                analysis_file_contexts=analysis_file_contexts,
                user_id=user_id,
                conversation_id=conversation_id,
                execution_mode=execution_mode,
                allowed_function_names=allowed_function_names,
                workbook_sheet_hints=workbook_sheet_hints,
                workbook_related_sheet_hints=workbook_related_sheet_hints,
                workbook_cross_sheet_bridge_hints=workbook_cross_sheet_bridge_hints,
                tool_error_messages=previous_tool_error_messages,
                execution_gap_messages=previous_execution_gap_messages,
                discovery_feedback_messages=previous_discovery_feedback_messages,
                fallback_source_hint=source_hint,
                fallback_group_id=group_id,
                fallback_public_workspace_id=public_workspace_id,
            )
            if reviewer_recovery and reviewer_recovery.get('fallback'):
                return reviewer_recovery['fallback']

        log_event("[Tabular SK Analysis] Unable to obtain computed tool-backed results", level=logging.WARNING)
        return None

    except Exception as e:
        log_event(f"[Tabular SK Analysis] Error: {e}", level=logging.WARNING, exceptionTraceback=True)
        return None

def collect_tabular_sk_citations(user_id, conversation_id):
    """Collect plugin invocations from the tabular SK analysis and convert to citation format."""
    from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger

    plugin_logger = get_plugin_logger()
    plugin_invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id)
    plugin_invocations = filter_tabular_citation_invocations(plugin_invocations)

    if not plugin_invocations:
        return []

    citations = []
    for inv in plugin_invocations:
        timestamp_str = None
        if inv.timestamp:
            if hasattr(inv.timestamp, 'isoformat'):
                timestamp_str = inv.timestamp.isoformat()
            else:
                timestamp_str = str(inv.timestamp)

        parameters = getattr(inv, 'parameters', {}) or {}
        sheet_name = parameters.get('sheet_name')
        sheet_index = parameters.get('sheet_index')
        tool_name = build_agent_citation_tool_label(
            inv.plugin_name,
            inv.function_name,
            parameters,
            inv.result,
        )
        if sheet_name:
            tool_name = f"{tool_name} [{sheet_name}]"
        elif sheet_index not in (None, ''):
            tool_name = f"{tool_name} [sheet #{sheet_index}]"

        citation = {
            'tool_name': tool_name,
            'function_name': inv.function_name,
            'plugin_name': inv.plugin_name,
            'function_arguments': make_json_serializable(parameters),
            'function_result': make_json_serializable(inv.result),
            'duration_ms': inv.duration_ms,
            'timestamp': timestamp_str,
            'success': inv.success,
            'error_message': make_json_serializable(inv.error_message),
            'user_id': inv.user_id,
            'sheet_name': sheet_name,
            'sheet_index': sheet_index,
        }
        citations.append(citation)

    log_event(f"[Tabular SK Citations] Collected {len(citations)} tool execution citations", level=logging.INFO)
    return citations


def is_tabular_filename(filename):
    """Return True when the filename has a supported tabular extension."""
    if not filename or not isinstance(filename, str):
        return False

    _, extension = os.path.splitext(filename.strip().lower())
    return extension.lstrip('.') in TABULAR_EXTENSIONS


def get_citation_location(file_name, page_number=None, chunk_text=None, sheet_name=None):
    """Return a display label/value pair for a citation location."""
    if sheet_name:
        return 'Sheet', str(sheet_name)

    normalized_chunk_text = (chunk_text or '').strip()
    if is_tabular_filename(file_name) and (
        normalized_chunk_text.startswith('Tabular workbook:')
        or normalized_chunk_text.startswith('Tabular data file:')
    ):
        return 'Location', 'Workbook Schema'

    return 'Page', str(page_number or 1)


def get_document_container_for_scope(document_scope):
    """Return the Cosmos documents container that matches the workspace scope."""
    if document_scope == 'group':
        return cosmos_group_documents_container
    if document_scope == 'public':
        return cosmos_public_documents_container
    return cosmos_user_documents_container


def get_document_containers_for_scope(document_scope):
    """Return workspace source/container pairs for the requested document scope."""
    if document_scope == 'group':
        return [('group', cosmos_group_documents_container)]
    if document_scope == 'public':
        return [('public', cosmos_public_documents_container)]
    if document_scope == 'all':
        return [
            ('workspace', cosmos_user_documents_container),
            ('group', cosmos_group_documents_container),
            ('public', cosmos_public_documents_container),
        ]
    return [('workspace', cosmos_user_documents_container)]


def build_tabular_file_context(file_name, source_hint='workspace', group_id=None, public_workspace_id=None):
    """Build normalized source metadata for a tabular file when enough scope is known."""
    normalized_file_name = str(file_name or '').strip()
    if not is_tabular_filename(normalized_file_name):
        return None

    normalized_source_hint = str(source_hint or 'workspace').strip().lower()
    if normalized_source_hint == 'personal':
        normalized_source_hint = 'workspace'
    if normalized_source_hint not in {'workspace', 'chat', 'group', 'public'}:
        normalized_source_hint = 'workspace'

    normalized_group_id = str(group_id or '').strip() or None
    normalized_public_workspace_id = str(public_workspace_id or '').strip() or None

    if normalized_source_hint == 'group' and not normalized_group_id:
        normalized_source_hint = 'workspace'
    if normalized_source_hint == 'public' and not normalized_public_workspace_id:
        normalized_source_hint = 'workspace'

    context = {
        'file_name': normalized_file_name,
        'source_hint': normalized_source_hint,
    }
    if normalized_source_hint == 'group' and normalized_group_id:
        context['group_id'] = normalized_group_id
    if normalized_source_hint == 'public' and normalized_public_workspace_id:
        context['public_workspace_id'] = normalized_public_workspace_id
    return context


def dedupe_tabular_file_contexts(file_contexts=None):
    """Return unique tabular file contexts while preserving the first-seen order."""
    unique_contexts = []
    seen_contexts = set()

    for file_context in file_contexts or []:
        if not isinstance(file_context, Mapping):
            continue

        context_key = (
            str(file_context.get('file_name') or '').strip(),
            str(file_context.get('source_hint') or 'workspace').strip().lower(),
            str(file_context.get('group_id') or '').strip(),
            str(file_context.get('public_workspace_id') or '').strip(),
        )
        if not context_key[0] or context_key in seen_contexts:
            continue

        seen_contexts.add(context_key)
        unique_contexts.append(dict(file_context))

    return unique_contexts


def infer_tabular_source_context_from_document(source_doc, document_scope='personal',
                                              active_group_id=None, active_public_workspace_id=None):
    """Infer tabular file source metadata from a search result or citation document."""
    if not isinstance(source_doc, Mapping):
        return None

    file_name = source_doc.get('file_name')
    doc_group_id = str(source_doc.get('group_id') or '').strip() or None
    doc_public_workspace_id = str(source_doc.get('public_workspace_id') or '').strip() or None

    if doc_public_workspace_id:
        return build_tabular_file_context(
            file_name,
            source_hint='public',
            public_workspace_id=doc_public_workspace_id,
        )
    if doc_group_id:
        return build_tabular_file_context(
            file_name,
            source_hint='group',
            group_id=doc_group_id,
        )
    if document_scope == 'group':
        return build_tabular_file_context(
            file_name,
            source_hint='group',
            group_id=active_group_id,
        )
    if document_scope == 'public':
        return build_tabular_file_context(
            file_name,
            source_hint='public',
            public_workspace_id=active_public_workspace_id,
        )
    return build_tabular_file_context(file_name, source_hint='workspace')


def get_selected_workspace_tabular_file_contexts(selected_document_ids=None, selected_document_id=None,
                                                 document_scope='personal', user_id=None,
                                                 active_group_id=None, active_group_ids=None,
                                                 active_public_workspace_id=None,
                                                 active_public_workspace_ids=None):
    """Resolve explicitly selected workspace documents and return tabular source contexts."""
    selected_ids = list(selected_document_ids or [])
    if not selected_ids and selected_document_id and selected_document_id != 'all':
        selected_ids = [selected_document_id]

    if not selected_ids:
        return []

    tabular_file_contexts = []

    for doc_id in selected_ids:
        if not doc_id or doc_id == 'all':
            continue

        try:
            doc_info = _resolve_chat_selected_document_metadata(
                doc_id,
                user_id=user_id,
                document_scope=document_scope,
                active_group_id=active_group_id,
                active_group_ids=active_group_ids,
                active_public_workspace_id=active_public_workspace_id,
                active_public_workspace_ids=active_public_workspace_ids,
            )
            if not doc_info:
                continue

            file_context = build_tabular_file_context(
                doc_info.get('file_name') or doc_info.get('title'),
                source_hint=doc_info.get('source_hint', 'workspace'),
                group_id=doc_info.get('group_id') or active_group_id,
                public_workspace_id=doc_info.get('public_workspace_id') or active_public_workspace_id,
            )
            if file_context:
                tabular_file_contexts.append(file_context)
        except Exception as e:
            log_event(
                f"[Tabular SK Analysis] Failed to resolve selected document '{doc_id}': {e}",
                level=logging.WARNING
            )

    return dedupe_tabular_file_contexts(tabular_file_contexts)


def collect_workspace_tabular_file_contexts(combined_documents=None, selected_document_ids=None,
                                            selected_document_id=None, document_scope='personal',
                                            user_id=None, active_group_id=None,
                                            active_group_ids=None,
                                            active_public_workspace_id=None,
                                            active_public_workspace_ids=None):
    """Collect tabular source contexts from search results and explicit workspace selection."""
    tabular_file_contexts = []

    for source_doc in combined_documents or []:
        file_context = infer_tabular_source_context_from_document(
            source_doc,
            document_scope=document_scope,
            active_group_id=active_group_id,
            active_public_workspace_id=active_public_workspace_id,
        )
        if file_context:
            tabular_file_contexts.append(file_context)

    tabular_file_contexts.extend(get_selected_workspace_tabular_file_contexts(
        selected_document_ids=selected_document_ids,
        selected_document_id=selected_document_id,
        document_scope=document_scope,
        user_id=user_id,
        active_group_id=active_group_id,
        active_group_ids=active_group_ids,
        active_public_workspace_id=active_public_workspace_id,
        active_public_workspace_ids=active_public_workspace_ids,
    ))

    return dedupe_tabular_file_contexts(tabular_file_contexts)


def collect_workspace_tabular_filenames(combined_documents=None, selected_document_ids=None,
                                        selected_document_id=None, document_scope='personal',
                                        user_id=None, active_group_id=None,
                                        active_group_ids=None,
                                        active_public_workspace_id=None,
                                        active_public_workspace_ids=None):
    """Collect unique tabular filenames from search results and explicit workspace selection."""
    tabular_file_contexts = collect_workspace_tabular_file_contexts(
        combined_documents=combined_documents,
        selected_document_ids=selected_document_ids,
        selected_document_id=selected_document_id,
        document_scope=document_scope,
        user_id=user_id,
        active_group_id=active_group_id,
        active_group_ids=active_group_ids,
        active_public_workspace_id=active_public_workspace_id,
        active_public_workspace_ids=active_public_workspace_ids,
    )
    return {file_context['file_name'] for file_context in tabular_file_contexts}


def normalize_tabular_file_contexts_for_analysis(tabular_filenames=None, tabular_file_contexts=None,
                                                 fallback_source_hint='workspace', fallback_group_id=None,
                                                 fallback_public_workspace_id=None):
    """Return per-file tabular source contexts, defaulting to a shared fallback only when needed."""
    normalized_contexts = dedupe_tabular_file_contexts(tabular_file_contexts)
    if normalized_contexts:
        return normalized_contexts

    fallback_contexts = []
    for file_name in tabular_filenames or []:
        fallback_context = build_tabular_file_context(
            file_name,
            source_hint=fallback_source_hint,
            group_id=fallback_group_id,
            public_workspace_id=fallback_public_workspace_id,
        )
        if fallback_context:
            fallback_contexts.append(fallback_context)

    return dedupe_tabular_file_contexts(fallback_contexts)


def build_tabular_analysis_source_context(tabular_file_contexts=None, fallback_source_hint='workspace',
                                          fallback_group_id=None, fallback_public_workspace_id=None):
    """Build prompt instructions for per-file tabular source metadata."""
    normalized_contexts = dedupe_tabular_file_contexts(tabular_file_contexts)
    if normalized_contexts:
        lines = [
            "Use the following per-file source metadata on tabular_processing tool calls. "
            "Do not substitute a different source for a listed file:",
        ]
        for file_context in normalized_contexts:
            context_parts = [f"source='{file_context.get('source_hint', 'workspace')}'"]
            if file_context.get('group_id'):
                context_parts.append(f"group_id='{file_context['group_id']}'")
            if file_context.get('public_workspace_id'):
                context_parts.append(f"public_workspace_id='{file_context['public_workspace_id']}'")
            lines.append(f"- {file_context['file_name']}: {', '.join(context_parts)}")
        return "\n".join(lines)

    fallback_parts = [f"source='{fallback_source_hint}'"]
    if fallback_source_hint == 'group' and fallback_group_id:
        fallback_parts.append(f"group_id='{fallback_group_id}'")
    if fallback_source_hint == 'public' and fallback_public_workspace_id:
        fallback_parts.append(f"public_workspace_id='{fallback_public_workspace_id}'")
    return f"Use {', '.join(fallback_parts)} on tabular_processing tool calls."


def build_tabular_attachment_search_scope_context(tabular_file_contexts=None, fallback_source_hint='workspace',
                                                  fallback_group_id=None, fallback_public_workspace_id=None):
    """Build prompt instructions for document-search scope arguments tied to tabular files."""
    normalized_contexts = normalize_tabular_file_contexts_for_analysis(
        tabular_file_contexts=tabular_file_contexts,
        fallback_source_hint=fallback_source_hint,
        fallback_group_id=fallback_group_id,
        fallback_public_workspace_id=fallback_public_workspace_id,
    )

    lines = [
        'Use the following document_search scope arguments when retrieving attachment-backed row evidence:',
    ]
    for file_context in normalized_contexts:
        scope_parts = []
        source_hint = file_context.get('source_hint', 'workspace')
        if source_hint == 'group':
            scope_parts.append("doc_scope='group'")
            if file_context.get('group_id'):
                scope_parts.append(f"active_group_ids='{file_context['group_id']}'")
        elif source_hint == 'public':
            scope_parts.append("doc_scope='public'")
            if file_context.get('public_workspace_id'):
                scope_parts.append(
                    f"active_public_workspace_id='{file_context['public_workspace_id']}'"
                )
        else:
            scope_parts.append("doc_scope='personal'")
        lines.append(f"- {file_context['file_name']}: {', '.join(scope_parts)}")

    return '\n'.join(lines)


def determine_tabular_source_hint(document_scope, active_group_id=None, active_public_workspace_id=None):
    """Map workspace scope metadata to the tabular plugin source hint."""
    if document_scope == 'group' and active_group_id:
        return 'group'
    if document_scope == 'public' and active_public_workspace_id:
        return 'public'
    return 'workspace'


async def run_multi_file_tabular_distinct_url_analysis(user_question, analysis_file_contexts,
                                                       user_id, conversation_id):
    """Run deterministic per-file URL extraction and union the distinct results in Python."""
    from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

    del user_question
    normalized_contexts = dedupe_tabular_file_contexts(analysis_file_contexts)
    if len(normalized_contexts) <= 1:
        return None

    tabular_plugin = TabularProcessingPlugin()
    successful_results = []
    fatal_failures = []

    for file_context in normalized_contexts:
        filename = file_context['file_name']
        source_hint = file_context.get('source_hint', 'workspace')
        group_id = file_context.get('group_id')
        public_workspace_id = file_context.get('public_workspace_id')

        try:
            container_name, blob_name = tabular_plugin._resolve_blob_location_with_fallback(
                user_id,
                conversation_id,
                filename,
                source_hint,
                group_id=group_id,
                public_workspace_id=public_workspace_id,
            )
            tabular_plugin.remember_resolved_blob_location(
                source_hint,
                filename,
                container_name,
                blob_name,
            )
            schema_info = tabular_plugin._build_workbook_schema_summary(
                container_name,
                blob_name,
                filename,
                preview_rows=2,
            )
        except Exception as exc:
            fatal_failures.append({
                'filename': filename,
                'source': source_hint,
                'error': f'Could not load workbook schema: {exc}',
            })
            continue

        selected_sheet, selected_column = select_tabular_distinct_url_sheet_and_column(schema_info)
        if not selected_column:
            fatal_failures.append({
                'filename': filename,
                'source': source_hint,
                'error': 'Could not identify a URL/location-style column from workbook schema.',
            })
            continue

        base_arguments = {
            'user_id': user_id,
            'conversation_id': conversation_id,
            'filename': filename,
            'column': selected_column,
            'extract_mode': 'regex',
            'extract_pattern': MULTI_FILE_TABULAR_DISTINCT_URL_EXTRACT_PATTERN,
            'normalize_match': 'false',
            'max_values': '10000',
            'source': source_hint,
        }
        if group_id:
            base_arguments['group_id'] = group_id
        if public_workspace_id:
            base_arguments['public_workspace_id'] = public_workspace_id

        attempt_arguments = []
        primary_arguments = dict(base_arguments)
        if selected_sheet:
            primary_arguments['sheet_name'] = selected_sheet
        attempt_arguments.append(primary_arguments)

        if (
            selected_sheet
            and schema_info.get('is_workbook')
            and int(schema_info.get('sheet_count', 0) or 0) > 1
        ):
            attempt_arguments.append(dict(base_arguments))

        best_result_payload = None
        best_result_counts = None
        last_error_message = None
        for current_arguments in attempt_arguments:
            raw_result = await tabular_plugin.get_distinct_values(**current_arguments)
            try:
                result_payload = json.loads(raw_result)
            except (TypeError, ValueError):
                last_error_message = 'get_distinct_values returned a non-JSON payload.'
                continue

            if result_payload.get('error'):
                last_error_message = str(result_payload.get('error')).strip()
                continue

            distinct_count = parse_tabular_result_count(result_payload.get('distinct_count')) or 0
            returned_values = parse_tabular_result_count(result_payload.get('returned_values')) or 0
            comparison_key = (distinct_count, returned_values)
            if best_result_counts is None or comparison_key > best_result_counts:
                best_result_payload = result_payload
                best_result_counts = comparison_key

        if best_result_payload is None:
            fatal_failures.append({
                'filename': filename,
                'source': source_hint,
                'error': last_error_message or 'Distinct URL extraction failed for this file.',
            })
            continue

        successful_results.append(best_result_payload)

    if fatal_failures:
        log_event(
            '[Tabular Multi-File] Deterministic distinct URL analysis could not cover every file; falling back to SK orchestration.',
            extra={
                'conversation_id': conversation_id,
                'file_count': len(normalized_contexts),
                'fatal_failures': fatal_failures[:5],
            },
            level=logging.WARNING,
        )
        return None

    combined_analysis = build_multi_file_tabular_distinct_value_analysis(successful_results)
    if combined_analysis:
        log_event(
            '[Tabular Multi-File] Deterministic distinct URL analysis completed.',
            extra={
                'conversation_id': conversation_id,
                'file_count': len(normalized_contexts),
                'matched_file_count': len(successful_results),
            },
            level=logging.INFO,
        )

    return combined_analysis


async def run_tabular_analysis_with_multi_file_support(user_question, tabular_filenames, user_id,
                                                       conversation_id, gpt_model, settings,
                                                       source_hint='workspace', group_id=None,
                                                       public_workspace_id=None,
                                                       execution_mode='analysis',
                                                       tabular_file_contexts=None,
                                                       thought_callback=None,
                                                       model_context=None):
    """Run deterministic multi-file helpers first, then fall back to the SK planner."""
    analysis_file_contexts = normalize_tabular_file_contexts_for_analysis(
        tabular_filenames=tabular_filenames,
        tabular_file_contexts=tabular_file_contexts,
        fallback_source_hint=source_hint,
        fallback_group_id=group_id,
        fallback_public_workspace_id=public_workspace_id,
    )
    multi_file_mode = get_multi_file_tabular_analysis_mode(
        user_question,
        execution_mode=execution_mode,
        analysis_file_contexts=analysis_file_contexts,
    )

    if multi_file_mode == 'distinct_url_union':
        log_event(
            '[Tabular Multi-File] Starting deterministic distinct URL union analysis.',
            extra={
                'conversation_id': conversation_id,
                'file_names': [file_context['file_name'] for file_context in analysis_file_contexts],
            },
            level=logging.INFO,
        )
        deterministic_analysis = await run_multi_file_tabular_distinct_url_analysis(
            user_question,
            analysis_file_contexts,
            user_id,
            conversation_id,
        )
        if deterministic_analysis:
            return deterministic_analysis

    return await run_tabular_sk_analysis(
        user_question=user_question,
        tabular_filenames=tabular_filenames,
        tabular_file_contexts=analysis_file_contexts,
        user_id=user_id,
        conversation_id=conversation_id,
        gpt_model=gpt_model,
        settings=settings,
        source_hint=source_hint,
        group_id=group_id,
        public_workspace_id=public_workspace_id,
        execution_mode=execution_mode,
        thought_callback=thought_callback,
        model_context=model_context,
    )


async def run_tabular_analysis_with_thought_tracking(user_question, tabular_filenames, user_id,
                                                     conversation_id, gpt_model, settings,
                                                     source_hint='workspace', group_id=None,
                                                     public_workspace_id=None,
                                                     execution_mode='analysis',
                                                     tabular_file_contexts=None,
                                                     thought_tracker=None,
                                                     live_thought_callback=None,
                                                     model_context=None):
    """Run tabular analysis while streaming/persisting live tool thoughts when available."""
    plugin_logger = get_plugin_logger()
    callback_key = None
    tabular_progress_callback = None
    live_tool_thoughts_enabled = False

    try:
        if thought_tracker is not None and user_id and conversation_id:
            callback_key = register_tabular_invocation_thought_callback(
                plugin_logger,
                thought_tracker,
                user_id,
                conversation_id,
                live_thought_callback=live_thought_callback,
            )
            live_tool_thoughts_enabled = True

            def record_and_publish_tabular_progress_thought(thought_payload):
                thought_tracker.add_thought(
                    thought_payload['step_type'],
                    thought_payload['content'],
                    detail=thought_payload.get('detail'),
                    activity=thought_payload.get('activity'),
                )

                if callable(live_thought_callback):
                    live_payload = dict(thought_payload)
                    live_payload['message_id'] = getattr(thought_tracker, 'message_id', None)
                    live_payload['step_index'] = thought_tracker.current_index - 1
                    live_thought_callback(live_payload)

            tabular_progress_callback = record_and_publish_tabular_progress_thought

            await emit_tabular_analysis_lifecycle_thought(
                tabular_progress_callback,
                'Tabular analysis is running',
                detail=f"Preparing workbook evidence across {len(tabular_filenames or [])} file(s).",
                title='Analyzing workbook evidence',
                state='running',
                phase='analysis',
                attempt_number=1,
                attempt_count=3,
            )

        tabular_analysis = await run_tabular_analysis_with_multi_file_support(
            user_question=user_question,
            tabular_filenames=tabular_filenames,
            tabular_file_contexts=tabular_file_contexts,
            user_id=user_id,
            conversation_id=conversation_id,
            gpt_model=gpt_model,
            settings=settings,
            source_hint=source_hint,
            group_id=group_id,
            public_workspace_id=public_workspace_id,
            execution_mode=execution_mode,
            thought_callback=tabular_progress_callback,
            model_context=model_context,
        )

        if callable(tabular_progress_callback):
            await emit_tabular_analysis_lifecycle_thought(
                tabular_progress_callback,
                'Tabular analysis complete; preparing final response',
                detail='Workbook evidence is ready for final response synthesis.',
                title='Preparing final tabular response',
                state='completed',
                phase='handoff',
            )

        return tabular_analysis, live_tool_thoughts_enabled
    except Exception as exc:
        if callable(tabular_progress_callback):
            await emit_tabular_analysis_lifecycle_thought(
                tabular_progress_callback,
                'Tabular analysis stopped before completion',
                detail=str(exc),
                title='Tabular analysis stopped',
                state='failed',
                phase='failed',
            )
        raise
    finally:
        if callback_key:
            plugin_logger.deregister_callbacks(callback_key)


def resolve_foundry_scope_for_auth(auth_settings, endpoint=None):
    """Resolve the correct scope for Foundry-backed inference authentication."""
    auth_settings = auth_settings or {}
    custom_scope = str(auth_settings.get('foundry_scope') or '').strip()
    if custom_scope:
        return custom_scope

    management_cloud = str(auth_settings.get('management_cloud') or 'public').lower()
    if management_cloud in ('government', 'usgovernment', 'usgov'):
        return 'https://ai.azure.us/.default'
    if management_cloud == 'china':
        return 'https://ai.azure.cn/.default'
    if management_cloud == 'germany':
        return 'https://ai.azure.de/.default'

    endpoint_value = str(endpoint or '').lower()
    if 'azure.us' in endpoint_value:
        return 'https://ai.azure.us/.default'
    if 'azure.cn' in endpoint_value:
        return 'https://ai.azure.cn/.default'
    if 'azure.de' in endpoint_value:
        return 'https://ai.azure.de/.default'

    return 'https://ai.azure.com/.default'


def get_foundry_api_version_candidates(primary_version, settings):
    """Return distinct Foundry API versions to try for inference compatibility."""
    settings = settings or {}
    candidates = [
        str(primary_version or '').strip(),
        str(settings.get('azure_openai_gpt_api_version') or '').strip(),
        '2024-10-01-preview',
        '2024-07-01-preview',
        '2024-05-01-preview',
        '2024-02-01',
    ]

    unique_candidates = []
    seen_candidates = set()
    for candidate in candidates:
        if not candidate or candidate in seen_candidates:
            continue
        seen_candidates.add(candidate)
        unique_candidates.append(candidate)

    return unique_candidates


def build_streaming_multi_endpoint_client(auth_settings, provider, endpoint, api_version, deployment_name=''):
    """Create an inference client for a resolved streaming model endpoint."""
    auth_settings = auth_settings or {}
    auth_type = str(auth_settings.get('type') or 'managed_identity').lower()
    normalized_provider = str(provider or 'aoai').lower()
    runtime_protocol = infer_model_endpoint_protocol(normalized_provider, endpoint, deployment_name)

    if auth_type in ('api_key', 'key'):
        api_key = auth_settings.get('api_key')
        if not api_key:
            raise ValueError('Selected model endpoint is missing an API key.')
        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
            return build_anthropic_chat_client(endpoint=endpoint, api_key=api_key)
        if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
            return build_openai_style_chat_client(api_key, endpoint, api_version)
        return AzureOpenAI(
            api_version=api_version,
            azure_endpoint=endpoint,
            api_key=api_key,
        )

    if auth_type == 'service_principal':
        credential = ClientSecretCredential(
            tenant_id=auth_settings.get('tenant_id'),
            client_id=auth_settings.get('client_id'),
            client_secret=auth_settings.get('client_secret'),
            authority=resolve_authority(auth_settings),
        )
    else:
        managed_identity_client_id = auth_settings.get('managed_identity_client_id') or None
        credential = DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)

    scope = cognitive_services_scope
    if normalized_provider in ('aifoundry', 'new_foundry') or runtime_protocol != MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
        scope = resolve_foundry_scope_for_auth(auth_settings, endpoint=endpoint)
        if auth_type == 'service_principal':
            debug_print(
                f"[Streaming][Model Resolution] Multi-endpoint SP scope={scope} provider={normalized_provider} protocol={runtime_protocol}"
            )
        else:
            debug_print(
                f"[Streaming][Model Resolution] Multi-endpoint MI scope={scope} provider={normalized_provider} protocol={runtime_protocol}"
            )

    if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC:
        token = credential.get_token(scope).token
        return build_anthropic_chat_client(endpoint=endpoint, bearer_token=token)

    if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE:
        token = credential.get_token(scope).token
        return build_openai_style_chat_client(token, endpoint, api_version)

    token_provider = get_bearer_token_provider(credential, scope)
    return AzureOpenAI(
        api_version=api_version,
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
    )


def get_streaming_model_endpoint_candidates(settings, user_id, active_group_ids=None):
    """Collect normalized endpoint candidates available to the streaming request."""
    endpoints = []
    active_group_ids = active_group_ids or []

    user_settings_doc = get_user_settings(user_id) if user_id else {}
    user_settings = user_settings_doc.get('settings', {}) if isinstance(user_settings_doc, dict) else {}

    if settings.get('allow_user_custom_endpoints', False):
        try:
            ensure_governance_access('governance_user_endpoints', user_id)
            personal_endpoints, _ = normalize_model_endpoints(user_settings.get('personal_model_endpoints', []) or [])
            endpoints.extend([
                {**endpoint, '_endpoint_scope': 'user'}
                for endpoint in personal_endpoints
                if isinstance(endpoint, dict)
            ])
        except PermissionError:
            debug_print('[Streaming][Model Resolution] User endpoint governance policy denied access to personal endpoints.')

    if settings.get('allow_group_custom_endpoints', False):
        try:
            ensure_governance_access('governance_group_endpoints', user_id)
            seen_group_ids = set()
            for group_id in active_group_ids:
                group_key = str(group_id or '').strip()
                if not group_key or group_key in seen_group_ids:
                    continue
                seen_group_ids.add(group_key)

                try:
                    group_endpoints, _ = normalize_model_endpoints(get_group_model_endpoints(group_key) or [])
                except Exception as group_error:
                    debug_print(
                        f"[Streaming][Model Resolution] Failed to load group endpoints for group_id={group_key}: {group_error}"
                    )
                    continue

                endpoints.extend([
                    {**endpoint, '_endpoint_scope': 'group'}
                    for endpoint in group_endpoints
                    if isinstance(endpoint, dict)
                ])
        except PermissionError:
            debug_print('[Streaming][Model Resolution] Group endpoint governance policy denied access to group endpoints.')

    try:
        ensure_governance_access('governance_global_endpoints', user_id)
        global_endpoints, _ = normalize_model_endpoints(settings.get('model_endpoints', []) or [])
        for endpoint in global_endpoints:
            if not isinstance(endpoint, dict):
                continue
            endpoint_id = str(endpoint.get('id') or '').strip()
            if endpoint_id:
                try:
                    ensure_governance_access(
                        'governance_global_endpoints',
                        user_id,
                        item_entity_type='global_endpoint',
                        item_id=endpoint_id,
                    )
                except PermissionError:
                    continue
            endpoints.append({**endpoint, '_endpoint_scope': 'global'})
    except PermissionError:
        debug_print('[Streaming][Model Resolution] Global endpoint governance policy denied access to global endpoints.')

    return endpoints


def resolve_streaming_multi_endpoint_gpt_config(settings, data, user_id, active_group_ids=None, allow_default_selection=False):
    """Resolve a streaming GPT config from explicit or default multi-endpoint selections."""
    if not settings.get('enable_multi_model_endpoints', False):
        return None

    requested_endpoint_id = str(data.get('model_endpoint_id') or '').strip()
    requested_model_id = str(data.get('model_id') or '').strip()
    requested_provider = str(data.get('model_provider') or '').strip().lower()
    requested_deployment = str(data.get('model_deployment') or '').strip()

    selection_source = None
    if requested_model_id and not requested_endpoint_id:
        raise ValueError('Selected model endpoint is missing for the streaming request.')

    if requested_endpoint_id:
        if not (requested_model_id or requested_deployment):
            raise ValueError('Selected model information is incomplete for the streaming request.')
        selection_source = 'request'
    elif allow_default_selection:
        default_selection = settings.get('default_model_selection', {}) or {}
        default_endpoint_id = str(default_selection.get('endpoint_id') or '').strip()
        default_model_id = str(default_selection.get('model_id') or '').strip()
        default_provider = str(default_selection.get('provider') or '').strip().lower()
        if default_endpoint_id and default_model_id:
            requested_endpoint_id = default_endpoint_id
            requested_model_id = default_model_id
            requested_provider = requested_provider or default_provider
            selection_source = 'default'
        else:
            return None
    else:
        return None

    endpoint_candidates = get_streaming_model_endpoint_candidates(
        settings,
        user_id,
        active_group_ids=active_group_ids,
    )
    endpoint_cfg = next((endpoint for endpoint in endpoint_candidates if endpoint.get('id') == requested_endpoint_id), None)

    if not endpoint_cfg:
        if selection_source == 'request':
            raise LookupError('Selected model endpoint could not be found.')
        debug_print(
            f"[Streaming][Model Resolution] Default model endpoint_id={requested_endpoint_id} was not found. Falling back to legacy streaming config."
        )
        return None

    if not endpoint_cfg.get('enabled', True):
        if selection_source == 'request':
            raise ValueError('Selected model endpoint is disabled.')
        debug_print(
            f"[Streaming][Model Resolution] Default model endpoint_id={requested_endpoint_id} is disabled. Falling back to legacy streaming config."
        )
        return None

    endpoint_scope = endpoint_cfg.get('_endpoint_scope', 'global')
    resolved_endpoint_cfg = dict(endpoint_cfg)
    resolved_endpoint_cfg.pop('_endpoint_scope', None)
    resolved_endpoint_cfg = keyvault_model_endpoint_get_helper(
        resolved_endpoint_cfg,
        resolved_endpoint_cfg.get('id') or requested_endpoint_id,
        scope=endpoint_scope,
        return_type=SecretReturnType.VALUE,
    )

    models = resolved_endpoint_cfg.get('models', []) or []
    model_cfg = None
    if requested_model_id:
        model_cfg = next((model for model in models if model.get('id') == requested_model_id), None)
    if model_cfg is None and requested_deployment:
        model_cfg = next(
            (
                model for model in models
                if str(model.get('deploymentName') or model.get('deployment') or '').strip() == requested_deployment
            ),
            None,
        )

    if not model_cfg:
        if selection_source == 'request':
            raise LookupError('Selected model could not be found on the configured endpoint.')
        debug_print(
            f"[Streaming][Model Resolution] Default model_id={requested_model_id} was not found on endpoint_id={requested_endpoint_id}. Falling back to legacy streaming config."
        )
        return None

    if not model_cfg.get('enabled', True):
        if selection_source == 'request':
            raise ValueError('Selected model is disabled.')
        debug_print(
            f"[Streaming][Model Resolution] Default model_id={requested_model_id} is disabled. Falling back to legacy streaming config."
        )
        return None

    provider = str(resolved_endpoint_cfg.get('provider') or requested_provider or 'aoai').lower()
    if provider not in MODEL_ENDPOINT_PROVIDER_ALLOWLIST:
        if selection_source == 'request':
            raise ValueError('Selected model provider is not supported for streaming.')
        debug_print(
            f"[Streaming][Model Resolution] Default provider '{provider}' is not supported for streaming. Falling back to legacy streaming config."
        )
        return None

    connection = resolved_endpoint_cfg.get('connection', {}) or {}
    auth_settings = resolved_endpoint_cfg.get('auth', {}) or {}
    deployment = str(model_cfg.get('deploymentName') or model_cfg.get('deployment') or '').strip()
    endpoint = str(connection.get('endpoint') or '').strip()
    api_version = str(connection.get('openai_api_version') or connection.get('api_version') or '').strip()
    runtime_protocol = infer_model_endpoint_protocol(provider, endpoint, deployment)

    if requested_provider and requested_provider != provider:
        debug_print(
            f"[Streaming][Model Resolution] Request provider '{requested_provider}' did not match saved provider '{provider}' for endpoint_id={requested_endpoint_id}."
        )

    missing_required_config = not endpoint or not deployment or (
        runtime_protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI and not api_version
    )
    if missing_required_config:
        if selection_source == 'request':
            if runtime_protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI:
                raise ValueError('Selected model endpoint is missing endpoint, API version, or deployment configuration.')
            raise ValueError('Selected model endpoint is missing endpoint or deployment configuration.')
        debug_print(
            f"[Streaming][Model Resolution] Default selection for endpoint_id={requested_endpoint_id} is incomplete. Falling back to legacy streaming config."
        )
        return None

    gpt_client = build_streaming_multi_endpoint_client(
        auth_settings,
        provider,
        endpoint,
        api_version,
        deployment_name=deployment,
    )
    debug_print(
        f"[Streaming][Model Resolution] Resolved {selection_source} multi-endpoint model | "
        f"provider={provider} | endpoint_id={requested_endpoint_id} | model_id={model_cfg.get('id')} | "
        f"deployment={deployment} | api_version={api_version} | protocol={runtime_protocol}"
    )
    return (
        gpt_client,
        deployment,
        provider,
        endpoint,
        auth_settings,
        api_version,
        requested_endpoint_id,
        str(model_cfg.get('id') or '').strip(),
    )


def classify_agent_stream_retry_mode(stream_error):
    """Return retry details for agent streaming failures that can recover without tools."""
    normalized_error = str(stream_error or '').lower()

    if (
        'auto tool choice requires' in normalized_error
        or 'tool-call-parser' in normalized_error
        or 'does not support tool calling' in normalized_error
        or ('tool choice' in normalized_error and 'parser' in normalized_error)
    ):
        return {
            'mode': 'disable_tools',
            'reason': 'tool_choice_unsupported',
        }

    if (
        '431' in normalized_error
        or 'header fields too large' in normalized_error
        or ('request header' in normalized_error and 'too large' in normalized_error)
        or ('header' in normalized_error and 'too large' in normalized_error)
    ):
        return {
            'mode': 'disable_tools',
            'reason': 'request_headers_too_large',
        }

    return None


def apply_agent_stream_retry_mode(agent, retry_mode):
    """Temporarily adjust agent tool settings for a retry attempt."""
    retry_state = {
        'function_choice_behavior': None,
        'execution_settings': [],
        'service_prompt_settings': None,
    }

    if agent is None or retry_mode != 'disable_tools':
        return retry_state

    retry_state['function_choice_behavior'] = getattr(agent, 'function_choice_behavior', None)
    agent.function_choice_behavior = None

    agent_arguments = getattr(agent, 'arguments', None)
    execution_settings = getattr(agent_arguments, 'execution_settings', None)
    if isinstance(execution_settings, dict):
        for settings in execution_settings.values():
            if hasattr(settings, 'function_choice_behavior'):
                retry_state['execution_settings'].append(
                    (settings, getattr(settings, 'function_choice_behavior', None))
                )
                settings.function_choice_behavior = None

    prompt_execution_settings = getattr(getattr(agent, 'service', None), 'prompt_execution_settings', None)
    if prompt_execution_settings is not None and hasattr(prompt_execution_settings, 'function_choice_behavior'):
        retry_state['service_prompt_settings'] = (
            prompt_execution_settings,
            getattr(prompt_execution_settings, 'function_choice_behavior', None),
        )
        prompt_execution_settings.function_choice_behavior = None

    return retry_state


def restore_agent_stream_retry_state(agent, retry_state):
    """Restore any temporary agent retry settings after the stream attempt finishes."""
    if agent is None or not retry_state:
        return

    agent.function_choice_behavior = retry_state.get('function_choice_behavior')

    for settings, original_behavior in retry_state.get('execution_settings', []):
        settings.function_choice_behavior = original_behavior

    service_prompt_settings = retry_state.get('service_prompt_settings')
    if service_prompt_settings:
        settings, original_behavior = service_prompt_settings
        settings.function_choice_behavior = original_behavior


def register_route_backend_chats(app):
    def build_background_stream_response(event_generator_factory, stream_session=None):
        """Run SSE generation in background execution so it survives disconnects."""
        stream_bridge = BackgroundStreamBridge(stream_session=stream_session)

        def publish_background_event(event_text):
            if event_text is None:
                return False

            if stream_session:
                stream_session.publish(event_text)

            return stream_bridge.push(event_text)

        @copy_current_request_context
        def stream_worker():
            try:
                generator_signature = inspect.signature(event_generator_factory)
                if 'publish_background_event' in generator_signature.parameters:
                    event_iterator = event_generator_factory(
                        publish_background_event=publish_background_event
                    )
                else:
                    event_iterator = event_generator_factory()

                for event in event_iterator:
                    publish_background_event(event)
            except Exception as e:
                debug_print(f"[STREAM BACKGROUND] Worker error: {e}")
                stream_status = stream_session.get_status_snapshot() if stream_session else {}
                log_event(
                    f"[Streaming] Background worker error: {e}",
                    extra={
                        'conversation_id': stream_status.get('conversation_id'),
                        'user_id': stream_status.get('user_id'),
                        'status': stream_status.get('status'),
                        'event_count': stream_status.get('event_count'),
                        'content_event_count': stream_status.get('content_event_count'),
                    },
                    level=logging.ERROR,
                    exceptionTraceback=True,
                )
                error_event = f"data: {json.dumps({'error': f'Internal server error: {str(e)}'})}\n\n"
                publish_background_event(error_event)
            finally:
                if stream_session:
                    stream_session.close()
                stream_bridge.finish()

        executor = current_app.extensions.get('executor')
        if executor:
            try:
                executor.submit(stream_worker)
            except Exception as e:
                debug_print(f"[STREAM BACKGROUND] Executor submit failed, falling back to thread: {e}")
                worker_thread = threading.Thread(target=stream_worker, daemon=True)
                worker_thread.start()
        else:
            worker_thread = threading.Thread(target=stream_worker, daemon=True)
            worker_thread.start()

        def consume_stream():
            stream_consumed = False
            try:
                for event in stream_bridge.iter_events():
                    yield event
                stream_consumed = True
            except GeneratorExit:
                stream_bridge.detach_consumer(reason='client_disconnect', update_session=True)
                raise
            finally:
                stream_bridge.detach_consumer(
                    reason='stream_consumed' if stream_consumed else 'consumer_cleanup',
                    update_session=False,
                )

        return Response(
            stream_with_context(consume_stream()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )

    def get_facts_for_context(scope_id, scope_type, query_text: str = None, conversation_id: str = None, agent_id: str = None, enabled: bool = True):
        return _build_fact_memory_context_lines(
            scope_id=scope_id,
            scope_type=scope_type,
            query_text=query_text,
            conversation_id=conversation_id,
            agent_id=agent_id,
            enabled=enabled,
        )

    def inject_fact_memory_context(
        conversation_history,
        scope_id,
        scope_type,
        query_text: str = None,
        conversation_id: str = None,
        agent_id: str = None,
        enabled: bool = True,
        include_metadata: bool = False,
    ):
        prompt_payload = build_fact_memory_prompt_payload(
            scope_id=scope_id,
            scope_type=scope_type,
            query_text=query_text,
            conversation_id=conversation_id,
            agent_id=agent_id,
            enabled=enabled,
            include_metadata=include_metadata,
        )
        for message in reversed(prompt_payload.get('context_messages', [])):
            conversation_history.insert(0, message)
        return prompt_payload

    def normalize_terminal_chat_payload(payload):
        return make_json_serializable({
            'done': True,
            'conversation_id': payload.get('conversation_id'),
            'conversation_title': payload.get('conversation_title'),
            'classification': payload.get('classification', []),
            'model_deployment_name': payload.get('model_deployment_name'),
            'message_id': payload.get('message_id'),
            'user_message_id': payload.get('user_message_id'),
            'augmented': payload.get('augmented', False),
            'hybrid_citations': payload.get('hybrid_citations', []),
            'web_search_citations': payload.get('web_search_citations', []),
            'agent_citations': payload.get('agent_citations', []),
            'agent_display_name': payload.get('agent_display_name'),
            'agent_name': payload.get('agent_name'),
            'full_content': payload.get('reply', ''),
            'image_url': payload.get('image_url'),
            'reload_messages': payload.get('reload_messages', False),
            'kernel_fallback_notice': payload.get('kernel_fallback_notice'),
            'thoughts_enabled': payload.get('thoughts_enabled', False),
            'blocked': payload.get('blocked', False),
            'context': payload.get('context', []),
            'chat_type': payload.get('chat_type'),
            'scope_locked': payload.get('scope_locked'),
            'locked_contexts': payload.get('locked_contexts', []),
            'analysis_coverage': payload.get('analysis_coverage', {}),
            'document_action': payload.get('document_action', {}),
            'metadata': payload.get('metadata', {}),
        })

    def _build_document_action_stream_content(event):
        event = event if isinstance(event, dict) else {}
        event_type = str(event.get('type') or '').strip().lower()
        document_name = str(event.get('document_name') or 'Document').strip() or 'Document'
        window_range = event.get('window_range') if isinstance(event.get('window_range'), dict) else {}
        window_number = window_range.get('window_number')
        progress = event.get('progress') if isinstance(event.get('progress'), dict) else {}
        documents = progress.get('documents') if isinstance(progress.get('documents'), list) else []
        document_progress = next(
            (document for document in documents if document.get('document_id') == event.get('document_id')),
            {},
        )
        total_windows = document_progress.get('total_windows') or event.get('window_count') or 0

        if event_type == 'document_started':
            return f'Starting analysis for {document_name}'
        if event_type == 'window_started' and window_number is not None:
            return f'Analyzing window {window_number} of {total_windows} for {document_name}'
        if event_type == 'window_retry' and window_number is not None:
            return f'Retrying window {window_number} for {document_name} (attempt {event.get("attempt_number")})'
        if event_type == 'window_failed' and window_number is not None:
            return f'Window {window_number} failed for {document_name}'
        if event_type == 'window_completed' and window_number is not None:
            return f'Completed window {window_number} of {total_windows} for {document_name}'
        if event_type == 'document_completed':
            return f'Completed analysis for {document_name}'
        if event_type == 'reduction_started':
            reduction_step_index = event.get('reduction_step_index')
            reduction_step_total = event.get('reduction_step_total')
            if reduction_step_index is not None and reduction_step_total:
                return (
                    'Combining analysis findings into the final response '
                    f'({reduction_step_index}/{reduction_step_total})'
                )
            return 'Combining analysis findings into the final response'
        if event_type == 'reduction_completed':
            return 'Completed analysis across the selected documents'
        if event_type == 'comparison_started':
            right_document_name = str(event.get('right_document_name') or 'Document').strip() or 'Document'
            return f'Comparing {document_name} to {right_document_name}'
        if event_type == 'comparison_completed':
            right_document_name = str(event.get('right_document_name') or 'Document').strip() or 'Document'
            return f'Completed comparison of {document_name} to {right_document_name}'
        if event_type == 'comparison_reduction_started':
            comparison_count = event.get('comparison_count')
            if comparison_count:
                return f'Combining {comparison_count} pairwise comparisons into the final response'
            return 'Combining comparison findings into the final response'
        if event_type == 'comparison_reduction_completed':
            comparison_count = event.get('comparison_count')
            if comparison_count:
                return f'Completed comparison across {comparison_count} document pairs'
            return 'Completed comparison across the selected documents'
        return 'Running analysis across the selected documents'

    def _build_document_action_hybrid_citations(execution_result):
        def _coerce_metric_int(value, default_value=0):
            try:
                return int(value if value not in (None, '') else default_value)
            except (TypeError, ValueError):
                return int(default_value or 0)

        analysis_result = execution_result.get('analysis_result') if isinstance(execution_result, dict) else {}
        analysis_result = analysis_result if isinstance(analysis_result, dict) else {}
        analysis_coverage = execution_result.get('analysis_coverage') if isinstance(execution_result, dict) else {}
        analysis_coverage = analysis_coverage if isinstance(analysis_coverage, dict) else {}

        document_summaries = analysis_result.get('documents') if isinstance(analysis_result.get('documents'), list) else []
        if not document_summaries:
            document_summaries = analysis_coverage.get('documents') if isinstance(analysis_coverage.get('documents'), list) else []

        citations = []
        is_comparison = bool(analysis_result.get('left_document') or analysis_result.get('right_documents'))
        left_document = analysis_result.get('left_document') if isinstance(analysis_result.get('left_document'), dict) else {}
        right_documents = analysis_result.get('right_documents') if isinstance(analysis_result.get('right_documents'), list) else []
        document_count = _coerce_metric_int(analysis_coverage.get('document_count'), len(document_summaries))
        total_windows = _coerce_metric_int(analysis_coverage.get('total_windows'))
        processed_windows = _coerce_metric_int(analysis_coverage.get('processed_windows'))
        failed_windows = _coerce_metric_int(analysis_coverage.get('failed_windows'))
        total_chunks = _coerce_metric_int(analysis_coverage.get('total_chunks'))
        processed_chunks = _coerce_metric_int(analysis_coverage.get('processed_chunks'))
        failed_chunks = _coerce_metric_int(analysis_coverage.get('failed_chunks'))
        retries_used = _coerce_metric_int(analysis_coverage.get('retries'))
        window_unit = str(analysis_coverage.get('window_unit') or 'pages').strip() or 'pages'

        has_coverage_summary = bool(document_summaries) or any([
            document_count,
            total_windows,
            processed_windows,
            failed_windows,
            total_chunks,
            processed_chunks,
            failed_chunks,
            retries_used,
        ])

        if has_coverage_summary:
            coverage_lines = [
                'Coverage',
                f'Documents analyzed: {document_count}',
                f'Total windows: {total_windows}',
                f'Processed windows: {processed_windows}',
                f'Failed windows: {failed_windows}',
                f'Total chunks: {total_chunks}',
                f'Processed chunks: {processed_chunks}',
                f'Failed chunks: {failed_chunks}',
                f'Retries used: {retries_used}',
                f'Window unit: {window_unit}',
            ]

            left_document_name = str(left_document.get('document_name') or left_document.get('document_id') or '').strip()
            if is_comparison and left_document_name:
                coverage_lines.append(f'Source document: {left_document_name}')
            if is_comparison:
                coverage_lines.append(f'Target documents compared: {len(right_documents)}')

            citations.append({
                'file_name': 'Coverage',
                'document_id': None,
                'citation_id': 'document_action_coverage',
                'page_number': 'Metadata',
                'chunk_id': 'document_action_coverage',
                'chunk_sequence': 20000,
                'score': 0.0,
                'metadata_type': 'document_comparison_coverage' if is_comparison else 'document_analysis_coverage',
                'metadata_content': '\n'.join(coverage_lines),
                'location_label': 'Coverage',
                'location_value': 'Overall summary',
            })

        seen_document_ids = set()
        for index, document_summary in enumerate(document_summaries, start=1):
            if not isinstance(document_summary, dict):
                continue

            document_id = str(document_summary.get('document_id') or '').strip()
            dedupe_key = document_id or f'document-{index}'
            if dedupe_key in seen_document_ids:
                continue
            seen_document_ids.add(dedupe_key)

            file_name = str(
                document_summary.get('file_name')
                or document_summary.get('document_name')
                or document_summary.get('title')
                or 'Document'
            ).strip() or 'Document'
            role_label = str(document_summary.get('role_label') or '').strip().lower()
            status_text = str(document_summary.get('status_text') or document_summary.get('status') or 'Completed').strip()
            processed_windows = _coerce_metric_int(document_summary.get('processed_windows'))
            total_windows = _coerce_metric_int(document_summary.get('total_windows'))
            failed_windows = _coerce_metric_int(document_summary.get('failed_windows'))
            processed_chunks = _coerce_metric_int(document_summary.get('processed_chunks'))
            total_chunks = _coerce_metric_int(document_summary.get('total_chunks'))
            failed_chunks = _coerce_metric_int(document_summary.get('failed_chunks'))
            total_pages = _coerce_metric_int(document_summary.get('total_pages'))
            failed_ranges = [
                str(range_label).strip()
                for range_label in (document_summary.get('failed_ranges') or [])
                if str(range_label).strip()
            ]

            metadata_lines = []
            if role_label:
                metadata_lines.append(f"Role: {role_label.title()} document")
            if status_text:
                metadata_lines.append(f"Status: {status_text}")
            metadata_lines.append(f"Windows analyzed: {processed_windows}/{total_windows}")
            if total_chunks or processed_chunks or failed_chunks:
                metadata_lines.append(f"Chunks completed: {processed_chunks}/{total_chunks}")
            if failed_windows:
                metadata_lines.append(f"Failed windows: {failed_windows}")
            if failed_chunks:
                metadata_lines.append(f"Failed chunks: {failed_chunks}")
            if total_pages:
                metadata_lines.append(f"Pages covered: {total_pages}")
            if failed_ranges:
                metadata_lines.append(f"Failed ranges: {', '.join(failed_ranges)}")

            citations.append({
                'file_name': file_name,
                'document_id': document_id,
                'citation_id': f'{dedupe_key}_coverage',
                'page_number': 'Metadata',
                'chunk_id': f'{dedupe_key}_coverage',
                'chunk_sequence': 10000 - index,
                'score': 0.0,
                'group_id': document_summary.get('scope_id') if document_summary.get('scope') == 'group' else None,
                'public_workspace_id': document_summary.get('scope_id') if document_summary.get('scope') == 'public' else None,
                'version': document_summary.get('version'),
                'classification': document_summary.get('classification'),
                'metadata_type': 'document_comparison_summary' if role_label else 'document_analysis_summary',
                'metadata_content': '\n'.join(metadata_lines),
                'location_label': 'Coverage',
                'location_value': 'Document summary',
            })

        return citations

    def _resolve_document_action_selected_documents(
        document_ids,
        document_scope,
        user_id=None,
        conversation_id=None,
        active_group_ids=None,
        active_public_workspace_ids=None,
        max_documents=5,
    ):
        resolved_documents = []
        normalized_conversation_id = str(conversation_id or '').strip()

        for document_id in (document_ids or [])[:max_documents]:
            normalized_document_id = str(document_id or '').strip()
            if not normalized_document_id or normalized_document_id == 'all':
                continue

            resolved_document = {
                'id': normalized_document_id,
                'display_name': normalized_document_id,
                'file_name': None,
                'group_id': None,
                'public_workspace_id': None,
            }

            try:
                doc_info = _resolve_chat_selected_document_metadata(
                    normalized_document_id,
                    user_id=user_id,
                    document_scope=document_scope,
                    active_group_ids=active_group_ids,
                    active_public_workspace_ids=active_public_workspace_ids,
                )
                if doc_info:
                    display_name = str(
                        doc_info.get('title') or doc_info.get('file_name') or normalized_document_id
                    ).strip() or normalized_document_id
                    resolved_document = {
                        'id': normalized_document_id,
                        'display_name': display_name,
                        'file_name': doc_info.get('file_name'),
                        'group_id': doc_info.get('group_id'),
                        'public_workspace_id': doc_info.get('public_workspace_id'),
                        'source_hint': doc_info.get('source_hint'),
                    }

                if normalized_conversation_id:
                    message_query = (
                        'SELECT TOP 1 c.filename, c.role '
                        'FROM c WHERE c.conversation_id = @conversation_id AND c.id = @doc_id'
                    )
                    message_params = [
                        {'name': '@conversation_id', 'value': normalized_conversation_id},
                        {'name': '@doc_id', 'value': normalized_document_id},
                    ]
                    message_results = list(cosmos_messages_container.query_items(
                        query=message_query,
                        parameters=message_params,
                        partition_key=normalized_conversation_id,
                    ))
                    if message_results:
                        message_info = message_results[0]
                        display_name = str(
                            message_info.get('filename') or normalized_document_id
                        ).strip() or normalized_document_id
                        resolved_document = {
                            'id': normalized_document_id,
                            'display_name': display_name,
                            'file_name': message_info.get('filename'),
                            'group_id': None,
                            'public_workspace_id': None,
                            'source_hint': 'chat_upload',
                        }
            except Exception as exc:
                debug_print(
                    '[ChatDocumentAction] Failed to resolve selected document metadata | '
                    f'document_id={normalized_document_id} | '
                    f'error={exc}'
                )

            resolved_documents.append(resolved_document)

        return resolved_documents

    def _summarize_document_action_document_names(document_names, total_count):
        cleaned_names = [
            str(document_name).strip()
            for document_name in (document_names or [])
            if str(document_name).strip()
        ]
        if not cleaned_names:
            if total_count == 1:
                return '1 selected document'
            return f'{total_count} selected documents'

        preview_names = cleaned_names[:3]
        summary = ', '.join(preview_names)
        if total_count > len(preview_names):
            summary = f'{summary} (+{total_count - len(preview_names)} more)'
        return summary

    def _build_document_action_user_metadata(
        data,
        user_id,
        conversation_id,
        current_thread_id,
        previous_thread_id,
        normalized_action,
        request_agent_info,
        assigned_knowledge_filters=None,
        streaming_enabled=False,
    ):
        timestamp = datetime.utcnow().isoformat()
        selected_document_ids = normalized_action.get('document_ids', [])
        document_scope = normalized_action.get('doc_scope', 'all')
        active_group_ids = normalized_action.get('active_group_ids', [])
        active_public_workspace_ids = normalized_action.get('active_public_workspace_id', [])
        resolved_documents = _resolve_document_action_selected_documents(
            selected_document_ids,
            document_scope,
            user_id=user_id,
            conversation_id=conversation_id,
            active_group_ids=active_group_ids,
            active_public_workspace_ids=active_public_workspace_ids,
        )
        resolved_documents_by_id = {
            document.get('id'): document
            for document in resolved_documents
            if document.get('id')
        }
        resolved_document_names = [
            document.get('display_name')
            for document in resolved_documents
            if document.get('display_name')
        ]

        selected_document_summary = _summarize_document_action_document_names(
            resolved_document_names,
            len(selected_document_ids),
        )
        if normalized_action.get('type') == DOCUMENT_ACTION_TYPE_COMPARISON:
            left_document_id = str(normalized_action.get('left_document_id') or '').strip()
            left_document_name = resolved_documents_by_id.get(left_document_id, {}).get('display_name') or left_document_id or 'Selected Source document'
            right_document_ids = normalized_action.get('right_document_ids', [])
            right_document_names = [
                resolved_documents_by_id.get(document_id, {}).get('display_name') or str(document_id).strip()
                for document_id in right_document_ids
                if str(document_id).strip()
            ]
            right_document_summary = _summarize_document_action_document_names(
                right_document_names,
                len(right_document_ids),
            )
            selected_document_summary = f'Source: {left_document_name} | Targets: {right_document_summary}'

        current_user = get_current_user_info()
        user_info = {
            'user_id': user_id,
            'timestamp': timestamp,
        }
        if current_user:
            user_info.update({
                'username': current_user.get('userPrincipalName'),
                'display_name': current_user.get('displayName'),
                'email': current_user.get('email'),
            })

        workspace_search = {
            'search_enabled': False,
            'document_scope': document_scope,
            'selected_document_id': selected_document_ids[0] if len(selected_document_ids) == 1 else None,
            'document_name': selected_document_summary,
            'selected_document_count': len(selected_document_ids),
            'selected_document_names': resolved_document_names,
        }

        if document_scope == 'group' and active_group_ids:
            group_doc = find_group_by_id(active_group_ids[0])
            workspace_search['group_name'] = group_doc.get('name') if group_doc else None
        if document_scope == 'public' and active_public_workspace_ids:
            workspace_search['active_public_workspace_id'] = active_public_workspace_ids[0]

        selected_model = str(data.get('model_deployment') or data.get('model_id') or '').strip()
        user_metadata = {
            'user_info': user_info,
            'thread_info': {
                'thread_id': current_thread_id,
                'previous_thread_id': previous_thread_id,
                'active_thread': True,
                'thread_attempt': 1,
            },
            'button_states': {
                'image_generation': False,
                'document_search': False,
                'web_search': False,
                'url_access': False,
                'deep_research': False,
            },
            'workspace_search': workspace_search,
            'model_selection': {
                'selected_model': selected_model,
                'frontend_requested_model': selected_model,
                'model_id': data.get('model_id'),
                'model_endpoint_id': data.get('model_endpoint_id'),
                'model_provider': data.get('model_provider'),
                'reasoning_effort': data.get('reasoning_effort') if data.get('reasoning_effort') not in (None, '', 'none') else None,
                'streaming': bool(streaming_enabled),
            },
            'chat_context': {
                'conversation_id': conversation_id,
                'chat_type': 'group' if document_scope == 'group' else 'public' if document_scope == 'public' else 'personal',
            },
            'analyze': {
                'enabled': normalized_action.get('type') == DOCUMENT_ACTION_TYPE_ANALYZE,
                'document_ids': selected_document_ids,
                'doc_scope': document_scope,
                'active_group_ids': active_group_ids,
                'active_public_workspace_id': active_public_workspace_ids,
            },
            'compare': {
                'enabled': normalized_action.get('type') == DOCUMENT_ACTION_TYPE_COMPARISON,
                'document_ids': selected_document_ids,
                'left_document_id': normalized_action.get('left_document_id'),
                'right_document_ids': normalized_action.get('right_document_ids', []),
                'doc_scope': document_scope,
                'active_group_ids': active_group_ids,
                'active_public_workspace_id': active_public_workspace_ids,
            },
            'capability_usage': _build_capability_usage_metadata(
                workspace_search_used=True,
                document_action_type=normalized_action.get('type'),
                document_scope=document_scope,
                selected_document_ids=selected_document_ids,
                active_group_ids=active_group_ids,
                active_public_workspace_ids=active_public_workspace_ids,
            ),
            'document_action': normalized_action,
        }

        if user_metadata['chat_context']['chat_type'] == 'group' and workspace_search.get('group_name'):
            user_metadata['chat_context']['group_name'] = workspace_search.get('group_name')
        if user_metadata['chat_context']['chat_type'] == 'public' and active_public_workspace_ids:
            user_metadata['chat_context']['workspace_context'] = active_public_workspace_ids[0]

        agent_selection_metadata = _build_agent_selection_metadata(
            request_agent_info,
            assigned_knowledge_filters,
        )
        if agent_selection_metadata:
            user_metadata['agent_selection'] = agent_selection_metadata

        return user_metadata

    def _build_document_action_stream_activity_callback(publish_background_event, assistant_message_id):
        if not callable(publish_background_event) or not assistant_message_id:
            return None, None

        step_index_state = {'value': 0}

        def publish_thought_payload(thought_payload, default_step_type='document_analysis'):
            payload = thought_payload if isinstance(thought_payload, dict) else {}
            payload_step_index = payload.get('step_index')

            if isinstance(payload_step_index, (int, float)):
                step_index = int(payload_step_index)
                step_index_state['value'] = max(step_index_state['value'], step_index + 1)
            else:
                step_index = step_index_state['value']
                step_index_state['value'] += 1

            outbound_payload = {
                'type': 'thought',
                'message_id': payload.get('message_id') or assistant_message_id,
                'step_index': step_index,
                'step_type': str(payload.get('step_type') or default_step_type).strip() or default_step_type,
                'content': str(payload.get('content') or '').strip(),
            }

            detail = payload.get('detail')
            if detail is not None:
                outbound_payload['detail'] = detail

            activity = payload.get('activity')
            if isinstance(activity, dict) and activity:
                outbound_payload['activity'] = activity

            progress = payload.get('progress')
            if isinstance(progress, dict) and progress:
                outbound_payload['progress'] = progress

            publish_background_event(f"data: {json.dumps(make_json_serializable(outbound_payload))}\n\n")

        def publish_thought(content, progress=None):
            payload = {
                'step_type': 'document_analysis',
                'content': content,
            }
            if isinstance(progress, dict) and progress:
                payload['progress'] = progress

            publish_thought_payload(payload)

        def callback(event):
            event = event if isinstance(event, dict) else {}
            if event.get('step_type') or isinstance(event.get('activity'), dict):
                publish_thought_payload(event)
                return

            publish_thought(
                _build_document_action_stream_content(event),
                progress=event.get('progress') if isinstance(event.get('progress'), dict) else None,
            )

        return publish_thought, callback

    def _get_latest_chat_thread_id(conversation_id):
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

    def _load_or_create_analyze_conversation(user_id, conversation_id=None):
        if conversation_id:
            try:
                conversation_item = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id,
                )
                if conversation_item.get('user_id') != user_id:
                    raise PermissionError('You do not have access to this conversation.')
                return conversation_item
            except CosmosResourceNotFoundError:
                pass

        created_conversation_id = conversation_id or str(uuid.uuid4())
        conversation_item = {
            'id': created_conversation_id,
            'user_id': user_id,
            'last_updated': datetime.utcnow().isoformat(),
            'title': 'New Conversation',
            'context': [],
            'tags': [],
            'strict': False,
            'chat_type': 'new',
            'has_unread_assistant_response': False,
            'last_unread_assistant_message_id': None,
            'last_unread_assistant_at': None,
        }
        cosmos_conversations_container.upsert_item(conversation_item)
        log_conversation_creation(
            user_id=user_id,
            conversation_id=created_conversation_id,
            title='New Conversation',
            workspace_type='personal',
        )
        conversation_item['added_to_activity_log'] = True
        cosmos_conversations_container.upsert_item(conversation_item)
        return conversation_item

    def execute_document_action_chat_request(data=None, publish_background_event=None, forced_action_type=None):
        settings = get_settings()
        data = data if isinstance(data, dict) else (request.get_json() or {})
        user_id = get_current_user_id()
        if not user_id:
            return {'error': 'User not authenticated'}, 401

        user_message = str(data.get('message') or '').strip()
        if not user_message:
            return {'error': 'Message is required'}, 400

        conversation_id = getattr(g, 'conversation_id', None) or data.get('conversation_id')
        if conversation_id is not None:
            conversation_id = str(conversation_id).strip() or None

        selected_document_id = data.get('selected_document_id')
        selected_document_ids = data.get('selected_document_ids', [])
        if not selected_document_ids and selected_document_id:
            selected_document_ids = [selected_document_id]

        requested_action = data.get('document_action') if isinstance(data.get('document_action'), dict) else {}
        debug_print(
            '[ChatDocumentAction] Received request | '
            f'user_id={user_id} | '
            f'conversation_id={conversation_id or "new"} | '
            f'forced_action_type={forced_action_type or "none"} | '
            f'requested_action_type={requested_action.get("type") or "none"} | '
            f'selected_document_count={len(selected_document_ids)}'
        )
        if forced_action_type == DOCUMENT_ACTION_TYPE_ANALYZE and not requested_action:
            requested_action = {
                'type': DOCUMENT_ACTION_TYPE_ANALYZE,
                'document_ids': selected_document_ids,
                'doc_scope': data.get('doc_scope'),
                'active_group_ids': data.get('active_group_ids') or data.get('active_group_id'),
                'active_public_workspace_id': data.get('active_public_workspace_ids') or data.get('active_public_workspace_id'),
                'window_unit': 'pages',
                'max_retries_per_window': 1,
            }
        request_agent_info = data.get('agent_info') if isinstance(data.get('agent_info'), dict) else {}
        canonical_request_agent = _resolve_canonical_chat_agent(user_id, settings, request_agent_info)
        assigned_knowledge_filters = (
            build_assigned_knowledge_runtime_filters(canonical_request_agent)
            if canonical_request_agent
            else None
        )
        if canonical_request_agent:
            request_agent_info = canonical_request_agent

        conversation_item = None
        auto_linked_chat_upload_document_ids = []
        requested_action_type = str(
            requested_action.get('type') or forced_action_type or DOCUMENT_ACTION_TYPE_NONE
        ).strip().lower() or DOCUMENT_ACTION_TYPE_NONE
        if (
            requested_action_type == DOCUMENT_ACTION_TYPE_ANALYZE
            and not _normalize_conversation_task_document_ids(requested_action.get('document_ids'))
            and conversation_id
        ):
            try:
                conversation_item = _load_or_create_analyze_conversation(user_id, conversation_id=conversation_id)
            except PermissionError as exc:
                return {'error': str(exc)}, 403

            conversation_id = conversation_item.get('id')
            g.conversation_id = conversation_id
            task_resolution = _resolve_conversation_task_documents(
                user_id=user_id,
                conversation_id=conversation_id,
                document_action_type=DOCUMENT_ACTION_TYPE_ANALYZE,
                assigned_knowledge_filters=assigned_knowledge_filters,
                candidate_document_ids=data.get('conversation_task_document_ids'),
            )
            if task_resolution.get('blocked'):
                return {
                    'error': 'This agent does not allow document analysis with uploaded task documents.'
                }, 403
            if task_resolution.get('document_ids'):
                requested_action = dict(requested_action)
                auto_linked_chat_upload_document_ids = list(task_resolution.get('document_ids') or [])
                requested_action['document_ids'] = auto_linked_chat_upload_document_ids
                requested_action['doc_scope'] = _merge_document_scope_with_conversation_task_documents(
                    requested_action.get('doc_scope') or data.get('doc_scope') or 'personal',
                    task_resolution.get('documents') or [],
                    assigned_knowledge_filters=assigned_knowledge_filters,
                    assigned_knowledge_user_context_active=False,
                )

                resolved_group_ids = _normalize_conversation_task_document_ids(
                    requested_action.get('active_group_ids') or requested_action.get('active_group_id')
                )
                resolved_public_workspace_ids = _normalize_conversation_task_document_ids(
                    requested_action.get('active_public_workspace_id')
                    or requested_action.get('active_public_workspace_ids')
                )
                for task_document in task_resolution.get('documents') or []:
                    task_group_id = str(task_document.get('group_id') or '').strip() if isinstance(task_document, dict) else ''
                    task_public_workspace_id = str(task_document.get('public_workspace_id') or '').strip() if isinstance(task_document, dict) else ''
                    if task_group_id and task_group_id not in resolved_group_ids:
                        resolved_group_ids.append(task_group_id)
                    if task_public_workspace_id and task_public_workspace_id not in resolved_public_workspace_ids:
                        resolved_public_workspace_ids.append(task_public_workspace_id)
                requested_action['active_group_ids'] = resolved_group_ids
                requested_action['active_public_workspace_id'] = resolved_public_workspace_ids
                debug_print(
                    '[ChatDocumentAction] Auto-filled Analyze targets from linked chat uploads | '
                    f'user_id={user_id} | conversation_id={conversation_id} | '
                    f'documents={len(auto_linked_chat_upload_document_ids)}'
                )
            elif task_resolution.get('pending_count'):
                return {
                    'error': 'Uploaded task documents are still processing. Try again when the upload is ready.'
                }, 400
        try:
            normalized_action = normalize_document_action_config(
                action_payload=requested_action,
                max_documents_by_type=get_document_action_max_documents_by_type(
                    DOCUMENT_ACTION_CONTEXT_CHAT,
                    settings=settings,
                ),
                allowed_action_types=get_enabled_document_action_types(settings=settings),
            )
        except ValueError as exc:
            debug_print(
                '[ChatDocumentAction] Validation failed | '
                f'user_id={user_id} | '
                f'conversation_id={conversation_id or "new"} | '
                f'error={exc}'
            )
            return {'error': str(exc)}, 400
        if normalized_action.get('type') == DOCUMENT_ACTION_TYPE_NONE:
            return {'error': 'Select a document action before sending this request.'}, 400

        selected_document_ids = normalized_action.get('document_ids', [])
        document_scope = normalized_action.get('doc_scope', 'all')
        requested_action_group_ids = _normalize_requested_scope_ids(normalized_action.get('active_group_ids'))
        requested_action_public_workspace_ids = _normalize_requested_scope_ids(
            normalized_action.get('active_public_workspace_id')
        )
        action_scope_context = _get_authorized_chat_scope_context(
            user_id,
            active_group_ids=requested_action_group_ids,
            active_public_workspace_ids=requested_action_public_workspace_ids,
        )
        unauthorized_group_ids = [
            group_id
            for group_id in requested_action_group_ids
            if group_id not in action_scope_context.get('active_group_ids', [])
        ]
        unauthorized_public_workspace_ids = [
            workspace_id
            for workspace_id in requested_action_public_workspace_ids
            if workspace_id not in action_scope_context.get('active_public_workspace_ids', [])
        ]
        if unauthorized_group_ids or unauthorized_public_workspace_ids:
            return {
                'error': 'You do not have access to one or more selected workspaces.'
            }, 403

        normalized_action = dict(normalized_action)
        normalized_action['active_group_ids'] = action_scope_context.get('active_group_ids', [])
        normalized_action['active_public_workspace_id'] = action_scope_context.get('active_public_workspace_ids', [])
        active_group_ids = normalized_action.get('active_group_ids', [])
        active_public_workspace_ids = normalized_action.get('active_public_workspace_id', [])
        if assigned_knowledge_filters and not _assigned_knowledge_allows_document_action(
            assigned_knowledge_filters,
            normalized_action.get('type'),
        ):
            return {
                'error': 'This agent does not allow that workspace document action with user context.'
            }, 403
        runner_type = 'agent' if request_agent_info else 'model'
        debug_print(
            '[ChatDocumentAction] Normalized action | '
            f'user_id={user_id} | '
            f'conversation_id={conversation_id or "new"} | '
            f'action_type={normalized_action.get("type")} | '
            f'doc_scope={document_scope} | '
            f'documents={len(selected_document_ids)} | '
            f'group_ids={len(active_group_ids)} | '
            f'public_workspace_ids={len(active_public_workspace_ids)} | '
            f'runner_type={runner_type}'
        )

        if conversation_item is None:
            try:
                conversation_item = _load_or_create_analyze_conversation(user_id, conversation_id=conversation_id)
            except PermissionError as exc:
                return {'error': str(exc)}, 403

        conversation_id = conversation_item.get('id')
        g.conversation_id = conversation_id

        previous_thread_id = _get_latest_chat_thread_id(conversation_id)
        current_thread_id = str(uuid.uuid4())
        user_message_id = f"{conversation_id}_user_{int(time.time())}_{random.randint(1000,9999)}"
        user_metadata = _build_document_action_user_metadata(
            data=data,
            user_id=user_id,
            conversation_id=conversation_id,
            current_thread_id=current_thread_id,
            previous_thread_id=previous_thread_id,
            normalized_action=normalized_action,
            request_agent_info=request_agent_info,
            assigned_knowledge_filters=assigned_knowledge_filters,
            streaming_enabled=callable(publish_background_event),
        )
        if auto_linked_chat_upload_document_ids:
            user_metadata['workspace_search']['auto_linked_chat_upload_document_ids'] = auto_linked_chat_upload_document_ids
            user_metadata['workspace_search']['auto_linked_chat_upload_document_count'] = len(auto_linked_chat_upload_document_ids)
            user_metadata['document_action']['auto_linked_chat_upload_document_ids'] = auto_linked_chat_upload_document_ids
        user_message_doc = make_json_serializable({
            'id': user_message_id,
            'conversation_id': conversation_id,
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.utcnow().isoformat(),
            'model_deployment_name': data.get('model_deployment'),
            'metadata': user_metadata,
        })
        cosmos_messages_container.upsert_item(user_message_doc)

        try:
            document_action_activity_context = {
                key: value
                for key, value in {
                    'conversation_source': 'document_action_chat',
                    'document_action_type': normalized_action.get('type'),
                    'selected_document_count': len(selected_document_ids),
                    'streaming_enabled': bool(callable(publish_background_event)),
                    'runner_type': runner_type,
                }.items()
                if value not in (None, '', [])
            }
            log_chat_activity(
                user_id=user_id,
                conversation_id=conversation_id,
                message_type='user_message',
                message_length=len(user_message) if user_message else 0,
                has_document_search=False,
                has_image_generation=False,
                document_scope=document_scope,
                chat_context=(user_metadata.get('chat_context') or {}).get('chat_type'),
                workspace_type=(user_metadata.get('chat_context') or {}).get('chat_type'),
                group_id=active_group_ids[0] if document_scope == 'group' and active_group_ids else None,
                public_workspace_id=active_public_workspace_ids[0] if document_scope == 'public' and active_public_workspace_ids else None,
                additional_context=document_action_activity_context,
            )
        except Exception as e:
            debug_print(f"Activity logging error: {e}")

        title_updated = _set_initial_conversation_title(conversation_item, user_message)
        if title_updated:
            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            cosmos_conversations_container.upsert_item(conversation_item)
            if callable(publish_background_event):
                publish_background_event(_build_conversation_metadata_stream_event(conversation_item))

        assistant_message_id, thought_tracker, assistant_thread_attempt, response_message_context = _initialize_assistant_response_tracking(
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            current_user_thread_id=current_thread_id,
            previous_thread_id=previous_thread_id,
            retry_thread_attempt=None,
            is_retry=False,
            user_id=user_id,
        )

        publish_stream_thought = None
        stream_activity_callback = None
        if callable(publish_background_event):
            publish_stream_thought, stream_activity_callback = _build_document_action_stream_activity_callback(
                publish_background_event,
                assistant_message_id,
            )
            if callable(publish_stream_thought):
                publish_stream_thought(
                    f"Queued {normalized_action.get('type').replace('_', ' ')} for {len(selected_document_ids)} selected document{'s' if len(selected_document_ids) != 1 else ''}"
                )

        assigned_knowledge_action_context = {}
        assigned_context_metadata = {}
        assigned_knowledge_context_citations = []
        if assigned_knowledge_filters and assigned_knowledge_filters.get('has_workspace_knowledge'):
            try:
                assigned_knowledge_action_context = _build_assigned_knowledge_reference_context(
                    assigned_knowledge_filters,
                    query=user_message,
                    user_id=user_id,
                    top_n=ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N,
                )
            except SemanticSearchQuotaExceededError as exc:
                debug_print(f'Semantic search quota exceeded during Assigned Knowledge action context search: {exc}')
                return {
                    'error': exc.user_message,
                    'warning_type': SEMANTIC_SEARCH_QUOTA_WARNING_TYPE,
                    'service_health_warning': True,
                }, 503
            except Exception as exc:
                debug_print(f'[ChatDocumentAction] Assigned Knowledge context search failed: {exc}')
                return {
                    'error': 'There was an issue searching the assigned knowledge for this agent.'
                }, 500

            assigned_context_metadata = assigned_knowledge_action_context.get('metadata') or {}
            assigned_knowledge_context_citations = list(assigned_knowledge_action_context.get('citations') or [])
            if assigned_context_metadata.get('searched'):
                user_metadata.setdefault('workspace_search', {})['assigned_knowledge_context'] = assigned_context_metadata
                user_metadata.setdefault('document_action', {})['assigned_knowledge_context'] = assigned_context_metadata
                user_message_doc['metadata'] = user_metadata
                cosmos_messages_container.upsert_item(user_message_doc)
                assigned_context_thought = (
                    'Searched assigned knowledge for '
                    f"{assigned_context_metadata.get('result_count', 0)} reference excerpt(s)"
                )
                if callable(publish_stream_thought):
                    publish_stream_thought(assigned_context_thought)
                elif thought_tracker.enabled:
                    thought_tracker.add_thought('search', assigned_context_thought)

        workflow_task_prompt = _build_document_action_prompt_with_assigned_knowledge_context(
            user_message,
            assigned_knowledge_action_context.get('context_block'),
            normalized_action.get('type'),
        )

        workflow_like = {
            'id': f'chat-analyze:{conversation_id}',
            'user_id': user_id,
            'name': 'Chat Document Action',
            'task_prompt': workflow_task_prompt,
            'runner_type': runner_type,
            'selected_agent': request_agent_info,
            'assigned_knowledge_context': assigned_context_metadata,
            'model_endpoint_id': str(data.get('model_endpoint_id') or '').strip(),
            'model_id': str(data.get('model_id') or '').strip(),
            'legacy_model_deployment': str(data.get('model_deployment') or '').strip(),
            'model_binding_summary': {
                'endpoint_id': str(data.get('model_endpoint_id') or '').strip(),
                'model_id': str(data.get('model_id') or '').strip(),
                'provider': str(data.get('model_provider') or '').strip(),
            },
            'document_action': normalized_action,
            'analyze': {
                'enabled': normalized_action.get('type') == DOCUMENT_ACTION_TYPE_ANALYZE,
                'document_ids': normalized_action.get('document_ids', []),
                'doc_scope': normalized_action.get('doc_scope'),
                'active_group_ids': normalized_action.get('active_group_ids', []),
                'active_public_workspace_id': normalized_action.get('active_public_workspace_id', []),
                'window_unit': normalized_action.get('window_unit'),
                'window_size': normalized_action.get('window_size'),
                'window_percent': normalized_action.get('window_percent'),
                'max_retries_per_window': normalized_action.get('max_retries_per_window'),
            },
        }

        try:
            debug_print(
                '[ChatDocumentAction] Executing action | '
                f'user_id={user_id} | '
                f'conversation_id={conversation_id} | '
                f'action_type={normalized_action.get("type")} | '
                f'runner_type={runner_type} | '
                f'assistant_message_id={assistant_message_id}'
            )
            execution_result = _execute_document_action_workflow(
                workflow_like,
                settings,
                conversation_id=conversation_id,
                run_id=assistant_message_id,
                thought_tracker=thought_tracker,
                external_activity_callback=stream_activity_callback,
            )
        except Exception as exc:
            debug_print(
                '[ChatDocumentAction] Execution failed | '
                f'user_id={user_id} | '
                f'conversation_id={conversation_id} | '
                f'action_type={normalized_action.get("type")} | '
                f'runner_type={runner_type} | '
                f'error={exc}'
            )
            log_event(
                f'[ChatDocumentAnalysis] Chat document analysis failed: {exc}',
                extra={
                    'conversation_id': conversation_id,
                    'user_id': user_id,
                    'document_count': len(selected_document_ids),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return {'error': str(exc), 'conversation_id': conversation_id, 'user_message_id': user_message_id}, 500

        assistant_timestamp = datetime.utcnow().isoformat()
        hybrid_citations_list = _build_document_action_hybrid_citations(execution_result)
        if assigned_knowledge_context_citations:
            hybrid_citations_list.extend(assigned_knowledge_context_citations)
            hybrid_citations_list.sort(key=_build_hybrid_citation_sort_key, reverse=True)
        prepared_agent_citations = persist_agent_citation_artifacts(
            conversation_id=conversation_id,
            assistant_message_id=assistant_message_id,
            agent_citations=execution_result.get('agent_citations') or [],
            created_timestamp=assistant_timestamp,
            user_info=response_message_context.get('user_info'),
        )
        document_generated_analysis_artifacts = list(execution_result.get('generated_analysis_artifacts') or [])
        document_generated_tabular_outputs = list(execution_result.get('generated_tabular_outputs') or [])
        assistant_table_generated_output = maybe_create_assistant_table_generated_output(
            user_question=user_message,
            assistant_content=execution_result.get('reply', ''),
            conversation_id=conversation_id,
            existing_outputs=document_generated_analysis_artifacts + document_generated_tabular_outputs,
        )
        if assistant_table_generated_output:
            document_generated_analysis_artifacts.append(assistant_table_generated_output)
            document_generated_tabular_outputs.append(assistant_table_generated_output)
        generated_analysis_metadata = _build_generated_analysis_metadata(
            generated_analysis_artifacts=document_generated_analysis_artifacts,
            generated_tabular_outputs=document_generated_tabular_outputs,
        )
        document_action_capability_usage = _build_capability_usage_metadata(
            workspace_search_used=True,
            workspace_search_result_count=len(hybrid_citations_list or []),
            document_action_type=normalized_action.get('type'),
            document_scope=document_scope,
            selected_document_ids=selected_document_ids,
            active_group_ids=active_group_ids,
            active_public_workspace_ids=active_public_workspace_ids,
        )

        assistant_doc = make_json_serializable({
            'id': assistant_message_id,
            'conversation_id': conversation_id,
            'role': 'assistant',
            'content': execution_result.get('reply', ''),
            'timestamp': assistant_timestamp,
            'augmented': False,
            'hybrid_citations': hybrid_citations_list,
            'web_search_citations': [],
            'hybridsearch_query': None,
            'agent_citations': prepared_agent_citations,
            'model_deployment_name': execution_result.get('model_deployment_name'),
            'agent_display_name': execution_result.get('agent_display_name'),
            'agent_name': execution_result.get('agent_name'),
            'metadata': {
                'token_usage': execution_result.get('token_usage'),
                'user_info': response_message_context.get('user_info'),
                'capability_usage': document_action_capability_usage,
                'thread_info': {
                    'thread_id': response_message_context.get('thread_id'),
                    'previous_thread_id': response_message_context.get('previous_thread_id'),
                    'active_thread': True,
                    'thread_attempt': assistant_thread_attempt,
                },
                **generated_analysis_metadata,
                'analyze': {
                    'enabled': normalized_action.get('type') == DOCUMENT_ACTION_TYPE_ANALYZE,
                    'coverage': execution_result.get('analysis_coverage') or {},
                },
                'compare': {
                    'enabled': normalized_action.get('type') == DOCUMENT_ACTION_TYPE_COMPARISON,
                    'document_count': len(selected_document_ids),
                },
                'assigned_knowledge_context': assigned_context_metadata,
                'document_action': normalized_action,
            },
        })
        cosmos_messages_container.upsert_item(assistant_doc)

        token_usage = execution_result.get('token_usage') if isinstance(execution_result.get('token_usage'), dict) else None
        if token_usage and token_usage.get('total_tokens'):
            try:
                workspace_type = 'personal'
                effective_active_group_id = active_group_ids[0] if active_group_ids else None
                effective_active_public_workspace_id = active_public_workspace_ids[0] if active_public_workspace_ids else None
                if effective_active_public_workspace_id:
                    workspace_type = 'public'
                elif effective_active_group_id:
                    workspace_type = 'group'

                log_token_usage(
                    user_id=user_id,
                    token_type='chat',
                    total_tokens=token_usage.get('total_tokens'),
                    model=execution_result.get('model_deployment_name'),
                    workspace_type=workspace_type,
                    prompt_tokens=token_usage.get('prompt_tokens'),
                    completion_tokens=token_usage.get('completion_tokens'),
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    group_id=effective_active_group_id,
                    public_workspace_id=effective_active_public_workspace_id,
                    additional_context={
                        'document_action_type': normalized_action.get('type'),
                        'runner_type': runner_type,
                        'request_count': token_usage.get('request_count'),
                    },
                )
            except Exception as log_error:
                debug_print(f'[ChatDocumentAction] Failed to log token usage: {log_error}')

        _set_initial_conversation_title(conversation_item, user_message)

        conversation_item['last_updated'] = datetime.utcnow().isoformat()
        conversation_item['chat_type'] = data.get('chat_type') or conversation_item.get('chat_type') or 'new'

        try:
            conversation_item = collect_conversation_metadata(
                user_message=user_message,
                conversation_id=conversation_id,
                user_id=user_id,
                active_group_id=active_group_ids[0] if active_group_ids else None,
                active_group_ids=active_group_ids,
                document_scope=document_scope,
                selected_document_id=selected_document_ids[0] if selected_document_ids else None,
                model_deployment=execution_result.get('model_deployment_name'),
                hybrid_search_enabled=False,
                image_gen_enabled=False,
                selected_documents=execution_result.get('analysis_result', {}).get('documents', []),
                selected_agent=execution_result.get('agent_name'),
                selected_agent_details=_build_agent_selection_metadata(
                    request_agent_info,
                    assigned_knowledge_filters,
                ),
                search_results=None,
                conversation_item=conversation_item,
                active_public_workspace_id=active_public_workspace_ids[0] if active_public_workspace_ids else None,
                active_public_workspace_ids=active_public_workspace_ids,
            )
        except Exception as exc:
            debug_print(f'[ChatDocumentAnalysis] Conversation metadata update failed: {exc}')

        cosmos_conversations_container.upsert_item(conversation_item)
        debug_print(
            '[ChatDocumentAction] Execution completed | '
            f'user_id={user_id} | '
            f'conversation_id={conversation_id} | '
            f'action_type={normalized_action.get("type")} | '
            f'runner_type={runner_type} | '
            f'assistant_message_id={assistant_message_id} | '
            f"model={execution_result.get('model_deployment_name')} | "
            f"processed_windows={(execution_result.get('analysis_coverage') or {}).get('processed_windows', 0)} | "
            f"failed_windows={(execution_result.get('analysis_coverage') or {}).get('failed_windows', 0)}"
        )

        return make_json_serializable({
            'reply': execution_result.get('reply', ''),
            'conversation_id': conversation_id,
            'conversation_title': conversation_item.get('title', 'New Conversation'),
            'classification': conversation_item.get('classification', []),
            'context': conversation_item.get('context', []),
            'chat_type': conversation_item.get('chat_type'),
            'scope_locked': conversation_item.get('scope_locked'),
            'locked_contexts': conversation_item.get('locked_contexts', []),
            'model_deployment_name': execution_result.get('model_deployment_name'),
            'agent_display_name': execution_result.get('agent_display_name'),
            'agent_name': execution_result.get('agent_name'),
            'message_id': assistant_message_id,
            'user_message_id': user_message_id,
            'blocked': False,
            'augmented': False,
            'hybrid_citations': hybrid_citations_list,
            'web_search_citations': [],
            'agent_citations': prepared_agent_citations,
            'reload_messages': False,
            'kernel_fallback_notice': None,
            'thoughts_enabled': thought_tracker.enabled,
            'analysis_coverage': execution_result.get('analysis_coverage') or {},
            'document_action': normalized_action,
            'token_usage': execution_result.get('token_usage'),
            'metadata': assistant_doc.get('metadata', {}),
        }), 200

    def execute_analyze_chat_request(data=None, publish_background_event=None):
        return execute_document_action_chat_request(
            data=data,
            publish_background_event=publish_background_event,
            forced_action_type=DOCUMENT_ACTION_TYPE_ANALYZE,
        )

    @app.route('/api/chat/document-action', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_document_action_api():
        payload, status_code = execute_document_action_chat_request()
        return jsonify(payload), status_code

    @app.route('/api/chat/document-action/stream', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_document_action_stream_api():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json() or {}
        conversation_id = getattr(g, 'conversation_id', None) or data.get('conversation_id')
        if conversation_id is not None:
            conversation_id = str(conversation_id).strip() or None
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        data['conversation_id'] = conversation_id
        g.conversation_id = conversation_id
        stream_session = CHAT_STREAM_REGISTRY.start_session(user_id, conversation_id)

        def generate_document_action_response(publish_background_event=None):
            try:
                if stream_session and stream_session.is_cancel_requested():
                    yield _build_stream_cancel_event(
                        conversation_id,
                        reason=stream_session.get_cancel_reason(),
                    )
                    return

                payload, status_code = execute_document_action_chat_request(
                    data=data,
                    publish_background_event=publish_background_event,
                )
                if stream_session and stream_session.is_cancel_requested():
                    yield _build_stream_cancel_event(
                        payload.get('conversation_id') or conversation_id,
                        user_message_id=payload.get('user_message_id'),
                        message_id=payload.get('message_id'),
                        partial_content=payload.get('reply') or payload.get('full_content') or '',
                        reason=stream_session.get_cancel_reason(),
                        message_persisted=bool(payload.get('message_id')),
                    )
                    return
                if status_code >= 400:
                    error_message = payload.get('error') or f'Document action failed ({status_code})'
                    yield f"data: {json.dumps({'error': error_message, 'conversation_id': payload.get('conversation_id')})}\n\n"
                    return

                yield f"data: {json.dumps(normalize_terminal_chat_payload(payload))}\n\n"
            except Exception as document_action_error:
                yield f"data: {json.dumps({'error': str(document_action_error), 'conversation_id': conversation_id})}\n\n"

        return build_background_stream_response(generate_document_action_response, stream_session=stream_session)

    @app.route('/api/chat/analyze', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_analyze_api():
        payload, status_code = execute_analyze_chat_request()
        return jsonify(payload), status_code

    @app.route('/api/chat/analyze/stream', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_analyze_stream_api():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json() or {}
        conversation_id = getattr(g, 'conversation_id', None) or data.get('conversation_id')
        if conversation_id is not None:
            conversation_id = str(conversation_id).strip() or None
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        data['conversation_id'] = conversation_id
        g.conversation_id = conversation_id
        stream_session = CHAT_STREAM_REGISTRY.start_session(user_id, conversation_id)

        def generate_analyze_response(publish_background_event=None):
            try:
                if stream_session and stream_session.is_cancel_requested():
                    yield _build_stream_cancel_event(
                        conversation_id,
                        reason=stream_session.get_cancel_reason(),
                    )
                    return

                payload, status_code = execute_analyze_chat_request(
                    data=data,
                    publish_background_event=publish_background_event,
                )
                if stream_session and stream_session.is_cancel_requested():
                    yield _build_stream_cancel_event(
                        payload.get('conversation_id') or conversation_id,
                        user_message_id=payload.get('user_message_id'),
                        message_id=payload.get('message_id'),
                        partial_content=payload.get('reply') or payload.get('full_content') or '',
                        reason=stream_session.get_cancel_reason(),
                        message_persisted=bool(payload.get('message_id')),
                    )
                    return
                if status_code >= 400:
                    error_message = payload.get('error') or f'Document analysis failed ({status_code})'
                    yield f"data: {json.dumps({'error': error_message, 'conversation_id': payload.get('conversation_id')})}\n\n"
                    return

                yield f"data: {json.dumps(normalize_terminal_chat_payload(payload))}\n\n"
            except Exception as analysis_error:
                yield f"data: {json.dumps({'error': str(analysis_error), 'conversation_id': conversation_id})}\n\n"

        return build_background_stream_response(generate_analyze_response, stream_session=stream_session)

    @app.route('/api/chat/image-proposals/generate', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def generate_image_from_proposal():
        """Approve a model-authored image proposal and persist the generated image."""
        data = request.get_json(silent=True) or {}
        try:
            settings = get_settings()
            if not image_generation_is_enabled(settings):
                return jsonify({'error': 'Image generation is not enabled'}), 403

            user_id = get_current_user_id()
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            conversation_id = str(data.get('conversation_id') or '').strip()
            if not conversation_id:
                return jsonify({'error': 'conversation_id is required'}), 400

            conversation_item = _authorize_personal_conversation_access(user_id, conversation_id)

            proposal_payload = data.get('proposal') if isinstance(data.get('proposal'), dict) else dict(data)
            if data.get('prompt'):
                proposal_payload = dict(proposal_payload)
                proposal_payload['prompt'] = data.get('prompt')
            proposal = normalize_image_proposal(proposal_payload)

            source_assistant_message_id = str(
                data.get('assistant_message_id')
                or data.get('source_assistant_message_id')
                or ''
            ).strip()
            if source_assistant_message_id:
                try:
                    source_message = cosmos_messages_container.read_item(
                        item=source_assistant_message_id,
                        partition_key=conversation_id,
                    )
                    if source_message.get('conversation_id') != conversation_id:
                        return jsonify({'error': 'Source message does not belong to this conversation'}), 403
                    if source_message.get('role') != 'assistant':
                        return jsonify({'error': 'Source message must be an assistant message'}), 400
                except CosmosResourceNotFoundError:
                    source_assistant_message_id = ''

            image_result = generate_chat_image_message(
                settings=settings,
                user_id=user_id,
                conversation_id=conversation_id,
                prompt=proposal['prompt'],
                user_info=get_current_user_info(),
                proposal=proposal,
                source_assistant_message_id=source_assistant_message_id or None,
                store_in_blob=True,
            )

            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            cosmos_conversations_container.upsert_item(conversation_item)

            image_doc = image_result.pop('image_message', {}) or {}
            image_doc_metadata = image_doc.get('metadata') if isinstance(image_doc.get('metadata'), dict) else {}
            response_metadata = {}
            if isinstance(image_doc_metadata.get('image_proposal'), dict):
                response_metadata['image_proposal'] = image_doc_metadata['image_proposal']
            image_result.update({
                'conversation_title': conversation_item.get('title'),
                'image_message': {
                    'id': image_doc.get('id') or image_result.get('message_id'),
                    'conversation_id': conversation_id,
                    'role': 'image',
                    'content': image_result.get('image_url'),
                    'prompt': image_doc.get('prompt') or proposal['prompt'],
                    'created_at': image_doc.get('created_at'),
                    'timestamp': image_doc.get('timestamp'),
                    'model_deployment_name': image_result.get('model_deployment_name'),
                    'metadata': response_metadata,
                },
            })

            return jsonify(image_result), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation or source message not found'}), 404
        except PermissionError as exc:
            return jsonify({'error': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'error': str(exc)}), 400
        except Exception as exc:
            error_message = str(exc)
            status_code = 500
            if 'safety system' in error_message.lower() or 'moderation_blocked' in error_message:
                error_message = 'Image generation was blocked by content safety policies. Please edit the prompt and try again.'
                status_code = 400
            elif '400' in error_message and 'BadRequestError' in str(type(exc)):
                status_code = 400

            log_event(
                f'[ImageGeneration] Proposal approval failed: {exc}',
                extra={'conversation_id': data.get('conversation_id') if isinstance(data, dict) else None},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': error_message}), status_code

    @app.route('/api/chat', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_api():
        try:
            request_start_time = time.time()
            settings = get_settings()
            data = request.get_json()
            user_id = get_current_user_id()
            if not user_id:
                return jsonify({
                    'error': 'User not authenticated'
                }), 401

            # Extract agent_info early to guide GPT initialization decisions
            request_agent_info = data.get('agent_info')

            # Extract from request
            user_message = data.get('message', '')
            conversation_id = getattr(g, 'conversation_id', None) or data.get('conversation_id')
            if conversation_id is not None:
                conversation_id = str(conversation_id).strip() or None
            hybrid_search_enabled = data.get('hybrid_search')
            web_search_enabled = data.get('web_search_enabled')
            url_access_enabled = data.get('url_access_enabled')
            source_review_enabled = data.get('source_review_enabled')
            deep_research_enabled = data.get('deep_research_enabled')
            selected_document_id = data.get('selected_document_id')
            selected_document_ids = data.get('selected_document_ids', [])
            # Backwards compat: if no multi-select but single ID is set, wrap in list
            if not selected_document_ids and selected_document_id:
                selected_document_ids = [selected_document_id]
            image_gen_enabled = data.get('image_generation')
            document_scope = data.get('doc_scope')
            tags_filter = data.get('tags', [])  # Extract tags filter
            reload_messages_required = False

            def parse_json_string(candidate: str) -> Any:
                """Parse JSON content when strings look like serialized structures."""
                trimmed = candidate.strip()
                if not trimmed or trimmed[0] not in ('{', '['):
                    return None
                try:
                    return json.loads(trimmed)
                except Exception as exc:
                    log_event(
                        f"[result_requires_message_reload] Failed to parse JSON: {str(exc)} | candidate: {trimmed[:200]}",
                        level=logging.WARNING
                    )
                    return None

            def dict_requires_reload(payload: Dict[str, Any]) -> bool:
                """Inspect dictionary payloads for any signal that messages were persisted."""
                if payload.get('reload_messages') or payload.get('requires_message_reload'):
                    return True

                metadata = payload.get('metadata')
                if isinstance(metadata, dict) and metadata.get('requires_message_reload'):
                    return True

                image_url = payload.get('image_url')
                if isinstance(image_url, dict) and image_url.get('url'):
                    return True
                if isinstance(image_url, str) and image_url.strip():
                    return True

                result_type = payload.get('type')
                if isinstance(result_type, str) and result_type.lower() == 'image_url':
                    return True

                mime = payload.get('mime')
                if isinstance(mime, str) and mime.startswith('image/'):
                    return True

                for value in payload.values():
                    if result_requires_message_reload(value):
                        return True
                return False

            def list_requires_reload(items: List[Any]) -> bool:
                """Evaluate list items for reload requirements."""
                return any(result_requires_message_reload(item) for item in items)

            def result_requires_message_reload(result: Any) -> bool:
                """Heuristically detect plugin outputs that inject new Cosmos messages (e.g., chart images)."""
                if result is None:
                    return False
                if isinstance(result, str):
                    parsed = parse_json_string(result)
                    return result_requires_message_reload(parsed) if parsed is not None else False
                if isinstance(result, list):
                    return list_requires_reload(result)
                if isinstance(result, dict):
                    return dict_requires_reload(result)
                return False

            active_group_id = data.get('active_group_id')
            active_group_ids = data.get('active_group_ids', [])
            active_public_workspace_id = data.get('active_public_workspace_id')  # Extract active public workspace ID
            active_public_workspace_ids = data.get('active_public_workspace_ids', [])
            scope_context = _get_authorized_chat_scope_context(
                user_id,
                active_group_id=active_group_id,
                active_group_ids=active_group_ids,
                active_public_workspace_id=active_public_workspace_id,
                active_public_workspace_ids=active_public_workspace_ids,
            )
            active_group_ids = scope_context['active_group_ids']
            active_group_id = scope_context['active_group_id']
            active_public_workspace_ids = scope_context['active_public_workspace_ids']
            active_public_workspace_id = scope_context['active_public_workspace_id']
            frontend_gpt_model = data.get('model_deployment')
            top_n_results = data.get('top_n')  # Extract top_n parameter from request
            classifications_to_send = data.get('classifications')  # Extract classifications parameter from request
            chat_type = data.get('chat_type', 'user')  # 'user' or 'group', default to 'user'
            reasoning_effort = data.get('reasoning_effort')  # Extract reasoning effort for reasoning models

            # Check if this is a retry or edit request (both work the same way - reuse existing user message)
            retry_user_message_id = data.get('retry_user_message_id') or data.get('edited_user_message_id')
            retry_thread_id = data.get('retry_thread_id')
            retry_thread_attempt = data.get('retry_thread_attempt')
            is_retry = bool(retry_user_message_id)
            is_edit = bool(data.get('edited_user_message_id'))

            if is_retry:
                operation_type = 'Edit' if is_edit else 'Retry'
                debug_print(f"🔍 Chat API - {operation_type} detected! user_message_id={retry_user_message_id}, thread_id={retry_thread_id}, attempt={retry_thread_attempt}")

            # Validate chat_type
            if chat_type not in ('user', 'group'):
                chat_type = 'user'

            search_query = user_message # <--- ADD THIS LINE (Initialize search_query)
            web_search_query_text = build_web_search_query_text(user_message)
            hybrid_citations_list = [] # <--- ADD THIS LINE (Initialize hybrid list)
            agent_citations_list = [] # <--- ADD THIS LINE (Initialize agent citations list)
            web_search_citations_list = []
            source_review_result = {}
            deep_research_result = {}
            deep_research_query_plan = {}
            deep_research_web_search_runs = []
            generated_tabular_outputs_list = []
            generated_analysis_artifacts_list = []
            system_messages_for_augmentation = [] # Collect system messages from search
            search_results = []
            selected_agent = None  # Initialize selected_agent early to prevent NameError
            # --- Configuration ---
            # History / Summarization Settings
            raw_conversation_history_limit = settings.get('conversation_history_limit', 6)
            # Round up to nearest even number
            conversation_history_limit = math.ceil(raw_conversation_history_limit)
            if conversation_history_limit % 2 != 0:
                conversation_history_limit += 1
            enable_summarize_content_history_beyond_conversation_history_limit = settings.get('enable_summarize_content_history_beyond_conversation_history_limit', True) # Use a dedicated setting if possible
            enable_summarize_content_history_for_search = settings.get('enable_summarize_content_history_for_search', False) # Use a dedicated setting if possible
            number_of_historical_messages_to_summarize = settings.get('number_of_historical_messages_to_summarize', 10) # Number of messages to summarize for search context

            max_file_content_length = 50000 # 50KB

            # Convert toggles from string -> bool if needed
            if isinstance(hybrid_search_enabled, str):
                hybrid_search_enabled = hybrid_search_enabled.lower() == 'true'
            if isinstance(web_search_enabled, str):
                web_search_enabled = web_search_enabled.lower() == 'true'
            if isinstance(url_access_enabled, str):
                url_access_enabled = url_access_enabled.lower() == 'true'
            if isinstance(source_review_enabled, str):
                source_review_enabled = source_review_enabled.lower() == 'true'
            if isinstance(deep_research_enabled, str):
                deep_research_enabled = deep_research_enabled.lower() == 'true'
            if isinstance(image_gen_enabled, str):
                image_gen_enabled = image_gen_enabled.lower() == 'true'
            user_workspace_context_requested = data.get('user_workspace_context_enabled')
            if isinstance(user_workspace_context_requested, str):
                user_workspace_context_requested = user_workspace_context_requested.lower() == 'true'
            user_workspace_context_requested = bool(user_workspace_context_requested)
            current_user_info = get_current_user_info() or {}
            current_user_email = current_user_info.get('email')
            current_user_roles = (session.get('user') or {}).get('roles', [])
            prompt_urls = extract_urls_from_text(user_message)
            url_access_requested = bool(url_access_enabled)
            if url_access_requested:
                url_access_validation = validate_url_access_request(
                    user_message,
                    settings,
                    URL_ACCESS_CONTEXT_CHAT,
                    user_roles=current_user_roles,
                )
                if not url_access_validation.get('allowed'):
                    limit = url_access_validation.get('limit') or get_url_access_max_urls(URL_ACCESS_CONTEXT_CHAT, settings)
                    if url_access_validation.get('reason') == 'url_count_exceeded':
                        return jsonify({
                            'error': f'URL Access supports up to {limit} URL(s) per chat message.'
                        }), 400
                    if url_access_validation.get('reason') == 'url_access_role_required':
                        return jsonify({'error': 'URL Access requires the UrlAccessUser app role.'}), 403
                    return jsonify({'error': 'URL Access is disabled by an administrator.'}), 403
            url_access_enabled = bool(
                url_access_requested
                and prompt_urls
                and is_url_access_enabled_for_user(settings, user_roles=current_user_roles)
            )
            source_review_allowed_for_user = is_source_review_enabled_for_user(
                settings,
                user_id,
                user_email=current_user_email,
                user_roles=current_user_roles,
            )
            deep_research_requested = bool(source_review_enabled) or bool(deep_research_enabled)
            deep_research_enabled = source_review_allowed_for_user and deep_research_requested
            source_review_enabled = bool(deep_research_enabled or url_access_enabled)

            history_grounded_search_used = False
            history_only_answerability = None
            prior_grounded_document_refs = []
            effective_document_scope = document_scope
            effective_selected_document_ids = list(selected_document_ids or [])
            effective_selected_document_id = selected_document_id
            effective_active_group_ids = list(active_group_ids or [])
            effective_active_group_id = active_group_id
            effective_active_public_workspace_ids = list(active_public_workspace_ids or [])
            effective_active_public_workspace_id = active_public_workspace_id
            assigned_knowledge_filters = None
            canonical_request_agent = _resolve_canonical_chat_agent(user_id, settings, request_agent_info)
            if canonical_request_agent:
                request_agent_info = canonical_request_agent
                assigned_knowledge_filters = build_assigned_knowledge_runtime_filters(canonical_request_agent)

            assigned_knowledge_user_context_active = False
            assigned_knowledge_url_review_urls = []
            assigned_knowledge_deep_research_urls = []
            if assigned_knowledge_filters:
                assigned_knowledge_user_context_active = (
                    user_workspace_context_requested
                    and _assigned_knowledge_allows_user_workspace_context(assigned_knowledge_filters)
                    and _assigned_knowledge_allows_document_action(
                        assigned_knowledge_filters,
                        DOCUMENT_ACTION_TYPE_NONE,
                    )
                )
                if assigned_knowledge_filters.get('has_workspace_knowledge'):
                    hybrid_search_enabled = True
                    if not assigned_knowledge_user_context_active:
                        effective_document_scope = assigned_knowledge_filters.get('doc_scope') or 'all'
                        effective_selected_document_ids = list(assigned_knowledge_filters.get('document_ids') or [])
                        effective_selected_document_id = None
                        effective_active_group_ids = list(assigned_knowledge_filters.get('active_group_ids') or [])
                        effective_active_group_id = effective_active_group_ids[0] if effective_active_group_ids else None
                        effective_active_public_workspace_ids = list(
                            assigned_knowledge_filters.get('active_public_workspace_ids') or []
                        )
                        effective_active_public_workspace_id = (
                            effective_active_public_workspace_ids[0]
                            if effective_active_public_workspace_ids
                            else None
                        )
                        tags_filter = list(assigned_knowledge_filters.get('tags_filter') or [])
                        document_scope = effective_document_scope
                        selected_document_ids = list(effective_selected_document_ids)
                        selected_document_id = None
                        active_group_ids = list(effective_active_group_ids)
                        active_group_id = effective_active_group_id
                        active_public_workspace_ids = list(effective_active_public_workspace_ids)
                        active_public_workspace_id = effective_active_public_workspace_id
                elif assigned_knowledge_user_context_active:
                    hybrid_search_enabled = True

                assigned_knowledge_url_review_urls = _get_assigned_knowledge_web_source_urls(
                    assigned_knowledge_filters,
                    ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_URL_REVIEW,
                )
                assigned_knowledge_deep_research_urls = _get_assigned_knowledge_web_source_urls(
                    assigned_knowledge_filters,
                    ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH,
                )
                if assigned_knowledge_url_review_urls and not is_url_access_enabled_for_user(
                    settings,
                    user_roles=current_user_roles,
                ):
                    return jsonify({
                        'error': 'This agent has assigned URL sources, but URL Access is not available for your account.'
                    }), 403
                if assigned_knowledge_deep_research_urls and not source_review_allowed_for_user:
                    return jsonify({
                        'error': 'This agent has assigned Deep Research sources, but Deep Research is not available for your account.'
                    }), 403
                if assigned_knowledge_url_review_urls or assigned_knowledge_deep_research_urls:
                    source_review_enabled = True
                    if assigned_knowledge_deep_research_urls:
                        deep_research_enabled = True
                g.assigned_knowledge_context = assigned_knowledge_filters
                g.assigned_knowledge_user_context_active = assigned_knowledge_user_context_active

            original_hybrid_search_enabled = bool(hybrid_search_enabled)

            # GPT & Image generation APIM or direct
            gpt_model = ""
            gpt_client = None
            gpt_provider = None
            gpt_endpoint = None
            gpt_auth = None
            gpt_api_version = None
            gpt_endpoint_id = None
            gpt_model_id = None
            tabular_model_context = None
            enable_gpt_apim = settings.get('enable_gpt_apim', False)
            enable_image_gen_apim = settings.get('enable_image_gen_apim', False)
            should_use_default_model = (
                _has_chat_agent_selection(request_agent_info)
                and settings.get('enable_multi_model_endpoints', False)
                and not data.get('model_id')
                and not data.get('model_endpoint_id')
            )
            try:
                multi_endpoint_config = None
                if settings.get('enable_multi_model_endpoints', False):
                    multi_endpoint_config = resolve_streaming_multi_endpoint_gpt_config(
                        settings,
                        data,
                        user_id,
                        active_group_ids=active_group_ids,
                        allow_default_selection=should_use_default_model,
                    )
                    if multi_endpoint_config and should_use_default_model and not data.get('model_endpoint_id'):
                        debug_print("[GPTClient] Using default multi-endpoint model for agent request.")
                if multi_endpoint_config:
                    (
                        gpt_client,
                        gpt_model,
                        gpt_provider,
                        gpt_endpoint,
                        gpt_auth,
                        gpt_api_version,
                        gpt_endpoint_id,
                        gpt_model_id,
                    ) = multi_endpoint_config
                elif enable_gpt_apim:
                    # read raw comma-delimited deployments
                    raw = settings.get('azure_apim_gpt_deployment', '')
                    if not raw:
                        raise ValueError("APIM GPT deployment name not configured.")

                    # split, strip, and filter out empty entries
                    apim_models = [m.strip() for m in raw.split(',') if m.strip()]
                    if not apim_models:
                        raise ValueError("No valid APIM GPT deployment names found.")

                    # if frontend specified one, use it (must be in the configured list)
                    if frontend_gpt_model:
                        if frontend_gpt_model not in apim_models:
                            raise ValueError(
                                f"Requested model '{frontend_gpt_model}' is not configured for APIM."
                            )
                        gpt_model = frontend_gpt_model

                    # otherwise if there's exactly one deployment, default to it
                    elif len(apim_models) == 1:
                        gpt_model = apim_models[0]

                    # otherwise you must pass model_deployment in the request
                    else:
                        if request_agent_info:
                            gpt_model = apim_models[0]
                            debug_print(
                                "[GPTClient] Agent request without model_deployment; defaulting to first APIM deployment."
                            )
                        else:
                            raise ValueError(
                                "Multiple APIM GPT deployments configured; please include "
                                "'model_deployment' in your request."
                            )

                    # initialize the APIM client
                    gpt_client = AzureOpenAI(
                        api_version=settings.get('azure_apim_gpt_api_version'),
                        azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
                        api_key=settings.get('azure_apim_gpt_subscription_key')
                    )
                else:
                    auth_type = settings.get('azure_openai_gpt_authentication_type')
                    endpoint = settings.get('azure_openai_gpt_endpoint')
                    api_version = settings.get('azure_openai_gpt_api_version')
                    gpt_model_obj = settings.get('gpt_model', {})

                    if gpt_model_obj and gpt_model_obj.get('selected'):
                        selected_gpt_model = gpt_model_obj['selected'][0]
                        gpt_model = selected_gpt_model['deploymentName']
                    else:
                        # Fallback or raise error if no model selected/configured
                        raise ValueError("No GPT model selected or configured.")

                    if frontend_gpt_model:
                        gpt_model = frontend_gpt_model
                    elif gpt_model_obj and gpt_model_obj.get('selected'):
                        selected_gpt_model = gpt_model_obj['selected'][0]
                        gpt_model = selected_gpt_model['deploymentName']
                    else:
                        raise ValueError("No GPT model selected or configured.")

                    if auth_type == 'managed_identity':
                        token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
                        gpt_client = AzureOpenAI(
                            api_version=api_version,
                            azure_endpoint=endpoint,
                            azure_ad_token_provider=token_provider
                        )
                    else: # Default to API Key
                        api_key = settings.get('azure_openai_gpt_key')
                        if not api_key: raise ValueError("Azure OpenAI API Key not configured.")
                        gpt_client = AzureOpenAI(
                            api_version=api_version,
                            azure_endpoint=endpoint,
                            api_key=api_key
                        )

                if not gpt_client or not gpt_model:
                    raise ValueError("GPT Client or Model could not be initialized.")

                tabular_model_context = build_model_endpoint_context(
                    provider=gpt_provider,
                    endpoint=gpt_endpoint,
                    auth=gpt_auth,
                    api_version=gpt_api_version,
                    endpoint_id=gpt_endpoint_id or data.get('model_endpoint_id'),
                    model_id=gpt_model_id or data.get('model_id'),
                    model_deployment=gpt_model,
                    user_id=user_id,
                    active_group_ids=active_group_ids,
                )

            except Exception as e:
                debug_print(f"Error initializing GPT client/model: {e}")
                # Handle error appropriately - maybe return 500 or default behavior
                return jsonify({'error': f'Failed to initialize AI model: {str(e)}'}), 500
        # region 1 - Load or Create Conversation
            # ---------------------------------------------------------------------
            # 1) Load or create conversation
            # ---------------------------------------------------------------------
            try:
                conversation_item, conversation_id = _resolve_or_create_authorized_personal_conversation(
                    user_id,
                    conversation_id,
                )
            except LookupError:
                return jsonify({'error': 'Conversation not found'}), 404
            except PermissionError:
                return jsonify({'error': 'Forbidden'}), 403
            except Exception as e:
                debug_print(f"Error reading conversation {conversation_id}: {e}")
                return jsonify({'error': f'Error reading conversation: {str(e)}'}), 500

            _set_authorized_chat_request_context(user_id, conversation_id, scope_context)

            auto_linked_chat_upload_document_ids = []
            chat_upload_context = _resolve_chat_upload_workspace_context(
                user_id=user_id,
                conversation_id=conversation_id,
                effective_document_scope=effective_document_scope,
                effective_selected_document_ids=effective_selected_document_ids,
                assigned_knowledge_filters=assigned_knowledge_filters,
                assigned_knowledge_user_context_active=assigned_knowledge_user_context_active,
                candidate_document_ids=data.get('conversation_task_document_ids'),
            )
            task_resolution = chat_upload_context.get('task_resolution') or {}
            if task_resolution.get('blocked') and task_resolution.get('linked_count'):
                return jsonify({'error': 'This agent does not allow uploaded task documents for search.'}), 403
            if (
                task_resolution.get('pending_count')
                and not task_resolution.get('document_ids')
                and not _has_nonpending_requested_task_document_selection(data, task_resolution)
            ):
                return jsonify(_build_chat_upload_pending_response_payload(task_resolution)), 400

            effective_document_scope = chat_upload_context.get('effective_document_scope')
            effective_selected_document_ids = list(chat_upload_context.get('effective_selected_document_ids') or [])
            auto_linked_chat_upload_document_ids = list(
                chat_upload_context.get('auto_linked_chat_upload_document_ids') or []
            )
            if auto_linked_chat_upload_document_ids:
                auto_linked_assigned_knowledge_user_context = (
                    assigned_knowledge_filters
                    and assigned_knowledge_filters.get('has_workspace_knowledge')
                    and not assigned_knowledge_user_context_active
                )
                if auto_linked_assigned_knowledge_user_context:
                    assigned_knowledge_user_context_active = True
                    g.assigned_knowledge_user_context_active = True
                    tags_filter = []
                    debug_print(
                        "[ChatUploadWorkspaceContext] Enabled Assigned Knowledge user context "
                        f"from {len(auto_linked_chat_upload_document_ids)} linked chat upload workspace document(s)."
                    )
                hybrid_search_enabled = True
                original_hybrid_search_enabled = True
                effective_selected_document_id = (
                    effective_selected_document_ids[0]
                    if len(effective_selected_document_ids) == 1
                    else None
                )
                selected_document_ids = list(effective_selected_document_ids)
                selected_document_id = effective_selected_document_id
                document_scope = effective_document_scope

            # Clear plugin invocations at start of message processing to ensure
            # each message only shows citations for tools executed during that specific interaction
            plugin_logger = get_plugin_logger()
            plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)

            # Determine the actual chat context based on existing conversation or document usage
            # For existing conversations, use the chat_type from conversation metadata
            # For new conversations, it will be determined during metadata collection
            actual_chat_type = 'personal_single_user'  # Default

            if conversation_item.get('chat_type'):
                # Use existing chat_type from conversation metadata
                actual_chat_type = conversation_item['chat_type']
                debug_print(f"[ChatType] Using existing chat_type from conversation: {actual_chat_type}")
            elif conversation_item.get('context'):
                # Fallback: determine from existing context
                primary_context = next((ctx for ctx in conversation_item['context'] if ctx.get('type') == 'primary'), None)
                if primary_context:
                    if primary_context.get('scope') == 'group':
                        actual_chat_type = 'group-single-user'  # Default to single-user for groups
                    elif primary_context.get('scope') == 'public':
                        actual_chat_type = 'public'
                    elif primary_context.get('scope') == 'personal':
                        actual_chat_type = 'personal_single_user'
                    debug_print(f"[ChatType] Determined chat_type from existing primary context: {actual_chat_type}")
                else:
                    # No primary context exists - default to personal_single_user
                    actual_chat_type = 'personal_single_user'
                    debug_print(f"[ChatType] No primary context found - defaulted to personal_single_user")
            else:
                # New conversation - will be determined by document usage during metadata collection
                # For now, use the legacy logic as fallback
                if document_scope == 'group' or (active_group_id and chat_type == 'group'):
                    actual_chat_type = 'group-single-user'
                elif document_scope == 'public':
                    actual_chat_type = 'public'
                else:
                    actual_chat_type = 'personal_single_user'
                debug_print(f"[ChatType] New conversation - using legacy logic: {actual_chat_type}")

            # Capture conversation-level group context for downstream agent/model resolution
            conversation_primary_context = next((ctx for ctx in conversation_item.get('context', []) if ctx.get('type') == 'primary'), None)
            conversation_group_id = None
            if conversation_primary_context and conversation_primary_context.get('scope') == 'group':
                conversation_group_id = conversation_primary_context.get('id')
            if conversation_group_id:
                g.conversation_group_id = conversation_group_id
        # region 2 - Append User Message
            # ---------------------------------------------------------------------
            # 2) Append the user message to conversation immediately (or use existing for retry)
            # ---------------------------------------------------------------------

            if is_retry:
                # For retry, use the provided user message ID and thread info
                user_message_id = retry_user_message_id
                current_user_thread_id = retry_thread_id
                latest_thread_id = current_user_thread_id

                # Read the existing user message to get metadata
                try:
                    user_message_doc = cosmos_messages_container.read_item(
                        item=user_message_id,
                        partition_key=conversation_id
                    )
                    previous_thread_id = user_message_doc.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
                    # Extract user_metadata from existing message for later use
                    user_metadata = user_message_doc.get('metadata', {})

                    debug_print(f"🔍 Chat API - Read retry user message:")
                    debug_print(f"    thread_id: {user_message_doc.get('metadata', {}).get('thread_info', {}).get('thread_id')}")
                    debug_print(f"    previous_thread_id: {previous_thread_id}")
                    debug_print(f"    attempt: {user_message_doc.get('metadata', {}).get('thread_info', {}).get('thread_attempt')}")
                    debug_print(f"    active: {user_message_doc.get('metadata', {}).get('thread_info', {}).get('active_thread')}")
                except Exception as e:
                    debug_print(f"Error reading retry user message: {e}")
                    return jsonify({'error': 'Retry user message not found'}), 404
            else:
                # Normal flow: create new user message
                user_message_id = f"{conversation_id}_user_{int(time.time())}_{random.randint(1000,9999)}"

                # Collect comprehensive metadata for user message
                user_metadata = {}

                # Get current user information
                current_user = get_current_user_info()
                if current_user:
                    user_metadata['user_info'] = {
                        'user_id': current_user.get('userId'),
                        'username': current_user.get('userPrincipalName'),
                        'display_name': current_user.get('displayName'),
                        'email': current_user.get('email'),
                        'timestamp': datetime.utcnow().isoformat()
                    }

                # Button states and selections
                user_metadata['button_states'] = {
                    'image_generation': image_gen_enabled,
                    'document_search': hybrid_search_enabled,
                    'web_search': bool(web_search_enabled),
                    'url_access': bool(url_access_enabled),
                    'deep_research': bool(deep_research_enabled)
                }
                user_metadata['capability_usage'] = _build_capability_usage_metadata(
                    workspace_search_enabled=hybrid_search_enabled,
                    document_action_type=DOCUMENT_ACTION_TYPE_NONE,
                    document_scope=effective_document_scope,
                    selected_document_ids=effective_selected_document_ids,
                    active_group_ids=effective_active_group_ids,
                    active_public_workspace_ids=effective_active_public_workspace_ids,
                    web_search_enabled=web_search_enabled,
                    url_access_enabled=url_access_enabled,
                    source_review_enabled=source_review_enabled,
                    deep_research_enabled=deep_research_enabled,
                )

                # Document search scope and selections
                if hybrid_search_enabled:
                    user_metadata['workspace_search'] = {
                        'search_enabled': True,
                        'document_scope': effective_document_scope,
                        'selected_document_id': effective_selected_document_id,
                        'selected_document_ids': effective_selected_document_ids,
                        'tags': tags_filter,
                        'classification': classifications_to_send
                    }
                    if assigned_knowledge_filters:
                        assigned_knowledge = assigned_knowledge_filters.get('assigned_knowledge') or {}
                        user_metadata['workspace_search']['assigned_knowledge'] = {
                            'enabled': True,
                            'document_count': len(assigned_knowledge.get('document_ids') or []),
                            'tag_count': len(assigned_knowledge.get('tags') or []),
                            'document_scope': effective_document_scope,
                            'active_group_ids': effective_active_group_ids,
                            'active_public_workspace_ids': effective_active_public_workspace_ids,
                        }
                    if auto_linked_chat_upload_document_ids:
                        user_metadata['workspace_search']['auto_linked_chat_upload_document_ids'] = auto_linked_chat_upload_document_ids
                        user_metadata['workspace_search']['auto_linked_chat_upload_document_count'] = len(auto_linked_chat_upload_document_ids)

                # Get document details if specific document selected
                if effective_selected_document_id and effective_selected_document_id != "all":
                    try:
                        doc_info = _resolve_chat_selected_document_metadata(
                            effective_selected_document_id,
                            user_id=user_id,
                            document_scope=effective_document_scope,
                            active_group_id=effective_active_group_id,
                            active_group_ids=effective_active_group_ids,
                            active_public_workspace_id=effective_active_public_workspace_id,
                            active_public_workspace_ids=effective_active_public_workspace_ids,
                        )
                        if doc_info and 'workspace_search' in user_metadata:
                            user_metadata['workspace_search']['document_name'] = doc_info.get('title') or doc_info.get('file_name')
                            user_metadata['workspace_search']['document_filename'] = doc_info.get('file_name')
                    except Exception as e:
                        debug_print(f"Error retrieving document details: {e}")

                # Add scope-specific details
                if effective_document_scope == 'group' and effective_active_group_id:
                    try:
                        debug_print(f"Workspace search - looking up group for id: {effective_active_group_id}")
                        group_doc = find_group_by_id(effective_active_group_id)
                        debug_print(f"Workspace search group lookup result: {group_doc}")

                        if group_doc:
                            # Check if group status allows chat operations
                            from functions_group import check_group_status_allows_operation
                            allowed, reason = check_group_status_allows_operation(group_doc, 'chat')
                            if not allowed:
                                return jsonify({'error': reason}), 403

                            if group_doc.get('name'):
                                group_name = group_doc.get('name')
                                if 'workspace_search' in user_metadata:
                                    user_metadata['workspace_search']['group_name'] = group_name
                                    debug_print(f"Workspace search - set group_name to: {group_name}")
                            else:
                                debug_print(f"Workspace search - no name for group: {effective_active_group_id}")
                                if 'workspace_search' in user_metadata:
                                    user_metadata['workspace_search']['group_name'] = None
                        else:
                            debug_print(f"Workspace search - no group found for id: {effective_active_group_id}")
                            if 'workspace_search' in user_metadata:
                                user_metadata['workspace_search']['group_name'] = None

                    except Exception as e:
                        debug_print(f"Error retrieving group details: {e}")
                        if 'workspace_search' in user_metadata:
                            user_metadata['workspace_search']['group_name'] = None
                        import traceback
                        traceback.print_exc()

                if effective_document_scope == 'public' and effective_active_public_workspace_id:
                    # Check if public workspace status allows chat operations
                    try:
                        from functions_public_workspaces import find_public_workspace_by_id, check_public_workspace_status_allows_operation
                        workspace_doc = find_public_workspace_by_id(effective_active_public_workspace_id)
                        if workspace_doc:
                            allowed, reason = check_public_workspace_status_allows_operation(workspace_doc, 'chat')
                            if not allowed:
                                return jsonify({'error': reason}), 403
                    except Exception as e:
                        debug_print(f"Error checking public workspace status: {e}")

                    if 'workspace_search' in user_metadata:
                        user_metadata['workspace_search']['active_public_workspace_id'] = effective_active_public_workspace_id

                # Ensure workspace_search key always exists for consistency
                if 'workspace_search' not in user_metadata:
                    user_metadata['workspace_search'] = {
                        'search_enabled': False
                    }

                # Prompt selection (extract from message if available)
                prompt_info = data.get('prompt_info')
                if prompt_info:
                    user_metadata['prompt_selection'] = {
                        'selected_prompt_index': prompt_info.get('index'),
                        'selected_prompt_text': prompt_info.get('content'),
                        'prompt_name': prompt_info.get('name'),
                        'prompt_id': prompt_info.get('id')
                    }

                # Agent selection (from frontend if available, override settings-based selection)
                agent_selection_metadata = _build_agent_selection_metadata(
                    request_agent_info,
                    assigned_knowledge_filters,
                )
                if agent_selection_metadata:
                    user_metadata['agent_selection'] = agent_selection_metadata

                # Model selection information
                user_metadata['model_selection'] = {
                    'selected_model': gpt_model,
                    'frontend_requested_model': frontend_gpt_model,
                    'reasoning_effort': reasoning_effort if reasoning_effort and reasoning_effort != 'none' else None,
                    'streaming': 'Disabled'
                }

                # Chat type and group context for this specific message
                user_metadata['chat_context'] = {
                    'conversation_id': conversation_id
                }

                # Note: Message-level chat_type will be determined after document search is completed

                # --- Threading Logic ---
                # Find the last message in the conversation to establish the chain
                previous_thread_id = None
                try:
                    # Query for the last message in this conversation
                    last_msg_query = f"""
                        SELECT TOP 1 c.metadata.thread_info.thread_id as thread_id
                        FROM c
                        WHERE c.conversation_id = '{conversation_id}'
                        ORDER BY c.timestamp DESC
                    """
                    last_msgs = list(cosmos_messages_container.query_items(
                        query=last_msg_query,
                        partition_key=conversation_id
                    ))
                    if last_msgs:
                        previous_thread_id = last_msgs[0].get('thread_id')
                except Exception as e:
                    debug_print(f"Error fetching last message for threading: {e}")

                # Generate thread_id for the user message
                # We track the 'tip' of the thread in latest_thread_id
                import uuid
                current_user_thread_id = str(uuid.uuid4())
                latest_thread_id = current_user_thread_id

                # Add thread information to user metadata
                user_metadata['thread_info'] = {
                    'thread_id': current_user_thread_id,
                    'previous_thread_id': previous_thread_id,
                    'active_thread': True,
                    'thread_attempt': 1
                }

                user_message_doc = {
                    'id': user_message_id,
                    'conversation_id': conversation_id,
                    'role': 'user',
                    'content': user_message,
                    'timestamp': datetime.utcnow().isoformat(),
                    'model_deployment_name': None,  # Model not used for user message
                    'metadata': user_metadata
                }

                # Debug: Print the complete metadata being saved
                debug_print(f"Complete user_metadata being saved: {json.dumps(user_metadata, indent=2, default=str)}")
                debug_print(f"Final chat_context for message: {user_metadata['chat_context']}")
                debug_print(f"document_search: {hybrid_search_enabled}, has_search_results: {bool(search_results)}")

                # Note: Message-level chat_type will be updated after document search

                cosmos_messages_container.upsert_item(user_message_doc)

                # Log chat activity for real-time tracking
                try:
                    log_chat_activity(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_type='user_message',
                        message_length=len(user_message) if user_message else 0,
                        has_document_search=hybrid_search_enabled,
                        has_image_generation=image_gen_enabled,
                        document_scope=document_scope,
                        chat_context=actual_chat_type,
                        workspace_type='group' if actual_chat_type == 'group' else 'public' if actual_chat_type == 'public' else 'personal',
                        group_id=active_group_id if actual_chat_type == 'group' else None,
                        public_workspace_id=active_public_workspace_id if actual_chat_type == 'public' else None,
                    )
                except Exception as e:
                    # Don't let activity logging errors interrupt chat flow
                    debug_print(f"Activity logging error: {e}")

                # Set conversation title if it's still the default
                _set_initial_conversation_title(conversation_item, user_message)

                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                cosmos_conversations_container.upsert_item(conversation_item) # Update timestamp and potentially title

            assistant_message_id, thought_tracker, assistant_thread_attempt, response_message_context = _initialize_assistant_response_tracking(
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                current_user_thread_id=current_user_thread_id,
                previous_thread_id=previous_thread_id,
                retry_thread_attempt=retry_thread_attempt,
                is_retry=is_retry,
                user_id=user_id,
            )
            user_info_for_assistant = response_message_context.get('user_info')
            user_thread_id = response_message_context.get('thread_id')
            user_previous_thread_id = response_message_context.get('previous_thread_id')

        # region 3 - Content Safety
            # ---------------------------------------------------------------------
            # 3) Check Content Safety (but DO NOT return 403).
            #    If blocked, add a "safety" role message & skip GPT.
            # ---------------------------------------------------------------------
            blocked = False
            block_reasons = []
            triggered_categories = []
            blocklist_matches = []

            if settings.get('enable_content_safety') and "content_safety_client" in CLIENTS:
                thought_tracker.add_thought('content_safety', 'Checking content safety...')
                try:
                    content_safety_client = CLIENTS["content_safety_client"]
                    request_obj = AnalyzeTextOptions(text=user_message)
                    cs_response = content_safety_client.analyze_text(request_obj)

                    max_severity = 0
                    for cat_result in cs_response.categories_analysis:
                        triggered_categories.append({
                            "category": cat_result.category,
                            "severity": cat_result.severity
                        })
                        if cat_result.severity > max_severity:
                            max_severity = cat_result.severity

                    if cs_response.blocklists_match:
                        for match in cs_response.blocklists_match:
                            blocklist_matches.append({
                                "blocklistName": match.blocklist_name,
                                "blocklistItemId": match.blocklist_item_id,
                                "blocklistItemText": match.blocklist_item_text
                            })

                    # Example: If severity >=4 or blocklist, we call it "blocked"
                    if max_severity >= 4:
                        blocked = True
                        block_reasons.append("Max severity >= 4")
                    if len(blocklist_matches) > 0:
                        blocked = True
                        block_reasons.append("Blocklist match")

                    if blocked:
                        # Upsert to safety container
                        safety_item = {
                            'id': str(uuid.uuid4()),
                            'user_id': user_id,
                            'conversation_id': conversation_id,
                            'message': user_message,
                            'triggered_categories': triggered_categories,
                            'blocklist_matches': blocklist_matches,
                            'timestamp': datetime.utcnow().isoformat(),
                            'reason': "; ".join(block_reasons),
                            'metadata': {
                                'message_id': assistant_message_id,
                                'thread_info': {
                                    'thread_id': response_message_context.get('thread_id'),
                                    'previous_thread_id': response_message_context.get('previous_thread_id'),
                                    'thread_attempt': assistant_thread_attempt,
                                },
                            }
                        }
                        cosmos_safety_container.upsert_item(safety_item)

                        # Instead of 403, we'll add a "safety" message
                        blocked_msg_content = (
                            "Your message was blocked by Content Safety.\n\n"
                            f"**Reason**: {', '.join(block_reasons)}\n"
                            "Triggered categories:\n"
                        )
                        for cat in triggered_categories:
                            blocked_msg_content += (
                                f" - {cat['category']} (severity={cat['severity']})\n"
                            )
                        if blocklist_matches:
                            blocked_msg_content += (
                                "\nBlocklist Matches:\n" +
                                "\n".join([f" - {m['blocklistItemText']} (in {m['blocklistName']})"
                                        for m in blocklist_matches])
                            )

                        # Insert a special "role": "safety" or "blocked"
                        safety_doc = _build_safety_message_doc(
                            conversation_id=conversation_id,
                            message_id=assistant_message_id,
                            content=blocked_msg_content.strip(),
                            response_context=response_message_context,
                            thread_attempt=assistant_thread_attempt,
                        )
                        cosmos_messages_container.upsert_item(safety_doc)

                        # Update conversation's last_updated
                        conversation_item['last_updated'] = datetime.utcnow().isoformat()
                        cosmos_conversations_container.upsert_item(conversation_item)

                        # Return a normal 200 with a special field: blocked=True
                        return jsonify({
                            'reply': blocked_msg_content.strip(),
                            'blocked': True,
                            'role': 'safety',
                            'triggered_categories': triggered_categories,
                            'blocklist_matches': blocklist_matches,
                            'conversation_id': conversation_id,
                            'conversation_title': conversation_item['title'],
                            'message_id': assistant_message_id
                        }), 200

                except HttpResponseError as e:
                    debug_print(f"[Content Safety Error] {e}")
                except Exception as ex:
                    debug_print(f"[Content Safety] Unexpected error: {ex}")

            if not original_hybrid_search_enabled:
                prior_grounded_document_refs = _normalize_prior_grounded_document_refs(conversation_item)
                if prior_grounded_document_refs:
                    thought_tracker.add_thought(
                        'history_context',
                        'Checking whether prior conversation context already answers the question',
                        detail=f"grounded_documents={len(prior_grounded_document_refs)}"
                    )
                    try:
                        preflight_messages_query = (
                            "SELECT * FROM c WHERE c.conversation_id = @conv_id ORDER BY c.timestamp ASC"
                        )
                        preflight_messages_params = [{"name": "@conv_id", "value": conversation_id}]
                        preflight_messages = list(cosmos_messages_container.query_items(
                            query=preflight_messages_query,
                            parameters=preflight_messages_params,
                            partition_key=conversation_id,
                            enable_cross_partition_query=True,
                        ))
                        preflight_history_segments = build_conversation_history_segments(
                            all_messages=preflight_messages,
                            conversation_history_limit=conversation_history_limit,
                            enable_summarize_older_messages=enable_summarize_content_history_beyond_conversation_history_limit,
                            gpt_client=gpt_client,
                            gpt_model=gpt_model,
                            user_message_id=user_message_id,
                            fallback_user_message=user_message,
                        )
                        history_only_answerability = assess_history_only_answerability(
                            gpt_client,
                            gpt_model,
                            build_history_only_assessment_messages(
                                preflight_history_segments,
                                settings.get('default_system_prompt', '').strip(),
                            ),
                        )
                    except Exception as assessment_error:
                        debug_print(
                            f"[History Fallback] History-only sufficiency assessment failed: {assessment_error}"
                        )

                    if history_only_answerability and history_only_answerability.get('can_answer_from_history'):
                        thought_tracker.add_thought(
                            'history_context',
                            'Prior conversation context appears sufficient without new document retrieval',
                            detail=history_only_answerability.get('reason') or None,
                        )
                    else:
                        fallback_search_parameters = build_prior_grounded_document_search_parameters(
                            prior_grounded_document_refs
                        )
                        fallback_search_parameters = revalidate_prior_grounded_document_search_parameters(
                            user_id,
                            fallback_search_parameters,
                        )
                        if fallback_search_parameters.get('document_ids') and fallback_search_parameters.get('doc_scope'):
                            history_grounded_search_used = True
                            effective_document_scope = fallback_search_parameters.get('doc_scope') or 'all'
                            effective_selected_document_ids = list(
                                fallback_search_parameters.get('document_ids') or []
                            )
                            effective_selected_document_id = (
                                effective_selected_document_ids[0]
                                if len(effective_selected_document_ids) == 1
                                else None
                            )
                            effective_active_group_ids = list(
                                fallback_search_parameters.get('active_group_ids') or []
                            )
                            effective_active_group_id = fallback_search_parameters.get('active_group_id')
                            effective_active_public_workspace_ids = list(
                                fallback_search_parameters.get('active_public_workspace_ids') or []
                            )
                            effective_active_public_workspace_id = fallback_search_parameters.get(
                                'active_public_workspace_id'
                            )

                            rewritten_search_query = ''
                            if history_only_answerability:
                                rewritten_search_query = str(
                                    history_only_answerability.get('search_query') or ''
                                ).strip()
                            if rewritten_search_query:
                                search_query = rewritten_search_query

                            fallback_detail_parts = [
                                f"documents={len(effective_selected_document_ids)}",
                                f"scope={effective_document_scope or 'all'}",
                            ]
                            if history_only_answerability and history_only_answerability.get('reason'):
                                fallback_detail_parts.append(
                                    f"reason={history_only_answerability['reason']}"
                                )
                            thought_tracker.add_thought(
                                'search',
                                'Conversation context alone was insufficient; searching previously grounded documents',
                                detail=' | '.join(fallback_detail_parts),
                            )

                            user_metadata.setdefault('workspace_search', {})[
                                'history_grounded_fallback'
                            ] = {
                                'used': True,
                                'document_scope': effective_document_scope,
                                'document_count': len(effective_selected_document_ids),
                                'search_query': search_query,
                            }
                            user_message_doc['metadata'] = user_metadata
                            cosmos_messages_container.upsert_item(user_message_doc)
                else:
                    thought_tracker.add_thought(
                        'history_context',
                        'No prior grounded documents were available; using conversation history only'
                    )
        # region 4 - Augmentation
            # ---------------------------------------------------------------------
            # 4) Augmentation (Search, etc.) - Run *before* final history prep
            # ---------------------------------------------------------------------

            # Hybrid Search
            if hybrid_search_enabled or history_grounded_search_used:

                # Optional: Summarize recent history *for search* (uses its own limit)
                if hybrid_search_enabled and enable_summarize_content_history_for_search:
                    # Fetch last N messages for search context
                    limit_n_search = number_of_historical_messages_to_summarize * 2
                    query_search = f"SELECT TOP {limit_n_search} * FROM c WHERE c.conversation_id = @conv_id ORDER BY c.timestamp DESC"
                    params_search = [{"name": "@conv_id", "value": conversation_id}]


                    try:
                        last_messages_desc = list(cosmos_messages_container.query_items(
                            query=query_search, parameters=params_search, partition_key=conversation_id, enable_cross_partition_query=True
                        ))
                        last_messages_asc = list(reversed(last_messages_desc))

                        if last_messages_asc and len(last_messages_asc) >= conversation_history_limit:
                            summary_prompt_search = "Please summarize the key topics or questions from this recent conversation history in 50 words or less:\n\n"

                            # Filter out inactive thread messages before summarizing
                            message_texts_search = []
                            for msg in last_messages_asc:
                                role = msg.get('role', 'user')
                                thread_info = msg.get('metadata', {}).get('thread_info', {})
                                active_thread = thread_info.get('active_thread')

                                # Exclude messages with active_thread=False
                                if active_thread is False:
                                    debug_print(f"[THREAD] Skipping inactive thread message {msg.get('id')} from search summary")
                                    continue

                                if role not in ('user', 'assistant'):
                                    continue

                                content = msg.get('content', '')
                                if role == 'assistant':
                                    content = build_assistant_history_content_with_citations(msg, content)

                                message_texts_search.append(f"{role.upper()}: {content}")

                            if not message_texts_search:
                                # No active messages to summarize
                                debug_print("[THREAD] No active thread messages available for search summary")
                            else:
                                summary_prompt_search += "\n".join(message_texts_search)

                                try:
                                    # Use the already initialized gpt_client and gpt_model
                                    summary_response_search = gpt_client.chat.completions.create(
                                        model=gpt_model,
                                        messages=[
                                            {"role": "system", "content": "Summarize recent conversation context for search query rewriting."},
                                            {"role": "user", "content": summary_prompt_search},
                                        ],
                                        max_tokens=100 # Keep summary short
                                    )
                                    summary_for_search = summary_response_search.choices[0].message.content.strip()
                                    if summary_for_search:
                                        search_query = f"Based on the recent conversation about: '{summary_for_search}', the user is now asking: {user_message}"
                                except Exception as e:
                                    debug_print(f"Error summarizing conversation for search: {e}")
                                    # Proceed with original user_message as search_query
                    except Exception as e:
                        debug_print(f"Error fetching messages for search summarization: {e}")


                # Perform the search
                if history_grounded_search_used and not hybrid_search_enabled:
                    thought_tracker.add_thought(
                        'search',
                        f"Searching {len(effective_selected_document_ids)} previously grounded document(s) for '{(search_query or user_message)[:50]}'"
                    )
                else:
                    thought_tracker.add_thought(
                        'search',
                        f"Searching {effective_document_scope or 'personal'} workspace documents for '{(search_query or user_message)[:50]}'"
                    )
                try:
                    # Prepare search arguments
                    default_top_n = SEARCH_DEFAULT_TOP_N
                    top_n = normalize_search_top_n(
                        top_n_results,
                        default_top_n=SEARCH_DEFAULT_TOP_N,
                        max_top_n=SEARCH_MAX_TOP_N,
                    )

                    search_args = {
                        "query": search_query,
                        "user_id": user_id,
                        "top_n": top_n,
                        "doc_scope": effective_document_scope,
                    }

                    # Add active_group_ids when:
                    # 1. Document scope is 'group' or chat_type is 'group', OR
                    # 2. Document scope is 'all' and groups are enabled (so group search can be included)
                    if effective_active_group_ids and (
                        effective_document_scope == 'group'
                        or effective_document_scope == 'all'
                        or chat_type == 'group'
                    ):
                        search_args["active_group_ids"] = effective_active_group_ids

                    # Add active_public_workspace_id(s) when:
                    # 1. Document scope is 'public' or
                    # 2. Document scope is 'all' and public workspaces are enabled
                    if effective_active_public_workspace_ids and (
                        effective_document_scope == 'public' or effective_document_scope == 'all'
                    ):
                        search_args["active_public_workspace_id"] = effective_active_public_workspace_ids
                    elif effective_active_public_workspace_id and (
                        effective_document_scope == 'public' or effective_document_scope == 'all'
                    ):
                        search_args["active_public_workspace_id"] = effective_active_public_workspace_id

                    if effective_selected_document_ids:
                        search_args["document_ids"] = effective_selected_document_ids
                    elif effective_selected_document_id:
                        search_args["document_id"] = effective_selected_document_id
                    if auto_linked_chat_upload_document_ids:
                        search_args["enable_file_sharing"] = False

                    # Add tags filter if provided
                    if tags_filter and isinstance(tags_filter, list) and len(tags_filter) > 0:
                        search_args["tags_filter"] = tags_filter

                    # Log if a non-default top_n value is being used
                    if top_n != default_top_n:
                        debug_print(f"Using custom top_n value: {top_n} (requested: {top_n_results})")

                    if assigned_knowledge_filters and assigned_knowledge_filters.get('has_workspace_knowledge'):
                        assigned_search_args = _build_assigned_knowledge_search_args(
                            assigned_knowledge_filters,
                            query=search_query,
                            user_id=user_id,
                            top_n=ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N,
                        )
                        assigned_search_results = hybrid_search(**assigned_search_args)
                        if assigned_knowledge_user_context_active:
                            user_context_search_results = hybrid_search(**search_args)
                            search_results = _merge_assigned_knowledge_user_context_search_results(
                                assigned_search_results,
                                user_context_search_results,
                                top_n=ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N,
                                user_id=user_id,
                            )
                        else:
                            search_results = assigned_search_results
                    else:
                        # Public scope now automatically searches all visible public workspaces
                        search_results = hybrid_search(**search_args) # Assuming hybrid_search handles None document_id
                except SemanticSearchQuotaExceededError as e:
                    debug_print(f"Semantic search quota exceeded during hybrid search: {e}")
                    return jsonify({
                        'error': e.user_message,
                        'warning_type': SEMANTIC_SEARCH_QUOTA_WARNING_TYPE,
                        'service_health_warning': True,
                    }), 503
                except Exception as e:
                    debug_print(f"Error during hybrid search: {e}")
                    # Only treat as error if the exception is from embedding failure
                    return jsonify({
                        'error': 'There was an issue with the embedding process. Please check with an admin on embedding configuration.'
                    }), 500

                combined_documents = []
                if search_results:
                    unique_doc_names = set(doc.get('file_name', 'Unknown') for doc in search_results)
                    thought_tracker.add_thought('search', f"Found {len(search_results)} results from {len(unique_doc_names)} documents")
                    retrieved_texts = []
                    classifications_found = set(conversation_item.get('classification', [])) # Load existing

                    for doc in search_results:
                        # ... (your existing doc processing logic) ...
                        chunk_text = doc.get('chunk_text', '')
                        file_name = doc.get('file_name', 'Unknown')
                        version = doc.get('version', 'N/A') # Add default
                        chunk_sequence = doc.get('chunk_sequence', 0) # Add default
                        page_number = doc.get('page_number') or chunk_sequence or 1 # Ensure a fallback page
                        citation_id = doc.get('id', str(uuid.uuid4())) # Ensure ID exists
                        document_id = str(doc.get('document_id') or '').strip()
                        if not document_id:
                            document_id = (
                                '_'.join(str(citation_id).split('_')[:-1])
                                if '_' in str(citation_id)
                                else str(citation_id)
                            )
                        classification = doc.get('document_classification')
                        chunk_id = doc.get('chunk_id', str(uuid.uuid4())) # Ensure ID exists
                        score = doc.get('score', 0.0) # Add default score
                        group_id = doc.get('group_id', None) # Add default group ID
                        doc_public_workspace_id = doc.get('public_workspace_id', None)
                        sheet_name = doc.get('sheet_name')
                        location_label, location_value = get_citation_location(
                            file_name,
                            page_number=page_number,
                            chunk_text=chunk_text,
                            sheet_name=sheet_name,
                        )

                        citation = f"(Source: {file_name}, {location_label}: {location_value}) [#{citation_id}]"
                        retrieved_texts.append(f"{chunk_text}\n{citation}")
                        combined_documents.append({
                            "file_name": file_name,
                            "document_id": document_id,
                            "citation_id": citation_id,
                            "page_number": page_number,
                            "sheet_name": sheet_name,
                            "location_label": location_label,
                            "location_value": location_value,
                            "version": version,
                            "classification": classification,
                            "chunk_text": chunk_text,
                            "chunk_sequence": chunk_sequence,
                            "chunk_id": chunk_id,
                            "score": score,
                            "group_id": group_id,
                            "public_workspace_id": doc_public_workspace_id,
                        })
                        if classification:
                            classifications_found.add(classification)

                    retrieved_content = "\n\n".join(retrieved_texts)
                    # Construct system prompt for search results
                    system_prompt_search = build_search_augmentation_system_prompt(retrieved_content)
                    # Add this to a temporary list, don't save to DB yet
                    system_messages_for_augmentation.append({
                        'role': 'system',
                        'content': system_prompt_search,
                        'documents': combined_documents # Keep track of docs used
                    })

                    # Loop through each source document/chunk used for this message
                    for source_doc in combined_documents:
                        # 4. Create a citation dictionary, selecting the desired fields
                        #    It's generally best practice *not* to include the full chunk_text
                        #    in the citation itself, as it can be large. The citation points *to* the chunk.
                        citation_data = {
                            "file_name": source_doc.get("file_name"),
                            "document_id": source_doc.get("document_id"),
                            "citation_id": source_doc.get("citation_id"), # Seems like a useful identifier
                            "page_number": source_doc.get("page_number"),
                            "chunk_id": source_doc.get("chunk_id"), # Specific chunk identifier
                            "chunk_sequence": source_doc.get("chunk_sequence"), # Order within document/group
                            "score": source_doc.get("score"), # Relevance score from search
                            "group_id": source_doc.get("group_id"), # Grouping info if used
                            "public_workspace_id": source_doc.get("public_workspace_id"),
                            "version": source_doc.get("version"), # Document version
                            "classification": source_doc.get("classification") # Document classification
                            # Add any other relevant metadata fields from source_doc here
                        }
                        # Using .get() provides None if a key is missing, preventing KeyErrors
                        hybrid_citations_list.append(citation_data)

                    hybrid_citations_list.sort(key=_build_hybrid_citation_sort_key, reverse=True)

                    # --- NEW: Extract metadata (keywords/abstract) for additional citations ---
                    # Only if extract_metadata is enabled
                    if settings.get('enable_extract_meta_data', False):
                        from functions_documents import get_document_metadata_for_citations

                        # Track which documents we've already processed to avoid duplicates
                        processed_doc_ids = set()

                        for doc in search_results:
                            # Get document ID (from the chunk's document reference)
                            # AI Search chunks contain references to their parent document
                            doc_id = str(doc.get('document_id') or '').strip()
                            if not doc_id and doc.get('id'):
                                raw_doc_id = str(doc.get('id') or '').strip()
                                doc_id = '_'.join(raw_doc_id.split('_')[:-1]) if '_' in raw_doc_id else raw_doc_id

                            # Skip if we've already processed this document
                            if not doc_id or doc_id in processed_doc_ids:
                                continue

                            processed_doc_ids.add(doc_id)
                            # Determine workspace type from the search result fields
                            doc_user_id = doc.get('user_id')
                            doc_group_id = doc.get('group_id')
                            doc_public_workspace_id = doc.get('public_workspace_id')


                            # Query Cosmos for this document's metadata
                            metadata = get_document_metadata_for_citations(
                                document_id=doc_id,
                                user_id=doc_user_id if doc_user_id else None,
                                group_id=doc_group_id if doc_group_id else None,
                                public_workspace_id=doc_public_workspace_id if doc_public_workspace_id else None
                            )


                            # If we have metadata with content, create additional citations
                            if metadata:
                                file_name = metadata.get('file_name', 'Unknown')
                                keywords = metadata.get('keywords', [])
                                abstract = metadata.get('abstract', '')


                                # Create citation for keywords if they exist
                                if keywords and len(keywords) > 0:
                                    keywords_text = ', '.join(keywords) if isinstance(keywords, list) else str(keywords)
                                    keywords_citation_id = f"{doc_id}_keywords"


                                    keywords_citation = {
                                        "file_name": file_name,
                                        "document_id": doc_id,
                                        "citation_id": keywords_citation_id,
                                        "page_number": "Metadata",  # Special page identifier
                                        "chunk_id": keywords_citation_id,
                                        "chunk_sequence": 9999,  # High number to sort to end
                                        "score": 0.0,  # No relevance score for metadata
                                        "group_id": doc_group_id,
                                        "version": doc.get('version', 'N/A'),
                                        "classification": doc.get('document_classification'),
                                        "metadata_type": "keywords",  # Flag this as metadata citation
                                        "metadata_content": keywords_text
                                    }
                                    hybrid_citations_list.append(keywords_citation)
                                    combined_documents.append(keywords_citation)  # Add to combined_documents too

                                    # Add keywords to retrieved content for the model
                                    keywords_context = f"Document Keywords ({file_name}): {keywords_text}"
                                    retrieved_texts.append(keywords_context)

                                # Create citation for abstract if it exists
                                if abstract and len(abstract.strip()) > 0:
                                    abstract_citation_id = f"{doc_id}_abstract"


                                    # Add keywords to retrieved content for the model
                                    keywords_context = f"Document Keywords ({file_name}): {keywords_text}"
                                    retrieved_texts.append(keywords_context)

                                # Create citation for abstract if it exists
                                if abstract and len(abstract.strip()) > 0:
                                    abstract_citation_id = f"{doc_id}_abstract"

                                    abstract_citation = {
                                        "file_name": file_name,
                                        "document_id": doc_id,
                                        "citation_id": abstract_citation_id,
                                        "page_number": "Metadata",  # Special page identifier
                                        "chunk_id": abstract_citation_id,
                                        "chunk_sequence": 9998,  # High number to sort to end
                                        "score": 0.0,  # No relevance score for metadata
                                        "group_id": doc_group_id,
                                        "version": doc.get('version', 'N/A'),
                                        "classification": doc.get('document_classification'),
                                        "metadata_type": "abstract",  # Flag this as metadata citation
                                        "metadata_content": abstract
                                    }
                                    hybrid_citations_list.append(abstract_citation)
                                    combined_documents.append(abstract_citation)  # Add to combined_documents too

                                    # Add abstract to retrieved content for the model
                                    abstract_context = f"Document Abstract ({file_name}): {abstract}"
                                    retrieved_texts.append(abstract_context)


                                    # Add abstract to retrieved content for the model
                                    abstract_context = f"Document Abstract ({file_name}): {abstract}"
                                    retrieved_texts.append(abstract_context)

                                # Create citation for vision analysis if it exists
                                vision_analysis = metadata.get('vision_analysis')
                                if vision_analysis:
                                    vision_citation_id = f"{doc_id}_vision"

                                    # Format vision analysis for citation display
                                    vision_description = vision_analysis.get('description', '')
                                    vision_objects = vision_analysis.get('objects', [])
                                    vision_text = vision_analysis.get('text', '')

                                    vision_content = f"AI Vision Analysis:\n"
                                    if vision_description:
                                        vision_content += f"Description: {vision_description}\n"
                                    if vision_objects:
                                        vision_content += f"Objects: {', '.join(vision_objects)}\n"
                                    if vision_text:
                                        vision_content += f"Text in Image: {vision_text}\n"

                                    vision_citation = {
                                        "file_name": file_name,
                                        "document_id": doc_id,
                                        "citation_id": vision_citation_id,
                                        "page_number": "AI Vision",  # Special page identifier
                                        "chunk_id": vision_citation_id,
                                        "chunk_sequence": 9997,  # High number to sort to end (before keywords/abstract)
                                        "score": 0.0,  # No relevance score for vision analysis
                                        "group_id": doc_group_id,
                                        "version": doc.get('version', 'N/A'),
                                        "classification": doc.get('document_classification'),
                                        "metadata_type": "vision",  # Flag this as vision citation
                                        "metadata_content": vision_content
                                    }
                                    hybrid_citations_list.append(vision_citation)
                                    combined_documents.append(vision_citation)  # Add to combined_documents too

                                    # Add vision analysis to retrieved content for the model
                                    vision_context = f"AI Vision Analysis ({file_name}): {vision_content}"
                                    retrieved_texts.append(vision_context)


                        # Update the system prompt with the enhanced content including metadata
                        if retrieved_texts:
                            retrieved_content = "\n\n".join(retrieved_texts)
                            system_prompt_search = build_search_augmentation_system_prompt(retrieved_content)
                            # Update the system message with enhanced content and updated documents array
                            if system_messages_for_augmentation:
                                system_messages_for_augmentation[0]['content'] = system_prompt_search
                                system_messages_for_augmentation[0]['documents'] = combined_documents
                    # --- END NEW METADATA CITATIONS ---

                    # Update conversation classifications if new ones were found
                    if list(classifications_found) != conversation_item.get('classification', []):
                        conversation_item['classification'] = list(classifications_found)
                        # No need to upsert item here, will be updated later
                elif history_grounded_search_used:
                    thought_tracker.add_thought(
                        'search',
                        'No matching excerpts were found in the previously grounded documents'
                    )

            if (
                assigned_knowledge_filters
                and assigned_knowledge_filters.get('has_workspace_knowledge')
                and _is_assigned_knowledge_inventory_request(user_message)
            ):
                inventory_message = _build_assigned_knowledge_inventory_aug_message(
                    user_id,
                    assigned_knowledge_filters,
                    user_message,
                )
                system_messages_for_augmentation.append(inventory_message)
                inventory_meta = inventory_message.get('assigned_knowledge_inventory') or {}
                thought_tracker.add_thought(
                    'search',
                    f"Prepared assigned knowledge inventory with {inventory_meta.get('active_document_count', 0)} active documents",
                    detail=f"web_sources={inventory_meta.get('web_source_count', 0)}",
                )

            # Update message-level chat_type based on actual document usage for this message
            # This must happen after document search is completed so search_results is populated
            message_chat_type = None
            if (hybrid_search_enabled or history_grounded_search_used) and search_results and len(search_results) > 0:
                # Documents were actually used for this message
                if effective_document_scope == 'group':
                    message_chat_type = 'group'
                elif effective_document_scope == 'public':
                    message_chat_type = 'public'
                else:
                    message_chat_type = 'personal_single_user'
            else:
                # No documents used for this message - only model knowledge
                message_chat_type = 'Model'

            # Update the message-level chat_type in user_metadata
            user_metadata['chat_context']['chat_type'] = message_chat_type
            debug_print(f"Set message-level chat_type to: {message_chat_type}")
            debug_print(
                f"hybrid_search_enabled: {hybrid_search_enabled}, history_grounded_search_used: {history_grounded_search_used}, "
                f"search_results count: {len(search_results) if search_results else 0}"
            )

            # Add context-specific information based on message chat type
            if message_chat_type == 'group' and effective_active_group_id:
                user_metadata['chat_context']['group_id'] = effective_active_group_id
                # We may have already fetched this in workspace_search section
                if 'workspace_search' in user_metadata and user_metadata['workspace_search'].get('group_name'):
                    user_metadata['chat_context']['group_name'] = user_metadata['workspace_search']['group_name']
                    debug_print(f"Chat context - using group_name from workspace_search: {user_metadata['workspace_search']['group_name']}")
                else:
                    try:
                        debug_print(f"Chat context - looking up group for id: {effective_active_group_id}")
                        group_doc = find_group_by_id(effective_active_group_id)
                        debug_print(f"Chat context group lookup result: {group_doc}")

                        if group_doc and group_doc.get('name'):
                            group_title = group_doc.get('name')
                            user_metadata['chat_context']['group_name'] = group_title
                            debug_print(f"Chat context - set group_name to: {group_title}")
                        else:
                            debug_print(f"Chat context - no group found or no name for id: {effective_active_group_id}")
                            user_metadata['chat_context']['group_name'] = None

                    except Exception as e:
                        debug_print(f"Error retrieving group name for chat context: {e}")
                        user_metadata['chat_context']['group_name'] = None
                        import traceback
                        traceback.print_exc()
            elif message_chat_type == 'public':
                # For public chat, add workspace information if available from document selection
                if 'workspace_search' in user_metadata and user_metadata['workspace_search'].get('document_name'):
                    # Use the document name as workspace context for public documents
                    user_metadata['chat_context']['workspace_context'] = f"Public Document: {user_metadata['workspace_search']['document_name']}"
                else:
                    user_metadata['chat_context']['workspace_context'] = "Public Workspace"
                debug_print(f"Set public workspace_context: {user_metadata['chat_context'].get('workspace_context')}")
            # For personal chat type or Model, no additional context needed beyond conversation_id

            source_review_used = _source_review_metadata_used(source_review_result)
            user_metadata['capability_usage'] = _build_capability_usage_metadata(
                workspace_search_enabled=hybrid_search_enabled or history_grounded_search_used,
                workspace_search_used=bool(search_results),
                workspace_search_result_count=len(search_results or []),
                document_action_type=DOCUMENT_ACTION_TYPE_NONE,
                document_scope=effective_document_scope,
                selected_document_ids=effective_selected_document_ids,
                active_group_ids=effective_active_group_ids,
                active_public_workspace_ids=effective_active_public_workspace_ids,
                web_search_enabled=web_search_enabled,
                web_search_used=bool(web_search_citations_list or deep_research_web_search_runs),
                web_search_citation_count=len(web_search_citations_list or []),
                web_search_run_count=len(deep_research_web_search_runs or []),
                url_access_enabled=url_access_enabled,
                source_review_enabled=source_review_enabled,
                source_review_used=source_review_used,
                deep_research_enabled=deep_research_enabled,
                deep_research_used=bool(deep_research_enabled and (deep_research_result or deep_research_web_search_runs or source_review_used)),
                deep_research_query_count=_deep_research_query_count(deep_research_query_plan, deep_research_web_search_runs),
            )

            # Update the user message document with the final metadata
            user_message_doc['metadata'] = user_metadata
            debug_print(f"Updated message metadata with chat_type: {message_chat_type}")

            # Update the user message in Cosmos DB with the final chat_type information
            cosmos_messages_container.upsert_item(user_message_doc)
            debug_print(f"User message re-saved to Cosmos DB with updated chat_context")

            # Image Generation
            if image_gen_enabled:
                if enable_image_gen_apim:
                    image_gen_model = settings.get('azure_apim_image_gen_deployment')
                    image_gen_client = AzureOpenAI(
                        api_version=settings.get('azure_apim_image_gen_api_version'),
                        azure_endpoint=settings.get('azure_apim_image_gen_endpoint'),
                        api_key=settings.get('azure_apim_image_gen_subscription_key')
                    )
                else:
                    if (settings.get('azure_openai_image_gen_authentication_type') == 'managed_identity'):
                        token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
                        image_gen_client = AzureOpenAI(
                            api_version=settings.get('azure_openai_image_gen_api_version'),
                            azure_endpoint=settings.get('azure_openai_image_gen_endpoint'),
                            azure_ad_token_provider=token_provider
                        )
                        image_gen_model_obj = settings.get('image_gen_model', {})

                        if image_gen_model_obj and image_gen_model_obj.get('selected'):
                            selected_image_gen_model = image_gen_model_obj['selected'][0]
                            image_gen_model = selected_image_gen_model['deploymentName']
                    else:
                        image_gen_client = AzureOpenAI(
                            api_version=settings.get('azure_openai_image_gen_api_version'),
                            azure_endpoint=settings.get('azure_openai_image_gen_endpoint'),
                            api_key=settings.get('azure_openai_image_gen_key')
                        )
                        image_gen_obj = settings.get('image_gen_model', {})
                        if image_gen_obj and image_gen_obj.get('selected'):
                            selected_image_gen_model = image_gen_obj['selected'][0]
                            image_gen_model = selected_image_gen_model['deploymentName']

                try:
                    debug_print(f"Generating image with model: {image_gen_model}")
                    debug_print(f"Using prompt: {user_message}")

                    # Azure OpenAI doesn't support response_format parameter
                    # Different models return different formats automatically
                    image_response = image_gen_client.images.generate(
                        prompt=user_message,
                        n=1,
                        model=image_gen_model
                    )

                    debug_print(f"Image response received: {type(image_response)}")
                    response_dict = json.loads(image_response.model_dump_json())
                    debug_print(f"Response dict: {response_dict}")

                    # Extract image URL or base64 data with validation
                    if 'data' not in response_dict or not response_dict['data']:
                        raise ValueError("No image data in response")

                    image_data = response_dict['data'][0]
                    debug_print(f"Image data keys: {list(image_data.keys())}")

                    generated_image_url = None

                    # Handle different response formats
                    if 'url' in image_data and image_data['url']:
                        # dall-e-3 format: returns URL
                        generated_image_url = image_data['url']
                        debug_print(f"Using URL format: {generated_image_url}")
                    elif 'b64_json' in image_data and image_data['b64_json']:
                        # gpt-image-1 format: returns base64 data
                        b64_data = image_data['b64_json']
                        # Create data URL for frontend
                        generated_image_url = f"data:image/png;base64,{b64_data}"

                        # Redacted logging for large base64 content
                        if len(b64_data) > 100:
                            redacted_content = f"{b64_data[:50]}...{b64_data[-50:]}"
                            debug_print(f"Using base64 format, length: {len(b64_data)}")
                            debug_print(f"Base64 content (redacted): {redacted_content}")
                        else:
                            debug_print(f"Using base64 format, full content: {b64_data}")
                    else:
                        available_keys = list(image_data.keys())
                        raise ValueError(f"No URL or base64 data in image data. Available keys: {available_keys}")

                    # Validate we have a valid image source
                    if not generated_image_url or generated_image_url == 'null':
                        raise ValueError("Generated image URL is null or empty")

                    image_message_id = f"{conversation_id}_image_{int(time.time())}_{random.randint(1000,9999)}"

                    user_info_for_image, user_thread_id, user_previous_thread_id = _get_user_message_image_context(
                        conversation_id,
                        user_message_id,
                    )
                    image_timestamp = datetime.utcnow().isoformat()

                    image_doc = {
                        'id': image_message_id,
                        'conversation_id': conversation_id,
                        'role': 'image',
                        'content': generated_image_url,
                        'prompt': user_message,
                        'created_at': image_timestamp,
                        'timestamp': image_timestamp,
                        'model_deployment_name': image_gen_model,
                        'metadata': {
                            'user_info': user_info_for_image,
                            'thread_info': {
                                'thread_id': user_thread_id,
                                'previous_thread_id': user_previous_thread_id,
                                'active_thread': True,
                                'thread_attempt': 1
                            }
                        }
                    }

                    if settings.get('enable_enhanced_citations', False):
                        image_mime_type, image_bytes = _resolve_generated_image_bytes(generated_image_url)
                        blob_image_info = upload_chat_image_bytes_for_user(
                            user_id=user_id,
                            conversation_id=conversation_id,
                            message_id=image_message_id,
                            file_name=f"{image_message_id}.png",
                            image_bytes=image_bytes,
                            content_type=image_mime_type,
                            image_source='generated',
                        )
                        image_doc.update({
                            'content': blob_image_info['content'],
                            'filename': blob_image_info['filename'],
                            'file_content_source': blob_image_info['file_content_source'],
                            'blob_container': blob_image_info['blob_container'],
                            'blob_path': blob_image_info['blob_path'],
                            'mime_type': blob_image_info['mime_type'],
                        })
                        image_doc['metadata']['is_chunked'] = False
                        image_doc['metadata']['is_blob_backed'] = True
                        image_doc['metadata']['original_size'] = blob_image_info['image_size']
                        cosmos_messages_container.upsert_item(image_doc)
                        response_image_url = blob_image_info['content']
                    else:
                        image_documents = build_image_message_documents(image_doc)
                        for image_document in image_documents:
                            cosmos_messages_container.upsert_item(image_document)

                        response_image_url = generated_image_url

                    conversation_item['last_updated'] = datetime.utcnow().isoformat()
                    cosmos_conversations_container.upsert_item(conversation_item)

                    return jsonify({
                        'reply': "Image loading...",
                        'image_url': response_image_url,
                        'conversation_id': conversation_id,
                        'conversation_title': conversation_item['title'],
                        'model_deployment_name': image_gen_model,
                        'message_id': image_message_id,
                        'user_message_id': user_message_id
                    }), 200
                except Exception as e:
                    debug_print(f"Image generation error: {str(e)}")
                    debug_print(f"Error type: {type(e)}")
                    import traceback
                    debug_print(f"Traceback: {traceback.format_exc()}")

                    # Handle different types of errors appropriately
                    error_message = str(e)
                    status_code = 500

                    # Check if this is a content moderation error
                    if "safety system" in error_message.lower() or "moderation_blocked" in error_message:
                        user_friendly_message = "Image generation was blocked by content safety policies. Please try a different prompt that doesn't involve potentially harmful content."
                        status_code = 400  # Bad request rather than server error
                    elif "400" in error_message and "BadRequestError" in str(type(e)):
                        user_friendly_message = f"Image generation request was invalid: {error_message}"
                        status_code = 400
                    else:
                        user_friendly_message = f"Image generation failed due to a technical error: {error_message}"

                    return jsonify({
                        'error': user_friendly_message
                    }), status_code

            workspace_tabular_file_contexts = []
            workspace_tabular_files = set()
            if (hybrid_search_enabled or history_grounded_search_used) and is_tabular_processing_enabled(settings):
                workspace_tabular_file_contexts = collect_workspace_tabular_file_contexts(
                    combined_documents=combined_documents,
                    selected_document_ids=effective_selected_document_ids,
                    selected_document_id=effective_selected_document_id,
                    document_scope=effective_document_scope,
                    user_id=user_id,
                    active_group_id=effective_active_group_id,
                    active_group_ids=effective_active_group_ids,
                    active_public_workspace_id=effective_active_public_workspace_id,
                    active_public_workspace_ids=effective_active_public_workspace_ids,
                )
                workspace_tabular_files = {
                    file_context['file_name'] for file_context in workspace_tabular_file_contexts
                }

            def record_tabular_post_processing_thought(thought_payload):
                thought_tracker.add_thought(
                    thought_payload.get('step_type', 'tabular_analysis'),
                    thought_payload.get('content', ''),
                    detail=thought_payload.get('detail'),
                    activity=thought_payload.get('activity'),
                )

            if (hybrid_search_enabled or history_grounded_search_used) and workspace_tabular_files and is_tabular_processing_enabled(settings):
                tabular_source_hint = determine_tabular_source_hint(
                    effective_document_scope,
                    active_group_id=effective_active_group_id,
                    active_public_workspace_id=effective_active_public_workspace_id,
                )
                tabular_execution_mode = get_tabular_execution_mode(user_message)
                tabular_filenames_str = ", ".join(sorted(workspace_tabular_files))
                plugin_logger = get_plugin_logger()
                baseline_tabular_invocation_count = len(
                    plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
                )

                thought_tracker.add_thought(
                    'tabular_analysis',
                    f"Starting tabular analysis across {len(workspace_tabular_files)} file(s)",
                    detail=f"files={tabular_filenames_str}; mode={tabular_execution_mode}",
                )

                tabular_analysis, streamed_tabular_tool_thoughts = asyncio.run(run_tabular_analysis_with_thought_tracking(
                    user_question=user_message,
                    tabular_filenames=workspace_tabular_files,
                    tabular_file_contexts=workspace_tabular_file_contexts,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    gpt_model=gpt_model,
                    settings=settings,
                    source_hint=tabular_source_hint,
                    group_id=effective_active_group_id if tabular_source_hint == 'group' else None,
                    public_workspace_id=effective_active_public_workspace_id if tabular_source_hint == 'public' else None,
                    execution_mode=tabular_execution_mode,
                    thought_tracker=thought_tracker,
                    model_context=tabular_model_context,
                ))
                tabular_invocations = get_new_plugin_invocations(
                    plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000),
                    baseline_tabular_invocation_count
                )
                tabular_related_document_summary = ''
                tabular_related_document_stats = augment_tabular_invocations_with_related_document_evidence(
                    tabular_invocations,
                    user_message,
                    user_id,
                    conversation_id=conversation_id,
                )
                if tabular_related_document_stats.get('augmented_row_count'):
                    tabular_related_document_summary = build_tabular_related_document_evidence_summary(
                        tabular_invocations,
                    )
                if not streamed_tabular_tool_thoughts:
                    tabular_thought_payloads = get_tabular_tool_thought_payloads(tabular_invocations)
                    for thought_content, thought_detail in tabular_thought_payloads:
                        thought_tracker.add_thought('tabular_analysis', thought_content, thought_detail)
                tabular_status_thought_payloads = get_tabular_status_thought_payloads(
                    tabular_invocations,
                    analysis_succeeded=bool(tabular_analysis),
                )
                for thought_content, thought_detail in tabular_status_thought_payloads:
                    thought_tracker.add_thought('tabular_analysis', thought_content, thought_detail)

                tabular_generated_output = asyncio.run(maybe_create_tabular_generated_output(
                    user_question=user_message,
                    invocations=tabular_invocations,
                    gpt_model=gpt_model,
                    settings=settings,
                    conversation_id=conversation_id,
                    thought_callback=record_tabular_post_processing_thought,
                    user_id=user_id,
                    model_context=tabular_model_context,
                ))
                if tabular_generated_output:
                    generated_tabular_outputs_list.append(tabular_generated_output)
                    generated_analysis_artifacts_list.append(tabular_generated_output)

                if tabular_analysis:
                    tabular_system_msg = build_tabular_computed_results_system_message(
                        f"the file(s) {tabular_filenames_str}",
                        tabular_analysis,
                        related_document_evidence_summary=tabular_related_document_summary,
                    )
                else:
                    tabular_system_msg = build_tabular_fallback_system_message(
                        tabular_filenames_str,
                        execution_mode=tabular_execution_mode,
                    )

                system_messages_for_augmentation.append({
                    'role': 'system',
                    'content': tabular_system_msg
                })
                if tabular_generated_output:
                    system_messages_for_augmentation.append({
                        'role': 'system',
                        'content': _build_tabular_generated_output_system_message(tabular_generated_output)
                    })
                    _log_tabular_generated_output_handoff(
                        conversation_id,
                        user_message,
                        tabular_generated_output,
                        'workspace_search_augmentation',
                    )

                if tabular_analysis:
                    tabular_sk_citations = collect_tabular_sk_citations(user_id, conversation_id)
                    if tabular_sk_citations:
                        agent_citations_list.extend(tabular_sk_citations)
                    tabular_chart_citations = build_tabular_inline_chart_citations(user_message, tabular_invocations)
                    if tabular_chart_citations:
                        agent_citations_list.extend(tabular_chart_citations)
                        thought_tracker.add_thought(
                            'tabular_analysis',
                            f"Prepared {len(tabular_chart_citations)} inline chart{'s' if len(tabular_chart_citations) != 1 else ''} from tabular results",
                        )
                else:
                    thought_tracker.add_thought(
                        'tabular_analysis',
                        "Tabular analysis could not compute results; using schema context instead",
                        detail=f"files={tabular_filenames_str}"
                    )

            if web_search_enabled:
                search_thought_label = 'deep_research' if deep_research_enabled else 'web_search'
                search_thought_text = "Planning Deep Research web searches" if deep_research_enabled else f"Searching the web for '{web_search_query_text[:50]}'"
                thought_tracker.add_thought(search_thought_label, search_thought_text)
                research_search_result = perform_research_web_searches(
                    settings=settings,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    user_message=user_message,
                    user_message_id=user_message_id,
                    chat_type=chat_type,
                    document_scope=document_scope,
                    active_group_id=active_group_id,
                    active_public_workspace_id=active_public_workspace_id,
                    web_search_query_text=web_search_query_text,
                    system_messages_for_augmentation=system_messages_for_augmentation,
                    agent_citations_list=agent_citations_list,
                    web_search_citations_list=web_search_citations_list,
                    deep_research_enabled=deep_research_enabled,
                    deep_research_planner_client=gpt_client,
                    deep_research_planner_model=gpt_model,
                )
                deep_research_query_plan = research_search_result.get('query_plan', {})
                deep_research_web_search_runs = research_search_result.get('web_search_runs', [])
                if web_search_citations_list:
                    if deep_research_enabled:
                        planned_count = len(deep_research_query_plan.get('queries') or []) or 1
                        query_label = 'queries' if planned_count != 1 else 'query'
                        thought_tracker.add_thought(
                            'deep_research',
                            f"Ran {planned_count} Deep Research web search {query_label}",
                            detail=f"discovered_urls={len(web_search_citations_list)}"
                        )
                    else:
                        thought_tracker.add_thought('web_search', f"Got {len(web_search_citations_list)} web search results")

            if source_review_enabled:
                source_review_thought_label = 'deep_research' if deep_research_enabled else 'url_access'
                source_review_start_text = (
                    "Reviewing source pages for supporting evidence"
                    if deep_research_enabled
                    else "Reviewing pasted URLs"
                )
                thought_tracker.add_thought(source_review_thought_label, source_review_start_text)
                source_review_result = perform_source_review(
                    settings=settings,
                    user_id=user_id,
                    user_email=current_user_email,
                    user_roles=current_user_roles,
                    user_message=user_message,
                    web_search_citations=web_search_citations_list if deep_research_enabled else [],
                    conversation_id=conversation_id,
                    source_review_planner_client=gpt_client,
                    source_review_planner_model=gpt_model,
                    url_access_only=not deep_research_enabled,
                    url_access_context=URL_ACCESS_CONTEXT_CHAT,
                    include_direct_user_urls=bool(url_access_enabled),
                    additional_seed_urls=(
                        assigned_knowledge_url_review_urls
                        + assigned_knowledge_deep_research_urls
                    ),
                )
                source_review_message = source_review_result.get('system_message') if isinstance(source_review_result, dict) else None
                if source_review_message:
                    system_messages_for_augmentation.append(source_review_message)
                    existing_source_urls = {
                        citation.get('url')
                        for citation in web_search_citations_list
                        if isinstance(citation, dict) and citation.get('url')
                    }
                    for citation in source_review_result.get('citations', []):
                        citation_url = citation.get('url') if isinstance(citation, dict) else None
                        if citation_url and citation_url not in existing_source_urls:
                            web_search_citations_list.append(citation)
                            existing_source_urls.add(citation_url)
                    coverage = source_review_result.get('coverage', {})
                    planner_status = 'deterministic'
                    if coverage.get('llm_planning_used'):
                        planner_status = 'used'
                    elif coverage.get('llm_planning_attempted'):
                        planner_status = 'attempted'
                    thought_tracker.add_thought(
                        source_review_thought_label,
                        f"Reviewed {coverage.get('pages_reviewed', 0)} URL source pages",
                        detail=(
                            f"seed={coverage.get('seed_pages_reviewed', 0)}, "
                            f"child={coverage.get('child_pages_reviewed', 0)}, "
                            f"planner={planner_status}, "
                            f"load_more={coverage.get('load_more_clicks_succeeded', 0)}, "
                            f"skipped={coverage.get('pages_skipped', 0)}"
                        )
                    )
                else:
                    thought_tracker.add_thought(
                        source_review_thought_label,
                        "Deep Research did not add page evidence" if deep_research_enabled else "URL Access did not add page evidence",
                        detail=source_review_result.get('skipped_reason') if isinstance(source_review_result, dict) else None
                    )

                if deep_research_enabled:
                    deep_research_ledger = build_deep_research_ledger(
                        settings=settings,
                        user_message=user_message,
                        query_plan=deep_research_query_plan,
                        web_search_runs=deep_research_web_search_runs,
                        web_search_citations=web_search_citations_list,
                        source_review_result=source_review_result,
                    )
                    deep_research_artifact = _maybe_create_deep_research_ledger_artifact(
                        settings,
                        conversation_id,
                        deep_research_ledger,
                    )
                    if deep_research_artifact:
                        deep_research_ledger['ledger_artifact'] = deep_research_artifact
                        generated_analysis_artifacts_list.append(deep_research_artifact)
                    deep_research_result = compact_deep_research_result_for_metadata(deep_research_ledger)

        # region 5 - FINAL conversation history preparation
            # ---------------------------------------------------------------------
            # 5) Prepare FINAL conversation history for GPT (including summarization)
            # ---------------------------------------------------------------------
            conversation_history_for_api = []
            summary_of_older = ""
            history_debug_info = {}
            final_api_source_refs = []


            try:
                # Fetch ALL messages for potential summarization, sorted OLD->NEW
                all_messages_query = "SELECT * FROM c WHERE c.conversation_id = @conv_id ORDER BY c.timestamp ASC"
                params_all = [{"name": "@conv_id", "value": conversation_id}]
                all_messages = list(cosmos_messages_container.query_items(
                    query=all_messages_query, parameters=params_all, partition_key=conversation_id, enable_cross_partition_query=True
                ))
                history_segments = build_conversation_history_segments(
                    all_messages=all_messages,
                    conversation_history_limit=conversation_history_limit,
                    enable_summarize_older_messages=enable_summarize_content_history_beyond_conversation_history_limit,
                    gpt_client=gpt_client,
                    gpt_model=gpt_model,
                    user_message_id=user_message_id,
                    fallback_user_message=user_message,
                )
                summary_of_older = history_segments['summary_of_older']
                chat_tabular_files = history_segments['chat_tabular_files']
                history_debug_info = history_segments.get('debug_info', {})


                # Construct the final history for the API call
                # Start with the summary if available
                if summary_of_older:
                    conversation_history_for_api.append({
                        "role": "system",
                        "content": f"<Summary of previous conversation context>\n{summary_of_older}\n</Summary of previous conversation context>"
                    })
                    final_api_source_refs.append('system:summary_of_older')

                # Add augmentation system messages (search, agents) next
                # **Important**: Decide if you want these saved. If so, you need to upsert them now.
                # For simplicity here, we're just adding them to the API call context.
                for aug_msg in system_messages_for_augmentation:
                    # 1. Extract the source documents list for this specific system message
                    # Use .get with a default empty list [] for safety in case 'documents' is missing

                    # 5. Create the final system_doc dictionary for Cosmos DB upsert
                    system_message_id = f"{conversation_id}_system_aug_{int(time.time())}_{random.randint(1000,9999)}"

                    # Get user_info and thread_id from the user message for ownership tracking and threading
                    user_info_for_system = None
                    user_thread_id = None
                    user_previous_thread_id = None
                    try:
                        user_msg = cosmos_messages_container.read_item(
                            item=user_message_id,
                            partition_key=conversation_id
                        )
                        user_info_for_system = user_msg.get('metadata', {}).get('user_info')
                        user_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
                        user_previous_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
                    except Exception as e:
                        debug_print(f"Warning: Could not retrieve user_info from user message for system message: {e}")

                    system_doc = {
                        'id': system_message_id,
                        'conversation_id': conversation_id,
                        'role': aug_msg.get('role'),
                        'content': aug_msg.get('content'),
                        'search_query': search_query, # Include the search query used for this augmentation
                        'user_message': user_message, # Include the original user message for context
                        'model_deployment_name': None, # As per your original structure
                        'timestamp': datetime.utcnow().isoformat(),
                        'metadata': {
                            'user_info': user_info_for_system,
                            'thread_info': {
                                'thread_id': user_thread_id,  # Same thread as user message
                                'previous_thread_id': user_previous_thread_id,  # Same previous_thread_id as user message
                                'active_thread': True,
                                'thread_attempt': 1
                            }
                        }
                    }
                    cosmos_messages_container.upsert_item(system_doc)
                    conversation_history_for_api.append(aug_msg) # Add to API context
                    final_api_source_refs.append(f"system:augmentation:{len(final_api_source_refs) + 1}")
                    # System message shares the same thread as user message, no thread update needed

                    # --- NEW: Save plugin output as agent citation ---
                    agent_citations_list.append({
                        "tool_name": str(selected_agent.name) if selected_agent else "All Citations",
                        "function_arguments": json.dumps(aug_msg, default=str),
                        "function_result": aug_msg.get('content', ''),
                        "timestamp": datetime.utcnow().isoformat()
                    })

                conversation_history_for_api.extend(history_segments['history_messages'])
                final_api_source_refs.extend(history_debug_info.get('history_message_source_refs', []))

                # --- Mini SK analysis for tabular files uploaded directly to chat ---
                if chat_tabular_files and is_tabular_processing_enabled(settings):
                    chat_tabular_filenames_str = ", ".join(chat_tabular_files)
                    chat_tabular_execution_mode = get_tabular_execution_mode(user_message)
                    log_event(
                        f"[Chat Tabular SK] Detected {len(chat_tabular_files)} tabular file(s) uploaded to chat: {chat_tabular_filenames_str}",
                        level=logging.INFO
                    )
                    plugin_logger = get_plugin_logger()
                    baseline_tabular_invocation_count = len(
                        plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
                    )

                    thought_tracker.add_thought(
                        'tabular_analysis',
                        f"Starting tabular analysis across {len(chat_tabular_files)} chat-uploaded file(s)",
                        detail=f"files={chat_tabular_filenames_str}; mode={chat_tabular_execution_mode}",
                    )

                    chat_tabular_analysis, streamed_chat_tabular_tool_thoughts = asyncio.run(run_tabular_analysis_with_thought_tracking(
                        user_question=user_message,
                        tabular_filenames=chat_tabular_files,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        gpt_model=gpt_model,
                        settings=settings,
                        source_hint="chat",
                        execution_mode=chat_tabular_execution_mode,
                        thought_tracker=thought_tracker,
                        model_context=tabular_model_context,
                    ))
                    chat_tabular_invocations = get_new_plugin_invocations(
                        plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000),
                        baseline_tabular_invocation_count
                    )
                    chat_tabular_related_document_summary = ''
                    chat_tabular_related_document_stats = augment_tabular_invocations_with_related_document_evidence(
                        chat_tabular_invocations,
                        user_message,
                        user_id,
                        conversation_id=conversation_id,
                    )
                    if chat_tabular_related_document_stats.get('augmented_row_count'):
                        chat_tabular_related_document_summary = build_tabular_related_document_evidence_summary(
                            chat_tabular_invocations,
                        )
                    if not streamed_chat_tabular_tool_thoughts:
                        chat_tabular_thought_payloads = get_tabular_tool_thought_payloads(chat_tabular_invocations)
                        for thought_content, thought_detail in chat_tabular_thought_payloads:
                            thought_tracker.add_thought('tabular_analysis', thought_content, thought_detail)
                    chat_tabular_status_thought_payloads = get_tabular_status_thought_payloads(
                        chat_tabular_invocations,
                        analysis_succeeded=bool(chat_tabular_analysis),
                    )
                    for thought_content, thought_detail in chat_tabular_status_thought_payloads:
                        thought_tracker.add_thought('tabular_analysis', thought_content, thought_detail)

                    chat_tabular_generated_output = asyncio.run(maybe_create_tabular_generated_output(
                        user_question=user_message,
                        invocations=chat_tabular_invocations,
                        gpt_model=gpt_model,
                        settings=settings,
                        conversation_id=conversation_id,
                        thought_callback=record_tabular_post_processing_thought,
                        user_id=user_id,
                        model_context=tabular_model_context,
                    ))
                    if chat_tabular_generated_output:
                        generated_tabular_outputs_list.append(chat_tabular_generated_output)
                        generated_analysis_artifacts_list.append(chat_tabular_generated_output)

                    if chat_tabular_analysis:
                        # Inject pre-computed analysis results as context
                        conversation_history_for_api.append({
                            'role': 'system',
                            'content': build_tabular_computed_results_system_message(
                                f"the chat-uploaded file(s) {chat_tabular_filenames_str}",
                                chat_tabular_analysis,
                                related_document_evidence_summary=chat_tabular_related_document_summary,
                            )
                        })
                        final_api_source_refs.append('system:tabular_results')
                        if chat_tabular_generated_output:
                            conversation_history_for_api.append({
                                'role': 'system',
                                'content': _build_tabular_generated_output_system_message(chat_tabular_generated_output)
                            })
                            final_api_source_refs.append('system:tabular_generated_output')
                            _log_tabular_generated_output_handoff(
                                conversation_id,
                                user_message,
                                chat_tabular_generated_output,
                                'chat_upload_history',
                            )

                        # Collect tool execution citations from SK tabular analysis
                        chat_tabular_sk_citations = collect_tabular_sk_citations(user_id, conversation_id)
                        if chat_tabular_sk_citations:
                            agent_citations_list.extend(chat_tabular_sk_citations)
                        chat_tabular_chart_citations = build_tabular_inline_chart_citations(user_message, chat_tabular_invocations)
                        if chat_tabular_chart_citations:
                            agent_citations_list.extend(chat_tabular_chart_citations)
                            thought_tracker.add_thought(
                                'tabular_analysis',
                                f"Prepared {len(chat_tabular_chart_citations)} inline chart{'s' if len(chat_tabular_chart_citations) != 1 else ''} from chat-uploaded tabular results",
                            )

                        debug_print(f"[Chat Tabular SK] Analysis injected, {len(chat_tabular_analysis)} chars")
                    else:
                        if chat_tabular_generated_output:
                            conversation_history_for_api.append({
                                'role': 'system',
                                'content': _build_tabular_generated_output_system_message(chat_tabular_generated_output)
                            })
                            final_api_source_refs.append('system:tabular_generated_output')
                            _log_tabular_generated_output_handoff(
                                conversation_id,
                                user_message,
                                chat_tabular_generated_output,
                                'chat_upload_history_fallback',
                            )
                        thought_tracker.add_thought(
                            'tabular_analysis',
                            "Tabular analysis could not compute results; using existing chat file context",
                            detail=f"files={chat_tabular_filenames_str}"
                        )
                        debug_print("[Chat Tabular SK] Analysis returned None, relying on existing file context messages")

            except Exception as e:
                debug_print(f"Error preparing conversation history: {e}")
                return jsonify({'error': f'Error preparing conversation history: {str(e)}'}), 500

        # region 6 - Final GPT Call
            # ---------------------------------------------------------------------
            # 6) Final GPT Call
            # ---------------------------------------------------------------------
            default_system_prompt = settings.get('default_system_prompt', '').strip()
            default_system_prompt_inserted = False
            # Only add if non-empty and not already present (excluding summary/augmentation system messages)
            if default_system_prompt:
                # Find if any system message (not summary or augmentation) is present
                has_general_system_prompt = any(
                    msg.get('role') == 'system' and not (
                        msg.get('content', '').startswith('<Summary of previous conversation context>') or
                        "retrieved document excerpts" in msg.get('content', '')
                    )
                    for msg in conversation_history_for_api
                )
                if not has_general_system_prompt:
                    # Insert at the start, after any summary if present
                    insert_idx = 0
                    if conversation_history_for_api and conversation_history_for_api[0].get('role') == 'system' and conversation_history_for_api[0].get('content', '').startswith('<Summary of previous conversation context>'):
                        insert_idx = 1
                    conversation_history_for_api.insert(insert_idx, {
                        "role": "system",
                        "content": default_system_prompt
                    })
                    final_api_source_refs.insert(insert_idx, 'system:default_prompt')
                    default_system_prompt_inserted = True

            if should_apply_history_grounding_message(
                original_hybrid_search_enabled,
                prior_grounded_document_refs,
            ):
                history_grounding_message = build_history_grounding_system_message()
                insert_idx = 0
                if (
                    conversation_history_for_api
                    and conversation_history_for_api[0].get('role') == 'system'
                    and conversation_history_for_api[0].get('content', '').startswith(
                        '<Summary of previous conversation context>'
                    )
                ):
                    insert_idx = 1
                if default_system_prompt_inserted:
                    insert_idx += 1
                conversation_history_for_api.insert(insert_idx, history_grounding_message)
                final_api_source_refs.insert(insert_idx, 'system:history_grounding')

            history_debug_info = enrich_history_context_debug_info(
                history_debug_info,
                conversation_history_for_api,
                final_api_source_refs,
                path_label='standard',
                augmentation_message_count=len(system_messages_for_augmentation),
                default_system_prompt_inserted=default_system_prompt_inserted,
            )
            emit_history_context_debug(history_debug_info, conversation_id)
            thought_tracker.add_thought(
                'history_context',
                build_history_context_thought_content(history_debug_info),
                build_history_context_thought_detail(history_debug_info),
            )
            if settings.get('enable_debug_logging', False):
                agent_citations_list.append(
                    build_history_context_debug_citation(history_debug_info, 'standard')
                )

            # --- DRY Fallback Chain Helper ---
            def try_fallback_chain(steps):
                """
                steps: list of dicts with keys:
                    'name': str, 'func': callable, 'on_success': callable, 'on_error': callable
                Returns: (ai_message, final_model_used, chat_mode, kernel_fallback_notice)
                """
                for step in steps:
                    try:
                        result = step['func']()
                        return step['on_success'](result)
                    except Exception as e:
                        log_event(
                            f"[Fallback Failure] Fallback step {step['name']} failed: {e}",
                            extra={
                                "step_name": step['name'],
                                "error": str(e)
                            }
                        )
                        if 'on_error' in step and step['on_error']:
                            step['on_error'](e)
                        continue
                # If all fail, return default error
                return ("Sorry, I encountered an error.", gpt_model, None, None)

            async def run_sk_call(callable_obj, *args, **kwargs):
                log_event(
                    f"Running Semantic Kernel callable: {callable_obj.__name__}",
                    extra={
                        "callable_name": callable_obj.__name__,
                        "call_args": args,
                        "call_kwargs": kwargs
                    }
                )
                runtime = kwargs.get("runtime", None)
                started_runtime = False
                try:
                    if runtime is not None and getattr(runtime, "_run_context", None) is None:
                        runtime.start()
                        started_runtime = True
                        log_event(
                            f"Started runtime for callable: {callable_obj.__name__}",
                            extra={"runtime": runtime}
                        )
                    result = callable_obj(*args, **kwargs)
                    if asyncio.iscoroutine(result):
                        log_event(
                            f"Callable {callable_obj.__name__} returned a coroutine, awaiting.",
                            extra={"callable_name": callable_obj.__name__}
                        )
                        result = await result
                    if hasattr(result, "get") and asyncio.iscoroutinefunction(result.get):
                        try:
                            log_event(
                                f"Callable {callable_obj.__name__} returned an orchestration result, awaiting result.get().",
                                extra={"callable_name": callable_obj.__name__}
                            )
                            return await result.get()
                        except Exception as e:
                            log_event(
                                f"Error awaiting orchestration result.get()",
                                extra={"error": str(e)},
                                level=logging.ERROR,
                                exceptionTraceback=True
                            )
                            return "Sorry, the orchestration failed."
                    elif isinstance(result, types.AsyncGeneratorType):
                        log_event(
                            f"Callable {callable_obj.__name__} returned an async generator, iterating.",
                            extra={"callable_name": callable_obj.__name__}
                        )
                        async for r in result:
                            return r
                    else:
                        return result
                except asyncio.CancelledError:
                    log_event(
                        f"Callable {callable_obj.__name__} was cancelled.",
                        extra={"callable_name": callable_obj.__name__},
                        level=logging.WARNING,
                        exceptionTraceback=True
                    )
                    raise
                finally:
                    if runtime is not None and started_runtime:
                        log_event(
                            f"Stopping runtime for callable: {callable_obj.__name__}",
                            extra={"runtime": runtime}
                        )
                        await runtime.stop_when_idle()

            ai_message = "Sorry, I encountered an error." # Default error message
            final_model_used = gpt_model # Track model used for the response
            kernel_fallback_notice = None
            chat_mode = None
            scope_id=active_group_id if chat_type == 'group' else user_id
            scope_type='group' if chat_type == 'group' else 'user'
            enable_multi_agent_orchestration = False
            fallback_steps = []
            selected_agent = None
            user_settings = get_user_settings(user_id).get('settings', {})
            per_user_semantic_kernel = settings.get('per_user_semantic_kernel', False)
            enable_semantic_kernel = settings.get('enable_semantic_kernel', False)

            # Check if agent_info is provided in request (e.g., from retry with agent selection)
            force_enable_agents = _has_chat_agent_selection(request_agent_info)

            user_enable_agents = user_settings.get('enable_agents', True)  # Default to True for backward compatibility
            # Override user setting if agent explicitly requested via agent_info
            if force_enable_agents:
                user_enable_agents = True
                g.force_enable_agents = True  # Store in Flask g for SK loader to check
                if isinstance(request_agent_info, dict):
                    g.request_agent_info = request_agent_info
                    g.request_agent_name = request_agent_info.get('name')
                else:
                    g.request_agent_info = {'name': request_agent_info}
                    g.request_agent_name = request_agent_info
                log_event(f"[SKChat] agent_info provided in request - forcing agent enablement for this request", level=logging.INFO)

            enable_key_vault_secret_storage = settings.get('enable_key_vault_secret_storage', False)
            redis_client = None
            # --- Semantic Kernel state management (per-user mode) ---
            if enable_semantic_kernel and per_user_semantic_kernel:
                redis_client = current_app.config.get('SESSION_REDIS') if 'current_app' in globals() else None
                initialize_semantic_kernel(user_id=user_id, redis_client=redis_client)
            elif enable_semantic_kernel:
                # Global mode: set g.kernel/g.kernel_agents from builtins
                g.kernel = getattr(builtins, 'kernel', None)
                g.kernel_agents = getattr(builtins, 'kernel_agents', None)
            if per_user_semantic_kernel:
                settings_agents = user_settings.get('agents', [])
                logging.debug(f"[SKChat] Per-user Semantic Kernel enabled. Using user-specific settings.")
            else:
                enable_multi_agent_orchestration = settings.get('enable_multi_agent_orchestration', False)
                settings_agents = settings.get('semantic_kernel_agents', [])
            kernel = get_kernel()
            all_agents = get_kernel_agents()

            log_event(f"[SKChat] Retrieved kernel: {type(kernel)}, all_agents: {type(all_agents)} with {len(all_agents) if all_agents else 0} agents", level=logging.INFO)
            if all_agents:
                if isinstance(all_agents, dict):
                    agent_names = list(all_agents.keys())
                else:
                    agent_names = [getattr(agent, 'name', 'unnamed') for agent in all_agents]
                log_event(f"[SKChat] Agent names available: {agent_names}", level=logging.INFO)
            else:
                log_event(f"[SKChat] No agents loaded - proceeding in model-only mode", level=logging.INFO)

            log_event(f"[SKChat] Semantic Kernel enabled. Per-user mode: {per_user_semantic_kernel}, Multi-agent orchestration: {enable_multi_agent_orchestration}, agents enabled: {user_enable_agents}")

            explicit_chart_request = user_requested_chart_visualization(user_message)

            fact_memory_enabled = bool(settings.get('enable_fact_memory_plugin', False))
            fact_memory_payload = inject_fact_memory_context(
                conversation_history=conversation_history_for_api,
                scope_id=scope_id,
                scope_type=scope_type,
                query_text=user_message,
                conversation_id=conversation_id,
                agent_id=None,
                enabled=fact_memory_enabled,
                include_metadata=bool(enable_semantic_kernel and user_enable_agents),
            )
            for thought in fact_memory_payload.get('thoughts', []):
                thought_tracker.add_thought(
                    thought.get('step_type') or 'fact_memory',
                    thought.get('content'),
                    thought.get('detail'),
                )
            for citation in fact_memory_payload.get('citations', []):
                agent_citations_list.append(citation)

            if enable_semantic_kernel and user_enable_agents:
                agent_name_to_select = _get_chat_agent_selection_name(request_agent_info)
                if agent_name_to_select:
                    log_event(f"[SKChat] Using agent from request agent_info: {agent_name_to_select}")
                else:
                    log_event("[SKChat] No explicit request agent selected; proceeding in model-only mode")

                if all_agents and agent_name_to_select:
                    agent_iter = all_agents.values() if isinstance(all_agents, dict) else all_agents
                    agent_debug_info = []
                    for agent in agent_iter:
                        agent_debug_info.append({
                            "name": getattr(agent, 'name', None),
                            "default_agent": getattr(agent, 'default_agent', None),
                            "is_global": getattr(agent, 'is_global', None),
                            "repr": repr(agent)
                        })
                        if agent_name_to_select and getattr(agent, 'name', None) == agent_name_to_select:
                            selected_agent = agent
                            log_event(f"[SKChat] selected_agent found by explicit selection: {agent_name_to_select}")
                            break
                    if not selected_agent:
                        log_event(
                            f"[SKChat] Requested chat agent was not found: {agent_name_to_select}",
                            level=logging.WARNING,
                        )
                    log_event(f"[SKChat] Agent selection debug info: {agent_debug_info}")
                elif all_agents:
                    log_event("[SKChat] No chat agent selected for this request; proceeding in model-only mode")
                else:
                    log_event(f"[SKChat] all_agents is empty or None!", level=logging.WARNING)
                if selected_agent is None:
                    log_event("[SKChat] No selected chat agent found; model-only path will be used")
                log_event(f"[SKChat] selected_agent: {str(getattr(selected_agent, 'name', None))}")
                agent_id = getattr(selected_agent, 'id', None)
                extra={
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "scope_type": scope_type,
                    "message_count": len(conversation_history_for_api),
                    "agent": bool(selected_agent is not None),
                    "selected_agent_id": agent_id or None,
                    "kernel": bool(kernel is not None),
                }

                conversation_history_for_api = maybe_append_chart_tool_system_message(
                    conversation_history_for_api,
                    user_message,
                    selected_agent,
                )
                conversation_history_for_api = maybe_append_image_proposal_system_message(
                    conversation_history_for_api,
                    user_message,
                    settings,
                    selected_agent,
                )

                agent_message_history = [
                    ChatMessageContent(
                        role=msg["role"],
                        content=msg["content"],
                        metadata=msg.get("metadata", {})
                    )
                    for msg in conversation_history_for_api
                ]

                # --- Fallback Chain Steps ---
                if enable_multi_agent_orchestration and all_agents and agent_name_to_select and "orchestrator" in all_agents and not per_user_semantic_kernel:
                    def invoke_orchestrator():
                        orchestrator = all_agents["orchestrator"]
                        runtime = InProcessRuntime()
                        return asyncio.run(run_sk_call(
                            orchestrator.invoke,
                            task=agent_message_history,
                            runtime=runtime,
                        ))
                    def orchestrator_success(result):
                        msg = str(result)
                        notice = None
                        return (msg, "multi-agent-chat", "multi-agent-chat", notice)
                    def orchestrator_error(e):
                        debug_print(f"Error during Semantic Kernel Agent invocation: {str(e)}")
                        log_event(
                            f"Error during Semantic Kernel Agent invocation: {str(e)}",
                            extra=extra,
                            level=logging.ERROR,
                            exceptionTraceback=True
                        )
                    fallback_steps.append({
                        'name': 'orchestrator',
                        'func': invoke_orchestrator,
                        'on_success': orchestrator_success,
                        'on_error': orchestrator_error
                    })

                if selected_agent:
                    agent_deployment_name = getattr(selected_agent, 'deployment_name', None) or gpt_model
                    thought_tracker.add_thought('agent_tool_call', f"Sending to agent '{getattr(selected_agent, 'display_name', getattr(selected_agent, 'name', 'unknown'))}'")
                    thought_tracker.add_thought('generation', f"Sending to '{agent_deployment_name}'")

                    # Register callback to write plugin thoughts to Cosmos in real-time
                    plugin_logger = get_plugin_logger()
                    callback_key = register_plugin_invocation_thought_callback(
                        plugin_logger,
                        thought_tracker,
                        user_id,
                        conversation_id,
                        actor_label='Agent'
                    )

                    agent_invoke_start_time = time.time()

                    def invoke_selected_agent():
                        return asyncio.run(run_sk_call(
                            selected_agent.invoke,
                            agent_message_history,
                        ))
                    def agent_success(result):
                        nonlocal reload_messages_required
                        msg = str(result)
                        notice = None
                        agent_used = getattr(selected_agent, 'name', 'All Plugins')

                        # Emit responded thought with total duration from user message
                        agent_total_duration_s = round(time.time() - request_start_time, 1)
                        thought_tracker.add_thought('generation', f"'{agent_deployment_name}' responded ({agent_total_duration_s}s from initial message)")

                        # Deregister real-time thought callback
                        plugin_logger.deregister_callbacks(callback_key)

                        # Get the actual model deployment used by the agent
                        actual_model_deployment = getattr(selected_agent, 'deployment_name', None) or agent_used
                        debug_print(f"Agent '{agent_used}' using deployment: {actual_model_deployment}")

                        # Extract detailed plugin invocations for enhanced agent citations
                        # (Thoughts already written to Cosmos in real-time by callback)
                        plugin_invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id)

                        # Convert plugin invocations to citation format with detailed information
                        detailed_citations = []
                        for inv in plugin_invocations:
                            # Handle timestamp formatting safely
                            timestamp_str = None
                            if inv.timestamp:
                                if hasattr(inv.timestamp, 'isoformat'):
                                    timestamp_str = inv.timestamp.isoformat()
                                else:
                                    timestamp_str = str(inv.timestamp)
                            tool_name = build_agent_citation_tool_label(
                                inv.plugin_name,
                                inv.function_name,
                                inv.parameters,
                                inv.result,
                            )

                            citation = {
                                'tool_name': tool_name,
                                'function_name': inv.function_name,
                                'plugin_name': inv.plugin_name,
                                'function_arguments': make_json_serializable(inv.parameters),
                                'function_result': make_json_serializable(inv.result),
                                'duration_ms': inv.duration_ms,
                                'timestamp': timestamp_str,
                                'success': inv.success,
                                'error_message': make_json_serializable(inv.error_message),
                                'user_id': inv.user_id
                            }
                            detailed_citations.append(citation)

                        log_event(
                            f"[Enhanced Agent Citations] Extracted {len(detailed_citations)} detailed plugin invocations",
                            extra={
                                "agent": agent_used,
                                "plugin_count": len(detailed_citations),
                                "plugins": [f"{inv.plugin_name}.{inv.function_name}" for inv in plugin_invocations],
                                "total_duration_ms": sum(inv.duration_ms for inv in plugin_invocations if inv.duration_ms)
                            }
                        )

                        # debug_print(f"[Enhanced Agent Citations] Agent used: {agent_used}")
                        # debug_print(f"[Enhanced Agent Citations] Extracted {len(detailed_citations)} detailed plugin invocations")
                        # for citation in detailed_citations:
                        #     debug_print(f"[Enhanced Agent Citations] - Plugin: {citation['plugin_name']}, Function: {citation['function_name']}")
                        #     debug_print(f"  Parameters: {citation['function_arguments']}")
                        #     debug_print(f"  Result: {citation['function_result']}")
                        #     debug_print(f"  Duration: {citation['duration_ms']}ms, Success: {citation['success']}")

                        # Store detailed citations globally to be accessed by the calling function
                        agent_citations_list.extend(detailed_citations)

                        if not reload_messages_required:
                            for citation in detailed_citations:
                                if result_requires_message_reload(citation.get('function_result')):
                                    reload_messages_required = True
                                    break

                        if enable_multi_agent_orchestration and not per_user_semantic_kernel:
                            # If the agent response indicates fallback mode
                            notice = (
                                "[SK Fallback]: The AI assistant is running in single agent fallback mode. "
                                "Some advanced features may not be available. "
                                "Please contact your administrator to configure Semantic Kernel for richer responses."
                            )
                        return (msg, actual_model_deployment, "agent", notice)
                    def agent_error(e):
                        plugin_logger.deregister_callbacks(callback_key)
                        debug_print(f"Error during Semantic Kernel Agent invocation: {str(e)}")
                        log_event(
                            f"Error during Semantic Kernel Agent invocation: {str(e)}",
                            extra=extra,
                            level=logging.ERROR,
                            exceptionTraceback=True
                        )

                    selected_agent_type = getattr(selected_agent, 'agent_type', 'local') or 'local'
                    if isinstance(selected_agent_type, str):
                        selected_agent_type = selected_agent_type.lower()

                    if _is_foundry_selected_agent_type(selected_agent_type):
                        def invoke_foundry_agent():
                            foundry_metadata = {
                                'conversation_id': conversation_id,
                                'user_id': user_id,
                                'message_id': user_message_id,
                                'chat_type': chat_type,
                                'document_scope': document_scope,
                                'group_id': active_group_id if chat_type == 'group' else None,
                                'hybrid_search_enabled': hybrid_search_enabled,
                                'selected_document_id': selected_document_id,
                                'selected_document_ids': effective_selected_document_ids,
                                'active_group_ids': effective_active_group_ids,
                                'active_public_workspace_ids': effective_active_public_workspace_ids,
                                'selected_document_count': len(effective_selected_document_ids or []),
                                'search_query': search_query,
                            }
                            return selected_agent.invoke(
                                agent_message_history,
                                metadata={k: v for k, v in foundry_metadata.items() if v is not None}
                            )

                        def foundry_agent_success(result):
                            msg = str(result)
                            notice = None
                            foundry_label = _get_foundry_agent_label(selected_agent_type)
                            agent_used = getattr(selected_agent, 'name', foundry_label)
                            actual_model_deployment = (
                                getattr(selected_agent, 'last_run_model', None)
                                or getattr(selected_agent, 'deployment_name', None)
                                or agent_used
                            )

                            # Emit responded thought with total duration from user message
                            foundry_total_duration_s = round(time.time() - request_start_time, 1)
                            thought_tracker.add_thought('generation', f"'{actual_model_deployment}' responded ({foundry_total_duration_s}s from initial message)")

                            # Deregister real-time thought callback
                            plugin_logger.deregister_callbacks(callback_key)

                            foundry_citations = getattr(selected_agent, 'last_run_citations', []) or []
                            if foundry_citations:
                                # Emit thoughts for Foundry agent citations/tool calls
                                for citation in foundry_citations:
                                    thought_tracker.add_thought(
                                        'agent_tool_call',
                                        f"Agent retrieved citation from {_get_foundry_agent_label(selected_agent_type)}"
                                    )
                                for citation in foundry_citations:
                                    serializable = make_json_serializable(citation)
                                    if not isinstance(serializable, dict):
                                        serializable = {'value': str(citation)}
                                    agent_citations_list.append({
                                        'tool_name': agent_used,
                                        'function_name': 'foundry_citation',
                                        'plugin_name': _get_foundry_agent_plugin_name(selected_agent_type),
                                        'function_arguments': serializable,
                                        'function_result': serializable,
                                        'timestamp': datetime.utcnow().isoformat(),
                                        'success': True
                                    })

                            if enable_multi_agent_orchestration and not per_user_semantic_kernel:
                                notice = (
                                    "[SK Fallback]: The AI assistant is running in single agent fallback mode. "
                                    "Some advanced features may not be available. "
                                    "Please contact your administrator to configure Semantic Kernel for richer responses."
                                )

                            log_event(
                                f"[Foundry Agent] Invocation complete for {agent_used}",
                                extra={
                                    'conversation_id': conversation_id,
                                    'user_id': user_id,
                                    'agent_id': getattr(selected_agent, 'id', None),
                                    'model_used': actual_model_deployment,
                                    'citation_count': len(foundry_citations),
                                }
                            )

                            return (msg, actual_model_deployment, 'agent', notice)

                        def foundry_agent_error(e):
                            plugin_logger.deregister_callbacks(callback_key)
                            log_event(
                                f"Error during {selected_agent_type} agent invocation: {str(e)}",
                                extra={
                                    'conversation_id': conversation_id,
                                    'user_id': user_id,
                                    'agent_id': getattr(selected_agent, 'id', None),
                                    'agent_type': selected_agent_type,
                                },
                                level=logging.ERROR,
                                exceptionTraceback=True
                            )

                        fallback_steps.append({
                            'name': 'foundry_agent',
                            'func': invoke_foundry_agent,
                            'on_success': foundry_agent_success,
                            'on_error': foundry_agent_error
                        })
                    else:
                        fallback_steps.append({
                            'name': 'agent',
                            'func': invoke_selected_agent,
                            'on_success': agent_success,
                            'on_error': agent_error
                        })

                if kernel and (selected_agent or explicit_chart_request):
                    def invoke_kernel():
                        plugin_logger = get_plugin_logger()
                        baseline_invocation_count = len(
                            plugin_logger.get_invocations_for_conversation(
                                user_id,
                                conversation_id,
                                limit=1000,
                            )
                        )
                        callback_key = register_plugin_invocation_thought_callback(
                            plugin_logger,
                            thought_tracker,
                            user_id,
                            conversation_id,
                            actor_label='Kernel'
                        )
                        chat_history = "\n".join([
                            f"{msg['role']}: {msg['content']}" for msg in conversation_history_for_api
                        ])
                        try:
                            chat_func = None
                            if hasattr(kernel, 'plugins'):
                                for plugin in kernel.plugins.values():
                                    if hasattr(plugin, 'functions') and 'chat' in plugin.functions:
                                        chat_func = plugin.functions['chat']
                                        break
                            if chat_func:
                                kernel_result = asyncio.run(run_sk_call(kernel.invoke, chat_func, input=chat_history))
                                _append_new_plugin_invocation_citations(
                                    agent_citations_list,
                                    plugin_logger,
                                    user_id,
                                    conversation_id,
                                    baseline_invocation_count,
                                )
                                return kernel_result
                            else:
                                log_event(
                                    "No dedicated chat action/plugin found. Trying kernel-native chatcompletion via service lookup.",
                                    extra=extra,
                                    level=logging.WARNING
                                )
                                chat_service = kernel.get_service(type=ChatCompletionClientBase)
                                if chat_service is not None:
                                    chat_hist = ChatHistory()
                                    for msg in conversation_history_for_api:
                                        chat_hist.add_message({"role": msg["role"], "content": msg["content"]})
                                    settings_obj = PromptExecutionSettings()
                                    if hasattr(settings_obj, 'function_choice_behavior'):
                                        settings_obj.function_choice_behavior = FunctionChoiceBehavior.Auto(maximum_auto_invoke_attempts=20)

                                    async def run_chatcompletion():
                                        return await chat_service.get_chat_message_contents(chat_hist, settings_obj)

                                    chat_result = asyncio.run(run_chatcompletion())
                                    if chat_result and hasattr(chat_result[0], 'content'):
                                        kernel_result = chat_result[0].content
                                    else:
                                        kernel_result = str(chat_result)
                                    _append_new_plugin_invocation_citations(
                                        agent_citations_list,
                                        plugin_logger,
                                        user_id,
                                        conversation_id,
                                        baseline_invocation_count,
                                    )
                                    return kernel_result
                                else:
                                    log_event("No chat completion service found in kernel. Falling back to GPT.", extra=extra, level=logging.WARNING)
                                    raise Exception("No chat completion service found in kernel.")
                        finally:
                            plugin_logger.deregister_callbacks(callback_key)
                    def kernel_success(result):
                        msg = '[SK fallback] Running in kernel only mode. Ask your administrator to configure Semantic Kernel for richer responses.'
                        return (str(result), "kernel", "kernel", msg)
                    def kernel_error(e):
                        debug_print(f"Error during kernel invocation: {str(e)}")
                        log_event(
                            f"Error during kernel invocation: {str(e)}",
                            extra=extra,
                            level=logging.ERROR,
                            exceptionTraceback=True
                        )
                    fallback_steps.append({
                        'name': 'kernel',
                        'func': invoke_kernel,
                        'on_success': kernel_success,
                        'on_error': kernel_error
                    })

            conversation_history_for_api = maybe_append_chart_tool_system_message(
                conversation_history_for_api,
                user_message,
                selected_agent,
            )
            conversation_history_for_api = maybe_append_image_proposal_system_message(
                conversation_history_for_api,
                user_message,
                settings,
                selected_agent,
            )

            thought_tracker.add_thought('generation', f"Sending to '{gpt_model}'")
            def invoke_gpt_fallback():
                if not conversation_history_for_api:
                    raise Exception('Cannot generate response: No conversation history available.')
                if conversation_history_for_api[-1].get('role') != 'user':
                    raise Exception('Internal error: Conversation history improperly formed.')
                debug_print(f"--- Sending to GPT ({gpt_model}) ---")
                debug_print(f"Total messages in API call: {len(conversation_history_for_api)}")

                # Prepare API call parameters
                api_params = {
                    'model': gpt_model,
                    'messages': conversation_history_for_api,
                }

                # Add reasoning_effort if provided and not 'none'
                if reasoning_effort and reasoning_effort != 'none':
                    api_params['reasoning_effort'] = reasoning_effort
                    debug_print(f"Using reasoning effort: {reasoning_effort}")

                try:
                    response = gpt_client.chat.completions.create(**api_params)
                except Exception as e:
                    error_str = str(e).lower()
                    if reasoning_effort and reasoning_effort != 'none' and (
                        'reasoning_effort' in error_str or
                        'unrecognized request argument' in error_str or
                        'invalid_request_error' in error_str
                    ):
                        debug_print(f"Reasoning effort not supported by {gpt_model}, retrying without reasoning_effort...")
                        api_params.pop('reasoning_effort', None)
                        response = gpt_client.chat.completions.create(**api_params)
                    elif (
                        gpt_provider in ('aifoundry', 'new_foundry')
                        and 'api version not supported' in error_str
                        and infer_model_endpoint_protocol(gpt_provider, gpt_endpoint, gpt_model) == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
                    ):
                        debug_print("Foundry API version not supported. Retrying with fallback versions...")
                        api_params.pop('reasoning_effort', None)
                        fallback_versions = get_foundry_api_version_candidates(gpt_api_version, settings)
                        response = None
                        last_error = None
                        for candidate in fallback_versions:
                            if candidate == gpt_api_version:
                                continue
                            try:
                                debug_print(f"[SKChat] Foundry retry api_version={candidate}")
                                retry_client = build_streaming_multi_endpoint_client(
                                    gpt_auth or {},
                                    gpt_provider,
                                    gpt_endpoint,
                                    candidate,
                                    deployment_name=gpt_model,
                                )
                                response = retry_client.chat.completions.create(**api_params)
                                break
                            except Exception as retry_exc:
                                last_error = retry_exc
                                debug_print(f"[SKChat] Foundry retry failed for api_version={candidate}: {retry_exc}")
                        if response is None and last_error is not None:
                            raise last_error
                    else:
                        raise

                msg = response.choices[0].message.content
                notice = None
                if enable_semantic_kernel and user_enable_agents:
                    msg = f"[GPT Fallback. Advanced features not available.] {msg}"
                    notice = (
                        "[SK Fallback]: The AI assistant is running in GPT only mode. "
                        "No advanced features are available. "
                        "Please contact your administrator to resolve Semantic Kernel integration."
                    )
                # Capture token usage for storage in message metadata
                token_usage_data = {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens,
                    'captured_at': datetime.utcnow().isoformat()
                }

                log_event(
                    f"[Tokens] GPT completion response received - prompt_tokens: {response.usage.prompt_tokens}, completion_tokens: {response.usage.completion_tokens}, total_tokens: {response.usage.total_tokens}",
                    extra={
                        "model": gpt_model,
                        "completion_tokens": response.usage.completion_tokens,
                        "prompt_tokens": response.usage.prompt_tokens,
                        "total_tokens": response.usage.total_tokens,
                        "user_id": get_current_user_id(),
                        "active_group_id": active_group_id,
                        "doc_scope": document_scope
                    },
                    level=logging.INFO
                )
                return (msg, gpt_model, None, notice, token_usage_data)
            def gpt_success(result):
                return result
            def gpt_error(e):
                debug_print(f"Error during final GPT completion: {str(e)}")
                if "context length" in str(e).lower():
                    return ("Sorry, the conversation history is too long even after summarization. Please start a new conversation or try a shorter message.", gpt_model, None, None, None)
                else:
                    return (f"Sorry, I encountered an error generating the response. Details: {str(e)}", gpt_model, None, None, None)
            fallback_steps.append({
                'name': 'gpt',
                'func': invoke_gpt_fallback,
                'on_success': gpt_success,
                'on_error': gpt_error
            })

            fallback_result = try_fallback_chain(fallback_steps)

            # Unpack result - handle both 4-tuple (SK) and 5-tuple (GPT with tokens)
            if len(fallback_result) == 5:
                ai_message, final_model_used, chat_mode, kernel_fallback_notice, token_usage_data = fallback_result
            else:
                ai_message, final_model_used, chat_mode, kernel_fallback_notice = fallback_result
                token_usage_data = None

            ai_message = _append_inline_chart_blocks_to_message(ai_message, agent_citations_list)

            # Emit responded thought for non-agent paths (agent paths emit their own inside callbacks)
            if not selected_agent:
                gpt_total_duration_s = round(time.time() - request_start_time, 1)
                thought_tracker.add_thought('generation', f"'{final_model_used}' responded ({gpt_total_duration_s}s from initial message)")

            # Collect token usage from Semantic Kernel services if available
            if kernel and not token_usage_data:
                try:
                    for service in getattr(kernel, "services", {}).values():
                        # Each service is likely an AzureChatCompletion or similar
                        prompt_tokens = getattr(service, "prompt_tokens", None)
                        completion_tokens = getattr(service, "completion_tokens", None)
                        total_tokens = getattr(service, "total_tokens", None)
                        debug_print(f"Service {getattr(service, 'service_id', None)} prompt_tokens: {prompt_tokens}, completion_tokens: {completion_tokens}, total_tokens: {total_tokens}")
                        log_event(
                            f"[Tokens] Service token usage: prompt_tokens: {prompt_tokens}, completion_tokens: {completion_tokens}, total_tokens: {total_tokens}",
                            extra={
                                "service_id": getattr(service, "service_id", None),
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "total_tokens": total_tokens,
                                "user_id": get_current_user_id(),
                                "active_group_id": active_group_id,
                                "doc_scope": document_scope
                            },
                            level=logging.INFO
                        )

                        # Capture token usage from first service with token data
                        if (prompt_tokens or completion_tokens or total_tokens) and not token_usage_data:
                            token_usage_data = {
                                'prompt_tokens': prompt_tokens,
                                'completion_tokens': completion_tokens,
                                'total_tokens': total_tokens,
                                'captured_at': datetime.utcnow().isoformat(),
                                'service_id': getattr(service, 'service_id', None)
                            }
                except Exception as e:
                    log_event(
                        f"[Tokens] Error logging service token usage for user '{get_current_user_id()}': {e}",
                        level=logging.ERROR,
                        exceptionTraceback=True
                    )

        # region 7 - Save GPT Response
            # ---------------------------------------------------------------------
            # 7) Save GPT response (or error message)
            # ---------------------------------------------------------------------

            # Determine the actual model used and agent information
            actual_model_used = final_model_used
            agent_display_name = None
            agent_name = None
            agent_icon = None
            agent_tags = []

            if selected_agent:
                # When using an agent, use the agent's actual model deployment
                if hasattr(selected_agent, 'deployment_name') and selected_agent.deployment_name:
                    actual_model_used = selected_agent.deployment_name

                # Get agent display information
                if hasattr(selected_agent, 'display_name'):
                    agent_display_name = selected_agent.display_name
                if hasattr(selected_agent, 'name'):
                    agent_name = selected_agent.name
            agent_scope_for_usage = 'personal'
            agent_group_id_for_usage = None
            agent_catalog_key_for_usage = None
            if selected_agent:
                selection_metadata = user_metadata.get('agent_selection') if isinstance(user_metadata, dict) else None
                if isinstance(selection_metadata, dict):
                    if selection_metadata.get('is_global'):
                        agent_scope_for_usage = 'global'
                    elif selection_metadata.get('is_group'):
                        agent_scope_for_usage = 'group'
                        agent_group_id_for_usage = selection_metadata.get('group_id')
                    agent_catalog_key_for_usage = selection_metadata.get('catalog_key')
                    agent_icon = selection_metadata.get('agent_icon')
                    agent_tags = selection_metadata.get('agent_tags') or []

            # assistant_message_id was generated earlier for thought tracking

            user_info_for_assistant = response_message_context.get('user_info')
            user_thread_id = response_message_context.get('thread_id')
            user_previous_thread_id = response_message_context.get('previous_thread_id')

            # Assistant message should be part of the same thread as the user message
            # Only system/augmentation messages create new threads within a conversation
            assistant_timestamp = datetime.utcnow().isoformat()
            prepared_agent_citations = persist_agent_citation_artifacts(
                conversation_id=conversation_id,
                assistant_message_id=assistant_message_id,
                agent_citations=agent_citations_list,
                created_timestamp=assistant_timestamp,
                user_info=user_info_for_assistant,
            )
            assistant_table_generated_output = maybe_create_assistant_table_generated_output(
                user_question=user_message,
                assistant_content=ai_message,
                conversation_id=conversation_id,
                existing_outputs=generated_analysis_artifacts_list + generated_tabular_outputs_list,
            )
            if assistant_table_generated_output:
                generated_analysis_artifacts_list.append(assistant_table_generated_output)
                generated_tabular_outputs_list.append(assistant_table_generated_output)
            generated_analysis_metadata = _build_generated_analysis_metadata(
                generated_analysis_artifacts=generated_analysis_artifacts_list,
                generated_tabular_outputs=generated_tabular_outputs_list,
            )
            source_review_used = _source_review_metadata_used(source_review_result)
            assistant_capability_usage = _build_capability_usage_metadata(
                workspace_search_enabled=hybrid_search_enabled or history_grounded_search_used,
                workspace_search_used=bool(search_results),
                workspace_search_result_count=len(hybrid_citations_list or []),
                document_action_type=DOCUMENT_ACTION_TYPE_NONE,
                document_scope=effective_document_scope,
                selected_document_ids=effective_selected_document_ids,
                active_group_ids=effective_active_group_ids,
                active_public_workspace_ids=effective_active_public_workspace_ids,
                web_search_enabled=web_search_enabled,
                web_search_used=bool(web_search_citations_list or deep_research_web_search_runs),
                web_search_citation_count=len(web_search_citations_list or []),
                web_search_run_count=len(deep_research_web_search_runs or []),
                url_access_enabled=url_access_enabled,
                source_review_enabled=source_review_enabled,
                source_review_used=source_review_used,
                deep_research_enabled=deep_research_enabled,
                deep_research_used=bool(deep_research_enabled and (deep_research_result or deep_research_web_search_runs or source_review_used)),
                deep_research_query_count=_deep_research_query_count(deep_research_query_plan, deep_research_web_search_runs),
            )
            agent_runtime_metadata = _build_foundry_runtime_metadata(selected_agent) if selected_agent else {}

            assistant_doc = make_json_serializable({
                'id': assistant_message_id,
                'conversation_id': conversation_id,
                'role': 'assistant',
                'content': ai_message,
                'timestamp': assistant_timestamp,
                'augmented': bool(system_messages_for_augmentation),
                'hybrid_citations': hybrid_citations_list, # <--- SIMPLIFIED: Directly use the list
                'web_search_citations': web_search_citations_list,
                'hybridsearch_query': search_query if search_results else None, # Log query when any bounded document retrieval produced results
                'agent_citations': prepared_agent_citations,
                'model_deployment_name': actual_model_used,
                'agent_display_name': agent_display_name,
                'agent_name': agent_name,
                'agent_icon': agent_icon,
                'agent_tags': agent_tags,
                'metadata': {
                    'user_info': user_info_for_assistant,  # Track which user created this assistant message
                    'reasoning_effort': reasoning_effort,
                    'history_context': history_debug_info,
                    'capability_usage': assistant_capability_usage,
                    'agent_runtime': agent_runtime_metadata or None,
                    'source_review': compact_source_review_result_for_metadata(source_review_result),
                    'deep_research': deep_research_result,
                    **generated_analysis_metadata,
                    'thread_info': {
                        'thread_id': user_thread_id,  # Same thread as user message
                        'previous_thread_id': user_previous_thread_id,  # Same previous_thread_id as user message
                        'active_thread': True,
                        'thread_attempt': assistant_thread_attempt
                    },
                    'token_usage': token_usage_data  # Store token usage information
                } # Used by SK and reasoning effort
            })

            debug_print(f"🔍 Chat API - Creating assistant message with thread_info:")
            debug_print(f"    thread_id: {user_thread_id}")
            debug_print(f"    previous_thread_id: {user_previous_thread_id}")
            debug_print(f"    attempt: {assistant_thread_attempt}")
            debug_print(f"    is_retry: {is_retry}")

            cosmos_messages_container.upsert_item(assistant_doc)

            if selected_agent and agent_name:
                log_agent_run(
                    user_id=get_current_user_id(),
                    agent_id=getattr(selected_agent, 'id', None),
                    agent_name=agent_name,
                    agent_display_name=agent_display_name,
                    scope=agent_scope_for_usage,
                    group_id=agent_group_id_for_usage,
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    model=actual_model_used,
                    agent_catalog_key=agent_catalog_key_for_usage,
                )

            # Log chat token usage to activity_logs for easy reporting
            if token_usage_data and token_usage_data.get('total_tokens'):
                try:
                    from functions_activity_logging import log_token_usage

                    # Determine workspace type based on active group/public workspace
                    workspace_type = 'personal'
                    if effective_active_public_workspace_id:
                        workspace_type = 'public'
                    elif effective_active_group_id:
                        workspace_type = 'group'

                    log_token_usage(
                        user_id=get_current_user_id(),
                        token_type='chat',
                        total_tokens=token_usage_data.get('total_tokens'),
                        model=actual_model_used,
                        workspace_type=workspace_type,
                        prompt_tokens=token_usage_data.get('prompt_tokens'),
                        completion_tokens=token_usage_data.get('completion_tokens'),
                        conversation_id=conversation_id,
                        message_id=assistant_message_id,
                        group_id=effective_active_group_id,
                        public_workspace_id=effective_active_public_workspace_id,
                        additional_context={
                            'agent_name': agent_name,
                            'augmented': bool(system_messages_for_augmentation),
                            'reasoning_effort': reasoning_effort
                        }
                    )
                except Exception as log_error:
                    debug_print(f"⚠️  Warning: Failed to log chat token usage: {log_error}")
                    # Don't fail the chat flow if logging fails

            # Update the user message metadata with the actual model used
            # This ensures the UI shows the correct model in the metadata panel
            try:
                user_message_doc = cosmos_messages_container.read_item(
                    item=user_message_id,
                    partition_key=conversation_id
                )

                # Update the model selection in metadata to show actual model used
                if 'metadata' in user_message_doc and 'model_selection' in user_message_doc['metadata']:
                    user_message_doc['metadata']['model_selection']['selected_model'] = actual_model_used
                    cosmos_messages_container.upsert_item(user_message_doc)

            except Exception as e:
                debug_print(f"Warning: Could not update user message metadata: {e}")

            # Update conversation's last_updated timestamp one last time
            conversation_item['last_updated'] = datetime.utcnow().isoformat()

            # Collect comprehensive conversation metadata
            try:
                # Determine selected agent name if one was used
                selected_agent_name = None
                if selected_agent:
                    selected_agent_name = getattr(selected_agent, 'name', None)

                # Collect metadata for this conversation interaction
                conversation_item = collect_conversation_metadata(
                    user_message=user_message,
                    conversation_id=conversation_id,
                    user_id=user_id,
                    active_group_id=effective_active_group_id,
                    active_group_ids=effective_active_group_ids,
                    document_scope=effective_document_scope,
                    selected_document_id=effective_selected_document_id,
                    model_deployment=actual_model_used,
                    hybrid_search_enabled=hybrid_search_enabled or history_grounded_search_used,
                    image_gen_enabled=image_gen_enabled,
                    selected_documents=combined_documents if 'combined_documents' in locals() else None,
                    selected_agent=selected_agent_name,
                    selected_agent_details=user_metadata.get('agent_selection'),
                    search_results=search_results if 'search_results' in locals() else None,
                    conversation_item=conversation_item,
                    active_public_workspace_id=effective_active_public_workspace_id,
                    active_public_workspace_ids=effective_active_public_workspace_ids
                )
            except Exception as e:
                debug_print(f"Error collecting conversation metadata: {e}")
                # Continue even if metadata collection fails

            # Add any other final updates to conversation_item if needed (like classifications if not done earlier)
            cosmos_conversations_container.upsert_item(conversation_item)

            # ---------------------------------------------------------------------
            # 8) Return final success (even if AI generated an error message)
            # ---------------------------------------------------------------------
            # Persist per-user kernel state if needed
            enable_redis_for_kernel = False
            if enable_semantic_kernel and per_user_semantic_kernel and redis_client and enable_redis_for_kernel:
                save_user_kernel(user_id, g.kernel, g.kernel_agents, redis_client)
            return jsonify(make_json_serializable({
                'reply': ai_message, # Send the AI's response (or the error message) back
                'conversation_id': conversation_id,
                'conversation_title': conversation_item['title'], # Send updated title
                'classification': conversation_item.get('classification', []), # Send classifications if any
                'context': conversation_item.get('context', []),
                'chat_type': conversation_item.get('chat_type'),
                'scope_locked': conversation_item.get('scope_locked'),
                'locked_contexts': conversation_item.get('locked_contexts', []),
                'model_deployment_name': actual_model_used,
                'agent_display_name': agent_display_name,
                'agent_name': agent_name,
                'agent_icon': agent_icon,
                'agent_tags': agent_tags,
                'message_id': assistant_message_id,
                'user_message_id': user_message_id,  # Include the user message ID
                'blocked': False, # Explicitly false if we got this far
                'augmented': bool(system_messages_for_augmentation),
                'hybrid_citations': hybrid_citations_list,
                'web_search_citations': web_search_citations_list,
                'source_review': compact_source_review_result_for_metadata(source_review_result),
                'deep_research': deep_research_result,
                'agent_citations': prepared_agent_citations,
                'metadata': assistant_doc.get('metadata', {}),
                'reload_messages': reload_messages_required,
                'kernel_fallback_notice': kernel_fallback_notice,
                'thoughts_enabled': thought_tracker.enabled
            })), 200

        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            debug_print(f"[CHAT API ERROR] Unhandled exception in chat_api: {str(e)}")
            debug_print(f"[CHAT API ERROR] Full traceback:\n{error_traceback}")
            log_event(
                f"[CHAT API ERROR] Unhandled exception in chat_api: {str(e)}",
                extra={
                    "error_message": str(e),
                    "traceback": error_traceback,
                    "user_id": user_id if 'user_id' in locals() else None,
                    "conversation_id": conversation_id if 'conversation_id' in locals() else None
                },
                level=logging.ERROR
            )
            return jsonify({
                'error': f'Internal server error: {str(e)}',
                'details': error_traceback if app.debug else None
            }), 500

    @app.route('/api/chat/stream', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_stream_api():
        """
        Streaming version of chat endpoint using Server-Sent Events (SSE).
        Streams tokens as they are generated from Azure OpenAI.
        """
        from flask import Response, stream_with_context
        import json
        from queue import Queue, Empty

        # IMPORTANT: Parse JSON and get user_id BEFORE entering the generator
        # because request context may not be available inside the generator
        try:
            data = request.get_json()
            user_id = get_current_user_id()
            current_user_info = get_current_user_info() or {}
            current_user_email = current_user_info.get('email')
            current_user_roles = (session.get('user') or {}).get('roles', [])
            settings = get_settings()
            request_start_time = time.time()
        except Exception as e:
            return jsonify({'error': f'Failed to parse request: {str(e)}'}), 400

        retry_user_message_id = data.get('retry_user_message_id') or data.get('edited_user_message_id')
        retry_thread_id = data.get('retry_thread_id')
        retry_thread_attempt = data.get('retry_thread_attempt')
        is_retry = bool(retry_user_message_id)
        is_edit = bool(data.get('edited_user_message_id'))

        compatibility_mode = bool(data.get('image_generation')) or is_retry
        requested_conversation_id = str(data.get('conversation_id') or '').strip() or None

        if requested_conversation_id:
            try:
                _authorize_personal_conversation_access(user_id, requested_conversation_id)
            except LookupError:
                return jsonify({'error': 'Conversation not found'}), 404
            except PermissionError:
                return jsonify({'error': 'Forbidden'}), 403
            except Exception as exc:
                debug_print(f"[Streaming] Error authorizing conversation {requested_conversation_id}: {exc}")
                return jsonify({'error': 'Failed to authorize conversation'}), 500

        initial_scope_context = _get_authorized_chat_scope_context(
            user_id,
            active_group_id=data.get('active_group_id'),
            active_group_ids=data.get('active_group_ids', []),
            active_public_workspace_id=data.get('active_public_workspace_id'),
            active_public_workspace_ids=data.get('active_public_workspace_ids', []),
        )
        finalized_conversation_id = requested_conversation_id or str(uuid.uuid4())
        is_new_stream_conversation = requested_conversation_id is None
        data['conversation_id'] = finalized_conversation_id
        data['active_group_ids'] = list(initial_scope_context['active_group_ids'])
        data['active_group_id'] = initial_scope_context['active_group_id']
        data['active_public_workspace_ids'] = list(initial_scope_context['active_public_workspace_ids'])
        data['active_public_workspace_id'] = initial_scope_context['active_public_workspace_id']
        stream_session = CHAT_STREAM_REGISTRY.start_session(user_id, finalized_conversation_id)

        request_message = (data.get('message') or '').strip()
        request_preview = request_message[:120] + '...' if len(request_message) > 120 else request_message
        debug_print(
            "[Streaming] Incoming /api/chat/stream request | "
            f"requested_conversation_id={requested_conversation_id} | "
            f"conversation_id={finalized_conversation_id} | "
            f"compatibility_mode={compatibility_mode} | "
            f"is_retry={is_retry} | "
            f"hybrid_search={data.get('hybrid_search')} | "
            f"web_search={data.get('web_search_enabled')} | "
            f"doc_scope={data.get('doc_scope')} | "
            f"chat_type={data.get('chat_type', 'user')} | "
            f"selected_document_id={data.get('selected_document_id')} | "
            f"selected_document_ids={len(data.get('selected_document_ids', []) or [])} | "
            f"active_group_id={data.get('active_group_id')} | "
            f"active_group_ids={len(data.get('active_group_ids', []) or [])} | "
            f"active_public_workspace_id={data.get('active_public_workspace_id')} | "
            f"frontend_model={data.get('model_deployment')} | "
            f"message_preview={request_preview!r}"
        )

        if is_retry:
            operation_type = 'Edit' if is_edit else 'Retry'
            debug_print(
                f"[Streaming] {operation_type} detected | "
                f"user_message_id={retry_user_message_id} | "
                f"thread_id={retry_thread_id} | "
                f"attempt={retry_thread_attempt}"
            )

        def normalize_legacy_chat_payload(payload):
            """Convert the legacy JSON response shape into the streaming terminal payload."""
            return make_json_serializable({
                'done': True,
                'conversation_id': payload.get('conversation_id'),
                'conversation_title': payload.get('conversation_title'),
                'classification': payload.get('classification', []),
                'model_deployment_name': payload.get('model_deployment_name'),
                'message_id': payload.get('message_id'),
                'user_message_id': payload.get('user_message_id'),
                'augmented': payload.get('augmented', False),
                'hybrid_citations': payload.get('hybrid_citations', []),
                'web_search_citations': payload.get('web_search_citations', []),
                'agent_citations': payload.get('agent_citations', []),
                'agent_display_name': payload.get('agent_display_name'),
                'agent_name': payload.get('agent_name'),
                'full_content': payload.get('reply', ''),
                'image_url': payload.get('image_url'),
                'reload_messages': payload.get('reload_messages', False),
                'kernel_fallback_notice': payload.get('kernel_fallback_notice'),
                'thoughts_enabled': payload.get('thoughts_enabled', False),
                'blocked': payload.get('blocked', False),
            })

        def generate_compatibility_response():
            """Bridge legacy JSON chat handling into a terminal SSE event for parity cases."""
            try:
                g.conversation_id = finalized_conversation_id

                if data.get('image_generation'):
                    prompt_text = (data.get('message') or '').strip()
                    prompt_preview = prompt_text[:120] + '...' if len(prompt_text) > 120 else prompt_text

                    image_prompt_event = {
                        'type': 'thought',
                        'step_type': 'generation',
                        'content': f'Generating image based on \"{prompt_preview}\"' if prompt_preview else 'Generating image from your prompt'
                    }
                    yield f"data: {json.dumps(image_prompt_event)}\n\n"

                    image_request_event = {
                        'type': 'thought',
                        'step_type': 'generation',
                        'content': 'Preparing image model request'
                    }
                    yield f"data: {json.dumps(image_request_event)}\n\n"

                legacy_result = chat_api()
                legacy_response = legacy_result
                status_code = 200

                if isinstance(legacy_result, tuple):
                    legacy_response = legacy_result[0]
                    if len(legacy_result) > 1 and isinstance(legacy_result[1], int):
                        status_code = legacy_result[1]

                if hasattr(legacy_response, 'get_json'):
                    payload = legacy_response.get_json(silent=True) or {}
                else:
                    payload = {}

                if status_code >= 400:
                    error_message = payload.get('error') or f'Compatibility chat request failed ({status_code})'
                    yield f"data: {json.dumps({'error': error_message})}\n\n"
                    return

                if payload.get('image_url'):
                    image_ready_event = {
                        'type': 'thought',
                        'step_type': 'generation',
                        'content': 'Image generated and ready to display'
                    }
                    yield f"data: {json.dumps(image_ready_event)}\n\n"

                yield f"data: {json.dumps(normalize_legacy_chat_payload(payload))}\n\n"
            except Exception as compatibility_error:
                yield f"data: {json.dumps({'error': str(compatibility_error)})}\n\n"

        if compatibility_mode:
            debug_print("[Streaming] Routing request through compatibility bridge")
            return build_background_stream_response(generate_compatibility_response, stream_session=stream_session)

        def generate(publish_background_event=None):
            try:
                # Import debug_print for use in generator
                from functions_debug import debug_print

                def stream_cancel_requested():
                    return bool(stream_session and stream_session.is_cancel_requested())

                if not user_id:
                    yield f"data: {json.dumps({'error': 'User not authenticated'})}\n\n"
                    return

                # Extract request parameters (same as non-streaming endpoint)
                user_message = data.get('message', '')
                conversation_id = finalized_conversation_id
                hybrid_search_enabled = data.get('hybrid_search')
                web_search_enabled = data.get('web_search_enabled')
                url_access_enabled = data.get('url_access_enabled')
                source_review_enabled = data.get('source_review_enabled')
                deep_research_enabled = data.get('deep_research_enabled')
                selected_document_id = data.get('selected_document_id')
                selected_document_ids = data.get('selected_document_ids', [])
                # Backwards compat: if no multi-select but single ID is set, wrap in list
                if not selected_document_ids and selected_document_id:
                    selected_document_ids = [selected_document_id]
                image_gen_enabled = data.get('image_generation')
                document_scope = data.get('doc_scope')
                tags_filter = data.get('tags', [])  # Extract tags filter
                active_group_id = data.get('active_group_id')
                active_group_ids = data.get('active_group_ids', [])
                active_public_workspace_id = data.get('active_public_workspace_id')  # Extract active public workspace ID
                active_public_workspace_ids = data.get('active_public_workspace_ids', [])
                scope_context = _get_authorized_chat_scope_context(
                    user_id,
                    active_group_id=active_group_id,
                    active_group_ids=active_group_ids,
                    active_public_workspace_id=active_public_workspace_id,
                    active_public_workspace_ids=active_public_workspace_ids,
                )
                active_group_ids = scope_context['active_group_ids']
                active_group_id = scope_context['active_group_id']
                active_public_workspace_ids = scope_context['active_public_workspace_ids']
                active_public_workspace_id = scope_context['active_public_workspace_id']
                frontend_gpt_model = data.get('model_deployment')
                frontend_model_id = data.get('model_id')
                frontend_model_endpoint_id = data.get('model_endpoint_id')
                frontend_model_provider = data.get('model_provider')
                classifications_to_send = data.get('classifications')
                chat_type = data.get('chat_type', 'user')
                reasoning_effort = data.get('reasoning_effort')  # Extract reasoning effort for reasoning models
                request_agent_info = data.get('agent_info')

                debug_print(
                    "[Streaming] Parsed request payload | "
                    f"user_id={user_id} | "
                    f"conversation_id={conversation_id} | "
                    f"message_length={len(user_message)} | "
                    f"hybrid_search={hybrid_search_enabled} | "
                    f"web_search={web_search_enabled} | "
                    f"doc_scope={document_scope} | "
                    f"chat_type={chat_type} | "
                    f"selected_document_id={selected_document_id} | "
                    f"selected_document_ids={len(selected_document_ids)} | "
                    f"active_group_id={active_group_id} | "
                    f"active_group_ids={len(active_group_ids)} | "
                    f"active_public_workspace_id={active_public_workspace_id} | "
                    f"frontend_model={frontend_gpt_model} | "
                    f"frontend_model_id={frontend_model_id} | "
                    f"frontend_model_endpoint_id={frontend_model_endpoint_id} | "
                    f"frontend_model_provider={frontend_model_provider} | "
                    f"reasoning_effort={reasoning_effort}"
                )

                # Check if agents are enabled
                enable_semantic_kernel = settings.get('enable_semantic_kernel', False)
                per_user_semantic_kernel = settings.get('per_user_semantic_kernel', False)
                user_settings = {}
                user_enable_agents = True
                force_enable_agents = _has_chat_agent_selection(request_agent_info)

                debug_print(f"[DEBUG] enable_semantic_kernel={enable_semantic_kernel}, per_user_semantic_kernel={per_user_semantic_kernel}")

                if force_enable_agents:
                    g.force_enable_agents = True
                    if isinstance(request_agent_info, dict):
                        g.request_agent_info = request_agent_info
                        g.request_agent_name = request_agent_info.get('name')
                    else:
                        g.request_agent_info = {'name': request_agent_info}
                        g.request_agent_name = request_agent_info

                # Initialize Semantic Kernel if needed
                redis_client = None
                if enable_semantic_kernel and per_user_semantic_kernel:
                    redis_client = current_app.config.get('SESSION_REDIS') if 'current_app' in globals() else None
                    initialize_semantic_kernel(user_id=user_id, redis_client=redis_client)
                    debug_print(f"[DEBUG] Initialized Semantic Kernel for user {user_id}")
                elif enable_semantic_kernel:
                    # Global mode: set g.kernel/g.kernel_agents from builtins
                    g.kernel = getattr(builtins, 'kernel', None)
                    g.kernel_agents = getattr(builtins, 'kernel_agents', None)
                    debug_print(f"[DEBUG] Using global Semantic Kernel")

                if enable_semantic_kernel and per_user_semantic_kernel:
                    try:
                        user_settings_obj = get_user_settings(user_id)
                        debug_print(f"[DEBUG] user_settings_obj type: {type(user_settings_obj)}")
                        # Sanitize user_settings_obj to remove sensitive data (keys, base64, images) from debug logs
                        sanitized_settings = sanitize_settings_for_logging(user_settings_obj) if isinstance(user_settings_obj, dict) else user_settings_obj
                        debug_print(f"[DEBUG] user_settings_obj (sanitized): {sanitized_settings}")

                        # user_settings_obj might be nested with 'settings' key
                        if isinstance(user_settings_obj, dict):
                            if 'settings' in user_settings_obj:
                                user_settings = user_settings_obj['settings']
                                sanitized_user_settings = sanitize_settings_for_logging(user_settings) if isinstance(user_settings, dict) else user_settings
                                debug_print(f"[DEBUG] Extracted user_settings from 'settings' key (sanitized): {sanitized_user_settings}")
                            else:
                                user_settings = user_settings_obj
                                sanitized_user_settings = sanitize_settings_for_logging(user_settings) if isinstance(user_settings, dict) else user_settings
                                debug_print(f"[DEBUG] Using user_settings_obj directly (sanitized): {sanitized_user_settings}")

                        user_enable_agents = user_settings.get('enable_agents', True)
                        if force_enable_agents:
                            user_enable_agents = True
                        debug_print(f"[DEBUG] user_enable_agents={user_enable_agents}")
                    except Exception as e:
                        debug_print(f"Error loading user settings: {e}")
                        import traceback
                        traceback.print_exc()

                # Streaming does not support image generation
                if image_gen_enabled:
                    yield f"data: {json.dumps({'error': 'Image generation is not supported in streaming mode'})}\n\n"
                    return

                _set_authorized_chat_request_context(user_id, conversation_id, scope_context)

                # Clear plugin invocations
                plugin_logger = get_plugin_logger()
                plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)
                debug_print(
                    f"[Streaming] Cleared plugin invocations for user_id={user_id}, conversation_id={conversation_id}"
                )

                # Validate chat_type
                if chat_type not in ('user', 'group'):
                    chat_type = 'user'
                scope_id = active_group_id if chat_type == 'group' else user_id
                scope_type = 'group' if chat_type == 'group' else 'user'

                # Initialize variables
                search_query = user_message
                web_search_query_text = build_web_search_query_text(user_message)
                hybrid_citations_list = []
                agent_citations_list = []
                web_search_citations_list = []
                source_review_result = {}
                deep_research_result = {}
                deep_research_query_plan = {}
                deep_research_web_search_runs = []
                generated_tabular_outputs_list = []
                generated_analysis_artifacts_list = []
                system_messages_for_augmentation = []
                search_results = []
                selected_agent = None

                # Configuration
                raw_conversation_history_limit = settings.get('conversation_history_limit', 6)
                conversation_history_limit = math.ceil(raw_conversation_history_limit)
                if conversation_history_limit % 2 != 0:
                    conversation_history_limit += 1
                enable_summarize_content_history_beyond_conversation_history_limit = settings.get(
                    'enable_summarize_content_history_beyond_conversation_history_limit',
                    True,
                )

                # Convert toggles
                if isinstance(hybrid_search_enabled, str):
                    hybrid_search_enabled = hybrid_search_enabled.lower() == 'true'
                if isinstance(web_search_enabled, str):
                    web_search_enabled = web_search_enabled.lower() == 'true'
                if isinstance(url_access_enabled, str):
                    url_access_enabled = url_access_enabled.lower() == 'true'
                if isinstance(source_review_enabled, str):
                    source_review_enabled = source_review_enabled.lower() == 'true'
                if isinstance(deep_research_enabled, str):
                    deep_research_enabled = deep_research_enabled.lower() == 'true'
                user_workspace_context_requested = data.get('user_workspace_context_enabled')
                if isinstance(user_workspace_context_requested, str):
                    user_workspace_context_requested = user_workspace_context_requested.lower() == 'true'
                user_workspace_context_requested = bool(user_workspace_context_requested)
                prompt_urls = extract_urls_from_text(user_message)
                url_access_requested = bool(url_access_enabled)
                if url_access_requested:
                    url_access_validation = validate_url_access_request(
                        user_message,
                        settings,
                        URL_ACCESS_CONTEXT_CHAT,
                        user_roles=current_user_roles,
                    )
                    if not url_access_validation.get('allowed'):
                        limit = url_access_validation.get('limit') or get_url_access_max_urls(URL_ACCESS_CONTEXT_CHAT, settings)
                        if url_access_validation.get('reason') == 'url_count_exceeded':
                            yield f"data: {json.dumps({'error': f'URL Access supports up to {limit} URL(s) per chat message.'})}\n\n"
                        elif url_access_validation.get('reason') == 'url_access_role_required':
                            yield f"data: {json.dumps({'error': 'URL Access requires the UrlAccessUser app role.'})}\n\n"
                        else:
                            yield f"data: {json.dumps({'error': 'URL Access is disabled by an administrator.'})}\n\n"
                        return
                url_access_enabled = bool(
                    url_access_requested
                    and prompt_urls
                    and is_url_access_enabled_for_user(settings, user_roles=current_user_roles)
                )
                source_review_allowed_for_user = is_source_review_enabled_for_user(
                    settings,
                    user_id,
                    user_email=current_user_email,
                    user_roles=current_user_roles,
                )
                deep_research_requested = bool(source_review_enabled) or bool(deep_research_enabled)
                deep_research_enabled = source_review_allowed_for_user and deep_research_requested
                source_review_enabled = bool(deep_research_enabled or url_access_enabled)
                original_hybrid_search_enabled = bool(hybrid_search_enabled)
                history_grounded_search_used = False
                history_only_answerability = None
                prior_grounded_document_refs = []
                effective_document_scope = document_scope
                effective_selected_document_ids = list(selected_document_ids or [])
                effective_selected_document_id = selected_document_id
                effective_active_group_ids = list(active_group_ids or [])
                effective_active_group_id = active_group_id
                effective_active_public_workspace_ids = list(active_public_workspace_ids or [])
                effective_active_public_workspace_id = active_public_workspace_id
                assigned_knowledge_filters = None
                canonical_request_agent = _resolve_canonical_chat_agent(user_id, settings, request_agent_info)
                if canonical_request_agent:
                    request_agent_info = canonical_request_agent
                    assigned_knowledge_filters = build_assigned_knowledge_runtime_filters(canonical_request_agent)

                assigned_knowledge_user_context_active = False
                assigned_knowledge_url_review_urls = []
                assigned_knowledge_deep_research_urls = []
                if assigned_knowledge_filters:
                    assigned_knowledge_user_context_active = (
                        user_workspace_context_requested
                        and _assigned_knowledge_allows_user_workspace_context(assigned_knowledge_filters)
                        and _assigned_knowledge_allows_document_action(
                            assigned_knowledge_filters,
                            DOCUMENT_ACTION_TYPE_NONE,
                        )
                    )
                    if assigned_knowledge_filters.get('has_workspace_knowledge'):
                        hybrid_search_enabled = True
                        if not assigned_knowledge_user_context_active:
                            effective_document_scope = assigned_knowledge_filters.get('doc_scope') or 'all'
                            effective_selected_document_ids = list(assigned_knowledge_filters.get('document_ids') or [])
                            effective_selected_document_id = effective_selected_document_ids[0] if len(effective_selected_document_ids) == 1 else None
                            effective_active_group_ids = list(assigned_knowledge_filters.get('active_group_ids') or [])
                            effective_active_group_id = effective_active_group_ids[0] if len(effective_active_group_ids) == 1 else None
                            effective_active_public_workspace_ids = list(
                                assigned_knowledge_filters.get('active_public_workspace_ids') or []
                            )
                            effective_active_public_workspace_id = (
                                effective_active_public_workspace_ids[0]
                                if len(effective_active_public_workspace_ids) == 1
                                else None
                            )
                            tags_filter = list(assigned_knowledge_filters.get('tags_filter') or [])
                            document_scope = effective_document_scope
                            selected_document_ids = effective_selected_document_ids
                            selected_document_id = effective_selected_document_id
                            active_group_ids = effective_active_group_ids
                            active_group_id = effective_active_group_id
                            active_public_workspace_ids = effective_active_public_workspace_ids
                            active_public_workspace_id = effective_active_public_workspace_id
                    elif assigned_knowledge_user_context_active:
                        hybrid_search_enabled = True

                    assigned_knowledge_url_review_urls = _get_assigned_knowledge_web_source_urls(
                        assigned_knowledge_filters,
                        ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_URL_REVIEW,
                    )
                    assigned_knowledge_deep_research_urls = _get_assigned_knowledge_web_source_urls(
                        assigned_knowledge_filters,
                        ASSIGNED_KNOWLEDGE_WEB_SOURCE_MODE_DEEP_RESEARCH,
                    )
                    if assigned_knowledge_url_review_urls and not is_url_access_enabled_for_user(
                        settings,
                        user_roles=current_user_roles,
                    ):
                        yield f"data: {json.dumps({'error': 'This agent has assigned URL sources, but URL Access is not available for your account.'})}\n\n"
                        return
                    if assigned_knowledge_deep_research_urls and not source_review_allowed_for_user:
                        yield f"data: {json.dumps({'error': 'This agent has assigned Deep Research sources, but Deep Research is not available for your account.'})}\n\n"
                        return
                    if assigned_knowledge_url_review_urls or assigned_knowledge_deep_research_urls:
                        source_review_enabled = True
                        if assigned_knowledge_deep_research_urls:
                            deep_research_enabled = True
                    g.assigned_knowledge_context = assigned_knowledge_filters
                    g.assigned_knowledge_user_context_active = assigned_knowledge_user_context_active
                    debug_print(
                        "[Streaming] Assigned Knowledge applied | "
                        f"scope={effective_document_scope} | "
                        f"documents={len(effective_selected_document_ids)} | "
                        f"groups={len(effective_active_group_ids)} | "
                        f"public_workspaces={len(effective_active_public_workspace_ids)} | "
                        f"tags={len(tags_filter)}"
                    )
                debug_print(
                    "[Streaming] Normalized toggles | "
                    f"hybrid_search={hybrid_search_enabled} | "
                    f"web_search={web_search_enabled} | "
                    f"source_review={source_review_enabled} | "
                    f"chat_type={chat_type}"
                )

                def build_streaming_capability_usage():
                    source_review_was_used = _source_review_metadata_used(source_review_result)
                    return _build_capability_usage_metadata(
                        workspace_search_enabled=hybrid_search_enabled or history_grounded_search_used,
                        workspace_search_used=bool(search_results),
                        workspace_search_result_count=len(hybrid_citations_list or []),
                        document_action_type=DOCUMENT_ACTION_TYPE_NONE,
                        document_scope=effective_document_scope,
                        selected_document_ids=effective_selected_document_ids,
                        active_group_ids=effective_active_group_ids,
                        active_public_workspace_ids=effective_active_public_workspace_ids,
                        web_search_enabled=web_search_enabled,
                        web_search_used=bool(web_search_citations_list or deep_research_web_search_runs),
                        web_search_citation_count=len(web_search_citations_list or []),
                        web_search_run_count=len(deep_research_web_search_runs or []),
                        url_access_enabled=url_access_enabled,
                        source_review_enabled=source_review_enabled,
                        source_review_used=source_review_was_used,
                        deep_research_enabled=deep_research_enabled,
                        deep_research_used=bool(deep_research_enabled and (deep_research_result or deep_research_web_search_runs or source_review_was_used)),
                        deep_research_query_count=_deep_research_query_count(deep_research_query_plan, deep_research_web_search_runs),
                    )

                # Initialize GPT client (simplified version)
                gpt_model = ""
                gpt_client = None
                gpt_provider = None
                gpt_endpoint = None
                gpt_auth = None
                gpt_api_version = None
                gpt_endpoint_id = None
                gpt_model_id = None
                tabular_model_context = None
                enable_gpt_apim = settings.get('enable_gpt_apim', False)
                should_use_default_model = (
                    _has_chat_agent_selection(request_agent_info)
                    and settings.get('enable_multi_model_endpoints', False)
                    and not data.get('model_id')
                    and not data.get('model_endpoint_id')
                )

                try:
                    streaming_multi_endpoint_config = None
                    if settings.get('enable_multi_model_endpoints', False):
                        streaming_multi_endpoint_config = resolve_streaming_multi_endpoint_gpt_config(
                            settings,
                            data,
                            user_id,
                            active_group_ids=active_group_ids,
                            allow_default_selection=should_use_default_model,
                        )
                        if streaming_multi_endpoint_config and should_use_default_model and not frontend_model_endpoint_id:
                            debug_print("[GPTClient] Using default multi-endpoint model for agent streaming request.")

                    if streaming_multi_endpoint_config:
                        (
                            gpt_client,
                            gpt_model,
                            gpt_provider,
                            gpt_endpoint,
                            gpt_auth,
                            gpt_api_version,
                            gpt_endpoint_id,
                            gpt_model_id,
                        ) = streaming_multi_endpoint_config
                    elif enable_gpt_apim:
                        raw = settings.get('azure_apim_gpt_deployment', '')
                        if not raw:
                            yield f"data: {json.dumps({'error': 'APIM deployment not configured'})}\n\n"
                            return

                        apim_models = [m.strip() for m in raw.split(',') if m.strip()]
                        if not apim_models:
                            yield f"data: {json.dumps({'error': 'No valid APIM models configured'})}\n\n"
                            return

                        if frontend_gpt_model and frontend_gpt_model in apim_models:
                            gpt_model = frontend_gpt_model
                        else:
                            gpt_model = apim_models[0]

                        gpt_provider = 'aoai'
                        gpt_endpoint = settings.get('azure_apim_gpt_endpoint')
                        gpt_api_version = settings.get('azure_apim_gpt_api_version')

                        gpt_client = AzureOpenAI(
                            api_version=gpt_api_version,
                            azure_endpoint=gpt_endpoint,
                            api_key=settings.get('azure_apim_gpt_subscription_key')
                        )
                    else:
                        auth_type = settings.get('azure_openai_gpt_authentication_type')
                        endpoint = settings.get('azure_openai_gpt_endpoint')
                        api_version = settings.get('azure_openai_gpt_api_version')
                        gpt_model_obj = settings.get('gpt_model', {})

                        if gpt_model_obj and gpt_model_obj.get('selected'):
                            gpt_model = gpt_model_obj['selected'][0]['deploymentName']
                        else:
                            gpt_model = settings.get('azure_openai_gpt_deployment', 'gpt-4o')

                        if frontend_gpt_model:
                            gpt_model = frontend_gpt_model

                        gpt_provider = 'aoai'
                        gpt_endpoint = endpoint
                        gpt_api_version = api_version

                        if auth_type == 'managed_identity':
                            credential = DefaultAzureCredential()
                            token_provider = get_bearer_token_provider(
                                credential,
                                cognitive_services_scope
                            )
                            gpt_client = AzureOpenAI(
                                api_version=api_version,
                                azure_endpoint=endpoint,
                                azure_ad_token_provider=token_provider
                            )
                        else:
                            gpt_client = AzureOpenAI(
                                api_version=api_version,
                                azure_endpoint=endpoint,
                                api_key=settings.get('azure_openai_gpt_key')
                            )

                    if not gpt_client or not gpt_model:
                        yield f"data: {json.dumps({'error': 'Failed to initialize AI model'})}\n\n"
                        return

                    tabular_model_context = build_model_endpoint_context(
                        provider=gpt_provider,
                        endpoint=gpt_endpoint,
                        auth=gpt_auth,
                        api_version=gpt_api_version,
                        endpoint_id=gpt_endpoint_id or frontend_model_endpoint_id,
                        model_id=gpt_model_id or frontend_model_id,
                        model_deployment=gpt_model,
                        user_id=user_id,
                        active_group_ids=active_group_ids,
                    )

                    debug_print(
                        "[Streaming] Initialized model client | "
                        f"model={gpt_model} | provider={gpt_provider or 'legacy'} | "
                        f"endpoint_id={frontend_model_endpoint_id or ''} | api_version={gpt_api_version or ''} | "
                        f"enable_gpt_apim={enable_gpt_apim}"
                    )

                except Exception as e:
                    yield f"data: {json.dumps({'error': f'Model initialization failed: {str(e)}'})}\n\n"
                    return

                # Load or create conversation (simplified)
                if is_new_stream_conversation:
                    conversation_item = _create_personal_conversation(user_id, conversation_id=conversation_id)
                    debug_print(f"[Streaming] Created new conversation {conversation_id}")
                else:
                    try:
                        conversation_item = _authorize_personal_conversation_access(user_id, conversation_id)
                        debug_print(f"[Streaming] Loaded existing conversation {conversation_id}")
                    except LookupError:
                        yield f"data: {json.dumps({'error': 'Conversation not found'})}\n\n"
                        return
                    except PermissionError:
                        yield f"data: {json.dumps({'error': 'Forbidden'})}\n\n"
                        return

                auto_linked_chat_upload_document_ids = []
                chat_upload_context = _resolve_chat_upload_workspace_context(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    effective_document_scope=effective_document_scope,
                    effective_selected_document_ids=effective_selected_document_ids,
                    assigned_knowledge_filters=assigned_knowledge_filters,
                    assigned_knowledge_user_context_active=assigned_knowledge_user_context_active,
                    candidate_document_ids=data.get('conversation_task_document_ids'),
                )
                task_resolution = chat_upload_context.get('task_resolution') or {}
                if task_resolution.get('blocked') and task_resolution.get('linked_count'):
                    yield f"data: {json.dumps({'error': 'This agent does not allow uploaded task documents for search.'})}\n\n"
                    return
                if (
                    task_resolution.get('pending_count')
                    and not task_resolution.get('document_ids')
                    and not _has_nonpending_requested_task_document_selection(data, task_resolution)
                ):
                    yield f"data: {json.dumps(_build_chat_upload_pending_response_payload(task_resolution))}\n\n"
                    return

                effective_document_scope = chat_upload_context.get('effective_document_scope')
                effective_selected_document_ids = list(chat_upload_context.get('effective_selected_document_ids') or [])
                auto_linked_chat_upload_document_ids = list(
                    chat_upload_context.get('auto_linked_chat_upload_document_ids') or []
                )
                if auto_linked_chat_upload_document_ids:
                    auto_linked_assigned_knowledge_user_context = (
                        assigned_knowledge_filters
                        and assigned_knowledge_filters.get('has_workspace_knowledge')
                        and not assigned_knowledge_user_context_active
                    )
                    if auto_linked_assigned_knowledge_user_context:
                        assigned_knowledge_user_context_active = True
                        g.assigned_knowledge_user_context_active = True
                        tags_filter = []
                        debug_print(
                            "[ChatUploadWorkspaceContext] Enabled Assigned Knowledge user context "
                            f"from {len(auto_linked_chat_upload_document_ids)} linked chat upload workspace document(s)."
                        )
                    hybrid_search_enabled = True
                    original_hybrid_search_enabled = True
                    effective_selected_document_id = (
                        effective_selected_document_ids[0]
                        if len(effective_selected_document_ids) == 1
                        else None
                    )
                    selected_document_ids = list(effective_selected_document_ids)
                    selected_document_id = effective_selected_document_id
                    document_scope = effective_document_scope

                # Determine chat type
                actual_chat_type = 'personal_single_user'
                if conversation_item.get('chat_type'):
                    actual_chat_type = conversation_item['chat_type']
                    if actual_chat_type == 'personal':
                        actual_chat_type = 'personal_single_user'

                # Capture conversation-level group context for downstream agent/model resolution
                conversation_primary_context = next((ctx for ctx in conversation_item.get('context', []) if ctx.get('type') == 'primary'), None)
                conversation_group_id = None
                if conversation_primary_context and conversation_primary_context.get('scope') == 'group':
                    conversation_group_id = conversation_primary_context.get('id')
                if conversation_group_id:
                    g.conversation_group_id = conversation_group_id

                # Save user message
                user_message_id = f"{conversation_id}_user_{int(time.time())}_{random.randint(1000,9999)}"

                user_metadata = {}
                current_user = get_current_user_info()
                if current_user:
                    user_metadata['user_info'] = {
                        'user_id': current_user.get('userId'),
                        'username': current_user.get('userPrincipalName'),
                        'display_name': current_user.get('displayName'),
                        'email': current_user.get('email'),
                        'timestamp': datetime.utcnow().isoformat()
                    }

                user_metadata['button_states'] = {
                    'image_generation': False,
                    'document_search': hybrid_search_enabled,
                    'web_search': bool(web_search_enabled),
                    'url_access': bool(url_access_enabled),
                    'deep_research': bool(deep_research_enabled)
                }
                user_metadata['capability_usage'] = _build_capability_usage_metadata(
                    workspace_search_enabled=hybrid_search_enabled,
                    document_action_type=DOCUMENT_ACTION_TYPE_NONE,
                    document_scope=effective_document_scope,
                    selected_document_ids=effective_selected_document_ids,
                    active_group_ids=effective_active_group_ids,
                    active_public_workspace_ids=effective_active_public_workspace_ids,
                    web_search_enabled=web_search_enabled,
                    url_access_enabled=url_access_enabled,
                    source_review_enabled=source_review_enabled,
                    deep_research_enabled=deep_research_enabled,
                )

                # Document search scope and selections
                if hybrid_search_enabled:
                    user_metadata['workspace_search'] = {
                        'search_enabled': True,
                        'document_scope': effective_document_scope,
                        'selected_document_id': effective_selected_document_id,
                        'selected_document_ids': effective_selected_document_ids,
                        'active_group_ids': effective_active_group_ids,
                        'active_public_workspace_ids': effective_active_public_workspace_ids,
                        'classification': classifications_to_send
                    }
                    if assigned_knowledge_filters:
                        assigned_knowledge = assigned_knowledge_filters.get('assigned_knowledge') or {}
                        user_metadata['workspace_search']['assigned_knowledge'] = {
                            'enabled': True,
                            'document_count': len(assigned_knowledge.get('document_ids') or []),
                            'tag_count': len(assigned_knowledge.get('tags') or []),
                            'effective_scope': effective_document_scope,
                            'active_group_ids': effective_active_group_ids,
                            'active_public_workspace_ids': effective_active_public_workspace_ids,
                        }
                    if auto_linked_chat_upload_document_ids:
                        user_metadata['workspace_search']['auto_linked_chat_upload_document_ids'] = auto_linked_chat_upload_document_ids
                        user_metadata['workspace_search']['auto_linked_chat_upload_document_count'] = len(auto_linked_chat_upload_document_ids)

                    # Get document details if specific document selected
                    if effective_selected_document_id and effective_selected_document_id != "all":
                        try:
                            doc_info = _resolve_chat_selected_document_metadata(
                                effective_selected_document_id,
                                user_id=user_id,
                                document_scope=effective_document_scope,
                                active_group_id=effective_active_group_id,
                                active_group_ids=effective_active_group_ids,
                                active_public_workspace_id=effective_active_public_workspace_id,
                                active_public_workspace_ids=effective_active_public_workspace_ids,
                            )
                            if doc_info:
                                user_metadata['workspace_search']['document_name'] = doc_info.get('title') or doc_info.get('file_name')
                                user_metadata['workspace_search']['document_filename'] = doc_info.get('file_name')
                        except Exception as e:
                            debug_print(f"Error retrieving document details: {e}")

                    # Add scope-specific details
                    if effective_document_scope == 'group' and effective_active_group_id:
                        try:
                            from functions_debug import debug_print
                            debug_print(f"Workspace search - looking up group for id: {effective_active_group_id}")
                            group_doc = find_group_by_id(effective_active_group_id)
                            debug_print(f"Workspace search group lookup result: {group_doc}")

                            if group_doc and group_doc.get('name'):
                                group_name = group_doc.get('name')
                                user_metadata['workspace_search']['group_name'] = group_name
                                debug_print(f"Workspace search - set group_name to: {group_name}")
                            else:
                                debug_print(f"Workspace search - no group found or no name for id: {effective_active_group_id}")
                                user_metadata['workspace_search']['group_name'] = None

                        except Exception as e:
                            debug_print(f"Error retrieving group details: {e}")
                            user_metadata['workspace_search']['group_name'] = None
                            import traceback
                            traceback.print_exc()

                    if effective_document_scope == 'public' and effective_active_public_workspace_id:
                        # Check if public workspace status allows chat operations
                        try:
                            from functions_public_workspaces import find_public_workspace_by_id, check_public_workspace_status_allows_operation
                            workspace_doc = find_public_workspace_by_id(effective_active_public_workspace_id)
                            if workspace_doc:
                                allowed, reason = check_public_workspace_status_allows_operation(workspace_doc, 'chat')
                                if not allowed:
                                    yield f"data: {json.dumps({'error': reason})}\n\n"
                                    return
                        except Exception as e:
                            debug_print(f"Error checking public workspace status: {e}")

                        user_metadata['workspace_search']['active_public_workspace_id'] = effective_active_public_workspace_id
                else:
                    user_metadata['workspace_search'] = {
                        'search_enabled': False
                    }

                user_metadata['model_selection'] = {
                    'selected_model': gpt_model,
                    'frontend_requested_model': frontend_gpt_model,
                    'reasoning_effort': reasoning_effort if reasoning_effort and reasoning_effort != 'none' else None,
                    'streaming': 'Enabled'
                }

                agent_selection_metadata = _build_agent_selection_metadata(
                    request_agent_info,
                    assigned_knowledge_filters,
                )
                if agent_selection_metadata:
                    user_metadata['agent_selection'] = agent_selection_metadata

                user_metadata['chat_context'] = {
                    'conversation_id': conversation_id
                }

                # --- Threading Logic for Streaming ---
                previous_thread_id = None
                try:
                    last_msg_query = f"""
                        SELECT TOP 1 c.metadata.thread_info.thread_id as thread_id
                        FROM c
                        WHERE c.conversation_id = '{conversation_id}'
                        ORDER BY c.timestamp DESC
                    """
                    last_msgs = list(cosmos_messages_container.query_items(
                        query=last_msg_query,
                        partition_key=conversation_id
                    ))
                    if last_msgs:
                        previous_thread_id = last_msgs[0].get('thread_id')
                except Exception as e:
                    debug_print(f"Error fetching last message for threading: {e}")

                current_user_thread_id = str(uuid.uuid4())
                latest_thread_id = current_user_thread_id

                # Add thread information to user metadata
                user_metadata['thread_info'] = {
                    'thread_id': current_user_thread_id,
                    'previous_thread_id': previous_thread_id,
                    'active_thread': True,
                    'thread_attempt': 1
                }

                user_message_doc = {
                    'id': user_message_id,
                    'conversation_id': conversation_id,
                    'role': 'user',
                    'content': user_message,
                    'timestamp': datetime.utcnow().isoformat(),
                    'model_deployment_name': None,
                    'metadata': user_metadata
                }

                cosmos_messages_container.upsert_item(user_message_doc)
                debug_print(
                    f"[Streaming] Saved user message {user_message_id} | thread_id={current_user_thread_id} | previous_thread_id={previous_thread_id}"
                )

                # Log activity
                try:
                    log_chat_activity(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        message_type='user_message',
                        message_length=len(user_message) if user_message else 0,
                        has_document_search=hybrid_search_enabled,
                        has_image_generation=False,
                        document_scope=effective_document_scope,
                        chat_context=actual_chat_type,
                        workspace_type='group' if actual_chat_type == 'group' else 'public' if actual_chat_type == 'public' else 'personal',
                        group_id=effective_active_group_id if actual_chat_type == 'group' else None,
                        public_workspace_id=effective_active_public_workspace_id if actual_chat_type == 'public' else None,
                    )
                except Exception as e:
                    debug_print(f"Activity logging error: {e}")

                # Update conversation title
                title_updated = _set_initial_conversation_title(conversation_item, user_message)

                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                cosmos_conversations_container.upsert_item(conversation_item)
                if title_updated:
                    yield _build_conversation_metadata_stream_event(conversation_item)

                assistant_message_id, thought_tracker, assistant_thread_attempt, response_message_context = _initialize_assistant_response_tracking(
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    current_user_thread_id=current_user_thread_id,
                    previous_thread_id=previous_thread_id,
                    retry_thread_attempt=retry_thread_attempt,
                    is_retry=is_retry,
                    user_id=user_id,
                )
                user_info_for_assistant = response_message_context.get('user_info')
                user_thread_id = response_message_context.get('thread_id')
                user_previous_thread_id = response_message_context.get('previous_thread_id')

                def serialize_thought_event(step_type, content, step_index, message_id=None, detail=None, activity=None, progress=None):
                    payload = {
                        'type': 'thought',
                        'message_id': message_id or assistant_message_id,
                        'step_index': step_index,
                        'step_type': step_type,
                        'content': content,
                    }

                    if detail is not None:
                        payload['detail'] = detail
                    if isinstance(activity, dict) and activity:
                        payload['activity'] = activity
                    if isinstance(progress, dict) and progress:
                        payload['progress'] = progress

                    return f"data: {json.dumps(payload)}\n\n"

                def emit_thought(step_type, content, detail=None):
                    """Add a thought to Cosmos and return an SSE event string."""
                    thought_tracker.add_thought(step_type, content, detail)
                    return serialize_thought_event(step_type, content, thought_tracker.current_index - 1, detail=detail)

                def publish_live_plugin_thought(thought_payload):
                    if not callable(publish_background_event):
                        return

                    step_index = thought_payload.get('step_index')
                    if step_index is None:
                        return

                    publish_background_event(
                        serialize_thought_event(
                            thought_payload.get('step_type', 'agent_tool_call'),
                            thought_payload.get('content', ''),
                            step_index,
                            message_id=thought_payload.get('message_id') or assistant_message_id,
                            detail=thought_payload.get('detail'),
                            activity=thought_payload.get('activity'),
                            progress=thought_payload.get('progress'),
                        )
                    )

                def record_and_publish_streaming_thought(thought_payload):
                    thought_tracker.add_thought(
                        thought_payload.get('step_type', 'tabular_analysis'),
                        thought_payload.get('content', ''),
                        detail=thought_payload.get('detail'),
                        activity=thought_payload.get('activity'),
                    )

                    if not callable(publish_background_event):
                        return

                    publish_background_event(
                        serialize_thought_event(
                            thought_payload.get('step_type', 'tabular_analysis'),
                            thought_payload.get('content', ''),
                            thought_tracker.current_index - 1,
                            detail=thought_payload.get('detail'),
                            activity=thought_payload.get('activity'),
                            progress=thought_payload.get('progress'),
                        )
                    )

                # Content Safety check (matching non-streaming path)
                blocked = False
                if settings.get('enable_content_safety') and "content_safety_client" in CLIENTS:
                    yield emit_thought('content_safety', 'Checking content safety...')
                    try:
                        content_safety_client = CLIENTS["content_safety_client"]
                        request_obj = AnalyzeTextOptions(text=user_message)
                        cs_response = content_safety_client.analyze_text(request_obj)

                        max_severity = 0
                        triggered_categories = []
                        blocklist_matches = []
                        block_reasons = []

                        for cat_result in cs_response.categories_analysis:
                            triggered_categories.append({
                                "category": cat_result.category,
                                "severity": cat_result.severity
                            })
                            if cat_result.severity > max_severity:
                                max_severity = cat_result.severity

                        if cs_response.blocklists_match:
                            for match in cs_response.blocklists_match:
                                blocklist_matches.append({
                                    "blocklistName": match.blocklist_name,
                                    "blocklistItemId": match.blocklist_item_id,
                                    "blocklistItemText": match.blocklist_item_text
                                })

                        if max_severity >= 4:
                            blocked = True
                            block_reasons.append("Max severity >= 4")
                        if len(blocklist_matches) > 0:
                            blocked = True
                            block_reasons.append("Blocklist match")

                        if blocked:
                            # Upsert to safety container
                            safety_item = {
                                'id': str(uuid.uuid4()),
                                'user_id': user_id,
                                'conversation_id': conversation_id,
                                'message': user_message,
                                'triggered_categories': triggered_categories,
                                'blocklist_matches': blocklist_matches,
                                'timestamp': datetime.utcnow().isoformat(),
                                'reason': "; ".join(block_reasons),
                                'metadata': {
                                    'message_id': assistant_message_id,
                                    'thread_info': {
                                        'thread_id': response_message_context.get('thread_id'),
                                        'previous_thread_id': response_message_context.get('previous_thread_id'),
                                        'thread_attempt': assistant_thread_attempt,
                                    },
                                }
                            }
                            cosmos_safety_container.upsert_item(safety_item)

                            # Build blocked message
                            blocked_msg_content = (
                                "Your message was blocked by Content Safety.\n\n"
                                f"**Reason**: {', '.join(block_reasons)}\n"
                                "Triggered categories:\n"
                            )
                            for cat in triggered_categories:
                                blocked_msg_content += (
                                    f" - {cat['category']} (severity={cat['severity']})\n"
                                )
                            if blocklist_matches:
                                blocked_msg_content += (
                                    "\nBlocklist Matches:\n" +
                                    "\n".join([f" - {m['blocklistItemText']} (in {m['blocklistName']})"
                                            for m in blocklist_matches])
                                )

                            # Insert safety message
                            safety_doc = _build_safety_message_doc(
                                conversation_id=conversation_id,
                                message_id=assistant_message_id,
                                content=blocked_msg_content.strip(),
                                response_context=response_message_context,
                                thread_attempt=assistant_thread_attempt,
                            )
                            cosmos_messages_container.upsert_item(safety_doc)

                            conversation_item['last_updated'] = datetime.utcnow().isoformat()
                            cosmos_conversations_container.upsert_item(conversation_item)

                            final_data = make_json_serializable({
                                'content': blocked_msg_content.strip(),
                                'full_content': blocked_msg_content.strip(),
                                'blocked': True,
                                'role': 'safety',
                                'done': True,
                                'conversation_id': conversation_id,
                                'conversation_title': conversation_item.get('title'),
                                'message_id': assistant_message_id,
                                'user_message_id': user_message_id,
                                'augmented': False,
                                'hybrid_citations': [],
                                'web_search_citations': [],
                                'agent_citations': [],
                                'model_deployment_name': None,
                                'metadata': safety_doc.get('metadata', {}),
                                'thoughts_enabled': thought_tracker.enabled,
                            })
                            yield f"data: {json.dumps(final_data)}\n\n"
                            return

                    except HttpResponseError as e:
                        debug_print(f"[Content Safety Error - Streaming] {e}")
                    except Exception as ex:
                        debug_print(f"[Content Safety - Streaming] Unexpected error: {ex}")

                if not original_hybrid_search_enabled:
                    prior_grounded_document_refs = _normalize_prior_grounded_document_refs(conversation_item)
                    if prior_grounded_document_refs:
                        yield emit_thought(
                            'history_context',
                            'Checking whether prior conversation context already answers the question',
                            detail=f"grounded_documents={len(prior_grounded_document_refs)}"
                        )
                        try:
                            preflight_messages_query = (
                                "SELECT * FROM c WHERE c.conversation_id = @conv_id ORDER BY c.timestamp ASC"
                            )
                            preflight_messages_params = [{"name": "@conv_id", "value": conversation_id}]
                            preflight_messages = list(cosmos_messages_container.query_items(
                                query=preflight_messages_query,
                                parameters=preflight_messages_params,
                                partition_key=conversation_id,
                                enable_cross_partition_query=True,
                            ))
                            preflight_history_segments = build_conversation_history_segments(
                                all_messages=preflight_messages,
                                conversation_history_limit=conversation_history_limit,
                                enable_summarize_older_messages=enable_summarize_content_history_beyond_conversation_history_limit,
                                gpt_client=gpt_client,
                                gpt_model=gpt_model,
                                user_message_id=user_message_id,
                                fallback_user_message=user_message,
                            )
                            history_only_answerability = assess_history_only_answerability(
                                gpt_client,
                                gpt_model,
                                build_history_only_assessment_messages(
                                    preflight_history_segments,
                                    settings.get('default_system_prompt', '').strip(),
                                ),
                            )
                        except Exception as assessment_error:
                            debug_print(
                                f"[Streaming][History Fallback] History-only sufficiency assessment failed: {assessment_error}"
                            )

                        if history_only_answerability and history_only_answerability.get('can_answer_from_history'):
                            yield emit_thought(
                                'history_context',
                                'Prior conversation context appears sufficient without new document retrieval',
                                detail=history_only_answerability.get('reason') or None,
                            )
                        else:
                            fallback_search_parameters = build_prior_grounded_document_search_parameters(
                                prior_grounded_document_refs
                            )
                            fallback_search_parameters = revalidate_prior_grounded_document_search_parameters(
                                user_id,
                                fallback_search_parameters,
                            )
                            if fallback_search_parameters.get('document_ids') and fallback_search_parameters.get('doc_scope'):
                                history_grounded_search_used = True
                                effective_document_scope = fallback_search_parameters.get('doc_scope') or 'all'
                                effective_selected_document_ids = list(
                                    fallback_search_parameters.get('document_ids') or []
                                )
                                effective_selected_document_id = (
                                    effective_selected_document_ids[0]
                                    if len(effective_selected_document_ids) == 1
                                    else None
                                )
                                effective_active_group_ids = list(
                                    fallback_search_parameters.get('active_group_ids') or []
                                )
                                effective_active_group_id = fallback_search_parameters.get('active_group_id')
                                effective_active_public_workspace_ids = list(
                                    fallback_search_parameters.get('active_public_workspace_ids') or []
                                )
                                effective_active_public_workspace_id = fallback_search_parameters.get(
                                    'active_public_workspace_id'
                                )

                                rewritten_search_query = ''
                                if history_only_answerability:
                                    rewritten_search_query = str(
                                        history_only_answerability.get('search_query') or ''
                                    ).strip()
                                if rewritten_search_query:
                                    search_query = rewritten_search_query

                                fallback_detail_parts = [
                                    f"documents={len(effective_selected_document_ids)}",
                                    f"scope={effective_document_scope or 'all'}",
                                ]
                                if history_only_answerability and history_only_answerability.get('reason'):
                                    fallback_detail_parts.append(
                                        f"reason={history_only_answerability['reason']}"
                                    )
                                yield emit_thought(
                                    'search',
                                    'Conversation context alone was insufficient; searching previously grounded documents',
                                    detail=' | '.join(fallback_detail_parts),
                                )

                                user_metadata.setdefault('workspace_search', {})[
                                    'history_grounded_fallback'
                                ] = {
                                    'used': True,
                                    'document_scope': effective_document_scope,
                                    'document_count': len(effective_selected_document_ids),
                                    'search_query': search_query,
                                }
                                user_message_doc['metadata'] = user_metadata
                                cosmos_messages_container.upsert_item(user_message_doc)
                    else:
                        yield emit_thought(
                            'history_context',
                            'No prior grounded documents were available; using conversation history only'
                        )

                # Hybrid search (if enabled)
                combined_documents = []
                if hybrid_search_enabled or history_grounded_search_used:
                    debug_print(
                        "[Streaming] Starting hybrid search | "
                        f"conversation_id={conversation_id} | doc_scope={effective_document_scope} | "
                        f"selected_document_ids={len(effective_selected_document_ids)} | tags={len(tags_filter) if isinstance(tags_filter, list) else 0}"
                    )
                    if history_grounded_search_used and not hybrid_search_enabled:
                        yield emit_thought(
                            'search',
                            f"Searching {len(effective_selected_document_ids)} previously grounded document(s) for '{(search_query or user_message)[:50]}'"
                        )
                    else:
                        yield emit_thought(
                            'search',
                            f"Searching {effective_document_scope or 'personal'} workspace documents for '{(search_query or user_message)[:50]}'"
                        )
                    try:
                        search_args = {
                            "query": search_query,
                            "user_id": user_id,
                            "top_n": 12,
                            "doc_scope": effective_document_scope,
                        }

                        if effective_active_group_ids and (
                            effective_document_scope == 'group'
                            or effective_document_scope == 'all'
                            or chat_type == 'group'
                        ):
                            search_args['active_group_ids'] = effective_active_group_ids

                        # Add active_public_workspace_id(s) when:
                        # 1. Document scope is 'public' or
                        # 2. Document scope is 'all' and public workspaces are enabled
                        if effective_active_public_workspace_ids and (
                            effective_document_scope == 'public' or effective_document_scope == 'all'
                        ):
                            search_args['active_public_workspace_id'] = effective_active_public_workspace_ids
                        elif effective_active_public_workspace_id and (
                            effective_document_scope == 'public' or effective_document_scope == 'all'
                        ):
                            search_args['active_public_workspace_id'] = effective_active_public_workspace_id

                        if effective_selected_document_ids:
                            search_args['document_ids'] = effective_selected_document_ids
                        elif effective_selected_document_id:
                            search_args['document_id'] = effective_selected_document_id
                        if auto_linked_chat_upload_document_ids:
                            search_args['enable_file_sharing'] = False

                        # Add tags filter if provided
                        if tags_filter and isinstance(tags_filter, list) and len(tags_filter) > 0:
                            search_args['tags_filter'] = tags_filter

                        if assigned_knowledge_filters and assigned_knowledge_filters.get('has_workspace_knowledge'):
                            assigned_search_args = _build_assigned_knowledge_search_args(
                                assigned_knowledge_filters,
                                query=search_query,
                                user_id=user_id,
                                top_n=ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N,
                            )
                            assigned_search_results = hybrid_search(**assigned_search_args)
                            if assigned_knowledge_user_context_active:
                                user_context_search_results = hybrid_search(**search_args)
                                search_results = _merge_assigned_knowledge_user_context_search_results(
                                    assigned_search_results,
                                    user_context_search_results,
                                    top_n=ASSIGNED_KNOWLEDGE_CONTEXT_TOP_N,
                                    user_id=user_id,
                                )
                            else:
                                search_results = assigned_search_results
                        else:
                            search_results = hybrid_search(**search_args)
                        debug_print(
                            f"[Streaming] Hybrid search completed | results={len(search_results) if search_results else 0}"
                        )
                    except SemanticSearchQuotaExceededError as e:
                        debug_print(f"Semantic search quota exceeded during streaming hybrid search: {e}")
                        yield emit_thought(
                            'search',
                            'Workspace search warning: Semantic Ranker quota has been exceeded.',
                            detail=e.user_message,
                        )
                        yield f"data: {json.dumps({'error': e.user_message, 'warning_type': SEMANTIC_SEARCH_QUOTA_WARNING_TYPE, 'service_health_warning': True})}\n\n"
                        return
                    except Exception as e:
                        debug_print(f"Error during hybrid search: {e}")

                    if search_results:
                        unique_doc_names_stream = set(doc.get('file_name', 'Unknown') for doc in search_results)
                        yield emit_thought('search', f"Found {len(search_results)} results from {len(unique_doc_names_stream)} documents")
                        retrieved_texts = []

                        for doc in search_results:
                            chunk_text = doc.get('chunk_text', '')
                            file_name = doc.get('file_name', 'Unknown')
                            version = doc.get('version', 'N/A')
                            chunk_sequence = doc.get('chunk_sequence', 0)
                            page_number = doc.get('page_number') or chunk_sequence or 1
                            citation_id = doc.get('id', str(uuid.uuid4()))
                            document_id = str(doc.get('document_id') or '').strip()
                            if not document_id:
                                document_id = (
                                    '_'.join(str(citation_id).split('_')[:-1])
                                    if '_' in str(citation_id)
                                    else str(citation_id)
                                )
                            classification = doc.get('document_classification')
                            chunk_id = doc.get('chunk_id', str(uuid.uuid4()))
                            score = doc.get('score', 0.0)
                            group_id = doc.get('group_id', None)
                            doc_public_workspace_id = doc.get('public_workspace_id', None)
                            sheet_name = doc.get('sheet_name')
                            location_label, location_value = get_citation_location(
                                file_name,
                                page_number=page_number,
                                chunk_text=chunk_text,
                                sheet_name=sheet_name,
                            )

                            citation = f"(Source: {file_name}, {location_label}: {location_value}) [#{citation_id}]"
                            retrieved_texts.append(f"{chunk_text}\n{citation}")

                            combined_documents.append({
                                "file_name": file_name,
                                "document_id": document_id,
                                "citation_id": citation_id,
                                "page_number": page_number,
                                "sheet_name": sheet_name,
                                "location_label": location_label,
                                "location_value": location_value,
                                "version": version,
                                "classification": classification,
                                "chunk_text": chunk_text,
                                "chunk_sequence": chunk_sequence,
                                "chunk_id": chunk_id,
                                "score": score,
                                "group_id": group_id,
                                "public_workspace_id": doc_public_workspace_id,
                            })

                            # Build citation data to match non-streaming format
                            citation_data = {
                                "file_name": file_name,
                                "document_id": document_id,
                                "citation_id": citation_id,
                                "page_number": page_number,
                                "chunk_id": chunk_id,
                                "chunk_sequence": chunk_sequence,
                                "score": score,
                                "group_id": group_id,
                                "public_workspace_id": doc_public_workspace_id,
                                "version": version,
                                "classification": classification
                            }
                            hybrid_citations_list.append(citation_data)

                        # --- Extract metadata (keywords/abstract) for additional citations ---
                        if settings.get('enable_extract_meta_data', False):
                            from functions_documents import get_document_metadata_for_citations

                            processed_doc_ids = set()

                            for doc in search_results:
                                doc_id = str(doc.get('document_id') or '').strip()
                                if not doc_id and doc.get('id'):
                                    raw_doc_id = str(doc.get('id') or '').strip()
                                    doc_id = '_'.join(raw_doc_id.split('_')[:-1]) if '_' in raw_doc_id else raw_doc_id
                                if not doc_id or doc_id in processed_doc_ids:
                                    continue

                                processed_doc_ids.add(doc_id)

                                file_name = doc.get('file_name', 'Unknown')
                                doc_group_id = doc.get('group_id', None)

                                # Map document_scope to correct parameter names for the function
                                metadata_params = {'user_id': user_id}
                                if effective_document_scope == 'group':
                                    metadata_params['group_id'] = effective_active_group_id
                                elif effective_document_scope == 'public':
                                    metadata_params['public_workspace_id'] = effective_active_public_workspace_id

                                metadata = get_document_metadata_for_citations(
                                    doc_id,
                                    **metadata_params
                                )

                                if metadata:
                                    keywords = metadata.get('keywords', [])
                                    abstract = metadata.get('abstract', '')

                                    if keywords and len(keywords) > 0:
                                        keywords_citation_id = f"{doc_id}_keywords"
                                        keywords_text = ', '.join(keywords) if isinstance(keywords, list) else str(keywords)

                                        keywords_citation = {
                                            "file_name": file_name,
                                            "document_id": doc_id,
                                            "citation_id": keywords_citation_id,
                                            "page_number": "Metadata",
                                            "chunk_id": keywords_citation_id,
                                            "chunk_sequence": 9999,
                                            "score": 0.0,
                                            "group_id": doc_group_id,
                                            "version": doc.get('version', 'N/A'),
                                            "classification": doc.get('document_classification'),
                                            "metadata_type": "keywords",
                                            "metadata_content": keywords_text
                                        }
                                        hybrid_citations_list.append(keywords_citation)
                                        combined_documents.append(keywords_citation)

                                        keywords_context = f"Document Keywords ({file_name}): {keywords_text}"
                                        retrieved_texts.append(keywords_context)

                                    if abstract and len(abstract.strip()) > 0:
                                        abstract_citation_id = f"{doc_id}_abstract"

                                        abstract_citation = {
                                            "file_name": file_name,
                                            "document_id": doc_id,
                                            "citation_id": abstract_citation_id,
                                            "page_number": "Metadata",
                                            "chunk_id": abstract_citation_id,
                                            "chunk_sequence": 9998,
                                            "score": 0.0,
                                            "group_id": doc_group_id,
                                            "version": doc.get('version', 'N/A'),
                                            "classification": doc.get('document_classification'),
                                            "metadata_type": "abstract",
                                            "metadata_content": abstract
                                        }
                                        hybrid_citations_list.append(abstract_citation)
                                        combined_documents.append(abstract_citation)

                                        abstract_context = f"Document Abstract ({file_name}): {abstract}"
                                        retrieved_texts.append(abstract_context)

                                    vision_analysis = metadata.get('vision_analysis')
                                    if vision_analysis:
                                        vision_citation_id = f"{doc_id}_vision"

                                        vision_description = vision_analysis.get('description', '')
                                        vision_objects = vision_analysis.get('objects', [])
                                        vision_text = vision_analysis.get('text', '')

                                        vision_content = f"AI Vision Analysis:\n"
                                        if vision_description:
                                            vision_content += f"Description: {vision_description}\n"
                                        if vision_objects:
                                            vision_content += f"Objects: {', '.join(vision_objects)}\n"
                                        if vision_text:
                                            vision_content += f"Text in Image: {vision_text}\n"

                                        vision_citation = {
                                            "file_name": file_name,
                                            "document_id": doc_id,
                                            "citation_id": vision_citation_id,
                                            "page_number": "AI Vision",
                                            "chunk_id": vision_citation_id,
                                            "chunk_sequence": 9997,
                                            "score": 0.0,
                                            "group_id": doc_group_id,
                                            "version": doc.get('version', 'N/A'),
                                            "classification": doc.get('document_classification'),
                                            "metadata_type": "vision",
                                            "metadata_content": vision_content
                                        }
                                        hybrid_citations_list.append(vision_citation)
                                        combined_documents.append(vision_citation)

                                        vision_context = f"AI Vision Analysis ({file_name}): {vision_content}"
                                        retrieved_texts.append(vision_context)

                        retrieved_content = "\n\n".join(retrieved_texts)
                        system_prompt_search = build_search_augmentation_system_prompt(retrieved_content)

                        system_messages_for_augmentation.append({
                            'role': 'system',
                            'content': system_prompt_search,
                            'documents': combined_documents
                        })

                        hybrid_citations_list.sort(key=_build_hybrid_citation_sort_key, reverse=True)
                    elif history_grounded_search_used:
                        yield emit_thought(
                            'search',
                            'No matching excerpts were found in the previously grounded documents'
                        )

                if (
                    assigned_knowledge_filters
                    and assigned_knowledge_filters.get('has_workspace_knowledge')
                    and _is_assigned_knowledge_inventory_request(user_message)
                ):
                    inventory_message = _build_assigned_knowledge_inventory_aug_message(
                        user_id,
                        assigned_knowledge_filters,
                        user_message,
                    )
                    system_messages_for_augmentation.append(inventory_message)
                    inventory_meta = inventory_message.get('assigned_knowledge_inventory') or {}
                    yield emit_thought(
                        'search',
                        f"Prepared assigned knowledge inventory with {inventory_meta.get('active_document_count', 0)} active documents",
                        detail=f"web_sources={inventory_meta.get('web_source_count', 0)}",
                    )

                workspace_tabular_file_contexts = []
                workspace_tabular_files = set()
                if (hybrid_search_enabled or history_grounded_search_used) and is_tabular_processing_enabled(settings):
                    workspace_tabular_file_contexts = collect_workspace_tabular_file_contexts(
                        combined_documents=combined_documents,
                        selected_document_ids=effective_selected_document_ids,
                        selected_document_id=effective_selected_document_id,
                        document_scope=effective_document_scope,
                        user_id=user_id,
                        active_group_id=effective_active_group_id,
                        active_group_ids=effective_active_group_ids,
                        active_public_workspace_id=effective_active_public_workspace_id,
                        active_public_workspace_ids=effective_active_public_workspace_ids,
                    )
                    workspace_tabular_files = {
                        file_context['file_name'] for file_context in workspace_tabular_file_contexts
                    }

                if (hybrid_search_enabled or history_grounded_search_used) and workspace_tabular_files and is_tabular_processing_enabled(settings):
                    tabular_source_hint = determine_tabular_source_hint(
                        effective_document_scope,
                        active_group_id=effective_active_group_id,
                        active_public_workspace_id=effective_active_public_workspace_id,
                    )
                    tabular_execution_mode = get_tabular_execution_mode(user_message)
                    tabular_filenames_str = ", ".join(sorted(workspace_tabular_files))
                    plugin_logger = get_plugin_logger()
                    baseline_tabular_invocation_count = len(
                        plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
                    )
                    debug_print(
                        "[Streaming][Tabular SK] Starting workspace tabular analysis | "
                        f"files={sorted(workspace_tabular_files)} | source_hint={tabular_source_hint} | "
                        f"file_contexts={workspace_tabular_file_contexts} | "
                        f"execution_mode={tabular_execution_mode} | baseline_invocations={baseline_tabular_invocation_count}"
                    )

                    yield emit_thought(
                        'tabular_analysis',
                        f"Starting tabular analysis across {len(workspace_tabular_files)} file(s)",
                        detail=f"files={tabular_filenames_str}; mode={tabular_execution_mode}"
                    )

                    tabular_analysis, streamed_tabular_tool_thoughts = asyncio.run(run_tabular_analysis_with_thought_tracking(
                        user_question=user_message,
                        tabular_filenames=workspace_tabular_files,
                        tabular_file_contexts=workspace_tabular_file_contexts,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        gpt_model=gpt_model,
                        settings=settings,
                        source_hint=tabular_source_hint,
                        group_id=effective_active_group_id if tabular_source_hint == 'group' else None,
                        public_workspace_id=effective_active_public_workspace_id if tabular_source_hint == 'public' else None,
                        execution_mode=tabular_execution_mode,
                        thought_tracker=thought_tracker,
                        live_thought_callback=publish_live_plugin_thought,
                        model_context=tabular_model_context,
                    ))
                    tabular_invocations = get_new_plugin_invocations(
                        plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000),
                        baseline_tabular_invocation_count
                    )
                    tabular_related_document_summary = ''
                    tabular_related_document_stats = augment_tabular_invocations_with_related_document_evidence(
                        tabular_invocations,
                        user_message,
                        user_id,
                        conversation_id=conversation_id,
                    )
                    if tabular_related_document_stats.get('augmented_row_count'):
                        tabular_related_document_summary = build_tabular_related_document_evidence_summary(
                            tabular_invocations,
                        )
                    debug_print(
                        "[Streaming][Tabular SK] Completed workspace tabular analysis | "
                        f"analysis_returned={bool(tabular_analysis)} | new_invocations={len(tabular_invocations)}"
                    )
                    if not streamed_tabular_tool_thoughts:
                        tabular_thought_payloads = get_tabular_tool_thought_payloads(tabular_invocations)
                        for thought_content, thought_detail in tabular_thought_payloads:
                            yield emit_thought('tabular_analysis', thought_content, thought_detail)
                    tabular_status_thought_payloads = get_tabular_status_thought_payloads(
                        tabular_invocations,
                        analysis_succeeded=bool(tabular_analysis),
                    )
                    for thought_content, thought_detail in tabular_status_thought_payloads:
                        yield emit_thought('tabular_analysis', thought_content, thought_detail)

                    tabular_generated_output = asyncio.run(maybe_create_tabular_generated_output(
                        user_question=user_message,
                        invocations=tabular_invocations,
                        gpt_model=gpt_model,
                        settings=settings,
                        conversation_id=conversation_id,
                        thought_callback=record_and_publish_streaming_thought,
                        user_id=user_id,
                        model_context=tabular_model_context,
                    ))
                    if tabular_generated_output:
                        generated_tabular_outputs_list.append(tabular_generated_output)
                        generated_analysis_artifacts_list.append(tabular_generated_output)

                    if tabular_analysis:
                        system_messages_for_augmentation.append({
                            'role': 'system',
                            'content': build_tabular_computed_results_system_message(
                                f"the file(s) {tabular_filenames_str}",
                                tabular_analysis,
                                related_document_evidence_summary=tabular_related_document_summary,
                            )
                        })
                        if tabular_generated_output:
                            system_messages_for_augmentation.append({
                                'role': 'system',
                                'content': _build_tabular_generated_output_system_message(tabular_generated_output)
                            })
                            _log_tabular_generated_output_handoff(
                                conversation_id,
                                user_message,
                                tabular_generated_output,
                                'streaming_workspace_search_augmentation',
                            )

                        tabular_sk_citations = collect_tabular_sk_citations(user_id, conversation_id)
                        if tabular_sk_citations:
                            agent_citations_list.extend(tabular_sk_citations)
                        tabular_chart_citations = build_tabular_inline_chart_citations(user_message, tabular_invocations)
                        if tabular_chart_citations:
                            agent_citations_list.extend(tabular_chart_citations)
                            yield emit_thought(
                                'tabular_analysis',
                                f"Prepared {len(tabular_chart_citations)} inline chart{'s' if len(tabular_chart_citations) != 1 else ''} from tabular results",
                            )
                    else:
                        system_messages_for_augmentation.append({
                            'role': 'system',
                            'content': build_tabular_fallback_system_message(
                                tabular_filenames_str,
                                execution_mode=tabular_execution_mode,
                            )
                        })
                        if tabular_generated_output:
                            system_messages_for_augmentation.append({
                                'role': 'system',
                                'content': _build_tabular_generated_output_system_message(tabular_generated_output)
                            })
                            _log_tabular_generated_output_handoff(
                                conversation_id,
                                user_message,
                                tabular_generated_output,
                                'streaming_workspace_search_fallback',
                            )

                        yield emit_thought(
                            'tabular_analysis',
                            "Tabular analysis could not compute results; using schema context instead",
                            detail=f"files={tabular_filenames_str}"
                        )

                if web_search_enabled:
                    debug_print(
                        f"[Streaming] Starting web search augmentation for conversation_id={conversation_id}"
                    )
                    if deep_research_enabled:
                        yield emit_thought('deep_research', "Planning Deep Research web searches")
                    else:
                        yield emit_thought('web_search', f"Searching the web for '{web_search_query_text[:50]}'")
                    research_search_result = perform_research_web_searches(
                        settings=settings,
                        conversation_id=conversation_id,
                        user_id=user_id,
                        user_message=user_message,
                        user_message_id=user_message_id,
                        chat_type=chat_type,
                        document_scope=document_scope,
                        active_group_id=active_group_id,
                        active_public_workspace_id=active_public_workspace_id,
                        web_search_query_text=web_search_query_text,
                        system_messages_for_augmentation=system_messages_for_augmentation,
                        agent_citations_list=agent_citations_list,
                        web_search_citations_list=web_search_citations_list,
                        deep_research_enabled=deep_research_enabled,
                        deep_research_planner_client=gpt_client,
                        deep_research_planner_model=gpt_model,
                    )
                    deep_research_query_plan = research_search_result.get('query_plan', {})
                    deep_research_web_search_runs = research_search_result.get('web_search_runs', [])
                    if web_search_citations_list:
                        debug_print(
                            f"[Streaming] Web search completed | citations={len(web_search_citations_list)}"
                        )
                        if deep_research_enabled:
                            planned_count = len(deep_research_query_plan.get('queries') or []) or 1
                            query_label = 'queries' if planned_count != 1 else 'query'
                            yield emit_thought(
                                'deep_research',
                                f"Ran {planned_count} Deep Research web search {query_label}",
                                detail=f"discovered_urls={len(web_search_citations_list)}"
                            )
                        else:
                            yield emit_thought('web_search', f"Got {len(web_search_citations_list)} web search results")

                if source_review_enabled:
                    debug_print(
                        f"[Streaming] Starting Source Review for conversation_id={conversation_id}"
                    )
                    source_review_thought_label = 'deep_research' if deep_research_enabled else 'url_access'
                    source_review_start_text = (
                        "Reviewing source pages for supporting evidence"
                        if deep_research_enabled
                        else "Reviewing pasted URLs"
                    )
                    yield emit_thought(source_review_thought_label, source_review_start_text)
                    source_review_result = perform_source_review(
                        settings=settings,
                        user_id=user_id,
                        user_email=current_user_email,
                        user_roles=current_user_roles,
                        user_message=user_message,
                        web_search_citations=web_search_citations_list if deep_research_enabled else [],
                        conversation_id=conversation_id,
                        source_review_planner_client=gpt_client,
                        source_review_planner_model=gpt_model,
                        url_access_only=not deep_research_enabled,
                        url_access_context=URL_ACCESS_CONTEXT_CHAT,
                        include_direct_user_urls=bool(url_access_enabled),
                        additional_seed_urls=(
                            assigned_knowledge_url_review_urls
                            + assigned_knowledge_deep_research_urls
                        ),
                    )
                    source_review_message = source_review_result.get('system_message') if isinstance(source_review_result, dict) else None
                    if source_review_message:
                        system_messages_for_augmentation.append(source_review_message)
                        existing_source_urls = {
                            citation.get('url')
                            for citation in web_search_citations_list
                            if isinstance(citation, dict) and citation.get('url')
                        }
                        for citation in source_review_result.get('citations', []):
                            citation_url = citation.get('url') if isinstance(citation, dict) else None
                            if citation_url and citation_url not in existing_source_urls:
                                web_search_citations_list.append(citation)
                                existing_source_urls.add(citation_url)
                        coverage = source_review_result.get('coverage', {})
                        planner_status = 'deterministic'
                        if coverage.get('llm_planning_used'):
                            planner_status = 'used'
                        elif coverage.get('llm_planning_attempted'):
                            planner_status = 'attempted'
                        yield emit_thought(
                            source_review_thought_label,
                            f"Reviewed {coverage.get('pages_reviewed', 0)} URL source pages",
                            detail=(
                                f"seed={coverage.get('seed_pages_reviewed', 0)}, "
                                f"child={coverage.get('child_pages_reviewed', 0)}, "
                                f"planner={planner_status}, "
                                f"load_more={coverage.get('load_more_clicks_succeeded', 0)}, "
                                f"skipped={coverage.get('pages_skipped', 0)}"
                            )
                        )
                    else:
                        yield emit_thought(
                            source_review_thought_label,
                            "Deep Research did not add page evidence" if deep_research_enabled else "URL Access did not add page evidence",
                            detail=source_review_result.get('skipped_reason') if isinstance(source_review_result, dict) else None
                        )

                    if deep_research_enabled:
                        deep_research_ledger = build_deep_research_ledger(
                            settings=settings,
                            user_message=user_message,
                            query_plan=deep_research_query_plan,
                            web_search_runs=deep_research_web_search_runs,
                            web_search_citations=web_search_citations_list,
                            source_review_result=source_review_result,
                        )
                        deep_research_artifact = _maybe_create_deep_research_ledger_artifact(
                            settings,
                            conversation_id,
                            deep_research_ledger,
                        )
                        if deep_research_artifact:
                            deep_research_ledger['ledger_artifact'] = deep_research_artifact
                            generated_analysis_artifacts_list.append(deep_research_artifact)
                        deep_research_result = compact_deep_research_result_for_metadata(deep_research_ledger)

                # Update message chat type
                message_chat_type = None
                if (hybrid_search_enabled or history_grounded_search_used) and search_results and len(search_results) > 0:
                    if effective_document_scope == 'group':
                        message_chat_type = 'group'
                    elif effective_document_scope == 'public':
                        message_chat_type = 'public'
                    else:
                        message_chat_type = 'personal_single_user'
                else:
                    message_chat_type = 'Model'

                source_review_used = _source_review_metadata_used(source_review_result)
                user_metadata['capability_usage'] = _build_capability_usage_metadata(
                    workspace_search_enabled=hybrid_search_enabled or history_grounded_search_used,
                    workspace_search_used=bool(search_results),
                    workspace_search_result_count=len(search_results or []),
                    document_action_type=DOCUMENT_ACTION_TYPE_NONE,
                    document_scope=effective_document_scope,
                    selected_document_ids=effective_selected_document_ids,
                    active_group_ids=effective_active_group_ids,
                    active_public_workspace_ids=effective_active_public_workspace_ids,
                    web_search_enabled=web_search_enabled,
                    web_search_used=bool(web_search_citations_list or deep_research_web_search_runs),
                    web_search_citation_count=len(web_search_citations_list or []),
                    web_search_run_count=len(deep_research_web_search_runs or []),
                    url_access_enabled=url_access_enabled,
                    source_review_enabled=source_review_enabled,
                    source_review_used=source_review_used,
                    deep_research_enabled=deep_research_enabled,
                    deep_research_used=bool(deep_research_enabled and (deep_research_result or deep_research_web_search_runs or source_review_used)),
                    deep_research_query_count=_deep_research_query_count(deep_research_query_plan, deep_research_web_search_runs),
                )
                user_metadata['chat_context']['chat_type'] = message_chat_type
                user_message_doc['metadata'] = user_metadata
                cosmos_messages_container.upsert_item(user_message_doc)

                # Prepare conversation history
                conversation_history_for_api = []
                history_debug_info = {}
                final_api_source_refs = []

                try:
                    all_messages_query = "SELECT * FROM c WHERE c.conversation_id = @conv_id ORDER BY c.timestamp ASC"
                    params_all = [{"name": "@conv_id", "value": conversation_id}]
                    all_messages = list(cosmos_messages_container.query_items(
                        query=all_messages_query, parameters=params_all,
                        partition_key=conversation_id, enable_cross_partition_query=True
                    ))
                    history_segments = build_conversation_history_segments(
                        all_messages=all_messages,
                        conversation_history_limit=conversation_history_limit,
                        enable_summarize_older_messages=enable_summarize_content_history_beyond_conversation_history_limit,
                        gpt_client=gpt_client,
                        gpt_model=gpt_model,
                        user_message_id=user_message_id,
                        fallback_user_message=user_message,
                    )
                    summary_of_older = history_segments['summary_of_older']
                    chat_tabular_files = history_segments['chat_tabular_files']
                    history_debug_info = history_segments.get('debug_info', {})

                    if summary_of_older:
                        conversation_history_for_api.append({
                            'role': 'system',
                            'content': (
                                f"<Summary of previous conversation context>\n{summary_of_older}\n"
                                "</Summary of previous conversation context>"
                            )
                        })
                        final_api_source_refs.append('system:summary_of_older')

                    # Add augmentation messages
                    for aug_msg in system_messages_for_augmentation:
                        conversation_history_for_api.append({
                            'role': aug_msg['role'],
                            'content': aug_msg['content']
                        })
                        final_api_source_refs.append(f"system:augmentation:{len(final_api_source_refs) + 1}")
                    conversation_history_for_api.extend(history_segments['history_messages'])
                    final_api_source_refs.extend(history_debug_info.get('history_message_source_refs', []))

                    # --- Mini SK analysis for tabular files uploaded directly to chat ---
                    if chat_tabular_files and is_tabular_processing_enabled(settings):
                        chat_tabular_filenames_str = ", ".join(chat_tabular_files)
                        chat_tabular_execution_mode = get_tabular_execution_mode(user_message)
                        log_event(
                            f"[Chat Tabular SK] Streaming: Detected {len(chat_tabular_files)} tabular file(s) uploaded to chat: {chat_tabular_filenames_str}",
                            level=logging.INFO
                        )
                        plugin_logger = get_plugin_logger()
                        baseline_tabular_invocation_count = len(
                            plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
                        )
                        debug_print(
                            "[Streaming][Chat Tabular SK] Starting chat-uploaded tabular analysis | "
                            f"files={sorted(chat_tabular_files)} | execution_mode={chat_tabular_execution_mode} | "
                            f"baseline_invocations={baseline_tabular_invocation_count}"
                        )

                        yield emit_thought(
                            'tabular_analysis',
                            f"Starting tabular analysis across {len(chat_tabular_files)} chat-uploaded file(s)",
                            detail=f"files={chat_tabular_filenames_str}; mode={chat_tabular_execution_mode}"
                        )

                        chat_tabular_analysis, streamed_chat_tabular_tool_thoughts = asyncio.run(run_tabular_analysis_with_thought_tracking(
                            user_question=user_message,
                            tabular_filenames=chat_tabular_files,
                            user_id=user_id,
                            conversation_id=conversation_id,
                            gpt_model=gpt_model,
                            settings=settings,
                            source_hint="chat",
                            execution_mode=chat_tabular_execution_mode,
                            thought_tracker=thought_tracker,
                            live_thought_callback=publish_live_plugin_thought,
                            model_context=tabular_model_context,
                        ))
                        chat_tabular_invocations = get_new_plugin_invocations(
                            plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000),
                            baseline_tabular_invocation_count
                        )
                        chat_tabular_related_document_summary = ''
                        chat_tabular_related_document_stats = augment_tabular_invocations_with_related_document_evidence(
                            chat_tabular_invocations,
                            user_message,
                            user_id,
                            conversation_id=conversation_id,
                        )
                        if chat_tabular_related_document_stats.get('augmented_row_count'):
                            chat_tabular_related_document_summary = build_tabular_related_document_evidence_summary(
                                chat_tabular_invocations,
                            )
                        debug_print(
                            "[Streaming][Chat Tabular SK] Completed chat-uploaded tabular analysis | "
                            f"analysis_returned={bool(chat_tabular_analysis)} | new_invocations={len(chat_tabular_invocations)}"
                        )
                        if not streamed_chat_tabular_tool_thoughts:
                            chat_tabular_thought_payloads = get_tabular_tool_thought_payloads(chat_tabular_invocations)
                            for thought_content, thought_detail in chat_tabular_thought_payloads:
                                yield emit_thought('tabular_analysis', thought_content, thought_detail)
                        chat_tabular_status_thought_payloads = get_tabular_status_thought_payloads(
                            chat_tabular_invocations,
                            analysis_succeeded=bool(chat_tabular_analysis),
                        )
                        for thought_content, thought_detail in chat_tabular_status_thought_payloads:
                            yield emit_thought('tabular_analysis', thought_content, thought_detail)

                        chat_tabular_generated_output = asyncio.run(maybe_create_tabular_generated_output(
                            user_question=user_message,
                            invocations=chat_tabular_invocations,
                            gpt_model=gpt_model,
                            settings=settings,
                            conversation_id=conversation_id,
                            thought_callback=record_and_publish_streaming_thought,
                            user_id=user_id,
                            model_context=tabular_model_context,
                        ))
                        if chat_tabular_generated_output:
                            generated_tabular_outputs_list.append(chat_tabular_generated_output)
                            generated_analysis_artifacts_list.append(chat_tabular_generated_output)

                        if chat_tabular_analysis:
                            conversation_history_for_api.append({
                                'role': 'system',
                                'content': build_tabular_computed_results_system_message(
                                    f"the chat-uploaded file(s) {chat_tabular_filenames_str}",
                                    chat_tabular_analysis,
                                    related_document_evidence_summary=chat_tabular_related_document_summary,
                                )
                            })
                            final_api_source_refs.append('system:tabular_results')
                            if chat_tabular_generated_output:
                                conversation_history_for_api.append({
                                    'role': 'system',
                                    'content': _build_tabular_generated_output_system_message(chat_tabular_generated_output)
                                })
                                final_api_source_refs.append('system:tabular_generated_output')
                                _log_tabular_generated_output_handoff(
                                    conversation_id,
                                    user_message,
                                    chat_tabular_generated_output,
                                    'streaming_chat_upload_history',
                                )

                            # Collect tool execution citations
                            chat_tabular_sk_citations = collect_tabular_sk_citations(user_id, conversation_id)
                            if chat_tabular_sk_citations:
                                agent_citations_list.extend(chat_tabular_sk_citations)
                            chat_tabular_chart_citations = build_tabular_inline_chart_citations(user_message, chat_tabular_invocations)
                            if chat_tabular_chart_citations:
                                agent_citations_list.extend(chat_tabular_chart_citations)
                                yield emit_thought(
                                    'tabular_analysis',
                                    f"Prepared {len(chat_tabular_chart_citations)} inline chart{'s' if len(chat_tabular_chart_citations) != 1 else ''} from chat-uploaded tabular results",
                                )

                            debug_print(f"[Chat Tabular SK] Streaming: Analysis injected, {len(chat_tabular_analysis)} chars")
                        else:
                            if chat_tabular_generated_output:
                                conversation_history_for_api.append({
                                    'role': 'system',
                                    'content': _build_tabular_generated_output_system_message(chat_tabular_generated_output)
                                })
                                final_api_source_refs.append('system:tabular_generated_output')
                                _log_tabular_generated_output_handoff(
                                    conversation_id,
                                    user_message,
                                    chat_tabular_generated_output,
                                    'streaming_chat_upload_history_fallback',
                                )
                            yield emit_thought(
                                'tabular_analysis',
                                "Tabular analysis could not compute results; using existing chat file context",
                                detail=f"files={chat_tabular_filenames_str}"
                            )
                            debug_print("[Chat Tabular SK] Streaming: Analysis returned None, relying on existing file context")

                except Exception as e:
                    yield f"data: {json.dumps({'error': f'History error: {str(e)}'})}\n\n"
                    return

                # Add system prompt
                default_system_prompt = settings.get('default_system_prompt', '').strip()
                default_system_prompt_inserted = False
                if default_system_prompt:
                    has_general_system_prompt = any(
                        msg.get('role') == 'system' and not (
                            msg.get('content', '').startswith('<Summary of previous conversation context>') or
                            "retrieved document excerpts" in msg.get('content', '')
                        )
                        for msg in conversation_history_for_api
                    )
                    if not has_general_system_prompt:
                        insert_idx = 0
                        if (
                            conversation_history_for_api
                            and conversation_history_for_api[0].get('role') == 'system'
                            and conversation_history_for_api[0].get('content', '').startswith(
                                '<Summary of previous conversation context>'
                            )
                        ):
                            insert_idx = 1
                        conversation_history_for_api.insert(insert_idx, {
                            'role': 'system',
                            'content': default_system_prompt
                        })
                        final_api_source_refs.insert(insert_idx, 'system:default_prompt')
                        default_system_prompt_inserted = True

                if should_apply_history_grounding_message(
                    original_hybrid_search_enabled,
                    prior_grounded_document_refs,
                ):
                    history_grounding_message = build_history_grounding_system_message()
                    insert_idx = 0
                    if (
                        conversation_history_for_api
                        and conversation_history_for_api[0].get('role') == 'system'
                        and conversation_history_for_api[0].get('content', '').startswith(
                            '<Summary of previous conversation context>'
                        )
                    ):
                        insert_idx = 1
                    if default_system_prompt_inserted:
                        insert_idx += 1
                    conversation_history_for_api.insert(insert_idx, history_grounding_message)
                    final_api_source_refs.insert(insert_idx, 'system:history_grounding')

                history_debug_info = enrich_history_context_debug_info(
                    history_debug_info,
                    conversation_history_for_api,
                    final_api_source_refs,
                    path_label='streaming',
                    augmentation_message_count=len(system_messages_for_augmentation),
                    default_system_prompt_inserted=default_system_prompt_inserted,
                )
                emit_history_context_debug(history_debug_info, conversation_id)
                yield emit_thought(
                    'history_context',
                    build_history_context_thought_content(history_debug_info),
                    build_history_context_thought_detail(history_debug_info),
                )
                if settings.get('enable_debug_logging', False):
                    agent_citations_list.append(
                        build_history_context_debug_citation(history_debug_info, 'streaming')
                    )

                fact_memory_enabled = bool(settings.get('enable_fact_memory_plugin', False))
                fact_memory_payload = inject_fact_memory_context(
                    conversation_history=conversation_history_for_api,
                    scope_id=scope_id,
                    scope_type=scope_type,
                    query_text=user_message,
                    conversation_id=conversation_id,
                    agent_id=None,
                    enabled=fact_memory_enabled,
                    include_metadata=bool(enable_semantic_kernel and user_enable_agents),
                )
                for thought in fact_memory_payload.get('thoughts', []):
                    yield emit_thought(
                        thought.get('step_type') or 'fact_memory',
                        thought.get('content'),
                        thought.get('detail'),
                    )
                for citation in fact_memory_payload.get('citations', []):
                    agent_citations_list.append(citation)

                # Check if agents are enabled and should be used
                selected_agent = None
                selected_agent_metadata = None
                agent_name_used = None
                agent_display_name_used = None
                agent_icon_used = None
                agent_tags_used = []
                use_agent_streaming = False

                if enable_semantic_kernel and user_enable_agents:
                    # Agent selection logic (similar to non-streaming)
                    kernel = get_kernel()
                    all_agents = get_kernel_agents()

                    if all_agents:
                        agent_name_to_select = _get_chat_agent_selection_name(request_agent_info)
                        if agent_name_to_select:
                            selected_agent_metadata = _build_agent_selection_metadata(
                                request_agent_info,
                                assigned_knowledge_filters,
                            )
                            debug_print(f"[Streaming] Request agent name to select: {agent_name_to_select}")
                        else:
                            debug_print("[Streaming] No explicit request agent selected; using model-only response path")

                        agent_iter = all_agents.values() if isinstance(all_agents, dict) else all_agents
                        if agent_name_to_select:
                            for agent in agent_iter:
                                agent_obj_name = getattr(agent, 'name', None)
                                debug_print(f"[Streaming] Checking agent: {agent_obj_name} against target: {agent_name_to_select}")
                                if agent_obj_name == agent_name_to_select:
                                    selected_agent = agent
                                    debug_print(f"[Streaming] Found matching agent: {agent_obj_name}")
                                    break
                            if not selected_agent:
                                debug_print(f"[Streaming] Requested chat agent was not found: {agent_name_to_select}")
                                selected_agent_metadata = None
                        else:
                            debug_print("[Streaming] No chat agent selected for this request; using model-only response path")

                        if selected_agent:
                            use_agent_streaming = True
                            agent_name_used = getattr(selected_agent, 'name', 'agent')
                            agent_display_name_used = getattr(selected_agent, 'display_name', agent_name_used)
                            if not selected_agent_metadata:
                                selected_agent_metadata = _build_agent_selection_metadata(
                                    selected_agent,
                                    assigned_knowledge_filters,
                                )
                            actual_model_used = getattr(selected_agent, 'deployment_name', None) or gpt_model
                            if isinstance(selected_agent_metadata, dict):
                                agent_icon_used = selected_agent_metadata.get('agent_icon')
                                agent_tags_used = selected_agent_metadata.get('agent_tags') or []
                            debug_print(f"--- Streaming from Agent: {agent_name_used} (model: {actual_model_used}) ---")
                        else:
                            debug_print(f"[Streaming] ⚠️ No agent selected, falling back to GPT")

                if selected_agent_metadata:
                    user_metadata['agent_selection'] = selected_agent_metadata

                conversation_history_for_api = maybe_append_chart_tool_system_message(
                    conversation_history_for_api,
                    user_message,
                    selected_agent,
                )
                conversation_history_for_api = maybe_append_image_proposal_system_message(
                    conversation_history_for_api,
                    user_message,
                    settings,
                    selected_agent,
                )

                # Stream the response
                accumulated_content = ""
                token_usage_data = None  # Will be populated from final stream chunk
                # assistant_message_id was generated earlier for thought tracking
                final_model_used = gpt_model  # Default to gpt_model, will be overridden if agent is used

                def finalize_cancelled_stream_response():
                    cancel_reason = stream_session.get_cancel_reason() if stream_session else 'user_requested'
                    partial_content = accumulated_content.strip()
                    message_persisted = False
                    cancel_metadata = {
                        'incomplete': True,
                        'canceled': True,
                        'cancel_reason': cancel_reason,
                    }

                    if partial_content:
                        assistant_timestamp = datetime.utcnow().isoformat()
                        prepared_agent_citations = persist_agent_citation_artifacts(
                            conversation_id=conversation_id,
                            assistant_message_id=assistant_message_id,
                            agent_citations=agent_citations_list,
                            created_timestamp=assistant_timestamp,
                            user_info=user_info_for_assistant,
                        )
                        generated_analysis_metadata = _build_generated_analysis_metadata(
                            generated_analysis_artifacts=generated_analysis_artifacts_list,
                            generated_tabular_outputs=generated_tabular_outputs_list,
                        )
                        assistant_doc = make_json_serializable({
                            'id': assistant_message_id,
                            'conversation_id': conversation_id,
                            'role': 'assistant',
                            'content': partial_content,
                            'timestamp': assistant_timestamp,
                            'augmented': bool(system_messages_for_augmentation),
                            'hybrid_citations': hybrid_citations_list,
                            'web_search_citations': web_search_citations_list,
                            'hybridsearch_query': search_query if hybrid_search_enabled and search_results else None,
                            'agent_citations': prepared_agent_citations,
                            'model_deployment_name': final_model_used if use_agent_streaming else gpt_model,
                            'agent_display_name': agent_display_name_used if use_agent_streaming else None,
                            'agent_name': agent_name_used if use_agent_streaming else None,
                            'agent_icon': agent_icon_used if use_agent_streaming else None,
                            'agent_tags': agent_tags_used if use_agent_streaming else [],
                            'metadata': {
                                **cancel_metadata,
                                'reasoning_effort': reasoning_effort,
                                'history_context': history_debug_info,
                                'capability_usage': build_streaming_capability_usage(),
                                'source_review': compact_source_review_result_for_metadata(source_review_result),
                                'deep_research': deep_research_result,
                                **generated_analysis_metadata,
                                'thread_info': {
                                    'thread_id': response_message_context.get('thread_id'),
                                    'previous_thread_id': response_message_context.get('previous_thread_id'),
                                    'active_thread': True,
                                    'thread_attempt': assistant_thread_attempt,
                                },
                            },
                        })
                        cosmos_messages_container.upsert_item(assistant_doc)
                        conversation_item['last_updated'] = datetime.utcnow().isoformat()
                        cosmos_conversations_container.upsert_item(conversation_item)
                        message_persisted = True

                    log_event(
                        '[Streaming] Stream generation stopped by user request',
                        extra={
                            'conversation_id': conversation_id,
                            'user_id': user_id,
                            'message_id': assistant_message_id if message_persisted else None,
                            'partial_content_length': len(partial_content),
                            'cancel_reason': cancel_reason,
                        },
                        level=logging.INFO,
                    )

                    return _build_stream_cancel_event(
                        conversation_id,
                        user_message_id=user_message_id,
                        message_id=assistant_message_id if message_persisted else None,
                        partial_content=partial_content,
                        reason=cancel_reason,
                        message_persisted=message_persisted,
                        extra_payload={
                            'augmented': bool(system_messages_for_augmentation),
                            'hybrid_citations': hybrid_citations_list,
                            'web_search_citations': web_search_citations_list,
                            'agent_citations': agent_citations_list,
                            'model_deployment_name': final_model_used if use_agent_streaming else gpt_model,
                            'agent_display_name': agent_display_name_used if use_agent_streaming else None,
                            'agent_name': agent_name_used if use_agent_streaming else None,
                            'agent_icon': agent_icon_used if use_agent_streaming else None,
                            'agent_tags': agent_tags_used if use_agent_streaming else [],
                            'metadata': cancel_metadata,
                            'thoughts_enabled': thought_tracker.enabled,
                        },
                    )

                if stream_cancel_requested():
                    yield finalize_cancelled_stream_response()
                    return

                # DEBUG: Check agent streaming decision
                debug_print(f"[DEBUG] use_agent_streaming={use_agent_streaming}, selected_agent={selected_agent is not None}")
                debug_print(f"[DEBUG] enable_semantic_kernel={enable_semantic_kernel}, user_enable_agents={user_enable_agents}")
                debug_print(
                    "[Streaming] Selected response path | "
                    f"use_agent_streaming={use_agent_streaming} | "
                    f"selected_agent={getattr(selected_agent, 'name', None) if selected_agent else None} | "
                    f"model={gpt_model}"
                )
                stream_selected_agent_type = (
                    str(getattr(selected_agent, 'agent_type', 'local') or 'local').lower()
                    if selected_agent
                    else 'local'
                )

                try:
                    if use_agent_streaming and selected_agent:
                        # Stream from agent using invoke_stream
                        yield emit_thought('agent_tool_call', f"Sending to agent '{agent_display_name_used or agent_name_used}'")
                        yield emit_thought('generation', f"Sending to '{actual_model_used}'")
                        debug_print(f"--- Streaming from Agent: {agent_name_used} ---")

                        # Register callback to persist plugin thoughts to Cosmos in real-time
                        plugin_logger_cb = get_plugin_logger()
                        callback_key = register_plugin_invocation_thought_callback(
                            plugin_logger_cb,
                            thought_tracker,
                            user_id,
                            conversation_id,
                            actor_label='Agent',
                            live_thought_callback=publish_live_plugin_thought,
                        )
                        debug_print(
                            f"[Streaming][Plugin Callback] Registering callback for key={callback_key}"
                        )

                        def finalize_cancelled_agent_stream_response():
                            plugin_logger_cb.deregister_callbacks(callback_key)
                            debug_print(
                                f"[Streaming][Plugin Callback] Deregistered callback after stream cancellation for key={callback_key}"
                            )
                            return finalize_cancelled_stream_response()

                        # Convert conversation history to ChatMessageContent (same as non-streaming)
                        agent_message_history = [
                            ChatMessageContent(
                                role=msg["role"],
                                content=msg["content"],
                                metadata=msg.get("metadata", {})
                            )
                            for msg in conversation_history_for_api
                        ]
                        stream_usage = None

                        # Execute async streaming
                        try:
                            # Try to get existing event loop
                            loop = asyncio.get_event_loop()
                            if loop.is_closed():
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                        except RuntimeError:
                            # No event loop in current thread
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)

                        agent_retry_plan = None
                        retry_state = None

                        try:
                            for attempt_number in range(2):
                                try:
                                    if agent_retry_plan:
                                        debug_print(
                                            f"[Streaming][Agent Retry] Retrying agent stream | "
                                            f"agent={getattr(selected_agent, 'name', None)} | "
                                            f"model={getattr(selected_agent, 'deployment_name', actual_model_used)} | "
                                            f"mode={agent_retry_plan['mode']} | "
                                            f"reason={agent_retry_plan['reason']}"
                                        )

                                    if stream_cancel_requested():
                                        yield finalize_cancelled_agent_stream_response()
                                        return

                                    if stream_selected_agent_type in ('foundry_workflow', 'new_foundry'):
                                        foundry_stream_metadata = {
                                            'conversation_id': conversation_id,
                                            'user_id': user_id,
                                            'message_id': user_message_id,
                                            'chat_type': chat_type,
                                            'document_scope': effective_document_scope,
                                            'group_id': effective_active_group_id if chat_type == 'group' else None,
                                            'hybrid_search_enabled': hybrid_search_enabled,
                                            'selected_document_id': effective_selected_document_id,
                                            'selected_document_ids': effective_selected_document_ids,
                                            'active_group_ids': effective_active_group_ids,
                                            'active_public_workspace_ids': effective_active_public_workspace_ids,
                                            'selected_document_count': len(effective_selected_document_ids or []),
                                            'search_query': search_query,
                                        }
                                        agent_stream = selected_agent.invoke_stream(
                                            messages=agent_message_history,
                                            metadata={
                                                key: value
                                                for key, value in foundry_stream_metadata.items()
                                                if value is not None
                                            },
                                        )
                                    else:
                                        agent_stream = selected_agent.invoke_stream(messages=agent_message_history)
                                    while True:
                                        if stream_cancel_requested():
                                            yield finalize_cancelled_agent_stream_response()
                                            return
                                        try:
                                            response = loop.run_until_complete(agent_stream.__anext__())
                                        except StopAsyncIteration:
                                            break

                                        response_metadata = getattr(response, 'metadata', None)
                                        if isinstance(response_metadata, dict):
                                            usage = response_metadata.get('usage')
                                            if usage:
                                                stream_usage = usage
                                            response_model = response_metadata.get('model')
                                            if isinstance(response_model, str) and response_model.strip():
                                                actual_model_used = response_model.strip()

                                        chunk_content = None
                                        if hasattr(response, 'content') and response.content:
                                            chunk_content = str(response.content)
                                        elif isinstance(response, str) and response:
                                            chunk_content = response

                                        if chunk_content:
                                            accumulated_content += chunk_content
                                            yield f"data: {json.dumps({'content': chunk_content})}\n\n"

                                        if stream_cancel_requested():
                                            yield finalize_cancelled_agent_stream_response()
                                            return

                                    if agent_retry_plan:
                                        debug_print(
                                            f"[Streaming][Agent Retry] Agent retry succeeded | "
                                            f"agent={getattr(selected_agent, 'name', None)} | "
                                            f"model={actual_model_used} | "
                                            f"reason={agent_retry_plan['reason']}"
                                        )
                                    break
                                except Exception as stream_error:
                                    if agent_retry_plan is None:
                                        candidate_retry_plan = classify_agent_stream_retry_mode(stream_error)
                                        if candidate_retry_plan and not accumulated_content and attempt_number == 0:
                                            agent_retry_plan = candidate_retry_plan
                                            retry_state = apply_agent_stream_retry_mode(
                                                selected_agent,
                                                agent_retry_plan['mode'],
                                            )
                                            debug_print(
                                                f"[Streaming][Agent Retry] Retrying agent stream without tool calling | "
                                                f"agent={getattr(selected_agent, 'name', None)} | "
                                                f"model={getattr(selected_agent, 'deployment_name', actual_model_used)} | "
                                                f"reason={agent_retry_plan['reason']} | "
                                                f"error={stream_error}"
                                            )
                                            continue
                                    raise
                        except Exception as stream_error:
                            import traceback
                            plugin_logger_cb.deregister_callbacks(callback_key)
                            debug_print(
                                f"[Streaming][Plugin Callback] Deregistered callback after streaming error for key={callback_key}"
                            )
                            debug_print(
                                f"[Streaming][Agent Retry] Terminal agent streaming error | "
                                f"retried={agent_retry_plan is not None} | error={stream_error}"
                            )
                            debug_print(f"❌ Agent streaming error: {stream_error}")
                            traceback.print_exc()
                            error_payload = {'error': f'Agent streaming failed: {str(stream_error)}'}
                            if isinstance(stream_error, FoundryAgentUserAuthenticationRequired):
                                auth_response = getattr(stream_error, 'auth_response', {}) or {}
                                error_payload = {
                                    'error': str(stream_error),
                                    'auth_required': True,
                                    'scopes': auth_response.get('scopes') or [],
                                }
                                if auth_response.get('consent_url') or auth_response.get('auth_url'):
                                    error_payload['consent_url'] = auth_response.get('consent_url') or auth_response.get('auth_url')
                                    error_payload['auth_url'] = auth_response.get('auth_url') or auth_response.get('consent_url')
                            yield f"data: {json.dumps(error_payload)}\n\n"
                            return
                        finally:
                            restore_agent_stream_retry_state(selected_agent, retry_state)

                        actual_model_used = (
                            getattr(selected_agent, 'last_run_model', None)
                            or actual_model_used
                        )

                        # Emit responded thought with total duration from user message
                        agent_stream_total_duration_s = round(time.time() - request_start_time, 1)
                        yield emit_thought('generation', f"'{actual_model_used}' responded ({agent_stream_total_duration_s}s from initial message)")

                        # Deregister callback (agent completed successfully)
                        plugin_logger_cb.deregister_callbacks(callback_key)
                        debug_print(
                            f"[Streaming][Plugin Callback] Deregistered callback after successful stream for key={callback_key}"
                        )

                        agent_plugin_invocations = plugin_logger_cb.get_invocations_for_conversation(user_id, conversation_id)

                        # Try to capture token usage from stream metadata
                        if stream_usage:
                            if isinstance(stream_usage, dict):
                                prompt_tokens = int(stream_usage.get('prompt_tokens') or 0)
                                completion_tokens = int(stream_usage.get('completion_tokens') or 0)
                                total_tokens = stream_usage.get('total_tokens')
                            else:
                                prompt_tokens = getattr(stream_usage, 'prompt_tokens', 0)
                                completion_tokens = getattr(stream_usage, 'completion_tokens', 0)
                                total_tokens = getattr(stream_usage, 'total_tokens', None)

                            # Calculate total if not provided
                            if total_tokens is None or total_tokens == 0:
                                total_tokens = prompt_tokens + completion_tokens

                            token_usage_data = {
                                'prompt_tokens': prompt_tokens,
                                'completion_tokens': completion_tokens,
                                'total_tokens': total_tokens,
                                'captured_at': datetime.utcnow().isoformat()
                            }
                            debug_print(f"[Agent Streaming Tokens] From metadata - prompt: {prompt_tokens}, completion: {completion_tokens}, total: {total_tokens}")

                        # Collect token usage from kernel services if not captured from stream
                        if not token_usage_data:
                            kernel = get_kernel()
                            if kernel:
                                try:
                                    for service in getattr(kernel, "services", {}).values():
                                        prompt_tokens = getattr(service, "prompt_tokens", None)
                                        completion_tokens = getattr(service, "completion_tokens", None)
                                        total_tokens = getattr(service, "total_tokens", None)

                                        if prompt_tokens is not None or completion_tokens is not None:
                                            token_usage_data = {
                                                'prompt_tokens': prompt_tokens or 0,
                                                'completion_tokens': completion_tokens or 0,
                                                'total_tokens': total_tokens or (prompt_tokens or 0) + (completion_tokens or 0),
                                                'captured_at': datetime.utcnow().isoformat()
                                            }
                                            debug_print(f"[Agent Streaming Tokens] From kernel service - prompt: {prompt_tokens}, completion: {completion_tokens}, total: {total_tokens}")
                                            break
                                except Exception as e:
                                    debug_print(f"Warning: Could not collect token usage from kernel services: {e}")

                        # Capture agent citations after streaming completes
                        # Plugin invocations should have been logged during agent execution
                        plugin_logger = get_plugin_logger()

                        # Debug: Check all invocations first
                        all_invocations = plugin_logger.get_recent_invocations()
                        debug_print(f"[Agent Streaming] Total plugin invocations logged: {len(all_invocations)}")

                        plugin_invocations = plugin_logger.get_invocations_for_conversation(user_id, conversation_id)
                        debug_print(f"[Agent Streaming] Found {len(plugin_invocations)} plugin invocations for user {user_id}, conversation {conversation_id}")

                        # If no invocations found, check if plugins were called at all
                        if len(plugin_invocations) == 0 and len(all_invocations) > 0:
                            debug_print(f"[Agent Streaming] ⚠️ Plugin invocations exist but not for this conversation - possible filtering issue")
                            # Debug: show last few invocations
                            for inv in all_invocations[-3:]:
                                debug_print(f"[Agent Streaming] Recent invocation: user={inv.user_id}, conv={inv.conversation_id}, plugin={inv.plugin_name}.{inv.function_name}")

                        # Convert to citation format
                        for inv in plugin_invocations:
                            timestamp_str = None
                            if inv.timestamp:
                                if hasattr(inv.timestamp, 'isoformat'):
                                    timestamp_str = inv.timestamp.isoformat()
                                else:
                                    timestamp_str = str(inv.timestamp)
                            tool_name = build_agent_citation_tool_label(
                                inv.plugin_name,
                                inv.function_name,
                                inv.parameters,
                                inv.result,
                            )

                            citation = {
                                'tool_name': tool_name,
                                'function_name': inv.function_name,
                                'plugin_name': inv.plugin_name,
                                'function_arguments': make_json_serializable(inv.parameters),
                                'function_result': make_json_serializable(inv.result),
                                'duration_ms': inv.duration_ms,
                                'timestamp': timestamp_str,
                                'success': inv.success,
                                'error_message': make_json_serializable(inv.error_message),
                                'user_id': inv.user_id
                            }
                            agent_citations_list.append(citation)

                        foundry_citations = getattr(selected_agent, 'last_run_citations', []) or []
                        if _is_foundry_selected_agent_type(stream_selected_agent_type) and foundry_citations:
                            foundry_plugin_name = _get_foundry_agent_plugin_name(stream_selected_agent_type)
                            foundry_label = agent_name_used or _get_foundry_agent_label(stream_selected_agent_type)
                            for citation in foundry_citations:
                                yield emit_thought('agent_tool_call', f"Agent retrieved citation from {_get_foundry_agent_label(stream_selected_agent_type)}")
                                serializable = make_json_serializable(citation)
                                if not isinstance(serializable, dict):
                                    serializable = {'value': str(citation)}
                                agent_citations_list.append({
                                    'tool_name': foundry_label,
                                    'function_name': 'foundry_citation',
                                    'plugin_name': foundry_plugin_name,
                                    'function_arguments': serializable,
                                    'function_result': serializable,
                                    'timestamp': datetime.utcnow().isoformat(),
                                    'success': True
                                })

                        debug_print(f"[Agent Streaming] Captured {len(agent_citations_list)} citations")
                        final_model_used = actual_model_used

                    else:
                        # Stream from regular GPT model (non-agent)
                        yield emit_thought('generation', f"Sending to '{gpt_model}'")
                        debug_print(f"--- Streaming from GPT ({gpt_model}) ---")

                        if stream_cancel_requested():
                            yield finalize_cancelled_stream_response()
                            return

                        # Prepare stream parameters
                        stream_params = {
                            'model': gpt_model,
                            'messages': conversation_history_for_api,
                            'stream': True,
                            'stream_options': {'include_usage': True}  # Request token usage in final chunk
                        }

                        # Add reasoning_effort if provided and not 'none'
                        if reasoning_effort and reasoning_effort != 'none':
                            stream_params['reasoning_effort'] = reasoning_effort
                            debug_print(f"Using reasoning effort: {reasoning_effort}")

                        final_model_used = gpt_model

                        try:
                            stream = gpt_client.chat.completions.create(**stream_params)
                        except Exception as e:
                            # Check if error is related to reasoning_effort parameter
                            error_str = str(e).lower()
                            if reasoning_effort and reasoning_effort != 'none' and (
                                'reasoning_effort' in error_str or
                                'unrecognized request argument' in error_str or
                                'invalid_request_error' in error_str
                            ):
                                debug_print(f"Reasoning effort not supported by {gpt_model}, retrying without reasoning_effort...")
                                # Retry without reasoning_effort
                                stream_params.pop('reasoning_effort', None)
                                stream = gpt_client.chat.completions.create(**stream_params)
                            else:
                                raise

                        for chunk in stream:
                            if stream_cancel_requested():
                                yield finalize_cancelled_stream_response()
                                return

                            if chunk.choices and len(chunk.choices) > 0:
                                delta = chunk.choices[0].delta
                                if delta.content:
                                    accumulated_content += delta.content
                                    yield f"data: {json.dumps({'content': delta.content})}\n\n"

                            if stream_cancel_requested():
                                yield finalize_cancelled_stream_response()
                                return

                            # Capture token usage from final chunk with stream_options
                            if hasattr(chunk, 'usage') and chunk.usage:
                                token_usage_data = {
                                    'prompt_tokens': chunk.usage.prompt_tokens,
                                    'completion_tokens': chunk.usage.completion_tokens,
                                    'total_tokens': chunk.usage.total_tokens,
                                    'captured_at': datetime.utcnow().isoformat()
                                }
                                debug_print(f"[Streaming Tokens] Captured usage - prompt: {chunk.usage.prompt_tokens}, completion: {chunk.usage.completion_tokens}, total: {chunk.usage.total_tokens}")

                        # Emit responded thought for regular LLM streaming
                        gpt_stream_total_duration_s = round(time.time() - request_start_time, 1)
                        yield emit_thought('generation', f"'{gpt_model}' responded ({gpt_stream_total_duration_s}s from initial message)")

                    if stream_cancel_requested():
                        yield finalize_cancelled_stream_response()
                        return

                    # Stream complete - save message and send final metadata
                    accumulated_content_before_chart_append = accumulated_content
                    accumulated_content = _append_inline_chart_blocks_to_message(accumulated_content, agent_citations_list)
                    appended_chart_content = _get_appended_inline_chart_content_delta(
                        accumulated_content_before_chart_append,
                        accumulated_content,
                    )
                    if appended_chart_content:
                        yield f"data: {json.dumps({'content': appended_chart_content})}\n\n"
                    user_info_for_assistant = response_message_context.get('user_info')
                    user_thread_id = response_message_context.get('thread_id')
                    user_previous_thread_id = response_message_context.get('previous_thread_id')
                    assistant_timestamp = datetime.utcnow().isoformat()
                    prepared_agent_citations = persist_agent_citation_artifacts(
                        conversation_id=conversation_id,
                        assistant_message_id=assistant_message_id,
                        agent_citations=agent_citations_list,
                        created_timestamp=assistant_timestamp,
                        user_info=user_info_for_assistant,
                    )
                    assistant_table_generated_output = maybe_create_assistant_table_generated_output(
                        user_question=user_message,
                        assistant_content=accumulated_content,
                        conversation_id=conversation_id,
                        existing_outputs=generated_analysis_artifacts_list + generated_tabular_outputs_list,
                    )
                    if assistant_table_generated_output:
                        generated_analysis_artifacts_list.append(assistant_table_generated_output)
                        generated_tabular_outputs_list.append(assistant_table_generated_output)
                    generated_analysis_metadata = _build_generated_analysis_metadata(
                        generated_analysis_artifacts=generated_analysis_artifacts_list,
                        generated_tabular_outputs=generated_tabular_outputs_list,
                    )
                    agent_runtime_metadata = _build_foundry_runtime_metadata(selected_agent) if use_agent_streaming else {}

                    assistant_doc = make_json_serializable({
                        'id': assistant_message_id,
                        'conversation_id': conversation_id,
                        'role': 'assistant',
                        'content': accumulated_content,
                        'timestamp': assistant_timestamp,
                        'augmented': bool(system_messages_for_augmentation),
                        'hybrid_citations': hybrid_citations_list,
                        'web_search_citations': web_search_citations_list,
                        'hybridsearch_query': search_query if search_results else None,
                        'agent_citations': prepared_agent_citations,
                        'model_deployment_name': final_model_used if use_agent_streaming else gpt_model,
                        'agent_display_name': agent_display_name_used if use_agent_streaming else None,
                        'agent_name': agent_name_used if use_agent_streaming else None,
                        'agent_icon': agent_icon_used if use_agent_streaming else None,
                        'agent_tags': agent_tags_used if use_agent_streaming else [],
                        'metadata': {
                            'reasoning_effort': reasoning_effort,
                            'history_context': history_debug_info,
                            'capability_usage': build_streaming_capability_usage(),
                            'agent_runtime': agent_runtime_metadata or None,
                            'source_review': compact_source_review_result_for_metadata(source_review_result),
                            'deep_research': deep_research_result,
                            **generated_analysis_metadata,
                            'thread_info': {
                                'thread_id': user_thread_id,
                                'previous_thread_id': user_previous_thread_id,
                                'active_thread': True,
                                'thread_attempt': assistant_thread_attempt
                            },
                            'token_usage': token_usage_data if token_usage_data else None  # Store token usage from stream
                        }
                    })
                    cosmos_messages_container.upsert_item(assistant_doc)
                    if use_agent_streaming and agent_name_used:
                        agent_scope_for_usage = 'personal'
                        agent_group_id_for_usage = None
                        agent_catalog_key_for_usage = None
                        if isinstance(selected_agent_metadata, dict):
                            if selected_agent_metadata.get('is_global'):
                                agent_scope_for_usage = 'global'
                            elif selected_agent_metadata.get('is_group'):
                                agent_scope_for_usage = 'group'
                                agent_group_id_for_usage = selected_agent_metadata.get('group_id')
                            agent_catalog_key_for_usage = selected_agent_metadata.get('catalog_key')
                        log_agent_run(
                            user_id=user_id,
                            agent_id=getattr(selected_agent, 'id', None) if selected_agent else None,
                            agent_name=agent_name_used,
                            agent_display_name=agent_display_name_used,
                            scope=agent_scope_for_usage,
                            group_id=agent_group_id_for_usage,
                            conversation_id=conversation_id,
                            message_id=assistant_message_id,
                            model=final_model_used if use_agent_streaming else gpt_model,
                            agent_catalog_key=agent_catalog_key_for_usage,
                        )

                    # Log chat token usage to activity_logs for easy reporting
                    if token_usage_data and token_usage_data.get('total_tokens'):
                        try:
                            from functions_activity_logging import log_token_usage

                            # Determine workspace type based on active group/public workspace
                            workspace_type = 'personal'
                            if effective_active_public_workspace_id:
                                workspace_type = 'public'
                            elif effective_active_group_id:
                                workspace_type = 'group'

                            log_token_usage(
                                user_id=user_id,
                                token_type='chat',
                                total_tokens=token_usage_data.get('total_tokens'),
                                model=final_model_used if use_agent_streaming else gpt_model,
                                workspace_type=workspace_type,
                                prompt_tokens=token_usage_data.get('prompt_tokens'),
                                completion_tokens=token_usage_data.get('completion_tokens'),
                                conversation_id=conversation_id,
                                message_id=assistant_message_id,
                                group_id=effective_active_group_id,
                                public_workspace_id=effective_active_public_workspace_id,
                                additional_context={
                                    'agent_name': agent_name_used if use_agent_streaming else None,
                                    'augmented': bool(system_messages_for_augmentation),
                                    'reasoning_effort': reasoning_effort
                                }
                            )
                            debug_print(f"✅ Logged streaming chat token usage: {token_usage_data.get('total_tokens')} tokens")
                        except Exception as log_error:
                            debug_print(f"⚠️  Warning: Failed to log streaming chat token usage: {log_error}")
                            # Don't fail the chat flow if logging fails

                    # Update conversation
                    conversation_item['last_updated'] = datetime.utcnow().isoformat()

                    try:
                        user_message_doc = cosmos_messages_container.read_item(
                            item=user_message_id,
                            partition_key=conversation_id
                        )
                        if 'metadata' in user_message_doc and 'model_selection' in user_message_doc['metadata']:
                            user_message_doc['metadata']['model_selection']['selected_model'] = final_model_used if use_agent_streaming else gpt_model
                        if selected_agent_metadata:
                            user_message_doc.setdefault('metadata', {})['agent_selection'] = selected_agent_metadata
                        cosmos_messages_container.upsert_item(user_message_doc)
                    except Exception as e:
                        debug_print(f"Warning: Could not update streaming user message metadata: {e}")

                    try:
                        conversation_item = collect_conversation_metadata(
                            user_message=user_message,
                            conversation_id=conversation_id,
                            user_id=user_id,
                            active_group_id=effective_active_group_id,
                            active_group_ids=effective_active_group_ids,
                            document_scope=effective_document_scope,
                            selected_document_id=effective_selected_document_id,
                            model_deployment=final_model_used if use_agent_streaming else gpt_model,
                            hybrid_search_enabled=hybrid_search_enabled or history_grounded_search_used,
                            image_gen_enabled=False,
                            selected_documents=combined_documents if combined_documents else None,
                            selected_agent=agent_name_used if use_agent_streaming else None,
                            selected_agent_details=selected_agent_metadata if use_agent_streaming else None,
                            search_results=search_results if search_results else None,
                            conversation_item=conversation_item,
                            active_public_workspace_id=effective_active_public_workspace_id,
                            active_public_workspace_ids=effective_active_public_workspace_ids
                        )
                    except Exception as e:
                        debug_print(f"Error collecting conversation metadata: {e}")

                    if is_personal_chat_conversation(conversation_item):
                        conversation_item = mark_conversation_unread(
                            conversation_item,
                            assistant_message_id,
                            unread_timestamp=conversation_item['last_updated']
                        )

                        notification_doc = create_chat_response_notification(
                            user_id=user_id,
                            conversation_id=conversation_id,
                            message_id=assistant_message_id,
                            conversation_title=conversation_item.get('title', ''),
                            response_preview=accumulated_content,
                        )
                        if notification_doc:
                            debug_print(
                                f"Created chat completion notification {notification_doc['id']} for conversation {conversation_id}"
                            )
                    else:
                        debug_print(
                            f"Skipping personal chat completion notification for conversation {conversation_id} because chat_type={conversation_item.get('chat_type')}"
                        )

                    cosmos_conversations_container.upsert_item(conversation_item)

                    # Send final message with metadata
                    final_data = make_json_serializable({
                        'done': True,
                        'conversation_id': conversation_id,
                        'conversation_title': conversation_item['title'],
                        'classification': conversation_item.get('classification', []),
                        'context': conversation_item.get('context', []),
                        'chat_type': conversation_item.get('chat_type'),
                        'scope_locked': conversation_item.get('scope_locked'),
                        'locked_contexts': conversation_item.get('locked_contexts', []),
                        'model_deployment_name': final_model_used if use_agent_streaming else gpt_model,
                        'message_id': assistant_message_id,
                        'user_message_id': user_message_id,
                        'augmented': bool(system_messages_for_augmentation),
                        'hybrid_citations': hybrid_citations_list,
                        'web_search_citations': web_search_citations_list,
                        'source_review': compact_source_review_result_for_metadata(source_review_result),
                        'deep_research': deep_research_result,
                        'agent_citations': prepared_agent_citations,
                        'agent_display_name': agent_display_name_used if use_agent_streaming else None,
                        'agent_name': agent_name_used if use_agent_streaming else None,
                        'agent_icon': agent_icon_used if use_agent_streaming else None,
                        'agent_tags': agent_tags_used if use_agent_streaming else [],
                        'metadata': assistant_doc.get('metadata', {}),
                        'full_content': accumulated_content,
                        'thoughts_enabled': thought_tracker.enabled
                    })
                    debug_print(
                        "[Streaming] Finalizing stream response | "
                        f"conversation_id={conversation_id} | message_id={assistant_message_id} | "
                        f"content_length={len(accumulated_content)} | hybrid_citations={len(hybrid_citations_list)} | "
                        f"web_citations={len(web_search_citations_list)} | agent_citations={len(agent_citations_list)} | "
                        f"thoughts_enabled={thought_tracker.enabled}"
                    )
                    yield f"data: {json.dumps(final_data)}\n\n"

                except Exception as e:
                    error_msg = str(e)
                    debug_print(f"Error during streaming: {error_msg}")

                    # Save partial response if we have content
                    if accumulated_content:
                        current_assistant_thread_id = str(uuid.uuid4())
                        assistant_timestamp = datetime.utcnow().isoformat()
                        prepared_agent_citations = persist_agent_citation_artifacts(
                            conversation_id=conversation_id,
                            assistant_message_id=assistant_message_id,
                            agent_citations=agent_citations_list,
                            created_timestamp=assistant_timestamp,
                            user_info=user_info_for_assistant,
                        )
                        generated_analysis_metadata = _build_generated_analysis_metadata(
                            generated_analysis_artifacts=generated_analysis_artifacts_list,
                            generated_tabular_outputs=generated_tabular_outputs_list,
                        )

                        assistant_doc = make_json_serializable({
                            'id': assistant_message_id,
                            'conversation_id': conversation_id,
                            'role': 'assistant',
                            'content': accumulated_content,
                            'timestamp': assistant_timestamp,
                            'augmented': bool(system_messages_for_augmentation),
                            'hybrid_citations': hybrid_citations_list,
                            'web_search_citations': web_search_citations_list,
                            'hybridsearch_query': search_query if hybrid_search_enabled and search_results else None,
                            'agent_citations': prepared_agent_citations,
                            'model_deployment_name': final_model_used if use_agent_streaming else gpt_model,
                            'agent_display_name': agent_display_name_used if use_agent_streaming else None,
                            'agent_name': agent_name_used if use_agent_streaming else None,
                            'metadata': {
                                'incomplete': True,
                                'error': error_msg,
                                'reasoning_effort': reasoning_effort,
                                'history_context': history_debug_info,
                                'capability_usage': build_streaming_capability_usage(),
                                'source_review': compact_source_review_result_for_metadata(source_review_result),
                                'deep_research': deep_research_result,
                                **generated_analysis_metadata,
                                'thread_info': {
                                    'thread_id': user_thread_id,
                                    'previous_thread_id': user_previous_thread_id,
                                    'active_thread': True,
                                    'thread_attempt': 1
                                }
                            }
                        })
                        try:
                            cosmos_messages_container.upsert_item(assistant_doc)
                        except Exception as ex:
                            pass

                    yield f"data: {json.dumps({'error': error_msg, 'partial_content': accumulated_content})}\n\n"

            except Exception as e:
                import traceback
                error_traceback = traceback.format_exc()
                debug_print(f"[STREAM API ERROR] Unhandled exception: {str(e)}")
                debug_print(f"[STREAM API ERROR] Full traceback:\n{error_traceback}")
                yield f"data: {json.dumps({'error': f'Internal server error: {str(e)}'})}\n\n"

        return build_background_stream_response(generate, stream_session=stream_session)

    @app.route('/api/chat/stream/cancel/<conversation_id>', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_stream_cancel_api(conversation_id):
        """Request best-effort cancellation for the current user's active chat stream."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        cancel_reason = str(data.get('reason') or 'user_requested').strip() or 'user_requested'
        stream_session = CHAT_STREAM_REGISTRY.get_session(user_id, conversation_id, active_only=True)
        if not stream_session:
            return jsonify({'error': 'No active stream is available for this conversation'}), 404

        stream_status = stream_session.request_cancel(reason=cancel_reason) or {}
        return jsonify({
            'success': True,
            'cancel_requested': True,
            **stream_status,
        })

    @app.route('/api/chat/stream/status/<conversation_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_stream_status_api(conversation_id):
        """Report whether a conversation has a live stream that can be reattached."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        stream_session = CHAT_STREAM_REGISTRY.get_session(user_id, conversation_id, active_only=False)
        stream_status = stream_session.get_status_snapshot() if stream_session else _build_stream_status_payload(None)
        stream_status['conversation_id'] = conversation_id
        return jsonify(stream_status)

    @app.route('/api/tabular/generated-output/runs/<run_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def tabular_generated_output_run_status_api(run_id):
        """Return durable generated-output run progress for the current user."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        run_status = get_tabular_generated_output_run_status(user_id, run_id)
        if not run_status:
            return jsonify({'error': 'Tabular generated-output run not found'}), 404
        return jsonify({'success': True, 'run': run_status})

    @app.route('/api/tabular/generated-output/runs/<run_id>/resume', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def tabular_generated_output_run_resume_api(run_id):
        """Requeue a resumable generated-output run for the current user."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        resume_result = resume_tabular_generated_output_run(user_id, run_id)
        if not resume_result:
            return jsonify({'error': 'Tabular generated-output run not found'}), 404
        if not resume_result.get('success'):
            return jsonify(resume_result), 409
        return jsonify(resume_result)

    @app.route('/api/chat/stream/reattach/<conversation_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_stream_reattach_api(conversation_id):
        """Replay and continue an in-flight stream for a previously opened conversation."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        stream_session = CHAT_STREAM_REGISTRY.get_session(user_id, conversation_id, active_only=True)
        if not stream_session:
            return jsonify({'error': 'No active stream is available for this conversation'}), 404

        stream_status = stream_session.mark_reattached() or {}
        log_event(
            '[Streaming] Stream consumer reattached',
            extra={
                'conversation_id': stream_status.get('conversation_id'),
                'user_id': stream_status.get('user_id'),
                'status': stream_status.get('status'),
                'reattach_count': stream_status.get('reattach_count'),
                'detach_count': stream_status.get('detach_count'),
                'event_count': stream_status.get('event_count'),
            },
            level=logging.INFO,
        )

        def consume_reattach_stream():
            stream_consumed = False
            detach_recorded = False
            try:
                for event in stream_session.iter_events():
                    yield event
                stream_consumed = True
            except GeneratorExit:
                detach_status = stream_session.mark_consumer_detached(reason='reattach_disconnect') or {}
                detach_recorded = True
                log_event(
                    '[Streaming] Reattached stream consumer detached',
                    extra={
                        'conversation_id': detach_status.get('conversation_id'),
                        'user_id': detach_status.get('user_id'),
                        'status': detach_status.get('status'),
                        'detach_reason': detach_status.get('detach_reason'),
                        'detach_count': detach_status.get('detach_count'),
                        'reattach_count': detach_status.get('reattach_count'),
                    },
                    level=logging.WARNING,
                )
                raise
            finally:
                if not detach_recorded and not stream_consumed and stream_session.is_active():
                    stream_session.mark_consumer_detached(reason='reattach_cleanup')

        return Response(
            stream_with_context(consume_reattach_stream()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )

    @app.route('/api/chat/stream/client-event', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_stream_client_event_api():
        """Capture best-effort client-side streaming failures for backend correlation."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        event_type = str(data.get('event_type') or '').strip().lower()
        if event_type not in ALLOWED_STREAM_CLIENT_EVENTS:
            return jsonify({'error': 'Unsupported stream client event'}), 400

        conversation_id = str(data.get('conversation_id') or '').strip() or None
        elapsed_ms = max(_safe_int(data.get('elapsed_ms')), 0)
        time_since_last_chunk_ms = max(_safe_int(data.get('time_since_last_chunk_ms')), 0)
        level = logging.WARNING if event_type in {
            'stream_premature_end',
            'stream_read_error',
            'stream_request_error',
            'stream_recovery_unavailable',
        } else logging.INFO

        log_event(
            f'[Streaming Client] {event_type}',
            extra={
                'user_id': user_id,
                'conversation_id': conversation_id,
                'event_type': event_type,
                'elapsed_ms': elapsed_ms,
                'time_since_last_chunk_ms': time_since_last_chunk_ms,
                'had_streamed_content': bool(data.get('had_streamed_content')),
                'event_count': max(_safe_int(data.get('event_count')), 0),
                'pending': bool(data.get('pending')),
                'reattachable': bool(data.get('reattachable')),
                'reported_status': str(data.get('status') or '').strip() or None,
                'error_message': _truncate_log_text(data.get('error_message')) or None,
                'abort_reason': _truncate_log_text(data.get('abort_reason'), max_length=120) or None,
            },
            level=level,
        )

        return jsonify({'success': True, 'event_type': event_type})

    @app.route('/api/message/<message_id>/mask', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def mask_message_api(message_id):
        """
        API endpoint to mask/unmask messages or parts of messages.
        This prevents masked content from being sent to the AI model in conversation history.
        """
        try:
            data = request.get_json(silent=True) or {}
            user_id = get_current_user_id()

            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401

            # Get action: "mask_all", "mask_selection", "unmask_message", or "clear_all_masks".
            # The legacy "unmask_all" action remains supported as a destructive clear-all action.
            action = data.get('action')
            selection = data.get('selection', {})
            request_conversation_id = str(data.get('conversation_id') or '').strip()
            current_user = get_current_user_info() or {}
            user_display_name = resolve_mask_display_name(current_user)

            # Validate action
            if action not in SUPPORTED_MESSAGE_MASK_ACTIONS:
                return jsonify({'error': 'Invalid action'}), 400

            # Fetch the message
            try:
                message_doc = None
                if request_conversation_id:
                    try:
                        message_doc = cosmos_messages_container.read_item(
                            item=message_id,
                            partition_key=request_conversation_id,
                        )
                    except CosmosResourceNotFoundError:
                        message_doc = None

                if message_doc is None:
                    query = "SELECT TOP 1 * FROM c WHERE c.id = @message_id"
                    params = [{"name": "@message_id", "value": message_id}]
                    message_results = list(cosmos_messages_container.query_items(
                        query=query,
                        parameters=params,
                        enable_cross_partition_query=True,
                    ))

                    if not message_results:
                        return jsonify({'error': 'Message not found'}), 404

                    message_doc = message_results[0]

                conversation_id = message_doc.get('conversation_id')

                # Verify ownership - only the message author can mask their message
                message_user_id = message_doc.get('metadata', {}).get('user_info', {}).get('user_id')
                if not message_user_id:
                    # Fallback: check conversation ownership for backwards compatibility
                    # All messages in a conversation (user, assistant, system) belong to the conversation owner
                    try:
                        conversation = cosmos_conversations_container.read_item(
                            item=conversation_id,
                            partition_key=conversation_id
                        )
                        if conversation.get('user_id') != user_id:
                            return jsonify({'error': 'You can only mask messages from your own conversations'}), 403
                    except Exception as ex:
                        return jsonify({'error': 'Conversation not found'}), 404
                elif message_user_id != user_id:
                    return jsonify({'error': 'You can only mask your own messages'}), 403

            except Exception as e:
                debug_print(f"Error fetching message {message_id}: {str(e)}")
                return jsonify({'error': f'Error fetching message: {str(e)}'}), 500

            # Initialize metadata if it doesn't exist
            if 'metadata' not in message_doc:
                message_doc['metadata'] = {}

            # Process based on action
            try:
                apply_message_mask_action(
                    message_doc,
                    action,
                    selection,
                    user_id,
                    user_display_name,
                )
            except ValueError as ex:
                return jsonify({'error': str(ex)}), 400

            # Update the message in Cosmos DB
            try:
                cosmos_messages_container.upsert_item(message_doc)
            except Exception as e:
                debug_print(f"Error updating message {message_id}: {str(e)}")
                return jsonify({'error': f'Error updating message: {str(e)}'}), 500

            return jsonify({
                'success': True,
                'message_id': message_id,
                'masked': message_doc['metadata'].get('masked', False),
                'masked_ranges': message_doc['metadata'].get('masked_ranges', [])
            }), 200

        except Exception as e:
            import traceback
            error_traceback = traceback.format_exc()
            debug_print(f"[MASK API ERROR] Unhandled exception: {str(e)}")
            debug_print(f"[MASK API ERROR] Full traceback:\n{error_traceback}")
            return jsonify({
                'error': f'Internal server error: {str(e)}',
                'details': error_traceback if app.debug else None
            }), 500


def _format_history_message_ref(message):
    role = str((message or {}).get('role') or 'unknown')
    message_id = str((message or {}).get('id') or 'unknown')
    return f"{role}:{message_id}"


def _capture_history_refs(refs, max_items=12):
    ref_list = [str(ref) for ref in refs if ref]
    if len(ref_list) <= max_items:
        return ref_list
    remaining = len(ref_list) - max_items
    return ref_list[:max_items] + [f"... (+{remaining} more)"]


def _format_history_refs_for_detail(refs):
    if not refs:
        return 'none'
    return ', '.join(str(ref) for ref in refs)


def _truncate_history_citation_text(text, max_chars=1600):
    value = str(text or '').strip()
    if not value:
        return ''
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}... [truncated {len(value) - max_chars} chars]"


def _serialize_history_citation_value(value, max_chars=1200):
    if value in (None, '', [], {}):
        return ''

    if isinstance(value, str):
        serialized = value
    else:
        try:
            serialized = json.dumps(value, default=str, ensure_ascii=False)
        except Exception:
            serialized = str(value)

    compact_serialized = ' '.join(serialized.split())
    return _truncate_history_citation_text(compact_serialized, max_chars=max_chars)


def _build_agent_citation_history_lines(agent_citations, max_citations=4):
    fact_memory_tool_names = {'instruction memory', 'fact memory recall'}
    fact_memory_plugin_names = {'fact_memory', 'factmemoryplugin', 'factmemory'}

    def parse_citation_payload(value):
        if isinstance(value, str):
            stripped_value = value.strip()
            if stripped_value[:1] in ('{', '['):
                try:
                    return json.loads(stripped_value)
                except Exception:
                    return value
        return value

    def should_exclude_from_history_replay(citation):
        if not isinstance(citation, dict):
            return False

        tool_name = str(citation.get('tool_name') or citation.get('function_name') or '').strip()
        plugin_name = str(citation.get('plugin_name') or '').strip().lower()
        normalized_tool_name = tool_name.lower()
        if tool_name.startswith('[Debug]') or tool_name == 'Conversation History':
            return True
        if plugin_name in fact_memory_plugin_names or normalized_tool_name in fact_memory_tool_names:
            return True
        return False

    def is_tabular_citation(citation):
        if not isinstance(citation, dict):
            return False
        tool_name = str(citation.get('tool_name') or '')
        function_name = str(citation.get('function_name') or '')
        plugin_name = str(citation.get('plugin_name') or '')
        return (
            plugin_name == 'TabularProcessingPlugin'
            or 'TabularProcessingPlugin.' in tool_name
            or function_name in {
                'aggregate_column',
                'count_rows',
                'count_rows_by_related_values',
                'describe_tabular_file',
                'filter_rows',
                'filter_rows_by_related_values',
                'get_distinct_values',
                'group_by_aggregate',
                'group_by_datetime_component',
                'lookup_value',
                'query_tabular_data',
            }
        )

    def build_tabular_signature(citation):
        arguments = parse_citation_payload(citation.get('function_arguments'))
        result = parse_citation_payload(citation.get('function_result'))
        if not isinstance(arguments, dict):
            arguments = {}
        if not isinstance(result, dict):
            result = {}

        tool_signature_name = str(citation.get('function_name') or citation.get('tool_name') or '').strip()
        if ' [' in tool_signature_name:
            tool_signature_name = tool_signature_name.split(' [', 1)[0]

        signature_payload = {
            'tool': tool_signature_name,
            'filename': result.get('filename') or arguments.get('filename'),
            'column': result.get('column') or arguments.get('column'),
            'values': result.get('values'),
            'sample_rows': result.get('sample_rows'),
            'value': result.get('value'),
        }
        try:
            return json.dumps(signature_payload, sort_keys=True, default=str)
        except Exception:
            return str(signature_payload)

    def summarize_tabular_values(values, max_chars=2200, max_items=60):
        if not isinstance(values, list) or not values:
            return ''

        compact_values = []
        current_length = 0
        for index, item in enumerate(values[:max_items]):
            item_text = _serialize_history_citation_value(item, max_chars=300)
            if not item_text:
                continue

            separator_length = 2 if compact_values else 0
            if current_length + separator_length + len(item_text) > max_chars:
                remaining = len(values) - index
                compact_values.append(f"... (+{remaining} more values)")
                break

            compact_values.append(item_text)
            current_length += separator_length + len(item_text)

        if len(values) > max_items and (not compact_values or not str(compact_values[-1]).startswith('... (+')):
            compact_values.append(f"... (+{len(values) - max_items} more values)")

        return '; '.join(compact_values)

    def build_tabular_line(citation):
        arguments = parse_citation_payload(citation.get('function_arguments'))
        result = parse_citation_payload(citation.get('function_result'))
        if not isinstance(arguments, dict):
            arguments = {}
        if not isinstance(result, dict):
            result = {}

        tool_name = str(citation.get('tool_name') or citation.get('function_name') or 'TabularProcessingPlugin').strip()
        filename = result.get('filename') or arguments.get('filename') or 'unknown file'
        selected_sheet = result.get('selected_sheet') or arguments.get('sheet_name') or 'unknown sheet'
        column = result.get('column') or arguments.get('column') or 'unknown column'
        distinct_count = result.get('distinct_count')
        returned_values = result.get('returned_values')
        values_summary = summarize_tabular_values(result.get('values'))

        line_parts = [
            tool_name,
            f"file={filename}",
            f"sheet={selected_sheet}",
            f"column={column}",
        ]
        if distinct_count not in (None, ''):
            line_parts.append(f"distinct_count={distinct_count}")
        if returned_values not in (None, ''):
            line_parts.append(f"returned_values={returned_values}")
        if values_summary:
            line_parts.append(f"values={values_summary}")

        return f"- {' | '.join(str(part) for part in line_parts if part not in (None, ''))}"

    eligible_citations = []
    seen_tabular_signatures = set()
    for citation in agent_citations or []:
        if isinstance(citation, dict):
            if should_exclude_from_history_replay(citation):
                continue
            if is_tabular_citation(citation):
                signature = build_tabular_signature(citation)
                if signature in seen_tabular_signatures:
                    continue
                seen_tabular_signatures.add(signature)
        eligible_citations.append(citation)

    lines = []
    for citation in eligible_citations[:max_citations]:
        if not isinstance(citation, dict):
            value_summary = _serialize_history_citation_value(citation, max_chars=800)
            if value_summary:
                lines.append(f"- Tool result: {value_summary}")
            continue

        if is_tabular_citation(citation):
            lines.append(build_tabular_line(citation))
            continue

        tool_name = str(citation.get('tool_name') or citation.get('function_name') or 'Tool invocation').strip()
        argument_summary = _serialize_history_citation_value(citation.get('function_arguments'), max_chars=350)
        result_summary = _serialize_history_citation_value(citation.get('function_result'), max_chars=700)
        error_summary = ''
        if citation.get('success') is False:
            error_summary = _serialize_history_citation_value(citation.get('error_message'), max_chars=400)

        line_parts = [tool_name]
        if argument_summary:
            line_parts.append(f"args={argument_summary}")
        if result_summary:
            line_parts.append(f"result={result_summary}")
        if error_summary:
            line_parts.append(f"error={error_summary}")
        lines.append(f"- {' | '.join(line_parts)}")

    remaining = len(eligible_citations) - min(len(eligible_citations), max_citations)
    if remaining > 0:
        lines.append(f"- ... (+{remaining} more prior tool results)")

    return lines


def _build_document_citation_history_lines(hybrid_citations, max_citations=5):
    lines = []
    for citation in (hybrid_citations or [])[:max_citations]:
        if not isinstance(citation, dict):
            continue

        file_name = str(citation.get('file_name') or 'Document').strip()
        line_parts = [file_name]

        page_number = citation.get('page_number')
        if page_number not in (None, ''):
            line_parts.append(f"page {page_number}")

        chunk_sequence = citation.get('chunk_sequence')
        chunk_id = citation.get('chunk_id')
        if chunk_sequence not in (None, ''):
            line_parts.append(f"chunk {chunk_sequence}")
        elif chunk_id not in (None, ''):
            line_parts.append(f"chunk {chunk_id}")

        classification = citation.get('classification')
        if classification not in (None, ''):
            line_parts.append(str(classification))

        lines.append(f"- {', '.join(line_parts)}")

    remaining = max(0, len(hybrid_citations or []) - min(len(hybrid_citations or []), max_citations))
    if remaining > 0:
        lines.append(f"- ... (+{remaining} more cited documents)")

    return lines


def _build_web_citation_history_lines(web_search_citations, max_citations=4):
    lines = []
    for citation in (web_search_citations or [])[:max_citations]:
        if not isinstance(citation, dict):
            continue

        title = str(citation.get('title') or citation.get('url') or 'Web source').strip()
        url = str(citation.get('url') or '').strip()
        if url and url != title:
            lines.append(f"- {title} ({url})")
        else:
            lines.append(f"- {title}")

    remaining = max(0, len(web_search_citations or []) - min(len(web_search_citations or []), max_citations))
    if remaining > 0:
        lines.append(f"- ... (+{remaining} more web sources)")

    return lines


def _parse_json_object_from_text(text):
    """Extract a JSON object from a plain text model response."""
    value = str(text or '').strip()
    if not value:
        return None

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    start_index = value.find('{')
    end_index = value.rfind('}')
    if start_index == -1 or end_index == -1 or end_index <= start_index:
        return None

    try:
        parsed = json.loads(value[start_index:end_index + 1])
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        return None


def _normalize_prior_grounded_document_refs(conversation_item):
    """Return the reusable grounded document set for follow-up turns with search disabled."""
    normalized_refs = []
    seen_refs = set()

    def add_ref(raw_ref):
        if not isinstance(raw_ref, dict):
            return

        document_id = str(raw_ref.get('document_id') or '').strip()
        scope = str(raw_ref.get('scope') or '').strip().lower()
        scope_id = str(
            raw_ref.get('scope_id')
            or raw_ref.get('group_id')
            or raw_ref.get('public_workspace_id')
            or raw_ref.get('user_id')
            or ''
        ).strip()
        if not document_id or not scope or not scope_id:
            return

        ref_key = (scope, scope_id, document_id)
        if ref_key in seen_refs:
            return

        seen_refs.add(ref_key)

        normalized_ref = {
            'document_id': document_id,
            'scope': scope,
            'scope_id': scope_id,
            'file_name': raw_ref.get('file_name') or raw_ref.get('title'),
            'classification': raw_ref.get('classification'),
        }

        if scope == 'group':
            normalized_ref['group_id'] = scope_id
        elif scope == 'public':
            normalized_ref['public_workspace_id'] = scope_id
        else:
            normalized_ref['user_id'] = scope_id

        normalized_refs.append(normalized_ref)

    for raw_ref in (conversation_item or {}).get('last_grounded_document_refs', []) or []:
        add_ref(raw_ref)

    if normalized_refs:
        return normalized_refs

    for tag in (conversation_item or {}).get('tags', []) or []:
        if not isinstance(tag, dict) or tag.get('category') != 'document':
            continue

        scope_info = tag.get('scope') or {}
        add_ref({
            'document_id': tag.get('document_id'),
            'scope': scope_info.get('type'),
            'scope_id': scope_info.get('id'),
            'title': tag.get('title'),
            'classification': tag.get('classification'),
        })

    return normalized_refs


def build_prior_grounded_document_search_parameters(grounded_refs):
    """Translate grounded document refs into bounded search parameters."""
    document_ids = []
    group_ids = []
    public_workspace_ids = []
    scope_types = set()

    for ref in grounded_refs or []:
        if not isinstance(ref, dict):
            continue

        document_id = str(ref.get('document_id') or '').strip()
        if document_id and document_id not in document_ids:
            document_ids.append(document_id)

        scope = str(ref.get('scope') or '').strip().lower()
        if not scope:
            continue
        scope_types.add(scope)

        if scope == 'group':
            group_id = str(ref.get('group_id') or ref.get('scope_id') or '').strip()
            if group_id and group_id not in group_ids:
                group_ids.append(group_id)
        elif scope == 'public':
            public_workspace_id = str(ref.get('public_workspace_id') or ref.get('scope_id') or '').strip()
            if public_workspace_id and public_workspace_id not in public_workspace_ids:
                public_workspace_ids.append(public_workspace_id)

    if len(scope_types) == 1:
        doc_scope = next(iter(scope_types))
    else:
        doc_scope = 'all'

    return {
        'document_ids': document_ids,
        'doc_scope': doc_scope,
        'active_group_ids': group_ids,
        'active_group_id': group_ids[0] if group_ids else None,
        'active_public_workspace_ids': public_workspace_ids,
        'active_public_workspace_id': public_workspace_ids[0] if public_workspace_ids else None,
        'scope_types': sorted(scope_types),
    }


def revalidate_prior_grounded_document_search_parameters(user_id, search_parameters):
    """Filter fallback search parameters to scopes the caller can still access."""
    normalized_parameters = dict(search_parameters or {})
    scope_types = set(normalized_parameters.get('scope_types') or [])
    scope_context = _get_authorized_chat_scope_context(
        user_id,
        active_group_ids=normalized_parameters.get('active_group_ids') or [],
        active_public_workspace_ids=normalized_parameters.get('active_public_workspace_ids') or [],
    )
    allowed_group_ids = scope_context['active_group_ids']
    allowed_public_workspace_ids = scope_context['active_public_workspace_ids']

    allowed_scope_types = []
    if 'personal' in scope_types:
        allowed_scope_types.append('personal')
    if allowed_group_ids:
        allowed_scope_types.append('group')
    if allowed_public_workspace_ids:
        allowed_scope_types.append('public')

    normalized_parameters['active_group_ids'] = allowed_group_ids
    normalized_parameters['active_group_id'] = scope_context['active_group_id']
    normalized_parameters['active_public_workspace_ids'] = allowed_public_workspace_ids
    normalized_parameters['active_public_workspace_id'] = scope_context['active_public_workspace_id']
    normalized_parameters['scope_types'] = allowed_scope_types

    if not allowed_scope_types:
        normalized_parameters['document_ids'] = []
        normalized_parameters['doc_scope'] = None
        return normalized_parameters

    normalized_parameters['doc_scope'] = (
        allowed_scope_types[0] if len(allowed_scope_types) == 1 else 'all'
    )
    return normalized_parameters


def build_history_only_assessment_messages(history_segments, default_system_prompt=''):
    """Construct the prompt context used to decide whether history alone is sufficient."""
    assessment_messages = []
    summary_of_older = str((history_segments or {}).get('summary_of_older') or '').strip()
    if summary_of_older:
        assessment_messages.append({
            'role': 'system',
            'content': (
                f"<Summary of previous conversation context>\n{summary_of_older}\n"
                "</Summary of previous conversation context>"
            )
        })

    normalized_default_system_prompt = str(default_system_prompt or '').strip()
    if normalized_default_system_prompt:
        assessment_messages.append({
            'role': 'system',
            'content': normalized_default_system_prompt,
        })

    assessment_messages.extend((history_segments or {}).get('history_messages', []))
    return assessment_messages


def assess_history_only_answerability(gpt_client, gpt_model, conversation_history_for_api):
    """Return whether the current question can be answered from existing conversation grounding alone."""
    assessment_prompt = (
        "You are evaluating whether the latest user question can be answered using only the "
        "existing conversation context already provided. Earlier assistant turns may include "
        "supporting citation context from previously grounded document answers.\n\n"
        "Respond with JSON only using this schema:\n"
        "{\"can_answer_from_history\": true|false, \"search_query\": \"...\", \"reason\": \"...\"}\n\n"
        "Set can_answer_from_history to true only if the conversation already contains enough "
        "grounded information to answer confidently without retrieving any new document excerpts. "
        "If false, produce a concise standalone search_query that resolves pronouns and omitted "
        "references from the conversation for use against the previously grounded documents. "
        "Keep reason short."
    )

    assessment_messages = [{
        'role': 'system',
        'content': 'Evaluate whether existing conversation context can answer the latest question.',
    }]
    assessment_messages.extend(conversation_history_for_api or [])
    assessment_messages.append({'role': 'user', 'content': assessment_prompt})

    assessment_response = gpt_client.chat.completions.create(
        model=gpt_model,
        messages=assessment_messages,
        max_tokens=180,
        temperature=0,
    )
    response_text = str(assessment_response.choices[0].message.content or '').strip()
    response_payload = _parse_json_object_from_text(response_text) or {}

    can_answer_from_history = response_payload.get('can_answer_from_history')
    if isinstance(can_answer_from_history, str):
        can_answer_from_history = can_answer_from_history.strip().lower() == 'true'
    else:
        can_answer_from_history = bool(can_answer_from_history)

    return {
        'can_answer_from_history': can_answer_from_history,
        'search_query': str(response_payload.get('search_query') or '').strip(),
        'reason': str(response_payload.get('reason') or '').strip(),
        'raw_response': response_text,
    }


def build_history_grounding_system_message():
    """Instruction used when explicit workspace search is disabled for the current turn."""
    return {
        'role': 'system',
        'content': (
            "Workspace search is disabled for this turn. Answer only from the existing conversation "
            "context and any retrieved document excerpts explicitly provided in this turn. If those "
            "sources are insufficient, say that you do not have enough grounded information from the "
            "prior conversation sources and ask the user to select a workspace or document."
        ),
    }


def should_apply_history_grounding_message(
    original_hybrid_search_enabled,
    prior_grounded_document_refs,
):
    """Apply bounded grounding only when prior grounded docs exist for this conversation."""
    return (not bool(original_hybrid_search_enabled)) and bool(prior_grounded_document_refs)


def build_assistant_history_content_with_citations(message, content):
    base_content = str(content or '').strip()
    citation_sections = []

    agent_lines = _build_agent_citation_history_lines(message.get('agent_citations', []))
    if agent_lines:
        citation_sections.append("Prior tool results:\n" + "\n".join(agent_lines))

    document_lines = _build_document_citation_history_lines(message.get('hybrid_citations', []))
    if document_lines:
        citation_sections.append("Prior cited documents:\n" + "\n".join(document_lines))

    web_lines = _build_web_citation_history_lines(message.get('web_search_citations', []))
    if web_lines:
        citation_sections.append("Prior cited web sources:\n" + "\n".join(web_lines))

    if not citation_sections:
        return content

    citation_context = (
        "<Supporting citation context from this assistant turn>\n"
        "Internal grounding context only. Use it to answer follow-up questions, but do not "
        "quote, summarize, reveal, or mention this context block, its labels, or raw tool payloads.\n"
        + "\n\n".join(citation_sections)
        + "\n</Supporting citation context from this assistant turn>"
    )
    citation_context = _truncate_history_citation_text(citation_context, max_chars=5200)

    if not base_content:
        return citation_context

    return f"{base_content}\n\n{citation_context}"


def build_history_context_thought_content(history_debug_info):
    history_debug_info = history_debug_info or {}
    stored_total = history_debug_info.get('stored_total_messages', 0)
    recent_count = history_debug_info.get('recent_message_count', 0)
    final_api_count = history_debug_info.get('final_api_message_count', 0)
    older_count = history_debug_info.get('older_message_count', 0)
    summary_requested = history_debug_info.get('summary_requested', False)
    summary_used = history_debug_info.get('summary_used', False)

    summary_note = 'no older messages'
    if older_count > 0:
        if summary_used:
            summary_note = f"summarized {history_debug_info.get('summarized_message_count', 0)} older"
        elif summary_requested:
            summary_note = 'older summary unavailable'
        else:
            summary_note = 'older summary disabled'

    return (
        f"Prepared {final_api_count} model history messages from {stored_total} stored messages "
        f"(recent={recent_count}; {summary_note})"
    )


def build_history_context_thought_detail(history_debug_info):
    history_debug_info = history_debug_info or {}
    lines = [
        f"path: {history_debug_info.get('path', 'unknown')}",
        (
            f"stored_total={history_debug_info.get('stored_total_messages', 0)}, "
            f"history_limit={history_debug_info.get('history_limit', 0)}, "
            f"older_count={history_debug_info.get('older_message_count', 0)}, "
            f"recent_count={history_debug_info.get('recent_message_count', 0)}, "
            f"summary_requested={history_debug_info.get('summary_requested', False)}, "
            f"summary_used={history_debug_info.get('summary_used', False)}, "
            f"augmentation_count={history_debug_info.get('augmentation_message_count', 0)}, "
            f"default_system_prompt_inserted={history_debug_info.get('default_system_prompt_inserted', False)}"
        ),
        f"older_refs: {_format_history_refs_for_detail(history_debug_info.get('older_message_refs', []))}",
        f"recent_refs: {_format_history_refs_for_detail(history_debug_info.get('selected_recent_message_refs', []))}",
        f"summarized_refs: {_format_history_refs_for_detail(history_debug_info.get('summarized_message_refs', []))}",
        f"skipped_inactive_refs: {_format_history_refs_for_detail(history_debug_info.get('skipped_inactive_message_refs', []))}",
        f"skipped_masked_refs: {_format_history_refs_for_detail(history_debug_info.get('skipped_masked_message_refs', []))}",
        f"masked_range_refs: {_format_history_refs_for_detail(history_debug_info.get('masked_range_message_refs', []))}",
        f"history_segment_refs: {_format_history_refs_for_detail(history_debug_info.get('history_message_source_refs', []))}",
        f"final_api_roles: {_format_history_refs_for_detail(history_debug_info.get('final_api_message_roles', []))}",
        f"final_api_refs: {_format_history_refs_for_detail(history_debug_info.get('final_api_source_refs', []))}",
    ]
    return "\n".join(lines)


def build_history_context_debug_citation(history_debug_info, path_label):
    history_debug_info = dict(history_debug_info or {})
    history_debug_info['path'] = path_label
    return {
        'tool_name': 'Conversation History',
        'function_arguments': json.dumps({
            'path': path_label,
            'stored_total_messages': history_debug_info.get('stored_total_messages', 0),
            'history_limit': history_debug_info.get('history_limit', 0),
            'older_message_count': history_debug_info.get('older_message_count', 0),
            'recent_message_count': history_debug_info.get('recent_message_count', 0),
            'final_api_message_count': history_debug_info.get('final_api_message_count', 0),
            'summary_requested': history_debug_info.get('summary_requested', False),
            'summary_used': history_debug_info.get('summary_used', False),
        }),
        'function_result': build_history_context_thought_detail(history_debug_info),
        'timestamp': datetime.utcnow().isoformat(),
    }


def enrich_history_context_debug_info(
    history_debug_info,
    conversation_history_for_api,
    final_api_source_refs,
    path_label,
    augmentation_message_count=0,
    default_system_prompt_inserted=False,
):
    enriched = dict(history_debug_info or {})
    enriched['path'] = path_label
    enriched['augmentation_message_count'] = augmentation_message_count
    enriched['default_system_prompt_inserted'] = bool(default_system_prompt_inserted)
    enriched['final_api_message_count'] = len(conversation_history_for_api or [])
    enriched['final_api_message_roles'] = [
        str((message or {}).get('role') or 'unknown')
        for message in (conversation_history_for_api or [])
    ]
    enriched['final_api_source_refs'] = _capture_history_refs(final_api_source_refs, max_items=20)
    return enriched


def emit_history_context_debug(history_debug_info, conversation_id):
    debug_payload = history_debug_info or {}
    debug_print(
        f"[History Context][{debug_payload.get('path', 'unknown')}] conversation_id={conversation_id} | "
        f"{json.dumps(debug_payload, default=str)}"
    )


def build_conversation_history_segments(
    all_messages,
    conversation_history_limit,
    enable_summarize_older_messages=False,
    gpt_client=None,
    gpt_model=None,
    user_message_id=None,
    fallback_user_message="",
):
    """Build shared conversation history segments for chat completions."""
    conversation_history_messages = []
    summary_of_older = ""
    chat_tabular_files = set()

    artifact_payload_map = build_message_artifact_payload_map(all_messages or [])
    filtered_messages = filter_assistant_artifact_items(all_messages or [])
    filtered_messages = hydrate_agent_citations_from_artifacts(filtered_messages, artifact_payload_map)
    ordered_messages = sort_messages_by_thread(filtered_messages)

    total_messages = len(ordered_messages)
    num_recent_messages = min(total_messages, conversation_history_limit)
    num_older_messages = total_messages - num_recent_messages

    recent_messages = ordered_messages[-num_recent_messages:] if num_recent_messages else []
    older_messages_to_summarize = ordered_messages[:num_older_messages]

    summarized_message_refs = []
    skipped_inactive_message_refs = []
    skipped_masked_message_refs = []
    masked_range_message_refs = []
    history_message_source_refs = []
    appended_fallback_user_message = False

    if enable_summarize_older_messages and older_messages_to_summarize and gpt_client and gpt_model:
        debug_print(
            f"Summarizing {len(older_messages_to_summarize)} older messages for current conversation history"
        )
        summary_prompt_older = (
            "Summarize the following conversation history concisely (around 50-100 words), "
            "focusing on key facts, decisions, or context that might be relevant for future turns. "
            "Do not add any introductory phrases like 'Here is a summary'.\n\n"
            "Conversation History:\n"
        )
        message_texts_older = []
        for message in older_messages_to_summarize:
            role = message.get('role', 'user')
            metadata = message.get('metadata', {})
            thread_info = metadata.get('thread_info', {})
            active_thread = thread_info.get('active_thread')

            if active_thread is False:
                debug_print(f"[THREAD] Skipping inactive thread message {message.get('id')} from summary")
                skipped_inactive_message_refs.append(_format_history_message_ref(message))
                continue

            if role in ['system', 'safety', 'blocked', 'image', 'file']:
                continue

            content = message.get('content', '')
            if role == 'assistant':
                content = build_assistant_history_content_with_citations(message, content)
            message_texts_older.append(f"{role.upper()}: {content}")
            summarized_message_refs.append(_format_history_message_ref(message))

        if message_texts_older:
            summary_prompt_older += "\n".join(message_texts_older)
            try:
                summary_response_older = gpt_client.chat.completions.create(
                    model=gpt_model,
                    messages=[
                        {"role": "system", "content": "Summarize older conversation context for future chat turns."},
                        {"role": "user", "content": summary_prompt_older},
                    ],
                    max_tokens=150,
                    temperature=0.3,
                )
                summary_of_older = summary_response_older.choices[0].message.content.strip()
                debug_print(f"Generated summary: {summary_of_older}")
            except Exception as exc:
                debug_print(f"Error summarizing older conversation history: {exc}")
                summary_of_older = ""
        else:
            debug_print("No summarizable content found in older messages.")

    allowed_roles_in_history = ['user', 'assistant']
    max_file_content_length_in_history = 50000
    max_tabular_content_length_in_history = 50000

    for message in recent_messages:
        role = message.get('role')
        content = message.get('content')
        metadata = message.get('metadata', {})

        if metadata.get('is_generated_chat_artifact', False):
            history_message_source_refs.append(f"system:hidden_generated_artifact:{message.get('id', 'unknown')}")
            continue

        thread_info = metadata.get('thread_info', {})
        active_thread = thread_info.get('active_thread')
        if active_thread is False:
            debug_print(
                f"[THREAD] Skipping inactive thread message {message.get('id')} "
                f"(thread_id: {thread_info.get('thread_id')}, attempt: {thread_info.get('thread_attempt')})"
            )
            skipped_inactive_message_refs.append(_format_history_message_ref(message))
            continue

        if metadata.get('masked', False):
            debug_print(f"[MASK] Skipping fully masked message {message.get('id')}")
            skipped_masked_message_refs.append(_format_history_message_ref(message))
            continue

        masked_ranges = metadata.get('masked_ranges', [])
        if masked_ranges and content:
            content = remove_masked_content(content, masked_ranges)
            masked_range_message_refs.append(_format_history_message_ref(message))
            debug_print(f"[MASK] Applied {len(masked_ranges)} masked ranges to message {message.get('id')}")

        if role in allowed_roles_in_history:
            if role == 'assistant':
                content = build_assistant_history_content_with_citations(message, content)
            conversation_history_messages.append({"role": role, "content": content})
            history_message_source_refs.append(_format_history_message_ref(message))
        elif role == 'file':
            filename = message.get('filename', 'uploaded_file')
            file_content = message.get('file_content', '')
            is_table = message.get('is_table', False)
            file_content_source = message.get('file_content_source', '')

            if is_table and file_content_source == 'blob':
                chat_tabular_files.add(filename)
                conversation_history_messages.append({
                    'role': 'system',
                    'content': (
                        f"[User uploaded a tabular data file named '{filename}'. "
                        f"The file is stored in blob storage and available for analysis. "
                        f"Use the tabular_processing plugin functions (list_tabular_files, describe_tabular_file, "
                        f"aggregate_column, filter_rows, query_tabular_data, group_by_aggregate, "
                        f"group_by_datetime_component) to analyze this data. "
                        f"The file source is 'chat'.]"
                    )
                })
            else:
                content_limit = (
                    max_tabular_content_length_in_history
                    if is_table else max_file_content_length_in_history
                )
                display_content = file_content[:content_limit]
                if len(file_content) > content_limit:
                    display_content += "..."

                if is_table:
                    conversation_history_messages.append({
                        'role': 'system',
                        'content': (
                            f"[User uploaded a tabular data file named '{filename}'. This is CSV format data for analysis:\n"
                            f"{display_content}]\n"
                            "This is complete tabular data in CSV format. You can perform calculations, analysis, and "
                            "data operations on this dataset."
                        )
                    })
                else:
                    conversation_history_messages.append({
                        'role': 'system',
                        'content': (
                            f"[User uploaded a file named '{filename}'. Content preview:\n{display_content}]\n"
                            "Use this file context if relevant."
                        )
                    })
            history_message_source_refs.append(f"system:file:{message.get('id', 'unknown')}")
        elif role == 'image':
            filename = message.get('filename', 'uploaded_image')
            is_user_upload = metadata.get('is_user_upload', False)

            if is_user_upload:
                extracted_text = message.get('extracted_text', '')
                vision_analysis = message.get('vision_analysis', {})
                image_context_parts = [f"[User uploaded an image named '{filename}'.]"]

                if extracted_text:
                    extracted_preview = extracted_text[:max_file_content_length_in_history]
                    if len(extracted_text) > max_file_content_length_in_history:
                        extracted_preview += "..."
                    image_context_parts.append(f"\n\nExtracted Text (OCR):\n{extracted_preview}")

                if vision_analysis:
                    image_context_parts.append("\n\nAI Vision Analysis:")
                    if vision_analysis.get('description'):
                        image_context_parts.append(f"\nDescription: {vision_analysis['description']}")
                    if vision_analysis.get('objects'):
                        objects_str = ', '.join(vision_analysis['objects'])
                        image_context_parts.append(f"\nObjects detected: {objects_str}")
                    if vision_analysis.get('text'):
                        image_context_parts.append(f"\nText visible in image: {vision_analysis['text']}")
                    if vision_analysis.get('contextual_analysis'):
                        image_context_parts.append(
                            f"\nContextual analysis: {vision_analysis['contextual_analysis']}"
                        )

                image_context_content = ''.join(image_context_parts)
                image_context_content += "\n\nUse this image information to answer questions about the uploaded image."

                if 'data:image/' in image_context_content or ';base64,' in image_context_content:
                    debug_print(
                        f"WARNING: Base64 image data detected in chat history for {filename}! Removing to save tokens."
                    )
                    image_context_content = (
                        f"[User uploaded an image named '{filename}' - image data excluded from chat history to conserve tokens]"
                    )

                debug_print(
                    f"[IMAGE_CONTEXT] Adding user-uploaded image to history: {filename}, "
                    f"context length: {len(image_context_content)} chars"
                )
                conversation_history_messages.append({
                    'role': 'system',
                    'content': image_context_content,
                })
            else:
                prompt = message.get('prompt', 'User requested image generation.')
                debug_print(f"[IMAGE_CONTEXT] Adding system-generated image to history: {prompt[:100]}...")
                conversation_history_messages.append({
                    'role': 'system',
                    'content': f"[Assistant generated an image based on the prompt: '{prompt}']",
                })

            history_message_source_refs.append(f"system:image:{message.get('id', 'unknown')}")

    if not conversation_history_messages or conversation_history_messages[-1].get('role') != 'user':
        debug_print("Warning: Last message in history is not the user's current message. Appending.")
        user_msg_found = False
        for message in reversed(recent_messages):
            if message.get('role') != 'user':
                continue
            if user_message_id and message.get('id') != user_message_id:
                continue
            conversation_history_messages.append({
                'role': 'user',
                'content': message.get('content', ''),
            })
            history_message_source_refs.append(_format_history_message_ref(message))
            user_msg_found = True
            break

        if not user_msg_found and fallback_user_message:
            conversation_history_messages.append({
                'role': 'user',
                'content': fallback_user_message,
            })
            history_message_source_refs.append('user:fallback_input')
            appended_fallback_user_message = True

    debug_info = {
        'history_limit': conversation_history_limit,
        'summary_requested': bool(enable_summarize_older_messages),
        'summary_used': bool(summary_of_older),
        'stored_total_messages': total_messages,
        'older_message_count': len(older_messages_to_summarize),
        'recent_message_count': len(recent_messages),
        'summarized_message_count': len(summarized_message_refs),
        'older_message_refs': _capture_history_refs(
            [_format_history_message_ref(message) for message in older_messages_to_summarize]
        ),
        'selected_recent_message_refs': _capture_history_refs(
            [_format_history_message_ref(message) for message in recent_messages]
        ),
        'summarized_message_refs': _capture_history_refs(summarized_message_refs),
        'skipped_inactive_message_refs': _capture_history_refs(skipped_inactive_message_refs),
        'skipped_masked_message_refs': _capture_history_refs(skipped_masked_message_refs),
        'masked_range_message_refs': _capture_history_refs(masked_range_message_refs),
        'history_message_source_refs': _capture_history_refs(history_message_source_refs, max_items=20),
        'appended_fallback_user_message': appended_fallback_user_message,
    }

    return {
        'summary_of_older': summary_of_older,
        'history_messages': conversation_history_messages,
        'chat_tabular_files': chat_tabular_files,
        'debug_info': debug_info,
    }


def _extract_web_search_citations_from_content(content: str) -> List[Dict[str, str]]:
    if not content:
        return []
    debug_print(f"[Citation Extraction] Extracting citations from:\n{content}\n")

    citations: List[Dict[str, str]] = []

    markdown_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\s\)]+)(?:\s+\"([^\"]+)\")?\)")
    html_pattern = re.compile(
        r"<a[^>]+href=\"(https?://[^\"]+)\"([^>]*)>(.*?)</a>",
        re.IGNORECASE | re.DOTALL,
    )
    title_pattern = re.compile(r"title=\"([^\"]+)\"", re.IGNORECASE)
    url_pattern = re.compile(r"https?://[^\s\)\]\">]+")

    occupied_spans: List[range] = []

    for match in markdown_pattern.finditer(content):
        text, url, title = match.groups()
        url = (url or "").strip().rstrip(".,)")
        if not url:
            continue
        display_title = (title or text or url).strip()
        citations.append({"url": url, "title": display_title})
        occupied_spans.append(range(match.start(), match.end()))

    for match in html_pattern.finditer(content):
        url, attrs, inner = match.groups()
        url = (url or "").strip().rstrip(".,)")
        if not url:
            continue
        title_match = title_pattern.search(attrs or "")
        title = title_match.group(1) if title_match else None
        inner_text = re.sub(r"<[^>]+>", "", inner or "").strip()
        display_title = (title or inner_text or url).strip()
        citations.append({"url": url, "title": display_title})
        occupied_spans.append(range(match.start(), match.end()))

    for match in url_pattern.finditer(content):
        if any(match.start() in span for span in occupied_spans):
            continue
        url = (match.group(0) or "").strip().rstrip(".,)")
        if not url:
            continue
        citations.append({"url": url, "title": url})
    debug_print(f"[Citation Extraction] Extracted {len(citations)} citations. - {citations}\n")

    return citations


def _append_source_review_web_citation(web_search_citations_list, raw_citation, source_label='web_search'):
    """Append a normalized URL citation for Source Review seed discovery."""
    if not isinstance(web_search_citations_list, list):
        return False
    serializable = make_json_serializable(raw_citation)
    if not isinstance(serializable, dict):
        serializable = {'url': str(raw_citation or '')}

    raw_url = serializable.get('url') or serializable.get('href') or serializable.get('link')
    normalized_url, _reason = normalize_review_url(raw_url)
    if not normalized_url:
        return False

    existing_urls = set()
    for existing_citation in web_search_citations_list:
        if not isinstance(existing_citation, dict):
            continue
        existing_url, _existing_reason = normalize_review_url(
            existing_citation.get('url') or existing_citation.get('href') or existing_citation.get('link')
        )
        if existing_url:
            existing_urls.add(existing_url)
    if normalized_url in existing_urls:
        return False

    citation_title = (
        serializable.get('title')
        or serializable.get('name')
        or serializable.get('tool_name')
        or normalized_url
    )
    web_search_citations_list.append({
        'url': normalized_url,
        'title': str(citation_title or normalized_url).strip()[:300],
        'source': source_label,
    })
    return True


def _extract_token_usage_from_metadata(metadata: Dict[str, Any]) -> Dict[str, int]:
    if not isinstance(metadata, Mapping):
        debug_print(
            "[Web Search][Token Usage Extraction] Metadata is not a mapping. "
            f"type={type(metadata)}"
        )
        return {}

    usage = metadata.get("usage")
    if not usage:
        debug_print("[Web Search][Token Usage Extraction] No usage field found in metadata.")
        return {}

    if isinstance(usage, str):
        raw_usage = usage.strip()
        if not raw_usage:
            debug_print("[Web Search][Token Usage Extraction] Usage string was empty.")
            return {}
        try:
            usage = json.loads(raw_usage)
        except json.JSONDecodeError:
            try:
                usage = ast.literal_eval(raw_usage)
            except (ValueError, SyntaxError):
                debug_print(
                    "[Web Search][Token Usage Extraction] Failed to parse usage string."
                )
                return {}

    if not isinstance(usage, Mapping):
        debug_print(
            "[Web Search][Token Usage Extraction] Usage is not a mapping. "
            f"type={type(usage)}"
        )
        return {}

    def to_int(value: Any) -> Optional[int]:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    total_tokens = to_int(usage.get("total_tokens"))
    if total_tokens is None:
        debug_print(
            "[Web Search][Token Usage Extraction] total_tokens missing or invalid. "
            f"usage={usage}"
        )
        return {}

    prompt_tokens = to_int(usage.get("prompt_tokens")) or 0
    completion_tokens = to_int(usage.get("completion_tokens")) or 0
    debug_print(
        "[Web Search][Token Usage Extraction] Extracted token usage - "
        f"prompt: {prompt_tokens}, completion: {completion_tokens}, total: {total_tokens}"
    )

    return {
        "total_tokens": int(total_tokens),
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
    }


def build_web_search_query_text(user_message):
    """Return the only chat content allowed to leave the app for external web search."""
    return str(user_message or "").strip()


def perform_research_web_searches(
    *,
    settings,
    conversation_id,
    user_id,
    user_message,
    user_message_id,
    chat_type,
    document_scope,
    active_group_id,
    active_public_workspace_id,
    web_search_query_text,
    system_messages_for_augmentation,
    agent_citations_list,
    web_search_citations_list,
    deep_research_enabled=False,
    deep_research_planner_client=None,
    deep_research_planner_model=None,
):
    """Run one or more current-message-only web searches for normal or Deep Research mode."""
    web_search_runs = []
    query_plan = {}

    if deep_research_enabled:
        query_plan = build_deep_research_query_plan(
            settings=settings,
            user_message=user_message,
            base_query=web_search_query_text,
            planner_client=deep_research_planner_client,
            planner_model=deep_research_planner_model,
        )
        planned_queries = query_plan.get('queries') or []
    else:
        planned_queries = [{
            'query': web_search_query_text,
            'reason': 'Original current-message web search',
            'source': 'base',
        }]

    if not planned_queries:
        planned_queries = [{
            'query': web_search_query_text,
            'reason': 'Original current-message web search',
            'source': 'base',
        }]

    total_queries = len(planned_queries)
    for query_index, query_item in enumerate(planned_queries, start=1):
        if not isinstance(query_item, dict):
            continue
        query_text = str(query_item.get('query') or '').strip()
        if not query_text:
            continue
        search_label = None
        if deep_research_enabled:
            search_label = f"Deep Research query {query_index}/{total_queries}"
        perform_web_search(
            settings=settings,
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=user_message,
            user_message_id=user_message_id,
            chat_type=chat_type,
            document_scope=document_scope,
            active_group_id=active_group_id,
            active_public_workspace_id=active_public_workspace_id,
            web_search_query_text=query_text,
            system_messages_for_augmentation=system_messages_for_augmentation,
            agent_citations_list=agent_citations_list,
            web_search_citations_list=web_search_citations_list,
            web_search_runs_list=web_search_runs,
            search_context_label=search_label,
        )

    return {
        'query_plan': query_plan,
        'web_search_runs': web_search_runs,
    }

def perform_web_search(
    *,
    settings,
    conversation_id,
    user_id,
    user_message,
    user_message_id,
    chat_type,
    document_scope,
    active_group_id,
    active_public_workspace_id,
    web_search_query_text,
    system_messages_for_augmentation,
    agent_citations_list,
    web_search_citations_list,
    web_search_runs_list=None,
    search_context_label=None,
):
    debug_print("[WebSearch] ========== ENTERING perform_web_search ==========")
    debug_print(f"[WebSearch] Parameters received:")
    debug_print(f"[WebSearch]   conversation_id: {conversation_id}")
    debug_print(f"[WebSearch]   user_id: {user_id}")
    debug_print(f"[WebSearch]   user_message: {user_message[:100] if user_message else None}...")
    debug_print(f"[WebSearch]   user_message_id: {user_message_id}")
    debug_print(f"[WebSearch]   chat_type: {chat_type}")
    debug_print(f"[WebSearch]   document_scope: {document_scope}")
    debug_print(f"[WebSearch]   active_group_id: {active_group_id}")
    debug_print(f"[WebSearch]   active_public_workspace_id: {active_public_workspace_id}")
    debug_print(
        "[WebSearch]   web_search_query_text: "
        f"{web_search_query_text[:100] if web_search_query_text else None}..."
    )

    initial_seed_url_count = len(web_search_citations_list or []) if isinstance(web_search_citations_list, list) else 0
    run_started_at = datetime.utcnow().isoformat()

    def record_web_search_run(success, status, error=None, result_message_length=0, raw_citation_count=0):
        if not isinstance(web_search_runs_list, list):
            return
        final_seed_url_count = len(web_search_citations_list or []) if isinstance(web_search_citations_list, list) else initial_seed_url_count
        web_search_runs_list.append({
            'query': str(web_search_query_text or user_message or '').strip()[:300],
            'label': str(search_context_label or '').strip()[:100],
            'status': status,
            'success': bool(success),
            'started_at': run_started_at,
            'completed_at': datetime.utcnow().isoformat(),
            'seed_url_count_before': initial_seed_url_count,
            'seed_url_count_after': final_seed_url_count,
            'new_seed_url_count': max(0, final_seed_url_count - initial_seed_url_count),
            'result_message_length': int(result_message_length or 0),
            'raw_citation_count': int(raw_citation_count or 0),
            'error': str(error or '')[:500],
        })

    enable_web_search = settings.get("enable_web_search")
    debug_print(f"[WebSearch] enable_web_search setting: {enable_web_search}")

    if not enable_web_search:
        debug_print("[WebSearch] Web search is DISABLED in settings, returning early")
        record_web_search_run(True, 'disabled')
        return True  # Not an error, just disabled

    web_search_agent = settings.get("web_search_agent") or {}
    debug_print(f"[WebSearch] web_search_agent config present: {bool(web_search_agent)}")
    if web_search_agent:
        # Avoid logging sensitive data, just log structure
        debug_print(f"[WebSearch]   web_search_agent keys: {list(web_search_agent.keys())}")

    other_settings = web_search_agent.get("other_settings") or {}
    debug_print(f"[WebSearch] other_settings keys: {list(other_settings.keys()) if other_settings else '<empty>'}")

    foundry_settings = other_settings.get("azure_ai_foundry") or {}
    debug_print(f"[WebSearch] foundry_settings present: {bool(foundry_settings)}")
    if foundry_settings:
        # Log only non-sensitive keys
        safe_keys = ['agent_id', 'project_id', 'endpoint']
        safe_info = {k: foundry_settings.get(k, '<not set>') for k in safe_keys}
        debug_print(f"[WebSearch]   foundry_settings (safe keys): {safe_info}")

    agent_id = (foundry_settings.get("agent_id") or "").strip()
    debug_print(f"[WebSearch] Extracted agent_id: '{agent_id}'")

    if not agent_id:
        log_event(
            "[WebSearch] Skipping Foundry web search: agent_id is not configured",
            extra={
                "conversation_id": conversation_id,
                "user_id": user_id,
            },
            level=logging.WARNING,
        )
        debug_print("[WebSearch] Foundry agent_id not configured, skipping web search.")
        # Add failure message so the model knows search was requested but not configured
        system_messages_for_augmentation.append({
            "role": "system",
            "content": "Web search was requested but is not properly configured. Please inform the user that web search is currently unavailable and you cannot provide real-time information. Do not attempt to answer questions requiring current information from your training data.",
        })
        record_web_search_run(False, 'agent_not_configured', error='agent_id_not_configured')
        return False  # Configuration error

    debug_print(f"[WebSearch] Agent ID is configured: {agent_id}")

    query_text = (web_search_query_text or user_message or "").strip()
    debug_print(f"[WebSearch] Final query_text after fallback: '{query_text[:100] if query_text else ''}'")

    if not query_text:
        debug_print("[WebSearch] Query text is EMPTY after processing, skipping web search")
        log_event(
            "[WebSearch] Skipping Foundry web search: empty query",
            extra={
                "conversation_id": conversation_id,
                "user_id": user_id,
            },
            level=logging.WARNING,
        )
        record_web_search_run(True, 'empty_query')
        return True  # Not an error, just empty query

    search_request_content = build_research_search_prompt(query_text)
    debug_print(f"[WebSearch] Building message history with query: {query_text[:100]}...")
    message_history = [
        ChatMessageContent(role="user", content=search_request_content)
    ]
    debug_print(f"[WebSearch] Message history created with {len(message_history)} message(s)")

    try:
        foundry_metadata = {}
        debug_print("[WebSearch] Foundry metadata prepared: {}")

        debug_print("[WebSearch] Calling execute_foundry_agent...")
        debug_print(f"[WebSearch]   foundry_settings keys: {list(foundry_settings.keys())}")
        debug_print(f"[WebSearch]   global_settings type: {type(settings)}")

        result = asyncio.run(
            execute_foundry_agent(
                foundry_settings=foundry_settings,
                global_settings=settings,
                message_history=message_history,
                metadata={k: v for k, v in foundry_metadata.items() if v is not None},
            )
        )
    except FoundryAgentInvocationError as exc:
        log_event(
            f"[WebSearch] Foundry agent invocation failed: {exc}",
            extra={
                "conversation_id": conversation_id,
                "user_id": user_id,
                "agent_id": agent_id,
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        # Add failure message so the model informs the user
        system_messages_for_augmentation.append({
            "role": "system",
            "content": f"Web search failed with error: {exc}. Please inform the user that the web search encountered an error and you cannot provide real-time information for this query. Do not attempt to answer questions requiring current information from your training data - instead, acknowledge the search failure and suggest the user try again.",
        })
        record_web_search_run(False, 'foundry_invocation_error', error=str(exc))
        return False  # Search failed
    except Exception as exc:
        log_event(
            f"[WebSearch] Unexpected error invoking Foundry agent: {exc}",
            extra={
                "conversation_id": conversation_id,
                "user_id": user_id,
                "agent_id": agent_id,
            },
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        # Add failure message so the model informs the user
        system_messages_for_augmentation.append({
            "role": "system",
            "content": f"Web search failed with an unexpected error: {exc}. Please inform the user that the web search encountered an error and you cannot provide real-time information for this query. Do not attempt to answer questions requiring current information from your training data - instead, acknowledge the search failure and suggest the user try again.",
        })
        record_web_search_run(False, 'unexpected_error', error=str(exc))
        return False  # Search failed

    debug_print("[WebSearch] ========== FOUNDRY AGENT RESULT ==========")
    debug_print(f"[WebSearch] Result type: {type(result)}")
    debug_print(f"[WebSearch] Result has message: {bool(result.message)}")
    debug_print(f"[WebSearch] Result has citations: {bool(result.citations)}")
    debug_print(f"[WebSearch] Result has metadata: {bool(result.metadata)}")
    debug_print(f"[WebSearch] Result model: {getattr(result, 'model', 'N/A')}")

    if result.message:
        debug_print(f"[WebSearch] Result message length: {len(result.message)} chars")
        debug_print(f"[WebSearch] Result message preview: {result.message[:500] if len(result.message) > 500 else result.message}")
    else:
        debug_print("[WebSearch] Result message is EMPTY or None")

    if result.citations:
        debug_print(f"[WebSearch] Result citations count: {len(result.citations)}")
        for i, cit in enumerate(result.citations[:3]):
            debug_print(f"[WebSearch]   Citation {i}: {json.dumps(cit, default=str)[:200]}...")
    else:
        debug_print("[WebSearch] Result citations is EMPTY or None")

    if result.metadata:
        try:
            metadata_payload = json.dumps(result.metadata, default=str)
        except (TypeError, ValueError):
            metadata_payload = str(result.metadata)
        debug_print(f"[WebSearch] Foundry metadata: {metadata_payload}")
    else:
        debug_print("[WebSearch] Foundry metadata: <empty>")

    if result.message:
        debug_print("[WebSearch] Adding result message to system_messages_for_augmentation")
        result_heading = "Web search results"
        if search_context_label:
            result_heading = f"Web search results ({search_context_label})"
        system_messages_for_augmentation.append({
            "role": "system",
            "content": f"{result_heading}:\n{result.message}",
        })
        debug_print(f"[WebSearch] Added system message to augmentation list. Total augmentation messages: {len(system_messages_for_augmentation)}")

        debug_print("[WebSearch] Extracting web citations from result message...")
        web_citations = _extract_web_search_citations_from_content(result.message)
        debug_print(f"[WebSearch] Extracted {len(web_citations)} web citations from message content")
        if web_citations:
            appended_message_citations = 0
            for web_citation in web_citations:
                if _append_source_review_web_citation(
                    web_search_citations_list,
                    web_citation,
                    source_label='web_search_message',
                ):
                    appended_message_citations += 1
            debug_print(f"[WebSearch] Total web_search_citations_list now has {len(web_search_citations_list)} citations")
            debug_print(f"[WebSearch] Added {appended_message_citations} message citation(s) for Source Review")
        else:
            debug_print("[WebSearch] No web citations extracted from message content")
    else:
        debug_print("[WebSearch] No result.message to process for augmentation")

    citations = result.citations or []
    debug_print(f"[WebSearch] Processing {len(citations)} citations from result.citations")
    if citations:
        for i, citation in enumerate(citations):
            debug_print(f"[WebSearch] Processing citation {i}: {json.dumps(citation, default=str)[:200]}...")
            serializable = make_json_serializable(citation)
            if not isinstance(serializable, dict):
                serializable = {"value": str(citation)}
            citation_title = serializable.get("title") or serializable.get("url") or "Web search source"
            debug_print(f"[WebSearch] Adding agent citation with title: {citation_title}")
            agent_citations_list.append({
                "tool_name": citation_title,
                "function_name": "azure_ai_foundry_web_search",
                "plugin_name": "azure_ai_foundry",
                "function_arguments": serializable,
                "function_result": serializable,
                "timestamp": datetime.utcnow().isoformat(),
                "success": True,
            })
            _append_source_review_web_citation(
                web_search_citations_list,
                serializable,
                source_label='foundry_citation',
            )
        debug_print(f"[WebSearch] Total agent_citations_list now has {len(agent_citations_list)} citations")
        debug_print(f"[WebSearch] Total Source Review citation seeds now has {len(web_search_citations_list)} citations")
    else:
        debug_print("[WebSearch] No citations in result.citations to process")

    debug_print(f"[WebSearch] Starting token usage extraction from Foundry metadata. Metadata: {result.metadata}")
    token_usage = _extract_token_usage_from_metadata(result.metadata or {})
    if token_usage.get("total_tokens"):
        try:
            workspace_type = 'personal'
            if active_public_workspace_id:
                workspace_type = 'public'
            elif active_group_id:
                workspace_type = 'group'

            log_token_usage(
                user_id=user_id,
                token_type='web_search',
                total_tokens=token_usage.get('total_tokens', 0),
                model=result.model or 'azure-ai-foundry-web-search',
                workspace_type=workspace_type,
                prompt_tokens=token_usage.get('prompt_tokens'),
                completion_tokens=token_usage.get('completion_tokens'),
                conversation_id=conversation_id,
                message_id=user_message_id,
                group_id=active_group_id,
                public_workspace_id=active_public_workspace_id,
                additional_context={
                    'agent_id': agent_id,
                    'search_query': query_text,
                    'token_source': 'foundry_metadata'
                }
            )
        except Exception as log_error:
            log_event(
                f"[WebSearch] Failed to log web search token usage: {log_error}",
                extra={
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "agent_id": agent_id,
                },
                level=logging.WARNING,
            )

    debug_print("[WebSearch] ========== FINAL SUMMARY ==========")
    debug_print(f"[WebSearch] system_messages_for_augmentation count: {len(system_messages_for_augmentation)}")
    debug_print(f"[WebSearch] agent_citations_list count: {len(agent_citations_list)}")
    debug_print(f"[WebSearch] web_search_citations_list count: {len(web_search_citations_list)}")
    debug_print(f"[WebSearch] Token usage extracted: {token_usage}")
    debug_print("[WebSearch] ========== EXITING perform_web_search ==========")

    log_event(
        "[WebSearch] Foundry web search invocation complete",
        extra={
            "conversation_id": conversation_id,
            "user_id": user_id,
            "agent_id": agent_id,
            "citation_count": len(citations),
        },
        level=logging.INFO,
    )
    record_web_search_run(
        True,
        'completed',
        result_message_length=len(result.message or ''),
        raw_citation_count=len(citations),
    )

    return True  # Search succeeded
