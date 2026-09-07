# test_inbound_mcp_admin_ui.py
#!/usr/bin/env python3
"""
Functional test for the inbound MCP admin UI settings slice.
Version: 0.261.002
Implemented in: 0.250.071
Easy Auth enablement guard implemented in: 0.250.072
Cloud-aware Easy Auth script implemented in: 0.250.073
Script copy and authsettingsV2 GET fix implemented in: 0.250.074
Delegated scope default and setup preflight implemented in: 0.250.075
OAuth protected-resource discovery header implemented in: 0.250.076
Inbound MCP governance policy UI implemented in: 0.250.077
Inbound MCP user/app role split implemented in: 0.250.078
MCP governance help modal implemented in: 0.250.079
Simplified inbound MCP governance UX implemented in: 0.250.080
Single inbound MCP access policy implemented in: 0.250.081
Personal conversation read tools implemented in: 0.250.082
Personal document and prompt listing tools implemented in: 0.250.083
Personal document search tool implemented in: 0.250.084
OAuth authorization server metadata bridge implemented in: 0.250.085
Public HTTPS metadata URL normalization implemented in: 0.250.086
Protected-resource metadata aliases implemented in: 0.250.087
Easy Auth restart reminder implemented in: 0.250.088
Personal workflow execution tool implemented in: 0.250.090
Inbound MCP object-list settings and source governance controls implemented in: 0.250.091
Inbound MCP source-only governance implemented in: 0.250.092
Inbound MCP source governance CTA guidance implemented in: 0.250.093
Inbound MCP enterprise readiness hardening implemented in: 0.250.096
Inbound MCP admin throttle controls implemented in: 0.250.097
Inbound MCP observability query panel implemented in: 0.250.098
Inbound MCP disabled-state guidance implemented in: 0.261.002

This test ensures inbound MCP runtime configuration is stored in app_settings,
the full Admin Settings UI is gated by an OS-only feature flag, the disabled
state explains how to enable the preview UI, and the feature flag itself is not
exposed as an editable UI setting. It also verifies that enabling inbound MCP
requires the Easy Auth exclusion confirmation and server-side endpoint check.
"""

import sys
from pathlib import Path
from test_support.versioning import assert_app_version_at_least
from test_support.nav import iter_tabs
from test_support.templates import compose_if_admin_settings
from test_support.nav import iter_tabs


ROOT_DIR = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    """Read a repository file for source-level contract validation."""
    _path = ROOT_DIR / relative_path
    return compose_if_admin_settings(
        _path, _path.read_text(encoding="utf-8")
    )


def test_inbound_mcp_runtime_settings_are_app_settings():
    """Validate mutable inbound MCP runtime settings live in app_settings."""
    config_source = read_repo_file("application/single_app/config.py")
    helper_source = read_repo_file("application/single_app/functions_mcp_server_config.py")
    settings_source = read_repo_file("application/single_app/functions_settings.py")

    assert_app_version_at_least("0.250.098")
    assert "ENABLE_INBOUND_MCP_SERVER = os.getenv" not in config_source
    assert "INBOUND_MCP_REQUIRED_ROLE = os.getenv" not in config_source
    assert "INBOUND_MCP_ALLOWED_CLIENT_APP_IDS = _split_env_list" not in config_source

    expected_settings = [
        '"enable_inbound_mcp_server": False',
        '"inbound_mcp_required_user_role": "InboundMCPUserAccess"',
        '"inbound_mcp_required_app_role": "InboundMCPAppAccess"',
        '"inbound_mcp_required_user_roles": ["InboundMCPUserAccess"]',
        '"inbound_mcp_required_app_roles": ["InboundMCPAppAccess"]',
        '"inbound_mcp_required_scope": "DelegatedMcpServerAccess"',
        '"inbound_mcp_allowed_client_app_entries": []',
        '"inbound_mcp_allowed_client_app_ids": []',
        '"inbound_mcp_allow_external_tenants": False',
        '"inbound_mcp_allowed_tenant_entries": []',
        '"inbound_mcp_allowed_tenant_ids": []',
        '"inbound_mcp_allow_all_source_ids": True',
        '"inbound_mcp_allowed_source_entries": [',
        '"inbound_mcp_allowed_source_ids": ["*"]',
        '"inbound_mcp_source_header": "X-SimpleChat-MCP-Source"',
        '"enable_inbound_mcp_rate_limits": True',
        '"inbound_mcp_rate_limit_window_seconds": 60',
        '"inbound_mcp_rate_limit_read_per_window": 120',
        '"inbound_mcp_rate_limit_search_per_window": 30',
        '"inbound_mcp_rate_limit_write_per_window": 10',
        '"inbound_mcp_max_request_bytes": 65536',
    ]
    for expected_setting in expected_settings:
        assert expected_setting in helper_source

    assert "**INBOUND_MCP_SETTINGS_DEFAULTS" in settings_source
    assert "normalize_inbound_mcp_settings(merged)" in settings_source
    assert "normalize_inbound_mcp_settings(settings_item)" in settings_source
    assert "enable_mcp_ui" not in settings_source


