# test_orchestration_interaction_policy.py
#!/usr/bin/env python3
"""
Functional test for Phase 12 orchestration interaction policy.
Version: 0.250.127
Implemented in: 0.250.127

This test ensures that execution mode and review visibility policy resolves
deterministically before chat turns persist their per-turn snapshot.
"""

import os
import sys


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_orchestration_interaction import (  # noqa: E402
    apply_execution_mode_to_capability_inventory,
    normalize_orchestration_interaction_policy,
    resolve_orchestration_interaction,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_admin_policy_normalization():
    """Disabled modes and invalid defaults fall back to an enabled admin mode."""
    policy = normalize_orchestration_interaction_policy({
        "orchestration_interaction_policy": {
            "enabled_execution_modes": ["manual", "balanced"],
            "default_execution_mode": "auto",
            "enabled_review_visibility": ["collapsed"],
            "default_review_visibility": "expanded",
            "context_execution_modes": {
                "public": ["auto"],
            },
        }
    })

    assert_equal(policy["enabled_execution_modes"], ["manual", "balanced"], "enabled modes")
    assert_equal(policy["default_execution_mode"], "manual", "default mode fallback")
    assert_equal(policy["default_review_visibility"], "collapsed", "review visibility fallback")
    assert_equal(policy["context_execution_modes"]["public"], ["manual"], "context fallback")
    assert policy["policy_version"]


def test_per_message_override_and_legacy_review_only():
    """Per-message overrides win when allowed; legacy review_only migrates safely."""
    settings = {
        "orchestration_interaction_policy": {
            "enabled_execution_modes": ["manual", "balanced", "auto"],
            "default_execution_mode": "manual",
            "enabled_review_visibility": ["collapsed", "expanded"],
        }
    }
    user_settings = {
        "settings": {
            "orchestration_interaction": {
                "default_execution_mode": "balanced",
                "default_review_visibility": "collapsed",
            }
        }
    }

    snapshot = resolve_orchestration_interaction(
        settings=settings,
        user_settings=user_settings,
        request_payload={
            "orchestration_interaction": {
                "execution_mode": "auto",
                "review_visibility": "expanded",
            }
        },
    )
    assert_equal(snapshot["execution_mode"], "auto", "per-message execution mode")
    assert_equal(snapshot["execution_mode_source"], "per_message_override", "execution source")
    assert_equal(snapshot["review_visibility"], "expanded", "per-message review visibility")

    legacy_snapshot = resolve_orchestration_interaction(
        settings=settings,
        request_payload={"mode": "review_only"},
    )
    assert_equal(legacy_snapshot["execution_mode"], "balanced", "legacy execution mode")
    assert_equal(legacy_snapshot["review_visibility"], "expanded", "legacy review visibility")
    assert_equal(legacy_snapshot["legacy_migration"]["mode"], "review_only", "legacy marker")


def test_context_restriction_and_fallback_record():
    """Context-specific restrictions create an explicit fallback state."""
    snapshot = resolve_orchestration_interaction(
        settings={
            "orchestration_interaction_policy": {
                "enabled_execution_modes": ["manual", "balanced", "auto"],
                "default_execution_mode": "balanced",
                "context_execution_modes": {
                    "public": ["manual"],
                },
            }
        },
        request_payload={"orchestration_interaction": {"execution_mode": "auto"}},
        context_type="public",
    )

    assert_equal(snapshot["execution_mode"], "manual", "restricted context fallback")
    assert_equal(snapshot["execution_mode_source"], "admin_policy_fallback", "fallback source")
    assert_equal(snapshot["fallbacks"][0]["requested"], "auto", "fallback requested mode")
    assert_equal(snapshot["context_type"], "public", "context type")


def test_mode_applies_to_inventory_flags():
    """Manual mode disables silent automation while balanced keeps safe read-only auto-use."""
    inventory = {
        "version": 1,
        "capabilities": [
            {
                "id": "workspace_search",
                "read_only": True,
                "external_data": False,
                "auto_use_allowed": True,
                "requires_user_choice": True,
            },
            {
                "id": "web_search",
                "read_only": True,
                "external_data": True,
                "auto_use_allowed": False,
                "requires_user_choice": True,
            },
        ],
    }
    manual_inventory = apply_execution_mode_to_capability_inventory(
        inventory,
        {"execution_mode": "manual"},
    )
    assert_equal(manual_inventory["capabilities"][0]["auto_use_allowed"], False, "manual auto-use")
    assert_equal(manual_inventory["capabilities"][0]["requires_user_choice"], True, "manual recommendation")

    auto_inventory = apply_execution_mode_to_capability_inventory(
        inventory,
        {"execution_mode": "auto"},
    )
    assert_equal(auto_inventory["capabilities"][0]["auto_use_allowed"], True, "auto internal read")
    assert_equal(auto_inventory["capabilities"][0]["requires_user_choice"], False, "auto internal recommendation")
    assert_equal(auto_inventory["capabilities"][1]["requires_user_choice"], True, "auto external approval")


def main():
    tests = [
        test_admin_policy_normalization,
        test_per_message_override_and_legacy_review_only,
        test_context_restriction_and_fallback_record,
        test_mode_applies_to_inventory_flags,
    ]
    passed = 0
    for test in tests:
        print(f"Running {test.__name__}...")
        test()
        passed += 1
    print(f"Passed {passed}/{len(tests)} orchestration interaction tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())