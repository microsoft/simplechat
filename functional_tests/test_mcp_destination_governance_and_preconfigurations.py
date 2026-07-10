# test_mcp_destination_governance_and_preconfigurations.py
#!/usr/bin/env python3
"""
Functional test for outbound MCP destination governance and preconfigurations.
Version: 0.250.065
Implemented in: 0.250.064

This test ensures MCP destination allowlisting and server preconfiguration catalog
loading work without exposing secret-bearing defaults.
"""

import json
import os
import sys
import tempfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
PRECONFIGURATION_DIR = APP_DIR / "mcp_preconfigurations" / "definitions"
sys.path.insert(0, str(APP_DIR))

import functions_mcp_destinations as mcp_destinations  # noqa: E402
from functions_mcp_destinations import (  # noqa: E402
    MCP_DESTINATION_SCOPE_GLOBAL,
    MCP_DESTINATION_SCOPE_GROUP,
    MCP_DESTINATION_SCOPE_PERSONAL,
    McpDestinationPolicyError,
    assert_mcp_destination_allowed,
    evaluate_mcp_destination_policy,
)
from functions_mcp_preconfigurations import (  # noqa: E402
    ENABLE_LOCAL_MCP_PRECONFIGURATION_ENV,
    MCP_PRECONFIGURATION_PATHS_ENV,
    build_mcp_server_preconfigurations_response,
    clear_mcp_server_preconfiguration_cache,
    load_mcp_server_preconfigurations,
)


def _mcp_manifest(endpoint, preconfiguration_id="", server_profile="generic"):
    return {
        "name": "test_mcp",
        "type": "mcp",
        "endpoint": endpoint,
        "auth": {"type": "NoAuth"},
        "additionalFields": {
            "transport": "streamable_http",
            "server_profile": server_profile,
            "preconfiguration_id": preconfiguration_id,
            "auth_method": "none",
            "load_tools": True,
            "load_prompts": False,
            "request_timeout": 30,
            "connect_timeout": 10,
            "sse_read_timeout": 300,
            "retry_count": 0,
            "retry_backoff_seconds": 1,
            "allowed_tool_names": [],
            "mcp_tools": [],
        },
    }


def _policy(enabled=True, block_unsafe=True, common_patterns=None, personal_patterns=None, group_patterns=None):
    return {
        "enabled": enabled,
        "block_unsafe_destinations": block_unsafe,
        "common_patterns": common_patterns or [],
        "scope_patterns": {
            MCP_DESTINATION_SCOPE_PERSONAL: personal_patterns or [],
            MCP_DESTINATION_SCOPE_GROUP: group_patterns or [],
            MCP_DESTINATION_SCOPE_GLOBAL: [],
        },
        "group_patterns": {},
    }


def test_outbound_mcp_destination_policy_matching():
    """Validate exact, wildcard, preconfiguration, scope, and unsafe destination decisions."""
    learn_manifest = _mcp_manifest("https://learn.microsoft.com/api/mcp", "microsoft_learn")
    github_manifest = _mcp_manifest("https://api.githubcopilot.com/mcp/", "github")

    preconfiguration_policy = _policy(common_patterns=["preconfiguration:microsoft_learn"])
    decision = evaluate_mcp_destination_policy(
        learn_manifest,
        scope_type=MCP_DESTINATION_SCOPE_PERSONAL,
        scope_id="user-1",
        policy_config=preconfiguration_policy,
    )
    assert decision["allowed"] is True
    assert decision["matched_pattern"] == "preconfiguration:microsoft_learn"

    wildcard_policy = _policy(personal_patterns=["https://learn.microsoft.com/api/*"])
    assert evaluate_mcp_destination_policy(
        learn_manifest,
        scope_type=MCP_DESTINATION_SCOPE_PERSONAL,
        scope_id="user-1",
        policy_config=wildcard_policy,
    )["allowed"] is True
    assert evaluate_mcp_destination_policy(
        github_manifest,
        scope_type=MCP_DESTINATION_SCOPE_PERSONAL,
        scope_id="user-1",
        policy_config=wildcard_policy,
    )["allowed"] is False

    host_wildcard_policy = _policy(group_patterns=["*.githubcopilot.com"])
    assert_mcp_destination_allowed(
        github_manifest,
        scope_type=MCP_DESTINATION_SCOPE_GROUP,
        scope_id="group-1",
        policy_config=host_wildcard_policy,
    )

    unsafe_manifest = _mcp_manifest("http://127.0.0.1:9000/mcp")
    unsafe_decision = evaluate_mcp_destination_policy(
        unsafe_manifest,
        scope_type=MCP_DESTINATION_SCOPE_PERSONAL,
        scope_id="user-1",
        policy_config=_policy(enabled=False, block_unsafe=True),
    )
    assert unsafe_decision["allowed"] is False
    assert "loopback" in unsafe_decision["reason"]

    try:
        assert_mcp_destination_allowed(
            github_manifest,
            scope_type=MCP_DESTINATION_SCOPE_PERSONAL,
            scope_id="user-1",
            policy_config=wildcard_policy,
        )
        raise AssertionError("Expected destination policy denial for unlisted GitHub endpoint.")
    except McpDestinationPolicyError:
        pass


