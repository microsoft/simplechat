# functions_conversation_unread.py

"""Helpers for conversation unread assistant-response state."""

from datetime import datetime


def normalize_conversation_unread_state(conversation_item):
    """Ensure unread assistant-response fields always exist on a conversation."""
    if not isinstance(conversation_item, dict):
        return conversation_item

    conversation_item['has_unread_assistant_response'] = bool(
        conversation_item.get('has_unread_assistant_response', False)
    )
    conversation_item['last_unread_assistant_message_id'] = conversation_item.get(
        'last_unread_assistant_message_id'
    )
    conversation_item['last_unread_assistant_at'] = conversation_item.get(
        'last_unread_assistant_at'
    )
    return conversation_item


def mark_conversation_unread(
    conversation_item,
    assistant_message_id,
    unread_timestamp=None,
):
    """Mark a conversation as having an unread assistant response."""
    normalized_item = normalize_conversation_unread_state(conversation_item)
    normalized_item['has_unread_assistant_response'] = True
    normalized_item['last_unread_assistant_message_id'] = assistant_message_id
    normalized_item['last_unread_assistant_at'] = unread_timestamp or datetime.utcnow().isoformat()
    return normalized_item


def clear_conversation_unread(conversation_item):
    """Clear unread assistant-response state from a conversation."""
    normalized_item = normalize_conversation_unread_state(conversation_item)
    normalized_item['has_unread_assistant_response'] = False
    normalized_item['last_unread_assistant_message_id'] = None
    normalized_item['last_unread_assistant_at'] = None
    return normalized_item
