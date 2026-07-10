# test_inbound_mcp_server_shell.py
#!/usr/bin/env python3
"""
Functional test for the disabled inbound MCP server shell.
Version: 0.250.063
Implemented in: 0.250.063

This test ensures the inbound MCP shell is wired as a disabled-by-default,
dedicated bearer-token route surface with safe PRM metadata, governance and
registry skeletons, and route policy coverage.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"


def read_repo_file(relative_path):
    """Read a repository file for source-level contract validation."""
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_inbound_mcp_config_defaults():
    """Validate inbound MCP is disabled by default and has explicit config knobs."""
    config_source = read_repo_file("application/single_app/config.py")

    assert 'VERSION = "0.250.063"' in config_source
    assert 'ENABLE_INBOUND_MCP_SERVER = os.getenv("ENABLE_INBOUND_MCP_SERVER", "false").lower() == "true"' in config_source
    assert 'INBOUND_MCP_REQUIRED_ROLE = os.getenv("INBOUND_MCP_REQUIRED_ROLE", "McpServerAccess")' in config_source
    assert 'INBOUND_MCP_REQUIRED_SCOPE = os.getenv("INBOUND_MCP_REQUIRED_SCOPE", "McpServerAccess")' in config_source
    assert 'INBOUND_MCP_ALLOWED_CLIENT_APP_IDS = _split_env_list(' in config_source
    assert 'INBOUND_MCP_ALLOWED_TENANT_IDS = _split_env_list(' in config_source
    assert 'INBOUND_MCP_ALLOWED_SOURCE_IDS = _split_env_list(' in config_source
    assert 'os.getenv("INBOUND_MCP_ALLOWED_SOURCE_IDS", "*")' in config_source
    assert 'INBOUND_MCP_SOURCE_HEADER = os.getenv("INBOUND_MCP_SOURCE_HEADER", "X-SimpleChat-MCP-Source")' in config_source
    assert 'INBOUND_MCP_RESOURCE_PATH = os.getenv("INBOUND_MCP_RESOURCE_PATH", "/api/mcp")' in config_source
    assert '"/.well-known/oauth-protected-resource/mcp"' in config_source


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
    assert "inbound_mcp_disabled" in auth_source
    assert "validate_bearer_token" in auth_source
    assert "ExternalApi" not in auth_source
    assert "g.inbound_mcp_auth_context" in auth_source
    assert 'guard._simplechat_auth_policy = ("inbound_mcp_required",)' in auth_source


def test_inbound_mcp_routes_expose_only_shell():
    """Validate routes expose PRM, health, and no-tools MCP shell only."""
    route_source = read_repo_file("application/single_app/route_inbound_mcp.py")

    assert '@bp.route("/.well-known/oauth-protected-resource/mcp", methods=["GET"])' in route_source
    assert '@bp.route("/api/mcp/health", methods=["GET"])' in route_source
    assert '@bp.route("/api/mcp", methods=["POST"])' in route_source
    assert route_source.count("@swagger_route(security=get_auth_security())") == 3
    assert "build_inbound_mcp_protected_resource_metadata" in route_source
    assert '"bearer_methods_supported": ["header"]' in route_source
    assert '"resource_documentation": "https://aka.ms/simplechat-documentation"' in route_source
    assert "get_inbound_mcp_governance_baseline()" in route_source
    assert "get_enabled_inbound_mcp_tools(auth_context)" in route_source
    assert "inbound_mcp_no_tools_enabled" in route_source
    assert '"enabled_tools": []' in route_source


def test_inbound_mcp_governance_and_registry_default_deny():
    """Validate registry and governance helpers expose no enabled tools by default."""
    governance_source = read_repo_file("application/single_app/functions_mcp_server_governance.py")
    registry_source = read_repo_file("application/single_app/functions_mcp_server_registry.py")

    assert '"default_effect": "deny"' in governance_source
    assert '"personal_scope_enabled": False' in governance_source
    assert '"group_scope_enabled": False' in governance_source
    assert '"public_scope_enabled": False' in governance_source
    assert '"all_scope_enabled": False' in governance_source
    assert 'allowed=False' in governance_source
    assert 'error="mcp_tool_not_allowed"' in governance_source

    assert "PLANNED_INBOUND_MCP_TOOLS" in registry_source
    assert 'enabled_by_default": False' in registry_source
    assert "def get_enabled_inbound_mcp_tools(" in registry_source
    assert "return []" in registry_source


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
        test_inbound_mcp_routes_expose_only_shell,
        test_inbound_mcp_governance_and_registry_default_deny,
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