def test_mcp_ui_gate_is_os_environment_only():
    """Validate the UI feature gate is not persisted as an app setting."""
    config_source = read_repo_file("application/single_app/config.py")
    helper_source = read_repo_file("application/single_app/functions_mcp_server_config.py")
    app_source = read_repo_file("application/single_app/app.py")
    admin_route_source = read_repo_file("application/single_app/route_frontend_admin_settings.py")

    assert 'ENABLE_MCP_UI = os.getenv("ENABLE_MCP_UI"' in config_source
    assert 'os.getenv("ENABLE_MCP_UI", os.getenv("enable_mcp_ui", "false"))' in helper_source
    assert "def is_mcp_ui_enabled():" in helper_source
    assert "mcp_ui_enabled=is_mcp_ui_enabled()" in app_source
    assert "mcp_ui_enabled=is_mcp_ui_enabled()" in admin_route_source
    assert "if is_mcp_ui_enabled():" in admin_route_source
    assert "'enable_mcp_ui'" not in admin_route_source


def test_admin_settings_mcp_ui_disabled_message_and_enabled_form():
    """Validate the Inbound MCP tab shows guidance when the full UI is gated."""
    admin_template = read_repo_file("application/single_app/templates/admin_settings.html")
    admin_route_source = read_repo_file("application/single_app/route_frontend_admin_settings.py")

    assert "{% if mcp_ui_enabled %}" in admin_template
    assert "{% else %}" in admin_template
    assert 'id="inbound-mcp-configuration"' in admin_template
    assert "Inbound MCP admin UI is disabled." in admin_template
    assert "Azure App Service application setting" in admin_template
    assert "ENABLE_MCP_UI" in admin_template
    assert "The inbound MCP runtime remains off" in admin_template
    assert 'name="enable_inbound_mcp_server"' in admin_template
    assert 'name="inbound_mcp_required_user_role"' in admin_template
    assert 'name="inbound_mcp_required_app_role"' in admin_template
    assert 'name="inbound_mcp_required_user_roles"' not in admin_template
    assert 'name="inbound_mcp_required_app_roles"' not in admin_template
    assert 'name="inbound_mcp_required_role"' not in admin_template
    assert 'name="inbound_mcp_required_scope"' in admin_template
    assert 'name="inbound_mcp_allowed_client_app_entries_json"' in admin_template
    assert 'name="inbound_mcp_allow_external_tenants"' in admin_template
    assert 'name="inbound_mcp_allowed_tenant_entries_json"' in admin_template
    assert 'name="inbound_mcp_allow_all_source_ids"' in admin_template
    assert 'name="inbound_mcp_allowed_source_entries_json"' in admin_template
    assert 'name="enable_inbound_mcp_rate_limits"' in admin_template
    assert 'name="inbound_mcp_max_request_bytes"' in admin_template
    assert 'name="inbound_mcp_rate_limit_window_seconds"' in admin_template
    assert 'name="inbound_mcp_rate_limit_read_per_window"' in admin_template
    assert 'name="inbound_mcp_rate_limit_search_per_window"' in admin_template
    assert 'name="inbound_mcp_rate_limit_write_per_window"' in admin_template
    assert 'name="inbound_mcp_allowed_client_app_ids"' not in admin_template
    assert 'name="inbound_mcp_allowed_tenant_ids"' not in admin_template
    assert 'name="inbound_mcp_allowed_source_ids"' not in admin_template
    assert 'name="inbound_mcp_source_header"' in admin_template
    assert "Default on accepts any source signal at the runtime allowlist layer." in admin_template
    assert "Default on creates a locked governance policy" not in admin_template
    assert "inbound-mcp-all-source-governance-callout" in admin_template
    assert "inbound-mcp-controlled-source-governance-callout" in admin_template
    assert "Create Wildcard Source Policy" in admin_template
    assert "Create Source Policy" in admin_template
    assert "Request Size &amp; Throttling" in admin_template
    assert "Enable tool throttles" in admin_template
    assert "mcp_request_id" in admin_template
    assert "Application Insights starter queries" in admin_template
    assert "inbound-mcp-observability-accordion" in admin_template
    assert "inbound-mcp-kql-request-trends" in admin_template
    assert "inbound-mcp-kql-error-categories" in admin_template
    assert "inbound-mcp-kql-tool-latency" in admin_template
    assert "inbound-mcp-kql-rate-limits" in admin_template
    assert "customDimensions.error_type" in admin_template
    assert "Inbound MCP tool call denied by rate limit" in admin_template
    assert 'data-governance-open-tab="true"' in admin_template
    assert 'data-governance-inbound-mcp-item="*"' in admin_template
    assert "About MCP &amp; Tools" in admin_template
    assert "{% for tool in inbound_mcp_tools %}" in admin_template
    assert 'name="enable_mcp_ui"' not in admin_template
    assert "'enable_inbound_mcp_rate_limits': form_data.get('enable_inbound_mcp_rate_limits') == 'on'" in admin_route_source
    for operational_setting in [
        "inbound_mcp_max_request_bytes",
        "inbound_mcp_rate_limit_window_seconds",
        "inbound_mcp_rate_limit_read_per_window",
        "inbound_mcp_rate_limit_search_per_window",
        "inbound_mcp_rate_limit_write_per_window",
    ]:
        assert f"'{operational_setting}': form_data.get(" in admin_route_source
        assert f"'{operational_setting}'," in admin_route_source
        assert f"INBOUND_MCP_SETTINGS_DEFAULTS['{operational_setting}']" in admin_route_source

    # The Inbound MCP navigation entry stays visible so admins can discover the
    # enablement guidance even when the full preview form is gated.
    inbound_tab = next(
        (
            tab
            for _, tab in iter_tabs()
            if tab["id"] == "inbound-mcp"
        ),
        None,
    )
    assert inbound_tab is not None, (
        "Inbound MCP tab missing from the navigation map"
    )
    assert inbound_tab.get("condition") is None, (
        "Inbound MCP tab must stay visible even when mcp_ui_enabled is false"
    )

    inbound_section = next(
        (
            section
            for _, tab in iter_tabs()
            for section in tab["sections"]
            if section["id"] == "inbound-mcp-configuration"
        ),
        None,
    )
    assert inbound_section is not None, (
        "Inbound MCP navigation entry missing from the navigation map"
    )
    assert inbound_section.get("condition") is None, (
        "Inbound MCP navigation entry must stay visible even when mcp_ui_enabled is false"
    )
    assert inbound_section["label"] == "Inbound MCP", (
        f"Unexpected Inbound MCP navigation label: {inbound_section['label']}"
    )


