# test_inbound_mcp_admin_ui.py
#!/usr/bin/env python3
"""
Functional test for the inbound MCP admin UI settings slice.
Version: 0.250.081
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

This test ensures inbound MCP runtime configuration is stored in app_settings,
the minimal Admin Settings UI is gated by an OS-only feature flag, and the
feature flag itself is not exposed as an editable UI setting. It also verifies
that enabling inbound MCP requires the Easy Auth exclusion confirmation and
server-side endpoint check.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    """Read a repository file for source-level contract validation."""
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_inbound_mcp_runtime_settings_are_app_settings():
    """Validate mutable inbound MCP runtime settings live in app_settings."""
    config_source = read_repo_file("application/single_app/config.py")
    helper_source = read_repo_file("application/single_app/functions_mcp_server_config.py")
    settings_source = read_repo_file("application/single_app/functions_settings.py")

    assert 'VERSION = "0.250.081"' in config_source
    assert "ENABLE_INBOUND_MCP_SERVER = os.getenv" not in config_source
    assert "INBOUND_MCP_REQUIRED_ROLE = os.getenv" not in config_source
    assert "INBOUND_MCP_ALLOWED_CLIENT_APP_IDS = _split_env_list" not in config_source

    expected_settings = [
        '"enable_inbound_mcp_server": False',
        '"inbound_mcp_required_user_roles": ["InboundMCPUserAccess"]',
        '"inbound_mcp_required_app_roles": ["InboundMCPAppAccess"]',
        '"inbound_mcp_required_scope": "DelegatedMcpServerAccess"',
        '"inbound_mcp_allowed_client_app_ids": []',
        '"inbound_mcp_allowed_tenant_ids": []',
        '"inbound_mcp_allowed_source_ids": ["*"]',
        '"inbound_mcp_source_header": "X-SimpleChat-MCP-Source"',
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


def test_admin_settings_mcp_ui_is_gated_and_minimal():
    """Validate the Admin Settings card and sidebar are behind mcp_ui_enabled."""
    admin_template = read_repo_file("application/single_app/templates/admin_settings.html")
    sidebar_template = read_repo_file("application/single_app/templates/_sidebar_nav.html")

    assert "{% if mcp_ui_enabled %}" in admin_template
    assert 'id="inbound-mcp-configuration"' in admin_template
    assert 'name="enable_inbound_mcp_server"' in admin_template
    assert 'name="inbound_mcp_required_user_roles"' in admin_template
    assert 'name="inbound_mcp_required_app_roles"' in admin_template
    assert 'name="inbound_mcp_required_role"' not in admin_template
    assert 'name="inbound_mcp_required_scope"' in admin_template
    assert 'name="inbound_mcp_allowed_client_app_ids"' in admin_template
    assert 'name="inbound_mcp_allowed_tenant_ids"' in admin_template
    assert 'name="inbound_mcp_allowed_source_ids"' in admin_template
    assert 'name="inbound_mcp_source_header"' in admin_template
    assert 'name="enable_mcp_ui"' not in admin_template
    assert "ENABLE_MCP_UI" not in admin_template

    assert "{% if mcp_ui_enabled %}" in sidebar_template
    assert 'data-section="inbound-mcp-configuration"' in sidebar_template
    assert "Inbound MCP" in sidebar_template


def test_inbound_mcp_auth_uses_settings_runtime_config():
    """Validate the auth guard no longer imports static env-backed MCP runtime config."""
    auth_source = read_repo_file("application/single_app/functions_mcp_server_auth.py")
    route_source = read_repo_file("application/single_app/route_inbound_mcp.py")

    assert "from functions_mcp_server_config import get_inbound_mcp_runtime_config" in auth_source
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
    assert "from functions_mcp_server_config import get_inbound_mcp_runtime_config" in route_source
    assert "runtime_config = get_inbound_mcp_runtime_config()" in route_source


def test_inbound_mcp_easy_auth_guard_contract():
    """Validate the Easy Auth exclusion modal, endpoint probe, and save guard exist."""
    helper_source = read_repo_file("application/single_app/functions_mcp_server_config.py")
    admin_route_source = read_repo_file("application/single_app/route_frontend_admin_settings.py")
    admin_template = read_repo_file("application/single_app/templates/admin_settings.html")
    admin_js = read_repo_file("application/single_app/static/js/admin/admin_settings.js")

    required_paths = [
        'INBOUND_MCP_EASY_AUTH_EXCLUDED_PATHS = (',
        'INBOUND_MCP_PRM_PATH,',
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
    assert '$authSettingsUrl = "$resourceManagerEndpoint$siteId/config/authsettingsV2?api-version=2023-12-01"' in admin_route_source
    assert "$rawCurrent = az rest --method get --url $authSettingsUrl" in admin_route_source
    assert "$current = $rawCurrent | ConvertFrom-Json" in admin_route_source
    assert "authsettingsV2/list" not in admin_route_source
    assert "--method post --url $listUrl" not in admin_route_source

    assert 'id="inboundMcpEasyAuthModal"' in admin_template
    assert 'id="inbound-mcp-easy-auth-confirm"' in admin_template
    assert 'id="inbound-mcp-easy-auth-verify"' in admin_template
    assert 'id="inbound-mcp-copy-script"' in admin_template
    assert 'aria-label="Copy PowerShell script"' in admin_template
    assert 'id="inbound-mcp-easy-auth-script-code"' in admin_template
    assert "/.well-known/oauth-protected-resource/mcp" in admin_template
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
    assert "navigator.clipboard.writeText(scriptText)" in admin_js
    assert "PowerShell script copied to clipboard." in admin_js
    assert "Verify the inbound MCP Easy Auth exclusions before saving." in admin_js
    assert "enableToggle.checked = false;" in admin_js


def test_inbound_mcp_governance_ui_policy_creation_contract():
    """Validate the simplified inbound MCP access policy is exposed in the governance editor."""
    admin_template = read_repo_file("application/single_app/templates/admin_settings.html")
    governance_js = read_repo_file("application/single_app/static/js/admin/admin_governance.js")

    expected_entities = [
        "inbound_mcp_access",
    ]
    for entity in expected_entities:
        assert entity in admin_template
        assert entity in governance_js

    assert 'id="governance-inbound-mcp-section"' in admin_template
    assert "governance-new-inbound-mcp-policy-btn" in admin_template
    assert "governance-policy-help-btn" in admin_template
    assert "Inbound MCP Access Governance" in admin_template
    assert "Minimum policy required for inbound MCP" in admin_template
    assert "New Inbound MCP Access Policy" in admin_template
    assert 'data-governance-inbound-mcp-entity="inbound_mcp_access"' in admin_template
    assert 'data-governance-inbound-mcp-item="inbound_mcp"' in admin_template
    assert 'data-governance-help-key="inbound_mcp_access"' in admin_template
    assert 'data-governance-help-key="inbound_mcp_source"' not in admin_template
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
    assert "'inbound_mcp_access'," in governance_js
    assert "function isGovernanceCustomItemIdEntityType" in governance_js
    assert "async function openGovernanceInboundMcpPolicyEditor" in governance_js
    assert "const GOVERNANCE_POLICY_HELP_CONTENT = {" in governance_js
    assert "function openGovernancePolicyHelpModal" in governance_js
    assert "function ensureGovernancePolicyHelpModal" in governance_js
    assert "https://agent.fedorg.gov" in governance_js
    assert "https://mcp.fedorg.gov/mcp*" in governance_js
    assert "Source filtering now lives in Inbound MCP configuration." in governance_js
    assert "Inbound MCP Source (Legacy)" in governance_js
    assert "Item ID: inbound_mcp." in governance_js
    assert "Inbound MCP Client (Legacy)" in governance_js
    assert "document.querySelectorAll('.governance-policy-help-btn')" in governance_js
    assert "allow_all: false" in governance_js
    assert "Quick-create inbound MCP policies open in restricted user/group mode by default." in admin_template
    assert "document.querySelectorAll('.governance-new-inbound-mcp-policy-btn')" in governance_js


if __name__ == "__main__":
    tests = [
        test_inbound_mcp_runtime_settings_are_app_settings,
        test_mcp_ui_gate_is_os_environment_only,
        test_admin_settings_mcp_ui_is_gated_and_minimal,
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
