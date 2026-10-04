# test_model_endpoint_protocol_inference.py
#!/usr/bin/env python3
"""
Functional test for model endpoint protocol inference.
Version: 0.261.046
Implemented in: 0.241.179; schema-v2 resolver in 0.261.041; live route adapters in 0.261.044
Capability, async transport, and cancellation coverage added in: 0.261.046

This test ensures that Foundry model endpoint runtime calls infer Claude as
Anthropic messages, OpenAI-compatible Foundry endpoints as /openai/v1, and
legacy Azure OpenAI endpoints as Azure OpenAI without making network calls. It
also verifies dated preview API versions are preserved for OpenAI-compatible
Foundry requests and the Semantic Kernel agent adapter can build Claude request
payloads without using the Azure OpenAI connector.
"""

import sys
import asyncio
import threading
import ast
import httpx
import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import quote
from openai import AzureOpenAI
import pytest


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

from model_endpoint_clients import (  # noqa: E402
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    AnthropicChatCompletionClient,
    AnthropicSemanticKernelChatCompletion,
    SanitizedCustomChatCompletionClient,
    build_anthropic_chat_client,
    build_openai_style_chat_client,
    bind_model_endpoint_request_policy,
    extract_chat_completion_response_text,
    infer_model_endpoint_protocol,
    ModelEndpointBehavior,
    normalize_anthropic_messages_url,
    normalize_chat_completion_text,
    normalize_openai_style_base_url,
    resolve_openai_style_request_api_version,
)
from functions_model_endpoint_auth import (  # noqa: E402
    normalize_custom_endpoint_auth_type,
    resolve_client_certificate,
    resolve_custom_endpoint_credentials,
)
from functions_model_endpoint_providers import get_model_endpoint_provider  # noqa: E402
from functions_model_endpoint_validation import ModelEndpointValidationError  # noqa: E402
from test_custom_model_endpoint_provider import load_model_endpoint_runtime_module, _restore_modules  # noqa: E402
from functions_model_endpoint_types import get_model_endpoint_api_type, resolve_model_endpoint_request_model  # noqa: E402
from functions_model_endpoint_urls import (  # noqa: E402
    build_model_endpoint_routing_context,
    resolve_model_endpoint_route,
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
        ModelEndpointBehavior("aoai", "gpt-5.6-luna").response_length_parameter,
        "max_completion_tokens",
        "GPT-5 models should use max_completion_tokens for response length",
    )
    assert_equal(
        ModelEndpointBehavior("aoai", "N-gpt-5.6-terra").response_length_parameter,
        "max_completion_tokens",
        "GPT-5 aliases embedded in deployment names should use max_completion_tokens",
    )
    assert_equal(
        ModelEndpointBehavior("aoai", "luna-deployment GPT 5.6 Luna").response_length_parameter,
        "max_completion_tokens",
        "GPT-5 aliases from model display names should use max_completion_tokens",
    )
    assert_equal(
        ModelEndpointBehavior("aoai", "o4-mini").response_length_parameter,
        "max_completion_tokens",
        "o-series models should use max_completion_tokens for response length",
    )
    assert_equal(
        ModelEndpointBehavior("aoai", "gpt-4o").response_length_parameter,
        "max_tokens",
        "Non-reasoning chat models should use max_tokens for response length",
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


def _routing_fixture(api_type="openai", path="", mode="auto", base="https://gateway.example"):
    return {
        "id": "gateway", "name": "Gateway", "provider": "custom",
        "routing_schema_version": 2, "enabled": True,
        "connection": {"endpoint": base},
        "auth": {"type": "api_key", "api_key": "test-secret", "api_key_header": "Ocp-Apim-Subscription-Key", "api_key_prefix": ""},
        "models": [{
            "id": "model", "api_type": api_type, "api_path": path, "url_mode": mode,
            "modelName": "claude-on-openai", "deploymentName": "D", "enabled": True,
            "api_version": "2025-01-01-preview", "anthropic_version": "2023-06-01",
        }],
    }


def _expect_routing_error(operation, *args, **kwargs):
    try:
        operation(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError("Invalid routing input was accepted.")


def test_schema_v2_url_matrix():
    routing = importlib.import_module("functions_model_endpoint_urls")
    cases = [
        ("openai", "aoai-global-team", "auto", "", "/aoai-global-team/v1/chat/completions"),
        ("openai", "aoai-global-team/v1", "auto", "", "/aoai-global-team/v1/chat/completions"),
        ("openai", "aoai-global-team/openai/v1", "auto", "", "/aoai-global-team/openai/v1/chat/completions"),
        ("openai", "aoai-global-team", "exact", "", "/aoai-global-team/chat/completions"),
        ("azure_openai_v1", "team", "auto", "", "/team/openai/v1/chat/completions"),
        ("azure_openai_v1", "team/openai/v1", "auto", "", "/team/openai/v1/chat/completions"),
        ("azure_openai_v1", "team/v1", "auto", "", "/team/v1/openai/v1/chat/completions"),
        ("azure_openai_v1", "team", "exact", "", "/team/chat/completions"),
        ("azure_openai_v1", "team", "auto", "/openai/v1", "/team/openai/v1/chat/completions"),
        ("azure_openai_v1", "team", "auto", "/openai", "/team/openai/v1/chat/completions"),
        ("anthropic", "aoai-global-team", "auto", "", "/aoai-global-team/v1/messages"),
        ("anthropic", "aoai-global-team/v2", "auto", "", "/aoai-global-team/v2/messages"),
        ("anthropic", "aoai-global-team/anthropic/v1", "auto", "", "/aoai-global-team/anthropic/v1/messages"),
        ("anthropic", "team", "exact", "", "/team/messages"),
        ("azure_openai", "aoai-global-team", "auto", "", "/aoai-global-team/openai/deployments/D/chat/completions?api-version=2025-01-01-preview"),
        ("azure_openai", "aoai-global-team/v1", "auto", "", "/aoai-global-team/v1/openai/deployments/D/chat/completions?api-version=2025-01-01-preview"),
        ("azure_openai", "team/openai/deployments/D", "exact", "", "/team/openai/deployments/D/chat/completions?api-version=2025-01-01-preview"),
        ("azure_openai", "team", "auto", "/openai", "/team/openai/deployments/D/chat/completions?api-version=2025-01-01-preview"),
        ("openai", "team", "auto", "/openai/v1", "/team/openai/v1/chat/completions"),
        ("openai", " /team/sub/ ", "auto", "/shared", "/team/sub/shared/v1/chat/completions"),
        ("openai", "models/team", "auto", "/shared/models-prefix", "/models/team/shared/models-prefix/v1/chat/completions"),
        ("openai", "team", "auto", "/team", "/team/team/v1/chat/completions"),
        ("gemini", "team", "auto", "/v1beta/openai", "/team/v1beta/openai/chat/completions"),
    ]
    for api_type, suffix, mode, endpoint_path, expected in cases:
        endpoint = _routing_fixture(api_type, suffix, mode, "https://gateway.example" + endpoint_path)
        original = copy.deepcopy(endpoint)
        route = routing.resolve_model_endpoint_route(endpoint, endpoint["models"][0])
        assert_equal(route["operation_url"], "https://gateway.example" + expected, str((api_type, suffix, mode)))
        assert endpoint == original
        assert "test-secret" not in json.dumps(route)
        assert route["credential_policy"]["header"] == "Ocp-Apim-Subscription-Key"
        assert route["credential_policy"]["prefix"] == ""
        if api_type == "azure_openai_v1":
            assert route["protocol"] == "openai_style"
            assert route["request_model"] == "claude-on-openai"
            assert route["api_version"] == ""
    endpoint = _routing_fixture("azure_openai", "team", "auto", "https://gateway.example:8443/openai")
    endpoint["models"][0]["deploymentName"] = "my deployment"
    route = routing.resolve_model_endpoint_route(endpoint, endpoint["models"][0])
    assert ":8443/team/openai/deployments/my%20deployment/" in route["operation_url"]


def test_schema_v2_rejects_unsafe_and_deferred_routes():
    routing = importlib.import_module("functions_model_endpoint_urls")
    bad_paths = [
        "//evil.example", "https://evil.example", "team?key=value", "team#fragment",
        "team\\next", "team//next", "../team", "team/./next", "team/../next",
        "team/%2e%2e", "team/%2fnext", "team/%5cnext", "team/%252e%252e",
        "team/%252f", "team/%", "team/%zz", "team/%00", "team\x00", "team\n",
        "team\t", "user@host", "team;parameter", "team///", "///team",
    ]
    for suffix in bad_paths:
        endpoint = _routing_fixture(path=suffix)
        _expect_routing_error(routing.resolve_model_endpoint_route, endpoint, endpoint["models"][0])
    for base in ("https://user:secret@gateway.example", "https://gateway.example/?secret=1", "https://gateway.example/#part", "https://gateway.example/a//b", "https://gateway.example/%252f", "https://gateway.example/../x", "https://gateway.example\\evil", "ftp://gateway.example"):
        endpoint = _routing_fixture(base=base)
        _expect_routing_error(routing.resolve_model_endpoint_route, endpoint, endpoint["models"][0])
    for field, value in (("api_type", "responses"), ("api_type", "custom_call"), ("api_type", ""), ("url_mode", "inherit"), ("url_mode", ""), ("modelName", "")):
        endpoint = _routing_fixture()
        endpoint["models"][0][field] = value
        _expect_routing_error(routing.resolve_model_endpoint_route, endpoint, endpoint["models"][0])
    for api_type, path, mode in (("azure_openai", "team/openai/v1", "auto"), ("azure_openai", "team", "exact"), ("azure_openai", "team/openai/deployments/other", "exact"), ("azure_openai_v1", "team/openai/deployments/D", "auto"), ("openai", "team/chat/completions", "exact"), ("anthropic", "team/messages", "exact")):
        endpoint = _routing_fixture(api_type, path, mode)
        _expect_routing_error(routing.resolve_model_endpoint_route, endpoint, endpoint["models"][0])
    for path in ("team/openai/deployments/D/extra/other", "team/openai/deployments/D/openai/deployments/D"):
        endpoint = _routing_fixture("azure_openai", path)
        _expect_routing_error(routing.resolve_model_endpoint_route, endpoint, endpoint["models"][0])
    for field in ("request_template", "url_template", "custom_call", "response_id"):
        endpoint = _routing_fixture()
        endpoint["models"][0][field] = "not-supported"
        _expect_routing_error(routing.resolve_model_endpoint_route, endpoint, endpoint["models"][0])
    for identifier in ("../other", "a/b", "a?b", "a%2fb", "a\\b", "a#b", "a\r\nHost: evil"):
        endpoint = _routing_fixture("azure_openai")
        endpoint["models"][0]["deploymentName"] = identifier
        _expect_routing_error(routing.resolve_model_endpoint_route, endpoint, endpoint["models"][0])


def test_schema_v2_versions_capabilities_and_cache_identity():
    routing = importlib.import_module("functions_model_endpoint_urls")
    endpoint = _routing_fixture("anthropic")
    model = endpoint["models"][0]
    model["modelName"] = "gpt-on-messages"
    endpoint["capabilities"] = {"toolCalling": False, "processesImages": True, "structuredOutput": True}
    model["capabilities"] = {"toolCalling": True, "processesImages": True, "structuredOutput": True}
    route = routing.resolve_model_endpoint_route(endpoint, model)
    assert route["request_model"] == "gpt-on-messages"
    assert route["capabilities"]["toolCalling"] is False
    assert route["capabilities"]["processesImages"] is True
    assert route["capabilities"]["structuredOutput"] is False
    capabilities = importlib.import_module("functions_model_capabilities")
    effective = capabilities.resolve_model_capabilities(model, endpoint, use_model_routing=True)
    assert effective == route["capabilities"]
    _expect_routing_error(capabilities.resolve_model_capabilities, model, endpoint)
    key = routing.model_endpoint_route_cache_key(route, scope_type="group", scope_id="one", configuration_revision="r1")
    for changed_scope, revision in (("two", "r1"), ("one", "r2")):
        changed_key = routing.model_endpoint_route_cache_key(route, scope_type="group", scope_id=changed_scope, configuration_revision=revision)
        assert changed_key != key
    model["api_path"] = "different"
    changed_route = routing.resolve_model_endpoint_route(endpoint, model)
    changed_key = routing.model_endpoint_route_cache_key(changed_route, scope_type="group", scope_id="one", configuration_revision="r1")
    assert changed_key != key
    assert "test-secret" not in key
    endpoint = _routing_fixture("azure_openai")
    endpoint["api_type"] = "azure_openai"
    endpoint["connection"]["api_version"] = "2024-01-01"
    route = routing.resolve_model_endpoint_route(endpoint, endpoint["models"][0])
    assert route["api_version"] == "2025-01-01-preview"
    del endpoint["models"][0]["api_version"]
    route = routing.resolve_model_endpoint_route(endpoint, endpoint["models"][0])
    assert route["api_version"] == "2024-01-01"
    endpoint["api_type"] = "openai"
    _expect_routing_error(routing.resolve_model_endpoint_route, endpoint, endpoint["models"][0])


def test_non_custom_explicit_routing_preserves_provider_contract():
    routing = importlib.import_module("functions_model_endpoint_urls")
    cases = (
        ("aoai", "https://gateway.example/shared", "gpt-model", "/team/shared/openai/deployments/gpt-model/chat/completions?api-version=2024-01-01"),
        ("aoai", "https://gateway.example/shared", "claude-model", "/team/shared/v1/messages"),
        ("new_foundry", "https://resource.services.ai.azure.com/api/projects/project", "gpt-model", "/team/api/projects/project/openai/v1/chat/completions"),
        ("new_foundry", "https://resource.services.ai.azure.com/api/projects/project", "claude-model", "/team/anthropic/v1/messages"),
    )
    for provider, base, deployment, expected in cases:
        endpoint = _routing_fixture(base=base)
        endpoint["provider"] = provider
        endpoint["connection"]["api_version"] = "2024-01-01"
        endpoint["models"] = [{"id": "selected", "deploymentName": deployment, "api_path": "team"}]
        route = routing.resolve_model_endpoint_route(endpoint, endpoint["models"][0])
        origin = base.split("/", 3)[:3]
        assert route["operation_url"] == "/".join(origin) + expected
        normalized = routing.normalize_model_endpoint_routing(endpoint)
        repeated = routing.resolve_model_endpoint_route(normalized, normalized["models"][0])
        assert repeated == route


def test_schema_v2_adapters_send_exact_resolved_operation_urls():
    routing = importlib.import_module("functions_model_endpoint_urls")
    captured_requests = []

    def response_for_request(request):
        captured_requests.append(request)
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={
                "id": "msg-test", "type": "message", "role": "assistant",
                "model": "claude-as-messages", "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
            })
        return httpx.Response(200, json={
            "id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": "test-model", "choices": [{
                "index": 0, "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }],
        })

    openai_endpoint = _routing_fixture(
        "openai", "aoai-global-team", "auto", "https://gateway.example/shared/v1"
    )
    openai_route = routing.resolve_model_endpoint_route(
        openai_endpoint, openai_endpoint["models"][0]
    )
    openai_http_client = httpx.Client(transport=httpx.MockTransport(response_for_request))
    with patch(
        "model_endpoint_clients.build_custom_openai_sync_http_client",
        return_value=openai_http_client,
    ):
        openai_client = build_openai_style_chat_client(
            "test-key", openai_endpoint["connection"]["endpoint"],
            api_type="openai", direct_custom=True,
            resolved_base_url=openai_route["api_base"],
            request_url=openai_route["operation_url"],
            default_headers={"Ocp-Apim-Subscription-Key": "test-key"},
        )
        openai_client.chat.completions.create(
            model=openai_route["request_model"],
            messages=[{"role": "user", "content": "test"}],
        )
    openai_http_client.close()

    messages_endpoint = _routing_fixture(
        "anthropic", "gateway-v2", "auto", "https://gateway.example/shared/v1"
    )
    messages_endpoint["models"][0]["modelName"] = "claude-as-messages"
    messages_route = routing.resolve_model_endpoint_route(
        messages_endpoint, messages_endpoint["models"][0]
    )
    messages_http_client = httpx.Client(transport=httpx.MockTransport(response_for_request))
    with patch(
        "model_endpoint_clients.build_custom_openai_sync_http_client",
        return_value=messages_http_client,
    ):
        messages_client = build_anthropic_chat_client(
            endpoint=messages_endpoint["connection"]["endpoint"],
            api_key="test-key", direct_custom=True,
            operation_url=messages_route["operation_url"],
            extra_headers={"Ocp-Apim-Subscription-Key": "test-key"},
        )
        messages_client.chat.completions.create(
            model=messages_route["request_model"],
            messages=[{"role": "user", "content": "test"}],
            max_tokens=16,
        )

    azure_endpoint = _routing_fixture(
        "azure_openai", "aoai-global-team", "auto", "https://gateway.example/shared"
    )
    azure_route = routing.resolve_model_endpoint_route(
        azure_endpoint, azure_endpoint["models"][0]
    )
    azure_http_client = httpx.Client(transport=httpx.MockTransport(response_for_request))
    runtime_source = ast.parse(
        (APP_DIR / "functions_model_endpoint_runtime.py").read_text(encoding="utf-8")
    )
    sync_builder = next(
        node for node in runtime_source.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_model_endpoint_sync_chat_client"
    )
    azure_endpoint_builder = next(
        node for node in runtime_source.body
        if isinstance(node, ast.FunctionDef) and node.name == "_azure_endpoint_from_resolved_route"
    )
    from functions_model_endpoint_providers import (
        MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
        MODEL_ENDPOINT_PROVIDER_CUSTOM,
    )

    namespace = {
        "quote": quote,
        "build_model_endpoint_identity_headers": lambda *_args, **_kwargs: {},
        "MODEL_ENDPOINT_PROVIDER_CUSTOM": MODEL_ENDPOINT_PROVIDER_CUSTOM,
        "MODEL_ENDPOINT_PROTOCOL_ANTHROPIC": MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
        "MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI": MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
        "MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE": MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
        "DEFAULT_ANTHROPIC_VERSION": "2023-06-01",
        "routing_schema_version": importlib.import_module("functions_model_endpoint_urls").routing_schema_version,
        "normalize_custom_endpoint_auth_type": normalize_custom_endpoint_auth_type,
        "resolve_client_certificate": resolve_client_certificate,
        "resolve_custom_endpoint_credentials": resolve_custom_endpoint_credentials,
        "get_model_endpoint_provider": get_model_endpoint_provider,
        "validate_custom_model_endpoint_url": lambda endpoint, **_kwargs: endpoint,
        "infer_model_endpoint_protocol": infer_model_endpoint_protocol,
        "build_anthropic_chat_client": build_anthropic_chat_client,
        "build_openai_style_chat_client": build_openai_style_chat_client,
        "bind_model_endpoint_request_policy": bind_model_endpoint_request_policy,
        "AzureOpenAI": AzureOpenAI,
        "SanitizedCustomChatCompletionClient": SanitizedCustomChatCompletionClient,
        "build_custom_openai_sync_http_client": lambda **_kwargs: azure_http_client,
    }
    exec(compile(ast.Module(body=[azure_endpoint_builder, sync_builder], type_ignores=[]), "<sync-route-client>", "exec"), namespace)
    azure_client, protocol = namespace["build_model_endpoint_sync_chat_client"](
        auth_settings=azure_endpoint["auth"],
        provider=MODEL_ENDPOINT_PROVIDER_CUSTOM,
        endpoint=azure_endpoint["connection"]["endpoint"],
        api_version=azure_route["api_version"],
        deployment_name=azure_route["request_model"],
        api_type=MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
        url_mode=azure_route["url_mode"],
        settings={},
        endpoint_config=azure_endpoint,
        resolved_route=azure_route,
    )
    assert protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
    azure_client.chat.completions.create(
        model=azure_route["request_model"],
        messages=[{"role": "user", "content": "test"}],
    )

    bearer_endpoint = copy.deepcopy(azure_endpoint)
    bearer_endpoint["auth"] = {"type": "bearer", "bearer_token": "test-bearer"}
    bearer_client, _ = namespace["build_model_endpoint_sync_chat_client"](
        auth_settings=bearer_endpoint["auth"],
        provider=MODEL_ENDPOINT_PROVIDER_CUSTOM,
        endpoint=bearer_endpoint["connection"]["endpoint"],
        api_version=azure_route["api_version"],
        deployment_name=azure_route["request_model"],
        api_type=MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
        url_mode=azure_route["url_mode"],
        settings={},
        endpoint_config=bearer_endpoint,
        resolved_route=azure_route,
    )
    bearer_client.chat.completions.create(
        model=azure_route["request_model"],
        messages=[{"role": "user", "content": "test"}],
    )

    assert [str(request.url) for request in captured_requests] == [
        openai_route["operation_url"],
        messages_route["operation_url"],
        azure_route["operation_url"],
        azure_route["operation_url"],
    ]
    for request, expected_key in zip(captured_requests[:3], ("test-key", "test-key", "test-secret")):
        assert request.method == "POST"
        assert request.headers["Ocp-Apim-Subscription-Key"] == expected_key
    assert captured_requests[3].headers["Authorization"] == "Bearer test-bearer"
    assert "api-key" not in captured_requests[3].headers


@pytest.mark.parametrize("api_type", ("openai", "azure_openai_v1", "azure_openai", "anthropic"))
@pytest.mark.parametrize("request_changes", (
    {"tools": [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]},
    {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.com/image.png"}}]}]},
    {"messages": [{"role": "tool", "tool_call_id": "one", "content": "result"}]},
    {"response_format": {"type": "json_object"}},
    {"stream": True},
    {"model": "different-model"},
    {"extra_body": {"model": "different-model"}},
    {"extra_body": {"tools": [{"type": "function", "function": {"name": "lookup"}}]}},
))
def test_schema_v2_sync_request_policy_rejects_before_transport(api_type, request_changes):
    endpoint = _routing_fixture(api_type, "team")
    endpoint["capabilities"] = {"supportsStreaming": False}
    route = resolve_model_endpoint_route(endpoint, endpoint["models"][0])
    captured = []

    def handle_request(request):
        captured.append(request)
        if api_type == "anthropic":
            return httpx.Response(200, json={
                "id": "message", "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            })
        return httpx.Response(200, json={
            "id": "completion", "object": "chat.completion", "created": 1,
            "model": route["request_model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })

    runtime, originals = load_model_endpoint_runtime_module()
    try:
        with httpx.Client(transport=httpx.MockTransport(handle_request)) as transport:
            with patch.object(runtime, "validate_custom_model_endpoint_url", side_effect=lambda value, **_kwargs: value), patch.object(
                runtime, "build_custom_openai_sync_http_client", return_value=transport,
            ), patch("model_endpoint_clients.build_custom_openai_sync_http_client", return_value=transport):
                client, _protocol = runtime.build_model_endpoint_sync_chat_client(
                    endpoint["auth"], "custom", endpoint["connection"]["endpoint"], route["api_version"],
                    endpoint_config=endpoint, resolved_route=route,
                )
                with pytest.raises(ModelEndpointValidationError):
                    client.chat.completions.create(**{
                        "model": route["request_model"],
                        "messages": [{"role": "user", "content": "test"}],
                        **request_changes,
                    })
        assert captured == [], "A denied request must never reach the inference transport."
    finally:
        _restore_modules(originals)


@pytest.mark.parametrize("api_type", ("openai", "azure_openai_v1", "azure_openai", "anthropic"))
def test_schema_v2_async_services_enforce_request_policy(api_type):
    endpoint = _routing_fixture(api_type, "team")
    route = resolve_model_endpoint_route(endpoint, endpoint["models"][0])
    endpoint["_resolved_route"] = route
    captured = []

    def handle_request(request):
        captured.append(request)
        return httpx.Response(200, json={
            "id": "completion", "object": "chat.completion", "created": 1,
            "model": route["request_model"],
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })

    async def exercise(runtime):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle_request)) as transport:
            with patch.object(runtime, "validate_custom_model_endpoint_url", side_effect=lambda value, **_kwargs: value), patch.object(
                runtime, "build_custom_openai_async_http_client", return_value=transport,
            ):
                service, _protocol = runtime.build_semantic_kernel_chat_service_for_model(
                    route["request_model"], {}, model_context={"model_id": "model"},
                    resolved_model_endpoint=endpoint,
                )
                if api_type == "anthropic":
                    history = ChatHistory()
                    history.add_user_message("test")
                    settings = service.get_prompt_execution_settings_class()(response_format={"type": "json_object"})
                    with pytest.raises(ModelEndpointValidationError):
                        service._build_request_kwargs(history, settings, stream=False)
                else:
                    with pytest.raises(ModelEndpointValidationError):
                        await service.client.chat.completions.create(
                            model=route["request_model"], messages=[{"role": "user", "content": "test"}],
                            response_format={"type": "json_object"},
                        )
        assert captured == []

    runtime, originals = load_model_endpoint_runtime_module()
    try:
        asyncio.run(exercise(runtime))
    finally:
        _restore_modules(originals)


@pytest.mark.parametrize("stop_mode", ("complete", "early", "error"))
def test_messages_helper_closes_upstream_stream(stop_mode):
    service = AnthropicSemanticKernelChatCompletion(
        service_id="helper", deployment_name="model", endpoint="https://gateway.example/v1",
        api_key="test-key", direct_custom=True,
    )
    closed = []

    def chunks():
        try:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="first"))])
            if stop_mode == "error":
                raise RuntimeError("synthetic parser error")
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="second"))])
        finally:
            closed.append(True)

    upstream = chunks()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: upstream)))

    async def exercise():
        history = ChatHistory()
        history.add_user_message("test")
        settings = service.get_prompt_execution_settings_class()()
        stream = service._inner_get_streaming_chat_message_contents(history, settings)
        first = await anext(stream)
        assert first[0].content == "first"
        if stop_mode == "early":
            await stream.aclose()
        elif stop_mode == "error":
            with pytest.raises(RuntimeError, match="synthetic parser error"):
                await anext(stream)
        else:
            remainder = [batch async for batch in stream]
            assert remainder[0][0].content == "second"
        assert closed == [True], "The helper must release the provider stream before returning."

    try:
        with patch.object(AnthropicSemanticKernelChatCompletion, "_build_client", return_value=client):
            asyncio.run(exercise())
    finally:
        upstream.close()


