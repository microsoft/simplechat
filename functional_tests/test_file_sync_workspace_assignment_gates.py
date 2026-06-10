#!/usr/bin/env python3
# test_file_sync_workspace_assignment_gates.py
"""
Functional test for File Sync workspace assignment gates.
Version: 0.241.180
Implemented in: 0.241.180

This test ensures group and public workspace File Sync access uses workspace
assignment lists instead of group/public File Sync app roles, including the
scheduled-run guard and Admin Settings persistence wiring.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def read_text(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def get_function_source(relative_path, function_name):
    """Return source for a top-level function from a Python file."""
    path = REPO_ROOT / relative_path
    source = path.read_text(encoding="utf-8")
    parsed = ast.parse(source)
    lines = source.splitlines()

    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return "\n".join(lines[node.lineno - 1:node.end_lineno])

    raise AssertionError(f"Function {function_name} not found in {relative_path}")


def test_assignment_settings_are_defined_and_normalized():
    """Validate settings defaults and JSON-array hidden-field parsing."""
    settings_text = read_text("application/single_app/functions_settings.py")

    assert "def normalize_file_sync_allowed_group_ids" in settings_text
    assert "def normalize_file_sync_allowed_public_workspace_ids" in settings_text
    assert "json.loads(stripped_value)" in settings_text
    assert "'require_group_assignment_for_file_sync': False" in settings_text
    assert "'file_sync_allowed_group_ids': []" in settings_text
    assert "'require_public_workspace_assignment_for_file_sync': False" in settings_text
    assert "'file_sync_allowed_public_workspace_ids': []" in settings_text


def test_group_public_gates_use_assignment_lists():
    """Validate group/public File Sync gates use assigned workspace ids."""
    group_gate = get_function_source(
        "application/single_app/functions_file_sync.py",
        "is_file_sync_enabled_for_group",
    )
    public_gate = get_function_source(
        "application/single_app/functions_file_sync.py",
        "is_file_sync_enabled_for_public_workspace",
    )

    assert "require_group_assignment_for_file_sync" in group_gate
    assert "file_sync_allowed_group_ids" in group_gate
    assert "file_sync_group_require_app_role" not in group_gate
    assert "GroupFileSyncUser" not in group_gate

    assert "require_public_workspace_assignment_for_file_sync" in public_gate
    assert "file_sync_allowed_public_workspace_ids" in public_gate
    assert "file_sync_public_require_app_role" not in public_gate
    assert "PublicWorkspaceFileSyncUser" not in public_gate


def test_scheduled_runs_honor_workspace_assignments():
    """Validate scheduled File Sync skips unassigned group/public sources."""
    scheduler_guard = get_function_source(
        "application/single_app/functions_file_sync.py",
        "_is_scheduled_source_allowed",
    )
    scheduler = get_function_source(
        "application/single_app/functions_file_sync.py",
        "check_due_file_sync_sources_once",
    )

    assert "_is_scheduled_source_allowed(source, settings)" in scheduler
    assert "require_group_assignment_for_file_sync" in scheduler_guard
    assert "file_sync_allowed_group_ids" in scheduler_guard
    assert "require_public_workspace_assignment_for_file_sync" in scheduler_guard
    assert "file_sync_allowed_public_workspace_ids" in scheduler_guard


def test_admin_settings_assignment_ui_and_persistence():
    """Validate Admin Settings renders and saves File Sync assignment lists."""
    admin_template = read_text("application/single_app/templates/admin_settings.html")
    admin_route = read_text("application/single_app/route_frontend_admin_settings.py")
    admin_js = read_text("application/single_app/static/js/admin/admin_settings.js")

    for field_name in [
        "require_group_assignment_for_file_sync",
        "file_sync_allowed_group_ids",
        "require_public_workspace_assignment_for_file_sync",
        "file_sync_allowed_public_workspace_ids",
    ]:
        assert f'name="{field_name}"' in admin_template
        assert field_name in admin_route

    assert "Require Group Assignment to Use File Sync" in admin_template
    assert "Require Public Workspace Assignment to Use File Sync" in admin_template
    assert "fileSyncGroupAssignmentModal" in admin_template
    assert "fileSyncPublicWorkspaceAssignmentModal" in admin_template
    assert "setupFileSyncAssignments" in admin_js
    assert "file_sync_group_require_app_role" not in admin_template
    assert "file_sync_public_require_app_role" not in admin_template
    assert "GroupFileSyncUser" not in admin_template
    assert "PublicWorkspaceFileSyncUser" not in admin_template


if __name__ == "__main__":
    tests = [
        test_assignment_settings_are_defined_and_normalized,
        test_group_public_gates_use_assignment_lists,
        test_scheduled_runs_honor_workspace_assignments,
        test_admin_settings_assignment_ui_and_persistence,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as ex:
            print(f"Test failed: {ex}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)