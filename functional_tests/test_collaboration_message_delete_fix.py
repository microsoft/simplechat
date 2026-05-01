#!/usr/bin/env python3
# test_collaboration_message_delete_fix.py
"""
Functional test for collaborative message delete fix.
Version: 0.241.024
Implemented in: 0.241.024

This test ensures shared message deletion uses the collaboration delete API,
removes the message from the collaboration store, and publishes a live delete
event instead of falling back to the personal message delete route, without
replaying stale shared-delete toasts every time a collaborative conversation is reloaded.
"""

import copy
import os
import sys

from flask import Flask


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


FUNCTIONS_COLLABORATION_FILE = os.path.join(APP_ROOT, 'functions_collaboration.py')
ROUTE_BACKEND_COLLABORATION_FILE = os.path.join(APP_ROOT, 'route_backend_collaboration.py')
CHAT_MESSAGES_FILE = os.path.join(APP_ROOT, 'static', 'js', 'chat', 'chat-messages.js')
CHAT_COLLABORATION_FILE = os.path.join(APP_ROOT, 'static', 'js', 'chat', 'chat-collaboration.js')


def read_text(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return handle.read()


class FakeCollaborationMessageContainer:
    """In-memory collaboration message container for delete tests."""

    def __init__(self, items=None):
        self.items = {}
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def query_items(self, query=None, parameters=None, partition_key=None, enable_cross_partition_query=False):
        results = [copy.deepcopy(item) for item in self.items.values()]
        parameter_map = {param['name']: param['value'] for param in (parameters or [])}

        if '@message_id' in parameter_map:
            results = [item for item in results if item.get('id') == parameter_map['@message_id']]
        if '@conversation_id' in parameter_map:
            results = [
                item for item in results
                if item.get('conversation_id') == parameter_map['@conversation_id']
            ]
            results.sort(key=lambda item: item.get('timestamp') or '')

        return results

    def delete_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        self.items.pop(item_id, None)


class FakeConversationContainer:
    """In-memory collaboration conversation container for delete tests."""

    def __init__(self, items=None):
        self.items = {}
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        return copy.deepcopy(self.items[item_id])

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)


class FakeEventRegistry:
    """Captures collaboration events published by the route."""

    def __init__(self):
        self.events = []

    def publish(self, conversation_id, event_payload):
        self.events.append((conversation_id, copy.deepcopy(event_payload)))


def unwrap_response(result):
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, result.status_code


def build_delete_route_test_app(test_user_id, deleted_message_doc, updated_conversation_doc):
    """Register the collaboration delete route with fake auth and event dependencies."""
    import route_backend_collaboration

    fake_event_registry = FakeEventRegistry()

    original_login_required = route_backend_collaboration.login_required
    original_user_required = route_backend_collaboration.user_required
    original_swagger_route = route_backend_collaboration.swagger_route
    original_get_auth_security = route_backend_collaboration.get_auth_security
    original_require_feature = route_backend_collaboration._require_collaboration_feature_enabled
    original_get_current_user = route_backend_collaboration._get_current_collaboration_user
    original_delete_message = route_backend_collaboration.delete_collaboration_message
    original_serialize_conversation = route_backend_collaboration.serialize_collaboration_conversation
    original_get_user_state_or_none = route_backend_collaboration.get_user_state_or_none
    original_event_registry = route_backend_collaboration.COLLABORATION_EVENT_REGISTRY

    route_backend_collaboration.login_required = lambda func: func
    route_backend_collaboration.user_required = lambda func: func
    route_backend_collaboration.swagger_route = lambda **kwargs: (lambda func: func)
    route_backend_collaboration.get_auth_security = lambda: {}
    route_backend_collaboration._require_collaboration_feature_enabled = lambda: {}
    route_backend_collaboration._get_current_collaboration_user = lambda: {
        'user_id': test_user_id,
        'display_name': 'Owner User',
        'email': 'owner@example.com',
    }
    route_backend_collaboration.delete_collaboration_message = (
        lambda conversation_id, message_id, current_user_id: (
            copy.deepcopy(deleted_message_doc),
            copy.deepcopy(updated_conversation_doc),
        )
    )
    route_backend_collaboration.serialize_collaboration_conversation = (
        lambda conversation_doc, current_user_id=None, user_state=None: {
            'id': conversation_doc['id'],
            'conversation_kind': 'collaborative',
            'last_message_preview': conversation_doc.get('last_message_preview', ''),
            'message_count': conversation_doc.get('message_count', 0),
        }
    )
    route_backend_collaboration.get_user_state_or_none = lambda user_id, conversation_id: None
    route_backend_collaboration.COLLABORATION_EVENT_REGISTRY = fake_event_registry

    app = Flask(__name__)
    app.config['TESTING'] = True
    route_backend_collaboration.register_route_backend_collaboration(app)

    def restore():
        route_backend_collaboration.login_required = original_login_required
        route_backend_collaboration.user_required = original_user_required
        route_backend_collaboration.swagger_route = original_swagger_route
        route_backend_collaboration.get_auth_security = original_get_auth_security
        route_backend_collaboration._require_collaboration_feature_enabled = original_require_feature
        route_backend_collaboration._get_current_collaboration_user = original_get_current_user
        route_backend_collaboration.delete_collaboration_message = original_delete_message
        route_backend_collaboration.serialize_collaboration_conversation = original_serialize_conversation
        route_backend_collaboration.get_user_state_or_none = original_get_user_state_or_none
        route_backend_collaboration.COLLABORATION_EVENT_REGISTRY = original_event_registry

    return app, fake_event_registry, restore


