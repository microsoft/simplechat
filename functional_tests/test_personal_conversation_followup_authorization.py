#!/usr/bin/env python3
# test_personal_conversation_followup_authorization.py
"""
Functional test for personal conversation authorization follow-up.
Version: 0.241.022
Implemented in: 0.241.012; 0.241.022

This test ensures destructive, file-content, and frontend personal
conversation routes enforce ownership, and the chat message loader handles
authorization failures cleanly.
"""

import copy
import importlib
import json
import os
import sys
import traceback
import types

import werkzeug
from flask import Flask, jsonify, request


if not hasattr(werkzeug, '__version__'):
    werkzeug.__version__ = '3'


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_MESSAGES_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-messages.js',
)
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'v0.241.012',
    'PERSONAL_CONVERSATION_AUTHORIZATION_FOLLOW_UP_FIX.md',
)

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT_DIR, 'application', 'single_app'))


class DummyNotFoundError(Exception):
    """Raised when a fake Cosmos item is not found."""


class FakeConversationContainer:
    """In-memory conversation container for authorization tests."""

    def __init__(self, items=None):
        self.items = {}
        self.deleted_ids = []
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        if item_id not in self.items:
            raise DummyNotFoundError(item_id)
        return copy.deepcopy(self.items[item_id])

    def delete_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        if item_id not in self.items:
            raise DummyNotFoundError(item_id)
        self.deleted_ids.append(item_id)
        del self.items[item_id]


class FakeMessageContainer:
    """In-memory message container that tracks query and delete attempts."""

    def __init__(self, items=None):
        self.items = [copy.deepcopy(item) for item in (items or [])]
        self.query_count = 0
        self.deleted_ids = []

    def query_items(self, query=None, parameters=None, partition_key=None, *args, **kwargs):
        self.query_count += 1
        conversation_id = partition_key
        file_id = None

        for parameter in parameters or []:
            if parameter.get('name') == '@conversation_id':
                conversation_id = parameter.get('value')
            elif parameter.get('name') == '@file_id':
                file_id = parameter.get('value')

        matching_items = []
        for item in self.items:
            if conversation_id and item.get('conversation_id') != conversation_id:
                continue
            if file_id and item.get('id') != file_id:
                continue
            matching_items.append(copy.deepcopy(item))

        matching_items.sort(key=lambda item: item.get('timestamp', ''))
        return matching_items

    def delete_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        self.deleted_ids.append(item_id)
        self.items = [existing_item for existing_item in self.items if existing_item.get('id') != item_id]


def _passthrough_decorator(*args, **kwargs):
    """Return the wrapped function unchanged for decorator stubs."""
    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return args[0]
    return lambda func: func


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8-sig') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def _install_route_backend_conversations_stubs():
    """Install lightweight import stubs for route_backend_conversations."""
    stub_modules = {}

    config_module = types.ModuleType('config')
    config_module.cosmos_conversations_container = None
    config_module.cosmos_messages_container = None
    config_module.CosmosResourceNotFoundError = DummyNotFoundError
    stub_modules['config'] = config_module

    auth_module = types.ModuleType('functions_authentication')
    auth_module.login_required = _passthrough_decorator
    auth_module.user_required = _passthrough_decorator
    auth_module.get_current_user_id = lambda: None
    auth_module.jsonify = jsonify
    stub_modules['functions_authentication'] = auth_module

    settings_module = types.ModuleType('functions_settings')
    settings_module.get_settings = lambda: {}
    stub_modules['functions_settings'] = settings_module

    metadata_module = types.ModuleType('functions_conversation_metadata')
    metadata_module.get_conversation_metadata = lambda *args, **kwargs: {}
    metadata_module.update_conversation_with_metadata = lambda *args, **kwargs: None
    stub_modules['functions_conversation_metadata'] = metadata_module

    unread_module = types.ModuleType('functions_conversation_unread')
    unread_module.clear_conversation_unread = lambda *args, **kwargs: None
    unread_module.normalize_conversation_unread_state = lambda item: item
    stub_modules['functions_conversation_unread'] = unread_module

    notifications_module = types.ModuleType('functions_notifications')
    notifications_module.mark_chat_response_notifications_read_for_conversation = lambda *args, **kwargs: None
    stub_modules['functions_notifications'] = notifications_module

    debug_module = types.ModuleType('functions_debug')
    debug_module.debug_print = lambda *args, **kwargs: None
    stub_modules['functions_debug'] = debug_module

    artifacts_module = types.ModuleType('functions_message_artifacts')
    artifacts_module.filter_assistant_artifact_items = lambda items: items
    stub_modules['functions_message_artifacts'] = artifacts_module

    swagger_module = types.ModuleType('swagger_wrapper')
    swagger_module.swagger_route = lambda **kwargs: (lambda func: func)
    swagger_module.get_auth_security = lambda: {}
    stub_modules['swagger_wrapper'] = swagger_module

    activity_module = types.ModuleType('functions_activity_logging')
    activity_module.log_conversation_creation = lambda *args, **kwargs: None
    activity_module.log_conversation_deletion = lambda *args, **kwargs: None
    activity_module.log_conversation_archival = lambda *args, **kwargs: None
    stub_modules['functions_activity_logging'] = activity_module

    thoughts_module = types.ModuleType('functions_thoughts')
    thoughts_module.archive_thoughts_for_conversation = lambda *args, **kwargs: None
    thoughts_module.delete_thoughts_for_conversation = lambda *args, **kwargs: None
    stub_modules['functions_thoughts'] = thoughts_module

    for module_name, module in stub_modules.items():
        sys.modules[module_name] = module


