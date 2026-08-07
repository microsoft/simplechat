# test_mcp_tool_argument_normalization.py
#!/usr/bin/env python3
"""
Functional test for outbound MCP tool argument normalization.
Version: 0.250.127
Implemented in: 0.250.127

This test ensures wrapped Semantic Kernel kwargs are normalized before outbound
MCP tool validation and invocation, while legitimate kwargs tool fields remain
unchanged.
"""

import asyncio
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))


def _noop(*_args, **_kwargs):
    return None


class _NoopLogger:
    def __getattr__(self, _name):
        return _noop


class _KernelPlugin:
    def __init__(self, functions):
        self.functions = functions

    @classmethod
    def from_object(cls, _plugin_name, functions, description=None):
        return cls(functions)


def _kernel_function(*_args, **_kwargs):
    def decorator(func):
        return func

    return decorator


sys.modules.setdefault(
    "functions_appinsights",
    types.SimpleNamespace(
        log_event=_noop,
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
sys.modules.setdefault("semantic_kernel", types.SimpleNamespace())
sys.modules.setdefault(
    "semantic_kernel.functions",
    types.SimpleNamespace(kernel_function=_kernel_function),
)
sys.modules.setdefault(
    "semantic_kernel.functions.kernel_plugin",
    types.SimpleNamespace(KernelPlugin=_KernelPlugin),
)
sys.modules.setdefault(
    "semantic_kernel.connectors",
    types.SimpleNamespace(),
)
sys.modules.setdefault(
    "semantic_kernel.connectors.mcp",
    types.SimpleNamespace(
        MCPSsePlugin=object,
        MCPStdioPlugin=object,
        MCPStreamableHttpPlugin=object,
        MCPWebsocketPlugin=object,
    ),
)

from functions_mcp_operations import (  # noqa: E402
    MCP_PLUGIN_TYPE,
    normalize_mcp_tool_call_arguments,
    validate_mcp_tool_arguments,
)
from semantic_kernel_plugins.mcp_plugin import McpPlugin  # noqa: E402
from semantic_kernel_plugins.mcp_plugin_factory import McpPluginFactory  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _splunk_type_tool():
    return {
        "original_name": "get-splunk-objects",
        "function_name": "get_splunk_objects",
        "description": "Get Splunk objects by type.",
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "count": {"type": "integer"},
            },
            "required": ["type"],
        },
    }


def _mcp_manifest(tool, validate_arguments=True):
    return {
        "name": "splunk_mcp",
        "type": MCP_PLUGIN_TYPE,
        "endpoint": "https://splunk.example.com/mcp",
        "auth": {"type": "NoAuth"},
        "additionalFields": {
            "transport": "streamable_http",
            "auth_method": "none",
            "server_profile": "splunk",
            "validate_tool_arguments": validate_arguments,
            "mcp_tools": [tool],
        },
    }


def test_wrapped_kwargs_arguments_are_unwrapped_for_required_schema():
    """Validate the Splunk-style kwargs wrapper becomes top-level MCP arguments."""
    tool = _splunk_type_tool()
    wrapped_arguments = {"kwargs": {"type": "savedsearch", "count": 25}}

    wrapped_validation_errors = validate_mcp_tool_arguments(tool, wrapped_arguments)
    assert any("'type' is a required property" in error for error in wrapped_validation_errors)

    normalized_arguments = normalize_mcp_tool_call_arguments(tool, wrapped_arguments)

    assert normalized_arguments == {"type": "savedsearch", "count": 25}
    assert validate_mcp_tool_arguments(tool, normalized_arguments) == []


def test_direct_arguments_are_preserved():
    """Validate already-correct MCP arguments are left untouched."""
    tool = _splunk_type_tool()
    direct_arguments = {"type": "savedsearch"}

    normalized_arguments = normalize_mcp_tool_call_arguments(tool, direct_arguments)

    assert normalized_arguments == direct_arguments


def test_legitimate_kwargs_tool_property_is_preserved():
    """Validate tools that define a real kwargs field do not get unwrapped."""
    tool = {
        "original_name": "kwargs-tool",
        "function_name": "kwargs_tool",
        "input_schema": {
            "type": "object",
            "properties": {
                "kwargs": {
                    "type": "object",
                    "properties": {"type": {"type": "string"}},
                },
            },
            "required": ["kwargs"],
        },
    }
    arguments = {"kwargs": {"type": "intended-field"}}

    normalized_arguments = normalize_mcp_tool_call_arguments(tool, arguments)

    assert normalized_arguments == arguments
    assert validate_mcp_tool_arguments(tool, normalized_arguments) == []


