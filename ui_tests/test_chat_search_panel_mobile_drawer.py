# test_chat_search_panel_mobile_drawer.py
"""
UI test for the mobile grounded-search drawer.
Version: 0.241.022
Implemented in: 0.241.022

This test ensures the grounded search panel stays behind the toolbar on mobile,
opens as an end-side drawer, and closes cleanly through its mobile close button.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
MOBILE_VIEWPORT = {"width": 430, "height": 932}


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_chat_search_panel_uses_mobile_drawer(playwright):
    """Validate that grounded search opens in an end-side mobile drawer."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=MOBILE_VIEWPORT,
    )
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        search_button = page.locator("#search-documents-btn")
        search_panel = page.locator("#search-documents-container")

        if search_button.count() == 0 or search_panel.count() == 0:
            pytest.skip("Grounded search is not enabled for this environment.")

        expect(search_button).to_be_visible()
        expect(search_panel).to_be_hidden()

        search_button.click()
        expect(page.locator("#search-documents-container.show")).to_be_visible()
        expect(page.locator("#search-documents-container .chat-search-panel-mobile-header")).to_be_visible()
        expect(page.locator("#searchDocumentsDrawerLabel")).to_contain_text("Grounded Search")

        close_button = page.locator("#search-documents-container .chat-search-panel-mobile-header .btn-close")
        expect(close_button).to_be_visible()
        close_button.click()
        expect(page.locator("#search-documents-container.show")).to_have_count(0)
    finally:
        context.close()
        browser.close()