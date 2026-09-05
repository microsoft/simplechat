# test_custom_model_endpoint_provider.py
#!/usr/bin/env python3
"""
Functional test for the Custom model endpoint provider.
Version: 0.250.172
Implemented in: 0.250.172

This test validates canonical model identifiers, API-type precedence, Custom
endpoint URL safety, direct Anthropic request behavior, normalization, secret
sanitization, and the admin/workspace UI contract without network traffic.
"""

import asyncio
import importlib
import re
import socket
import sys
import types
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(ROOT))

from functions_model_endpoint_providers import (  # noqa: E402
    get_model_endpoint_provider_ui_options,
)
from functions_model_endpoint_types import (  # noqa: E402
    MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
    MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
    MODEL_ENDPOINT_API_TYPE_OPENAI,
    resolve_model_endpoint_request_model,
)
from functions_model_endpoint_validation import (  # noqa: E402
    ModelEndpointValidationError,
    validate_custom_model_endpoint,
    validate_custom_model_endpoint_url,
)
from model_endpoint_clients import (  # noqa: E402
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    _PinnedCustomEndpointAsyncBackend,
    _PinnedCustomEndpointSyncBackend,
    AnthropicChatCompletionClient,
    SanitizedCustomChatCompletionClient,
    build_custom_openai_async_http_client,
    build_custom_openai_sync_http_client,
    infer_model_endpoint_protocol,
    normalize_anthropic_messages_url,
    normalize_custom_openai_base_url,
    sanitize_custom_async_openai_client,
)
from test_model_endpoint_normalization_backend import (  # noqa: E402
    _load_functions_settings_module,
    _restore_modules,
)


PUBLIC_ADDRESS_INFO = [
    (
        socket.AF_INET,
        socket.SOCK_STREAM,
        socket.IPPROTO_TCP,
        "",
        ("93.184.216.34", 443),
    )
]


def assert_validation_error(callable_value, expected_message):
    """Assert a configuration is rejected with a stable, user-safe message."""
    try:
        callable_value()
    except ModelEndpointValidationError as exc:
        assert expected_message in str(exc)
        return
    raise AssertionError(f"Expected ModelEndpointValidationError containing {expected_message!r}")


def build_custom_endpoint(api_type, model, connection=None):
    """Build a valid Custom endpoint record for validation tests."""
    endpoint_connection = {"endpoint": "https://models.example.com"}
    endpoint_connection.update(connection or {})
    return {
        "id": f"custom-{api_type}",
        "name": "Custom Models",
        "provider": "custom",
        "api_type": api_type,
        "enabled": True,
        "auth": {"type": "api_key", "api_key": "test-key"},
        "connection": endpoint_connection,
        "models": [{"id": "stable-model-id", "enabled": True, **model}],
    }


def load_model_endpoint_runtime_module():
    """Load the runtime helper without initializing the application config."""
    config_stub = types.ModuleType("config")
    config_stub.cognitive_services_scope = "https://cognitiveservices.azure.com/.default"

    foundry_runtime_stub = types.ModuleType("foundry_agent_runtime")
    foundry_runtime_stub.resolve_authority = lambda auth_settings: None

    settings_stub = types.ModuleType("functions_settings")
    settings_stub.resolve_model_endpoint_foundry_scope = (
        lambda auth_settings, endpoint=None: "https://ai.azure.com/.default"
    )

    original_modules = {}
    for module_name, module_stub in {
        "config": config_stub,
        "foundry_agent_runtime": foundry_runtime_stub,
        "functions_settings": settings_stub,
    }.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules["functions_model_endpoint_runtime"] = sys.modules.get(
        "functions_model_endpoint_runtime"
    )
    sys.modules.pop("functions_model_endpoint_runtime", None)
    module = importlib.import_module("functions_model_endpoint_runtime")
    return module, original_modules


