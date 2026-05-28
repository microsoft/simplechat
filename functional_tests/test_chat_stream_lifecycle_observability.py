#!/usr/bin/env python3
# test_chat_stream_lifecycle_observability.py
"""
Functional test for chat stream lifecycle observability.
Version: 0.241.111
Implemented in: 0.241.109

This test ensures long-running chat streams persist lifecycle state for
started, detached, reattached, completed, and errored runs, and that the
frontend reports stream failures back to the backend for correlation.
"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
STREAMING_FILE = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-streaming.js"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "v0.241.109" / "CHAT_STREAM_LIFECYCLE_OBSERVABILITY_FIX.md"
CURRENT_VERSION = "0.241.111"


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def test_chat_stream_lifecycle_observability() -> None:
    print("Testing chat stream lifecycle observability...")

    assert_contains(ROUTE_FILE, "STREAM_STATUS_DETACHED_RUNNING = 'detached_running'")
    assert_contains(ROUTE_FILE, "ALLOWED_STREAM_CLIENT_EVENTS = {")
    assert_contains(ROUTE_FILE, "def _build_stream_status_payload(metadata):")
    assert_contains(ROUTE_FILE, "def note_keepalive(self, source='unknown'):")
    assert_contains(ROUTE_FILE, "def note_queue_backpressure(self, queue_depth=0):")
    assert_contains(ROUTE_FILE, "def mark_consumer_detached(self, reason='client_disconnect'):")
    assert_contains(ROUTE_FILE, "def mark_reattached(self):")
    assert_contains(ROUTE_FILE, "self._stream_session.note_keepalive(source='bridge')")
    assert_contains(ROUTE_FILE, "self.note_keepalive(source='session')")
    assert_contains(ROUTE_FILE, "@app.route('/api/chat/stream/client-event', methods=['POST'])")
    assert_contains(ROUTE_FILE, "def chat_stream_client_event_api():")
    assert_contains(ROUTE_FILE, "stream_status = stream_session.get_status_snapshot() if stream_session else _build_stream_status_payload(None)")
    assert_contains(ROUTE_FILE, "stream_session.mark_reattached()")
    assert_contains(ROUTE_FILE, "stream_session.mark_consumer_detached(reason='reattach_disconnect')")
    assert_contains(ROUTE_FILE, "stream_bridge.detach_consumer(reason='client_disconnect', update_session=True)")

    assert_contains(STREAMING_FILE, "function reportClientStreamEvent(eventType, payload = {})")
    assert_contains(STREAMING_FILE, "fetch('/api/chat/stream/client-event', {")
    assert_contains(STREAMING_FILE, "void reportClientStreamEvent('stream_request_error'")
    assert_contains(STREAMING_FILE, "void reportClientStreamEvent('stream_read_error'")
    assert_contains(STREAMING_FILE, "void reportClientStreamEvent('stream_premature_end'")
    assert_contains(STREAMING_FILE, "void reportClientStreamEvent('stream_recovery_attempt'")
    assert_contains(STREAMING_FILE, "void reportClientStreamEvent('stream_recovery_attached'")
    assert_contains(STREAMING_FILE, "void reportClientStreamEvent('stream_recovery_unavailable'")
    assert_contains(STREAMING_FILE, "void reportClientStreamEvent('stream_aborted'")

    assert_contains(CONFIG_FILE, f'VERSION = "{CURRENT_VERSION}"')
    assert_contains(FIX_DOC_FILE, "Fixed/Implemented in version: **0.241.109**")
    assert_contains(FIX_DOC_FILE, "client-event endpoint")
    assert_contains(FIX_DOC_FILE, "detach, reattach, keepalive, queue backpressure, and terminal status")

    print("Chat stream lifecycle observability checks passed!")


if __name__ == "__main__":
    try:
        test_chat_stream_lifecycle_observability()
        success = True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)
