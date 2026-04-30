# test_model_endpoint_normalization_backend.py
"""
Functional test for backend model endpoint normalization.
Version: 0.239.155
Implemented in: 0.239.155

This test ensures model endpoints are normalized with stable IDs and enabled
flags so frontend consumers receive consistent identifiers.
"""

import os
import sys
import importlib
import json
import types

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
single_app_root = os.path.join(repo_root, "application", "single_app")
sys.path.append(repo_root)
sys.path.append(single_app_root)


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


def test_model_endpoint_normalization_backend():
    """Ensure IDs and enabled flags are normalized on backend."""
    print("🔍 Validating backend model endpoint normalization...")
    functions_settings, original_modules = _load_functions_settings_module()

    endpoints = [
        {
            "name": "Foundry Endpoint",
            "has_api_key": True,
            "has_client_secret": True,
            "connection": {"endpoint": "https://foundry.example"},
            "models": [
                {
                    "deploymentName": "gpt-4o"
                }
            ]
        }
    ]

    try:
        normalized, changed = functions_settings.normalize_model_endpoints(endpoints)

        assert changed is True
        assert normalized[0]["id"] == "Foundry Endpoint"
        assert normalized[0]["enabled"] is True
        assert "has_api_key" not in normalized[0]
        assert "has_client_secret" not in normalized[0]
        assert normalized[0]["models"][0]["id"] == "gpt-4o"
        assert normalized[0]["models"][0]["enabled"] is True
    finally:
        _restore_modules(original_modules)

    print("✅ Backend model endpoint normalization passed.")


def run_tests():
    tests = [test_model_endpoint_normalization_backend]
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
    success = run_tests()
    sys.exit(0 if success else 1)
