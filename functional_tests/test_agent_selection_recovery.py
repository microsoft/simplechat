# test_agent_selection_recovery.py
#!/usr/bin/env python3
"""
Functional test for per-user agent loading and selection safeguards.
Version: 0.239.173
Implemented in: 0.239.173

This test ensures per-user agent loading preserves personal agents during
global merge and invalid persisted agent selections are rejected when saved.
"""

import os


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_agent_selection_recovery_wiring():
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    loader_path = os.path.join(
        repo_root, "application", "single_app", "semantic_kernel_loader.py"
    )
    agents_route_path = os.path.join(
        repo_root, "application", "single_app", "route_backend_agents.py"
    )
    chats_route_path = os.path.join(
        repo_root, "application", "single_app", "route_backend_chats.py"
    )

    loader_text = read_file_text(loader_path)
    agents_route_text = read_file_text(agents_route_path)
    chats_route_text = read_file_text(chats_route_path)

    assert "agents_cfg = get_personal_agents(user_id)" in loader_text, (
        "Expected semantic kernel loader to initialize candidate agents from personal agents."
    )
    assert "agents_cfg = []" not in loader_text.split("agents_cfg = get_personal_agents(user_id)", 1)[1][:2500], (
        "Unexpected reset of agents_cfg after personal agents are loaded."
    )
    assert "Selected agent is not available for this user or scope." in agents_route_text, (
        "Expected selected-agent endpoint to reject invalid selections."
    )
    assert "def _find_matching_user_selected_agent" in agents_route_text, (
        "Expected user selected-agent matching helper in route_backend_agents.py."
    )
    assert "if isinstance(selected_agent_info, dict):" in chats_route_text, (
        "Expected chat route to normalize dict-based selected_agent settings."
    )

    print("✅ Agent loading and selection wiring verified.")


def run_tests():
    tests = [test_agent_selection_recovery_wiring]
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