def test_inbound_mcp_auth_uses_settings_runtime_config():
    """Validate the auth guard no longer imports static env-backed MCP runtime config."""
    auth_source = read_repo_file("application/single_app/functions_mcp_server_auth.py")
    route_source = read_repo_file("application/single_app/route_inbound_mcp.py")

    assert "get_inbound_mcp_runtime_config" in auth_source
    assert "build_inbound_mcp_public_base_url" in auth_source
    assert "get_inbound_mcp_runtime_config()" in auth_source
    assert "ENABLE_INBOUND_MCP_SERVER" not in auth_source
    assert "INBOUND_MCP_ALLOWED_CLIENT_APP_IDS" not in auth_source
    assert "INBOUND_MCP_REQUIRED_ROLE" not in auth_source
    assert "INBOUND_MCP_REQUIRED_SCOPE" not in auth_source
    assert "def _has_required_delegated_scope(" in auth_source
    assert "def _has_required_delegated_user_role(" in auth_source
    assert "def _has_required_app_role(" in auth_source
    assert '"inbound_mcp_required_user_roles"' in auth_source
    assert '"inbound_mcp_required_app_roles"' in auth_source
    assert "_has_required_role_or_scope" not in auth_source
    assert "get_inbound_mcp_runtime_config" in route_source
    assert "build_inbound_mcp_public_base_url" in route_source
    assert "runtime_config = get_inbound_mcp_runtime_config()" in route_source


