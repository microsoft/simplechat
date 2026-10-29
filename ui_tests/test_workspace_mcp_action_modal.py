# test_workspace_mcp_action_modal.py
"""
UI test for the workspace MCP action modal.
Version: 0.261.029
Implemented in: 0.241.103
Stdio retirement coverage implemented in: 0.261.029

This test ensures users can select the MCP action type, configure transport,
authentication, tool exposure, and timeouts, then save the expected manifest
through the shared workspace validation flow. Retired actions remain visible
and unchanged until an explicit remote reconfiguration or deletion.
Migration coverage distinguishes retained-only cleanup from retryable failures.

Set PLAYWRIGHT_SERVICE_URL to use Azure Playwright with DefaultAzureCredential.
Optional AZURE_PLAYWRIGHT_RESOURCE_GROUP and AZURE_PLAYWRIGHT_WORKSPACE_NAME
validate the workspace through azure-mgmt-playwright using AZURE_SUBSCRIPTION_ID.
"""

import json
import os
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}
APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
RETIREMENT_MESSAGE = (
    "This action uses stdio, which is no longer supported. "
    "Reconfigure it to use a supported remote MCP server, or delete it."
)


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _launch_browser(playwright):
    """Use the existing local runner or an explicitly configured Azure workspace."""
    service_url = os.getenv("PLAYWRIGHT_SERVICE_URL", "").strip()
    if not service_url:
        return playwright.chromium.launch()

    # Azure-only dependencies and credentials must not initialize during collection.
    identity = pytest.importorskip("azure.identity")
    management = pytest.importorskip("azure.mgmt.playwright")
    parsed_url = urlsplit(service_url)
    if parsed_url.scheme != "wss" or not parsed_url.netloc:
        pytest.fail("PLAYWRIGHT_SERVICE_URL must be an Azure Playwright wss endpoint.")
    with identity.DefaultAzureCredential() as credential:
        resource_group = os.getenv("AZURE_PLAYWRIGHT_RESOURCE_GROUP", "")
        workspace_name = os.getenv("AZURE_PLAYWRIGHT_WORKSPACE_NAME", "")
        if resource_group or workspace_name:
            subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID", "")
            if not all((subscription_id, resource_group, workspace_name)):
                pytest.fail("Azure workspace validation requires subscription, resource group, and workspace name.")
            with management.PlaywrightMgmtClient(credential, subscription_id) as client:
                workspace = client.playwright_workspaces.get(resource_group, workspace_name)
                workspace_id = workspace.properties.workspace_id
                if workspace_id and workspace_id not in parsed_url.path:
                    pytest.fail("PLAYWRIGHT_SERVICE_URL does not identify the configured Azure workspace.")
        token = credential.get_token("https://playwright.azure.com/.default")
        parameters = dict(parse_qsl(parsed_url.query))
        parameters.setdefault("os", "linux")
        parameters.setdefault("runId", f"mcp-retirement-{uuid4()}")
        endpoint = urlunsplit(parsed_url._replace(query=urlencode(parameters)))
        return playwright.chromium.connect(
            endpoint,
            headers={"Authorization": f"Bearer {token.token}"},
            timeout=120000,
        )


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
    browser = _launch_browser(playwright)
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
                            "allowedTransports": ["streamable_http", "sse", "websocket"],
                            "allowedAuthMethods": ["none", "bearer", "api_key", "basic", "identity"],
                            "customHeadersAllowed": True,
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
        expect(page.locator('#mcp-transport option[value="stdio"]')).to_have_count(0)
        expect(page.locator("#mcp-command, #mcp-args, #mcp-env")).to_have_count(0)
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
        assert not {"command", "args", "env"} & additional_fields.keys()
    finally:
        context.close()
        browser.close()
        playwright.stop()


