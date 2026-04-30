# test_foundry_token_limit_defaults.py
#!/usr/bin/env python3
"""
Functional test for Foundry token limit defaults and runtime forwarding.
Version: 0.241.005
Implemented in: 0.241.005

This test ensures seeded agent defaults use model-native output limits and
that classic and new Foundry runtimes forward configured token caps.
"""

import asyncio
import importlib
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = ROOT / "application" / "single_app"

sys.path.insert(0, str(SINGLE_APP_ROOT))
sys.path.insert(0, str(ROOT))


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding="utf-8")
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


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
    requests_stub.last_post_args = None
    requests_stub.last_post_kwargs = None

    class StubResponse:
        def __init__(self, payload, status_code=200, headers=None, text=""):
            self._payload = payload
            self.status_code = status_code
            self.headers = headers or {"Content-Type": "application/json"}
            self.text = text

        def json(self):
            return self._payload

        def close(self):
            return None

    def post(*args, **kwargs):
        requests_stub.last_post_args = args
        requests_stub.last_post_kwargs = kwargs
        return StubResponse(
            {
                "id": "resp-123",
                "model": "gpt-5.4",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "new foundry result",
                            }
                        ],
                    }
                ],
            }
        )

    requests_stub.Response = StubResponse
    requests_stub.get = lambda *args, **kwargs: None
    requests_stub.post = post

    azure_stub = types.ModuleType("azure")
    azure_identity_stub = types.ModuleType("azure.identity")
    azure_identity_aio_stub = types.ModuleType("azure.identity.aio")

    class Token:
        def __init__(self, value):
            self.token = value

    class SyncDefaultAzureCredential:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def get_token(self, scope):
            return Token(f"sync:{scope}")

        def close(self):
            return None

    class SyncClientSecretCredential(SyncDefaultAzureCredential):
        pass

    class AsyncDefaultAzureCredential:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def get_token(self, scope):
            return Token(f"async:{scope}")

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

    class StubAgentsOperations:
        async def get_agent(self, agent_id):
            return types.SimpleNamespace(model={"id": "gpt-5.4"}, agent_id=agent_id)

        async def delete_thread(self, thread_id):
            return None

    class StubClient:
        def __init__(self):
            self.agents = StubAgentsOperations()

        async def close(self):
            return None

    async def _delete_thread():
        return None

    class ChatMessageContent:
        def __init__(self, content="", role="user", metadata=None):
            self.content = content
            self.role = role
            self.metadata = metadata or {}
            self.items = []

    class AzureAIAgent:
        last_invoke_kwargs = None

        def __init__(self, client=None, definition=None):
            self.client = client
            self.definition = definition

        @staticmethod
        def create_client(*args, **kwargs):
            return StubClient()

        async def invoke(self, **kwargs):
            AzureAIAgent.last_invoke_kwargs = kwargs
            message = ChatMessageContent(content="classic foundry result", metadata={})
            thread = types.SimpleNamespace(id="thread-123", delete=_delete_thread)
            yield types.SimpleNamespace(thread=thread, message=message)

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
    return module, original_modules, requests_stub, AzureAIAgent


def test_foundry_defaults_and_runtime_forwarding():
    """Seeded defaults should use -1 and Foundry runtimes should forward token caps."""
    print("🔍 Testing Foundry defaults and runtime token forwarding...")

    globals_path = ROOT / "application" / "single_app" / "functions_global_agents.py"
    schema_path = ROOT / "application" / "single_app" / "static" / "json" / "schemas" / "agent.schema.json"

    assert_contains(globals_path, '"max_completion_tokens": -1')
    assert_contains(schema_path, '"default": -1')

    module, original_modules, requests_stub, azure_ai_agent_cls = load_foundry_agent_runtime_module()

    try:
        message_history = [module.ChatMessageContent(content="Hello Foundry")]

        classic_result = asyncio.run(
            module.execute_foundry_agent(
                foundry_settings={
                    "agent_id": "agent-123",
                    "endpoint": "https://example.services.ai.azure.com",
                },
                global_settings={},
                message_history=message_history,
                metadata={"conversation_id": "conv-1"},
                max_completion_tokens=4096,
            )
        )

        assert azure_ai_agent_cls.last_invoke_kwargs is not None
        assert azure_ai_agent_cls.last_invoke_kwargs.get("max_completion_tokens") == 4096
        assert classic_result.message == "classic foundry result"

        payload_without_limit = module._build_new_foundry_request_payload(
            message_history,
            {"conversation_id": "conv-1"},
            stream=False,
        )
        assert "max_output_tokens" not in payload_without_limit

        new_result = asyncio.run(
            module.execute_new_foundry_agent(
                foundry_settings={
                    "application_name": "test-app",
                    "endpoint": "https://example.services.ai.azure.com",
                    "responses_api_version": "2025-11-15-preview",
                },
                global_settings={},
                message_history=message_history,
                metadata={"conversation_id": "conv-2"},
                max_completion_tokens=8192,
            )
        )

        assert requests_stub.last_post_kwargs is not None
        assert requests_stub.last_post_kwargs["json"].get("max_output_tokens") == 8192
        assert new_result.message == "new foundry result"
    finally:
        restore_modules(original_modules)

    print("✅ Foundry defaults and runtime token forwarding verified.")


if __name__ == "__main__":
    success = True
    try:
        test_foundry_defaults_and_runtime_forwarding()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback

        traceback.print_exc()
        success = False

    raise SystemExit(0 if success else 1)