def test_inbound_mcp_easy_auth_guard_contract():
    """Validate the Easy Auth exclusion modal, endpoint probe, and save guard exist."""
    helper_source = read_repo_file("application/single_app/functions_mcp_server_config.py")
    admin_route_source = read_repo_file("application/single_app/route_frontend_admin_settings.py")
    admin_template = read_repo_file("application/single_app/templates/admin_settings.html")
    admin_js = read_repo_file("application/single_app/static/js/admin/admin_settings.js")

    required_paths = [
        'INBOUND_MCP_EASY_AUTH_EXCLUDED_PATHS = (',
        '*INBOUND_MCP_PRM_PATHS,',
        'INBOUND_MCP_AUTHORIZATION_SERVER_METADATA_PATH,',
        'INBOUND_MCP_RESOURCE_PATH,',
        'f"{INBOUND_MCP_RESOURCE_PATH}/health"',
    ]
    for required_path in required_paths:
        assert required_path in helper_source

    assert "def check_inbound_mcp_easy_auth_exclusions(" in helper_source
    assert "allow_redirects=False" in helper_source
    assert "sign-in HTML page" in helper_source
    assert '"bearer_token_required", "inbound_mcp_disabled"' in helper_source

    assert "@bp.route('/api/admin/settings/inbound-mcp/easy-auth-check', methods=['POST'])" in admin_route_source
    assert "@swagger_route(security=get_auth_security())" in admin_route_source
    assert "def get_inbound_mcp_easy_auth_check_base_url():" in admin_route_source
    assert "os.getenv('WEBSITE_HOSTNAME')" in admin_route_source
    assert "def inbound_mcp_easy_auth_check():" in admin_route_source
    assert "check_inbound_mcp_easy_auth_exclusions(get_inbound_mcp_easy_auth_check_base_url())" in admin_route_source
    assert "Prevented enabling inbound MCP because Easy Auth exclusions failed" in admin_route_source

    assert "def get_inbound_mcp_easy_auth_script_context(settings=None):" in admin_route_source
    assert "def build_inbound_mcp_easy_auth_script(" in admin_route_source
    assert "WEBSITE_SITE_NAME" in admin_route_source
    assert "WEBSITE_RESOURCE_GROUP" in admin_route_source
    assert "WEBSITE_OWNER_NAME" in admin_route_source
    assert "AZURE_CLI_CLOUD_NAMES_BY_ENVIRONMENT" in admin_route_source
    assert "resource_manager" in admin_route_source
    assert "az cloud set --name $cloudNameToSet" in admin_route_source
    assert "az login --tenant $tenantId" in admin_route_source
    assert "az account set --subscription $subscriptionId" in admin_route_source
    assert "$simpleChatApiClientId" in admin_route_source
    assert "$requiredDelegatedScope" in admin_route_source
    assert "$requiredUserRoles" in admin_route_source
    assert "$requiredAppRoles" in admin_route_source
    assert "'scope_check_missing_values': scope_check_missing_values" in admin_route_source
    assert "az ad app show --id $simpleChatApiClientId" in admin_route_source
    assert "does not expose enabled delegated scope" in admin_route_source
    assert "does not expose enabled user-assignable app role" in admin_route_source
    assert "does not expose enabled application app role" in admin_route_source
    assert "endpoints.resourceManager" in admin_route_source
    assert "simplechat-authsettingsV2-backup-$timestamp.json" in admin_route_source
    assert "Restart your web app now so App Service Authentication reloads the excluded paths." in admin_route_source
    assert "-ForegroundColor Green" in admin_route_source
    assert '$authSettingsUrl = "$resourceManagerEndpoint$siteId/config/authsettingsV2?api-version=2023-12-01"' in admin_route_source
    assert "$rawCurrent = az rest --method get --url $authSettingsUrl" in admin_route_source
    assert "$current = $rawCurrent | ConvertFrom-Json" in admin_route_source
    assert "authsettingsV2/list" not in admin_route_source
    assert "--method post --url $listUrl" not in admin_route_source
    assert '"/.well-known/oauth-protected-resource",' in admin_route_source
    assert '"/.well-known/oauth-protected-resource/api/mcp",' in admin_route_source
    assert '"/.well-known/oauth-protected-resource/mcp",' in admin_route_source
    assert '"/.well-known/oauth-authorization-server",' in admin_route_source

    assert 'id="inboundMcpEasyAuthModal"' in admin_template
    assert 'id="inbound-mcp-easy-auth-confirm"' in admin_template
    assert 'id="inbound-mcp-easy-auth-verify"' in admin_template
    assert 'id="inbound-mcp-copy-script"' in admin_template
    assert 'aria-label="Copy PowerShell script"' in admin_template
    assert 'id="inbound-mcp-easy-auth-script-code"' in admin_template
    assert "/.well-known/oauth-protected-resource" in admin_template
    assert "/.well-known/oauth-protected-resource/api/mcp" in admin_template
    assert "/.well-known/oauth-protected-resource/mcp" in admin_template
    assert "/.well-known/oauth-authorization-server" in admin_template
    assert "/api/mcp/health" in admin_template
    assert "inbound_mcp_easy_auth_script_context.resource_manager_endpoint" in admin_template
    assert "inbound_mcp_easy_auth_script_context.resource_group" in admin_template
    assert "inbound_mcp_easy_auth_script_context.app_name" in admin_template
    assert "inbound_mcp_easy_auth_script_context.simplechat_api_client_id" in admin_template
    assert "inbound_mcp_easy_auth_script_context.required_delegated_scope" in admin_template
    assert "inbound_mcp_easy_auth_script_context.required_user_roles" in admin_template
    assert "inbound_mcp_easy_auth_script_context.required_app_roles" in admin_template
    assert "scope_check_missing_values" in admin_template
    assert "Default: <code>DelegatedMcpServerAccess</code>" in admin_template
    assert "Default: <code>InboundMCPUserAccess</code>" in admin_template
    assert "Default: <code>InboundMCPAppAccess</code>" in admin_template
    assert "Personal MCP tools require delegated user context plus an assigned user role" in admin_template
    assert "inbound_mcp_easy_auth_script" in admin_template
    assert "Creates a timestamped backup" in admin_template
    assert "Azure Cloud Shell" in admin_template
    assert "https://management.azure.com$siteId" not in admin_template

    assert "function setupInboundMcpEasyAuthGuard()" in admin_js
    assert "setupInboundMcpEasyAuthGuard();" in admin_js
    assert "fetch('/api/admin/settings/inbound-mcp/easy-auth-check'" in admin_js
    assert "async function copyTextToClipboard(text)" in admin_js
    assert "navigator.clipboard.writeText(text)" in admin_js
    assert "await copyTextToClipboard(scriptText)" in admin_js
    assert "PowerShell script copied to clipboard." in admin_js
    assert "function setupInboundMcpObservabilityCopyButtons()" in admin_js
    assert "document.querySelectorAll('.inbound-mcp-kql-copy-btn')" in admin_js
    assert "setupInboundMcpObservabilityCopyButtons();" in admin_js
    assert "Application Insights query copied to clipboard." in admin_js
    assert "Verify the inbound MCP Easy Auth exclusions before saving." in admin_js
    assert "enableToggle.checked = false;" in admin_js


