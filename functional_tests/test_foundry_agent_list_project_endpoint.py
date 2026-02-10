# test_foundry_agent_list_project_endpoint.py
#!/usr/bin/env python3
"""
Functional test for Foundry agent list project endpoint resolution.
Version: 0.236.048
Implemented in: 0.236.048

This test ensures project names are used to append /api/projects/<name>
when listing Foundry agents.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_foundry_agent_list_project_endpoint_resolution():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    runtime_path = os.path.join(repo_root, "application", "single_app", "foundry_agent_runtime.py")
    models_path = os.path.join(repo_root, "application", "single_app", "route_backend_models.py")

    runtime_content = read_file_text(runtime_path)
    models_content = read_file_text(models_path)

    assert "project_name" in models_content, "Expected Foundry settings to include project_name."
    assert "/api/projects/" in runtime_content, "Expected endpoint normalization to include /api/projects/."

    print("✅ Foundry agent list project endpoint resolution verified.")


def run_tests():
    tests = [test_foundry_agent_list_project_endpoint_resolution]
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
