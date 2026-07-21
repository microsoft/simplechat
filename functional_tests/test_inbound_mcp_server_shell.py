# test_inbound_mcp_server_shell.py
#!/usr/bin/env python3
"""
Functional test for the inbound MCP server shell.
Version: 0.250.081
Implemented in: 0.250.063
OAuth protected-resource discovery header implemented in: 0.250.076
Inbound MCP user/app role split implemented in: 0.250.078
Simplified inbound MCP access/source governance implemented in: 0.250.080
Single inbound MCP access policy implemented in: 0.250.081

This test ensures the inbound MCP shell is wired as a disabled-by-default,
dedicated bearer-token route surface with safe PRM metadata, explicit
governance, an explicit registry, app-settings-backed runtime configuration,
and route policy coverage.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"


def read_repo_file(relative_path):
    """Read a repository file for source-level contract validation."""
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_inbound_mcp_config_defaults():
    """Validate inbound MCP runtime config is app-settings backed and disabled by default."""
    config_source = read_repo_file("application/single_app/config.py")
    settings_source = read_repo_file("application/single_app/functions_settings.py")
    mcp_config_source = read_repo_file("application/single_app/functions_mcp_server_config.py")

    assert 'VERSION = "0.250.081"' in config_source
    assert 'ENABLE_INBOUND_MCP_SERVER = os.getenv(' not in config_source
    assert 'INBOUND_MCP_REQUIRED_ROLE = os.getenv(' not in config_source
    assert 'INBOUND_MCP_REQUIRED_SCOPE = os.getenv(' not in config_source
    assert 'INBOUND_MCP_ALLOWED_CLIENT_APP_IDS = _split_env_list(' not in config_source
    assert 'INBOUND_MCP_SOURCE_HEADER = os.getenv(' not in config_source
    assert 'ENABLE_MCP_UI = os.getenv("ENABLE_MCP_UI"' in config_source
    assert 'INBOUND_MCP_RESOURCE_PATH = "/api/mcp"' in config_source
    assert '"/.well-known/oauth-protected-resource/mcp"' in config_source
    assert '"enable_inbound_mcp_server": False' in mcp_config_source
    assert '"inbound_mcp_required_user_roles": ["InboundMCPUserAccess"]' in mcp_config_source
    assert '"inbound_mcp_required_app_roles": ["InboundMCPAppAccess"]' in mcp_config_source
    assert '"inbound_mcp_required_scope": "DelegatedMcpServerAccess"' in mcp_config_source
    assert '"inbound_mcp_allowed_source_ids": ["*"]' in mcp_config_source
    assert "**INBOUND_MCP_SETTINGS_DEFAULTS" in settings_source
    assert "normalize_inbound_mcp_settings(merged)" in settings_source
    assert "normalize_inbound_mcp_settings(settings_item)" in settings_source


def test_inbound_mcp_auth_guard_is_dedicated():
    """Validate inbound MCP uses a dedicated auth guard and not ExternalApi auth."""
    auth_source = read_repo_file("application/single_app/functions_mcp_server_auth.py")

    assert "def validate_inbound_mcp_request(" in auth_source
    assert "def inbound_mcp_required_blueprint():" in auth_source
    assert "bearer_token_required" in auth_source
    assert "invalid_token" in auth_source
    assert "mcp_client_not_allowed" in auth_source
    assert "mcp_source_not_allowed" in auth_source
    assert "insufficient_mcp_permissions" in auth_source
    assert "_has_required_delegated_scope" in auth_source
    assert "_has_required_delegated_user_role" in auth_source
    assert "_has_required_app_role" in auth_source
    assert "_has_required_role_or_scope" not in auth_source
    assert "inbound_mcp_disabled" in auth_source
    assert "WWW-Authenticate" in auth_source
    assert "resource_metadata" in auth_source
    assert "_build_resource_metadata_url(flask_request)" in auth_source
    assert "build_inbound_mcp_auth_error_response(auth_error, request)" in auth_source
    assert "validate_bearer_token" in auth_source
    assert "ExternalApi" not in auth_source
    assert "g.inbound_mcp_auth_context" in auth_source
    assert 'guard._simplechat_auth_policy = ("inbound_mcp_required",)' in auth_source
    assert "get_inbound_mcp_runtime_config()" in auth_source
    assert "ENABLE_INBOUND_MCP_SERVER" not in auth_source
    assert "INBOUND_MCP_ALLOWED_CLIENT_APP_IDS" not in auth_source


def test_inbound_mcp_routes_expose_json_rpc_shell():
    """Validate routes expose PRM, health, and governed JSON-RPC MCP methods."""
    route_source = read_repo_file("application/single_app/route_inbound_mcp.py")

    assert '@bp.route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])' in route_source
    assert '@bp.route("/api/mcp/health", methods=["GET"])' in route_source
    assert '@bp.route("/api/mcp", methods=["POST"])' in route_source
    assert route_source.count("@swagger_route(security=get_auth_security())") == 3
    assert "build_inbound_mcp_protected_resource_metadata" in route_source
    assert "get_inbound_mcp_runtime_config()" in route_source
    assert '"bearer_methods_supported": ["header"]' in route_source
    assert '"resource_documentation": "https://aka.ms/simplechat-documentation"' in route_source
    assert "get_inbound_mcp_governance_baseline()" in route_source
    assert "get_enabled_inbound_mcp_tools(auth_context)" in route_source
    assert 'method == "initialize"' in route_source
    assert 'method == "tools/list"' in route_source
    assert 'method == "tools/call"' in route_source
    assert "execute_inbound_mcp_tool" in route_source
    assert "Unsupported inbound MCP method." in route_source


def test_inbound_mcp_governance_and_registry_default_deny():
    """Validate registry and governance helpers keep tools deny-by-default."""
    governance_source = read_repo_file("application/single_app/functions_mcp_server_governance.py")
    registry_source = read_repo_file("application/single_app/functions_mcp_server_registry.py")

    assert '"default_effect": "deny"' in governance_source
    assert '"personal_scope_enabled": False' in governance_source
    assert '"personal_access_enabled": False' in governance_source
    assert '"group_scope_enabled": False' in governance_source
    assert '"public_scope_enabled": False' in governance_source
    assert '"all_scope_enabled": False' in governance_source
    assert '"required_policy_entities"' in governance_source
    assert "get_explicit_item_policies" in governance_source
    assert "explicit inbound MCP policy" in governance_source
    assert "effect == \"deny\"" in governance_source
    assert "INBOUND_MCP_ACCESS_POLICY_ENTITY" in governance_source
    assert "INBOUND_MCP_ACCESS_ITEM_ID" in governance_source
    assert "INBOUND_MCP_SOURCE_POLICY_ENTITY" not in governance_source
    assert '"source_filtering_config_key": "inbound_mcp_allowed_source_ids"' in governance_source
    assert "LEGACY_INBOUND_MCP_POLICY_ENTITIES" in governance_source
    assert "INBOUND_MCP_CLIENT_POLICY_ENTITY" not in governance_source
    assert "INBOUND_MCP_TOOL_POLICY_ENTITY" not in governance_source
    assert "INBOUND_MCP_RESOURCE_OPERATION_POLICY_ENTITY" not in governance_source
    assert "INBOUND_MCP_TARGET_POLICY_ENTITY" in governance_source

    assert "PLANNED_INBOUND_MCP_TOOLS" in registry_source
    assert "show_user_profile" not in registry_source
    assert "list_agent_template_tags" not in registry_source
    assert '"id": "list_personal_tags"' in registry_source
    assert '"id": "execute_workflow"' in registry_source
    assert '"resource_family": "workflows"' in registry_source
    assert '"operation": "execute"' in registry_source
    assert 'enabled_by_default": False' in registry_source
    assert '"implemented": True' in registry_source
    assert '"implemented": False' in registry_source
    assert "evaluate_inbound_mcp_governance" in registry_source
    assert "def get_enabled_inbound_mcp_tools(" in registry_source
    assert "return []" not in registry_source


def test_inbound_mcp_first_tool_service_layer():
    """Validate the first exposed tool is service-layer backed and user-bound."""
    tool_source = read_repo_file("application/single_app/functions_mcp_server_tools.py")

    assert "def list_personal_tags(auth_context, arguments=None):" in tool_source
    assert "delegated_user_id = _require_delegated_user_id(auth_context)" in tool_source
    assert "get_workspace_tags(delegated_user_id)" in tool_source
    assert '"scope": "personal"' in tool_source
    assert "def execute_inbound_mcp_tool(tool_id, auth_context, arguments=None):" in tool_source
    assert 'normalized_tool_id == "list_personal_tags"' in tool_source
    assert "raise LookupError" in tool_source


def test_inbound_mcp_app_and_route_policy_wiring():
    """Validate app registration and route policy tests know the inbound MCP surface."""
    app_source = read_repo_file("application/single_app/app.py")
    inventory_test_source = read_repo_file("functional_tests/route_tests/test_route_blueprint_policy_inventory.py")
    unauth_test_source = read_repo_file("functional_tests/route_tests/test_route_unauthenticated_policy_contract.py")

    assert "from route_inbound_mcp import register_route_inbound_mcp" in app_source
    assert "from functions_mcp_server_auth import inbound_mcp_required_blueprint" in app_source
    assert "register_route_blueprint('inbound_mcp', register_route_inbound_mcp, inbound_mcp_required_blueprint)" in app_source

    assert '"inbound_mcp": ("inbound_mcp_required",)' in inventory_test_source
    assert '"/.well-known/oauth-protected-resource/mcp"' in inventory_test_source

    assert '"/.well-known/oauth-protected-resource/mcp"' in unauth_test_source
    assert "INBOUND_MCP_BEARER_PATH_PREFIXES" in unauth_test_source
    assert '"/api/mcp"' in unauth_test_source
    assert '"inbound_mcp_bearer_401_or_404"' in unauth_test_source


if __name__ == "__main__":
    tests = [
        test_inbound_mcp_config_defaults,
        test_inbound_mcp_auth_guard_is_dedicated,
        test_inbound_mcp_routes_expose_json_rpc_shell,
        test_inbound_mcp_governance_and_registry_default_deny,
        test_inbound_mcp_first_tool_service_layer,
        test_inbound_mcp_app_and_route_policy_wiring,
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
