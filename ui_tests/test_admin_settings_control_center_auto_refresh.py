# test_admin_settings_control_center_auto_refresh.py
"""
UI test for Control Center auto-refresh admin settings.
Version: 0.241.026
Implemented in: 0.241.026

This test ensures the admin settings page exposes the daily UTC Control Center
auto-refresh schedule controls with the enabled 06:00 default.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


@pytest.mark.ui
def test_admin_settings_control_center_auto_refresh_controls(playwright):
    """Validate admins can see and adjust the Control Center refresh schedule."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated admin storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/admin/settings", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response for admin settings."
        if response.status in {401, 403}:
            pytest.skip("Configured admin storage state cannot access admin settings.")
        assert response.ok, f"Expected admin settings to load, got HTTP {response.status}."

        page.get_by_role("tab", name="Control Center").click()
        auto_refresh_section = page.locator("#control-center-auto-refresh-section")
        expect(auto_refresh_section).to_be_visible()

        auto_refresh_toggle = page.locator("#control_center_auto_refresh_enabled")
        auto_refresh_time = page.locator("#control_center_auto_refresh_time")
        expect(auto_refresh_toggle).to_be_checked()
        expect(auto_refresh_time).to_be_visible()
        expect(auto_refresh_time).to_have_value("06:00")

        auto_refresh_toggle.uncheck()
        expect(page.locator("#control-center-auto-refresh-inputs")).to_have_class(
            re.compile(r"(?:^|\s)d-none(?:\s|$)")
        )
    finally:
        context.close()
        browser.close()