#!/usr/bin/env python3
# test_collaboration_message_notifications.py
"""
Functional test for collaboration message notifications.
Version: 0.241.016
Implemented in: 0.241.016

This test ensures shared conversations create per-recipient inbox notifications
with chat deep links and mark those notifications read when the recipient opens
the shared conversation.
"""

import copy
import os
import sys

from flask import Flask


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


class FakeNotificationContainer:
    """In-memory container for collaboration notification tests."""

    def __init__(self):
        self.items = {}

    def create_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def query_items(self, query=None, parameters=None, partition_key=None, enable_cross_partition_query=False):
        results = [copy.deepcopy(item) for item in self.items.values()]
        parameter_map = {param['name']: param['value'] for param in (parameters or [])}

        if '@notification_id' in parameter_map:
            results = [item for item in results if item.get('id') == parameter_map['@notification_id']]
        if '@user_id' in parameter_map:
            results = [item for item in results if item.get('user_id') == parameter_map['@user_id']]
        if '@notification_type' in parameter_map:
            results = [
                item for item in results
                if item.get('notification_type') == parameter_map['@notification_type']
            ]
        if '@conversation_id' in parameter_map:
            results = [
                item for item in results
                if item.get('metadata', {}).get('conversation_id') == parameter_map['@conversation_id']
            ]

        return results


class FakeConversationContainer:
    """In-memory conversation lookup for collaboration route tests."""

    def __init__(self, items=None):
        self.items = {}
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        if item_id not in self.items:
            raise KeyError(item_id)
        return copy.deepcopy(self.items[item_id])


def build_mark_read_test_app(test_user_id, conversation_container, notification_container):
    """Register the collaboration mark-read route with fake auth/container dependencies."""
    import functions_notifications
    import route_backend_collaboration

    original_notification_container = functions_notifications.cosmos_notifications_container
    original_login_required = route_backend_collaboration.login_required
    original_user_required = route_backend_collaboration.user_required
    original_swagger_route = route_backend_collaboration.swagger_route
    original_get_auth_security = route_backend_collaboration.get_auth_security
    original_require_feature = route_backend_collaboration._require_collaboration_feature_enabled
    original_get_current_user = route_backend_collaboration._get_current_collaboration_user
    original_get_conversation = route_backend_collaboration.get_collaboration_conversation
    original_assert_view = route_backend_collaboration.assert_user_can_view_collaboration_conversation

    functions_notifications.cosmos_notifications_container = notification_container
    route_backend_collaboration.login_required = lambda func: func
    route_backend_collaboration.user_required = lambda func: func
    route_backend_collaboration.swagger_route = lambda **kwargs: (lambda func: func)
    route_backend_collaboration.get_auth_security = lambda: {}
    route_backend_collaboration._require_collaboration_feature_enabled = lambda: {}
    route_backend_collaboration._get_current_collaboration_user = lambda: {
        'user_id': test_user_id,
        'display_name': 'Recipient User',
        'email': 'recipient@example.com',
    }
    route_backend_collaboration.get_collaboration_conversation = lambda conversation_id: conversation_container.read_item(
        item=conversation_id,
        partition_key=conversation_id,
    )
    route_backend_collaboration.assert_user_can_view_collaboration_conversation = (
        lambda user_id, conversation_doc, allow_pending=False: {'user_state': None}
    )

    app = Flask(__name__)
    app.config['TESTING'] = True
    route_backend_collaboration.register_route_backend_collaboration(app)

    def restore():
        functions_notifications.cosmos_notifications_container = original_notification_container
        route_backend_collaboration.login_required = original_login_required
        route_backend_collaboration.user_required = original_user_required
        route_backend_collaboration.swagger_route = original_swagger_route
        route_backend_collaboration.get_auth_security = original_get_auth_security
        route_backend_collaboration._require_collaboration_feature_enabled = original_require_feature
        route_backend_collaboration._get_current_collaboration_user = original_get_current_user
        route_backend_collaboration.get_collaboration_conversation = original_get_conversation
        route_backend_collaboration.assert_user_can_view_collaboration_conversation = original_assert_view

    return app, restore


