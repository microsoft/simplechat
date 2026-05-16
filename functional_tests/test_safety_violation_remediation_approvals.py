#!/usr/bin/env python3
# test_safety_violation_remediation_approvals.py
"""
Functional test for safety violation remediation approvals.
Version: 0.241.030
Implemented in: 0.241.030

This test ensures warn, suspend, and block actions collect user-facing
remediation details, follow the shared approval workflow, and apply the same
access restriction payloads used by Control Center restrictions.
"""

import sys
from pathlib import Path
from unittest.mock import patch


ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / 'application' / 'single_app'

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


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
        ],
        'admin safety script',
    )
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
        ],
        'backend safety route',
    )

    print('✅ Safety remediation UI and approval markers are present')


def test_safety_remediation_execution_and_approval_roles():
    """Safety remediation roles and execution payloads should match the new workflow."""
    print('🔍 Testing safety remediation execution and approval role routing...')

    import functions_approvals
    import functions_safety_remediation

    with patch.object(functions_approvals, 'get_settings', return_value={'require_member_of_control_center_admin': True}):
        assert functions_approvals.get_approval_roles_for_request_type(functions_approvals.TYPE_WARN_USER) == ['ControlCenterAdmin']
        assert functions_approvals.get_approval_roles_for_request_type(functions_approvals.TYPE_SUSPEND_USER) == ['ControlCenterAdmin']
        assert functions_approvals.get_approval_roles_for_request_type(functions_approvals.TYPE_BLOCK_USER) == ['ControlCenterAdmin']

    with patch.object(functions_approvals, 'get_settings', return_value={'require_member_of_control_center_admin': False}):
        assert functions_approvals.get_approval_roles_for_request_type(functions_approvals.TYPE_WARN_USER) == ['Admin']

    approval_doc = {
        'request_type': functions_approvals.TYPE_SUSPEND_USER,
        'requester_id': 'safety-admin-1',
        'metadata': {},
    }
    with patch.object(functions_approvals, 'get_approval_roles_for_request_type', return_value=['ControlCenterAdmin']):
        assert not functions_approvals._can_user_approve(approval_doc, 'safety-admin-1', ['Admin'])
        assert not functions_approvals._can_user_approve(approval_doc, 'safety-admin-1', ['ControlCenterAdmin'])
        assert functions_approvals._can_user_deny(approval_doc, 'safety-admin-1', ['ControlCenterAdmin'])
        assert functions_approvals._can_user_approve(approval_doc, 'control-admin-2', ['ControlCenterAdmin'])

    created_notifications = []
    access_updates = []

    def fake_create_notification(**kwargs):
        notification = dict(kwargs)
        notification['id'] = f"notification-{len(created_notifications) + 1}"
        created_notifications.append(notification)
        return notification

    def fake_update_user_settings(user_id, updates, allow_cross_user=False):
        access_updates.append({
            'user_id': user_id,
            'updates': updates,
            'allow_cross_user': allow_cross_user,
        })
        return {'id': user_id, 'settings': updates}

    actor = {
        'id': 'safety-admin-1',
        'email': 'safety.admin@example.com',
        'display_name': 'Safety Admin',
    }
    safety_log = {
        'id': 'safety-log-1',
        'user_id': 'user-1',
        'triggered_categories': [
            {'category': 'Violence', 'severity': 4},
            {'category': 'Hate', 'severity': 2},
        ],
        'notes': 'Repeat policy violation.',
    }

    with patch.object(functions_safety_remediation, 'create_notification', side_effect=fake_create_notification), \
         patch.object(functions_safety_remediation, 'update_user_settings', side_effect=fake_update_user_settings), \
         patch.object(functions_safety_remediation, 'get_user_settings', return_value={
             'email': 'user@example.com',
             'display_name': 'Target User',
         }), \
         patch.object(functions_safety_remediation, 'log_event', lambda *args, **kwargs: None), \
         patch.object(functions_safety_remediation, 'debug_print', lambda *args, **kwargs: None):
        warn_result = functions_safety_remediation.execute_safety_violation_action(
            action=functions_safety_remediation.SAFETY_REMEDIATION_WARNING,
            safety_log=safety_log,
            notification_title='',
            notification_message='',
            datetime_to_allow=None,
            actor=actor,
        )

        assert warn_result['success'] is True
        assert warn_result['message'] == 'Warning notification sent to the user.'
        assert created_notifications[-1]['notification_type'] == 'safety_violation_warning'
        assert access_updates == []

        suspend_result = functions_safety_remediation.execute_safety_violation_action(
            action=functions_safety_remediation.SAFETY_REMEDIATION_SUSPEND,
            safety_log=safety_log,
            notification_title='Temporary suspension',
            notification_message='Your access is suspended pending review.',
            datetime_to_allow='2025-01-15T12:00:00Z',
            actor=actor,
        )

        assert suspend_result['success'] is True
        assert suspend_result['message'] == 'User access suspended until 2025-01-15T12:00:00Z.'
        assert access_updates[-1]['user_id'] == 'user-1'
        assert access_updates[-1]['updates']['access']['status'] == 'deny'
        assert access_updates[-1]['updates']['access']['datetime_to_allow'] == '2025-01-15T12:00:00Z'
        assert access_updates[-1]['allow_cross_user'] is True
        assert created_notifications[-1]['notification_type'] == 'safety_violation_suspension'

        block_result = functions_safety_remediation.execute_safety_violation_action(
            action=functions_safety_remediation.SAFETY_REMEDIATION_BLOCK,
            safety_log=safety_log,
            notification_title='Access blocked',
            notification_message='Your access has been blocked.',
            datetime_to_allow=None,
            actor=actor,
        )

        assert block_result['success'] is True
        assert block_result['message'] == 'User access blocked indefinitely.'
        assert access_updates[-1]['updates']['access']['status'] == 'deny'
        assert access_updates[-1]['updates']['access']['datetime_to_allow'] is None
        assert created_notifications[-1]['notification_type'] == 'safety_violation_block'

    print('✅ Safety remediation execution and approval roles match the workflow')


if __name__ == '__main__':
    raise SystemExit(0)