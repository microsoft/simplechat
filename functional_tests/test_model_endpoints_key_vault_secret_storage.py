# test_model_endpoints_key_vault_secret_storage.py
#!/usr/bin/env python3
"""
Functional test for MultiGPT endpoint Key Vault secret storage.
Version: 0.261.125
Implemented in: 0.241.179
Strict screening credential hydration and safe retrieval logging: 0.261.106
Custom credential strict hydration merge coverage: 0.261.113
Actionable secret-write errors and explicit diagnostic credentials: 0.261.125

This test ensures MultiGPT endpoint secrets are stored in Key Vault,
returned to the UI as placeholders, resolved for backend use, and cleaned up
when endpoint auth settings change. It also verifies saved endpoint edits can
reuse stored API keys and client secrets without requiring the user to retype
the secret.
"""

import importlib
import os
import sys
import types
from unittest.mock import Mock, patch

import pytest
from azure.core.exceptions import HttpResponseError


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SINGLE_APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
sys.path.insert(0, SINGLE_APP_ROOT)
sys.path.insert(0, REPO_ROOT)


class FakeRetrievedSecret:
    def __init__(self, value):
        self.value = value


class FakeSecretClient:
    stored_secrets = {}
    deleted_secrets = []

    def __init__(self, vault_url, credential):
        self.vault_url = vault_url
        self.credential = credential

    @classmethod
    def reset(cls):
        cls.stored_secrets = {}
        cls.deleted_secrets = []

    def set_secret(self, name, value):
        FakeSecretClient.stored_secrets[name] = value

    def get_secret(self, name):
        return FakeRetrievedSecret(FakeSecretClient.stored_secrets[name])

    def begin_delete_secret(self, name):
        FakeSecretClient.deleted_secrets.append(name)
        FakeSecretClient.stored_secrets.pop(name, None)


def restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def load_functions_keyvault_module():
    config_stub = types.ModuleType("config")
    config_stub.KEY_VAULT_DOMAIN = ".vault.azure.net"

    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None

    auth_stub = types.ModuleType("functions_authentication")
    settings_stub = types.ModuleType("functions_settings")

    app_settings_cache_stub = types.ModuleType("app_settings_cache")
    app_settings_cache_stub.get_settings_cache = lambda: {
        "enable_key_vault_secret_storage": True,
        "key_vault_name": "unit-test-vault",
        "key_vault_identity": None,
    }

    azure_stub = types.ModuleType("azure")
    identity_stub = types.ModuleType("azure.identity")
    keyvault_stub = types.ModuleType("azure.keyvault")
    secrets_stub = types.ModuleType("azure.keyvault.secrets")

    class FakeDefaultAzureCredential:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    identity_stub.DefaultAzureCredential = FakeDefaultAzureCredential
    secrets_stub.SecretClient = FakeSecretClient
    azure_stub.identity = identity_stub
    azure_stub.keyvault = keyvault_stub
    keyvault_stub.secrets = secrets_stub

    original_modules = {}
    module_stubs = {
        "config": config_stub,
        "functions_appinsights": appinsights_stub,
        "functions_authentication": auth_stub,
        "functions_settings": settings_stub,
        "app_settings_cache": app_settings_cache_stub,
        "azure": azure_stub,
        "azure.identity": identity_stub,
        "azure.keyvault": keyvault_stub,
        "azure.keyvault.secrets": secrets_stub,
    }

    for module_name, module_stub in module_stubs.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules["functions_keyvault"] = sys.modules.get("functions_keyvault")
    sys.modules.pop("functions_keyvault", None)

    module = importlib.import_module("functions_keyvault")
    return module, original_modules


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def test_denied_secret_write_is_actionable_without_plaintext_fallback():
    FakeSecretClient.reset()
    module, original_modules = load_functions_keyvault_module()
    denied = HttpResponseError(message="private provider details: synthetic-secret")
    denied.status_code = 403
    endpoint = {"id": "endpoint-123", "auth": {"type": "api_key", "api_key": "synthetic-secret"}}
    try:
        with (
            patch.object(FakeSecretClient, "set_secret", side_effect=denied),
            patch.object(module, "log_event") as logged,
            pytest.raises(module.KeyVaultSecretStorageError) as failure,
        ):
            module.keyvault_model_endpoint_save_helper(
                endpoint, "endpoint-123", scope="global", stage_new_secrets=True,
            )
        assert failure.value.code == "key_vault_write_forbidden"
        assert "Key Vault Secrets Officer" in failure.value.public_message
        assert "synthetic-secret" not in failure.value.public_message
        assert "private provider details" not in str(logged.call_args_list)
        assert "synthetic-secret" not in str(logged.call_args_list)
        assert FakeSecretClient.stored_secrets == {}
        assert endpoint["auth"]["api_key"] == "synthetic-secret"
    finally:
        restore_modules(original_modules)


