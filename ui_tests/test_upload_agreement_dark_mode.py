# test_upload_agreement_dark_mode.py
"""
UI test for upload agreement dark mode readability.
Version: 0.239.166
Implemented in: 0.239.166

This test ensures the upload agreement modal uses the dark-mode-safe light
surface styling so the agreement text remains readable when the app theme is
dark.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_upload_agreement_modal_uses_dark_mode_safe_surface(playwright):
    """Validate the upload agreement content surface remains readable in dark mode."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")

        if page.locator("#userAgreementUploadModal").count() == 0:
            pytest.skip("User agreement upload modal is not enabled in this environment.")

        page.evaluate(
            """
            () => {
                document.documentElement.setAttribute('data-bs-theme', 'dark');
                const content = document.getElementById('userAgreementUploadContent');
                if (content) {
                    content.textContent = 'Sample agreement content for dark mode verification.';
                }
                const modalEl = document.getElementById('userAgreementUploadModal');
                if (modalEl && window.bootstrap) {
                    bootstrap.Modal.getOrCreateInstance(modalEl).show();
                }
            }
            """
        )

        expect(page.locator("#userAgreementUploadModal")).to_be_visible()
        content_class_name = page.locator("#userAgreementUploadContent").evaluate(
            "node => node.className"
        )
        assert "bg-light" in content_class_name

        colors = page.locator("#userAgreementUploadContent").evaluate(
            """
            node => {
                const styles = getComputedStyle(node);
                return {
                    background: styles.backgroundColor,
                    color: styles.color
                };
            }
            """
        )

        assert colors["background"] != "rgb(248, 249, 250)"
        assert colors["background"] != colors["color"]
    finally:
        context.close()
        browser.close()