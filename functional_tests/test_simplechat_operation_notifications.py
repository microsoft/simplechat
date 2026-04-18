#!/usr/bin/env python3
# test_simplechat_operation_notifications.py
"""
Functional test for SimpleChat operation notifications.
Version: 0.241.030
Implemented in: 0.241.030

This test ensures SimpleChat group creation, direct group member additions,
and conversation creation fan out notifications into the notifications inbox
so workflow-driven workspace actions are visible in notifications.html.
"""

import importlib
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class StubContainer:
    def __init__(self):
        self.items = []

    def upsert_item(self, item):
        self.items.append(dict(item))
        return item


def load_module():
    module = importlib.import_module('functions_simplechat_operations')
    return importlib.reload(module)


def test_simplechat_notifications_for_group_and_conversation_actions(monkeypatch):
    """Validate notification fan-out for key workflow-driven SimpleChat actions."""
    module = load_module()
    created_notifications = []

    def fake_create_notification(**kwargs):
        created_notifications.append(dict(kwargs))
        return kwargs

    monkeypatch.setattr(module, 'create_notification', fake_create_notification)
    monkeypatch.setattr(module, '_require_group_workspaces_enabled', lambda: {
        'enable_group_workspaces': True,
        'enable_group_creation': True,
    })
    monkeypatch.setattr(module, '_require_group_creation_enabled', lambda settings=None: settings or {})
    monkeypatch.setattr(module, '_require_current_user_info', lambda: {
        'userId': 'owner-001',
        'email': 'owner@example.com',
        'displayName': 'Owner User',
    })
    monkeypatch.setattr(module, 'create_group', lambda name, description: {
        'id': 'group-001',
        'name': name,
        'description': description,
        'owner': {
            'id': 'owner-001',
            'email': 'owner@example.com',
            'displayName': 'Owner User',
        },
        'users': [
            {
                'userId': 'owner-001',
                'email': 'owner@example.com',
                'displayName': 'Owner User',
            },
            {
                'userId': 'member-001',
                'email': 'member@example.com',
                'displayName': 'Member User',
            },
        ],
    })
    monkeypatch.setattr(module, '_require_collaboration_feature_enabled', lambda: {})
    monkeypatch.setattr(module, 'normalize_collaboration_user', lambda user: {
        'user_id': user['userId'],
        'display_name': user['displayName'],
        'email': user['email'],
    })
    monkeypatch.setattr(module, '_resolve_group_doc_for_current_user', lambda *args, **kwargs: {
        'id': 'group-001',
        'name': 'Ops Group',
        'owner': {
            'id': 'owner-001',
            'email': 'owner@example.com',
            'displayName': 'Owner User',
        },
        'users': [
            {
                'userId': 'owner-001',
                'email': 'owner@example.com',
                'displayName': 'Owner User',
            },
            {
                'userId': 'member-001',
                'email': 'member@example.com',
                'displayName': 'Member User',
            },
        ],
    })
    monkeypatch.setattr(module, 'check_group_status_allows_operation', lambda group_doc, operation: (True, ''))
    monkeypatch.setattr(module, 'create_group_collaboration_conversation_record', lambda title, creator_user, group_doc: {
        'id': 'conversation-001',
        'title': title or 'Standup Summary',
        'chat_type': 'group_multi_user',
        'conversation_kind': 'collaboration',
        'scope': {
            'group_id': group_doc['id'],
            'group_name': group_doc['name'],
        },
    })

    group_doc = module.create_group_for_current_user('Ops Group', 'Workflow-created group')
    assert group_doc['id'] == 'group-001'
    assert created_notifications[0]['notification_type'] == 'group_created'
    assert created_notifications[0]['user_id'] == 'owner-001'
    assert created_notifications[0]['link_url'] == '/manage_group/group-001'

    created_notifications.clear()
    conversation_doc, current_user, resolved_group = module.create_group_collaboration_conversation_for_current_user(
        title='Standup Summary',
        group_id='group-001',
    )

    assert conversation_doc['id'] == 'conversation-001'
    assert current_user['user_id'] == 'owner-001'
    assert resolved_group['id'] == 'group-001'
    assert {notification['user_id'] for notification in created_notifications} == {'owner-001', 'member-001'}
    assert all(notification['notification_type'] == 'conversation_created' for notification in created_notifications)
    assert all(notification['link_url'] == '/chats?conversationId=conversation-001' for notification in created_notifications)


def test_simplechat_member_addition_and_personal_conversation_notifications(monkeypatch):
    """Validate actor plus recipient notifications for member adds and explicit personal conversation creation."""
    module = load_module()
    created_notifications = []
    group_store = StubContainer()
    conversation_store = StubContainer()

    def fake_create_notification(**kwargs):
        created_notifications.append(dict(kwargs))
        return kwargs

    monkeypatch.setattr(module, 'create_notification', fake_create_notification)
    monkeypatch.setattr(module, '_require_current_user_info', lambda: {
        'userId': 'owner-001',
        'email': 'owner@example.com',
        'displayName': 'Owner User',
    })
    monkeypatch.setattr(module, '_resolve_group_doc_for_current_user', lambda *args, **kwargs: {
        'id': 'group-001',
        'name': 'Ops Group',
        'owner': {
            'id': 'owner-001',
            'email': 'owner@example.com',
            'displayName': 'Owner User',
        },
        'admins': [],
        'documentManagers': [],
        'users': [
            {
                'userId': 'owner-001',
                'email': 'owner@example.com',
                'displayName': 'Owner User',
            }
        ],
    })
    monkeypatch.setattr(module, 'get_user_role_in_group', lambda group_doc, user_id: 'Owner' if user_id == 'owner-001' else None)
    monkeypatch.setattr(module, 'resolve_directory_user', lambda **kwargs: {
        'id': 'member-002',
        'email': 'new.member@example.com',
        'displayName': 'New Member',
    })
    monkeypatch.setattr(module, '_log_group_member_addition', lambda **kwargs: None)
    monkeypatch.setattr(module, 'cosmos_groups_container', group_store)
    monkeypatch.setattr(module, 'cosmos_conversations_container', conversation_store)
    monkeypatch.setattr(module, 'log_conversation_creation', lambda **kwargs: None)

    add_member_result = module.add_group_member_for_current_user(
        group_id='group-001',
        user_identifier='new.member@example.com',
        role='admin',
    )

    assert add_member_result['success'] is True
    assert {notification['user_id'] for notification in created_notifications} == {'owner-001', 'member-002'}
    assert all(notification['notification_type'] == 'group_member_added' for notification in created_notifications)
    assert any(notification['title'] == 'Added to Group' for notification in created_notifications)
    assert any(notification['title'] == 'Group member added' for notification in created_notifications)

    created_notifications.clear()
    personal_conversation = module.create_personal_conversation_for_current_user(
        title='Workflow Follow-up',
        notify_creation=True,
    )
    assert personal_conversation['title'] == 'Workflow Follow-up'
    assert len(created_notifications) == 1
    assert created_notifications[0]['user_id'] == 'owner-001'
    assert created_notifications[0]['notification_type'] == 'conversation_created'
    assert created_notifications[0]['link_url'] == f"/chats?conversationId={personal_conversation['id']}"

    created_notifications.clear()
    module.create_personal_conversation_for_current_user(
        title='Manual Conversation',
        notify_creation=False,
    )
    assert created_notifications == []


if __name__ == '__main__':
    raise SystemExit(0)