@pytest.mark.parametrize("identity", ["", None, "11111111-2222-3333-4444-555555555555"])
def test_explicit_diagnostic_identity_does_not_reload_saved_settings(identity):
    module, original_modules = load_functions_keyvault_module()
    try:
        with patch.object(module.app_settings_cache, "get_settings_cache", side_effect=AssertionError("Unexpected saved identity")):
            credential = module.get_keyvault_credential(
                settings={"key_vault_identity": identity},
                connection_timeout=5, read_timeout=10, retry_total=0, process_timeout=10,
            )
        assert credential.kwargs == {
            "managed_identity_client_id": identity or None,
            "connection_timeout": 5, "read_timeout": 10, "retry_total": 0, "process_timeout": 10,
        }
    finally:
        restore_modules(original_modules)


def test_model_endpoint_key_vault_helper_lifecycle():
    """Ensure endpoint auth secrets are stored, resolved, and cleaned up correctly."""
    print("🔍 Testing model endpoint Key Vault helper lifecycle...")
    FakeSecretClient.reset()
    module, original_modules = load_functions_keyvault_module()

    try:
        endpoint = {
            "id": "endpoint-123",
            "name": "Primary Endpoint",
            "auth": {
                "type": "api_key",
                "api_key": "super-secret-key",
            },
        }

        saved_endpoint = module.keyvault_model_endpoint_save_helper(endpoint, "endpoint-123", scope="user")
        secret_reference = saved_endpoint["auth"]["api_key"]

        assert secret_reference == "endpoint-123--model-endpoint--user--model-endpoint-api-key"
        assert FakeSecretClient.stored_secrets[secret_reference] == "super-secret-key"

        placeholder_endpoint = module.keyvault_model_endpoint_get_helper(
            saved_endpoint,
            "endpoint-123",
            scope="user",
            return_type=module.SecretReturnType.TRIGGER,
        )
        assert placeholder_endpoint["auth"]["api_key"] == module.ui_trigger_word

        resolved_endpoint = module.keyvault_model_endpoint_get_helper(
            saved_endpoint,
            "endpoint-123",
            scope="user",
            return_type=module.SecretReturnType.VALUE,
        )
        assert resolved_endpoint["auth"]["api_key"] == "super-secret-key"

        updated_endpoint = module.keyvault_model_endpoint_save_helper(
            {
                "id": "endpoint-123",
                "name": "Primary Endpoint",
                "auth": {
                    "type": "managed_identity",
                    "api_key": "",
                },
            },
            "endpoint-123",
            scope="user",
            existing_endpoint=saved_endpoint,
        )
        assert updated_endpoint["auth"].get("api_key") is None

        module.keyvault_model_endpoint_cleanup_helper(
            saved_endpoint,
            updated_endpoint,
            "endpoint-123",
            scope="user",
        )
        assert secret_reference not in FakeSecretClient.stored_secrets
        assert secret_reference in FakeSecretClient.deleted_secrets

        print("✅ Model endpoint Key Vault helper lifecycle passed.")
    finally:
        restore_modules(original_modules)


