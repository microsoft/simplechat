# test_foundry_model_fetch_sync_credentials.py
#!/usr/bin/env python3
"""
Functional test for Foundry model fetch sync credential handling.
Version: 0.261.457
Implemented in: 0.239.156
Enhanced in: 0.261.457 (Azure request-boundary credential compatibility)

This test ensures sync Foundry model discovery helpers use synchronous Azure
credentials so token retrieval returns a token object instead of a coroutine.
"""

import importlib
import inspect
import os
import sys
import types

import pytest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SINGLE_APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
sys.path.insert(0, SINGLE_APP_ROOT)
sys.path.insert(0, REPO_ROOT)


def restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def load_foundry_agent_runtime_module():
    functions_appinsights_stub = types.ModuleType("functions_appinsights")
    functions_appinsights_stub.log_event = lambda *args, **kwargs: None

    functions_debug_stub = types.ModuleType("functions_debug")
    functions_debug_stub.debug_print = lambda *args, **kwargs: None

    functions_keyvault_stub = types.ModuleType("functions_keyvault")
    functions_keyvault_stub.retrieve_secret_from_key_vault_by_full_name = lambda value: value
    functions_keyvault_stub.validate_secret_name_dynamic = lambda value: False

    requests_stub = types.ModuleType("requests")

    class Response:
        pass

    requests_stub.Response = Response
    requests_stub.get = lambda *args, **kwargs: None
    requests_stub.post = lambda *args, **kwargs: None

    azure_identity_stub = types.ModuleType("azure.identity")
    azure_identity_aio_stub = types.ModuleType("azure.identity.aio")

    class SyncToken:
        def __init__(self, value):
            self.token = value

    class SyncDefaultAzureCredential:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def get_token(self, scope):
            return SyncToken(f"sync:{scope}")

        def close(self):
            return None

    class SyncClientSecretCredential(SyncDefaultAzureCredential):
        pass

    class AsyncDefaultAzureCredential:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def get_token(self, scope):
            return SyncToken(f"async:{scope}")

        async def close(self):
            return None

    class AsyncClientSecretCredential(AsyncDefaultAzureCredential):
        pass

    class AzureAuthorityHosts:
        AZURE_PUBLIC_CLOUD = "public"
        AZURE_GOVERNMENT = "government"

    azure_identity_stub.AzureAuthorityHosts = AzureAuthorityHosts
    azure_identity_stub.ClientSecretCredential = SyncClientSecretCredential
    azure_identity_stub.DefaultAzureCredential = SyncDefaultAzureCredential
    azure_identity_aio_stub.ClientSecretCredential = AsyncClientSecretCredential
    azure_identity_aio_stub.DefaultAzureCredential = AsyncDefaultAzureCredential

    semantic_kernel_stub = types.ModuleType("semantic_kernel")
    semantic_kernel_agents_stub = types.ModuleType("semantic_kernel.agents")
    semantic_kernel_open_ai_stub = types.ModuleType("semantic_kernel.agents.open_ai")
    semantic_kernel_polling_stub = types.ModuleType("semantic_kernel.agents.open_ai.run_polling_options")
    semantic_kernel_contents_stub = types.ModuleType("semantic_kernel.contents")
    semantic_kernel_chat_stub = types.ModuleType("semantic_kernel.contents.chat_message_content")
    functions_authentication_stub = types.ModuleType("functions_authentication")

    def refuse_delegated_token(*args, **kwargs):
        raise AssertionError("Delegated token acquisition is outside synchronous discovery")

    functions_authentication_stub.get_valid_access_token_for_plugins = refuse_delegated_token

    class AzureAIAgent:
        @staticmethod
        def create_client(*args, **kwargs):
            raise AssertionError("create_client should not be used in this regression test")

    class ChatMessageContent:
        pass

    class RunPollingOptions:
        pass

    semantic_kernel_agents_stub.AzureAIAgent = AzureAIAgent
    semantic_kernel_polling_stub.RunPollingOptions = RunPollingOptions
    semantic_kernel_chat_stub.ChatMessageContent = ChatMessageContent

    original_modules = {}
    module_stubs = {
        "functions_appinsights": functions_appinsights_stub,
        "functions_debug": functions_debug_stub,
        "functions_keyvault": functions_keyvault_stub,
        "requests": requests_stub,
        "azure.identity": azure_identity_stub,
        "azure.identity.aio": azure_identity_aio_stub,
        "semantic_kernel": semantic_kernel_stub,
        "semantic_kernel.agents": semantic_kernel_agents_stub,
        "semantic_kernel.agents.open_ai": semantic_kernel_open_ai_stub,
        "semantic_kernel.agents.open_ai.run_polling_options": semantic_kernel_polling_stub,
        "semantic_kernel.contents": semantic_kernel_contents_stub,
        "semantic_kernel.contents.chat_message_content": semantic_kernel_chat_stub,
        "functions_authentication": functions_authentication_stub,
    }

    for module_name, module_stub in module_stubs.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules["foundry_agent_runtime"] = sys.modules.get("foundry_agent_runtime")
    sys.modules.pop("foundry_agent_runtime", None)
    try:
        module = importlib.import_module("foundry_agent_runtime")
    except BaseException:
        restore_modules(original_modules)
        raise
    return module, original_modules


def test_build_project_credential_returns_sync_token_provider():
    """Ensure sync discovery helper uses sync Azure credentials."""
    print("🔍 Testing Foundry sync discovery credential builder...")
    module, original_modules = load_foundry_agent_runtime_module()

    try:
        credential = module.build_project_credential({"type": "managed_identity"})
        token = credential.get_token("https://ai.azure.com/.default")

        assert not inspect.iscoroutine(token)
        assert token.token == "sync:https://ai.azure.com/.default"
    finally:
        restore_modules(original_modules)

    print("✅ Foundry sync discovery credential builder passed.")


@pytest.mark.parametrize("auth,scope,expected_options", [
    (
        {"type": "managed_identity", "managed_identity_client_id": "configured-identity"},
        "https://ai.azure.com/.default",
        {"managed_identity_client_id": "configured-identity"},
    ),
    (
        {"type": "service_principal", "management_cloud": "government",
         "tenant_id": "tenant", "client_id": "client", "client_secret": "fixture-only-secret"},
        "https://ai.azure.us/.default",
        {"tenant_id": "tenant", "client_id": "client", "client_secret": "fixture-only-secret",
         "authority": "https://login.microsoftonline.us"},
    ),
    (
        {"type": "service_principal", "management_cloud": "custom",
         "custom_authority": "https://login.custom.example",
         "tenant_id": "tenant", "client_id": "client", "client_secret": "fixture-only-secret"},
        "https://ai.custom.example/.default",
        {"tenant_id": "tenant", "client_id": "client", "client_secret": "fixture-only-secret",
         "authority": "https://login.custom.example"},
    ),
])
def test_sync_discovery_preserves_credential_type_authority_and_identity(auth, scope, expected_options):
    module, original_modules = load_foundry_agent_runtime_module()
    try:
        credential = module.build_project_credential(auth)
        token = credential.get_token(scope)
        assert not inspect.iscoroutine(token)
        assert token.token == f"sync:{scope}"
        assert credential.kwargs == expected_options
    finally:
        restore_modules(original_modules)


if __name__ == "__main__":
    success = True
    try:
        test_build_project_credential_returns_sync_token_provider()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)