def test_none_arguments_normalize_to_empty_object():
    """Validate no-parameter MCP tool calls keep the standard empty object shape."""
    assert normalize_mcp_tool_call_arguments({}, None) == {}


def test_mcp_plugin_call_tool_normalizes_before_validation_and_invocation():
    """Validate McpPlugin.call_tool forwards normalized args to invoke_tool."""
    plugin = McpPlugin(_mcp_manifest(_splunk_type_tool()))
    captured_call = {}

    async def fake_invoke_tool(tool_name, arguments=None):
        captured_call["tool_name"] = tool_name
        captured_call["arguments"] = arguments
        return {"success": True, "received_arguments": arguments}

    plugin.invoke_tool = fake_invoke_tool
    result = asyncio.run(
        plugin.call_tool(
            "get-splunk-objects",
            {"kwargs": {"type": "savedsearch", "count": 25}},
        )
    )

    assert result["success"] is True
    assert captured_call["tool_name"] == "get-splunk-objects"
    assert captured_call["arguments"] == {"type": "savedsearch", "count": 25}


def test_factory_call_tool_normalizes_cached_tool_arguments():
    """Validate direct factory callers also receive top-level MCP arguments."""
    captured_call = {}

    async def fake_run_with_retries(cls, _config, _operation, operation_factory):
        return await operation_factory()

    async def fake_call_tool_once(cls, _config, tool_name, arguments=None):
        captured_call["tool_name"] = tool_name
        captured_call["arguments"] = arguments
        return {"success": True, "received_arguments": arguments}

    original_run_with_retries = McpPluginFactory.__dict__["_run_with_retries"]
    original_call_tool_once = McpPluginFactory.__dict__["_call_tool_once"]
    McpPluginFactory._run_with_retries = classmethod(fake_run_with_retries)
    McpPluginFactory._call_tool_once = classmethod(fake_call_tool_once)
    try:
        result = asyncio.run(
            McpPluginFactory.call_tool_from_config(
                _mcp_manifest(_splunk_type_tool()),
                "get-splunk-objects",
                {"kwargs": {"type": "savedsearch", "count": 25}},
            )
        )
    finally:
        McpPluginFactory._run_with_retries = original_run_with_retries
        McpPluginFactory._call_tool_once = original_call_tool_once

    assert result["success"] is True
    assert captured_call["tool_name"] == "get-splunk-objects"
    assert captured_call["arguments"] == {"type": "savedsearch", "count": 25}


def test_factory_preserves_wrapper_without_cached_tool_metadata():
    """Validate factory normalization stays conservative without schema metadata."""
    captured_call = {}
    manifest = _mcp_manifest(_splunk_type_tool())
    manifest["additionalFields"]["mcp_tools"] = []
    wrapped_arguments = {"kwargs": {"type": "intended-wrapper"}}

    async def fake_run_with_retries(cls, _config, _operation, operation_factory):
        return await operation_factory()

    async def fake_call_tool_once(cls, _config, tool_name, arguments=None):
        captured_call["tool_name"] = tool_name
        captured_call["arguments"] = arguments
        return {"success": True, "received_arguments": arguments}

    original_run_with_retries = McpPluginFactory.__dict__["_run_with_retries"]
    original_call_tool_once = McpPluginFactory.__dict__["_call_tool_once"]
    McpPluginFactory._run_with_retries = classmethod(fake_run_with_retries)
    McpPluginFactory._call_tool_once = classmethod(fake_call_tool_once)
    try:
        result = asyncio.run(
            McpPluginFactory.call_tool_from_config(
                manifest,
                "unknown-tool",
                wrapped_arguments,
            )
        )
    finally:
        McpPluginFactory._run_with_retries = original_run_with_retries
        McpPluginFactory._call_tool_once = original_call_tool_once

    assert result["success"] is True
    assert captured_call["tool_name"] == "unknown-tool"
    assert captured_call["arguments"] == wrapped_arguments


def main():
    """Run tests as a standalone functional test script."""
    assert_app_version_at_least("0.250.127")
    tests = [
        test_wrapped_kwargs_arguments_are_unwrapped_for_required_schema,
        test_direct_arguments_are_preserved,
        test_legitimate_kwargs_tool_property_is_preserved,
        test_none_arguments_normalize_to_empty_object,
        test_mcp_plugin_call_tool_normalizes_before_validation_and_invocation,
        test_factory_call_tool_normalizes_cached_tool_arguments,
        test_factory_preserves_wrapper_without_cached_tool_metadata,
    ]
    for test in tests:
        try:
            test()
        except Exception as ex:
            print(f"{test.__name__} failed: {ex}")
            raise
    print("MCP tool argument normalization tests passed.")


if __name__ == "__main__":
    main()