def _load_route_backend_conversations_module():
    _install_route_backend_conversations_stubs()
    if 'route_backend_conversations' in sys.modules:
        del sys.modules['route_backend_conversations']
    return importlib.import_module('route_backend_conversations')


def build_delete_test_app(test_user_id, conversation_items, message_items):
    """Register conversation routes with fake containers for delete-route tests."""
    route_backend_conversations = _load_route_backend_conversations_module()

    conversation_container = FakeConversationContainer(conversation_items)
    message_container = FakeMessageContainer(message_items)

    route_backend_conversations.cosmos_conversations_container = conversation_container
    route_backend_conversations.cosmos_messages_container = message_container
    route_backend_conversations.login_required = lambda func: func
    route_backend_conversations.user_required = lambda func: func
    route_backend_conversations.swagger_route = lambda **kwargs: (lambda func: func)
    route_backend_conversations.get_auth_security = lambda: {}
    route_backend_conversations.get_current_user_id = lambda: test_user_id
    route_backend_conversations.debug_print = lambda *args, **kwargs: None
    route_backend_conversations.filter_assistant_artifact_items = lambda items: items
    route_backend_conversations.CosmosResourceNotFoundError = DummyNotFoundError

    app = Flask(__name__)
    app.config['TESTING'] = True
    route_backend_conversations.register_route_backend_conversations(app)

    return app, conversation_container, message_container


def _install_route_backend_documents_stubs():
    """Install lightweight import stubs for route_backend_documents."""
    stub_modules = {}

    config_module = types.ModuleType('config')
    config_module.cosmos_conversations_container = None
    config_module.cosmos_messages_container = None
    config_module.CosmosResourceNotFoundError = DummyNotFoundError
    config_module.CLIENTS = {}
    config_module.json = json
    config_module.traceback = traceback
    stub_modules['config'] = config_module

    auth_module = types.ModuleType('functions_authentication')
    auth_module.login_required = _passthrough_decorator
    auth_module.user_required = _passthrough_decorator
    auth_module.enabled_required = _passthrough_decorator
    auth_module.file_upload_required = _passthrough_decorator
    auth_module.get_current_user_id = lambda: None
    auth_module.jsonify = jsonify
    auth_module.request = request
    stub_modules['functions_authentication'] = auth_module

    documents_module = types.ModuleType('functions_documents')
    documents_module.add_file_task_to_file_processing_log = lambda *args, **kwargs: None
    stub_modules['functions_documents'] = documents_module

    settings_module = types.ModuleType('functions_settings')
    settings_module.get_settings = lambda: {}
    stub_modules['functions_settings'] = settings_module

    group_module = types.ModuleType('functions_group')
    group_module.get_user_groups = lambda *args, **kwargs: []
    stub_modules['functions_group'] = group_module

    public_module = types.ModuleType('functions_public_workspaces')
    public_module.get_user_visible_public_workspace_ids_from_settings = lambda *args, **kwargs: []
    stub_modules['functions_public_workspaces'] = public_module

    cache_module = types.ModuleType('utils_cache')
    cache_module.invalidate_personal_search_cache = lambda *args, **kwargs: None
    stub_modules['utils_cache'] = cache_module

    debug_module = types.ModuleType('functions_debug')
    debug_module.debug_print = lambda *args, **kwargs: None
    stub_modules['functions_debug'] = debug_module

    activity_module = types.ModuleType('functions_activity_logging')
    activity_module.log_document_upload = lambda *args, **kwargs: None
    activity_module.log_document_metadata_update_transaction = lambda *args, **kwargs: None
    stub_modules['functions_activity_logging'] = activity_module

    swagger_module = types.ModuleType('swagger_wrapper')
    swagger_module.swagger_route = lambda **kwargs: (lambda func: func)
    swagger_module.get_auth_security = lambda: {}
    stub_modules['swagger_wrapper'] = swagger_module

    for module_name, module in stub_modules.items():
        sys.modules[module_name] = module


