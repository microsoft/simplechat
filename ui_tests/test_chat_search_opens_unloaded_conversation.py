# test_chat_search_opens_unloaded_conversation.py
"""
UI regression test for opening a conversation that is not currently rendered.
Version: 0.261.476
Implemented in: 0.261.476

This test ensures selecting an unloaded conversation fetches its metadata and
adds it to the conversation list before notifying conversation-context listeners.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
CONVERSATION_ID = "search-result-not-in-list"


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_select_conversation_loads_it_before_notifying_listeners(playwright):
    """Validate selection loads an older search result absent from the rendered list."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE)
    page = context.new_page()
    metadata_requests = []

    def fulfill_api(route):
        if route.request.url.endswith(f"/api/conversations/{CONVERSATION_ID}/metadata"):
            metadata_requests.append(route.request.url)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "conversation_id": CONVERSATION_ID,
                    "title": "Older search result",
                    "chat_type": "personal_single_user",
                    "classification": [],
                    "context": [],
                    "is_hidden": False,
                    "is_pinned": False,
                    "used_documents": [],
                    "tags": [],
                }),
            )
            return

        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "settings": {}}),
        )

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."
        page.wait_for_function(
            "() => window.chatConversations && typeof window.chatConversations.selectConversation === 'function'"
        )

        page.route("**/api/**", fulfill_api)
        page.route(
            f"**/conversation/{CONVERSATION_ID}/messages**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"messages": []}),
            ),
        )
        page.evaluate(
            """conversationId => {
                document.getElementById("conversations-list").replaceChildren();
                window.__conversationPresentWhenNotified = null;
                window.addEventListener("chat:conversation-context-changed", event => {
                    if (event.detail.conversationId === conversationId) {
                        window.__conversationPresentWhenNotified = Boolean(
                            document.querySelector(
                                `.conversation-item[data-conversation-id="${conversationId}"]`
                            )
                        );
                    }
                }, { once: true });
            }""",
            CONVERSATION_ID,
        )

        page.evaluate(
            "conversationId => window.chatConversations.selectConversation(conversationId)",
            CONVERSATION_ID,
        )

        expect(page.locator(f'.conversation-item[data-conversation-id="{CONVERSATION_ID}"]')).to_have_count(1)
        expect(page.locator(".conversation-item.active")).to_have_attribute(
            "data-conversation-id",
            CONVERSATION_ID,
        )
        expect(page.locator("#current-conversation-title")).to_contain_text("Older search result")
        assert page.evaluate("window.__conversationPresentWhenNotified") is True
        assert metadata_requests, "Expected metadata to be fetched for the unloaded conversation."
        expect(page.locator("#chatbox")).not_to_contain_text("Conversation not found.")
    finally:
        context.close()
        browser.close()
