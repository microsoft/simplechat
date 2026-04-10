# test_chat_new_conversation_tag_reset.py
"""
UI test for chat tag reset on new conversation.
Version: 0.240.026
Implemented in: 0.240.026

This test ensures that selecting a chat tag updates the visible selector
state and that starting a brand new conversation clears the tag label and
checkbox state back to the default "All Tags" view.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_new_conversation_clears_selected_chat_tags(playwright):
    """Validate that explicit new chat creation clears stale tag selector state."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

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

    documents_payload = {
        "documents": [
            {
                "id": "personal-doc-1",
                "title": "Alpha Brief",
                "file_name": "alpha-brief.md",
                "tags": ["alpha"],
                "document_classification": "",
            }
        ]
    }

    page.route("**/api/user/settings", handle_user_settings)
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))
    page.route(
        "**/api/create_conversation",
        lambda route: _fulfill_json(
            route,
            {
                "conversation_id": "new-conversation-1",
                "title": "New Conversation",
            },
        ),
    )
    page.route("**/api/documents?page_size=1000", lambda route: _fulfill_json(route, documents_payload))
    page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/public_workspace_documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": [{"name": "alpha", "count": 1}]}))
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/public_workspace_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="networkidle")

        page.locator("#search-documents-btn").click()
        page.wait_for_function(
            """
            () => {
                const tagsDropdown = document.getElementById('tags-dropdown');
                return tagsDropdown && window.getComputedStyle(tagsDropdown).display !== 'none';
            }
            """
        )

        page.locator("#tags-dropdown-button").click()
        page.locator('#tags-dropdown-items [data-tag-value="alpha"]').click()
        expect(page.locator("#tags-dropdown-button .selected-tags-text")).to_have_text("alpha")

        page.locator("#new-conversation-btn").click()

        page.wait_for_function(
            """
            () => {
                const text = document.querySelector('#tags-dropdown-button .selected-tags-text');
                return text && text.textContent.trim() === 'All Tags'
                    && document.querySelectorAll('#tags-dropdown-items .tag-checkbox:checked').length === 0;
            }
            """
        )

        expect(page.locator("#tags-dropdown-button .selected-tags-text")).to_have_text("All Tags")
        assert page.locator("#tags-dropdown-items .tag-checkbox:checked").count() == 0
    finally:
        context.close()
        browser.close()
