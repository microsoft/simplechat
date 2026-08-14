# test_message_metadata_loading_fix.py
#!/usr/bin/env python3
"""
Functional test for live user-message metadata reconciliation.
Version: 0.250.201
Implemented in: 0.250.201

This test ensures streaming routes acknowledge persisted user messages before
assistant completion and the browser replaces temporary IDs without a refresh.
"""

import json
import sys
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from functions_chat_stream_events import (  # noqa: E402
    USER_MESSAGE_PERSISTED_EVENT_TYPE,
    build_user_message_persisted_stream_event,
    build_user_message_persisted_stream_payload,
)


CHAT_ROUTE = APP_ROOT / "route_backend_chats.py"
COLLABORATION_ROUTE = APP_ROOT / "route_backend_collaboration.py"
CHAT_STREAMING_JS = APP_ROOT / "static" / "js" / "chat" / "chat-streaming.js"
CHAT_MESSAGES_JS = APP_ROOT / "static" / "js" / "chat" / "chat-messages.js"
CHAT_COLLABORATION_JS = APP_ROOT / "static" / "js" / "chat" / "chat-collaboration.js"


def read_text(path: Path) -> str:
    """Read a UTF-8 repository file."""
    return path.read_text(encoding="utf-8")


def source_between(source: str, start_marker: str, end_marker: str) -> str:
    """Return source bounded by two required markers."""
    start_index = source.find(start_marker)
    end_index = source.find(end_marker, start_index + len(start_marker))
    assert start_index != -1, f"Missing start marker: {start_marker}"
    assert end_index != -1, f"Missing end marker: {end_marker}"
    return source[start_index:end_index]


def assert_ordered(source: str, *snippets: str) -> None:
    """Assert snippets occur in the supplied order."""
    cursor = -1
    for snippet in snippets:
        cursor = source.find(snippet, cursor + 1)
        assert cursor != -1, f"Missing or out-of-order snippet: {snippet}"


def test_user_message_persisted_event_contract() -> None:
    """Verify the nonterminal SSE event has the minimal persistence contract."""
    payload = build_user_message_persisted_stream_payload(
        "conversation-1",
        "conversation-1_user_1",
    )
    assert payload == {
        "type": USER_MESSAGE_PERSISTED_EVENT_TYPE,
        "conversation_id": "conversation-1",
        "user_message_id": "conversation-1_user_1",
        "message_persisted": True,
    }

    event_text = build_user_message_persisted_stream_event(
        "conversation-1",
        "conversation-1_user_1",
    )
    assert event_text.endswith("\n\n")
    assert json.loads(event_text.removeprefix("data: ").strip()) == payload


def test_all_streaming_paths_acknowledge_persistence_early() -> None:
    """Verify each server path emits after storage and before assistant work."""
    chat_source = read_text(CHAT_ROUTE)
    collaboration_source = read_text(COLLABORATION_ROUTE)

    document_action_source = source_between(
        chat_source,
        "def execute_document_action_chat_request(",
        "@bp.route('/api/chat/document-action', methods=['POST'])",
    )
    assert_ordered(
        document_action_source,
        "cosmos_messages_container.upsert_item(user_message_doc)",
        "publish_background_event(",
        "build_user_message_persisted_stream_event(",
        "_initialize_assistant_response_tracking(",
    )

    legacy_chat_source = source_between(
        chat_source,
        "def chat_api():",
        "@bp.route('/api/chat/stream', methods=['POST'])",
    )
    assert_ordered(
        legacy_chat_source,
        "cosmos_messages_container.upsert_item(user_message_doc)",
        "publish_background_event(",
        "build_user_message_persisted_stream_event(",
        "# Log chat activity for real-time tracking",
    )

    stream_route_source = chat_source[chat_source.find("@bp.route('/api/chat/stream', methods=['POST'])"):]
    assert "def generate_compatibility_response(publish_background_event=None):" in stream_route_source
    assert "g.chat_publish_background_event = publish_background_event" in stream_route_source
    assert "legacy_result = chat_api()" in stream_route_source
    assert_ordered(
        stream_route_source,
        "cosmos_messages_container.upsert_item(user_message_doc)",
        "yield build_user_message_persisted_stream_event(",
        "_initialize_assistant_response_tracking(",
    )

    collaboration_stream_source = source_between(
        collaboration_source,
        "def stream_collaboration_message_api(conversation_id):",
        "@bp.route('/api/collaboration/conversations/<conversation_id>/stream/cancel'",
    )
    assert_ordered(
        collaboration_stream_source,
        "persist_collaboration_message(",
        "yield build_user_message_persisted_stream_event(",
        "current_app.view_functions.get('chat_stream_api')",
    )
    assert "if stream_payload.get('type') == USER_MESSAGE_PERSISTED_EVENT_TYPE:" in collaboration_stream_source


