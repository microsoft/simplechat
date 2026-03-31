# test_group_agent_endpoint_scope_resolution.py
"""
Functional test for group agent endpoint scope resolution.
Version: 0.239.193
Implemented in: 0.239.192

This test ensures group agents resolve model endpoints from conversation or
persisted group scope instead of the mutable active group, while honoring the
group-specific custom endpoint feature flags.
"""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOADER_FILE = ROOT / "application" / "single_app" / "semantic_kernel_loader.py"
GROUP_AGENTS_FILE = ROOT / "application" / "single_app" / "functions_group_agents.py"
ROUTE_AGENTS_FILE = ROOT / "application" / "single_app" / "route_backend_agents.py"
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
FIX_DOC_FILE = ROOT / "docs" / "explanation" / "fixes" / "GROUP_AGENT_ENDPOINT_SCOPE_RESOLUTION_FIX.md"


def read_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


def test_group_agent_endpoint_scope_resolution() -> None:
    print("🔍 Validating group agent endpoint scope resolution...")

    loader_content = read_text(LOADER_FILE)
    group_agents_content = read_text(GROUP_AGENTS_FILE)
    route_agents_content = read_text(ROUTE_AGENTS_FILE)
    config_content = read_text(CONFIG_FILE)
    fix_doc_content = read_text(FIX_DOC_FILE)

    assert "def resolve_agent_config(agent, settings, group_scope_id=None):" in loader_content, (
        "resolve_agent_config should accept an explicit group scope override."
    )
    assert "explicit_group_scope_id = str(group_scope_id or \"\").strip()" in loader_content, (
        "Loader should normalize the explicit group scope id."
    )
    assert "allow_group_custom_endpoints = settings.get('allow_group_custom_endpoints', False) or settings.get('allow_group_custom_agent_endpoints', False)" in loader_content, (
        "Group endpoint gating should use the group-specific flag pair."
    )
    assert "allow_group_custom_endpoints = settings.get('allow_group_custom_endpoints', False) or settings.get('allow_user_custom_agent_endpoints', False)" not in loader_content, (
        "Group endpoint gating must not depend on the user-scoped legacy flag."
    )

    explicit_index = loader_content.index("if explicit_group_scope_id:")
    persisted_index = loader_content.index("persisted_group_id = str(agent.get(\"group_id\") or \"\").strip()")
    active_group_index = loader_content.index("return require_active_group(get_current_user_id())")
    assert explicit_index < persisted_index < active_group_index, (
        "Group scope precedence should be explicit scope, then persisted group_id, then active group fallback."
    )

    assert "effective_group_id = conversation_scope_group_id or selected_group_id" in loader_content, (
        "Conversation group scope should take precedence over selected agent group_id."
    )
    assert "Group agent scope mismatch between conversation and selection." in loader_content, (
        "Loader should reject mismatched conversation and selected-agent group scopes."
    )
    assert "assert_group_role(" in loader_content and "allowed_roles=(\"Owner\", \"Admin\", \"DocumentManager\", \"User\")" in loader_content, (
        "Loader should validate membership against the resolved group scope."
    )
    assert "group_scope_id=effective_group_id" in loader_content, (
        "Resolved group scope should be threaded into single-agent loading."
    )
    assert loader_content.count("group_id = get_group_scope_id()") >= 2, (
        "Both multi-endpoint and Foundry resolution should use get_group_scope_id()."
    )

    assert "payload[\"group_id\"] = group_id" in group_agents_content, (
        "Persisted group agents should retain their authoritative group_id."
    )
    assert '"group_id": matched_agent.get(\'group_id\')' in route_agents_content, (
        "Selected group agent payloads should preserve group_id for later resolution."
    )

    assert 'VERSION = "0.239.193"' in config_content, (
        "config.py should be updated to the implementation version."
    )
    assert "Fixed/Implemented in version: **0.239.192**" in fix_doc_content, (
        "Fix documentation should record the implementation version."
    )
    assert "conversation group first, persisted group second, active group only as a legacy fallback" in fix_doc_content, (
        "Fix documentation should describe the new scope precedence."
    )

    print("✅ Group agent endpoint scope resolution checks passed.")


if __name__ == "__main__":
    try:
        test_group_agent_endpoint_scope_resolution()
        success = True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)