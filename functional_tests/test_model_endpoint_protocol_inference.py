# test_model_endpoint_protocol_inference.py
#!/usr/bin/env python3
"""
Functional test for model endpoint protocol inference.
Version: 0.250.006
Implemented in: 0.241.179; updated in 0.250.006

This test ensures that Foundry model endpoint runtime calls infer Claude as
Anthropic messages, OpenAI-compatible Foundry endpoints as /openai/v1, and
legacy Azure OpenAI endpoints as Azure OpenAI without making network calls. It
also verifies dated preview API versions are preserved for OpenAI-compatible
Foundry requests and the Semantic Kernel agent adapter can build Claude request
payloads without using the Azure OpenAI connector.
"""

import sys
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from model_endpoint_clients import (  # noqa: E402
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    AnthropicChatCompletionClient,
    AnthropicSemanticKernelChatCompletion,
    extract_chat_completion_response_text,
    infer_model_endpoint_protocol,
    normalize_anthropic_messages_url,
    normalize_chat_completion_text,
    normalize_openai_style_base_url,
    resolve_openai_style_request_api_version,
)
from semantic_kernel.contents.chat_history import ChatHistory  # noqa: E402
from semantic_kernel.contents.chat_message_content import ChatMessageContent  # noqa: E402
from semantic_kernel.contents.utils.author_role import AuthorRole  # noqa: E402


def assert_equal(actual, expected, description):
    if actual != expected:
        raise AssertionError(f"{description}: expected {expected!r}, got {actual!r}")