def test_collaboration_message_delete_source_contracts():
    """Verify the collaboration delete route and client wiring exist in source."""
    print('🔍 Testing collaboration delete source contracts...')

    helper_source = read_text(FUNCTIONS_COLLABORATION_FILE)
    route_source = read_text(ROUTE_BACKEND_COLLABORATION_FILE)
    messages_source = read_text(CHAT_MESSAGES_FILE)
    collaboration_source = read_text(CHAT_COLLABORATION_FILE)

    assert 'def delete_collaboration_message(conversation_id, message_id, current_user_id)' in helper_source
    assert '/api/collaboration/conversations/<conversation_id>/messages/<message_id>' in route_source
    assert 'collaboration.message.deleted' in route_source
    assert '/api/collaboration/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}' in messages_source
    assert "messageType === 'user' && !isCollaborativeConversation" in messages_source
    assert 'function removeCollaborationMessage(messageId)' in collaboration_source
    assert 'function parseCollaborationEventTimestamp(timestamp)' in collaboration_source
    assert "const occurredAt = parseCollaborationEventTimestamp(eventEnvelope.occurred_at || '');" in collaboration_source
    assert "const utcTimestamp = Date.parse(`${normalizedTimestamp}Z`);" in collaboration_source
    assert "eventEnvelope.event_type === 'collaboration.message.deleted'" in collaboration_source

    print('✅ Collaboration delete source contracts are present')
    return True


