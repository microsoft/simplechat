# test_admin_source_review_settings.py
"""
UI test for Deep Research admin settings.
Version: 0.241.055
Implemented in: 0.241.055

This test ensures the Search & Extract admin tab exposes Deep Research controls,
including bounded review settings, query planning, ledger artifacts, editable domain
rules, and searchable/bulk user policy controls.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


@pytest.mark.ui
def test_admin_source_review_settings():
    """Validate admins can see and toggle Deep Research settings."""
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
        expect(source_review_section).to_contain_text("Deep Research")

        source_review_toggle = page.locator("#enable_source_review")
        if not source_review_toggle.is_checked():
            source_review_toggle.check(force=True)

        expect(page.locator("#source_review_settings")).to_be_visible()
        expect(page.locator("#source_review_default_mode")).to_be_visible()
        expect(page.locator("#source_review_max_pages_per_turn")).to_have_attribute("max", "10")
        expect(page.locator("#source_review_max_seed_pages_per_turn")).to_have_attribute("max", "10")
        expect(page.locator("#deep_research_max_user_urls_per_turn")).to_have_attribute("max", "100")
        expect(page.locator("#deep_research_max_search_queries_per_turn")).to_have_attribute("max", "8")
        expect(page.locator("#source_review_max_depth")).to_have_attribute("max", "2")
        expect(page.locator("#source_review_timeout_seconds")).to_have_attribute("max", "30")
        expect(page.locator("#source_review_max_bytes_per_page_mb")).to_have_attribute("max", "5")
        expect(page.locator("#source_review_js_load_more_clicks")).to_have_attribute("max", "12")

        deep_review_toggle = page.locator("#enable_deep_source_review")
        if not deep_review_toggle.is_checked():
            deep_review_toggle.check(force=True)
        expect(page.locator("#source_review_deep_settings")).to_be_visible()
        expect(page.locator("#deep_research_enable_query_planning")).to_have_count(1)
        expect(page.locator("#deep_research_enable_ledger_artifact")).to_have_count(1)
        expect(page.locator("#source_review_enable_llm_planning")).to_have_count(1)

        allowed_domains_editor = page.locator('[data-deep-research-policy="source_review_allowed_domains"]')
        allowed_domains_editor.locator('[data-policy-new-input]').fill("contoso.com")
        allowed_domains_editor.locator('[data-policy-add-button]').click()
        expect(page.locator("#source_review_allowed_domains")).to_have_value("contoso.com")

        allowed_domain_row = allowed_domains_editor.locator('[data-policy-list] input').first
        allowed_domain_row.fill("*.example.org")
        allowed_domain_row.press("Enter")
        expect(page.locator("#source_review_allowed_domains")).to_have_value("*.example.org")

        allowed_domains_editor.locator('[aria-label="Delete policy entry"]').first.click()
        expect(page.locator("#source_review_allowed_domains")).to_have_value("")

        blocked_users_editor = page.locator('[data-deep-research-policy="source_review_blocked_users"]')
        expect(blocked_users_editor.locator('[data-user-search-input]')).to_be_visible()
        expect(blocked_users_editor.locator('[data-user-search-button]')).to_be_visible()
        blocked_users_editor.locator('[data-user-bulk-input]').fill("blocked.user@contoso.com\n00000000-0000-0000-0000-000000000000")
        blocked_users_editor.locator('[data-user-bulk-add-button]').click()
        expect(page.locator("#source_review_blocked_users")).to_have_value("blocked.user@contoso.com\n00000000-0000-0000-0000-000000000000")
    finally:
        context.close()
        browser.close()
        playwright.stop()