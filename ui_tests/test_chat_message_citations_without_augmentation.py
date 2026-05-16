# test_chat_message_citations_without_augmentation.py
"""
UI test for assistant citations without augmentation.
Version: 0.241.122
Implemented in: 0.241.122

This test ensures assistant messages still surface stored citations in the
message footer and metadata drawer when citation arrays are present but the
message itself is marked as not augmented.
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


def _build_review_message_payload():
    hybrid_citations = [
        {
            "file_name": "Coverage",
            "citation_id": "document_action_coverage",
            "page_number": "Metadata",
            "chunk_id": "document_action_coverage",
            "chunk_sequence": 20000,
            "score": 0,
            "metadata_type": "document_analysis_coverage",
            "metadata_content": "Coverage\nDocuments reviewed: 7\nProcessed windows: 10",
            "location_label": "Coverage",
            "location_value": "Overall summary",
        },
        {
            "file_name": "6 Hour Shenandoah River Race Maps 2025.pdf",
            "document_id": "663babf8-a384-44e4-b079-a2d8355329ad",
            "citation_id": "663babf8-a384-44e4-b079-a2d8355329ad_coverage",
            "page_number": "Metadata",
            "chunk_id": "663babf8-a384-44e4-b079-a2d8355329ad_coverage",
            "chunk_sequence": 9999,
            "score": 0,
            "metadata_type": "document_analysis_summary",
            "metadata_content": "Status: Completed\nWindows reviewed: 1/1\nChunks completed: 2/2",
            "location_label": "Coverage",
            "location_value": "Document summary",
        },
    ]

    return {
        "id": "assistant-review-1",
        "conversation_id": "test-convo",
        "role": "assistant",
        "content": "Review output with citations",
        "timestamp": "2026-05-02T15:32:45.480651",
        "augmented": False,
        "hybrid_citations": hybrid_citations,
        "web_search_citations": [],
        "agent_citations": [],
        "metadata": {
            "reasoning_effort": "low",
        },
    }


@pytest.mark.ui
def test_chat_message_citations_render_when_augmented_is_false(playwright):
    """Validate stored citations render for non-augmented assistant review messages."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    message_payload = _build_review_message_payload()

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))
    page.route(
        "**/api/message/assistant-review-1/metadata",
        lambda route: _fulfill_json(route, message_payload),
    )
    page.route(
        "**/api/enhanced_citations/document_metadata?doc_id=663babf8-a384-44e4-b079-a2d8355329ad",
        lambda route: _fulfill_json(
            route,
            {
                "id": "663babf8-a384-44e4-b079-a2d8355329ad",
                "document_id": "663babf8-a384-44e4-b079-a2d8355329ad",
                "file_name": "6 Hour Shenandoah River Race Maps 2025.pdf",
                "enhanced_citations": True,
            },
        ),
    )
    page.route(
        "**/api/enhanced_citations/pdf?doc_id=663babf8-a384-44e4-b079-a2d8355329ad**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/pdf",
            body=(
                b"%PDF-1.4\n"
                b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
                b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
                b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
                b"trailer<</Root 1 0 R>>\n%%EOF"
            ),
        ),
    )

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        page.wait_for_selector("#chatbox")

        page.evaluate(
            """
            async (payload) => {
                window.enableEnhancedCitations = true;
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

        message = page.locator('.message[data-message-id="assistant-review-1"]')
        citation_toggle = message.locator('.citation-toggle-btn')
        expect(citation_toggle).to_be_visible()

        citation_toggle.click()
        inline_citations = message.locator('#citations-assistant-review-1 a.hybrid-citation-link')
        expect(inline_citations).to_have_count(3)
        expect(inline_citations.filter(has_text='Coverage, Coverage: Overall summary')).to_be_visible()

        source_file_citation = inline_citations.filter(has_text='6 Hour Shenandoah River Race Maps 2025.pdf')
        expect(source_file_citation).to_be_visible()

        metadata_summary_citation = inline_citations.filter(has_text='Coverage: Document summary')
        expect(metadata_summary_citation).to_be_visible()

        source_file_citation.click()
        pdf_modal = page.locator('#pdfModal')
        expect(pdf_modal).to_be_visible()
        expect(pdf_modal.locator('#pdfModalTitle')).to_contain_text('PDF Document - Page 1')

        pdf_modal.locator('.btn-close').click()

        metadata_summary_citation.click()
        metadata_modal = page.locator('#metadata-modal')
        expect(metadata_modal).to_be_visible()
        expect(metadata_modal.locator('#metadata-file-name')).to_have_text('6 Hour Shenandoah River Race Maps 2025.pdf')
        expect(metadata_modal.locator('#metadata-open-source-btn')).to_be_visible()

        metadata_modal.locator('.btn-close').click()

        metadata_button = message.locator('.metadata-info-btn')
        with page.expect_response('**/api/message/assistant-review-1/metadata'):
            metadata_button.click()

        metadata_drawer = message.locator('.message-metadata-drawer')
        expect(metadata_drawer).to_be_visible()
        expect(metadata_drawer).to_contain_text('Citations')
        expect(metadata_drawer).to_contain_text('Documents 3')
        expect(metadata_drawer.locator('a.hybrid-citation-link')).to_have_count(3)
    finally:
        context.close()
        browser.close()