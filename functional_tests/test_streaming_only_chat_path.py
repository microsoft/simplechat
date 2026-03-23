# test_streaming_only_chat_path.py
#!/usr/bin/env python3
"""
Functional test for streaming-only chat path migration.
Version: 0.239.136
Implemented in: 0.239.127

This test ensures that first-party chat clients use the streaming chat path,
that the legacy non-streaming fallback is not called directly from chat UI
entry points, and that the streaming backend retains a compatibility bridge
for parity-sensitive requests including image-generation thought events.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def assert_not_contains(file_path: Path, forbidden: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if forbidden in content:
        raise AssertionError(f"Did not expect to find {forbidden!r} in {file_path}")


def test_streaming_only_chat_path() -> bool:
    print("Testing streaming-only chat path migration...")

    chat_messages = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"
    chat_retry = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-retry.js"
    chat_edit = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-edit.js"
    chat_streaming = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-streaming.js"
    route_backend_chats = ROOT / "application" / "single_app" / "route_backend_chats.py"
    chats_template = ROOT / "application" / "single_app" / "templates" / "chats.html"
    settings_file = ROOT / "application" / "single_app" / "functions_settings.py"
    config_file = ROOT / "application" / "single_app" / "config.py"

    assert_contains(chat_messages, "sendMessageWithStreaming(")
    assert_not_contains(chat_messages, 'fetch("/api/chat"')
    assert_not_contains(chat_retry, "fetch('/api/chat'")
    assert_not_contains(chat_edit, "fetch('/api/chat'")

    assert_contains(chat_streaming, "fetch('/api/chat/stream'")
    assert_contains(chat_streaming, "finalData.image_url")
    assert_contains(chat_streaming, "finalData.reload_messages")

    assert_contains(route_backend_chats, "compatibility_mode = bool(data.get('image_generation'))")
    assert_contains(route_backend_chats, "generate_compatibility_response")
    assert_contains(route_backend_chats, "'user_message_id': user_message_id")
    assert_contains(route_backend_chats, 'Generating image based on')
    assert_contains(route_backend_chats, 'Preparing image model request')
    assert_contains(route_backend_chats, 'Image generated and ready to display')

    assert_not_contains(chats_template, "streaming-toggle-btn")
    assert_contains(settings_file, "'streamingEnabled': True")
    assert_contains(route_backend_chats, "return build_background_stream_response(generate_compatibility_response)")
    assert_contains(route_backend_chats, "return build_background_stream_response(generate)")
    assert_contains(config_file, 'VERSION = "0.239.136"')

    print("Streaming-only chat path checks passed!")
    return True


if __name__ == "__main__":
    try:
        success = test_streaming_only_chat_path()
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)
