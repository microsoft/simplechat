# test_admin_inbound_mcp_governance_ui.py
"""
UI test for inbound MCP governance policy creation controls.

Version: 0.250.081
Implemented in: 0.250.077
Inbound MCP restricted policy defaults implemented in: 0.250.078
MCP governance help modal implemented in: 0.250.079
Simplified inbound MCP access/source governance implemented in: 0.250.080
Single inbound MCP access policy implemented in: 0.250.081

This test ensures Admin Settings exposes inbound MCP governance policy
controls and can open the delegated item policy editor for inbound MCP access.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "") or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    """Skip unless an authenticated admin Playwright environment is configured."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE to a valid admin storage state file.")


@pytest.mark.ui
def test_admin_inbound_mcp_governance_policy_editor_controls():
    """Validate inbound MCP governance controls render and open the item policy editor."""
    sync_api = pytest.importorskip("playwright.sync_api")
    expect = sync_api.expect
    _require_ui_env()

    playwright = sync_api.sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
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

        inbound_section = page.locator("#governance-inbound-mcp-section")
        expect(inbound_section).to_be_visible()
        expect(inbound_section).to_contain_text("Inbound MCP Access Governance")
        expect(inbound_section).to_contain_text("Minimum policy required for inbound MCP")
        expect(inbound_section).to_contain_text("New Inbound MCP Access Policy")
        expect(inbound_section.locator(".governance-policy-help-btn")).to_have_count(1)
        expect(page.locator("#governance-mcp-destination-section .governance-policy-help-btn")).to_have_count(3)

        page.locator(".governance-policy-help-btn[data-governance-help-key=\"inbound_mcp_access\"]").click()
        help_modal = page.locator("#governance-policy-help-modal")
        expect(help_modal).to_be_visible()
        expect(help_modal).to_contain_text("Inbound MCP access policy")
        expect(help_modal).to_contain_text("Item ID: inbound_mcp.")
        page.keyboard.press("Escape")
        expect(help_modal).to_be_hidden()

        page.locator(".governance-new-inbound-mcp-policy-btn[data-governance-inbound-mcp-entity=\"inbound_mcp_access\"]").click()
        editor = page.locator("#governance-item-policy-editor-modal")
        expect(editor).to_be_visible()
        expect(page.locator("#governance-item-entity-type")).to_have_value("inbound_mcp_access")
        expect(page.locator("#governance-item-id-custom")).to_have_value("inbound_mcp")
        expect(page.locator("#governance-item-allow-all")).not_to_be_checked()
    finally:
        context.close()
        browser.close()
        playwright.stop()
