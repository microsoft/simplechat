# test_custom_model_endpoint_foundation.py
"""
Functional tests for the Custom endpoint foundation.
Version: 0.261.122
Implemented in: 0.261.107
Semantic Kernel screening/workflow guard merge coverage: 0.261.113

Exercise registry contracts, URL/address policy, DNS pinning, authentication,
normalization, safe diagnostics, and real SDK requests against mock transports.
No inference, token, DNS, or Azure service requests leave the test process.
"""

import asyncio
import ast
import copy
import importlib.util
import json
import logging
import socket
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpcore
import httpx
import pytest
from flask import Flask, jsonify, request
from openai import AsyncOpenAI
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.function_choice_behavior import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.prompt_execution_settings import PromptExecutionSettings
from semantic_kernel.contents import ChatHistory
from semantic_kernel.functions import kernel_function


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Application imports follow the path setup so standalone execution uses this worktree.
from content_screening import access as screening_access
from content_screening.contracts import DocumentHeldError
import functions_model_endpoint_auth as endpoint_auth
import functions_model_endpoint_diagnostics as diagnostics
import functions_model_endpoint_validation as validation
import functions_workflow_context as workflow_context
import model_endpoint_clients as clients
from functions_model_endpoint_providers import get_model_endpoint_provider, get_model_endpoint_provider_ui_options
from functions_model_endpoint_types import get_model_endpoint_api_type, resolve_model_endpoint_request_model
from functions_model_capabilities import project_model_budget_metadata, resolve_model_token_budget
from test_model_endpoint_normalization_backend import _load_functions_settings_module, _restore_modules
from test_v2_admin_model_endpoints_api import _load_persistence_helper
from test_workflow_context_budget import ToolCallingCompletion


def endpoint_record(api_type="openai", auth_type="api_key"):
    return {
        "id": "connection-stable-id",
        "name": "Custom gateway",
        "provider": "custom",
        "api_type": api_type,
        "enabled": True,
        "connection": {
            "endpoint": "https://gateway.example.test/prefix",
            "url_mode": "auto",
            **({"api_version": "2025-04-01-preview"} if api_type == "azure_openai" else {}),
        },
        "auth": {
            "type": auth_type,
            "api_key": "fixture-api-key",
            "bearer_token": "fixture-bearer-token",
            "token_url": "https://identity.example.test/token",
            "client_id": "fixture-client",
            "client_secret": "fixture-client-secret",
            "scope": "inference",
        },
        "models": [{
            "id": "model-stable-id",
            "modelName": "gateway-model",
            "deploymentName": "azure-deployment",
            "displayName": "Friendly label",
            "supportsChat": True,
            "enabled": True,
            "vendorOptions": {"future": [1, 2]},
        }],
    }


