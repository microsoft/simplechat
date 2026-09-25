# test_model_endpoint_normalization_backend.py
"""
Functional test for backend model endpoint normalization.
Version: 0.261.042
Implemented in: 0.239.155; schema-v2 normalization and migration in 0.261.041
Editor JSON round-trip coverage added in: 0.261.042

This test ensures model endpoints are normalized with stable IDs and enabled
flags so frontend consumers receive consistent identifiers. It also verifies
per-model response length values remain request allowances, while verified
endpoint/model capacities are normalized independently, reject invalid values,
and preserve explicit null inheritance and existing model metadata.
"""

import copy
import os
import sys
import importlib
import json
import types
from unittest.mock import patch

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
    config_stub.AZURE_ENVIRONMENT = "public"

    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None
    appinsights_stub.debug_print = lambda *args, **kwargs: None
    appinsights_stub.is_debug_enabled = lambda *args, **kwargs: False

    cache_stub = types.ModuleType("app_settings_cache")
    cache_stub.get_settings_cache = lambda: None
    cache_stub.update_settings_cache = lambda settings: None

    content_safety_stub = types.ModuleType("functions_content_safety")
    content_safety_stub.CONTENT_SAFETY_VIOLATION_MESSAGE_DEFAULT = "Content safety policy violation."

    throughput_stub = types.ModuleType("functions_cosmos_throughput")
    throughput_stub.get_default_cosmos_throughput_settings = lambda: {}

    document_actions_stub = types.ModuleType("functions_document_actions")
    document_actions_stub.get_default_document_action_capabilities = lambda: {}

    icon_utils_stub = types.ModuleType("functions_icon_utils")
    icon_utils_stub.normalize_icon_payload = lambda value, field_name="": value if isinstance(value, dict) else {}

    latest_features_stub = types.ModuleType("functions_latest_features_nav")
    latest_features_stub.LATEST_FEATURES_HIDDEN_VERSION_SETTING = "latest_features_hidden_version"

    mcp_stub = types.ModuleType("functions_mcp_server_config")
    mcp_stub.INBOUND_MCP_SETTINGS_DEFAULTS = {}
    mcp_stub.normalize_inbound_mcp_settings = lambda settings: None

    service_health_stub = types.ModuleType("functions_service_health")
    service_health_stub.get_default_service_health = lambda: {}

    support_menu_stub = types.ModuleType("support_menu_config")
    support_menu_stub.get_default_support_latest_features_visibility = lambda: {}
    support_menu_stub.has_visible_support_latest_features = lambda *args, **kwargs: False
    support_menu_stub.normalize_support_latest_features_visibility = lambda settings: None

    original_modules = {}
    for module_name, module_stub in {
        "config": config_stub,
        "functions_appinsights": appinsights_stub,
        "app_settings_cache": cache_stub,
        "functions_content_safety": content_safety_stub,
        "functions_cosmos_throughput": throughput_stub,
        "functions_document_actions": document_actions_stub,
        "functions_icon_utils": icon_utils_stub,
        "functions_latest_features_nav": latest_features_stub,
        "functions_mcp_server_config": mcp_stub,
        "functions_service_health": service_health_stub,
        "support_menu_config": support_menu_stub,
    }.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules["application.single_app.functions_settings"] = sys.modules.get("application.single_app.functions_settings")
    sys.modules.pop("application.single_app.functions_settings", None)
    try:
        module = importlib.import_module("application.single_app.functions_settings")
    except Exception:
        _restore_modules(original_modules)
        raise
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
                    "deploymentName": "gpt-4o",
                    "response_length": "2048"
                },
                {
                    "deploymentName": "gpt-5.6-luna",
                    "responseLength": 0
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
        assert normalized[0]["models"][0]["responseLength"] == 2048
        assert "response_length" not in normalized[0]["models"][0]
        assert "responseLength" not in normalized[0]["models"][1]
        legacy_response_length = functions_settings.normalize_model_response_length_from_model(
            {"max_completion_tokens": "4096"}
        )
        invalid_response_length = functions_settings.normalize_model_response_length_from_model(
            {"responseLength": "not-a-number"}
        )
        assert legacy_response_length == 4096
        assert invalid_response_length is None
    finally:
        _restore_modules(original_modules)

    print("✅ Backend model endpoint normalization passed.")


def _endpoint_with_metadata():
    return {
        "id": "custom-endpoint",
        "name": "Verified custom gateway",
        "enabled": True,
        "provider": "custom",
        "api_type": "openai",
        "connection": {"endpoint": "https://gateway.example"},
        "auth": {"type": "api_key", "api_key": "test-only-key"},
        "capabilities": {"toolCalling": True},
        "operatorMetadata": {"source": "deployment specification"},
        "models": [{
            "id": "deployment-row",
            "modelName": "arbitrary-deployment",
            "enabled": True,
            "responseLength": 1024,
            "capabilities": {"reasoning": False, "structuredOutput": True},
            "reasoning_effort": "none",
            "metadata": {"tags": ["verified"]},
        }],
    }


def test_model_endpoint_capacity_overrides_are_independent_and_idempotent():
    """Normalize real capacities without inventing them from response length."""
    functions_settings, original_modules = _load_functions_settings_module()
    try:
        endpoint = _endpoint_with_metadata()
        endpoint.update({
            "contextWindow": " 10000 ",
            "inputTokenLimit": "8000",
            "outputTokenLimit": "6000",
            "tokenLimitProvider": "custom",
            "outputTokenAccounting": "total_generation",
        })
        endpoint["models"][0].update({
            "contextWindow": "9007199254740991",
            "inputTokenLimit": None,
            "outputTokenLimit": " 4096 ",
            "catalogModelId": " gpt-5.6-terra ",
            "modelVersion": " deployment-snapshot-1 ",
            "tokenLimitProvider": "azure",
            "outputTokenAccounting": "visible_only",
        })
        original = copy.deepcopy(endpoint)
        normalized, changed = functions_settings.normalize_model_endpoints([endpoint])
        repeated, changed_again = functions_settings.normalize_model_endpoints(normalized)

        assert endpoint == original
        assert changed is True
        assert changed_again is False
        assert repeated == normalized
        saved_endpoint = normalized[0]
        saved_model = saved_endpoint["models"][0]
        assert saved_endpoint["contextWindow"] == 10000
        assert saved_endpoint["inputTokenLimit"] == 8000
        assert saved_endpoint["outputTokenLimit"] == 6000
        assert saved_endpoint["inputTokenLimit"] + saved_endpoint["outputTokenLimit"] > saved_endpoint["contextWindow"]
        assert saved_model["contextWindow"] == 9007199254740991
        assert saved_model["inputTokenLimit"] is None
        assert saved_model["outputTokenLimit"] == 4096
        assert saved_model["catalogModelId"] == "gpt-5.6-terra"
        assert saved_model["modelVersion"] == "deployment-snapshot-1"
        assert saved_model["responseLength"] == 1024
        assert saved_model["tokenLimitProvider"] == "azure"
        assert saved_model["outputTokenAccounting"] == "visible_only"
        assert saved_model["capabilities"] == original["models"][0]["capabilities"]
        assert saved_model["reasoning_effort"] == "none"
        assert saved_endpoint["capabilities"] == original["capabilities"]
        assert saved_endpoint["operatorMetadata"] == original["operatorMetadata"]
        saved_model["metadata"]["tags"].append("changed")
        assert endpoint == original
    finally:
        _restore_modules(original_modules)


def test_model_endpoint_capacity_inheritance_does_not_change_legacy_settings():
    """Absent fields stay absent; blank and explicit null remain inheritance."""
    functions_settings, original_modules = _load_functions_settings_module()
    try:
        legacy, _ = functions_settings.normalize_model_endpoints([_endpoint_with_metadata()])
        repeated, changed = functions_settings.normalize_model_endpoints(legacy)
        assert changed is False
        assert repeated == legacy
        for record in (repeated[0], repeated[0]["models"][0]):
            assert not {
                "contextWindow", "inputTokenLimit", "outputTokenLimit",
                "catalogModelId", "modelVersion", "tokenLimitProvider", "outputTokenAccounting",
            }.intersection(record)

        for record in (legacy[0], legacy[0]["models"][0]):
            record.update({
                "contextWindow": "  ",
                "inputTokenLimit": "",
                "outputTokenLimit": None,
                "catalogModelId": "",
                "modelVersion": None,
                "tokenLimitProvider": None,
                "outputTokenAccounting": "",
            })
        inherited, changed = functions_settings.normalize_model_endpoints(legacy)
        for record in (inherited[0], inherited[0]["models"][0]):
            for field_name in (
                "contextWindow", "inputTokenLimit", "outputTokenLimit",
                "catalogModelId", "modelVersion", "tokenLimitProvider", "outputTokenAccounting",
            ):
                assert record[field_name] is None
        assert changed is True
        assert inherited[0]["models"][0]["responseLength"] == 1024
        _, changed_again = functions_settings.normalize_model_endpoints(inherited)
        assert changed_again is False
    finally:
        _restore_modules(original_modules)


def test_model_endpoint_capacity_invalid_values_are_rejected():
    """Invalid explicit capacities must never disappear into a fallback."""
    functions_settings, original_modules = _load_functions_settings_module()
    try:
        invalid_values = (
            True, False, 0, -1, 1.0, 1.5, float("inf"), float("-inf"), float("nan"),
            "0", "-2", "+2", "1.0", "1e3", "1E3", "0x10", "1 000", "1,000",
            "NaN", "Infinity", "１２", 9007199254740992, "9007199254740992", [], {},
        )
        for scope in ("endpoint", "model"):
            for field_name in ("contextWindow", "inputTokenLimit", "outputTokenLimit"):
                for value in invalid_values:
                    endpoint = _endpoint_with_metadata()
                    record = endpoint if scope == "endpoint" else endpoint["models"][0]
                    record[field_name] = value
                    try:
                        functions_settings.normalize_model_endpoints([endpoint])
                    except ValueError:
                        continue
                    raise AssertionError(f"Accepted invalid {scope} {field_name}: {value!r}")

        for field_name, value in (
            ("catalogModelId", True),
            ("catalogModelId", {"model": "gpt-5.6-terra"}),
            ("modelVersion", 20260801),
            ("modelVersion", "snapshot\x00invalid"),
            ("modelVersion", "v" * 257),
            ("tokenLimitProvider", "not-a-provider"),
            ("outputTokenAccounting", "unlimited"),
        ):
            endpoint = _endpoint_with_metadata()
            endpoint["models"][0][field_name] = value
            try:
                functions_settings.normalize_model_endpoints([endpoint])
            except ValueError:
                continue
            raise AssertionError(f"Accepted invalid budget metadata: {field_name}")
    finally:
        _restore_modules(original_modules)


def test_model_endpoint_capacity_clear_survives_merge_and_sanitization():
    """A blank override clears capacity without clearing stored credentials."""
    functions_settings, original_modules = _load_functions_settings_module()
    try:
        endpoint = _endpoint_with_metadata()
        endpoint.update({
            "contextWindow": 16000,
            "inputTokenLimit": 12000,
            "outputTokenLimit": 4000,
            "tokenLimitProvider": "custom",
            "outputTokenAccounting": "total_generation",
        })
        endpoint["models"][0].update({
            "catalogModelId": "gpt-5.6-terra",
            "modelVersion": "deployment-snapshot-1",
            "contextWindow": None,
        })
        existing, _ = functions_settings.normalize_model_endpoints([endpoint])
        previous = copy.deepcopy(existing)
        merged = functions_settings.merge_model_endpoints_with_existing([{
            "id": endpoint["id"],
            "contextWindow": None,
            "inputTokenLimit": "",
            "outputTokenLimit": "2048",
            "tokenLimitProvider": None,
            "outputTokenAccounting": "",
            "auth": {"api_key": ""},
        }], existing)
        normalized, _ = functions_settings.normalize_model_endpoints(merged)
        sanitized = functions_settings.sanitize_model_endpoints_for_frontend(normalized)

        assert existing == previous
        assert normalized[0]["contextWindow"] is None
        assert normalized[0]["inputTokenLimit"] is None
        assert normalized[0]["outputTokenLimit"] == 2048
        assert normalized[0]["tokenLimitProvider"] is None
        assert normalized[0]["outputTokenAccounting"] is None
        assert normalized[0]["auth"]["api_key"] == "test-only-key"
        assert "api_key" not in sanitized[0]["auth"]
        assert sanitized[0]["has_api_key"] is True
        assert sanitized[0]["models"][0]["modelVersion"] == "deployment-snapshot-1"
        assert sanitized[0]["models"][0]["catalogModelId"] == "gpt-5.6-terra"
        assert sanitized[0]["models"][0]["contextWindow"] is None
        assert sanitized[0]["capabilities"] == endpoint["capabilities"]
    finally:
        _restore_modules(original_modules)


def test_model_endpoint_capacity_changed_flag_includes_removed_frontend_markers():
    """Secret-presence display flags are removed even on an otherwise stable record."""
    functions_settings, original_modules = _load_functions_settings_module()
    try:
        normalized, _ = functions_settings.normalize_model_endpoints([_endpoint_with_metadata()])
        normalized[0]["has_api_key"] = True
        cleaned, changed = functions_settings.normalize_model_endpoints(normalized)
        assert changed is True
        assert "has_api_key" not in cleaned[0]
    finally:
        _restore_modules(original_modules)


def _mixed_routing_endpoint():
    endpoint = _endpoint_with_metadata()
    endpoint["routing_schema_version"] = 2
    endpoint["api_type"] = "azure_openai"
    endpoint["connection"]["api_version"] = "2024-01-01"
    endpoint["auth"]["key_vault_secret_name"] = "gateway-reference"
    endpoint["auth"]["api_key_header"] = "Ocp-Apim-Subscription-Key"
    endpoint["auth"]["api_key_prefix"] = ""
    endpoint["identity_header"] = {"enabled": True}
    endpoint["models"] = [
        {"id": "azure", "api_type": "azure_openai", "url_mode": "auto", "api_path": " /azure/team/ ", "deploymentName": "D", "api_version": "2025-01-01-preview"},
        {"id": "openai", "api_type": "openai", "url_mode": "exact", "modelName": "claude-as-openai"},
        {"id": "foundry", "api_type": "azure_openai_v1", "url_mode": "auto", "modelName": "azure-model"},
        {"id": "messages", "api_type": "anthropic", "url_mode": "auto", "modelName": "gpt-as-messages", "anthropic_version": "2023-06-01"},
    ]
    return endpoint


def _expect_value_error(operation, *args, **kwargs):
    try:
        operation(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError("Invalid model configuration was accepted.")


def test_mixed_routing_normalization_and_sanitization():
    settings, originals = _load_functions_settings_module()
    try:
        endpoint = _mixed_routing_endpoint()
        previous = copy.deepcopy(endpoint)
        normalized, changed = settings.normalize_model_endpoints([endpoint])
        repeated, changed_again = settings.normalize_model_endpoints(normalized)
        assert changed and not changed_again
        assert repeated == normalized and endpoint == previous
        models = {model["id"]: model for model in normalized[0]["models"]}
        assert models["azure"]["deploymentName"] == "D"
        assert models["azure"]["api_version"] == "2025-01-01-preview"
        assert models["azure"]["api_path"] == "azure/team"
        assert models["messages"]["modelName"] == "gpt-as-messages"
        assert models["messages"]["anthropic_version"] == "2023-06-01"
        assert models["foundry"]["modelName"] == "azure-model"
        sanitized = settings.sanitize_model_endpoints_for_frontend(normalized)
        assert sanitized[0]["models"] == normalized[0]["models"]
        assert "test-only-key" not in json.dumps(sanitized)
        imported = json.loads(json.dumps(sanitized))
        restored = settings.merge_model_endpoints_with_existing(imported, normalized)
        restored, _ = settings.normalize_model_endpoints(restored)
        assert restored == normalized
        assert restored[0]["auth"]["key_vault_secret_name"] == "gateway-reference"
        assert restored[0]["identity_header"] == normalized[0]["identity_header"]
        assert normalized[0]["auth"] == previous["auth"]
        merged = settings.merge_model_endpoint_payload(normalized[0], {"auth": {"api_key": "", "api_key_prefix": ""}})
        assert merged["auth"]["api_key"] == "test-only-key"
        assert merged["auth"]["api_key_prefix"] == ""
        _expect_value_error(settings.merge_model_endpoint_payload, normalized[0], {"routing_schema_version": 1})
        _expect_value_error(settings.merge_model_endpoint_payload, normalized[0], {"models": [{"id": "azure", "deploymentName": "D"}]})
    finally:
        _restore_modules(originals)


def test_explicit_routing_validation_and_legacy_consumer_boundary():
    settings, originals = _load_functions_settings_module()
    try:
        validation = importlib.import_module("functions_model_endpoint_validation")
        types_module = importlib.import_module("functions_model_endpoint_types")
        endpoint = _mixed_routing_endpoint()
        normalized, _ = settings.normalize_model_endpoints([endpoint])
        with patch.object(validation, "resolve_custom_model_endpoint_addresses", return_value=("93.184.216.34",)):
            validation.validate_custom_model_endpoint(normalized[0])
        selected = normalized[0]["models"][3]
        result = types_module.resolve_model_endpoint_request_model(normalized[0], selected, use_model_routing=True)
        assert result == "gpt-as-messages"
        _expect_value_error(types_module.resolve_model_endpoint_request_model, normalized[0], selected)
        for field, value in (("api_type", "responses"), ("api_type", ""), ("url_mode", "inherit"), ("url_mode", ""), ("api_path", "../other"), ("request_template", {})):
            invalid = copy.deepcopy(endpoint)
            invalid["models"][0][field] = value
            _expect_value_error(settings.normalize_model_endpoints, [invalid])
        for marker in (True, "2", 3, None):
            invalid = copy.deepcopy(endpoint)
            invalid["routing_schema_version"] = marker
            _expect_value_error(settings.normalize_model_endpoints, [invalid])
        invalid = copy.deepcopy(endpoint)
        invalid["models"][1]["id"] = invalid["models"][0]["id"]
        _expect_value_error(settings.normalize_model_endpoints, [invalid])
        blocked = copy.deepcopy(endpoint)
        blocked["connection"]["endpoint"] = "https://localhost"
        _expect_value_error(validation.validate_custom_model_endpoint, blocked)
        legacy = _endpoint_with_metadata()
        legacy["api_type"] = "azure_openai_v1"
        _expect_value_error(validation.validate_custom_model_endpoint, legacy)
    finally:
        _restore_modules(originals)


def test_routing_migration_dry_run_idempotence_and_restore():
    settings, originals = _load_functions_settings_module()
    try:
        for api_type, base, model in (
            ("openai", "https://gateway.example/v1", {"id": "one", "modelName": "model"}),
            ("gemini", "https://gateway.example/v1beta/openai", {"id": "one", "modelName": "gemini"}),
            ("anthropic", "https://gateway.example/v1/messages", {"id": "one", "modelName": "gpt-on-messages"}),
            ("azure_openai", "https://gateway.example", {"id": "one", "deploymentName": "D"}),
        ):
            endpoint = _endpoint_with_metadata()
            endpoint["api_type"] = api_type
            endpoint["connection"] = {"endpoint": base, "api_version": "2024-01-01", "url_mode": "exact" if api_type == "anthropic" else "auto"}
            endpoint["models"] = [model]
            original = copy.deepcopy(endpoint)
            plan = settings.plan_model_endpoint_routing_migration(endpoint, excluded_consumers_present=False)
            assert plan["can_migrate"], plan["issues"]
            assert endpoint == original
            assert plan["backup"]["endpoint"] == original
            candidate = plan["endpoint"]
            assert candidate["routing_schema_version"] == 2
            assert candidate["id"] == endpoint["id"]
            assert candidate["auth"] == endpoint["auth"]
            assert candidate["models"][0]["id"] == "one"
            clients = importlib.import_module("model_endpoint_clients")
            routing = importlib.import_module("functions_model_endpoint_urls")
            actual_route = routing.resolve_model_endpoint_route(candidate, candidate["models"][0])
            if api_type == "anthropic":
                expected_url = clients.normalize_anthropic_messages_url(base, direct_custom=True)
            elif api_type == "azure_openai":
                expected_url = base + "/openai/deployments/D/chat/completions?api-version=2024-01-01"
            else:
                expected_url = clients.resolve_custom_openai_base_url(base, api_type, "auto") + "chat/completions"
            assert actual_route["operation_url"] == expected_url
            again = settings.plan_model_endpoint_routing_migration(candidate, excluded_consumers_present=False)
            assert again["can_migrate"] and again["endpoint"] == candidate
            restored = settings.restore_model_endpoint_routing_backup(candidate, plan["backup"])
            assert restored == original
            modified = copy.deepcopy(candidate)
            modified["name"] = "Later owner edit"
            _expect_value_error(settings.restore_model_endpoint_routing_backup, modified, plan["backup"])
    finally:
        _restore_modules(originals)


def test_routing_migration_requires_review_for_ambiguous_or_shared_records():
    settings, originals = _load_functions_settings_module()
    try:
        endpoint = _endpoint_with_metadata()
        unknown = settings.plan_model_endpoint_routing_migration(endpoint)
        referenced = settings.plan_model_endpoint_routing_migration(endpoint, excluded_consumers_present=True)
        assert not unknown["can_migrate"] and not referenced["can_migrate"]
        assert unknown["endpoint"] is None and referenced["endpoint"] is None
        for path in ("/team", "/team/v1", "/responses"):
            endpoint["connection"]["endpoint"] = "https://gateway.example" + path
            plan = settings.plan_model_endpoint_routing_migration(endpoint, excluded_consumers_present=False)
            assert not plan["can_migrate"] and plan["endpoint"] is None
        endpoint["api_type"] = "unknown"
        plan = settings.plan_model_endpoint_routing_migration(endpoint, excluded_consumers_present=False)
        assert not plan["can_migrate"]
        for suffix in ("?route=team", "#saved", "?", "#", "\n"):
            endpoint = _endpoint_with_metadata()
            endpoint["api_type"] = "anthropic"
            endpoint["connection"] = {"endpoint": "https://gateway.example/v1/messages" + suffix}
            original = copy.deepcopy(endpoint)
            plan = settings.plan_model_endpoint_routing_migration(endpoint, excluded_consumers_present=False)
            assert not plan["can_migrate"] and plan["endpoint"] is None
            assert endpoint == original
        for api_type, field, endpoint_version, model_version in (
            ("azure_openai", "api_version", "2024-01-01", "2025-01-01"),
            ("anthropic", "anthropic_version", "2023-06-01", "2024-06-01"),
        ):
            endpoint = _endpoint_with_metadata()
            endpoint["api_type"] = api_type
            endpoint["connection"] = {"endpoint": "https://gateway.example", field: endpoint_version}
            endpoint["models"] = [{"id": "one", "modelName": "model", "deploymentName": "D", field: model_version}]
            plan = settings.plan_model_endpoint_routing_migration(endpoint, excluded_consumers_present=False)
            assert not plan["can_migrate"] and plan["endpoint"] is None
    finally:
        _restore_modules(originals)


def test_pure_routing_import_boundary(reverse=False):
    modules = (
        "functions_model_endpoint_urls", "functions_model_endpoint_types",
        "functions_model_capabilities", "functions_model_endpoint_validation",
    )
    before = set(sys.modules)
    for module_name in reversed(modules) if reverse else modules:
        importlib.import_module(module_name)
    forbidden = {"config", "functions_settings", "model_endpoint_clients", "functions_model_endpoint_runtime"}
    unexpected = (set(sys.modules) - before) & forbidden
    if unexpected:
        raise AssertionError(f"Pure routing imports crossed the runtime boundary: {sorted(unexpected)}")


def run_tests():
    tests = [
        test_pure_routing_import_boundary,
        test_model_endpoint_normalization_backend,
        test_model_endpoint_capacity_overrides_are_independent_and_idempotent,
        test_model_endpoint_capacity_inheritance_does_not_change_legacy_settings,
        test_model_endpoint_capacity_invalid_values_are_rejected,
        test_model_endpoint_capacity_clear_survives_merge_and_sanitization,
        test_model_endpoint_capacity_changed_flag_includes_removed_frontend_markers,
        test_mixed_routing_normalization_and_sanitization,
        test_explicit_routing_validation_and_legacy_consumer_boundary,
        test_routing_migration_dry_run_idempotence_and_restore,
        test_routing_migration_requires_review_for_ambiguous_or_shared_records,
    ]
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
