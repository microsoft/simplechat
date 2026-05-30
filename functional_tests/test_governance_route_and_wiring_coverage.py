# test_governance_route_and_wiring_coverage.py
#!/usr/bin/env python3
"""
Functional test for governance route and enforcement wiring coverage.
Version: 0.242.011
Implemented in: 0.242.011

This test ensures governance routes are registered and guarded, and that
updated backend modules include governance enforcement hooks for endpoint,
agent, and action flows.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.append(SINGLE_APP_DIR)


def _read(*parts):
    path = os.path.join(ROOT_DIR, *parts)
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def test_governance_route_registration_and_guards():
    print("Testing governance route registration and guards...")

    app_content = _read("application", "single_app", "app.py")
    route_content = _read("application", "single_app", "route_backend_governance.py")

    assert "from route_backend_governance import register_route_backend_governance" in app_content, (
        "Expected app.py to import governance route registration"
    )
    assert "register_route_backend_governance(app)" in app_content, (
        "Expected governance routes to be registered in app.py"
    )

    expected_routes = [
        "/api/admin/governance/policies",
        "/api/admin/governance/policies/<feature_key>",
        "/api/admin/governance/item-policies",
        "/api/admin/governance/item-policies/review",
        "/api/admin/governance/item-policies/<entity_type>/<item_id>",
    ]
    for route in expected_routes:
        assert route in route_content, f"Missing governance route: {route}"

    assert route_content.count("@swagger_route(security=get_auth_security())") >= 4, (
        "Expected swagger security decorators on governance routes"
    )
    assert route_content.count("@login_required") >= 4, (
        "Expected login_required on governance routes"
    )
    assert route_content.count("@admin_required") >= 4, (
        "Expected admin_required on governance routes"
    )

    assert "def _sanitize_policy_payload(payload):" in route_content, (
        "Expected policy payload sanitization helper in governance route module"
    )
    assert "delete_governance_item_policy_route" in route_content, (
        "Expected delegated item policy delete route in governance route module"
    )

    print("PASS: governance route registration and guards verified")


def test_governance_enforcement_hooks_across_changed_routes():
    print("Testing governance enforcement hooks across changed route files...")

    agents_content = _read("application", "single_app", "route_backend_agents.py")
    plugins_content = _read("application", "single_app", "route_backend_plugins.py")
    chats_content = _read("application", "single_app", "route_backend_chats.py")
    frontend_chats_content = _read("application", "single_app", "route_frontend_chats.py")
    models_content = _read("application", "single_app", "route_backend_models.py")
    admin_settings_route_content = _read("application", "single_app", "route_frontend_admin_settings.py")
    settings_content = _read("application", "single_app", "functions_settings.py")
    admin_settings_template_content = _read("application", "single_app", "templates", "admin_settings.html")
    admin_governance_js_content = _read("application", "single_app", "static", "js", "admin", "admin_governance.js")

    # Agents route: user/group/global agent governance and endpoint governance hooks.
    for key in [
        "governance_user_agents",
        "governance_group_agents",
        "governance_global_agents_usage",
        "governance_user_endpoints",
        "governance_group_endpoints",
    ]:
        assert key in agents_content, f"Missing governance key in route_backend_agents.py: {key}"

    # Plugins route: user/global action governance hooks and item policy persistence.
    for key in [
        "governance_user_actions",
        "governance_global_actions_usage",
    ]:
        assert key in plugins_content, f"Missing governance key in route_backend_plugins.py: {key}"
    assert "upsert_item_policy(" in plugins_content, (
        "Expected route_backend_plugins.py to persist governance item policy updates"
    )

    # Chats/models route: endpoint governance hooks.
    for key in ["governance_user_endpoints", "governance_group_endpoints", "governance_global_endpoints"]:
        assert key in chats_content, f"Missing governance key in route_backend_chats.py: {key}"
        assert key in models_content, f"Missing governance key in route_backend_models.py: {key}"
    assert "item_entity_type=\"endpoint\"" in models_content or "item_entity_type='endpoint'" in models_content, (
        "Expected endpoint item delegation enforcement in route_backend_models.py"
    )

    # Admin settings route/template/js: governance toggles and governance tab wiring.
    for key in [
        "governance_user_endpoints",
        "governance_group_endpoints",
        "governance_global_endpoints",
        "governance_user_agents",
        "governance_group_agents",
        "governance_global_agents_usage",
        "governance_user_actions",
        "governance_group_actions",
        "governance_global_actions_usage",
    ]:
        assert key in admin_settings_route_content, f"Missing governance toggle persistence key: {key}"
        assert key in settings_content, f"Missing governance default setting key: {key}"

    for marker in [
        "id=\"governance\"",
        "governance-feature-policies-table",
        "governance-item-policies-table",
        "governance-save-feature-policies-btn",
        "governance-save-item-policy-btn",
    ]:
        assert marker in admin_settings_template_content, f"Missing governance UI marker in admin_settings.html: {marker}"

    for endpoint in [
        "/api/admin/governance/policies",
        "/api/admin/governance/item-policies",
        "/api/admin/governance/item-policies/review",
    ]:
        assert endpoint in admin_governance_js_content, f"Missing governance API call in admin_governance.js: {endpoint}"

    for marker in [
        "syncGovernanceFeaturePolicyVisibility()",
        "syncGovernanceFeaturePolicyRowVisibility(row)",
        "getGovernanceFeatureToggle(featureKey)",
        "governance-item-allowed-principals-controls",
        "_filter_chat_model_endpoints_by_governance",
        "_is_chat_agent_allowed_by_governance",
        "_is_agent_allowed_for_user_selection",
        "governance-edit-item-policy-btn",
        "governance-delete-item-policy-btn",
        "governance-item-policy-delete-confirm-modal",
        "loadGovernanceItemPolicyIntoEditor",
        "openCurrentDelegatedItemAllowListEditorAfterReviewModalCloses",
        "deleteGovernanceItemPolicyFromContext",
        "renderGovernancePrincipalReviewCell",
        "wireGovernanceItemReviewHandlers",
    ]:
        assert marker in admin_governance_js_content or marker in admin_settings_template_content or marker in frontend_chats_content or marker in agents_content, (
            f"Missing governance UI visibility marker: {marker}"
        )

    assert '<div id="governance-item-policy-form"' in admin_settings_template_content, (
        "Delegated item policy editor must not be a nested form inside Admin Settings"
    )
    assert 'type="button" class="btn btn-primary" id="governance-save-item-policy-btn"' in admin_settings_template_content, (
        "Delegated item policy save button must not submit the global settings form"
    )

    print("PASS: governance enforcement hooks and admin governance wiring verified")


def test_governance_cache_optimization_hooks():
    print("Testing governance cache optimization hooks...")

    governance_content = _read("application", "single_app", "functions_governance.py")
    app_cache_content = _read("application", "single_app", "app_settings_cache.py")

    for marker in [
        "GOVERNANCE_CACHE_TTL_SECONDS",
        "_get_request_cache()",
        "_get_cached_governance_value(",
        "invalidate_governance_cache()",
        "_get_shared_governance_cache_version()",
        "_bump_shared_governance_cache_version()",
        "_set_request_cache_value(decision_key, True)",
    ]:
        assert marker in governance_content, f"Missing governance cache optimization marker: {marker}"

    for marker in [
        "GOVERNANCE_CACHE_VERSION_KEY",
        "get_governance_cache_version",
        "bump_governance_cache_version",
        "get_governance_cache_version_redis",
        "bump_governance_cache_version_redis",
        "get_governance_cache_version_mem",
        "bump_governance_cache_version_mem",
    ]:
        assert marker in app_cache_content, f"Missing shared governance version cache marker: {marker}"

    assert "get_feature_policy(" in governance_content and "(\"feature_policy\"," in governance_content, (
        "Expected feature policy reads to use governance cache keys"
    )
    assert "get_item_policy(" in governance_content and "(\"item_policy\"," in governance_content, (
        "Expected item policy reads to use governance cache keys"
    )
    assert "delete_item_policy(" in governance_content and "item_policy_delete" in governance_content, (
        "Expected delegated item policy delete support and audit logging"
    )
    assert "get_user_governance_group_ids(" in governance_content and "user_governance_group_ids" in governance_content, (
        "Expected governance group memberships to use cache keys"
    )
    assert "rows_by_feature_key" in governance_content and "_default_feature_policy_doc(feature_key)" in governance_content, (
        "Expected feature policy listing to include defaults for newly added governance keys"
    )
    assert "_read_stored_feature_policy(feature_key)" in governance_content, (
        "Expected default feature policy bootstrap to distinguish stored rows from fallback defaults"
    )

    print("PASS: governance cache optimization hooks verified")


def test_workspace_jinja_governance_gating_hooks():
    print("Testing workspace Jinja governance gating hooks...")

    governance_content = _read("application", "single_app", "functions_governance.py")
    workspace_route_content = _read("application", "single_app", "route_frontend_workspace.py")
    group_route_content = _read("application", "single_app", "route_frontend_group_workspaces.py")
    workspace_template_content = _read("application", "single_app", "templates", "workspace.html")
    group_template_content = _read("application", "single_app", "templates", "group_workspaces.html")

    for marker in [
        "def is_governance_access_allowed(",
        "def filter_governed_model_endpoints(",
        "item_entity_type=\"endpoint\"",
    ]:
        assert marker in governance_content, f"Missing workspace governance helper marker: {marker}"

    for marker in [
        "workspace_governance = {",
        "governance_user_agents",
        "governance_user_actions",
        "governance_user_endpoints",
        "filter_governed_model_endpoints(user_id, personal_endpoints, \"governance_user_endpoints\")",
        "workspace_governance=workspace_governance",
    ]:
        assert marker in workspace_route_content, f"Missing personal workspace governance route marker: {marker}"

    for marker in [
        "workspace_governance = {",
        "governance_group_agents",
        "governance_group_actions",
        "governance_group_endpoints",
        "filter_governed_model_endpoints(user_id, group_endpoints, \"governance_group_endpoints\")",
        "workspace_governance=workspace_governance",
    ]:
        assert marker in group_route_content, f"Missing group workspace governance route marker: {marker}"

    for marker in [
        "workspace_governance.user_agents",
        "workspace_governance.user_actions",
        "workspace_governance.user_endpoints",
        "Personal agents are disabled by governance",
        "Personal actions are disabled by governance",
        "Personal endpoints are disabled by governance",
        "settings.allow_user_agents and workspace_governance.user_agents",
        "settings.allow_user_plugins and workspace_governance.user_actions",
        "settings.allow_user_custom_endpoints and settings.enable_multi_model_endpoints and workspace_governance.user_endpoints",
    ]:
        assert marker in workspace_template_content, f"Missing personal workspace Jinja governance marker: {marker}"

    for marker in [
        "workspace_governance.group_agents",
        "workspace_governance.group_actions",
        "workspace_governance.group_endpoints",
        "Group agents are disabled by governance",
        "Group actions are disabled by governance",
        "Group endpoints are disabled by governance",
        "settings.allow_group_agents and workspace_governance.group_agents",
        "settings.allow_group_plugins and workspace_governance.group_actions",
        "settings.allow_group_custom_endpoints and settings.enable_multi_model_endpoints and workspace_governance.group_endpoints",
    ]:
        assert marker in group_template_content, f"Missing group workspace Jinja governance marker: {marker}"

    print("PASS: workspace Jinja governance gating hooks verified")


if __name__ == "__main__":
    tests = [
        test_governance_route_registration_and_guards,
        test_governance_enforcement_hooks_across_changed_routes,
        test_governance_cache_optimization_hooks,
        test_workspace_jinja_governance_gating_hooks,
    ]
    results = []

    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__} -> {exc}")
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"Results: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
