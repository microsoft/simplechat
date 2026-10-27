# test_responses_model_tool_execution.py
"""Functional tests for Responses reasoning in the real authorized SDK tool loop.

Version: 0.261.389
Implemented in: 0.261.388

The real SDK and Semantic Kernel execute against a mock HTTP transport. Reasoning
continuation is request-owned and never appears in public message serialization.
"""

import asyncio
import ast
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import httpx
import pytest
from openai import AsyncOpenAI
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.functions import kernel_function

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_model_capabilities import project_model_budget_metadata, resolve_model_token_budget
from functions_model_endpoint_validation import ModelEndpointValidationError, model_endpoint_inference_api, validate_model_endpoint_api_version
from functions_orchestration_model_capture import azure_chat_construction_metadata
from functions_model_endpoint_diagnostics import SanitizedModelEndpointError
from model_endpoint_clients import (
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC, MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    infer_model_endpoint_protocol, normalize_openai_style_base_url, resolve_openai_style_request_api_version,
    resolve_model_inference_endpoint,
)
from model_responses_chat import responses_request
from model_tool_chat_completion import OpenAIToolChatCompletion


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra"])
@pytest.mark.parametrize("new_user_turn", [False, True])
def test_reasoning_and_function_results_continue_once_without_changing_model_or_effort(streaming, model, new_user_turn):
    requests, executions = [], []

    class Tools:
        @kernel_function
        def lookup(self, query: str) -> str:
            executions.append(query)
            return query

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url.path == "/openai/v1/responses"
        assert not request.url.query
        if len(requests) == 1:
            output = [
                {"type": "reasoning", "id": "reasoning-1", "summary": [], "encrypted_content": "encrypted-private"},
                {"type": "function_call", "id": "function-1", "call_id": "call-local",
                 "name": "local-lookup", "arguments": '{"query":"42"}', "status": "completed"},
            ]
        else:
            output = [{"type": "message", "id": "answer-1", "role": "assistant", "status": "completed",
                       "content": [{"type": "output_text", "text": "The verified total is 42.", "annotations": []}]}]
        return httpx.Response(200, json={
            "id": f"response-{len(requests)}", "object": "response", "created_at": 1,
            "model": model, "status": "completed", "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        })

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = AsyncOpenAI(api_key="offline", base_url="https://offline.invalid/openai/v1/", http_client=http)
            service = OpenAIToolChatCompletion(
                service_id="agent-model", ai_model_id="production-alias", async_client=client,
                inference_api="responses",
                model_token_budget=resolve_model_token_budget(model, provider="azure", protocol="responses"),
            )
            kernel = Kernel()
            kernel.add_plugin(Tools(), plugin_name="local")
            history = ChatHistory()
            history.add_user_message("Look up the total")
            settings = OpenAIChatPromptExecutionSettings(
                service_id="agent-model", max_completion_tokens=1024,
                extra_body={"reasoning_effort": "high"},
                function_choice_behavior=FunctionChoiceBehavior.Auto(maximum_auto_invoke_attempts=3),
            )
            try:
                if streaming:
                    chunks = [chunk async for chunk in service.get_streaming_chat_message_contents(history, settings, kernel=kernel)]
                    text = "".join(str(message) for chunk in chunks for message in chunk)
                    public = [message.model_dump_json() for chunk in chunks for message in chunk]
                else:
                    result = await service.get_chat_message_contents(history, settings, kernel=kernel)
                    text = result[0].content
                    public = [message.model_dump_json() for message in result]
                if new_user_turn:
                    history.add_assistant_message(text)
                    history.add_user_message("A separate follow-up question")
                    followup = await service.get_chat_message_contents(history, settings, kernel=kernel)
                    public.extend(message.model_dump_json() for message in followup)
            finally:
                await client.close()
            return text, public

    text, public = asyncio.run(execute())
    assert "The verified total is 42." in text
    assert executions == ["42"]
    assert len(requests) == (3 if new_user_turn else 2)
    for request in requests:
        assert request["model"] == "production-alias"
        assert request["reasoning"] == {"effort": "high"}
        assert request["max_output_tokens"] == 1024
        assert request["store"] is False
        assert "reasoning_effort" not in request
        assert "previous_response_id" not in request
    continuation = requests[1]["input"]
    assert any(item.get("encrypted_content") == "encrypted-private" for item in continuation)
    assert len([item for item in continuation if item.get("type") == "function_call"]) == 1
    assert any(item.get("type") == "function_call_output" and item["call_id"] == "call-local" and item["output"] == "42"
               for item in continuation)
    assert "encrypted-private" not in "".join(public)
    if new_user_turn:
        assert "encrypted-private" not in json.dumps(requests[2]["input"])


def test_a_callers_json_cannot_inject_private_reasoning_continuation():
    with pytest.raises(ModelEndpointValidationError):
        responses_request({"model": "selected", "messages": [
            {"role": "assistant", "_simplechat_responses_items": [{"type": "reasoning", "encrypted_content": "other-user"}]},
        ]})


def test_unsupported_options_are_not_silently_discarded():
    with pytest.raises(ModelEndpointValidationError):
        responses_request({"model": "selected", "messages": [], "frequency_penalty": 1})


def test_v1_responses_construction_is_observed_and_protocol_mutation_is_refused():
    async def execute():
        client = AsyncOpenAI(api_key="private-key-sentinel", base_url="https://offline.invalid/openai/v1/")
        service = OpenAIToolChatCompletion(ai_model_id="production-alias", async_client=client, inference_api="responses")
        endpoint = "https://offline.invalid/openai/v1/responses"
        try:
            observed = azure_chat_construction_metadata(
                service, protocol="openai_style", provider="aoai",
                configured_endpoint=endpoint, configured_api_version="v1",
            )
            service.inference_api = "chat_completions"
            refused = azure_chat_construction_metadata(
                service, protocol="openai_style", provider="aoai",
                configured_endpoint=endpoint, configured_api_version="v1",
            )
        finally:
            await client.close()
        return observed, refused

    observed, refused = asyncio.run(execute())
    assert observed["protocol"] == "responses"
    assert observed["deployment"] == "production-alias"
    assert observed["api_version"] == ""
    assert "private-key-sentinel" not in json.dumps(observed)
    assert refused is None
    assert model_endpoint_inference_api("https://offline.invalid/openai/v1/") == "chat_completions"
    assert model_endpoint_inference_api("https://offline.invalid/openai/v1/responses") == "responses"


def test_real_agent_factory_selects_responses_without_changing_the_action_plugins():
    source = Path(__file__).resolve().parents[1] / "application" / "single_app" / "semantic_kernel_loader.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"build_agent_model_budget", "create_model_endpoint_chat_completion_service",
             "resolve_agent_endpoint_protocol", "resolve_agent_endpoint_token"}
    namespace = {
        "AsyncOpenAI": AsyncOpenAI, "OpenAIChatCompletion": OpenAIToolChatCompletion,
        "MODEL_ENDPOINT_PROTOCOL_ANTHROPIC": MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        "MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE": MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        "infer_model_endpoint_protocol": infer_model_endpoint_protocol,
        "normalize_openai_style_base_url": normalize_openai_style_base_url,
        "resolve_openai_style_request_api_version": resolve_openai_style_request_api_version,
        "resolve_model_token_budget": resolve_model_token_budget,
        "project_model_budget_metadata": project_model_budget_metadata,
        "model_endpoint_inference_api": model_endpoint_inference_api,
        "resolve_model_inference_endpoint": resolve_model_inference_endpoint,
        "validate_model_endpoint_api_version": validate_model_endpoint_api_version,
    }
    exec(compile(ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names],
                            type_ignores=[]), str(source), "exec"), namespace)
    service = namespace["create_model_endpoint_chat_completion_service"]({
        "endpoint": "https://offline.invalid/openai/v1/responses", "deployment": "production-alias",
        "api_version": "v1", "model_provider": "aoai", "key": "offline",
        "model_budget_model": {"modelName": "gpt-5.6-sol"}, "max_completion_tokens": 1024,
    }, "configured-agent", {})
    try:
        assert service.inference_api == "responses"
        assert service.ai_model_id == "production-alias"
        assert service.model_token_budget.protocol == "responses"
        assert service.model_token_budget.model_id == "gpt-5.6-sol"
        assert str(service.client.base_url) == "https://offline.invalid/openai/v1/"
    finally:
        asyncio.run(service.client.close())


