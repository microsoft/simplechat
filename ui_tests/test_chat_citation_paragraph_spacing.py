# test_chat_citation_paragraph_spacing.py
"""
UI test for paragraph spacing around inline document citations.

Version: 0.250.229
Implemented in: 0.250.229

This test ensures that text following an inline citation renders as its own block
instead of being glued onto the closing parenthesis of the citation. Before the fix,
parseCitations() consumed the newlines after the trailing [#citation-id] marker, so
the next paragraph was absorbed into the preceding list item and sentences ran
together with no space after ")".

Refs: #1289
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")

CITATION_ONE = "181b54f7-fcf9-479b-a58b-81a5da3ba251_1"
CITATION_TWO = "159255fa-79d6-4619-9131-819813ae7997_1"
CITATION_THREE = "5e583e44-ea82-4569-bda8-e545bf12dca4_1"

MESSAGE_CONTENT = (
    "Simple Chat processes uploaded images as part of its document-ingestion pipeline:\n"
    "\n"
    "5. **Grounded chat:** Once processing completes, the image-derived content can be "
    "found through hybrid keyword and vector search and used to support cited answers in "
    f"chat. (Source: application_workflows.md, Page: 1) [#{CITATION_ONE}]\n"
    "\n"
    "Admins can configure the extraction approach for images and PDFs under "
    "**Admin Settings > Search & Extract**. The available modes are:\n"
    "\n"
    "- **Auto:** Samples the content and chooses the richer path when the document "
    f"structure warrants it (Source: document-intelligence.md, Page: 1) [#{CITATION_TWO}]\n"
    "\n"
    "For best results, upload clear, readable images. "
    f"(Source: uploading_documents.md, Page: 1) [#{CITATION_THREE}]\n"
    "\n"
    "Thank you, Paul."
)


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _build_message_payload():
    hybrid_citations = [
        {
            "file_name": "application_workflows.md",
            "document_id": "181b54f7-fcf9-479b-a58b-81a5da3ba251",
            "citation_id": CITATION_ONE,
            "page_number": 1,
            "chunk_id": CITATION_ONE,
        },
        {
            "file_name": "document-intelligence.md",
            "document_id": "159255fa-79d6-4619-9131-819813ae7997",
            "citation_id": CITATION_TWO,
            "page_number": 1,
            "chunk_id": CITATION_TWO,
        },
        {
            "file_name": "uploading_documents.md",
            "document_id": "5e583e44-ea82-4569-bda8-e545bf12dca4",
            "citation_id": CITATION_THREE,
            "page_number": 1,
            "chunk_id": CITATION_THREE,
        },
    ]

    return {
        "id": "assistant-citation-spacing-1",
        "conversation_id": "test-citation-spacing",
        "role": "assistant",
        "content": MESSAGE_CONTENT,
        "timestamp": "2026-08-18T15:32:45.480651",
        "augmented": True,
        "hybrid_citations": hybrid_citations,
        "web_search_citations": [],
        "agent_citations": [],
        "metadata": {},
    }


@pytest.mark.ui
def test_text_after_a_citation_renders_as_its_own_block(playwright):
    """Validate that citations do not absorb the paragraph that follows them."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    message_payload = _build_message_payload()

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        page.wait_for_selector("#chatbox")

        page.evaluate(
            """
            async (payload) => {
                currentConversationId = payload.conversation_id;
                window.currentConversationId = payload.conversation_id;

                const messagesModule = await import('/static/js/chat/chat-messages.js');
                messagesModule.appendMessage(
                    'AI',
                    payload.content,
                    null,
                    payload.id,
                    payload.augmented,
                    payload.hybrid_citations,
                    payload.web_search_citations,
                    payload.agent_citations,
                    null,
                    null,
                    payload,
                    true
                );
            }
            """,
            message_payload,
        )

        message = page.locator('.message[data-message-id="assistant-citation-spacing-1"]')
        message_text = message.locator(".message-text")
        expect(message_text).to_be_visible()

        # The three inline citations still render as clickable links.
        expect(message_text.locator("a.citation-link")).to_have_count(3)

        # The numbered list item ends at its citation and does not swallow the next paragraph.
        numbered_item = message_text.locator("ol > li")
        expect(numbered_item).to_have_count(1)
        expect(numbered_item).to_contain_text("Grounded chat:")
        assert "Admins can configure" not in numbered_item.inner_text(), \
            "The paragraph after the citation was absorbed into the numbered list item"

        # The bullet ends at its citation and does not swallow the next paragraph either.
        bullet_item = message_text.locator("ul > li")
        expect(bullet_item).to_have_count(1)
        expect(bullet_item).to_contain_text("Auto:")
        assert "For best results" not in bullet_item.inner_text(), \
            "The paragraph after the citation was absorbed into the bullet list item"

        # Each following block renders as its own paragraph.
        paragraph_texts = message_text.locator("p").all_inner_texts()
        assert any(text.startswith("Admins can configure the extraction approach") for text in paragraph_texts), \
            f"Expected a standalone paragraph starting with 'Admins can configure': {paragraph_texts}"
        assert any(text.startswith("For best results, upload clear, readable images.") for text in paragraph_texts), \
            f"Expected a standalone paragraph starting with 'For best results': {paragraph_texts}"
        assert any(text.strip() == "Thank you, Paul." for text in paragraph_texts), \
            f"Expected 'Thank you, Paul.' to render as its own paragraph: {paragraph_texts}"

        # No sentence may collide with the closing parenthesis of a citation.
        rendered_text = message_text.inner_text()
        for collapsed in (")Admins can configure", ")For best results", ")Thank you, Paul."):
            assert collapsed not in rendered_text, \
                f'Citation swallowed the whitespace before "{collapsed.lstrip(")")}"'
    finally:
        context.close()
        browser.close()
