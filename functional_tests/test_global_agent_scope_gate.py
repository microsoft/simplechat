# test_global_agent_scope_gate.py
"""
Functional test for global agent scope gating in per-user Semantic Kernel mode.
Version: 0.241.007
Implemented in: 0.241.007

This test ensures global agents remain eligible for loading even when personal
agent access is disabled, while personal and group scopes still respect their
own admin toggles.
"""

import os
import sys


repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(repo_root)

from application.single_app.functions_agent_scope import is_selected_agent_scope_enabled


def read_file_text(file_path):
    with open(file_path, "r", encoding="utf-8") as file:
        return file.read()


def test_global_agents_bypass_personal_toggle():
    """Ensure global agents are not blocked by the personal-agent toggle."""
    print("🔍 Validating global agent scope bypass...")

    settings = {
        "allow_user_agents": False,
        "allow_group_agents": False,
    }
    global_agent = {
        "name": "beta_occ_document_summarization_agent",
        "is_global": True,
        "is_group": False,
    }
    personal_agent = {
        "name": "personal-agent",
        "is_global": False,
        "is_group": False,
    }

    assert is_selected_agent_scope_enabled(settings, global_agent) is True
    assert is_selected_agent_scope_enabled(settings, personal_agent) is False

    print("✅ Global agent scope bypass passed.")


def test_group_agents_still_require_group_toggle():
    """Ensure group agents still honor the group-agent toggle."""
    print("🔍 Validating group agent scope enforcement...")

    settings = {
        "allow_user_agents": True,
        "allow_group_agents": False,
    }
    group_agent = {
        "name": "group-agent",
        "is_global": False,
        "is_group": True,
        "group_id": "group-a",
    }

    assert is_selected_agent_scope_enabled(settings, group_agent) is False

    settings["allow_group_agents"] = True
    assert is_selected_agent_scope_enabled(settings, group_agent) is True

    print("✅ Group agent scope enforcement passed.")


def test_loader_uses_scope_gate_helper():
    """Ensure the per-user loader uses the shared scope gate helper."""
    print("🔍 Validating loader wiring for shared scope gate helper...")

    loader_path = os.path.join(
        repo_root, "application", "single_app", "semantic_kernel_loader.py"
    )
    loader_text = read_file_text(loader_path)

    assert "is_selected_agent_scope_enabled(settings, selected_agent_data)" in loader_text, (
        "Expected semantic kernel loader to use the shared selected-agent scope helper."
    )

    print("✅ Loader wiring for scope gate helper passed.")


def run_tests():
    tests = [
        test_global_agents_bypass_personal_toggle,
        test_group_agents_still_require_group_toggle,
        test_loader_uses_scope_gate_helper,
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
    raise SystemExit(0 if run_tests() else 1)