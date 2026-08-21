# test_workspace_action_test_connection_controls.py
"""
UI test for the workspace action modal Test Connection controls.

Version: 0.250.217
Implemented in: 0.250.217

This test ensures every action type that supports connection testing renders a
Test Connection button in Step 3, posts the collected configuration to its own
backend route, and renders success, failure, and missing-field states as visible
Bootstrap alerts without leaving the modal.

Refs microsoft/simplechat#1267
"""

import json
import os
import re
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}

OPENAPI_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {"/status": {"get": {"operationId": "getStatus", "summary": "Status"}}},
}


def _fill_openapi(page):
    page.locator("#plugin-endpoint").fill("https://api.example.com")
    page.evaluate(
        """(spec) => {
            const fileInput = document.getElementById('plugin-openapi-file');
            fileInput.dataset.fileId = 'ui-test-spec';
            fileInput.dataset.specContent = JSON.stringify(spec);
        }""",
        OPENAPI_SPEC,
    )


def _fill_azure_maps(page):
    page.locator("#azure-maps-key").fill("maps-key-123")


def _fill_blob_storage(page):
    page.locator("#blob-storage-connection-string").fill(
        "DefaultEndpointsProtocol=https;AccountName=uitest;AccountKey=dGVzdC1hY2NvdW50LWtleQ==;EndpointSuffix=core.windows.net"
    )
    page.locator("#blob-storage-container-name").fill("knowledge-base")


def _fill_databricks(page):
    page.locator("#databricks-workspace-url").fill("https://adb-1234567890123456.7.azuredatabricks.net")
    page.locator("#databricks-warehouse-id").fill("warehouse-123")
    page.locator("#databricks-auth-method").select_option("pat")
    page.locator("#databricks-token").fill("test-token")


def _fill_log_analytics(page):
    page.locator("#log-analytics-workspace-id").fill("11111111-2222-3333-4444-555555555555")
    page.locator("#log-analytics-cloud").select_option("public")


def _fill_mcp(page):
    page.locator("#mcp-transport").select_option("streamable_http")
    page.locator("#mcp-endpoint").fill("https://example.com/mcp")


def _fill_snowflake(page):
    page.locator("#snowflake-account").fill("acme-analytics")
    page.locator("#snowflake-warehouse").fill("COMPUTE_WH")
    page.locator("#snowflake-auth-method").select_option("password")
    page.locator("#snowflake-user").fill("analyst@example.com")
    page.locator("#snowflake-password").fill("test-password")


def _fill_tableau(page):
    page.locator("#tableau-server-url").fill("https://10ax.online.tableau.com")
    page.locator("#tableau-pat-name").fill("simplechat-agent")
    page.locator("#tableau-pat-secret").fill("pat-secret")


ACTION_TEST_CASES = [
    pytest.param(
        "openapi",
        "#openapi-config-section",
        "openapi",
        "**/api/plugins/test-openapi-connection",
        "Status API",
        _fill_openapi,
        "#plugin-endpoint",
        id="openapi",
    ),
    pytest.param(
        "azure_maps_openlayers",
        "#azure-maps-config-section",
        "azure-maps",
        "**/api/plugins/test-azure-maps-connection",
        "Coverage Map",
        _fill_azure_maps,
        "#azure-maps-key",
        id="azure_maps",
    ),
    pytest.param(
        "blob_storage",
        "#blob-storage-config-section",
        "blob-storage",
        "**/api/plugins/test-blob-storage-connection",
        "Knowledge Base Blobs",
        _fill_blob_storage,
        "#blob-storage-container-name",
        id="blob_storage",
    ),
    pytest.param(
        "databricks",
        "#databricks-config-section",
        "databricks",
        "**/api/plugins/test-databricks-connection",
        "Commercial Databricks SQL",
        _fill_databricks,
        "#databricks-warehouse-id",
        id="databricks",
    ),
    pytest.param(
        "log_analytics",
        "#log-analytics-config-section",
        "log-analytics",
        "**/api/plugins/test-log-analytics-connection",
        "Platform Logs",
        _fill_log_analytics,
        "#log-analytics-workspace-id",
        id="log_analytics",
    ),
    pytest.param(
        "mcp",
        "#mcp-config-section",
        "mcp",
        "**/api/plugins/test-mcp-connection",
        "Docs MCP Server",
        _fill_mcp,
        "#mcp-endpoint",
        id="mcp",
    ),
    pytest.param(
        "snowflake",
        "#snowflake-config-section",
        "snowflake",
        "**/api/plugins/test-snowflake-connection",
        "Analytics Snowflake",
        _fill_snowflake,
        "#snowflake-account",
        id="snowflake",
    ),
    pytest.param(
        "tableau",
        "#tableau-config-section",
        "tableau",
        "**/api/plugins/test-tableau-connection",
        "Tableau Cloud Content",
        _fill_tableau,
        "#tableau-server-url",
        id="tableau",
    ),
]


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _open_action_step_three(page, expect, pytest_module, action_type, display_name):
    """Navigate the workspace action modal to Step 3 for the given action type."""
    response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
    assert response is not None, "Expected a navigation response when loading /workspace."

    if response.status in SKIP_RESPONSE_CODES:
        pytest_module.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")

    assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

    plugins_tab_button = page.locator("#plugins-tab-btn")
    if plugins_tab_button.count() == 0:
        pytest_module.skip("Workspace actions are not enabled in this environment.")
    plugins_tab_button.click()

    create_button = page.locator("#create-plugin-btn")
    if create_button.count() == 0:
        pytest_module.skip("Workspace action creation is not available in this environment.")
    expect(create_button).to_be_visible()
    create_button.click()

    modal = page.locator("#plugin-modal")
    expect(modal).to_be_visible()

    action_card = page.locator(f'.action-type-card[data-type="{action_type}"]')
    if action_card.count() == 0:
        pytest_module.skip(f"Action type {action_type} is not available in this environment.")
    action_card.click()

    modal.get_by_role("button", name="Next").click()
    page.locator("#plugin-display-name").fill(display_name)
    modal.get_by_role("button", name="Next").click()
    return modal


