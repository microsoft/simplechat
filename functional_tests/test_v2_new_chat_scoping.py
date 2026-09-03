#!/usr/bin/env python3
"""
Functional test for the V2 interface's New chat button.

Version: 0.261.041
Implemented in: 0.261.041

Three defects met at one button.

It was drawn in the rail on every page, but it is wired to a store action that resets chat
state and nothing else -- there is no router navigation anywhere in the V2 source -- so on
the workspace, admin or settings pages it reset state that was not on screen and left the
reader where they were. It looked like a button that did nothing.

It also did not look like a button at all. Tailwind v4's Preflight dropped the v3 rule
giving buttons a pointer cursor, and theme.css never restored it, so every control in the
interface rendered with the arrow browsers use for inert text.

And pressing it stranded the conversation drawer: the reset cleared the metadata but left
`drawerMode` set, while the header's Contents and Documents toggles are drawn only while a
conversation is open. The drawer stayed on screen, empty, with its controls gone -- the
same fault fixed in the classic interface in v0.260.004.

This test ensures the button is offered only where it can act, that reaching the chat page
from elsewhere starts a fresh chat instead of silently resuming the last conversation, that
an in-flight reply is not destroyed by that reset, and that buttons look clickable.
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


def _sidebar_component():
    """The body of the exported Sidebar component, without its helper components."""
    source = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    component = re.search(r"export function Sidebar\(\)(.|\n)*", source)
    assert component, "Sidebar should export a Sidebar component"
    return component.group(0)


def test_new_chat_is_only_offered_on_the_chat_page():
    """A button that resets state the reader cannot see is a button that does nothing."""
    print("Testing New chat placement...")

    body = _sidebar_component()

    assert "const onChatPage = location.pathname.startsWith('/chat')" in body, (
        "The rail must know which page it is on to place the button"
    )

    button = re.search(
        r"\{onChatPage && \(\s*<div className=\"px-3\">(.|\n)*?</div>\s*\)\}", body
    )
    assert button, (
        "The New chat button must be gated on the chat route. Rendered elsewhere it "
        "resets chat state that is not on screen and leaves the reader where they were"
    )
    assert "onClick={startNewConversation}" in button.group(0), (
        "The button must still start a new conversation"
    )
    assert "New chat" in button.group(0), "The gated block must be the New chat button"

    # The nav list took the button's place at the top of the rail on other pages, so its
    # spacing has to follow the button rather than being unconditional.
    assert "clsx('space-y-0.5 px-3', onChatPage && 'mt-3')" in body, (
        "The nav list must only carry the button's separating margin when the button "
        "is there, or the rail gains a gap on every other page"
    )

    print("New chat placement test passed!")
    return True


def test_reaching_chat_from_elsewhere_starts_a_new_chat():
    """Hiding the button elsewhere only works if Chats covers the case it left behind."""
    print("Testing the Chats navigation reset...")

    body = _sidebar_component()

    handler = re.search(r"const startNewChatOnArrival = \(\) => \{(.|\n)*?\n    \};", body)
    assert handler, (
        "Arriving at the chat page from another page must start a fresh chat: the store "
        "is plain in-memory state that outlives a route change, so without this the last "
        "conversation is silently reopened and put back in the address bar"
    )
    handler_body = handler.group(0)

    assert "startNewConversation();" in handler_body, "The handler must reset the chat"

    assert "onClick={item.to === '/chat' ? startNewChatOnArrival : undefined}" in body, (
        "Only the Chats nav item may reset the chat, and it must do so on the click "
        "rather than from an effect that a deep link would also trigger"
    )

    print("Chats navigation reset test passed!")
    return True


def test_the_reset_is_guarded_on_both_page_and_stream():
    """Neither a stray click on the active nav item nor a live reply may be destroyed."""
    print("Testing the reset guards...")

    body = _sidebar_component()
    handler = re.search(r"const startNewChatOnArrival = \(\) => \{(.|\n)*?\n    \};", body)
    assert handler, "startNewChatOnArrival should exist to be guarded"
    handler = handler.group(0)

    guard = re.search(
        r"if \(onChatPage \|\| useChatStore\.getState\(\)\.streaming\) \{\s*return;", handler
    )
    assert guard, (
        "The reset must be skipped when already on the chat page, so a stray click on the "
        "highlighted nav item cannot discard what is being read, and while a reply is "
        "streaming, because startNewConversation stops the stream and the reply is lost"
    )

    # The guard has to come before the reset, or it guards nothing.
    assert handler.index("return;") < handler.index("startNewConversation();"), (
        "The guard must return before the reset runs"
    )

    # `streaming` changes with every token it delivers, and `streamingContent` alongside it.
    # Subscribing here would re-render the rail -- the whole conversation list included --
    # throughout a response, so it is read from the store at click time instead.
    assert "useChatStore((state) => state.streaming)" not in body, (
        "streaming must be read through getState() at click time, not subscribed: it "
        "changes per token and would re-render the rail and its conversation list "
        "throughout every response"
    )

    print("Reset guard test passed!")
    return True


def test_starting_a_new_chat_closes_the_conversation_drawer():
    """The drawer's own controls disappear with the conversation, so it must go too."""
    print("Testing the drawer reset...")

    store = _read(V2_SRC / "stores" / "chatStore.ts")
    action = re.search(r"    startNewConversation: \(\) => \{(.|\n)*?\n    \},", store)
    assert action, "startNewConversation should be implemented"
    body = action.group(0)

    assert "drawerMode: null," in body, (
        "New chat must close the drawer. ChatHeader draws the Contents and Documents "
        "toggles only while a conversation is open, so an open drawer would survive with "
        "nothing to describe and no control to dismiss it from"
    )

    # The pane reads the conversation it belongs to from metadata, which is cleared in the
    # same batch. Clearing one without the other is what produced the stale-document
    # symptom in the classic interface.
    assert "metadata: null," in body, (
        "The drawer's contents come from metadata, which must be cleared with it"
    )

    page = _read(V2_SRC / "pages" / "ChatPage.tsx")
    assert "{detailsOpen && activeConversationId && (" in page, (
        "Conversation details must not outlive the conversation it describes, for the "
        "same reason: the button that opens it is drawn only while one is open"
    )

    print("Drawer reset test passed!")
    return True


