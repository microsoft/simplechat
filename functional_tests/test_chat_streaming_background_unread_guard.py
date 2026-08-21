#!/usr/bin/env python3
"""
Functional test for background chat streaming unread-state guard.
Version: 0.250.036
Implemented in: 0.250.036

This test ensures streaming finalization only clears unread assistant-response
state when the completed conversation is still the active conversation, so
background completions keep their notification and green unread dot.
"""

import os
import re
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STREAMING_JS = os.path.join(
    ROOT_DIR,
    "application",
    "single_app",
    "static",
    "js",
    "chat",
    "chat-streaming.js",
)


def test_streaming_finalization_keeps_background_unread_state():
    """Validate streaming completion mark-read is active-conversation guarded."""
    print("Testing streaming background unread guard...")

    with open(STREAMING_JS, "r", encoding="utf-8") as handle:
        source = handle.read()

    required_snippets = [
        "function isConversationCurrentlyActive(conversationId)",
        "function markStreamingConversationReadIfActive(conversationId, contextLabel)",
        "if (!isConversationCurrentlyActive(conversationId)) {",
        "markConversationRead(conversationId, { force: true, suppressErrorToast: true })",
        "markStreamingConversationReadIfActive(finalData.conversation_id, 'stream cancellation')",
        "markStreamingConversationReadIfActive(finalData.conversation_id, 'live streaming completion')",
        "if (finalData.conversation_id && !window.currentConversationId) {",
    ]
    for snippet in required_snippets:
        if snippet not in source:
            print(f"Missing required streaming guard snippet: {snippet}")
            return False

    forbidden_patterns = [
        r"markConversationRead\(finalData\.conversation_id,\s*\{\s*force:\s*true",
        r"if\s*\(\s*finalData\.conversation_id\s*&&\s*window\.currentConversationId\s*!==\s*finalData\.conversation_id\s*\)",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, source):
            print(f"Found forbidden unguarded streaming pattern: {pattern}")
            return False

    print("Streaming background unread guard test passed!")
    return True


if __name__ == "__main__":
    success = test_streaming_finalization_keeps_background_unread_state()
    sys.exit(0 if success else 1)
