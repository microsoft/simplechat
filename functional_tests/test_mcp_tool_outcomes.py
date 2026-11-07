# test_mcp_tool_outcomes.py
"""
Functional regressions for outbound MCP protocol and invocation outcomes.
Version: 0.261.371
Implemented in: 0.261.371

Real modules and MCP response types run in fresh normal/optimized processes.
Only external I/O is mocked. Application imports are deferred until the offline
bootstrap is active, including the real citation builder's route dependencies.
"""

import asyncio
import importlib
import json
import logging
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from mcp.types import AudioContent, CallToolResult, ImageContent, TextContent
import pytest


ROOT = Path(__file__).resolve().parents[1]


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


@pytest.mark.parametrize("optimized", [False, True])
def test_mcp_outcomes_reach_logging_reasoning_and_citations(optimized):
    completed = subprocess.run(
        [sys.executable, "-B", *(["-O"] if optimized else []), str(Path(__file__).resolve()), "--probe"],
        cwd=ROOT, text=True, capture_output=True, timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _manifest():
    return {
        "name": "outcome_test",
        "type": "mcp",
        "endpoint": "https://example.test/mcp",
        "auth": {"type": "NoAuth"},
        "additionalFields": {
            "transport": "streamable_http",
            "auth_method": "none",
            "load_tools": True,
            "validate_tool_arguments": True,
            "retry_count": 3,
            "mcp_tools": [{
                "original_name": "echo",
                "function_name": "echo",
                "input_schema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }],
        },
    }


def _connector(result):
    return SimpleNamespace(
        session=SimpleNamespace(call_tool=AsyncMock(return_value=result)),
        load_tools_flag=True,
        connect=AsyncMock(),
        close=AsyncMock(),
        call_tool=AsyncMock(side_effect=AssertionError("Content-only SDK invocation lost the MCP outcome.")),
    )


async def _exercise(logger):
    from route_backend_chats import _build_plugin_invocation_agent_citation
    from semantic_kernel import Kernel
    from semantic_kernel.functions import KernelArguments
    from semantic_kernel.connectors.mcp import _mcp_call_tool_result_to_kernel_contents
    from semantic_kernel_plugins.mcp_plugin import McpPlugin
    from semantic_kernel_plugins.mcp_plugin_factory import McpPluginFactory
    from semantic_kernel_plugins.plugin_invocation_thoughts import format_plugin_invocation_thought
    from functions_mcp_operations import MCP_MAX_TOOL_RESULT_TEXT_LENGTH

    async def invoke(plugin, dynamic, arguments):
        if not dynamic:
            return await plugin.call_tool("echo", arguments)
        kernel = Kernel()
        kernel.add_plugin(plugin.get_kernel_plugin("outcome_test"))
        response = await kernel.invoke(
            plugin_name="outcome_test", function_name="echo",
            arguments=KernelArguments(kwargs=arguments),
        )
        return response.value

    def check_records(before, result, count, success):
        invocations = logger.invocations[before:]
        _check(len(invocations) == count, "entry point changed its invocation count")
        for invocation in invocations:
            _check(invocation.success is success, "MCP result and invocation outcome disagree")
            _check(invocation.result is result, "invocation lost the actual returned result")
            thought = format_plugin_invocation_thought(invocation)
            state = "completed" if success else "failed"
            _check(thought["activity"]["state"] == state, "reasoning has the wrong MCP outcome")
            citation = _build_plugin_invocation_agent_citation(invocation)
            _check(citation["success"] is success, "citation has the wrong MCP outcome")
            _check(citation["function_result"]["success"] is success, "citation lost the result envelope")
            if not success:
                _check(invocation.error_message == result["error"], "invocation lost the safe failure message")
                _check(citation["error_message"] == result["error"], "citation lost the safe failure message")
            _check("SyntheticSecret" not in json.dumps(citation), "citation exposed a secret-bearing value")
        return invocations

    starts, completions = [], []
    logger.register_start_callback("mcp-outcome-user:None", starts.append)
    logger.register_callback("mcp-outcome-user:None", completions.append)
    try:
        for dynamic in (False, True):
            count = 2 if dynamic else 1
            plugin = McpPlugin(_manifest())
            for raw in (
                CallToolResult(isError=True, content=[
                    TextContent(type="text", text="Synthetic failure; password=SyntheticSecret"),
                ]),
                CallToolResult(isError=True, content=[]),
            ):
                connector = _connector(raw)
                before = len(logger.invocations)
                with patch.object(McpPluginFactory, "create_connector", return_value=connector) as create:
                    result = await invoke(plugin, dynamic, {"text": "fail"})
                _check(result["success"] is False and result["error_type"] == "tool_error",
                       "protocol tool error was reported as success")
                _check(result["retryable"] is False, "protocol tool failure must not request a replay")
                check_records(before, result, count, False)
                _check(create.call_count == connector.connect.await_count == connector.close.await_count == 1,
                       "protocol failure was replayed or the connector was not closed")
                _check(connector.session.call_tool.await_count == 1, "protocol failure replayed the tool")
                _check(connector.call_tool.await_count == 0, "content-only SDK boundary was used")
                _check(connector.session.call_tool.call_args.kwargs == {"arguments": {"text": "fail"}},
                       "wire arguments were changed")
                if not raw.content:
                    _check(result["content"] == [], "empty error content changed the outcome")

            business = {"error": "business data", "success": False, "isError": True}
            raw = CallToolResult(
                isError=False, structuredContent=business,
                content=[TextContent(type="text", text=json.dumps(business))],
            )
            connector = _connector(raw)
            before = len(logger.invocations)
            with patch.object(McpPluginFactory, "create_connector", return_value=connector):
                result = await invoke(plugin, dynamic, {"text": "valid after failure"})
            _check(set(result) == {"success", "tool_name", "content"}, "successful envelope changed")
            _check(json.loads(result["content"][0]["text"]) == business, "business data was reclassified or lost")
            check_records(before, result, count, True)

            connector = _connector(raw)
            before = len(logger.invocations)
            with patch.object(McpPluginFactory, "create_connector", return_value=connector) as create:
                result = await invoke(plugin, dynamic, {})
            _check(result["error_type"] == "validation" and create.call_count == 0,
                   "local validation invoked an external tool")
            check_records(before, result, count, False)

            for cause in (
                PermissionError("Authorization: Bearer SyntheticSecret"),
                ValueError("password=SyntheticSecret"),
            ):
                before = len(logger.invocations)
                with patch.object(McpPluginFactory, "create_connector", side_effect=cause) as create:
                    result = await invoke(plugin, dynamic, {"text": "denied"})
                _check(create.call_count == 1, "configuration/permission failure retried")
                check_records(before, result, count, False)

            connector = _connector(raw)
            connector.session.call_tool.side_effect = TimeoutError("password=SyntheticSecret")
            manifest = _manifest()
            manifest["additionalFields"]["retry_count"] = 0
            before = len(logger.invocations)
            with patch.object(McpPluginFactory, "create_connector", return_value=connector):
                result = await invoke(McpPlugin(manifest), dynamic, {"text": "timeout"})
            _check(result["error_type"] == "timeout", "transport error classification changed")
            _check(connector.session.call_tool.await_count == connector.close.await_count == 1,
                   "transport failure lost cleanup or changed retry behavior")
            check_records(before, result, count, False)

            manifest = _manifest()
            manifest["additionalFields"]["retry_count"] = 1
            failed_connector = _connector(raw)
            failed_connector.session.call_tool.side_effect = TimeoutError("Synthetic timeout")
            recovered_connector = _connector(raw)
            before = len(logger.invocations)
            with patch.object(McpPluginFactory, "create_connector", side_effect=[
                failed_connector, recovered_connector,
            ]) as create, patch.object(asyncio, "sleep", new_callable=AsyncMock) as sleep:
                result = await invoke(McpPlugin(manifest), dynamic, {"text": "transport recovery"})
            _check(create.call_count == 2 and sleep.await_count == 1, "bounded transport retry behavior changed")
            _check(failed_connector.close.await_count == recovered_connector.close.await_count == 1,
                   "transport retry lost connector cleanup")
            check_records(before, result, count, True)

            for missing_session in (False, True):
                connector = _connector(raw)
                session = connector.session
                connector.load_tools_flag = False
                if missing_session:
                    connector.session = None
                before = len(logger.invocations)
                with patch.object(McpPluginFactory, "create_connector", return_value=connector):
                    result = await invoke(plugin, dynamic, {"text": "must not execute"})
                check_records(before, result, count, False)
                _check(session.call_tool.await_count == 0 and connector.close.await_count == 1,
                       "tool loading/session restriction was bypassed")

            for policy in ("truncate", "error_on_limit"):
                manifest = _manifest()
                manifest["additionalFields"]["tool_result_policy"] = policy
                connector = _connector(CallToolResult(content=[
                    TextContent(type="text", text="x" * (MCP_MAX_TOOL_RESULT_TEXT_LENGTH + 1)),
                ]))
                before = len(logger.invocations)
                with patch.object(McpPluginFactory, "create_connector", return_value=connector):
                    result = await invoke(McpPlugin(manifest), dynamic, {"text": "large result"})
                success = policy == "truncate"
                check_records(before, result, count, success)
                if success:
                    _check(result["content"][0]["text"].endswith("[truncated]"), "result was not truncated")
                else:
                    _check(result["error_type"] == "result_limit", "result-limit classification changed")
                _check(connector.session.call_tool.await_count == connector.close.await_count == 1,
                       "result policy replayed a tool or lost cleanup")

        for name, manifest, expected in (
            ("", _manifest(), "validation"),
            ("unknown", _manifest(), "not_configured"),
            ("unknown", {**_manifest(), "additionalFields": {
                **_manifest()["additionalFields"], "allowed_tool_names": ["echo"],
            }}, "not_allowed"),
        ):
            before = len(logger.invocations)
            with patch.object(McpPluginFactory, "create_connector") as create:
                result = await McpPlugin(manifest).call_tool(name, {"text": "rejected"})
            _check(result["error_type"] == expected and create.call_count == 0,
                   "local tool admission behavior changed")
            check_records(before, result, 1, False)

        for dynamic in (False, True):
            plugin = McpPlugin(_manifest())
            plugin.manifest["type"] = "openapi"
            before = len(logger.invocations)
            with patch.object(McpPluginFactory, "create_connector") as create:
                result = await invoke(plugin, dynamic, {"text": "invalid manifest"})
            _check(create.call_count == 0, "invalid manifest reached connector construction")
            check_records(before, result, 2 if dynamic else 1, False)

        raw = CallToolResult(content=[
            TextContent(type="text", text="ordinary text"),
            ImageContent(type="image", mimeType="image/png", data="YWJj"),
            AudioContent(type="audio", mimeType="audio/wav", data="YWJj"),
        ])
        expected_content = [
            McpPluginFactory._serialize_content_item(item, "truncate")
            for item in _mcp_call_tool_result_to_kernel_contents(raw)
        ]
        connector = _connector(raw)
        with patch.object(McpPluginFactory, "create_connector", return_value=connector):
            result = await McpPluginFactory.call_tool_from_config(_manifest(), "echo", {"text": "multimedia"})
        _check(result["content"] == expected_content, "existing SDK multimedia content format changed")

        plugin = McpPlugin(_manifest())
        before = len(logger.invocations)
        connectors = [
            _connector(CallToolResult(isError=True, content=[])),
            _connector(CallToolResult(content=[TextContent(type="text", text="ok")])),
        ]
        with patch.object(McpPluginFactory, "create_connector", side_effect=connectors):
            results = await asyncio.gather(
                invoke(plugin, True, {"text": "failure"}),
                invoke(plugin, False, {"text": "success"}),
            )
        _check([result["success"] for result in results] == [False, True], "concurrent outcomes leaked")
        for invocation in logger.invocations[before:]:
            _check(invocation.success is invocation.result["success"], "concurrent logger state leaked")
        _check(len(starts) == len(completions), "start/completion callbacks were lost or duplicated")
        _check({item.invocation_id for item in starts} == {item.invocation_id for item in completions},
               "start/completion identities disagree")
    finally:
        logger.deregister_callbacks("mcp-outcome-user:None")


def _probe():
    sys.path.insert(0, str(ROOT / "functional_tests"))
    sys.path.insert(0, str(ROOT / "application" / "single_app"))
    from test_support.offline_bootstrap import offline_app_imports

    with offline_app_imports() as offline:
        module = importlib.import_module("semantic_kernel_plugins.plugin_invocation_logger")
        factory = importlib.import_module("semantic_kernel_plugins.mcp_plugin_factory")
        logger = module.PluginInvocationLogger()
        logger.logger = Mock(spec=logging.Logger)
        with patch.object(module, "_plugin_logger", logger), \
                patch.object(module, "get_current_user_id", return_value="mcp-outcome-user"), \
                patch.object(module, "log_event"), patch.object(factory, "log_event"):
            offline.loop.run_until_complete(_exercise(logger))


if __name__ == "__main__":
    if sys.argv[1:] == ["--probe"]:
        _probe()
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
