# test_admin_home_page_logo_scale_slider.py
"""
UI test for admin home page logo scale slider.
Version: 0.241.059
Implemented in: 0.241.058

This test ensures the Branding section exposes a bounded slider for the
home-page logo size and updates the visible percentage label without saving
shared admin settings.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "") or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _require_storage_state():
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_admin_home_page_logo_scale_slider(playwright):
    """Validate that the home-page logo scale slider renders and updates its label."""
    _require_base_url()
    _require_storage_state()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = context.new_page()
        response = page.goto(f"{BASE_URL}/admin/settings#general", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /admin/settings."
        if response.status in {401, 403, 404}:
            pytest.skip("Admin settings page was not available for the configured admin session.")

        assert response.ok, f"Expected /admin/settings to load successfully, got HTTP {response.status}."

        general_nav = page.locator('[data-bs-target="#general"], [data-tab="general"]').first
        if general_nav.count() > 0:
            general_nav.click()

        branding_section = page.locator("#branding-section")
        expect(branding_section).to_be_visible()

        slider = page.locator("#landing_page_logo_scale_percent")
        value_display = page.locator("#landing-page-logo-scale-value")
        help_text = page.locator("#landing-page-logo-scale-help")

        expect(slider).to_be_visible()
        expect(value_display).to_be_visible()
        expect(help_text).to_contain_text("home page only")
        expect(help_text).to_contain_text("sidebar navigation")

        assert slider.get_attribute("min") == "50"
        assert slider.get_attribute("max") == "500"

        expect(value_display).to_have_text(f"{slider.input_value()}%")

        slider.evaluate(
            """(element) => {
                element.value = '250';
                element.dispatchEvent(new Event('input', { bubbles: true }));
            }"""
        )

        expect(slider).to_have_value("250")
        expect(value_display).to_have_text("250%")
    finally:
        context.close()
        browser.close()