def test_request_model_resolution_and_protocol_precedence():
    """Ensure stable IDs and model-name heuristics never override Custom API type."""
    openai_endpoint = build_custom_endpoint(
        MODEL_ENDPOINT_API_TYPE_OPENAI,
        {"modelName": "claude-compatible-model", "deploymentName": "wrong-deployment"},
    )
    anthropic_endpoint = build_custom_endpoint(
        MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
        {"modelName": "vendor-model"},
    )
    azure_endpoint = build_custom_endpoint(
        MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
        {"deploymentName": "azure-deployment", "modelName": "wrong-model"},
        {"api_version": "2024-05-01-preview"},
    )

    assert resolve_model_endpoint_request_model(
        openai_endpoint,
        openai_endpoint["models"][0],
    ) == "claude-compatible-model"
    assert resolve_model_endpoint_request_model(
        anthropic_endpoint,
        anthropic_endpoint["models"][0],
    ) == "vendor-model"
    assert resolve_model_endpoint_request_model(
        azure_endpoint,
        azure_endpoint["models"][0],
    ) == "azure-deployment"

    assert infer_model_endpoint_protocol(
        "custom",
        "https://models.example.com",
        "claude-compatible-model",
        MODEL_ENDPOINT_API_TYPE_OPENAI,
    ) == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE
    assert infer_model_endpoint_protocol(
        "custom",
        "https://models.example.com",
        "gpt-compatible-name",
        MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
    ) == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC
    assert infer_model_endpoint_protocol(
        "custom",
        "https://models.example.com/openai/v1",
        "claude-name",
        MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
    ) == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
    assert infer_model_endpoint_protocol(
        "new_foundry",
        "https://eastus.services.ai.azure.com/api/projects/example",
        "claude-sonnet",
    ) == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC


def test_custom_endpoint_url_policy():
    """Ensure Custom URLs enforce HTTPS, DNS, and address-class policy."""
    with patch("functions_model_endpoint_validation.socket.getaddrinfo", return_value=PUBLIC_ADDRESS_INFO):
        assert validate_custom_model_endpoint_url(
            "https://Models.Example.com/custom/"
        ) == "https://models.example.com/custom"

    for endpoint, expected_message in (
        ("http://models.example.com", "must use HTTPS"),
        ("https://user:password@models.example.com", "embedded credentials"),
        ("https://models.example.com?key=value", "query string or fragment"),
        ("https://127.0.0.1", "fully qualified domain name"),
        ("https://single-label", "fully qualified domain name"),
        ("https://localhost", "hostname is blocked"),
    ):
        assert_validation_error(
            lambda endpoint=endpoint: validate_custom_model_endpoint_url(endpoint),
            expected_message,
        )

    private_address_info = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("10.20.30.40", 443),
        )
    ]
    with patch(
        "functions_model_endpoint_validation.socket.getaddrinfo",
        return_value=private_address_info,
    ):
        assert_validation_error(
            lambda: validate_custom_model_endpoint_url("https://private.example.com"),
            "not enabled",
        )
        assert validate_custom_model_endpoint_url(
            "https://private.example.com",
            allow_private=True,
        ) == "https://private.example.com"

    loopback_address_info = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("127.0.0.1", 443),
        )
    ]
    with patch(
        "functions_model_endpoint_validation.socket.getaddrinfo",
        return_value=loopback_address_info,
    ):
        assert_validation_error(
            lambda: validate_custom_model_endpoint_url(
                "https://loopback.example.com",
                allow_private=True,
            ),
            "loopback",
        )

    shared_address_info = [
        (
            socket.AF_INET,
            socket.SOCK_STREAM,
            socket.IPPROTO_TCP,
            "",
            ("100.64.0.1", 443),
        )
    ]
    with patch(
        "functions_model_endpoint_validation.socket.getaddrinfo",
        return_value=shared_address_info,
    ):
        assert_validation_error(
            lambda: validate_custom_model_endpoint_url(
                "https://shared.example.com",
                allow_private=True,
            ),
            "globally routable",
        )

    with patch(
        "functions_model_endpoint_validation.socket.getaddrinfo",
        side_effect=socket.gaierror(),
    ):
        assert_validation_error(
            lambda: validate_custom_model_endpoint_url("https://missing.example.com"),
            "could not be resolved",
        )


