# test_governance_enforcement_logic.py
#!/usr/bin/env python3
"""
Functional test for governance enforcement logic.
Version: 0.242.022
Implemented in: 0.241.010; updated in 0.242.022

This test ensures ensure_governance_access correctly allows and denies access
based on feature toggles, feature policies, item policies, and caller groups.
"""

import os
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
SINGLE_APP_DIR = os.path.join(CURRENT_DIR, "..", "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.append(SINGLE_APP_DIR)

import functions_governance as governance


def test_ensure_governance_access_allows_when_feature_toggle_disabled():
    print("Testing governance access bypass when feature toggle is disabled...")

    original_get_settings = governance.get_settings
    original_get_feature_policy = governance.get_feature_policy

    def _settings_disabled():
        return {"governance_user_agents": False}

    def _deny_policy(_):
        return {
            "allow_all": False,
            "allowed_users": [],
            "allowed_groups": [],
        }

    try:
        governance.get_settings = _settings_disabled
        governance.get_feature_policy = _deny_policy

        # Should not raise because governance feature toggle is disabled.
        governance.ensure_governance_access("governance_user_agents", "user-1")
        print("PASS: feature toggle disabled bypassed governance checks")
        return True
    finally:
        governance.get_settings = original_get_settings
        governance.get_feature_policy = original_get_feature_policy


def test_ensure_governance_access_enforces_feature_and_item_policies():
    print("Testing governance feature and item policy enforcement...")

    original_get_settings = governance.get_settings
    original_get_feature_policy = governance.get_feature_policy
    original_get_item_policies = governance.get_item_policies
    original_get_user_governance_group_ids = governance.get_user_governance_group_ids

    try:
        governance.get_settings = lambda: {"governance_global_actions_usage": True}

        governance.get_feature_policy = lambda _feature_key: {
            "allow_all": False,
            "allowed_users": [],
            "allowed_groups": ["group-a"],
        }

        governance.get_item_policies = lambda _entity_type, _item_id: [
            {
                "allow_all": False,
                "allowed_users": ["user-allowed"],
                "allowed_groups": [],
            }
        ]

        # 1) Allowed by feature policy via group membership and by item policy via user allowlist.
        governance.get_user_governance_group_ids = lambda _user_id: {"group-a"}
        governance.ensure_governance_access(
            feature_key="governance_global_actions_usage",
            user_id="user-allowed",
            item_entity_type="global_action",
            item_id="global-action-1",
        )

        # 2) Blocked by feature policy when user has no allowed group.
        governance.get_user_governance_group_ids = lambda _user_id: set()
        blocked_feature = False
        try:
            governance.ensure_governance_access(
                feature_key="governance_global_actions_usage",
                user_id="user-allowed",
                item_entity_type="global_action",
                item_id="global-action-1",
            )
        except PermissionError:
            blocked_feature = True
        assert blocked_feature, "Expected feature policy to block access without allowed groups"

        # 3) Allowed by feature policy, then blocked by item policy for non-allowlisted user.
        governance.get_user_governance_group_ids = lambda _user_id: {"group-a"}
        blocked_item = False
        try:
            governance.ensure_governance_access(
                feature_key="governance_global_actions_usage",
                user_id="user-denied",
                item_entity_type="global_action",
                item_id="global-action-1",
            )
        except PermissionError:
            blocked_item = True
        assert blocked_item, "Expected item policy to block non-allowlisted user"

        print("PASS: governance enforcement allows/denies correctly for feature and item policies")
        return True
    finally:
        governance.get_settings = original_get_settings
        governance.get_feature_policy = original_get_feature_policy
        governance.get_item_policies = original_get_item_policies
        governance.get_user_governance_group_ids = original_get_user_governance_group_ids


if __name__ == "__main__":
    tests = [
        test_ensure_governance_access_allows_when_feature_toggle_disabled,
        test_ensure_governance_access_enforces_feature_and_item_policies,
    ]
    results = []

    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f"FAIL: {test.__name__} -> {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
