# test_schema_v2_agent_model_routing.py
#!/usr/bin/env python3
"""
Functional test for schema-v2 agent model routing.
Version: 0.261.061
Implemented in: 0.261.058; streaming compatibility added in: 0.261.061

This test ensures local Semantic Kernel agents retain their authorized
schema-v2 endpoint route and pass it to the existing route-aware service
builder for OpenAI-compatible and Anthropic models. It also ensures agents do
not send tool metadata to routes that do not advertise tool-calling support.
"""

import ast
import asyncio
import copy
import json
import sys
from pathlib import Path

import httpx
from openai import AsyncOpenAI
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion
from semantic_kernel.core_plugins import TimePlugin
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
LOADER_FILE = APP_DIR / "semantic_kernel_loader.py"
sys.path.insert(0, str(APP_DIR))

from functions_model_endpoint_types import (  # noqa: E402
    get_model_endpoint_api_type,
    resolve_model_endpoint_request_model,
)
from functions_model_endpoint_urls import (  # noqa: E402
    resolve_model_endpoint_route,
    routing_schema_version,
)
from agent_logging_chat_completion import LoggingChatCompletionAgent  # noqa: E402
from model_endpoint_clients import (  # noqa: E402
    bind_model_endpoint_request_policy,
    sanitize_custom_async_openai_client,
)


def _find_function(function_name: str, *, parent_name: str | None = None) -> ast.FunctionDef:
    source = ast.parse(LOADER_FILE.read_text(encoding="utf-8"))
    nodes = source.body
    if parent_name:
        parent = next(
            node for node in nodes
            if isinstance(node, ast.FunctionDef) and node.name == parent_name
        )
        nodes = parent.body
    return next(
        node for node in nodes
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )


def _endpoint(api_type: str) -> dict:
    uses_model_name = api_type in {"openai", "anthropic", "azure_openai_v1"}
    model = {
        "id": f"{api_type}-model",
        "enabled": True,
        "api_type": api_type,
        "api_path": "shared-foundry;rev=2",
        "url_mode": "auto",
    }
    model["modelName" if uses_model_name else "deploymentName"] = f"{api_type}-deployment"
    return {
        "id": f"{api_type}-endpoint",
        "enabled": True,
        "provider": "custom",
        "routing_schema_version": 2,
        "connection": {"endpoint": "https://gateway.example"},
        "auth": {
            "type": "api_key",
            "api_key": "server-secret",
            "api_key_header": "Ocp-Apim-Subscription-Key",
            "api_key_prefix": "",
        },
        "models": [model],
    }


def test_schema_v2_agent_binding_retains_resolved_route() -> None:
    binding_function = _find_function(
        "resolve_multi_endpoint_agent_binding",
        parent_name="resolve_agent_config",
    )

    namespace = {
        "keyvault_model_endpoint_get_helper": lambda endpoint, *_args, **_kwargs: endpoint,
        "SecretReturnType": type("SecretReturnType", (), {"VALUE": "value"}),
        "resolve_model_endpoint_request_model": resolve_model_endpoint_request_model,
        "get_model_endpoint_api_type": get_model_endpoint_api_type,
        "resolve_model_endpoint_route": resolve_model_endpoint_route,
        "routing_schema_version": routing_schema_version,
        "project_model_budget_metadata": lambda value: copy.deepcopy(value),
    }
    exec(
        compile(ast.Module(body=[binding_function], type_ignores=[]), str(LOADER_FILE), "exec"),
        namespace,
    )

    for api_type in ("azure_openai_v1", "anthropic"):
        endpoint = _endpoint(api_type)
        result = namespace["resolve_multi_endpoint_agent_binding"](
            [{**copy.deepcopy(endpoint), "_endpoint_scope": "global"}],
            endpoint["id"],
            endpoint["models"][0]["id"],
        )
        route = result["resolved_model_endpoint"]["_resolved_route"]
        assert result["deployment"] == route["request_model"]
        assert result["api_type"] == api_type
        assert result["routing_schema_version"] == 2
        assert result["model_endpoint_id"] == endpoint["id"]
        assert result["model_id"] == endpoint["models"][0]["id"]
        assert route["api_path"] == "shared-foundry;rev=2"
        assert route["credential_policy"]["header"] == "Ocp-Apim-Subscription-Key"


