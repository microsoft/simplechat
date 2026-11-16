# test_model_tool_execution_policy.py
"""Functional tests for policy enforcement at actual Semantic Kernel SDK calls.

Version: 0.261.389
Implemented in: 0.261.388

Real SDK requests use an in-memory HTTP transport. No Azure resource or test
configuration is imported, and no function tool with external effects is run.
"""

import asyncio
import json
from pathlib import Path
import sys

import httpx
import pytest
from openai import AsyncAzureOpenAI, AsyncOpenAI
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import AzureChatPromptExecutionSettings
from semantic_kernel.contents.chat_history import ChatHistory
from semantic_kernel.functions import kernel_function

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_model_capabilities import ModelTokenBudgetError, resolve_model_token_budget
from model_tool_chat_completion import AzureToolChatCompletion, OpenAIToolChatCompletion


class LocalTools:
    @kernel_function
    def lookup(self, query: str) -> str:
        return query


def invoke(model, *, provider="azure", effort=None, tools=True):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "offline", "object": "chat.completion", "created": 0,
            "model": model, "choices": [{
                "index": 0, "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }],
        })

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            budget = resolve_model_token_budget(model, provider=provider)
            if provider == "azure":
                client = AsyncAzureOpenAI(
                    api_key="offline", azure_endpoint="https://offline.invalid",
                    api_version="2024-10-01-preview", http_client=http,
                )
                service = AzureToolChatCompletion(
                    service_id="tabular-analysis", deployment_name="friendly-deployment",
                    async_client=client, model_token_budget=budget,
                )
            else:
                client = AsyncOpenAI(
                    api_key="offline", base_url="https://offline.invalid/v1/",
                    http_client=http,
                )
                service = OpenAIToolChatCompletion(
                    service_id="tabular-analysis", ai_model_id="friendly-deployment",
                    async_client=client, model_token_budget=budget,
                )
            kernel = Kernel()
            kernel.add_plugin(LocalTools(), plugin_name="local")
            history = ChatHistory()
            history.add_user_message("Look up the selected data")
            settings = AzureChatPromptExecutionSettings(
                service_id="tabular-analysis",
                function_choice_behavior=FunctionChoiceBehavior.Auto() if tools else None,
                max_completion_tokens=1024,
                extra_body={"reasoning_effort": effort} if effort is not None else None,
            )
            try:
                result = await service.get_chat_message_contents(history, settings, kernel=kernel)
            finally:
                await client.close()
            return result

    result = asyncio.run(execute())
    return result, requests


@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.6-terra"])
@pytest.mark.parametrize("effort", [None, "none"])
def test_azure_tool_calls_send_explicit_none_with_canonical_model_and_deployment_alias(model, effort):
    result, requests = invoke(model, effort=effort)
    assert result[0].content == "ok"
    assert len(requests) == 1
    assert requests[0]["reasoning_effort"] == "none"
    assert requests[0]["model"] == "friendly-deployment"
    assert requests[0]["tools"]
    assert requests[0]["max_completion_tokens"] == 1024
    assert "max_tokens" not in requests[0]


def test_explicit_positive_effort_is_not_silently_disabled():
    with pytest.raises(ModelTokenBudgetError, match="Reasoning Effort None"):
        invoke("gpt-5.6-sol", effort="high")


@pytest.mark.parametrize("provider,tools", [("openai", True), ("azure", False)])
def test_nonrestricted_request_preserves_the_requested_reasoning(provider, tools):
    _, requests = invoke("gpt-5.6-sol", provider=provider, effort="high", tools=tools)
    assert requests[0]["reasoning_effort"] == "high"


def test_gpt51_tools_do_not_gain_an_unrequested_none_override():
    _, requests = invoke("gpt-5.1")
    assert "reasoning_effort" not in requests[0]