@pytest.mark.ui
def test_workspace_retired_mcp_action_requires_explicit_reconfiguration():
    """Keep old actions visible and unchanged on cancel, Test, Discover, and Save."""
    sync_api = pytest.importorskip("playwright.sync_api")
    expect = sync_api.expect
    _require_ui_env()
    retired = {
        "id": "retired-mcp-locator",
        "name": "retired_mcp",
        "displayName": "Retired MCP Action",
        "type": "mcp",
        "description": "An unsupported historical action.",
        "endpoint": "stdio://local",
        "auth": {"type": "NoAuth"},
        "metadata": {},
        "additionalFields": {"transport": " StDiO ", "load_tools": True},
        "is_enabled": True,
        "execution_status": {"state": "unsupported", "code": "mcp_stdio_removed", "message": RETIREMENT_MESSAGE},
    }
    remote = {
        "id": "unrelated-remote",
        "name": "unrelated_remote",
        "displayName": "Unrelated Remote",
        "type": "mcp",
        "endpoint": "https://example.invalid/mcp",
        "auth": {"type": "NoAuth"},
        "additionalFields": {"transport": "streamable_http"},
    }
    actions = [retired, remote]
    saved_payloads = []
    validation_requests = []
    connection_requests = []
    discovery_requests = []
    browser_errors = []
    generic = json.loads((APP_DIR / "mcp_presets" / "definitions" / "generic.json").read_text(encoding="utf-8"))
    playwright = sync_api.sync_playwright().start()
    browser = _launch_browser(playwright)
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    def fulfill(route, payload):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    def handle_plugins(route):
        if route.request.method == "GET":
            fulfill(route, actions)
        else:
            payload = json.loads(route.request.post_data or "[]")
            saved_payloads.append(payload)
            actions[:] = payload
            fulfill(route, {"success": True})

    def handle_validation(route):
        validation_requests.append(json.loads(route.request.post_data or "{}"))
        fulfill(route, {"valid": True, "errors": [], "warnings": []})

    def handle_connection(route):
        connection_requests.append(json.loads(route.request.post_data or "{}"))
        fulfill(route, {"success": True, "message": "Connected.", "warnings": []})

    def handle_discovery(route):
        discovery_requests.append(json.loads(route.request.post_data or "{}"))
        fulfill(route, {"success": True, "tools": [], "warnings": []})

    page.route("**/api/user/plugins", handle_plugins)
    page.route("**/api/user/plugins/types", lambda route: fulfill(route, [{"type": "mcp", "displayName": "Model Context Protocol server"}]))
    page.route("**/api/plugins/mcp/presets", lambda route: fulfill(route, {"defaultPreset": "generic", "presets": [generic]}))
    page.route("**/api/plugins/mcp/preconfigurations*", lambda route: fulfill(route, {"preconfigurations": []}))
    page.route("**/api/plugins/mcp/auth-types", lambda route: fulfill(route, {"allowedAuthTypes": ["NoAuth", "key", "identity"]}))
    page.route("**/api/workspace-identities/**", lambda route: fulfill(route, []))
    page.route("**/api/plugins/validate", handle_validation)
    page.route("**/api/plugins/test-mcp-connection", handle_connection)
    page.route("**/api/plugins/mcp/discover", handle_discovery)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        if response is None or response.status in SKIP_RESPONSE_CODES:
            pytest.skip("The authenticated workspace is unavailable in this environment.")
        assert response.ok
        plugins_tab = page.locator("#plugins-tab-btn")
        if plugins_tab.count() == 0:
            pytest.skip("Workspace actions are not enabled in this environment.")
        plugins_tab.click()
        row = page.locator("#plugins-table-body tr").filter(
            has=page.locator('.edit-plugin-btn[data-plugin-name="retired-mcp-locator"]')
        )
        expect(row).to_contain_text("Unsupported")
        expect(row).to_contain_text(RETIREMENT_MESSAGE)
        expect(row.get_by_text("Enabled", exact=True)).to_have_count(0)
        page.locator('label[for="plugins-view-grid"]').click()
        card = page.locator("#plugins-grid-view .item-card").filter(has_text="Retired MCP Action")
        expect(card).to_be_visible()
        expect(card).to_contain_text("Unsupported")
        expect(card).to_contain_text(RETIREMENT_MESSAGE)
        page.locator('label[for="plugins-view-list"]').click()
        row.get_by_title("Reconfigure action").click()
        modal = page.locator("#plugin-modal")
        expect(modal).to_be_visible()
        expect(page.locator("#mcp-retirement-notice")).to_have_text(RETIREMENT_MESSAGE)
        expect(page.locator("#mcp-transport")).to_have_value("")
        expect(page.locator("#mcp-endpoint")).to_have_value("")
        expect(page.locator('#mcp-transport option[value="stdio"]')).to_have_count(0)
        expect(page.locator("#mcp-command, #mcp-args, #mcp-env")).to_have_count(0)
        modal.get_by_role("button", name="Close", exact=True).first.click()
        expect(modal).to_be_hidden()
        assert not saved_payloads and not validation_requests
        assert not connection_requests and not discovery_requests

        row.get_by_title("Reconfigure action").click()
        expect(modal).to_be_visible()
        page.locator("#plugin-modal-next").click()
        page.locator("#mcp-test-connection-btn").click()
        expect(page.locator("#mcp-test-connection-alert")).to_contain_text("Select a supported remote MCP transport")
        page.locator("#mcp-discover-tools-btn").click()
        expect(page.locator("#mcp-discover-status")).to_contain_text("Select a supported remote MCP transport")
        page.locator("#plugin-modal-skip").click()
        page.locator("#save-plugin-btn").click()
        expect(page.locator("#plugin-modal-error")).to_contain_text("Select a supported remote MCP transport")
        assert not saved_payloads and not validation_requests
        assert not connection_requests and not discovery_requests

        page.locator("#plugin-modal-prev").click()
        page.locator("#plugin-modal-prev").click()
        page.locator("#mcp-transport").select_option("sse")
        page.locator("#mcp-endpoint").fill("stdio://local")
        page.locator("#mcp-test-connection-btn").click()
        expect(page.locator("#mcp-test-connection-alert")).to_contain_text("requires a valid http/https endpoint")
        assert not connection_requests
        page.locator("#mcp-endpoint").fill("https://example.invalid/events")
        page.locator("#mcp-test-connection-btn").click()
        expect(page.locator("#mcp-test-connection-alert")).to_contain_text("Connected.")
        page.locator("#mcp-discover-tools-btn").click()
        expect(page.locator("#mcp-discover-status")).to_contain_text("Discovered 0 tools.")
        page.locator("#plugin-modal-skip").click()
        expect(page.locator("#summary-mcp-transport")).to_have_text("Server-Sent Events")
        page.locator("#save-plugin-btn").click()
        expect(modal).to_be_hidden()
        assert len(saved_payloads) == 1
        assert len(validation_requests) == len(connection_requests) == len(discovery_requests) == 1
        converted, unchanged = saved_payloads[0]
        assert converted["id"] == retired["id"]
        assert converted["endpoint"] == "https://example.invalid/events"
        assert converted["additionalFields"]["transport"] == "sse"
        assert not {"command", "args", "env"} & converted["additionalFields"].keys()
        assert "execution_status" not in converted
        assert unchanged == remote
        assert not browser_errors
    finally:
        context.close()
        browser.close()
        playwright.stop()


