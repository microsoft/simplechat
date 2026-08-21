# test_workspace_mcp_action_modal.py
"""
UI test for the workspace MCP action modal.
Version: 0.250.068
Implemented in: 0.241.103

This test ensures users can select the MCP action type, configure transport,
authentication, tool exposure, and timeouts, then save the expected manifest
through the shared workspace validation flow.
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
def test_workspace_mcp_action_modal():
    """Validate that the workspace action modal exposes the dedicated MCP flow."""
    sync_api = pytest.importorskip("playwright.sync_api")
    expect = sync_api.expect
    _require_ui_env()

    validation_requests = []
    admin_validation_requests = []
    saved_payloads = []
    discovery_requests = []
    type_requests = []
    preset_requests = []
    preconfiguration_requests = []

    playwright = sync_api.sync_playwright().start()
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
                        "output_schema": {"type": "object"},
                        "annotations": {"readOnlyHint": True},
                        "structured_content": True,
                    }
                ],
                "capabilities": {
                    "tools": True,
                    "connector_type": "MCPStreamableHttpPlugin",
                },
                "warnings": [
                    "1 MCP tool input schema is missing or broad; argument validation may be limited.",
                ],
            }),
        )

    def handle_types(route):
        type_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([
                {
                    "type": "mcp",
                    "displayName": "Model Context Protocol server",
                    "description": "Connect to an MCP server.",
                }
            ]),
        )

    def handle_presets(route):
        preset_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "defaultPreset": "generic",
                "presets": [
                    {
                        "id": "generic",
                        "displayName": "Generic MCP Server",
                        "description": "Default MCP server preset.",
                        "defaults": {
                            "transport": "streamable_http",
                            "auth_method": "none",
                            "api_key_header_name": "X-API-Key",
                            "load_tools": True,
                            "load_prompts": False,
                            "request_timeout": 30,
                            "connect_timeout": 10,
                            "sse_read_timeout": 300,
                            "retry_count": 0,
                            "retry_backoff_seconds": 1,
                            "validate_tool_arguments": False,
                            "tool_result_policy": "truncate",
                            "allowed_tool_names": [],
                        },
                        "ui": {
                            "helpText": "Use generic unless the server needs a specific compatibility preset.",
                            "endpointPlaceholder": "https://example.com/mcp",
                            "websocketEndpointPlaceholder": "wss://example.com/mcp",
                        },
                        "constraints": {
                            "allowedTransports": ["streamable_http", "sse", "websocket", "stdio"],
                            "allowedAuthMethods": ["none", "bearer", "api_key", "basic", "identity"],
                            "customHeadersAllowed": True,
                            "stdioAllowed": True,
                        },
                    },
                    {
                        "id": "splunk",
                        "displayName": "Splunk MCP Server",
                        "description": "Splunk MCP compatibility preset.",
                        "defaults": {
                            "transport": "streamable_http",
                            "auth_method": "bearer",
                            "api_key_header_name": "X-API-Key",
                            "load_tools": True,
                            "load_prompts": False,
                            "request_timeout": 30,
                            "connect_timeout": 10,
                            "sse_read_timeout": 300,
                            "retry_count": 0,
                            "retry_backoff_seconds": 1,
                            "validate_tool_arguments": False,
                            "tool_result_policy": "truncate",
                            "allowed_tool_names": [],
                        },
                        "ui": {
                            "helpText": "Splunk preset returned by the test catalog.",
                            "endpointPlaceholder": "https://splunk.example.com:8089/mcp",
                            "websocketEndpointPlaceholder": "wss://splunk.example.com/mcp",
                        },
                        "constraints": {
                            "allowedTransports": ["streamable_http"],
                            "allowedAuthMethods": ["bearer"],
                            "customHeadersAllowed": True,
                            "stdioAllowed": False,
                        },
                    },
                ],
            }),
        )

    def handle_preconfigurations(route):
        preconfiguration_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "defaultPreconfiguration": "",
                "scope": "personal",
                "preconfigurations": [
                    {
                        "id": "github",
                        "displayName": "GitHub MCP Server",
                        "description": "GitHub hosted MCP server returned by the test catalog.",
                        "provider": "GitHub",
                        "category": "Developer Tools",
                        "presetId": "generic",
                        "endpoint": "https://api.githubcopilot.com/mcp/",
                        "transport": "streamable_http",
                        "authRequirement": "required",
                        "implementation": {
                            "id": "github",
                            "schemaVersion": "1.0.0",
                        },
                        "additionalSettings": {
                            "hostedServer": True,
                            "permissionModel": "supplied_identity_permissions",
                            "recommendedCredentialHandling": "least_privilege_pat_or_identity",
                            "defaultRepositoryScope": "user_selected",
                        },
                        "catalogTier": "public",
                        "authTier": "user_supplied_credential",
                        "deploymentModel": "hosted_remote",
                        "disabledByDefault": False,
                        "requiresAdminEnablement": False,
                        "requiresEndpointReview": False,
                        "defaults": {
                            "auth_method": "bearer",
                            "api_key_header_name": "X-API-Key",
                            "load_tools": True,
                            "load_prompts": False,
                            "request_timeout": 30,
                            "connect_timeout": 10,
                            "sse_read_timeout": 300,
                            "retry_count": 0,
                            "retry_backoff_seconds": 1,
                            "validate_tool_arguments": False,
                            "tool_result_policy": "truncate",
                            "allowed_tool_names": [],
                        },
                        "scopeEligibility": ["personal", "group", "global"],
                        "destinationTags": ["github", "hosted"],
                        "requiredGovernanceGates": [],
                        "riskLabel": "medium",
                        "documentationUrl": "https://docs.github.com/",
                        "ui": {
                            "helpText": "Requires a GitHub token.",
                        },
                        "operatorNotes": [],
                        "warnings": [
                            "Use least-privilege credentials.",
                        ],
                    },
                ],
            }),
        )

    page.route("**/api/user/plugins", handle_plugins)
    page.route("**/api/user/plugins/types", handle_types)
    page.route("**/api/plugins/mcp/presets", handle_presets)
    page.route("**/api/plugins/mcp/preconfigurations*", handle_preconfigurations)
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
        expect(page.locator("#mcp-test-connection-btn")).to_be_visible()
        expect(page.locator("#mcp-test-connection-result")).to_be_hidden()
        expect(page.locator("#mcp-discover-tools-btn")).to_be_visible()
        expect(page.locator("#generic-config-section")).to_be_hidden()
        expect(page.locator("#sql-config-section")).to_be_hidden()

        page.locator("#mcp-preconfiguration").select_option("github")
        expect(page.locator("#mcp-preconfiguration-help")).to_contain_text("Requires a GitHub token.")
        expect(page.locator("#mcp-preconfiguration-help")).to_contain_text("Use least-privilege credentials.")
        expect(page.locator("#mcp-endpoint")).to_have_value("https://api.githubcopilot.com/mcp/")
        expect(page.locator("#mcp-auth-method")).to_have_value("bearer")
        page.locator("#mcp-bearer-token").fill("test-token")
        page.locator("#mcp-custom-headers").fill(json.dumps({
            "X-GitHub-Host": "api.github.com",
        }, indent=2))
        page.locator("#mcp-tool-names").fill("search_repositories\nget_issue")
        page.locator("#mcp-validate-tool-arguments").check()
        page.locator("#mcp-tool-result-policy").select_option("error_on_limit")
        page.locator("#mcp-discover-tools-btn").click()
        expect(page.locator("#mcp-discover-status")).to_contain_text("Discovered 1 tool.")
        expect(page.locator("#mcp-discover-status")).to_contain_text("MCPStreamableHttpPlugin")
        expect(page.locator("#mcp-discover-warnings")).to_contain_text("argument validation may be limited")
        page.locator("#mcp-request-timeout").fill("45")
        page.locator("#mcp-connect-timeout").fill("12")
        page.locator("#mcp-sse-read-timeout").fill("120")
        page.locator("#mcp-retry-count").fill("2")
        page.locator("#mcp-retry-backoff-seconds").fill("3")

        page.locator("#plugin-modal-skip").click()

        expect(page.locator("#summary-mcp-section")).to_be_visible()
        expect(page.locator("#summary-plugin-database-type")).to_have_text("Model Context Protocol server")
        expect(page.locator("#summary-plugin-auth")).to_have_text("Bearer Token")
        expect(page.locator("#summary-plugin-endpoint")).to_have_text("https://api.githubcopilot.com/mcp/")
        expect(page.locator("#summary-mcp-transport")).to_have_text("Streamable HTTP")
        expect(page.locator("#summary-mcp-preconfiguration")).to_have_text("GitHub MCP Server")
        expect(page.locator("#summary-mcp-server-profile")).to_have_text("Generic MCP Server")
        expect(page.locator("#summary-mcp-custom-headers")).to_contain_text("X-GitHub-Host")
        expect(page.locator("#summary-mcp-custom-headers")).not_to_contain_text("api.github.com")
        expect(page.locator("#summary-mcp-retry-policy")).to_have_text("2 retries, 3s initial backoff")
        expect(page.locator("#summary-mcp-tool-names")).to_contain_text("search_repositories")
        expect(page.locator("#summary-mcp-tool-metadata")).to_contain_text("1 cached tool")
        expect(page.locator("#summary-mcp-tool-metadata")).to_contain_text("validation on")
        expect(page.locator("#summary-mcp-tool-metadata")).to_contain_text("error on oversized results")

        modal.get_by_role("button", name="Save Action").click()

        expect(modal).to_be_hidden()
        assert len(discovery_requests) == 1, "Expected the MCP discovery endpoint to be called once."
        assert len(type_requests) == 1, "Expected the personal action types endpoint to be called once."
        assert len(preset_requests) == 1, "Expected MCP server presets to be loaded from the API."
        assert len(preconfiguration_requests) == 1, "Expected MCP server preconfigurations to be loaded from the API."
        assert type_requests[0].endswith("/api/user/plugins/types")
        assert len(validation_requests) == 1, "Expected the shared validation endpoint to be called once."
        assert not admin_validation_requests, "Workspace action save should not call the admin validation endpoint."
        assert len(saved_payloads) == 1, "Expected the workspace action save request to be submitted once."

        saved_plugin = saved_payloads[0][0]
        discovery_payload = discovery_requests[0]
        assert discovery_payload["type"] == "mcp"
        assert discovery_payload["endpoint"] == "https://api.githubcopilot.com/mcp/"
        assert discovery_payload["additionalFields"]["auth_method"] == "bearer"
        assert discovery_payload["additionalFields"]["server_profile"] == "generic"
        assert discovery_payload["additionalFields"]["preconfiguration_id"] == "github"
        assert discovery_payload["additionalFields"]["implementation"]["id"] == "github"
        assert discovery_payload["additionalFields"]["additionalSettings"]["hostedServer"] is True
        assert discovery_payload["additionalFields"]["custom_headers"]["X-GitHub-Host"] == "api.github.com"
        assert discovery_payload["additionalFields"]["validate_tool_arguments"] is True
        assert discovery_payload["additionalFields"]["tool_result_policy"] == "error_on_limit"

        assert saved_plugin["type"] == "mcp"
        assert saved_plugin["name"] == "github_mcp_tools"
        assert saved_plugin["endpoint"] == "https://api.githubcopilot.com/mcp/"
        assert saved_plugin["auth"]["type"] == "key"
        assert saved_plugin["auth"]["key"] == "test-token"

        additional_fields = saved_plugin["additionalFields"]
        assert additional_fields["preconfiguration_id"] == "github"
        assert additional_fields["server_profile"] == "generic"
        assert additional_fields["implementation"]["id"] == "github"
        assert additional_fields["additionalSettings"]["permissionModel"] == "supplied_identity_permissions"
        assert additional_fields["transport"] == "streamable_http"
        assert additional_fields["auth_method"] == "bearer"
        assert additional_fields["custom_headers"]["X-GitHub-Host"] == "api.github.com"
        assert additional_fields["load_tools"] is True
        assert additional_fields["load_prompts"] is False
        assert additional_fields["validate_tool_arguments"] is True
        assert additional_fields["tool_result_policy"] == "error_on_limit"
        assert additional_fields["request_timeout"] == 45
        assert additional_fields["connect_timeout"] == 12
        assert additional_fields["sse_read_timeout"] == 120
        assert additional_fields["retry_count"] == 2
        assert additional_fields["retry_backoff_seconds"] == 3
        assert additional_fields["allowed_tool_names"] == ["search_repositories", "get_issue"]
        assert additional_fields["mcp_tools"][0]["function_name"] == "search_repositories"
        assert additional_fields["mcp_tools"][0]["output_schema"]["type"] == "object"
        assert additional_fields["mcp_tools"][0]["annotations"]["readOnlyHint"] is True
    finally:
        context.close()
        browser.close()
        playwright.stop()