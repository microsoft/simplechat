# test_chat_url_access_button_reset.py
"""
UI test for URL Access button reset on conversation changes.
Version: 0.241.084
Implemented in: 0.241.084

This test ensures the URL Access action button does not remain selected
when a user switches conversations or starts a new conversation.
"""

import json
import os
import re
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


def _conversation(conversation_id, title, last_updated):
    return {
        "id": conversation_id,
        "title": title,
        "last_updated": last_updated,
        "is_pinned": False,
        "is_hidden": False,
        "classification": [],
        "chat_type": "personal_single_user",
        "context": [],
        "has_unread_assistant_response": False,
    }


@pytest.mark.ui
def test_url_access_button_resets_on_conversation_context_change():
    """Validate URL Access clears its selected state on switch and new chat."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    conversations_payload = {
        "conversations": [
            _conversation("conversation-alpha", "Alpha", "2025-01-02T00:00:00Z"),
            _conversation("conversation-beta", "Beta", "2025-01-01T00:00:00Z"),
        ]
    }
    metadata_payload = {
        "chat_type": "personal_single_user",
        "context": [],
        "classification": [],
        "is_pinned": False,
        "is_hidden": False,
        "scope_locked": False,
        "locked_contexts": [],
        "can_manage_members": True,
        "can_post_messages": True,
    }
    user_settings_payload = {
        "selected_agent": None,
        "settings": {
            "enable_agents": False,
        },
    }

    def handle_user_settings(route):
        if route.request.method == "GET":
            _fulfill_json(route, user_settings_payload)
            return
        if route.request.method == "POST":
            _fulfill_json(route, {"success": True})
            return
        route.continue_()

    page.route("**/api/user/settings", handle_user_settings)
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, conversations_payload))
    page.route("**/conversation/*/messages**", lambda route: _fulfill_json(route, {"messages": []}))
    page.route("**/api/conversations/*/metadata", lambda route: _fulfill_json(route, metadata_payload))
    page.route("**/api/conversations/*/mark-read", lambda route: _fulfill_json(route, {"success": True}))
    page.route("**/api/create_conversation", lambda route: _fulfill_json(route, {"conversation_id": "new-conversation-reset", "title": "New Conversation"}))
    page.route("**/api/documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/public_workspace_documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/public_workspace_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None, "Expected /chats navigation response."
        assert response.ok, f"Expected /chats to load successfully, got HTTP {response.status}."

        url_access_button = page.locator("#url-access-btn")
        if url_access_button.count() == 0:
            pytest.skip("URL Access is not enabled in this test environment.")

        page.locator('.conversation-item[data-conversation-id="conversation-alpha"]').click()
        prompt = page.locator("#user-input")
        prompt.fill("Review https://example.com/alpha")

        expect(url_access_button).not_to_have_class(re.compile(r".*\bd-none\b.*"))
        url_access_button.click()
        expect(url_access_button).to_have_class(re.compile(r".*\bactive\b.*"))
        expect(url_access_button).to_have_attribute("aria-pressed", "true")

        page.locator('.conversation-item[data-conversation-id="conversation-beta"]').click()
        expect(url_access_button).not_to_have_class(re.compile(r".*\bactive\b.*"))
        expect(url_access_button).to_have_attribute("aria-pressed", "false")

        prompt.fill("Review https://example.com/beta")
        url_access_button.click()
        expect(url_access_button).to_have_class(re.compile(r".*\bactive\b.*"))

        page.locator("#new-conversation-btn").click()
        expect(url_access_button).not_to_have_class(re.compile(r".*\bactive\b.*"))
        expect(url_access_button).to_have_attribute("aria-pressed", "false")
    finally:
        context.close()
        browser.close()
        playwright.stop()
