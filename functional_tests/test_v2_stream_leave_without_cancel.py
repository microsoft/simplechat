#!/usr/bin/env python3
"""
Functional test for leaving a V2 conversation without cancelling its generation.

Version: 0.261.051
Implemented in: 0.261.050 (cancellation), 0.261.051 (conversation-creation window)

Sending a message and then opening a different conversation used to end the answer. Not
because the reader was dropped -- that is harmless, generation runs in background execution
and outlives the connection carrying it -- but because the thread switch POSTed
``/api/chat/stream/cancel``, which is a real server-side cancellation. Leaving during the
thinking phase, before the first content token, persisted no assistant message at all, so
returning to the thread showed the question with no answer and nothing left to reattach to.

The distinction this test protects is between *stopping reading* and *stopping generating*.
Only the Stop button means the second one. Everything else -- switching threads, starting a
new chat -- must detach.

A second, narrower version of "leave straight after sending" is covered here too. The first
message of a brand-new chat has to create the conversation before it can stream, and a
reader who clicks away during that round trip used to be snapped back into the chat they had
just left, sometimes with the other thread's messages rendered underneath it. Their click
wins instead: the answer is still generated and saved, and the interface stays put.
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


def _function_body(source, signature_pattern):
    """Return one top-level function body, matched to its closing brace at column zero."""
    match = re.search(signature_pattern + r"(.|\n)*?\n\}", source)
    assert match, f"Could not find a function matching {signature_pattern!r}"
    return match.group(0)


def _store_action_body(source, action_name):
    """Return one store action's body, matched to its closing brace at store indentation.

    Sliced past the `ChatState` interface first: it declares every action with the same
    `name: (` shape as the implementation, so an unanchored search matches the type
    signature and then runs on into unrelated code.
    """
    start = source.index("export const useChatStore = create")
    implementation = source[start:]
    match = re.search(
        r"^    " + re.escape(action_name) + r": (?:async )?\((.|\n)*?\n    \},",
        implementation,
        re.MULTILINE,
    )
    assert match, f"Could not find the {action_name} store action"
    return match.group(0)


def test_cancelling_really_ends_the_generation():
    """The premise: the cancel route is destructive, not a client-side detach."""
    print("Testing that cancel is destructive...")

    chats = _read(APP_DIR / "route_backend_chats.py")

    assert "'/api/chat/stream/cancel/<conversation_id>', methods=['POST']" in chats, (
        "The cancel route moved; this test's premise needs rechecking"
    )
    assert "stream_session.request_cancel(reason=cancel_reason)" in chats, (
        "The cancel route no longer requests a real cancellation"
    )
    assert re.search(
        r"def request_cancel\(self, reason='user_requested'\):(.|\n)*?metadata\['cancel_requested'\] = True",
        chats,
    ), "request_cancel no longer sets cancel_requested, which the generation loop honours"
    assert "def is_cancel_requested(self):" in chats, (
        "The generation loop's cancellation check is gone; cancel may no longer stop work"
    )

    print("Cancel destructiveness test passed!")
    return True


def test_an_early_cancel_persists_no_answer_at_all():
    """Why the timing mattered: cancelling before the first token saves nothing.

    A cancel that lands after content has started keeps the partial answer. One that lands
    during the thinking phase does not, which is why leaving early looked like the response
    was never generated rather than like it was cut short.
    """
    print("Testing early-cancel persistence...")

    chats = _read(APP_DIR / "route_backend_chats.py")

    assert "message_persisted=False," in chats, (
        "The pre-content cancel path no longer reports message_persisted=False; the reason "
        "an early leave left no answer behind needs rechecking"
    )
    assert "message_persisted=bool(payload.get('message_id'))," in chats, (
        "The post-content cancel path no longer persists a partial answer"
    )

    print("Early-cancel persistence test passed!")
    return True


def test_generation_survives_a_dropped_reader():
    """Detaching is only safe because the server keeps generating without a listener."""
    print("Testing background execution...")

    chats = _read(APP_DIR / "route_backend_chats.py")

    assert re.search(
        r"def build_background_stream_response\(event_generator_factory, stream_session=None\):\s*\n\s*\"\"\"[^\"]*survives disconnects",
        chats,
    ), (
        "Streaming no longer documents surviving disconnects; if generation now dies with "
        "its reader, detaching on a thread switch would lose the answer"
    )

    print("Background execution test passed!")
    return True


def test_leaving_a_conversation_detaches_rather_than_cancels():
    """The fix: a thread switch drops the reader and leaves the generation running."""
    print("Testing detach on conversation switch...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    select = _store_action_body(store, "selectConversation")
    assert "detachActiveStream()" in select, (
        "selectConversation must detach the running stream's reader"
    )
    assert "stopStreaming()" not in select, (
        "selectConversation calls stopStreaming again, which POSTs a real server-side "
        "cancel; opening another conversation would once more destroy the answer being "
        "written in the one being left"
    )
    assert "cancelStream(" not in select, (
        "selectConversation must not reach the cancel route by any route"
    )

    print("Detach on conversation switch test passed!")
    return True


def test_starting_a_new_chat_detaches_rather_than_cancels():
    """Same rule for New chat, which is the other way out of a generating thread."""
    print("Testing detach on new chat...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    start_new = _store_action_body(store, "startNewConversation")
    assert "detachActiveStream()" in start_new, (
        "startNewConversation must detach the running stream's reader"
    )
    assert "stopStreaming()" not in start_new, (
        "startNewConversation calls stopStreaming again, so clicking New chat mid-answer "
        "cancels it server-side instead of leaving it to finish"
    )
    assert "cancelStream(" not in start_new, (
        "startNewConversation must not reach the cancel route by any route"
    )

    print("Detach on new chat test passed!")
    return True


def test_the_detach_helper_does_not_cancel():
    """Detaching is defined by what it does not do, so that is what is pinned."""
    print("Testing the detach helper...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    detach = _function_body(store, r"function detachActiveStream\(\): void \{")
    assert "cancelStream" not in detach, (
        "detachActiveStream must not ask the server to stop generating; that is the whole "
        "difference between it and stopStreaming"
    )
    assert "activeStreamController.abort();" in detach, (
        "detachActiveStream must still abort the local reader, or a stream for the thread "
        "just left keeps writing into the newly opened one"
    )
    assert "streamingConversationId = null;" in detach, (
        "The ownership marker must be cleared, or Stop would later cancel a conversation "
        "that is no longer on screen"
    )

    print("Detach helper test passed!")
    return True


def test_detaching_leaves_the_composer_usable():
    """The streaming flag has to be cleared by the helper, because no caller clears it.

    Neither `selectConversation` nor `startNewConversation` sets `streaming: false` in its
    own state reset -- both relied on `stopStreaming` doing it. If the helper dropped it,
    leaving a generating thread would strand the composer showing Stop for a stream nothing
    is reading.
    """
    print("Testing composer state after detach...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    detach = _function_body(store, r"function detachActiveStream\(\): void \{")
    assert "streaming: false" in detach, (
        "detachActiveStream must clear the streaming flag; its callers do not"
    )
    assert "reconnectPhase: null" in detach, (
        "A detach must clear any reconnect phase, or the next thread opens still claiming "
        "to be reconnecting"
    )

    for action in ("selectConversation", "startNewConversation"):
        body = _store_action_body(store, action)
        assert "streaming: false" not in body, (
            f"{action} now clears `streaming` itself. That is fine, but this test's reason "
            f"for requiring it of detachActiveStream needs rechecking"
        )

    print("Composer state test passed!")
    return True


def test_stop_still_cancels():
    """The Stop button is the one control that must still end the generation."""
    print("Testing that Stop still cancels...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    stop = _store_action_body(store, "stopStreaming")
    assert "cancelStream(" in stop, (
        "stopStreaming no longer cancels server-side, so Stop would leave the answer being "
        "written and billed after the reader asked for it to end"
    )
    assert "detachActiveStream()" in stop, (
        "stopStreaming should share the teardown rather than repeat it"
    )

    # Stop is a user action, so it stays wired to the button rather than to navigation.
    composer = _read(V2_SRC / "components" / "chat" / "Composer.tsx")
    assert "onClick={stopStreaming}" in composer, (
        "The Stop button is no longer wired to stopStreaming"
    )

    print("Stop cancellation test passed!")
    return True


def test_only_the_stop_button_reaches_the_cancel_route():
    """No other caller may cancel, which is what regressed the first time."""
    print("Testing cancel call sites...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    # Two references only: the import and the single call inside stopStreaming.
    assert store.count("cancelStream(") == 1, (
        "cancelStream is called from more than one place in the store. Every caller other "
        "than stopStreaming ends a generation the reader did not ask to end"
    )

    print("Cancel call site test passed!")
    return True


def test_legacy_never_cancelled_on_a_thread_switch():
    """The behaviour being restored is V1's, so V1 is what it is measured against."""
    print("Testing legacy parity...")

    conversations = _read(APP_DIR / "static" / "js" / "chat" / "chat-conversations.js")
    assert "reattachStreamingConversation(conversationId)" in conversations, (
        "chat-conversations.js no longer reattaches on select; parity needs rechecking"
    )
    assert "requestStreamCancellation" not in conversations, (
        "chat-conversations.js now cancels on a thread switch, so it is no longer the "
        "reference behaviour this fix restores"
    )

    streaming = _read(APP_DIR / "static" / "js" / "chat" / "chat-streaming.js")
    assert "export function cancelStreaming()" in streaming, (
        "The explicit stop entry point moved; the claim that cancellation is user-driven "
        "needs rechecking"
    )

    print("Legacy parity test passed!")
    return True


