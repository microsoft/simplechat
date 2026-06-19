# test_claude_agent_tool_calling.py
#!/usr/bin/env python3
"""
Functional test for Claude local agent tool calling.
Version: 0.250.007
Implemented in: 0.250.007

This test ensures Claude-backed local Semantic Kernel agents can expose loaded
plugins to the Anthropic messages protocol and receive tool_use responses that
Semantic Kernel can auto-invoke.
"""

import asyncio
import json
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from model_endpoint_clients import (  # noqa: E402
    AnthropicChatCompletionClient,
    AnthropicSemanticKernelChatCompletion,
)
from semantic_kernel.contents.chat_history import ChatHistory  # noqa: E402
from semantic_kernel.contents.chat_message_content import ChatMessageContent  # noqa: E402
from semantic_kernel.contents.function_call_content import FunctionCallContent  # noqa: E402
from semantic_kernel.contents.function_result_content import FunctionResultContent  # noqa: E402
from semantic_kernel.contents.utils.author_role import AuthorRole  # noqa: E402


PROJECT_ENDPOINT = "https://eastus2.services.ai.azure.com/api/projects/project-eastus2-dev"
TOOL_NAME = "enterprise_software_asset_management-execute_query"


def assert_equal(actual, expected, description):
    """Assert equality with a useful failure message."""
    if actual != expected:
        raise AssertionError(f"{description}: expected {expected!r}, got {actual!r}")


def assert_true(value, description):
    """Assert truthiness with a useful failure message."""
    if not value:
        raise AssertionError(description)


def build_tool_schema():
    """Build a minimal OpenAI-style tool schema like SK places in prompt settings."""
    return [{
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Execute a read-only SQL query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_rows": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    }]


def test_anthropic_payload_converts_sk_tools():
    """Validate SK/OpenAI tool schemas are converted to Anthropic tool schemas."""
    print("Testing Anthropic tool schema conversion...")
    client = AnthropicChatCompletionClient(endpoint=PROJECT_ENDPOINT, api_key="fake-key")
    payload = client._build_payload({
        "model": "claude-opus-4-6",
        "messages": [{"role": "user", "content": "How many Office licenses are available?"}],
        "tools": build_tool_schema(),
        "tool_choice": "auto",
    })

    assert_equal(payload["tools"][0]["name"], TOOL_NAME, "tool name")
    assert_equal(payload["tools"][0]["input_schema"]["required"], ["query"], "tool input schema")
    assert_equal(payload["tool_choice"], {"type": "auto"}, "tool choice")


def test_anthropic_tool_use_maps_to_sk_function_call():
    """Validate Anthropic tool_use responses become SK FunctionCallContent."""
    print("Testing Anthropic tool_use response conversion...")
    client = AnthropicChatCompletionClient(endpoint=PROJECT_ENDPOINT, api_key="fake-key")
    response = client._build_completion_response({
        "content": [{
            "type": "tool_use",
            "id": "toolu_123",
            "name": TOOL_NAME,
            "input": {"query": "SELECT 1", "max_rows": 10},
        }],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 11, "output_tokens": 7},
    })

    service = AnthropicSemanticKernelChatCompletion(
        service_id="agent-claude",
        deployment_name="claude-opus-4-6",
        endpoint=PROJECT_ENDPOINT,
        api_key="fake-key",
    )
    message = service._create_chat_message_contents_from_response(response)[0]
    function_calls = [item for item in message.items if isinstance(item, FunctionCallContent)]

    assert_equal(len(function_calls), 1, "function call count")
    assert_equal(function_calls[0].id, "toolu_123", "function call id")
    assert_equal(function_calls[0].name, TOOL_NAME, "function call name")
    assert_equal(json.loads(function_calls[0].arguments)["query"], "SELECT 1", "function call arguments")
    assert_true(AnthropicSemanticKernelChatCompletion.SUPPORTS_FUNCTION_CALLING, "SK Anthropic service should support function calling")


def test_sk_history_converts_tool_results_for_anthropic():
    """Validate SK function-call history is rendered as Anthropic tool blocks."""
    print("Testing SK tool history conversion...")
    service = AnthropicSemanticKernelChatCompletion(
        service_id="agent-claude",
        deployment_name="claude-opus-4-6",
        endpoint=PROJECT_ENDPOINT,
        api_key="fake-key",
    )
    history = ChatHistory(messages=[
        ChatMessageContent(role=AuthorRole.USER, content="Check Office availability."),
        ChatMessageContent(
            role=AuthorRole.ASSISTANT,
            items=[FunctionCallContent(id="toolu_123", name=TOOL_NAME, arguments={"query": "SELECT 1"})],
        ),
        ChatMessageContent(
            role=AuthorRole.TOOL,
            items=[FunctionResultContent(id="toolu_123", name=TOOL_NAME, result="[{\"Available\": 20}]")],
        ),
    ])

    request_kwargs = service._build_request_kwargs(history, service.instantiate_prompt_execution_settings(), stream=False)
    assert_equal(request_kwargs["messages"][1]["content"][0]["type"], "tool_use", "assistant tool_use block")
    assert_equal(request_kwargs["messages"][2]["role"], "user", "tool result role")
    assert_equal(request_kwargs["messages"][2]["content"][0]["type"], "tool_result", "tool result block")
    assert_equal(request_kwargs["messages"][2]["content"][0]["tool_use_id"], "toolu_123", "tool result id")


class FakeAnthropicService(AnthropicSemanticKernelChatCompletion):
    """Test double that returns a fake Anthropic response without network calls."""

    def __init__(self, fake_client, **kwargs):
        super().__init__(**kwargs)
        object.__setattr__(self, "fake_client", fake_client)

    def _build_client(self):
        return self.fake_client


def test_streaming_with_tools_uses_non_streaming_tool_request():
    """Validate streaming agent turns with tools still return SK function calls."""
    print("Testing streaming tool fallback request mode...")
    captured_kwargs = {}

    def fake_create(**kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    tool_calls=[SimpleNamespace(
                        id="toolu_123",
                        function=SimpleNamespace(name=TOOL_NAME, arguments='{"query": "SELECT 1"}'),
                    )],
                ),
                finish_reason="tool_use",
            )],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    service = FakeAnthropicService(
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))),
        service_id="agent-claude",
        deployment_name="claude-opus-4-6",
        endpoint=PROJECT_ENDPOINT,
        api_key="fake-key",
    )
    settings = service.instantiate_prompt_execution_settings()
    settings.tools = build_tool_schema()
    settings.tool_choice = "auto"
    history = ChatHistory(messages=[
        ChatMessageContent(role=AuthorRole.USER, content="Check Office availability."),
    ])

    async def collect_chunks():
        chunks = []
        async for messages in service._inner_get_streaming_chat_message_contents(history, settings):
            chunks.extend(messages)
        return chunks

    chunks = asyncio.run(collect_chunks())
    function_calls = [item for chunk in chunks for item in chunk.items if isinstance(item, FunctionCallContent)]

    assert_equal(captured_kwargs["stream"], False, "tool-enabled stream request mode")
    assert_equal(captured_kwargs["tools"][0]["function"]["name"], TOOL_NAME, "SK tool schema preserved before Anthropic conversion")
    assert_equal(len(function_calls), 1, "streaming function call count")
    assert_equal(function_calls[0].id, "toolu_123", "streaming function call id")


def main():
    """Run all checks."""
    tests = [
        test_anthropic_payload_converts_sk_tools,
        test_anthropic_tool_use_maps_to_sk_function_call,
        test_sk_history_converts_tool_results_for_anthropic,
        test_streaming_with_tools_uses_non_streaming_tool_request,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)