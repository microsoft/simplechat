#!/usr/bin/env python3
# test_approval_notification_routing_fix.py
"""
Functional test for approval notification routing, cleanup, and template activity logging.
Version: 0.239.162
Implemented in: 0.239.159

This test ensures that approval requests notify submitters and reviewers,
that reviewer pending notifications are cleared when a decision is made,
and that agent template review outcomes notify the original submitter.
"""

import copy
import os
import sys

from azure.cosmos import exceptions

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class FakeNotificationContainer:
    """In-memory Cosmos-like container for notification tests."""

    def __init__(self):
        self.items = {}

    def create_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def delete_item(self, item=None, partition_key=None):
        item_id = item if item is not None else partition_key
        if item_id not in self.items:
            raise exceptions.CosmosResourceNotFoundError(message='Notification not found')
        del self.items[item_id]

    def query_items(self, query=None, parameters=None, partition_key=None, enable_cross_partition_query=False):
        results = [copy.deepcopy(item) for item in self.items.values()]
        parameter_map = {param['name']: param['value'] for param in (parameters or [])}

        if "c.scope = 'assignment'" in (query or ''):
            results = [item for item in results if item.get('scope') == 'assignment']

        if '@notification_id' in parameter_map:
            results = [item for item in results if item.get('id') == parameter_map['@notification_id']]

        if '@user_id' in parameter_map:
            results = [item for item in results if item.get('user_id') == parameter_map['@user_id']]

        if '@group_id' in parameter_map:
            results = [item for item in results if item.get('group_id') == parameter_map['@group_id']]

        notification_types = [
            value
            for name, value in parameter_map.items()
            if name.startswith('@notification_type')
        ]
        if notification_types:
            results = [
                item for item in results
                if item.get('notification_type') in notification_types
            ]

        for metadata_key in ('approval_id', 'template_id'):
            parameter_name = f'@metadata_{metadata_key}'
            if parameter_name in parameter_map:
                results = [
                    item for item in results
                    if item.get('metadata', {}).get(metadata_key) == parameter_map[parameter_name]
                ]

        return results


class FakeApprovalsContainer:
    """In-memory Cosmos-like container for approval documents."""

    def __init__(self):
        self.items = {}

    def create_item(self, body=None, **kwargs):
        item = body or kwargs.get('item')
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def read_item(self, item=None, partition_key=None):
        if item not in self.items:
            raise exceptions.CosmosResourceNotFoundError(message='Approval not found')
        stored = self.items[item]
        if partition_key != stored.get('group_id'):
            raise exceptions.CosmosResourceNotFoundError(message='Approval partition mismatch')
        return copy.deepcopy(stored)


class FakeTemplateContainer:
    """In-memory Cosmos-like container for agent template documents."""

    def __init__(self):
        self.items = {}

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def read_item(self, item=None, partition_key=None):
        if item not in self.items:
            raise exceptions.CosmosResourceNotFoundError(message='Template not found')
        stored = self.items[item]
        if partition_key != stored.get('id'):
            raise exceptions.CosmosResourceNotFoundError(message='Template partition mismatch')
        return copy.deepcopy(stored)

    def delete_item(self, item=None, partition_key=None):
        if item not in self.items:
            raise exceptions.CosmosResourceNotFoundError(message='Template not found')
        del self.items[item]


class FakeActivityLogsContainer:
    """In-memory Cosmos-like container for activity log tests."""

    def __init__(self):
        self.items = {}

    def create_item(self, body=None, **kwargs):
        item = body or kwargs.get('item')
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)


def _notification_types(container, metadata_key, metadata_value):
    return sorted([
        item.get('notification_type')
        for item in container.items.values()
        if item.get('metadata', {}).get(metadata_key) == metadata_value
    ])


def _notifications(container, metadata_key, metadata_value):
    return [
        copy.deepcopy(item)
        for item in container.items.values()
        if item.get('metadata', {}).get(metadata_key) == metadata_value
    ]


def _activity_logs(container, activity_type):
    return [
        copy.deepcopy(item)
        for item in container.items.values()
        if item.get('activity_type') == activity_type
    ]


