#!/usr/bin/env python3
# test_chat_stream_debug_logging.py
"""
Functional test for chat stream debug logging.
Version: 0.239.185
Implemented in: 0.239.142

This test ensures that the streaming chat route retains unconditional
debug_print instrumentation for request entry, plugin callback orchestration,
and final stream completion so local troubleshooting remains visible.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_chat_stream_debug_logging() -> None:
    print("Testing chat stream debug logging markers...")

    assert_contains(ROUTE_FILE, '[Streaming] Incoming /api/chat/stream request | ')
    assert_contains(ROUTE_FILE, '[Streaming] Routing request through compatibility bridge')
    assert_contains(ROUTE_FILE, '[Streaming] Parsed request payload | ')
    assert_contains(ROUTE_FILE, '[Streaming] Cleared plugin invocations for user_id=')
    assert_contains(ROUTE_FILE, '[Streaming] Selected response path | ')
    assert_contains(ROUTE_FILE, '[Streaming][Plugin Callback] Registering callback for key=')
    assert_contains(ROUTE_FILE, '[Streaming][Plugin Callback] Deregistered callback after successful stream for key=')
    assert_contains(ROUTE_FILE, '[Streaming] Finalizing stream response | ')
    assert_contains(CONFIG_FILE, 'VERSION = "0.239.185"')

    print("Chat stream debug logging checks passed!")


if __name__ == "__main__":
    try:
        test_chat_stream_debug_logging()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)