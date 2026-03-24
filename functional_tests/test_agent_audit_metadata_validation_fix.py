#!/usr/bin/env python3
# test_agent_audit_metadata_validation_fix.py
"""
Functional test for agent audit metadata validation fix.
Version: 0.239.112
Implemented in: 0.239.112

This test ensures that round-tripped agent payloads containing server-managed
audit and Cosmos metadata can still be sanitized and validated before save.
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from functions_agent_payload import sanitize_agent_payload
from json_schema_validation import validate_agent


def test_round_tripped_agent_metadata_is_ignored():
    """Audit and Cosmos metadata should not block agent validation."""
    print("🔍 Testing round-tripped agent payload sanitization...")

    payload = {
        "id": "123e4567-e89b-42d3-a456-426614174000",
        "name": "metadata_safe_agent",
        "display_name": "Metadata Safe Agent",
        "description": "Validates metadata stripping before agent save.",
        "instructions": "Be helpful.",
        "azure_openai_gpt_endpoint": "",
        "azure_openai_gpt_key": "",
        "azure_openai_gpt_deployment": "deployment-a",
        "azure_openai_gpt_api_version": "2024-05-01-preview",
        "azure_agent_apim_gpt_endpoint": "",
        "azure_agent_apim_gpt_subscription_key": "",
        "azure_agent_apim_gpt_deployment": "",
        "azure_agent_apim_gpt_api_version": "",
        "enable_agent_gpt_apim": False,
        "is_global": False,
        "is_group": False,
        "agent_type": "local",
        "actions_to_load": [],
        "other_settings": {},
        "max_completion_tokens": 4096,
        "created_at": "2026-03-13T10:00:00Z",
        "created_by": "user-1",
        "modified_at": "2026-03-13T10:05:00Z",
        "modified_by": "user-2",
        "updated_at": "2026-03-13T10:05:00Z",
        "last_updated": "2026-03-13T10:05:00Z",
        "user_id": "user-1",
        "group_id": "group-1",
        "_etag": "etag-value",
        "_rid": "rid-value",
        "_self": "self-value",
        "_ts": 1234567890
    }

    cleaned = sanitize_agent_payload(payload)
    validation_error = validate_agent(cleaned)

    unexpected_fields = [
        "created_at",
        "created_by",
        "modified_at",
        "modified_by",
        "updated_at",
        "last_updated",
        "user_id",
        "group_id",
        "_etag",
        "_rid",
        "_self",
        "_ts",
    ]

    for field in unexpected_fields:
        if field in cleaned:
            print(f"❌ Field should have been stripped during sanitization: {field}")
            return False

    if validation_error:
        print(f"❌ Validation failed after sanitization: {validation_error}")
        return False

    print("✅ Agent payload validation ignores server-managed metadata.")
    return True


if __name__ == "__main__":
    print("🧪 Testing Agent Audit Metadata Validation Fix...")
    print("=" * 70)

    tests = [
        test_round_tripped_agent_metadata_is_ignored,
    ]

    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(tests)} tests passed")

    if success:
        print("✅ All agent audit metadata validation tests passed!")
    else:
        print("❌ Some tests failed. Please review the agent metadata sanitization changes.")

    sys.exit(0 if success else 1)