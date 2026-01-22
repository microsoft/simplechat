#!/usr/bin/env python3
"""
Functional test for Azure AI Foundry agent payload sanitation.
Version: 0.233.176
Implemented in: 0.233.176

This test ensures that sanitize_agent_payload enforces Foundry-specific backend
constraints (actions_to_load cleared, APIM disabled, agent_id required) and
prevents invalid Foundry payloads from being persisted.
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from functions_agent_payload import sanitize_agent_payload, AgentPayloadError


def test_foundry_agent_actions_and_apim_rules():
    """Azure AI Foundry agents drop plugins and APIM metadata."""
    print("🔍 Testing Foundry agent sanitization rules...")

    payload = {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "name": "foundry_agent",
        "display_name": "Foundry Agent",
        "description": "Test agent",
        "instructions": "Be helpful",
        "agent_type": "aifoundry",
        "actions_to_load": ["pluginA", "pluginB"],
        "enable_agent_gpt_apim": True,
        "azure_agent_apim_gpt_endpoint": "https://example",
        "azure_agent_apim_gpt_subscription_key": "secret",
        "azure_agent_apim_gpt_deployment": "deployment",
        "azure_agent_apim_gpt_api_version": "2024-06-01",
        "azure_openai_gpt_endpoint": "https://aoai.cognitiveservices.azure.com",
        "azure_openai_gpt_deployment": "project",
        "azure_openai_gpt_api_version": "2024-05-01-preview",
        "other_settings": {
            "azure_ai_foundry": {"agent_id": " agent-123 "}
        },
        "max_completion_tokens": 16384
    }

    cleaned = sanitize_agent_payload(payload)

    assert cleaned['agent_type'] == 'aifoundry'
    assert cleaned['actions_to_load'] == []
    assert cleaned['enable_agent_gpt_apim'] is False
    assert 'azure_agent_apim_gpt_endpoint' not in cleaned
    assert 'azure_agent_apim_gpt_subscription_key' not in cleaned
    assert cleaned['other_settings']['azure_ai_foundry']['agent_id'] == 'agent-123'

    print("✅ Foundry agents automatically drop plugins and APIM secrets.")


def test_foundry_agent_requires_agent_id():
    """Missing azure_ai_foundry.agent_id should raise AgentPayloadError."""
    print("🔍 Validating Foundry agent_id requirement...")

    payload = {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "name": "foundry_agent",
        "display_name": "Foundry Agent",
        "description": "Test agent",
        "instructions": "Be helpful",
        "agent_type": "aifoundry",
        "actions_to_load": [],
        "azure_openai_gpt_endpoint": "https://aoai.cognitiveservices.azure.com",
        "azure_openai_gpt_deployment": "project",
        "azure_openai_gpt_api_version": "2024-05-01-preview",
        "other_settings": {"azure_ai_foundry": {}},
        "max_completion_tokens": 4096
    }

    try:
        sanitize_agent_payload(payload)
    except AgentPayloadError as exc:
        assert 'agent_id' in str(exc)
        print("✅ Missing agent_id correctly rejected.")
        return

    raise AssertionError("Expected AgentPayloadError for missing agent_id")

if __name__ == "__main__":
     tests = [
         test_foundry_agent_actions_and_apim_rules,
         test_foundry_agent_requires_agent_id
     ]
     results = []
@@
     success = all(results)
     print(f"\n📊 Results: {sum(results)}/{len(tests)} tests passed")
     sys.exit(0 if success else 1)
