#!/usr/bin/env python3
# test_safety_violation_remediation_approvals.py
"""
Functional test for safety violation remediation approvals.
Version: 0.261.297
Implemented in: 0.241.030
Warnings sent without approval, restriction notice persisted: 0.261.297

This test ensures warn, suspend, and block actions collect user-facing remediation
details; that a warning is sent as soon as a reviewer saves it, while a suspension or block
still needs a second eligible reviewer, and a requester can never approve their own
request; and that suspend and block write the same access restriction payload Control
Center uses, with the notice the user was sent. Real modules run in fresh processes with
network access blocked, under normal and optimized Python.
"""

import subprocess
import sys
from pathlib import Path

import pytest


ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / 'application' / 'single_app'

ADMIN_SAFETY_TEMPLATE = APP_DIR / 'templates' / 'admin_safety_violations.html'
ADMIN_SAFETY_JS = APP_DIR / 'static' / 'js' / 'admin' / 'admin-safety-violations.js'
APPROVALS_TEMPLATE = APP_DIR / 'templates' / 'approvals.html'
BACKEND_SAFETY_ROUTE = APP_DIR / 'route_backend_safety.py'


def read_text(path):
    return path.read_text(encoding='utf-8')


def assert_markers(source_text, markers, label):
    missing_markers = [marker for marker in markers if marker not in source_text]
    assert not missing_markers, f'Missing {label} markers: {missing_markers}'


def test_safety_remediation_ui_and_route_markers():
    """Safety admin UI should expose remediation details and pending approval states."""
    print('🔍 Testing safety remediation UI and approval markers...')

    admin_safety_template = read_text(ADMIN_SAFETY_TEMPLATE)
    admin_safety_js = read_text(ADMIN_SAFETY_JS)
    approvals_template = read_text(APPROVALS_TEMPLATE)
    backend_safety_route = read_text(BACKEND_SAFETY_ROUTE)

    assert_markers(
        admin_safety_template,
        [
            'id="safetyPageStatusAlert"',
            'id="safetyRemediationFields"',
            'id="editNotificationMessage"',
            'id="editSuspendUntil"',
            'id="safetyWarningAcknowledgment"',
        ],
        'admin safety template',
    )
    assert_markers(
        admin_safety_js,
        [
            'Pending approval',
            'notification_message',
            'datetime_to_allow',
            'function updateRemediationFields(logItem, forcePopulate)',
            'showPageStatus(result.message ||',
            'as soon as you save, without a second reviewer',
            'another eligible reviewer approves it',
        ],
        'admin safety script',
    )
    assert 'If this reviewer also has the required Control Center approval role' not in admin_safety_js
    assert_markers(
        approvals_template,
        [
            'value="warn_user"',
            'value="suspend_user"',
            'value="block_user"',
            '<th>Target</th>',
            'Warn User',
            'Suspend User',
            'Block User',
        ],
        'approvals template',
    )
    assert_markers(
        backend_safety_route,
        [
            "item['action_notification_title'] = notification_title or None",
            "item['action_notification_message'] = notification_message or None",
            "item['action_datetime_to_allow'] = normalized_datetime_to_allow",
            'SAFETY_APPROVAL_REQUIRED_ACTIONS = {',
            'return _send_safety_warning_now(item, actor, notification_title, notification_message)',
        ],
        'backend safety route',
    )

    print('✅ Safety remediation UI and approval markers are present')


