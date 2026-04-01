# test_chat_page_multi_endpoint_notice_render.py
# test_chat_page_multi_endpoint_notice_render.py
"""
UI test for chat page multi-endpoint notice rendering.
Version: 0.240.008
Implemented in: 0.240.008

This test ensures the authenticated chats page loads successfully and renders
the primary chat UI without a server-side template failure or a JavaScript
bootstrap syntax error.
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
    page_errors = []
    console_errors = []

    def track_page_error(error):
        page_errors.append(str(error))

    def track_console(message):
        if message.type == "error":
            console_errors.append(message.text)

    page.on("pageerror", track_page_error)
    page.on("console", track_console)

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")

        assert response is not None, "Expected a navigation response when loading /chats."
        assert response.ok, f"Expected /chats to load successfully, got HTTP {response.status}."

        expect(page.locator("#chatbox")).to_be_visible()
        expect(page.locator("#user-input")).to_be_visible()
        page.wait_for_load_state("networkidle")

        syntax_errors = [message for message in page_errors if "SyntaxError" in message]
        bad_control_errors = [
            message for message in console_errors
            if "Bad control character" in message or "JSON.parse" in message
        ]

        assert not syntax_errors, (
            "Expected /chats to boot without JavaScript syntax errors. "
            f"Observed: {syntax_errors}"
        )
        assert not bad_control_errors, (
            "Expected /chats to avoid JSON bootstrap parse errors. "
            f"Observed: {bad_control_errors}"
        )
    finally:
        context.close()
        browser.close()
