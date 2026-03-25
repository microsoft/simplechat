# test_workspace_multi_endpoints.py
"""
Functional test for workspace multi-endpoint routing.
Version: 0.239.155
Implemented in: 0.239.155

This test ensures that workspace multi-endpoint payloads are sanitized and that
agent payloads accept multi-endpoint selection fields.
"""

import sys
import os
import importlib
import json
import types

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
single_app_root = os.path.join(repo_root, "application", "single_app")
sys.path.append(repo_root)
sys.path.append(single_app_root)

from application.single_app.functions_agent_payload import sanitize_agent_payload


def _restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def _load_functions_settings_module():
    config_stub = types.ModuleType("config")
    config_stub.json = json

    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None

    cache_stub = types.ModuleType("app_settings_cache")
    cache_stub.get_settings_cache = lambda: None
    cache_stub.update_settings_cache = lambda settings: None

    original_modules = {}
    for module_name, module_stub in {
        "config": config_stub,
        "functions_appinsights": appinsights_stub,
        "app_settings_cache": cache_stub,
    }.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules["application.single_app.functions_settings"] = sys.modules.get("application.single_app.functions_settings")
    sys.modules.pop("application.single_app.functions_settings", None)
    module = importlib.import_module("application.single_app.functions_settings")
    return module, original_modules


def test_model_endpoint_sanitization():
    """Ensure secrets are stripped and flags are preserved."""
    functions_settings, original_modules = _load_functions_settings_module()
    endpoints = [
        {
            "id": "endpoint-1",
            "name": "Personal Endpoint",
            "provider": "aoai",
            "auth": {
                "type": "api_key",
                "api_key": "super-secret"
            },
            "connection": {
                "endpoint": "https://example.openai.azure.com",
                "openai_api_version": "2024-05-01-preview"
            },
            "models": [
                {"id": "model-1", "deploymentName": "gpt-4o", "enabled": True}
            ]
        }
    ]
    try:
        sanitized = functions_settings.sanitize_model_endpoints_for_frontend(endpoints)
        assert sanitized[0]["auth"].get("api_key") is None
        assert sanitized[0]["has_api_key"] is True

        service_principal_endpoints = [
            {
                "id": "endpoint-2",
                "name": "Foundry Endpoint",
                "provider": "aifoundry",
                "auth": {
                    "type": "service_principal",
                    "client_secret": "client-secret-value"
                },
                "connection": {
                    "endpoint": "https://foundry.example.azure.com",
                    "openai_api_version": "2024-05-01-preview"
                },
                "models": []
            }
        ]
        sanitized_sp = functions_settings.sanitize_model_endpoints_for_frontend(service_principal_endpoints)
        assert sanitized_sp[0]["auth"].get("client_secret") is None
        assert sanitized_sp[0]["has_client_secret"] is True
    finally:
        _restore_modules(original_modules)


def test_agent_payload_multi_endpoint_fields():
    """Ensure agent payload accepts multi-endpoint selection fields."""
    agent_payload = {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "name": "workspace_agent",
        "display_name": "Workspace Agent",
        "description": "Test agent",
        "instructions": "Be helpful",
        "actions_to_load": [],
        "other_settings": {},
        "max_completion_tokens": 256,
        "agent_type": "local",
        "is_global": False,
        "is_group": False,
        "model_endpoint_id": "endpoint-1",
        "model_id": "model-1",
        "model_provider": "aoai",
        "azure_openai_gpt_deployment": "gpt-4o"
    }
    sanitized = sanitize_agent_payload(agent_payload)
    assert sanitized.get("model_endpoint_id") == "endpoint-1"
    assert sanitized.get("model_id") == "model-1"
    assert sanitized.get("model_provider") == "aoai"


def run_tests():
    tests = [test_model_endpoint_sanitization, test_agent_payload_multi_endpoint_fields]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
            print("✅ Test passed")
            results.append(True)
        except Exception as exc:
            print(f"❌ Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    return success


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