def test_inbound_mcp_governance_ui_policy_creation_contract():
    """Validate inbound MCP source policies are exposed in the governance editor."""
    admin_template = read_repo_file("application/single_app/templates/admin_settings.html")
    governance_js = read_repo_file("application/single_app/static/js/admin/admin_governance.js")
    admin_js = read_repo_file("application/single_app/static/js/admin/admin_settings.js")
    governance_source = read_repo_file("application/single_app/functions_governance.py")

    assert "inbound_mcp_source" in admin_template
    assert "inbound_mcp_source" in governance_js
    assert "inbound_mcp_access" not in admin_template
    assert "inbound_mcp_access" not in governance_js

    assert 'id="governance-inbound-mcp-section"' in admin_template
    assert "governance-new-inbound-mcp-policy-btn" in admin_template
    assert "governance-policy-help-btn" in admin_template
    assert "Inbound MCP Source Governance" in admin_template
    assert "Policy required for inbound MCP" in admin_template
    assert "New Inbound MCP Source Access Policy" in admin_template
    assert "New Inbound MCP Access Policy" not in admin_template
    assert 'data-governance-inbound-mcp-entity="inbound_mcp_source"' in admin_template
    assert 'data-governance-help-key="inbound_mcp_source"' in admin_template
    assert 'data-governance-help-key="inbound_mcp_access"' not in admin_template
    assert 'data-governance-help-key="inbound_mcp_tool"' not in admin_template
    assert 'data-governance-help-key="inbound_mcp_scope"' not in admin_template
    assert 'data-governance-help-key="inbound_mcp_resource_operation"' not in admin_template
    assert 'data-governance-help-key="inbound_mcp_target"' not in admin_template
    assert 'data-governance-inbound-mcp-item="list_personal_tags"' not in admin_template
    assert 'data-governance-inbound-mcp-item="personal:tags:list"' not in admin_template
    assert 'data-governance-inbound-mcp-item="personal:*"' not in admin_template
    assert 'data-governance-help-key="mcp_personal_destination"' in admin_template
    assert 'data-governance-help-key="mcp_group_destination"' in admin_template
    assert 'data-governance-help-key="mcp_global_destination"' in admin_template
    assert "const GOVERNANCE_CUSTOM_ITEM_ID_ENTITY_TYPES = new Set" in governance_js
    assert "const GOVERNANCE_INBOUND_MCP_QUICK_CREATE_ENTITY_TYPES = new Set" in governance_js
    assert "'inbound_mcp_source'," in governance_js
    assert "'inbound_mcp_access'," not in governance_js
    assert "function isGovernanceCustomItemIdEntityType" in governance_js
    assert "async function openGovernanceInboundMcpPolicyEditor" in governance_js
    assert "const GOVERNANCE_POLICY_HELP_CONTENT = {" in governance_js
    assert "function openGovernancePolicyHelpModal" in governance_js
    assert "function ensureGovernancePolicyHelpModal" in governance_js
    assert "function getInboundMcpSourceLookupOptionsFromSettings()" in governance_js
    assert "https://mcp.fedorg.gov/mcp*" in governance_js
    assert "Choose * for any accepted source" in governance_js
    assert "All accepted source IDs (*)" in governance_js
    assert "Inbound MCP Source (Legacy)" not in governance_js
    assert "Item ID: inbound_mcp." not in governance_js
    assert "Inbound MCP Client (Legacy)" not in governance_js
    assert "document.querySelectorAll('.governance-policy-help-btn')" in governance_js
    assert "allow_all: false" in governance_js
    assert "Quick-create inbound MCP policies open in restricted user/group mode by default." in admin_template
    assert "document.querySelectorAll('.governance-new-inbound-mcp-policy-btn')" in governance_js
    assert "button.dataset.governanceOpenTab === 'true'" in governance_js
    assert "window.openAdminSettingsTab(GOVERNANCE_MCP_TAB_HASH, 'governance-inbound-mcp-section')" in governance_js
    assert "policyName: button.dataset.governanceInboundMcpPolicyName || ''" in governance_js
    assert "resourceLabel: button.dataset.governanceInboundMcpResourceLabel || ''" in governance_js
    assert "System-managed policies cannot be edited." in governance_js
    assert "System-managed policies cannot be deleted." in governance_js
    assert "disabled: systemManaged" in governance_js
    assert "applyGovernanceItemPolicyActionDataset(button, policyDetails)" in governance_js
    assert "policy_id: button?.dataset?.policyId || ''" in governance_js
    assert "policy_id: String(policyIdInput?.value || '').trim()" in governance_js
    assert "The wildcard inbound MCP source policy is system-managed." not in governance_js
    assert "disallowWildcard: true" in admin_js
    assert "Use wildcard source access in Governance policies" in admin_js
    assert "syncSourceGovernanceCallouts" in admin_js
    assert "inbound-mcp-all-source-governance-callout" in admin_js
    assert "inbound-mcp-controlled-source-governance-callout" in admin_js
    assert "sync_inbound_mcp_source_governance_policy" not in governance_source
    assert "_delete_inbound_mcp_wildcard_source_policies" not in governance_source
    assert "INBOUND_MCP_SYSTEM_SOURCE_POLICY_ID = \"system-allow-all-sources\"" in governance_source
    assert "allow_system_managed: bool = False" in governance_source


if __name__ == "__main__":
    tests = [
        test_inbound_mcp_runtime_settings_are_app_settings,
        test_mcp_ui_gate_is_os_environment_only,
        test_admin_settings_mcp_ui_disabled_message_and_enabled_form,
        test_inbound_mcp_auth_uses_settings_runtime_config,
        test_inbound_mcp_easy_auth_guard_contract,
        test_inbound_mcp_governance_ui_policy_creation_contract,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as ex:
            print(f"FAIL: {ex}")
            import traceback

            traceback.print_exc()
            results.append(False)

    passed = sum(results)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