def test_messages_helper_cancellation_does_not_close_running_generator():
    service = AnthropicSemanticKernelChatCompletion(
        service_id="helper", deployment_name="model", endpoint="https://gateway.example/v1",
        api_key="test-key", direct_custom=True,
    )
    release = threading.Event()
    completed = threading.Event()
    closed = threading.Event()

    async def exercise():
        loop = asyncio.get_running_loop()
        reading = asyncio.Event()

        def chunks():
            try:
                loop.call_soon_threadsafe(reading.set)
                release.wait(5)
                completed.set()
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="late"))])
            finally:
                closed.set()

        upstream = chunks()
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: upstream)))
        history = ChatHistory()
        history.add_user_message("test")
        with patch.object(AnthropicSemanticKernelChatCompletion, "_build_client", return_value=client):
            stream = service._inner_get_streaming_chat_message_contents(history, service.get_prompt_execution_settings_class()())
            pending = asyncio.create_task(anext(stream))
            try:
                await asyncio.wait_for(reading.wait(), timeout=5)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            finally:
                release.set()
                await asyncio.to_thread(completed.wait, 5)
            was_closed = await asyncio.to_thread(closed.wait, 5)
            assert was_closed, "Cancellation must release the stream when its in-flight read finishes."

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_messages_helper_cancellation_closes_late_created_stream():
    service = AnthropicSemanticKernelChatCompletion(
        service_id="helper", deployment_name="model", endpoint="https://gateway.example/v1",
        api_key="test-key", direct_custom=True,
    )
    release = threading.Event()
    closed = threading.Event()

    async def exercise():
        loop = asyncio.get_running_loop()
        opening = asyncio.Event()

        def create(**_kwargs):
            loop.call_soon_threadsafe(opening.set)
            release.wait(5)
            return SimpleNamespace(close=closed.set)

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        history = ChatHistory()
        history.add_user_message("test")
        with patch.object(AnthropicSemanticKernelChatCompletion, "_build_client", return_value=client):
            stream = service._inner_get_streaming_chat_message_contents(history, service.get_prompt_execution_settings_class()())
            pending = asyncio.create_task(anext(stream))
            try:
                await asyncio.wait_for(opening.wait(), timeout=5)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            finally:
                release.set()
            was_closed = await asyncio.to_thread(closed.wait, 5)
            assert was_closed, "An upstream stream returned after cancellation must be closed."

    try:
        asyncio.run(exercise())
    finally:
        release.set()