def test_model_endpoint_protocol_inference():
    """Validate protocol inference and endpoint normalization for configured model endpoints."""
    print("Testing model endpoint protocol inference...")

    project_endpoint = "https://eastus2.services.ai.azure.com/api/projects/project-eastus2-dev"
    openai_endpoint = "https://eastus2.services.ai.azure.com/api/projects/project-eastus2-dev/openai/v1"
    anthropic_endpoint = "https://eastus2.services.ai.azure.com/anthropic/v1/messages"
    azure_openai_endpoint = "https://example.openai.azure.com"

    assert_equal(
        infer_model_endpoint_protocol("new_foundry", project_endpoint, "claude-sonnet-4"),
        MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        "Claude deployment names should use Anthropic",
    )
    assert_equal(
        infer_model_endpoint_protocol("claude", project_endpoint, "sonnet-4"),
        MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        "Literal Claude providers should use Anthropic",
    )
    assert_equal(
        infer_model_endpoint_protocol("anthropic", project_endpoint, "sonnet-4"),
        MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        "Literal Anthropic providers should use Anthropic",
    )
    assert_equal(
        infer_model_endpoint_protocol("new_foundry", anthropic_endpoint, "gpt-4o"),
        MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        "Anthropic endpoint paths should use Anthropic",
    )
    assert_equal(
        infer_model_endpoint_protocol("new_foundry", project_endpoint, "grok-3"),
        MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        "Project endpoints should use OpenAI-compatible Foundry for non-Claude models",
    )
    assert_equal(
        infer_model_endpoint_protocol("aifoundry", openai_endpoint, "gpt-4.1"),
        MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        "Explicit /openai/v1 endpoints should use OpenAI-compatible Foundry",
    )
    assert_equal(
        infer_model_endpoint_protocol("aoai", azure_openai_endpoint, "gpt-4o"),
        MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
        "Azure OpenAI endpoints should keep the Azure OpenAI protocol",
    )

    assert_equal(
        normalize_anthropic_messages_url(project_endpoint),
        "https://eastus2.services.ai.azure.com/anthropic/v1/messages",
        "Project endpoints should normalize to the Anthropic messages URL",
    )
    assert_equal(
        normalize_anthropic_messages_url("https://eastus2.services.ai.azure.com/anthropic/v1"),
        anthropic_endpoint,
        "Anthropic v1 base URLs should normalize to messages",
    )
    assert_equal(
        normalize_openai_style_base_url(project_endpoint),
        "https://eastus2.services.ai.azure.com/api/projects/project-eastus2-dev/openai/v1/",
        "Project endpoints should normalize to /openai/v1 base URLs",
    )
    assert_equal(
        normalize_openai_style_base_url(openai_endpoint + "/chat/completions"),
        openai_endpoint + "/",
        "Chat completion URLs should normalize back to the /openai/v1 base URL",
    )
    assert_equal(
        resolve_openai_style_request_api_version("v1"),
        "",
        "OpenAI-compatible v1 should not add an api-version query string",
    )
    assert_equal(
        resolve_openai_style_request_api_version("2024-05-01-preview"),
        "",
        "OpenAI-compatible /v1 calls should not add dated api-version query strings",
    )
    assert_equal(
        resolve_openai_style_request_api_version("2025-11-15-preview"),
        "",
        "Provider-specific dated preview values should be omitted for /v1 calls",
    )
    assert_equal(
        resolve_openai_style_request_api_version("preview"),
        "",
        "Preview should be omitted for OpenAI-compatible /v1 calls",
    )
    assert_equal(
        normalize_chat_completion_text([{"type": "text", "text": "Hello"}, {"content": " world"}]),
        "Hello world",
        "Structured OpenAI-compatible message content should normalize to text",
    )
    assert_equal(
        extract_chat_completion_response_text(
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=[{"type": "text", "text": "Recovered"}])
                    )
                ]
            )
        ),
        "Recovered",
        "Non-streaming fallback should extract structured response text",
    )

    client = AnthropicChatCompletionClient(endpoint=project_endpoint, api_key="test-key")
    payload = client._build_payload(
        {
            "model": "claude-sonnet-4",
            "messages": [
                {"role": "system", "content": "Use concise answers."},
                {"role": "user", "content": "Testing access."},
            ],
            "max_tokens": 64,
            "stream": True,
        }
    )
    assert_equal(payload["model"], "claude-sonnet-4", "Anthropic payload should keep deployment name")
    assert_equal(payload["system"], "Use concise answers.", "System messages should map to Anthropic system")
    assert_equal(payload["messages"], [{"role": "user", "content": "Testing access."}], "User messages should be preserved")
    assert_equal(payload["max_tokens"], 64, "max_tokens should be preserved")
    assert_equal(payload["stream"], True, "stream should be preserved")

    sk_service = AnthropicSemanticKernelChatCompletion(
        service_id="agent-claude",
        deployment_name="claude-sonnet-4",
        endpoint=project_endpoint,
        api_key="test-key",
    )
    settings = sk_service.get_prompt_execution_settings_class()(max_tokens=128, temperature=0.2)
    history = ChatHistory(
        messages=[
            ChatMessageContent(role=AuthorRole.SYSTEM, content="Use concise answers."),
            ChatMessageContent(role=AuthorRole.USER, content="Testing agent access."),
        ]
    )
    sk_payload = sk_service._build_request_kwargs(history, settings, stream=True)
    assert_equal(sk_payload["model"], "claude-sonnet-4", "SK Claude service should keep deployment name")
    assert_equal(sk_payload["messages"][0]["role"], "system", "SK Claude service should preserve system message role")
    assert_equal(sk_payload["messages"][1]["content"], "Testing agent access.", "SK Claude service should preserve user content")
    assert_equal(sk_payload["max_tokens"], 128, "SK Claude service should copy max_tokens")
    assert_equal(sk_payload["temperature"], 0.2, "SK Claude service should copy temperature")
    assert_equal(sk_payload["stream"], True, "SK Claude service should support streaming")

    loader_content = (APP_DIR / "semantic_kernel_loader.py").read_text(encoding="utf-8")
    if "create_model_endpoint_chat_completion_service" not in loader_content:
        raise AssertionError("Semantic Kernel loader should centralize endpoint chat service creation.")
    if "AnthropicSemanticKernelChatCompletion" not in loader_content:
        raise AssertionError("Semantic Kernel loader should wire Claude endpoints to the Anthropic SK service.")
    if "MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE" not in loader_content:
        raise AssertionError("Semantic Kernel loader should wire OpenAI-compatible Foundry endpoints for agents.")

    print("✅ Model endpoint protocol inference verified.")


if __name__ == "__main__":
    success = True
    try:
        test_model_endpoint_protocol_inference()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)