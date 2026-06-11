# route_backend_conversations.py

import logging
import math
import re

from collaboration_models import GROUP_MULTI_USER_CHAT_TYPE, PERSONAL_MULTI_USER_CHAT_TYPE
from config import *
from functions_appinsights import log_event
from functions_authentication import *
from functions_collaboration import (
    assert_user_can_view_collaboration_conversation,
    assert_user_can_participate_in_collaboration_conversation,
    ensure_collaboration_source_conversation,
    get_collaboration_conversation,
    list_group_collaboration_conversations_for_user,
    list_collaboration_messages,
    list_personal_collaboration_conversations_for_user,
    serialize_collaboration_conversation,
)
from functions_settings import *
from functions_conversation_feed import (
    CONVERSATION_FEED_SOURCE_COLLABORATION,
    CONVERSATION_FEED_SOURCE_LEGACY,
    build_conversation_feed_page,
    decode_conversation_feed_cursor,
    get_conversation_feed_source_offsets,
    is_conversation_feed_cursor_compatible,
    normalize_conversation_feed_page_size,
    sort_conversation_feed_recent,
    tag_conversation_feed_source,
)
from functions_conversation_metadata import get_conversation_metadata, update_conversation_with_metadata
from functions_conversation_unread import clear_conversation_unread, normalize_conversation_unread_state
from functions_image_messages import decode_image_content, get_complete_image_content, hydrate_image_messages, is_blob_backed_image_message, is_external_image_url
from functions_notifications import mark_chat_response_notifications_read_for_conversation
from flask import Response, request, stream_with_context
from functions_debug import debug_print
from functions_documents import (
    delete_chat_upload_workspace_documents_for_conversation,
    serialize_chat_upload_workspace_documents_for_conversation,
)
from functions_message_artifacts import (
    build_message_artifact_payload_map,
    filter_assistant_artifact_items,
    hydrate_agent_citations_from_artifacts,
)
from functions_simplechat_operations import (
    create_personal_conversation_for_current_user,
    delete_blob_backed_chat_message_files,
    derive_conversation_title_from_message,
)
from swagger_wrapper import swagger_route, get_auth_security
from functions_activity_logging import log_conversation_creation, log_conversation_deletion, log_conversation_archival
from functions_thoughts import archive_thoughts_for_conversation, delete_thoughts_for_conversation
from utils_cache import invalidate_personal_search_cache

def normalize_chat_type(conversation_item):
    chat_type = conversation_item.get('chat_type')
    if chat_type:
        if chat_type == 'personal':
            conversation_item['chat_type'] = 'personal_single_user'
            return conversation_item['chat_type'], True
        return chat_type, False

    primary_context = next(
        (ctx for ctx in conversation_item.get('context', []) if ctx.get('type') == 'primary'),
        None
    )
    if primary_context:
        if primary_context.get('scope') == 'group':
            chat_type = 'group-single-user'
        elif primary_context.get('scope') == 'public':
            chat_type = 'public'
        else:
            chat_type = 'personal_single_user'
    else:
        chat_type = 'personal_single_user'

    conversation_item['chat_type'] = chat_type
    return chat_type, True


SEARCH_MATCH_CONTAINS = 'contains'
SEARCH_MATCH_ALL_WORDS = 'all_words'
SEARCH_MATCH_ANY_WORD = 'any_word'
SEARCH_MATCH_WHOLE_WORD = 'whole_word'
SEARCH_MATCH_MODES = {
    SEARCH_MATCH_CONTAINS,
    SEARCH_MATCH_ALL_WORDS,
    SEARCH_MATCH_ANY_WORD,
    SEARCH_MATCH_WHOLE_WORD,
}

SEARCH_CHAT_TYPE_ALIASES = {
    'personal': {'personal_single_user', PERSONAL_MULTI_USER_CHAT_TYPE},
    'personal-single-user': {'personal_single_user'},
    'personal_single_user': {'personal_single_user'},
    'personal-multi-user': {PERSONAL_MULTI_USER_CHAT_TYPE},
    PERSONAL_MULTI_USER_CHAT_TYPE: {PERSONAL_MULTI_USER_CHAT_TYPE},
    'group': {'group-single-user', GROUP_MULTI_USER_CHAT_TYPE},
    'group-single-user': {'group-single-user'},
    'group_single_user': {'group-single-user'},
    'group-multi-user': {GROUP_MULTI_USER_CHAT_TYPE},
    GROUP_MULTI_USER_CHAT_TYPE: {GROUP_MULTI_USER_CHAT_TYPE},
    'public': {'public'},
}


def _normalize_workspace_document_delete_ids(raw_document_ids):
    if raw_document_ids is None:
        return []
    if not isinstance(raw_document_ids, list):
        raise ValueError('delete_workspace_document_ids must be an array')

    normalized_document_ids = []
    seen_document_ids = set()
    for raw_document_id in raw_document_ids:
        document_id = str(raw_document_id or '').strip()
        if not document_id or document_id in seen_document_ids:
            continue
        seen_document_ids.add(document_id)
        normalized_document_ids.append(document_id)

    return normalized_document_ids


def _get_requested_workspace_document_delete_ids_for_conversation(payload, conversation_id):
    if not isinstance(payload, dict):
        return []

    if 'delete_workspace_document_ids' in payload:
        return _normalize_workspace_document_delete_ids(payload.get('delete_workspace_document_ids'))

    delete_ids_by_conversation = payload.get('delete_workspace_document_ids_by_conversation')
    if isinstance(delete_ids_by_conversation, dict):
        return _normalize_workspace_document_delete_ids(delete_ids_by_conversation.get(conversation_id))

    return []


def _normalize_search_match_mode(match_mode):
    normalized_mode = str(match_mode or SEARCH_MATCH_CONTAINS).strip().lower().replace('-', '_')
    if normalized_mode in SEARCH_MATCH_MODES:
        return normalized_mode
    return SEARCH_MATCH_CONTAINS


def _tokenize_search_terms(search_term):
    return [term for term in re.split(r'\s+', str(search_term or '').strip()) if term]


def _get_message_query_terms(search_term, match_mode):
    normalized_mode = _normalize_search_match_mode(match_mode)
    if normalized_mode in (SEARCH_MATCH_ALL_WORDS, SEARCH_MATCH_ANY_WORD):
        return _tokenize_search_terms(search_term)
    return [str(search_term or '').strip()]


def _normalize_search_chat_type_value(chat_type):
    normalized_type = str(chat_type or '').strip().lower()
    if not normalized_type:
        return 'personal_single_user'

    if normalized_type == 'personal':
        return 'personal_single_user'
    if normalized_type == 'group':
        return 'group-single-user'
    if normalized_type == 'group-multi-user':
        return GROUP_MULTI_USER_CHAT_TYPE
    if normalized_type == 'group_single_user':
        return 'group-single-user'
    if normalized_type == 'personal-multi-user':
        return PERSONAL_MULTI_USER_CHAT_TYPE
    if normalized_type == 'personal-single-user':
        return 'personal_single_user'
    return normalized_type


def _expand_search_chat_type_filters(chat_types):
    normalized_filters = set()
    for chat_type in chat_types or []:
        normalized_key = str(chat_type or '').strip().lower()
        if not normalized_key:
            continue
        normalized_filters.update(
            SEARCH_CHAT_TYPE_ALIASES.get(
                normalized_key,
                {_normalize_search_chat_type_value(normalized_key)},
            )
        )
    return normalized_filters


def _get_search_conversation_chat_type(conversation_item):
    raw_chat_type = str((conversation_item or {}).get('chat_type') or '').strip()
    if raw_chat_type:
        return _normalize_search_chat_type_value(raw_chat_type)

    normalized_item = dict(conversation_item or {})
    inferred_chat_type, _ = normalize_chat_type(normalized_item)
    return _normalize_search_chat_type_value(inferred_chat_type)


def _conversation_matches_selected_chat_types(conversation_item, selected_chat_types):
    if not selected_chat_types:
        return True
    return _get_search_conversation_chat_type(conversation_item) in selected_chat_types


def _conversation_matches_classifications(conversation_item, classifications):
    if not classifications:
        return True
    conversation_classifications = conversation_item.get('classification', []) or []
    return any(classification in conversation_classifications for classification in classifications)


def _conversation_timestamp(conversation_item):
    return (
        conversation_item.get('last_updated')
        or conversation_item.get('updated_at')
        or conversation_item.get('last_message_at')
        or conversation_item.get('created_at')
        or ''
    )


def _conversation_matches_date_range(conversation_item, date_from='', date_to=''):
    timestamp = _conversation_timestamp(conversation_item)
    if date_from and (not timestamp or timestamp < date_from):
        return False
    if date_to and (not timestamp or timestamp > f'{date_to}T23:59:59'):
        return False
    return True


def _matches_search_text(text, search_term, match_mode=SEARCH_MATCH_CONTAINS):
    normalized_mode = _normalize_search_match_mode(match_mode)
    text_value = str(text or '')
    text_lower = text_value.lower()
    normalized_search = str(search_term or '').strip()
    search_lower = normalized_search.lower()

    if not search_lower:
        return False

    if normalized_mode == SEARCH_MATCH_ALL_WORDS:
        terms = [term.lower() for term in _tokenize_search_terms(normalized_search)]
        return bool(terms) and all(term in text_lower for term in terms)

    if normalized_mode == SEARCH_MATCH_ANY_WORD:
        terms = [term.lower() for term in _tokenize_search_terms(normalized_search)]
        return bool(terms) and any(term in text_lower for term in terms)

    if normalized_mode == SEARCH_MATCH_WHOLE_WORD:
        whole_word_pattern = re.compile(rf'(?<!\w){re.escape(normalized_search)}(?!\w)', re.IGNORECASE)
        return whole_word_pattern.search(text_value) is not None

    return search_lower in text_lower


def _find_search_match(text, search_term, match_mode=SEARCH_MATCH_CONTAINS):
    normalized_mode = _normalize_search_match_mode(match_mode)
    text_value = str(text or '')
    text_lower = text_value.lower()
    normalized_search = str(search_term or '').strip()
    search_lower = normalized_search.lower()

    if not search_lower:
        return -1, 0

    if normalized_mode in (SEARCH_MATCH_ALL_WORDS, SEARCH_MATCH_ANY_WORD):
        matches = []
        for term in _tokenize_search_terms(normalized_search):
            position = text_lower.find(term.lower())
            if position != -1:
                matches.append((position, len(term)))
        if matches:
            return min(matches, key=lambda item: item[0])
        return -1, 0

    if normalized_mode == SEARCH_MATCH_WHOLE_WORD:
        whole_word_pattern = re.compile(rf'(?<!\w){re.escape(normalized_search)}(?!\w)', re.IGNORECASE)
        match = whole_word_pattern.search(text_value)
        if match:
            return match.start(), match.end() - match.start()
        return -1, 0

    position = text_lower.find(search_lower)
    return position, len(normalized_search) if position != -1 else 0


