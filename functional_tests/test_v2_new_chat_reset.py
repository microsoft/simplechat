#!/usr/bin/env python3
# test_v2_new_chat_reset.py
"""
Functional test for starting a new chat in V2 while the open conversation is busy.

Version: 0.261.226
Implemented in: 0.261.226

Clicking New chat while an orchestration turn was planning or running kept the old turn's
"Thinking" bubble and a Stop button with nothing to stop, hid the new chat's empty state,
and refused to send until the page was reloaded (issue #1617). An orchestration turn holds
the store's `streaming` flag without the chat-stream controller that `detachActiveStream`
clears, and its settle is skipped once its conversation is off screen, so nothing ever
cleared it.

Three neighbouring defects are pinned here as well: a first message still creating its
conversation took over a new chat opened during that round trip, a conversation still
loading left its loading placeholders in the new chat, and the workspace Chat actions and
Home's Start chatting reopened whichever conversation was last open instead of starting a
new one.

The browser behaviour is covered by ui_tests/test_v2_new_chat_reset.py; this test pins the
source decisions that behaviour depends on.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def _store():
    return _read(V2_SRC / "stores" / "chatStore.ts")


def _store_action_body(source, action_name):
    """Return one store action's body, matched to its closing brace at store indentation.

    Sliced past the `ChatState` interface first, which declares every action with the same
    `name: (` shape as the implementation.
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


def test_new_chat_releases_the_streaming_surface():
    """New chat clears `streaming` and `messagesLoading` itself, not only via the detach helper."""
    print("Testing the New chat reset...")

    start_new = _store_action_body(_store(), "startNewConversation")

    assert "streaming: false," in start_new, (
        "startNewConversation must clear `streaming`: an orchestration turn holds it without a "
        "chat-stream controller, so detachActiveStream never clears it and the new chat keeps the "
        "old turn's Thinking state and a Stop button with nothing to stop"
    )
    assert "messagesLoading: false," in start_new, (
        "startNewConversation must clear `messagesLoading`: a load in flight for the conversation "
        "being left returns early without clearing it, leaving placeholders in the new chat"
    )
    assert "conversationEpoch += 1;" in start_new, (
        "startNewConversation must advance the conversation epoch so a first message still "
        "creating its conversation cannot claim the new chat"
    )
    assert start_new.index("detachActiveStream();") < start_new.index("streaming: false,"), (
        "The chat stream must still be detached (not cancelled) before the reset"
    )

    print("New chat reset test passed!")
    return True


def test_opening_a_conversation_restores_only_a_running_orchestration_turn():
    """Opening a conversation drops the inherited flag and restores it only for its own turn."""
    print("Testing selectConversation's streaming flag...")

    select = _store_action_body(_store(), "selectConversation")

    assert "streaming: conversationId ? orchestrationSurfaces.has(conversationId) : false," in select, (
        "selectConversation must not inherit `streaming` from the conversation being left, and "
        "should restore Thinking and Stop for an orchestration turn still running in the one "
        "being opened"
    )
    assert "conversationEpoch += 1;" in select, (
        "selectConversation must advance the conversation epoch"
    )

    print("selectConversation streaming test passed!")
    return True


