#!/usr/bin/env python3
# test_group_plugin_global_merge_fix.py
"""
Functional test for group plugin global merge behavior.
Version: 0.233.164
Implemented in: 0.233.164

This test ensures that when global actions are merged into group workspaces,
only group-owned actions remain editable and duplicate names are handled.
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def test_global_actions_are_included_without_duplicates():
    """Validate merge helper returns global actions and skips name collisions."""
    print("🔍 Testing global action merge helper...")

    from route_backend_plugins import (
        _merge_group_and_global_actions,
        _normalize_group_action,
        _normalize_global_action,
    )

    group_actions = [
        {"id": "group-1", "name": "group_action", "displayName": "Group Action"},
        {"id": "group-2", "name": "shared", "display_name": "Shared Group"},
    ]
    global_actions = [
        {"id": "global-1", "name": "global_action", "displayName": "Global Action"},
        {"id": "global-2", "name": "shared", "displayName": "Shared Global"},
    ]

    merged = _merge_group_and_global_actions(group_actions, global_actions)

    if len(merged) != 3:
        print(f"❌ Expected 3 merged actions, found {len(merged)}")
        return False

    names = {item.get("name") for item in merged}
    expected_names = {"group_action", "shared", "global_action"}
    if names != expected_names:
        print(f"❌ Merged action names mismatch: expected {expected_names}, got {names}")
        return False

    global_items = [item for item in merged if item.get("is_global")]
    if len(global_items) != 1 or global_items[0].get("name") != "global_action":
        print("❌ Global action handling incorrect")
        return False

    group_items = [item for item in merged if not item.get("is_global")]
    if len(group_items) != 2:
        print("❌ Group actions should remain editable")
        return False

    print("✅ Global merge helper returned expected results")
    return True


def test_group_normalization_sets_flags():
    """Validate group action normalization flags scope correctly."""
    print("🔍 Testing group action normalization...")

    from route_backend_plugins import _normalize_group_action

    sample = {"id": "group-3", "name": "local", "displayName": "Local"}
    normalized = _normalize_group_action(sample)

    if normalized.get("is_global"):
        print("❌ Group action incorrectly marked as global")
        return False

    if not normalized.get("is_group"):
        print("❌ Group action missing group flag")
        return False

    if normalized.get("scope") != "group":
        print("❌ Group action scope mismatch")
        return False

    print("✅ Group normalization flags are correct")
    return True


if __name__ == "__main__":
    tests = [
        test_global_actions_are_included_without_duplicates,
        test_group_normalization_sets_flags,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    passed = sum(bool(result) for result in results)
    total = len(tests)
    print(f"\n📊 Results: {passed}/{total} tests passed")

    if all(results):
        print("✅ Global action merge functional tests passed!")
    else:
        print("❌ Some global action merge tests failed.")

    sys.exit(0 if all(results) else 1)