def _build_message_search_query(search_term, match_mode):
    query_terms = _get_message_query_terms(search_term, match_mode)
    query_terms = [term for term in query_terms if term]
    if not query_terms:
        return None, []

    operator = ' OR ' if _normalize_search_match_mode(match_mode) == SEARCH_MATCH_ANY_WORD else ' AND '
    contains_conditions = []
    parameters = []
    for index, term in enumerate(query_terms):
        parameter_name = f'@term{index}'
        contains_conditions.append(f'CONTAINS(m.content, {parameter_name}, true)')
        parameters.append({'name': parameter_name, 'value': term})

    query = (
        'SELECT * FROM m WHERE '
        f'({operator.join(contains_conditions)}) '
        "AND (m.role = 'user' OR m.role = 'assistant')"
    )
    return query, parameters


def _query_matching_messages(container, search_term, match_mode):
    query, parameters = _build_message_search_query(search_term, match_mode)
    if not query:
        return []

    messages = list(container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
        max_item_count=-1,
    ))

    return [
        message for message in messages
        if _matches_search_text(message.get('content', ''), search_term, match_mode)
    ]


def _message_is_in_active_thread(message_item):
    thread_info = (message_item.get('metadata') or {}).get('thread_info', {})
    return thread_info.get('active_thread') is not False


def _message_matches_attachment_filters(message_item, has_files=False, has_images=False):
    if not has_files and not has_images:
        return True

    metadata = message_item.get('metadata') or {}
    if has_files and metadata.get('uploaded_files'):
        return True
    if has_images and metadata.get('generated_images'):
        return True
    return False


def _build_message_snippets(matching_messages, search_term, match_mode, max_messages=5):
    message_snippets = []
    for message_item in matching_messages[:max_messages]:
        content = str(message_item.get('content', '') or '')
        match_pos, match_length = _find_search_match(content, search_term, match_mode)
        if match_pos == -1:
            continue

        start = max(0, match_pos - 50)
        end = min(len(content), match_pos + match_length + 50)
        snippet = content[start:end]

        if start > 0:
            snippet = f'...{snippet}'
        if end < len(content):
            snippet = f'{snippet}...'

        message_snippets.append({
            'message_id': message_item.get('id'),
            'content_snippet': snippet,
            'timestamp': message_item.get('timestamp', ''),
            'role': message_item.get('role', 'unknown'),
        })
    return message_snippets


def _build_search_conversation_payload(conversation_item):
    return {
        'id': conversation_item.get('id'),
        'title': conversation_item.get('title', 'Untitled'),
        'last_updated': _conversation_timestamp(conversation_item),
        'classification': conversation_item.get('classification', []) or [],
        'chat_type': _get_search_conversation_chat_type(conversation_item),
        'is_pinned': bool(conversation_item.get('is_pinned', False)),
        'is_hidden': bool(conversation_item.get('is_hidden', False)),
    }


def _load_accessible_collaboration_search_conversations(user_id):
    conversations = []
    seen_conversation_ids = set()

    for conversation_doc, user_state in list_personal_collaboration_conversations_for_user(user_id):
        serialized = serialize_collaboration_conversation(
            conversation_doc,
            current_user_id=user_id,
            user_state=user_state,
        )
        conversation_id = serialized.get('id')
        if conversation_id and conversation_id not in seen_conversation_ids:
            conversations.append(serialized)
            seen_conversation_ids.add(conversation_id)

    for conversation_doc, user_state in list_group_collaboration_conversations_for_user(user_id):
        serialized = serialize_collaboration_conversation(
            conversation_doc,
            current_user_id=user_id,
            user_state=user_state,
        )
        conversation_id = serialized.get('id')
        if conversation_id and conversation_id not in seen_conversation_ids:
            conversations.append(serialized)
            seen_conversation_ids.add(conversation_id)

    return conversations


def _is_conversation_priority(conversation_item):
    return bool(
        (conversation_item or {}).get('is_pinned', False)
        or (conversation_item or {}).get('has_unread_assistant_response', False)
    )


def _conversation_feed_matches_search(conversation_item, search_term):
    normalized_search = str(search_term or '').strip()
    if not normalized_search:
        return True
    return _matches_search_text((conversation_item or {}).get('title', ''), normalized_search)


def _query_legacy_conversations_for_feed(
    user_id,
    include_hidden=False,
    search_term='',
    extra_conditions=None,
    offset=0,
    limit=None,
):
    query_parts = ['c.user_id = @user_id']
    query_parameters = [{'name': '@user_id', 'value': user_id}]

    if not include_hidden:
        query_parts.append('(NOT IS_DEFINED(c.is_hidden) OR c.is_hidden = false)')

    if search_term:
        query_parts.append('(IS_STRING(c.title) AND CONTAINS(LOWER(c.title), @search_term))')
        query_parameters.append({'name': '@search_term', 'value': str(search_term).lower()})

    for condition in extra_conditions or []:
        query_parts.append(condition)

    normalized_offset = max(0, int(offset or 0))
    normalized_limit = None
    if limit is not None:
        normalized_limit = max(1, int(limit))

    query = f"SELECT * FROM c WHERE {' AND '.join(query_parts)} ORDER BY c.last_updated DESC"
    if normalized_limit is not None:
        query = f'{query} OFFSET {normalized_offset} LIMIT {normalized_limit}'

    items = list(cosmos_conversations_container.query_items(
        query=query,
        parameters=query_parameters,
        enable_cross_partition_query=True,
    ))

    return [
        tag_conversation_feed_source(
            normalize_conversation_unread_state(item),
            CONVERSATION_FEED_SOURCE_LEGACY,
        )
        for item in items
    ]


def _count_hidden_legacy_conversations(user_id):
    query = (
        'SELECT VALUE COUNT(1) FROM c '
        'WHERE c.user_id = @user_id AND c.is_hidden = true'
    )
    results = list(cosmos_conversations_container.query_items(
        query=query,
        parameters=[{'name': '@user_id', 'value': user_id}],
        enable_cross_partition_query=True,
    ))
    return int(results[0]) if results else 0


def _load_unread_collaboration_notification_map(user_id):
    query = """
        SELECT c.metadata.conversation_id AS conversation_id,
               c.metadata.message_id AS message_id,
               c.created_at AS created_at
        FROM c
        WHERE c.user_id = @user_id
        AND c.notification_type = @notification_type
        AND (NOT IS_DEFINED(c.read_by) OR NOT ARRAY_CONTAINS(c.read_by, @user_id))
    """
    notifications = list(cosmos_notifications_container.query_items(
        query=query,
        parameters=[
            {'name': '@user_id', 'value': user_id},
            {'name': '@notification_type', 'value': 'collaboration_message_received'},
        ],
        partition_key=user_id,
    ))

    unread_by_conversation = {}
    for notification in notifications:
        conversation_id = str(notification.get('conversation_id') or '').strip()
        if not conversation_id:
            continue

        current_notification = unread_by_conversation.get(conversation_id)
        if (
            current_notification is None
            or str(notification.get('created_at') or '') > str(current_notification.get('created_at') or '')
        ):
            unread_by_conversation[conversation_id] = notification

    return unread_by_conversation


