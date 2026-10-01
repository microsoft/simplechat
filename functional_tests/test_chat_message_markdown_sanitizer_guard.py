#!/usr/bin/env python3
"""
Functional test for chat message markdown sanitizer availability guard.
Version: 0.261.047
Implemented in: 0.261.047

This test ensures chat-messages.js routes Markdown rendering through guarded
helpers so a missing DOMPurify or marked global cannot break message sending.
"""

from pathlib import Path

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_MESSAGES_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"


def assert_contains(source, expected, label):
    if expected not in source:
        raise AssertionError(f"Expected {label}: {expected}")


def assert_not_contains(source, unexpected, label):
    if unexpected in source:
        raise AssertionError(f"Unexpected unguarded {label}: {unexpected}")


def test_chat_message_markdown_sanitizer_guard():
    """Validate guarded Markdown rendering helpers are used in chat messages."""
    assert_app_version_at_least("0.261.047", REPO_ROOT)

    source = CHAT_MESSAGES_JS.read_text(encoding="utf-8")

    assert_contains(source, "function getMarkdownRenderer()", "markdown renderer availability helper")
    assert_contains(source, "function renderMarkdownSafely(markdownText, options = {})", "safe markdown render helper")
    assert_contains(source, "function sanitizeHtmlSafely(htmlText)", "safe html sanitizer helper")
    assert_contains(source, "return escapeHtml(text);", "escaped markdown fallback")
    assert_contains(source, "return escapeHtml(html);", "escaped html fallback")
    assert_not_contains(source, "DOMPurify.sanitize(", "DOMPurify call")
    assert_not_contains(source, "marked.parse(", "marked parse call")

    print("✅ Chat message markdown sanitizer guard verified")
    return True


if __name__ == "__main__":
    success = test_chat_message_markdown_sanitizer_guard()
    raise SystemExit(0 if success else 1)