# test_group_workflow_activity_view_gate.py
#!/usr/bin/env python3
"""
Functional test for group workflow activity view authorization.
Version: 0.241.179
Implemented in: 0.241.179

This test ensures that the shared workflow activity page can render for group
workflow activity when personal workflows are disabled, while preserving the
personal workflow gate for personal activity links.
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


def _assert_not_contains(content, unexpected, label):
    if unexpected in content:
        print(f"FAIL: Found unexpected {label}: {unexpected}")
        return False
    print(f"PASS: Did not find {label}")
    return True


def _extract_workflow_activity_route(content):
    route_marker = "@app.route('/workflow-activity', methods=['GET'])"
    start_index = content.find(route_marker)
    if start_index == -1:
        return ""

    next_route_index = content.find("\n    @app.route(", start_index + len(route_marker))
    if next_route_index == -1:
        return content[start_index:]
    return content[start_index:next_route_index]


def test_group_workflow_activity_view_gate():
    """Validate group workflow activity view gating is independent of personal workflows."""
    print("Testing group workflow activity view gate...")

    config = _read("application/single_app/config.py")
    frontend_chats = _read("application/single_app/route_frontend_chats.py")
    activity_js = _read("application/single_app/static/js/workflow/workflow-activity.js")
    workspace_workflows_js = _read("application/single_app/static/js/workspace/workspace_workflows.js")

    activity_route = _extract_workflow_activity_route(frontend_chats)

    checks = [
        _assert_contains(config, 'VERSION = "0.241.179"', "version bump"),
        _assert_contains(frontend_chats, "def _authorize_workflow_activity_view", "scope-aware activity authorization helper"),
        _assert_contains(frontend_chats, "scope == 'group'", "group activity scope branch"),
        _assert_contains(frontend_chats, "allow_group_workflows", "group workflow feature gate"),
        _assert_contains(frontend_chats, "is_group_workflows_enabled_for_group(settings, group_id)", "group assignment gate"),
        _assert_contains(frontend_chats, "_resolve_workflow_activity_group_id", "group activity membership resolver"),
        _assert_contains(frontend_chats, "is_user_workflows_enabled_for_user(settings, user_roles=user_roles)", "personal activity gate retained"),
        _assert_contains(activity_route, "authorization_error = _authorize_workflow_activity_view(user_id, settings)", "route uses scope-aware authorization"),
        _assert_not_contains(activity_route, "@enabled_required('allow_user_workflows')", "personal enabled decorator on shared activity page"),
        _assert_not_contains(activity_route, "@workflow_user_required", "personal role decorator on shared activity page"),
        _assert_contains(workspace_workflows_js, 'url.searchParams.set("scope", activityScope)', "group activity link scope parameter"),
        _assert_contains(workspace_workflows_js, 'url.searchParams.set("groupId", activeGroupId)', "group activity link group parameter"),
        _assert_contains(activity_js, '"/api/group/workflows/activity"', "group activity API selection"),
        _assert_contains(activity_js, 'url.searchParams.set("group_id", groupId)', "group activity API group propagation"),
    ]

    passed = all(checks)
    print(f"Result: {sum(1 for item in checks if item)}/{len(checks)} checks passed")
    return passed


if __name__ == "__main__":
    success = test_group_workflow_activity_view_gate()
    sys.exit(0 if success else 1)