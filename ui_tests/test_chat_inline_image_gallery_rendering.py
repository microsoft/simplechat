# test_chat_inline_image_gallery_rendering.py
"""
UI test for inline image gallery rendering in chat.
Version: 0.241.066
Implemented in: 0.241.056

This test ensures assistant messages can hydrate inline image gallery agent
citations, render up to five framed images inside the chat bubble, and expose
an overlay info button that opens a detail modal for each image.
"""

import base64
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}
TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF9sAAAAASUVORK5CYII="
)
TINY_PNG_BYTES = base64.b64decode(TINY_PNG_BASE64)


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _build_full_image_gallery_citation():
    return {
        "tool_name": "Image gallery: Incident Photos",
        "function_name": "collect_images",
        "plugin_name": "ExternalMediaPlugin",
        "function_arguments": json.dumps({"title": "Incident Photos"}),
        "function_result": json.dumps(
            {
                "success": True,
                "render_type": "inline_image_gallery",
                "summary": "Prepared an inline image gallery with 2 images.",
                "image_gallery": {
                    "title": "Incident Photos",
                    "summary": "Key visuals gathered from the workspace and an external feed.",
                    "source_action_name": "media_collector",
                    "items": [
                        {
                            "title": "Loading Dock Camera",
                            "description": "Still image captured from the facility entrance camera.",
                            "image_url": f"data:image/png;base64,{TINY_PNG_BASE64}",
                            "source_label": "External image (api.example.com)",
                            "source_url": "https://api.example.com/images/loading-dock.png",
                        },
                        {
                            "title": "Workspace Photo Evidence",
                            "description": "Image stored in the workspace document library.",
                            "doc_id": "workspace-image-001",
                            "file_name": "workspace-photo.png",
                        },
                    ],
                },
            }
        ),
        "artifact_id": "assistant-msg-images-1_artifact_1",
    }


@pytest.mark.ui
def test_chat_inline_image_gallery_rendering(playwright):
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    compact_citation = {
        "tool_name": "Image gallery: Incident Photos",
        "function_name": "collect_images",
        "plugin_name": "ExternalMediaPlugin",
        "function_arguments": {"title": "Incident Photos"},
        "function_result": {
            "success": True,
            "render_type": "inline_image_gallery",
            "summary": "Prepared an inline image gallery.",
            "image_gallery": {
                "title": "Incident Photos",
                "summary": "Compacted gallery preview.",
                "items": ["<dict with 6 keys>", "<dict with 4 keys>"],
                "total_count": 2,
                "source_action_name": "media_collector",
            },
        },
        "artifact_id": "assistant-msg-images-1_artifact_1",
        "raw_payload_externalized": True,
    }

    page.route(
        "**/api/user/settings",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"selected_agent": None, "settings": {"enable_agents": False}}),
        ),
    )
    page.route(
        "**/api/get_conversations",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"conversations": []})),
    )
    page.route(
        "**/api/conversation/test-convo/agent-citation/assistant-msg-images-1_artifact_1",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"citation": _build_full_image_gallery_citation()}),
        ),
    )
    page.route(
        "**/api/enhanced_citations/image?doc_id=workspace-image-001",
        lambda route: route.fulfill(status=200, content_type="image/png", body=TINY_PNG_BYTES),
    )

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /chats."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Chat page unavailable in this environment (HTTP {response.status}).")

        if "login" in page.url.lower():
            pytest.skip("Inline image gallery UI test requires an authenticated chat session.")

        page.wait_for_selector("#chatbox")

        with page.expect_response("**/api/conversation/test-convo/agent-citation/assistant-msg-images-1_artifact_1"):
            page.evaluate(
                """
                async ({ agentCitation, hybridCitation }) => {
                    currentConversationId = 'test-convo';
                    window.currentConversationId = 'test-convo';
                    const messagesModule = await import('/static/js/chat/chat-messages.js');
                    messagesModule.appendMessage(
                        'AI',
                        'Incident image results',
                        null,
                        'assistant-msg-images-1',
                        true,
                        [hybridCitation],
                        [],
                        [agentCitation],
                        null,
                        null,
                        {
                            id: 'assistant-msg-images-1',
                            role: 'assistant',
                            content: 'Incident image results',
                            conversation_id: 'test-convo',
                            hybrid_citations: [hybridCitation],
                            agent_citations: [agentCitation],
                        },
                        true
                    );
                }
                """,
                {
                    "agentCitation": compact_citation,
                    "hybridCitation": {
                        "file_name": "workspace-photo.png",
                        "citation_id": "workspace-image-001_1",
                        "page_number": 1,
                    },
                },
            )

        message_scope = page.locator('[data-message-id="assistant-msg-images-1"]')
        gallery_cards = message_scope.locator('.inline-image-gallery-card')
        expect(gallery_cards).to_have_count(2)
        expect(gallery_cards.first).to_be_visible()
        expect(gallery_cards.nth(0).locator('.inline-image-gallery-title')).to_have_text('Workspace images')
        expect(gallery_cards.nth(0).locator('.inline-image-gallery-item-title')).to_have_text('workspace-photo.png')
        expect(gallery_cards.nth(0).locator('.inline-image-gallery-badges')).to_contain_text('Images: 1')
        expect(gallery_cards.nth(1).locator('.inline-image-gallery-title')).to_have_text('Incident Photos')
        expect(gallery_cards.nth(1).locator('.inline-image-gallery-summary')).to_contain_text('Key visuals gathered from the workspace and an external feed.')
        expect(gallery_cards.nth(1).locator('.inline-image-gallery-badges')).to_contain_text('Images: 1')
        expect(gallery_cards.nth(1).locator('.inline-image-gallery-footer')).to_contain_text('media_collector')
        expect(message_scope.locator('.inline-image-gallery-item')).to_have_count(2)
        expect(message_scope.locator('.inline-image-gallery-info-btn')).to_have_count(2)
        expect(message_scope.locator('a.agent-citation-link')).to_have_count(1)

        message_scope.locator('.inline-image-gallery-info-btn').nth(1).click()
        details_modal = page.locator('#inline-image-details-modal')
        expect(details_modal).to_be_visible()
        expect(details_modal.locator('#inline-image-details-title')).to_have_text('Loading Dock Camera')
        expect(details_modal.locator('#inline-image-details-description')).to_contain_text('facility entrance camera')
        expect(details_modal.locator('#inline-image-details-meta')).to_contain_text('External image (api.example.com)')

        page.locator('[data-message-id="assistant-msg-images-1"] .inline-image-gallery-item-image').nth(1).click()
        expect(page.locator('#image-modal')).to_be_visible()
        expect(page.locator('#image-modal img')).to_be_visible()
    finally:
        context.close()
        browser.close()