def test_model_endpoint_frontend_contract_files():
    """Ensure the frontend/backend contract includes endpoint IDs and stored-secret placeholders."""
    print("🔍 Verifying model endpoint UI/backend stored-secret contract...")
    admin_js_path = os.path.join(SINGLE_APP_ROOT, "static", "js", "admin", "admin_model_endpoints.js")
    workspace_js_path = os.path.join(SINGLE_APP_ROOT, "static", "js", "workspace", "workspace_model_endpoints.js")
    backend_path = os.path.join(SINGLE_APP_ROOT, "route_backend_models.py")

    admin_js = read_file_text(admin_js_path)
    workspace_js = read_file_text(workspace_js_path)
    backend_content = read_file_text(backend_path)

    assert 'const endpointId = endpointIdInput?.value.trim() || "";' in admin_js
    assert 'const endpointId = endpointIdInput?.value.trim() || "";' in workspace_js
    assert 'clientSecretInput.placeholder = "Stored"' in admin_js
    assert 'apiKeyInput.placeholder = "Stored"' in admin_js
    assert 'const hasStoredApiKey = authType === "api_key" && Boolean(existingEndpoint?.has_api_key);' in admin_js
    assert 'const hasStoredApiKey = authType === "api_key" && Boolean(existingEndpoint?.has_api_key);' in workspace_js
    assert 'const hasStoredClientSecret = authType === "service_principal" && Boolean(existingEndpoint?.has_client_secret);' in admin_js
    assert 'const hasStoredClientSecret = authType === "service_principal" && Boolean(existingEndpoint?.has_client_secret);' in workspace_js
    assert 'if (authType === "api_key" && !auth.api_key && !hasStoredApiKey)' in admin_js
    assert 'if (authType === "api_key" && !auth.api_key && !hasStoredApiKey)' in workspace_js
    assert '(!auth.client_secret && !hasStoredClientSecret)' in admin_js
    assert '(!auth.client_secret && !hasStoredClientSecret)' in workspace_js
    assert 'resolve_request_endpoint_payload' in backend_content
    assert 'keyvault_model_endpoint_get_helper' in backend_content

    print("✅ Model endpoint UI/backend stored-secret contract passed.")


def test_model_endpoint_strict_hydration_preserves_legacy_returns_and_plaintext():
    """Strict runtime hydration fails closed while legacy retrieval remains opt-in."""
    FakeSecretClient.reset()
    module, original_modules = load_functions_keyvault_module()
    reference = "endpoint-123--model-endpoint--global--model-endpoint-api-key"
    endpoint = {"id": "endpoint-123", "auth": {"type": "api_key", "api_key": reference}}
    configured = {"enable_key_vault_secret_storage": True, "key_vault_name": "unit-test-vault"}
    try:
        module.log_event = Mock()
        for settings in (
            configured,
            {**configured, "enable_key_vault_secret_storage": False},
            {**configured, "key_vault_name": ""},
        ):
            module.app_settings_cache.get_settings_cache = Mock(return_value=settings)
            assert module.retrieve_secret_from_key_vault_by_full_name(reference) == reference
            assert module.keyvault_model_endpoint_get_helper(
                endpoint, "endpoint-123", return_type=module.SecretReturnType.VALUE,
            )["auth"]["api_key"] == reference
            for return_type in (module.SecretReturnType.NAME, module.SecretReturnType.TRIGGER):
                assert module.keyvault_model_endpoint_get_helper(
                    endpoint, "endpoint-123", return_type=return_type, strict=True,
                ) == module.keyvault_model_endpoint_get_helper(
                    endpoint, "endpoint-123", return_type=return_type,
                )
            for operation in (
                lambda: module.retrieve_secret_from_key_vault_by_full_name(reference, strict=True),
                lambda: module.keyvault_model_endpoint_get_helper(
                    endpoint, "endpoint-123", return_type=module.SecretReturnType.VALUE, strict=True,
                ),
            ):
                try:
                    operation()
                except ValueError as error:
                    assert reference not in str(error)
                else:
                    raise AssertionError("Strict hydration must reject an unresolved stored credential.")
            plaintext = {"id": "endpoint-123", "auth": {"type": "api_key", "api_key": "plaintext-test-key"}}
            assert module.keyvault_model_endpoint_get_helper(
                plaintext, "endpoint-123", return_type=module.SecretReturnType.VALUE, strict=True,
            ) == plaintext
            assert module.retrieve_secret_from_key_vault_by_full_name("plaintext-test-key", strict=True) == "plaintext-test-key"
            for placeholder in (module.ui_trigger_word, module.REDACTED_SECRET_VALUE):
                redacted = {"id": "endpoint-123", "auth": {"type": "api_key", "api_key": placeholder}}
                assert module.keyvault_model_endpoint_get_helper(
                    redacted, "endpoint-123", return_type=module.SecretReturnType.VALUE,
                ) == redacted
                try:
                    module.keyvault_model_endpoint_get_helper(
                        redacted, "endpoint-123", return_type=module.SecretReturnType.VALUE, strict=True,
                    )
                except ValueError as error:
                    assert placeholder not in str(error)
                else:
                    raise AssertionError("Strict hydration must reject a redacted credential placeholder.")
        assert reference not in repr(module.log_event.call_args_list)
        assert all(not call.kwargs.get("exceptionTraceback") for call in module.log_event.call_args_list)
    finally:
        FakeSecretClient.reset()
        restore_modules(original_modules)


