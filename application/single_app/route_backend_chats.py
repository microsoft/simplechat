# route_backend_chats.py
from semantic_kernel import Kernel
from semantic_kernel.agents.runtime import InProcessRuntime
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.contents.chat_message_content import ChatMessageContent
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import AzureChatPromptExecutionSettings
from semantic_kernel_fact_memory_store import FactMemoryStore
from semantic_kernel_loader import initialize_semantic_kernel
from semantic_kernel_plugins.plugin_invocation_thoughts import (
    format_plugin_invocation_thought,
    register_plugin_invocation_thought_callback,
)
from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
from foundry_agent_runtime import FoundryAgentInvocationError, execute_foundry_agent, resolve_authority
import builtins
import asyncio, types
import ast
import inspect
import json
import os
import app_settings_cache
import queue
import re
import traceback
from urllib.parse import urlparse
import threading
from typing import Any, Dict, List, Mapping, Optional
from config import *
from flask import Response, copy_current_request_context, g, stream_with_context
from functions_authentication import *
from functions_search import *
from functions_settings import *
from functions_agents import get_agent_id_by_name
from functions_group import find_group_by_id, get_group_model_endpoints, get_user_role_in_group
from functions_chat import *
from functions_conversation_metadata import collect_conversation_metadata, update_conversation_with_metadata
from functions_conversation_unread import mark_conversation_unread
from functions_debug import debug_print
from functions_notifications import create_chat_response_notification
from functions_activity_logging import log_chat_activity, log_conversation_creation, log_token_usage
from flask import current_app
from swagger_wrapper import swagger_route, get_auth_security
from azure.identity import ClientSecretCredential, DefaultAzureCredential, get_bearer_token_provider
from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper
from functions_message_artifacts import (
    build_agent_citation_artifact_documents,
    build_message_artifact_payload_map,
    filter_assistant_artifact_items,
    hydrate_agent_citations_from_artifacts,
)
from functions_thoughts import ThoughtTracker


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


def get_tabular_discovery_function_names():
    """Return discovery-oriented tabular function names from the plugin."""
    from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

    return TabularProcessingPlugin.get_discovery_function_names()


def get_tabular_analysis_function_names():
    """Return analytical tabular function names from the plugin."""
    from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

    return TabularProcessingPlugin.get_analysis_function_names()


def get_tabular_thought_excluded_parameter_names():
    """Return tabular parameter names hidden from thought details."""
    from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

    return TabularProcessingPlugin.get_thought_excluded_parameter_names()


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


def build_tabular_computed_results_system_message(source_label, tabular_analysis):
    """Build the outer-model handoff message for successful tabular analysis."""
    rendered_analysis = str(tabular_analysis or '').strip()
    max_handoff_chars = 24000
    if len(rendered_analysis) > max_handoff_chars:
        rendered_analysis = (
            rendered_analysis[:max_handoff_chars]
            + "\n[Computed results handoff truncated for prompt budget.]"
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
    )


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

    def __init__(self, max_queue_size=200):
        self._queue = queue.Queue(maxsize=max_queue_size)
        self._sentinel = object()
        self._consumer_attached = True
        self._state_lock = threading.Lock()

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

                yield ': keep-alive\n\n'
                continue

            if next_item is self._sentinel:
                break
            yield next_item

    def detach_consumer(self):
        """Stop queueing new events once the HTTP consumer disconnects."""
        with self._state_lock:
            already_detached = not self._consumer_attached
            self._consumer_attached = False

        if already_detached:
            return

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

    def _build_metadata(self, active):
        return {
            'user_id': self.user_id,
            'conversation_id': self.conversation_id,
            'active': bool(active),
            'heartbeat_interval_seconds': self.heartbeat_interval_seconds,
            'updated_at': datetime.utcnow().isoformat(),
        }

    def initialize(self):
        """Initialize the stream session cache state for a new live response."""
        app_settings_cache.initialize_stream_session_cache(
            self.cache_key,
            self._build_metadata(active=True),
            ttl_seconds=self.session_ttl_seconds,
        )

    def publish(self, event_text):
        """Append an SSE event to the replay history and notify listeners."""
        if event_text is None:
            return False

        with self._condition:
            if not self._accepting_events:
                return False

        payload = _extract_sse_event_payload(event_text)
        is_terminal_event = isinstance(payload, dict) and (payload.get('done') or payload.get('error'))

        app_settings_cache.append_stream_session_event(
            self.cache_key,
            event_text,
            ttl_seconds=self.session_ttl_seconds,
        )
        app_settings_cache.set_stream_session_meta(
            self.cache_key,
            self._build_metadata(active=not is_terminal_event),
            ttl_seconds=self.session_ttl_seconds,
        )

        with self._condition:
            self._condition.notify_all()
            return True

    def close(self):
        """Mark the session as closed once the worker has no more events."""
        with self._condition:
            self._accepting_events = False
            self._condition.notify_all()

        app_settings_cache.set_stream_session_meta(
            self.cache_key,
            self._build_metadata(active=False),
            ttl_seconds=self.session_ttl_seconds,
        )

    def is_active(self):
        metadata = app_settings_cache.get_stream_session_meta(self.cache_key) or {}
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