def test_delete_collaboration_message_updates_message_summary():
    """Verify the helper deletes a shared message and refreshes conversation summary data."""
    print('🔍 Testing collaboration delete helper...')

    import functions_collaboration
    from collaboration_models import PERSONAL_MULTI_USER_CHAT_TYPE

    conversation_id = 'shared-conversation-delete-001'
    owner_user_id = 'owner-001'
    message_one = {
        'id': 'shared-message-001',
        'conversation_id': conversation_id,
        'content': 'First shared message',
        'timestamp': '2026-04-16T10:00:00Z',
        'metadata': {
            'sender': {'user_id': owner_user_id, 'display_name': 'Owner User'},
            'last_message_preview': 'First shared message',
        },
    }
    message_two = {
        'id': 'shared-message-002',
        'conversation_id': conversation_id,
        'content': 'Second shared message',
        'timestamp': '2026-04-16T10:05:00Z',
        'metadata': {
            'sender': {'user_id': owner_user_id, 'display_name': 'Owner User'},
            'last_message_preview': 'Second shared message',
        },
    }
    conversation_doc = {
        'id': conversation_id,
        'title': 'Delete Test Conversation',
        'chat_type': PERSONAL_MULTI_USER_CHAT_TYPE,
        'participants': [
            {'user_id': owner_user_id, 'status': 'accepted', 'role': 'owner'},
        ],
        'owner_user_ids': [owner_user_id],
        'message_count': 2,
        'last_message_at': message_two['timestamp'],
        'last_message_preview': 'Second shared message',
        'updated_at': message_two['timestamp'],
    }

    original_message_container = functions_collaboration.cosmos_collaboration_messages_container
    original_conversation_container = functions_collaboration.cosmos_collaboration_conversations_container
    original_assert_participate = functions_collaboration.assert_user_can_participate_in_collaboration_conversation

    functions_collaboration.cosmos_collaboration_messages_container = FakeCollaborationMessageContainer([
        message_one,
        message_two,
    ])
    functions_collaboration.cosmos_collaboration_conversations_container = FakeConversationContainer([
        conversation_doc,
    ])
    functions_collaboration.assert_user_can_participate_in_collaboration_conversation = (
        lambda user_id, conversation: {'user_state': {'role': 'owner'}, 'membership_status': 'accepted'}
    )

    try:
        deleted_message_doc, updated_conversation_doc = functions_collaboration.delete_collaboration_message(
            conversation_id,
            message_two['id'],
            owner_user_id,
        )

        assert deleted_message_doc['id'] == message_two['id']
        assert message_two['id'] not in functions_collaboration.cosmos_collaboration_messages_container.items
        assert updated_conversation_doc['message_count'] == 1
        assert updated_conversation_doc['last_message_preview'] == 'First shared message'
        assert updated_conversation_doc['last_message_at'] == message_one['timestamp']

        print('✅ Collaboration delete helper removed the message and refreshed conversation summary data')
        return True
    finally:
        functions_collaboration.cosmos_collaboration_messages_container = original_message_container
        functions_collaboration.cosmos_collaboration_conversations_container = original_conversation_container
        functions_collaboration.assert_user_can_participate_in_collaboration_conversation = original_assert_participate


def test_collaboration_delete_route_publishes_delete_event():
    """Verify the delete route returns the shared-delete contract and publishes a delete event."""
    print('🔍 Testing collaboration delete route...')

    conversation_id = 'shared-conversation-delete-002'
    message_id = 'shared-message-003'
    deleted_message_doc = {
        'id': message_id,
        'conversation_id': conversation_id,
        'metadata': {
            'sender': {'user_id': 'owner-001'},
        },
    }
    updated_conversation_doc = {
        'id': conversation_id,
        'last_message_preview': 'Earlier message',
        'message_count': 1,
    }

    app, fake_event_registry, restore = build_delete_route_test_app(
        'owner-001',
        deleted_message_doc,
        updated_conversation_doc,
    )

    try:
        with app.test_request_context(
            f'/api/collaboration/conversations/{conversation_id}/messages/{message_id}',
            method='DELETE',
            json={'delete_thread': False},
        ):
            response, status_code = unwrap_response(
                app.view_functions['delete_collaboration_message_api'](conversation_id, message_id)
            )

        assert status_code == 200
        payload = response.get_json()
        assert payload['success'] is True
        assert payload['deleted_message_ids'] == [message_id]
        assert payload['archived'] is False

        assert len(fake_event_registry.events) == 1
        published_conversation_id, event_payload = fake_event_registry.events[0]
        assert published_conversation_id == conversation_id
        assert event_payload['event_type'] == 'collaboration.message.deleted'
        assert event_payload['payload']['message_id'] == message_id
        assert event_payload['payload']['deleted_by_user_id'] == 'owner-001'

        print('✅ Collaboration delete route returned the expected payload and published a live delete event')
        return True
    finally:
        restore()


if __name__ == '__main__':
    tests = [
        test_collaboration_message_delete_source_contracts,
        test_delete_collaboration_message_updates_message_summary,
        test_collaboration_delete_route_publishes_delete_event,
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