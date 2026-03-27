#!/usr/bin/env python3
# test_chat_stream_heartbeat_reattach.py
"""
Functional test for chat stream heartbeat and reattach support.
Version: 0.239.183
Implemented in: 0.239.183

This test ensures long-running chat streams emit keep-alive heartbeat frames,
register replayable in-flight sessions for reconnecting consumers through the
shared app cache, and that the chat UI attempts to reattach when a user
reopens an active conversation.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
APP_CACHE_FILE = ROOT / "application" / "single_app" / "app_settings_cache.py"
STREAMING_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-streaming.js"
CONVERSATIONS_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-conversations.js"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "CHAT_STREAM_HEARTBEAT_REATTACH_FIX.md"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def assert_not_contains(file_path: Path, forbidden: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if forbidden in content:
        raise AssertionError(f"Did not expect to find {forbidden!r} in {file_path}")


def test_chat_stream_heartbeat_and_reattach() -> None:
    print("Testing chat stream heartbeat and reattach support...")

    assert_contains(ROUTE_FILE, "yield ': keep-alive\\n\\n'")
    assert_contains(ROUTE_FILE, "class ActiveConversationStreamSession:")
    assert_contains(ROUTE_FILE, "CHAT_STREAM_REGISTRY = ActiveConversationStreamRegistry()")
    assert_contains(ROUTE_FILE, "@app.route('/api/chat/stream/status/<conversation_id>', methods=['GET'])")
    assert_contains(ROUTE_FILE, "@app.route('/api/chat/stream/reattach/<conversation_id>', methods=['GET'])")
    assert_contains(ROUTE_FILE, "stream_with_context(stream_session.iter_events())")
    assert_contains(ROUTE_FILE, "import app_settings_cache")
    assert_contains(ROUTE_FILE, "app_settings_cache.initialize_stream_session_cache(")
    assert_contains(ROUTE_FILE, "app_settings_cache.append_stream_session_event(")
    assert_contains(ROUTE_FILE, "app_settings_cache.get_stream_session_events(")

    assert_contains(APP_CACHE_FILE, "APP_STREAM_SESSION_METADATA = {}")
    assert_contains(APP_CACHE_FILE, "APP_STREAM_SESSION_EVENTS = {}")
    assert_contains(APP_CACHE_FILE, "def initialize_stream_session_cache_redis(cache_key, metadata, ttl_seconds=None):")
    assert_contains(APP_CACHE_FILE, "def append_stream_session_event_redis(cache_key, event_text, ttl_seconds=None):")
    assert_contains(APP_CACHE_FILE, "def get_stream_session_events_mem(cache_key, start_index=0):")

    assert_contains(STREAMING_FILE, "export async function reattachStreamingConversation(conversationId)")
    assert_contains(STREAMING_FILE, "fetch(`/api/chat/stream/status/${conversationId}`")
    assert_contains(STREAMING_FILE, "fetch(`/api/chat/stream/reattach/${conversationId}`")
    assert_not_contains(STREAMING_FILE, "5 * 60 * 1000")

    assert_contains(CONVERSATIONS_FILE, "await loadMessages(conversationId);")
    assert_contains(CONVERSATIONS_FILE, "await streamingModule.reattachStreamingConversation(conversationId);")

    assert_contains(CONFIG_FILE, 'VERSION = "0.239.183"')
    assert_contains(FIX_DOC_FILE, "Fixed/Implemented in version: **0.239.183**")
    assert_contains(FIX_DOC_FILE, "Redis-backed session metadata and event replay")

    print("Chat stream heartbeat and reattach checks passed!")


if __name__ == "__main__":
    try:
        test_chat_stream_heartbeat_and_reattach()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)