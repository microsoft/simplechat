# test_action_runtime_usage.py
"""
Functional regressions for metadata-only action runtime usage.
Version: 0.261.447
Implemented in: 0.261.447

Real registration, decorated invocations and connector retries execute with offline
bootstrap in fresh normal/optimized processes. No cloud credentials are required.
"""

import asyncio
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
CANARY = "private-content-canary"


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


@pytest.mark.parametrize("optimized", [False, True])
def test_real_action_usage_runtime(optimized):
    completed = subprocess.run(
        [sys.executable, "-B", *(["-O"] if optimized else []), str(Path(__file__).resolve()), "--probe"],
        cwd=ROOT, text=True, capture_output=True, timeout=180,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


async def _exercise():
    from action_runtime_contracts import register_action_plugin
    import action_usage
    from agent_execution_context import (
        AgentExecutionFrame, DelegationBudget, ExecutionIdentity, agent_execution,
    )
    from functions_action_manifest import bind_action_origin
    from flask import Flask, g, session
    from mcp.types import CallToolResult, TextContent
    import runtime_usage
    from semantic_kernel import Kernel
    from semantic_kernel.functions import KernelArguments, kernel_function
    from semantic_kernel_plugins.mcp_plugin import McpPlugin
    from semantic_kernel_plugins.mcp_plugin_factory import McpPluginFactory
    from semantic_kernel_plugins.openapi_plugin import OpenApiPlugin
    import semantic_kernel_plugins.plugin_invocation_logger as logger

    events = []

    def sink(target, **fields):
        events.append(runtime_usage.build_usage_record(target, **fields))

    def manifest(scope_id="owner-a", action_id="action-a"):
        return bind_action_origin({
            "id": action_id, "name": "Duplicate", "type": "OpenAPI",
            "endpoint": f"https://user:{CANARY}@EXAMPLE.test/private/{CANARY}?token={CANARY}",
            "auth": {"type": "key", "key": CANARY},
            "additionalFields": {"auth_method": "basic"},
            "description": CANARY, "instructions": CANARY,
        }, "personal", scope_id)

    class Plugin:
        @kernel_function(name="execute")
        @logger.plugin_function_logger("SelfLogging")
        async def execute(self, mode: str = "success") -> dict:
            await asyncio.sleep(0)
            if mode == "declared":
                logger.report_plugin_invocation_failure(CANARY)
            if mode == "raises":
                raise ValueError(CANARY)
            if mode == "timeout":
                raise TimeoutError(CANARY)
            if mode == "cancel":
                raise asyncio.CancelledError(CANARY)
            return {"success": False, "error": CANARY, "arguments": CANARY}

        @kernel_function(name="sync")
        @logger.plugin_function_logger("SelfLogging")
        def sync(self, content: str = CANARY) -> str:
            return content

    with patch.object(runtime_usage, "emit_usage", side_effect=sink), \
            patch.object(logger, "log_event"), \
            patch.object(logger, "_plugin_logger", logger.PluginInvocationLogger()):
        first, second = manifest(), manifest("owner-b", "action-a")
        second["endpoint"] = f"https://second.test/{CANARY}"
        second["additionalFields"]["auth_method"] = "bearer"
        kernel = Kernel()
        name_a = register_action_plugin(kernel, Plugin(), first)
        name_b = register_action_plugin(kernel, Plugin(), second)
        _check(name_a != name_b, "runtime plugin names must be collision safe")
        first["endpoint"] = f"https://{CANARY}.invalid"
        first["auth"]["type"] = "none"
        first["name"] = CANARY

        async def invoke(name, owner, mode):
            frame = AgentExecutionFrame(
                identity=ExecutionIdentity(owner, f"conversation-{owner}"),
                caller={}, budget=DelegationBudget(),
            )
            with agent_execution(frame):
                return await kernel.invoke(
                    plugin_name=name, function_name="execute",
                    arguments=KernelArguments(mode=mode, user_id=CANARY),
                )

        results = await asyncio.gather(
            invoke(name_a, "user-a", "declared"), invoke(name_b, "user-b", "success"),
        )
        _check(all(result.value["error"] == CANARY for result in results), "tool results changed")
        _check(len(events) == 2, "self logging duplicated or lost usage")
        pairs = {
            (event["user_id"], event["runtime_usage"]["scope_id"], event["status"])
            for event in events
        }
        _check(pairs == {("user-a", "owner-a", "failed"), ("user-b", "owner-b", "succeeded")},
               "concurrent identity or declared failure leaked")
        configurations = {
            (event["user_id"], event["runtime_usage"]["endpoint_host"], event["runtime_usage"]["auth_type"])
            for event in events
        }
        _check(configurations == {("user-a", "example.test", "basic"), ("user-b", "second.test", "bearer")},
               "configured host/auth snapshot crossed concurrent bindings")

        method = kernel.plugins[name_a].functions["execute"].method
        rebound = action_usage.bind_action_callable(
            method, action_usage.action_usage_target(manifest()), "execute",
        )
        _check(rebound is method, "identical binding was wrapped twice")
        with action_usage.action_usage_identity("background-user", workflow_id="workflow", run_id="run"):
            for mode, expected in (("raises", "failed"), ("timeout", "timeout"), ("cancel", "cancelled")):
                try:
                    await method(mode=mode)
                except (ValueError, TimeoutError, asyncio.CancelledError):
                    pass
                else:
                    raise AssertionError("action exception swallowed")
                _check(events[-1]["status"] == expected, "exception outcome is incorrect")
                _check(events[-1]["user_id"] == "background-user", "background identity lost")
            sync_method = kernel.plugins[name_a].functions["sync"].method
            result = sync_method(CANARY)
            _check(result == CANARY, "sync return changed")
            result = sync_method(CANARY)
            _check(result == CANARY, "retry return changed")
            _check(events[-1]["runtime_usage"]["attempt_id"] != events[-2]["runtime_usage"]["attempt_id"],
                   "real reinvocation reused its attempt ID")

            def deferred():
                logger.report_plugin_invocation_failure(CANARY)

                async def complete():
                    await asyncio.sleep(0)
                    return CANARY

                return complete()

            deferred_call = action_usage.bind_action_callable(
                deferred, action_usage.action_usage_target(manifest()), "deferred",
            )
            value = await deferred_call()
            _check(value == CANARY and events[-1]["status"] == "failed", "deferred declared failure lost")

            def continuation():
                action_usage.report_action_authentication_pending()
                return {"error": "interactive_auth_required", "auth_url": CANARY}

            pending = action_usage.bind_action_callable(
                continuation, action_usage.action_usage_target(manifest()), "connect",
            )
            baseline = len(events)
            pending()
            _check(len(events) == baseline, "credential continuation inflated successful use")

            with patch.object(runtime_usage, "emit_usage", side_effect=RuntimeError(CANARY)), \
                    patch("functions_appinsights.log_event") as diagnostic:
                value = sync_method(CANARY)
                try:
                    await method(mode="raises")
                except ValueError as exc:
                    _check(str(exc) == CANARY, "telemetry replaced the original operation exception")
                else:
                    raise AssertionError("telemetry swallowed an operation failure")
            _check(value == CANARY, "telemetry sink failure changed action success")
            _check(CANARY not in str(diagnostic.call_args_list), "telemetry diagnostic leaked content")

        baseline = len(events)
        sync_method()
        _check(len(events) == baseline, "missing background identity must not fabricate a user")

        app = Flask(__name__)
        app.secret_key = "offline-session"
        with app.test_request_context("/internal-action"):
            session["user"] = {"oid": "session-user"}
            g.authorized_chat_context = {"conversation_id": "authorized-conversation"}
            sync_method()
        _check(events[-1]["user_id"] == "session-user", "request identity was not server-resolved")
        _check(events[-1]["conversation_id"] == "authorized-conversation", "authorized request context lost")

        spec = {
            "openapi": "3.0.0", "info": {"title": "Records", "version": "1"},
            "paths": {"/private": {"get": {
                "operationId": "lookup", "responses": {"200": {"description": "OK"}},
            }}},
        }
        openapi_manifest = manifest()
        openapi_manifest["id"] = "ignored-untrusted-id"
        openapi_plugin = OpenApiPlugin(
            base_url="https://example.test", openapi_spec_content=spec,
        )
        openapi_name = register_action_plugin(kernel, openapi_plugin, openapi_manifest)
        response = requests.Response()
        response.status_code = 503
        response.url = f"https://example.test/private?token={CANARY}"
        response._content = json.dumps({"message": CANARY}).encode()
        with action_usage.action_usage_identity("openapi-user"), \
                patch("semantic_kernel_plugins.openapi_plugin.guarded_request", return_value=response) as request:
            baseline = len(events)
            await kernel.invoke(
                plugin_name=openapi_name, function_name="lookup", arguments=KernelArguments(kwargs={}),
            )
        _check(request.call_count == 1, "usage instrumentation replayed HTTP request")
        _check(len(events) == baseline + 1 and events[-1]["status"] == "failed",
               "real OpenAPI declared failure lost or duplicated")
        _check(events[-1]["runtime_usage"]["entity_id"] == "action-a", "JSON id replaced trusted origin")

        mcp_manifest = bind_action_origin({
            "id": "mcp-action", "name": "Duplicate", "type": "mcp",
            "endpoint": f"https://mcp.test/private?secret={CANARY}",
            "auth": {"type": "none"},
            "additionalFields": {
                "transport": "streamable_http", "auth_method": "none",
                "load_tools": True, "retry_count": 1,
                "mcp_tools": [{"original_name": "echo", "function_name": "echo", "input_schema": {}}],
            },
        }, "group", "group-a")
        mcp_name = register_action_plugin(kernel, McpPlugin(mcp_manifest), mcp_manifest)
        raw = CallToolResult(isError=False, content=[TextContent(type="text", text=CANARY)])
        connector = SimpleNamespace(
            session=SimpleNamespace(call_tool=AsyncMock(side_effect=[TimeoutError(CANARY), raw])),
            load_tools_flag=True, connect=AsyncMock(), close=AsyncMock(),
        )
        with action_usage.action_usage_identity("mcp-user"), \
                patch.object(McpPluginFactory, "create_connector", return_value=connector), \
                patch("semantic_kernel_plugins.mcp_plugin_factory.asyncio.sleep", new=AsyncMock()):
            baseline = len(events)
            result = await kernel.invoke(
                plugin_name=mcp_name, function_name="echo", arguments=KernelArguments(kwargs={"text": CANARY}),
            )
        _check(result.value["success"], "MCP retry did not retain successful result")
        attempts = events[baseline:]
        _check(len(attempts) == 2, "MCP retry must count exactly two dispatches, not outer wrappers")
        _check([event["status"] for event in attempts] == ["timeout", "succeeded"], "MCP retry outcomes lost")
        _check(all(event["runtime_usage"]["operation"] == "echo" for event in attempts),
               "MCP configured operation was replaced with a generated name")
        _check(connector.session.call_tool.await_count == 2, "telemetry replayed the operation")

        connector.session.call_tool = AsyncMock(return_value=raw)
        with action_usage.action_usage_identity("mcp-user"), \
                patch.object(McpPluginFactory, "create_connector", return_value=connector):
            baseline = len(events)
            await kernel.invoke(
                plugin_name=mcp_name, function_name="call_tool",
                arguments=KernelArguments(tool_name="echo", arguments={}),
            )
        _check(len(events) == baseline + 1 and events[-1]["runtime_usage"]["operation"] == "echo",
               "generic MCP entry point lost its verified configured operation")

        raw.isError = True
        connector.session.call_tool = AsyncMock(return_value=raw)
        with action_usage.action_usage_identity("mcp-user"), \
                patch.object(McpPluginFactory, "create_connector", return_value=connector):
            baseline = len(events)
            await kernel.invoke(
                plugin_name=mcp_name, function_name="echo", arguments=KernelArguments(kwargs={}),
            )
        _check(len(events) == baseline + 1 and events[-1]["status"] == "failed",
               "MCP protocol-declared failure was counted as success or duplicated")
        _check(CANARY not in json.dumps(events), "usage payload leaked private tool/configuration content")
        _check(all(event["runtime_usage"]["duration_ms"] >= 0 for event in events), "duration missing")
        _check(action_usage.action_usage_target(dict(mcp_manifest)) is None, "untrusted dict forged origin")

        for action_type, auth, fields, expected in (
            ("mcp", {}, {"auth_method": "bearer_token"}, "bearer"),
            ("mcp", {}, {"auth_method": "none"}, "none"),
            ("OpenAPI", {"type": "key"}, {"auth_method": "basic"}, "basic"),
            ("databricks", {"type": "identity"}, {}, "managed_identity"),
            ("snowflake", {"type": "key"}, {}, "key_pair"),
            ("tableau", {"type": "key"}, {}, "personal_access_token"),
            ("yamcs", {"type": "none"}, {"auth_method": "none"}, "none"),
        ):
            config = manifest()
            config.update(type=action_type, auth=auth, additionalFields=fields)
            target = action_usage.action_usage_target(config)
            _check(target.auth_type == expected, f"connector auth normalization failed: {action_type}")
        config = manifest()
        config.update(type="python", auth={}, additionalFields={})
        config.pop("endpoint")
        target = action_usage.action_usage_target(config)
        _check(target.auth_type == "unknown" and target.endpoint_host == "not_applicable",
               "unknown authentication must not become verified none")
        config.update(type="mcp", endpoint=f"wss://mcp.test/{CANARY}", additionalFields={"auth_method": "none"})
        target = action_usage.action_usage_target(config)
        _check(target.endpoint_host == "mcp.test" and target.auth_type == "none", "MCP websocket host missing")
        config["auth"] = {"type": "identity"}
        target = action_usage.action_usage_target(config)
        _check(target.auth_type == "unknown", "unknown identity authentication became verified none")


def _probe():
    sys.path.insert(0, str(ROOT / "functional_tests"))
    sys.path.insert(0, str(ROOT / "application" / "single_app"))
    importlib.import_module("action_usage")
    _check("config" not in sys.modules and "functions_settings" not in sys.modules,
           "action discovery bootstrapped application settings")
    from test_support.offline_bootstrap import offline_app_imports

    with offline_app_imports() as offline:
        importlib.import_module("semantic_kernel_plugins.plugin_invocation_logger")
        offline.loop.run_until_complete(_exercise())


if __name__ == "__main__":
    if "--probe" in sys.argv:
        _probe()
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