def test_standard_approval_notifications_and_cleanup():
    """Verify submitter/admin notifications and cleanup for standard approvals."""
    print('🔍 Testing standard approval notification lifecycle...')

    import functions_approvals
    import functions_notifications

    notification_container = FakeNotificationContainer()
    approval_container = FakeApprovalsContainer()
    group_doc = {
        'id': 'group-1',
        'name': 'Operations Group',
        'owner': {
            'id': 'group-owner-1',
            'email': 'owner@example.com',
            'displayName': 'Group Owner'
        }
    }

    originals = {
        'notification_container': functions_notifications.cosmos_notifications_container,
        'approval_container': functions_approvals.cosmos_approvals_container,
        'find_group_by_id': functions_approvals.find_group_by_id,
        'approvals_log_event': functions_approvals.log_event,
    }

    functions_notifications.cosmos_notifications_container = notification_container
    functions_approvals.cosmos_approvals_container = approval_container
    functions_approvals.find_group_by_id = lambda group_id: copy.deepcopy(group_doc) if group_id == group_doc['id'] else None
    functions_approvals.log_event = lambda *args, **kwargs: None

    try:
        approved_request = functions_approvals.create_approval_request(
            request_type=functions_approvals.TYPE_DELETE_GROUP,
            group_id='group-1',
            requester_id='requester-1',
            requester_email='requester@example.com',
            requester_name='Requester One',
            reason='Please remove this unused group.',
            metadata={'entity_type': 'group'}
        )

        pending_types = _notification_types(notification_container, 'approval_id', approved_request['id'])
        if pending_types.count('approval_request_pending') != 1 or pending_types.count('approval_request_pending_submitter') != 1:
            print(f'❌ Unexpected pending notification set: {pending_types}')
            return False

        functions_approvals.approve_request(
            approval_id=approved_request['id'],
            group_id='group-1',
            approver_id='admin-1',
            approver_email='admin@example.com',
            approver_name='Admin Reviewer',
            comment='Looks good.'
        )

        approved_types = _notification_types(notification_container, 'approval_id', approved_request['id'])
        if 'approval_request_pending' in approved_types:
            print(f'❌ Pending admin notification was not cleared after approval: {approved_types}')
            return False
        if 'approval_request_approved' not in approved_types:
            print(f'❌ Approved notification missing after approval: {approved_types}')
            return False

        denied_request = functions_approvals.create_approval_request(
            request_type=functions_approvals.TYPE_DELETE_DOCUMENTS,
            group_id='group-1',
            requester_id='requester-2',
            requester_email='requester2@example.com',
            requester_name='Requester Two',
            reason='Clear legacy documents.',
            metadata={'entity_type': 'group'}
        )

        functions_approvals.deny_request(
            approval_id=denied_request['id'],
            group_id='group-1',
            denier_id='admin-2',
            denier_email='admin2@example.com',
            denier_name='Admin Denier',
            comment='Need more details.',
            auto_denied=False
        )

        denied_types = _notification_types(notification_container, 'approval_id', denied_request['id'])
        if 'approval_request_pending' in denied_types:
            print(f'❌ Pending admin notification was not cleared after denial: {denied_types}')
            return False
        if 'approval_request_denied' not in denied_types:
            print(f'❌ Denied notification missing after denial: {denied_types}')
            return False

        denied_notifications = _notifications(notification_container, 'approval_id', denied_request['id'])
        denied_message = next(
            (
                item.get('message', '')
                for item in denied_notifications
                if item.get('notification_type') == 'approval_request_denied'
            ),
            ''
        )
        if 'Need more details.' not in denied_message:
            print(f'❌ Denied approval notification did not include reason: {denied_message}')
            return False

        print('✅ Standard approvals notify submitters and clear reviewer pending notifications')
        return True
    finally:
        functions_notifications.cosmos_notifications_container = originals['notification_container']
        functions_approvals.cosmos_approvals_container = originals['approval_container']
        functions_approvals.find_group_by_id = originals['find_group_by_id']
        functions_approvals.log_event = originals['approvals_log_event']