@pytest.fixture(autouse=True)
def no_live_requests(monkeypatch):
    def addresses(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", addresses)
    monkeypatch.setattr(diagnostics, "log_event", Mock())
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", Mock(side_effect=AssertionError("Unexpected live TCP request")))
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", AsyncMock(side_effect=AssertionError("Unexpected live TCP request")))
    endpoint_auth.clear_oauth2_token_cache()


@pytest.mark.parametrize("registration_index", range(3))
@pytest.mark.parametrize("blocked_by", [None, "screening", "budget"])
def test_loader_registration_preserves_screening_and_workflow_tool_round_guards(
    monkeypatch, registration_index, blocked_by,
):
    """Run all merged registration paths with the real SK automatic tool loop."""
    source = ast.parse((APP / "semantic_kernel_loader.py").read_text(encoding="utf-8"))
    registrations = []
    for node in ast.walk(source):
        body = getattr(node, "body", None)
        if not isinstance(body, list):
            continue
        for index, statement in enumerate(body[:-1]):
            if (
                isinstance(statement, ast.Assign)
                and isinstance(statement.value, ast.Call)
                and isinstance(statement.value.func, ast.Name)
                and statement.value.func.id == "wrap_workflow_chat_service"
            ):
                registrations.append([statement, body[index + 1]])
    registrations.sort(key=lambda statements: statements[0].lineno)
    assert len(registrations) == 3
    budget_model = {
        "modelName": "fixture-model", "contextWindow": 4096,
        "outputTokenLimit": 512, "outputTokenAccounting": "total_generation",
    }
    held = False

    def verify_sources():
        if held:
            raise DocumentHeldError()

    monkeypatch.setattr(screening_access, "assert_current_request_sources_available", verify_sources)
    original = ToolCallingCompletion(ai_model_id="fixture-model", service_id="loader-model", api_key="test-only")
    kernel = Kernel()

    @kernel_function(name="load", description="Read the full inventory.")
    def load() -> str:
        nonlocal held
        held = blocked_by == "screening"
        return "inventory " * (10000 if blocked_by == "budget" else 1)

    kernel.add_function(plugin_name="evidence", function=load)
    history = ChatHistory()
    history.add_user_message("Review the inventory using the evidence tool.")
    settings = PromptExecutionSettings()
    settings.function_choice_behavior = FunctionChoiceBehavior.Auto(maximum_auto_invoke_attempts=3)
    agent_config = {
        "model_metadata": {"modelName": "fixture-model", "id": "agent-model"},
        "model_budget_model": budget_model,
        "deployment": "agent-deployment", "model_provider": "new_foundry",
    }
    orchestrator_config = {
        "model_metadata": {"modelName": "fixture-model", "id": "orchestrator-model"},
        "model_budget_model": budget_model,
        "deployment": "orchestrator-deployment", "model_provider": "aoai",
    }
    namespace = {
        "chat_service": original, "kernel": kernel,
        "agent_config": agent_config, "orchestrator_config": orchestrator_config,
        "guard_chat_service": screening_access.guard_chat_service,
        "wrap_workflow_chat_service": workflow_context.wrap_workflow_chat_service,
        "settings": {},
        "project_model_budget_metadata": project_model_budget_metadata,
        "resolve_model_token_budget": resolve_model_token_budget,
        "infer_model_endpoint_protocol": clients.infer_model_endpoint_protocol,
        "MODEL_ENDPOINT_PROTOCOL_ANTHROPIC": clients.MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    }
    budget_helpers = [
        node for node in source.body if isinstance(node, ast.FunctionDef)
        and node.name in {"build_agent_model_budget", "resolve_agent_endpoint_protocol"}
    ]
    assert len(budget_helpers) == 2
    exec(compile(ast.Module(body=budget_helpers, type_ignores=[]), str(APP / "semantic_kernel_loader.py"), "exec"), namespace)
    workflow = {}
    with workflow_context.workflow_context_budget_scope(workflow):
        exec(compile(
            ast.Module(body=registrations[registration_index], type_ignores=[]),
            str(APP / "semantic_kernel_loader.py"), "exec",
        ), namespace)
        service = namespace["chat_service"]
        expected_config = orchestrator_config if registration_index == 2 else agent_config
        expected_budget = namespace["build_agent_model_budget"](expected_config, {})
        assert service.model_metadata == expected_budget
        assert expected_budget.model_id == "fixture-model"
        assert expected_budget.context_window == 4096
        assert expected_budget.output_limit == 512
        assert expected_budget.output_accounting == "total_generation"
        assert service.provider == expected_config["model_provider"]
        assert kernel.get_service(service_id="loader-model") is service
        if blocked_by:
            error = DocumentHeldError if blocked_by == "screening" else workflow_context.WorkflowContextBudgetError
            with pytest.raises(error):
                asyncio.run(service.get_chat_message_contents(history, settings, kernel=kernel))
            assert original.request_count == 1
        else:
            messages = asyncio.run(service.get_chat_message_contents(history, settings, kernel=kernel))
            assert messages[-1].content == "Finished."
            assert original.request_count == 2
    if blocked_by == "budget":
        assert workflow["context_budget"]["decision"] == "blocked"


@pytest.fixture
def runtime(monkeypatch):
    config = types.ModuleType("config")
    config.cognitive_services_scope = "https://cognitiveservices.azure.com/.default"
    foundry = types.ModuleType("foundry_agent_runtime")
    foundry.resolve_authority = lambda auth: ""
    settings = types.ModuleType("functions_settings")
    settings.resolve_model_endpoint_foundry_scope = lambda auth, endpoint=None: "https://ai.azure.com/.default"
    for name, module in {"config": config, "foundry_agent_runtime": foundry, "functions_settings": settings}.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("custom_endpoint_runtime_under_test", APP / "functions_model_endpoint_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registry_is_explicit_and_never_uses_registry_ids_on_the_wire():
    options = get_model_endpoint_provider_ui_options()
    assert {option["value"] for option in options} == {"openai", "azure_openai", "anthropic", "gemini"}
    for option in options:
        endpoint = endpoint_record(option["value"])
        assert get_model_endpoint_api_type(endpoint) == option["value"]
        assert clients.infer_model_endpoint_protocol("custom", "https://gateway.example.test/anthropic", "claude", option["value"]) == option["protocol"]
        expected = "gateway-model" if option["usesModelName"] else "azure-deployment"
        assert resolve_model_endpoint_request_model(endpoint, endpoint["models"][0]) == expected
        assert resolve_model_endpoint_request_model(endpoint, {"id": "never-a-request-model"}) == ""
    with pytest.raises(validation.ModelEndpointValidationError):
        clients.infer_model_endpoint_protocol("custom", "https://gateway.example.test", "gpt-4o")


@pytest.mark.parametrize("url,api_type,mode,expected", [
    ("https://gateway.example.test/prefix", "openai", "auto", "https://gateway.example.test/prefix/v1/"),
    ("https://gateway.example.test/prefix/v2", "openai", "auto", "https://gateway.example.test/prefix/v2/"),
    ("https://gateway.example.test/prefix/v1beta", "openai", "auto", "https://gateway.example.test/prefix/v1beta/"),
    ("https://gateway.example.test/prefix/responses", "openai", "auto", "https://gateway.example.test/prefix/"),
    ("https://gateway.example.test/prefix/images/edits", "openai", "auto", "https://gateway.example.test/prefix/"),
    ("https://gateway.example.test/prefix", "openai", "exact", "https://gateway.example.test/prefix/"),
    ("https://gateway.example.test/v1beta/openai", "gemini", "auto", "https://gateway.example.test/v1beta/openai/"),
])
def test_custom_url_policy(url, api_type, mode, expected):
    assert clients.resolve_custom_openai_base_url(url, api_type, mode) == expected
    assert "/openai/deployments/" not in expected


def test_custom_azure_and_anthropic_urls_keep_prefixes_and_exact_mode():
    assert clients.resolve_custom_azure_openai_base_url(
        "https://gateway.example.test/prefix/openai/deployments/old/chat/completions", "right-deployment",
    ) == "https://gateway.example.test/prefix/openai/deployments/right-deployment/"
    assert clients.resolve_custom_azure_openai_base_url(
        "https://gateway.example.test/exact", "right-deployment", "exact",
    ) == "https://gateway.example.test/exact/"
    assert clients.normalize_anthropic_messages_url(
        "https://gateway.example.test/prefix", direct_custom=True,
    ) == "https://gateway.example.test/prefix/v1/messages"
    assert clients.normalize_anthropic_messages_url(
        "https://gateway.example.test/exact/messages", direct_custom=True, url_mode="exact",
    ) == "https://gateway.example.test/exact/messages"


@pytest.mark.parametrize("url", [
    "file:///secret", "https://localhost", "https://metadata.google.internal",
    "https://user:secret@gateway.example.test", "https://gateway.example.test?api-key=secret",
    "https://gateway.example.test/#fragment", "https://gateway.example.test:0",
    "https://[::1]", "https://[::ffff:127.0.0.1]", "https://[2002:7f00:1::]",
    "https://169.254.169.254", "https://168.63.129.16", "https://gateway.example.test\\evil",
])
def test_blocked_urls_fail_even_with_private_permission(url):
    with pytest.raises(validation.ModelEndpointValidationError):
        validation.validate_custom_model_endpoint_url(url, allow_private=True, allow_insecure=True)


def test_dns_all_answers_are_checked_and_save_only_tolerates_unresolvable_names(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ])
    with pytest.raises(validation.ModelEndpointValidationError):
        validation.validate_custom_model_endpoint_url("https://gateway.example.test", require_resolvable=False)
    monkeypatch.setattr(socket, "getaddrinfo", Mock(side_effect=socket.gaierror()))
    assert validation.validate_custom_model_endpoint_url(
        "https://gateway.example.test", require_resolvable=False,
    ) == "https://gateway.example.test"
    with pytest.raises(validation.ModelEndpointUnresolvableError):
        validation.validate_custom_model_endpoint_url("https://gateway.example.test")


def test_private_http_requires_both_permissions_and_ipv6_stays_well_formed():
    for private, insecure in [(False, False), (True, False), (False, True)]:
        with pytest.raises(validation.ModelEndpointValidationError):
            validation.validate_custom_model_endpoint_url(
                "http://10.20.30.40:8080/api", allow_private=private, allow_insecure=insecure,
            )
    assert validation.validate_custom_model_endpoint_url(
        "http://10.20.30.40:8080/api", allow_private=True, allow_insecure=True,
    ) == "http://10.20.30.40:8080/api"
    assert validation.validate_custom_model_endpoint_url(
        "https://[fd00::42]:8443/api", allow_private=True,
    ) == "https://[fd00::42]:8443/api"
    assert not validation.custom_endpoint_setting_enabled({"gate": "false"}, "gate")


def test_sync_and_async_backends_dial_only_validated_addresses():
    sync = clients._PinnedCustomEndpointSyncBackend()
    sync._backend = Mock()
    sync.connect_tcp("gateway.example.test", 443)
    assert sync._backend.connect_tcp.call_args.args[0] == "93.184.216.34"

    async def run():
        asynchronous = clients._PinnedCustomEndpointAsyncBackend()
        asynchronous._backend = Mock(connect_tcp=AsyncMock())
        await asynchronous.connect_tcp("gateway.example.test", 443)
        assert asynchronous._backend.connect_tcp.call_args.args[0] == "93.184.216.34"
    asyncio.run(run())


def test_transport_rejects_redirects_host_overrides_and_plaintext(monkeypatch):
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", lambda *args: httpx.Response(302, headers={"location": "https://other.example.test"}))
    with clients.build_custom_openai_sync_http_client() as client:
        assert client.follow_redirects is False
        assert client.trust_env is False
        assert not client._mounts
        with pytest.raises(validation.ModelEndpointValidationError, match="redirects"):
            client.get("https://gateway.example.test", follow_redirects=True)
        with pytest.raises(validation.ModelEndpointValidationError, match="Host"):
            client.get("https://gateway.example.test", headers={"Host": "other.example.test"})
        with pytest.raises(validation.ModelEndpointValidationError, match="HTTPS"):
            client.get("http://gateway.example.test")


def test_ca_and_mtls_fail_closed(monkeypatch):
    with pytest.raises(validation.ModelEndpointValidationError):
        clients.build_custom_endpoint_ssl_context(str(APP / "does-not-exist.pem"))
    context = Mock()
    monkeypatch.setattr(clients.httpx, "create_ssl_context", Mock(return_value=context))
    assert clients.build_custom_endpoint_ssl_context(client_cert=("mounted-cert.pem", "mounted-key.pem")) is context
    context.load_cert_chain.assert_called_once_with("mounted-cert.pem", "mounted-key.pem")
    assert endpoint_auth.resolve_client_certificate({"client_cert_path": "cert.pem", "client_key_path": "key.pem"}) == ("cert.pem", "key.pem")


@pytest.mark.parametrize("api_type", ["openai", "azure_openai", "gemini"])
@pytest.mark.parametrize("auth_type", ["api_key", "bearer", "oauth2_client_credentials"])
def test_real_sdk_uses_custom_url_auth_and_request_identity(runtime, monkeypatch, api_type, auth_type):
    endpoint = endpoint_record(api_type, auth_type)
    request_model = resolve_model_endpoint_request_model(endpoint, endpoint["models"][0])
    requests = []
    factory_options = []
    monkeypatch.setattr(endpoint_auth, "fetch_oauth2_client_credentials_token", lambda *args, **kwargs: "fresh-oauth-token")

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={
            "id": "fixture-completion", "object": "chat.completion", "model": request_model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
        })

    def factory(**kwargs):
        factory_options.append(kwargs)
        return httpx.Client(transport=httpx.MockTransport(handle), trust_env=False, follow_redirects=False)
    monkeypatch.setattr(runtime, "build_custom_openai_sync_http_client", factory)
    client, protocol = runtime.build_model_endpoint_sync_chat_client(
        endpoint["auth"], "custom", endpoint["connection"]["endpoint"], endpoint["connection"].get("api_version"),
        request_model, settings={}, endpoint_config=endpoint,
    )
    try:
        assert client.chat.completions.create(model=request_model, messages=[{"role": "user", "content": "fixture"}]).choices[0].message.content == "ok"
    finally:
        client.close()
    request = requests[0]
    assert json.loads(request.content)["model"] == request_model
    if api_type == "azure_openai":
        assert request.url.path == "/prefix/openai/deployments/azure-deployment/chat/completions"
        assert request.url.params["api-version"] == "2025-04-01-preview"
    else:
        assert request.url.path == ("/prefix/v1/chat/completions" if api_type == "openai" else "/prefix/chat/completions")
        assert "api-version" not in request.url.params
    if auth_type == "api_key" and api_type == "azure_openai":
        assert request.headers["api-key"] == "fixture-api-key"
        assert not request.headers.get("authorization")
    else:
        token = {"api_key": "fixture-api-key", "bearer": "fixture-bearer-token", "oauth2_client_credentials": "fresh-oauth-token"}[auth_type]
        assert request.headers["authorization"] == f"Bearer {token}"
        assert len(request.headers.get_list("authorization")) == 1
    assert protocol == get_model_endpoint_provider(api_type).protocol
    assert factory_options == [{"allow_private": False, "allow_insecure": False, "ca_bundle_path": "", "client_cert": None}]


