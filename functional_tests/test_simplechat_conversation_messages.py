# test_simplechat_conversation_messages.py
#!/usr/bin/env python3
"""
Functional test for SimpleChat conversation message support.
Version: 0.241.028
Implemented in: 0.241.028

This test ensures SimpleChat can add user-authored messages to personal and
collaborative conversations and can seed newly created conversations when the
message capability is enabled.
"""

import importlib
import os
import sys
import traceback
from copy import deepcopy

from azure.cosmos.exceptions import CosmosResourceNotFoundError


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class FakeConversationsContainer:
    def __init__(self, conversation=None, raise_not_found=False):
        self.conversation = deepcopy(conversation) if conversation else None
        self.raise_not_found = raise_not_found
        self.upserts = []

    def read_item(self, item, partition_key):
        if self.raise_not_found or not self.conversation or self.conversation.get('id') != item:
            raise CosmosResourceNotFoundError(message='Conversation not found')
        return deepcopy(self.conversation)

    def upsert_item(self, item):
        self.conversation = deepcopy(item)
        self.upserts.append(deepcopy(item))
        return deepcopy(item)


class FakeMessagesContainer:
    def __init__(self, last_thread_id=None):
        self.last_thread_id = last_thread_id
        self.upserts = []

    def query_items(self, query, parameters=None, partition_key=None):
        if self.last_thread_id:
            return [{'thread_id': self.last_thread_id}]
        return []

    def upsert_item(self, item):
        self.upserts.append(deepcopy(item))
        return deepcopy(item)


class PatchSet:
    def __init__(self, module, replacements):
        self.module = module
        self.replacements = replacements
        self.originals = {}

    def __enter__(self):
        for attribute_name, replacement in self.replacements.items():
            self.originals[attribute_name] = getattr(self.module, attribute_name)
            setattr(self.module, attribute_name, replacement)
        return self

    def __exit__(self, exc_type, exc, tb):
        for attribute_name, original in self.originals.items():
            setattr(self.module, attribute_name, original)
        return False


def test_add_message_to_personal_conversation_for_current_user():
    """SimpleChat should persist a user-authored message to a personal conversation."""
    print('🔍 Testing personal conversation message seeding...')

    operations_module = importlib.import_module('functions_simplechat_operations')
    fake_conversation = {
        'id': 'conversation-personal-1',
        'user_id': 'user-123',
        'title': 'New Conversation',
        'chat_type': 'personal_single_user',
        'last_updated': '2026-04-16T00:00:00Z',
    }
    fake_conversations_container = FakeConversationsContainer(conversation=fake_conversation)
    fake_messages_container = FakeMessagesContainer(last_thread_id='thread-prev-1')
    logged_activity = []

    with PatchSet(
        operations_module,
        {
            'get_current_user_info': lambda: {
                'userId': 'user-123',
                'userPrincipalName': 'user@example.com',
                'displayName': 'Test User',
                'email': 'user@example.com',
            },
            'cosmos_conversations_container': fake_conversations_container,
            'cosmos_messages_container': fake_messages_container,
            'log_chat_activity': lambda **kwargs: logged_activity.append(kwargs),
        },
    ):
        result = operations_module.add_conversation_message_for_current_user(
            conversation_id='conversation-personal-1',
            content='Kick off the personal workflow with this starter note.',
        )

    assert result['conversation_kind'] == 'personal'
    assert result['message']['role'] == 'user'
    assert result['message']['content'] == 'Kick off the personal workflow with this starter note.'
    assert result['message']['metadata']['thread_info']['previous_thread_id'] == 'thread-prev-1'
    assert result['conversation']['title'].startswith('Kick off the personal workflow')
    assert len(fake_messages_container.upserts) == 1
    assert len(fake_conversations_container.upserts) == 1
    assert logged_activity and logged_activity[0]['conversation_id'] == 'conversation-personal-1'

    print('✅ Personal conversation message seeding verified.')