@pytest.mark.ui
@pytest.mark.parametrize(
    "action_type,section_selector,id_prefix,route_glob,display_name,fill_configuration,required_field_selector",
    ACTION_TEST_CASES,
)
def test_workspace_action_test_connection_controls(
    action_type,
    section_selector,
    id_prefix,
    route_glob,
    display_name,
    fill_configuration,
    required_field_selector,
):
    """Validate the Test Connection button posts configuration and renders every result state."""
    _require_ui_env()
    playwright_sync_api = pytest.importorskip("playwright.sync_api")
    expect = playwright_sync_api.expect

    test_requests = []
    responder = {
        "status": 200,
        "body": {"success": True, "message": "Connection successful for the configured resource."},
    }

    with playwright_sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        def handle_plugins(route):
            if route.request.method == "GET":
                route.fulfill(status=200, content_type="application/json", body="[]")
                return
            route.fulfill(status=200, content_type="application/json", body='{"success": true}')

        def handle_connection_test(route):
            test_requests.append(json.loads(route.request.post_data or "{}"))
            route.fulfill(
                status=responder["status"],
                content_type="application/json",
                body=json.dumps(responder["body"]),
            )

        page.route("**/api/user/plugins", handle_plugins)
        page.route(route_glob, handle_connection_test)

        try:
            _open_action_step_three(page, expect, pytest, action_type, display_name)

            config_section = page.locator(section_selector)
            expect(config_section).to_be_visible()
            expect(page.locator("#generic-config-section")).to_be_hidden()

            test_button = page.locator(f"#{id_prefix}-test-connection-btn")
            result_alert = page.locator(f"#{id_prefix}-test-connection-alert")
            expect(test_button).to_be_visible()
            expect(page.locator(f"#{id_prefix}-test-connection-result")).to_be_hidden()

            # Missing required configuration renders a warning without calling the backend.
            page.locator(required_field_selector).fill("")
            test_button.click()
            expect(result_alert).to_be_visible()
            expect(result_alert).to_have_class(re.compile(r"alert-warning"))
            assert not test_requests, "A warning state must not send a connection test request."

            # A complete configuration posts to the type-specific route and renders success.
            fill_configuration(page)
            test_button.click()
            expect(result_alert).to_have_class(re.compile(r"alert-success"))
            expect(result_alert).to_contain_text("Connection successful")
            assert len(test_requests) == 1, "Expected exactly one connection test request."

            submitted = test_requests[0]
            assert submitted["type"] == action_type, (
                f"Expected the {action_type} manifest type, got {submitted.get('type')}."
            )
            assert submitted["action_scope"] == "personal"
            assert isinstance(submitted.get("auth"), dict)
            assert isinstance(submitted.get("additionalFields"), dict)

            # A backend failure renders a danger alert with the server-provided reason.
            responder["status"] = 403
            responder["body"] = {"success": False, "error": "Credentials were rejected by the resource."}
            test_button.click()
            expect(result_alert).to_have_class(re.compile(r"alert-danger"))
            expect(result_alert).to_contain_text("Credentials were rejected")
            assert len(test_requests) == 2, "Expected a second connection test request."

            expect(page.locator("#plugin-modal")).to_be_visible()
        finally:
            context.close()
            browser.close()