def test_gateway_header_override_does_not_duplicate_the_real_key():
    credential, headers = endpoint_auth.resolve_custom_endpoint_credentials({
        "type": "api_key", "api_key": "fixture-key", "api_key_header": "x-gateway-key", "api_key_prefix": "Token",
    })
    assert credential != "fixture-key"
    assert headers == {"Authorization": "", "x-gateway-key": "Token fixture-key"}
    _, headers = endpoint_auth.resolve_custom_endpoint_credentials({
        "type": "api_key", "api_key": "fixture-key", "api_key_header": "Authorization", "api_key_prefix": "Token",
    })
    assert headers["Authorization"] == "Token fixture-key"
    for name in ("Host", "Content-Length", "Proxy-Authorization", "bad\r\nheader"):
        with pytest.raises(validation.ModelEndpointValidationError):
            endpoint_auth.build_api_key_headers({"api_key": "key", "api_key_header": name})


def test_async_sdk_and_semantic_kernel_keep_the_custom_transport(runtime, monkeypatch):
    endpoint = endpoint_record("gemini", "bearer")
    endpoint["auth"]["refresh_token"] = "not-a-browser-field"
    endpoint["connection"].update(client_cert_path="cert.pem", client_key_path="key.pem")
    requests = []
    options = []

    def factory(**kwargs):
        options.append(kwargs)
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={
                "id": "async-completion", "object": "chat.completion", "model": "gateway-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            })
        return httpx.AsyncClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(runtime, "build_custom_openai_async_http_client", factory)

    async def run():
        service, protocol = runtime.build_semantic_kernel_chat_service_for_model(
            "gateway-model", {}, model_context={"model_id": "model-stable-id"},
            resolved_model_endpoint=endpoint,
        )
        assert isinstance(service.client, AsyncOpenAI)
        assert protocol == "openai_style"
        try:
            result = await service.client.chat.completions.create(model="gateway-model", messages=[{"role": "user", "content": "fixture"}])
            assert result.choices[0].message.content == "ok"
        finally:
            await service.client.close()
    asyncio.run(run())
    assert requests[0].url.path == "/prefix/chat/completions"
    assert options[0]["client_cert"] == ("cert.pem", "key.pem")


def test_custom_reasoning_rejection_retains_one_model_default_retry(runtime, monkeypatch):
    endpoint = endpoint_record()
    endpoint["models"][0]["modelName"] = "gpt-5.6-luna"
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(400, json={"error": {
                "message": "provider-secret-echo", "param": "reasoning_effort", "code": "unsupported_value",
            }})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}, "index": 0}]})
    monkeypatch.setattr(runtime, "build_custom_openai_sync_http_client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handle)))
    client, _ = runtime.build_model_endpoint_sync_chat_client(
        endpoint["auth"], "custom", endpoint["connection"]["endpoint"], "", "gpt-5.6-luna",
        settings={}, endpoint_config=endpoint,
    )
    try:
        _, resolution = clients.create_completion_with_reasoning(
            client.chat.completions.create,
            {"model": "gpt-5.6-luna", "messages": [{"role": "user", "content": "fixture"}], "reasoning_effort": "high"},
            "gpt-5.6-luna",
        )
    finally:
        client.close()
    assert len(requests) == 2 and requests[0]["model"] == requests[1]["model"]
    assert "reasoning_effort" not in requests[1]
    assert resolution["adjustment_reason"] == "reasoning_parameter_rejected"


def test_incomplete_custom_bindings_never_fall_through_to_azure(runtime, monkeypatch):
    azure = Mock(side_effect=AssertionError("Custom must not use a legacy Azure client"))
    monkeypatch.setattr(runtime, "AzureOpenAI", azure)
    monkeypatch.setattr(runtime, "AzureChatCompletion", azure)
    with pytest.raises(runtime.AIConnectionError):
        runtime.build_semantic_kernel_chat_service_for_model(
            "gateway-model", {}, model_context={"provider": "custom"},
        )
    endpoint = endpoint_record()
    with pytest.raises(runtime.AIConnectionError):
        runtime.build_model_endpoint_sync_chat_client(
            endpoint["auth"], "custom", endpoint["connection"]["endpoint"], "", "model-stable-id",
            settings={}, endpoint_config=endpoint,
        )
    azure.assert_not_called()


def test_oauth_cache_isolated_by_rotated_secret_and_network_policy():
    calls = []
    auth = endpoint_record(auth_type="oauth2_client_credentials")["auth"]

    def factory(**options):
        def handle(request):
            calls.append((request, options))
            assert b"grant_type=client_credentials" in request.content
            return httpx.Response(200, json={"access_token": f"token-{len(calls)}", "token_type": "Bearer", "expires_in": 3600})
        return httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=False)
    assert endpoint_auth.fetch_oauth2_client_credentials_token(auth, http_client_factory=factory) == "token-1"
    assert endpoint_auth.fetch_oauth2_client_credentials_token(auth, http_client_factory=factory) == "token-1"
    auth = {**auth, "client_secret": "rotated"}
    assert endpoint_auth.fetch_oauth2_client_credentials_token(auth, http_client_factory=factory) == "token-2"
    assert endpoint_auth.fetch_oauth2_client_credentials_token(auth, allow_private=True, http_client_factory=factory) == "token-3"
    assert len(calls) == 3


