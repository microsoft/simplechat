#!/usr/bin/env python3
"""
Functional test for File Sync capability wiring.
Version: 0.241.042
Implemented in: 0.241.042

This test ensures File Sync storage, settings, routes, scheduler hooks, and
credential redaction are wired without requiring live Cosmos DB or SMB access.
"""

import ast
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def read_text(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_config_version_and_containers():
    """Validate version bump and File Sync Cosmos containers."""
    config_text = read_text("application/single_app/config.py")
    assert 'VERSION = "0.241.042"' in config_text

    expected_containers = [
        "personal_file_sync_sources",
        "group_file_sync_sources",
        "public_file_sync_sources",
        "personal_file_sync_items",
        "group_file_sync_items",
        "public_file_sync_items",
        "personal_file_sync_runs",
        "group_file_sync_runs",
        "public_file_sync_runs",
    ]
    missing = [container for container in expected_containers if container not in config_text]
    assert not missing, f"Missing File Sync containers: {missing}"
    assert 'PartitionKey(path="/source_id")' in config_text


def test_file_sync_settings_and_routes():
    """Validate settings defaults and route registration."""
    settings_text = read_text("application/single_app/functions_settings.py")
    route_text = read_text("application/single_app/route_backend_file_sync.py")
    app_text = read_text("application/single_app/app.py")

    for key in [
        "enable_file_sync",
        "enable_file_sync_personal",
        "enable_file_sync_group",
        "enable_file_sync_public",
        "file_sync_allowed_users",
        "file_sync_blocked_users",
        "file_sync_allowed_groups",
        "file_sync_blocked_groups",
        "file_sync_allowed_public_workspaces",
        "file_sync_blocked_public_workspaces",
    ]:
        assert key in settings_text

    route_count = len(re.findall(r"@app\.route\(", route_text))
    swagger_count = route_text.count("@swagger_route(security=get_auth_security())")
    assert route_count > 0
    assert route_count == swagger_count
    assert "register_route_backend_file_sync(app)" in app_text


def test_file_sync_service_security_shapes():
    """Validate the service module has authorization and redaction safeguards."""
    file_sync_path = APP_ROOT / "functions_file_sync.py"
    file_sync_text = file_sync_path.read_text(encoding="utf-8")
    parsed = ast.parse(file_sync_text)
    function_names = {node.name for node in ast.walk(parsed) if isinstance(node, ast.FunctionDef)}

    expected_functions = {
        "get_authorized_sync_source",
        "assert_public_workspace_role",
        "sanitize_file_sync_source",
        "create_file_sync_source",
        "update_file_sync_source",
        "queue_file_sync_source_run",
        "check_due_file_sync_sources_once",
        "build_synced_document_delete_guard",
        "apply_synced_document_delete_action",
    }
    assert expected_functions.issubset(function_names)
    assert "assert_group_role" in file_sync_text
    assert "get_user_role_in_public_workspace" in file_sync_text
    assert "password_secret_name" in file_sync_text
    assert "sanitized_source.pop(\"auth\", None)" in file_sync_text


def test_file_sync_delete_guards():
    """Validate document delete routes call the synced-document guard."""
    route_files = [
        "application/single_app/route_backend_documents.py",
        "application/single_app/route_backend_group_documents.py",
        "application/single_app/route_backend_public_documents.py",
    ]
    for route_file in route_files:
        route_text = read_text(route_file)
        assert "build_synced_document_delete_guard" in route_text
        assert "apply_synced_document_delete_action" in route_text
        assert "file_sync_delete_action" in route_text


def test_file_sync_delete_prompt_frontend_wiring():
    """Validate workspace delete flows can resolve synced document delete actions."""
    frontend_files = [
        "application/single_app/static/js/workspace/workspace-documents.js",
        "application/single_app/templates/group_workspaces.html",
        "application/single_app/static/js/public/public_workspace.js",
    ]
    for frontend_file in frontend_files:
        frontend_text = read_text(frontend_file)
        assert "synced_document_delete_requires_action" in frontend_text
        assert "file_sync_delete_action" in frontend_text
        assert "ignore_remote" in frontend_text


def test_file_sync_activity_log_display_wiring():
    """Validate Control Center recognizes File Sync activity records."""
    control_center_template = read_text("application/single_app/templates/control_center.html")
    control_center_js = read_text("application/single_app/static/js/control-center.js")
    control_center_backend = read_text("application/single_app/route_backend_control_center.py")
    activity_logging_text = read_text("application/single_app/functions_activity_logging.py")

    assert "log_file_sync_activity" in activity_logging_text
    assert "activity_type': 'file_sync'" in activity_logging_text
    assert '<option value="file_sync">File Sync</option>' in control_center_template
    assert "'file_sync': 'File Sync'" in control_center_js
    assert "case 'file_sync':" in control_center_js
    assert "activity_type == 'file_sync'" in control_center_backend


def run_tests():
    """Run all tests in this file."""
    tests = [
        test_config_version_and_containers,
        test_file_sync_settings_and_routes,
        test_file_sync_service_security_shapes,
        test_file_sync_delete_guards,
        test_file_sync_delete_prompt_frontend_wiring,
        test_file_sync_activity_log_display_wiring,
    ]
    failures = []
    for test in tests:
        try:
            print(f"Running {test.__name__}...")
            test()
            print(f"Passed {test.__name__}")
        except Exception as error:
            failures.append((test.__name__, error))
            print(f"Failed {test.__name__}: {error}")

    if failures:
        return False
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)