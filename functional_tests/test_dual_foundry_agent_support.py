# test_dual_foundry_agent_support.py
#!/usr/bin/env python3
"""
Functional test for dual Foundry agent support.
Version: 0.239.154
Implemented in: 0.239.154

This test ensures that classic Foundry and new Foundry agent payloads both
validate through the backend sanitizer, preserve separate settings, and that
runtime/modal code paths include explicit support for the new_foundry type.
"""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")

sys.path.append(APP_ROOT)

from functions_agent_payload import AgentPayloadError, sanitize_agent_payload
from json_schema_validation import validate_agent


def read_file_text(*relative_parts):
    file_path = os.path.join(REPO_ROOT, *relative_parts)
    with open(file_path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_classic_foundry_payload_still_validates():
    """Classic Foundry payloads should remain valid and isolated."""
    print("🔍 Testing classic Foundry payload validation...")

    payload = {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "name": "classic_foundry_agent",
        "display_name": "Classic Foundry Agent",
        "description": "Classic Foundry path",
        "instructions": "Managed in Foundry",
        "agent_type": "aifoundry",
        "actions_to_load": ["pluginA"],
        "enable_agent_gpt_apim": True,
        "azure_openai_gpt_endpoint": "https://example.services.ai.azure.com",
        "azure_openai_gpt_deployment": "sc-aifoundry",
        "azure_openai_gpt_api_version": "v1",
        "other_settings": {
            "azure_ai_foundry": {
                "agent_id": "asst_123",
                "endpoint_id": "classic-endpoint"
            }
        },
        "max_completion_tokens": 4096,
    }

    cleaned = sanitize_agent_payload(payload)
    validation_error = validate_agent(cleaned)

    assert cleaned["agent_type"] == "aifoundry"
    assert cleaned["actions_to_load"] == []
    assert cleaned["enable_agent_gpt_apim"] is False
    assert cleaned["other_settings"]["azure_ai_foundry"]["agent_id"] == "asst_123"
    assert "new_foundry" not in cleaned["other_settings"]
    assert validation_error is None, validation_error
    print("✅ Classic Foundry payload validation passed.")


def test_new_foundry_payload_validates_and_stays_separate():
    """New Foundry payloads should sanitize and validate independently."""
    print("🔍 Testing new Foundry payload validation...")

    payload = {
        "id": "123e4567-e89b-12d3-a456-426614174001",
        "name": "new_foundry_agent",
        "display_name": "New Foundry Agent",
        "description": "New Foundry path",
        "instructions": "Managed in Foundry",
        "agent_type": "new_foundry",
        "actions_to_load": ["pluginA", "pluginB"],
        "enable_agent_gpt_apim": True,
        "azure_openai_gpt_endpoint": "https://nadoyle-foundry.services.ai.azure.com",
        "azure_openai_gpt_deployment": "sc-aifoundry",
        "azure_openai_gpt_api_version": "2025-11-15-preview",
        "other_settings": {
            "new_foundry": {
                "application_id": "new-foundry-agent-not-openai:3",
                "application_name": "new-foundry-agent-not-openai",
                "application_version": "3",
                "endpoint_id": "new-foundry-endpoint",
                "responses_api_version": "2025-11-15-preview",
                "activity_api_version": "2025-11-15-preview",
                "notes": "phase-1 validation"
            }
        },
        "max_completion_tokens": 4096,
    }

    cleaned = sanitize_agent_payload(payload)
    validation_error = validate_agent(cleaned)

    assert cleaned["agent_type"] == "new_foundry"
    assert cleaned["actions_to_load"] == []
    assert cleaned["enable_agent_gpt_apim"] is False
    assert cleaned["other_settings"]["new_foundry"]["application_id"] == "new-foundry-agent-not-openai:3"
    assert cleaned["other_settings"]["new_foundry"]["responses_api_version"] == "2025-11-15-preview"
    assert "azure_ai_foundry" not in cleaned["other_settings"]
    assert validation_error is None, validation_error
    print("✅ New Foundry payload validation passed.")


def test_new_foundry_requires_application_reference():
    """New Foundry payloads should fail without an application reference."""
    print("🔍 Testing new Foundry application reference requirement...")

    payload = {
        "id": "123e4567-e89b-12d3-a456-426614174002",
        "name": "missing_new_foundry_app",
        "display_name": "Missing New Foundry App",
        "description": "Invalid new Foundry payload",
        "instructions": "Managed in Foundry",
        "agent_type": "new_foundry",
        "actions_to_load": [],
        "azure_openai_gpt_endpoint": "https://nadoyle-foundry.services.ai.azure.com",
        "azure_openai_gpt_deployment": "sc-aifoundry",
        "azure_openai_gpt_api_version": "2025-11-15-preview",
        "other_settings": {
            "new_foundry": {
                "responses_api_version": "2025-11-15-preview"
            }
        },
        "max_completion_tokens": 4096,
    }

    try:
        sanitize_agent_payload(payload)
    except AgentPayloadError as exc:
        assert "application" in str(exc).lower()
        print("✅ Missing New Foundry application reference correctly rejected.")
        return

    raise AssertionError("Expected AgentPayloadError for missing New Foundry application reference")


def test_dual_foundry_runtime_and_modal_hooks_exist():
    """Runtime, loader, and modal files should include explicit dual Foundry support hooks."""
    print("🔍 Verifying runtime and modal support hooks...")

    runtime_content = read_file_text("application", "single_app", "foundry_agent_runtime.py")
    loader_content = read_file_text("application", "single_app", "semantic_kernel_loader.py")
    modal_js_content = read_file_text("application", "single_app", "static", "js", "agent_modal_stepper.js")
    modal_html_content = read_file_text("application", "single_app", "templates", "_agent_modal.html")

    required_snippets = [
        (runtime_content, "class AzureAIFoundryNewChatCompletionAgent"),
        (runtime_content, "execute_new_foundry_agent"),
        (loader_content, 'if agent_type in {"aifoundry", "new_foundry"}:'),
        (loader_content, '("aoai", "aifoundry", "new_foundry")'),
        (modal_js_content, "selectedAgentType === 'new_foundry'"),
        (modal_js_content, "getAgentTypeLabel"),
        (modal_html_content, 'value="new_foundry"'),
        (modal_html_content, "agent-new-foundry-application-id"),
    ]

    missing = [snippet for content, snippet in required_snippets if snippet not in content]
    if missing:
        raise AssertionError(f"Missing expected dual Foundry support hooks: {', '.join(missing)}")

    print("✅ Runtime, loader, and modal hooks verified.")


def run_tests():
    tests = [
        test_classic_foundry_payload_still_validates,
        test_new_foundry_payload_validates_and_stays_separate,
        test_new_foundry_requires_application_reference,
        test_dual_foundry_runtime_and_modal_hooks_exist,
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
    raise SystemExit(0 if run_tests() else 1)