def test_agent_template_review_notifications_and_cleanup():
    """Verify template review notifications for approve, reject, and delete paths."""
    print('🔍 Testing agent template approval notification lifecycle...')

    import functions_agent_templates
    import functions_activity_logging
    import functions_notifications

    notification_container = FakeNotificationContainer()
    template_container = FakeTemplateContainer()
    activity_container = FakeActivityLogsContainer()

    originals = {
        'notification_container': functions_notifications.cosmos_notifications_container,
        'template_container': functions_agent_templates.cosmos_agent_templates_container,
        'template_log_event': functions_agent_templates.log_event,
        'activity_container': functions_activity_logging.cosmos_activity_logs_container,
        'activity_log_event': functions_activity_logging.log_event,
    }

    functions_notifications.cosmos_notifications_container = notification_container
    functions_agent_templates.cosmos_agent_templates_container = template_container
    functions_agent_templates.log_event = lambda *args, **kwargs: None
    functions_activity_logging.cosmos_activity_logs_container = activity_container
    functions_activity_logging.log_event = lambda *args, **kwargs: None

    submitter = {
        'userId': 'template-user-1',
        'email': 'template-user@example.com',
        'displayName': 'Template Submitter'
    }
    admin = {
        'userId': 'template-admin-1',
        'email': 'template-admin@example.com',
        'displayName': 'Template Admin'
    }

    try:
        approved_template = functions_agent_templates.create_agent_template(
            payload={
                'title': 'Agent One',
                'display_name': 'Agent One',
                'description': 'Test agent for approval.',
                'instructions': 'Always be helpful.',
                'source_scope': 'personal'
            },
            user_info=submitter,
            auto_approve=False
        )

        initial_types = _notification_types(notification_container, 'template_id', approved_template['id'])
        if initial_types.count('agent_template_pending_admin') != 1 or initial_types.count('agent_template_pending_submitter') != 1:
            print(f'❌ Unexpected pending template notifications: {initial_types}')
            return False
        if not _activity_logs(activity_container, 'agent_template_submission'):
            print('❌ Template submission activity log missing')
            return False

        functions_agent_templates.approve_agent_template(approved_template['id'], admin, notes='Approved for gallery.')
        approved_types = _notification_types(notification_container, 'template_id', approved_template['id'])
        if 'agent_template_pending_admin' in approved_types:
            print(f'❌ Pending admin template notification not cleared after approval: {approved_types}')
            return False
        if 'agent_template_approved' not in approved_types:
            print(f'❌ Approved template notification missing: {approved_types}')
            return False
        approval_logs = _activity_logs(activity_container, 'agent_template_approval')
        if not approval_logs:
            print('❌ Template approval activity log missing')
            return False

        rejected_template = functions_agent_templates.create_agent_template(
            payload={
                'title': 'Agent Two',
                'display_name': 'Agent Two',
                'description': 'Test agent for rejection.',
                'instructions': 'Never leak secrets.',
                'source_scope': 'personal'
            },
            user_info=submitter,
            auto_approve=False
        )

        functions_agent_templates.reject_agent_template(
            rejected_template['id'],
            admin,
            reason='Needs clearer instructions.',
            notes='Please simplify the prompt.'
        )
        rejected_types = _notification_types(notification_container, 'template_id', rejected_template['id'])
        if 'agent_template_pending_admin' in rejected_types:
            print(f'❌ Pending admin template notification not cleared after rejection: {rejected_types}')
            return False
        if 'agent_template_rejected' not in rejected_types:
            print(f'❌ Rejected template notification missing: {rejected_types}')
            return False

        rejected_notifications = _notifications(notification_container, 'template_id', rejected_template['id'])
        rejected_message = next(
            (
                item.get('message', '')
                for item in rejected_notifications
                if item.get('notification_type') == 'agent_template_rejected'
            ),
            ''
        )
        if 'Needs clearer instructions.' not in rejected_message:
            print(f'❌ Rejected template notification did not include reason: {rejected_message}')
            return False
        rejection_logs = _activity_logs(activity_container, 'agent_template_rejection')
        if not rejection_logs:
            print('❌ Template rejection activity log missing')
            return False
        if rejection_logs[-1].get('review_reason') != 'Needs clearer instructions.':
            print(f"❌ Template rejection activity log missing review reason: {rejection_logs[-1]}")
            return False

        deleted_template = functions_agent_templates.create_agent_template(
            payload={
                'title': 'Agent Three',
                'display_name': 'Agent Three',
                'description': 'Test agent for deletion.',
                'instructions': 'Be concise.',
                'source_scope': 'personal'
            },
            user_info=submitter,
            auto_approve=False
        )

        deleted = functions_agent_templates.delete_agent_template(deleted_template['id'], actor_info=admin)
        if not deleted:
            print('❌ Expected template deletion to succeed')
            return False

        deleted_types = _notification_types(notification_container, 'template_id', deleted_template['id'])
        if 'agent_template_pending_admin' in deleted_types:
            print(f'❌ Pending admin template notification not cleared after deletion: {deleted_types}')
            return False
        if 'agent_template_deleted' not in deleted_types:
            print(f'❌ Deleted template notification missing: {deleted_types}')
            return False
        if not _activity_logs(activity_container, 'agent_template_deletion'):
            print('❌ Template deletion activity log missing')
            return False

        print('✅ Agent template review notifications route to submitters and clear stale admin pending notices')
        return True
    finally:
        functions_notifications.cosmos_notifications_container = originals['notification_container']
        functions_agent_templates.cosmos_agent_templates_container = originals['template_container']
        functions_agent_templates.log_event = originals['template_log_event']
        functions_activity_logging.cosmos_activity_logs_container = originals['activity_container']
        functions_activity_logging.log_event = originals['activity_log_event']


