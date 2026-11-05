# test_microsoft_mai_model_connections.py
"""
Functional tests for Microsoft MAI chat connections and gateway compatibility.
Version: 0.261.407
Implemented in: 0.261.407

Real sync/async SDKs and Semantic Kernel run against in-memory HTTP responses.
Fresh normal and optimized interpreters block external network access. No Azure
deployment, credential acquisition, or paid inference is performed.
"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import httpx
from openai import OpenAI
import pytest

from test_orchestration_result_imports import run_probe
from test_support.versioning import assert_app_version_at_least

# Standalone tests need the dependency-light application modules on the path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_model_capabilities import (
    get_model_catalog_capabilities,
    resolve_model_reasoning_effort,
    resolve_model_token_budget,
)
from functions_model_catalog import built_in_profiles
from functions_model_endpoint_validation import (
    ModelEndpointValidationError,
    is_native_foundry_endpoint,
    model_endpoint_inference_api,
    normalize_model_inference_connection,
    validate_custom_model_endpoint,
    validate_model_endpoint_api_version,
)
from model_endpoint_clients import (
    ModelEndpointBehavior,
    OpenAIStyleChatCompletionClient,
    bind_callable_with_timeout,
    infer_model_endpoint_protocol,
    normalize_openai_style_base_url,
    prepare_mai_chat_request,
    resolve_custom_openai_base_url,
    resolve_model_inference_endpoint,
)


@pytest.mark.parametrize("provider", ["aoai", "aifoundry", "new_foundry"])
@pytest.mark.parametrize("base", [
    "https://resource.services.ai.azure.com/mai/v1",
    "https://gateway.example/team/inference/mai/v1",
])
@pytest.mark.parametrize("suffix", ["", "/", "/chat/completions", "/models"])
def test_native_mai_base_survives_storage_and_protocol_resolution(provider, base, suffix):
    normalized = normalize_model_inference_connection({"endpoint": base + suffix})
    endpoint = normalized["endpoint"]
    validate_model_endpoint_api_version(provider, endpoint, "v1")
    protocol = infer_model_endpoint_protocol(provider, endpoint, "production-alias")
    resolved = normalize_openai_style_base_url(endpoint)
    assert protocol == "openai_style"
    assert resolved == base + "/"


@pytest.mark.parametrize("provider,api_type", [
    ("aoai", ""), ("custom", "openai"),
])
def test_native_mai_contract_cannot_be_changed_to_responses(provider, api_type):
    with pytest.raises(ModelEndpointValidationError, match="Chat Completions"):
        validate_model_endpoint_api_version(
            provider, "https://resource.services.ai.azure.com/mai/v1", "v1",
            api_type, use_responses_api=True,
        )


def test_mai_catalog_has_verified_text_reasoning_tools_and_generation_capacity():
    assert_app_version_at_least("0.261.407")
    model = {"modelName": "gateway-alias", "catalogModelId": "mai-thinking-1"}
    budget = resolve_model_token_budget(model, provider="new_foundry")
    capabilities = get_model_catalog_capabilities("MAI-Thinking-1")
    profile = next((profile for profile in built_in_profiles() if profile["id"] == "mai-thinking-1"), None)
    effort = resolve_model_reasoning_effort("MAI-Thinking-1", "high")
    assert capabilities is not None
    assert capabilities["processesText"] and capabilities["generatesText"]
    assert capabilities["reasoning"] and capabilities["toolCalling"] and capabilities["supportsStreaming"]
    assert not capabilities["processesImages"] and not capabilities["generatesImages"]
    assert not capabilities["structuredOutput"]
    assert profile is not None and profile["publisher"] == "microsoft"
    assert profile["chatCompletions"] is True
    assert profile["technical"]["foundryChatApi"] == "mai"
    assert budget.model_id == "mai-thinking-1"
    assert budget.context_window == 256000
    assert budget.input_limit is None
    assert budget.output_limit == 64000
    assert budget.output_accounting == "total_generation"
    assert effort["effective_effort"] is None
    assert ModelEndpointBehavior("new_foundry", "MAI-Thinking-1").response_length_parameter == "max_completion_tokens"


@pytest.mark.parametrize("provider", ["aifoundry", "new_foundry"])
@pytest.mark.parametrize("path", ["", "/api/projects/team", "/openai/v1", "/mai/v1"])
@pytest.mark.parametrize("model,api", [
    ("gpt-4o", "openai"),
    ("grok-4.7", "openai"),
    ("MAI-Thinking-1", "mai"),
    ({"deploymentName": "production-alias", "catalogModelId": "mai-thinking-1"}, "mai"),
    ({"deploymentName": "production-alias", "catalogModelId": "claude-sonnet-4-5-20250929"}, "anthropic"),
])
@pytest.mark.parametrize("responses", [False, True])
def test_one_native_foundry_connection_derives_each_models_contract(provider, path, model, api, responses):
    endpoint = "https://resource.services.ai.azure.com" + path
    before = deepcopy(model)
    validate_model_endpoint_api_version(provider, endpoint, "v1", use_responses_api=responses, model=model)
    resolved = resolve_model_inference_endpoint(endpoint, provider=provider, model=model, use_responses_api=responses)
    selected = model_endpoint_inference_api(endpoint, responses, provider=provider, model=model)
    if api == "mai":
        expected = "https://resource.services.ai.azure.com/mai/v1"
    elif api == "anthropic":
        expected = "https://resource.services.ai.azure.com/anthropic/v1/messages"
    else:
        project = "/api/projects/team" if path.startswith("/api/projects/") else ""
        expected = f"https://resource.services.ai.azure.com{project}/openai/v1"
        if responses:
            expected += "/responses"
    assert resolved == expected
    assert selected == ("responses" if api == "openai" and responses else "chat_completions")
    assert model == before


@pytest.mark.parametrize("provider", ["custom", "aoai", "new_foundry"])
def test_native_model_metadata_never_rewrites_a_gateway_authority_or_prefix(provider):
    endpoint = "https://gateway.example/team/proxy/mai/v1"
    resolved = resolve_model_inference_endpoint(
        endpoint, provider=provider, api_type="openai" if provider == "custom" else "",
        model={"catalogModelId": "mai-thinking-1"}, url_mode="exact", use_responses_api=False,
    )
    native = is_native_foundry_endpoint(provider, endpoint)
    assert resolved == endpoint
    assert native is False


@pytest.mark.parametrize("endpoint", [
    "https://resource.services.ai.azure.com.attacker.example/api/projects/team",
    "https://resource.example/?next=services.ai.azure.com",
])
def test_automatic_native_routing_does_not_follow_lookalike_hosts(endpoint):
    native = is_native_foundry_endpoint("new_foundry", endpoint)
    assert native is False


@pytest.mark.parametrize("endpoint", [
    "http://resource.services.ai.azure.com",
    "https://user:password@resource.services.ai.azure.com",
    "https://resource.services.ai.azure.com:8443/api/projects/team",
    "https://resource.services.ai.azure.com?query=1",
])
def test_native_routing_rejects_invalid_resource_urls(endpoint):
    with pytest.raises(ModelEndpointValidationError, match="native Foundry HTTPS"):
        resolve_model_inference_endpoint(endpoint, provider="new_foundry", model="MAI-Thinking-1")


def test_custom_mai_routes_keep_gateway_bases_and_do_not_gain_azure_authentication():
    base = resolve_custom_openai_base_url("https://gateway.example/team/mai/v1", "openai")
    exact = resolve_custom_openai_base_url("https://gateway.example/team/model-proxy", "openai", "exact")
    assert base == "https://gateway.example/team/mai/v1/"
    assert exact == "https://gateway.example/team/model-proxy/"
    assert infer_model_endpoint_protocol("aoai", "https://gateway.example/mai/v10") == "azure_openai"
    endpoint = {
        "id": "custom", "name": "MAI gateway", "provider": "custom", "api_type": "openai",
        "connection": {"endpoint": "https://gateway.example/mai/v1"},
        "auth": {"type": "managed_identity"}, "models": [],
    }
    with pytest.raises(ModelEndpointValidationError, match="authentication"):
        validate_custom_model_endpoint(endpoint, require_api_key=False)


@pytest.mark.parametrize("model_name", [
    "gpt-6.1-sol", "grok-4.7", "phi-4", "mai-image-2.6", "mai-ds-r1", "mai-thinking-10",
])
def test_mai_request_policy_does_not_change_other_models(model_name):
    parameters = {
        "model": model_name, "messages": [{"role": "user", "content": "Answer."}],
        "max_tokens": 128, "temperature": 0.2, "reasoning_effort": "high",
        "extra_body": {"top_p": 0.8},
    }
    original = deepcopy(parameters)
    prepared = prepare_mai_chat_request(parameters, model_name=model_name, endpoint="https://gateway.example/v1")
    assert prepared == original
    assert parameters == original


def test_mai_request_policy_preserves_extra_body_limits_without_mutating_the_caller():
    parameters = {
        "model": "gateway-alias", "max_tokens": 128,
        "extra_body": {"max_tokens": 64, "temperature": 0.3, "reasoning_effort": "high"},
    }
    original = deepcopy(parameters)
    prepared = prepare_mai_chat_request(parameters, model_name="mai-thinking-1")
    assert prepared["model"] == "gateway-alias"
    assert prepared["max_completion_tokens"] == 128
    assert prepared["extra_body"] == {"max_completion_tokens": 64}
    assert parameters == original


def test_auxiliary_timeout_binding_retains_mai_gateway_request_policy():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "mai", "object": "chat.completion", "created": 0, "model": "gateway-alias",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}],
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        sdk = OpenAI(api_key="offline-key", base_url="https://gateway.example/team/proxy/", http_client=http)
        client = OpenAIStyleChatCompletionClient(
            sdk, sanitize_errors=True, api_type="openai",
            request_url=str(sdk.base_url), model_name="mai-thinking-1",
        )
        create = bind_callable_with_timeout(client, client.chat.completions.create)
        result = create(
            model="gateway-alias", messages=[{"role": "user", "content": "Answer."}],
            max_tokens=128, temperature=0.2,
        )
        body = json.loads(requests[0].content)
        assert result.choices[0].message.content == "OK"
        assert requests[0].url.path == "/team/proxy/chat/completions"
        assert body["model"] == "gateway-alias"
        assert body["max_completion_tokens"] == 128
        assert "max_tokens" not in body and "temperature" not in body


RUNTIME_PROBE = r'''
from contextlib import ExitStack, closing
from copy import deepcopy
from itertools import product
import json
import socket
import sys
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from openai import AsyncOpenAI, OpenAI
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import AzureChatPromptExecutionSettings
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import kernel_function

sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

def check(condition, message):
    if not condition:
        raise AssertionError(message)

with offline_app_imports() as environment:
    import functions_settings as owner
    import functions_model_endpoint_runtime as runtime
    import model_endpoint_clients as clients
    import semantic_kernel_loader as loader
    import functions_tabular_generated_exports as tabular
    from functions_orchestration_model_capture import azure_chat_construction_metadata
    from functions_workflow_context import workflow_context_budget_scope, wrap_workflow_model_client
    requests = []
    token_scopes = []
    active = {}

    def respond(request):
        body = json.loads(request.content)
        requests.append((request, body))
        check(request.url.path == active["path"], "MAI or gateway API base was rewritten.")
        check(not request.url.query, "MAI chat received a dated api-version query.")
        check(body["model"] == active["request_model"], "The selected deployment/request model changed.")
        if active.get("mai", True):
            check(body.get("max_completion_tokens") == 2048, "The total-generation ceiling was not preserved.")
            for field in ("max_tokens", "temperature", "top_p", "reasoning_effort", "stream_options"):
                check(field not in body, "Undocumented MAI parameter was sent: " + field)
        check(request.headers.get(active["header"]) == active["credential"], "Connection authentication changed.")
        if active["header"].lower() != "authorization":
            check(not request.headers.get("Authorization"), "A subscription/resource key became a bearer token.")
        tools = body.get("tools") or []
        if request.url.path.endswith("/responses"):
            has_result = any(item.get("type") == "function_call_output" for item in body.get("input") or [])
            output = [{
                "id": "message", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "MAI_OK", "annotations": []}],
            }]
            if tools and not has_result:
                output = [{
                    "id": "fc_lookup", "type": "function_call", "status": "completed",
                    "call_id": "call_lookup", "name": tools[0]["name"], "arguments": "{}",
                }]
            return httpx.Response(200, json={
                "id": "response", "object": "response", "created_at": 0, "model": body["model"],
                "status": "completed", "output": output,
                "usage": {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            })
        has_result = any(message["role"] == "tool" for message in body["messages"])
        message = {"role": "assistant", "content": "MAI_OK"}
        if tools and not has_result:
            message.update(content=None, tool_calls=[{
                "id": "call_lookup", "type": "function",
                "function": {"name": tools[0]["function"]["name"], "arguments": "{}"},
            }])
        if body.get("stream"):
            delta = dict(message)
            if delta.get("tool_calls"):
                delta["tool_calls"][0]["index"] = 0
            chunks = [
                {"id": "mai", "object": "chat.completion.chunk", "created": 0,
                 "model": body["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                {"id": "mai", "object": "chat.completion.chunk", "created": 0,
                 "model": body["model"], "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}},
            ]
            events = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
            return httpx.Response(200, text=events, headers={"Content-Type": "text/event-stream"})
        return httpx.Response(200, json={
            "id": "mai", "object": "chat.completion", "created": 0, "model": body["model"],
            "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
        })

    def sync_http(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(respond))

    def async_http(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))

    def sync_client(**kwargs):
        if "http_client" not in kwargs:
            kwargs["http_client"] = sync_http()
        return OpenAI(**kwargs)

    def async_client(**kwargs):
        if "http_client" not in kwargs:
            kwargs["http_client"] = async_http()
        return AsyncOpenAI(**kwargs)

    def get_token(scope):
        token_scopes.append(scope)
        return SimpleNamespace(token="offline-entra-token")

    class Tools:
        def __init__(self):
            self.calls = 0

        @kernel_function(name="lookup", description="Look up the in-memory status.")
        def lookup(self) -> str:
            self.calls += 1
            return "available"

    async def exercise_service(endpoint, stream, local_agent=False):
        selected_model = next(
            model for model in endpoint["models"] if model["id"] == active.get("model_id", "model")
        )
        if local_agent:
            config = {
                "model_provider": endpoint["provider"],
                "endpoint": endpoint["connection"]["endpoint"],
                "deployment": active["request_model"], "api_version": "v1",
                "api_type": endpoint.get("api_type"), "auth": endpoint["auth"],
                "model_endpoint_config": endpoint, "model_budget_model": selected_model,
                "model_budget_endpoint": endpoint, "model_id": selected_model["id"],
                "use_responses_api": endpoint["connection"].get("use_responses_api"),
                "key": endpoint["auth"].get("api_key", ""),
                "token_provider": (lambda: "offline-entra-token") if endpoint["auth"]["type"] == "managed_identity" else None,
            }
            service = loader.create_model_endpoint_chat_completion_service(config, "mai-agent", {})
            protocol = loader.resolve_agent_endpoint_protocol(config)
        else:
            service, protocol = runtime.build_semantic_kernel_chat_service_for_model(
                active["request_model"], {}, resolved_model_endpoint=endpoint,
                model_context={"model_id": selected_model["id"]},
            )
        tools = Tools()
        kernel = Kernel()
        kernel.add_plugin(tools, plugin_name="probe")
        history = ChatHistory()
        history.add_user_message("Look up the status and answer.")
        settings_options = dict(
            max_tokens=2048, temperature=0.2, top_p=0.8,
            function_choice_behavior=FunctionChoiceBehavior.Auto(),
        )
        if active.get("mai", True):
            settings_options["reasoning_effort"] = "high"
        settings = AzureChatPromptExecutionSettings(**settings_options)
        try:
            check(protocol == "openai_style", "MAI agent used the dated Azure transport.")
            if endpoint["provider"] != "custom":
                observed = azure_chat_construction_metadata(
                    service, protocol=protocol, provider=endpoint["provider"],
                    configured_endpoint=endpoint["connection"]["endpoint"], configured_api_version="v1",
                    use_responses_api=endpoint["connection"].get("use_responses_api"),
                )
                check(observed is not None, "Capture rejected the selected native model's effective route.")
                check(service.model_token_budget.protocol == active.get("inference_api", "chat_completions"),
                      "The native model budget inherited an incompatible connection-wide API preference.")
            if stream:
                text = ""
                async for messages in service.get_streaming_chat_message_contents(history, settings, kernel=kernel):
                    text += "".join(message.content or "" for message in messages)
            else:
                messages = await service.get_chat_message_contents(history, settings, kernel=kernel)
                text = messages[0].content
            check(text == "MAI_OK", "MAI tool continuation did not produce the final answer.")
            check(tools.calls == 1, "MAI tool calls with finish_reason stop were not executed exactly once.")
        finally:
            await service.client.close()

    with ExitStack() as patches:
        patches.enter_context(patch.object(runtime, "OpenAI", side_effect=sync_client))
        patches.enter_context(patch.object(clients, "OpenAI", side_effect=sync_client))
        patches.enter_context(patch.object(runtime, "AsyncOpenAI", side_effect=async_client))
        patches.enter_context(patch.object(loader, "AsyncOpenAI", side_effect=async_client))
        patches.enter_context(patch.object(runtime, "build_custom_openai_sync_http_client", side_effect=sync_http))
        patches.enter_context(patch.object(runtime, "build_custom_openai_async_http_client", side_effect=async_http))
        patches.enter_context(patch.object(
            runtime, "resolve_credential_for_model_endpoint_auth",
            return_value=SimpleNamespace(get_token=get_token),
        ))
        patches.enter_context(patch.object(socket, "getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
        ]))
        cases = [*product(("aoai", "aifoundry", "new_foundry"), ("managed_identity", "api_key")),
                 ("custom", "api_key"), ("custom", "bearer")]
        for provider, auth_type in cases:
            custom = provider == "custom"
            auth = {"type": auth_type}
            if auth_type == "managed_identity":
                header, credential = "Authorization", "Bearer offline-entra-token"
            elif auth_type == "bearer":
                auth["bearer_token"] = "offline-gateway-token"
                header, credential = "Authorization", "Bearer offline-gateway-token"
            else:
                auth["api_key"] = "offline-resource-key"
                header, credential = "api-key", "offline-resource-key"
                if custom:
                    auth["api_key_header"] = header = "Ocp-Apim-Subscription-Key"
                    auth["api_key_prefix"] = ""
            endpoint = {
                "id": "connection", "name": "MAI", "provider": provider, "enabled": True,
                "connection": {
                    "endpoint": "https://gateway.example/team/model-proxy" if custom else
                                "https://resource.services.ai.azure.com/mai/v1/chat/completions",
                    "openai_api_version": "v1", "url_mode": "exact",
                },
                "auth": auth,
                "models": [{
                    "id": "model", "deploymentName": "production-mai", "modelName": "gateway-mai" if custom else "MAI-Thinking-1",
                    "catalogModelId": "mai-thinking-1", "responseLength": 2048, "enabled": True,
                }],
            }
            if custom:
                endpoint["api_type"] = "openai"
            normalized, _ = owner.normalize_model_endpoints([endpoint])
            endpoint = normalized[0]
            scopes = [
                ({}, "https://resource.services.ai.azure.com/mai/v1", "https://cognitiveservices.azure.com/.default"),
                ({"foundry_scope": "https://explicit.example/.default"}, "https://resource.services.ai.azure.com/mai/v1",
                 "https://explicit.example/.default"),
                ({}, "https://resource.services.ai.azure.com/openai/v1", "https://ai.azure.com/.default"),
                ({}, "https://gateway.example/mai/v1", "https://ai.azure.com/.default"),
                ({}, "https://resource.services.ai.azure.com.attacker.example/mai/v1", "https://ai.azure.com/.default"),
            ]
            for auth_config, address, expected in scopes:
                scope = owner.resolve_model_endpoint_foundry_scope(auth_config, address)
                check(scope == expected, "MAI scope inference changed an explicit audience or an unrelated endpoint.")
            saved = deepcopy(endpoint)
            active.update(
                path="/team/model-proxy/chat/completions" if custom else "/mai/v1/chat/completions",
                request_model="gateway-mai" if custom else "production-mai",
                header=header, credential=credential,
            )
            previous_tokens = len(token_scopes)
            for stream in (False, True):
                client, protocol = runtime.build_model_endpoint_sync_chat_client(
                    endpoint["auth"], provider, endpoint["connection"]["endpoint"], "v1",
                    active["request_model"], endpoint_config=endpoint, model_id="model",
                )
                try:
                    check(protocol == "openai_style", "MAI chat used the dated Azure transport.")
                    response = client.chat.completions.create(
                        model=active["request_model"], messages=[{"role": "user", "content": "Answer."}],
                        max_tokens=2048, temperature=0.2, top_p=0.8, reasoning_effort="high", stream=stream,
                    )
                    if stream:
                        with response:
                            text = "".join(chunk.choices[0].delta.content or "" for chunk in response)
                    else:
                        text = response.choices[0].message.content
                    check(text == "MAI_OK", "MAI chat/stream did not return the mock answer.")
                finally:
                    client.close()
                environment.loop.run_until_complete(exercise_service(endpoint, stream))
                environment.loop.run_until_complete(exercise_service(endpoint, stream, local_agent=True))
            if custom:
                check(len(token_scopes) == previous_tokens, "A Custom host acquired an Azure token.")
            elif auth_type == "managed_identity":
                check(token_scopes[previous_tokens:] == ["https://cognitiveservices.azure.com/.default"] * 4,
                      "Native MAI inference acquired a project token instead of a Cognitive Services token.")
            check(endpoint == saved, "MAI runtime mutated the saved connection.")
        for provider, responses, auth_type in product(
            ("aifoundry", "new_foundry"), (False, True), ("managed_identity", "api_key"),
        ):
            auth = {"type": auth_type}
            if auth_type == "api_key":
                auth["api_key"] = "offline-resource-key"
            shared = {
                "id": "shared", "name": "Mixed native models", "provider": provider, "enabled": True,
                "connection": {
                    "endpoint": "https://resource.services.ai.azure.com/api/projects/team",
                    "openai_api_version": "", "use_responses_api": responses,
                },
                "auth": auth,
                "models": [
                    {"id": "gpt", "deploymentName": "gpt-production", "modelName": "gpt-4o", "enabled": True},
                    {"id": "grok", "deploymentName": "grok-production", "modelName": "grok-4.7", "enabled": True},
                    {"id": "mai", "deploymentName": "mai-production", "catalogModelId": "mai-thinking-1", "enabled": True},
                ],
            }
            normalized, _ = owner.normalize_model_endpoints([shared])
            shared = normalized[0]
            before = deepcopy(shared)
            for model in shared["models"]:
                mai = model["id"] == "mai"
                api = "responses" if responses and not mai else "chat_completions"
                path = "/mai/v1/chat/completions" if mai else "/api/projects/team/openai/v1/" + (
                    "responses" if responses else "chat/completions"
                )
                header = "Authorization" if auth_type == "managed_identity" or not mai else "api-key"
                key = "offline-entra-token" if auth_type == "managed_identity" else "offline-resource-key"
                active.update(
                    model_id=model["id"], request_model=model["deploymentName"], path=path, mai=mai,
                    inference_api=api, header=header,
                    credential=("Bearer " + key) if header == "Authorization" else key,
                )
                with patch.object(tabular, "_resolve_tabular_budget_model_selection", return_value=(model, shared)):
                    limits = tabular._resolve_tabular_model_token_limits(
                        active["request_model"], {"enable_multi_model_endpoints": True},
                        model_context={
                            "provider": provider, "endpoint_id": shared["id"], "model_id": model["id"],
                            "model_deployment": active["request_model"],
                        },
                    )
                check(limits["model_token_budget"].protocol == api,
                      "Tabular evidence budgeting lost the selected native model's inference API.")
                previous_tokens = len(token_scopes)
                for stream in (False, True):
                    client, protocol = runtime.build_model_endpoint_sync_chat_client(
                        shared["auth"], provider, shared["connection"]["endpoint"], "",
                        active["request_model"], endpoint_config=shared, model_id=model["id"],
                    )
                    try:
                        with workflow_context_budget_scope({}):
                            wrapped = wrap_workflow_model_client(client, model, provider, endpoint_metadata=shared)
                            check(wrapped.model_metadata.protocol == api, "Workflow metadata lost the per-model API choice.")
                        response = client.chat.completions.create(
                            model=active["request_model"], messages=[{"role": "user", "content": "Answer."}],
                            max_tokens=2048, stream=stream,
                        )
                        if stream:
                            with closing(response):
                                text = "".join(chunk.choices[0].delta.content or "" for chunk in response)
                        else:
                            text = response.choices[0].message.content
                        check(text == "MAI_OK", "The mixed Foundry model did not execute its selected operation.")
                    finally:
                        client.close()
                    environment.loop.run_until_complete(exercise_service(shared, stream))
                    environment.loop.run_until_complete(exercise_service(shared, stream, local_agent=True))
                if auth_type == "managed_identity":
                    scope = "https://cognitiveservices.azure.com/.default" if mai else "https://ai.azure.com/.default"
                    check(token_scopes[previous_tokens:] == [scope] * 4, "Shared native authentication used the wrong model audience.")
                check(shared == before, "Per-model routing changed the saved project connection.")
    check(requests, "No real SDK requests were exercised.")
    check(not environment.network_attempts, "MAI construction/execution attempted external network I/O.")
print("PASS: MAI sync/streaming chat, native identity/key auth and Custom/SK tool continuation")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_real_mai_factories_preserve_auth_routes_and_tool_continuation(optimized):
    run_probe(RUNTIME_PROBE, (), optimized)
