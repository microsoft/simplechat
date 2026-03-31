# test_chat_page_multi_endpoint_notice_render.py
"""
UI test for chat page multi-endpoint notice rendering.
Version: 0.240.004
Implemented in: 0.240.004

This test ensures the authenticated chats page loads successfully and renders
the primary chat UI without a server-side template failure.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_chat_page_multi_endpoint_notice_render(playwright):
    """Validate that the chats page renders for an authenticated user."""
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

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")

        assert response is not None, "Expected a navigation response when loading /chats."
        assert response.ok, f"Expected /chats to load successfully, got HTTP {response.status}."

        expect(page.locator("#chatbox")).to_be_visible()
        expect(page.locator("#user-input")).to_be_visible()
    finally:
        context.close()
        browser.close()
