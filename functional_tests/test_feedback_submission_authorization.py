#!/usr/bin/env python3
# test_feedback_submission_authorization.py
"""
Functional test for feedback submission authorization hardening.
Version: 0.241.022
Implemented in: 0.241.013; 0.241.022

This test ensures feedback submission only accepts assistant messages from
the authenticated user's own conversation, rejects foreign conversation ids
before querying messages, and does not persist feedback rows when the target
assistant message is missing.
"""

import copy
import importlib
import os
import sys
import types
import uuid

from datetime import datetime

from flask import Flask, jsonify, request, session
import werkzeug


if not hasattr(werkzeug, '__version__'):
    werkzeug.__version__ = '3'


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'application', 'single_app'))


class DummyNotFoundError(Exception):
    """Raised when a fake Cosmos item is not found."""


class FakeConversationContainer:
    """In-memory conversation container for feedback authorization tests."""

    def __init__(self, items=None):
        self.items = {}
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        if item_id not in self.items:
            raise DummyNotFoundError(item_id)
        return copy.deepcopy(self.items[item_id])


class FakeMessageContainer:
    """In-memory message container that tracks feedback target lookups."""

    def __init__(self, items=None):
        self.items = [copy.deepcopy(item) for item in (items or [])]
        self.query_count = 0

    def query_items(self, query=None, parameters=None, partition_key=None, *args, **kwargs):
        self.query_count += 1
        matching_items = [
            copy.deepcopy(item)
            for item in self.items
            if item.get('conversation_id') == partition_key
        ]
        matching_items.sort(key=lambda item: item.get('timestamp', ''))
        return matching_items


class FakeFeedbackContainer:
    """In-memory feedback container that tracks persisted feedback rows."""

    def __init__(self, items=None):
        self.items = {}
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)


def _passthrough_decorator(*args, **kwargs):
    """Return the wrapped function unchanged for decorator stubs."""
    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return args[0]
    return lambda func: func


def _install_route_import_stubs():
    """Install lightweight module stubs so the feedback route imports in isolation."""
    stub_modules = {}

    config_module = types.ModuleType('config')
    config_module.cosmos_conversations_container = None
    config_module.cosmos_messages_container = None
    config_module.cosmos_feedback_container = None
    config_module.CosmosResourceNotFoundError = DummyNotFoundError
    config_module.exceptions = types.SimpleNamespace(CosmosResourceNotFoundError=DummyNotFoundError)
    config_module.datetime = datetime
    config_module.request = request
    config_module.session = session
    config_module.jsonify = jsonify
    config_module.uuid = uuid
    stub_modules['config'] = config_module

    auth_module = types.ModuleType('functions_authentication')
    auth_module.login_required = _passthrough_decorator
    auth_module.user_required = _passthrough_decorator
    auth_module.feedback_admin_required = _passthrough_decorator
    auth_module.jsonify = jsonify
    stub_modules['functions_authentication'] = auth_module

    settings_module = types.ModuleType('functions_settings')
    settings_module.enabled_required = _passthrough_decorator
    settings_module.get_settings = lambda: {}
    stub_modules['functions_settings'] = settings_module

    swagger_module = types.ModuleType('swagger_wrapper')
    swagger_module.swagger_route = lambda **kwargs: (lambda func: func)
    swagger_module.get_auth_security = lambda: {}
    stub_modules['swagger_wrapper'] = swagger_module

    for module_name, module in stub_modules.items():
        sys.modules[module_name] = module


def _load_route_backend_feedback_module():
    """Import the feedback route module after installing lightweight stubs."""
    _install_route_import_stubs()
    if 'route_backend_feedback' in sys.modules:
        del sys.modules['route_backend_feedback']
    return importlib.import_module('route_backend_feedback')


def build_test_app(test_user_id, conversation_items, message_items, roles=None):
    """Register feedback routes with fake auth and fake Cosmos containers."""
    route_backend_feedback = _load_route_backend_feedback_module()

    conversation_container = FakeConversationContainer(conversation_items)
    message_container = FakeMessageContainer(message_items)
    feedback_container = FakeFeedbackContainer()

    route_backend_feedback.cosmos_conversations_container = conversation_container
    route_backend_feedback.cosmos_messages_container = message_container
    route_backend_feedback.cosmos_feedback_container = feedback_container
    route_backend_feedback.CosmosResourceNotFoundError = DummyNotFoundError
    route_backend_feedback.login_required = lambda func: func
    route_backend_feedback.user_required = lambda func: func
    route_backend_feedback.feedback_admin_required = lambda func: func
    route_backend_feedback.enabled_required = _passthrough_decorator
    route_backend_feedback.swagger_route = lambda **kwargs: (lambda func: func)
    route_backend_feedback.get_auth_security = lambda: {}

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.secret_key = 'test-secret'
    route_backend_feedback.register_route_backend_feedback(app)

    def create_client():
        client = app.test_client()
        with client.session_transaction() as flask_session:
            flask_session['user'] = {
                'oid': test_user_id,
                'roles': roles or ['User'],
            }
        return client

    return create_client, message_container, feedback_container


