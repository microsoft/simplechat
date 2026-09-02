#!/usr/bin/env python3
"""
Functional test for conversation deep linking in the V2 interface.

Version: 0.261.028
Implemented in: 0.261.028

The classic interface has supported linking straight to a conversation since v0.237.001:
chat-onload.js reads ?conversationId= (or the older ?conversation_id=) on load, and
chat-conversations.js writes the open conversation back into the address bar. The V2 SPA
had none of it -- it never read a query parameter and never wrote one -- so a link such as
/chats?conversationId=<id> had no V2 equivalent, copying the address bar shared nothing,
and a refresh dropped the reader into an empty chat.

This test ensures the V2 interface reads a linked conversation, keeps the URL describing
whatever is open, survives the two ways this is easy to get wrong -- effect ordering
silently discarding the incoming link, and a dead link stranding itself in the URL so every
refresh reproduces it -- and hands the conversation over when crossing back to classic.
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


def test_both_parameter_spellings_are_read():
    """A link built by any part of the server opens, not just the camel-cased half."""
    print("Testing parameter spellings...")

    module = V2_SRC / "lib" / "conversationUrl.ts"
    assert module.exists(), "conversationUrl.ts should hold the URL rules"
    source = _read(module)

    assert "export const CONVERSATION_PARAM = 'conversationId'" in source, (
        "The canonical parameter must match what the classic interface writes"
    )
    assert "export const LEGACY_CONVERSATION_PARAM = 'conversation_id'" in source, (
        "The underscore spelling is emitted by route_frontend_chats.py and "
        "functions_documents.py and must still open a conversation"
    )

    # Both are consulted on read, canonical first so normalising a legacy link can never
    # change which conversation it opens.
    assert re.search(
        r"params\.get\(CONVERSATION_PARAM\)\s*\?\?\s*params\.get\(LEGACY_CONVERSATION_PARAM\)",
        source,
    ), "Reading must accept the canonical spelling first, then the legacy one"

    print("Parameter spelling test passed!")
    return True


def test_only_the_canonical_spelling_is_written():
    """An incoming legacy link is normalised rather than propagated."""
    print("Testing parameter normalisation...")

    source = _read(V2_SRC / "lib" / "conversationUrl.ts")

    synced = re.search(
        r"export function syncedConversationParams\((.|\n)*?\n}", source
    )
    assert synced, "syncedConversationParams should exist"
    body = synced.group(0)

    assert "next.delete(LEGACY_CONVERSATION_PARAM)" in body, (
        "Writing must drop the legacy spelling so a URL never carries both"
    )
    assert "next.set(CONVERSATION_PARAM, conversationId)" in body, (
        "Only the canonical spelling may be written"
    )
    assert "next.delete(CONVERSATION_PARAM)" in body, (
        "Closing a conversation must remove the parameter, not leave a stale id behind"
    )

    # Returning null when nothing needs to change is what stops the effect that writes the
    # URL from re-entering itself.
    assert "return null" in body, (
        "The helper must report 'no change needed' so the sync effect cannot loop"
    )
    assert "hasLegacy" in body, (
        "A legacy parameter must count as a difference, otherwise it is never normalised"
    )

    print("Parameter normalisation test passed!")
    return True


def test_incoming_link_is_captured_before_any_effect_runs():
    """The ordering bug this design exists to avoid."""
    print("Testing incoming link capture...")

    source = _read(V2_SRC / "pages" / "ChatPage.tsx")

    assert "useConversationUrlSync" in source, "The chat page must sync its URL"
    assert "useConversationUrlSync();" in source, (
        "The hook must actually be called from the page, not merely defined"
    )

    # A lazy useState initialiser runs during the first render. Reading the parameter inside
    # an effect instead would race the effect that writes the URL, which also runs on mount
    # and would strip the parameter before it was ever read.
    assert re.search(
        r"const \[linkedConversationId\] = useState\(\(\) => readConversationParam\(searchParams\)\)",
        source,
    ), "The linked id must be captured in a lazy initialiser, not inside an effect"

    hook = re.search(r"function useConversationUrlSync\(\)(.|\n)*?\n}", source)
    assert hook, "The sync hook should exist"
    hook_body = hook.group(0)

    # Consumed once. Without the guard, returning to the chat page would re-open the
    # conversation and discard a running stream.
    assert "linkHandled" in hook_body, "The link must be consumed exactly once"
    assert "if (!linkHandled) {" in hook_body, (
        "The write must wait for the read, or the parameter is cleared before it is used"
    )
    assert "useChatStore.getState().activeConversationId" in hook_body, (
        "The already-open conversation must not be re-opened"
    )

    # A ref, not a state flag: StrictMode invokes mount effects twice and the second
    # invocation still sees the first render's state, so a state flag alone would open the
    # conversation -- and refetch its messages -- twice in development.
    assert "const linkConsumed = useRef(false);" in hook_body, (
        "Opening the link must be guarded by a ref so it happens exactly once"
    )
    assert "if (linkConsumed.current || !linkedConversationId) {" in hook_body, (
        "The ref must be checked before the link is opened"
    )
    assert "linkConsumed.current = true;" in hook_body, (
        "The ref must be marked before the open, not after it"
    )

    # The write must not be released until the open has settled. Releasing it up front lets
    # the write effect run while the conversation is still being fetched, see nothing open,
    # and strip the parameter that named it.
    assert re.search(
        r"openLinkedConversation\(linkedConversationId\)\.finally\(\(\) => setLinkHandled\(true\)\)",
        hook_body,
    ), "The write gate must be released only once the open has settled, either way"

    print("Incoming link capture test passed!")
    return True


def test_url_follows_the_open_conversation_without_growing_history():
    """The address bar describes what is open; the back button is not a visit log."""
    print("Testing URL synchronisation...")

    source = _read(V2_SRC / "pages" / "ChatPage.tsx")

    assert "syncedConversationParams(searchParams, activeConversationId)" in source, (
        "The URL must be derived from the open conversation"
    )
    assert "setSearchParams(next, { replace: true })" in source, (
        "The write must replace, matching the classic interface's history.replaceState"
    )

    hook = re.search(r"function useConversationUrlSync\(\)(.|\n)*?\n}", source).group(0)
    assert "if (!next) {" in hook, (
        "A no-op must be skipped rather than navigating to the URL already shown"
    )

    print("URL synchronisation test passed!")
    return True


def test_a_dead_link_is_reported_and_does_not_strand_itself():
    """A deleted or forbidden conversation must not reproduce on every refresh."""
    print("Testing dead link handling...")

    source = _read(V2_SRC / "stores" / "chatStore.ts")

    assert "openLinkedConversation: (conversationId: string) => Promise<void>;" in source, (
        "Opening from a link must be a distinct action from selecting a rail row"
    )

    action = re.search(
        r"openLinkedConversation: async \(conversationId\) => \{(.|\n)*?\n    \},", source
    )
    assert action, "openLinkedConversation should be implemented"
    body = action.group(0)

    # /api/get_messages is not an existence check: route_backend_conversations.py catches the
    # not-found LookupError and answers `{'messages': []}` with a 200. Relying on it would
    # open a deleted conversation as an empty chat, leave its id in the URL, and leave it as
    # the target of the next message sent. The metadata endpoint 404s and 403s instead.
    existence_check = body.index("await fetchConversationMetadata(conversationId)")
    select = body.index("await get().selectConversation(conversationId)")
    assert existence_check < select, (
        "The conversation must be shown to exist before it is opened, because "
        "/api/get_messages answers 200 with an empty list when it does not"
    )

    assert "toast.error(" in body, "An unopenable link must say so rather than look dead"
    assert "get().messagesError" in body, (
        "A conversation that exists but whose messages fail to load must still be reported"
    )
    assert "get().startNewConversation()" in body, (
        "Falling back to an empty chat is what clears the failing parameter from the URL"
    )

    print("Dead link handling test passed!")
    return True


def test_a_linked_conversation_outside_the_loaded_feed_still_gets_a_row():
    """Older than the first page, or hidden: the rail and header must still be honest."""
    print("Testing conversation list backfill...")

    source = _read(V2_SRC / "stores" / "chatStore.ts")

    assert "function conversationFromMetadata(" in source, (
        "A list row must be derivable from a metadata response"
    )
    # Metadata keys the conversation as conversation_id and the feed as id, so the row is
    # built from the id it was fetched for to guarantee the rail can match it.
    assert re.search(
        r"function conversationFromMetadata\(\s*conversationId: string,\s*metadata: ConversationMetadata,\s*\): Conversation",
        source,
    ), "The row must be built against the requested id, not a field of the response"

    load_metadata = re.search(r"loadMetadata: async \(conversationId\) => \{(.|\n)*?\n    \},", source)
    assert load_metadata, "loadMetadata should exist"
    body = load_metadata.group(0)

    # The backfill must sit behind the existing in-flight guard, otherwise a response
    # arriving after the user moved on would re-add a row for a conversation they left --
    # including one they just deleted.
    guard = body.index("if (get().activeConversationId !== conversationId)")
    backfill = body.index("conversationFromMetadata(conversationId, metadata)")
    assert guard < backfill, (
        "The backfill must run after the stale-response guard, not before it"
    )

    assert "state.conversations.some((item) => item.id === conversationId)" in body, (
        "A conversation already in the list must not be duplicated"
    )

    print("Conversation list backfill test passed!")
    return True


def test_crossing_back_to_classic_carries_the_conversation():
    """Both interfaces read the same parameter, so the handover should keep your place."""
    print("Testing the classic interface link...")

    helpers = _read(V2_SRC / "lib" / "conversationUrl.ts")
    assert "export function classicChatHref(" in helpers, (
        "The classic link must be built in one place"
    )
    assert "encodeURIComponent(conversationId)" in helpers, (
        "The id must be encoded into the query string"
    )

    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    assert "href={classicChatHref(activeConversationId)}" in sidebar, (
        "Back to classic UI must carry the open conversation"
    )
    assert 'href="/chats"' not in sidebar, (
        "The bare link would drop the conversation the reader was in"
    )

    print("Classic interface link test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The change is present from the version that introduced it onwards."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.028")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_both_parameter_spellings_are_read,
        test_only_the_canonical_spelling_is_written,
        test_incoming_link_is_captured_before_any_effect_runs,
        test_url_follows_the_open_conversation_without_growing_history,
        test_a_dead_link_is_reported_and_does_not_strand_itself,
        test_a_linked_conversation_outside_the_loaded_feed_still_gets_a_row,
        test_crossing_back_to_classic_carries_the_conversation,
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