def unwrap_response(result):
    """Normalize Flask view return values into (response, status_code)."""
    if isinstance(result, tuple):
        response = result[0]
        status_code = result[1]
    else:
        response = result
        status_code = response.status_code

    return response, status_code


def test_collaboration_notification_helper_creates_deep_link():
    """Verify the helper creates a deep-link collaboration inbox notification."""
    print('🔍 Testing collaboration notification helper...')

    import functions_notifications
    from collaboration_models import GROUP_MULTI_USER_CHAT_TYPE

    fake_container = FakeNotificationContainer()
    original_container = functions_notifications.cosmos_notifications_container
    functions_notifications.cosmos_notifications_container = fake_container

    try:
        notification = functions_notifications.create_collaboration_message_notification(
            user_id='recipient-001',
            conversation_id='shared-conversation-001',
            message_id='shared-message-001',
            conversation_title='Shared Planning',
            sender_display_name='Owner User',
            message_preview='Please review the updated milestones.',
            chat_type=GROUP_MULTI_USER_CHAT_TYPE,
            group_id='group-001',
            mentioned_user=True,
        )

        assert notification is not None
        assert notification['notification_type'] == 'collaboration_message_received'
        assert notification['link_url'] == '/chats?conversationId=shared-conversation-001'
        assert notification['link_context']['conversation_kind'] == 'collaborative'
        assert notification['link_context']['group_id'] == 'group-001'
        assert notification['metadata']['conversation_id'] == 'shared-conversation-001'
        assert notification['metadata']['message_id'] == 'shared-message-001'
        assert notification['metadata']['mentioned_user'] is True
        assert 'tagged you' in notification['title']

        print('✅ Collaboration notification helper created the expected deep link and metadata')
        return True
    finally:
        functions_notifications.cosmos_notifications_container = original_container


def test_collaboration_notifications_fan_out_to_other_participants():
    """Verify shared-message notifications exclude the sender and flag direct mentions."""
    print('🔍 Testing collaboration notification recipient fan-out...')

    import functions_collaboration
    from collaboration_models import PERSONAL_MULTI_USER_CHAT_TYPE

    original_create_notification = functions_collaboration.create_collaboration_message_notification
    captured_calls = []

    functions_collaboration.create_collaboration_message_notification = lambda **kwargs: captured_calls.append(kwargs) or kwargs

    try:
        conversation_doc = {
            'id': 'shared-conversation-002',
            'title': 'Roadmap Review',
            'chat_type': PERSONAL_MULTI_USER_CHAT_TYPE,
            'accepted_participant_ids': ['owner-001', 'member-001', 'member-002'],
            'scope': {},
        }
        message_doc = {
            'id': 'shared-message-002',
            'conversation_id': 'shared-conversation-002',
            'content': 'Can @Member Two confirm the rollout plan?',
            'metadata': {
                'sender': {
                    'user_id': 'owner-001',
                    'display_name': 'Owner User',
                    'email': 'owner@example.com',
                },
                'mentioned_participants': [
                    {
                        'user_id': 'member-002',
                        'display_name': 'Member Two',
                        'email': 'member.two@example.com',
                    }
                ],
            },
        }

        notifications = functions_collaboration.create_collaboration_message_notifications(
            conversation_doc,
            message_doc,
        )

        assert len(notifications) == 2
        assert {call['user_id'] for call in captured_calls} == {'member-001', 'member-002'}

        mention_call = next(call for call in captured_calls if call['user_id'] == 'member-002')
        non_mention_call = next(call for call in captured_calls if call['user_id'] == 'member-001')

        assert mention_call['mentioned_user'] is True
        assert non_mention_call['mentioned_user'] is False
        assert all(call['conversation_id'] == 'shared-conversation-002' for call in captured_calls)

        print('✅ Collaboration notifications fan out to the expected recipients')
        return True
    finally:
        functions_collaboration.create_collaboration_message_notification = original_create_notification