def test_buttons_look_clickable():
    """Tailwind v4 dropped Preflight's pointer cursor for buttons; it is restored here."""
    print("Testing the button cursor...")

    theme = _read(V2_SRC / "styles" / "theme.css")

    rule = re.search(
        r"button:not\(:disabled\),\s*\[role='button'\]:not\(:disabled\)\s*\{\s*cursor: pointer;",
        theme,
    )
    assert rule, (
        "Tailwind v4's Preflight no longer gives buttons cursor: pointer, so without this "
        "every control in the interface renders with the arrow browsers use for inert text"
    )

    # A blanket rule would fight the disabled:cursor-not-allowed utilities the app already
    # uses, so the exclusion is not decoration.
    assert "disabled:cursor-not-allowed" in _read(
        V2_SRC / "components" / "ui" / "primitives.tsx"
    ), (
        "The :not(:disabled) exclusion exists because disabled controls declare their own "
        "cursor; if that stops being true the rule should be revisited"
    )

    base_layer = re.search(r"@layer base \{(.|\n)*?\n\}", theme)
    assert base_layer and "cursor: pointer" in base_layer.group(0), (
        "The rule belongs in the base layer so any utility class still overrides it"
    )

    print("Button cursor test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The change is present from the version that introduced it onwards."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.041")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_new_chat_is_only_offered_on_the_chat_page,
        test_reaching_chat_from_elsewhere_starts_a_new_chat,
        test_the_reset_is_guarded_on_both_page_and_stream,
        test_starting_a_new_chat_closes_the_conversation_drawer,
        test_buttons_look_clickable,
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
