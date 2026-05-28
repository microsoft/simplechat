# functions_conversation_feed.py

"""Helpers for building a paged conversation feed."""

import base64
import json


CONVERSATION_FEED_DEFAULT_PAGE_SIZE = 20
CONVERSATION_FEED_MAX_PAGE_SIZE = 50
CONVERSATION_FEED_SOURCE_LEGACY = 'legacy'
CONVERSATION_FEED_SOURCE_COLLABORATION = 'collaboration'


def normalize_conversation_feed_page_size(raw_page_size):
    """Normalize a caller-provided feed page size."""
    try:
        page_size = int(raw_page_size)
    except (TypeError, ValueError):
        page_size = CONVERSATION_FEED_DEFAULT_PAGE_SIZE

    if page_size < 1:
        return CONVERSATION_FEED_DEFAULT_PAGE_SIZE
    return min(page_size, CONVERSATION_FEED_MAX_PAGE_SIZE)


def encode_conversation_feed_cursor(cursor_data):
    """Encode cursor metadata as a URL-safe token."""
    if not isinstance(cursor_data, dict):
        return None

    encoded = base64.urlsafe_b64encode(
        json.dumps(cursor_data, separators=(',', ':')).encode('utf-8')
    ).decode('ascii')
    return encoded.rstrip('=')


def decode_conversation_feed_cursor(raw_cursor):
    """Decode a feed cursor token, returning an empty dict for invalid input."""
    normalized_cursor = str(raw_cursor or '').strip()
    if not normalized_cursor:
        return {}

    try:
        padding = '=' * (-len(normalized_cursor) % 4)
        decoded = base64.urlsafe_b64decode(f'{normalized_cursor}{padding}'.encode('ascii'))
        cursor_data = json.loads(decoded.decode('utf-8'))
    except (ValueError, TypeError, json.JSONDecodeError):
        return {}

    return cursor_data if isinstance(cursor_data, dict) else {}


def is_conversation_feed_cursor_compatible(cursor_data, search_term='', include_hidden=False):
    """Return True when a cursor belongs to the current feed filters."""
    if not isinstance(cursor_data, dict) or not cursor_data:
        return False

    return (
        str(cursor_data.get('search_term') or '') == str(search_term or '')
        and bool(cursor_data.get('include_hidden', False)) == bool(include_hidden)
    )


def get_conversation_feed_source_offsets(cursor_data):
    """Extract source offsets from a decoded cursor."""
    raw_offsets = cursor_data.get('source_offsets') if isinstance(cursor_data, dict) else {}
    if not isinstance(raw_offsets, dict):
        raw_offsets = {}

    source_offsets = {}
    for source_name in (CONVERSATION_FEED_SOURCE_LEGACY, CONVERSATION_FEED_SOURCE_COLLABORATION):
        try:
            source_offsets[source_name] = max(0, int(raw_offsets.get(source_name, 0)))
        except (TypeError, ValueError):
            source_offsets[source_name] = 0
    return source_offsets


def conversation_feed_timestamp(conversation_item):
    """Resolve the timestamp used for feed ordering."""
    return str(
        (conversation_item or {}).get('last_updated')
        or (conversation_item or {}).get('updated_at')
        or (conversation_item or {}).get('last_message_at')
        or (conversation_item or {}).get('created_at')
        or ''
    )


def tag_conversation_feed_source(conversation_item, source_name):
    """Copy a conversation item and attach its feed source for cursor accounting."""
    tagged_item = dict(conversation_item or {})
    tagged_item['_feed_source'] = source_name
    return tagged_item


def sort_conversation_feed_recent(conversations):
    """Sort conversations by feed timestamp descending."""
    return sorted(
        conversations or [],
        key=lambda item: (conversation_feed_timestamp(item), str((item or {}).get('id') or '')),
        reverse=True,
    )


def _sort_conversation_feed_priority(conversations):
    return sorted(
        conversations or [],
        key=lambda item: (
            bool((item or {}).get('is_pinned', False)),
            bool((item or {}).get('has_unread_assistant_response', False)),
            conversation_feed_timestamp(item),
            str((item or {}).get('id') or ''),
        ),
        reverse=True,
    )


def _strip_internal_feed_fields(conversation_item):
    public_item = dict(conversation_item or {})
    public_item.pop('_feed_source', None)
    return public_item


def _append_unique_conversation(target, conversation_item, seen_ids):
    conversation_id = str((conversation_item or {}).get('id') or '').strip()
    if not conversation_id or conversation_id in seen_ids:
        return False

    target.append(_strip_internal_feed_fields(conversation_item))
    seen_ids.add(conversation_id)
    return True


def build_conversation_feed_page(
    priority_conversations=None,
    recent_conversations_by_source=None,
    page_size=CONVERSATION_FEED_DEFAULT_PAGE_SIZE,
    source_offsets=None,
    include_priority=True,
    hidden_count=0,
    search_term='',
    include_hidden=False,
):
    """Build a feed payload from priority conversations and source-specific recent windows."""
    normalized_page_size = normalize_conversation_feed_page_size(page_size)
    normalized_offsets = {
        CONVERSATION_FEED_SOURCE_LEGACY: 0,
        CONVERSATION_FEED_SOURCE_COLLABORATION: 0,
    }
    normalized_offsets.update(source_offsets or {})

    response_conversations = []
    seen_ids = set()

    if include_priority:
        for conversation_item in _sort_conversation_feed_priority(priority_conversations or []):
            _append_unique_conversation(response_conversations, conversation_item, seen_ids)

    recent_candidates = []
    recent_conversations_by_source = recent_conversations_by_source or {}
    for source_name, source_conversations in recent_conversations_by_source.items():
        for conversation_item in source_conversations or []:
            if (conversation_item or {}).get('_feed_source'):
                recent_candidates.append(dict(conversation_item))
            else:
                recent_candidates.append(tag_conversation_feed_source(conversation_item, source_name))

    consumed_by_source = {
        CONVERSATION_FEED_SOURCE_LEGACY: 0,
        CONVERSATION_FEED_SOURCE_COLLABORATION: 0,
    }
    selected_recent_count = 0
    for conversation_item in sort_conversation_feed_recent(recent_candidates):
        if selected_recent_count >= normalized_page_size:
            break

        source_name = conversation_item.get('_feed_source') or CONVERSATION_FEED_SOURCE_LEGACY
        consumed_by_source[source_name] = consumed_by_source.get(source_name, 0) + 1
        if _append_unique_conversation(response_conversations, conversation_item, seen_ids):
            selected_recent_count += 1

    next_offsets = {
        source_name: max(0, int(normalized_offsets.get(source_name, 0))) + consumed_by_source.get(source_name, 0)
        for source_name in normalized_offsets
    }

    has_more = False
    for source_name, source_conversations in recent_conversations_by_source.items():
        source_count = len(source_conversations or [])
        consumed_count = consumed_by_source.get(source_name, 0)
        if source_count > consumed_count or source_count > normalized_page_size:
            has_more = True
            break

    next_cursor = None
    if has_more:
        next_cursor = encode_conversation_feed_cursor({
            'source_offsets': next_offsets,
            'search_term': str(search_term or ''),
            'include_hidden': bool(include_hidden),
        })

    return {
        'success': True,
        'conversations': response_conversations,
        'has_more': has_more,
        'next_cursor': next_cursor,
        'page_size': normalized_page_size,
        'hidden_count': max(0, int(hidden_count or 0)),
        'priority_count': len(response_conversations) - selected_recent_count if include_priority else 0,
        'recent_count': selected_recent_count,
        'source_offsets': next_offsets,
    }