def test_custom_endpoint_configuration_validation():
    """Validate required type-specific fields and manual model uniqueness."""
    openai_endpoint = build_custom_endpoint(
        MODEL_ENDPOINT_API_TYPE_OPENAI,
        {"modelName": "openai-model"},
    )
    azure_endpoint = build_custom_endpoint(
        MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
        {"deploymentName": "azure-deployment"},
        {"api_version": "2024-05-01-preview"},
    )
    anthropic_endpoint = build_custom_endpoint(
        MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
        {"modelName": "anthropic-model"},
        {"anthropic_version": "2023-06-01"},
    )

    with patch("functions_model_endpoint_validation.socket.getaddrinfo", return_value=PUBLIC_ADDRESS_INFO):
        validate_custom_model_endpoint(openai_endpoint)
        validate_custom_model_endpoint(azure_endpoint)
        validate_custom_model_endpoint(anthropic_endpoint)

        missing_version = build_custom_endpoint(
            MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
            {"deploymentName": "azure-deployment"},
        )
        assert_validation_error(
            lambda: validate_custom_model_endpoint(missing_version),
            "Azure OpenAI API version",
        )

        wrong_model_field = build_custom_endpoint(
            MODEL_ENDPOINT_API_TYPE_OPENAI,
            {"deploymentName": "deployment-only"},
        )
        assert_validation_error(
            lambda: validate_custom_model_endpoint(wrong_model_field),
            "Model Name",
        )

        wrong_azure_model_field = build_custom_endpoint(
            MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
            {"modelName": "model-only"},
            {"api_version": "2024-05-01-preview"},
        )
        assert_validation_error(
            lambda: validate_custom_model_endpoint(wrong_azure_model_field),
            "Deployment Name",
        )

        no_models = build_custom_endpoint(
            MODEL_ENDPOINT_API_TYPE_OPENAI,
            {"modelName": "unused"},
        )
        no_models["models"] = []
        assert_validation_error(
            lambda: validate_custom_model_endpoint(no_models),
            "at least one manually configured model",
        )

        duplicate_models = build_custom_endpoint(
            MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
            {"modelName": "duplicate-model"},
        )
        duplicate_models["models"].append({
            "id": "another-stable-id",
            "modelName": "DUPLICATE-MODEL",
            "enabled": True,
        })
        assert_validation_error(
            lambda: validate_custom_model_endpoint(duplicate_models),
            "must be unique",
        )