def _load_route_backend_documents_module():
    _install_route_backend_documents_stubs()
    if 'route_backend_documents' in sys.modules:
        del sys.modules['route_backend_documents']
    return importlib.import_module('route_backend_documents')


def build_file_content_test_app(test_user_id, conversation_items, message_items):
    """Register document routes with fake containers for file-content tests."""
    route_backend_documents = _load_route_backend_documents_module()

    conversation_container = FakeConversationContainer(conversation_items)
    message_container = FakeMessageContainer(message_items)

    route_backend_documents.cosmos_conversations_container = conversation_container
    route_backend_documents.cosmos_messages_container = message_container
    route_backend_documents.get_current_user_id = lambda: test_user_id
    route_backend_documents.login_required = lambda func: func
    route_backend_documents.user_required = lambda func: func
    route_backend_documents.enabled_required = _passthrough_decorator
    route_backend_documents.swagger_route = lambda **kwargs: (lambda func: func)
    route_backend_documents.get_auth_security = lambda: {}
    route_backend_documents.debug_print = lambda *args, **kwargs: None
    route_backend_documents.CosmosResourceNotFoundError = DummyNotFoundError

    app = Flask(__name__)
    app.config['TESTING'] = True
    route_backend_documents.register_route_backend_documents(app)

    return app, message_container


def _install_route_frontend_conversations_stubs():
    """Install lightweight import stubs for route_frontend_conversations."""
    stub_modules = {}

    config_module = types.ModuleType('config')
    config_module.cosmos_conversations_container = None
    config_module.cosmos_messages_container = None
    config_module.CosmosResourceNotFoundError = DummyNotFoundError
    stub_modules['config'] = config_module

    auth_module = types.ModuleType('functions_authentication')
    auth_module.login_required = _passthrough_decorator
    auth_module.user_required = _passthrough_decorator
    auth_module.get_current_user_id = lambda: None
    auth_module.jsonify = jsonify
    auth_module.redirect = lambda location: f'redirect:{location}'
    auth_module.url_for = lambda endpoint: f'/{endpoint}'
    auth_module.render_template = lambda template_name, **kwargs: (
        f"rendered:{template_name}:{kwargs.get('conversation_id', '')}"
    )
    stub_modules['functions_authentication'] = auth_module

    debug_module = types.ModuleType('functions_debug')
    debug_module.debug_print = lambda *args, **kwargs: None
    stub_modules['functions_debug'] = debug_module

    chat_module = types.ModuleType('functions_chat')
    chat_module.sort_messages_by_thread = lambda items: items
    stub_modules['functions_chat'] = chat_module

    artifacts_module = types.ModuleType('functions_message_artifacts')
    artifacts_module.build_message_artifact_payload_map = lambda *args, **kwargs: {}
    artifacts_module.filter_assistant_artifact_items = lambda items: items
    stub_modules['functions_message_artifacts'] = artifacts_module

    swagger_module = types.ModuleType('swagger_wrapper')
    swagger_module.swagger_route = lambda **kwargs: (lambda func: func)
    swagger_module.get_auth_security = lambda: {}
    stub_modules['swagger_wrapper'] = swagger_module

    for module_name, module in stub_modules.items():
        sys.modules[module_name] = module


def _load_route_frontend_conversations_module():
    _install_route_frontend_conversations_stubs()
    if 'route_frontend_conversations' in sys.modules:
        del sys.modules['route_frontend_conversations']
    return importlib.import_module('route_frontend_conversations')


