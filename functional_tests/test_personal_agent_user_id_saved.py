# test_personal_agent_user_id_saved.py
#!/usr/bin/env python3
"""
Functional test for personal agent user_id persistence.
Version: 0.236.050
Implemented in: 0.236.050

This test ensures personal agent saves assign user_id to the persisted payload.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_personal_agent_user_id_saved():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    file_path = os.path.join(repo_root, "application", "single_app", "functions_personal_agents.py")
    content = read_file_text(file_path)

    assert "agent_data['user_id'] = user_id" in content, "Expected user_id to be set on persisted agent payload."
    assert "agent_data['last_updated']" in content, "Expected last_updated to be set on persisted agent payload."

    print("✅ Personal agent save user_id persistence verified.")


def run_tests():
    tests = [test_personal_agent_user_id_saved]
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