def test_token_provider_errors_are_safe_and_do_not_become_success():
    auth = endpoint_record(auth_type="oauth2_client_credentials")["auth"]
    for status, payload in [(302, {"access_token": "not-followed"}), (401, {"error": "fixture-client-secret"}), (200, {"error": "fixture-client-secret"})]:
        factory = lambda **kwargs: httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload)))
        with pytest.raises(diagnostics.SanitizedModelEndpointError) as error:
            endpoint_auth.fetch_oauth2_client_credentials_token(auth, http_client_factory=factory)
        assert "fixture-client-secret" not in str(error.value)
        assert "reference" in str(error.value)


def test_anthropic_uses_guarded_native_messages_and_mtls(runtime, monkeypatch):
    endpoint = endpoint_record("anthropic", "bearer")
    endpoint["connection"].update(client_cert_path="cert.pem", client_key_path="key.pem")
    requests = []
    factory_options = []

    def factory(**kwargs):
        factory_options.append(kwargs)
        def handle(request):
            requests.append(request)
            return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "usage": {}})
        return httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(clients, "build_custom_openai_sync_http_client", factory)
    client, protocol = runtime.build_model_endpoint_sync_chat_client(
        endpoint["auth"], "custom", endpoint["connection"]["endpoint"], "",
        "gateway-model", settings={}, endpoint_config=endpoint,
    )
    result = client.chat.completions.create(model="gateway-model", messages=[{
        "role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}}],
    }])
    assert result.choices[0].message.content == "ok"
    assert protocol == "anthropic"
    assert requests[0].url.path == "/prefix/v1/messages"
    assert requests[0].headers["authorization"] == "Bearer fixture-bearer-token"
    assert "api-key" not in requests[0].headers and "x-api-key" not in requests[0].headers
    assert json.loads(requests[0].content)["messages"][0]["content"][0]["type"] == "image"
    assert factory_options[0]["client_cert"] == ("cert.pem", "key.pem")