def build_frontend_conversation_test_app(test_user_id, conversation_items, message_items):
    """Register frontend conversation routes with fake containers."""
    route_frontend_conversations = _load_route_frontend_conversations_module()

    conversation_container = FakeConversationContainer(conversation_items)
    message_container = FakeMessageContainer(message_items)

    route_frontend_conversations.cosmos_conversations_container = conversation_container
    route_frontend_conversations.cosmos_messages_container = message_container
    route_frontend_conversations.get_current_user_id = lambda: test_user_id
    route_frontend_conversations.login_required = lambda func: func
    route_frontend_conversations.user_required = lambda func: func
    route_frontend_conversations.swagger_route = lambda **kwargs: (lambda func: func)
    route_frontend_conversations.get_auth_security = lambda: {}
    route_frontend_conversations.debug_print = lambda *args, **kwargs: None
    route_frontend_conversations.filter_assistant_artifact_items = lambda items: items
    route_frontend_conversations.sort_messages_by_thread = lambda items: items
    route_frontend_conversations.CosmosResourceNotFoundError = DummyNotFoundError

    app = Flask(__name__)
    app.config['TESTING'] = True
    route_frontend_conversations.register_route_frontend_conversations(app)

    return app, message_container


def test_foreign_delete_returns_forbidden_before_message_work():
    """Verify foreign conversation deletes fail before any message work executes."""
    print('🔍 Testing foreign delete rejection...')

    app, conversation_container, message_container = build_delete_test_app(
        'user-attacker',
        [
            {
                'id': 'conversation-victim',
                'user_id': 'user-victim',
                'title': 'Victim Conversation',
            }
        ],
        [
            {
                'id': 'message-victim',
                'conversation_id': 'conversation-victim',
                'content': 'Victim content',
            }
        ],
    )

    with app.test_client() as client:
        response = client.delete('/api/conversations/conversation-victim')

    payload = response.get_json()
    if response.status_code != 403:
        print(f'❌ Expected 403, got {response.status_code}: {payload}')
        return False
    if payload.get('error') != 'Forbidden':
        print(f'❌ Expected Forbidden error, got {payload}')
        return False
    if message_container.query_count != 0:
        print(f'❌ Expected no message query, got {message_container.query_count}')
        return False
    if 'conversation-victim' not in conversation_container.items:
        print('❌ Conversation should not have been deleted for a foreign user')
        return False

    print('✅ Foreign delete was blocked before destructive work')
    return True


def test_owner_delete_succeeds_and_removes_records():
    """Verify owners can still delete their own conversations."""
    print('🔍 Testing owner delete success...')

    app, conversation_container, message_container = build_delete_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-owner',
                'user_id': 'user-owner',
                'title': 'Owner Conversation',
            }
        ],
        [
            {
                'id': 'message-owner',
                'conversation_id': 'conversation-owner',
                'content': 'Owner content',
            }
        ],
    )

    with app.test_client() as client:
        response = client.delete('/api/conversations/conversation-owner')

    payload = response.get_json()
    if response.status_code != 200 or payload != {'success': True}:
        print(f'❌ Expected successful delete, got {response.status_code}: {payload}')
        return False
    if 'conversation-owner' in conversation_container.items:
        print('❌ Owner conversation should have been deleted')
        return False
    if 'message-owner' not in message_container.deleted_ids:
        print(f'❌ Expected message delete, got {message_container.deleted_ids}')
        return False

    print('✅ Owner delete removed the conversation and its messages')
    return True


