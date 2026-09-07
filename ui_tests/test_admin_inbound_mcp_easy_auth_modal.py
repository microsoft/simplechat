# test_admin_inbound_mcp_easy_auth_modal.py
"""
UI test for the inbound MCP Easy Auth verification modal.

Version: 0.261.002
Implemented in: 0.250.072
Cloud-aware script improvements implemented in: 0.250.073
Script copy and authsettingsV2 GET fix implemented in: 0.250.074
Delegated scope default and setup preflight implemented in: 0.250.075
Inbound MCP user/app role split implemented in: 0.250.078
OAuth authorization server metadata bridge implemented in: 0.250.085
Public HTTPS metadata URL normalization implemented in: 0.250.086
Protected-resource metadata aliases implemented in: 0.250.087
Easy Auth restart reminder implemented in: 0.250.088
Personal workflow execution tool implemented in: 0.250.090
Inbound MCP object-list settings implemented in: 0.250.091
Inbound MCP disabled-state guidance implemented in: 0.261.002

This test ensures enabling inbound MCP from Admin Settings requires the Easy Auth
exclusion modal, keeps the runtime gate disabled on failed verification, and
allows the toggle only after the verification endpoint succeeds.
"""

import json
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
def test_admin_inbound_mcp_easy_auth_modal_blocks_until_verified():
    """Validate the inbound MCP Easy Auth modal blocks enablement until verification succeeds."""
    sync_api = pytest.importorskip("playwright.sync_api")
    expect = sync_api.expect
    _require_ui_env()

    verification_responses = [
        {
            "success": False,
            "message": "One or more inbound MCP endpoints are still intercepted before reaching SimpleChat.",
            "endpoints": [
                {
                    "path": "/.well-known/oauth-protected-resource",
                    "status_code": 302,
                    "success": False,
                    "message": "App Service Authentication redirected this endpoint to sign-in.",
                }
            ],
        },
        {
            "success": True,
            "message": "All inbound MCP Easy Auth exclusions are reachable.",
            "endpoints": [
                {
                    "path": "/.well-known/oauth-protected-resource",
                    "status_code": 200,
                    "success": True,
                    "message": "Protected resource metadata returned JSON successfully.",
                },
                {
                    "path": "/.well-known/oauth-protected-resource/api/mcp",
                    "status_code": 200,
                    "success": True,
                    "message": "Protected resource metadata returned JSON successfully.",
                },
                {
                    "path": "/.well-known/oauth-protected-resource/mcp",
                    "status_code": 200,
                    "success": True,
                    "message": "Protected resource metadata returned JSON successfully.",
                },
                {
                    "path": "/.well-known/oauth-authorization-server",
                    "status_code": 200,
                    "success": True,
                    "message": "OAuth authorization server metadata returned JSON successfully.",
                },
                {
                    "path": "/api/mcp",
                    "status_code": 401,
                    "success": True,
                    "message": "Endpoint reached SimpleChat and returned the expected unauthenticated JSON response.",
                },
                {
                    "path": "/api/mcp/health",
                    "status_code": 401,
                    "success": True,
                    "message": "Endpoint reached SimpleChat and returned the expected unauthenticated JSON response.",
                },
            ],
        },
    ]

    playwright = sync_api.sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    verification_index = {"value": 0}

    def fulfill_verification(route):
        index = min(verification_index["value"], len(verification_responses) - 1)
        payload = verification_responses[index]
        verification_index["value"] += 1
        route.fulfill(
            status=200 if payload["success"] else 409,
            content_type="application/json",
            body=json.dumps(payload),
        )

    try:
        page.route("**/api/admin/settings/inbound-mcp/easy-auth-check", fulfill_verification)
        response = page.goto(f"{BASE_URL}/admin/settings#inbound-mcp", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading admin settings."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Admin settings page unavailable in this environment (HTTP {response.status}).")
        assert response.ok, f"Expected admin settings to load successfully, got HTTP {response.status}."

        inbound_tab = page.locator("#inbound-mcp-tab")
        if inbound_tab.count() > 0:
            inbound_tab.click()

        enable_toggle = page.locator("#enable_inbound_mcp_server")
        if enable_toggle.count() == 0:
            pytest.skip("Inbound MCP UI is not enabled for this environment.")
        if enable_toggle.is_checked():
            pytest.skip("Inbound MCP is already enabled in this environment.")

        enable_toggle.click()
        expect(page.locator("#inboundMcpEasyAuthModal")).to_be_visible()
        expect(page.locator("#inboundMcpEasyAuthModal")).to_contain_text("Derived deployment values")
        expect(page.locator("#inboundMcpEasyAuthModal")).to_contain_text("simplechat-authsettingsV2-backup")
        expect(page.locator("#inboundMcpEasyAuthModal")).to_contain_text("az login --tenant")
        expect(page.locator("#inboundMcpEasyAuthModal")).to_contain_text("Delegated scope")
        expect(page.locator("#inboundMcpEasyAuthModal")).to_contain_text("User role")
        expect(page.locator("#inboundMcpEasyAuthModal")).to_contain_text("App-only role")
        expect(page.locator("#inbound-mcp-copy-script")).to_be_visible()
        expect(page.locator("#inbound-mcp-easy-auth-script-code")).to_contain_text("az rest --method get --url $authSettingsUrl")
        expect(page.locator("#inbound-mcp-easy-auth-script-code")).to_contain_text("az ad app show --id $simpleChatApiClientId")
        expect(page.locator("#inbound-mcp-easy-auth-script-code")).to_contain_text("/.well-known/oauth-protected-resource/api/mcp")
        expect(page.locator("#inbound-mcp-easy-auth-script-code")).to_contain_text("/.well-known/oauth-authorization-server")
        expect(page.locator("#inbound-mcp-easy-auth-script-code")).to_contain_text("Restart your web app now")
        expect(page.locator("#inbound-mcp-easy-auth-script-code")).to_contain_text("InboundMCPUserAccess")
        expect(page.locator("#inbound-mcp-easy-auth-script-code")).to_contain_text("InboundMCPAppAccess")
        expect(enable_toggle).not_to_be_checked()

        page.locator("#inbound-mcp-easy-auth-confirm").check()
        page.locator("#inbound-mcp-easy-auth-verify").click()
        expect(page.locator("#inbound-mcp-easy-auth-status")).to_contain_text("still intercepted")
        expect(enable_toggle).not_to_be_checked()

        page.locator("#inbound-mcp-easy-auth-verify").click()
        expect(page.locator("#inboundMcpEasyAuthModal")).to_be_hidden()
        expect(enable_toggle).to_be_checked()
    finally:
        context.close()
        browser.close()
        playwright.stop()
