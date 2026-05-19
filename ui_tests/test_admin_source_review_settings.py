# test_admin_source_review_settings.py
"""
UI test for Source Review admin settings.
Version: 0.241.046
Implemented in: 0.241.041

This test ensures the Search & Extract admin tab exposes Source Review controls,
including bounded review settings, deep review, model planning, and domain/user
policy fields.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


@pytest.mark.ui
def test_admin_source_review_settings():
    """Validate admins can see and toggle Source Review settings."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated admin storage state file.")
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 1000},
    )
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/admin/settings#search-extract", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response for admin settings."
        if response.status in {401, 403, 404}:
            pytest.skip("Configured admin storage state cannot access admin settings.")
        assert response.ok, f"Expected admin settings to load, got HTTP {response.status}."

        search_extract_nav = page.locator('[data-bs-target="#search-extract"], [data-tab="search-extract"]').first
        if search_extract_nav.count() > 0:
            search_extract_nav.click()

        source_review_section = page.locator("#source-review-section")
        expect(source_review_section).to_be_visible()

        source_review_toggle = page.locator("#enable_source_review")
        if not source_review_toggle.is_checked():
            source_review_toggle.check(force=True)

        expect(page.locator("#source_review_settings")).to_be_visible()
        expect(page.locator("#source_review_default_mode")).to_be_visible()
        expect(page.locator("#source_review_max_pages_per_turn")).to_have_attribute("max", "10")
        expect(page.locator("#source_review_max_seed_pages_per_turn")).to_have_attribute("max", "10")
        expect(page.locator("#source_review_max_depth")).to_have_attribute("max", "2")
        expect(page.locator("#source_review_timeout_seconds")).to_have_attribute("max", "30")
        expect(page.locator("#source_review_max_bytes_per_page_mb")).to_have_attribute("max", "5")
        expect(page.locator("#source_review_js_load_more_clicks")).to_have_attribute("max", "12")

        deep_review_toggle = page.locator("#enable_deep_source_review")
        if not deep_review_toggle.is_checked():
            deep_review_toggle.check(force=True)
        expect(page.locator("#source_review_deep_settings")).to_be_visible()
        expect(page.locator("#source_review_enable_llm_planning")).to_have_count(1)

        page.locator("#source_review_allowed_domains").fill("contoso.com\n*.example.org")
        page.locator("#source_review_blocked_users").fill("blocked.user@contoso.com")
        expect(page.locator("#source_review_allowed_domains")).to_have_value("contoso.com\n*.example.org")
        expect(page.locator("#source_review_blocked_users")).to_have_value("blocked.user@contoso.com")
    finally:
        context.close()
        browser.close()
        playwright.stop()