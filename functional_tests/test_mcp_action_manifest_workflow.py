#!/usr/bin/env python3
"""
Functional test for MCP action manifest workflow.
Version: 0.250.059
Implemented in: 0.241.103

This test ensures that MCP action configuration defaults, validation, and
plugin metadata creation produce the manifest shape used by the shared action
modal.
"""

import os
import sys
import asyncio
import types
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))


class _NoopLogger:
    def __getattr__(self, _name):
        return lambda *args, **kwargs: None


sys.modules.setdefault(
    "functions_appinsights",
    types.SimpleNamespace(
        log_event=lambda *args, **kwargs: None,
        get_appinsights_logger=lambda: _NoopLogger(),
    ),
)
sys.modules.setdefault(
    "functions_authentication",
    types.SimpleNamespace(get_current_user_id=lambda: "functional-test-user"),
)
sys.modules.setdefault(
    "functions_debug",
    types.SimpleNamespace(debug_print=lambda *args, **kwargs: None),
)
sys.modules.setdefault(
    "functions_azure_maps",
    types.SimpleNamespace(
        AZURE_MAPS_DEFAULT_ENDPOINT="https://atlas.microsoft.com",
        AZURE_MAPS_PLUGIN_TYPE="azure_maps_openlayers",
    ),
)
sys.modules.setdefault(
    "functions_blob_storage_operations",
    types.SimpleNamespace(BLOB_STORAGE_PLUGIN_TYPE="blob_storage"),
)
sys.modules.setdefault(
    "functions_databricks_operations",
    types.SimpleNamespace(
        DATABRICKS_CLOUD_AZURE_COMMERCIAL="azure_commercial",
        DATABRICKS_LEGACY_TABLE_PLUGIN_TYPE="databricks_table",
        DATABRICKS_PLUGIN_TYPE="databricks",
        normalize_databricks_additional_fields=lambda value: value or {},
    ),
)
sys.modules.setdefault(
    "functions_snowflake_operations",
    types.SimpleNamespace(
        SNOWFLAKE_AUTH_METHOD_KEY_PAIR="key_pair",
        SNOWFLAKE_AUTH_METHOD_OAUTH="oauth",
        SNOWFLAKE_AUTH_METHOD_PASSWORD="password",
        SNOWFLAKE_DEFAULT_ENDPOINT="snowflake://query",
        SNOWFLAKE_PLUGIN_TYPE="snowflake",
        normalize_snowflake_additional_fields=lambda value: value or {},
    ),
)
sys.modules.setdefault(
    "functions_tableau_operations",
    types.SimpleNamespace(
        TABLEAU_AUTH_METHOD_PAT="personal_access_token",
        TABLEAU_AUTH_METHOD_USERNAME_PASSWORD="username_password",
        TABLEAU_DEFAULT_MAX_RESULTS=100,
        TABLEAU_DEFAULT_PAGE_SIZE=100,
        TABLEAU_DEFAULT_TIMEOUT=30,
        TABLEAU_MAX_MAX_RESULTS=1000,
        TABLEAU_MAX_PAGE_SIZE=1000,
        TABLEAU_MAX_TIMEOUT=300,
        TABLEAU_MIN_MAX_RESULTS=1,
        TABLEAU_MIN_PAGE_SIZE=1,
        TABLEAU_MIN_TIMEOUT=1,
        TABLEAU_PLUGIN_TYPE="tableau",
        normalize_tableau_additional_fields=lambda value: value or {},
        normalize_tableau_server_url=lambda value: value,
    ),
)
sys.modules.setdefault(
    "functions_simplechat_operations",
    types.SimpleNamespace(SIMPLECHAT_DEFAULT_ENDPOINT="simplechat://internal"),
)

from functions_mcp_operations import (  # noqa: E402
    MCP_PLUGIN_TYPE,
    classify_mcp_exception,
    normalize_mcp_additional_fields,
)
from semantic_kernel_plugins.mcp_plugin_factory import McpPluginFactory
from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker


