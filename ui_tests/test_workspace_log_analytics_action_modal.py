# test_workspace_log_analytics_action_modal.py
"""
UI test for the workspace Log Analytics action modal.

Version: 0.250.217
Implemented in: 0.250.217

This test ensures the Log Analytics action type now uses a dedicated Step 3
configuration section instead of the generic endpoint form, reveals the custom
cloud fields only when the custom cloud is selected, validates required fields,
and saves a manifest that keeps the required query_history additional field.

Refs microsoft/simplechat#1267
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}
WORKSPACE_ID = "11111111-2222-3333-4444-555555555555"


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_workspace_log_analytics_action_modal():
    """Validate the dedicated Log Analytics configuration section and save payload."""
    _require_ui_env()
    playwright_sync_api = pytest.importorskip("playwright.sync_api")
    expect = playwright_sync_api.expect

    validation_requests = []
    saved_payloads = []

    with playwright_sync_api.sync_playwright() as playwright:
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

        page.route("**/api/user/plugins", handle_plugins)
        page.route("**/api/plugins/validate", handle_validation)

        try:
            response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
            assert response is not None, "Expected a navigation response when loading /workspace."

            if response.status in SKIP_RESPONSE_CODES:
                pytest.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")

            assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

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

            log_analytics_card = page.locator('.action-type-card[data-type="log_analytics"]')
            if log_analytics_card.count() == 0:
                pytest.skip("The Log Analytics action type is not available in this environment.")
            log_analytics_card.click()

            modal.get_by_role("button", name="Next").click()
            page.locator("#plugin-display-name").fill("Platform Logs")
            modal.get_by_role("button", name="Next").click()

            expect(page.locator("#step-3-title")).to_have_text("Log Analytics Configuration")
            expect(page.locator("#log-analytics-config-section")).to_be_visible()
            expect(page.locator("#generic-config-section")).to_be_hidden()
            expect(page.locator("#sql-config-section")).to_be_hidden()

            # Custom cloud fields stay hidden until the custom cloud is selected.
            expect(page.locator("#log-analytics-custom-cloud-group")).to_be_hidden()
            page.locator("#log-analytics-cloud").select_option("custom")
            expect(page.locator("#log-analytics-custom-cloud-group")).to_be_visible()
            page.locator("#log-analytics-cloud").select_option("public")
            expect(page.locator("#log-analytics-custom-cloud-group")).to_be_hidden()

            # Service principal fields appear only for service principal authentication.
            expect(page.locator("#log-analytics-auth-tenant-id-group")).to_be_hidden()
            page.locator("#log-analytics-auth-method").select_option("servicePrincipal")
            expect(page.locator("#log-analytics-auth-tenant-id-group")).to_be_visible()
            expect(page.locator("#log-analytics-auth-key-group")).to_be_visible()
            page.locator("#log-analytics-auth-method").select_option("identity")
            expect(page.locator("#log-analytics-auth-tenant-id-group")).to_be_hidden()

            # A missing workspace ID blocks navigation to the next step.
            modal.get_by_role("button", name="Next").click()
            expect(page.locator("#log-analytics-config-section")).to_be_visible()

            page.locator("#log-analytics-workspace-id").fill(WORKSPACE_ID)
            page.locator("#plugin-modal-skip").click()

            expect(page.locator("#summary-plugin-database-type")).to_have_text("Azure Log Analytics workspace")
            expect(page.locator("#summary-plugin-endpoint")).to_have_text("https://api.loganalytics.io")

            modal.get_by_role("button", name="Save Action").click()

            expect(modal).to_be_hidden()
            assert len(validation_requests) == 1, "Expected the shared validation endpoint to be called once."
            assert len(saved_payloads) == 1, "Expected the workspace action save request to be submitted once."

            saved_plugin = saved_payloads[0][0]
            assert saved_plugin["type"] == "log_analytics"
            assert saved_plugin["name"] == "platform_logs"
            assert saved_plugin["endpoint"] == "https://api.loganalytics.io"
            assert saved_plugin["auth"]["type"] == "identity"

            additional_fields = saved_plugin["additionalFields"]
            assert additional_fields["workspaceId"] == WORKSPACE_ID
            assert additional_fields["cloud"] == "public"
            assert additional_fields["query_history"] == [], (
                "New Log Analytics actions must save an empty query_history list."
            )
            assert "authorityHost" not in additional_fields, (
                "Custom cloud fields must be omitted for non-custom clouds."
            )
            assert "endpointOverride" not in additional_fields, (
                "Custom cloud fields must be omitted for non-custom clouds."
            )
        finally:
            context.close()
            browser.close()