def test_custom_client_paths_headers_and_redirect_policy():
    """Ensure direct Custom adapters use provider paths, headers, and no redirects."""
    assert normalize_custom_openai_base_url(
        "https://models.example.com"
    ) == "https://models.example.com/v1/"
    assert normalize_custom_openai_base_url(
        "https://models.example.com/v1/chat/completions"
    ) == "https://models.example.com/v1/"
    assert normalize_anthropic_messages_url(
        "https://models.example.com",
        direct_custom=True,
    ) == "https://models.example.com/v1/messages"

    client = AnthropicChatCompletionClient(
        endpoint="https://models.example.com",
        api_key="test-key",
        anthropic_version="2024-01-01",
        direct_custom=True,
    )
    headers = client._build_headers()
    assert headers["x-api-key"] == "test-key"
    assert headers["anthropic-version"] == "2024-01-01"
    assert "api-key" not in headers
    assert "Authorization" not in headers

    image_payload = client._build_payload({
        "model": "anthropic-model",
        "messages": [{
            "role": "user",
            "content": [{
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,aW1hZ2U="},
            }],
        }],
    })
    assert image_payload["messages"][0]["content"][0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "aW1hZ2U=",
        },
    }

    class FakeResponse:
        status_code = 200
        closed = False

        def json(self):
            return {
                "id": "message-1",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }

        def close(self):
            self.closed = True

    class FakeHttpClient:
        def __init__(self, response):
            self.response = response
            self.closed = False
            self.send_kwargs = None

        def build_request(self, *args, **kwargs):
            return (args, kwargs)

        def send(self, request, **kwargs):
            self.send_kwargs = kwargs
            return self.response

        def close(self):
            self.closed = True

    fake_response = FakeResponse()
    fake_http_client = FakeHttpClient(fake_response)
    with patch(
        "model_endpoint_clients.build_custom_openai_sync_http_client",
        return_value=fake_http_client,
    ):
        client.create(
            model="anthropic-model",
            messages=[{"role": "user", "content": "test"}],
        )
        assert fake_http_client.send_kwargs["follow_redirects"] is False
        assert fake_response.closed is True
        assert fake_http_client.closed is True

    class FakeErrorResponse:
        status_code = 401
        closed = False

        def close(self):
            self.closed = True

    fake_error_response = FakeErrorResponse()
    fake_error_client = FakeHttpClient(fake_error_response)
    with patch(
        "model_endpoint_clients.build_custom_openai_sync_http_client",
        return_value=fake_error_client,
    ):
        try:
            client.create(
                model="anthropic-model",
                messages=[{"role": "user", "content": "test"}],
            )
        except RuntimeError as exc:
            assert "provider secret response" not in str(exc)
            assert "status 401" in str(exc)
        else:
            raise AssertionError("Expected the direct Anthropic client to surface a safe error")
    assert fake_error_response.closed is True
    assert fake_error_client.closed is True

    class FailingCompletions:
        @staticmethod
        def create(**kwargs):
            raise ValueError("provider secret response")

    fake_sync_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=FailingCompletions())
    )
    safe_sync_client = SanitizedCustomChatCompletionClient(fake_sync_client)
    try:
        safe_sync_client.chat.completions.create(model="test")
    except RuntimeError as exc:
        # The message stays sanitized, but now carries a correlation id so an
        # administrator can find the real cause in the server log.
        assert "provider secret response" not in str(exc)
        assert str(exc).startswith("Custom model request failed.")
        assert re.search(r"\(reference [0-9a-f]{8}\)$", str(exc))
        assert exc.__cause__ is None
    else:
        raise AssertionError("Expected direct Custom SDK errors to be sanitized")

    class FailingAsyncCompletions:
        @staticmethod
        async def create(**kwargs):
            raise ValueError("provider secret response")

    fake_async_client = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=FailingAsyncCompletions())
    )
    sanitize_custom_async_openai_client(fake_async_client)

    async def assert_safe_async_error():
        try:
            await fake_async_client.chat.completions.create(model="test")
        except RuntimeError as exc:
            assert "provider secret response" not in str(exc)
            assert str(exc).startswith("Custom model request failed.")
            assert re.search(r"\(reference [0-9a-f]{8}\)$", str(exc))
            assert exc.__cause__ is None
            return
        raise AssertionError("Expected direct Custom async SDK errors to be sanitized")

    asyncio.run(assert_safe_async_error())

    sync_http_client = build_custom_openai_sync_http_client()
    async_http_client = build_custom_openai_async_http_client()
    try:
        assert sync_http_client.follow_redirects is False
        assert async_http_client.follow_redirects is False
    finally:
        sync_http_client.close()
        asyncio.run(async_http_client.aclose())

    sync_backend = _PinnedCustomEndpointSyncBackend(allow_private=True)
    sync_connections = []

    class FakeSyncBackend:
        @staticmethod
        def connect_tcp(host, port, **kwargs):
            sync_connections.append((host, port))
            return "sync-stream"

    sync_backend._backend = FakeSyncBackend()
    with patch(
        "model_endpoint_clients.resolve_custom_model_endpoint_addresses",
        return_value=("93.184.216.34",),
    ) as resolve_addresses:
        assert sync_backend.connect_tcp("models.example.com", 443) == "sync-stream"
        resolve_addresses.assert_called_once_with(
            "models.example.com",
            443,
            allow_private=True,
        )
    assert sync_connections == [("93.184.216.34", 443)]

    async_backend = _PinnedCustomEndpointAsyncBackend(allow_private=False)
    async_connections = []

    class FakeAsyncBackend:
        @staticmethod
        async def connect_tcp(host, port, **kwargs):
            async_connections.append((host, port))
            return "async-stream"

    async_backend._backend = FakeAsyncBackend()

    async def assert_async_dns_pinning():
        with patch(
            "model_endpoint_clients.resolve_custom_model_endpoint_addresses",
            return_value=("93.184.216.34",),
        ):
            stream = await async_backend.connect_tcp("models.example.com", 443)
            assert stream == "async-stream"

    asyncio.run(assert_async_dns_pinning())
    assert async_connections == [("93.184.216.34", 443)]


