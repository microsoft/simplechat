# test_profile_sidebar_toggle_style_preference.py
"""
UI test for profile sidebar toggle style preference.
Version: 0.241.015
Implemented in: 0.241.015

This test ensures a signed-in user can choose the compact sidebar hide control
from the profile page and that Chat renders the compact control after the
preference is saved.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _get_storage_state_path():
    for candidate in (STORAGE_STATE, ADMIN_STORAGE_STATE):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


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
def test_profile_can_save_compact_sidebar_toggle_style(playwright):
    """Validate that the profile preference switches Chat to the compact sidebar toggle."""
    _require_base_url()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    original_settings = None

    try:
        response = page.goto(f"{BASE_URL}/profile", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /profile."
        if response.status in {401, 403, 404}:
            pytest.skip("Profile page was not available for the configured session.")

        assert response.ok, f"Expected /profile to load successfully, got HTTP {response.status}."
        expect(page.get_by_role("heading", name="Navigation Preferences")).to_be_visible()

        original_settings = _get_user_settings(page)

        page.locator("#sidebar-toggle-style-compact").check(force=True)
        page.locator("#save-navigation-preferences-btn").click()
        expect(page.locator("#navigation-preference-status")).to_contain_text("compact sidebar hide control")

        saved_settings = _get_user_settings(page)
        assert saved_settings.get("sidebarToggleStyle") == "compact", "Expected compact sidebar toggle style to be saved."

        assert _set_user_settings(page, {"navLayout": "top"}), "Expected nav layout update to succeed."

        chat_response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert chat_response is not None, "Expected a navigation response when loading /chats."
        if chat_response.status in {401, 403, 404}:
            pytest.skip("Chat page was not available for the configured session.")

        assert chat_response.ok, f"Expected /chats to load successfully, got HTTP {chat_response.status}."
        expect(page.locator("#sidebar-toggle-btn.sidebar-toggle-compact")).to_be_visible()
        expect(page.locator("#sidebar-toggle-btn i.bi-layout-sidebar")).to_be_visible()
    finally:
        if original_settings is not None:
            _set_user_settings(page, {
                "navLayout": original_settings.get("navLayout", ""),
                "sidebarToggleStyle": original_settings.get("sidebarToggleStyle", "large"),
            })
        context.close()
        browser.close()