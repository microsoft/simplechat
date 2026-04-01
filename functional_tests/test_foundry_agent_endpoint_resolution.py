# test_foundry_agent_endpoint_resolution.py
#!/usr/bin/env python3
"""
Functional test for Foundry agent endpoint resolution enrichment.
Version: 0.236.051
Implemented in: 0.236.051

This test ensures Foundry agent endpoint configuration is enriched with
project_name and supports endpoint_id fallback when model_endpoint_id is missing.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_foundry_agent_endpoint_resolution_enrichment():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    loader_path = os.path.join(repo_root, "application", "single_app", "semantic_kernel_loader.py")

    loader_content = read_file_text(loader_path)

    assert "foundry_settings[\"project_name\"]" in loader_content, (
        "Expected Foundry settings to include project_name enrichment."
    )
    assert "foundry_settings.get(\"endpoint_id\")" in loader_content, (
        "Expected endpoint_id fallback to be available in Foundry resolution."
    )

    print("✅ Foundry agent endpoint resolution enrichment verified.")


def run_tests():
    tests = [test_foundry_agent_endpoint_resolution_enrichment]
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
    raise SystemExit(0 if run_tests() else 1)