def test_schema_v2_agent_service_uses_resolved_endpoint() -> None:
    service_function = _find_function("create_model_endpoint_chat_completion_service")
    calls = []

    def build_service(deployment, settings, **kwargs):
        calls.append((deployment, settings, kwargs))
        return "route-aware-service", "anthropic"

    namespace = {
        "build_semantic_kernel_chat_service_for_model": build_service,
        "resolve_agent_endpoint_protocol": lambda _config: "unused",
        "resolve_agent_endpoint_token": lambda _config: "",
        "MODEL_ENDPOINT_PROTOCOL_ANTHROPIC": "anthropic",
        "MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE": "openai_style",
        "AnthropicSemanticKernelChatCompletion": object,
        "OpenAIChatCompletion": object,
        "AzureChatCompletion": object,
        "AsyncOpenAI": object,
        "resolve_openai_style_request_api_version": lambda _value: "",
        "normalize_openai_style_base_url": lambda value: value,
    }
    exec(
        compile(ast.Module(body=[service_function], type_ignores=[]), str(LOADER_FILE), "exec"),
        namespace,
    )

    endpoint = _endpoint("anthropic")
    endpoint["_resolved_route"] = {"request_model": "anthropic-deployment"}
    service = namespace["create_model_endpoint_chat_completion_service"](
        {
            "endpoint": "https://gateway.example",
            "deployment": "anthropic-deployment",
            "model_provider": "custom",
            "model_endpoint_id": endpoint["id"],
            "model_id": endpoint["models"][0]["id"],
            "routing_schema_version": 2,
            "resolved_model_endpoint": endpoint,
            "auth": endpoint["auth"],
        },
        "agent-service",
        {"enable_multi_model_endpoints": True},
    )

    assert service == "route-aware-service"
    assert len(calls) == 1
    _, _, kwargs = calls[0]
    assert kwargs["resolved_model_endpoint"] is endpoint
    assert kwargs["model_context"]["endpoint_id"] == endpoint["id"]
    assert kwargs["model_context"]["model_id"] == endpoint["models"][0]["id"]
    assert kwargs["model_context"]["routing_schema_version"] == 2
    assert_app_version_at_least("0.261.061")


def test_schema_v2_agent_tool_choice_respects_route_capability() -> None:
    behavior_function = _find_function("build_agent_function_choice_behavior")
    namespace = {
        "FunctionChoiceBehavior": FunctionChoiceBehavior,
        "get_max_auto_invoke_attempts": lambda _settings: 7,
    }
    exec(
        compile(ast.Module(body=[behavior_function], type_ignores=[]), str(LOADER_FILE), "exec"),
        namespace,
    )

    endpoint = _endpoint("azure_openai_v1")
    endpoint["_resolved_route"] = {"capabilities": {"toolCalling": False}}
    disabled_behavior = namespace["build_agent_function_choice_behavior"](
        {"resolved_model_endpoint": endpoint},
        {},
    )
    assert disabled_behavior.enable_kernel_functions is False
    assert disabled_behavior.maximum_auto_invoke_attempts == 0

    endpoint["_resolved_route"]["capabilities"]["toolCalling"] = True
    enabled_behavior = namespace["build_agent_function_choice_behavior"](
        {"resolved_model_endpoint": endpoint},
        {},
    )
    assert enabled_behavior.enable_kernel_functions is True
    assert enabled_behavior.maximum_auto_invoke_attempts == 7


