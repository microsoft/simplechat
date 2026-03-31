# test_foundry_agent_list_async_paging.py
#!/usr/bin/env python3
"""
Functional test for Foundry agent list async paging handling.
Version: 0.236.047
Implemented in: 0.236.047

This test ensures Foundry agent listing avoids awaiting AsyncItemPaged
and iterates async results safely.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_foundry_agent_list_async_paging():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    runtime_path = os.path.join(repo_root, "application", "single_app", "foundry_agent_runtime.py")
    content = read_file_text(runtime_path)

    assert "async for item in result" in content, "Expected async iteration over agent list results."
    assert "return agents_client.list_agents()" in content, "list_agents should not be awaited."

    print("✅ Foundry agent list async paging handling verified.")


def run_tests():
    tests = [test_foundry_agent_list_async_paging]
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
