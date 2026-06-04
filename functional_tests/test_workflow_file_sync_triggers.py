# test_workflow_file_sync_triggers.py
#!/usr/bin/env python3
"""
Functional test for workflow File Sync triggers and batch item tracking.
Version: 0.241.133
Implemented in: 0.241.133

This test ensures workflows can persist File Sync pre-run configuration,
monitor File Sync sources for changes, record per-document batch items,
and expose resume-failed item support.
"""

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def _read(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _assert_contains(content, expected, label):
    if expected not in content:
        print(f"FAIL: Missing {label}: {expected}")
        return False
    print(f"PASS: Found {label}")
    return True


def test_workflow_file_sync_trigger_contracts():
    """Validate the static contracts for workflow-triggered File Sync."""
    print("Testing workflow File Sync trigger contracts...")

    config = _read("application/single_app/config.py")
    personal_workflows = _read("application/single_app/functions_personal_workflows.py")
    workflow_runner = _read("application/single_app/functions_workflow_runner.py")
    file_sync = _read("application/single_app/functions_file_sync.py")
    workflow_routes = _read("application/single_app/route_backend_workflows.py")
    background_tasks = _read("application/single_app/background_tasks.py")
    workspace_workflows_js = _read("application/single_app/static/js/workspace/workspace_workflows.js")
    workspace_template = _read("application/single_app/templates/workspace.html")

    checks = [
        _assert_contains(config, 'VERSION = "0.241.133"', "version bump"),
        _assert_contains(config, 'cosmos_personal_workflow_run_items_container_name = "personal_workflow_run_items"', "workflow run item container"),
        _assert_contains(personal_workflows, "WORKFLOW_TRIGGER_TYPES = {'manual', 'interval', 'file_sync'}", "file_sync trigger type"),
        _assert_contains(personal_workflows, "def _normalize_file_sync_config", "workflow File Sync normalizer"),
        _assert_contains(personal_workflows, "__dynamic_file_sync_document__", "dynamic Analyze placeholder"),
        _assert_contains(personal_workflows, "def save_personal_workflow_run_item", "run item save helper"),
        _assert_contains(personal_workflows, "def list_personal_workflow_run_items", "run item list helper"),
        _assert_contains(file_sync, "run_inline: bool = False", "inline File Sync execution flag"),
        _assert_contains(file_sync, '"changed_documents": []', "changed document run metadata"),
        _assert_contains(file_sync, '"created": 0', "created count"),
        _assert_contains(file_sync, '"updated": 0', "updated count"),
        _assert_contains(file_sync, '"last_sync_action"', "sync item action metadata"),
        _assert_contains(workflow_runner, "def _execute_workflow_file_sync", "workflow File Sync pre-run executor"),
        _assert_contains(workflow_runner, "def _apply_file_sync_context_to_workflow", "dynamic File Sync context application"),
        _assert_contains(workflow_runner, "def _build_run_item_activity_callback", "per-document run item callback"),
        _assert_contains(workflow_routes, "/api/user/workflows/file-sync-sources", "File Sync source picker API"),
        _assert_contains(workflow_routes, "/resume-failed", "resume failed API"),
        _assert_contains(background_tasks, "file_sync_monitor", "File Sync monitor scheduler trigger source"),
        _assert_contains(workspace_template, "workflow-file-sync-enabled", "workflow File Sync modal control"),
        _assert_contains(workspace_template, "Monitor File Sync Changes", "monitor run mode option"),
        _assert_contains(workspace_workflows_js, "getSelectedFileSyncSources", "File Sync source payload builder"),
        _assert_contains(workspace_workflows_js, "resumeFailedWorkflowRun", "resume failed UI handler"),
    ]

    passed = all(checks)
    print(f"Result: {sum(1 for item in checks if item)}/{len(checks)} checks passed")
    return passed


if __name__ == "__main__":
    success = test_workflow_file_sync_trigger_contracts()
    sys.exit(0 if success else 1)
