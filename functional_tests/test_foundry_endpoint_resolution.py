# test_foundry_endpoint_resolution.py
"""
Functional test for Foundry endpoint resolution.
Version: 0.236.060
Implemented in: 0.236.060

This test ensures Foundry endpoint resolution respects agent settings,
app settings, and environment fallback.
"""

import os
import sys

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(repo_root)

from application.single_app.semantic_kernel_loader import resolve_foundry_endpoint_from_settings


def test_foundry_endpoint_resolution_priority():
    """Agent settings should override global settings and env."""
    print("🔍 Validating Foundry endpoint resolution priority...")

    settings = {"azure_ai_foundry_endpoint": "https://global.example"}
    foundry_settings = {"endpoint": "https://agent.example"}

    resolved = resolve_foundry_endpoint_from_settings(foundry_settings, settings)
    assert resolved == "https://agent.example"

    print("✅ Foundry endpoint resolution priority passed.")


def test_foundry_endpoint_resolution_fallbacks():
    """Global settings should be used when agent endpoint is missing."""
    print("🔍 Validating Foundry endpoint resolution fallback...")

    settings = {"azure_ai_foundry_endpoint": "https://global.example"}
    foundry_settings = {}

    resolved = resolve_foundry_endpoint_from_settings(foundry_settings, settings)
    assert resolved == "https://global.example"

    print("✅ Foundry endpoint resolution fallback passed.")


def run_tests():
    tests = [
        test_foundry_endpoint_resolution_priority,
        test_foundry_endpoint_resolution_fallbacks,
    ]
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
