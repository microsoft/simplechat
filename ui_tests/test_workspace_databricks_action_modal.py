# test_workspace_databricks_action_modal.py
"""
UI test for the workspace Databricks action modal.

Version: 0.241.104
Implemented in: 0.241.104

This test ensures users can select the Databricks action type, configure an
Azure Commercial workspace and SQL Warehouse, review the summary, and save the
expected action manifest through the shared workspace validation flow.
"""

import json
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
def test_workspace_databricks_action_modal():
    """Validate the workspace action modal exposes the Databricks-specific flow."""
    _require_ui_env()
    playwright_sync_api = pytest.importorskip("playwright.sync_api")
    expect = playwright_sync_api.expect

    validation_requests = []
    admin_validation_requests = []
    saved_payloads = []
    workspace_url = "https://adb-1234567890123456.7.azuredatabricks.net/api/2.0/sql/statements"
    normalized_workspace_url = "https://adb-1234567890123456.7.azuredatabricks.net"

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

            databricks_card = page.locator('.action-type-card[data-type="databricks"]')
            expect(databricks_card).to_have_count(1)
            databricks_card.click()

            modal.get_by_role("button", name="Next").click()
            page.locator("#plugin-display-name").fill("Commercial Databricks SQL")
            modal.get_by_role("button", name="Next").click()

            expect(page.locator("#databricks-config-section")).to_be_visible()
            expect(page.locator("#generic-config-section")).to_be_hidden()
            expect(page.locator("#sql-config-section")).to_be_hidden()

            page.locator("#databricks-workspace-url").fill(workspace_url)
            page.locator("#databricks-warehouse-id").fill("warehouse-123")
            page.locator("#databricks-catalog").fill("main")
            page.locator("#databricks-schema").fill("analytics")
            page.locator("#databricks-auth-method").select_option("pat")
            page.locator("#databricks-token").fill("test-token")
            page.locator("#databricks-max-rows").fill("250")
            page.locator("#databricks-timeout").fill("45")
            page.locator("#databricks-wait-timeout").fill("20")

            page.locator("#plugin-modal-skip").click()

            expect(page.locator("#summary-databricks-section")).to_be_visible()
            expect(page.locator("#summary-plugin-database-type")).to_have_text("Azure Commercial Databricks SQL Warehouse")
            expect(page.locator("#summary-plugin-auth")).to_have_text("Personal Access Token")
            expect(page.locator("#summary-plugin-endpoint")).to_have_text(normalized_workspace_url)
            expect(page.locator("#summary-databricks-warehouse-id")).to_have_text("warehouse-123")
            expect(page.locator("#summary-databricks-namespace")).to_have_text("main.analytics")
            expect(page.locator("#summary-databricks-max-rows")).to_have_text("250")

            modal.get_by_role("button", name="Save Action").click()

            expect(modal).to_be_hidden()
            assert len(validation_requests) == 1, "Expected the shared validation endpoint to be called once."
            assert not admin_validation_requests, "Workspace action save should not call the admin validation endpoint."
            assert len(saved_payloads) == 1, "Expected the workspace action save request to be submitted once."

            saved_plugin = saved_payloads[0][0]
            assert saved_plugin["type"] == "databricks"
            assert saved_plugin["name"] == "commercial_databricks_sql"
            assert saved_plugin["endpoint"] == normalized_workspace_url
            assert saved_plugin["auth"]["type"] == "key"
            assert saved_plugin["auth"]["key"] == "test-token"

            additional_fields = saved_plugin["additionalFields"]
            assert additional_fields["cloud"] == "azure_commercial"
            assert additional_fields["workspace_url"] == normalized_workspace_url
            assert additional_fields["auth_method"] == "pat"
            assert additional_fields["warehouse_id"] == "warehouse-123"
            assert additional_fields["catalog"] == "main"
            assert additional_fields["schema"] == "analytics"
            assert additional_fields["read_only"] is True
            assert additional_fields["max_rows"] == 250
            assert additional_fields["timeout"] == 45
            assert additional_fields["wait_timeout"] == 20
        finally:
            context.close()
            browser.close()