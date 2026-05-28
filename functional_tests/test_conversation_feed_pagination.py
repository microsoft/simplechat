# test_conversation_feed_pagination.py
#!/usr/bin/env python3
"""
Functional test for paged conversation feed merging.
Version: 0.241.112
Implemented in: 0.241.112

This test ensures pinned and unread conversations are included on the first
conversation feed page while normal conversations page by source cursor.
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from functions_conversation_feed import (  # noqa: E402
    CONVERSATION_FEED_SOURCE_COLLABORATION,
    CONVERSATION_FEED_SOURCE_LEGACY,
    build_conversation_feed_page,
    decode_conversation_feed_cursor,
    get_conversation_feed_source_offsets,
)


def _conversation(conversation_id, timestamp, source, pinned=False, unread=False):
    return {
        'id': conversation_id,
        'title': conversation_id.replace('-', ' ').title(),
        'last_updated': timestamp,
        'is_pinned': pinned,
        'has_unread_assistant_response': unread,
        '_feed_source': source,
    }


def test_first_page_includes_priority_and_tracks_recent_offsets():
    """Validate priority inclusion and per-source recent cursor accounting."""
    priority_conversations = [
        _conversation('legacy-pinned', '2026-05-28T10:00:00', CONVERSATION_FEED_SOURCE_LEGACY, pinned=True),
        _conversation('collab-unread', '2026-05-28T09:59:00', CONVERSATION_FEED_SOURCE_COLLABORATION, unread=True),
    ]
    recent_by_source = {
        CONVERSATION_FEED_SOURCE_LEGACY: [
            _conversation('legacy-recent-1', '2026-05-28T09:58:00', CONVERSATION_FEED_SOURCE_LEGACY),
            _conversation('legacy-recent-2', '2026-05-28T09:55:00', CONVERSATION_FEED_SOURCE_LEGACY),
        ],
        CONVERSATION_FEED_SOURCE_COLLABORATION: [
            _conversation('collab-recent-1', '2026-05-28T09:57:00', CONVERSATION_FEED_SOURCE_COLLABORATION),
            _conversation('collab-recent-2', '2026-05-28T09:56:00', CONVERSATION_FEED_SOURCE_COLLABORATION),
        ],
    }

    payload = build_conversation_feed_page(
        priority_conversations=priority_conversations,
        recent_conversations_by_source=recent_by_source,
        page_size=2,
        source_offsets={
            CONVERSATION_FEED_SOURCE_LEGACY: 0,
            CONVERSATION_FEED_SOURCE_COLLABORATION: 0,
        },
        include_priority=True,
        hidden_count=3,
    )

    conversation_ids = [conversation['id'] for conversation in payload['conversations']]
    assert conversation_ids == [
        'legacy-pinned',
        'collab-unread',
        'legacy-recent-1',
        'collab-recent-1',
    ]
    assert payload['priority_count'] == 2
    assert payload['recent_count'] == 2
    assert payload['hidden_count'] == 3
    assert payload['has_more'] is True

    cursor_data = decode_conversation_feed_cursor(payload['next_cursor'])
    source_offsets = get_conversation_feed_source_offsets(cursor_data)
    assert source_offsets[CONVERSATION_FEED_SOURCE_LEGACY] == 1
    assert source_offsets[CONVERSATION_FEED_SOURCE_COLLABORATION] == 1


def test_subsequent_page_omits_priority_conversations():
    """Validate that load-more pages contain only recent conversations."""
    payload = build_conversation_feed_page(
        priority_conversations=[
            _conversation('legacy-pinned', '2026-05-28T10:00:00', CONVERSATION_FEED_SOURCE_LEGACY, pinned=True),
        ],
        recent_conversations_by_source={
            CONVERSATION_FEED_SOURCE_LEGACY: [
                _conversation('legacy-recent-2', '2026-05-28T09:55:00', CONVERSATION_FEED_SOURCE_LEGACY),
            ],
            CONVERSATION_FEED_SOURCE_COLLABORATION: [
                _conversation('collab-recent-2', '2026-05-28T09:56:00', CONVERSATION_FEED_SOURCE_COLLABORATION),
            ],
        },
        page_size=2,
        source_offsets={
            CONVERSATION_FEED_SOURCE_LEGACY: 1,
            CONVERSATION_FEED_SOURCE_COLLABORATION: 1,
        },
        include_priority=False,
    )

    conversation_ids = [conversation['id'] for conversation in payload['conversations']]
    assert conversation_ids == ['collab-recent-2', 'legacy-recent-2']
    assert payload['priority_count'] == 0
    assert payload['recent_count'] == 2


if __name__ == '__main__':
    test_first_page_includes_priority_and_tracks_recent_offsets()
    test_subsequent_page_omits_priority_conversations()
    print('Conversation feed pagination tests passed.')