#!/usr/bin/env python3
# test_v2_control_center_foundation.py
"""
Functional test for the V2 Control Center foundation.
Version: 0.261.291
Implemented in: 0.261.278

This test covers the shared access capability contract, bootstrap wiring, stable
activity-log IDs, removal of the legacy automatic migration check, removal of the
V2 Data health section and its backfill APIs (0.261.291), and route/pane structure.
"""

import ast
import itertools
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
V2 = ROOT / "application" / "v2_ui" / "src"
AUTH = APP / "functions_authentication.py"
BOOTSTRAP = APP / "route_backend_v2.py"
BACKFILL = APP / "route_backend_control_center.py"
ACTIVITY = APP / "functions_activity_logging.py"
LEGACY_JS = APP / "static" / "js" / "control-center.js"
LEGACY_HTML = APP / "templates" / "control_center.html"
PAGE = V2 / "pages" / "ControlCenterPage.tsx"


def _source(path):
    assert path.is_file(), f"Expected file is missing: {path}"
    return path.read_text(encoding="utf-8")


def _capabilities_function():
    tree = ast.parse(_source(AUTH))
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "get_control_center_capabilities"
    )
    namespace = {}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(AUTH), "exec"), namespace)
    return namespace[function.name]


def test_capability_helper_matches_legacy_access_rules():
    """Every relevant role/settings combination has the same dashboard/admin outcome."""
    capability_helper = _capabilities_function()
    role_names = ("Admin", "ControlCenterAdmin", "ControlCenterDashboardReader")
    settings_values = (False, True)
    for enabled_roles in itertools.chain.from_iterable(
        itertools.combinations(role_names, size) for size in range(len(role_names) + 1)
    ):
        for admin_required, reader_required in itertools.product(settings_values, repeat=2):
            user = {"roles": list(enabled_roles)}
            settings = {
                "require_member_of_control_center_admin": admin_required,
                "require_member_of_control_center_dashboard_reader": reader_required,
            }
            capabilities = capability_helper(user, settings)
            full_access = (
                "ControlCenterAdmin" in enabled_roles
                if admin_required else "Admin" in enabled_roles
            )
            dashboard_access = full_access or (
                reader_required and "ControlCenterDashboardReader" in enabled_roles
            )
            assert capabilities == {
                "can_view_dashboard": bool(dashboard_access),
                "can_manage_users": bool(full_access),
                "can_manage_groups": bool(full_access),
                "can_manage_workspaces": bool(full_access),
                "can_view_activity_logs": bool(full_access),
                "can_run_maintenance": bool(full_access),
            }

    source = _source(AUTH)
    decorator = source.split("def control_center_required(", 1)[1].split(
        "\ndef create_group_role_required", 1
    )[0]
    assert "get_control_center_capabilities(user, settings)" in decorator
    assert "capabilities['can_view_dashboard']" in decorator
    assert "capabilities['can_manage_users']" in decorator


def test_bootstrap_publishes_control_center_capabilities():
    """The SPA receives the same server-computed authorization contract."""
    source = _source(BOOTSTRAP)
    assert "get_control_center_capabilities" in source
    assert '"control_center": get_control_center_capabilities(session_user, settings)' in source


def test_activity_log_backfill_is_removed_from_both_control_centers():
    """Neither Control Center offers the legacy backfill, and its APIs no longer exist."""
    js = _source(LEGACY_JS)
    html = _source(LEGACY_HTML)
    page = _source(PAGE)
    route = _source(BACKFILL)
    assert "/api/admin/control-center/migrate/status" not in js
    assert "checkMigrationStatus" not in js
    assert "migrationBanner" not in html
    assert "migrationConfirmModal" not in html
    for removed in ("data-health", "Data health", "MigrationDataHealth", "/control-center/migrate", "Run backfill"):
        assert removed not in page, f"V2 Control Center still references {removed!r}."
    for removed in ("/api/admin/control-center/migrate/", "api_get_migration_status", "api_migrate_to_activity_logs"):
        assert removed not in route, f"The removed backfill API is still registered: {removed!r}."


def test_activity_log_ids_are_stable_and_backfill_lookup_is_removed():
    """Idempotent writers keep deterministic IDs; the backfill-only lookup helper is gone."""
    activity = _source(ACTIVITY)
    helper_tree = ast.parse(activity)
    helper_names = {node.name for node in helper_tree.body if isinstance(node, ast.FunctionDef)}
    assert "has_activity_log_for_resource" not in helper_names
    helper_nodes = [
        node for node in helper_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build_activity_log_id"
    ]

    import uuid

    namespace = {"uuid": uuid}
    exec(compile(ast.Module(body=helper_nodes, type_ignores=[]), str(ACTIVITY), "exec"), namespace)
    stable_id = namespace["build_activity_log_id"](
        "document_creation", "user-1", "backfill:group:doc-1"
    )
    assert stable_id == namespace["build_activity_log_id"](
        "document_creation", "user-1", "backfill:group:doc-1"
    )
    assert stable_id != namespace["build_activity_log_id"](
        "document_creation", "user-2", "backfill:group:doc-1"
    )
    assert "build_activity_log_id(" in activity.split("def _create_activity_record", 1)[1]


def test_pane_has_section_routes_and_capability_gating():
    """Each section is deep-linkable and its menu entry is permission-gated."""
    app = _source(V2 / "App.tsx")
    sidebar = _source(V2 / "components" / "layout" / "Sidebar.tsx")
    page = _source(PAGE)
    for route in ('path="/control-center"', 'path="/control-center/:section"'):
        assert route in app
    for capability in (
        "can_view_dashboard", "can_manage_users", "can_manage_groups",
        "can_manage_workspaces", "can_view_activity_logs",
    ):
        assert capability in page
    assert "canOpenControlCenter" in sidebar
    assert "v2ControlCenterRailCollapsed" in page


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.291")


TESTS = [
    test_capability_helper_matches_legacy_access_rules,
    test_bootstrap_publishes_control_center_capabilities,
    test_activity_log_backfill_is_removed_from_both_control_centers,
    test_activity_log_ids_are_stable_and_backfill_lookup_is_removed,
    test_pane_has_section_routes_and_capability_gating,
    test_version_is_at_least_the_implementing_release,
]


if __name__ == "__main__":
    passed = 0
    for test in TESTS:
        test()
        passed += 1
    print(f"{passed}/{len(TESTS)} Control Center checks passed")
