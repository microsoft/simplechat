#!/usr/bin/env python3
# test_chat_early_conversation_title.py
"""
Functional test for early conversation title assignment.
Version: 0.241.042
Implemented in: 0.241.042

This test ensures new chat conversations derive a useful title from the first
submitted message and stream that metadata before long-running document actions
complete.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
CONVERSATIONS_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_conversations.py"
CHATS_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
OPERATIONS_FILE = ROOT / "application" / "single_app" / "functions_simplechat_operations.py"
CHAT_CONVERSATIONS_JS = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-conversations.js"
CHAT_MESSAGES_JS = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"
CHAT_STREAMING_JS = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-streaming.js"
FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "CONVERSATION_EARLY_TITLE_UPDATE_FIX.md"


def read_text(file_path):
    return file_path.read_text(encoding="utf-8")


def assert_contains(file_path, expected):
    content = read_text(file_path)
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def assert_ordered(file_path, first, second, start_marker=None):
    content = read_text(file_path)
    start_index = content.index(start_marker) if start_marker else 0
    first_index = content.index(first, start_index)
    second_index = content.index(second, start_index)
    if first_index >= second_index:
        raise AssertionError(
            f"Expected {first!r} to appear before {second!r} in {file_path}"
        )


def test_chat_early_conversation_title():
    """Verify early title derivation, persistence, and streaming hooks exist."""
    print("Testing early conversation title assignment...")

    assert_contains(CONFIG_FILE, 'VERSION = "0.241.042"')
    assert_contains(OPERATIONS_FILE, "def derive_conversation_title_from_message(content: str) -> str:")
    assert_contains(OPERATIONS_FILE, "normalized_content = re.sub")

    assert_contains(CONVERSATIONS_ROUTE_FILE, "data.get('initial_message')")
    assert_contains(CONVERSATIONS_ROUTE_FILE, "create_personal_conversation_for_current_user(title=initial_title)")
    assert_contains(CHAT_CONVERSATIONS_JS, "initialMessage = \"\"")
    assert_contains(CHAT_CONVERSATIONS_JS, "requestBody.initial_message = normalizedInitialMessage;")
    assert_contains(CHAT_MESSAGES_JS, "initialMessage: combinedMessage")

    assert_contains(CHATS_ROUTE_FILE, "def _build_conversation_metadata_stream_event(conversation_item):")
    assert_contains(CHATS_ROUTE_FILE, "'type': 'conversation_metadata'")
    assert_contains(CHATS_ROUTE_FILE, "publish_background_event(_build_conversation_metadata_stream_event(conversation_item))")
    assert_contains(CHATS_ROUTE_FILE, "yield _build_conversation_metadata_stream_event(conversation_item)")
    assert_ordered(
        CHATS_ROUTE_FILE,
        "title_updated = _set_initial_conversation_title(conversation_item, user_message)",
        "execution_result = _execute_document_action_workflow(",
        start_marker="def execute_document_action_chat_request",
    )

    assert_contains(CHAT_STREAMING_JS, "export function applyStreamingConversationMetadata(data = {})")
    assert_contains(CHAT_STREAMING_JS, "if (data.type === 'conversation_metadata')")
    assert_contains(CHAT_STREAMING_JS, "applyConversationMetadataUpdate(conversationId, metadataUpdates);")

    assert_contains(FIX_DOC_FILE, "Fixed/Implemented in version: **0.241.042**")
    assert_contains(FIX_DOC_FILE, "before `_execute_document_action_workflow(...)` begins")

    print("Early conversation title checks passed.")


if __name__ == "__main__":
    try:
        test_chat_early_conversation_title()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)