@pytest.mark.ui
@pytest.mark.parametrize("failed_count", [0, 1], ids=["retained-only", "mixed-failure"])
def test_workspace_mcp_migration_retained_and_failed_notices(failed_count):
    """Retained actions need manual cleanup; only pending/failed work prompts retry."""
    sync_api = pytest.importorskip("playwright.sync_api")
    expect = sync_api.expect
    _require_ui_env()
    state = {"finished": False}
    migration_requests = []
    browser_errors = []
    playwright = sync_api.sync_playwright().start()
    browser = _launch_browser(playwright)
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.on("pageerror", lambda error: browser_errors.append(str(error)))

    def handle_status(route):
        pending = 0 if state["finished"] else 2
        failed = failed_count if state["finished"] else 0
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "migration_needed": bool(pending or failed),
                "legacy_data": {
                    "agents_count": 0,
                    "actions_count": pending + failed + 2,
                    "actions_pending_count": pending,
                    "actions_failed_count": failed,
                    "actions_retained_count": 2,
                },
            }),
        )

    def handle_migration(route):
        migration_requests.append(route.request.method)
        state["finished"] = True
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "success": not failed_count,
                "action_migration": {
                    "migrated_count": 2 - failed_count,
                    "retained_count": 2,
                    "failed_count": failed_count,
                    "complete": not failed_count,
                },
            }),
        )

    page.route("**/api/migrate/status", handle_status)
    page.route("**/api/migrate/all", handle_migration)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        if response is None or response.status in SKIP_RESPONSE_CODES:
            pytest.skip("The authenticated workspace is unavailable in this environment.")
        assert response.ok
        banner = page.locator("#migration-banner")
        if banner.count() == 0:
            pytest.skip("The migration surface is unavailable in this environment.")
        expect(banner).to_be_visible()
        expect(banner).to_contain_text("2 actions ready to migrate or retry")
        expect(banner).to_contain_text("2 other legacy actions need manual reconfiguration or deletion")
        page.locator("#migrate-all-btn").click()
        if failed_count:
            expect(page.get_by_text("Migration is incomplete.", exact=False)).to_be_visible()
            expect(banner).to_be_visible()
            expect(banner).to_contain_text("1 action ready to migrate or retry")
        else:
            expect(page.get_by_text("2 legacy actions were kept for manual reconfiguration or deletion", exact=False)).to_be_visible()
            expect(banner).to_be_hidden()
        expect(page.locator("#migration-progress")).to_be_hidden()
        expect(page.locator("#migrate-all-btn")).to_be_enabled()
        assert migration_requests == ["POST"]

        page.reload(wait_until="networkidle")
        if failed_count:
            expect(banner).to_be_visible()
            expect(banner).to_contain_text("1 action ready to migrate or retry")
        else:
            expect(banner).to_be_hidden()
        assert migration_requests == ["POST"], "Refreshing a retained-only notice must not retry migration."
        assert not browser_errors
    finally:
        context.close()
        browser.close()
        playwright.stop()


