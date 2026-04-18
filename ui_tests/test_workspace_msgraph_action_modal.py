# test_workspace_msgraph_action_modal.py
"""
UI test for the workspace Microsoft Graph action modal.
Version: 0.241.037
Implemented in: 0.241.037

This test ensures users can select the Microsoft Graph action type,
configure its default capabilities without exposing a user-editable URL,
review the capability summary, and complete validation plus save without
calling the admin-only validation endpoint.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_workspace_msgraph_action_modal(playwright):
    """Validate that the workspace action modal exposes the dedicated Microsoft Graph flow."""
    _require_ui_env()

    validation_requests = []
    admin_validation_requests = []
    saved_payloads = []

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    def handle_plugins(route):
        request = route.request
        if request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body="[]")
            return

        saved_payloads.append(json.loads(request.post_data or "[]"))
        route.fulfill(status=200, content_type="application/json", body='{"success": true}')

    def handle_validation(route):
        validation_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"valid": true, "errors": [], "warnings": []}',
        )

    def handle_admin_validation(route):
        admin_validation_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=418,
            content_type="application/json",
            body='{"error": "unexpected admin validation route"}',
        )

    page.route("**/api/user/plugins", handle_plugins)
    page.route("**/api/plugins/validate", handle_validation)
    page.route("**/api/admin/plugins/validate", handle_admin_validation)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /workspace."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."
        expect(page.locator("#documents-tab")).to_be_visible()

        plugins_tab_button = page.locator("#plugins-tab-btn")
        if plugins_tab_button.count() == 0:
            pytest.skip("Workspace actions are not enabled in this environment.")

        plugins_tab_button.click()

        create_button = page.locator("#create-plugin-btn")
        if create_button.count() == 0:
            pytest.skip("Workspace action creation is not available in this environment.")

        expect(create_button).to_be_visible()
        create_button.click()

        modal = page.locator("#plugin-modal")
        expect(modal).to_be_visible()

        msgraph_card = page.locator('.action-type-card[data-type="msgraph"]')
        expect(msgraph_card).to_have_count(1)
        msgraph_card.click()

        modal.get_by_role("button", name="Next").click()
        page.locator("#plugin-display-name").fill("Microsoft Graph Workspace Tools")
        modal.get_by_role("button", name="Next").click()

        expect(page.locator("#msgraph-config-section")).to_be_visible()
        expect(page.locator("#generic-config-section")).to_be_hidden()
        expect(page.locator("#simplechat-config-section")).to_be_hidden()
        expect(page.locator("#msgraph-config-section")).to_contain_text("delegated permissions")

        get_profile_toggle = page.locator("#msgraph-capability-get_my_profile")
        security_alerts_toggle = page.locator("#msgraph-capability-get_my_security_alerts")
        create_invite_toggle = page.locator("#msgraph-capability-create_calendar_invite")
        read_mail_toggle = page.locator("#msgraph-capability-get_my_messages")
        get_profile_toggle.uncheck()
        security_alerts_toggle.uncheck()
        expect(create_invite_toggle).to_be_checked()
        expect(read_mail_toggle).to_be_checked()

        page.locator("#plugin-modal-skip").click()

        expect(page.locator("#summary-msgraph-section")).to_be_visible()
        expect(page.locator("#summary-plugin-database-type")).to_have_text("Built-in Microsoft Graph action")
        expect(page.locator("#summary-plugin-endpoint-row")).to_be_hidden()
        expect(page.locator("#summary-msgraph-enabled-list")).to_contain_text("Create calendar invites")
        expect(page.locator("#summary-msgraph-enabled-list")).to_contain_text("Read my mail")
        expect(page.locator("#summary-msgraph-disabled-list")).to_contain_text("Read my profile")
        expect(page.locator("#summary-msgraph-disabled-list")).to_contain_text("Read my security alerts")

        modal.get_by_role("button", name="Save Action").click()

        expect(modal).to_be_hidden()
        assert len(validation_requests) == 1, "Expected the shared validation endpoint to be called once."
        assert not admin_validation_requests, "Workspace action save should not call the admin validation endpoint."
        assert len(saved_payloads) == 1, "Expected the workspace action save request to be submitted once."

        saved_plugin = saved_payloads[0][0]
        assert saved_plugin["type"] == "msgraph"
        assert saved_plugin["name"] == "microsoft_graph_workspace_tools"
        assert saved_plugin["endpoint"] == "https://graph.microsoft.com"
        assert saved_plugin["auth"]["type"] == "user"
        capabilities = saved_plugin["additionalFields"]["msgraph_capabilities"]
        assert capabilities["get_my_profile"] is False
        assert capabilities["get_my_security_alerts"] is False
        assert capabilities["create_calendar_invite"] is True
        assert capabilities["get_my_messages"] is True
    finally:
        context.close()
        browser.close()