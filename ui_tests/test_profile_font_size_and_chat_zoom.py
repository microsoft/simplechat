# test_profile_font_size_and_chat_zoom.py
"""
UI test for profile font sizing and 200 percent chat zoom resilience.
Version: 0.250.073
Implemented in: 0.250.073

This test ensures users can preview and save a global font size and that the
chat remains usable at a 720x450 CSS viewport representing 200 percent zoom.
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
    pytest.skip(
        "Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE "
        "to a valid authenticated Playwright storage state file."
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


def _assert_chat_viewport_is_usable(page):
    expect(page.locator("#chatbox")).to_be_visible()
    expect(page.locator("#user-input")).to_be_visible()
    expect(page.locator("#chat-mobile-tools-toggle")).to_be_visible()

    chatbox = page.locator("#chatbox").bounding_box()
    user_input = page.locator("#user-input").bounding_box()
    assert chatbox is not None and chatbox["height"] >= 40
    assert user_input is not None
    assert user_input["y"] + user_input["height"] <= 450
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth + 1"
    )


@pytest.mark.ui
def test_profile_font_size_and_chat_zoom_reflow(playwright):
    """Validate preview, persistence, and zoom-equivalent chat reflow."""
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
        response = page.goto(f"{BASE_URL}/profile?tab=settings", wait_until="domcontentloaded")
        assert response is not None and response.ok
        expect(page.get_by_role("heading", name="Appearance Preferences")).to_be_visible()
        original_settings = _get_user_settings(page)

        original_preference = original_settings.get("fontSizePreference", "m")
        page.locator("#font-size-preference-xl").check()
        expect(page.locator("html")).to_have_attribute("data-font-size", "xl")
        expect(page.locator("html")).to_have_css("font-size", "32px")

        unsaved_settings = _get_user_settings(page)
        assert unsaved_settings.get("fontSizePreference", "m") == original_preference

        page.locator("#save-font-size-preference-btn").click()
        expect(page.locator("#font-size-preference-status")).to_contain_text(
            "XL is now your saved font size"
        )
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("html")).to_have_attribute("data-font-size", "xl")

        assert _set_user_settings(
            page,
            {"fontSizePreference": "m", "navLayout": "top"},
        )
        page.set_viewport_size({"width": 720, "height": 450})
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        _assert_chat_viewport_is_usable(page)

        assert _set_user_settings(page, {"navLayout": "sidebar"})
        page.reload(wait_until="domcontentloaded")
        assert page.locator("body").evaluate(
            "element => element.classList.contains('sidebar-nav-enabled')"
        )
        expect(page.locator("#sidebar-content")).to_be_visible()
        _assert_chat_viewport_is_usable(page)
    finally:
        if original_settings is not None:
            _set_user_settings(
                page,
                {
                    "fontSizePreference": original_settings.get(
                        "fontSizePreference",
                        "m",
                    ),
                    "navLayout": original_settings.get("navLayout", ""),
                },
            )
        context.close()
        browser.close()
