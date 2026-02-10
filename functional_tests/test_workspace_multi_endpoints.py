# test_workspace_multi_endpoints.py
"""
Functional test for workspace multi-endpoint routing.
Version: 0.236.045
Implemented in: 0.236.045

This test ensures that workspace multi-endpoint payloads are sanitized and that
agent payloads accept multi-endpoint selection fields.
"""

import sys
import os

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(repo_root)

from application.single_app.functions_settings import sanitize_model_endpoints_for_frontend
from application.single_app.functions_agent_payload import sanitize_agent_payload


def test_model_endpoint_sanitization():
    """Ensure secrets are stripped and flags are preserved."""
    endpoints = [
        {
            "id": "endpoint-1",
            "name": "Personal Endpoint",
            "provider": "aoai",
            "auth": {
                "type": "api_key",
                "api_key": "super-secret"
            },
            "connection": {
                "endpoint": "https://example.openai.azure.com",
                "openai_api_version": "2024-05-01-preview"
            },
            "models": [
                {"id": "model-1", "deploymentName": "gpt-4o", "enabled": True}
            ]
        }
    ]
    sanitized = sanitize_model_endpoints_for_frontend(endpoints)
    assert sanitized[0]["auth"].get("api_key") is None
    assert sanitized[0]["has_api_key"] is True


def test_agent_payload_multi_endpoint_fields():
    """Ensure agent payload accepts multi-endpoint selection fields."""
    agent_payload = {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "name": "workspace_agent",
        "display_name": "Workspace Agent",
        "description": "Test agent",
        "instructions": "Be helpful",
        "actions_to_load": [],
        "other_settings": {},
        "max_completion_tokens": 256,
        "agent_type": "local",
        "is_global": False,
        "is_group": False,
        "model_endpoint_id": "endpoint-1",
        "model_id": "model-1",
        "model_provider": "aoai",
        "azure_openai_gpt_deployment": "gpt-4o"
    }
    sanitized = sanitize_agent_payload(agent_payload)
    assert sanitized.get("model_endpoint_id") == "endpoint-1"
    assert sanitized.get("model_id") == "model-1"
    assert sanitized.get("model_provider") == "aoai"


def run_tests():
    tests = [test_model_endpoint_sanitization, test_agent_payload_multi_endpoint_fields]
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
    sys.exit(0 if run_tests() else 1)
