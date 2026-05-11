# test_foundry_endpoint_resolution.py
# test_foundry_endpoint_resolution.py
#!/usr/bin/env python3
"""
Functional test for Foundry endpoint resolution.
Version: 0.241.007
Implemented in: 0.236.060

This test ensures Foundry endpoint resolution respects agent settings,
app settings, and environment fallback.
"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
LOADER_FILE = ROOT / "application" / "single_app" / "semantic_kernel_loader.py"


def read_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")


def test_foundry_endpoint_resolution_priority():
    """Agent settings should override global settings and env in the helper logic."""
    print("🔍 Validating Foundry endpoint resolution priority...")

    loader_content = read_text(LOADER_FILE)

    assert "def resolve_foundry_endpoint_from_settings(foundry_settings, settings):" in loader_content, (
        "The loader should expose the Foundry endpoint resolution helper."
    )
    assert 'endpoint = (foundry_settings or {}).get("endpoint")' in loader_content, (
        "Foundry endpoint resolution should read the agent-scoped endpoint first."
    )
    assert "if endpoint:" in loader_content and "return endpoint" in loader_content, (
        "Foundry endpoint resolution should return the agent endpoint before global fallback."
    )

    print("✅ Foundry endpoint resolution priority passed.")


def test_foundry_endpoint_resolution_fallbacks():
    """Global settings and env should be used when agent endpoint is missing."""
    print("🔍 Validating Foundry endpoint resolution fallback...")

    loader_content = read_text(LOADER_FILE)

    assert 'return settings.get("azure_ai_foundry_endpoint") or os.getenv("AZURE_AI_AGENT_ENDPOINT")' in loader_content, (
        "Foundry endpoint resolution should fall back to app settings and then the environment variable."
    )

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
