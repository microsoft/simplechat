#!/usr/bin/env python3
# test_chat_new_conversation_documents_drawer_reset.py
"""
Functional test for the New chat reset of the conversation Documents side pane.
Version: 0.260.004
Implemented in: 0.260.004

This test ensures that clicking New chat clears the conversation side drawer's
Documents pane instead of re-rendering the previous conversation's documents,
so the pane empties out and closes just like the Contents pane.

Refs: https://github.com/microsoft/simplechat/issues/1298
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(ROOT_DIR, "application", "single_app")

CONVERSATION_CONTENTS_JS = os.path.join(
    APP_ROOT, "static", "js", "chat", "chat-conversation-contents.js"
)
CONVERSATIONS_JS = os.path.join(APP_ROOT, "static", "js", "chat", "chat-conversations.js")
CHATS_TEMPLATE_FILE = os.path.join(APP_ROOT, "templates", "chats.html")


def read_file(path):
    """Read a source file as UTF-8 text."""
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_new_conversation_dispatches_context_reset_without_id():
    """Verify New chat still signals a context reset with no conversation id."""
    print("Testing New chat context reset dispatch...")
    source = read_file(CONVERSATIONS_JS)

    required_snippets = [
        'window.dispatchEvent(new CustomEvent("chat:conversation-context-changed", {',
        'notifyConversationContextChanged("new", null, { preserveSelections });',
        'notifyConversationContextChanged("select", conversationId);',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing new-conversation reset dispatch snippets: {missing}"

    print("New chat context reset dispatch verified.")
    return True


def test_documents_refresh_supports_fallback_opt_out():
    """Verify refreshConversationDocuments can require an explicit conversation id."""
    print("Testing conversation documents fallback opt-out...")
    source = read_file(CONVERSATION_CONTENTS_JS)

    required_snippets = [
        'const requestedConversationId = String(options.conversationId || "").trim();',
        "const allowCurrentConversationFallback = options.allowCurrentConversationFallback !== false;",
        "const conversationId = requestedConversationId",
        '|| (allowCurrentConversationFallback ? getCurrentConversationId() : "");',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing fallback opt-out snippets: {missing}"

    assert (
        "String(options.conversationId || getCurrentConversationId()).trim()" not in source
    ), (
        "refreshConversationDocuments must not silently fall back to the current "
        "conversation when an explicit reset supplies an empty conversation id."
    )

    print("Conversation documents fallback opt-out verified.")
    return True


def test_context_change_listener_resets_documents_pane():
    """Verify the context-changed listener opts out of the current-conversation fallback."""
    print("Testing context-changed listener reset wiring...")
    source = read_file(CONVERSATION_CONTENTS_JS)

    listener_start = source.find('window.addEventListener("chat:conversation-context-changed"')
    assert listener_start != -1, "chat:conversation-context-changed listener not found."

    listener_end = source.find('window.addEventListener("chat:conversation-documents-refresh"')
    assert listener_end > listener_start, (
        "chat:conversation-documents-refresh listener should follow the context-changed listener."
    )

    listener_source = source[listener_start:listener_end]
    required_snippets = [
        'conversationId: detail.conversationId || "",',
        "allowCurrentConversationFallback: false,",
        "autoOpen: false,",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in listener_source]
    assert not missing, f"Missing context-changed listener snippets: {missing}"

    print("Context-changed listener reset wiring verified.")
    return True


def test_documents_refresh_path_still_uses_current_conversation():
    """Verify targeted document refreshes keep resolving the active conversation."""
    print("Testing document refresh fallback retention...")
    source = read_file(CONVERSATION_CONTENTS_JS)

    required_snippets = [
        'const conversationId = String(event.detail?.conversationId || getCurrentConversationId()).trim();',
        "if (!conversationId || conversationId !== getCurrentConversationId()) {",
        "void refreshConversationDocuments();",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing document refresh fallback snippets: {missing}"

    print("Document refresh fallback retention verified.")
    return True


def test_empty_conversation_clears_documents_and_closes_drawer():
    """Verify the empty-id path clears document state and lets the drawer close."""
    print("Testing empty conversation reset behavior...")
    source = read_file(CONVERSATION_CONTENTS_JS)

    required_snippets = [
        "if (!conversationId) {",
        'documentLoadState = "idle";',
        "documentUsageTrackingAvailable = false;",
        "exactDocumentUsageAvailable = false;",
        "legacyDocumentFallbackAvailable = false;",
        "renderConversationDocuments([]);",
        "documentEntries = documents.map(createDocumentEntry);",
        "if (!hasContents && !hasDocuments) {",
        "closeDrawer({ restoreFocus: false });",
        'documentsCountBadge.classList.toggle("d-none", !hasDocuments);',
        'documentsToggleButton.classList.toggle("d-none", !hasDocuments);',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing empty conversation reset snippets: {missing}"

    print("Empty conversation reset behavior verified.")
    return True


def test_drawer_markup_supports_documents_reset_surfaces():
    """Verify the drawer markup still exposes the elements the reset updates."""
    print("Testing conversation drawer markup...")
    source = read_file(CHATS_TEMPLATE_FILE)

    required_snippets = [
        'id="conversation-documents-toggle"',
        'id="conversation-documents-count"',
        'id="conversation-documents-list"',
        'id="conversation-documents-empty"',
        'id="conversation-contents-drawer"',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f"Missing conversation drawer markup snippets: {missing}"

    print("Conversation drawer markup verified.")
    return True


def test_config_version_updated():
    """Verify config.py reflects the documents drawer reset implementation version."""
    print("Testing config.py version update...")
    assert_app_version_at_least("0.260.004")
    print("Config version update verified.")
    return True


def main():
    """Run all regression checks."""
    tests = [
        test_new_conversation_dispatches_context_reset_without_id,
        test_documents_refresh_supports_fallback_opt_out,
        test_context_change_listener_resets_documents_pane,
        test_documents_refresh_path_still_uses_current_conversation,
        test_empty_conversation_clears_documents_and_closes_drawer,
        test_drawer_markup_supports_documents_reset_surfaces,
        test_config_version_updated,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(1 for result in results if result)}/{len(results)} tests passed")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