def test_provider_failure_has_no_private_body_or_exception_chain():
    async def execute():
        def respond(request):
            return httpx.Response(400, json={"error": {
                "message": "private-provider-body-sentinel", "type": "invalid_request_error",
            }})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = AsyncOpenAI(api_key="offline", base_url="https://offline.invalid/openai/v1/", http_client=http)
            service = OpenAIToolChatCompletion(ai_model_id="gpt-5.6-sol", async_client=client, inference_api="responses")
            history = ChatHistory()
            history.add_user_message("Test a model failure")
            try:
                await service.get_chat_message_contents(history, OpenAIChatPromptExecutionSettings())
            finally:
                await client.close()
    with patch("functions_model_endpoint_diagnostics.log_event") as logged:
        with pytest.raises(SanitizedModelEndpointError) as caught:
            asyncio.run(execute())
    assert "private-provider-body-sentinel" not in str(caught.value)
    assert "private-provider-body-sentinel" not in str(logged.call_args_list)
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_cancellation_does_not_replay_a_completed_tool():
    async def execute():
        started = asyncio.Event()
        requests, executions = [], []

        class Tools:
            @kernel_function
            def lookup(self, query: str) -> str:
                executions.append(query)
                return query

        async def respond(request):
            requests.append(request)
            if len(requests) == 1:
                return httpx.Response(200, json={
                    "id": "response-before-cancel", "object": "response", "created_at": 1,
                    "model": "gpt-5.6-sol", "status": "completed",
                    "output": [{"type": "function_call", "id": "function-1", "call_id": "call-local",
                                "name": "local-lookup", "arguments": '{"query":"42"}', "status": "completed"}],
                    "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
                })
            started.set()
            await asyncio.Event().wait()

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = AsyncOpenAI(api_key="offline", base_url="https://offline.invalid/openai/v1/", http_client=http)
            service = OpenAIToolChatCompletion(ai_model_id="gpt-5.6-sol", async_client=client, inference_api="responses")
            history = ChatHistory()
            history.add_user_message("A cancellable request")
            kernel = Kernel()
            kernel.add_plugin(Tools(), plugin_name="local")
            task = asyncio.create_task(service.get_chat_message_contents(
                history, OpenAIChatPromptExecutionSettings(function_choice_behavior=FunctionChoiceBehavior.Auto()),
                kernel=kernel,
            ))
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                await client.close()
            return len(requests), executions
    count, executions = asyncio.run(execute())
    assert count == 2 and executions == ["42"]


@pytest.mark.parametrize("first,second", [
    ("model_tool_chat_completion", "model_endpoint_clients"),
    ("model_endpoint_clients", "model_tool_chat_completion"),
])
def test_model_tool_modules_cold_import_without_settings_or_network(first, second):
    root = Path(__file__).resolve().parents[1]
    script = """
import importlib, socket, ssl, sys
def blocked(*args, **kwargs):
    raise AssertionError("Network is blocked during model-module import")
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.getaddrinfo = blocked
sys.path.insert(0, sys.argv[1])
importlib.import_module(sys.argv[2])
importlib.import_module(sys.argv[3])
if "config" in sys.modules or "functions_settings" in sys.modules:
    raise AssertionError("A model wire module initialized its configuration owner")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(root / "application" / "single_app"), first, second],
        capture_output=True, text=True, timeout=60, cwd=root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