REMEDIATION_PROBE = r'''
import importlib
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import build_safety_app, check, sign_in

with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    import functions_approvals
    import functions_safety_remediation as remediation
    import route_backend_safety as safety_routes

    with patch.object(functions_approvals, "get_settings", return_value={"require_member_of_control_center_admin": True}):
        for request_type in (functions_approvals.TYPE_WARN_USER, functions_approvals.TYPE_SUSPEND_USER,
                             functions_approvals.TYPE_BLOCK_USER):
            check(functions_approvals.get_approval_roles_for_request_type(request_type) == ["ControlCenterAdmin"],
                  request_type)
    with patch.object(functions_approvals, "get_settings", return_value={"require_member_of_control_center_admin": False}):
        check(functions_approvals.get_approval_roles_for_request_type(functions_approvals.TYPE_WARN_USER) == ["Admin"],
              "warn roles")

    approval_doc = {"request_type": functions_approvals.TYPE_SUSPEND_USER, "requester_id": "safety-admin-1", "metadata": {}}
    with patch.object(functions_approvals, "get_approval_roles_for_request_type", return_value=["ControlCenterAdmin"]):
        check(not functions_approvals._can_user_approve(approval_doc, "safety-admin-1", ["Admin"]), "requester approve")
        check(not functions_approvals._can_user_approve(approval_doc, "safety-admin-1", ["ControlCenterAdmin"]), "self")
        check(functions_approvals._can_user_deny(approval_doc, "safety-admin-1", ["ControlCenterAdmin"]), "deny")
        check(functions_approvals._can_user_approve(approval_doc, "control-admin-2", ["ControlCenterAdmin"]), "other")

    # The requester can never approve their own request, whatever roles they hold.
    pending = {"id": "approval-1", "group_id": "user-1", "status": "pending", "requester_id": "safety-admin-1",
               "request_type": functions_approvals.TYPE_BLOCK_USER}
    try:
        functions_approvals.approve_request("approval-1", "user-1", "safety-admin-1", "a@contoso.test", "A",
                                            approval=dict(pending))
    except PermissionError:
        pass
    else:
        raise AssertionError("A requester approved their own request")
    for request_type in safety_routes.SAFETY_ACTION_REQUEST_TYPE_MAP.values():
        check(safety_routes._actor_can_self_approve_safety_request(request_type, ["Admin", "ControlCenterAdmin"]) is False,
              request_type)

    # Suspend and block still wait for a second reviewer; nothing is applied on save.
    h = build_safety_app(stack)
    client, container = h.client, h.container
    base = {"user_id": "user-1", "status": "New", "action": "None", "created_at": "2026-10-01T00:00:00",
            "triggered_categories": [{"category": "Violence", "severity": 4}]}
    container.seed({**base, "id": "log-suspend"})
    container.seed({**base, "id": "log-block"})
    sign_in(client, "safety-admin-1", roles=("Admin",))
    for log_id, payload, request_type in (
        ("log-suspend", {"action": "SuspendUser", "datetime_to_allow": "2026-10-15T12:00:00Z",
                         "notification_message": "Suspended pending review."}, "suspend_user"),
        ("log-block", {"action": "BlockUser", "notification_message": "Blocked."}, "block_user"),
    ):
        response = client.patch(f"/api/safety/logs/{log_id}", json={"status": "In-Review", **payload})
        body = response.get_json()
        check(response.status_code == 200 and body["approval_required"] is True, str(body))
        approval = h.approvals[-1]
        check(approval["request_type"] == request_type and approval["requester_id"] == "safety-admin-1", str(approval))
        check(approval["group_id"] == "user-1" and approval["metadata"]["safety_log_id"] == log_id, str(approval))
        check(container.items[log_id]["action_request_status"] == "pending", log_id)
        response = client.patch(f"/api/safety/logs/{log_id}", json={"status": "Resolved"})
        check(response.status_code == 409, "A pending record could be changed")
    check(h.access_writes == [] and h.notifications == [], "A restriction applied before approval")

    response = client.patch("/api/safety/logs/log-suspend-missing", json={"status": "Resolved"})
    check(response.status_code == 404 and response.get_json() == {"error": "Safety violation not found"}, "missing")

    # Execution, once approved: the notification, plus the access payload Control Center
    # uses, with the notice the user was sent.
    h.notifications.clear()
    h.access_writes.clear()
    actor = {"id": "control-admin-2", "email": "approver@contoso.test"}
    safety_log = {"id": "safety-log-1", "user_id": "user-1", "notes": "Repeat policy violation.",
                  "triggered_categories": [{"category": "Violence", "severity": 4}, {"category": "Hate", "severity": 2}]}

    warn = remediation.execute_safety_violation_action(
        action="WarnUser", safety_log=safety_log, notification_title="", notification_message="",
        datetime_to_allow=None, actor=actor,
    )
    check(warn["success"] is True and warn["message"] == "Warning notification sent to the user.", str(warn))
    check(h.notifications[-1]["notification_type"] == "safety_violation_warning", "warning type")
    check(warn["notification_title"] == "Safety Violation Warning", str(warn))
    check(warn["notification_message"] == h.notifications[-1]["message"], "the sent message is not returned")
    check(h.access_writes == [], "A warning restricted access")

    suspend = remediation.execute_safety_violation_action(
        action="SuspendUser", safety_log=safety_log, notification_title="Temporary suspension",
        notification_message="Your access is suspended pending review.", datetime_to_allow="2025-01-15T12:00:00Z",
        actor=actor,
    )
    check(suspend["message"] == "User access suspended until 2025-01-15T12:00:00Z.", str(suspend))
    write = h.access_writes[-1]
    access = write["updates"]["access"]
    check(write["user_id"] == "user-1" and write["allow_cross_user"] is True, str(write))
    check(access["status"] == "deny" and access["datetime_to_allow"] == "2025-01-15T12:00:00Z", str(access))
    notice = access["notice"]
    check(notice["kind"] == "suspended" and notice["until"] == "2025-01-15T12:00:00Z", str(notice))
    check(notice["title"] == "Temporary suspension" and notice["message"] == "Your access is suspended pending review.",
          str(notice))
    check(notice["source"] == "safety_violation" and notice["reference_id"] == "safety-log-1" and notice["applied_at"],
          str(notice))
    check(h.notifications[-1]["notification_type"] == "safety_violation_suspension", "suspension type")
    check(h.notifications[-1]["title"] == notice["title"], "notice differs from the notification")

    block = remediation.execute_safety_violation_action(
        action="BlockUser", safety_log=safety_log, notification_title="", notification_message="",
        datetime_to_allow=None, actor=actor,
    )
    check(block["message"] == "User access blocked indefinitely.", str(block))
    access = h.access_writes[-1]["updates"]["access"]
    check(access["status"] == "deny" and access["datetime_to_allow"] is None, str(access))
    check(access["notice"]["kind"] == "blocked" and access["notice"]["until"] is None, str(access))
    check(access["notice"]["title"] == "Account Access Blocked", str(access))
    check(access["notice"]["message"] == h.notifications[-1]["message"], "the default notice differs from the sent one")
    check("Admin notes: Repeat policy violation." in access["notice"]["message"], "default message changed")
    check(h.notifications[-1]["notification_type"] == "safety_violation_block", "block type")

print("PASS: safety remediation approvals and execution")
'''


@pytest.mark.parametrize('optimized', [False, True])
def test_safety_remediation_execution_and_approval_roles(optimized):
    """Safety remediation roles, the two-person rule and execution payloads match the workflow."""
    command = [sys.executable, '-B']
    if optimized:
        command.append('-O')
    result = subprocess.run(
        command + ['-c', REMEDIATION_PROBE, str(ROOT_DIR), 'route_backend_safety'],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'PASS: safety remediation approvals and execution' in result.stdout


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
