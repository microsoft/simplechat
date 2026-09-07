# test_admin_inbound_mcp_governance_ui.py
"""
UI test for inbound MCP governance policy creation controls.

Version: 0.261.002
Implemented in: 0.250.077
Inbound MCP restricted policy defaults implemented in: 0.250.078
MCP governance help modal implemented in: 0.250.079
Simplified inbound MCP access/source governance implemented in: 0.250.080
Single inbound MCP access policy implemented in: 0.250.081
Personal workflow execution tool implemented in: 0.250.090
Inbound MCP source governance controls implemented in: 0.250.091
Inbound MCP source-only governance implemented in: 0.250.092
Inbound MCP source governance CTA guidance implemented in: 0.250.093
Inbound MCP admin throttle controls implemented in: 0.250.097
Inbound MCP observability query panel implemented in: 0.250.098
Inbound MCP disabled-state guidance implemented in: 0.261.002

This test ensures Admin Settings exposes inbound MCP source governance policy
controls when the preview UI is enabled, explains how to enable the preview UI
when it is disabled, and can open the delegated item policy editor for source
policies.
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
        response = page.goto(f"{BASE_URL}/admin/settings#inbound-mcp", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading admin settings."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Admin settings page unavailable in this environment (HTTP {response.status}).")
        assert response.ok, f"Expected admin settings to load successfully, got HTTP {response.status}."

        inbound_tab = page.locator("#inbound-mcp-tab")
        if inbound_tab.count() > 0:
            inbound_tab.click()

        inbound_config = page.locator("#inbound-mcp-configuration")
        expect(inbound_config).to_be_visible()
        enable_toggle = page.locator("#enable_inbound_mcp_server")
        if enable_toggle.count() == 0:
            expect(inbound_config).to_contain_text("Inbound MCP admin UI is disabled")
            expect(inbound_config).to_contain_text("ENABLE_MCP_UI")
            return

        expect(inbound_config).to_contain_text("admins must still create an inbound MCP source governance policy")
        expect(inbound_config).to_contain_text("Create Wildcard Source Policy")
        expect(inbound_config).to_contain_text("Create Source Policy")
        expect(inbound_config).to_contain_text("Request Size & Throttling")
        expect(inbound_config).to_contain_text("Enable tool throttles")
        expect(page.locator("#enable_inbound_mcp_rate_limits")).to_be_visible()
        expect(page.locator("#inbound_mcp_max_request_bytes")).to_be_visible()
        expect(page.locator("#inbound_mcp_rate_limit_window_seconds")).to_be_visible()
        expect(inbound_config).not_to_contain_text("Default on creates a locked governance policy")
        inbound_config.locator("button[data-bs-target=\"#inboundMcpInfoModal\"]").click()
        overview_modal = page.locator("#inboundMcpInfoModal")
        expect(overview_modal).to_be_visible()
        expect(overview_modal).to_contain_text("Application Insights starter queries")
        expect(overview_modal).to_contain_text("Request and failure trends")
        expect(overview_modal).to_contain_text("Rate-limit denials")
        expect(overview_modal.locator(".inbound-mcp-kql-copy-btn")).to_have_count(4)
        expect(overview_modal.locator("#inbound-mcp-kql-tool-latency")).to_contain_text("percentile")
        page.keyboard.press("Escape")
        expect(overview_modal).to_be_hidden()

        governance_tab = page.locator("#mcp-governance-tab")
        if governance_tab.count() > 0:
            governance_tab.click()

        inbound_section = page.locator("#governance-inbound-mcp-section")
        expect(inbound_section).to_be_visible()
        expect(inbound_section).to_contain_text("Inbound MCP Source Governance")
        expect(inbound_section).to_contain_text("Policy required for inbound MCP")
        expect(inbound_section).to_contain_text("New Inbound MCP Source Access Policy")
        expect(inbound_section.locator(".governance-policy-help-btn")).to_have_count(1)
        expect(page.locator("#governance-mcp-destination-section .governance-policy-help-btn")).to_have_count(3)

        help_modal = page.locator("#governance-policy-help-modal")
        page.locator(".governance-policy-help-btn[data-governance-help-key=\"inbound_mcp_source\"]").click()
        expect(help_modal).to_be_visible()
        expect(help_modal).to_contain_text("Inbound MCP source policy")
        expect(help_modal).to_contain_text("choose * for any accepted source")
        page.keyboard.press("Escape")
        expect(help_modal).to_be_hidden()

        inbound_section.locator(".governance-new-inbound-mcp-policy-btn[data-governance-inbound-mcp-entity=\"inbound_mcp_source\"]").click()
        editor = page.locator("#governance-item-policy-editor-modal")
        expect(editor).to_be_visible()
        expect(page.locator("#governance-item-entity-type")).to_have_value("inbound_mcp_source")
        expect(page.locator("#governance-item-id")).to_have_value("*")
        expect(page.locator("#governance-item-allow-all")).not_to_be_checked()
    finally:
        context.close()
        browser.close()
        playwright.stop()