def parse_tabular_reviewer_plan(review_text):
    """Parse a JSON-only LLM reviewer plan into executable call descriptors."""
    payload = extract_json_object_from_text(review_text)
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
        'visible excerpt you provided',
        'if those tool-backed results exist',
        'allow me to query again',
        'can outline what i would retrieve',
    )
    return any(phrase in normalized_analysis for phrase in inaccessible_phrases)


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
                                   tabular_file_contexts=None):
    """Run lightweight SK with TabularProcessingPlugin to analyze tabular data.

    Creates a temporary Kernel with only the TabularProcessingPlugin, uses the
    same chat model as the user's session, and returns computed analysis results.
    Returns None on failure for graceful degradation.
    """
    from semantic_kernel import Kernel as SKKernel
    from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
    from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
    from semantic_kernel.connectors.ai.open_ai.prompt_execution_settings.azure_chat_prompt_execution_settings import AzureChatPromptExecutionSettings
    from semantic_kernel.contents.chat_history import ChatHistory as SKChatHistory
    from semantic_kernel_plugins.tabular_processing_plugin import TabularProcessingPlugin

    try:
        plugin_logger = get_plugin_logger()
        execution_mode = execution_mode if execution_mode in {'analysis', 'schema_summary', 'entity_lookup'} else 'analysis'
        schema_summary_mode = execution_mode == 'schema_summary'
        entity_lookup_mode = execution_mode == 'entity_lookup'
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

        # 1. Create lightweight kernel with only tabular plugin
        kernel = SKKernel()
        tabular_plugin = TabularProcessingPlugin()
        kernel.add_plugin(tabular_plugin, plugin_name="tabular_processing")

        # 2. Create chat service using same config as main chat
        enable_gpt_apim = settings.get('enable_gpt_apim', False)
        if enable_gpt_apim:
            chat_service = AzureChatCompletion(
                service_id="tabular-analysis",
                deployment_name=gpt_model,
                endpoint=settings.get('azure_apim_gpt_endpoint'),
                api_key=settings.get('azure_apim_gpt_subscription_key'),
                api_version=settings.get('azure_apim_gpt_api_version'),
            )
        else:
            auth_type = settings.get('azure_openai_gpt_authentication_type')
            if auth_type == 'managed_identity':
                token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
                chat_service = AzureChatCompletion(
                    service_id="tabular-analysis",
                    deployment_name=gpt_model,
                    endpoint=settings.get('azure_openai_gpt_endpoint'),
                    api_version=settings.get('azure_openai_gpt_api_version'),
                    ad_token_provider=token_provider,
                )
            else:
                chat_service = AzureChatCompletion(
                    service_id="tabular-analysis",
                    deployment_name=gpt_model,
                    endpoint=settings.get('azure_openai_gpt_endpoint'),
                    api_key=settings.get('azure_openai_gpt_key'),
                    api_version=settings.get('azure_openai_gpt_api_version'),
                )
        kernel.add_service(chat_service)

        # 3. Pre-dispatch: load file schemas to eliminate discovery LLM rounds
        source_context = build_tabular_analysis_source_context(
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
        if allow_multi_sheet_discovery:
            allowed_function_names = ['describe_tabular_file'] + allowed_function_names
        allowed_function_filters = {
            'included_functions': [
                f"tabular_processing-{function_name}"
                for function_name in allowed_function_names
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
                    "15. Do not mention hypothetical follow-up analyses, parser errors, or failed attempts unless the user explicitly asked about failures and you have actual tool error output to report."
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
                f"{recovery_sheet_feedback}"
                f"{sheet_hint_feedback}"
                f"{related_sheet_feedback}"
                f"{cross_sheet_bridge_feedback}"
                f"{discovery_step_feedback}"
                f"{missing_sheet_feedback}"
                f"FILE SCHEMAS:\n"
                f"{schema_context}\n\n"
                f"AVAILABLE FUNCTIONS: {', '.join(allowed_function_names)} for year/quarter/month/week/day/hour trend analysis.\n\n"
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
                "25. Do not mention hypothetical follow-up analyses, parser errors, or failed attempts unless the user explicitly asked about failures and you have actual tool error output to report.\n"
                "26. When using query_tabular_data, use simple DataFrame.query() syntax with backticked column names for columns containing spaces. Avoid method calls such as .str.lower(), .astype(...), or other Python expressions that DataFrame.query() may reject."
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

        for attempt_number in range(1, 4):
            force_tool_use = attempt_number > 1 or (attempt_number == 1 and analysis_requires_immediate_tool_choice)
            # 4. Build chat history with pre-loaded schemas
            chat_history = SKChatHistory()
            chat_history.add_system_message(build_system_prompt(
                force_tool_use=force_tool_use,
                tool_error_messages=previous_tool_error_messages,
                execution_gap_messages=previous_execution_gap_messages,
                discovery_feedback_messages=previous_discovery_feedback_messages,
            ))

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
                        maximum_auto_invoke_attempts=8,
                        filters=allowed_function_filters,
                    )
                    if force_tool_use else
                    FunctionChoiceBehavior.Auto(
                        maximum_auto_invoke_attempts=7,
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

                        if entity_lookup_mode:
                            selected_sheets = get_tabular_invocation_selected_sheets(successful_analytical_invocations)
                            execution_gap_messages = []

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

                            if is_tabular_access_limited_analysis(analysis):
                                execution_gap_messages.append(
                                    'Previous attempt still claimed the requested data was unavailable even though analytical tool calls succeeded. Use the returned rows and answer directly.'
                                )

                            if execution_gap_messages and attempt_number < 3:
                                previous_execution_gap_messages = execution_gap_messages
                                log_event(
                                    f"[Tabular SK Analysis] Attempt {attempt_number} entity lookup was incomplete despite successful tool calls; retrying",
                                    extra={
                                        'selected_sheets': selected_sheets,
                                        'execution_gaps': previous_execution_gap_messages,
                                        'successful_tool_count': len(successful_analytical_invocations),
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

    def make_json_serializable(obj):
        if obj is None:
            return None
        elif isinstance(obj, (str, int, float, bool)):
            return obj
        elif isinstance(obj, dict):
            return {str(k): make_json_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [make_json_serializable(item) for item in obj]
        else:
            return str(obj)

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
        tool_name = f"{inv.plugin_name}.{inv.function_name}"
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
                                                 document_scope='personal', active_group_id=None,
                                                 active_public_workspace_id=None):
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
            doc_query = (
                "SELECT TOP 1 c.file_name, c.title, c.group_id, c.public_workspace_id "
                "FROM c WHERE c.id = @doc_id "
                "ORDER BY c.version DESC"
            )
            doc_params = [{"name": "@doc_id", "value": doc_id}]

            for source_hint, cosmos_container in get_document_containers_for_scope(document_scope):
                doc_results = list(cosmos_container.query_items(
                    query=doc_query,
                    parameters=doc_params,
                    enable_cross_partition_query=True
                ))

                if not doc_results:
                    continue

                doc_info = doc_results[0]
                file_context = build_tabular_file_context(
                    doc_info.get('file_name') or doc_info.get('title'),
                    source_hint=source_hint,
                    group_id=doc_info.get('group_id') or active_group_id,
                    public_workspace_id=doc_info.get('public_workspace_id') or active_public_workspace_id,
                )
                if file_context:
                    tabular_file_contexts.append(file_context)
                break
        except Exception as e:
            log_event(
                f"[Tabular SK Analysis] Failed to resolve selected document '{doc_id}': {e}",
                level=logging.WARNING
            )

    return dedupe_tabular_file_contexts(tabular_file_contexts)


def collect_workspace_tabular_file_contexts(combined_documents=None, selected_document_ids=None,
                                            selected_document_id=None, document_scope='personal',
                                            active_group_id=None, active_public_workspace_id=None):
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
        active_group_id=active_group_id,
        active_public_workspace_id=active_public_workspace_id,
    ))

    return dedupe_tabular_file_contexts(tabular_file_contexts)


def collect_workspace_tabular_filenames(combined_documents=None, selected_document_ids=None,
                                        selected_document_id=None, document_scope='personal',
                                        active_group_id=None, active_public_workspace_id=None):
    """Collect unique tabular filenames from search results and explicit workspace selection."""
    tabular_file_contexts = collect_workspace_tabular_file_contexts(
        combined_documents=combined_documents,
        selected_document_ids=selected_document_ids,
        selected_document_id=selected_document_id,
        document_scope=document_scope,
        active_group_id=active_group_id,
        active_public_workspace_id=active_public_workspace_id,
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


def determine_tabular_source_hint(document_scope, active_group_id=None, active_public_workspace_id=None):
    """Map workspace scope metadata to the tabular plugin source hint."""
    if document_scope == 'group' and active_group_id:
        return 'group'
    if document_scope == 'public' and active_public_workspace_id:
        return 'public'
    return 'workspace'


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


def build_streaming_multi_endpoint_client(auth_settings, provider, endpoint, api_version):
    """Create an inference client for a resolved streaming model endpoint."""
    auth_settings = auth_settings or {}
    auth_type = str(auth_settings.get('type') or 'managed_identity').lower()
    normalized_provider = str(provider or 'aoai').lower()

    if auth_type in ('api_key', 'key'):
        api_key = auth_settings.get('api_key')
        if not api_key:
            raise ValueError('Selected model endpoint is missing an API key.')
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
    if normalized_provider in ('aifoundry', 'new_foundry'):
        scope = resolve_foundry_scope_for_auth(auth_settings, endpoint=endpoint)
        if auth_type == 'service_principal':
            debug_print(
                f"[Streaming][Model Resolution] Multi-endpoint SP scope={scope} provider={normalized_provider}"
            )
        else:
            debug_print(
                f"[Streaming][Model Resolution] Multi-endpoint MI scope={scope} provider={normalized_provider}"
            )

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
        personal_endpoints, _ = normalize_model_endpoints(user_settings.get('personal_model_endpoints', []) or [])
        endpoints.extend([
            {**endpoint, '_endpoint_scope': 'user'}
            for endpoint in personal_endpoints
            if isinstance(endpoint, dict)
        ])

    if settings.get('allow_group_custom_endpoints', False):
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

    global_endpoints, _ = normalize_model_endpoints(settings.get('model_endpoints', []) or [])
    endpoints.extend([
        {**endpoint, '_endpoint_scope': 'global'}
        for endpoint in global_endpoints
        if isinstance(endpoint, dict)
    ])

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
    if provider not in ('aoai', 'aifoundry', 'new_foundry'):
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

    if requested_provider and requested_provider != provider:
        debug_print(
            f"[Streaming][Model Resolution] Request provider '{requested_provider}' did not match saved provider '{provider}' for endpoint_id={requested_endpoint_id}."
        )

    if not endpoint or not api_version or not deployment:
        if selection_source == 'request':
            raise ValueError('Selected model endpoint is missing endpoint, API version, or deployment configuration.')
        debug_print(
            f"[Streaming][Model Resolution] Default selection for endpoint_id={requested_endpoint_id} is incomplete. Falling back to legacy streaming config."
        )
        return None

    gpt_client = build_streaming_multi_endpoint_client(auth_settings, provider, endpoint, api_version)
    debug_print(
        f"[Streaming][Model Resolution] Resolved {selection_source} multi-endpoint model | "
        f"provider={provider} | endpoint_id={requested_endpoint_id} | model_id={model_cfg.get('id')} | "
        f"deployment={deployment} | api_version={api_version}"
    )
    return gpt_client, deployment, provider, endpoint, auth_settings, api_version


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
        stream_bridge = BackgroundStreamBridge()

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
            try:
                for event in stream_bridge.iter_events():
                    yield event
            except GeneratorExit:
                stream_bridge.detach_consumer()
                raise
            finally:
                stream_bridge.detach_consumer()

        return Response(
            stream_with_context(consume_stream()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )

    def get_facts_for_context(scope_id, scope_type, conversation_id: str = None, agent_id: str = None):
        if not scope_id or not scope_type:
            return ""
        fact_store = FactMemoryStore()
        kwargs = dict(
            scope_type=scope_type,
            scope_id=scope_id,
        )
        if agent_id:
            kwargs['agent_id'] = agent_id
        if conversation_id:
            kwargs['conversation_id'] = conversation_id
        facts = fact_store.get_facts(**kwargs)
        if not facts:
            return ""
        fact_lines = []
        for fact in facts:
            value = str(fact.get('value') or '').strip()
            if value:
                fact_lines.append(f"- {value}")
        if not fact_lines:
            return ""
        fact_lines.append(f"- agent_id: {agent_id or 'None'}")
        fact_lines.append(f"- scope_type: {scope_type}")
        fact_lines.append(f"- scope_id: {scope_id}")
        fact_lines.append(f"- conversation_id: {conversation_id or 'None'}")
        return "\n".join(fact_lines)

    def inject_fact_memory_context(conversation_history, scope_id, scope_type, conversation_id: str = None, agent_id: str = None):
        facts = get_facts_for_context(
            scope_id=scope_id,
            scope_type=scope_type,
            conversation_id=conversation_id,
            agent_id=agent_id,
        )
        if facts:
            conversation_history.insert(0, {
                "role": "system",
                "content": f"<Fact Memory>\n{facts}\n</Fact Memory>"
            })
        conversation_history.insert(0, {
            "role": "system",
            "content": f"""<Conversation Metadata>\n<Scope ID: {scope_id}>\n<Scope Type: {scope_type}>\n<Conversation ID: {conversation_id}>\n<Agent ID: {agent_id}>\n</Conversation Metadata>"""
        })

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
            # Backwards compat: if new list not provided, wrap single ID
            if not active_group_ids and active_group_id:
                active_group_ids = [active_group_id]
            # Permission validation: only keep groups user is a member of
            validated_group_ids = []
            for gid in active_group_ids:
                g_doc = find_group_by_id(gid)
                if g_doc and get_user_role_in_group(g_doc, user_id):
                    validated_group_ids.append(gid)
            active_group_ids = validated_group_ids
            # Keep single ID for backwards compat in metadata/context
            active_group_id = active_group_ids[0] if active_group_ids else data.get('active_group_id')
            active_public_workspace_id = data.get('active_public_workspace_id')  # Extract active public workspace ID
            active_public_workspace_ids = data.get('active_public_workspace_ids', [])
            if not active_public_workspace_ids and active_public_workspace_id:
                active_public_workspace_ids = [active_public_workspace_id]
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
            
            # Store conversation_id in Flask context for plugin logger access
            g.conversation_id = conversation_id
            
            # Clear plugin invocations at start of message processing to ensure
            # each message only shows citations for tools executed during that specific interaction
            from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
            plugin_logger = get_plugin_logger()
            plugin_logger.clear_invocations_for_conversation(user_id, conversation_id)
            
            # Validate chat_type
            if chat_type not in ('user', 'group'):
                chat_type = 'user'
                
            search_query = user_message # <--- ADD THIS LINE (Initialize search_query)
            hybrid_citations_list = [] # <--- ADD THIS LINE (Initialize hybrid list)
            agent_citations_list = [] # <--- ADD THIS LINE (Initialize agent citations list)
            web_search_citations_list = []
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
            if isinstance(image_gen_enabled, str):
                image_gen_enabled = image_gen_enabled.lower() == 'true'

            # GPT & Image generation APIM or direct
            gpt_model = ""
            gpt_client = None
            gpt_provider = None
            gpt_endpoint = None
            gpt_auth = None
            gpt_api_version = None
            enable_gpt_apim = settings.get('enable_gpt_apim', False)
            enable_image_gen_apim = settings.get('enable_image_gen_apim', False)
            should_use_default_model = (
                bool(request_agent_info)
                and settings.get('enable_multi_model_endpoints', False)
                and not data.get('model_id')
                and not data.get('model_endpoint_id')
            )
            try:
                multi_endpoint_config = None
                if should_use_default_model:
                    try:
                        multi_endpoint_config = resolve_default_model_gpt_config(settings)
                        if multi_endpoint_config:
                            debug_print("[GPTClient] Using default multi-endpoint model for agent request.")
                    except Exception as default_exc:
                        log_event(
                            f"[GPTClient] Default model selection unavailable: {default_exc}",
                            level=logging.WARNING,
                            exceptionTraceback=True
                        )
                if multi_endpoint_config is None and request_agent_info:
                    debug_print("[GPTClient] Skipping multi-endpoint resolution because agent_info is provided.")
                elif multi_endpoint_config is None:
                    multi_endpoint_config = resolve_multi_endpoint_gpt_config(settings, data, enable_gpt_apim)
                if multi_endpoint_config:
                    gpt_client, gpt_model, gpt_provider, gpt_endpoint, gpt_auth, gpt_api_version = multi_endpoint_config
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

            except Exception as e:
                debug_print(f"Error initializing GPT client/model: {e}")
                # Handle error appropriately - maybe return 500 or default behavior
                return jsonify({'error': f'Failed to initialize AI model: {str(e)}'}), 500
        # region 1 - Load or Create Conversation
            # ---------------------------------------------------------------------
            # 1) Load or create conversation
            # ---------------------------------------------------------------------
            if not conversation_id:
                conversation_id = str(uuid.uuid4())
                conversation_item = {
                    'id': conversation_id,
                    'user_id': user_id,
                    'last_updated': datetime.utcnow().isoformat(),
                    'title': 'New Conversation',
                    'context': [],
                    'tags': [],
                    'strict': False,
                    'chat_type': 'new'
                }
                cosmos_conversations_container.upsert_item(conversation_item)
                
                # Log conversation creation
                log_conversation_creation(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    title='New Conversation',
                    workspace_type='personal'
                )
                
                # Mark as logged to activity logs to prevent duplicate migration
                conversation_item['added_to_activity_log'] = True
                cosmos_conversations_container.upsert_item(conversation_item)
            else:
                try:
                    conversation_item = cosmos_conversations_container.read_item(item=conversation_id, partition_key=conversation_id)
                except CosmosResourceNotFoundError:
                    # If conversation ID is provided but not found, create a new one with that ID
                    # Or decide if you want to return an error instead
                    conversation_item = {
                        'id': conversation_id, # Keep the provided ID if needed for linking
                        'user_id': user_id,
                        'last_updated': datetime.utcnow().isoformat(),
                        'title': 'New Conversation', # Or maybe fetch title differently?
                        'context': [],
                        'tags': [],
                        'strict': False,
                        'chat_type': 'new'
                    }
                    # Optionally log that a conversation was expected but not found
                    debug_print(f"Warning: Conversation ID {conversation_id} not found, creating new.")
                    cosmos_conversations_container.upsert_item(conversation_item)
                    
                    # Log conversation creation
                    log_conversation_creation(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        title='New Conversation',
                        workspace_type='personal'
                    )
                    
                    # Mark as logged to activity logs to prevent duplicate migration
                    conversation_item['added_to_activity_log'] = True
                    cosmos_conversations_container.upsert_item(conversation_item)
                except Exception as e:
                    debug_print(f"Error reading conversation {conversation_id}: {e}")
                    return jsonify({'error': f'Error reading conversation: {str(e)}'}), 500

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
                    'web_search': bool(web_search_enabled)
                }
                
                # Document search scope and selections
                if hybrid_search_enabled:
                    user_metadata['workspace_search'] = {
                        'search_enabled': True,
                        'document_scope': document_scope,
                        'selected_document_id': selected_document_id,
                        'classification': classifications_to_send
                    }
                
                # Get document details if specific document selected
                if selected_document_id and selected_document_id != "all":
                    try:
                        # Use the appropriate documents container based on scope
                        if document_scope == 'group':
                            cosmos_container = cosmos_group_documents_container
                        elif document_scope == 'public':
                            cosmos_container = cosmos_public_documents_container
                        elif document_scope == 'personal':
                            cosmos_container = cosmos_user_documents_container
                        
                        doc_query = "SELECT c.file_name, c.title, c.document_id, c.group_id FROM c WHERE c.id = @doc_id"
                        doc_params = [{"name": "@doc_id", "value": selected_document_id}]
                        doc_results = list(cosmos_container.query_items(
                            query=doc_query, parameters=doc_params, enable_cross_partition_query=True
                        ))
                        if doc_results and 'workspace_search' in user_metadata:
                            doc_info = doc_results[0]
                            user_metadata['workspace_search']['document_name'] = doc_info.get('title') or doc_info.get('file_name')
                            user_metadata['workspace_search']['document_filename'] = doc_info.get('file_name')
                    except Exception as e:
                        debug_print(f"Error retrieving document details: {e}")
                
                # Add scope-specific details
                if document_scope == 'group' and active_group_id:
                    try:
                        debug_print(f"Workspace search - looking up group for id: {active_group_id}")
                        group_doc = find_group_by_id(active_group_id)
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
                                debug_print(f"Workspace search - no name for group: {active_group_id}")
                                if 'workspace_search' in user_metadata:
                                    user_metadata['workspace_search']['group_name'] = None
                        else:
                            debug_print(f"Workspace search - no group found for id: {active_group_id}")
                            if 'workspace_search' in user_metadata:
                                user_metadata['workspace_search']['group_name'] = None
                            
                    except Exception as e:
                        debug_print(f"Error retrieving group details: {e}")
                        if 'workspace_search' in user_metadata:
                            user_metadata['workspace_search']['group_name'] = None
                        import traceback
                        traceback.print_exc()
                
                if document_scope == 'public' and active_public_workspace_id:
                    # Check if public workspace status allows chat operations
                    try:
                        from functions_public_workspaces import find_public_workspace_by_id, check_public_workspace_status_allows_operation
                        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
                        if workspace_doc:
                            allowed, reason = check_public_workspace_status_allows_operation(workspace_doc, 'chat')
                            if not allowed:
                                return jsonify({'error': reason}), 403
                    except Exception as e:
                        debug_print(f"Error checking public workspace status: {e}")
                    
                    if 'workspace_search' in user_metadata:
                        user_metadata['workspace_search']['active_public_workspace_id'] = active_public_workspace_id
                
                # Ensure workspace_search key always exists for consistency
                if 'workspace_search' not in user_metadata:
                    user_metadata['workspace_search'] = {
                        'search_enabled': False
                    }
            
                # Agent selection (if available)
                if hasattr(g, 'kernel_agents') and g.kernel_agents:
                    try:
                        # Try to get selected agent info from user settings or global settings
                        selected_agent_info = None
                        if user_id:
                            try:
                                user_settings_doc = cosmos_user_settings_container.read_item(
                                    item=user_id, partition_key=user_id
                                )
                                selected_agent_info = user_settings_doc.get('settings', {}).get('selected_agent')
                            except Exception as ex:
                                pass
                        
                        if not selected_agent_info:
                            # Fallback to global selected agent
                            selected_agent_info = settings.get('global_selected_agent')
                        
                        if selected_agent_info:
                            user_metadata['agent_selection'] = {
                                'selected_agent': selected_agent_info.get('name'),
                                'agent_display_name': selected_agent_info.get('display_name'),
                                'is_global': selected_agent_info.get('is_global', False),
                                'is_group': selected_agent_info.get('is_group', False),
                                'group_id': selected_agent_info.get('group_id'),
                                'group_name': selected_agent_info.get('group_name'),
                                'agent_id': selected_agent_info.get('id')
                            }
                    except Exception as e:
                        debug_print(f"Error retrieving agent details: {e}")
                
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
                agent_info = data.get('agent_info')
                if agent_info:
                    user_metadata['agent_selection'] = {
                        'selected_agent': agent_info.get('name'),
                        'agent_display_name': agent_info.get('display_name'),
                        'is_global': agent_info.get('is_global', False),
                        'is_group': agent_info.get('is_group', False),
                        'group_id': agent_info.get('group_id'),
                        'group_name': agent_info.get('group_name'),
                        'agent_id': agent_info.get('id')
                    }
                
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
                        chat_context=actual_chat_type
                    )
                except Exception as e:
                    # Don't let activity logging errors interrupt chat flow
                    debug_print(f"Activity logging error: {e}")
                    
                # Set conversation title if it's still the default
                if conversation_item.get('title', 'New Conversation') == 'New Conversation' and user_message:
                    new_title = (user_message[:30] + '...') if len(user_message) > 30 else user_message
                    conversation_item['title'] = new_title

                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                cosmos_conversations_container.upsert_item(conversation_item) # Update timestamp and potentially title

                # Generate assistant_message_id early for thought tracking
                assistant_message_id = f"{conversation_id}_assistant_{int(time.time())}_{random.randint(1000,9999)}"

                # Initialize thought tracker
                thought_tracker = ThoughtTracker(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    thread_id=current_user_thread_id,
                    user_id=user_id
                )

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
                            'metadata': {}
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
                        safety_message_id = f"{conversation_id}_safety_{int(time.time())}_{random.randint(1000,9999)}"

                        safety_doc = {
                            'id': safety_message_id,
                            'conversation_id': conversation_id,
                            'role': 'safety',
                            'content': blocked_msg_content.strip(),
                            'timestamp': datetime.utcnow().isoformat(),
                            'model_deployment_name': None,
                            'metadata': {},  # No metadata needed for safety messages
                        }
                        cosmos_messages_container.upsert_item(safety_doc)

                        # Update conversation's last_updated
                        conversation_item['last_updated'] = datetime.utcnow().isoformat()
                        cosmos_conversations_container.upsert_item(conversation_item)

                        # Return a normal 200 with a special field: blocked=True
                        return jsonify({
                            'reply': blocked_msg_content.strip(),
                            'blocked': True,
                            'triggered_categories': triggered_categories,
                            'blocklist_matches': blocklist_matches,
                            'conversation_id': conversation_id,
                            'conversation_title': conversation_item['title'],
                            'message_id': safety_message_id
                        }), 200

                except HttpResponseError as e:
                    debug_print(f"[Content Safety Error] {e}")
                except Exception as ex:
                    debug_print(f"[Content Safety] Unexpected error: {ex}")
        # region 4 - Augmentation
            # ---------------------------------------------------------------------
            # 4) Augmentation (Search, etc.) - Run *before* final history prep
            # ---------------------------------------------------------------------
            
            # Hybrid Search
            if hybrid_search_enabled:
                
                # Optional: Summarize recent history *for search* (uses its own limit)
                if enable_summarize_content_history_for_search:
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
                                thread_info = msg.get('metadata', {}).get('thread_info', {})
                                active_thread = thread_info.get('active_thread')
                                
                                # Exclude messages with active_thread=False
                                if active_thread is False:
                                    debug_print(f"[THREAD] Skipping inactive thread message {msg.get('id')} from search summary")
                                    continue
                                    
                                message_texts_search.append(f"{msg.get('role', 'user').upper()}: {msg.get('content', '')}")
                            
                            if not message_texts_search:
                                # No active messages to summarize
                                debug_print("[THREAD] No active thread messages available for search summary")
                            else:
                                summary_prompt_search += "\n".join(message_texts_search)

                                try:
                                    # Use the already initialized gpt_client and gpt_model
                                    summary_response_search = gpt_client.chat.completions.create(
                                        model=gpt_model,
                                        messages=[{"role": "system", "content": summary_prompt_search}],
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
                thought_tracker.add_thought('search', f"Searching {document_scope or 'personal'} workspace documents for '{(search_query or user_message)[:50]}'")
                try:
                    # Prepare search arguments
                    # Set default and maximum values for top_n
                    default_top_n = 12
                    max_top_n = 500  # Reasonable cap to prevent excessive resource usage
                    
                    # Process top_n_results if provided
                    if top_n_results is not None:
                        try:
                            top_n = int(top_n_results)
                            # Ensure top_n is within reasonable bounds
                            if top_n < 1:
                                top_n = default_top_n
                            elif top_n > max_top_n:
                                top_n = max_top_n
                        except (ValueError, TypeError):
                            # If conversion fails, use default
                            top_n = default_top_n
                    else:
                        top_n = default_top_n
                    
                    search_args = {
                        "query": search_query,
                        "user_id": user_id,
                        "top_n": top_n,
                        "doc_scope": document_scope,
                    }
                    
                    # Add active_group_ids when:
                    # 1. Document scope is 'group' or chat_type is 'group', OR
                    # 2. Document scope is 'all' and groups are enabled (so group search can be included)
                    if active_group_ids and (document_scope == 'group' or document_scope == 'all' or chat_type == 'group'):
                        search_args["active_group_ids"] = active_group_ids
    
                    # Add active_public_workspace_id when:
                    # 1. Document scope is 'public' or
                    # 2. Document scope is 'all' and public workspaces are enabled
                    if active_public_workspace_id and (document_scope == 'public' or document_scope == 'all'):
                        search_args["active_public_workspace_id"] = active_public_workspace_id
                        
                    if selected_document_ids:
                        search_args["document_ids"] = selected_document_ids
                    elif selected_document_id:
                        search_args["document_id"] = selected_document_id
                    
                    # Add tags filter if provided
                    if tags_filter and isinstance(tags_filter, list) and len(tags_filter) > 0:
                        search_args["tags_filter"] = tags_filter
                    
                    # Log if a non-default top_n value is being used
                    if top_n != default_top_n:
                        debug_print(f"Using custom top_n value: {top_n} (requested: {top_n_results})")
                    
                    # Public scope now automatically searches all visible public workspaces
                    search_results = hybrid_search(**search_args) # Assuming hybrid_search handles None document_id
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

                    # Reorder hybrid citations list in descending order based on page_number
                    hybrid_citations_list.sort(key=lambda x: x.get('page_number', 0), reverse=True)

                    # --- NEW: Extract metadata (keywords/abstract) for additional citations ---
                    # Only if extract_metadata is enabled
                    if settings.get('enable_extract_meta_data', False):
                        from functions_documents import get_document_metadata_for_citations

                        # Track which documents we've already processed to avoid duplicates
                        processed_doc_ids = set()

                        for doc in search_results:
                            # Get document ID (from the chunk's document reference)
                            # AI Search chunks contain references to their parent document
                            doc_id = doc.get('id', '').split('_')[0] if doc.get('id') else None

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

            # Update message-level chat_type based on actual document usage for this message
            # This must happen after document search is completed so search_results is populated
            message_chat_type = None
            if hybrid_search_enabled and search_results and len(search_results) > 0:
                # Documents were actually used for this message
                if document_scope == 'group':
                    message_chat_type = 'group'
                elif document_scope == 'public':
                    message_chat_type = 'public'  
                else:
                        message_chat_type = 'personal_single_user'
            else:
                # No documents used for this message - only model knowledge
                message_chat_type = 'Model'
            
            # Update the message-level chat_type in user_metadata
            user_metadata['chat_context']['chat_type'] = message_chat_type
            debug_print(f"Set message-level chat_type to: {message_chat_type}")
            debug_print(f"hybrid_search_enabled: {hybrid_search_enabled}, search_results count: {len(search_results) if search_results else 0}")
            
            # Add context-specific information based on message chat type
            if message_chat_type == 'group' and active_group_id:
                user_metadata['chat_context']['group_id'] = active_group_id
                # We may have already fetched this in workspace_search section
                if 'workspace_search' in user_metadata and user_metadata['workspace_search'].get('group_name'):
                    user_metadata['chat_context']['group_name'] = user_metadata['workspace_search']['group_name']
                    debug_print(f"Chat context - using group_name from workspace_search: {user_metadata['workspace_search']['group_name']}")
                else:
                    try:
                        debug_print(f"Chat context - looking up group for id: {active_group_id}")
                        group_doc = find_group_by_id(active_group_id)
                        debug_print(f"Chat context group lookup result: {group_doc}")
                        
                        if group_doc and group_doc.get('name'):
                            group_title = group_doc.get('name')
                            user_metadata['chat_context']['group_name'] = group_title
                            debug_print(f"Chat context - set group_name to: {group_title}")
                        else:
                            debug_print(f"Chat context - no group found or no name for id: {active_group_id}")
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
                    
                    # Check if image data is too large for a single Cosmos document (2MB limit)
                    # Account for JSON overhead by using 1.5MB as the safe limit for base64 content
                    max_content_size = 1500000  # 1.5MB in bytes
                    
                    if len(generated_image_url) > max_content_size:
                        debug_print(f"Large image detected ({len(generated_image_url)} bytes), splitting across multiple documents")
                        
                        # Split the data URL into manageable chunks
                        if generated_image_url.startswith('data:image/png;base64,'):
                            # Extract just the base64 part for splitting
                            data_url_prefix = 'data:image/png;base64,'
                            base64_content = generated_image_url[len(data_url_prefix):]
                            debug_print(f"Extracted base64 content length: {len(base64_content)} bytes")
                        else:
                            # For regular URLs, store as-is (shouldn't happen with large content)
                            data_url_prefix = ''
                            base64_content = generated_image_url
                        
                        # Calculate chunk size and number of chunks
                        chunk_size = max_content_size - len(data_url_prefix) - 200  # More room for JSON overhead
                        chunks = [base64_content[i:i+chunk_size] for i in range(0, len(base64_content), chunk_size)]
                        total_chunks = len(chunks)
                        
                        debug_print(f"Splitting into {total_chunks} chunks of max {chunk_size} bytes each")
                        for i, chunk in enumerate(chunks):
                            debug_print(f"Chunk {i} length: {len(chunk)} bytes")
                        
                        # Verify we can reassemble before storing
                        reassembled_test = data_url_prefix + ''.join(chunks)
                        if len(reassembled_test) == len(generated_image_url):
                            debug_print(f"✅ Chunking verification passed - can reassemble to original size")
                        else:
                            debug_print(f"❌ Chunking verification failed - {len(reassembled_test)} vs {len(generated_image_url)}")
                        
                        
                        # Create main image document with metadata
                        
                        # Get user_info and thread_id from the user message for ownership tracking and threading
                        user_info_for_chunked_image = None
                        user_thread_id = None
                        user_previous_thread_id = None
                        try:
                            user_msg = cosmos_messages_container.read_item(
                                item=user_message_id,
                                partition_key=conversation_id
                            )
                            user_info_for_chunked_image = user_msg.get('metadata', {}).get('user_info')
                            user_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
                            user_previous_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
                        except Exception as e:
                            debug_print(f"Warning: Could not retrieve user_info from user message for chunked image: {e}")
                        
                        main_image_doc = {
                            'id': image_message_id,
                            'conversation_id': conversation_id,
                            'role': 'image',
                            'content': f"{data_url_prefix}{chunks[0]}",  # First chunk with data URL prefix
                            'prompt': user_message,
                            'created_at': datetime.utcnow().isoformat(),
                            'timestamp': datetime.utcnow().isoformat(),
                            'model_deployment_name': image_gen_model,
                            'metadata': {
                                'user_info': user_info_for_chunked_image,  # Track which user created this image
                                'is_chunked': True,
                                'total_chunks': total_chunks,
                                'chunk_index': 0,
                                'original_size': len(generated_image_url),
                                'thread_info': {
                                    'thread_id': user_thread_id,  # Same thread as user message
                                    'previous_thread_id': user_previous_thread_id,  # Same previous_thread_id as user message
                                    'active_thread': True,
                                    'thread_attempt': 1
                                }
                            }
                        }
                        # Image message shares the same thread as user message
                        
                        # Create additional chunk documents
                        chunk_docs = []
                        for i in range(1, total_chunks):
                            chunk_doc = {
                                'id': f"{image_message_id}_chunk_{i}",
                                'conversation_id': conversation_id,
                                'role': 'image_chunk',
                                'content': chunks[i],
                                'parent_message_id': image_message_id,
                                'created_at': datetime.utcnow().isoformat(),
                                'timestamp': datetime.utcnow().isoformat(),
                                'metadata': {
                                    'is_chunk': True,
                                    'chunk_index': i,
                                    'total_chunks': total_chunks,
                                    'parent_message_id': image_message_id
                                }
                            }
                            chunk_docs.append(chunk_doc)
                        
                        # Store all documents
                        debug_print(f"Storing main document with content length: {len(main_image_doc['content'])} bytes")
                        cosmos_messages_container.upsert_item(main_image_doc)
                        
                        for i, chunk_doc in enumerate(chunk_docs):
                            debug_print(f"Storing chunk {i+1} with content length: {len(chunk_doc['content'])} bytes")
                            cosmos_messages_container.upsert_item(chunk_doc)
                            
                        debug_print(f"Successfully stored image in {total_chunks} documents")
                        debug_print(f"Main doc content starts with: {main_image_doc['content'][:50]}...")
                        debug_print(f"Main doc content ends with: ...{main_image_doc['content'][-50:]}")
                        
                        # Return the full image URL for immediate display
                        response_image_url = generated_image_url
                        
                    else:
                        # Small image - store normally in single document
                        debug_print(f"Small image ({len(generated_image_url)} bytes), storing in single document")
                        
                        # Get user_info and thread_id from the user message for ownership tracking and threading
                        user_info_for_image = None
                        user_thread_id = None
                        user_previous_thread_id = None
                        try:
                            user_msg = cosmos_messages_container.read_item(
                                item=user_message_id,
                                partition_key=conversation_id
                            )
                            user_info_for_image = user_msg.get('metadata', {}).get('user_info')
                            user_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
                            user_previous_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
                        except Exception as e:
                            debug_print(f"Warning: Could not retrieve user_info from user message for image: {e}")
                        
                        image_doc = {
                            'id': image_message_id,
                            'conversation_id': conversation_id,
                            'role': 'image',
                            'content': generated_image_url,
                            'prompt': user_message,
                            'created_at': datetime.utcnow().isoformat(),
                            'timestamp': datetime.utcnow().isoformat(),
                            'model_deployment_name': image_gen_model,
                            'metadata': {
                                'user_info': user_info_for_image,  # Track which user created this image
                                'is_chunked': False,
                                'original_size': len(generated_image_url),
                                'thread_info': {
                                    'thread_id': user_thread_id,  # Same thread as user message
                                    'previous_thread_id': user_previous_thread_id,  # Same previous_thread_id as user message
                                    'active_thread': True,
                                    'thread_attempt': 1
                                }
                            }
                        }
                        cosmos_messages_container.upsert_item(image_doc)
                        response_image_url = generated_image_url
                        # Image message shares the same thread as user message

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

            workspace_tabular_files = set()
            if hybrid_search_enabled and is_tabular_processing_enabled(settings):
                workspace_tabular_files = collect_workspace_tabular_filenames(
                    combined_documents=combined_documents,
                    selected_document_ids=selected_document_ids,
                    selected_document_id=selected_document_id,
                    document_scope=document_scope,
                )

            if hybrid_search_enabled and workspace_tabular_files and is_tabular_processing_enabled(settings):
                tabular_source_hint = determine_tabular_source_hint(
                    document_scope,
                    active_group_id=active_group_id,
                    active_public_workspace_id=active_public_workspace_id,
                )
                tabular_execution_mode = get_tabular_execution_mode(user_message)
                tabular_filenames_str = ", ".join(sorted(workspace_tabular_files))
                plugin_logger = get_plugin_logger()
                baseline_tabular_invocation_count = len(
                    plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000)
                )

                tabular_analysis = asyncio.run(run_tabular_sk_analysis(
                    user_question=user_message,
                    tabular_filenames=workspace_tabular_files,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    gpt_model=gpt_model,
                    settings=settings,
                    source_hint=tabular_source_hint,
                    group_id=active_group_id if tabular_source_hint == 'group' else None,
                    public_workspace_id=active_public_workspace_id if tabular_source_hint == 'public' else None,
                    execution_mode=tabular_execution_mode,
                ))
                tabular_invocations = get_new_plugin_invocations(
                    plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000),
                    baseline_tabular_invocation_count
                )
                tabular_thought_payloads = get_tabular_tool_thought_payloads(tabular_invocations)
                for thought_content, thought_detail in tabular_thought_payloads:
                    thought_tracker.add_thought('tabular_analysis', thought_content, thought_detail)
                tabular_status_thought_payloads = get_tabular_status_thought_payloads(
                    tabular_invocations,
                    analysis_succeeded=bool(tabular_analysis),
                )
                for thought_content, thought_detail in tabular_status_thought_payloads:
                    thought_tracker.add_thought('tabular_analysis', thought_content, thought_detail)

                if tabular_analysis:
                    tabular_system_msg = build_tabular_computed_results_system_message(
                        f"the file(s) {tabular_filenames_str}",
                        tabular_analysis,
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

                if tabular_analysis:
                    tabular_sk_citations = collect_tabular_sk_citations(user_id, conversation_id)
                    if tabular_sk_citations:
                        agent_citations_list.extend(tabular_sk_citations)
                else:
                    thought_tracker.add_thought(
                        'tabular_analysis',
                        "Tabular analysis could not compute results; using schema context instead",
                        detail=f"files={tabular_filenames_str}"
                    )

            if web_search_enabled:
                thought_tracker.add_thought('web_search', f"Searching the web for '{(search_query or user_message)[:50]}'")
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
                    search_query=search_query,
                    system_messages_for_augmentation=system_messages_for_augmentation,
                    agent_citations_list=agent_citations_list,
                    web_search_citations_list=web_search_citations_list,
                )
                if web_search_citations_list:
                    thought_tracker.add_thought('web_search', f"Got {len(web_search_citations_list)} web search results")

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

                    chat_tabular_analysis = asyncio.run(run_tabular_sk_analysis(
                        user_question=user_message,
                        tabular_filenames=chat_tabular_files,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        gpt_model=gpt_model,
                        settings=settings,
                        source_hint="chat",
                        execution_mode=chat_tabular_execution_mode,
                    ))
                    chat_tabular_invocations = get_new_plugin_invocations(
                        plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000),
                        baseline_tabular_invocation_count
                    )
                    chat_tabular_thought_payloads = get_tabular_tool_thought_payloads(chat_tabular_invocations)
                    for thought_content, thought_detail in chat_tabular_thought_payloads:
                        thought_tracker.add_thought('tabular_analysis', thought_content, thought_detail)
                    chat_tabular_status_thought_payloads = get_tabular_status_thought_payloads(
                        chat_tabular_invocations,
                        analysis_succeeded=bool(chat_tabular_analysis),
                    )
                    for thought_content, thought_detail in chat_tabular_status_thought_payloads:
                        thought_tracker.add_thought('tabular_analysis', thought_content, thought_detail)

                    if chat_tabular_analysis:
                        # Inject pre-computed analysis results as context
                        conversation_history_for_api.append({
                            'role': 'system',
                            'content': build_tabular_computed_results_system_message(
                                f"the chat-uploaded file(s) {chat_tabular_filenames_str}",
                                chat_tabular_analysis,
                            )
                        })
                        final_api_source_refs.append('system:tabular_results')

                        # Collect tool execution citations from SK tabular analysis
                        chat_tabular_sk_citations = collect_tabular_sk_citations(user_id, conversation_id)
                        if chat_tabular_sk_citations:
                            agent_citations_list.extend(chat_tabular_sk_citations)

                        debug_print(f"[Chat Tabular SK] Analysis injected, {len(chat_tabular_analysis)} chars")
                    else:
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
            force_enable_agents = bool(request_agent_info)  # Force enable agents if agent_info provided
            
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
            if enable_semantic_kernel and user_enable_agents:
            # PATCH: Use new agent selection logic
                agent_name_to_select = None
                
                # Priority 1: Use agent_info from request if provided (e.g., retry with specific agent)
                if request_agent_info:
                    # Extract agent name or create dict format expected by selection logic
                    agent_name_to_select = request_agent_info if isinstance(request_agent_info, dict) else {'name': request_agent_info}
                    if isinstance(agent_name_to_select, dict):
                        agent_name_to_select = agent_name_to_select.get('name')
                    log_event(f"[SKChat] Using agent from request agent_info: {agent_name_to_select}")
                # Priority 2: Use user settings
                elif per_user_semantic_kernel:
                    selected_agent_info = user_settings.get('selected_agent')
                    if isinstance(selected_agent_info, dict):
                        agent_name_to_select = selected_agent_info.get('name')
                    else:
                        agent_name_to_select = selected_agent_info
                    log_event(f"[SKChat] Per-user mode: selected_agent from user_settings: {selected_agent_info}")
                # Priority 3: Use global settings
                else:
                    global_selected_agent_info = settings.get('global_selected_agent')
                    if global_selected_agent_info:
                        agent_name_to_select = global_selected_agent_info.get('name')
                        log_event(f"[SKChat] Global mode: selected_agent from global_selected_agent: {agent_name_to_select}")
                if all_agents:
                    agent_iter = all_agents.values() if isinstance(all_agents, dict) else all_agents
                    agent_debug_info = []
                    for agent in agent_iter:
                        agent_debug_info.append({
                            "name": getattr(agent, 'name', None),
                            "default_agent": getattr(agent, 'default_agent', None),
                            "is_global": getattr(agent, 'is_global', None),
                            "repr": repr(agent)
                        })
                        # Prefer explicit selection, fallback to default_agent
                        if agent_name_to_select and getattr(agent, 'name', None) == agent_name_to_select:
                            selected_agent = agent
                            log_event(f"[SKChat] selected_agent found by explicit selection: {agent_name_to_select}")
                            break
                    if not selected_agent:
                        # Fallback to default_agent
                        for agent in agent_iter:
                            if getattr(agent, 'default_agent', False):
                                selected_agent = agent
                                log_event(f"[SKChat] selected_agent found by default_agent=True")
                                break
                    if not selected_agent and agent_iter:
                        selected_agent = next(iter(agent_iter), None)
                        log_event(f"[SKChat] selected_agent fallback to first agent: {getattr(selected_agent, 'name', None)}")
                    log_event(f"[SKChat] Agent selection debug info: {agent_debug_info}")
                else:
                    log_event(f"[SKChat] all_agents is empty or None!", level=logging.WARNING)
                if selected_agent is None:
                    log_event(f"[SKChat][ERROR] No selected_agent found! all_agents: {all_agents}", level=logging.ERROR)
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

                # Use the orchestrator agent as the default agent
                

                # Add additional metadata here to scope the facts to be returned
                # Allows for additional per agent and per conversation scoping.
                inject_fact_memory_context(
                    conversation_history=conversation_history_for_api,
                    scope_id=scope_id,
                    scope_type=scope_type,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
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
                if enable_multi_agent_orchestration and all_agents and "orchestrator" in all_agents and not per_user_semantic_kernel:
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
                            
                            # Ensure all values are JSON serializable
                            def make_json_serializable(obj):
                                if obj is None:
                                    return None
                                elif isinstance(obj, (str, int, float, bool)):
                                    return obj
                                elif isinstance(obj, dict):
                                    return {str(k): make_json_serializable(v) for k, v in obj.items()}
                                elif isinstance(obj, (list, tuple)):
                                    return [make_json_serializable(item) for item in obj]
                                else:
                                    return str(obj)
                            
                            citation = {
                                'tool_name': f"{inv.plugin_name}.{inv.function_name}",
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

                    if selected_agent_type in ('aifoundry', 'new_foundry'):
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
                                'search_query': search_query,
                            }
                            return selected_agent.invoke(
                                agent_message_history,
                                metadata={k: v for k, v in foundry_metadata.items() if v is not None}
                            )

                        def foundry_agent_success(result):
                            msg = str(result)
                            notice = None
                            foundry_label = 'New Foundry Application' if selected_agent_type == 'new_foundry' else 'Azure AI Foundry Agent'
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
                                        f"Agent retrieved citation from Azure AI Foundry"
                                    )
                                for citation in foundry_citations:
                                    try:
                                        serializable = json.loads(json.dumps(citation, default=str))
                                    except (TypeError, ValueError):
                                        serializable = {'value': str(citation)}
                                    agent_citations_list.append({
                                        'tool_name': agent_used,
                                        'function_name': 'foundry_citation',
                                        'plugin_name': 'new_foundry' if selected_agent_type == 'new_foundry' else 'azure_ai_foundry',
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

                if kernel:
                    def invoke_kernel():
                        plugin_logger = get_plugin_logger()
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
                                return asyncio.run(run_sk_call(kernel.invoke, chat_func, input=chat_history))
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

                                    async def run_chatcompletion():
                                        return await chat_service.get_chat_message_contents(chat_hist, settings_obj)

                                    chat_result = asyncio.run(run_chatcompletion())
                                    if chat_result and hasattr(chat_result[0], 'content'):
                                        return chat_result[0].content
                                    else:
                                        return str(chat_result)
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
                    elif gpt_provider in ('aifoundry', 'new_foundry') and 'api version not supported' in error_str:
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
                                retry_client = build_multi_endpoint_client(gpt_auth or {}, gpt_provider, gpt_endpoint, candidate)
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
            
            if selected_agent:
                # When using an agent, use the agent's actual model deployment
                if hasattr(selected_agent, 'deployment_name') and selected_agent.deployment_name:
                    actual_model_used = selected_agent.deployment_name
                
                # Get agent display information
                if hasattr(selected_agent, 'display_name'):
                    agent_display_name = selected_agent.display_name
                if hasattr(selected_agent, 'name'):
                    agent_name = selected_agent.name
            
            # assistant_message_id was generated earlier for thought tracking

            # Get user_info and thread_id from the user message for ownership tracking and threading
            user_info_for_assistant = None
            user_thread_id = None
            user_previous_thread_id = None
            try:
                user_msg = cosmos_messages_container.read_item(
                    item=user_message_id,
                    partition_key=conversation_id
                )
                user_info_for_assistant = user_msg.get('metadata', {}).get('user_info')
                user_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
                user_previous_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
            except Exception as e:
                debug_print(f"Warning: Could not retrieve user_info from user message: {e}")
            
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

            assistant_doc = {
                'id': assistant_message_id,
                'conversation_id': conversation_id,
                'role': 'assistant',
                'content': ai_message,
                'timestamp': assistant_timestamp,
                'augmented': bool(system_messages_for_augmentation),
                'hybrid_citations': hybrid_citations_list, # <--- SIMPLIFIED: Directly use the list
                'web_search_citations': web_search_citations_list,
                'hybridsearch_query': search_query if hybrid_search_enabled and search_results else None, # Log query only if hybrid search ran and found results
                'agent_citations': prepared_agent_citations,
                'model_deployment_name': actual_model_used,
                'agent_display_name': agent_display_name,
                'agent_name': agent_name,
                'metadata': {
                    'user_info': user_info_for_assistant,  # Track which user created this assistant message
                    'reasoning_effort': reasoning_effort,
                    'history_context': history_debug_info,
                    'thread_info': {
                        'thread_id': user_thread_id,  # Same thread as user message
                        'previous_thread_id': user_previous_thread_id,  # Same previous_thread_id as user message
                        'active_thread': True,
                        'thread_attempt': retry_thread_attempt if is_retry else 1
                    },
                    'token_usage': token_usage_data  # Store token usage information
                } # Used by SK and reasoning effort
            }
            
            debug_print(f"🔍 Chat API - Creating assistant message with thread_info:")
            debug_print(f"    thread_id: {user_thread_id}")
            debug_print(f"    previous_thread_id: {user_previous_thread_id}")
            debug_print(f"    attempt: {retry_thread_attempt if is_retry else 1}")
            debug_print(f"    is_retry: {is_retry}")
            
            cosmos_messages_container.upsert_item(assistant_doc)
            
            # Log chat token usage to activity_logs for easy reporting
            if token_usage_data and token_usage_data.get('total_tokens'):
                try:
                    from functions_activity_logging import log_token_usage
                    
                    # Determine workspace type based on active group/public workspace
                    workspace_type = 'personal'
                    if active_public_workspace_id:
                        workspace_type = 'public'
                    elif active_group_id:
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
                        group_id=active_group_id,
                        public_workspace_id=active_public_workspace_id,
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
                    active_group_id=active_group_id,
                    active_group_ids=active_group_ids,
                    document_scope=document_scope,
                    selected_document_id=selected_document_id,
                    model_deployment=actual_model_used,
                    hybrid_search_enabled=hybrid_search_enabled,
                    image_gen_enabled=image_gen_enabled,
                    selected_documents=combined_documents if 'combined_documents' in locals() else None,
                    selected_agent=selected_agent_name,
                    selected_agent_details=user_metadata.get('agent_selection'),
                    search_results=search_results if 'search_results' in locals() else None,
                    conversation_item=conversation_item,
                    active_public_workspace_id=active_public_workspace_id,
                    active_public_workspace_ids=active_public_workspace_ids
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
            return jsonify({
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
                'message_id': assistant_message_id,
                'user_message_id': user_message_id,  # Include the user message ID
                'blocked': False, # Explicitly false if we got this far
                'augmented': bool(system_messages_for_augmentation),
                'hybrid_citations': hybrid_citations_list,
                'web_search_citations': web_search_citations_list,
                'agent_citations': prepared_agent_citations,
                'reload_messages': reload_messages_required,
                'kernel_fallback_notice': kernel_fallback_notice,
                'thoughts_enabled': thought_tracker.enabled
            }), 200
        
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
            settings = get_settings()
            request_start_time = time.time()
        except Exception as e:
            return jsonify({'error': f'Failed to parse request: {str(e)}'}), 400

        compatibility_mode = bool(data.get('image_generation')) or bool(
            data.get('retry_user_message_id') or data.get('edited_user_message_id')
        )
        requested_conversation_id = str(data.get('conversation_id') or '').strip() or None
        finalized_conversation_id = requested_conversation_id or str(uuid.uuid4())
        is_new_stream_conversation = requested_conversation_id is None
        data['conversation_id'] = finalized_conversation_id
        stream_session = CHAT_STREAM_REGISTRY.start_session(user_id, finalized_conversation_id)

        request_message = (data.get('message') or '').strip()
        request_preview = request_message[:120] + '...' if len(request_message) > 120 else request_message
        debug_print(
            "[Streaming] Incoming /api/chat/stream request | "
            f"requested_conversation_id={requested_conversation_id} | "
            f"conversation_id={finalized_conversation_id} | "
            f"compatibility_mode={compatibility_mode} | "
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

        def normalize_legacy_chat_payload(payload):
            """Convert the legacy JSON response shape into the streaming terminal payload."""
            return {
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
            }

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
                
                if not user_id:
                    yield f"data: {json.dumps({'error': 'User not authenticated'})}\n\n"
                    return
                
                # Extract request parameters (same as non-streaming endpoint)
                user_message = data.get('message', '')
                conversation_id = finalized_conversation_id
                hybrid_search_enabled = data.get('hybrid_search')
                web_search_enabled = data.get('web_search_enabled')
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
                # Backwards compat: if new list not provided, wrap single ID
                if not active_group_ids and active_group_id:
                    active_group_ids = [active_group_id]
                # Permission validation: only keep groups user is a member of
                validated_group_ids = []
                for gid in active_group_ids:
                    g_doc = find_group_by_id(gid)
                    if g_doc and get_user_role_in_group(g_doc, user_id):
                        validated_group_ids.append(gid)
                active_group_ids = validated_group_ids
                # Keep single ID for backwards compat in metadata/context
                active_group_id = active_group_ids[0] if active_group_ids else data.get('active_group_id')
                active_public_workspace_id = data.get('active_public_workspace_id')  # Extract active public workspace ID
                active_public_workspace_ids = data.get('active_public_workspace_ids', [])
                if not active_public_workspace_ids and active_public_workspace_id:
                    active_public_workspace_ids = [active_public_workspace_id]
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
                user_enable_agents = False
                
                debug_print(f"[DEBUG] enable_semantic_kernel={enable_semantic_kernel}, per_user_semantic_kernel={per_user_semantic_kernel}")
                
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
                        
                        user_enable_agents = user_settings.get('enable_agents', False)
                        debug_print(f"[DEBUG] user_enable_agents={user_enable_agents}")
                    except Exception as e:
                        debug_print(f"Error loading user settings: {e}")
                        import traceback
                        traceback.print_exc()
                
                # Streaming does not support image generation
                if image_gen_enabled:
                    yield f"data: {json.dumps({'error': 'Image generation is not supported in streaming mode'})}\n\n"
                    return
                
                # Initialize Flask context
                g.conversation_id = conversation_id
                
                # Clear plugin invocations
                from semantic_kernel_plugins.plugin_invocation_logger import get_plugin_logger
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
                hybrid_citations_list = []
                agent_citations_list = []
                web_search_citations_list = []
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
                debug_print(
                    "[Streaming] Normalized toggles | "
                    f"hybrid_search={hybrid_search_enabled} | "
                    f"web_search={web_search_enabled} | "
                    f"chat_type={chat_type}"
                )
                
                # Initialize GPT client (simplified version)
                gpt_model = ""
                gpt_client = None
                gpt_provider = None
                gpt_endpoint = None
                gpt_auth = None
                gpt_api_version = None
                enable_gpt_apim = settings.get('enable_gpt_apim', False)
                should_use_default_model = (
                    bool(request_agent_info)
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
                        gpt_client, gpt_model, gpt_provider, gpt_endpoint, gpt_auth, gpt_api_version = streaming_multi_endpoint_config
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
                    conversation_item = {
                        'id': conversation_id,
                        'user_id': user_id,
                        'last_updated': datetime.utcnow().isoformat(),
                        'title': 'New Conversation',
                        'context': [],
                        'tags': [],
                        'strict': False,
                        'chat_type': 'new'
                    }
                    cosmos_conversations_container.upsert_item(conversation_item)
                    debug_print(f"[Streaming] Created new conversation {conversation_id}")
                else:
                    try:
                        conversation_item = cosmos_conversations_container.read_item(
                            item=conversation_id, partition_key=conversation_id
                        )
                        debug_print(f"[Streaming] Loaded existing conversation {conversation_id}")
                    except CosmosResourceNotFoundError:
                        conversation_item = {
                            'id': conversation_id,
                            'user_id': user_id,
                            'last_updated': datetime.utcnow().isoformat(),
                            'title': 'New Conversation',
                            'context': [],
                            'tags': [],
                            'strict': False,
                            'chat_type': 'new'
                        }
                        cosmos_conversations_container.upsert_item(conversation_item)
                        debug_print(f"[Streaming] Conversation {conversation_id} not found; created replacement")
                
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
                    'web_search': bool(web_search_enabled)
                }
                
                # Document search scope and selections
                if hybrid_search_enabled:
                    user_metadata['workspace_search'] = {
                        'search_enabled': True,
                        'document_scope': document_scope,
                        'selected_document_id': selected_document_id,
                        'classification': classifications_to_send
                    }
                    
                    # Get document details if specific document selected
                    if selected_document_id and selected_document_id != "all":
                        try:
                            # Use the appropriate documents container based on scope
                            if document_scope == 'group':
                                cosmos_container = cosmos_group_documents_container
                            elif document_scope == 'public':
                                cosmos_container = cosmos_public_documents_container
                            elif document_scope == 'personal':
                                cosmos_container = cosmos_user_documents_container
                            
                            doc_query = "SELECT c.file_name, c.title, c.document_id, c.group_id FROM c WHERE c.id = @doc_id"
                            doc_params = [{"name": "@doc_id", "value": selected_document_id}]
                            doc_results = list(cosmos_container.query_items(
                                query=doc_query, parameters=doc_params, enable_cross_partition_query=True
                            ))
                            if doc_results:
                                doc_info = doc_results[0]
                                user_metadata['workspace_search']['document_name'] = doc_info.get('title') or doc_info.get('file_name')
                                user_metadata['workspace_search']['document_filename'] = doc_info.get('file_name')
                        except Exception as e:
                            debug_print(f"Error retrieving document details: {e}")
                    
                    # Add scope-specific details
                    if document_scope == 'group' and active_group_id:
                        try:
                            from functions_debug import debug_print
                            debug_print(f"Workspace search - looking up group for id: {active_group_id}")
                            group_doc = find_group_by_id(active_group_id)
                            debug_print(f"Workspace search group lookup result: {group_doc}")
                            
                            if group_doc and group_doc.get('name'):
                                group_name = group_doc.get('name')
                                user_metadata['workspace_search']['group_name'] = group_name
                                debug_print(f"Workspace search - set group_name to: {group_name}")
                            else:
                                debug_print(f"Workspace search - no group found or no name for id: {active_group_id}")
                                user_metadata['workspace_search']['group_name'] = None
                                
                        except Exception as e:
                            debug_print(f"Error retrieving group details: {e}")
                            user_metadata['workspace_search']['group_name'] = None
                            import traceback
                            traceback.print_exc()
                    
                    if document_scope == 'public' and active_public_workspace_id:
                        # Check if public workspace status allows chat operations
                        try:
                            from functions_public_workspaces import find_public_workspace_by_id, check_public_workspace_status_allows_operation
                            workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
                            if workspace_doc:
                                allowed, reason = check_public_workspace_status_allows_operation(workspace_doc, 'chat')
                                if not allowed:
                                    yield f"data: {json.dumps({'error': reason})}\n\n"
                                    return
                        except Exception as e:
                            debug_print(f"Error checking public workspace status: {e}")
                        
                        user_metadata['workspace_search']['active_public_workspace_id'] = active_public_workspace_id
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
                        document_scope=document_scope,
                        chat_context=actual_chat_type
                    )
                except Exception as e:
                    debug_print(f"Activity logging error: {e}")
                
                # Update conversation title
                if conversation_item.get('title', 'New Conversation') == 'New Conversation' and user_message:
                    new_title = (user_message[:30] + '...') if len(user_message) > 30 else user_message
                    conversation_item['title'] = new_title
                
                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                cosmos_conversations_container.upsert_item(conversation_item)

                # Generate assistant_message_id early for thought tracking
                assistant_message_id = f"{conversation_id}_assistant_{int(time.time())}_{random.randint(1000,9999)}"

                # Initialize thought tracker for streaming path
                thought_tracker = ThoughtTracker(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    thread_id=current_user_thread_id,
                    user_id=user_id
                )

                def serialize_thought_event(step_type, content, step_index, message_id=None):
                    return f"data: {json.dumps({'type': 'thought', 'message_id': message_id or assistant_message_id, 'step_index': step_index, 'step_type': step_type, 'content': content})}\n\n"

                def emit_thought(step_type, content, detail=None):
                    """Add a thought to Cosmos and return an SSE event string."""
                    thought_tracker.add_thought(step_type, content, detail)
                    return serialize_thought_event(step_type, content, thought_tracker.current_index - 1)

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
                                'metadata': {}
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
                            safety_message_id = f"{conversation_id}_safety_{int(time.time())}_{random.randint(1000,9999)}"
                            safety_doc = {
                                'id': safety_message_id,
                                'conversation_id': conversation_id,
                                'role': 'safety',
                                'content': blocked_msg_content.strip(),
                                'timestamp': datetime.utcnow().isoformat(),
                                'model_deployment_name': None,
                                'metadata': {},
                            }
                            cosmos_messages_container.upsert_item(safety_doc)

                            conversation_item['last_updated'] = datetime.utcnow().isoformat()
                            cosmos_conversations_container.upsert_item(conversation_item)

                            # Stream the blocked response and stop
                            yield f"data: {json.dumps({'content': blocked_msg_content.strip(), 'blocked': True})}\n\n"
                            yield "data: [DONE]\n\n"
                            return

                    except HttpResponseError as e:
                        debug_print(f"[Content Safety Error - Streaming] {e}")
                    except Exception as ex:
                        debug_print(f"[Content Safety - Streaming] Unexpected error: {ex}")

                # Hybrid search (if enabled)
                combined_documents = []
                if hybrid_search_enabled:
                    debug_print(
                        "[Streaming] Starting hybrid search | "
                        f"conversation_id={conversation_id} | doc_scope={document_scope} | "
                        f"selected_document_ids={len(selected_document_ids)} | tags={len(tags_filter) if isinstance(tags_filter, list) else 0}"
                    )
                    yield emit_thought('search', f"Searching {document_scope or 'personal'} workspace documents for '{(search_query or user_message)[:50]}'")
                    try:
                        search_args = {
                            "query": search_query,
                            "user_id": user_id,
                            "top_n": 12,
                            "doc_scope": document_scope,
                        }
                        
                        if active_group_ids and (document_scope == 'group' or document_scope == 'all' or chat_type == 'group'):
                            search_args['active_group_ids'] = active_group_ids
                        
                        # Add active_public_workspace_id when:
                        # 1. Document scope is 'public' or
                        # 2. Document scope is 'all' and public workspaces are enabled
                        if active_public_workspace_id and (document_scope == 'public' or document_scope == 'all'):
                            search_args['active_public_workspace_id'] = active_public_workspace_id
                        
                        if selected_document_ids:
                            search_args['document_ids'] = selected_document_ids
                        elif selected_document_id:
                            search_args['document_id'] = selected_document_id
                        
                        # Add tags filter if provided
                        if tags_filter and isinstance(tags_filter, list) and len(tags_filter) > 0:
                            search_args['tags_filter'] = tags_filter
                        
                        search_results = hybrid_search(**search_args)
                        debug_print(
                            f"[Streaming] Hybrid search completed | results={len(search_results) if search_results else 0}"
                        )
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
                                doc_id = doc.get('document_id') or doc.get('id')
                                if not doc_id or doc_id in processed_doc_ids:
                                    continue
                                
                                processed_doc_ids.add(doc_id)
                                
                                file_name = doc.get('file_name', 'Unknown')
                                doc_group_id = doc.get('group_id', None)
                                
                                # Map document_scope to correct parameter names for the function
                                metadata_params = {'user_id': user_id}
                                if document_scope == 'group':
                                    metadata_params['group_id'] = active_group_id
                                elif document_scope == 'public':
                                    metadata_params['public_workspace_id'] = active_public_workspace_id
                                
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

                        # Reorder hybrid citations list in descending order based on page_number
                        hybrid_citations_list.sort(key=lambda x: x.get('page_number', 0), reverse=True)
                
                workspace_tabular_file_contexts = []
                workspace_tabular_files = set()
                if hybrid_search_enabled and is_tabular_processing_enabled(settings):
                    workspace_tabular_file_contexts = collect_workspace_tabular_file_contexts(
                        combined_documents=combined_documents,
                        selected_document_ids=selected_document_ids,
                        selected_document_id=selected_document_id,
                        document_scope=document_scope,
                        active_group_id=active_group_id,
                        active_public_workspace_id=active_public_workspace_id,
                    )
                    workspace_tabular_files = {
                        file_context['file_name'] for file_context in workspace_tabular_file_contexts
                    }

                if hybrid_search_enabled and workspace_tabular_files and is_tabular_processing_enabled(settings):
                    tabular_source_hint = determine_tabular_source_hint(
                        document_scope,
                        active_group_id=active_group_id,
                        active_public_workspace_id=active_public_workspace_id,
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

                    tabular_analysis = asyncio.run(run_tabular_sk_analysis(
                        user_question=user_message,
                        tabular_filenames=workspace_tabular_files,
                        tabular_file_contexts=workspace_tabular_file_contexts,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        gpt_model=gpt_model,
                        settings=settings,
                        source_hint=tabular_source_hint,
                        group_id=active_group_id if tabular_source_hint == 'group' else None,
                        public_workspace_id=active_public_workspace_id if tabular_source_hint == 'public' else None,
                        execution_mode=tabular_execution_mode,
                    ))
                    tabular_invocations = get_new_plugin_invocations(
                        plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000),
                        baseline_tabular_invocation_count
                    )
                    debug_print(
                        "[Streaming][Tabular SK] Completed workspace tabular analysis | "
                        f"analysis_returned={bool(tabular_analysis)} | new_invocations={len(tabular_invocations)}"
                    )
                    tabular_thought_payloads = get_tabular_tool_thought_payloads(tabular_invocations)
                    for thought_content, thought_detail in tabular_thought_payloads:
                        yield emit_thought('tabular_analysis', thought_content, thought_detail)
                    tabular_status_thought_payloads = get_tabular_status_thought_payloads(
                        tabular_invocations,
                        analysis_succeeded=bool(tabular_analysis),
                    )
                    for thought_content, thought_detail in tabular_status_thought_payloads:
                        yield emit_thought('tabular_analysis', thought_content, thought_detail)

                    if tabular_analysis:
                        system_messages_for_augmentation.append({
                            'role': 'system',
                            'content': build_tabular_computed_results_system_message(
                                f"the file(s) {tabular_filenames_str}",
                                tabular_analysis,
                            )
                        })

                        tabular_sk_citations = collect_tabular_sk_citations(user_id, conversation_id)
                        if tabular_sk_citations:
                            agent_citations_list.extend(tabular_sk_citations)
                    else:
                        system_messages_for_augmentation.append({
                            'role': 'system',
                            'content': build_tabular_fallback_system_message(
                                tabular_filenames_str,
                                execution_mode=tabular_execution_mode,
                            )
                        })

                        yield emit_thought(
                            'tabular_analysis',
                            "Tabular analysis could not compute results; using schema context instead",
                            detail=f"files={tabular_filenames_str}"
                        )

                if web_search_enabled:
                    debug_print(
                        f"[Streaming] Starting web search augmentation for conversation_id={conversation_id}"
                    )
                    yield emit_thought('web_search', f"Searching the web for '{(search_query or user_message)[:50]}'")
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
                        search_query=search_query,
                        system_messages_for_augmentation=system_messages_for_augmentation,
                        agent_citations_list=agent_citations_list,
                        web_search_citations_list=web_search_citations_list,
                    )
                    if web_search_citations_list:
                        debug_print(
                            f"[Streaming] Web search completed | citations={len(web_search_citations_list)}"
                        )
                        yield emit_thought('web_search', f"Got {len(web_search_citations_list)} web search results")

                # Update message chat type
                message_chat_type = None
                if hybrid_search_enabled and search_results and len(search_results) > 0:
                    if document_scope == 'group':
                        message_chat_type = 'group'
                    elif document_scope == 'public':
                        message_chat_type = 'public'
                    else:
                        message_chat_type = 'personal_single_user'
                else:
                    message_chat_type = 'Model'
                
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

                        chat_tabular_analysis = asyncio.run(run_tabular_sk_analysis(
                            user_question=user_message,
                            tabular_filenames=chat_tabular_files,
                            user_id=user_id,
                            conversation_id=conversation_id,
                            gpt_model=gpt_model,
                            settings=settings,
                            source_hint="chat",
                            execution_mode=chat_tabular_execution_mode,
                        ))
                        chat_tabular_invocations = get_new_plugin_invocations(
                            plugin_logger.get_invocations_for_conversation(user_id, conversation_id, limit=1000),
                            baseline_tabular_invocation_count
                        )
                        debug_print(
                            "[Streaming][Chat Tabular SK] Completed chat-uploaded tabular analysis | "
                            f"analysis_returned={bool(chat_tabular_analysis)} | new_invocations={len(chat_tabular_invocations)}"
                        )
                        chat_tabular_thought_payloads = get_tabular_tool_thought_payloads(chat_tabular_invocations)
                        for thought_content, thought_detail in chat_tabular_thought_payloads:
                            yield emit_thought('tabular_analysis', thought_content, thought_detail)
                        chat_tabular_status_thought_payloads = get_tabular_status_thought_payloads(
                            chat_tabular_invocations,
                            analysis_succeeded=bool(chat_tabular_analysis),
                        )
                        for thought_content, thought_detail in chat_tabular_status_thought_payloads:
                            yield emit_thought('tabular_analysis', thought_content, thought_detail)

                        if chat_tabular_analysis:
                            conversation_history_for_api.append({
                                'role': 'system',
                                'content': build_tabular_computed_results_system_message(
                                    f"the chat-uploaded file(s) {chat_tabular_filenames_str}",
                                    chat_tabular_analysis,
                                )
                            })
                            final_api_source_refs.append('system:tabular_results')

                            # Collect tool execution citations
                            chat_tabular_sk_citations = collect_tabular_sk_citations(user_id, conversation_id)
                            if chat_tabular_sk_citations:
                                agent_citations_list.extend(chat_tabular_sk_citations)

                            debug_print(f"[Chat Tabular SK] Streaming: Analysis injected, {len(chat_tabular_analysis)} chars")
                        else:
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
                
                # Check if agents are enabled and should be used
                selected_agent = None
                selected_agent_metadata = None
                agent_name_used = None
                agent_display_name_used = None
                use_agent_streaming = False
                
                if enable_semantic_kernel and user_enable_agents:
                    # Agent selection logic (similar to non-streaming)
                    kernel = get_kernel()
                    all_agents = get_kernel_agents()
                    
                    if all_agents:
                        agent_name_to_select = None
                        if per_user_semantic_kernel:
                            # user_settings.get('selected_agent') returns a dict with agent info
                            selected_agent_info = user_settings.get('selected_agent')
                            if isinstance(selected_agent_info, dict):
                                agent_name_to_select = selected_agent_info.get('name')
                                selected_agent_metadata = {
                                    'selected_agent': selected_agent_info.get('name'),
                                    'agent_display_name': selected_agent_info.get('display_name'),
                                    'is_global': selected_agent_info.get('is_global', False),
                                    'is_group': selected_agent_info.get('is_group', False),
                                    'group_id': selected_agent_info.get('group_id'),
                                    'group_name': selected_agent_info.get('group_name'),
                                    'agent_id': selected_agent_info.get('id')
                                }
                            elif isinstance(selected_agent_info, str):
                                agent_name_to_select = selected_agent_info
                            debug_print(f"[Streaming] Per-user agent name to select: {agent_name_to_select}")
                        else:
                            global_selected_agent_info = settings.get('global_selected_agent')
                            if global_selected_agent_info:
                                agent_name_to_select = global_selected_agent_info.get('name')
                                selected_agent_metadata = {
                                    'selected_agent': global_selected_agent_info.get('name'),
                                    'agent_display_name': global_selected_agent_info.get('display_name'),
                                    'is_global': global_selected_agent_info.get('is_global', False),
                                    'is_group': global_selected_agent_info.get('is_group', False),
                                    'group_id': global_selected_agent_info.get('group_id'),
                                    'group_name': global_selected_agent_info.get('group_name'),
                                    'agent_id': global_selected_agent_info.get('id')
                                }
                            debug_print(f"[Streaming] Global agent name to select: {agent_name_to_select}")
                        
                        # Find the agent
                        agent_iter = all_agents.values() if isinstance(all_agents, dict) else all_agents
                        for agent in agent_iter:
                            agent_obj_name = getattr(agent, 'name', None)
                            debug_print(f"[Streaming] Checking agent: {agent_obj_name} against target: {agent_name_to_select}")
                            if agent_name_to_select and agent_obj_name == agent_name_to_select:
                                selected_agent = agent
                                debug_print(f"[Streaming] ✅ Found matching agent: {agent_obj_name}")
                                break
                        
                        # Fallback to default agent
                        if not selected_agent:
                            for agent in agent_iter:
                                if getattr(agent, 'default_agent', False):
                                    selected_agent = agent
                                    debug_print(f"[Streaming] Using default agent: {getattr(agent, 'name', 'unknown')}")
                                    break
                        
                        # Fallback to first agent
                        if not selected_agent:
                            selected_agent = next(iter(agent_iter), None)
                            if selected_agent:
                                debug_print(f"[Streaming] Using first agent: {getattr(selected_agent, 'name', 'unknown')}")
                        
                        if selected_agent:
                            use_agent_streaming = True
                            agent_name_used = getattr(selected_agent, 'name', 'agent')
                            agent_display_name_used = getattr(selected_agent, 'display_name', agent_name_used)
                            if not selected_agent_metadata:
                                selected_agent_metadata = {
                                    'selected_agent': agent_name_used,
                                    'agent_display_name': agent_display_name_used,
                                    'is_global': getattr(selected_agent, 'is_global', False),
                                    'is_group': getattr(selected_agent, 'is_group', False),
                                    'group_id': getattr(selected_agent, 'group_id', None),
                                    'group_name': getattr(selected_agent, 'group_name', None),
                                    'agent_id': getattr(selected_agent, 'id', None)
                                }
                            actual_model_used = getattr(selected_agent, 'deployment_name', None) or gpt_model
                            debug_print(f"--- Streaming from Agent: {agent_name_used} (model: {actual_model_used}) ---")
                        else:
                            debug_print(f"[Streaming] ⚠️ No agent selected, falling back to GPT")

                    inject_fact_memory_context(
                        conversation_history=conversation_history_for_api,
                        scope_id=scope_id,
                        scope_type=scope_type,
                        conversation_id=conversation_id,
                        agent_id=getattr(selected_agent, 'id', None),
                    )
                
                # Stream the response
                accumulated_content = ""
                token_usage_data = None  # Will be populated from final stream chunk
                # assistant_message_id was generated earlier for thought tracking
                final_model_used = gpt_model  # Default to gpt_model, will be overridden if agent is used
                
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

                                    agent_stream = selected_agent.invoke_stream(messages=agent_message_history)
                                    while True:
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
                                            yield f"data: {json.dumps({'content': chunk_content})}\\n\\n"

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
                            yield f"data: {json.dumps({'error': f'Agent streaming failed: {str(stream_error)}'})}\n\n"
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
                            
                            def make_json_serializable(obj):
                                if obj is None:
                                    return None
                                elif isinstance(obj, (str, int, float, bool)):
                                    return obj
                                elif isinstance(obj, dict):
                                    return {str(k): make_json_serializable(v) for k, v in obj.items()}
                                elif isinstance(obj, (list, tuple)):
                                    return [make_json_serializable(item) for item in obj]
                                else:
                                    return str(obj)
                            
                            citation = {
                                'tool_name': f"{inv.plugin_name}.{inv.function_name}",
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
                        if stream_selected_agent_type in ('aifoundry', 'new_foundry') and foundry_citations:
                            foundry_plugin_name = 'new_foundry' if stream_selected_agent_type == 'new_foundry' else 'azure_ai_foundry'
                            foundry_label = agent_name_used or ('New Foundry Application' if stream_selected_agent_type == 'new_foundry' else 'Azure AI Foundry Agent')
                            for citation in foundry_citations:
                                yield emit_thought('agent_tool_call', 'Agent retrieved citation from Azure AI Foundry')
                                try:
                                    serializable = json.loads(json.dumps(citation, default=str))
                                except (TypeError, ValueError):
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
                            if chunk.choices and len(chunk.choices) > 0:
                                delta = chunk.choices[0].delta
                                if delta.content:
                                    accumulated_content += delta.content
                                    yield f"data: {json.dumps({'content': delta.content})}\n\n"
                            
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
                    
                    # Stream complete - save message and send final metadata
                    # Get user thread info to maintain thread consistency
                    user_thread_id = None
                    user_previous_thread_id = None
                    user_info_for_assistant = None
                    try:
                        user_msg = cosmos_messages_container.read_item(
                            item=user_message_id,
                            partition_key=conversation_id
                        )
                        user_info_for_assistant = user_msg.get('metadata', {}).get('user_info')
                        user_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
                        user_previous_thread_id = user_msg.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
                    except Exception as e:
                        debug_print(f"Warning: Could not retrieve thread_id from user message: {e}")
                    assistant_timestamp = datetime.utcnow().isoformat()
                    prepared_agent_citations = persist_agent_citation_artifacts(
                        conversation_id=conversation_id,
                        assistant_message_id=assistant_message_id,
                        agent_citations=agent_citations_list,
                        created_timestamp=assistant_timestamp,
                        user_info=user_info_for_assistant,
                    )

                    assistant_doc = {
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
                            'reasoning_effort': reasoning_effort,
                            'history_context': history_debug_info,
                            'thread_info': {
                                'thread_id': user_thread_id,
                                'previous_thread_id': user_previous_thread_id,
                                'active_thread': True,
                                'thread_attempt': 1
                            },
                            'token_usage': token_usage_data if token_usage_data else None  # Store token usage from stream
                        }
                    }
                    cosmos_messages_container.upsert_item(assistant_doc)
                    
                    # Log chat token usage to activity_logs for easy reporting
                    if token_usage_data and token_usage_data.get('total_tokens'):
                        try:
                            from functions_activity_logging import log_token_usage
                            
                            # Determine workspace type based on active group/public workspace
                            workspace_type = 'personal'
                            if active_public_workspace_id:
                                workspace_type = 'public'
                            elif active_group_id:
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
                                group_id=active_group_id,
                                public_workspace_id=active_public_workspace_id,
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
                        conversation_item = collect_conversation_metadata(
                            user_message=user_message,
                            conversation_id=conversation_id,
                            user_id=user_id,
                            active_group_id=active_group_id,
                            active_group_ids=active_group_ids,
                            document_scope=document_scope,
                            selected_document_id=selected_document_id,
                            model_deployment=gpt_model,
                            hybrid_search_enabled=hybrid_search_enabled,
                            image_gen_enabled=False,
                            selected_documents=combined_documents if combined_documents else None,
                            selected_agent=agent_name_used if use_agent_streaming else None,
                            selected_agent_details=selected_agent_metadata if use_agent_streaming else None,
                            search_results=search_results if search_results else None,
                            conversation_item=conversation_item,
                            active_public_workspace_id=active_public_workspace_id,
                            active_public_workspace_ids=active_public_workspace_ids
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
                    final_data = {
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
                        'agent_citations': prepared_agent_citations,
                        'agent_display_name': agent_display_name_used if use_agent_streaming else None,
                        'agent_name': agent_name_used if use_agent_streaming else None,
                        'full_content': accumulated_content,
                        'thoughts_enabled': thought_tracker.enabled
                    }
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
                        
                        assistant_doc = {
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
                                'thread_info': {
                                    'thread_id': user_thread_id,
                                    'previous_thread_id': user_previous_thread_id,
                                    'active_thread': True,
                                    'thread_attempt': 1
                                }
                            }
                        }
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

    @app.route('/api/chat/stream/status/<conversation_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def chat_stream_status_api(conversation_id):
        """Report whether a conversation has a live stream that can be reattached."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        stream_session = CHAT_STREAM_REGISTRY.get_session(user_id, conversation_id, active_only=True)
        return jsonify({
            'conversation_id': conversation_id,
            'pending': bool(stream_session),
            'reattachable': bool(stream_session),
        })

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

        return Response(
            stream_with_context(stream_session.iter_events()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )

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
            settings = get_settings()
            data = request.get_json()
            user_id = get_current_user_id()
            
            if not user_id:
                return jsonify({'error': 'User not authenticated'}), 401
            
            # Get action: "mask_all", "mask_selection", or "unmask_all"
            action = data.get('action')
            selection = data.get('selection', {})
            user_display_name = data.get('display_name', 'Unknown User')
            
            # Validate action
            if action not in ['mask_all', 'mask_selection', 'unmask_all']:
                return jsonify({'error': 'Invalid action'}), 400
            
            # Fetch the message
            try:
                # Query for the message (need conversation_id for partition key)
                query = "SELECT * FROM c WHERE c.id = @message_id"
                params = [{"name": "@message_id", "value": message_id}]
                
                # We need to find the message across all partitions first
                # This is inefficient but necessary without knowing the conversation_id
                message_results = list(cosmos_messages_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True
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
            if action == 'mask_all':
                # Mask the entire message
                message_doc['metadata']['masked'] = True
                message_doc['metadata']['masked_by_user_id'] = user_id
                message_doc['metadata']['masked_timestamp'] = datetime.now(timezone.utc).isoformat()
                message_doc['metadata']['masked_by_display_name'] = user_display_name
                
            elif action == 'unmask_all':
                # Unmask the entire message and clear all masked ranges
                message_doc['metadata']['masked'] = False
                message_doc['metadata']['masked_ranges'] = []
                message_doc['metadata']['masked_by_user_id'] = None
                message_doc['metadata']['masked_timestamp'] = None
                message_doc['metadata']['masked_by_display_name'] = None
                
            elif action == 'mask_selection':
                # Mask a selection of text
                start = selection.get('start')
                end = selection.get('end')
                text = selection.get('text', '')
                
                if start is None or end is None:
                    return jsonify({'error': 'Selection start and end required'}), 400
                
                # Initialize masked_ranges if it doesn't exist
                if 'masked_ranges' not in message_doc['metadata']:
                    message_doc['metadata']['masked_ranges'] = []
                
                # Create new masked range
                new_range = {
                    'id': str(uuid.uuid4()),
                    'user_id': user_id,
                    'display_name': user_display_name,
                    'start': start,
                    'end': end,
                    'text': text,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
                
                # Add the new range
                message_doc['metadata']['masked_ranges'].append(new_range)
                
                # Sort and merge overlapping/adjacent ranges
                message_doc['metadata']['masked_ranges'] = merge_masked_ranges(
                    message_doc['metadata']['masked_ranges']
                )
            
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


def merge_masked_ranges(ranges):
    """
    Merge overlapping and adjacent masked ranges.
    Preserves the earliest timestamp and user info for merged ranges.
    """
    if not ranges:
        return []
    
    # Sort by start position
    sorted_ranges = sorted(ranges, key=lambda x: x['start'])
    merged = [sorted_ranges[0]]
    
    for current in sorted_ranges[1:]:
        last_merged = merged[-1]
        
        # Check if current range overlaps or is adjacent to the last merged range
        if current['start'] <= last_merged['end']:
            # Merge: extend the end if current goes further
            if current['end'] > last_merged['end']:
                last_merged['end'] = current['end']
                # Update text to cover merged range
                last_merged['text'] = last_merged['text'] + current['text'][last_merged['end'] - current['start']:]
            # Keep the earliest timestamp
            if current['timestamp'] < last_merged['timestamp']:
                last_merged['timestamp'] = current['timestamp']
        else:
            # No overlap, add as separate range
            merged.append(current)
    
    return merged


def remove_masked_content(content, masked_ranges):
    """
    Remove masked portions from message content.
    Works backwards through sorted ranges to maintain correct offsets.
    """
    if not masked_ranges or not content:
        return content
    
    # Sort ranges by start position (descending) to work backwards
    sorted_ranges = sorted(masked_ranges, key=lambda x: x['start'], reverse=True)
    
    # Create a list from content for easier manipulation
    result = content
    
    # Remove masked ranges working backwards to maintain offsets
    for range_item in sorted_ranges:
        start = range_item['start']
        end = range_item['end']
        
        # Ensure indices are within bounds
        if start < 0:
            start = 0
        if end > len(result):
            end = len(result)
        
        # Remove the masked portion
        if start < end:
            result = result[:start] + result[end:]
    
    return result


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
    eligible_citations = []
    for citation in agent_citations or []:
        if isinstance(citation, dict):
            tool_name = str(citation.get('tool_name') or citation.get('function_name') or '').strip()
            if tool_name.startswith('[Debug]') or tool_name == 'Conversation History':
                continue
        eligible_citations.append(citation)

    lines = []
    for citation in eligible_citations[:max_citations]:
        if not isinstance(citation, dict):
            value_summary = _serialize_history_citation_value(citation, max_chars=800)
            if value_summary:
                lines.append(f"- Tool result: {value_summary}")
            continue

        tool_name = str(citation.get('tool_name') or citation.get('function_name') or 'Tool invocation').strip()
        argument_summary = _serialize_history_citation_value(citation.get('function_arguments'), max_chars=350)
        result_summary = _serialize_history_citation_value(citation.get('function_result'), max_chars=1400)
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
        + "\n\n".join(citation_sections)
        + "\n</Supporting citation context from this assistant turn>"
    )
    citation_context = _truncate_history_citation_text(citation_context, max_chars=3200)

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
                    messages=[{"role": "system", "content": summary_prompt_older}],
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
    search_query,
    system_messages_for_augmentation,
    agent_citations_list,
    web_search_citations_list,
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
    debug_print(f"[WebSearch]   search_query: {search_query[:100] if search_query else None}...")
    
    enable_web_search = settings.get("enable_web_search")
    debug_print(f"[WebSearch] enable_web_search setting: {enable_web_search}")
    
    if not enable_web_search:
        debug_print("[WebSearch] Web search is DISABLED in settings, returning early")
        return True  # Not an error, just disabled

    debug_print("[WebSearch] Web search is ENABLED, proceeding...")
    
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
        return False  # Configuration error

    debug_print(f"[WebSearch] Agent ID is configured: {agent_id}")
    
    query_text = None
    try:
        query_text = search_query
        debug_print(f"[WebSearch] Using search_query as query_text: {query_text[:100] if query_text else None}...")
    except NameError:
        query_text = None
        debug_print("[WebSearch] search_query not defined, query_text is None")

    query_text = (query_text or user_message or "").strip()
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
        return True  # Not an error, just empty query

    debug_print(f"[WebSearch] Building message history with query: {query_text[:100]}...")
    message_history = [
        ChatMessageContent(role="user", content=query_text)
    ]
    debug_print(f"[WebSearch] Message history created with {len(message_history)} message(s)")

    try:
        foundry_metadata = {
            "conversation_id": conversation_id,
            "user_id": user_id,
            "message_id": user_message_id,
            "chat_type": chat_type,
            "document_scope": document_scope,
            "group_id": active_group_id if chat_type == "group" else None,
            "public_workspace_id": active_public_workspace_id,
            "search_query": query_text,
        }
        debug_print(f"[WebSearch] Foundry metadata prepared: {json.dumps(foundry_metadata, default=str)}")
        
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
        system_messages_for_augmentation.append({
            "role": "system",
            "content": f"Web search results:\n{result.message}",
        })
        debug_print(f"[WebSearch] Added system message to augmentation list. Total augmentation messages: {len(system_messages_for_augmentation)}")

        debug_print("[WebSearch] Extracting web citations from result message...")
        web_citations = _extract_web_search_citations_from_content(result.message)
        debug_print(f"[WebSearch] Extracted {len(web_citations)} web citations from message content")
        if web_citations:
            web_search_citations_list.extend(web_citations)
            debug_print(f"[WebSearch] Total web_search_citations_list now has {len(web_search_citations_list)} citations")
        else:
            debug_print("[WebSearch] No web citations extracted from message content")
    else:
        debug_print("[WebSearch] No result.message to process for augmentation")

    citations = result.citations or []
    debug_print(f"[WebSearch] Processing {len(citations)} citations from result.citations")
    if citations:
        for i, citation in enumerate(citations):
            debug_print(f"[WebSearch] Processing citation {i}: {json.dumps(citation, default=str)[:200]}...")
            try:
                serializable = json.loads(json.dumps(citation, default=str))
            except (TypeError, ValueError):
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
        debug_print(f"[WebSearch] Total agent_citations_list now has {len(agent_citations_list)} citations")
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
    
    return True  # Search succeeded
