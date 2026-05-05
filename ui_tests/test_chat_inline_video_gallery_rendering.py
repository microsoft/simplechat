# test_chat_inline_video_gallery_rendering.py
"""
UI test for inline video gallery rendering in chat.
Version: 0.241.066
Implemented in: 0.241.066

This test ensures assistant messages can hydrate inline video gallery agent
citations, render compact inline videos inside the chat bubble, and expose an
overlay info button that opens a detail modal for each video.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}
DUMMY_VIDEO_BYTES = b"not-a-real-video-stream"


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _build_full_video_gallery_citation():
    return {
        "tool_name": "Video gallery: Incident Clips",
        "function_name": "collect_videos",
        "plugin_name": "ExternalMediaPlugin",
        "function_arguments": json.dumps({"title": "Incident Clips"}),
        "function_result": json.dumps(
            {
                "success": True,
                "render_type": "inline_video_gallery",
                "summary": "Prepared an inline video gallery with 2 clips.",
                "video_gallery": {
                    "title": "Incident Clips",
                    "summary": "Relevant clips gathered from the workspace and an external feed.",
                    "source_action_name": "media_collector",
                    "items": [
                        {
                            "title": "Loading Dock Camera",
                            "description": "Short security clip captured from the loading dock camera.",
                            "video_url": "https://api.example.com/videos/loading-dock.mp4",
                            "source_label": "External video (api.example.com)",
                            "source_url": "https://api.example.com/videos/loading-dock.mp4",
                        },
                        {
                            "title": "Workspace Clip Evidence",
                            "description": "Video stored in the workspace document library.",
                            "doc_id": "workspace-video-001",
                            "file_name": "workspace-evidence.mp4",
                        },
                    ],
                },
            }
        ),
        "artifact_id": "assistant-msg-videos-1_artifact_1",
    }


@pytest.mark.ui
def test_chat_inline_video_gallery_rendering(playwright):
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    compact_citation = {
        "tool_name": "Video gallery: Incident Clips",
        "function_name": "collect_videos",
        "plugin_name": "ExternalMediaPlugin",
        "function_arguments": {"title": "Incident Clips"},
        "function_result": {
            "success": True,
            "render_type": "inline_video_gallery",
            "summary": "Prepared an inline video gallery.",
            "video_gallery": {
                "title": "Incident Clips",
                "summary": "Compacted gallery preview.",
                "items": ["<dict with 5 keys>", "<dict with 4 keys>"],
                "total_count": 2,
                "source_action_name": "media_collector",
            },
        },
        "artifact_id": "assistant-msg-videos-1_artifact_1",
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
        "**/api/conversation/test-convo/agent-citation/assistant-msg-videos-1_artifact_1",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"citation": _build_full_video_gallery_citation()}),
        ),
    )
    page.route(
        "**/api/enhanced_citations/video?doc_id=workspace-video-001",
        lambda route: route.fulfill(status=200, content_type="video/mp4", body=DUMMY_VIDEO_BYTES),
    )
    page.route(
        "https://api.example.com/videos/loading-dock.mp4",
        lambda route: route.fulfill(status=200, content_type="video/mp4", body=DUMMY_VIDEO_BYTES),
    )

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /chats."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Chat page unavailable in this environment (HTTP {response.status}).")

        if "login" in page.url.lower():
            pytest.skip("Inline video gallery UI test requires an authenticated chat session.")

        page.wait_for_selector("#chatbox")

        with page.expect_response("**/api/conversation/test-convo/agent-citation/assistant-msg-videos-1_artifact_1"):
            page.evaluate(
                """
                async ({ agentCitation, hybridCitation }) => {
                    currentConversationId = 'test-convo';
                    window.currentConversationId = 'test-convo';
                    const messagesModule = await import('/static/js/chat/chat-messages.js');
                    messagesModule.appendMessage(
                        'AI',
                        'Incident video results',
                        null,
                        'assistant-msg-videos-1',
                        true,
                        [hybridCitation],
                        [],
                        [agentCitation],
                        null,
                        null,
                        {
                            id: 'assistant-msg-videos-1',
                            role: 'assistant',
                            content: 'Incident video results',
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
                        "file_name": "workspace-evidence.mp4",
                        "citation_id": "workspace-video-001_1",
                        "page_number": 1,
                    },
                },
            )

        message_scope = page.locator('[data-message-id="assistant-msg-videos-1"]')
        gallery_cards = message_scope.locator('.inline-video-gallery-card')
        expect(gallery_cards).to_have_count(2)
        expect(gallery_cards.first).to_be_visible()
        expect(gallery_cards.nth(0).locator('.inline-video-gallery-title')).to_have_text('Workspace videos')
        expect(gallery_cards.nth(0).locator('.inline-video-gallery-item-title')).to_have_text('workspace-evidence.mp4')
        expect(gallery_cards.nth(0).locator('.inline-video-gallery-badges')).to_contain_text('Videos: 1')
        expect(gallery_cards.nth(1).locator('.inline-video-gallery-title')).to_have_text('Incident Clips')
        expect(gallery_cards.nth(1).locator('.inline-video-gallery-summary')).to_contain_text('Relevant clips gathered from the workspace and an external feed.')
        expect(gallery_cards.nth(1).locator('.inline-video-gallery-badges')).to_contain_text('Videos: 1')
        expect(gallery_cards.nth(1).locator('.inline-video-gallery-footer')).to_contain_text('media_collector')
        expect(message_scope.locator('.inline-video-gallery-item')).to_have_count(2)
        expect(message_scope.locator('.inline-video-gallery-item-video')).to_have_count(2)
        expect(message_scope.locator('.inline-video-gallery-info-btn')).to_have_count(2)
        expect(message_scope.locator('a.agent-citation-link')).to_have_count(1)

        message_scope.locator('.inline-video-gallery-info-btn').nth(1).click()
        details_modal = page.locator('#inline-video-details-modal')
        expect(details_modal).to_be_visible()
        expect(details_modal.locator('#inline-video-details-title')).to_have_text('Loading Dock Camera')
        expect(details_modal.locator('#inline-video-details-description')).to_contain_text('loading dock camera')
        expect(details_modal.locator('#inline-video-details-meta')).to_contain_text('External video (api.example.com)')
        expect(details_modal.locator('#inline-video-details-preview')).to_be_visible()
    finally:
        context.close()
        browser.close()