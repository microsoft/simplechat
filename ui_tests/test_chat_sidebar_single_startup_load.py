# test_chat_sidebar_single_startup_load.py
"""
UI test for single chat sidebar startup feed load.
Version: 0.241.112
Implemented in: 0.241.112

This test ensures the chat page bootstrap loads the paged conversation feed once
for the visible sidebar and does not fall back to duplicate legacy list requests.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_chat_sidebar_uses_single_startup_conversation_feed_load():
    """Validate that chat startup loads the conversation feed once."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    feed_request_count = 0
    legacy_request_count = 0
    collaboration_request_count = 0
    conversations_payload = {
        "success": True,
        "conversations": [
            {
                "id": "conversation-001",
                "title": "Architecture Notes",
                "last_updated": "2026-04-29T10:00:00Z",
                "classification": [],
                "context": [],
                "chat_type": "personal_single_user",
                "is_pinned": False,
                "is_hidden": False,
                "has_unread_assistant_response": False,
            },
            {
                "id": "conversation-002",
                "title": "Release Planning",
                "last_updated": "2026-04-29T09:45:00Z",
                "classification": [],
                "context": [],
                "chat_type": "personal_single_user",
                "is_pinned": False,
                "is_hidden": False,
                "has_unread_assistant_response": False,
            },
        ],
        "has_more": False,
        "next_cursor": None,
        "hidden_count": 0,
    }

    def handle_user_settings(route):
        if route.request.method == "GET":
            _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}})
            return

        _fulfill_json(route, {"success": True})

    def handle_feed_conversations(route):
        nonlocal feed_request_count
        feed_request_count += 1
        _fulfill_json(route, conversations_payload)

    def handle_legacy_conversations(route):
        nonlocal legacy_request_count
        legacy_request_count += 1
        _fulfill_json(route, {"conversations": []})

    def handle_collaboration_conversations(route):
        nonlocal collaboration_request_count
        collaboration_request_count += 1
        _fulfill_json(route, [])

    page.route("**/api/user/settings", handle_user_settings)
    page.route("**/api/conversations/feed?**", handle_feed_conversations)
    page.route("**/api/get_conversations", handle_legacy_conversations)
    page.route("**/api/collaboration/conversations?*", handle_collaboration_conversations)

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok

        sidebar_list = page.locator("#sidebar-conversations-list")
        page.wait_for_function(
            """
            () => {
                const sidebarList = document.getElementById('sidebar-conversations-list');
                const text = sidebarList?.textContent || '';
                const itemCount = document.querySelectorAll('#sidebar-conversations-list .sidebar-conversation-item').length;
                return itemCount === 2 && !/Loading conversations/i.test(text);
            }
            """
        )

        expect(sidebar_list).to_contain_text("Architecture Notes")
        expect(sidebar_list).to_contain_text("Release Planning")
        assert feed_request_count == 1
        assert legacy_request_count == 0
        assert collaboration_request_count == 0
    finally:
        context.close()
        browser.close()
        playwright_context.stop()
