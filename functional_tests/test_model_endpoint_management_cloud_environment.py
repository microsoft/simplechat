# test_model_endpoint_management_cloud_environment.py
"""
Functional test for model endpoint management cloud environment normalization.
Version: 0.250.004
Implemented in: 0.250.004

This test ensures model endpoint normalization derives non-editable management
cloud settings from AZURE_ENVIRONMENT and preserves explicit service principal
cross-cloud choices where the UI intentionally exposes the selector.
"""

import copy
import importlib
import json
import os
import sys
import types


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, "application", "single_app")

sys.path.append(ROOT_DIR)
sys.path.append(SINGLE_APP_ROOT)


def restore_modules(original_modules):
    """Restore sys.modules entries changed by the isolated module import."""
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def load_functions_settings_module():
    """Load functions_settings with a minimal config stub to avoid live Azure clients."""
    config_stub = types.ModuleType("config")
    config_stub.json = json
    config_stub.re = __import__("re")
    config_stub.WORD_CHUNK_SIZE = 400
    config_stub.AZURE_ENVIRONMENT = "public"
    config_stub.authority = "https://login.microsoftonline.com"
    config_stub.cognitive_services_scope = "https://cognitiveservices.azure.com/.default"
    config_stub.DOCUMENT_INTELLIGENCE_AUTO_SAMPLE_PAGES_DEFAULT = 2

    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None
    appinsights_stub.debug_print = lambda *args, **kwargs: None
    appinsights_stub.is_debug_enabled = lambda: False

    cache_stub = types.ModuleType("app_settings_cache")
    cache_stub.get_settings_cache = lambda: None
    cache_stub.update_settings_cache = lambda settings: None

    throughput_stub = types.ModuleType("functions_cosmos_throughput")
    throughput_stub.get_default_cosmos_throughput_settings = lambda: {}

    document_actions_stub = types.ModuleType("functions_document_actions")
    document_actions_stub.get_default_document_action_capabilities = lambda: {}

    icon_utils_stub = types.ModuleType("functions_icon_utils")
    icon_utils_stub.normalize_icon_payload = lambda icon, field_name=None: icon or {}

    service_health_stub = types.ModuleType("functions_service_health")
    service_health_stub.get_default_service_health = lambda: {}

    support_menu_stub = types.ModuleType("support_menu_config")
    support_menu_stub.get_default_support_latest_features_visibility = lambda: {}
    support_menu_stub.has_visible_support_latest_features = lambda settings=None: False
    support_menu_stub.normalize_support_latest_features_visibility = lambda settings=None: settings or {}

    original_modules = {}
    for module_name, module_stub in {
        "config": config_stub,
        "functions_appinsights": appinsights_stub,
        "app_settings_cache": cache_stub,
        "functions_cosmos_throughput": throughput_stub,
        "functions_document_actions": document_actions_stub,
        "functions_icon_utils": icon_utils_stub,
        "functions_service_health": service_health_stub,
        "support_menu_config": support_menu_stub,
        "functions_settings": None,
    }.items():
        original_modules[module_name] = sys.modules.get(module_name)
        if module_stub is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = module_stub

    return importlib.import_module("functions_settings"), original_modules


def run_with_environment(functions_settings, environment, authority_value=None, foundry_scope=None):
    """Temporarily update imported config globals used by functions_settings."""
    original_environment = functions_settings.AZURE_ENVIRONMENT
    original_authority = functions_settings.authority
    original_scope = functions_settings.cognitive_services_scope

    functions_settings.AZURE_ENVIRONMENT = environment
    if authority_value is not None:
        functions_settings.authority = authority_value
    if foundry_scope is not None:
        functions_settings.cognitive_services_scope = foundry_scope

    def restore():
        functions_settings.AZURE_ENVIRONMENT = original_environment
        functions_settings.authority = original_authority
        functions_settings.cognitive_services_scope = original_scope

    return restore


def normalize_single_endpoint(functions_settings, endpoint):
    """Normalize one endpoint and return the normalized endpoint and change flag."""
    normalized, changed = functions_settings.normalize_model_endpoints([copy.deepcopy(endpoint)])
    assert len(normalized) == 1
    return normalized[0], changed


