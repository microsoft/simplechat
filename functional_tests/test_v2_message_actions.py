#!/usr/bin/env python3
"""
Functional test for V2 chat per-message actions.

Version: 0.261.007
Implemented in: 0.261.007

This test ensures the V2 message action row agrees with the message API contracts it
drives. The retry and edit endpoints are the subtle ones: neither generates a reply on its
own. Each creates the next thread attempt and returns a ready-made request body for
/api/chat/stream, and skipping that second call leaves the new attempt permanently empty.

Attempt switching is likewise server-side state: the endpoint flips active_thread in
storage and /api/get_messages filters on it, so the client must re-read rather than
reorder locally.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def test_message_action_endpoints_exist():
    """Every endpoint the action row calls is still registered."""
    print("Testing message action endpoints...")

    conversations = _read(APP_DIR / "route_backend_conversations.py")
    for route in (
        "/api/message/<message_id>",
        "/api/message/<message_id>/retry",
        "/api/message/<message_id>/edit",
        "/api/message/<message_id>/switch-attempt",
        "/api/conversations/<conversation_id>/fork",
    ):
        assert f"'{route}'" in conversations, f"Route {route} is missing"

    exports = _read(APP_DIR / "route_backend_conversation_export.py")
    for route in (
        "/api/message/export-word",
        "/api/message/export-powerpoint",
        "/api/message/export-email-draft",
    ):
        assert f"'{route}'" in exports, f"Export route {route} is missing"

    # There is deliberately no markdown export endpoint; the client writes that file
    # itself. Asserting its absence keeps a future contributor from wiring a dead path.
    assert "export-markdown" not in exports, (
        "A markdown export endpoint now exists; the client currently generates markdown "
        "locally and should be switched to use it"
    )

    feedback = _read(APP_DIR / "route_backend_feedback.py")
    assert '"/feedback/submit"' in feedback, "The feedback submit route is missing"

    print("Message action endpoint test passed!")
    return True


def test_retry_and_edit_are_two_step_flows():
    """Retry and edit hand back a chat_request that must then be streamed."""
    print("Testing retry/edit two-step flow...")

    conversations = _read(APP_DIR / "route_backend_conversations.py")
    assert "'chat_request': chat_request" in conversations, (
        "The retry/edit endpoints no longer return a chat_request; the client depends on "
        "receiving a ready-made body to POST to /api/chat/stream"
    )

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    # Both must forward the server's body to the stream rather than generating locally.
    assert "result.chat_request" in store, (
        "retryMessage/editMessage must use the server-provided chat_request"
    )
    assert store.count("runChatStream(") >= 3, (
        "Send, retry and edit should all route through the shared stream runner"
    )
    assert "reloadOnDone: true" in store, (
        "Retry and edit rewrite thread state server-side and must re-read messages"
    )

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    assert "AttemptChatRequest" in endpoints, (
        "The retry/edit response type should model the chat_request handoff"
    )

    print("Retry/edit flow test passed!")
    return True


def test_attempt_switching_refetches_messages():
    """Switching attempts re-reads the message list rather than reordering locally."""
    print("Testing attempt switching...")

    conversations = _read(APP_DIR / "route_backend_conversations.py")
    assert "'available_attempts': available_attempts" in conversations
    assert "active_thread" in conversations, (
        "switch-attempt sets active_thread server-side, which is what /api/get_messages "
        "filters on"
    )

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    # Anchored on the implementation, since the same name also appears in the interface.
    # Sliced to the end of the function rather than a fixed character count, which breaks
    # whenever anything is added ahead of the call.
    changed = store[store.index("changeAttempt: async") :]
    changed = changed[: changed.index("\n    },")]
    assert "reloadMessages()" in changed, (
        "changeAttempt must refetch messages; the active attempt is server-side state"
    )

    print("Attempt switching test passed!")
    return True


def test_delete_sends_its_option_in_the_body():
    """Delete passes delete_thread in the JSON body, which is where the route reads it."""
    print("Testing delete request shape...")

    conversations = _read(APP_DIR / "route_backend_conversations.py")
    assert "delete_thread = data.get('delete_thread', False)" in conversations, (
        "The delete route reads delete_thread from the JSON body"
    )

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    delete_block = endpoints[endpoints.index("export const deleteMessage") :][:400]
    assert "delete_thread:" in delete_block, (
        "deleteMessage must send delete_thread in the body, not the query string"
    )

    client = _read(V2_SRC / "lib" / "apiClient.ts")
    assert "delete: <T>(path: string, body?: unknown" in client, (
        "The API client's delete helper must support a request body"
    )

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    remove_block = store[store.index("removeMessage: async") :][:900]
    assert "reloadMessages()" in remove_block, (
        "Deletion is soft when archiving is enabled, so the list must be re-read rather "
        "than trusting the optimistic removal"
    )

    print("Delete request shape test passed!")
    return True


def test_feedback_payload_matches_the_route():
    """Feedback uses the camelCase field names the route expects."""
    print("Testing feedback payload...")

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    feedback_block = endpoints[endpoints.index("export const submitFeedback") :][:500]
    for field in ("messageId", "conversationId", "feedbackType", "reason"):
        assert field in feedback_block, (
            f"The feedback payload must include {field!r}; the route reads camelCase keys"
        )

    actions = _read(V2_SRC / "components" / "chat" / "MessageActions.tsx")
    assert "enable_user_feedback" in actions, (
        "Feedback controls must be gated on enable_user_feedback"
    )

    print("Feedback payload test passed!")
    return True


def test_action_row_differs_by_role():
    """User messages can be edited; only assistant messages can be rated or forked."""
    print("Testing role-specific actions...")

    actions = _read(V2_SRC / "components" / "chat" / "MessageActions.tsx")

    assert "isUser && onEdit" in actions, "Edit must be offered only on user messages"
    assert "!isUser && feedbackEnabled" in actions, (
        "Feedback must be offered only on assistant messages"
    )
    assert "!isUser && (" in actions, "Fork must be offered only on assistant messages"

    # The overflow menu opens upward by default and would render off-screen for messages
    # near the top of the scroll area, so it flips when there is no room.
    assert "placement" in actions and "top-full" in actions, (
        "The overflow menu must flip below the trigger when there is no room above"
    )

    print("Role-specific action test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added message actions."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.007")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_message_action_endpoints_exist,
        test_retry_and_edit_are_two_step_flows,
        test_attempt_switching_refetches_messages,
        test_delete_sends_its_option_in_the_body,
        test_feedback_payload_matches_the_route,
        test_action_row_differs_by_role,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