def test_messages_stream_can_close_before_first_chunk():
    closed = []

    class ResponseStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"type":"message_stop"}\n\n'

        def close(self):
            closed.append(True)

    response = httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=ResponseStream())
    transport = httpx.Client(transport=httpx.MockTransport(lambda _request: response))
    try:
        with patch("model_endpoint_clients.build_custom_openai_sync_http_client", return_value=transport):
            client = build_anthropic_chat_client(
                endpoint="https://gateway.example/v1", api_key="test-key", direct_custom=True,
            )
            stream = client.chat.completions.create(
                model="model", messages=[{"role": "user", "content": "test"}], stream=True,
            )
            stream.close()
        assert response.is_closed
        assert transport.is_closed
        assert closed == [True]
    finally:
        response.close()
        transport.close()


def test_schema_v2_request_policies_are_isolated_and_allow_declared_features():
    endpoint = _routing_fixture("openai", "team")
    capabilities = {"toolCalling": True, "processesImages": True, "structuredOutput": True}
    endpoint["capabilities"] = capabilities.copy()
    endpoint["models"][0]["capabilities"] = capabilities.copy()
    route = resolve_model_endpoint_route(endpoint, endpoint["models"][0])
    calls = []
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs))))
    bind_model_endpoint_request_policy(client, route)
    route["capabilities"]["toolCalling"] = False
    client.chat.completions.create(
        model=route["request_model"],
        messages=[{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.com/image.png"}}]}],
        tools=[{"type": "function", "function": {"name": "lookup"}}],
        response_format={"type": "json_object"}, stream=True,
    )
    assert len(calls) == 1
    restricted = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: calls.append(kwargs))))
    bind_model_endpoint_request_policy(restricted, route)
    with pytest.raises(ModelEndpointValidationError):
        restricted.chat.completions.create(
            model=route["request_model"], messages=[], tools=[{"type": "function", "function": {"name": "lookup"}}],
        )
    assert len(calls) == 1


