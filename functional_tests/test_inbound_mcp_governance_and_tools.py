# test_inbound_mcp_governance_and_tools.py
#!/usr/bin/env python3
"""
Functional test for inbound MCP governance and first tool contracts.
Version: 0.250.081
Implemented in: 0.250.070
Simplified personal access/source governance implemented in: 0.250.080
Single inbound MCP access policy implemented in: 0.250.081

This test ensures inbound MCP uses explicit inbound MCP access governance,
exposes only implemented tools through JSON-RPC, and binds personal tools to
the delegated user rather than caller-supplied user identifiers.
"""

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    """Read a repository file for source-level contract validation."""
    return (ROOT_DIR / relative_path).read_text(encoding="utf-8")


def test_governance_policy_dimensions():
    """Validate inbound MCP governance requires the single access policy."""
    source = read_repo_file("application/single_app/functions_mcp_server_governance.py")

    expected_entities = [
        "inbound_mcp_access",
    ]
    for entity in expected_entities:
        assert entity in source

    assert "get_explicit_item_policies(entity_type, item_id)" in source
    assert "has no explicit inbound MCP policy" in source
    assert "effect == \"deny\"" in source
    assert "mcp_identity_type_not_allowed" in source
    assert "mcp_delegated_user_required" in source
    assert '"mcp_access_not_allowed"' in source
    assert "_evaluate_explicit_policy_group(" in source
    assert "INBOUND_MCP_ACCESS_ITEM_ID = \"inbound_mcp\"" in source
    assert "INBOUND_MCP_ACCESS_POLICY_ENTITY" in source
    assert "[INBOUND_MCP_ACCESS_ITEM_ID, normalized_scope]" in source
    assert '"source_filtering_config_key": "inbound_mcp_allowed_source_ids"' in source
    assert '"mcp_source_not_allowed"' not in source
    assert "LEGACY_INBOUND_MCP_POLICY_ENTITIES" in source
    assert "INBOUND_MCP_CLIENT_POLICY_ENTITY" not in source
    assert "INBOUND_MCP_TOOL_POLICY_ENTITY" not in source
    assert "INBOUND_MCP_RESOURCE_OPERATION_POLICY_ENTITY" not in source
    assert 'f"{normalized_scope}:{normalized_resource_family}:{normalized_operation}"' not in source
    assert 'f"{normalized_scope}:{normalized_target_scope_id}"' in source
    assert 'f"{normalized_scope}:*"' in source


def test_registry_exposes_only_implemented_governed_tools():
    """Validate the registry separates planned tools from implemented tools."""
    source = read_repo_file("application/single_app/functions_mcp_server_registry.py")

    assert '"id": "list_personal_tags"' in source
    assert '"implemented": True' in source
    assert '"id": "execute_workflow"' in source
    assert '"implemented": False' in source
    assert "if not bool(tool.get(\"implemented\", False)):" in source
    assert "evaluate_inbound_mcp_governance(" in source
    assert "build_mcp_tool_descriptor" in source
    assert '"inputSchema": tool.get("input_schema")' in source
    assert "show_user_profile" not in source
    assert "list_agent_template_tags" not in source


def test_json_rpc_tool_dispatch_contract():
    """Validate the inbound route implements the minimal MCP JSON-RPC methods."""
    source = read_repo_file("application/single_app/route_inbound_mcp.py")

    assert '"jsonrpc": "2.0"' in source
    assert 'method == "initialize"' in source
    assert 'method == "tools/list"' in source
    assert 'method == "tools/call"' in source
    assert 'method == "notifications/initialized"' in source
    assert "build_mcp_tool_descriptor(tool)" in source
    assert "execute_inbound_mcp_tool(tool.get(\"id\", \"\"), auth_context, arguments)" in source
    assert "Inbound MCP governance denied the tool call." in source
    assert "Unsupported inbound MCP method." in source


def test_list_personal_tags_contract():
    """Validate list_personal_tags stays delegated-user scoped and bounded."""
    source = read_repo_file("application/single_app/functions_mcp_server_tools.py")

    assert "INBOUND_MCP_TOOL_RESULT_LIMIT_MAX = 100" in source
    assert "delegated_user_id = _require_delegated_user_id(auth_context)" in source
    assert "get_workspace_tags(delegated_user_id)" in source
    assert "get_workspace_tags(arguments" not in source
    assert "user_id" not in source.replace("delegated_user_id", "")
    assert '"scope": "personal"' in source
    assert '"name": tag_name' in source
    assert '"count": int(tag.get("count") or 0)' in source
    assert '"color": str(tag.get("color") or "").strip()' in source


if __name__ == "__main__":
    tests = [
        test_governance_policy_dimensions,
        test_registry_exposes_only_implemented_governed_tools,
        test_json_rpc_tool_dispatch_contract,
        test_list_personal_tags_contract,
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