def test_orchestration_turns_record_their_streaming_surface_whatever_is_on_screen():
    """Begin claims and settle releases the surface before their on-screen guards."""
    print("Testing the orchestration surface bookkeeping...")

    store = _store()
    assert "const orchestrationSurfaces = new Set<string>();" in store, (
        "The store must track which conversations' orchestration turns hold the streaming surface"
    )

    begin = _store_action_body(store, "beginOrchestrationTurn")
    claim = begin.index("orchestrationSurfaces.add(conversationId);")
    assert claim < begin.index("if (get().activeConversationId === conversationId) {"), (
        "beginOrchestrationTurn must record the surface before its on-screen guard, so a turn "
        "started out of sight still shows as working when its conversation is opened"
    )

    settle = _store_action_body(store, "settleOrchestrationTurn")
    release = settle.index("orchestrationSurfaces.delete(conversationId);")
    assert release < settle.index("if (get().activeConversationId !== conversationId) {"), (
        "settleOrchestrationTurn must release the surface before its on-screen guard, or a turn "
        "that finished out of sight comes back as Thinking when its conversation is reopened"
    )

    reassign = _store_action_body(store, "reassignOrchestrationTurn")
    assert re.search(
        r"if \(conversationChanged && orchestrationSurfaces\.delete\(fromConversationId\)\) \{\s*"
        r"orchestrationSurfaces\.add\(toConversationId\);",
        reassign,
    ), "A turn re-keyed to the server's conversation id must take its surface with it"

    print("Orchestration surface bookkeeping test passed!")
    return True


def test_first_message_claims_need_an_unchanged_epoch():
    """Every creation path claims the screen only if no New chat or open happened meanwhile."""
    print("Testing the conversation-creation claims...")

    store = _store()
    assert re.search(r"let conversationEpoch = 0;", store), "The epoch counter is missing"
    assert "export function currentConversationEpoch(): number {" in store, (
        "The orchestration controller needs a reader for the epoch"
    )

    for action in ("sendMessage", "generateImageFromReference"):
        body = _store_action_body(store, action)
        assert "const epoch = conversationEpoch;" in body, (
            f"{action} must note the epoch before creating the conversation"
        )
        assert "if (get().activeConversationId === null && conversationEpoch === epoch) {" in body, (
            f"{action} claims the screen whenever the id is still null, which New chat also "
            f"leaves it; the question then takes over the fresh chat"
        )

    controller = _read(V2_SRC / "lib" / "orchestrationController.ts")
    ensure = re.search(r"async function ensureConversation\((.|\n)*?\n\}", controller)
    assert ensure, "Could not find ensureConversation"
    body = ensure.group(0)
    assert "const epoch = currentConversationEpoch();" in body, (
        "ensureConversation must note the epoch before creating the conversation"
    )
    assert "if (chat.activeConversationId === null && currentConversationEpoch() === epoch) {" in body, (
        "ensureConversation claims the screen whenever the id is still null"
    )

    print("Conversation-creation claim test passed!")
    return True


def test_chat_hand_offs_start_a_brand_new_conversation():
    """Workspace Chat actions and Home's Start chatting never reuse the open conversation."""
    print("Testing the hand-offs into chat...")

    explorer = _read(V2_SRC / "components" / "documents" / "DocumentExplorer.tsx")
    assert re.search(
        r"useChatStore\.getState\(\)\.startNewConversation\(\);\s*\n\s*navigate\(`/chat\?\$\{handoff\}`, \{ state \}\);",
        explorer,
    ), "Chat on selected documents must start a new chat immediately before navigating"

    tags = _read(V2_SRC / "pages" / "workspace" / "TagsSection.tsx")
    assert re.search(
        r"useChatStore\.getState\(\)\.startNewConversation\(\);\s*\n\s*navigate\(`/chat\?\$\{query\}`, \{ state \}\);",
        tags,
    ), "Chat on a tag must start a new chat immediately before navigating"

    home = _read(V2_SRC / "pages" / "HomePage.tsx")
    assert re.search(
        r"<Link\s+to=\"/chat\"\s+onClick=\{\(\) => useChatStore\.getState\(\)\.startNewConversation\(\)\}",
        home,
    ), "Start chatting must open a new chat rather than the conversation last open"

    print("Hand-off test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added the fix."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.226")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_new_chat_releases_the_streaming_surface,
        test_opening_a_conversation_restores_only_a_running_orchestration_turn,
        test_orchestration_turns_record_their_streaming_surface_whatever_is_on_screen,
        test_first_message_claims_need_an_unchanged_epoch,
        test_chat_hand_offs_start_a_brand_new_conversation,
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
