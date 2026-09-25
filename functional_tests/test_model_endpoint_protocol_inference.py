# test_model_endpoint_protocol_inference.py
#!/usr/bin/env python3
"""
Functional test for model endpoint protocol inference.
Version: 0.261.041
Implemented in: 0.241.179; schema-v2 resolver in 0.261.041

This test ensures that Foundry model endpoint runtime calls infer Claude as
Anthropic messages, OpenAI-compatible Foundry endpoints as /openai/v1, and
legacy Azure OpenAI endpoints as Azure OpenAI without making network calls. It
also verifies dated preview API versions are preserved for OpenAI-compatible
Foundry requests and the Semantic Kernel agent adapter can build Claude request
payloads without using the Azure OpenAI connector.
"""

import sys
import copy
import importlib
import json
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
    ModelEndpointBehavior,
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


if __name__ == "__main__":
    results = []
    for test in (test_model_endpoint_protocol_inference, test_schema_v2_url_matrix, test_schema_v2_rejects_unsafe_and_deferred_routes, test_schema_v2_versions_capabilities_and_cache_identity, test_non_custom_explicit_routing_preserves_provider_contract):
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            results.append(False)
    raise SystemExit(0 if all(results) else 1)