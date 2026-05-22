#!/usr/bin/env python3
# test_chat_stream_stop_control.py
"""
Functional test for chat stream stop control.
Version: 0.241.098
Implemented in: 0.241.097

This test ensures chat streams expose a user-scoped cancellation endpoint,
persist cancellation state, wire collaborative streams through their source
conversation, and render a message-local Stop control in the frontend.
"""

import sys
from pathlib import Path
import traceback


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content: str, expected: str, label: str) -> None:
    if expected not in content:
        raise AssertionError(f"Expected {label} to contain {expected!r}")


def test_chat_stream_stop_control_wiring() -> None:
    """Validate backend, collaboration, frontend, docs, and version wiring."""
    print("Testing chat stream stop control wiring...")

    config_content = read_text("application/single_app/config.py")
    route_content = read_text("application/single_app/route_backend_chats.py")
    collaboration_content = read_text("application/single_app/route_backend_collaboration.py")
    streaming_content = read_text("application/single_app/static/js/chat/chat-streaming.js")
    collaboration_js_content = read_text("application/single_app/static/js/chat/chat-collaboration.js")
    feature_doc_content = read_text("docs/explanation/features/v0.241.097/CHAT_STREAM_STOP_CONTROL.md")

    assert_contains(config_content, 'VERSION = "0.241.098"', "config version")

    assert_contains(route_content, "STREAM_STATUS_CANCEL_REQUESTED = 'cancel_requested'", "chat route")
    assert_contains(route_content, "STREAM_STATUS_CANCELED = 'canceled'", "chat route")
    assert_contains(route_content, "def request_cancel(self, reason='user_requested'):", "chat stream session")
    assert_contains(route_content, "def is_cancel_requested(self):", "chat stream session")
    assert_contains(route_content, "def _build_stream_cancel_event(", "cancel event builder")
    assert_contains(route_content, "@app.route('/api/chat/stream/cancel/<conversation_id>', methods=['POST'])", "chat cancel route")
    assert_contains(route_content, "if stream_cancel_requested():", "stream cancellation checkpoints")
    assert_contains(route_content, "yield finalize_cancelled_stream_response()", "cancelled stream finalization")

    assert_contains(
        collaboration_content,
        "@app.route('/api/collaboration/conversations/<conversation_id>/stream/cancel', methods=['POST'])",
        "collaboration cancel route",
    )
    assert_contains(collaboration_content, "source_conversation_id = str((conversation_doc or {}).get('source_conversation_id')", "source conversation lookup")
    assert_contains(collaboration_content, "CHAT_STREAM_REGISTRY.get_session(", "collaboration source stream lookup")
    assert_contains(collaboration_content, "stream_payload.get('cancelled') or stream_payload.get('canceled')", "collaboration cancel transform")

    assert_contains(streaming_content, "className = 'btn btn-sm btn-danger stream-stop-btn", "message-local Stop button")
    assert_contains(streaming_content, "rounded-circle p-0 border-0", "compact icon-only Stop button")
    assert_contains(streaming_content, "stopButton.style.width = '1.65rem'", "fixed-size Stop button")
    assert_contains(streaming_content, "async function requestStreamCancellation", "frontend cancel request")
    assert_contains(streaming_content, "fetch(streamContext.cancelEndpoint", "cancel endpoint POST")
    assert_contains(streaming_content, "finalizeCancelledStreamingMessage", "cancelled UI finalizer")
    assert_contains(streaming_content, "Stopped by you.", "stopped response banner")

    assert_contains(collaboration_js_content, "cancelEndpoint: `/api/collaboration/conversations/${encodeURIComponent(conversationId)}/stream/cancel`", "collaboration frontend cancel endpoint")
    assert_contains(feature_doc_content, "Implemented in version: **0.241.097**", "feature documentation")
    assert_contains(feature_doc_content, "Updated in version: **0.241.098**", "feature documentation refinement")
    assert_contains(feature_doc_content, "application/single_app/config.py", "feature documentation version reference")

    print("Chat stream stop control wiring verified")


def run_tests() -> bool:
    tests = [test_chat_stream_stop_control_wiring]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)