# test_workspace_mcp_action_modal.py
"""
UI test for the workspace MCP action modal.
Version: 0.241.103
Implemented in: 0.241.103

This test ensures users can select the MCP action type, configure transport,
authentication, tool exposure, and timeouts, then save the expected manifest
through the shared workspace validation flow.
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
def test_workspace_mcp_action_modal(playwright):
    """Validate that the workspace action modal exposes the dedicated MCP flow."""
    _require_ui_env()

    validation_requests = []
    admin_validation_requests = []
    saved_payloads = []
    discovery_requests = []

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

    def handle_mcp_discovery(route):
        discovery_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "success": True,
                "tool_count": 1,
                "tools": [
                    {
                        "original_name": "search-repositories",
                        "function_name": "search_repositories",
                        "description": "Search repositories.",
                        "input_schema": {"type": "object"},
                    }
                ],
            }),
        )

    page.route("**/api/user/plugins", handle_plugins)
    page.route("**/api/plugins/validate", handle_validation)
    page.route("**/api/admin/plugins/validate", handle_admin_validation)
    page.route("**/api/plugins/mcp/discover", handle_mcp_discovery)

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

        mcp_card = page.locator('.action-type-card[data-type="mcp"]')
        expect(mcp_card).to_have_count(1)
        mcp_card.click()

        modal.get_by_role("button", name="Next").click()
        page.locator("#plugin-display-name").fill("GitHub MCP Tools")
        modal.get_by_role("button", name="Next").click()

        expect(page.locator("#mcp-config-section")).to_be_visible()
        expect(page.locator("#generic-config-section")).to_be_hidden()
        expect(page.locator("#sql-config-section")).to_be_hidden()

        page.locator("#mcp-transport").select_option("streamable_http")
        page.locator("#mcp-endpoint").fill("https://example.com/mcp")
        page.locator("#mcp-auth-method").select_option("bearer")
        page.locator("#mcp-bearer-token").fill("test-token")
        page.locator("#mcp-tool-names").fill("search_repositories\nget_issue")
        page.locator("#mcp-discover-tools-btn").click()
        expect(page.locator("#mcp-discover-status")).to_have_text("Discovered 1 tool.")
        page.locator("#mcp-request-timeout").fill("45")
        page.locator("#mcp-connect-timeout").fill("12")
        page.locator("#mcp-sse-read-timeout").fill("120")

        page.locator("#plugin-modal-skip").click()

        expect(page.locator("#summary-mcp-section")).to_be_visible()
        expect(page.locator("#summary-plugin-database-type")).to_have_text("Model Context Protocol server")
        expect(page.locator("#summary-plugin-auth")).to_have_text("Bearer Token")
        expect(page.locator("#summary-plugin-endpoint")).to_have_text("https://example.com/mcp")
        expect(page.locator("#summary-mcp-transport")).to_have_text("Streamable HTTP")
        expect(page.locator("#summary-mcp-tool-names")).to_contain_text("search_repositories")
        expect(page.locator("#summary-mcp-tool-metadata")).to_have_text("1 cached tool")

        modal.get_by_role("button", name="Save Action").click()

        expect(modal).to_be_hidden()
        assert len(discovery_requests) == 1, "Expected the MCP discovery endpoint to be called once."
        assert len(validation_requests) == 1, "Expected the shared validation endpoint to be called once."
        assert not admin_validation_requests, "Workspace action save should not call the admin validation endpoint."
        assert len(saved_payloads) == 1, "Expected the workspace action save request to be submitted once."

        saved_plugin = saved_payloads[0][0]
        discovery_payload = discovery_requests[0]
        assert discovery_payload["type"] == "mcp"
        assert discovery_payload["endpoint"] == "https://example.com/mcp"
        assert discovery_payload["additionalFields"]["auth_method"] == "bearer"

        assert saved_plugin["type"] == "mcp"
        assert saved_plugin["name"] == "github_mcp_tools"
        assert saved_plugin["endpoint"] == "https://example.com/mcp"
        assert saved_plugin["auth"]["type"] == "key"
        assert saved_plugin["auth"]["key"] == "test-token"

        additional_fields = saved_plugin["additionalFields"]
        assert additional_fields["transport"] == "streamable_http"
        assert additional_fields["auth_method"] == "bearer"
        assert additional_fields["load_tools"] is True
        assert additional_fields["load_prompts"] is False
        assert additional_fields["request_timeout"] == 45
        assert additional_fields["connect_timeout"] == 12
        assert additional_fields["sse_read_timeout"] == 120
        assert additional_fields["allowed_tool_names"] == ["search_repositories", "get_issue"]
        assert additional_fields["mcp_tools"][0]["function_name"] == "search_repositories"
    finally:
        context.close()
        browser.close()