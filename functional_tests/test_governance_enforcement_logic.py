# test_governance_enforcement_logic.py
#!/usr/bin/env python3
"""
Functional test for governance enforcement logic.
Version: 0.242.071
Implemented in: 0.241.010; updated in 0.242.022; 0.242.063; 0.242.064; 0.242.065; 0.242.066

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


ROOT_DIR = os.path.dirname(CURRENT_DIR)


def _read_repo_file(*parts):
    path = os.path.join(ROOT_DIR, *parts)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


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


def test_empty_allowlist_denies_when_allow_all_disabled():
    print("Testing governance empty allowlist deny-all semantics...")

    original_get_settings = governance.get_settings
    original_get_feature_policy = governance.get_feature_policy
    original_get_user_governance_group_ids = governance.get_user_governance_group_ids

    try:
        governance.get_settings = lambda: {"governance_user_actions": True}
        governance.get_user_governance_group_ids = lambda _user_id: set()
        governance.get_feature_policy = lambda _feature_key: {
            "allow_all": False,
            "allowed_users": [],
            "allowed_groups": [],
        }

        blocked_empty_allowlist = False
        try:
            governance.ensure_governance_access("governance_user_actions", "user-denied")
        except PermissionError:
            blocked_empty_allowlist = True
        assert blocked_empty_allowlist, "Expected empty allowlist with allow_all disabled to deny access"

        governance.get_feature_policy = lambda _feature_key: {
            "allow_all": False,
            "allowed_users": ["user-allowed"],
            "allowed_groups": [],
        }
        governance.ensure_governance_access("governance_user_actions", "user-allowed")

        print("PASS: empty allowlists deny until explicit users or groups are assigned")
        return True
    finally:
        governance.get_settings = original_get_settings
        governance.get_feature_policy = original_get_feature_policy
        governance.get_user_governance_group_ids = original_get_user_governance_group_ids


def test_personal_action_entry_points_enforce_governance():
    print("Testing action type governance entry point coverage...")

    personal_actions_content = _read_repo_file("application", "single_app", "functions_personal_actions.py")
    group_actions_content = _read_repo_file("application", "single_app", "functions_group_actions.py")
    plugin_routes_content = _read_repo_file("application", "single_app", "route_backend_plugins.py")
    sk_loader_content = _read_repo_file("application", "single_app", "semantic_kernel_loader.py")
    agent_catalog_content = _read_repo_file("application", "single_app", "functions_agent_catalog.py")
    admin_governance_content = _read_repo_file("application", "single_app", "static", "js", "admin", "admin_governance.js")
    admin_template_content = _read_repo_file("application", "single_app", "templates", "admin_settings.html")

    assert "def get_governed_personal_actions(" in personal_actions_content, (
        "Expected a governed personal action read helper"
    )
    assert "ensure_action_type_access('governance_user_actions', user_id, action_data.get('type'), 'personal')" in personal_actions_content, (
        "Expected personal action saves to enforce action type governance"
    )
    assert "def get_governed_group_actions(" in group_actions_content, (
        "Expected a governed group action read helper"
    )
    assert "get_plugin_types(" in plugin_routes_content and "is_action_type_access_allowed(" in plugin_routes_content, (
        "Expected user action type discovery to filter by action type governance"
    )
    assert "_get_governed_personal_plugin_manifests" in sk_loader_content, (
        "Expected SK runtime loading to use governed personal action manifests"
    )
    assert "_get_governed_global_plugin_manifests" in sk_loader_content, (
        "Expected SK runtime loading to use governed global action manifests"
    )
    assert "get_governed_personal_actions(user_id, return_type=SecretReturnType.NAME)" in agent_catalog_content, (
        "Expected agent catalog action labels to respect personal action governance"
    )
    assert "filter_governed_global_actions_for_user" in agent_catalog_content, (
        "Expected agent catalog action labels to respect global action governance"
    )
    assert "No users or groups allowed" in admin_governance_content, (
        "Expected admin governance UI to describe deny-all empty allowlists"
    )
    assert "All users and groups allowed" in admin_governance_content, (
        "Expected admin governance UI to distinguish allow-all policies"
    )
    for marker in [
        "personal_action_type",
        "group_action_type",
        "global_action_type",
        "fetchAdminActionTypeLookupOptions",
    ]:
        assert marker in admin_governance_content, f"Missing action type governance UI marker: {marker}"
    for marker in [
        "Personal Action Type",
        "Group Action Type",
        "Global Action Type",
        "Action type policies grant create/use entitlement",
    ]:
        assert marker in admin_template_content, f"Missing action type governance template marker: {marker}"

    print("PASS: action type governance entry points are covered")
    return True


def test_action_type_policies_grant_specific_action_families():
    print("Testing delegated action type policy semantics...")

    original_get_settings = governance.get_settings
    original_get_feature_policy = governance.get_feature_policy
    original_get_explicit_item_policies = governance.get_explicit_item_policies
    original_get_item_policies = governance.get_item_policies
    original_list_item_policies = governance.list_item_policies
    original_get_user_governance_group_ids = governance.get_user_governance_group_ids

    try:
        governance.get_settings = lambda: {
            "governance_user_actions": True,
            "governance_global_actions_usage": True,
        }
        governance.get_feature_policy = lambda _feature_key: {
            "allow_all": False,
            "allowed_users": [],
            "allowed_groups": [],
        }
        governance.get_user_governance_group_ids = lambda _user_id: set()

        def explicit_policies(entity_type, item_id):
            if entity_type == "personal_action_type" and item_id == "sql":
                return [{"allow_all": False, "allowed_users": ["user-sql"], "allowed_groups": []}]
            if entity_type == "global_action_type" and item_id == "sql":
                return [{"allow_all": False, "allowed_users": ["user-sql"], "allowed_groups": []}]
            return []

        governance.get_explicit_item_policies = explicit_policies
        governance.list_item_policies = lambda entity_type=None: [
            {"allow_all": False, "allowed_users": ["user-sql"], "allowed_groups": [], "entity_type": entity_type, "item_id": "sql"}
        ] if entity_type in {"personal_action_type", "global_action_type"} else []

        governance.ensure_action_type_access("governance_user_actions", "user-sql", "sql_query", "personal")
        governance.ensure_action_type_access("governance_user_actions", "user-sql", "sql_schema", "personal")
        assert governance.is_action_scope_access_allowed("governance_user_actions", "user-sql", "personal"), (
            "Expected an explicit SQL type grant to expose the personal action scope"
        )

        blocked_simplechat = False
        try:
            governance.ensure_action_type_access("governance_user_actions", "user-sql", "simplechat", "personal")
        except PermissionError:
            blocked_simplechat = True
        assert blocked_simplechat, "Expected SQL type grant not to allow SimpleChat actions"

        governance.get_item_policies = lambda _entity_type, _item_id: [
            {"allow_all": False, "allowed_users": ["user-sql"], "allowed_groups": []}
        ]
        governance.ensure_global_action_access(
            "user-sql",
            {"id": "global-sql-action", "name": "Global SQL", "type": "sql_query", "is_enabled": True},
        )

        governance.get_item_policies = lambda _entity_type, _item_id: [
            {"allow_all": False, "allowed_users": ["someone-else"], "allowed_groups": []}
        ]
        blocked_instance = False
        try:
            governance.ensure_global_action_access(
                "user-sql",
                {"id": "global-sql-action", "name": "Global SQL", "type": "sql_query", "is_enabled": True},
            )
        except PermissionError:
            blocked_instance = True
        assert blocked_instance, "Expected configured global action instance policy to apply after type access"

        blocked_disabled = False
        try:
            governance.ensure_global_action_access(
                "user-sql",
                {"id": "global-sql-action", "name": "Global SQL", "type": "sql_query", "is_enabled": False},
            )
        except PermissionError:
            blocked_disabled = True
        assert blocked_disabled, "Expected disabled global action records to remain unavailable"

        print("PASS: delegated action type policies grant only matching action families")
        return True
    finally:
        governance.get_settings = original_get_settings
        governance.get_feature_policy = original_get_feature_policy
        governance.get_explicit_item_policies = original_get_explicit_item_policies
        governance.get_item_policies = original_get_item_policies
        governance.list_item_policies = original_list_item_policies
        governance.get_user_governance_group_ids = original_get_user_governance_group_ids


if __name__ == "__main__":
    tests = [
        test_ensure_governance_access_allows_when_feature_toggle_disabled,
        test_ensure_governance_access_enforces_feature_and_item_policies,
        test_empty_allowlist_denies_when_allow_all_disabled,
        test_personal_action_entry_points_enforce_governance,
        test_action_type_policies_grant_specific_action_families,
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