def test_model_endpoint_strict_hydration_success_is_nonmutating_and_logs_no_secrets():
    """Resolve API keys and client secrets without changing references or UI modes."""
    FakeSecretClient.reset()
    module, original_modules = load_functions_keyvault_module()
    reference = "endpoint-123--model-endpoint--global--model-endpoint-api-key"
    try:
        module.log_event = Mock()
        FakeSecretClient.stored_secrets[reference] = "hydrated-test-key"
        for field, auth_type in (("api_key", "api_key"), ("client_secret", "service_principal")):
            endpoint = {"id": "endpoint-123", "auth": {"type": auth_type, field: reference}}
            for return_type, expected in (
                (module.SecretReturnType.VALUE, "hydrated-test-key"),
                (module.SecretReturnType.NAME, reference),
                (module.SecretReturnType.TRIGGER, module.ui_trigger_word),
            ):
                resolved = module.keyvault_model_endpoint_get_helper(
                    endpoint, "endpoint-123", return_type=return_type, strict=True,
                )
                assert resolved["auth"][field] == expected
                assert endpoint["auth"][field] == reference
        for private_value in (reference, "hydrated-test-key"):
            assert private_value not in repr(module.log_event.call_args_list)
    finally:
        FakeSecretClient.reset()
        restore_modules(original_modules)


def test_custom_endpoint_key_vault_secret_schemes():
    """Custom secrets retain scoped staging, strict hydration, and cleanup."""
    module, original_modules = load_functions_keyvault_module()
    try:
        for auth_type, field in (("bearer", "bearer_token"), ("oauth2_client_credentials", "client_secret")):
            FakeSecretClient.reset()
            endpoint = {"id": "custom-connection", "provider": "custom", "auth": {"type": auth_type, field: "fixture-secret"}}
            saved = module.keyvault_model_endpoint_save_helper(endpoint, endpoint["id"], scope="global")
            reference = saved["auth"][field]
            assert FakeSecretClient.stored_secrets[reference] == "fixture-secret"
            for strict in (False, True):
                resolved = module.keyvault_model_endpoint_get_helper(
                    saved, endpoint["id"], scope="global", return_type=module.SecretReturnType.VALUE,
                    strict=strict,
                )
                assert resolved["auth"][field] == "fixture-secret"
                assert saved["auth"][field] == reference
            unchanged = module.keyvault_model_endpoint_save_helper(
                {**endpoint, "auth": {"type": auth_type, field: ""}},
                endpoint["id"], scope="global", existing_endpoint=saved,
            )
            assert unchanged["auth"][field] == reference
            try:
                module.keyvault_model_endpoint_save_helper(
                    {"auth": {"type": auth_type, field: reference}}, "different-connection", scope="global",
                )
            except ValueError:
                pass
            else:
                raise AssertionError("A Custom credential reference crossed endpoint scope.")
            staged = module.keyvault_model_endpoint_save_helper(
                {**endpoint, "auth": {"type": auth_type, field: "rotated-fixture-secret"}},
                endpoint["id"], scope="global", existing_endpoint=saved, stage_new_secrets=True,
            )
            assert staged["auth"][field] != reference
            assert FakeSecretClient.stored_secrets[reference] == "fixture-secret"
            module.keyvault_model_endpoint_cleanup_helper(saved, staged, endpoint["id"], scope="global")
            assert reference not in FakeSecretClient.stored_secrets
            module.keyvault_model_endpoint_delete_helper(staged, endpoint["id"], scope="global")
            assert not FakeSecretClient.stored_secrets
            assert module.keyvault_model_endpoint_get_helper(
                staged, endpoint["id"], scope="global", return_type=module.SecretReturnType.VALUE,
            ) == staged
            try:
                module.keyvault_model_endpoint_get_helper(
                    staged, endpoint["id"], scope="global", return_type=module.SecretReturnType.VALUE,
                    strict=True,
                )
            except ValueError as error:
                assert staged["auth"][field] not in str(error)
            else:
                raise AssertionError("Strict Custom hydration must reject an unavailable credential.")
    finally:
        FakeSecretClient.reset()
        restore_modules(original_modules)


def run_tests():
    tests = [
        test_model_endpoint_key_vault_helper_lifecycle,
        test_model_endpoint_frontend_contract_files,
        test_model_endpoint_strict_hydration_preserves_legacy_returns_and_plaintext,
        test_model_endpoint_strict_hydration_success_is_nonmutating_and_logs_no_secrets,
        test_custom_endpoint_key_vault_secret_schemes,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            test()
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