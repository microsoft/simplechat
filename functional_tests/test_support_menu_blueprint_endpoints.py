#!/usr/bin/env python3
"""
Functional test for support menu Blueprint endpoint normalization.
Version: 0.242.071
Implemented in: 0.242.071

This test ensures Admin Settings support feature previews use registered
Blueprint endpoint names instead of legacy Flask endpoint names.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
sys.path.insert(0, APP_DIR)


LEGACY_ENDPOINTS = {
    "chats",
    "workspace",
    "profile",
    "support_latest_features",
    "support_send_feedback",
}


def iter_actions_from_groups(feature_groups):
    """Yield every action from grouped feature metadata."""
    for feature_group in feature_groups:
        for feature in feature_group.get("features", []):
            for action in feature.get("actions", []):
                yield action


def assert_no_legacy_endpoints(actions):
    """Assert endpoint actions use Blueprint-qualified endpoint names."""
    legacy_actions = [
        action
        for action in actions
        if action.get("endpoint") in LEGACY_ENDPOINTS
    ]
    assert legacy_actions == [], f"Legacy action endpoints were not normalized: {legacy_actions}"


def test_support_release_groups_normalize_legacy_endpoints():
    """Validate support release group actions are safe for url_for()."""
    from support_menu_config import get_support_latest_feature_release_groups

    actions = list(iter_actions_from_groups(get_support_latest_feature_release_groups()))
    assert_no_legacy_endpoints(actions)


def test_admin_settings_preview_normalizes_legacy_endpoints():
    """Validate Admin Settings feature preview actions are safe for url_for()."""
    from support_menu_config import get_support_latest_feature_release_groups_for_settings

    groups = get_support_latest_feature_release_groups_for_settings({
        "enable_user_workspace": True,
        "enable_support_send_feedback": True,
    })
    actions = list(iter_actions_from_groups(groups))
    assert_no_legacy_endpoints(actions)


def test_support_catalog_normalizes_legacy_endpoints():
    """Validate flat support catalog actions are safe for url_for()."""
    from support_menu_config import get_support_latest_feature_catalog

    actions = [
        action
        for feature in get_support_latest_feature_catalog()
        for action in feature.get("actions", [])
    ]
    assert_no_legacy_endpoints(actions)


if __name__ == "__main__":
    tests = [
        test_support_release_groups_normalize_legacy_endpoints,
        test_admin_settings_preview_normalizes_legacy_endpoints,
        test_support_catalog_normalizes_legacy_endpoints,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    passed = sum(results)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
