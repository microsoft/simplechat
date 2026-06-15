# test_group_workflows_feature.py
#!/usr/bin/env python3
"""
Functional test for group workflows.
Version: 0.241.201
Implemented in: 0.241.179
Updated in: 0.241.201

This test ensures that group workflow storage, settings, routes, scheduler,
runtime wiring, activity deep links, and workspace UI contracts are present.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _assert_contains(content, expected, label):
    if expected not in content:
        print(f"FAIL: Missing {label}: {expected}")
        return False
    print(f"PASS: Found {label}")
    return True


def test_group_workflow_feature_contracts():
    """Validate the static contracts for group workflow feature parity."""
    print("Testing group workflow feature contracts...")

    config = _read("application/single_app/config.py")
    settings = _read("application/single_app/functions_settings.py")
    group_workflows = _read("application/single_app/functions_group_workflows.py")
    workflow_routes = _read("application/single_app/route_backend_workflows.py")
    workflow_runner = _read("application/single_app/functions_workflow_runner.py")
    background_tasks = _read("application/single_app/background_tasks.py")
    admin_template = _read("application/single_app/templates/admin_settings.html")
    admin_js = _read("application/single_app/static/js/admin/admin_settings.js")
    workspace_template = _read("application/single_app/templates/workspace.html")
    group_template = _read("application/single_app/templates/group_workspaces.html")
    workspace_workflows_js = _read("application/single_app/static/js/workspace/workspace_workflows.js")
    activity_js = _read("application/single_app/static/js/workflow/workflow-activity.js")

    checks = [
        _assert_contains(config, 'VERSION = "0.241.201"', "version bump"),
        _assert_contains(config, 'cosmos_group_workflows_container_name = "group_workflows"', "group workflow container"),
        _assert_contains(config, 'cosmos_group_workflow_runs_container_name = "group_workflow_runs"', "group workflow runs container"),
        _assert_contains(config, 'cosmos_group_workflow_run_items_container_name = "group_workflow_run_items"', "group workflow run items container"),
        _assert_contains(settings, "'allow_group_workflows': False", "group workflow default disabled"),
        _assert_contains(settings, "'require_group_assignment_for_group_workflows': False", "group workflow assignment default"),
        _assert_contains(settings, "def is_group_workflows_enabled_for_group", "group assignment helper"),
        _assert_contains(settings, "def get_group_workflow_management_roles", "group workflow management role helper"),
        _assert_contains(group_workflows, 'GROUP_WORKFLOW_MEMBER_ROLES = ("Owner", "Admin", "DocumentManager", "User")', "member runtime roles"),
        _assert_contains(group_workflows, "def get_group_workflow_agent_options", "group agent picker helper"),
        _assert_contains(group_workflows, "is_file_sync_enabled_for_group", "group File Sync gate"),
        _assert_contains(group_workflows, "scope_type != FILE_SYNC_SCOPE_GROUP or scope_id != group_id", "group-only File Sync sources"),
        _assert_contains(group_workflows, "def get_due_group_workflows", "scheduled group workflow query"),
        _assert_contains(workflow_routes, "@app.route('/api/group/workflows'", "group workflow list/save route"),
        _assert_contains(workflow_routes, "@app.route('/api/group/workflows/agents'", "group workflow agents route"),
        _assert_contains(workflow_routes, "@app.route('/api/group/workflows/file-sync-sources'", "group workflow File Sync route"),
        _assert_contains(workflow_routes, "@app.route('/api/group/workflows/activity'", "group workflow activity route"),
        _assert_contains(workflow_routes, "def _resolve_group_workflow_request_group", "group activity deep-link resolver"),
        _assert_contains(workflow_routes, "run_group_workflow", "group workflow runner route call"),
        _assert_contains(workflow_runner, "def run_group_workflow", "group workflow runner"),
        _assert_contains(workflow_runner, "Group workflow execution requires a group id.", "group runner scope validation"),
        _assert_contains(workflow_runner, "g.conversation_group_id", "group conversation context"),
        _assert_contains(background_tasks, "get_due_group_workflows", "scheduled group workflow polling"),
        _assert_contains(background_tasks, "group_workflow_run_", "group workflow scheduler lock"),
        _assert_contains(admin_template, "Enable Group Workflows", "admin enable setting"),
        _assert_contains(admin_template, "Require Group Assignment to Use Workflow", "admin assignment setting"),
        _assert_contains(admin_template, "Group Workflow Assignments", "admin assignment modal"),
        _assert_contains(admin_template, "Require Owner to Manage Group Agents, Actions and Workflows", "owner-only setting rename"),
        _assert_contains(admin_js, "setupGroupWorkflowAssignments", "admin assignment JavaScript"),
        _assert_contains(admin_js, "url.searchParams.set('showAll', 'true')", "admin group discovery API use"),
        _assert_contains(workspace_template, "Personal Workflows", "personal workflow rename"),
        _assert_contains(group_template, "Group Workflows", "group workflow tab label"),
        _assert_contains(group_template, "window.workflowWorkspaceConfig", "group workflow UI config"),
        _assert_contains(group_template, "apiBase: '/api/group/workflows'", "group workflow API base"),
        _assert_contains(group_template, "scope: 'group'", "group workflow UI scope"),
        _assert_contains(group_template, "js/workspace/workspace_workflows.js", "shared workflow UI module"),
        _assert_contains(workspace_workflows_js, "function getWorkflowLabel", "scope-aware workflow labels"),
        _assert_contains(workspace_workflows_js, "activityScope === \"group\"", "group activity URL builder"),
        _assert_contains(activity_js, '"/api/group/workflows/activity"', "group activity API path"),
        _assert_contains(activity_js, 'url.searchParams.set("group_id", groupId)', "group activity query propagation"),
    ]

    passed = all(checks)
    print(f"Result: {sum(1 for item in checks if item)}/{len(checks)} checks passed")
    return passed


if __name__ == "__main__":
    success = test_group_workflow_feature_contracts()
    sys.exit(0 if success else 1)