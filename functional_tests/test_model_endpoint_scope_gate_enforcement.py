# test_model_endpoint_scope_gate_enforcement.py
#!/usr/bin/env python3
"""
Functional test for user and group model endpoint scope enforcement.
Version: 0.261.046
Implemented in: 0.239.187

Schema-v2 preview authorization and no-I/O coverage added in: 0.261.042
Schema-v2 live model-test coverage added in: 0.261.044
Vision actor and canonical transport-policy coverage added in: 0.261.045
Saved credential-scope fallback coverage added in: 0.261.046

This test ensures non-admin model fetch and test routes require the
custom-endpoint feature gates while still allowing pre-save fetch/test
requests and restricting persisted endpoint IDs to authorized endpoints.
"""

import ast
import copy
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask, jsonify, request

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from functions_model_endpoint_urls import normalize_model_endpoint_routing, resolve_model_endpoint_route, routing_schema_version


def test_routing_preview_authorization_and_no_dispatch():
    source = ast.parse((APP_ROOT / "route_backend_models.py").read_text(encoding="utf-8"))
    registrar = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_models")
    names = {"handle_test_model_connection", "handle_model_routing_preview", "build_safe_error_response"}
    nodes = [node for node in registrar.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names), "The authorized, no-dispatch preview branch is missing."
    forbidden = Mock(side_effect=AssertionError("Preview must not resolve secrets or dispatch."))
    lookup = Mock(return_value={"id": "saved"})
    governance = Mock()
    settings = {"enable_multi_model_endpoints": True, "allow_user_custom_endpoints": True, "allow_group_custom_endpoints": True}
    namespace = {
        "request": request, "jsonify": jsonify,
        "get_settings": lambda: settings,
        "get_current_user_id": lambda: "actor",
        "ensure_governance_access": governance,
        "resolve_endpoint_by_id": lookup,
        "normalize_model_endpoint_routing": normalize_model_endpoint_routing,
        "resolve_model_endpoint_route": resolve_model_endpoint_route,
        "routing_schema_version": routing_schema_version,
        "resolve_request_endpoint_payload": forbidden,
        "build_inference_client": forbidden,
        "log_models_exception": Mock(), "log_event": Mock(),
        "logging": __import__("logging"),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<routing-preview>", "exec"), namespace)
    app = Flask(__name__)
    payload = {
        "id": "saved", "routing_schema_version": 2, "preview_only": True,
        "provider": "custom", "connection": {"endpoint": "https://gateway.example/shared"},
        "auth": {"api_key": "must-not-echo", "key_vault_reference": "must-not-echo"},
        "model": {"id": "one", "modelName": "not-an-anthropic-model", "api_type": "anthropic", "api_path": "team", "url_mode": "auto"},
    }
    for scope in ("global", "user", "group"):
        with app.test_request_context(json=payload):
            response, status = namespace["handle_test_model_connection"](scope)
        assert status == 200
        body = response.get_json()
        assert body["preview_only"] is True
        assert body["resolved"]["operation_url"] == "https://gateway.example/team/shared/v1/messages"
        assert body["resolved"]["method"] == "POST"
        assert "must-not-echo" not in response.get_data(as_text=True)
        lookup.assert_called_with("actor", scope, "saved")
        governance.assert_any_call(f"governance_{scope}_endpoints", "actor")
    forbidden.assert_not_called()
    for field, value in (("api_path", "../escape"), ("api_type", "responses"), ("url_mode", "inherit")):
        invalid = copy.deepcopy(payload)
        invalid["model"][field] = value
        with app.test_request_context(json=invalid):
            response, status = namespace["handle_test_model_connection"]("user")
        assert status == 400
        assert value not in response.get_data(as_text=True)
    lookup.return_value = None
    with app.test_request_context(json=payload):
        response, status = namespace["handle_test_model_connection"]("user")
    assert status == 404
    lookup.return_value = {"id": "saved"}
    governance.side_effect = PermissionError("private detail")
    with app.test_request_context(json=payload):
        response, status = namespace["handle_test_model_connection"]("group")
    assert status == 403
    assert "private detail" not in response.get_data(as_text=True)
    governance.side_effect = None
    settings["allow_user_custom_endpoints"] = False
    with app.test_request_context(json=payload):
        response, status = namespace["handle_test_model_connection"]("user")
    assert status == 403
    forbidden.assert_not_called()


def test_schema_v2_live_connection_uses_saved_endpoint_route():
    source = ast.parse((APP_ROOT / "route_backend_models.py").read_text(encoding="utf-8"))
    registrar = next(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_models")
    names = {
        "handle_test_model_connection", "handle_explicit_model_test",
        "handle_model_routing_preview", "build_safe_error_response",
        "resolve_endpoint_by_id", "resolve_scoped_model_endpoints",
    }
    nodes = [node for node in registrar.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(nodes) == len(names), "Live schema-v2 model-test dispatch is not implemented."

    saved_endpoint = {
        "id": "endpoint-1", "name": "Verified gateway", "provider": "custom",
        "routing_schema_version": 2, "enabled": True,
        "connection": {"endpoint": "https://gateway.example/shared/v1"},
        "auth": {"type": "api_key", "api_key": "must-not-echo"},
        "models": [{
            "id": "model-1", "enabled": True, "api_type": "openai",
            "api_path": "team", "url_mode": "auto", "modelName": "claude-as-openai",
        }],
    }
    settings = {
        "enable_multi_model_endpoints": True,
        "allow_user_custom_endpoints": True,
        "allow_group_custom_endpoints": True,
        "allow_insecure_custom_model_endpoints": True,
    }
    requests = []
    builder_calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))

    scoped_endpoints = {scope: [saved_endpoint] for scope in ("user", "group")}
    settings["model_endpoints"] = [saved_endpoint]
    secret_lookup = Mock(side_effect=lambda endpoint, *_args, **_kwargs: endpoint)
    governance = Mock()

    def validate_routing(endpoint, policy, *, require_resolvable=False):
        assert policy is settings
        return [resolve_model_endpoint_route(endpoint, model) for model in endpoint["models"]]

    def build_client(**kwargs):
        assert kwargs["allow_insecure_custom_endpoints"] is True
        builder_calls.append(kwargs)
        return client, kwargs["resolved_route"]["protocol"]

    log_exception = Mock()
    namespace = {
        "request": request, "jsonify": jsonify,
        "get_settings": lambda: settings,
        "get_current_user_id": lambda: "actor",
        "get_user_settings": lambda _user: {"settings": {"personal_model_endpoints": scoped_endpoints["user"]}},
        "get_group_model_endpoints": lambda _group: scoped_endpoints["group"],
        "require_active_group": lambda _user: "active-group",
        "ensure_governance_access": governance,
        "keyvault_model_endpoint_get_helper": secret_lookup,
        "SecretReturnType": SimpleNamespace(VALUE="value"),
        "normalize_model_endpoint_routing": normalize_model_endpoint_routing,
        "resolve_model_endpoint_route": resolve_model_endpoint_route,
        "routing_schema_version": routing_schema_version,
        "validate_model_endpoint_routing": validate_routing,
        "validate_custom_model_endpoint": lambda *_args, **_kwargs: None,
        "build_model_endpoint_sync_chat_client": build_client,
        "MODEL_ENDPOINT_PROVIDER_CUSTOM": "custom",
        "DEFAULT_ANTHROPIC_VERSION": "2023-06-01",
        "build_safe_error_response": lambda message, status: (jsonify({"error": message}), status),
        "log_models_exception": log_exception, "log_event": Mock(), "logging": __import__("logging"),
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<model-test-routing>", "exec"), namespace)
    app = Flask(__name__)
    payload = {
        "id": "endpoint-1", "routing_schema_version": 2, "model_id": "model-1",
        "connection": {"endpoint": "https://gateway.example/shared/v1"},
        "model": {
            "id": "model-1", "api_type": "openai", "api_path": "team",
            "url_mode": "auto", "modelName": "claude-as-openai",
        },
    }

    for scope in ("global", "user", "group"):
        with app.test_request_context(json=payload):
            response, status = namespace["handle_test_model_connection"](scope)
        assert status == 200, f"{response.get_data(as_text=True)}; captured={log_exception.call_args!r}"
        assert builder_calls[-1]["resolved_route"]["api_type"] == "openai"
        assert builder_calls[-1]["resolved_route"]["operation_url"] == (
            "https://gateway.example/team/shared/v1/chat/completions"
        )
        assert builder_calls[-1]["auth_settings"]["api_key"] == "must-not-echo"
        assert requests[-1]["model"] == "claude-as-openai"
        assert "must-not-echo" not in response.get_data(as_text=True)
        assert secret_lookup.call_args.kwargs["scope"] == scope

    assert len(builder_calls) == 3
    assert len(requests) == 3

    saved_endpoint["enabled"] = False
    saved_endpoint["models"][0]["enabled"] = False
    with app.test_request_context(json=payload):
        response, status = namespace["handle_test_model_connection"]("global")
    assert status == 200, "Authorized one-off model tests should be available before activation."
    assert len(builder_calls) == 4

    stale_payload = copy.deepcopy(payload)
    stale_payload["model"]["api_path"] = "client-override"
    calls_before_stale_test = len(builder_calls)
    with app.test_request_context(json=stale_payload):
        response, status = namespace["handle_test_model_connection"]("global")
    assert status == 409
    assert len(builder_calls) == calls_before_stale_test, "Unsaved routing must not reach an inference client."

    scoped_endpoints.update(user=[], group=[])
    for scope in ("user", "group"):
        with app.test_request_context(json=payload):
            response, status = namespace["handle_test_model_connection"](scope)
        assert status == 200, response.get_json()
        assert secret_lookup.call_args.kwargs["scope"] == "global"
        governance.assert_any_call(
            "governance_global_endpoints", "actor",
            item_entity_type="global_endpoint", item_id="endpoint-1",
        )


def test_multimodal_vision_test_uses_schema_v2_route_and_capability():
    source = ast.parse((APP_ROOT / "route_backend_settings.py").read_text(encoding="utf-8"))
    vision_test = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "_test_multimodal_vision_connection"
    )
    endpoint = {
        "id": "vision-endpoint", "provider": "custom", "routing_schema_version": 2,
        "connection": {"endpoint": "https://gateway.example/shared/v1"},
        "auth": {"api_key": "server-secret"},
            "capabilities": {"processesImages": True},
        "models": [{
            "id": "vision-model", "enabled": True, "api_type": "openai",
            "api_path": "vision-team", "url_mode": "auto",
            "modelName": "gpt-4o-vision", "capabilities": {"processesImages": True},
        }],
    }
    route = resolve_model_endpoint_route(endpoint, endpoint["models"][0])
    endpoint["_resolved_route"] = route
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="red"))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    context_resolver = Mock(return_value=endpoint)
    namespace = {
        "jsonify": jsonify,
        "get_settings": lambda: {"model_endpoints": [endpoint]},
        "get_current_user_id": lambda: "admin-user",
        "resolve_model_endpoint_from_context": context_resolver,
        "routing_schema_version": routing_schema_version,
        "build_model_endpoint_sync_chat_client": lambda *_args, **kwargs: (
            calls.append({"route": kwargs["resolved_route"]}) or client,
            kwargs["resolved_route"]["protocol"],
        ),
        "resolve_model_endpoint_request_model": lambda *_args, **_kwargs: "legacy-model",
        "get_model_endpoint_api_type": lambda *_args, **_kwargs: "openai",
        "build_model_endpoint_identity_headers": lambda *_args, **_kwargs: {},
        "DefaultAzureCredential": object,
        "get_bearer_token_provider": lambda *_args, **_kwargs: None,
        "AzureOpenAI": object,
        "cognitive_services_scope": "scope",
        "log_event": Mock(),
        "logging": __import__("logging"),
    }
    exec(compile(ast.Module(body=[vision_test], type_ignores=[]), "<vision-route-test>", "exec"), namespace)
    payload = {
        "vision_model": "gpt-4o-vision",
        "multi_endpoint": {
            "endpoint_id": "vision-endpoint", "model_id": "vision-model",
            "provider": "custom", "deployment_name": "client-override",
        },
    }
    app = Flask(__name__)
    with app.app_context():
        response, status = namespace["_test_multimodal_vision_connection"](payload)
        assert status == 200, response.get_json()
        assert context_resolver.call_args.args[1]["user_id"] == "admin-user"
        assert calls[0]["route"] == route
        assert calls[1]["model"] == route["request_model"]
        assert response.get_json()["details"] == "Model responded: red"

        endpoint["_resolved_route"]["capabilities"]["processesImages"] = False
        calls.clear()
        response, status = namespace["_test_multimodal_vision_connection"](payload)
        assert status == 400
        assert not calls, "Vision capability denial must occur before client construction or dispatch."


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_model_endpoint_scope_gate_enforcement():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    backend_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_models.py')

    backend_content = read_file_text(backend_path)

    assert 'if scope in ("user", "group") and endpoint_id:' in backend_content, (
        "User/group persisted endpoint validation should only apply when an endpoint_id is supplied."
    )
    assert "raise LookupError(\"Model endpoint not found.\")" in backend_content, (
        "User/group model routes must reject unknown endpoint IDs."
    )
    assert 'merge_model_endpoint_payload(persisted_endpoint or {}, payload)' in backend_content, (
        "Feature-gated user/group model routes should still accept ad hoc payloads for pre-save fetch/test flows."
    )
    assert 'merge_model_endpoint_payload(persisted_endpoint, {})' in backend_content, (
        "User/group requests that reference a saved endpoint must resolve persisted endpoint configuration."
    )
    assert "@enabled_required('allow_user_custom_endpoints')\n    def fetch_model_list_user():" in backend_content, (
        "User model fetch route must require allow_user_custom_endpoints."
    )
    assert "@enabled_required('allow_user_custom_endpoints')\n    def test_model_connection_user():" in backend_content, (
        "User model test route must require allow_user_custom_endpoints."
    )
    assert "@enabled_required('allow_group_custom_endpoints')\n    def fetch_model_list_group():" in backend_content, (
        "Group model fetch route must require allow_group_custom_endpoints."
    )
    assert "@enabled_required('allow_group_custom_endpoints')\n    def test_model_connection_group():" in backend_content, (
        "Group model test route must require allow_group_custom_endpoints."
    )

    print("✅ Model endpoint scope gates, pre-save fetch/test flow, and persisted-endpoint enforcement verified.")


if __name__ == "__main__":
    test_model_endpoint_scope_gate_enforcement()
    test_routing_preview_authorization_and_no_dispatch()
    test_schema_v2_live_connection_uses_saved_endpoint_route()
    test_multimodal_vision_test_uses_schema_v2_route_and_capability()