def test_normalization_merge_and_admin_user_projections_keep_the_contract():
    settings, originals = _load_functions_settings_module()
    try:
        endpoint = endpoint_record("gemini", "bearer")
        normalized, _ = settings.normalize_model_endpoints([endpoint])
        result = normalized[0]
        assert result["id"] == "connection-stable-id"
        assert result["models"][0]["id"] == "model-stable-id"
        assert result["models"][0]["vendorOptions"] == {"future": [1, 2]}
        assert "management_cloud" not in result["auth"]
        assert "supportsImageGeneration" not in result["models"][0]
        merged = settings.merge_model_endpoint_payload(result, {"auth": {"bearer_token": "", "scope": ""}})
        assert merged["auth"]["bearer_token"] == "fixture-bearer-token"
        assert merged["auth"]["scope"] == ""
        admin = settings.sanitize_model_endpoints_for_frontend([result])[0]
        assert admin["api_type"] == "gemini" and admin["has_bearer_token"]
        for secret in ("api_key", "client_secret", "bearer_token"):
            assert secret not in admin["auth"]
        assert "refresh_token" not in admin["auth"]
        public = settings.sanitize_settings_for_user({"model_endpoints": [result]})["model_endpoints"][0]
        assert "auth" not in public and "connection" not in public and "management" not in public
    finally:
        _restore_modules(originals)


