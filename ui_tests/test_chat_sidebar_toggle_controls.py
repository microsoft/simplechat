# test_chat_sidebar_toggle_controls.py
"""
UI test for the unified chat navigation shell.
Version: 0.241.023
Implemented in: 0.241.023

This test ensures that chats in top-nav mode use the adaptive conversation
rail, preserve compact desktop top-nav links, and become the hamburger drawer
on mobile without reintroducing the old top-nav drawer or the chat drawer
close-button crash while preserving direct workspace navigation in the mobile
drawer.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
MOBILE_VIEWPORT = {"width": 430, "height": 932}


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


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


@pytest.mark.ui
def test_chat_sidebar_desktop_uses_inline_toggle_without_floating_reopen(playwright):
    """Validate that desktop chat uses the docked rail, inline toggle, and compact header navigation."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=DESKTOP_VIEWPORT,
    )
    page = context.new_page()
    original_settings = None

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        original_settings = _get_user_settings(page)
        top_nav_settings = dict(original_settings)
        top_nav_settings["navLayout"] = "top"
        assert _set_user_settings(page, top_nav_settings), "Expected nav layout update to succeed."

        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None and response.ok, "Expected /chats to load in top-nav mode."

        sidebar = page.locator("#sidebar-nav")
        sidebar_toggle = page.locator("#sidebar-toggle-btn")
        inline_toggle = page.locator("#chat-sidebar-inline-toggle")

        expect(sidebar).to_be_visible()
        expect(sidebar_toggle).to_be_visible()
        expect(inline_toggle).to_be_visible()
        expect(page.locator("#floating-expand-btn")).to_have_count(0)
        expect(page.locator("#topNavMobileMenu")).to_have_count(0)
        expect(page.locator(".top-nav-chat-nav")).to_be_visible()
        expect(page.locator(".top-nav-chat-nav .nav-link").first).to_be_visible()

        sidebar_toggle.click()
        page.wait_for_function("document.body.classList.contains('sidebar-collapsed')")

        expect(sidebar).to_have_class(re.compile(r".*sidebar-collapsed.*"))
        expect(inline_toggle).to_have_attribute("aria-expanded", "false")

        inline_toggle.click()
        page.wait_for_function("!document.body.classList.contains('sidebar-collapsed')")

        expect(sidebar_toggle).to_have_attribute("aria-expanded", "true")
        expect(inline_toggle).to_have_attribute("aria-expanded", "true")
    finally:
        if original_settings is not None:
            _set_user_settings(page, original_settings)
        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_sidebar_mobile_uses_chat_drawer_and_separates_profile_menu(playwright):
    """Validate that mobile chat uses the rail drawer and coordinates it with the profile dropdown."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=MOBILE_VIEWPORT,
    )
    page = context.new_page()
    original_settings = None
    page_errors = []
    console_errors = []

    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        original_settings = _get_user_settings(page)
        top_nav_settings = dict(original_settings)
        top_nav_settings["navLayout"] = "top"
        assert _set_user_settings(page, top_nav_settings), "Expected nav layout update to succeed."

        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None and response.ok, "Expected /chats to load in mobile top-nav mode."

        drawer_button = page.get_by_role("button", name="Open chat navigation")
        drawer = page.locator("#sidebar-nav")

        expect(drawer_button).to_be_visible()
        expect(page.locator("#topNavMobileMenu")).to_have_count(0)
        expect(drawer).to_be_hidden()

        drawer_button.click()
        expect(page.locator("#sidebar-nav.show")).to_be_visible()
        expect(page.locator("#sidebar-nav .chat-sidebar-mobile-header")).to_be_visible()
        expect(page.locator("#sidebar-nav")).to_contain_text("Chat Navigation")
        expect(page.locator("#sidebar-nav .chat-sidebar-mobile-sections")).to_be_visible()
        expect(page.locator("#sidebar-nav .chat-sidebar-mobile-sections")).to_contain_text("Workspace")
        expect(page.locator("#sidebar-nav .chat-sidebar-mobile-sections").get_by_role("link", name="Chat")).to_be_visible()

        drawer_box = drawer.bounding_box()
        navbar_box = page.locator("nav.top-nav-bar").bounding_box()
        assert drawer_box is not None and navbar_box is not None, "Expected drawer and top navigation to be measurable."
        assert drawer_box["y"] >= (navbar_box["y"] + navbar_box["height"] - 1), "Expected the mobile chat drawer to open below the fixed top navigation."

        close_button = page.locator("#sidebar-nav .chat-sidebar-mobile-header .btn-close")
        expect(close_button).to_be_visible()
        close_button.click()
        expect(page.locator("#sidebar-nav.show")).to_have_count(0)

        page.locator("#userDropdown").click(force=True)
        expect(page.locator("#sidebar-nav.show")).to_have_count(0)
        expect(page.locator(".top-nav-user-menu.show")).to_be_visible()

        drawer_button.click(force=True)
        expect(page.locator("#sidebar-nav.show")).to_be_visible()
        expect(page.locator(".top-nav-user-menu.show")).to_have_count(0)

        backdrop_errors = [message for message in page_errors + console_errors if "backdrop" in message.lower()]
        assert not backdrop_errors, f"Expected chat drawer close interactions to avoid Bootstrap backdrop errors. Observed: {backdrop_errors}"
    finally:
        if original_settings is not None:
            _set_user_settings(page, original_settings)
        context.close()
        browser.close()