def _load_collaboration_conversations_for_feed(user_id):
    conversations = _load_accessible_collaboration_search_conversations(user_id)
    try:
        unread_by_conversation = _load_unread_collaboration_notification_map(user_id)
    except Exception as exc:
        log_event(
            f'[ConversationFeed] Failed to load collaboration unread state: {exc}',
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        unread_by_conversation = {}
    feed_conversations = []

    for conversation in conversations:
        feed_conversation = tag_conversation_feed_source(
            conversation,
            CONVERSATION_FEED_SOURCE_COLLABORATION,
        )
        unread_notification = unread_by_conversation.get(str(feed_conversation.get('id') or ''))
        if unread_notification:
            feed_conversation['has_unread_assistant_response'] = True
            feed_conversation['last_unread_assistant_message_id'] = unread_notification.get('message_id')
            feed_conversation['last_unread_assistant_at'] = unread_notification.get('created_at')
        feed_conversations.append(feed_conversation)

    return feed_conversations


def _filter_collaboration_conversations_for_feed(conversations, include_hidden=False, search_term=''):
    filtered_conversations = []
    for conversation in conversations or []:
        if not include_hidden and conversation.get('is_hidden', False):
            continue
        if not _conversation_feed_matches_search(conversation, search_term):
            continue
        filtered_conversations.append(conversation)
    return filtered_conversations


def _filter_legacy_source_duplicates(conversations, collaboration_source_ids):
    if not collaboration_source_ids:
        return list(conversations or [])

    return [
        conversation for conversation in conversations or []
        if str(conversation.get('id') or '').strip() not in collaboration_source_ids
    ]


def _build_conversation_feed(user_id, page_size, source_offsets, include_priority, include_hidden, search_term):
    recent_fetch_limit = page_size + 1
    hidden_count = _count_hidden_legacy_conversations(user_id)

    try:
        collaboration_conversations = _load_collaboration_conversations_for_feed(user_id)
    except Exception as exc:
        log_event(
            f'[ConversationFeed] Failed to load collaborative conversations: {exc}',
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        collaboration_conversations = []

    hidden_count += sum(1 for conversation in collaboration_conversations if conversation.get('is_hidden', False))
    collaboration_source_ids = {
        str(conversation.get('source_conversation_id') or '').strip()
        for conversation in collaboration_conversations
        if conversation.get('source_conversation_id')
    }

    filtered_collaboration_conversations = _filter_collaboration_conversations_for_feed(
        collaboration_conversations,
        include_hidden=include_hidden,
        search_term=search_term,
    )
    collaboration_priority_conversations = [
        conversation for conversation in filtered_collaboration_conversations
        if _is_conversation_priority(conversation)
    ]
    collaboration_recent_conversations = [
        conversation for conversation in filtered_collaboration_conversations
        if not _is_conversation_priority(conversation)
    ]
    collaboration_recent_conversations = sort_conversation_feed_recent(collaboration_recent_conversations)
    collaboration_offset = source_offsets.get(CONVERSATION_FEED_SOURCE_COLLABORATION, 0)
    collaboration_recent_window = collaboration_recent_conversations[
        collaboration_offset:collaboration_offset + recent_fetch_limit
    ]

    priority_conversations = list(collaboration_priority_conversations) if include_priority else []
    if include_priority:
        legacy_pinned_conversations = _query_legacy_conversations_for_feed(
            user_id,
            include_hidden=include_hidden,
            search_term=search_term,
            extra_conditions=['c.is_pinned = true'],
        )
        legacy_unread_conversations = _query_legacy_conversations_for_feed(
            user_id,
            include_hidden=include_hidden,
            search_term=search_term,
            extra_conditions=[
                'c.has_unread_assistant_response = true',
                '(NOT IS_DEFINED(c.is_pinned) OR c.is_pinned = false)',
            ],
        )
        priority_conversations.extend(_filter_legacy_source_duplicates(
            legacy_pinned_conversations + legacy_unread_conversations,
            collaboration_source_ids,
        ))

    legacy_recent_conversations = _query_legacy_conversations_for_feed(
        user_id,
        include_hidden=include_hidden,
        search_term=search_term,
        extra_conditions=[
            '(NOT IS_DEFINED(c.is_pinned) OR c.is_pinned = false)',
            '(NOT IS_DEFINED(c.has_unread_assistant_response) OR c.has_unread_assistant_response = false)',
        ],
        offset=source_offsets.get(CONVERSATION_FEED_SOURCE_LEGACY, 0),
        limit=recent_fetch_limit,
    )
    legacy_recent_conversations = _filter_legacy_source_duplicates(
        legacy_recent_conversations,
        collaboration_source_ids,
    )

    return build_conversation_feed_page(
        priority_conversations=priority_conversations,
        recent_conversations_by_source={
            CONVERSATION_FEED_SOURCE_LEGACY: legacy_recent_conversations,
            CONVERSATION_FEED_SOURCE_COLLABORATION: collaboration_recent_window,
        },
        page_size=page_size,
        source_offsets=source_offsets,
        include_priority=include_priority,
        hidden_count=hidden_count,
        search_term=search_term,
        include_hidden=include_hidden,
    )


def _collect_child_message_documents(conversation_id, root_message_ids):
    """Collect child records linked by parent_message_id for the provided message ids."""
    pending_ids = [message_id for message_id in root_message_ids if message_id]
    seen_ids = set(pending_ids)
    child_docs = []

    while pending_ids:
        parent_message_id = pending_ids.pop(0)
        child_query = (
            "SELECT * FROM c "
            "WHERE c.conversation_id = @conversation_id "
            "AND c.parent_message_id = @parent_message_id"
        )
        child_results = list(cosmos_messages_container.query_items(
            query=child_query,
            parameters=[
                {'name': '@conversation_id', 'value': conversation_id},
                {'name': '@parent_message_id', 'value': parent_message_id},
            ],
            partition_key=conversation_id,
        ))

        for child_doc in child_results:
            child_id = child_doc.get('id')
            if not child_id or child_id in seen_ids:
                continue

            seen_ids.add(child_id)
            child_docs.append(child_doc)
            pending_ids.append(child_id)

    return child_docs


def _authorize_personal_conversation_read(user_id, conversation_id):
    """Load a personal conversation and ensure the caller owns it."""
    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError(f"Conversation {conversation_id} not found") from exc

    if conversation_item.get('user_id') != user_id:
        raise PermissionError('Forbidden')

    return conversation_item


def _authorize_image_conversation_read(user_id, conversation_id):
    """Authorize image reads for either personal or collaborative conversations."""
    try:
        return _authorize_personal_conversation_read(user_id, conversation_id), 'personal'
    except PermissionError:
        raise
    except LookupError:
        pass

    try:
        conversation_item = get_collaboration_conversation(conversation_id)
    except CosmosResourceNotFoundError as exc:
        raise LookupError(f"Conversation {conversation_id} not found") from exc

    assert_user_can_view_collaboration_conversation(user_id, conversation_item, allow_pending=True)
    return conversation_item, 'collaboration'


def _stream_blob_backed_image_message(message_doc):
    """Stream a blob-backed image message through the authenticated image endpoint."""
    blob_container = str(message_doc.get('blob_container') or '').strip()
    blob_path = str(message_doc.get('blob_path') or '').strip()
    mime_type = str(message_doc.get('mime_type') or '').strip() or 'image/png'
    if not blob_container or not blob_path:
        raise LookupError('Image not found')

    blob_service_client = CLIENTS.get("storage_account_office_docs_client")
    if not blob_service_client:
        raise RuntimeError('Blob storage client not available')

    blob_client = blob_service_client.get_blob_client(
        container=blob_container,
        blob=blob_path,
    )

    content_length = None
    try:
        blob_properties = blob_client.get_blob_properties()
        content_length = getattr(blob_properties, 'size', None)
    except Exception:
        content_length = None

    def stream_blob_chunks():
        blob_stream = blob_client.download_blob()
        for blob_chunk in blob_stream.chunks():
            yield blob_chunk

    headers = {
        'Cache-Control': 'private, max-age=300',
    }
    if content_length is not None:
        headers['Content-Length'] = str(content_length)

    return Response(
        stream_with_context(stream_blob_chunks()),
        mimetype=mime_type,
        headers=headers,
    )


def _load_scope_lock_conversation(conversation_id, user_id):
    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
        if conversation_item.get('user_id') != user_id:
            raise PermissionError('Forbidden')
        return conversation_item, 'personal'
    except CosmosResourceNotFoundError:
        pass

    try:
        conversation_item = get_collaboration_conversation(conversation_id)
    except CosmosResourceNotFoundError as exc:
        raise LookupError('Conversation not found') from exc

    assert_user_can_participate_in_collaboration_conversation(user_id, conversation_item)
    return conversation_item, 'collaboration'


def _persist_scope_lock_update(conversation_item, conversation_kind, user_id, new_value):
    timestamp = datetime.utcnow().isoformat()
    conversation_item['scope_locked'] = new_value

    if conversation_kind == 'collaboration':
        conversation_item['updated_at'] = timestamp
        cosmos_collaboration_conversations_container.upsert_item(conversation_item)
        current_user = get_current_user_info() or {'userId': user_id}
        _, conversation_item = ensure_collaboration_source_conversation(conversation_item, current_user)
        return conversation_item

    conversation_item['last_updated'] = timestamp
    cosmos_conversations_container.upsert_item(conversation_item)
    return conversation_item


def register_route_backend_conversations(app):

    @app.route('/api/get_messages', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_messages():
        conversation_id = request.args.get('conversation_id')
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        if not conversation_id:
            return jsonify({'error': 'No conversation_id provided'}), 400
        try:
            _authorize_personal_conversation_read(user_id, conversation_id)
            # Query all messages in cosmos_messages_container
            # We'll filter for active_thread in Python since Cosmos DB boolean queries can be tricky
            message_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                ORDER BY c.timestamp ASC
            """
            
            debug_print(f"Executing query: {message_query}")
            
            all_items = list(cosmos_messages_container.query_items(
                query=message_query,
                partition_key=conversation_id
            ))
            artifact_payload_map = build_message_artifact_payload_map(all_items)
            all_items = filter_assistant_artifact_items(all_items)
            
            debug_print(f"Query returned {len(all_items)} total items (before filtering)")
            
            # Filter for active_thread = True OR active_thread is not defined (backwards compatibility)
            filtered_items = []
            for item in all_items:
                metadata = item.get('metadata', {}) or {}
                if metadata.get('is_generated_chat_artifact', False):
                    debug_print(f"  🫥 Excluding hidden generated artifact: id={item.get('id')}")
                    continue

                thread_info = metadata.get('thread_info', {})
                active = thread_info.get('active_thread')
                debug_print(f"Evaluating item id={item.get('id')}, role={item.get('role')}, active_thread={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
                
                # Include if: active_thread is True, OR active_thread is not defined, OR active_thread is None
                if active is True or active is None or 'active_thread' not in thread_info:
                    filtered_items.append(item)
                    debug_print(f"  ✅ Including: id={item.get('id')}, role={item.get('role')}, active={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
                else:
                    debug_print(f"  ❌ Excluding: id={item.get('id')}, role={item.get('role')}, active={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
            
            all_items = filtered_items
            debug_print(f"After filtering: {len(all_items)} items remaining")

            all_items = hydrate_agent_citations_from_artifacts(all_items, artifact_payload_map)

            messages = hydrate_image_messages(
                all_items,
                image_url_builder=lambda image_id: f"/api/image/{image_id}",
            )

            return jsonify({'messages': messages})
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        except LookupError:
            return jsonify({'messages': []})
        except Exception as e:
            print(f"ERROR: Failed to get messages: {str(e)}")
            return jsonify({'error': 'Conversation not found'}), 404

    @app.route('/api/image/<image_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_image(image_id):
        """Serve chat images from blob storage or legacy chunked message content."""
        
        user_id = get_current_user_id()
        if not user_id:
            print(f"🔥 Authentication failed for image request")
            return jsonify({'error': 'User not authenticated'}), 401
            
        try:
            # Extract conversation_id from image_id (format: conversation_id_image_timestamp_random)
            parts = image_id.split('_')
            if len(parts) < 4:
                return jsonify({'error': 'Invalid image ID format'}), 400
            
            # Reconstruct conversation_id (everything except the last 3 parts)
            conversation_id = '_'.join(parts[:-3])
            
            debug_print(f"Serving image {image_id} from conversation {conversation_id}")

            _authorize_image_conversation_read(user_id, conversation_id)
            image_message, complete_content = get_complete_image_content(
                cosmos_messages_container,
                conversation_id,
                image_id,
            )

            if is_blob_backed_image_message(image_message):
                return _stream_blob_backed_image_message(image_message)

            if is_external_image_url(complete_content):
                return redirect(complete_content)

            mime_type, image_data = decode_image_content(complete_content)
            return Response(
                image_data,
                mimetype=mime_type,
                headers={
                    'Content-Length': len(image_data),
                    'Cache-Control': 'public, max-age=3600'
                }
            )

        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Image not found'}), 404
        except LookupError:
            return jsonify({'error': 'Image not found'}), 404
        except Exception as e:
            print(f"ERROR: Failed to serve image {image_id}: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to retrieve image'}), 500
        
    @app.route('/api/get_conversations', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversations():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        query = f"SELECT * FROM c WHERE c.user_id = '{user_id}' ORDER BY c.last_updated DESC"
        items = list(cosmos_conversations_container.query_items(query=query, enable_cross_partition_query=True))
        normalized_items = [normalize_conversation_unread_state(item) for item in items]
        return jsonify({
            'conversations': normalized_items
        }), 200


    @app.route('/api/conversations/feed', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversations_feed():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            search_term = str(request.args.get('search') or '').strip()
            include_hidden = str(request.args.get('include_hidden', 'false')).strip().lower() in ('1', 'true', 'yes')
            page_size = normalize_conversation_feed_page_size(request.args.get('page_size'))
            cursor_data = decode_conversation_feed_cursor(request.args.get('cursor'))
            cursor_is_compatible = is_conversation_feed_cursor_compatible(
                cursor_data,
                search_term=search_term,
                include_hidden=include_hidden,
            )
            source_offsets = get_conversation_feed_source_offsets(cursor_data) if cursor_is_compatible else {}
            include_priority = not cursor_is_compatible

            feed_payload = _build_conversation_feed(
                user_id=user_id,
                page_size=page_size,
                source_offsets=source_offsets,
                include_priority=include_priority,
                include_hidden=include_hidden,
                search_term=search_term,
            )
            feed_payload['search_term'] = search_term
            feed_payload['include_hidden'] = include_hidden
            return jsonify(feed_payload), 200
        except Exception as exc:
            log_event(
                f'[ConversationFeed] Failed to load feed: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to load conversations'}), 500


    @app.route('/api/create_conversation', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def create_conversation():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        initial_title = derive_conversation_title_from_message(
            data.get('initial_message') or data.get('message') or data.get('title') or ''
        )
        conversation_item = create_personal_conversation_for_current_user(title=initial_title)

        return jsonify({
            'conversation_id': conversation_item.get('id'),
            'title': conversation_item.get('title', 'New Conversation')
        }), 200
    
    @app.route('/api/conversations/<conversation_id>', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def update_conversation_title(conversation_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        # Parse the new title from the request body
        data = request.get_json()
        new_title = data.get('title', '').strip()
        if not new_title:
            return jsonify({'error': 'Title is required'}), 400

        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )

            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403

            # Update the title
            conversation_item['title'] = new_title

            # Optionally update the last_updated time
            from datetime import datetime
            conversation_item['last_updated'] = datetime.utcnow().isoformat()

            # Write back to Cosmos DB
            cosmos_conversations_container.upsert_item(conversation_item)

            return jsonify({
                'message': 'Conversation updated', 
                'title': new_title,
                'classification': conversation_item.get('classification', []),
                'context': conversation_item.get('context', []),
                'chat_type': conversation_item.get('chat_type')
            }), 200
        except Exception as e:
            print(e)
            return jsonify({'error': 'Failed to update conversation'}), 500
        
    @app.route('/api/conversations/<conversation_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_conversation(conversation_id):
        """
        Delete a conversation. If archiving is enabled, copy it to archived_conversations first.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        settings = get_settings()
        archiving_enabled = settings.get('enable_conversation_archiving', False)

        try:
            request_payload = request.get_json(silent=True) or {}
            delete_workspace_document_ids = _get_requested_workspace_document_delete_ids_for_conversation(
                request_payload,
                conversation_id,
            )
        except ValueError as validation_error:
            return jsonify({'error': str(validation_error)}), 400

        try:
            conversation_item = _authorize_personal_conversation_read(user_id, conversation_id)
        except LookupError:
            return jsonify({
                "error": f"Conversation {conversation_id} not found."
            }), 404
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        except Exception as e:
            return jsonify({
                "error": str(e)
            }), 500

        if archiving_enabled:
            archived_item = dict(conversation_item)
            archived_item["archived_at"] = datetime.utcnow().isoformat()
            cosmos_archived_conversations_container.upsert_item(archived_item)
            
            # Log conversation archival
            log_conversation_archival(
                user_id=conversation_item.get('user_id'),
                conversation_id=conversation_id,
                title=conversation_item.get('title', 'Untitled'),
                workspace_type='personal',
                context=conversation_item.get('context', []),
                tags=conversation_item.get('tags', [])
            )

        message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}'"
        results = list(cosmos_messages_container.query_items(
            query=message_query,
            partition_key=conversation_id
        ))

        if delete_workspace_document_ids:
            try:
                workspace_delete_result = delete_chat_upload_workspace_documents_for_conversation(
                    conversation_item.get('user_id'),
                    conversation_id,
                    selected_document_ids=delete_workspace_document_ids,
                )
                if workspace_delete_result.get('deleted_document_ids'):
                    invalidate_personal_search_cache(conversation_item.get('user_id'))
                if workspace_delete_result.get('failed_documents'):
                    log_event(
                        f"[ConversationDelete] Failed to delete some selected linked workspace documents for {conversation_id}",
                        workspace_delete_result,
                        level=logging.WARNING,
                    )
            except Exception as workspace_delete_error:
                log_event(
                    f"[ConversationDelete] Failed to delete selected linked workspace documents for {conversation_id}: {workspace_delete_error}",
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )
                return jsonify({
                    'error': 'Failed to delete selected workspace documents'
                }), 500

        if not archiving_enabled:
            delete_blob_backed_chat_message_files(results)

        for doc in results:
            if archiving_enabled:
                archived_doc = dict(doc)
                archived_doc["archived_at"] = datetime.utcnow().isoformat()
                cosmos_archived_messages_container.upsert_item(archived_doc)

            cosmos_messages_container.delete_item(doc['id'], partition_key=conversation_id)

        # Archive/delete thoughts for conversation
        user_id_for_thoughts = conversation_item.get('user_id')
        if archiving_enabled:
            archive_thoughts_for_conversation(conversation_id, user_id_for_thoughts)
        else:
            delete_thoughts_for_conversation(conversation_id, user_id_for_thoughts)

        # Log conversation deletion before actual deletion
        log_conversation_deletion(
            user_id=conversation_item.get('user_id'),
            conversation_id=conversation_id,
            title=conversation_item.get('title', 'Untitled'),
            workspace_type='personal',
            context=conversation_item.get('context', []),
            tags=conversation_item.get('tags', []),
            is_archived=archiving_enabled,
            is_bulk_operation=False
        )
        
        try:
            cosmos_conversations_container.delete_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            # TODO: Delete any facts that were stored with this conversation.
        except Exception as e:
            return jsonify({
                "error": str(e)
            }), 500

        return jsonify({
            "success": True
        }), 200
        
    @app.route('/api/delete_multiple_conversations', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_multiple_conversations():
        """
        Delete multiple conversations at once. If archiving is enabled, copy them to archived_conversations first.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
            
        data = request.get_json()
        conversation_ids = data.get('conversation_ids', [])
        
        if not conversation_ids:
            return jsonify({'error': 'No conversation IDs provided'}), 400
            
        settings = get_settings()
        archiving_enabled = settings.get('enable_conversation_archiving', False)
        
        success_count = 0
        failed_ids = []
        
        for conversation_id in conversation_ids:
            try:
                # Verify the conversation exists and belongs to the user
                try:
                    conversation_item = _authorize_personal_conversation_read(user_id, conversation_id)
                except (LookupError, PermissionError):
                    failed_ids.append(conversation_id)
                    continue
                
                # Archive if enabled
                if archiving_enabled:
                    archived_item = dict(conversation_item)
                    archived_item["archived_at"] = datetime.utcnow().isoformat()
                    cosmos_archived_conversations_container.upsert_item(archived_item)
                    
                    # Log conversation archival
                    log_conversation_archival(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        title=conversation_item.get('title', 'Untitled'),
                        workspace_type='personal',
                        context=conversation_item.get('context', []),
                        tags=conversation_item.get('tags', [])
                    )
                
                # Get and archive messages if enabled
                message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}'"
                messages = list(cosmos_messages_container.query_items(
                    query=message_query,
                    partition_key=conversation_id
                ))

                if not archiving_enabled:
                    delete_blob_backed_chat_message_files(messages)
                
                for message in messages:
                    if archiving_enabled:
                        archived_message = dict(message)
                        archived_message["archived_at"] = datetime.utcnow().isoformat()
                        cosmos_archived_messages_container.upsert_item(archived_message)
                    
                    cosmos_messages_container.delete_item(message['id'], partition_key=conversation_id)

                # Archive/delete thoughts for conversation
                if archiving_enabled:
                    archive_thoughts_for_conversation(conversation_id, user_id)
                else:
                    delete_thoughts_for_conversation(conversation_id, user_id)

                # Log conversation deletion before actual deletion
                log_conversation_deletion(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    title=conversation_item.get('title', 'Untitled'),
                    workspace_type='personal',
                    context=conversation_item.get('context', []),
                    tags=conversation_item.get('tags', []),
                    is_archived=archiving_enabled,
                    is_bulk_operation=True
                )
                
                # Delete the conversation
                cosmos_conversations_container.delete_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
                
                success_count += 1
                
            except Exception as e:
                print(f"Error deleting conversation {conversation_id}: {str(e)}")
                failed_ids.append(conversation_id)
        
        return jsonify({
            "success": True,
            "deleted_count": success_count,
            "failed_ids": failed_ids
        }), 200

    @app.route('/api/conversations/<conversation_id>/pin', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def toggle_conversation_pin(conversation_id):
        """
        Toggle the pinned status of a conversation.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            
            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403
            
            # Toggle the pinned status
            current_pinned = conversation_item.get('is_pinned', False)
            conversation_item['is_pinned'] = not current_pinned
            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            
            # Update in Cosmos DB
            cosmos_conversations_container.upsert_item(conversation_item)
            
            return jsonify({
                'success': True,
                'is_pinned': conversation_item['is_pinned']
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error toggling conversation pin: {e}")
            return jsonify({'error': 'Failed to toggle pin status'}), 500
    
    @app.route('/api/conversations/<conversation_id>/hide', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def toggle_conversation_hide(conversation_id):
        """
        Toggle the hidden status of a conversation.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            
            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403
            
            # Toggle the hidden status
            current_hidden = conversation_item.get('is_hidden', False)
            conversation_item['is_hidden'] = not current_hidden
            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            
            # Update in Cosmos DB
            cosmos_conversations_container.upsert_item(conversation_item)
            
            return jsonify({
                'success': True,
                'is_hidden': conversation_item['is_hidden']
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error toggling conversation hide: {e}")
            return jsonify({'error': 'Failed to toggle hide status'}), 500

    @app.route('/api/conversations/bulk-pin', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def bulk_pin_conversations():
        """
        Pin or unpin multiple conversations at once.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        data = request.get_json()
        conversation_ids = data.get('conversation_ids', [])
        pin_action = data.get('action', 'pin')  # 'pin' or 'unpin'
        
        if not conversation_ids:
            return jsonify({'error': 'No conversation IDs provided'}), 400
        
        if pin_action not in ['pin', 'unpin']:
            return jsonify({'error': 'Invalid action. Must be "pin" or "unpin"'}), 400
        
        success_count = 0
        failed_ids = []
        
        for conversation_id in conversation_ids:
            try:
                conversation_item = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
                
                # Check if the conversation belongs to the current user
                if conversation_item.get('user_id') != user_id:
                    failed_ids.append(conversation_id)
                    continue
                
                # Set pin status
                conversation_item['is_pinned'] = (pin_action == 'pin')
                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                
                # Update in Cosmos DB
                cosmos_conversations_container.upsert_item(conversation_item)
                success_count += 1
                
            except CosmosResourceNotFoundError:
                failed_ids.append(conversation_id)
            except Exception as e:
                print(f"Error updating conversation {conversation_id}: {str(e)}")
                failed_ids.append(conversation_id)
        
        return jsonify({
            "success": True,
            "updated_count": success_count,
            "failed_ids": failed_ids,
            "action": pin_action
        }), 200

    @app.route('/api/conversations/bulk-hide', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def bulk_hide_conversations():
        """
        Hide or unhide multiple conversations at once.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        data = request.get_json()
        conversation_ids = data.get('conversation_ids', [])
        hide_action = data.get('action', 'hide')  # 'hide' or 'unhide'
        
        if not conversation_ids:
            return jsonify({'error': 'No conversation IDs provided'}), 400
        
        if hide_action not in ['hide', 'unhide']:
            return jsonify({'error': 'Invalid action. Must be "hide" or "unhide"'}), 400
        
        success_count = 0
        failed_ids = []
        
        for conversation_id in conversation_ids:
            try:
                conversation_item = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
                
                # Check if the conversation belongs to the current user
                if conversation_item.get('user_id') != user_id:
                    failed_ids.append(conversation_id)
                    continue
                
                # Set hide status
                conversation_item['is_hidden'] = (hide_action == 'hide')
                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                
                # Update in Cosmos DB
                cosmos_conversations_container.upsert_item(conversation_item)
                success_count += 1
                
            except CosmosResourceNotFoundError:
                failed_ids.append(conversation_id)
            except Exception as e:
                print(f"Error updating conversation {conversation_id}: {str(e)}")
                failed_ids.append(conversation_id)
        
        return jsonify({
            "success": True,
            "updated_count": success_count,
            "failed_ids": failed_ids,
            "action": hide_action
        }), 200

    @app.route('/api/conversations/<conversation_id>/metadata', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversation_metadata_api(conversation_id):
        """
        Get detailed metadata for a conversation including context, tags, and other information.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            conversation_item = normalize_conversation_unread_state(conversation_item)
            
            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403
            
            _, updated = normalize_chat_type(conversation_item)
            if updated:
                cosmos_conversations_container.upsert_item(conversation_item)

            linked_workspace_documents = []
            try:
                linked_workspace_documents = serialize_chat_upload_workspace_documents_for_conversation(
                    user_id,
                    conversation_id,
                )
            except Exception as linked_documents_error:
                log_event(
                    f"[ConversationMetadata] Failed to list linked workspace documents for {conversation_id}: {linked_documents_error}",
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )

            # Return the full conversation metadata
            return jsonify({
                "conversation_id": conversation_id,
                "title": conversation_item.get('title', ''),
                "user_id": conversation_item.get('user_id', ''),
                "last_updated": conversation_item.get('last_updated', ''),
                "classification": conversation_item.get('classification', []),
                "context": conversation_item.get('context', []),
                "tags": conversation_item.get('tags', []),
                "strict": conversation_item.get('strict', False),
                "is_pinned": conversation_item.get('is_pinned', False),
                "is_hidden": conversation_item.get('is_hidden', False),
                "has_unread_assistant_response": conversation_item.get('has_unread_assistant_response', False),
                "last_unread_assistant_message_id": conversation_item.get('last_unread_assistant_message_id'),
                "last_unread_assistant_at": conversation_item.get('last_unread_assistant_at'),
                "scope_locked": conversation_item.get('scope_locked'),
                "locked_contexts": conversation_item.get('locked_contexts', []),
                "chat_type": conversation_item.get('chat_type'),
                "workflow_id": conversation_item.get('workflow_id'),
                "summary": conversation_item.get('summary'),
                "linked_workspace_documents": linked_workspace_documents,
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error retrieving conversation metadata: {e}")
            return jsonify({'error': 'Failed to retrieve conversation metadata'}), 500

    @app.route('/api/conversations/<conversation_id>/mark-read', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def mark_conversation_read_api(conversation_id):
        """Clear unread assistant-response state and related chat notifications."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            conversation_item = normalize_conversation_unread_state(conversation_item)

            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403

            conversation_item = clear_conversation_unread(conversation_item)
            cosmos_conversations_container.upsert_item(conversation_item)

            notifications_marked_read = mark_chat_response_notifications_read_for_conversation(
                user_id,
                conversation_id
            )

            return jsonify({
                'success': True,
                'conversation_id': conversation_id,
                'has_unread_assistant_response': False,
                'notifications_marked_read': notifications_marked_read,
            }), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            debug_print(f"Error marking conversation {conversation_id} as read: {e}")
            return jsonify({'error': 'Failed to mark conversation as read'}), 500

    @app.route('/api/conversations/<conversation_id>/summary', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def generate_conversation_summary_api(conversation_id):
        """
        Generate (or regenerate) a summary for a conversation and persist it.

        Request body (optional):
            { "model_deployment": "gpt-4o" }

        Returns the generated summary dict on success.
        """
        from route_backend_conversation_export import generate_conversation_summary, _normalize_content
        from functions_chat import sort_messages_by_thread

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        conversation_item = None
        is_collaboration_summary = False

        try:
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403
        except CosmosResourceNotFoundError:
            try:
                conversation_item = get_collaboration_conversation(conversation_id)
                assert_user_can_view_collaboration_conversation(
                    user_id,
                    conversation_item,
                    allow_pending=True,
                )
                is_collaboration_summary = True
            except CosmosResourceNotFoundError:
                return jsonify({'error': 'Conversation not found'}), 404
            except PermissionError as exc:
                return jsonify({'error': str(exc)}), 403
            except Exception as e:
                debug_print(f"Error reading collaborative conversation for summary: {e}")
                return jsonify({'error': 'Failed to read conversation'}), 500
        except Exception as e:
            debug_print(f"Error reading conversation for summary: {e}")
            return jsonify({'error': 'Failed to read conversation'}), 500

        body = request.get_json(silent=True) or {}
        model_deployment = body.get('model_deployment', '')
        model_endpoint_id = body.get('model_endpoint_id', '')
        model_id = body.get('model_id', '')
        model_provider = body.get('model_provider', '')

        # Query messages for this conversation
        try:
            if is_collaboration_summary:
                raw_messages = list_collaboration_messages(conversation_id)
            else:
                query = "SELECT * FROM c WHERE c.conversation_id = @cid ORDER BY c.timestamp ASC"
                params = [{"name": "@cid", "value": conversation_id}]
                raw_messages = list(cosmos_messages_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True
                ))
            raw_messages = filter_assistant_artifact_items(raw_messages)
        except Exception as e:
            debug_print(f"Error querying messages for summary: {e}")
            return jsonify({'error': 'Failed to query messages'}), 500

        if not raw_messages:
            return jsonify({'error': 'No messages in this conversation'}), 400

        # Build lightweight export-style message list for the summary helper
        ordered_messages = sort_messages_by_thread(raw_messages)
        export_messages = []
        for msg in ordered_messages:
            role = msg.get('role', 'unknown')
            # Content may be a string OR a list of content parts — normalise it
            content = _normalize_content(msg.get('content', ''))
            speaker = 'USER' if role == 'user' else 'ASSISTANT' if role == 'assistant' else role.upper()
            export_messages.append({
                'role': role,
                'content_text': content,
                'speaker_label': speaker
            })

        message_time_start = ordered_messages[0].get('timestamp') if ordered_messages else None
        message_time_end = ordered_messages[-1].get('timestamp') if ordered_messages else None

        settings = get_settings()

        try:
            summary_data = generate_conversation_summary(
                messages=export_messages,
                conversation_title=conversation_item.get('title', 'Untitled'),
                settings=settings,
                model_deployment=model_deployment,
                message_time_start=message_time_start,
                message_time_end=message_time_end,
                conversation_id=conversation_id,
                user_id=user_id,
                model_endpoint_id=model_endpoint_id,
                model_id=model_id,
                model_provider=model_provider,
            )
            return jsonify({'success': True, 'summary': summary_data}), 200

        except (ValueError, RuntimeError) as known_exc:
            return jsonify({'error': str(known_exc)}), 400
        except Exception as exc:
            debug_print(f"Summary generation API error: {exc}")
            return jsonify({'error': 'Summary generation failed'}), 500

    @app.route('/api/conversations/<conversation_id>/scope_lock', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def patch_conversation_scope_lock(conversation_id):
        """
        Toggle the scope lock on a conversation.
        Unlock is reversible — locked_contexts are preserved for re-locking.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json()
        if data is None or 'scope_locked' not in data:
            return jsonify({'error': 'Missing scope_locked field'}), 400

        new_value = data['scope_locked']
        if new_value is not True and new_value is not False:
            return jsonify({'error': 'scope_locked must be true or false'}), 400

        # Enforce scope lock if admin setting is enabled
        if new_value is False:
            settings = get_settings()
            if settings.get('enforce_workspace_scope_lock', True):
                return jsonify({'error': 'Scope unlock is disabled by administrator'}), 403

        try:
            conversation_item, conversation_kind = _load_scope_lock_conversation(conversation_id, user_id)
            conversation_item = _persist_scope_lock_update(
                conversation_item,
                conversation_kind,
                user_id,
                new_value,
            )

            return jsonify({
                "success": True,
                "scope_locked": new_value,
                "locked_contexts": conversation_item.get('locked_contexts', [])
            }), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc) or 'Forbidden'}), 403
        except (CosmosResourceNotFoundError, LookupError):
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            debug_print(f"Error updating scope lock: {e}")
            return jsonify({'error': 'Failed to update scope lock'}), 500

    @app.route('/api/conversations/classifications', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_user_classifications():
        """
        Get all unique classifications from user's conversations
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Query all conversations for this user
            query = f"SELECT c.classification FROM c WHERE c.user_id = '{user_id}'"
            items = list(cosmos_conversations_container.query_items(
                query=query,
                enable_cross_partition_query=True
            ))
            
            # Extract and flatten all classifications
            classifications_set = set()
            for item in items:
                classifications = item.get('classification', [])
                if isinstance(classifications, list):
                    for classification in classifications:
                        if classification and isinstance(classification, str):
                            classifications_set.add(classification.strip())
            
            # Sort alphabetically
            classifications_list = sorted(list(classifications_set))
            
            return jsonify({
                'success': True,
                'classifications': classifications_list
            }), 200
            
        except Exception as e:
            print(f"Error fetching classifications: {e}")
            return jsonify({'error': 'Failed to fetch classifications'}), 500
    
    @app.route('/api/search_conversations', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def search_conversations():
        """
        Search conversations and messages with filters and pagination
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json(silent=True) or {}
            search_term = data.get('search_term', '').strip()
            match_mode = _normalize_search_match_mode(data.get('match_mode'))
            date_from = data.get('date_from', '')
            date_to = data.get('date_to', '')
            chat_types = data.get('chat_types', [])
            classifications = data.get('classifications', [])
            has_files = data.get('has_files', False)
            has_images = data.get('has_images', False)
            page = int(data.get('page', 1))
            per_page = int(data.get('per_page', 20))
            
            # Validate search term
            if not search_term or len(search_term) < 3:
                return jsonify({
                    'success': False,
                    'error': 'Search term must be at least 3 characters'
                }), 400
            
            selected_chat_types = _expand_search_chat_type_filters(chat_types)

            # Build conversation query with filters. Find conversations where user is a participant
            # and keep a Python-side pass for collaboration records that live in separate containers.
            query_parts = [
                "(c.user_id = @user_id OR EXISTS(SELECT VALUE t FROM t IN c.tags WHERE t.category = 'participant' AND t.user_id = @user_id))"
            ]
            query_parameters = [
                {'name': '@user_id', 'value': user_id},
            ]
            
            debug_print("🔍 Search parameters:")
            debug_print(f"  user_id: {user_id}")
            debug_print(f"  search_term: {search_term}")
            debug_print(f"  match_mode: {match_mode}")
            debug_print(f"  date_from: {date_from}")
            debug_print(f"  date_to: {date_to}")
            debug_print(f"  chat_types: {chat_types}")
            debug_print(f"  classifications: {classifications}")
            
            if date_from:
                query_parts.append("c.last_updated >= @date_from")
                query_parameters.append({'name': '@date_from', 'value': date_from})
            if date_to:
                query_parts.append("c.last_updated <= @date_to")
                query_parameters.append({'name': '@date_to', 'value': f'{date_to}T23:59:59'})
            
            conversation_query = f"SELECT * FROM c WHERE {' AND '.join(query_parts)}"
            debug_print(f"\n📋 Conversation query: {conversation_query}")
            
            conversations = list(cosmos_conversations_container.query_items(
                query=conversation_query,
                parameters=query_parameters,
                enable_cross_partition_query=True,
                max_item_count=-1  # Get all items, no pagination limit
            ))

            collaboration_conversations = _load_accessible_collaboration_search_conversations(user_id)
            collaboration_conversations = [
                conversation for conversation in collaboration_conversations
                if _conversation_matches_date_range(conversation, date_from, date_to)
            ]
            conversations.extend(collaboration_conversations)

            debug_print(f"Found {len(conversations)} conversations from legacy and collaboration stores")
            
            # Filter by chat types if specified
            if selected_chat_types:
                before_count = len(conversations)
                filtered_out = []
                filtered_in = []
                
                for conversation in conversations:
                    if _conversation_matches_selected_chat_types(conversation, selected_chat_types):
                        filtered_in.append(conversation)
                    else:
                        filtered_out.append(conversation)
                
                conversations = filtered_in
                debug_print(f"After chat_type filter: {len(conversations)} (removed {before_count - len(conversations)})")
                
                # Show some examples of filtered out chat types
                if filtered_out:
                    unique_types = set(_get_search_conversation_chat_type(c) for c in filtered_out[:10])
                    debug_print(f"   Filtered out chat_types (sample): {unique_types}")
            
            # Filter by classifications if specified
            if classifications:
                before_count = len(conversations)
                conversations = [
                    conversation for conversation in conversations
                    if _conversation_matches_classifications(conversation, classifications)
                ]
                debug_print(f"After classification filter: {len(conversations)} (removed {before_count - len(conversations)})")
            
            debug_print(f"🔍 Starting search for term: '{search_term}'")
            debug_print(f"Found {len(conversations)} conversations to search")
            
            # Create a set of conversation IDs for fast lookup
            conversation_ids = {conversation['id'] for conversation in conversations if conversation.get('id')}
            conversation_map = {
                conversation['id']: conversation
                for conversation in conversations
                if conversation.get('id')
            }
            
            # Do cross-partition message searches in both legacy and collaboration stores,
            # then filter to the user's authorized conversation set.
            message_query, _ = _build_message_search_query(search_term, match_mode)
            debug_print(f"\n📋 Cross-partition message query: {message_query}")

            all_matching_messages = _query_matching_messages(
                cosmos_messages_container,
                search_term,
                match_mode,
            )
            all_matching_messages.extend(_query_matching_messages(
                cosmos_collaboration_messages_container,
                search_term,
                match_mode,
            ))
            
            debug_print(f"Found {len(all_matching_messages)} total messages across all conversations")
            
            # Group messages by conversation and filter
            messages_by_conversation = {}
            for msg in all_matching_messages:
                conv_id = msg.get('conversation_id')
                
                # Only include messages from conversations we have access to
                if conv_id not in conversation_ids:
                    continue
                
                # Include all messages where active_thread is not explicitly False
                if _message_is_in_active_thread(msg):
                    messages_by_conversation.setdefault(conv_id, []).append(msg)
            
            debug_print(f"After filtering: {len(messages_by_conversation)} conversations have matching messages")
            
            results = []

            # Build results for conversations with matching titles or messages.
            for conv_id, conversation in conversation_map.items():
                matching_messages = messages_by_conversation.get(conv_id, [])
                title_match = _matches_search_text(conversation.get('title', ''), search_term, match_mode)
                
                # Apply file/image filters if specified
                if has_files or has_images:
                    matching_messages = [
                        message for message in matching_messages
                        if _message_matches_attachment_filters(message, has_files, has_images)
                    ]
                
                include_title_only_match = title_match and not (has_files or has_images)
                if not matching_messages and not include_title_only_match:
                    continue

                results.append({
                    'conversation': _build_search_conversation_payload(conversation),
                    'messages': _build_message_snippets(matching_messages, search_term, match_mode),
                    'match_count': len(matching_messages),
                    'title_match': title_match,
                    'match_mode': match_mode,
                })
            
            # Sort by last_updated (most recent first)
            results.sort(key=lambda x: x['conversation']['last_updated'], reverse=True)
            
            # Pagination
            total_results = len(results)
            total_pages = math.ceil(total_results / per_page) if total_results > 0 else 1
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_results = results[start_idx:end_idx]
            
            return jsonify({
                'success': True,
                'total_results': total_results,
                'page': page,
                'total_pages': total_pages,
                'per_page': per_page,
                'results': paginated_results
            }), 200
            
        except Exception as e:
            log_event(
                f'[ConversationSearch] Failed to search conversations: {e}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to search conversations'}), 500
    
    @app.route('/api/user-settings/search-history', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_search_history():
        """Get user's search history"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            history = get_user_search_history(user_id)
            return jsonify({
                'success': True,
                'history': history
            }), 200
        except Exception as e:
            print(f"Error retrieving search history: {e}")
            return jsonify({'error': 'Failed to retrieve search history'}), 500
    
    @app.route('/api/user-settings/search-history', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def save_search_to_history():
        """Save a search term to user's history"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json()
            search_term = data.get('search_term', '').strip()
            
            if not search_term:
                return jsonify({'error': 'Search term is required'}), 400
            
            history = add_search_to_history(user_id, search_term)
            return jsonify({
                'success': True,
                'history': history
            }), 200
        except Exception as e:
            print(f"Error saving search to history: {e}")
            return jsonify({'error': 'Failed to save search to history'}), 500
    
    @app.route('/api/user-settings/search-history', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def clear_search_history():
        """Clear user's search history"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            success = clear_user_search_history(user_id)
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Search history cleared'
                }), 200
            else:
                return jsonify({'error': 'Failed to clear search history'}), 500
        except Exception as e:
            print(f"Error clearing search history: {e}")
            return jsonify({'error': 'Failed to clear search history'}), 500
    
    @app.route('/api/message/<message_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_message(message_id):
        """
        Delete a message or entire thread. Only the message author can delete their messages.
        If archiving is enabled, messages are marked with is_deleted=true and masked.
        If archiving is disabled, messages are permanently deleted.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            delete_thread = data.get('delete_thread', False)
            
            settings = get_settings()
            archiving_enabled = settings.get('enable_conversation_archiving', False)
            
            # Find the message using cross-partition query
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            message_doc = message_results[0]
            conversation_id = message_doc.get('conversation_id')
            
            # Verify ownership - only the message author can delete their message
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
                        return jsonify({'error': 'You can only delete messages from your own conversations'}), 403
                except Exception as ex:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only delete your own messages'}), 403
            
            # Collect messages to delete
            messages_to_delete = []
            
            if delete_thread and message_doc.get('role') == 'user':
                # Delete entire thread: user message + system message + assistant/image messages
                thread_id = message_doc.get('metadata', {}).get('thread_info', {}).get('thread_id')
                thread_previous_id = message_doc.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
                
                if thread_id:
                    # Query all messages in this thread exchange (user, system, assistant messages with same thread_id)
                    # Do NOT include subsequent threads that reference this thread_id as previous_thread_id
                    thread_query = f"""
                        SELECT * FROM c 
                        WHERE c.conversation_id = '{conversation_id}' 
                        AND c.metadata.thread_info.thread_id = '{thread_id}'
                    """
                    thread_messages = list(cosmos_messages_container.query_items(
                        query=thread_query,
                        partition_key=conversation_id
                    ))
                    messages_to_delete = thread_messages
                    
                    # THREAD CHAIN REPAIR: Update subsequent threads to maintain chain integrity
                    # Find messages where previous_thread_id points to the thread we're deleting
                    subsequent_query = f"""
                        SELECT * FROM c 
                        WHERE c.conversation_id = '{conversation_id}' 
                        AND c.metadata.thread_info.previous_thread_id = '{thread_id}'
                    """
                    subsequent_messages = list(cosmos_messages_container.query_items(
                        query=subsequent_query,
                        partition_key=conversation_id
                    ))
                    
                    # Update each subsequent message to skip over the deleted thread
                    # Point their previous_thread_id to the deleted thread's previous_thread_id
                    for subsequent_msg in subsequent_messages:
                        # Skip messages that are being deleted (they're in the same thread)
                        if subsequent_msg['id'] in [m['id'] for m in messages_to_delete]:
                            continue
                        
                        # Update previous_thread_id to maintain chain
                        if 'metadata' not in subsequent_msg:
                            subsequent_msg['metadata'] = {}
                        if 'thread_info' not in subsequent_msg['metadata']:
                            subsequent_msg['metadata']['thread_info'] = {}
                        
                        subsequent_msg['metadata']['thread_info']['previous_thread_id'] = thread_previous_id
                        
                        # Upsert the updated message
                        cosmos_messages_container.upsert_item(subsequent_msg)
                        print(f"Repaired thread chain: Message {subsequent_msg['id']} now points to thread {thread_previous_id}")
                else:
                    messages_to_delete = [message_doc]
            else:
                # Delete only the specified message
                messages_to_delete = [message_doc]

            child_message_docs = _collect_child_message_documents(
                conversation_id,
                [message.get('id') for message in messages_to_delete],
            )
            if child_message_docs:
                messages_to_delete.extend(child_message_docs)
            
            # THREAD ATTEMPT PROMOTION: If deleting an active thread attempt, promote next attempt
            if messages_to_delete:
                first_msg = messages_to_delete[0]
                thread_id = first_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
                is_active = first_msg.get('metadata', {}).get('thread_info', {}).get('active_thread', True)
                
                if thread_id and is_active:
                    # Find all other attempts for this thread_id
                    other_attempts_query = f"""
                        SELECT * FROM c 
                        WHERE c.conversation_id = '{conversation_id}' 
                        AND c.metadata.thread_info.thread_id = '{thread_id}'
                        AND c.id NOT IN ({','.join([f"'{m['id']}'" for m in messages_to_delete])})
                        AND c.role = 'user'
                    """
                    other_attempts = list(cosmos_messages_container.query_items(
                        query=other_attempts_query,
                        partition_key=conversation_id
                    ))
                    
                    # If there are other attempts, promote the next one (lowest thread_attempt)
                    if other_attempts:
                        # Sort by thread_attempt to find the next one
                        other_attempts.sort(key=lambda m: m.get('metadata', {}).get('thread_info', {}).get('thread_attempt', 0))
                        next_attempt_number = other_attempts[0].get('metadata', {}).get('thread_info', {}).get('thread_attempt', 0)
                        
                        # Activate all messages with this thread_attempt
                        activate_query = f"""
                            SELECT * FROM c 
                            WHERE c.conversation_id = '{conversation_id}' 
                            AND c.metadata.thread_info.thread_id = '{thread_id}'
                            AND c.metadata.thread_info.thread_attempt = {next_attempt_number}
                        """
                        messages_to_activate = list(cosmos_messages_container.query_items(
                            query=activate_query,
                            partition_key=conversation_id
                        ))
                        
                        for msg_to_activate in messages_to_activate:
                            if 'metadata' not in msg_to_activate:
                                msg_to_activate['metadata'] = {}
                            if 'thread_info' not in msg_to_activate['metadata']:
                                msg_to_activate['metadata']['thread_info'] = {}
                            msg_to_activate['metadata']['thread_info']['active_thread'] = True
                            cosmos_messages_container.upsert_item(msg_to_activate)
                        
                        print(f"Promoted thread_attempt {next_attempt_number} to active after deleting active thread {thread_id}")
            
            deleted_message_ids = []
            
            for msg in messages_to_delete:
                msg_id = msg['id']
                
                if archiving_enabled:
                    # Mark as deleted and mask the message
                    if 'metadata' not in msg:
                        msg['metadata'] = {}
                    
                    msg['metadata']['is_deleted'] = True
                    msg['metadata']['deleted_by_user_id'] = user_id
                    msg['metadata']['deleted_timestamp'] = datetime.utcnow().isoformat()
                    msg['metadata']['masked'] = True
                    msg['metadata']['masked_by_user_id'] = user_id
                    msg['metadata']['masked_timestamp'] = datetime.utcnow().isoformat()
                    
                    # Archive the message
                    archived_msg = dict(msg)
                    archived_msg['archived_at'] = datetime.utcnow().isoformat()
                    cosmos_archived_messages_container.upsert_item(archived_msg)
                    
                    # Update the message in the main container (for conversation history exclusion)
                    cosmos_messages_container.upsert_item(msg)
                else:
                    # Permanently delete the message
                    cosmos_messages_container.delete_item(msg_id, partition_key=conversation_id)
                
                deleted_message_ids.append(msg_id)
            
            return jsonify({
                'success': True,
                'deleted_message_ids': deleted_message_ids,
                'archived': archiving_enabled
            }), 200
            
        except Exception as e:
            print(f"Error deleting message: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to delete message'}), 500
    @app.route('/api/message/<message_id>/retry', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def retry_message(message_id):
        """
        Retry/regenerate a message by creating new user+system+assistant messages 
        with incremented thread_attempt and same thread_id.
        Only the message author can retry their messages.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            selected_model = data.get('model')
            reasoning_effort = data.get('reasoning_effort')
            agent_info = data.get('agent_info')  # Get agent info if provided
            
            # Find the original message
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            original_msg = message_results[0]
            conversation_id = original_msg.get('conversation_id')
            original_role = original_msg.get('role')
            
            # Verify ownership
            message_user_id = original_msg.get('metadata', {}).get('user_info', {}).get('user_id')
            if not message_user_id:
                # Fallback to conversation ownership
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'You can only retry messages from your own conversations'}), 403
                except Exception as ex:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only retry your own messages'}), 403
            
            # Get thread info from original message
            thread_id = original_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
            previous_thread_id = original_msg.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
            
            if not thread_id:
                return jsonify({'error': 'Message has no thread_id'}), 400
            
            # Find current max thread_attempt for this thread_id
            attempt_query = f"""
                SELECT VALUE MAX(c.metadata.thread_info.thread_attempt) 
                FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            attempt_results = list(cosmos_messages_container.query_items(
                query=attempt_query,
                partition_key=conversation_id
            ))
            
            current_max_attempt = attempt_results[0] if attempt_results and attempt_results[0] is not None else 0
            new_attempt = current_max_attempt + 1
            
            # Set all existing attempts for this thread to active_thread=false
            deactivate_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            existing_messages = list(cosmos_messages_container.query_items(
                query=deactivate_query,
                partition_key=conversation_id
            ))
            
            print(f"🔍 Retry - Found {len(existing_messages)} existing messages to deactivate")
            
            for msg in existing_messages:
                msg_id = msg.get('id', 'unknown')
                msg_role = msg.get('role', 'unknown')
                old_active = msg.get('metadata', {}).get('thread_info', {}).get('active_thread', None)
                
                if 'metadata' not in msg:
                    msg['metadata'] = {}
                if 'thread_info' not in msg['metadata']:
                    msg['metadata']['thread_info'] = {}
                msg['metadata']['thread_info']['active_thread'] = False
                cosmos_messages_container.upsert_item(msg)
                
                print(f"  ✏️ Deactivated: {msg_id} (role={msg_role}, was_active={old_active}, now_active=False)")
            
            # Find the original user message in this thread to get the content
            # Get the FIRST user message in this thread (attempt=1) to ensure we get the original content
            user_msg_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
                AND c.role = 'user'
                ORDER BY c.metadata.thread_info.thread_attempt ASC
            """
            user_msg_results = list(cosmos_messages_container.query_items(
                query=user_msg_query,
                partition_key=conversation_id
            ))
            
            if not user_msg_results:
                return jsonify({'error': 'User message not found in thread'}), 404
            
            # Get the first user message (attempt 1) to get original content and metadata
            original_user_msg = user_msg_results[0]
            user_content = original_user_msg.get('content', '')
            original_metadata = original_user_msg.get('metadata', {})
            original_thread_info = original_metadata.get('thread_info', {})
            
            print(f"🔍 Retry - Original user message: {original_user_msg.get('id')}")
            print(f"🔍 Retry - Original thread_id: {original_thread_info.get('thread_id')}")
            print(f"🔍 Retry - Original previous_thread_id: {original_thread_info.get('previous_thread_id')}")
            print(f"🔍 Retry - Original attempt: {original_thread_info.get('thread_attempt')}")
            print(f"🔍 Retry - New attempt will be: {new_attempt}")
            
            # Create new user message with same content but new attempt number
            import uuid
            import time
            import random
            
            new_user_message_id = f"{conversation_id}_user_{int(time.time())}_{random.randint(1000,9999)}"
            
            # Copy metadata but update thread_attempt and keep same thread_id and previous_thread_id from original
            new_metadata = dict(original_metadata)
            new_metadata['retried'] = True  # Mark as retried
            new_metadata['thread_info'] = {
                'thread_id': thread_id,  # Keep same thread_id
                'previous_thread_id': original_thread_info.get('previous_thread_id'),  # Preserve original previous_thread_id
                'active_thread': True,
                'thread_attempt': new_attempt
            }
            
            print(f"🔍 Retry - New user message ID: {new_user_message_id}")
            print(f"🔍 Retry - New thread_info: {new_metadata['thread_info']}")
            
            # Create new user message
            new_user_message = {
                'id': new_user_message_id,
                'conversation_id': conversation_id,
                'role': 'user',
                'content': user_content,
                'timestamp': datetime.utcnow().isoformat(),
                'model_deployment_name': None,
                'metadata': new_metadata
            }
            cosmos_messages_container.upsert_item(new_user_message)
            
            # Build chat request parameters from original message metadata
            chat_request = {
                'message': user_content,
                'conversation_id': conversation_id,
                'model_deployment': selected_model or original_metadata.get('model_selection', {}).get('selected_model'),
                'reasoning_effort': reasoning_effort or original_metadata.get('reasoning_effort'),
                'hybrid_search': original_metadata.get('document_search', {}).get('enabled', False),
                'selected_document_id': original_metadata.get('document_search', {}).get('document_id'),
                'doc_scope': original_metadata.get('document_search', {}).get('scope'),
                'top_n': original_metadata.get('document_search', {}).get('top_n'),
                'classifications': original_metadata.get('document_search', {}).get('classifications'),
                'image_generation': original_metadata.get('image_generation', {}).get('enabled', False),
                'active_group_id': original_metadata.get('chat_context', {}).get('group_id'),
                'active_public_workspace_id': original_metadata.get('chat_context', {}).get('public_workspace_id'),
                'chat_type': original_metadata.get('chat_context', {}).get('type', 'user'),
                'retry_user_message_id': new_user_message_id,  # Pass this to skip user message creation
                'retry_thread_id': thread_id,  # Pass thread_id to maintain same thread
                'retry_thread_attempt': new_attempt  # Pass attempt number
            }
            
            # Add agent_info to chat request if provided (for agent-based retry)
            if agent_info:
                chat_request['agent_info'] = agent_info
                print(f"🤖 Retry - Using agent: {agent_info.get('display_name')} ({agent_info.get('name')})")
            elif original_metadata.get('agent_selection'):
                # Use original agent selection if no new agent specified
                chat_request['agent_info'] = original_metadata.get('agent_selection')
                print(f"🤖 Retry - Using original agent from metadata")
            
            print(f"🔍 Retry - Chat request params: retry_user_message_id={new_user_message_id}, retry_thread_id={thread_id}, retry_thread_attempt={new_attempt}")
            
            # Make internal request to chat API
            from flask import g
            g.conversation_id = conversation_id
            
            # Import and call chat function directly
            # We'll need to modify the chat_api to handle retry requests
            return jsonify({
                'success': True,
                'message': 'Retry initiated',
                'thread_id': thread_id,
                'new_attempt': new_attempt,
                'user_message_id': new_user_message_id,
                'chat_request': chat_request
            }), 200
            
        except Exception as e:
            print(f"Error retrying message: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to retry message'}), 500

    @app.route('/api/message/<message_id>/edit', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def edit_message(message_id):
        """
        Edit a user message and regenerate the response with the edited content.
        Creates a new attempt with edited content while preserving original model/settings.
        Only the message author can edit their messages.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            edited_content = data.get('content', '').strip()
            
            if not edited_content:
                return jsonify({'error': 'Message content cannot be empty'}), 400
            
            # Find the original message
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            original_msg = message_results[0]
            conversation_id = original_msg.get('conversation_id')
            original_role = original_msg.get('role')
            
            # Only allow editing user messages
            if original_role != 'user':
                return jsonify({'error': 'Only user messages can be edited'}), 400
            
            # Verify ownership
            message_user_id = original_msg.get('metadata', {}).get('user_info', {}).get('user_id')
            if not message_user_id:
                # Fallback to conversation ownership
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'You can only edit messages from your own conversations'}), 403
                except Exception as ex:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only edit your own messages'}), 403
            
            # Get thread info from original message
            thread_id = original_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
            previous_thread_id = original_msg.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
            
            if not thread_id:
                return jsonify({'error': 'Message has no thread_id'}), 400
            
            # Find current max thread_attempt for this thread_id
            attempt_query = f"""
                SELECT VALUE MAX(c.metadata.thread_info.thread_attempt) 
                FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            attempt_results = list(cosmos_messages_container.query_items(
                query=attempt_query,
                partition_key=conversation_id
            ))
            
            current_max_attempt = attempt_results[0] if attempt_results and attempt_results[0] is not None else 0
            new_attempt = current_max_attempt + 1
            
            # Set all existing attempts for this thread to active_thread=false
            deactivate_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            existing_messages = list(cosmos_messages_container.query_items(
                query=deactivate_query,
                partition_key=conversation_id
            ))
            
            print(f"🔍 Edit - Found {len(existing_messages)} existing messages to deactivate")
            
            for msg in existing_messages:
                msg_id = msg.get('id', 'unknown')
                msg_role = msg.get('role', 'unknown')
                old_active = msg.get('metadata', {}).get('thread_info', {}).get('active_thread', None)
                
                if 'metadata' not in msg:
                    msg['metadata'] = {}
                if 'thread_info' not in msg['metadata']:
                    msg['metadata']['thread_info'] = {}
                msg['metadata']['thread_info']['active_thread'] = False
                cosmos_messages_container.upsert_item(msg)
                
                print(f"  ✏️ Deactivated: {msg_id} (role={msg_role}, was_active={old_active}, now_active=False)")
            
            # Get the FIRST user message in this thread (attempt=1) to get original metadata
            user_msg_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
                AND c.role = 'user'
                ORDER BY c.metadata.thread_info.thread_attempt ASC
            """
            user_msg_results = list(cosmos_messages_container.query_items(
                query=user_msg_query,
                partition_key=conversation_id
            ))
            
            if not user_msg_results:
                return jsonify({'error': 'User message not found in thread'}), 404
            
            # Get the first user message (attempt 1) to get original metadata
            original_user_msg = user_msg_results[0]
            original_metadata = original_user_msg.get('metadata', {})
            original_thread_info = original_metadata.get('thread_info', {})
            
            print(f"🔍 Edit - Original user message: {original_user_msg.get('id')}")
            print(f"🔍 Edit - Original thread_id: {original_thread_info.get('thread_id')}")
            print(f"🔍 Edit - Original previous_thread_id: {original_thread_info.get('previous_thread_id')}")
            print(f"🔍 Edit - Original attempt: {original_thread_info.get('thread_attempt')}")
            print(f"🔍 Edit - New attempt will be: {new_attempt}")
            
            # Create new user message with edited content
            import time
            import random
            
            new_user_message_id = f"{conversation_id}_user_{int(time.time())}_{random.randint(1000,9999)}"
            
            # Copy metadata but update thread_attempt, add edited flag, and keep same thread_id
            new_metadata = dict(original_metadata)
            new_metadata['edited'] = True  # Mark as edited
            new_metadata['thread_info'] = {
                'thread_id': thread_id,  # Keep same thread_id
                'previous_thread_id': original_thread_info.get('previous_thread_id'),  # Preserve original
                'active_thread': True,
                'thread_attempt': new_attempt
            }
            
            print(f"🔍 Edit - New user message ID: {new_user_message_id}")
            print(f"🔍 Edit - New thread_info: {new_metadata['thread_info']}")
            print(f"🔍 Edit - Edited flag set: {new_metadata.get('edited')}")
            
            # Create new user message with edited content
            new_user_message = {
                'id': new_user_message_id,
                'conversation_id': conversation_id,
                'role': 'user',
                'content': edited_content,  # Use edited content
                'timestamp': datetime.utcnow().isoformat(),
                'model_deployment_name': None,
                'metadata': new_metadata
            }
            cosmos_messages_container.upsert_item(new_user_message)
            
            # Build chat request parameters from original message metadata
            # Keep all original settings (model, reasoning, doc search, etc.)
            chat_request = {
                'message': edited_content,  # Use edited content
                'conversation_id': conversation_id,
                'model_deployment': original_metadata.get('model_selection', {}).get('selected_model'),
                'reasoning_effort': original_metadata.get('reasoning_effort'),
                'hybrid_search': original_metadata.get('document_search', {}).get('enabled', False),
                'selected_document_id': original_metadata.get('document_search', {}).get('document_id'),
                'doc_scope': original_metadata.get('document_search', {}).get('scope'),
                'top_n': original_metadata.get('document_search', {}).get('top_n'),
                'classifications': original_metadata.get('document_search', {}).get('classifications'),
                'image_generation': original_metadata.get('image_generation', {}).get('enabled', False),
                'active_group_id': original_metadata.get('chat_context', {}).get('group_id'),
                'active_public_workspace_id': original_metadata.get('chat_context', {}).get('public_workspace_id'),
                'chat_type': original_metadata.get('chat_context', {}).get('type', 'user'),
                'edited_user_message_id': new_user_message_id,  # Pass this to skip user message creation
                'retry_thread_id': thread_id,  # Pass thread_id to maintain same thread
                'retry_thread_attempt': new_attempt  # Pass attempt number
            }
            
            # Include agent_info from original metadata if present (for agent-based edits)
            if original_metadata.get('agent_selection'):
                agent_selection = original_metadata.get('agent_selection')
                chat_request['agent_info'] = {
                    'name': agent_selection.get('selected_agent'),
                    'display_name': agent_selection.get('agent_display_name'),
                    'id': agent_selection.get('agent_id'),
                    'is_global': agent_selection.get('is_global', False),
                    'is_group': agent_selection.get('is_group', False),
                    'group_id': agent_selection.get('group_id'),
                    'group_name': agent_selection.get('group_name')
                }
                print(f"🤖 Edit - Using agent: {chat_request['agent_info'].get('display_name')} ({chat_request['agent_info'].get('name')})")
            
            print(f"🔍 Edit - Chat request params: edited_user_message_id={new_user_message_id}, retry_thread_id={thread_id}, retry_thread_attempt={new_attempt}")
            
            # Return success with chat_request for frontend to call chat API
            return jsonify({
                'success': True,
                'message': 'Edit initiated',
                'thread_id': thread_id,
                'new_attempt': new_attempt,
                'user_message_id': new_user_message_id,
                'edited': True,
                'chat_request': chat_request
            }), 200
            
        except Exception as e:
            print(f"Error editing message: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to edit message'}), 500

    @app.route('/api/message/<message_id>/switch-attempt', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def switch_attempt(message_id):
        """
        Switch between thread attempts by setting active_thread flags.
        Cycles through attempts based on direction (prev/next).
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            direction = data.get('direction', 'next')  # 'prev' or 'next'
            
            # Find the current message
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            current_msg = message_results[0]
            conversation_id = current_msg.get('conversation_id')
            
            # Verify ownership
            message_user_id = current_msg.get('metadata', {}).get('user_info', {}).get('user_id')
            if not message_user_id:
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'You can only switch attempts in your own conversations'}), 403
                except Exception as ex:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only switch attempts in your own conversations'}), 403
            
            # Get thread info
            thread_id = current_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
            current_attempt = current_msg.get('metadata', {}).get('thread_info', {}).get('thread_attempt', 0)
            
            if not thread_id:
                return jsonify({'error': 'Message has no thread_id'}), 400
            
            # Get all attempts for this thread_id, ordered by thread_attempt
            attempts_query = f"""
                SELECT DISTINCT c.metadata.thread_info.thread_attempt 
                FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
                AND c.role = 'user'
                ORDER BY c.metadata.thread_info.thread_attempt ASC
            """
            attempts_results = list(cosmos_messages_container.query_items(
                query=attempts_query,
                partition_key=conversation_id
            ))
            
            available_attempts = sorted([r.get('thread_attempt', 0) for r in attempts_results])
            
            if not available_attempts:
                return jsonify({'error': 'No attempts found'}), 404
            
            # Find current index and determine target attempt
            try:
                current_index = available_attempts.index(current_attempt)
            except ValueError:
                current_index = 0
            
            if direction == 'prev':
                target_index = (current_index - 1) % len(available_attempts)
            else:  # 'next'
                target_index = (current_index + 1) % len(available_attempts)
            
            target_attempt = available_attempts[target_index]
            
            # Deactivate all attempts for this thread
            deactivate_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            all_thread_messages = list(cosmos_messages_container.query_items(
                query=deactivate_query,
                partition_key=conversation_id
            ))
            
            # Update active_thread flags
            for msg in all_thread_messages:
                if 'metadata' not in msg:
                    msg['metadata'] = {}
                if 'thread_info' not in msg['metadata']:
                    msg['metadata']['thread_info'] = {}
                
                msg_attempt = msg['metadata']['thread_info'].get('thread_attempt', 0)
                msg['metadata']['thread_info']['active_thread'] = (msg_attempt == target_attempt)
                cosmos_messages_container.upsert_item(msg)
            
            return jsonify({
                'success': True,
                'target_attempt': target_attempt,
                'available_attempts': available_attempts
            }), 200
            
        except Exception as e:
            print(f"Error switching attempt: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to switch attempt'}), 500
