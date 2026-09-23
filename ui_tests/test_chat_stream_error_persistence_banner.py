# test_chat_stream_error_persistence_banner.py
"""
UI test for the classic chat stream error banner's saved-content wording.
Version: 0.261.129
Implemented in: 0.261.129

This test runs the real classic chat streaming helpers in Chromium and ensures
the stream error banner says partial content was saved only when the server
confirms a persisted assistant reply. Before this fix the banner always said
the partial content was saved, even when nothing reached the conversation.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_STREAMING_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-streaming.js"
SAVED = "The partial content above has been saved."
NOT_SAVED = "The partial content above was not saved and will not appear after a reload."
PAGE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Stream error banner</title>
</head>
<body>
    <main id="content"></main>
    <div data-message-id="temp-ai"><div class="message-text"><span class="streaming-cursor"></span></div></div>
</body>
</html>
""".strip()
# Stand-ins for the chat modules handleStreamError calls after rendering.
PAGE_DEPENDENCIES = """
window.toasts = [];
function removeStreamingStopButton() {}
function hydrateInlineCharts() {}
function hydrateInlineDiagrams() {}
function showToast(message, variant) { window.toasts.push([message, variant]); }
"""


def load_stream_error_helpers(page):
    source = CHAT_STREAMING_JS.read_text(encoding="utf-8")
    banner = source[source.index("function normalizeStreamHttpUrl("):source.index("function reportClientStreamEvent(")]
    handler = source[source.index("function handleStreamError("):source.index("function finalizeStreamingMessage(")]
    page.set_content(PAGE)
    page.add_script_tag(content=PAGE_DEPENDENCIES)
    page.add_script_tag(content=banner + handler)


@pytest.mark.ui
@pytest.mark.parametrize("payload,has_partial_content,expected,unexpected", [
    ({"message_persisted": True, "message_id": "assistant-1"}, True, f"Response may be incomplete. {SAVED}", "not saved"),
    ({"message_persisted": False}, True, f"Response may be incomplete. {NOT_SAVED}", "has been saved"),
    ({"message_persisted": True, "user_message_id": "user-1"}, True, NOT_SAVED, "has been saved"),
    ({}, False, "Response may be incomplete.", "saved"),
    ({"rate_limited": True, "message_persisted": False}, True, f"Wait a moment before sending the message again. {NOT_SAVED}", "has been saved"),
    ({"rate_limited": True, "message_persisted": True, "message_id": "assistant-1"}, True, SAVED, "not saved"),
    ({"rate_limited": True}, False, "Wait a moment before sending the message again.", "saved"),
    (
        {"type": "m365_approval_required", "message_persisted": True, "user_message_id": "user-1"},
        True, "The request continues after the approval is decided.", "saved",
    ),
])
def test_stream_error_banner_reports_whether_partial_content_was_saved(
    page, payload, has_partial_content, expected, unexpected,
):
    """The banner's saved-content claim follows the server's persisted reply."""
    load_stream_error_helpers(page)
    page.evaluate(
        "([payload, hasPartialContent]) => appendStreamErrorBanner("
        "document.getElementById('content'), 'Something went wrong.', payload, hasPartialContent)",
        [payload, has_partial_content],
    )

    banner = page.locator("#content .alert")
    expect(banner).to_have_count(1)
    expect(banner).to_contain_text(expected)
    expect(banner).not_to_contain_text(unexpected)


@pytest.mark.ui
@pytest.mark.parametrize("payload,partial_content,expected", [
    ({"error": "Something went wrong.", "message_persisted": False}, "Partial answer", NOT_SAVED),
    (
        {"error": "Something went wrong.", "message_persisted": True, "message_id": "assistant-1"},
        "Partial answer", SAVED,
    ),
    ({"error": "Something went wrong.", "message_persisted": False}, "", "Response may be incomplete."),
])
def test_stream_error_handler_keeps_visible_partial_content_and_honest_banner(page, payload, partial_content, expected):
    """A failed stream keeps the visible answer and says whether it was saved."""
    load_stream_error_helpers(page)
    page.evaluate(
        "([payload, partialContent]) => handleStreamError('temp-ai', partialContent, payload.error, payload)",
        [payload, partial_content],
    )

    message = page.locator("[data-message-id='temp-ai'] .message-text")
    banner = message.locator(".alert")
    expect(message).to_contain_text(partial_content or "Stream interrupted before any content was received.")
    expect(message.locator(".streaming-cursor")).to_have_count(0)
    expect(banner).to_contain_text("Stream interrupted:")
    expect(banner).to_contain_text(expected)
    if not partial_content:
        expect(banner).not_to_contain_text("saved")
    toasts = page.evaluate("window.toasts")
    assert toasts == [["Stream error: Something went wrong.", "error"]]
