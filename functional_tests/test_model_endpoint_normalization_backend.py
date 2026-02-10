# test_model_endpoint_normalization_backend.py
"""
Functional test for backend model endpoint normalization.
Version: 0.236.057
Implemented in: 0.236.057

This test ensures model endpoints are normalized with stable IDs and enabled
flags so frontend consumers receive consistent identifiers.
"""

import os
import sys

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(repo_root)

from application.single_app.functions_settings import normalize_model_endpoints


def test_model_endpoint_normalization_backend():
    """Ensure IDs and enabled flags are normalized on backend."""
    print("🔍 Validating backend model endpoint normalization...")

    endpoints = [
        {
            "name": "Foundry Endpoint",
            "connection": {"endpoint": "https://foundry.example"},
            "models": [
                {
                    "deploymentName": "gpt-4o"
                }
            ]
        }
    ]

    normalized, changed = normalize_model_endpoints(endpoints)

    assert changed is True
    assert normalized[0]["id"] == "Foundry Endpoint"
    assert normalized[0]["enabled"] is True
    assert normalized[0]["models"][0]["id"] == "gpt-4o"
    assert normalized[0]["models"][0]["enabled"] is True

    print("✅ Backend model endpoint normalization passed.")


def run_tests():
    tests = [test_model_endpoint_normalization_backend]
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
    success = run_tests()
    sys.exit(0 if success else 1)