def test_schema_v2_text_only_agent_omits_tools_from_request() -> None:
    behavior_function = _find_function("build_agent_function_choice_behavior")
    namespace = {
        "FunctionChoiceBehavior": FunctionChoiceBehavior,
        "get_max_auto_invoke_attempts": lambda _settings: 7,
    }
    exec(
        compile(ast.Module(body=[behavior_function], type_ignores=[]), str(LOADER_FILE), "exec"),
        namespace,
    )
    route = {
        "request_model": "gpt-6-luna",
        "capabilities": {
            "processesText": True,
            "generatesText": True,
            "supportsStreaming": True,
            "toolCalling": False,
            "structuredOutput": False,
        },
    }
    endpoint = _endpoint("azure_openai_v1")
    endpoint["_resolved_route"] = route
    behavior = namespace["build_agent_function_choice_behavior"](
        {"resolved_model_endpoint": endpoint},
        {},
    )
    captured_requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "completion",
                "object": "chat.completion",
                "created": 1,
                "model": "gpt-6-luna",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }],
            },
        )

    async def invoke_agent() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            client = AsyncOpenAI(
                api_key="test-key",
                base_url="https://gateway.example/openai/v1/",
                http_client=http_client,
            )
            bind_model_endpoint_request_policy(client, route)
            service = OpenAIChatCompletion(
                service_id="agent-service",
                ai_model_id="gpt-6-luna",
                async_client=client,
            )
            kernel = Kernel()
            kernel.add_service(service)
            kernel.add_plugin(TimePlugin(), plugin_name="time")
            agent = LoggingChatCompletionAgent(
                name="schema_v2_text_agent",
                instructions="Reply with ok.",
                kernel=kernel,
                service=service,
                function_choice_behavior=behavior,
            )
            await agent.invoke(messages="hello")

    asyncio.run(invoke_agent())
    assert len(captured_requests) == 1
    assert "tools" not in captured_requests[0]
    assert "tool_choice" not in captured_requests[0]


def test_schema_v2_agent_stream_preserves_openai_async_stream_contract() -> None:
    route = {
        "request_model": "gpt-6-luna",
        "capabilities": {
            "processesText": True,
            "generatesText": True,
            "supportsStreaming": True,
            "toolCalling": False,
            "structuredOutput": False,
        },
    }

    def respond(_request: httpx.Request) -> httpx.Response:
        events = [
            {
                "id": "completion",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-6-luna",
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": "ok"},
                    "finish_reason": None,
                }],
            },
            {
                "id": "completion",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": "gpt-6-luna",
                "choices": [{
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }],
            },
        ]
        body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        body += "data: [DONE]\n\n"
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    async def invoke_agent() -> list:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http_client:
            client = AsyncOpenAI(
                api_key="test-key",
                base_url="https://gateway.example/openai/v1/",
                http_client=http_client,
            )
            bind_model_endpoint_request_policy(client, route)
            sanitize_custom_async_openai_client(
                client,
                api_type="azure_openai_v1",
                request_url="https://gateway.example/openai/v1/chat/completions",
            )
            service = OpenAIChatCompletion(
                service_id="agent-service",
                ai_model_id="gpt-6-luna",
                async_client=client,
            )
            agent = LoggingChatCompletionAgent(
                name="schema_v2_streaming_agent",
                instructions="Reply with ok.",
                service=service,
                function_choice_behavior=FunctionChoiceBehavior(
                    enable_kernel_functions=False,
                    maximum_auto_invoke_attempts=0,
                ),
            )
            return [response async for response in agent.invoke_stream(messages="hello")]

    responses = asyncio.run(invoke_agent())
    assert "".join(str(response.content) for response in responses) == "ok"


if __name__ == "__main__":
    test_schema_v2_agent_binding_retains_resolved_route()
    test_schema_v2_agent_service_uses_resolved_endpoint()
    test_schema_v2_agent_tool_choice_respects_route_capability()
    test_schema_v2_text_only_agent_omits_tools_from_request()
    test_schema_v2_agent_stream_preserves_openai_async_stream_contract()
