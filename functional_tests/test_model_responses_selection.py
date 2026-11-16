# test_model_responses_selection.py
"""Functional tests for explicit Responses selection and canonical endpoint storage.

Version: 0.261.389
Implemented in: 0.261.389

Real settings owners, SDKs and workflow factories run with external I/O blocked.
Gateway API bases and authentication headers are preserved.
"""

from pathlib import Path
import sys

import pytest

from test_orchestration_result_imports import run_probe

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_model_endpoint_validation import (
    ModelEndpointValidationError,
    model_endpoint_inference_api,
    normalize_model_inference_connection,
    validate_model_endpoint_api_version,
)
from functions_model_endpoint_urls import resolve_model_inference_endpoint
from model_endpoint_clients import infer_model_endpoint_protocol, normalize_openai_style_base_url


@pytest.mark.parametrize("operation,enabled", [("responses", True), ("chat/completions", False)])
@pytest.mark.parametrize("prefix", ["/openai/v1", "/tenant/gateway/models/proxy"])
def test_operation_url_is_stored_as_a_base_and_explicit_choice(operation, enabled, prefix):
    original = {"endpoint": f"https://gateway.test{prefix}/{operation}", "use_responses_api": not enabled}
    normalized = normalize_model_inference_connection(original)
    assert normalized == {"endpoint": f"https://gateway.test{prefix}", "use_responses_api": enabled}
    assert original["endpoint"].endswith(operation)
    again = normalize_model_inference_connection(normalized)
    assert again == normalized


@pytest.mark.parametrize("endpoint,expected", [
    ("https://resource.openai.azure.com", "https://resource.openai.azure.com/openai/v1/responses"),
    ("https://resource.openai.azure.com/openai", "https://resource.openai.azure.com/openai/v1/responses"),
    ("https://gateway.test/tenant/openai/v1", "https://gateway.test/tenant/openai/v1/responses"),
    ("https://gateway.test/tenant/models/proxy", "https://gateway.test/tenant/models/proxy/responses"),
])
def test_explicit_responses_choice_materializes_only_the_needed_operation(endpoint, expected):
    actual = resolve_model_inference_endpoint(endpoint, use_responses_api=True)
    assert actual == expected
    assert normalize_openai_style_base_url(actual) == expected[:-len("responses")]
    assert resolve_model_inference_endpoint(actual, use_responses_api=True) == actual
    assert model_endpoint_inference_api(endpoint, True) == "responses"
    assert model_endpoint_inference_api(endpoint, False) == "chat_completions"
    assert infer_model_endpoint_protocol("aoai", endpoint, use_responses_api=True) == "openai_style"
    validate_model_endpoint_api_version("aoai", endpoint, "v1", use_responses_api=True)


@pytest.mark.parametrize("value", [None, "false", "true", 0, 1, [], {}])
def test_api_choice_requires_a_real_boolean(value):
    with pytest.raises(ModelEndpointValidationError, match="true or false"):
        normalize_model_inference_connection({"endpoint": "https://gateway.test", "use_responses_api": value})


@pytest.mark.parametrize("provider,api_type", [("anthropic", ""), ("custom", "gemini"), ("custom", "azure_openai")])
def test_unsupported_contract_does_not_silently_accept_responses(provider, api_type):
    with pytest.raises(ModelEndpointValidationError):
        validate_model_endpoint_api_version(provider, "https://gateway.test", "", api_type, use_responses_api=True)


def test_custom_exact_base_and_old_full_operation_urls_stay_compatible():
    actual = resolve_model_inference_endpoint(
        "https://gateway.test/team/proxy", provider="custom", api_type="openai",
        url_mode="exact", use_responses_api=True,
    )
    assert actual == "https://gateway.test/team/proxy/responses"
    assert resolve_model_inference_endpoint(
        actual, provider="custom", api_type="openai", url_mode="exact", use_responses_api=True,
    ) == actual
    assert model_endpoint_inference_api(actual) == "responses"


