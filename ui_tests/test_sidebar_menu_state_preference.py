# test_sidebar_menu_state_preference.py
"""
UI test for sidebar menu state preference.
Version: 0.241.027
Implemented in: 0.241.027

This test ensures the left sidebar remembers whether a user left a menu section
expanded or collapsed while navigating between pages, and that stale menu-state
values do not cause settings saves to fail.
"""

import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")
DESKTOP_VIEWPORT = {"width": 1440, "height": 900}
SIDEBAR_MENU_KEYS = {
    "workspaces", "support", "externalLinks", "adminSettings",
    "controlCenter", "conversations"
}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    try:
        with urlopen(BASE_URL, timeout=5):
            return
    except URLError as ex:
        pytest.skip(f"UI server is not reachable at {BASE_URL}: {ex.reason}")


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
    result = page.evaluate(
        """
        async (nextSettings) => {
            const response = await fetch('/api/user/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: nextSettings })
            });
            let body = {};
            try {
                body = await response.json();
            } catch (error) {
                body = { error: 'Unable to parse response body' };
            }
            return { ok: response.ok, status: response.status, body };
        }
        """,
        settings,
    )
    assert result["ok"], f"Expected user settings update to succeed. Response: {result}"
    return result


def _wait_for_sidebar_menu_state(page, menu_key, is_expanded):
    page.wait_for_function(
        """
        async ({ menuKey, expanded }) => {
            const response = await fetch('/api/user/settings');
            const data = await response.json();
            return data.settings
                && data.settings.sidebarMenuState
                && data.settings.sidebarMenuState[menuKey] === expanded;
        }
        """,
        {"menuKey": menu_key, "expanded": is_expanded},
    )


def _get_sidebar_menu_state(page):
    return _get_user_settings(page).get("sidebarMenuState") or {}


def _get_restorable_sidebar_menu_state(settings):
    sidebar_menu_state = settings.get("sidebarMenuState") or {}
    if not isinstance(sidebar_menu_state, dict):
        return {}

    return {
        key: value
        for key, value in sidebar_menu_state.items()
        if key in SIDEBAR_MENU_KEYS and isinstance(value, bool)
    }


@pytest.mark.ui
def test_sidebar_menu_state_persists_across_navigation(playwright):
    """Validate that a collapsed or expanded sidebar menu survives navigation."""
    _require_ui_env()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport=DESKTOP_VIEWPORT,
    )
    page = context.new_page()
    original_settings = None

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /chats."
        if response.status in {401, 403, 404}:
            pytest.skip("Chat page was not available for the configured session.")
        assert response.ok, f"Expected /chats to load successfully, got HTTP {response.status}."

        original_settings = _get_user_settings(page)
        original_sidebar_menu_state = _get_restorable_sidebar_menu_state(original_settings)
        legacy_state = dict(original_sidebar_menu_state)
        legacy_state.update({
            "workspaces": "false",
            "support": False,
            "legacyCustomMenu": True,
            "externalLinks": "not-a-bool",
        })

        _set_user_settings(page, {
            "navLayout": "sidebar",
            "sidebarMenuState": legacy_state,
        })

        saved_sidebar_state = _get_sidebar_menu_state(page)
        assert saved_sidebar_state.get("workspaces") is False, "Expected legacy string boolean to be normalized."
        assert saved_sidebar_state.get("support") is False, "Expected valid boolean menu state to be preserved."
        assert "legacyCustomMenu" not in saved_sidebar_state, "Expected unknown sidebar menu keys to be ignored."
        assert "externalLinks" not in saved_sidebar_state, "Expected invalid sidebar menu values to be ignored."

        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None and response.ok, "Expected /chats to reload in sidebar mode."

        sidebar = page.locator("#sidebar-nav")
        workspaces_toggle = page.locator("#workspaces-toggle")
        workspaces_section = page.locator("#workspaces-section")
        if sidebar.count() == 0 or workspaces_toggle.count() == 0:
            pytest.skip("Left sidebar Workspaces menu is not available in the current UI environment.")

        expect(sidebar).to_be_visible()
        expect(workspaces_toggle).to_have_attribute("aria-expanded", "false")
        expect(workspaces_section).to_be_hidden()

        workspaces_toggle.click()
        expect(workspaces_toggle).to_have_attribute("aria-expanded", "true")
        expect(workspaces_section).to_be_visible()
        _wait_for_sidebar_menu_state(page, "workspaces", True)

        profile_response = page.goto(f"{BASE_URL}/profile", wait_until="domcontentloaded")
        assert profile_response is not None, "Expected a navigation response when loading /profile."
        if profile_response.status in {401, 403, 404}:
            pytest.skip("Profile page was not available for the configured session.")
        assert profile_response.ok, f"Expected /profile to load successfully, got HTTP {profile_response.status}."
        expect(page.locator("#workspaces-toggle")).to_have_attribute("aria-expanded", "true")
        expect(page.locator("#workspaces-section")).to_be_visible()

        page.locator("#workspaces-toggle").click()
        expect(page.locator("#workspaces-toggle")).to_have_attribute("aria-expanded", "false")
        expect(page.locator("#workspaces-section")).to_be_hidden()
        _wait_for_sidebar_menu_state(page, "workspaces", False)

        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None and response.ok, "Expected /chats to reload after collapsing Workspaces."
        expect(page.locator("#workspaces-toggle")).to_have_attribute("aria-expanded", "false")
        expect(page.locator("#workspaces-section")).to_be_hidden()
    finally:
        if original_settings is not None:
            _set_user_settings(page, {
                "navLayout": original_settings.get("navLayout", ""),
                "sidebarMenuState": _get_restorable_sidebar_menu_state(original_settings),
            })
        context.close()
        browser.close()