# test_workspace_action_identity_modal.py
"""
UI test for workspace action reusable identity selection.
Version: 0.241.095
Implemented in: 0.241.095

This test ensures the workspace action modal loads personal action-capable
identities, lets users select one for a SQL action, and saves only an identity
reference instead of direct credential values.
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
def test_workspace_sql_action_uses_reusable_identity():
    """Validate SQL action creation can save a scoped reusable identity reference."""
    _require_ui_env()
    from playwright.sync_api import expect, sync_playwright

    saved_payloads = []
    validation_requests = []

    playwright_instance = sync_playwright().start()
    browser = playwright_instance.chromium.launch()
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

    def handle_plugin_types(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([
                {
                    "type": "sql_query",
                    "display": "SQL Query",
                    "description": "Execute read-only SQL queries."
                }
            ]),
        )

    def handle_identities(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "identities": [
                    {
                        "id": "identity-userpass-1",
                        "identity_id": "identity-userpass-1",
                        "name": "Reporting SQL User",
                        "usage_contexts": ["action"],
                        "supported_source_types": ["action"],
                        "credentials": {
                            "auth_type": "username_password",
                            "username": "reporting_user",
                            "password_stored": True,
                            "secret_stored": False,
                        },
                    }
                ]
            }),
        )

    def handle_validation(route):
        validation_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"valid": true, "errors": [], "warnings": []}',
        )

    page.route("**/api/user/plugins", handle_plugins)
    page.route("**/api/user/plugins/types", handle_plugin_types)
    page.route("**/api/workspace-identities/personal/identities", handle_identities)
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

        create_button.click()
        modal = page.locator("#plugin-modal")
        expect(modal).to_be_visible()

        page.locator('.action-type-card[data-type="sql_query"]').click()
        modal.get_by_role("button", name="Next").click()
        page.locator("#plugin-display-name").fill("Identity SQL Query")
        modal.get_by_role("button", name="Next").click()

        page.locator('label[for="sql-db-sqlserver"]').click()
        page.locator('label[for="sql-conn-params"]').click()
        page.locator("#sql-server").fill("sql.example.internal")
        page.locator("#sql-database").fill("reporting")

        identity_select = page.locator("#sql-identity-select")
        expect(identity_select).to_be_visible()
        identity_select.select_option("identity-userpass-1")
        expect(page.locator("#sql-auth-credentials")).to_be_hidden()
        expect(page.locator("#sql-auth-type")).to_be_disabled()

        page.locator("#plugin-modal-skip").click()
        modal.get_by_role("button", name="Save Action").click()

        expect(modal).to_be_hidden()
        assert len(validation_requests) == 1, "Expected validation to run once."
        assert len(saved_payloads) == 1, "Expected one workspace action save payload."

        saved_plugin = saved_payloads[0][0]
        assert saved_plugin["type"] == "sql_query"
        assert saved_plugin["identity_id"] == "identity-userpass-1"
        assert saved_plugin["auth"] == {"type": "identity", "identity": "identity-userpass-1"}
        assert saved_plugin["additionalFields"]["identity_auth_type"] == "username_password"
        assert "password" not in saved_plugin["additionalFields"]
        assert "username" not in saved_plugin["additionalFields"]
    finally:
        context.close()
        browser.close()
        playwright_instance.stop()