def test_browser_reconciles_pending_metadata_without_terminal_event() -> None:
    """Verify the client handles the persistence event independently of done."""
    streaming_source = read_text(CHAT_STREAMING_JS)
    messages_source = read_text(CHAT_MESSAGES_JS)
    collaboration_source = read_text(CHAT_COLLABORATION_JS)

    assert "export function applyStreamingUserMessagePersistence(" in streaming_source
    assert "if (data.type === USER_MESSAGE_PERSISTED_EVENT_TYPE)" in streaming_source
    assert "const acknowledgedUserMessageId = applyStreamingUserMessagePersistence(" in streaming_source
    assert "{ refreshExpandedMetadata: true }" in streaming_source
    assert "finalizePendingUserMessageMetadata();" in streaming_source
    assert "markInterruptedUserMessageMetadata();" in streaming_source
    assert "markUserMessageMetadataFinalizationUnconfirmed(persistedUserMessageId);" in streaming_source
    assert "markUserMessageMetadataUnconfirmed(tempUserMessageId);" in streaming_source
    assert "persistedUserMessageId = String(data.user_message_id);" in streaming_source

    assert "const currentMessageId = messageDiv.getAttribute('data-message-id') || messageId;" in messages_source
    assert "container.dataset.metadataState = 'pending';" in messages_source
    assert "renderUserMetadataStatus(container, 'Saving message metadata...');" in messages_source
    assert "loadUserMessageMetadata(realId, metadataContainer);" in messages_source
    assert "export function markUserMessageMetadataUnconfirmed(messageId)" in messages_source
    assert "export function markUserMessageMetadataFinalizationUnconfirmed(messageId)" in messages_source
    assert "container.dataset.metadataRequestToken !== requestToken" in messages_source
    assert "container.dataset.metadataRequestToken === requestToken" in messages_source
    assert "export function setUserMessageStreamingActionsDisabled(messageId, disabled)" in messages_source
    assert "isUserMessageStreamingActionDisabled(e.currentTarget)" in messages_source
    assert "isUserMessageStreamingActionDisabled(addButton)" in messages_source
    assert "isUserMessageStreamingActionDisabled(removeButton)" in messages_source
    assert "initialPersistedUserMessageId: persistedUserMessageId" in streaming_source
    assert "setUserMessageStreamingActionsDisabled(persistedUserMessageId, false);" in streaming_source
    assert "setUserMessageStreamingActionsDisabled(payload.message.id, false);" in collaboration_source
    assert "messageKind !== 'ai_request'" in collaboration_source
    assert "Message metadata unavailable (temporary ID not updated)." not in messages_source


def test_implementation_version() -> None:
    """Verify the application version includes this fix."""
    assert_app_version_at_least("0.250.201")


if __name__ == "__main__":
    tests = [
        test_user_message_persisted_event_contract,
        test_all_streaming_paths_acknowledge_persistence_early,
        test_browser_reconciles_pending_metadata_without_terminal_event,
        test_implementation_version,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            results.append(False)

    raise SystemExit(0 if all(results) else 1)
