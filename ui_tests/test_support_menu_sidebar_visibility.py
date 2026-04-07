# test_support_menu_sidebar_visibility.py
"""
UI test for support menu sidebar visibility.
Version: 0.240.069
Implemented in: 0.240.058

This test ensures that when the Support menu is enabled in Admin Settings and the
page is using the left sidebar layout, the sidebar renders the Support section
for a signed-in app user.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _require_storage_state():
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_admin_settings_support_sidebar_visible_when_enabled(playwright):
    """Validate the Support section appears in the left sidebar when enabled."""
    _require_base_url()
    _require_storage_state()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = context.new_page()
        response = page.goto(f"{BASE_URL}/admin/settings", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /admin/settings."
        if response.status in {401, 403, 404}:
            pytest.skip("Admin settings page was not available for the configured admin session.")

        assert response.ok, f"Expected /admin/settings to load successfully, got HTTP {response.status}."
        expect(page.locator("#adminSettingsTabContent")).to_be_visible()

        sidebar = page.locator("#sidebar-nav")
        if sidebar.count() == 0 or not sidebar.is_visible():
            pytest.skip("Support sidebar visibility requires the left navigation layout.")

        support_toggle = page.locator("#enable_support_menu")
        latest_features_toggle = page.locator("#enable_support_latest_features")
        send_feedback_toggle = page.locator("#enable_support_send_feedback")
        recipient_field = page.locator("#support_feedback_recipient_email")
        feature_visibility_note = page.get_by_text(
            "Deployment and Redis start unchecked because they are mainly admin-facing rollout and infrastructure topics."
        )

        if not support_toggle.is_checked():
            pytest.skip("Support menu is disabled in this environment.")

        if not latest_features_toggle.is_checked():
            latest_features_toggle.check()

        expect(feature_visibility_note).to_be_visible()

        latest_features_enabled = latest_features_toggle.is_checked()
        send_feedback_enabled = send_feedback_toggle.is_checked() and recipient_field.input_value().strip() != ""
        if not latest_features_enabled and not send_feedback_enabled:
            pytest.skip("Support menu has no enabled destinations in this environment.")

        expect(page.locator("#support-menu-toggle")).to_be_visible()
        if latest_features_enabled:
            expect(page.locator("a[href='/support/latest-features']")).to_be_visible()
        if send_feedback_enabled:
            expect(page.locator("a[href='/support/send-feedback']")).to_be_visible()
    finally:
        context.close()
        browser.close()