@pytest.fixture
def admin_routes():
    """Invoke real route bodies; the existing route-policy suites verify their guards."""
    settings, originals = _load_functions_settings_module()
    persist, calls = _load_persistence_helper()
    calls["settings"]["enable_multi_model_endpoints"] = False
    names = {
        "_load_global_model_endpoints", "_find_model_endpoint", "_model_endpoint_response",
        "v2_admin_create_model_endpoint", "v2_admin_update_model_endpoint",
        "v2_admin_get_model_endpoint", "v2_admin_delete_model_endpoint",
    }
    source = ast.parse((APP / "route_backend_v2.py").read_text(encoding="utf-8"))
    nodes = [node for node in ast.walk(source) if isinstance(node, ast.FunctionDef) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    namespace = {
        "request": request, "jsonify": jsonify, "uuid": uuid, "logging": logging,
        "log_event": Mock(), "get_settings": lambda: calls["settings"],
        "normalize_model_endpoints": settings.normalize_model_endpoints,
        "sanitize_model_endpoints_for_frontend": settings.sanitize_model_endpoints_for_frontend,
        "merge_model_endpoint_payload": settings.merge_model_endpoint_payload,
        "AIConnectionError": settings.AIConnectionError,
        "ModelEndpointValidationError": validation.ModelEndpointValidationError,
        "_persist_global_model_endpoints": persist,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(APP / "route_backend_v2.py"), "exec"), namespace)
    try:
        yield Flask(__name__), namespace, calls
    finally:
        _restore_modules(originals)