@pytest.mark.ui
def test_workspace_remote_action_delete_preserves_locator_identity():
    """Delete the selected retained/migrated remote record, not a same-named peer."""
    sync_api = pytest.importorskip("playwright.sync_api")
    expect = sync_api.expect
    _require_ui_env()
    remote = {
        "name": "shared_remote",
        "displayName": "Shared Remote",
        "type": "mcp",
        "endpoint": "https://example.invalid/mcp",
        "auth": {"type": "NoAuth"},
        "additionalFields": {"transport": "streamable_http"},
    }
    actions = [
        {
            **remote,
            "id": "legacy-action-remote-snapshot",
            "legacy_locator": "legacy-action-remote-snapshot",
            "is_legacy": True,
            "legacy_source": "settings.plugins",
        },
        {**remote, "id": "personal-remote-one"},
        {**remote, "id": "personal-remote-two"},
    ]
    deleted_locators = []
    browser_errors = []
    playwright = sync_api.sync_playwright().start()
    browser = _launch_browser(playwright)
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.on("pageerror", lambda error: browser_errors.append(str(error)))
    page.on("dialog", lambda dialog: dialog.accept())

    def handle_list(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(actions))

    def handle_delete(route):
        if route.request.method != "DELETE":
            route.fallback()
            return
        locator = urlsplit(route.request.url).path.rsplit("/", 1)[-1]
        deleted_locators.append(locator)
        if not any(action["id"] == locator for action in actions):
            route.fulfill(
                status=409,
                content_type="application/json",
                body=json.dumps({"error": "Use a stable action ID for this ambiguous name."}),
            )
            return
        actions[:] = [action for action in actions if action["id"] != locator]
        route.fulfill(status=200, content_type="application/json", body='{"success": true}')

    page.route("**/api/user/plugins", handle_list)
    page.route("**/api/user/plugins/*", handle_delete)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        if response is None or response.status in SKIP_RESPONSE_CODES:
            pytest.skip("The authenticated workspace is unavailable in this environment.")
        assert response.ok
        plugins_tab = page.locator("#plugins-tab-btn")
        if plugins_tab.count() == 0:
            pytest.skip("Workspace actions are not enabled in this environment.")
        plugins_tab.click()
        page.locator('label[for="plugins-view-list"]').click()
        expected_locators = ["legacy-action-remote-snapshot", "personal-remote-two", "personal-remote-one"]
        for index, locator in enumerate(expected_locators):
            button = page.locator(f'.delete-plugin-btn[data-plugin-name="{locator}"]')
            expect(button).to_be_visible()
            button.click()
            expect(page.locator("#plugins-table-body tr")).to_have_count(2 - index)
            assert deleted_locators == expected_locators[:index + 1]
        assert not browser_errors
    finally:
        context.close()
        browser.close()
        playwright.stop()