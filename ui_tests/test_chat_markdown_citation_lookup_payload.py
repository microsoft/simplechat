# test_chat_markdown_citation_lookup_payload.py
"""
UI test for markdown citation lookup payloads.

Version: 0.241.021
Implemented in: 0.241.021

This test ensures markdown citation buttons send document, page, and chunk
context to `/api/get_citation` so text citation lookup can recover when the
rendered citation id is incomplete or stale.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


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


@pytest.mark.ui
def test_markdown_citation_button_sends_lookup_context(playwright):
    """Validate markdown citation buttons send context-rich lookup payloads."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    captured_payload = {}

    def handle_get_citation(route):
        raw_body = route.request.post_data or "{}"
        captured_payload["value"] = json.loads(raw_body)
        _fulfill_json(
            route,
            {
                "cited_text": "# Markdown citation\nRecovered chunk text.",
                "file_name": "release-notes.md",
                "page_number": 2,
            },
        )

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))
    page.route("**/api/get_citation", handle_get_citation)

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        page.wait_for_selector("#chatbox")

        page.evaluate(
            """
            async () => {
                window.enableEnhancedCitations = false;
                currentConversationId = 'test-convo';
                window.currentConversationId = 'test-convo';

                const messagesModule = await import('/static/js/chat/chat-messages.js');
                messagesModule.appendMessage(
                    'AI',
                    'Markdown answer with a source.',
                    null,
                    'assistant-md-1',
                    true,
                    [
                        {
                            file_name: 'release-notes.md',
                            document_id: 'doc-md-123',
                            chunk_id: '2',
                            page_number: 2,
                            chunk_sequence: 2,
                            score: 0.91,
                        },
                    ],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'assistant-md-1',
                        role: 'assistant',
                        content: 'Markdown answer with a source.',
                    },
                    true
                );
            }
            """
        )

        message = page.locator('.message[data-message-id="assistant-md-1"]')
        citation_toggle = message.locator('.citation-toggle-btn')
        expect(citation_toggle).to_be_visible()
        citation_toggle.click()

        citation_button = message.locator('a.hybrid-citation-link').first
        expect(citation_button).to_be_visible()

        with page.expect_response("**/api/get_citation"):
            citation_button.click()

        assert captured_payload["value"] == {
            "citation_id": "doc-md-123_2",
            "document_id": "doc-md-123",
            "page_number": "2",
            "chunk_id": "2",
        }

        citation_modal = page.locator("#citation-modal")
        expect(citation_modal).to_be_visible()
        expect(citation_modal.locator(".modal-title")).to_have_text("Source: release-notes.md, Page: 2")
    finally:
        context.close()
        browser.close()