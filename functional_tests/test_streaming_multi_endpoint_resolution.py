# test_streaming_multi_endpoint_resolution.py
#!/usr/bin/env python3
"""
Functional test for streaming multi-endpoint model resolution.
Version: 0.261.046
Implemented in: 0.239.200; updated in 0.250.109; schema-v2 streaming dispatch in 0.261.044
Real wrapper TLS-policy and agent-default regression coverage added in: 0.261.045
Non-agent default resolution coverage added in: 0.261.046

This test ensures streaming requests resolve selected models by endpoint and
model identifiers, hydrate saved endpoint auth, and build provider-aware
clients for Azure OpenAI and Foundry selections. It also verifies the selected
model's response length is resolved and applied to chat completion params.
"""

import ast
import copy
import os
import sys
from pathlib import Path
from types import SimpleNamespace

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

from functions_model_endpoint_urls import normalize_model_endpoint_routing, resolve_model_endpoint_route
from functions_model_endpoint_types import get_model_endpoint_api_type, resolve_model_endpoint_request_model
from model_endpoint_clients import ModelEndpointBehavior, infer_model_endpoint_protocol


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


def test_streaming_multi_endpoint_resolution_wiring():
    """Verify the streaming route resolves selected models from endpoint metadata."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    chat_path = os.path.join(repo_root, 'application', 'single_app', 'route_backend_chats.py')

    content = read_file_text(chat_path)

    assert "frontend_model_id = data.get('model_id')" in content, (
        'Expected streaming payload parsing to capture model_id.'
    )
    assert "frontend_model_endpoint_id = data.get('model_endpoint_id')" in content, (
        'Expected streaming payload parsing to capture model_endpoint_id.'
    )
    assert "frontend_model_provider = data.get('model_provider')" in content, (
        'Expected streaming payload parsing to capture model_provider.'
    )
    assert 'def resolve_foundry_scope_for_auth(' in content, (
        'Expected streaming route helpers to include Foundry scope resolution.'
    )
    assert 'def build_streaming_multi_endpoint_client(' in content, (
        'Expected streaming route helpers to build provider-aware inference clients.'
    )
    assert 'def resolve_streaming_multi_endpoint_gpt_config(' in content, (
        'Expected streaming route helpers to resolve endpoint/model selections.'
    )
    assert 'keyvault_model_endpoint_get_helper(' in content, (
        'Expected streaming model resolution to hydrate stored secrets before inference.'
    )
    assert 'streaming_multi_endpoint_config = resolve_streaming_multi_endpoint_gpt_config(' in content, (
        'Expected /api/chat/stream to resolve models from endpoint/model ids before fallback.'
    )
    assert 'active_group_ids=active_group_ids' in content, (
        'Expected streaming group context to be supplied when resolving scoped model endpoints.'
    )
    assert 'model_response_length = normalize_model_response_length_from_model(model_cfg)' in content, (
        'Expected model endpoint resolution to read per-model response length.'
    )
    assert 'gpt_response_length' in content, (
        'Expected resolved response length to flow through chat generation state.'
    )
    assert '_apply_response_length_for_model(' in content, (
        'Expected chat completion params to apply per-model response length.'
    )
    assert 'response_length_parameter = response_length_parameter or ModelEndpointBehavior(provider, model_name).response_length_parameter' in content, (
        'Expected model behavior helper to choose max_tokens vs max_completion_tokens.'
    )
    assert 'gpt_response_length_parameter' in content, (
        'Expected resolved response length parameter to flow through chat generation state.'
    )
    assert '_build_model_endpoint_behavior_name(model_cfg, deployment)' in content, (
        'Expected parameter selection to consider model display/model/deployment aliases.'
    )

    print('✅ Streaming multi-endpoint model resolution wiring verified.')


def test_schema_v2_streaming_uses_model_route_and_excludes_agents():
    source = ast.parse((APP_ROOT / "route_backend_chats.py").read_text(encoding="utf-8"))
    resolver = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "resolve_streaming_multi_endpoint_gpt_config"
    )
    wrapper = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_streaming_multi_endpoint_client"
    )
    endpoint = {
        "id": "endpoint-1", "name": "Verified gateway", "provider": "custom",
        "routing_schema_version": 2, "enabled": True,
        "connection": {"endpoint": "https://gateway.example/shared/v1"},
        "auth": {"type": "api_key", "api_key": "test-key"},
        "models": [{
            "id": "model-1", "enabled": True, "api_type": "openai",
            "api_path": "aoai-team", "url_mode": "auto", "modelName": "claude-as-openai",
        }],
    }
    settings = {
        "enable_multi_model_endpoints": True,
        "allow_insecure_custom_model_endpoints": True,
        "custom_model_endpoint_ca_bundle_path": "configured-ca.pem",
    }
    resolved_routes = []

    def validate_routing(saved_endpoint, _settings, *, require_resolvable=False):
        return [
            resolve_model_endpoint_route(saved_endpoint, saved_model)
            for saved_model in saved_endpoint["models"]
        ]

    def build_client(*_args, **kwargs):
        resolved_routes.append(kwargs.get("resolved_route"))
        assert kwargs["allow_insecure_custom_endpoints"] is True
        assert kwargs["custom_endpoint_ca_bundle_path"] == "configured-ca.pem"
        return object(), "openai_style"

    namespace = {
        "settings": settings,
        "get_streaming_model_endpoint_candidates": lambda *_args, **_kwargs: [copy.deepcopy(endpoint)],
        "keyvault_model_endpoint_get_helper": lambda saved_endpoint, *_args, **_kwargs: saved_endpoint,
        "SecretReturnType": SimpleNamespace(VALUE="value"),
        "normalize_model_endpoints": lambda values: (values, False),
        "routing_schema_version": __import__("functions_model_endpoint_urls").routing_schema_version,
        "resolve_model_endpoint_route": resolve_model_endpoint_route,
        "validate_model_endpoint_routing": validate_routing,
        "normalize_model_endpoint_routing": normalize_model_endpoint_routing,
        "resolve_model_endpoint_request_model": resolve_model_endpoint_request_model,
        "get_model_endpoint_api_type": get_model_endpoint_api_type,
        "infer_model_endpoint_protocol": infer_model_endpoint_protocol,
        "ModelEndpointBehavior": ModelEndpointBehavior,
        "_normalize_model_icon_payload": lambda value: value,
        "normalize_model_response_length_from_model": lambda _model: None,
        "_build_model_endpoint_behavior_name": lambda _model, deployment: deployment,
        "build_model_endpoint_sync_chat_client": build_client,
        "MODEL_ENDPOINT_PROVIDER_ALLOWLIST": {"custom", "aoai", "aifoundry", "new_foundry", "anthropic", "claude"},
        "MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI": "azure_openai",
        "debug_print": lambda *_args, **_kwargs: None,
        "validate_custom_model_endpoint": lambda *_args, **_kwargs: None,
    }
    exec(compile(ast.Module(body=[wrapper, resolver], type_ignores=[]), "<stream-route-resolution>", "exec"), namespace)
    request = {
        "model_endpoint_id": "endpoint-1", "model_id": "model-1",
        "model_provider": "anthropic", "model_deployment": "client-override",
    }
    result = namespace["resolve_streaming_multi_endpoint_gpt_config"](
        settings, request, "actor", active_group_ids=[],
    )
    expected_route = resolve_model_endpoint_route(endpoint, endpoint["models"][0])
    assert result[1] == "claude-as-openai"
    assert result[2] == "custom"
    assert result[6] == "openai"
    assert resolved_routes == [expected_route]
    assert expected_route["protocol"] == "openai_style"

    try:
        namespace["resolve_streaming_multi_endpoint_gpt_config"](
            settings,
            {**request, "agent_info": {"agent_id": "legacy-agent"}},
            "actor",
            active_group_ids=[],
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Schema-v2 routing must not be enabled for agent requests.")
    assert resolved_routes == [expected_route]

    settings["default_model_selection"] = {"endpoint_id": "endpoint-1", "model_id": "model-1"}
    legacy_fallback = namespace["resolve_streaming_multi_endpoint_gpt_config"](
        settings,
        {"agent_info": {"agent_id": "legacy-agent"}},
        "actor",
        active_group_ids=[],
        allow_default_selection=True,
    )
    assert legacy_fallback is None
    assert resolved_routes == [expected_route]

    default_result = namespace["resolve_streaming_multi_endpoint_gpt_config"](
        settings, {}, "actor", active_group_ids=[], allow_default_selection=True,
    )
    assert default_result is not None
    assert default_result[1] == expected_route["request_model"]
    assert resolved_routes == [expected_route, expected_route]


def test_group_endpoint_candidates_recheck_membership_before_read():
    source = ast.parse((APP_ROOT / "route_backend_chats.py").read_text(encoding="utf-8"))
    candidate_loader = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_streaming_model_endpoint_candidates"
    )
    group_endpoint = {"id": "group-endpoint", "provider": "custom", "enabled": True}
    group_reads = []
    role_checks = []
    governance_checks = []
    allowed = [False]

    def assert_group_role(user_id, group_id, *, allowed_roles):
        role_checks.append((user_id, group_id, allowed_roles))
        if not allowed[0]:
            raise PermissionError("Membership was revoked.")
        return "User"

    def ensure_governance_access(feature, user_id, **kwargs):
        governance_checks.append((feature, user_id, kwargs))

    def read_group_endpoints(group_id):
        group_reads.append(group_id)
        return [copy.deepcopy(group_endpoint)]

    namespace = {
        "get_user_settings": lambda _user_id: {"settings": {}},
        "normalize_model_endpoints": lambda values: (values, False),
        "ensure_governance_access": ensure_governance_access,
        "assert_group_role": assert_group_role,
        "get_group_model_endpoints": read_group_endpoints,
        "debug_print": lambda *_args, **_kwargs: None,
    }
    exec(compile(ast.Module(body=[candidate_loader], type_ignores=[]), "<stream-scope-check>", "exec"), namespace)
    settings = {"allow_group_custom_endpoints": True, "model_endpoints": []}
    assert namespace["get_streaming_model_endpoint_candidates"](
        settings, "actor", active_group_ids=["group-1"]
    ) == []
    assert role_checks == [("actor", "group-1", ("Owner", "Admin", "DocumentManager", "User"))]
    assert group_reads == [], "Revoked group membership must be checked before reading endpoint data."

    allowed[0] = True
    candidates = namespace["get_streaming_model_endpoint_candidates"](
        settings, "actor", active_group_ids=["group-1"]
    )
    assert len(candidates) == 1
    assert candidates[0]["_endpoint_scope"] == "group"
    assert candidates[0]["_endpoint_scope_id"] == "group-1"
    assert group_reads == ["group-1"]
    assert (
        "governance_group_endpoints", "actor",
        {"item_entity_type": "global_endpoint", "item_id": "group-endpoint"},
    ) in governance_checks


def run_tests():
    tests = [
        test_streaming_multi_endpoint_resolution_wiring,
        test_schema_v2_streaming_uses_model_route_and_excludes_agents,
        test_group_endpoint_candidates_recheck_membership_before_read,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print('✅ Test passed')
            results.append(True)
        except Exception as exc:
            print(f'❌ Test failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == '__main__':
    raise SystemExit(0 if run_tests() else 1)