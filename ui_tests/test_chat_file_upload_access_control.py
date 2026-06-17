# test_chat_file_upload_access_control.py
"""
UI test for chat file upload access control.

Version: 0.242.064
Implemented in: 0.241.110; expanded in: 0.242.063

This test ensures the chat toolbar renders the file upload controls only when
the current user's effective chat upload setting allows new uploads and exposes
that same setting to browser-side upload guards. It also verifies the browser
file picker advertises Outlook MSG upload support.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_chat_file_upload_toolbar_matches_effective_setting():
    """Validate the chat file upload button follows the server-rendered effective setting."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        try:
            page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
            expect(page.locator("#user-input")).to_be_visible()

            upload_enabled = page.evaluate("() => window.appSettings?.enable_chat_file_uploads === true")
            upload_button = page.locator("#choose-file-btn")
            upload_input = page.locator("#file-input")

            if upload_enabled:
                expect(upload_button).to_be_visible()
                expect(upload_input).to_have_count(1)
                accept_value = upload_input.get_attribute("accept") or ""
                upload_title = upload_button.get_attribute("title") or ""
                assert ".msg" in {item.strip() for item in accept_value.split(",")}
                assert "msg" in upload_title.lower()
            else:
                expect(upload_button).to_have_count(0)
                expect(upload_input).to_have_count(0)
        finally:
            context.close()
            browser.close()