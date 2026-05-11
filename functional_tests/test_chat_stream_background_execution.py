#!/usr/bin/env python3
# test_chat_stream_background_execution.py
"""
Functional test for chat stream background execution.
Version: 0.239.185
Implemented in: 0.239.129

This test ensures that the streaming chat route runs its SSE generator through
background execution so chat completion can continue after the browser leaves
the page, while still streaming live events to an attached consumer and any
later reattached consumer.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "CHAT_STREAM_BACKGROUND_EXECUTION_FIX.md"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_chat_stream_background_execution() -> None:
    print("Testing chat stream background execution...")

    assert_contains(ROUTE_FILE, "class BackgroundStreamBridge:")
    assert_contains(ROUTE_FILE, "@copy_current_request_context")
    assert_contains(ROUTE_FILE, "executor = current_app.extensions.get('executor')")
    assert_contains(ROUTE_FILE, "executor.submit(stream_worker)")
    assert_contains(ROUTE_FILE, "worker_thread = threading.Thread(target=stream_worker, daemon=True)")
    assert_contains(ROUTE_FILE, "def publish_background_event(event_text):")
    assert_contains(ROUTE_FILE, "event_iterator = event_generator_factory(")
    assert_contains(ROUTE_FILE, "for event in event_iterator:")
    assert_contains(ROUTE_FILE, "stream_bridge.detach_consumer()")
    assert_contains(ROUTE_FILE, "CHAT_STREAM_REGISTRY = ActiveConversationStreamRegistry()")
    assert_contains(ROUTE_FILE, "return build_background_stream_response(generate_compatibility_response, stream_session=stream_session)")
    assert_contains(ROUTE_FILE, "return build_background_stream_response(generate, stream_session=stream_session)")

    assert_contains(CONFIG_FILE, 'VERSION = "0.239.185"')
    assert_contains(FIX_DOC_FILE, "Fixed/Implemented in version: **0.239.129**")

    print("Chat stream background execution checks passed!")


if __name__ == "__main__":
    try:
        test_chat_stream_background_execution()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)