def test_notification_display_backfills_rejection_reasons_from_metadata():
    """Verify notification reads append reasons for older generic rejection messages."""
    print('🔍 Testing notification display fallback for rejection reasons...')

    import functions_notifications
    import functions_group
    import functions_public_workspaces

    notification_container = FakeNotificationContainer()
    notification_container.create_item({
        'id': 'approval-denied-legacy',
        'user_id': 'legacy-user',
        'group_id': None,
        'public_workspace_id': None,
        'scope': 'personal',
        'notification_type': 'approval_request_denied',
        'title': 'Request Denied',
        'message': 'Your request was denied by break glass.',
        'created_at': '2026-03-25T15:00:00+00:00',
        'ttl': 100,
        'read_by': [],
        'dismissed_by': [],
        'link_url': '/approvals',
        'link_context': {'approval_id': 'approval-legacy'},
        'metadata': {
            'approval_id': 'approval-legacy',
            'comment': 'Testing the rejection reason in notifications'
        },
        'assignment': None
    })
    notification_container.create_item({
        'id': 'template-rejected-legacy',
        'user_id': 'legacy-user',
        'group_id': None,
        'public_workspace_id': None,
        'scope': 'personal',
        'notification_type': 'agent_template_rejected',
        'title': 'Template Declined: pa-gle',
        'message': "Your template 'pa-gle' was declined by break glass.",
        'created_at': '2026-03-25T15:01:00+00:00',
        'ttl': 100,
        'read_by': [],
        'dismissed_by': [],
        'link_url': '/workspace',
        'link_context': {'template_id': 'template-legacy'},
        'metadata': {
            'template_id': 'template-legacy',
            'rejection_reason': 'Testing the rejection reason in notifications'
        },
        'assignment': None
    })

    originals = {
        'notification_container': functions_notifications.cosmos_notifications_container,
        'get_user_groups': functions_group.get_user_groups,
        'get_user_public_workspaces': functions_public_workspaces.get_user_public_workspaces,
    }

    functions_notifications.cosmos_notifications_container = notification_container
    functions_group.get_user_groups = lambda user_id: []
    functions_public_workspaces.get_user_public_workspaces = lambda user_id: []

    try:
        result = functions_notifications.get_user_notifications(
            user_id='legacy-user',
            page=1,
            per_page=20,
            include_read=True,
            include_dismissed=False,
            user_roles=[]
        )
        notifications = {item['id']: item for item in result['notifications']}

        approval_message = notifications['approval-denied-legacy']['message']
        if 'Testing the rejection reason in notifications' not in approval_message:
            print(f'❌ Approval denial display message missing reason fallback: {approval_message}')
            return False

        template_message = notifications['template-rejected-legacy']['message']
        if 'Testing the rejection reason in notifications' not in template_message:
            print(f'❌ Template rejection display message missing reason fallback: {template_message}')
            return False

        print('✅ Notification display backfills rejection reasons from metadata')
        return True
    finally:
        functions_notifications.cosmos_notifications_container = originals['notification_container']
        functions_group.get_user_groups = originals['get_user_groups']
        functions_public_workspaces.get_user_public_workspaces = originals['get_user_public_workspaces']


if __name__ == '__main__':
    tests = [
        test_standard_approval_notifications_and_cleanup,
        test_agent_template_review_notifications_and_cleanup,
        test_notification_display_backfills_rejection_reasons_from_metadata,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)