# test_functional_application_logic.py
"""
Functional test for SimpleChat application logic without Playwright.
Version: 0.250.023
Implemented in: 0.250.023

This test validates backend model-endpoint routing and model behavior policy
directly in Python. It does not open a browser, use Playwright, require a live
Flask server, or require an authenticated session.
"""

import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from model_endpoint_clients import (  # noqa: E402
    MODEL_CONTEXT_MODE_FOLD_LATEST_USER,
    MODEL_CONTEXT_MODE_SYSTEM,
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    ModelEndpointBehavior,
    infer_model_endpoint_protocol,
    normalize_anthropic_messages_url,
    normalize_openai_style_base_url,
)


def test_foundry_gpt54_uses_openai_style_runtime():
    """Validate GPT-5.4 Foundry chat-completions endpoints use OpenAI-compatible runtime."""
    protocol = infer_model_endpoint_protocol(
        provider="new_foundry",
        endpoint="https://example.services.ai.azure.com/openai/v1/chat/completions",
        deployment_name="gpt-5.4",
    )
    base_url = normalize_openai_style_base_url(
        "https://example.services.ai.azure.com/openai/v1/chat/completions"
    )

    assert protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE
    assert base_url == "https://example.services.ai.azure.com/openai/v1/"
    print("GPT-5.4 Foundry endpoint routes through OpenAI-compatible runtime.")


def test_claude_deployment_uses_anthropic_runtime():
    """Validate Claude deployments route to Anthropic messages runtime."""
    protocol = infer_model_endpoint_protocol(
        provider="new_foundry",
        endpoint="https://example.services.ai.azure.com/api/projects/simplechat-demo",
        deployment_name="Claude-3-7-Sonnet",
    )
    messages_url = normalize_anthropic_messages_url(
        "https://example.services.ai.azure.com/api/projects/simplechat-demo"
    )

    assert protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC
    assert messages_url == "https://example.services.ai.azure.com/anthropic/v1/messages"
    print("Claude deployment routes through Anthropic messages runtime.")


def test_model_behavior_policy_for_reasoning_and_non_openai_models():
    """Validate reasoning effort and context-mode policy decisions."""
    gpt54_behavior = ModelEndpointBehavior(provider="new_foundry", deployment_name="gpt-5.4")
    llama_behavior = ModelEndpointBehavior(provider="new_foundry", deployment_name="Llama-3.3-70B-Instruct")
    gpt4o_behavior = ModelEndpointBehavior(provider="new_foundry", deployment_name="gpt-4o")

    assert gpt54_behavior.is_openai_reasoning_model
    assert gpt54_behavior.resolve_reasoning_effort("medium") == "medium"
    assert gpt54_behavior.context_mode == MODEL_CONTEXT_MODE_SYSTEM

    assert llama_behavior.is_foundry_non_openai_model
    assert llama_behavior.context_mode == MODEL_CONTEXT_MODE_FOLD_LATEST_USER
    assert llama_behavior.resolve_reasoning_effort("medium") == ""

    assert not gpt4o_behavior.is_openai_reasoning_model
    assert gpt4o_behavior.resolve_reasoning_effort("medium") == ""
    print("Model behavior policy handles reasoning and non-OpenAI context modes correctly.")