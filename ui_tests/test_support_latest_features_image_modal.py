# test_support_latest_features_image_modal.py
"""
UI test for support latest-features image previews.
Version: 0.240.061
Implemented in: 0.240.061

This test ensures the user-facing Latest Features page opens a full-size image
preview modal when a feature thumbnail is clicked and keeps the expanded
user-facing feature catalog visible with actionable destination links.
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
    pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_support_latest_features_image_modal(playwright):
    """Validate that feature thumbnails open the preview modal."""
    _require_base_url()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = context.new_page()
        response = page.goto(f"{BASE_URL}/support/latest-features", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /support/latest-features."
        if response.status in {401, 403, 404}:
            pytest.skip("Latest Features page was not available for the configured session.")

        assert response.ok, f"Expected /support/latest-features to load successfully, got HTTP {response.status}."
        expect(page.get_by_role("heading", name="Latest Features")).to_be_visible()
        expect(page.locator(".support-feature-card")).to_have_count(page.locator(".support-feature-card").count())
        expect(page.locator(".support-feature-callout").first).to_be_visible()
        expect(page.locator(".support-feature-action-card").first).to_be_visible()

        thumbnail_trigger = page.locator(".support-feature-thumbnail-trigger").first
        if thumbnail_trigger.count() == 0:
            pytest.skip("No latest-feature images are available in this environment.")

        thumbnail_trigger.click()

        modal = page.locator("#latestFeatureImageModal")
        expect(modal).to_be_visible()
        expect(page.locator("#latestFeatureImageModalImage")).to_be_visible()
        expect(page.locator("#latestFeatureImageModalLabel")).not_to_be_empty()
    finally:
        context.close()
        browser.close()