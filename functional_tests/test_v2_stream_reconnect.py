#!/usr/bin/env python3
"""
Functional test for V2 chat stream reconnection.

Version: 0.261.017
Implemented in: 0.261.017

A chat answer is generated on the server and written into a stream session that outlives
the HTTP connection carrying it. When that connection drops, V1 reattaches to the running
session instead of giving up; V2 previously surfaced "The response ended unexpectedly."
and discarded an answer that was still being written.

This test pins the reconnect implementation to the two routes it depends on, because both
its trigger and its replay semantics come from the server rather than from a client-side
choice:

  * ``GET /api/chat/stream/status/<id>``   -- whether anything is still running
  * ``GET /api/chat/stream/reattach/<id>`` -- the replayed SSE stream

The replay semantics matter most. The reattach route calls ``iter_events()`` with no start
index, so the session is replayed from its very first event. A client that appends the
replay to what it already rendered would show the answer twice.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def test_reattach_route_still_exists_and_replays_from_the_start():
    """The client's assumptions about the reattach route are read from the route itself."""
    print("Testing reattach route contract...")

    chats = _read(APP_DIR / "route_backend_chats.py")

    assert "'/api/chat/stream/reattach/<conversation_id>', methods=['GET']" in chats, (
        "The reattach route moved or changed method; the V2 client targets GET on this path"
    )
    assert "'/api/chat/stream/status/<conversation_id>', methods=['GET']" in chats, (
        "The stream status route moved; recovery is gated on it"
    )

    # The route hands back a replay, not a resume: iter_events() defaults start_index to 0.
    assert re.search(
        r"def consume_reattach_stream\(\):.*?stream_session\.iter_events\(\)",
        chats,
        re.DOTALL,
    ), (
        "The reattach route no longer replays with iter_events(); if it now resumes at an "
        "offset the client must stop clearing already-rendered content"
    )
    assert "def iter_events(self, start_index=0):" in chats, (
        "iter_events no longer defaults to replaying from the first event"
    )

    # Recovery is gated on `pending`, which the status payload derives from `active`.
    assert "snapshot['pending'] = snapshot['active']" in chats, (
        "The status payload no longer reports `pending`, which gates the reconnect attempt"
    )

    print("Reattach route contract test passed!")
    return True


def test_client_gates_recovery_on_stream_status():
    """A reconnect is only attempted when the server says something is still running."""
    print("Testing recovery gating...")

    sse = _read(V2_SRC / "lib" / "sse.ts")

    assert "/api/chat/stream/status/" in sse, (
        "The client must ask whether a stream is still live before reattaching"
    )
    assert "/api/chat/stream/reattach/" in sse, "The client must call the reattach route"
    assert "status?.pending" in sse, (
        "Recovery is gated on `pending`, matching chat-streaming.js:583"
    )

    legacy = _read(APP_DIR / "static" / "js" / "chat" / "chat-streaming.js")
    assert "if (!statusData?.pending)" in legacy, (
        "chat-streaming.js no longer gates recovery on `pending`; the parity this test "
        "asserts needs rechecking"
    )

    print("Recovery gating test passed!")
    return True


def test_replayed_content_replaces_rather_than_appends():
    """The replay starts at event zero, so prior content has to be discarded."""
    print("Testing replay reset...")

    sse = _read(V2_SRC / "lib" / "sse.ts")

    attach = re.search(
        r"async function attachToLiveStream\((.|\n)*?\n\}", sse
    )
    assert attach, "Could not find attachToLiveStream in the V2 stream reader"
    body = attach.group(0)

    assert "result.accumulated = '';" in body, (
        "The accumulated answer must be cleared before consuming a replay, or the "
        "reconnected answer is appended to a duplicate of itself"
    )
    assert "onReconnect" in body, (
        "The store has to be told to clear what is on screen for the same reason"
    )

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    assert re.search(r"onReconnect: \(\) => \{(.|\n)*?streamingContent: '',", store), (
        "The reconnect handler must clear the rendered streaming content"
    )
    assert re.search(r"onReconnect: \(\) => \{(.|\n)*?thoughts: \[\],", store), (
        "Reasoning steps are replayed too and would otherwise be listed twice"
    )

    print("Replay reset test passed!")
    return True