def test_foreign_file_content_returns_forbidden_before_query():
    """Verify foreign file-content reads fail before the message query executes."""
    print('🔍 Testing foreign file-content rejection...')

    app, message_container = build_file_content_test_app(
        'user-attacker',
        [
            {
                'id': 'conversation-victim',
                'user_id': 'user-victim',
            }
        ],
        [
            {
                'id': 'file-victim',
                'conversation_id': 'conversation-victim',
                'filename': 'victim.txt',
                'file_content': 'Victim file content',
            }
        ],
    )

    with app.test_client() as client:
        response = client.post(
            '/api/get_file_content',
            json={
                'conversation_id': 'conversation-victim',
                'file_id': 'file-victim',
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
        print(f'❌ Expected no file-content query, got {message_container.query_count}')
        return False

    print('✅ Foreign file-content read was blocked before querying messages')
    return True


def test_owner_file_content_succeeds():
    """Verify owners can still read their own uploaded file content."""
    print('🔍 Testing owner file-content success...')

    app, message_container = build_file_content_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-owner',
                'user_id': 'user-owner',
            }
        ],
        [
            {
                'id': 'file-owner',
                'conversation_id': 'conversation-owner',
                'filename': 'owner.txt',
                'file_content': 'Owner file content',
            }
        ],
    )

    with app.test_client() as client:
        response = client.post(
            '/api/get_file_content',
            json={
                'conversation_id': 'conversation-owner',
                'file_id': 'file-owner',
            },
        )

    payload = response.get_json()
    if response.status_code != 200:
        print(f'❌ Expected 200, got {response.status_code}: {payload}')
        return False
    if payload.get('file_content') != 'Owner file content':
        print(f'❌ Unexpected owner file-content payload: {payload}')
        return False
    if message_container.query_count != 1:
        print(f'❌ Expected one file-content query, got {message_container.query_count}')
        return False

    print('✅ Owner file-content read returned the expected content')
    return True


def test_frontend_routes_reject_foreign_conversation_reads():
    """Verify frontend conversation routes fail closed for foreign conversations."""
    print('🔍 Testing frontend conversation rejection...')

    app, message_container = build_frontend_conversation_test_app(
        'user-attacker',
        [
            {
                'id': 'conversation-victim',
                'user_id': 'user-victim',
            }
        ],
        [
            {
                'id': 'message-victim',
                'conversation_id': 'conversation-victim',
                'role': 'user',
                'content': 'Victim message',
            }
        ],
    )

    with app.test_client() as client:
        view_response = client.get('/conversation/conversation-victim')
        messages_response = client.get('/conversation/conversation-victim/messages')

    messages_payload = messages_response.get_json()
    if view_response.status_code != 403:
        print(f'❌ Expected frontend view 403, got {view_response.status_code}')
        return False
    if messages_response.status_code != 403:
        print(f'❌ Expected frontend messages 403, got {messages_response.status_code}: {messages_payload}')
        return False
    if messages_payload.get('error') != 'Forbidden':
        print(f'❌ Expected Forbidden error, got {messages_payload}')
        return False
    if message_container.query_count != 0:
        print(f'❌ Expected no frontend message query, got {message_container.query_count}')
        return False

    print('✅ Frontend conversation routes reject foreign reads before querying messages')
    return True


def test_chat_loader_handles_non_ok_message_responses():
    """Verify the chat loader has an explicit non-success response path."""
    print('🔍 Testing chat loader non-success handling...')

    source = read_file_text(CHAT_MESSAGES_FILE)
    required_snippets = [
        'const data = await response.json().catch(() => ({}));',
        'if (!response.ok) {',
        'error.status = response.status;',
        'if (error?.status === 403) {',
        'errorMessage = "You do not have access to this conversation.";',
        'showToast(errorMessage, "danger");',
        '${escapeHtml(errorMessage)}',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    if missing:
        print(f'❌ Missing chat loader snippets: {missing}')
        return False

    print('✅ Chat loader non-success handling passed')
    return True


def test_fix_documentation_and_version_exist():
    """Verify the follow-up fix document exists under the current version."""
    print('🔍 Testing follow-up fix documentation and version...')

    if read_config_version() != '0.241.022':
        print(f'❌ Expected config version 0.241.022, got {read_config_version()}')
        return False
    if not os.path.exists(FIX_DOC):
        print(f'❌ Expected follow-up fix documentation at {FIX_DOC}')
        return False

    print('✅ Follow-up fix documentation and version passed')
    return True


if __name__ == '__main__':
    tests = [
        test_foreign_delete_returns_forbidden_before_message_work,
        test_owner_delete_succeeds_and_removes_records,
        test_foreign_file_content_returns_forbidden_before_query,
        test_owner_file_content_succeeds,
        test_frontend_routes_reject_foreign_conversation_reads,
        test_chat_loader_handles_non_ok_message_responses,
        test_fix_documentation_and_version_exist,
    ]

    print('🧪 Running personal conversation authorization follow-up tests...')
    print('=' * 60)

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print('\n' + '=' * 60)
    print(f'📊 Test Results: {sum(results)}/{len(results)} tests passed')

    sys.exit(0 if success else 1)