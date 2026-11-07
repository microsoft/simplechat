# test_model_inference_api_versions.py
"""Functional tests for explicit inference protocols and dated API versions.

Version: 0.261.389
Implemented in: 0.261.388

Configuration checks are bootstrap-free and do not resolve DNS or call Azure.
"""

from pathlib import Path
import sys

import pytest

from test_orchestration_result_imports import run_probe

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_model_endpoint_validation import (
    ModelEndpointValidationError,
    endpoint_uses_openai_style_protocol,
    validate_custom_model_endpoints,
    validate_model_endpoint_api_version,
)
from model_endpoint_clients import infer_model_endpoint_protocol, resolve_openai_style_request_api_version


@pytest.mark.parametrize("provider", ["aoai", "aifoundry", "new_foundry"])
@pytest.mark.parametrize("version", ["v1", "preview", "latest"])
def test_resource_root_does_not_send_a_protocol_label_as_a_dated_version(provider, version):
    with pytest.raises(ModelEndpointValidationError, match="dated Azure API version"):
        validate_model_endpoint_api_version(provider, "https://resource.openai.azure.com", version)


@pytest.mark.parametrize("provider", ["aoai", "new_foundry"])
def test_explicit_v1_endpoint_uses_the_openai_client_without_version_query(provider):
    endpoint = "https://resource.openai.azure.com/openai/v1/"
    validate_model_endpoint_api_version(provider, endpoint, "v1")
    assert infer_model_endpoint_protocol(provider, endpoint, "gpt-5.6-sol") == "openai_style"
    assert resolve_openai_style_request_api_version("v1") == ""
    assert resolve_openai_style_request_api_version("2024-10-01-preview") == ""


def test_dated_legacy_connection_remains_valid_and_does_not_mutate():
    endpoint = {"provider": "aoai", "connection": {
        "endpoint": "https://resource.openai.azure.com",
        "openai_api_version": "2024-10-01-preview",
    }}
    validate_custom_model_endpoints([endpoint])
    assert endpoint["connection"]["openai_api_version"] == "2024-10-01-preview"
    assert infer_model_endpoint_protocol("aoai", endpoint["connection"]["endpoint"]) == "azure_openai"


def test_saved_global_group_and_personal_connections_share_version_validation():
    endpoint = {"provider": "aoai", "connection": {
        "endpoint": "https://resource.openai.azure.com", "openai_api_version": "v1",
    }}
    with pytest.raises(ModelEndpointValidationError):
        validate_custom_model_endpoints([endpoint])


def test_custom_azure_api_type_stays_explicitly_dated():
    with pytest.raises(ModelEndpointValidationError):
        validate_model_endpoint_api_version("custom", "https://gateway.test/openai/v1", "v1", "azure_openai")


def test_host_detection_does_not_read_an_unrelated_url_query_as_a_foundry_host():
    result = endpoint_uses_openai_style_protocol("https://gateway.test/?next=services.ai.azure.com")
    assert result is False


@pytest.mark.parametrize("use_apim", [False, True])
def test_legacy_global_settings_use_versionless_v1_sdk_requests(use_apim):
    probe = r'''
import asyncio
from itertools import product
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch
import httpx
from openai import AsyncOpenAI
from semantic_kernel.connectors.ai.open_ai import AzureChatPromptExecutionSettings
from semantic_kernel.contents import ChatHistory
sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports
from model_tool_chat_completion import OpenAIToolChatCompletion

with offline_app_imports() as environment:
    import functions_model_endpoint_runtime as runtime
    captured = []
    def respond(request):
        body = json.loads(request.content)
        captured.append((request, body))
        if request.url.path.endswith("/responses"):
            return httpx.Response(200, json={
                "id": "response", "object": "response", "created_at": 0, "model": "legacy-alias",
                "status": "completed", "output": [{
                    "id": "message", "type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "ok", "annotations": []}],
                }],
            })
        return httpx.Response(200, json={
            "id": "chat", "object": "chat.completion", "created": 0, "model": "legacy-alias",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })
    async def execute():
        use_apim = sys.argv[3] == "True"
        for operation, authentication in product(
            ("chat/completions", "responses"), ("key",) if use_apim else ("key", "managed_identity"),
        ):
            endpoint = "https://legacy.invalid/openai/v1/" + ("responses" if operation == "responses" else "")
            settings = {
                "enable_gpt_apim": use_apim,
                "azure_openai_gpt_endpoint": endpoint, "azure_openai_gpt_key": "offline-key",
                "azure_openai_gpt_api_version": "v1", "azure_openai_gpt_authentication_type": authentication,
                "azure_apim_gpt_endpoint": endpoint, "azure_apim_gpt_subscription_key": "offline-apim",
                "azure_apim_gpt_api_version": "2024-10-01-preview",
                "gpt_model": {"selected": [{"deploymentName": "legacy-alias", "modelName": "gpt-5.6-sol"}]},
            }
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
                credential = SimpleNamespace(get_token=lambda *_: SimpleNamespace(token="offline-token"))
                with patch.object(
                    runtime, "AsyncOpenAI", side_effect=lambda **kwargs: AsyncOpenAI(**kwargs, http_client=http),
                ), patch.object(runtime, "DefaultAzureCredential", return_value=credential):
                    service, protocol = runtime.build_semantic_kernel_chat_service_for_model("legacy-alias", settings)
                try:
                    if not isinstance(service, OpenAIToolChatCompletion) or protocol != "openai_style":
                        raise AssertionError("Legacy v1 settings selected the dated Azure SDK.")
                    if service.model_token_budget.model_id != "gpt-5.6-sol":
                        raise AssertionError("Legacy deployment alias lost canonical model metadata.")
                    history = ChatHistory()
                    history.add_user_message("Give a short answer.")
                    result = await service.get_chat_message_contents(
                        history, AzureChatPromptExecutionSettings(max_completion_tokens=512),
                    )
                    if result[0].content != "ok":
                        raise AssertionError("The real SDK did not return the mock answer.")
                finally:
                    await service.client.close()
            request, body = captured[-1]
            if request.url.path != "/openai/v1/" + operation or request.url.query:
                raise AssertionError("Legacy v1 inference sent a dated path or query.")
            if body["model"] != "legacy-alias":
                raise AssertionError("Legacy v1 inference changed the deployment.")
            expected_key = "offline-apim" if use_apim else "offline-token" if authentication == "managed_identity" else "offline-key"
            if not use_apim and authentication == "managed_identity":
                if request.headers.get("Authorization") != "Bearer " + expected_key:
                    raise AssertionError("Legacy v1 inference changed managed-identity authentication.")
            elif request.headers.get("api-key") != expected_key or request.headers.get("Authorization"):
                raise AssertionError("Legacy v1 inference changed or duplicated API-key authentication.")
    environment.loop.run_until_complete(execute())
    if environment.network_attempts:
        raise AssertionError("Legacy v1 construction or execution attempted real network I/O.")
print("PASS: real legacy global/APIM factories send versionless v1 SDK requests")
'''
    run_probe(probe, (str(use_apim),), False)