def test_only_one_recovery_attempt_is_made():
    """A failing reconnect is reported, not retried in a loop."""
    print("Testing single-attempt recovery...")

    sse = _read(V2_SRC / "lib" / "sse.ts")

    # The recovery consumer reports its own failure rather than recursing into another
    # attachToLiveStream call, mirroring allowRecovery: false in chat-streaming.js.
    assert sse.count("attachToLiveStream(") == 3, (
        "attachToLiveStream should be defined once and called exactly twice (from "
        "streamChat's recovery path and from reattachChatStream); an extra call site "
        "suggests recovery can recurse"
    )

    legacy = _read(APP_DIR / "static" / "js" / "chat" / "chat-streaming.js")
    assert "allowRecovery: false" in legacy, (
        "chat-streaming.js no longer limits recovery to a single attempt"
    )

    print("Single-attempt recovery test passed!")
    return True


def test_opening_a_generating_conversation_resumes_it():
    """Selecting a thread whose answer is still being written picks the stream back up."""
    print("Testing resume on conversation select...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    assert "async function resumeChatStream(" in store, (
        "A conversation opened mid-generation needs a resume path"
    )
    assert re.search(r"selectConversation:(.|\n)*?resumeChatStream\(conversationId\)", store), (
        "selectConversation must attempt a resume, as chat-conversations.js:1695 does"
    )

    # The status check has to happen before any streaming state is set, or every ordinary
    # conversation would flash a streaming placeholder on open.
    resume = re.search(r"async function resumeChatStream\((.|\n)*?\n\}", store).group(0)
    status_at = resume.index("fetchStreamStatus")
    streaming_at = resume.index("streaming: true")
    assert status_at < streaming_at, (
        "The stream status must be checked before the store is put into a streaming "
        "state, otherwise opening a normal conversation flickers a placeholder"
    )

    legacy = _read(APP_DIR / "static" / "js" / "chat" / "chat-conversations.js")
    assert "reattachStreamingConversation(conversationId)" in legacy, (
        "chat-conversations.js no longer reattaches on select; parity needs rechecking"
    )

    print("Resume on select test passed!")
    return True


def test_reconnecting_state_is_visible_to_the_user():
    """A silent reconnect looks identical to a hang, so it is surfaced."""
    print("Testing reconnect visibility...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    assert "reconnecting: boolean;" in store, "The store must model the reconnecting state"

    message_list = _read(V2_SRC / "components" / "chat" / "MessageList.tsx")
    assert "reconnecting" in message_list, (
        "The streaming bubble must tell the user the response was picked back up"
    )
    assert "Reconnect" in message_list, "The reconnect state needs a visible label"

    print("Reconnect visibility test passed!")
    return True


def test_attaching_to_a_stream_does_not_take_ownership_of_it():
    """Leaving a conversation must not cancel a generation this tab never started.

    ``stopStreaming`` POSTs ``/api/chat/stream/cancel``, which is a real server-side
    cancellation rather than a local abort, and it addresses ``streamingConversationId``.
    That marker therefore means "this tab started this stream". A resume attaches to a
    generation someone else started -- another tab, or this page before a reload -- so it
    must not set the marker, otherwise merely opening a generating conversation and then
    clicking away truncates the answer for whoever is waiting on it.
    """
    print("Testing stream ownership on attach...")

    chats = _read(APP_DIR / "route_backend_chats.py")
    # Establish that cancel really is destructive rather than a client-side detach.
    assert "def chat_stream_cancel_api" in chats or "stream/cancel" in chats, (
        "The cancel route moved; the premise of this test needs rechecking"
    )
    assert "request_cancel" in chats, (
        "The cancel route no longer requests a real cancellation"
    )

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    resume = re.search(r"async function resumeChatStream\((.|\n)*?\n\}", store).group(0)
    assert "streamingConversationId = conversationId" not in resume, (
        "resumeChatStream must not claim ownership of the stream it attaches to, or "
        "stopStreaming will cancel it server-side when the user navigates away"
    )

    # The stream this tab did start is still owned, so Stop still cancels it.
    run = re.search(r"async function runChatStream\((.|\n)*?\n\}", store).group(0)
    assert "streamingConversationId = conversationId;" in run, (
        "A stream this tab started must stay owned so the Stop button can cancel it"
    )

    # The classic client also only aborts locally on a thread switch.
    legacy = _read(APP_DIR / "static" / "js" / "chat" / "chat-conversations.js")
    assert "reattachStreamingConversation(conversationId)" in legacy
    assert "requestStreamCancellation" not in legacy, (
        "chat-conversations.js now cancels on switch; V2's behaviour should be revisited"
    )

    print("Stream ownership test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added reconnect."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.017")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_reattach_route_still_exists_and_replays_from_the_start,
        test_client_gates_recovery_on_stream_status,
        test_replayed_content_replaces_rather_than_appends,
        test_only_one_recovery_attempt_is_made,
        test_opening_a_generating_conversation_resumes_it,
        test_reconnecting_state_is_visible_to_the_user,
        test_attaching_to_a_stream_does_not_take_ownership_of_it,
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
