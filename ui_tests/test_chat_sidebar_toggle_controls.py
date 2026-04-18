# test_chat_sidebar_toggle_controls.py
"""
UI test for chat sidebar toggle controls.
Version: 0.241.011
Implemented in: 0.241.011

This test ensures the chats page renders a visible sidebar collapse control on
desktop and mobile viewports, and that collapsing the sidebar reveals the
floating reopen control without browser errors.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
@pytest.mark.parametrize(
    ("viewport", "expect_mobile_label"),
    [
        ({"width": 1440, "height": 900}, False),
        ({"width": 430, "height": 932}, True),
    ],
    ids=["desktop", "mobile"],
)
def test_chat_sidebar_toggle_visible_and_reopens(playwright, viewport, expect_mobile_label):
    """Validate that the chats sidebar can be collapsed and reopened across responsive breakpoints."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=viewport,
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

        sidebar = page.locator("#sidebar-nav")
        toggle_button = page.locator("#sidebar-toggle-btn")
        floating_button = page.locator("#floating-expand-btn")

        expect(sidebar).to_be_visible()
        expect(toggle_button).to_be_visible()
        expect(toggle_button).to_have_attribute("aria-expanded", "true")
        expect(floating_button).to_have_class(re.compile(r".*d-none.*"))

        if expect_mobile_label:
            expect(toggle_button).to_contain_text("Hide navigation")

        toggle_button.click()
        page.wait_for_function("document.body.classList.contains('sidebar-collapsed')")

        expect(sidebar).to_have_class(re.compile(r".*sidebar-collapsed.*"))
        expect(floating_button).to_be_visible()

        if expect_mobile_label:
            expect(floating_button).to_contain_text("Open")

        floating_button.click()
        page.wait_for_function("!document.body.classList.contains('sidebar-collapsed')")

        expect(toggle_button).to_have_attribute("aria-expanded", "true")

        toggle_errors = [message for message in page_errors if "toggleSidebar" in message or "sidebar" in message.lower()]
        null_reference_errors = [
            message for message in console_errors
            if "Cannot read" in message or "null" in message.lower()
        ]

        assert not toggle_errors, (
            "Expected chats sidebar toggling to avoid page errors. "
            f"Observed: {toggle_errors}"
        )
        assert not null_reference_errors, (
            "Expected chats sidebar toggling to avoid console null-reference errors. "
            f"Observed: {null_reference_errors}"
        )
    finally:
        context.close()
        browser.close()