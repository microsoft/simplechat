# test_group_agent_selection_scope.py
"""
Functional test for scope-aware agent selection.
Version: 0.236.059
Implemented in: 0.236.059

This test ensures scope-aware agent matching respects group IDs and global/personal scopes.
"""

import os
import sys

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(repo_root)

from application.single_app.semantic_kernel_loader import find_agent_by_scope


def test_group_agent_selection_requires_group_id_match():
    """Ensure group agent selection only matches when group_id aligns."""
    print("🔍 Validating group agent scope matching...")

    agents_cfg = [
        {"id": "g1", "name": "group-web-search", "is_group": True, "group_id": "group-a"},
        {"id": "p1", "name": "group-web-search", "is_group": False, "is_global": False}
    ]

    selected_agent = {
        "id": "g1",
        "name": "group-web-search",
        "is_group": True,
        "group_id": "group-b"
    }

    resolved = find_agent_by_scope(agents_cfg, selected_agent)
    assert resolved is None

    selected_agent["group_id"] = "group-a"
    resolved = find_agent_by_scope(agents_cfg, selected_agent)
    assert resolved is not None
    assert resolved.get("id") == "g1"

    print("✅ Group agent scope matching passed.")


def test_global_vs_personal_agent_selection():
    """Ensure global and personal agents with same name are disambiguated by scope."""
    print("🔍 Validating global vs personal agent selection...")

    agents_cfg = [
        {"id": "g1", "name": "researcher", "is_global": True, "is_group": False},
        {"id": "p1", "name": "researcher", "is_global": False, "is_group": False}
    ]

    selected_global = {"name": "researcher", "is_global": True, "is_group": False}
    resolved_global = find_agent_by_scope(agents_cfg, selected_global)
    assert resolved_global is not None
    assert resolved_global.get("id") == "g1"

    selected_personal = {"name": "researcher", "is_global": False, "is_group": False}
    resolved_personal = find_agent_by_scope(agents_cfg, selected_personal)
    assert resolved_personal is not None
    assert resolved_personal.get("id") == "p1"

    print("✅ Global vs personal selection passed.")


def run_tests():
    tests = [
        test_group_agent_selection_requires_group_id_match,
        test_global_vs_personal_agent_selection
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