def test_metadata_client_forwards_custom_transport_policy():
    source = ast.parse((APP_DIR / "functions_documents.py").read_text(encoding="utf-8"))
    node = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "_build_model_endpoint_client")
    calls = []

    def build_client(*_args, **kwargs):
        calls.append(kwargs)
        return "client", "openai_style"

    namespace = {"build_model_endpoint_sync_chat_client": build_client}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<metadata-transport>", "exec"), namespace)
    client = namespace["_build_model_endpoint_client"](
        {}, "custom", "https://gateway.example", "", "model",
        settings={"allow_insecure_custom_model_endpoints": True, "custom_model_endpoint_ca_bundle_path": "configured-ca.pem"},
    )
    assert client == "client"
    assert calls[0]["allow_insecure_custom_endpoints"] is True
    assert calls[0]["custom_endpoint_ca_bundle_path"] == "configured-ca.pem"


def test_schema_v2_helper_context_contains_only_saved_selection_identity():
    runtime_source = ast.parse(
        (APP_DIR / "functions_model_endpoint_runtime.py").read_text(encoding="utf-8")
    )
    context_builder = next(
        node for node in runtime_source.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_model_endpoint_context"
    )
    namespace = {"build_model_endpoint_routing_context": build_model_endpoint_routing_context}
    exec(compile(ast.Module(body=[context_builder], type_ignores=[]), "<helper-route-context>", "exec"), namespace)
    context = namespace["build_model_endpoint_context"](
        provider="custom",
        endpoint="https://gateway.example/private/path",
        auth={"api_key": "must-not-copy"},
        endpoint_id="endpoint-1",
        model_id="model-1",
        user_id="actor",
        active_group_ids=["untrusted-extra-group"],
        routing_schema_version=2,
        scope_type="group",
        scope_id="authorized-group",
    )
    assert context == {
        "routing_schema_version": 2,
        "scope_type": "group",
        "scope_id": "authorized-group",
        "endpoint_id": "endpoint-1",
        "model_id": "model-1",
        "user_id": "actor",
    }
    assert "must-not-copy" not in json.dumps(context)
    assert "gateway.example" not in json.dumps(context)