def test_custom_runtime_client_construction():
    """Ensure shared sync and Semantic Kernel builders honor explicit Custom types."""
    runtime, original_modules = load_model_endpoint_runtime_module()
    try:
        with patch.object(
            runtime,
            "validate_custom_model_endpoint_url",
            return_value="https://models.example.com",
        ) as validate_url:
            openai_client, openai_protocol = runtime.build_model_endpoint_sync_chat_client(
                {"type": "api_key", "api_key": "test-key"},
                "custom",
                "https://models.example.com",
                "",
                deployment_name="claude-compatible-model",
                api_type=MODEL_ENDPOINT_API_TYPE_OPENAI,
                allow_private_custom_endpoints=True,
            )
            assert openai_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE
            assert str(openai_client._client.base_url) == "https://models.example.com/v1/"
            validate_url.assert_called_with(
                "https://models.example.com",
                allow_private=True,
                allow_insecure=False,
            )
            openai_client._client.close()

            azure_client, azure_protocol = runtime.build_model_endpoint_sync_chat_client(
                {"type": "api_key", "api_key": "test-key"},
                "custom",
                "https://models.example.com",
                "2024-05-01-preview",
                deployment_name="azure-deployment",
                api_type=MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
            )
            assert azure_protocol == MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI
            azure_client.close()

            anthropic_client, anthropic_protocol = runtime.build_model_endpoint_sync_chat_client(
                {"type": "api_key", "api_key": "test-key"},
                "custom",
                "https://models.example.com",
                "",
                deployment_name="anthropic-model",
                api_type=MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
                anthropic_version="2024-01-01",
                allow_private_custom_endpoints=True,
            )
            assert anthropic_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC
            assert anthropic_client.direct_custom is True
            assert anthropic_client.anthropic_version == "2024-01-01"
            assert anthropic_client.allow_private_custom_endpoints is True

            openai_endpoint = build_custom_endpoint(
                MODEL_ENDPOINT_API_TYPE_OPENAI,
                {"modelName": "openai-model"},
            )
            openai_service, openai_service_protocol = (
                runtime.build_semantic_kernel_chat_service_for_model(
                    "stable-model-id",
                    {"allow_private_custom_model_endpoints": True},
                    model_context={"model_id": "stable-model-id"},
                    resolved_model_endpoint=openai_endpoint,
                )
            )
            assert openai_service_protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE
            assert openai_service.ai_model_id == "openai-model"

            anthropic_endpoint = build_custom_endpoint(
                MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
                {"modelName": "anthropic-model"},
                {"anthropic_version": "2024-01-01"},
            )
            service, service_protocol = runtime.build_semantic_kernel_chat_service_for_model(
                "stable-model-id",
                {"allow_private_custom_model_endpoints": True},
                model_context={"model_id": "stable-model-id"},
                resolved_model_endpoint=anthropic_endpoint,
            )
            assert service_protocol == MODEL_ENDPOINT_PROTOCOL_ANTHROPIC
            assert service.ai_model_id == "anthropic-model"
            assert service.direct_custom is True
            assert service.allow_private_custom_endpoints is True
    finally:
        sys.modules.pop("functions_model_endpoint_runtime", None)
        _restore_modules(original_modules)


def test_custom_endpoint_normalization_and_sanitization():
    """Ensure canonical persistence uses the right model field and strips API keys."""
    functions_settings, original_modules = _load_functions_settings_module()
    try:
        endpoints = [
            build_custom_endpoint(
                MODEL_ENDPOINT_API_TYPE_OPENAI,
                {"modelName": "openai-model", "deploymentName": "remove-me"},
            ),
            build_custom_endpoint(
                MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
                {"deploymentName": "azure-deployment", "modelName": "remove-me"},
                {"api_version": "2024-05-01-preview"},
            ),
            build_custom_endpoint(
                MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
                {"modelName": "anthropic-model"},
                {},
            ),
        ]
        normalized, changed = functions_settings.normalize_model_endpoints(endpoints)
        assert changed is True
        assert normalized[0]["models"][0]["modelName"] == "openai-model"
        assert "deploymentName" not in normalized[0]["models"][0]
        assert normalized[1]["models"][0]["deploymentName"] == "azure-deployment"
        assert "modelName" not in normalized[1]["models"][0]
        assert normalized[2]["connection"]["anthropic_version"] == "2023-06-01"
        assert "api_version" not in normalized[0]["connection"]
        assert "anthropic_version" not in normalized[1]["connection"]

        sanitized = functions_settings.sanitize_model_endpoints_for_frontend(normalized)
        assert len(sanitized) == 3
        assert all(endpoint["provider"] == "custom" for endpoint in sanitized)
        assert all(endpoint["has_api_key"] is True for endpoint in sanitized)
        assert all("api_key" not in endpoint["auth"] for endpoint in sanitized)
    finally:
        _restore_modules(original_modules)