def test_builtin_mcp_preconfiguration_catalog():
    """Validate bundled preconfigurations are loaded, filtered, and secret-free."""
    previous_local = os.environ.get(ENABLE_LOCAL_MCP_PRECONFIGURATION_ENV)
    os.environ[ENABLE_LOCAL_MCP_PRECONFIGURATION_ENV] = "false"
    clear_mcp_server_preconfiguration_cache()
    try:
        preconfigurations = load_mcp_server_preconfigurations()
        preconfiguration_ids = {preconfiguration["id"] for preconfiguration in preconfigurations}

        assert {"microsoft_learn", "azure_documentation", "github"}.issubset(preconfiguration_ids)
        assert "local_dev" not in preconfiguration_ids

        personal_response = build_mcp_server_preconfigurations_response(MCP_DESTINATION_SCOPE_PERSONAL)
        assert personal_response["scope"] == MCP_DESTINATION_SCOPE_PERSONAL
        assert "microsoft_learn" in {item["id"] for item in personal_response["preconfigurations"]}

        for preconfiguration_file in PRECONFIGURATION_DIR.glob("*.json"):
            definition = json.loads(preconfiguration_file.read_text(encoding="utf-8"))
            assert definition["id"] == preconfiguration_file.stem
            defaults = definition.get("defaults", {})
            assert "endpoint" not in defaults
            assert "auth" not in defaults
            assert "token" not in defaults
            assert "password" not in defaults
            assert "secret" not in defaults

        os.environ[ENABLE_LOCAL_MCP_PRECONFIGURATION_ENV] = "true"
        clear_mcp_server_preconfiguration_cache()
        assert "local_dev" in {item["id"] for item in load_mcp_server_preconfigurations()}
    finally:
        if previous_local is None:
            os.environ.pop(ENABLE_LOCAL_MCP_PRECONFIGURATION_ENV, None)
        else:
            os.environ[ENABLE_LOCAL_MCP_PRECONFIGURATION_ENV] = previous_local
        clear_mcp_server_preconfiguration_cache()


def test_governance_item_policy_backed_destination_patterns():
    """Validate delegated item policies can supply MCP destination patterns by scope and principal."""
    original_list = mcp_destinations._list_governance_item_policies
    original_groups = mcp_destinations._get_governance_group_ids_for_user

    policies_by_entity_type = {
        "mcp_personal_destination": [
            {
                "item_id": "preconfiguration:github",
                "allow_all": False,
                "allowed_users": ["user-1"],
                "allowed_groups": [],
            }
        ],
        "mcp_group_destination": [
            {
                "item_id": "group:group-1::preconfiguration:microsoft_learn",
                "allow_all": True,
                "allowed_users": [],
                "allowed_groups": [],
            }
        ],
        "mcp_global_destination": [],
    }

    def fake_list_governance_item_policies(entity_type):
        return policies_by_entity_type.get(entity_type, [])

    try:
        mcp_destinations._list_governance_item_policies = fake_list_governance_item_policies
        mcp_destinations._get_governance_group_ids_for_user = lambda user_id: set()
        policy_config = mcp_destinations.get_mcp_destination_policy_config(
            {"enable_mcp_destination_governance": True},
            user_id="user-1",
        )

        github_decision = evaluate_mcp_destination_policy(
            _mcp_manifest("https://api.githubcopilot.com/mcp/", "github"),
            scope_type=MCP_DESTINATION_SCOPE_PERSONAL,
            scope_id="user-1",
            policy_config=policy_config,
            user_id="user-1",
        )
        assert github_decision["allowed"] is True
        assert github_decision["matched_pattern"] == "preconfiguration:github"

        learn_group_decision = evaluate_mcp_destination_policy(
            _mcp_manifest("https://learn.microsoft.com/api/mcp", "microsoft_learn"),
            scope_type=MCP_DESTINATION_SCOPE_GROUP,
            scope_id="group-1",
            policy_config=policy_config,
            user_id="user-1",
        )
        assert learn_group_decision["allowed"] is True

        learn_other_group_decision = evaluate_mcp_destination_policy(
            _mcp_manifest("https://learn.microsoft.com/api/mcp", "microsoft_learn"),
            scope_type=MCP_DESTINATION_SCOPE_GROUP,
            scope_id="group-2",
            policy_config=policy_config,
            user_id="user-1",
        )
        assert learn_other_group_decision["allowed"] is False

        denied_user_config = mcp_destinations.get_mcp_destination_policy_config(
            {"enable_mcp_destination_governance": True},
            user_id="user-2",
        )
        denied_decision = evaluate_mcp_destination_policy(
            _mcp_manifest("https://api.githubcopilot.com/mcp/", "github"),
            scope_type=MCP_DESTINATION_SCOPE_PERSONAL,
            scope_id="user-2",
            policy_config=denied_user_config,
            user_id="user-2",
        )
        assert denied_decision["allowed"] is False
    finally:
        mcp_destinations._list_governance_item_policies = original_list
        mcp_destinations._get_governance_group_ids_for_user = original_groups


