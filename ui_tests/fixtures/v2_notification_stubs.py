# v2_notification_stubs.py
"""
The notification requests every real V2 page makes, answered the way the real routes answer.
Version: 0.261.194
Implemented in: 0.261.194

The V2 rail's bell reads the unread count as soon as the signed-in session loads, and again
whenever the tab comes back into view. A chat reply the reader watched finish is marked read,
because the server marks a personal conversation unread as it finishes a reply. Closed-API
fixtures that serve the built SPA answer both with these helpers, as a user with nothing
unread would see them, so a suite about something else is not failed by the bell.
"""

import re


NOTIFICATION_COUNT_PATH = "/api/notifications/count"
CONVERSATION_MARK_READ_PATH = re.compile(r"/api/conversations/([^/]+)/mark-read")


def notification_count_payload(count=0):
    """The answer of route_backend_notifications.api_get_notification_count."""
    return {
        "success": True,
        "count": count,
        "chat_completion_audio_enabled": False,
        "chat_completion_audio_updated_at": None,
    }


def conversation_mark_read_payload(conversation_id):
    """The answer of route_backend_conversations.mark_conversation_read_api."""
    return {
        "success": True,
        "conversation_id": conversation_id,
        "has_unread_assistant_response": False,
        "notifications_marked_read": 0,
        "conversation_state_changed": True,
    }


def is_notification_count(method, path):
    return method == "GET" and path == NOTIFICATION_COUNT_PATH


def mark_read_conversation(method, path):
    """The conversation a personal mark-read request names, or None for any other request."""
    if method != "POST":
        return None
    match = CONVERSATION_MARK_READ_PATH.fullmatch(path)
    return match.group(1) if match else None