def test_real_connection_agent_and_workflow_factories_keep_the_selected_api_and_gateway_auth():
    probe = r'''
import asyncio
from copy import deepcopy
from contextlib import ExitStack
import json
import socket
import sys
from unittest.mock import patch
import httpx
from openai import OpenAI, AsyncOpenAI
from semantic_kernel.connectors.ai.open_ai import AzureChatPromptExecutionSettings
from semantic_kernel.contents import ChatHistory
sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

def check(value, message):
    if not value:
        raise AssertionError(message)

with offline_app_imports() as environment:
    import functions_settings as settings_owner
    import functions_model_endpoint_runtime as runtime
    import model_endpoint_clients as clients
    import functions_workflow_runner as workflows
    from functions_workflow_context import workflow_context_budget_scope, wrap_workflow_model_client
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "response", "object": "response", "created_at": 0, "model": "alias",
            "status": "completed", "output": [{
                "id": "message", "type": "message", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "text": "ok", "annotations": []}],
            }],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        })
    def sync_http(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(respond))
    def sync_client(**kwargs):
        if "http_client" not in kwargs:
            kwargs["http_client"] = sync_http()
        return OpenAI(**kwargs)
    def async_client(**kwargs):
        if "http_client" not in kwargs:
            kwargs["http_client"] = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        return AsyncOpenAI(**kwargs)
    with ExitStack() as patches:
        patches.enter_context(patch.object(runtime, "OpenAI", side_effect=sync_client))
        patches.enter_context(patch.object(clients, "OpenAI", side_effect=sync_client))
        patches.enter_context(patch.object(runtime, "AsyncOpenAI", side_effect=async_client))
        patches.enter_context(patch.object(runtime, "build_custom_openai_sync_http_client", side_effect=sync_http))
        patches.enter_context(patch.object(socket, "getaddrinfo", return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 443)),
        ]))
        endpoint = {
            "id": "connection", "name": "Responses", "provider": "aoai", "enabled": True,
            "connection": {"endpoint": "https://resource.openai.azure.com/openai/v1/responses", "openai_api_version": "v1"},
            "auth": {"type": "api_key", "api_key": "offline-key"},
            "models": [{"id": "model", "deploymentName": "alias", "modelName": "gpt-5.6-sol", "enabled": True}],
        }
        normalized, changed = settings_owner.normalize_model_endpoints([endpoint])
        endpoint = normalized[0]
        check(changed and endpoint["connection"]["use_responses_api"] is True, "Save did not retain the API choice.")
        check(endpoint["connection"]["endpoint"].endswith("/openai/v1"), "Save retained an operation URL.")
        client, protocol = runtime.build_model_endpoint_sync_chat_client(
            endpoint["auth"], "aoai", endpoint["connection"]["endpoint"], "v1", "alias", endpoint_config=endpoint,
        )
        try:
            answer = client.chat.completions.create(model="alias", messages=[{"role": "user", "content": "Answer."}])
            check(answer.choices[0].message.content == "ok", "Named connection did not execute Responses.")
            with workflow_context_budget_scope({}):
                wrapped = wrap_workflow_model_client(client, endpoint["models"][0], "aoai", endpoint_metadata=endpoint)
                check(wrapped.model_metadata.protocol == "responses", "Workflow budget lost the selected API.")
        finally:
            client.close()
        gateway = deepcopy(endpoint)
        gateway.update(provider="custom", api_type="openai")
        gateway["connection"] = {"endpoint": "https://gateway.test/team/proxy", "url_mode": "exact", "use_responses_api": True}
        gateway["auth"] = {"type": "api_key", "api_key": "subscription-key", "api_key_header": "Ocp-Apim-Subscription-Key"}
        gateway["models"] = [{"id": "model", "modelName": "gpt-5.6-sol", "enabled": True}]
        client, protocol = runtime.build_model_endpoint_sync_chat_client(
            gateway["auth"], "custom", gateway["connection"]["endpoint"], "", "gpt-5.6-sol", endpoint_config=gateway,
        )
        try:
            answer = client.chat.completions.create(model="gpt-5.6-sol", messages=[{"role": "user", "content": "Answer."}])
        finally:
            client.close()
        check(requests[-1].url.path == "/team/proxy/responses", "Custom APIM base was rewritten.")
        check(requests[-1].headers["Ocp-Apim-Subscription-Key"] == "subscription-key", "Custom APIM subscription header changed.")
        check(not requests[-1].headers.get("Authorization"), "APIM subscription key became a Bearer token.")
        async def local_agent():
            service, protocol = runtime.build_semantic_kernel_chat_service_for_model(
                "alias", {}, resolved_model_endpoint=endpoint,
            )
            try:
                history = ChatHistory()
                history.add_user_message("Answer.")
                answer = await service.get_chat_message_contents(history, AzureChatPromptExecutionSettings())
                check(answer[0].content == "ok" and service.inference_api == "responses", "Local agent lost Responses selection.")
            finally:
                await service.client.close()
        environment.loop.run_until_complete(local_agent())
        legacy = {
            "enable_gpt_apim": True, "azure_apim_gpt_endpoint": "https://gateway.test/team/models/proxy",
            "azure_apim_gpt_use_responses_api": True, "azure_apim_gpt_subscription_key": "gateway-key",
            "azure_apim_gpt_deployment": "alias", "azure_apim_gpt_api_version": "v1",
        }
        client = runtime.build_legacy_chat_client(legacy, "alias", use_apim=True)
        try:
            answer = client.chat.completions.create(model="alias", messages=[{"role": "user", "content": "Answer."}])
        finally:
            client.close()
        check(requests[-1].url.path == "/team/models/proxy/responses", "APIM prefix was rewritten.")
        check(requests[-1].headers["api-key"] == "gateway-key", "Legacy APIM authentication changed.")
        check(not requests[-1].headers.get("Authorization"), "Gateway key was duplicated into Bearer authentication.")
        client, deployment, provider = workflows._build_legacy_default_client(legacy)
        try:
            answer = client.chat.completions.create(model=deployment, messages=[{"role": "user", "content": "Answer."}])
        finally:
            client.close()
        check(requests[-1].url.path == "/team/models/proxy/responses", "Workflow legacy fallback lost Responses.")
        check(all(not request.url.query for request in requests), "Responses emitted a dated API query.")
    check(not environment.network_attempts, "Responses selection attempted external network I/O.")
print("PASS: saved selection, local agents, chat/APIM clients and workflow fallback execute Responses")
'''
    run_probe(probe, (), False)
