# test_latest_features_nav_hide_preference.py
"""
UI test for Latest Features navigation hide preference.
Version: 0.250.059
Implemented in: 0.250.059

This test ensures an authenticated user can clear a versioned Latest Features
navigation hide preference from the profile Settings page.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")
CURRENT_VERSION = "0.250.059"


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


def _set_latest_features_hidden_version(page, hidden_version):
    return page.evaluate(
        """
        async (hiddenVersion) => {
            const response = await fetch('/api/user/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    settings: {
                        latestFeaturesHiddenVersion: hiddenVersion
                    }
                })
            });
            return response.ok;
        }
        """,
        hidden_version,
    )


@pytest.mark.ui
def test_profile_can_unhide_latest_features_navigation(playwright):
    """Validate the profile Settings page restores Latest Features navigation."""
    _require_base_url()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    original_hidden_version = None

    try:
        response = page.goto(f"{BASE_URL}/profile?tab=settings", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /profile."
        if response.status in {401, 403, 404}:
            pytest.skip("Profile page was not available for the configured session.")

        assert response.ok, f"Expected /profile to load successfully, got HTTP {response.status}."
        expect(page.get_by_role("heading", name="Latest Features Navigation")).to_be_visible()

        original_hidden_version = _get_user_settings(page).get("latestFeaturesHiddenVersion")
        assert _set_latest_features_hidden_version(page, CURRENT_VERSION), "Expected Latest Features hide preference update to succeed."

        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#latest-features-nav-status-badge")).to_contain_text("Hidden")
        expect(page.locator("#unhide-latest-features-nav-btn")).to_be_visible()

        page.locator("#unhide-latest-features-nav-btn").click()
        expect(page.locator("#latest-features-nav-status-badge")).to_contain_text("Visible")
        expect(page.locator("#latest-features-nav-preference-status")).to_contain_text("restored")

        saved_settings = _get_user_settings(page)
        assert saved_settings.get("latestFeaturesHiddenVersion") in {None, ""}, "Expected Latest Features hide preference to be cleared."
    finally:
        if original_hidden_version == CURRENT_VERSION:
            _set_latest_features_hidden_version(page, original_hidden_version)
        context.close()
        browser.close()
