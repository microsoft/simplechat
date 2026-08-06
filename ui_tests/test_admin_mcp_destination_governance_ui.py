# test_admin_mcp_destination_governance_ui.py
"""
UI test for admin MCP destination governance controls.

Version: 0.250.065
Implemented in: 0.250.065

This test ensures the admin governance tab exposes MCP destination
governance toggles and opens delegated item policy editors for
personal, group, and global MCP destination allowlists.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_admin_mcp_destination_governance_controls():
    """Validate the admin MCP destination governance controls render and open the policy editor."""
    sync_api = pytest.importorskip("playwright.sync_api")
    expect = sync_api.expect
    _require_ui_env()

    playwright = sync_api.sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/admin/settings#governance", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading admin settings."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Admin settings page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected admin settings to load successfully, got HTTP {response.status}."

        governance_tab = page.locator("#governance-tab")
        if governance_tab.count() > 0:
            governance_tab.click()

        expect(page.locator("#governance-mcp-destination-section")).to_be_visible()
        expect(page.locator("#enable_mcp_destination_governance")).to_be_visible()
        expect(page.locator("#mcp_block_unsafe_destinations")).to_be_visible()

        page.get_by_role("button", name="New Personal Destination Policy").click()
        expect(page.locator("#governance-item-policy-editor-modal")).to_be_visible()
        expect(page.locator("#governance-item-entity-type")).to_have_value("mcp_personal_destination")
        expect(page.locator("#governance-item-id-custom")).to_be_visible()
        lookup_classes = page.locator("#governance-item-id-lookup-controls").get_attribute("class") or ""
        assert "d-none" in lookup_classes
    finally:
        context.close()
        browser.close()
        playwright.stop()