def test_group_collaboration_notifications_use_group_membership():
    """Verify group collaborative conversations notify active group members except the sender."""
    print('🔍 Testing group collaboration notification recipients...')

    import functions_collaboration
    from collaboration_models import GROUP_MULTI_USER_CHAT_TYPE

    original_create_notification = functions_collaboration.create_collaboration_message_notification
    original_find_group_by_id = functions_collaboration.find_group_by_id
    captured_calls = []

    functions_collaboration.create_collaboration_message_notification = lambda **kwargs: captured_calls.append(kwargs) or kwargs
    functions_collaboration.find_group_by_id = lambda group_id: {
        'id': group_id,
        'owner': {'id': 'owner-001'},
        'users': [
            {'userId': 'owner-001'},
            {'userId': 'member-001'},
            {'userId': 'member-002'},
        ],
    }

    try:
        conversation_doc = {
            'id': 'shared-conversation-003',
            'title': 'Finance Shared Chat',
            'chat_type': GROUP_MULTI_USER_CHAT_TYPE,
            'scope': {'group_id': 'group-002'},
        }
        message_doc = {
            'id': 'shared-message-003',
            'conversation_id': 'shared-conversation-003',
            'content': 'The monthly close review is ready.',
            'metadata': {
                'sender': {
                    'user_id': 'member-001',
                    'display_name': 'Finance Member',
                },
                'mentioned_participants': [],
            },
        }

        functions_collaboration.create_collaboration_message_notifications(conversation_doc, message_doc)

        assert {call['user_id'] for call in captured_calls} == {'owner-001', 'member-002'}
        print('✅ Group collaboration notifications target group members other than the sender')
        return True
    finally:
        functions_collaboration.create_collaboration_message_notification = original_create_notification
        functions_collaboration.find_group_by_id = original_find_group_by_id


def test_mark_read_route_clears_collaboration_notifications():
    """Verify the collaboration mark-read API clears inbox notifications for the shared conversation."""
    print('🔍 Testing collaboration notification mark-read route...')

    import functions_notifications

    test_user_id = 'recipient-002'
    conversation_id = 'shared-conversation-004'
    fake_notifications = FakeNotificationContainer()
    original_container = functions_notifications.cosmos_notifications_container

    try:
        functions_notifications.cosmos_notifications_container = fake_notifications
        other_notification = functions_notifications.create_collaboration_message_notification(
            user_id=test_user_id,
            conversation_id='other-conversation',
            message_id='shared-message-other',
            conversation_title='Other Shared Chat',
            sender_display_name='Another User',
            message_preview='Other preview',
        )
        target_notification = functions_notifications.create_collaboration_message_notification(
            user_id=test_user_id,
            conversation_id=conversation_id,
            message_id='shared-message-004',
            conversation_title='Operations Shared Chat',
            sender_display_name='Operator User',
            message_preview='Please review the runbook update.',
        )

        app, restore = build_mark_read_test_app(
            test_user_id,
            FakeConversationContainer([
                {
                    'id': conversation_id,
                    'chat_type': 'personal_multi_user',
                }
            ]),
            fake_notifications,
        )

        try:
            with app.test_request_context(f'/api/collaboration/conversations/{conversation_id}/mark-read', method='POST'):
                response, status_code = unwrap_response(
                    app.view_functions['mark_collaboration_conversation_read_api'](conversation_id)
                )

            assert status_code == 200
            payload = response.get_json()
            assert payload['success'] is True
            assert payload['notifications_marked_read'] == 1

            assert test_user_id in fake_notifications.items[target_notification['id']]['read_by']
            assert fake_notifications.items[other_notification['id']]['read_by'] == []

            print('✅ Collaboration mark-read route cleared only the matching shared notification')
            return True
        finally:
            restore()
    finally:
        functions_notifications.cosmos_notifications_container = original_container


if __name__ == '__main__':
    tests = [
        test_collaboration_notification_helper_creates_deep_link,
        test_collaboration_notifications_fan_out_to_other_participants,
        test_group_collaboration_notifications_use_group_membership,
        test_mark_read_route_clears_collaboration_notifications,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            results.append(test())
        except Exception as exc:
            import traceback
            print(f'❌ Test failed: {exc}')
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f'\n📊 Results: {passed}/{total} tests passed')
    sys.exit(0 if all(results) else 1)