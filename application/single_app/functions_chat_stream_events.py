# functions_chat_stream_events.py

import json
from typing import Any, Dict


USER_MESSAGE_PERSISTED_EVENT_TYPE = "user_message_persisted"


def build_user_message_persisted_stream_payload(
    conversation_id: str,
    user_message_id: str,
) -> Dict[str, Any]:
    """Build the SSE payload that acknowledges durable user-message storage."""
    normalized_conversation_id = str(conversation_id or "").strip()
    normalized_user_message_id = str(user_message_id or "").strip()
    if not normalized_conversation_id or not normalized_user_message_id:
        raise ValueError("conversation_id and user_message_id are required")

    return {
        "type": USER_MESSAGE_PERSISTED_EVENT_TYPE,
        "conversation_id": normalized_conversation_id,
        "user_message_id": normalized_user_message_id,
        "message_persisted": True,
    }


def build_user_message_persisted_stream_event(
    conversation_id: str,
    user_message_id: str,
) -> str:
    """Serialize a user-message persistence acknowledgement as an SSE event."""
    payload = build_user_message_persisted_stream_payload(
        conversation_id,
        user_message_id,
    )
    return f"data: {json.dumps(payload)}\n\n"
