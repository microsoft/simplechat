# test_chat_sidebar_whole_panel_scroll.py
"""
UI test for whole-panel chat sidebar scrolling.
Version: 0.250.002
Implemented in: 0.250.002

This test ensures constrained-height chat sidebars use one outer scrollbar,
show New Chat at the top, and keep the Conversations heading pinned while
users scroll through the conversation list.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
VIEWPORT = {"width": 1440, "height": 600}


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _get_user_settings(page):
    return page.evaluate(
        """
        async () => {
            const response = await fetch('/api/user/settings');
            const data = await response.json();
            return data.settings || {};
        }
        """
    )


def _set_user_settings(page, settings):
    return page.evaluate(
        """
        async (nextSettings) => {
            const response = await fetch('/api/user/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: nextSettings })
            });
            return response.ok;
        }
        """,
        settings,
    )


def _conversation_payload():
    return {
        "conversations": [
            {
                "id": f"sidebar-scroll-conversation-{index}",
                "title": f"Sidebar Scroll Conversation {index:02d}",
                "last_updated": f"2026-07-30T10:{index:02d}:00Z",
                "classification": [],
                "context": [],
                "chat_type": "personal_single_user",
                "is_pinned": False,
                "is_hidden": False,
                "has_unread_assistant_response": False,
            }
            for index in range(1, 31)
        ]
    }


@pytest.mark.ui
@pytest.mark.parametrize("nav_layout", ["sidebar", "top"])
def test_chat_sidebar_scrolls_as_one_panel_with_sticky_conversations(playwright, nav_layout):
    """Validate whole-panel scrolling in the full and compact chat sidebar shells."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=VIEWPORT,
    )
    page = context.new_page()
    original_settings = None

    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, _conversation_payload()))
    page.route("**/api/collaboration/conversations?*", lambda route: _fulfill_json(route, []))

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        original_settings = _get_user_settings(page)
        test_settings = dict(original_settings)
        test_settings["navLayout"] = nav_layout
        assert _set_user_settings(page, test_settings), "Expected navigation layout update to succeed."

        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None and response.ok, "Expected /chats to load."

        sidebar_content = page.locator("#sidebar-content")
        conversations_toggle = page.locator("#conversations-toggle")
        conversations_list = page.locator("#sidebar-conversations-list")
        new_chat_button = page.locator("#sidebar-new-chat-btn")
        last_conversation = conversations_list.get_by_text("Sidebar Scroll Conversation 30", exact=True)

        page.wait_for_function(
            """
            () => document.querySelectorAll(
                '#sidebar-conversations-list .sidebar-conversation-item'
            ).length === 30
            """
        )

        expect(sidebar_content).to_be_visible()
        expect(new_chat_button).to_be_visible()
        expect(conversations_toggle).to_be_visible()

        layout = page.evaluate(
            """
            () => {
                const content = document.getElementById('sidebar-content');
                const list = document.getElementById('sidebar-conversations-list');
                return {
                    contentOverflowY: getComputedStyle(content).overflowY,
                    contentClientHeight: content.clientHeight,
                    contentScrollHeight: content.scrollHeight,
                    listOverflowY: getComputedStyle(list).overflowY,
                    listClientHeight: list.clientHeight,
                    listScrollHeight: list.scrollHeight
                };
            }
            """
        )
        assert layout["contentOverflowY"] == "auto"
        assert layout["contentScrollHeight"] > layout["contentClientHeight"]
        assert layout["listOverflowY"] == "visible"
        assert layout["listScrollHeight"] == layout["listClientHeight"]

        page.evaluate(
            """
            () => {
                const content = document.getElementById('sidebar-content');
                const toggle = document.getElementById('conversations-toggle');
                content.scrollTop = toggle.offsetTop + 120;
            }
            """
        )
        page.wait_for_function("document.getElementById('sidebar-content').scrollTop > 0")

        sticky_position = page.evaluate(
            """
            () => {
                const content = document.getElementById('sidebar-content').getBoundingClientRect();
                const toggle = document.getElementById('conversations-toggle').getBoundingClientRect();
                return {
                    contentTop: content.top,
                    toggleTop: toggle.top
                };
            }
            """
        )
        assert abs(sticky_position["toggleTop"] - sticky_position["contentTop"]) <= 1
        expect(new_chat_button).not_to_be_in_viewport()

        last_conversation.scroll_into_view_if_needed()
        expect(last_conversation).to_be_in_viewport()

        final_sticky_position = page.evaluate(
            """
            () => {
                const content = document.getElementById('sidebar-content').getBoundingClientRect();
                const toggle = document.getElementById('conversations-toggle').getBoundingClientRect();
                return Math.abs(toggle.top - content.top);
            }
            """
        )
        assert final_sticky_position <= 1
    finally:
        if original_settings is not None:
            _set_user_settings(page, original_settings)
        context.close()
        browser.close()