def test_schema_v2_background_resolution_rechecks_group_membership():
    runtime_source = ast.parse(
        (APP_DIR / "functions_model_endpoint_runtime.py").read_text(encoding="utf-8")
    )
    definitions = {
        node.name: node for node in runtime_source.body
        if isinstance(node, ast.FunctionDef)
    }
    required = {
        "resolve_authorized_model_endpoint_route",
        "resolve_model_endpoint_from_context",
        "_resolve_schema_v2_model_endpoint_context",
        "_append_model_endpoint_candidate",
    }
    assert required.issubset(definitions), "Authorized schema-v2 background resolution is missing."

    saved_endpoint = {
        "id": "endpoint-1", "name": "Verified gateway", "provider": "custom",
        "routing_schema_version": 2, "enabled": True,
        "connection": {"endpoint": "https://gateway.example/shared/v1"},
        "auth": {"type": "api_key", "key_vault_reference": "kv/ref"},
        "models": [{
            "id": "model-1", "enabled": True, "api_type": "openai",
            "api_path": "team", "url_mode": "auto", "modelName": "claude-as-openai",
        }],
    }
    policy = {
        "enable_multi_model_endpoints": True,
        "allow_group_custom_endpoints": True,
    }
    reads = []
    role_checks = []
    secret_scopes = []
    access = {"allowed": True}

    def assert_group_role(user_id, group_id, *, allowed_roles):
        role_checks.append((user_id, group_id, allowed_roles))
        if not access["allowed"]:
            raise PermissionError("Membership was revoked.")
        return "User"

    def read_group_endpoints(group_id):
        reads.append(group_id)
        return [copy.deepcopy(saved_endpoint)]

    def ensure_governance_access(feature, user_id, **kwargs):
        return None

    def hydrate_endpoint(endpoint, endpoint_id, *, scope, return_type):
        assert endpoint_id == "endpoint-1" and return_type == "value"
        secret_scopes.append(scope)
        hydrated = copy.deepcopy(endpoint)
        hydrated["auth"]["api_key"] = "server-secret"
        return hydrated

    group_module = SimpleNamespace(
        assert_group_role=assert_group_role,
        get_group_model_endpoints=read_group_endpoints,
    )
    governance_module = SimpleNamespace(ensure_governance_access=ensure_governance_access)
    keyvault_module = SimpleNamespace(
        SecretReturnType=SimpleNamespace(VALUE="value"),
        keyvault_model_endpoint_get_helper=hydrate_endpoint,
    )
    settings_module = SimpleNamespace(
        get_user_settings=lambda _user_id: {"settings": {}},
        normalize_model_endpoints=lambda endpoints: (endpoints, False),
    )
    namespace = {
        "build_model_endpoint_routing_context": build_model_endpoint_routing_context,
        "routing_schema_version": importlib.import_module("functions_model_endpoint_urls").routing_schema_version,
        "model_endpoint_route_cache_key": importlib.import_module("functions_model_endpoint_urls").model_endpoint_route_cache_key,
        "resolve_model_endpoint_route": resolve_model_endpoint_route,
        "validate_model_endpoint_routing": lambda endpoint, _settings, *, require_resolvable=False: [
            resolve_model_endpoint_route(endpoint, model) for model in endpoint["models"]
        ],
        "copy": copy, "json": json, "hashlib": __import__("hashlib"),
        "SecretReturnType": SimpleNamespace(VALUE="value"),
    }
    exec(compile(ast.Module(body=[definitions[name] for name in required], type_ignores=[]), "<background-route-resolution>", "exec"), namespace)
    context = {
        "routing_schema_version": 2, "scope_type": "group", "scope_id": "group-1",
        "endpoint_id": "endpoint-1", "model_id": "model-1", "user_id": "actor",
    }
    with patch.dict(sys.modules, {
        "functions_group": group_module,
        "functions_governance": governance_module,
        "functions_keyvault": keyvault_module,
        "functions_settings": settings_module,
    }):
        resolved = namespace["resolve_model_endpoint_from_context"](policy, context)
        assert resolved["_resolved_route"]["operation_url"] == (
            "https://gateway.example/team/shared/v1/chat/completions"
        )
        assert resolved["auth"]["api_key"] == "server-secret"
        assert resolved["_route_cache_key"]
        assert secret_scopes == ["group"]
        legacy_context = {
            key: value for key, value in context.items()
            if key not in ("routing_schema_version", "scope_type", "scope_id")
        }
        legacy_context["active_group_ids"] = ["group-1"]
        reads_before_legacy_context = len(reads)
        try:
            namespace["resolve_model_endpoint_from_context"](policy, legacy_context)
        except ValueError as exc:
            assert "explicit" in str(exc).lower()
        else:
            raise AssertionError("A schema-v2 record must not be reached through a legacy context.")
        assert len(reads) == reads_before_legacy_context + 1
        assert secret_scopes == ["group"], "Legacy selection must not hydrate schema-v2 endpoint secrets."
        access["allowed"] = False
        reads_before_revoked_context = len(reads)
        assert namespace["resolve_model_endpoint_from_context"](policy, legacy_context) is None
        assert len(reads) == reads_before_revoked_context, "Revoked group membership must stop before endpoint reads."
        try:
            namespace["resolve_model_endpoint_from_context"](policy, context)
        except PermissionError:
            pass
        else:
            raise AssertionError("Revoked group members must not resolve saved model endpoints.")
    assert reads == ["group-1", "group-1"]
    assert role_checks


