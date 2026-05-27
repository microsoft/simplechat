#!/usr/bin/env python3
"""
Functional test for MCP action manifest workflow.
Version: 0.241.103
Implemented in: 0.241.103

This test ensures that MCP action configuration defaults, validation, and
plugin metadata creation produce the manifest shape used by the shared action
modal.
"""

import os
import sys
import asyncio
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from functions_mcp_operations import MCP_PLUGIN_TYPE, normalize_mcp_additional_fields
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
            "transport": "streamable-http",
            "auth_method": "bearer_token",
            "load_tools": True,
            "load_prompts": False,
            "request_timeout": "45",
            "connect_timeout": "12",
            "sse_read_timeout": "120",
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
    assert normalized_fields["transport"] == "streamable_http"
    assert normalized_fields["auth_method"] == "bearer"
    assert normalized_fields["request_timeout"] == 45
    assert normalized_fields["connect_timeout"] == 12
    assert normalized_fields["sse_read_timeout"] == 120
    assert normalized_fields["allowed_tool_names"] == ["search_repositories", "get_issue"]
    assert normalized_fields["mcp_tools"][0]["function_name"] == "search_repositories"

    manifest["additionalFields"] = normalized_fields
    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(manifest, MCP_PLUGIN_TYPE)
    assert is_valid, f"Expected valid MCP manifest, got errors: {errors}"

    plugin = McpPluginFactory.create_from_config(manifest)
    metadata = plugin.metadata
    assert metadata["type"] == MCP_PLUGIN_TYPE
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

    print("MCP action manifest workflow test passed.")
    return True


if __name__ == "__main__":
    success = test_mcp_action_manifest_workflow()
    sys.exit(0 if success else 1)