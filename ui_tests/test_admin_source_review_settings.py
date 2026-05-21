# test_admin_source_review_settings.py
"""
UI test for Deep Research admin settings.
Version: 0.241.072
Implemented in: 0.241.055
Updated in: 0.241.072

This test ensures the Search & Extract admin tab exposes Deep Research controls,
including bounded review settings, query planning, ledger artifacts, editable domain
rules, app-role policy controls, setup guidance, and the Web Search test workflow.
"""

import json
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
        page.locator('[data-bs-target="#deepResearchInfoModal"]').click()
        deep_research_info_modal = page.locator("#deepResearchInfoModal")
        expect(deep_research_info_modal).to_be_visible()
        expect(deep_research_info_modal).to_contain_text("DeepResearchUser App Role Setup")
        expect(deep_research_info_modal).to_contain_text("Settings Reference")
        expect(deep_research_info_modal).to_contain_text("Allow internal network hostnames")
        expect(deep_research_info_modal).to_contain_text("Playwright Chromium support")
        deep_research_info_modal.locator(".btn-close").click()
        expect(deep_research_info_modal).to_be_hidden()

        page.route(
            "**/api/admin/settings/test_connection",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "success": True,
                    "status": "success",
                    "message": "Web Search test succeeded. The Foundry agent responded to a live web-search prompt.",
                    "details": ["Detected web citations: 1."],
                    "guidance": [],
                    "response_preview": "Microsoft official site: https://www.microsoft.com",
                }),
            ),
        )

        page.evaluate("""
            () => {
                const consent = document.getElementById('web_search_consent_accepted');
                if (consent) {
                    consent.value = 'true';
                }
            }
        """)
        web_search_toggle = page.locator("#enable_web_search")
        if not web_search_toggle.is_checked():
            web_search_toggle.check(force=True)
        expect(page.locator("#web_search_foundry_settings")).to_be_visible()
        page.locator("#web_search_foundry_endpoint").fill("https://contoso.services.ai.azure.com/api/projects/simplechat")
        page.locator("#web_search_foundry_api_version").fill("v1")
        page.locator("#web_search_foundry_agent_id").fill("asst_test123")
        page.locator("#test_web_search_button").click()
        expect(page.locator("#test_web_search_result")).to_contain_text("Web Search test passed")
        expect(page.locator("#test_web_search_result")).to_contain_text("Microsoft official site")

        source_review_toggle = page.locator("#enable_source_review")
        if source_review_toggle.is_checked():
            source_review_toggle.uncheck(force=True)
        source_review_toggle.check(force=True)

        expect(page.locator("#source_review_settings")).to_be_visible()
        expect(page.locator("#source_review_default_mode")).to_be_visible()
        expect(page.locator("#source_review_default_mode")).to_have_value("auto_with_web_search")
        expect(page.locator("#source_review_max_pages_per_turn")).to_have_attribute("max", "10")
        expect(page.locator("#source_review_max_pages_per_turn")).to_have_value("10")
        expect(page.locator("#source_review_max_seed_pages_per_turn")).to_have_attribute("max", "10")
        expect(page.locator("#source_review_max_seed_pages_per_turn")).to_have_value("10")
        expect(page.locator("#deep_research_max_user_urls_per_turn")).to_have_attribute("max", "100")
        expect(page.locator("#deep_research_max_user_urls_per_turn")).to_have_value("100")
        expect(page.locator("#deep_research_max_search_queries_per_turn")).to_have_attribute("max", "8")
        expect(page.locator("#deep_research_max_search_queries_per_turn")).to_have_value("8")
        expect(page.locator("#source_review_max_depth")).to_have_attribute("max", "2")
        expect(page.locator("#source_review_max_depth")).to_have_value("2")
        expect(page.locator("#source_review_timeout_seconds")).to_have_attribute("max", "30")
        expect(page.locator("#source_review_timeout_seconds")).to_have_value("30")
        expect(page.locator("#source_review_max_bytes_per_page_mb")).to_have_attribute("max", "5")
        expect(page.locator("#source_review_max_bytes_per_page_mb")).to_have_value("5")
        expect(page.locator("#source_review_js_load_more_clicks")).to_have_attribute("max", "12")
        expect(page.locator("#source_review_js_load_more_clicks")).to_have_value("12")
        expect(page.locator("#require_member_of_deep_research_user")).to_have_count(1)
        expect(page.locator("label[for='require_member_of_deep_research_user']")).to_contain_text("DeepResearchUser")
        expect(page.locator("#source_review_allow_internal_hosts")).to_have_count(1)
        expect(page.locator("label[for='source_review_allow_internal_hosts']")).to_contain_text("internal network hostnames")

        deep_review_toggle = page.locator("#enable_deep_source_review")
        if not deep_review_toggle.is_checked():
            deep_review_toggle.check(force=True)
        expect(page.locator("#source_review_deep_settings")).to_be_visible()
        expect(page.locator("#deep_research_enable_query_planning")).to_have_count(1)
        expect(page.locator("#deep_research_enable_ledger_artifact")).to_have_count(1)
        expect(page.locator("#source_review_enable_llm_planning")).to_have_count(1)
        expect(page.locator("#source_review_js_runtime_status")).to_be_visible()
        js_rendering_toggle = page.locator("#source_review_allow_js_rendering")
        js_runtime_status = page.locator("#source_review_js_runtime_status").inner_text()
        if "Chromium launch verified" in js_runtime_status:
            expect(js_rendering_toggle).to_be_enabled()
        else:
            expect(js_rendering_toggle).to_be_disabled()

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

        expect(page.locator('[data-deep-research-policy="source_review_blocked_users"]')).to_have_count(0)
        expect(page.locator("#source_review_blocked_users")).to_have_count(0)
        expect(page.locator("#source_review_allowed_users")).to_have_count(0)
        expect(page.locator("#manage_deep_research_allowed_users")).to_have_count(0)
        expect(page.locator("#deepResearchAllowedUsersModal")).to_have_count(0)
    finally:
        context.close()
        browser.close()
        playwright.stop()