def test_schema_v2_semantic_kernel_helper_uses_resolved_base_url():
    runtime, originals = load_model_endpoint_runtime_module()

    async def exercise():
        for api_type in ("openai", "azure_openai_v1", "azure_openai"):
            endpoint = _routing_fixture(api_type, "team", "auto", "https://gateway.example/shared")
            if api_type == "azure_openai":
                endpoint["auth"] = {"type": "bearer", "bearer_token": "test-bearer"}
            route = resolve_model_endpoint_route(endpoint, endpoint["models"][0])
            endpoint["_resolved_route"] = route
            captured = []

            def respond(request):
                captured.append(request)
                return httpx.Response(200, json={
                    "id": "completion", "object": "chat.completion", "created": 1,
                    "model": route["request_model"],
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                })

            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
                with patch.object(runtime, "validate_custom_model_endpoint_url", side_effect=lambda value, **_kwargs: value), patch.object(
                    runtime, "build_custom_openai_async_http_client", return_value=transport,
                ):
                    service, protocol = runtime.build_semantic_kernel_chat_service_for_model(
                        route["request_model"], {"enable_multi_model_endpoints": True},
                        model_context={"routing_schema_version": 2, "endpoint_id": "gateway", "model_id": "model"},
                        resolved_model_endpoint=endpoint,
                    )
                    response = await service.client.chat.completions.create(
                        model=route["request_model"], messages=[{"role": "user", "content": "test"}],
                    )
                    assert response.choices[0].message.content == "ok"
            assert protocol == route["protocol"]
            assert len(captured) == 1
            assert str(captured[0].url) == route["operation_url"]
            assert json.loads(captured[0].content)["model"] == route["request_model"]
            if api_type == "azure_openai":
                assert captured[0].headers["Authorization"] == "Bearer test-bearer"
                assert "api-key" not in captured[0].headers
            else:
                assert captured[0].headers["Ocp-Apim-Subscription-Key"] == "test-secret"

    try:
        asyncio.run(exercise())
    finally:
        _restore_modules(originals)