def test_preconfiguration_catalog_filters_with_destination_governance():
    """Validate the server-side catalog only returns preconfigurations allowed by destination policy."""
    original_list = mcp_destinations._list_governance_item_policies
    original_groups = mcp_destinations._get_governance_group_ids_for_user

    def fake_list_governance_item_policies(entity_type):
        if entity_type == "mcp_personal_destination":
            return [
                {
                    "item_id": "preconfiguration:microsoft_learn",
                    "allow_all": True,
                    "allowed_users": [],
                    "allowed_groups": [],
                }
            ]
        return []

    try:
        mcp_destinations._list_governance_item_policies = fake_list_governance_item_policies
        mcp_destinations._get_governance_group_ids_for_user = lambda user_id: set()
        response = build_mcp_server_preconfigurations_response(
            MCP_DESTINATION_SCOPE_PERSONAL,
            scope_id="user-1",
            user_id="user-1",
            settings={"enable_mcp_destination_governance": True},
        )
        preconfiguration_ids = {item["id"] for item in response["preconfigurations"]}
        assert "microsoft_learn" in preconfiguration_ids
        assert "github" not in preconfiguration_ids
    finally:
        mcp_destinations._list_governance_item_policies = original_list
        mcp_destinations._get_governance_group_ids_for_user = original_groups


def test_custom_mcp_preconfiguration_path_loading_and_scope_filtering():
    """Validate org-authored preconfigurations can be loaded and scoped."""
    previous_paths = os.environ.get(MCP_PRECONFIGURATION_PATHS_ENV)
    with tempfile.TemporaryDirectory() as temp_dir:
        custom_preconfiguration = {
            "id": "contoso_docs",
            "version": "1.0.0",
            "displayName": "Contoso Docs MCP",
            "description": "Contoso documentation MCP endpoint.",
            "provider": "Contoso",
            "category": "Documentation",
            "enabled": True,
            "developmentOnly": False,
            "sortOrder": 25,
            "presetId": "generic",
            "endpoint": "https://mcp.contoso.example/docs",
            "transport": "streamable_http",
            "authRequirement": "none",
            "defaults": {
                "auth_method": "none",
                "api_key_header_name": "X-API-Key",
                "load_tools": True,
                "load_prompts": False,
                "request_timeout": 30,
                "connect_timeout": 10,
                "sse_read_timeout": 300,
                "retry_count": 0,
                "retry_backoff_seconds": 1,
                "allowed_tool_names": ["search_docs"],
            },
            "scopeEligibility": ["personal"],
            "destinationTags": ["contoso", "documentation"],
            "riskLabel": "low",
            "documentationUrl": "https://docs.contoso.example/mcp",
            "ui": {
                "helpText": "Use this preconfiguration for Contoso documentation search.",
            },
            "warnings": [],
        }
        Path(temp_dir, "contoso_docs.json").write_text(json.dumps(custom_preconfiguration, indent=4), encoding="utf-8")

        os.environ[MCP_PRECONFIGURATION_PATHS_ENV] = temp_dir
        clear_mcp_server_preconfiguration_cache()
        try:
            personal_ids = {
                item["id"]
                for item in build_mcp_server_preconfigurations_response(MCP_DESTINATION_SCOPE_PERSONAL)["preconfigurations"]
            }
            group_ids = {
                item["id"]
                for item in build_mcp_server_preconfigurations_response(MCP_DESTINATION_SCOPE_GROUP)["preconfigurations"]
            }
            assert "contoso_docs" in personal_ids
            assert "contoso_docs" not in group_ids
        finally:
            if previous_paths is None:
                os.environ.pop(MCP_PRECONFIGURATION_PATHS_ENV, None)
            else:
                os.environ[MCP_PRECONFIGURATION_PATHS_ENV] = previous_paths
            clear_mcp_server_preconfiguration_cache()


if __name__ == "__main__":
    try:
        test_outbound_mcp_destination_policy_matching()
        test_builtin_mcp_preconfiguration_catalog()
        test_governance_item_policy_backed_destination_patterns()
        test_preconfiguration_catalog_filters_with_destination_governance()
        test_custom_mcp_preconfiguration_path_loading_and_scope_filtering()
        success = True
    except Exception as ex:
        print(f"MCP destination governance and preconfigurations test failed: {ex}")
        import traceback

        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)
