# test_model_persona_runtime.py
"""
Functional tests for model persona request composition.
Version: 0.261.463
Implemented in: 0.261.461; transport logging guard added in: 0.261.463

This test verifies strict persona validation, Unicode boundaries, request
isolation, provider request composition, and idempotent request-policy binding.
"""

import asyncio
import ast
import copy
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
single_app_root = os.path.join(repo_root, "application", "single_app")
sys.path.append(repo_root)
sys.path.append(single_app_root)

from functions_ai_connections import AIConnectionError
from functions_model_persona import (
    MODEL_PERSONA_MAX_CHARACTERS,
    active_model_persona_markdown,
    model_persona_character_count,
    model_persona_system_message,
    normalize_model_persona,
    prepend_model_persona_messages,
    prepend_model_persona_request,
    validate_model_persona_settings_document,
    validate_model_persona_collection_size,
)
from functions_model_capabilities import ModelTokenBudgetError
from model_endpoint_clients import (
    AnthropicSemanticKernelChatCompletion,
    bind_callable_with_timeout,
    bind_model_endpoint_request_policy,
)


class _CaptureResource:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return kwargs


class _CaptureAsyncResource(_CaptureResource):
    async def create(self, **kwargs):
        self.requests.append(kwargs)
        return kwargs


def test_persona_validation_and_unicode_limit():
    maximum = "\U0001f9d1" * MODEL_PERSONA_MAX_CHARACTERS
    assert model_persona_character_count(maximum) == MODEL_PERSONA_MAX_CHARACTERS
    assert normalize_model_persona({"persona_markdown": maximum})["persona_markdown"] == maximum

    for model in (
        {"persona_enabled": "true"},
        {"persona_markdown": 1},
        {"persona_text_visible": "true"},
        {"persona_markdown": maximum + "\U0001f9d1"},
    ):
        try:
            normalize_model_persona(model)
        except AIConnectionError:
            pass
        else:
            raise AssertionError(f"Invalid persona configuration was accepted: {model.keys()}")

    assert active_model_persona_markdown({
        "persona_enabled": True,
        "persona_markdown": "   \n",
    }) == ""
    assert active_model_persona_markdown({
        "persona_enabled": True,
        "persona_markdown": "Be concise.",
    }) == "Be concise."

    with_collection_headroom = [{
        "models": [
            {
                "persona_markdown": "x" * MODEL_PERSONA_MAX_CHARACTERS,
            }
            for _ in range(188)
        ],
    }]
    try:
        validate_model_persona_collection_size(with_collection_headroom)
    except AIConnectionError as exc:
        assert exc.code == "model_persona_collection_too_large"
    else:
        raise AssertionError("Aggregate model persona content must be bounded.")

    escaped_document = {
        "model_endpoints": [{
            "id": "escape-test",
            "models": [
                {"persona_enabled": True, "persona_markdown": "\U0001f9d1" * 8000}
                for _ in range(22)
            ],
        }],
    }
    try:
        validate_model_persona_settings_document(escaped_document)
    except AIConnectionError as exc:
        assert exc.code == "model_persona_settings_too_large"
    else:
        raise AssertionError("Cosmos-equivalent escaped JSON must be bounded.")


def test_persona_composition_preserves_original_request():
    original = {
        "model": "chat-model",
        "messages": [
            {"role": "system", "content": "Application rules"},
            {"role": "user", "content": "Hello"},
        ],
        "tools": [{"type": "function"}],
    }
    snapshot = copy.deepcopy(original)
    composed = prepend_model_persona_request(original, "Be concise.")

    assert original == snapshot
    assert composed is not original
    assert composed["messages"][0] == model_persona_system_message("Be concise.")
    assert composed["messages"][1:] == original["messages"]
    assert composed["tools"] == original["tools"]

    response_request = prepend_model_persona_request(
        {"model": "chat-model", "input": [{"role": "user", "content": "Hello"}]},
        "Be direct.",
    )
    assert response_request["input"][0] == model_persona_system_message("Be direct.")