def test_global_custom_crud_keeps_stable_ids_and_redacts_credentials(admin_routes):
    app, routes, calls = admin_routes
    candidate = endpoint_record(auth_type="bearer")
    with app.test_request_context(json=candidate):
        response, status = routes["v2_admin_create_model_endpoint"]()
    assert status == 201
    saved = response.get_json()["endpoint"]
    assert saved["id"] == "connection-stable-id" and saved["api_type"] == "openai"
    assert saved["has_bearer_token"] and "bearer_token" not in saved["auth"]
    assert calls["settings"]["enable_multi_model_endpoints"] is False
    with app.test_request_context(json={"name": "Renamed", "auth": {"bearer_token": ""}}):
        response, status = routes["v2_admin_update_model_endpoint"]("connection-stable-id")
    assert status == 200
    assert response.get_json()["endpoint"]["models"][0]["id"] == "model-stable-id"
    assert calls["settings"]["model_endpoints"][0]["auth"]["bearer_token"] == "fixture-bearer-token"
    with app.test_request_context():
        response, status = routes["v2_admin_get_model_endpoint"]("connection-stable-id")
    assert status == 200
    assert "fixture-bearer-token" not in response.get_data(as_text=True)
    with app.test_request_context():
        response, status = routes["v2_admin_delete_model_endpoint"]("connection-stable-id")
    assert status == 200 and calls["settings"]["model_endpoints"] == []


def test_invalid_custom_records_are_rejected_before_any_credential_write(admin_routes):
    app, routes, calls = admin_routes
    candidate = endpoint_record()
    candidate["api_type"] = "unsupported-type"
    with app.test_request_context(json=candidate):
        response, status = routes["v2_admin_create_model_endpoint"]()
    assert status == 400 and response.get_json()["code"] == "invalid_custom_endpoint"
    assert not calls["saved"] and not calls["updates"]
    assert "fixture-api-key" not in response.get_data(as_text=True)


def test_safe_diagnostics_keep_stack_without_provider_body():
    try:
        raise RuntimeError("unlabelled-credential-from-provider")
    except RuntimeError as exc:
        error = diagnostics.build_sanitized_model_endpoint_error(
            "Custom model request failed.", exc,
            request_url="https://user:secret@gateway.example.test/path?token=secret",
            detail="unlabelled-credential-from-provider",
        )
    assert "reference" in str(error)
    logged = diagnostics.log_event.call_args.kwargs["extra"]
    assert "test_safe_diagnostics" in logged["traceback"]
    assert logged["error_type"] == "RuntimeError"
    assert "unlabelled-credential" not in json.dumps(logged)
    assert logged["request_url"] == "https://gateway.example.test/path"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