def test_a_reattached_stream_is_not_owned():
    """Attaching to someone else's generation must not hand this tab the power to end it."""
    print("Testing reattach ownership...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")

    resume = _function_body(store, r"async function resumeChatStream\(")
    assert "streamingConversationId = conversationId" not in resume, (
        "resumeChatStream must not claim ownership of a stream it merely attached to, or "
        "Stop would cancel a generation another tab is waiting on"
    )

    run = _function_body(store, r"async function runChatStream\(")
    assert "streamingConversationId = conversationId;" in run, (
        "A stream this tab started must stay owned so Stop can cancel it"
    )

    # V1 draws the same line: its reattached stream is opened without a cancel endpoint.
    streaming = _read(APP_DIR / "static" / "js" / "chat" / "chat-streaming.js")
    reattach = re.search(
        r"export async function reattachStreamingConversation\((.|\n)*?\n\}", streaming
    )
    assert reattach, "Could not find reattachStreamingConversation"
    assert "cancelEndpoint" not in reattach.group(0), (
        "chat-streaming.js now gives a reattached stream a cancel endpoint; V2's matching "
        "choice should be revisited"
    )

    print("Reattach ownership test passed!")
    return True


def test_creating_a_conversation_does_not_take_the_screen_back():
    """Opening another thread while a new chat is being created must not be undone.

    The first message of a brand-new chat has to create the conversation before it can
    stream, and that round trip is a window in which the reader can click elsewhere. Claiming
    `activeConversationId` unconditionally afterwards snapped them back into the chat they
    had just left.
    """
    print("Testing conversation creation does not steal the screen...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    send = _store_action_body(store, "sendMessage")

    assert re.search(
        r"if \(get\(\)\.activeConversationId === null\) \{\s*\n\s*set\(\{ activeConversationId: conversationId",
        send,
    ), (
        "sendMessage claims activeConversationId without checking whether the reader opened "
        "something else while the conversation was being created; their click gets undone"
    )

    print("Screen ownership on creation test passed!")
    return True


def test_a_backgrounded_send_does_not_write_into_the_open_thread():
    """The optimistic message and streaming state belong to whatever is on screen."""
    print("Testing optimistic message placement...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    send = _store_action_body(store, "sendMessage")

    assert "const ownsScreen = get().activeConversationId === conversationId;" in send, (
        "sendMessage no longer works out whether this send owns the screen"
    )
    assert re.search(
        r"if \(ownsScreen\) \{\s*\n\s*set\(\(state\) => \(\{\s*\n\s*messages: \[\.\.\.state\.messages, optimisticUserMessage\]",
        send,
    ), (
        "The optimistic user message is appended unconditionally, so a send whose "
        "conversation is no longer on screen puts its question into another thread's list"
    )

    print("Optimistic message placement test passed!")
    return True


def test_rendering_is_gated_on_the_conversation_not_only_the_controller():
    """Controller identity answers teardown; it does not answer where to render.

    Switching threads mid-response clears the controller, so identity alone used to cover
    both questions. It does not cover the conversation-creation window, where there is no
    controller yet to clear -- the handlers would install one afterwards and write into
    whatever thread the reader had opened.
    """
    print("Testing render gating...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    run = _function_body(store, r"async function runChatStream\(")

    assert "const ownsController = () => activeStreamController === controller;" in run, (
        "runChatStream no longer tracks controller ownership separately from currency"
    )
    assert re.search(
        r"const isCurrent = \(\)\s*=>\s*ownsController\(\) && getState\(\)\.activeConversationId === conversationId;",
        run,
    ), (
        "The handlers' currency check no longer requires the stream's conversation to be "
        "the one on screen, so a backgrounded send renders into the open thread"
    )

    # Teardown must stay on identity: a stream whose conversation is off screen still owns
    # the module's controller and is the only thing allowed to clear it.
    assert "if (ownsController()) {" in run, (
        "Teardown is gated on something other than controller identity; a stream left off "
        "screen would never clear activeStreamController, and resumeChatStream refuses to "
        "attach while one is set"
    )

    print("Render gating test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added the fix."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.050")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_cancelling_really_ends_the_generation,
        test_an_early_cancel_persists_no_answer_at_all,
        test_generation_survives_a_dropped_reader,
        test_leaving_a_conversation_detaches_rather_than_cancels,
        test_starting_a_new_chat_detaches_rather_than_cancels,
        test_the_detach_helper_does_not_cancel,
        test_detaching_leaves_the_composer_usable,
        test_stop_still_cancels,
        test_only_the_stop_button_reaches_the_cancel_route,
        test_legacy_never_cancelled_on_a_thread_switch,
        test_a_reattached_stream_is_not_owned,
        test_creating_a_conversation_does_not_take_the_screen_back,
        test_a_backgrounded_send_does_not_write_into_the_open_thread,
        test_rendering_is_gated_on_the_conversation_not_only_the_controller,
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