def test_custom_endpoint_ui_contract():
    """Ensure both endpoint editors expose the same safe Custom workflow."""
    modal = (APP_DIR / "templates" / "_multiendpoint_modal.html").read_text(encoding="utf-8")
    admin_template = "\n".join(
        [(APP_DIR / "templates" / "admin_settings.html").read_text(encoding="utf-8")]
        + [
            pane.read_text(encoding="utf-8")
            for pane in sorted((APP_DIR / "templates" / "admin" / "_panes").glob("*.html"))
        ]
    )
    admin_js = (
        APP_DIR / "static" / "js" / "admin" / "admin_model_endpoints.js"
    ).read_text(encoding="utf-8")
    workspace_js = (
        APP_DIR / "static" / "js" / "workspace" / "workspace_model_endpoints.js"
    ).read_text(encoding="utf-8")
    agents_common_js = (
        APP_DIR / "static" / "js" / "agents_common.js"
    ).read_text(encoding="utf-8")
    agent_stepper_js = (
        APP_DIR / "static" / "js" / "agent_modal_stepper.js"
    ).read_text(encoding="utf-8")
    backend = (APP_DIR / "route_backend_models.py").read_text(encoding="utf-8")
    agent_backend = (APP_DIR / "route_backend_agents.py").read_text(encoding="utf-8")

    assert '<option value="custom">Custom</option>' in modal
    assert 'id="model-endpoint-api-type"' in modal
    # The API type options are rendered from the provider registry rather than
    # hard-coded, so assert the registry contract instead of literal markup.
    assert 'data-api-types=' in modal
    assert 'for api_type in model_endpoint_api_types' in modal
    registered_api_types = {
        option["value"] for option in get_model_endpoint_provider_ui_options()
    }
    assert {"openai", "azure_openai", "anthropic"}.issubset(registered_api_types)
    assert 'id="model-endpoint-anthropic-version"' in modal
    assert 'name="allow_private_custom_model_endpoints"' in admin_template

    for script in (admin_js, workspace_js):
        assert "Custom endpoints use API key authentication and manual model entry." in script
        assert "Model discovery is unavailable for Custom endpoints." in script
        assert "api_type" in script
        assert "anthropic_version" in script
        assert "customApiTypeUsesModelName" in script
        # Per-API-type behaviour comes from the rendered registry, not from
        # hard-coded api_type comparisons.
        assert "getCustomApiTypeRegistry" in script
        assert "customApiTypeVersionField" in script
        assert 'apiType === "azure_openai"' not in script
        assert "dataset.responseLengthFor" in script
        assert "model.responseLength = responseLength" in script

    assert "if (!response.ok)" in workspace_js
    assert "provider == MODEL_ENDPOINT_PROVIDER_CUSTOM" in backend
    assert "Model discovery is not available for Custom endpoints." in backend
    assert "persisted_model = next(" in backend
    assert "request_model: requestModel" in agents_common_js
    assert "selectedModelOption?.dataset?.requestModel" in agent_stepper_js
    assert "normalized_provider == 'custom'" in agent_backend


def run_tests():
    """Run all Custom endpoint functional checks."""
    tests = [
        test_request_model_resolution_and_protocol_precedence,
        test_custom_endpoint_url_policy,
        test_custom_endpoint_configuration_validation,
        test_custom_client_paths_headers_and_redirect_policy,
        test_custom_runtime_client_construction,
        test_custom_endpoint_normalization_and_sanitization,
        test_custom_endpoint_ui_contract,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("Test passed")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    raise SystemExit(0 if run_tests() else 1)