def test_owner_feedback_submission_saves_authorized_content():
    """Verify owners can submit feedback for assistant messages in their own conversation."""
    print('🔍 Testing owner feedback submission success...')

    create_client, message_container, feedback_container = build_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-owner',
                'user_id': 'user-owner',
            }
        ],
        [
            {
                'id': 'message-user',
                'conversation_id': 'conversation-owner',
                'role': 'user',
                'content': 'Owner prompt',
                'timestamp': '2026-05-05T12:00:00Z',
            },
            {
                'id': 'message-assistant',
                'conversation_id': 'conversation-owner',
                'role': 'assistant',
                'content': 'Owner response',
                'timestamp': '2026-05-05T12:00:01Z',
            },
        ],
    )

    client = create_client()
    response = client.post(
        '/feedback/submit',
        json={
            'messageId': 'message-assistant',
            'conversationId': 'conversation-owner',
            'feedbackType': 'positive',
            'reason': '',
        },
    )

    payload = response.get_json()
    if response.status_code != 200 or not payload.get('success'):
        print(f'❌ Expected successful feedback save, got {response.status_code}: {payload}')
        return False

    if message_container.query_count != 1:
        print(f'❌ Expected one message query, got {message_container.query_count}')
        return False

    if len(feedback_container.items) != 1:
        print(f'❌ Expected one feedback row, got {len(feedback_container.items)}')
        return False

    saved_feedback = next(iter(feedback_container.items.values()))
    if saved_feedback.get('userId') != 'user-owner':
        print(f'❌ Expected feedback to belong to owner, got {saved_feedback}')
        return False
    if saved_feedback.get('prompt') != 'Owner prompt':
        print(f'❌ Expected owner prompt to be copied, got {saved_feedback}')
        return False
    if saved_feedback.get('aiResponse') != 'Owner response':
        print(f'❌ Expected owner response to be copied, got {saved_feedback}')
        return False

    print('✅ Owner feedback submission saved the authorized conversation content')
    return True


def test_foreign_feedback_submission_returns_forbidden_before_query():
    """Verify foreign conversation ids fail closed before any message query executes."""
    print('🔍 Testing foreign feedback submission rejection...')

    create_client, message_container, feedback_container = build_test_app(
        'user-attacker',
        [
            {
                'id': 'conversation-victim',
                'user_id': 'user-victim',
            }
        ],
        [
            {
                'id': 'message-victim-user',
                'conversation_id': 'conversation-victim',
                'role': 'user',
                'content': 'Victim prompt',
                'timestamp': '2026-05-05T12:00:00Z',
            },
            {
                'id': 'message-victim-assistant',
                'conversation_id': 'conversation-victim',
                'role': 'assistant',
                'content': 'Victim response',
                'timestamp': '2026-05-05T12:00:01Z',
            },
        ],
    )

    client = create_client()
    response = client.post(
        '/feedback/submit',
        json={
            'messageId': 'message-victim-assistant',
            'conversationId': 'conversation-victim',
            'feedbackType': 'negative',
            'reason': 'Probe',
        },
    )

    payload = response.get_json()
    if response.status_code != 403:
        print(f'❌ Expected 403, got {response.status_code}: {payload}')
        return False
    if payload.get('error') != 'Forbidden':
        print(f'❌ Expected Forbidden error, got {payload}')
        return False
    if message_container.query_count != 0:
        print(f'❌ Message container should not be queried, got {message_container.query_count}')
        return False
    if feedback_container.items:
        print(f'❌ No feedback should be written on foreign submission, got {feedback_container.items}')
        return False

    print('✅ Foreign feedback submission was blocked before querying messages')
    return True


def test_missing_assistant_message_returns_not_found_without_persisting_feedback():
    """Verify missing assistant targets do not create placeholder feedback rows."""
    print('🔍 Testing missing assistant message rejection...')

    create_client, message_container, feedback_container = build_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-owner',
                'user_id': 'user-owner',
            }
        ],
        [
            {
                'id': 'message-user',
                'conversation_id': 'conversation-owner',
                'role': 'user',
                'content': 'Owner prompt',
                'timestamp': '2026-05-05T12:00:00Z',
            },
            {
                'id': 'message-assistant',
                'conversation_id': 'conversation-owner',
                'role': 'assistant',
                'content': 'Owner response',
                'timestamp': '2026-05-05T12:00:01Z',
            },
        ],
    )

    client = create_client()
    response = client.post(
        '/feedback/submit',
        json={
            'messageId': 'message-missing',
            'conversationId': 'conversation-owner',
            'feedbackType': 'negative',
            'reason': 'Missing target',
        },
    )

    payload = response.get_json()
    if response.status_code != 404:
        print(f'❌ Expected 404, got {response.status_code}: {payload}')
        return False
    if payload.get('error') != 'Assistant message not found':
        print(f'❌ Expected missing assistant error, got {payload}')
        return False
    if message_container.query_count != 1:
        print(f'❌ Expected one message query, got {message_container.query_count}')
        return False
    if feedback_container.items:
        print(f'❌ No feedback should be written for a missing assistant message, got {feedback_container.items}')
        return False

    print('✅ Missing assistant messages are rejected without persisting feedback')
    return True


if __name__ == '__main__':
    tests = [
        test_owner_feedback_submission_saves_authorized_content,
        test_foreign_feedback_submission_returns_forbidden_before_query,
        test_missing_assistant_message_returns_not_found_without_persisting_feedback,
    ]

    print('🧪 Running feedback submission authorization tests...')
    print('=' * 60)

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print('\n' + '=' * 60)
    print(f'📊 Test Results: {sum(results)}/{len(results)} tests passed')

    sys.exit(0 if success else 1)