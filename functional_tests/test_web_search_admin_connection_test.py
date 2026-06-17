# test_web_search_admin_connection_test.py
"""
Functional test for Web Search admin connection testing.
Version: 0.242.060
Implemented in: 0.241.069
Updated in: 0.241.094
Updated in: 0.242.060

This test ensures the Admin Settings Web Search test validates Foundry settings,
uses a live-search prompt boundary, returns actionable permission guidance, and
redacts secret values from browser-facing diagnostics. It also validates custom
admin test prompts from the Web Search test modal.
"""

import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_web_search_test.py"


class FakeChatMessageContent:
    """Small stand-in for Semantic Kernel ChatMessageContent."""

    def __init__(self, role, content):
        self.role = role
        self.content = content


class FakeFoundryAgentInvocationError(RuntimeError):
    """Small stand-in for the Foundry runtime error type."""


def load_module_with_stubs():
    """Load functions_web_search_test.py without importing app startup dependencies."""

    foundry_stub = types.ModuleType("foundry_agent_runtime")
    foundry_stub.FoundryAgentInvocationError = FakeFoundryAgentInvocationError

    async def execute_foundry_agent(**kwargs):
        return types.SimpleNamespace(message="stub", citations=[], model="stub")

    foundry_stub.execute_foundry_agent = execute_foundry_agent

    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None

    semantic_kernel_stub = types.ModuleType("semantic_kernel")
    contents_stub = types.ModuleType("semantic_kernel.contents")
    chat_message_stub = types.ModuleType("semantic_kernel.contents.chat_message_content")
    chat_message_stub.ChatMessageContent = FakeChatMessageContent

    original_modules = {
        name: sys.modules.get(name)
        for name in [
            "foundry_agent_runtime",
            "functions_appinsights",
            "semantic_kernel",
            "semantic_kernel.contents",
            "semantic_kernel.contents.chat_message_content",
        ]
    }
    sys.modules["foundry_agent_runtime"] = foundry_stub
    sys.modules["functions_appinsights"] = appinsights_stub
    sys.modules["semantic_kernel"] = semantic_kernel_stub
    sys.modules["semantic_kernel.contents"] = contents_stub
    sys.modules["semantic_kernel.contents.chat_message_content"] = chat_message_stub

    try:
        spec = importlib.util.spec_from_file_location(
            "functions_web_search_test_under_test",
            MODULE_PATH,
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original_module


def valid_payload():
    return {
        "enabled": True,
        "consent_accepted": True,
        "foundry": {
            "endpoint": "https://contoso.services.ai.azure.com/api/projects/simplechat",
            "api_version": "v1",
            "agent_id": "asst_test123",
            "authentication_type": "managed_identity",
            "managed_identity_type": "system_assigned",
        },
    }


def test_validation_requires_project_endpoint_and_agent_id():
    """Validate missing settings are caught before any outbound request."""

    print("Testing Web Search validation...")
    module = load_module_with_stubs()

    payload = {
        "enabled": True,
        "consent_accepted": True,
        "foundry": {
            "endpoint": "https://contoso.services.ai.azure.com",
            "api_version": "v1",
            "authentication_type": "managed_identity",
        },
    }
    response, status_code = module.run_web_search_connection_test(
        payload,
        global_settings={},
    )

    assert status_code == 400
    assert response["success"] is False
    assert any("/api/projects/" in item for item in response["guidance"])
    assert any("Agent ID" in item for item in response["guidance"])
    print("Validation checks passed")


def test_success_uses_foundry_prompt_and_returns_preview():
    """Validate a successful fake agent run returns safe details and preview text."""

    print("Testing Web Search success result...")
    module = load_module_with_stubs()
    captured = {}

    async def fake_execute_agent(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            message="Microsoft official site: https://www.microsoft.com",
            citations=[{"url": "https://www.microsoft.com"}],
            model="gpt-test",
        )

    response, status_code = module.run_web_search_connection_test(
        valid_payload(),
        global_settings={},
        execute_agent=fake_execute_agent,
    )

    assert status_code == 200
    assert response["success"] is True
    assert response["status"] == "success"
    assert "Microsoft official site" in response["response_preview"]
    assert captured["foundry_settings"]["agent_id"] == "asst_test123"
    assert "Grounding with Bing Search" in captured["message_history"][0].content
    print("Success result checks passed")


def test_warning_when_agent_returns_no_citations():
    """Validate no-citation responses surface agent tooling guidance."""

    print("Testing Web Search no-citation warning...")
    module = load_module_with_stubs()

    async def fake_execute_agent(**kwargs):
        return types.SimpleNamespace(
            message="Microsoft official site: https://www.microsoft.com",
            citations=[],
            model="gpt-test",
        )

    response, status_code = module.run_web_search_connection_test(
        valid_payload(),
        global_settings={},
        execute_agent=fake_execute_agent,
    )

    assert status_code == 200
    assert response["success"] is True
    assert response["status"] == "warning"
    assert any("Grounding with Bing Search" in item for item in response["guidance"])
    print("No-citation warning checks passed")


def test_custom_query_is_sent_to_foundry_agent():
    """Validate the modal's custom query is used for the Foundry smoke test."""

    print("Testing Web Search custom query handling...")
    module = load_module_with_stubs()
    captured = {}
    payload = valid_payload()
    payload["query"] = "Find the official Microsoft trust center page and reply with the URL."

    async def fake_execute_agent(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            message="Microsoft Trust Center: https://www.microsoft.com/trust-center",
            citations=[{"url": "https://www.microsoft.com/trust-center"}],
            model="gpt-test",
        )

    response, status_code = module.run_web_search_connection_test(
        payload,
        global_settings={},
        execute_agent=fake_execute_agent,
    )

    assert status_code == 200
    assert response["success"] is True
    assert captured["message_history"][0].content == payload["query"]
    print("Custom query checks passed")


def test_permission_error_redacts_secret_and_returns_guidance():
    """Validate permission failures return useful guidance without leaking secrets."""

    print("Testing Web Search permission diagnostics...")
    module = load_module_with_stubs()
    payload = valid_payload()
    payload["foundry"].update({
        "authentication_type": "service_principal",
        "tenant_id": "tenant-id",
        "client_id": "client-id",
        "client_secret": "super-secret-value",
    })

    async def fake_execute_agent(**kwargs):
        raise module.FoundryAgentInvocationError(
            "403 Forbidden while using client_secret super-secret-value"
        )

    response, status_code = module.run_web_search_connection_test(
        payload,
        global_settings={},
        execute_agent=fake_execute_agent,
    )

    assert status_code == 500
    assert response["success"] is False
    assert response["status"] == "permission"
    assert "super-secret-value" not in response["error"]
    assert "[redacted]" in response["error"]
    assert any("Foundry User" in item for item in response["guidance"])
    assert any("Azure AI User" in item for item in response["guidance"])
    print("Permission diagnostics checks passed")


if __name__ == "__main__":
    tests = [
        test_validation_requires_project_endpoint_and_agent_id,
        test_success_uses_foundry_prompt_and_returns_preview,
        test_warning_when_agent_returns_no_citations,
        test_custom_query_is_sent_to_foundry_agent,
        test_permission_error_redacts_secret_and_returns_guidance,
    ]

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        test()

    print(f"\nResults: {len(tests)}/{len(tests)} tests passed")
    sys.exit(0)