def test_schema_v2_metadata_extraction_uses_authorized_route():
    source = ast.parse((APP_DIR / "functions_documents.py").read_text(encoding="utf-8"))
    metadata_builder = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_metadata_extraction_client"
    )
    endpoint = _routing_fixture(
        "openai", "metadata-team", "auto", "https://gateway.example/shared/v1"
    )
    endpoint["id"] = "metadata-endpoint"
    endpoint["models"][0]["id"] = "metadata-model"
    route = importlib.import_module("functions_model_endpoint_urls").resolve_model_endpoint_route(
        endpoint, endpoint["models"][0]
    )
    settings = {
        "enable_multi_model_endpoints": True,
        "metadata_extraction_model_selection": {
            "endpoint_id": "metadata-endpoint", "model_id": "metadata-model", "provider": "custom",
        },
        "model_endpoints": [endpoint],
    }
    resolved_contexts = []
    client_calls = []

    def resolve_context(current_settings, context):
        assert current_settings is settings
        resolved_contexts.append(context)
        hydrated = copy.deepcopy(endpoint)
        hydrated["auth"]["api_key"] = "server-only"
        hydrated["_resolved_route"] = route
        return hydrated

    def build_client(*args, **kwargs):
        client_calls.append((args, kwargs))
        return "metadata-client"

    keyvault_calls = []
    namespace = {
        "_normalize_model_endpoint_selection": lambda selection: {
            "endpoint_id": selection.get("endpoint_id", ""),
            "model_id": selection.get("model_id", ""),
            "provider": selection.get("provider", ""),
        },
        "normalize_model_endpoints": lambda endpoints: (endpoints, False),
        "routing_schema_version": importlib.import_module("functions_model_endpoint_urls").routing_schema_version,
        "resolve_model_endpoint_from_context": resolve_context,
        "keyvault_model_endpoint_get_helper": lambda *args, **kwargs: keyvault_calls.append((args, kwargs)),
        "SecretReturnType": SimpleNamespace(VALUE="value"),
        "resolve_model_endpoint_request_model": resolve_model_endpoint_request_model,
        "get_model_endpoint_api_type": get_model_endpoint_api_type,
        "infer_model_endpoint_protocol": infer_model_endpoint_protocol,
        "MODEL_ENDPOINT_PROVIDER_ALLOWLIST": {"custom", "aoai", "aifoundry", "new_foundry", "anthropic", "claude"},
        "MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI": MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
        "_build_model_endpoint_client": build_client,
    }
    exec(compile(ast.Module(body=[metadata_builder], type_ignores=[]), "<metadata-route-builder>", "exec"), namespace)
    client, deployment = namespace["_resolve_metadata_extraction_client"](
        settings,
        identity_context={"user_id": "metadata-user"},
    )
    assert (client, deployment) == ("metadata-client", route["request_model"])
    assert resolved_contexts == [{
        "routing_schema_version": 2,
        "scope_type": "global",
        "scope_id": "global",
        "endpoint_id": "metadata-endpoint",
        "model_id": "metadata-model",
        "user_id": "metadata-user",
    }]
    assert client_calls[0][1]["resolved_route"] == route
    assert keyvault_calls == []


if __name__ == "__main__":
    results = []
    for test in (test_model_endpoint_protocol_inference, test_schema_v2_url_matrix, test_schema_v2_rejects_unsafe_and_deferred_routes, test_schema_v2_versions_capabilities_and_cache_identity, test_non_custom_explicit_routing_preserves_provider_contract, test_schema_v2_adapters_send_exact_resolved_operation_urls, test_schema_v2_helper_context_contains_only_saved_selection_identity, test_schema_v2_background_resolution_rechecks_group_membership, test_schema_v2_semantic_kernel_helper_uses_resolved_base_url, test_schema_v2_metadata_extraction_uses_authorized_route):
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            results.append(False)
    raise SystemExit(0 if all(results) else 1)