def test_add_message_to_collaboration_conversation_for_current_user():
    """SimpleChat should reuse collaboration persistence when adding messages to collaborative conversations."""
    print('🔍 Testing collaborative conversation message seeding...')

    operations_module = importlib.import_module('functions_simplechat_operations')
    notifications = []
    collaboration_doc = {
        'id': 'conversation-collab-1',
        'chat_type': 'group',
        'conversation_kind': 'collaboration',
        'group_id': 'group-123',
    }
    updated_collaboration_doc = {
        **collaboration_doc,
        'message_count': 1,
        'last_message_preview': 'Hello group',
    }

    with PatchSet(
        operations_module,
        {
            'get_current_user_info': lambda: {
                'userId': 'user-123',
                'userPrincipalName': 'user@example.com',
                'displayName': 'Test User',
                'email': 'user@example.com',
            },
            'cosmos_conversations_container': FakeConversationsContainer(raise_not_found=True),
            'get_collaboration_conversation': lambda conversation_id: deepcopy(collaboration_doc),
            'assert_user_can_participate_in_collaboration_conversation': lambda user_id, conversation_doc: {
                'group_role': 'User',
                'conversation_id': conversation_doc.get('id'),
            },
            'persist_collaboration_message': lambda conversation_doc, sender_user, content, reply_to_message_id=None: (
                {
                    'id': 'message-collab-1',
                    'conversation_id': conversation_doc.get('id'),
                    'role': 'user',
                    'content': content,
                    'metadata': {
                        'sender': sender_user,
                    },
                },
                deepcopy(updated_collaboration_doc),
            ),
            'create_collaboration_message_notifications': lambda conversation_doc, message_doc: notifications.append(
                (deepcopy(conversation_doc), deepcopy(message_doc))
            ),
        },
    ):
        result = operations_module.add_conversation_message_for_current_user(
            conversation_id='conversation-collab-1',
            content='Hello group',
        )

    assert result['conversation_kind'] == 'collaboration'
    assert result['message']['content'] == 'Hello group'
    assert result['conversation']['message_count'] == 1
    assert len(notifications) == 1

    print('✅ Collaborative conversation message seeding verified.')


def test_simplechat_plugin_initial_message_seeding_requires_capability():
    """SimpleChat should require the add-message capability before seeding a newly created conversation."""
    print('🔍 Testing SimpleChat plugin initial message capability guard...')

    plugin_module = importlib.import_module('semantic_kernel_plugins.simplechat_plugin')
    created_calls = []
    seeded_calls = []

    with PatchSet(
        plugin_module,
        {
            'create_personal_conversation_for_current_user': lambda title='New Conversation': created_calls.append(title) or {
                'id': 'conversation-seeded-1',
                'title': title,
                'chat_type': 'personal_single_user',
            },
            'add_conversation_message_for_current_user': lambda conversation_id, content, reply_to_message_id='': seeded_calls.append(
                {
                    'conversation_id': conversation_id,
                    'content': content,
                    'reply_to_message_id': reply_to_message_id,
                }
            ) or {
                'conversation': {
                    'id': conversation_id,
                    'title': 'Seeded Conversation',
                    'chat_type': 'personal_single_user',
                },
                'message': {
                    'id': 'message-seeded-1',
                    'conversation_id': conversation_id,
                    'content': content,
                    'role': 'user',
                },
                'conversation_kind': 'personal',
            },
        },
    ):
        enabled_plugin = plugin_module.SimpleChatPlugin(
            {
                'id': 'simplechat-action-id',
                'name': 'simplechat_tools',
                'type': 'simplechat',
                'enabled_functions': [
                    'create_personal_conversation',
                    'add_conversation_message',
                ],
            }
        )
        seeded_result = enabled_plugin.create_personal_conversation(
            title='Seeded Conversation',
            initial_message='Please summarize the attached request and draft a response.',
        )

        disabled_plugin = plugin_module.SimpleChatPlugin(
            {
                'id': 'simplechat-action-id',
                'name': 'simplechat_tools',
                'type': 'simplechat',
                'enabled_functions': [
                    'create_personal_conversation',
                ],
            }
        )
        disabled_result = disabled_plugin.create_personal_conversation(
            title='Blocked Seed',
            initial_message='This should fail because the message capability is disabled.',
        )

    assert seeded_result['success'] is True
    assert seeded_result['seeded_initial_message'] is True
    assert seeded_result['message']['content'] == 'Please summarize the attached request and draft a response.'
    assert created_calls == ['Seeded Conversation']
    assert seeded_calls and seeded_calls[0]['conversation_id'] == 'conversation-seeded-1'

    assert disabled_result['success'] is False
    assert disabled_result['error_type'] == 'permission'
    assert 'add conversation message capability is disabled' in disabled_result['error']
    assert created_calls == ['Seeded Conversation']

    print('✅ SimpleChat plugin initial message capability guard verified.')


if __name__ == '__main__':
    tests = [
        test_add_message_to_personal_conversation_for_current_user,
        test_add_message_to_collaboration_conversation_for_current_user,
        test_simplechat_plugin_initial_message_seeding_requires_capability,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'❌ Test failed: {exc}')
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)
