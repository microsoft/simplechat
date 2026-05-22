#!/usr/bin/env python3
# test_action_workspace_identity_scoping.py
"""
Functional test for action workspace identity scoping.
Version: 0.241.095
Implemented in: 0.241.095

This test ensures reusable workspace identities can be referenced by personal,
group, and global actions without copying secrets, while public identities and
cross-scope identity references remain excluded from action workflows.
"""

import ast
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def read_text(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def parse_app(relative_path):
    return ast.parse(read_text(f"application/single_app/{relative_path}"))


def function_names(parsed):
    return {node.name for node in ast.walk(parsed) if isinstance(node, ast.FunctionDef)}


def test_version_and_schema_contract():
    """Validate version bump and explicit action identity schema fields."""
    config_text = read_text("application/single_app/config.py")
    schema = json.loads(read_text("application/single_app/static/json/schemas/plugin.schema.json"))
    properties = schema["definitions"]["Plugin"]["properties"]

    assert 'VERSION = "0.241.095"' in config_text
    assert "identity_id" in properties
    assert properties["identity_id"]["type"] == "string"


def test_workspace_identity_action_helpers():
    """Validate action identity helpers and scope capability restrictions."""
    identity_text = read_text("application/single_app/functions_workspace_identities.py")
    parsed = parse_app("functions_workspace_identities.py")
    names = function_names(parsed)

    for expected in {
        "get_action_identity_reference_id",
        "validate_action_identity_reference",
        "hydrate_action_identity_reference",
        "_apply_sql_action_identity_auth",
        "_apply_openapi_action_identity_auth",
        "_apply_generic_action_identity_auth",
    }:
        assert expected in names

    assert "ACTION_IDENTITY_AUTH_TYPES" in identity_text
    assert "Public workspace identities cannot be used by actions" in identity_text
    assert 'allowed_usage_contexts = {"action"}' in identity_text
    assert 'allowed_usage_contexts = {"file_sync", "action"}' in identity_text
    assert 'allowed_usage_contexts = {"file_sync"}' in identity_text


def test_action_storage_validates_and_hydrates_identities():
    """Validate personal, group, and global action persistence uses scoped identities."""
    expected = {
        "functions_personal_actions.py": [
            "WORKSPACE_IDENTITY_SCOPE_PERSONAL",
            "validate_action_identity_reference",
            "hydrate_action_identity_reference",
        ],
        "functions_group_actions.py": [
            "WORKSPACE_IDENTITY_SCOPE_GROUP",
            "validate_action_identity_reference",
            "hydrate_action_identity_reference",
        ],
        "functions_global_actions.py": [
            "WORKSPACE_IDENTITY_SCOPE_GLOBAL",
            "validate_action_identity_reference",
            "hydrate_action_identity_reference",
        ],
    }

    for relative_path, markers in expected.items():
        source = read_text(f"application/single_app/{relative_path}")
        for marker in markers:
            assert marker in source, f"{marker} missing from {relative_path}"


def test_action_routes_enforce_scoped_identity_resolution():
    """Validate routes resolve identities from authorized personal/group/global scopes."""
    route_text = read_text("application/single_app/route_backend_plugins.py")

    for marker in [
        "_resolve_action_identity_context",
        "_hydrate_sql_test_identity",
        "WORKSPACE_IDENTITY_SCOPE_PERSONAL",
        "WORKSPACE_IDENTITY_SCOPE_GROUP",
        "WORKSPACE_IDENTITY_SCOPE_GLOBAL",
        "Admin role required for global action identities",
        "validate_action_identity_reference(plugin_manifest, scope_type, scope_id)",
        '"identity_id": identity_id',
    ]:
        assert marker in route_text

    assert "require_active_group(user_id)" in route_text
    assert "assert_group_role(" in route_text
    assert "hydrate_action_identity_reference(" in route_text


def test_identity_delete_guard_checks_file_sync_and_actions():
    """Validate identity deletion checks action references across scopes."""
    route_text = read_text("application/single_app/route_backend_workspace_identities.py")

    assert "_list_action_references" in route_text
    assert "get_action_identity_reference_id(action) == identity_id" in route_text
    assert "File Sync sources or actions" in route_text
    assert "get_global_actions(include_disabled=True)" in route_text


def test_action_modal_scope_and_selector_wiring():
    """Validate the action modal loads the correct identity catalog for each action scope."""
    modal_html = read_text("application/single_app/templates/_plugin_modal.html")
    modal_js = read_text("application/single_app/static/js/plugin_modal_stepper.js")
    personal_js = read_text("application/single_app/static/js/workspace/workspace_plugins.js")
    group_js = read_text("application/single_app/static/js/workspace/group_plugins.js")
    admin_js = read_text("application/single_app/static/js/admin/admin_plugins.js")

    for element_id in [
        "plugin-auth-identity-select",
        "plugin-auth-identity-select-generic",
        "sql-identity-select",
    ]:
        assert element_id in modal_html

    for marker in [
        "setActionScope",
        "loadActionIdentities",
        "getSelectedActionIdentity('sql')",
        "identityId = selectedIdentity.id",
        "payload.identity_id",
        "Use action-specific credentials",
    ]:
        assert marker in modal_js

    assert "apiBase: '/api/workspace-identities/personal'" in personal_js
    assert "apiBase: '/api/workspace-identities/group'" in group_js
    assert "apiBase: '/api/admin/workspace-identities/global'" in admin_js


if __name__ == "__main__":
    tests = [
        test_version_and_schema_contract,
        test_workspace_identity_action_helpers,
        test_action_storage_validates_and_hydrates_identities,
        test_action_routes_enforce_scoped_identity_resolution,
        test_identity_delete_guard_checks_file_sync_and_actions,
        test_action_modal_scope_and_selector_wiring,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            results.append(False)

    sys.exit(0 if all(results) else 1)