def test_request_policy_injects_persona_once_for_sync_and_async_clients():
    completions = _CaptureResource()
    responses = _CaptureResource()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        responses=responses,
    )

    bound = bind_model_endpoint_request_policy(
        client, None, persona_markdown="Use plain language."
    )
    assert bind_model_endpoint_request_policy(
        bound, None, persona_markdown="Use plain language."
    ) is client

    chat_request = client.chat.completions.create(
        model="chat-model",
        messages=[{"role": "user", "content": "Hello"}],
    )
    assert sum(
        message.get("content", "").endswith("Use plain language.")
        for message in chat_request["messages"]
    ) == 1

    response_request = client.responses.create(
        model="chat-model",
        input=[{"role": "user", "content": "Hello"}],
    )
    assert sum(
        item.get("content", "").endswith("Use plain language.")
        for item in response_request["input"]
    ) == 1

    async_completions = _CaptureAsyncResource()
    async_client = SimpleNamespace(
        chat=SimpleNamespace(completions=async_completions),
        responses=None,
    )
    bind_model_endpoint_request_policy(
        async_client, None, persona_markdown="Use async plain language."
    )
    async_result = asyncio.run(async_client.chat.completions.create(
        model="chat-model",
        messages=[{"role": "user", "content": "Hello"}],
    ))
    assert async_result["messages"][0]["content"].endswith(
        "Use async plain language."
    )


def test_anthropic_semantic_kernel_service_binds_persona_per_request():
    custom_client = SimpleNamespace(
        chat=SimpleNamespace(completions=_CaptureResource())
    )
    service = AnthropicSemanticKernelChatCompletion(
        service_id="persona-test",
        deployment_name="chat-model",
        endpoint="https://provider.example/messages",
        custom_client=custom_client,
        model_persona_markdown="Prefer short answers.",
    )
    bound_client = service._build_client()
    result = bound_client.chat.completions.create(
        model="chat-model",
        messages=[{"role": "user", "content": "Hello"}],
    )
    assert result["messages"][0]["content"].endswith("Prefer short answers.")
    assert service.model_persona_markdown == "Prefer short answers."


def test_timeout_scoped_callable_preserves_persona_policy():
    scoped_completions = _CaptureResource()

    class ScopedClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=scoped_completions)

    client = ScopedClient()
    client.with_options = lambda **_kwargs: ScopedClient()
    bind_model_endpoint_request_policy(
        client, None, persona_markdown="Keep timeout-scoped requests concise."
    )

    bounded = bind_callable_with_timeout(
        client,
        client.chat.completions.create,
        timeout_seconds=5,
        max_retries=0,
    )
    result = bounded(
        model="chat-model",
        messages=[{"role": "user", "content": "Hello"}],
    )
    assert result["messages"][0]["content"].endswith(
        "Keep timeout-scoped requests concise."
    )


def test_model_http_debug_logging_is_suppressed():
    for filename in ("app.py", "simplechat_scheduler.py"):
        source = Path(single_app_root, filename).read_text(encoding="utf-8")
        for logger_name in ("httpx", "httpcore", "openai", "anthropic"):
            assert logger_name in source
        assert "logging.getLogger(model_http_logger).setLevel(logging.INFO)" in source


def test_direct_chat_overflow_summarizes_history_before_dispatch():
    source_path = Path(single_app_root) / "route_backend_chats.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    helper = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_fit_direct_chat_persona_context"
    )
    audits = [
        {"decision": "blocked"},
        {"decision": "full_input"},
        {"decision": "full_input"},
    ]
    summary_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=object())))
    )
    namespace = {
        "bound_model_persona": lambda _client: "A strict persona.",
        "bound_model_persona_metadata": lambda _client: {"modelName": "chat-model"},
        "ModelTokenBudgetError": ModelTokenBudgetError,
        "prepend_model_persona_messages": prepend_model_persona_messages,
        "calculate_workflow_context_budget": lambda *_args, **_kwargs: audits.pop(0),
        "ModelEndpointBehavior": lambda *_args, **_kwargs: SimpleNamespace(
            response_length_parameter="max_tokens"
        ),
        "bind_callable_with_timeout": lambda *_args, **_kwargs: summary_client.chat.completions.create,
        "AUXILIARY_MODEL_CALL_TIMEOUT_SECONDS": 10,
        "_create_chat_completion_with_reasoning": lambda *_args, **_kwargs: (object(), {}),
        "extract_chat_completion_response_text": lambda _response: "Compact prior context.",
    }
    exec(
        compile(ast.Module(body=[helper], type_ignores=[]), str(source_path), "exec"),
        namespace,
    )
    messages = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Second question"},
        {"role": "assistant", "content": "Second answer"},
        {"role": "user", "content": "Latest question"},
    ]
    fitted = namespace["_fit_direct_chat_persona_context"](
        messages,
        client=summary_client,
        model_name="chat-model",
        provider="aoai",
        output_tokens=300,
    )
    assert len(fitted) < len(messages)
    assert "Compact prior context." in fitted[0]["content"]
    assert fitted[-1]["content"] == "Latest question"
