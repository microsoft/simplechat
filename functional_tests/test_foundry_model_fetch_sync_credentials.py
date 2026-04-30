# test_foundry_model_fetch_sync_credentials.py
#!/usr/bin/env python3
"""
Functional test for Foundry model fetch sync credential handling.
Version: 0.239.156
Implemented in: 0.239.156

This test ensures sync Foundry model discovery helpers use synchronous Azure
credentials so token retrieval returns a token object instead of a coroutine.
"""

import importlib
import inspect
import os
import sys
import types


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

    azure_stub = types.ModuleType("azure")
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
    semantic_kernel_contents_stub = types.ModuleType("semantic_kernel.contents")
    semantic_kernel_chat_stub = types.ModuleType("semantic_kernel.contents.chat_message_content")

    class AzureAIAgent:
        @staticmethod
        def create_client(*args, **kwargs):
            raise AssertionError("create_client should not be used in this regression test")

    class ChatMessageContent:
        pass

    semantic_kernel_agents_stub.AzureAIAgent = AzureAIAgent
    semantic_kernel_chat_stub.ChatMessageContent = ChatMessageContent

    original_modules = {}
    module_stubs = {
        "functions_appinsights": functions_appinsights_stub,
        "functions_debug": functions_debug_stub,
        "functions_keyvault": functions_keyvault_stub,
        "requests": requests_stub,
        "azure": azure_stub,
        "azure.identity": azure_identity_stub,
        "azure.identity.aio": azure_identity_aio_stub,
        "semantic_kernel": semantic_kernel_stub,
        "semantic_kernel.agents": semantic_kernel_agents_stub,
        "semantic_kernel.contents": semantic_kernel_contents_stub,
        "semantic_kernel.contents.chat_message_content": semantic_kernel_chat_stub,
    }

    for module_name, module_stub in module_stubs.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules["foundry_agent_runtime"] = sys.modules.get("foundry_agent_runtime")
    sys.modules.pop("foundry_agent_runtime", None)
    module = importlib.import_module("foundry_agent_runtime")
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