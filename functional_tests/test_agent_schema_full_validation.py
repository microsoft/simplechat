# test_agent_schema_full_validation.py
#!/usr/bin/env python3
"""
Functional test for full agent schema validation.
Version: 0.236.049
Implemented in: 0.236.049

This test ensures that validate_agent uses the full Draft 7 schema
so internal definitions resolve correctly for Foundry settings.
"""

import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

from json_schema_validation import validate_agent


def build_valid_foundry_agent():
    """Build a valid Azure AI Foundry agent payload."""
    return {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "user_id": "test-user-123",
        "last_updated": "2025-01-30T00:00:00Z",
        "name": "foundry_agent_1",
        "display_name": "Foundry Agent",
        "description": "Valid Foundry agent payload for schema validation.",
        "azure_openai_gpt_endpoint": "https://example.openai.azure.com",
        "azure_openai_gpt_deployment": "gpt-4o",
        "azure_openai_gpt_api_version": "2024-10-01-preview",
        "agent_type": "aifoundry",
        "instructions": "You are a helpful test agent.",
        "actions_to_load": [],
        "other_settings": {
            "azure_ai_foundry": {
                "agent_id": "agent-123"
            }
        },
        "max_completion_tokens": 2048,
        "is_global": False,
        "is_group": False
    }


def test_valid_agent_schema():
    """Ensure valid Foundry agent passes schema validation."""
    print("\n🔍 Testing valid Foundry agent schema validation...")
    try:
        agent = build_valid_foundry_agent()
        result = validate_agent(agent)
        if result is None:
            print("✅ Valid Foundry agent passed schema validation.")
            return True

        print(f"❌ Validation failed unexpectedly: {result}")
        return False
    except Exception as exc:
        print(f"❌ Unexpected exception during validation: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_invalid_agent_missing_foundry_agent_id():
    """Ensure missing Foundry agent_id triggers validation error."""
    print("\n🔍 Testing Foundry agent schema validation with missing agent_id...")
    try:
        agent = build_valid_foundry_agent()
        agent_missing_id = copy.deepcopy(agent)
        agent_missing_id["other_settings"]["azure_ai_foundry"].pop("agent_id", None)

        result = validate_agent(agent_missing_id)
        if result:
            print("✅ Missing agent_id correctly failed schema validation.")
            return True

        print("❌ Validation unexpectedly succeeded for missing agent_id.")
        return False
    except Exception as exc:
        print(f"❌ Unexpected exception during validation: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_valid_agent_schema,
        test_invalid_agent_missing_foundry_agent_id
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
