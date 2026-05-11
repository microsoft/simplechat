#!/usr/bin/env python3
# test_chat_stream_new_conversation_reattach.py
"""
Functional test for new-conversation chat stream reattach support.
Version: 0.239.191
Implemented in: 0.239.191

This test ensures the streaming chat route finalizes a conversation id before
registering the replayable stream session, and that the chat client performs a
single automatic reattach attempt when an in-flight stream disconnects.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
STREAMING_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-streaming.js"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "CHAT_STREAM_NEW_CONVERSATION_REATTACH_FIX.md"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_chat_stream_new_conversation_reattach() -> None:
    print("Testing new-conversation chat stream reattach support...")

    assert_contains(ROUTE_FILE, "finalized_conversation_id = requested_conversation_id or str(uuid.uuid4())")
    assert_contains(ROUTE_FILE, "data['conversation_id'] = finalized_conversation_id")
    assert_contains(ROUTE_FILE, "stream_session = CHAT_STREAM_REGISTRY.start_session(user_id, finalized_conversation_id)")
    assert_contains(ROUTE_FILE, "g.conversation_id = finalized_conversation_id")
    assert_contains(ROUTE_FILE, "conversation_id = finalized_conversation_id")
    assert_contains(ROUTE_FILE, "if is_new_stream_conversation:")

    assert_contains(STREAMING_FILE, "async function attemptStreamingRecovery(")
    assert_contains(STREAMING_FILE, "const recoveryConversationId = currentConversationId || messageData?.conversation_id || window.currentConversationId || null;")
    assert_contains(STREAMING_FILE, "const statusData = await getStreamingStatus(conversationId);")
    assert_contains(STREAMING_FILE, "if (allowRecovery) {")
    assert_contains(STREAMING_FILE, "allowRecovery: false,")

    assert_contains(CONFIG_FILE, 'VERSION = "0.239.191"')
    assert_contains(FIX_DOC_FILE, "Fixed/Implemented in version: **0.239.191**")
    assert_contains(FIX_DOC_FILE, "finalizes a conversation id before registering the stream session")

    print("New-conversation chat stream reattach checks passed!")


if __name__ == "__main__":
    try:
        test_chat_stream_new_conversation_reattach()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)