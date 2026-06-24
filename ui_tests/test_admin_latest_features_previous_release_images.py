# test_admin_latest_features_previous_release_images.py
"""
UI test for admin Latest Features previous-release images and optional media.
Version: 0.250.036
Implemented in: 0.241.002; 0.250.028; 0.250.036

This test ensures the admin Latest Features page can expand the Previous
Release Features section and open one of its thumbnails in the shared image
preview modal. It also validates that informational latest-feature cards can
render without screenshot thumbnails and that the admin Agents Catalog card
surfaces its current-release screenshot.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _require_storage_state():
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_admin_latest_features_previous_release_images():
    """Validate that previous-release thumbnails open the shared admin preview modal."""
    _require_base_url()
    _require_storage_state()

    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install Playwright to run this UI test.")

    with sync_playwright() as playwright:
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

            latest_features_pane = page.locator("#latest-features")
            if latest_features_pane.count() == 0:
                pytest.skip("Latest Features tab was not available in this environment.")

            agents_catalog_card = page.locator("#latest-features-admin-release-250-agents-catalog-card")
            expect(agents_catalog_card).to_be_visible()
            expect(agents_catalog_card.get_by_role("heading", name="Agents Catalog Administration")).to_be_visible()
            agents_catalog_card.get_by_role("link", name="Show Details").click()
            expect(agents_catalog_card.get_by_role("link", name="Open Agents Page Settings")).to_be_visible()
            expect(agents_catalog_card.locator("img[src*='admin_release_250_agents_catalog.png']")).to_be_visible()

            reliability_card = page.locator("#latest-features-admin-release-250-bug-fixes-card")
            expect(reliability_card).to_be_visible()
            reliability_card.get_by_role("link", name="Show Details").click()
            expect(reliability_card.get_by_role("heading", name="Rollout notes")).to_be_visible()
            expect(reliability_card.locator(".latest-feature-thumbnail-trigger")).to_have_count(0)

            previous_release_toggle = page.locator("a[href='#adminLatestFeaturesPreviousRelease']")
            if previous_release_toggle.count() == 0:
                pytest.skip("Previous Release Features section was not available in this environment.")

            previous_release_toggle.first.click()
            expect(page.locator("#adminLatestFeaturesPreviousRelease")).to_be_visible()

            previous_release_thumbnail = page.locator("#adminLatestFeaturesPreviousRelease .latest-feature-thumbnail-trigger").first
            if previous_release_thumbnail.count() == 0:
                pytest.skip("No previous-release thumbnails are available in this environment.")

            previous_release_thumbnail.click()

            modal = page.locator("#latestFeatureImageModal")
            expect(modal).to_be_visible()
            expect(page.locator("#latestFeatureImageModalImage")).to_be_visible()
            expect(page.locator("#latestFeatureImageModalLabel")).not_to_be_empty()
        finally:
            context.close()
            browser.close()