def test_mcp_action_manifest_workflow():
    """Validate MCP manifest normalization, health validation, and metadata."""
    print("Testing MCP action manifest workflow...")

    manifest = {
        "name": "github_mcp",
        "displayName": "GitHub MCP",
        "type": MCP_PLUGIN_TYPE,
        "description": "MCP server for repository tools.",
        "endpoint": "https://example.com/mcp",
        "auth": {
            "type": "key",
            "key": "test-token",
        },
        "metadata": {},
        "additionalFields": {
            "server_profile": "splunk_mcp",
            "transport": "streamable-http",
            "auth_method": "bearer_token",
            "custom_headers": {
                "Authorization": "Splunk custom-token",
                "X-Splunk-Host": "search-head",
            },
            "load_tools": True,
            "load_prompts": False,
            "request_timeout": "45",
            "connect_timeout": "12",
            "sse_read_timeout": "120",
            "retry_count": "2",
            "retry_backoff_seconds": "3",
            "allowed_tool_names": "search_repositories\nget_issue\nsearch_repositories",
            "mcp_tools": [
                {
                    "original_name": "search-repositories",
                    "function_name": "search_repositories",
                    "description": "Search repositories.",
                    "input_schema": {"type": "object"},
                }
            ],
        },
    }

    normalized_fields = normalize_mcp_additional_fields(manifest["additionalFields"])
    assert normalized_fields["server_profile"] == "splunk"
    assert normalized_fields["transport"] == "streamable_http"
    assert normalized_fields["auth_method"] == "bearer"
    assert normalized_fields["custom_headers"]["Authorization"] == "Splunk custom-token"
    assert normalized_fields["custom_headers"]["X-Splunk-Host"] == "search-head"
    assert normalized_fields["request_timeout"] == 45
    assert normalized_fields["connect_timeout"] == 12
    assert normalized_fields["sse_read_timeout"] == 120
    assert normalized_fields["retry_count"] == 2
    assert normalized_fields["retry_backoff_seconds"] == 3
    assert normalized_fields["allowed_tool_names"] == ["search_repositories", "get_issue"]
    assert normalized_fields["mcp_tools"][0]["function_name"] == "search_repositories"

    manifest["additionalFields"] = normalized_fields
    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(manifest, MCP_PLUGIN_TYPE)
    assert is_valid, f"Expected valid MCP manifest, got errors: {errors}"

    headers = McpPluginFactory._build_headers(manifest)
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["X-Splunk-Host"] == "search-head"
    assert "custom-token" not in headers.values()

    plugin = McpPluginFactory.create_from_config(manifest)
    metadata = plugin.metadata
    assert metadata["type"] == MCP_PLUGIN_TYPE
    assert metadata["server_profile"] == "splunk"
    assert metadata["transport"] == "streamable_http"
    assert any(method["name"] == "list_configured_tools" for method in metadata["methods"])
    assert any(method["name"] == "search_repositories" for method in metadata["methods"])

    tool_payload = plugin.list_configured_tools()
    assert tool_payload["success"] is True
    assert tool_payload["tool_count"] == 1
    assert tool_payload["tools"][0]["original_name"] == "search-repositories"

    async def fake_call_tool_from_config(cls, config, tool_name, arguments=None):
        return {
            "success": True,
            "tool_name": tool_name,
            "content": {
                "received_arguments": arguments or {},
                "transport": config["additionalFields"]["transport"],
            },
        }

    original_call_tool_from_config = McpPluginFactory.__dict__["call_tool_from_config"]
    McpPluginFactory.call_tool_from_config = classmethod(fake_call_tool_from_config)
    try:
        invocation_result = asyncio.run(plugin.invoke_tool("search-repositories", {"query": "simplechat"}))
        assert invocation_result["success"] is True
        assert invocation_result["tool_name"] == "search-repositories"
        assert invocation_result["content"]["received_arguments"]["query"] == "simplechat"

        kernel_plugin = plugin.get_kernel_plugin("github_mcp")
        assert "search_repositories" in kernel_plugin.functions
    finally:
        McpPluginFactory.call_tool_from_config = original_call_tool_from_config

    invalid_manifest = dict(manifest)
    invalid_manifest["endpoint"] = ""
    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(invalid_manifest, MCP_PLUGIN_TYPE)
    assert not is_valid
    assert any("endpoint" in error.lower() for error in errors)

    invalid_header_manifest = dict(manifest)
    invalid_header_manifest["additionalFields"] = dict(normalized_fields)
    invalid_header_manifest["additionalFields"]["custom_headers"] = {"Bad Header": "value"}
    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(invalid_header_manifest, MCP_PLUGIN_TYPE)
    assert not is_valid
    assert any("custom header" in error.lower() for error in errors)

    websocket_header_manifest = dict(manifest)
    websocket_header_manifest["endpoint"] = "wss://example.com/mcp"
    websocket_header_manifest["additionalFields"] = dict(normalized_fields)
    websocket_header_manifest["additionalFields"]["transport"] = "websocket"
    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(websocket_header_manifest, MCP_PLUGIN_TYPE)
    assert not is_valid
    assert any("websocket" in error.lower() and "headers" in error.lower() for error in errors)

    error_info = classify_mcp_exception(
        TimeoutError("Authorization=super-secret timed out calling MCP"),
        "tool_call",
    )
    assert error_info["category"] == "timeout"
    assert "super-secret" not in error_info["detail"]

    print("MCP action manifest workflow test passed.")


if __name__ == "__main__":
    try:
        test_mcp_action_manifest_workflow()
        success = True
    except Exception as ex:
        print(f"MCP action manifest workflow test failed: {ex}")
        import traceback

        traceback.print_exc()
        success = False
    sys.exit(0 if success else 1)