def test_managed_identity_uses_government_environment():
    """Managed identity cloud is backend-owned and follows AZURE_ENVIRONMENT."""
    functions_settings, original_modules = load_functions_settings_module()
    restore = run_with_environment(functions_settings, "usgovernment")
    try:
        endpoint, changed = normalize_single_endpoint(functions_settings, {
            "id": "gov-foundry-mi",
            "provider": "new_foundry",
            "enabled": True,
            "auth": {
                "type": "managed_identity",
                "management_cloud": "public",
            },
            "models": [],
        })
    finally:
        restore()
        restore_modules(original_modules)

    assert changed is True
    assert endpoint["auth"]["management_cloud"] == "government"


def test_managed_identity_uses_custom_environment_defaults():
    """Custom cloud inherited by managed identity includes app-level authority and scope."""
    functions_settings, original_modules = load_functions_settings_module()
    restore = run_with_environment(
        functions_settings,
        "custom",
        authority_value="https://login.custom.example",
        foundry_scope="https://ai.custom.example/.default",
    )
    try:
        endpoint, changed = normalize_single_endpoint(functions_settings, {
            "id": "custom-foundry-mi",
            "provider": "aifoundry",
            "enabled": True,
            "auth": {
                "type": "managed_identity",
                "management_cloud": "public",
            },
            "models": [],
        })
    finally:
        restore()
        restore_modules(original_modules)

    assert changed is True
    assert endpoint["auth"]["management_cloud"] == "custom"
    assert endpoint["auth"]["custom_authority"] == "https://login.custom.example"
    assert endpoint["auth"]["foundry_scope"] == "https://ai.custom.example/.default"


def test_service_principal_preserves_explicit_cross_cloud_selection():
    """Foundry service principals can intentionally target a different cloud."""
    functions_settings, original_modules = load_functions_settings_module()
    restore = run_with_environment(functions_settings, "usgovernment")
    try:
        endpoint, changed = normalize_single_endpoint(functions_settings, {
            "id": "public-foundry-sp",
            "provider": "new_foundry",
            "enabled": True,
            "auth": {
                "type": "service_principal",
                "management_cloud": "public",
            },
            "models": [],
        })
    finally:
        restore()
        restore_modules(original_modules)

    assert changed is False
    assert endpoint["auth"]["management_cloud"] == "public"


def test_missing_service_principal_cloud_defaults_to_environment():
    """Blank service principal cloud values still receive a valid environment default."""
    functions_settings, original_modules = load_functions_settings_module()
    restore = run_with_environment(functions_settings, "usgovernment")
    try:
        endpoint, changed = normalize_single_endpoint(functions_settings, {
            "id": "blank-foundry-sp",
            "provider": "new_foundry",
            "enabled": True,
            "auth": {
                "type": "service_principal",
            },
            "models": [],
        })
    finally:
        restore()
        restore_modules(original_modules)

    assert changed is True
    assert endpoint["auth"]["management_cloud"] == "government"


def test_custom_foundry_scope_resolver_requires_configured_scope():
    """Custom cloud resolver fails closed when no custom Foundry scope is configured."""
    functions_settings, original_modules = load_functions_settings_module()
    restore = run_with_environment(
        functions_settings,
        "custom",
        authority_value="https://login.custom.example",
        foundry_scope="",
    )
    try:
        try:
            functions_settings.resolve_model_endpoint_foundry_scope({"management_cloud": "custom"})
        except ValueError as exc:
            assert "Foundry scope is required" in str(exc)
        else:
            raise AssertionError("Expected custom cloud without scope to fail closed.")
    finally:
        restore()
        restore_modules(original_modules)


def run_all_tests():
    """Run all management cloud normalization tests."""
    tests = [
        test_managed_identity_uses_government_environment,
        test_managed_identity_uses_custom_environment_defaults,
        test_service_principal_preserves_explicit_cross_cloud_selection,
        test_missing_service_principal_cloud_defaults_to_environment,
        test_custom_foundry_scope_resolver_requires_configured_scope,
    ]

    for test in tests:
        print(f"Testing {test.__name__}...")
        test()

    print("All model endpoint management cloud normalization tests passed.")


if __name__ == "__main__":
    run_all_tests()