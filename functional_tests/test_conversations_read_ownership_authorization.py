#!/usr/bin/env python3
# test_conversations_read_ownership_authorization.py
"""
Functional test for personal conversation read authorization hardening.
Version: 0.250.101
Implemented in: 0.241.011; 0.241.022; 0.241.032; 0.250.033; 0.250.035; 0.250.074; 0.250.101

This test ensures authenticated users can only read messages and images from
their own personal conversations, and that foreign conversation reads fail with
403 without querying the message container. It also validates blob-backed image
messages stream only after conversation authorization succeeds. It validates
that mark-read cache invalidation is idempotent for already-read conversations
and that fork conflict logging preserves the intended HTTP 409 response.
"""

import copy
import importlib
import os
import sys
import types

from flask import Flask, jsonify
import werkzeug

if not hasattr(werkzeug, '__version__'):
    werkzeug.__version__ = '3'

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class DummyNotFoundError(Exception):
    """Raised when a fake Cosmos item is not found."""


class FakeConversationContainer:
    """In-memory conversation container for route authorization tests."""

    def __init__(self, items=None):
        self.items = {}
        self.upsert_count = 0
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        if item_id not in self.items:
            raise DummyNotFoundError(item_id)
        return copy.deepcopy(self.items[item_id])

    def upsert_item(self, item):
        self.upsert_count += 1
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)


class FakeMessageContainer:
    """In-memory message container that tracks query attempts."""

    def __init__(self, items=None):
        self.items = [copy.deepcopy(item) for item in (items or [])]
        self.query_count = 0

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        self.query_count += 1
        item_id = item if item is not None else args[0]
        for stored_item in self.items:
            if stored_item.get('id') == item_id and stored_item.get('conversation_id') == partition_key:
                return copy.deepcopy(stored_item)
        raise DummyNotFoundError(item_id)

    def query_items(self, query=None, partition_key=None, *args, **kwargs):
        self.query_count += 1
        matching_items = [
            copy.deepcopy(item)
            for item in self.items
            if item.get('conversation_id') == partition_key
        ]
        matching_items.sort(key=lambda item: item.get('timestamp', ''))
        return matching_items


class FakeBlobProperties:
    """Minimal blob properties object for streaming tests."""

    def __init__(self, content_bytes):
        self.size = len(content_bytes)


class FakeBlobDownload:
    """Minimal blob downloader that yields stored bytes as one chunk."""

    def __init__(self, content_bytes):
        self.content_bytes = content_bytes

    def chunks(self):
        yield self.content_bytes


class FakeBlobClient:
    """Minimal blob client for image route streaming tests."""

    def __init__(self, content_bytes):
        self.content_bytes = content_bytes

    def get_blob_properties(self):
        return FakeBlobProperties(self.content_bytes)

    def download_blob(self):
        return FakeBlobDownload(self.content_bytes)


class FakeBlobServiceClient:
    """In-memory blob service keyed by container and blob path."""

    def __init__(self, blob_items=None):
        self.blob_items = dict(blob_items or {})

    def get_blob_client(self, container=None, blob=None, *args, **kwargs):
        blob_key = (container, blob)
        if blob_key not in self.blob_items:
            raise DummyNotFoundError(blob_key)
        return FakeBlobClient(self.blob_items[blob_key])


def _passthrough_decorator(*args, **kwargs):
    """Return the wrapped function unchanged for decorator stubs."""
    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return args[0]
    return lambda func: func


def _install_route_import_stubs():
    """Install lightweight module stubs so the route module imports in isolation."""
    stub_modules = {}

    config_module = types.ModuleType('config')
    config_module.cosmos_conversations_container = None
    config_module.cosmos_messages_container = None
    config_module.CosmosResourceNotFoundError = DummyNotFoundError
    config_module.CLIENTS = {}
    stub_modules['config'] = config_module

    appinsights_module = types.ModuleType('functions_appinsights')
    appinsights_module.log_event = lambda *args, **kwargs: None
    stub_modules['functions_appinsights'] = appinsights_module

    collaboration_module = types.ModuleType('functions_collaboration')
    collaboration_module.assert_user_can_view_collaboration_conversation = lambda *args, **kwargs: None
    collaboration_module.assert_user_can_participate_in_collaboration_conversation = lambda *args, **kwargs: None
    collaboration_module.ensure_collaboration_source_conversation = lambda *args, **kwargs: None
    collaboration_module.get_collaboration_conversation = lambda *args, **kwargs: (_ for _ in ()).throw(DummyNotFoundError('missing'))
    collaboration_module.list_group_collaboration_conversations_for_user = lambda *args, **kwargs: []
    collaboration_module.list_collaboration_messages = lambda *args, **kwargs: []
    collaboration_module.list_personal_collaboration_conversations_for_user = lambda *args, **kwargs: []
    collaboration_module.serialize_collaboration_conversation = lambda item, *args, **kwargs: item
    stub_modules['functions_collaboration'] = collaboration_module

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

    conversation_cache_module = types.ModuleType('functions_conversation_cache')
    conversation_cache_module.build_conversation_cache_key = lambda *args, **kwargs: None
    conversation_cache_module.bump_conversation_cache_version = lambda *args, **kwargs: None
    conversation_cache_module.get_cached_conversation_payload = lambda *args, **kwargs: None
    conversation_cache_module.get_conversation_cache_settings = lambda *args, **kwargs: {
        'enabled': False,
        'ttl_seconds': 0,
    }
    conversation_cache_module.invalidate_conversation_cache_for_item = lambda *args, **kwargs: None
    conversation_cache_module.set_cached_conversation_payload = lambda *args, **kwargs: None
    stub_modules['functions_conversation_cache'] = conversation_cache_module

    conversation_feed_module = types.ModuleType('functions_conversation_feed')
    conversation_feed_module.CONVERSATION_FEED_SOURCE_COLLABORATION = 'collaboration'
    conversation_feed_module.CONVERSATION_FEED_SOURCE_LEGACY = 'legacy'
    conversation_feed_module.build_conversation_feed_page = lambda *args, **kwargs: {}
    conversation_feed_module.decode_conversation_feed_cursor = lambda *args, **kwargs: None
    conversation_feed_module.get_conversation_feed_source_offsets = lambda *args, **kwargs: {}
    conversation_feed_module.is_conversation_feed_cursor_compatible = lambda *args, **kwargs: False
    conversation_feed_module.normalize_conversation_feed_page_size = lambda value=None: int(value or 50)
    conversation_feed_module.sort_conversation_feed_recent = lambda items: items
    conversation_feed_module.tag_conversation_feed_source = lambda item, source: item
    stub_modules['functions_conversation_feed'] = conversation_feed_module

    def normalize_conversation_unread_state(item):
        item['has_unread_assistant_response'] = bool(item.get('has_unread_assistant_response', False))
        item['last_unread_assistant_message_id'] = item.get('last_unread_assistant_message_id')
        item['last_unread_assistant_at'] = item.get('last_unread_assistant_at')
        return item

    def clear_conversation_unread(item):
        normalized_item = normalize_conversation_unread_state(item)
        normalized_item['has_unread_assistant_response'] = False
        normalized_item['last_unread_assistant_message_id'] = None
        normalized_item['last_unread_assistant_at'] = None
        return normalized_item

    unread_module = types.ModuleType('functions_conversation_unread')
    unread_module.clear_conversation_unread = clear_conversation_unread
    unread_module.normalize_conversation_unread_state = normalize_conversation_unread_state
    stub_modules['functions_conversation_unread'] = unread_module

    notifications_module = types.ModuleType('functions_notifications')
    notifications_module.mark_chat_response_notifications_read_for_conversation = lambda *args, **kwargs: None
    stub_modules['functions_notifications'] = notifications_module

    debug_module = types.ModuleType('functions_debug')
    debug_module.debug_print = lambda *args, **kwargs: None
    stub_modules['functions_debug'] = debug_module

    documents_module = types.ModuleType('functions_documents')
    documents_module.delete_chat_upload_workspace_documents_for_conversation = lambda *args, **kwargs: None
    documents_module.serialize_chat_upload_workspace_documents_for_conversation = lambda *args, **kwargs: []
    stub_modules['functions_documents'] = documents_module

    group_module = types.ModuleType('functions_group')
    group_module.get_user_groups = lambda *args, **kwargs: []
    stub_modules['functions_group'] = group_module

    artifacts_module = types.ModuleType('functions_message_artifacts')
    artifacts_module.build_message_artifact_payload_map = lambda items: {}
    artifacts_module.filter_assistant_artifact_items = lambda items: items
    artifacts_module.hydrate_agent_citations_from_artifacts = lambda items, artifact_map: items
    stub_modules['functions_message_artifacts'] = artifacts_module

    simplechat_operations_module = types.ModuleType('functions_simplechat_operations')
    simplechat_operations_module.ConversationForkConflictError = RuntimeError
    simplechat_operations_module.create_personal_conversation_for_current_user = lambda *args, **kwargs: {}
    simplechat_operations_module.delete_blob_backed_chat_message_files = lambda *args, **kwargs: None
    simplechat_operations_module.derive_conversation_title_from_message = lambda *args, **kwargs: ''
    simplechat_operations_module.fork_personal_conversation_for_user = lambda *args, **kwargs: {}
    stub_modules['functions_simplechat_operations'] = simplechat_operations_module

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

    utils_cache_module = types.ModuleType('utils_cache')
    utils_cache_module.invalidate_personal_search_cache = lambda *args, **kwargs: None
    stub_modules['utils_cache'] = utils_cache_module

    for module_name, module in stub_modules.items():
        sys.modules[module_name] = module


def _load_route_backend_conversations_module():
    """Import the route module after installing lightweight dependency stubs."""
    _install_route_import_stubs()
    if 'route_backend_conversations' in sys.modules:
        del sys.modules['route_backend_conversations']
    return importlib.import_module('route_backend_conversations')


def build_test_app(test_user_id, conversation_items, message_items, blob_items=None):
    """Register the conversation routes with fake auth and fake Cosmos containers."""
    route_backend_conversations = _load_route_backend_conversations_module()

    conversation_container = FakeConversationContainer(conversation_items)
    message_container = FakeMessageContainer(message_items)
    cache_bumps = []

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
    route_backend_conversations.bump_conversation_cache_version = (
        lambda user_id, reason=None: cache_bumps.append((user_id, reason)) or len(cache_bumps)
    )
    route_backend_conversations.mark_chat_response_notifications_read_for_conversation = lambda *args, **kwargs: 0
    route_backend_conversations.CLIENTS = {
        'storage_account_office_docs_client': FakeBlobServiceClient(blob_items),
    }

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.config['conversation_container'] = conversation_container
    app.config['conversation_cache_bumps'] = cache_bumps
    app.config['route_backend_conversations'] = route_backend_conversations
    route_backend_conversations.register_route_backend_conversations(app)

    return app, message_container, (lambda: None)


def test_owner_can_read_messages():
    """Verify an owner can read their own conversation history."""
    print("🔍 Testing owner message read access...")

    app, message_container, restore = build_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-owner',
                'user_id': 'user-owner',
            }
        ],
        [
            {
                'id': 'message-1',
                'conversation_id': 'conversation-owner',
                'role': 'user',
                'content': 'Owner message',
                'timestamp': '2026-05-05T12:00:00Z',
                'metadata': {},
            }
        ],
    )

    try:
        with app.test_client() as client:
            response = client.get('/api/get_messages?conversation_id=conversation-owner')

        payload = response.get_json()
        if response.status_code != 200:
            print(f"❌ Expected 200, got {response.status_code}: {payload}")
            return False

        if len(payload.get('messages', [])) != 1:
            print(f"❌ Expected one message, got {payload}")
            return False

        if message_container.query_count != 1:
            print(f"❌ Expected one message query, got {message_container.query_count}")
            return False

        print("✅ Owner message read returned expected payload")
        return True
    finally:
        restore()


def test_foreign_messages_return_forbidden_before_query():
    """Verify foreign conversation message reads fail closed before querying messages."""
    print("🔍 Testing foreign message read rejection...")

    app, message_container, restore = build_test_app(
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
                'timestamp': '2026-05-05T12:00:00Z',
                'metadata': {},
            }
        ],
    )

    try:
        with app.test_client() as client:
            response = client.get('/api/get_messages?conversation_id=conversation-victim')

        payload = response.get_json()
        if response.status_code != 403:
            print(f"❌ Expected 403, got {response.status_code}: {payload}")
            return False

        if payload.get('error') != 'Forbidden':
            print(f"❌ Expected Forbidden error, got {payload}")
            return False

        if message_container.query_count != 0:
            print(f"❌ Message container should not be queried, got {message_container.query_count}")
            return False

        print("✅ Foreign message read was blocked before querying messages")
        return True
    finally:
        restore()


def test_missing_conversation_preserves_empty_message_history_response():
    """Verify missing conversations still return the legacy empty message payload."""
    print("🔍 Testing missing conversation message response...")

    app, message_container, restore = build_test_app('user-owner', [], [])

    try:
        with app.test_client() as client:
            response = client.get('/api/get_messages?conversation_id=missing-conversation')

        payload = response.get_json()
        if response.status_code != 200:
            print(f"❌ Expected 200, got {response.status_code}: {payload}")
            return False

        if payload != {'messages': []}:
            print(f"❌ Expected empty messages payload, got {payload}")
            return False

        if message_container.query_count != 0:
            print(f"❌ Message container should not be queried, got {message_container.query_count}")
            return False

        print("✅ Missing conversation preserves the legacy empty payload")
        return True
    finally:
        restore()


def test_owner_can_read_image():
    """Verify an owner can fetch inline image content from their own conversation."""
    print("🔍 Testing owner image read access...")

    image_id = 'conversation-owner_image_20260505_random'
    app, message_container, restore = build_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-owner',
                'user_id': 'user-owner',
            }
        ],
        [
            {
                'id': image_id,
                'conversation_id': 'conversation-owner',
                'role': 'image',
                'content': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sN7sK8AAAAASUVORK5CYII=',
                'timestamp': '2026-05-05T12:00:00Z',
                'metadata': {},
            }
        ],
    )

    try:
        with app.test_client() as client:
            response = client.get(f'/api/image/{image_id}')

        if response.status_code != 200:
            print(f"❌ Expected 200, got {response.status_code}: {response.get_data(as_text=True)}")
            return False

        if response.mimetype != 'image/png':
            print(f"❌ Expected image/png, got {response.mimetype}")
            return False

        if message_container.query_count != 1:
            print(f"❌ Expected one image query, got {message_container.query_count}")
            return False

        print("✅ Owner image read returned binary image data")
        return True
    finally:
        restore()


def test_owner_can_stream_blob_backed_image():
    """Verify an owner can fetch blob-backed image bytes from their own conversation."""
    print("🔍 Testing owner blob-backed image streaming...")

    image_id = 'conversation-owner_file_20260505_random'
    blob_path = 'user-owner/conversation-owner/images/conversation-owner_file_20260505_random/image.png'
    image_bytes = b'fake-png-bytes'
    app, message_container, restore = build_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-owner',
                'user_id': 'user-owner',
            }
        ],
        [
            {
                'id': image_id,
                'conversation_id': 'conversation-owner',
                'role': 'image',
                'content': f'/api/image/{image_id}',
                'file_content_source': 'blob',
                'blob_container': 'personal-chat',
                'blob_path': blob_path,
                'mime_type': 'image/png',
                'timestamp': '2026-05-05T12:00:00Z',
                'metadata': {
                    'is_blob_backed': True,
                },
            }
        ],
        blob_items={
            ('personal-chat', blob_path): image_bytes,
        },
    )

    try:
        with app.test_client() as client:
            response = client.get(f'/api/image/{image_id}')

        if response.status_code != 200:
            print(f"❌ Expected 200, got {response.status_code}: {response.get_data(as_text=True)}")
            return False

        if response.mimetype != 'image/png':
            print(f"❌ Expected image/png, got {response.mimetype}")
            return False

        if response.get_data() != image_bytes:
            print(f"❌ Expected streamed blob bytes, got {response.get_data()}")
            return False

        if message_container.query_count != 1:
            print(f"❌ Expected one image read, got {message_container.query_count}")
            return False

        print("✅ Owner blob-backed image streamed expected bytes")
        return True
    finally:
        restore()


def test_foreign_image_return_forbidden_before_query():
    """Verify foreign conversation image reads fail closed before querying messages."""
    print("🔍 Testing foreign image read rejection...")

    image_id = 'conversation-victim_image_20260505_random'
    app, message_container, restore = build_test_app(
        'user-attacker',
        [
            {
                'id': 'conversation-victim',
                'user_id': 'user-victim',
            }
        ],
        [
            {
                'id': image_id,
                'conversation_id': 'conversation-victim',
                'role': 'image',
                'content': 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9sN7sK8AAAAASUVORK5CYII=',
                'timestamp': '2026-05-05T12:00:00Z',
                'metadata': {},
            }
        ],
    )

    try:
        with app.test_client() as client:
            response = client.get(f'/api/image/{image_id}')

        payload = response.get_json()
        if response.status_code != 403:
            print(f"❌ Expected 403, got {response.status_code}: {payload}")
            return False

        if payload.get('error') != 'Forbidden':
            print(f"❌ Expected Forbidden error, got {payload}")
            return False

        if message_container.query_count != 0:
            print(f"❌ Message container should not be queried, got {message_container.query_count}")
            return False

        print("✅ Foreign image read was blocked before querying messages")
        return True
    finally:
        restore()


def test_missing_image_preserves_not_found_response():
    """Verify missing images still return the existing not-found contract."""
    print("🔍 Testing missing image response...")

    image_id = 'conversation-owner_image_20260505_random'
    app, message_container, restore = build_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-owner',
                'user_id': 'user-owner',
            }
        ],
        [],
    )

    try:
        with app.test_client() as client:
            response = client.get(f'/api/image/{image_id}')

        payload = response.get_json()
        if response.status_code != 404:
            print(f"❌ Expected 404, got {response.status_code}: {payload}")
            return False

        if payload.get('error') != 'Image not found':
            print(f"❌ Expected Image not found error, got {payload}")
            return False

        if message_container.query_count != 1:
            print(f"❌ Expected one image query, got {message_container.query_count}")
            return False

        print("✅ Missing image preserves the not-found response")
        return True
    finally:
        restore()


def test_mark_read_only_invalidates_cache_when_unread_state_changes():
    """Verify mark-read does not churn conversation cache for already-read conversations."""
    print("🔍 Testing mark-read cache invalidation idempotency...")

    app, _message_container, restore = build_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-unread',
                'user_id': 'user-owner',
                'has_unread_assistant_response': True,
                'last_unread_assistant_message_id': 'assistant-message-1',
                'last_unread_assistant_at': '2026-07-06T00:00:00Z',
            },
            {
                'id': 'conversation-read',
                'user_id': 'user-owner',
                'has_unread_assistant_response': False,
                'last_unread_assistant_message_id': None,
                'last_unread_assistant_at': None,
            },
        ],
        [],
    )

    try:
        conversation_container = app.config['conversation_container']
        cache_bumps = app.config['conversation_cache_bumps']
        conversation_container.upsert_count = 0

        with app.test_client() as client:
            unread_response = client.post('/api/conversations/conversation-unread/mark-read')
            read_response = client.post('/api/conversations/conversation-read/mark-read')

        unread_payload = unread_response.get_json()
        read_payload = read_response.get_json()
        if unread_response.status_code != 200 or unread_payload.get('conversation_state_changed') is not True:
            print(f"❌ Expected unread mark-read to change state: {unread_response.status_code} {unread_payload}")
            return False

        if read_response.status_code != 200 or read_payload.get('conversation_state_changed') is not False:
            print(f"❌ Expected already-read mark-read to be idempotent: {read_response.status_code} {read_payload}")
            return False

        updated_unread = conversation_container.read_item('conversation-unread', 'conversation-unread')
        if updated_unread.get('has_unread_assistant_response'):
            print(f"❌ Unread conversation was not cleared: {updated_unread}")
            return False

        if conversation_container.upsert_count != 1:
            print(f"❌ Expected only one conversation upsert, got {conversation_container.upsert_count}")
            return False

        if cache_bumps != [('user-owner', 'conversation_marked_read')]:
            print(f"❌ Expected only unread conversation to invalidate cache, got {cache_bumps}")
            return False

        print("✅ Mark-read cache invalidation is idempotent for already-read conversations")
        return True
    finally:
        restore()


def test_fork_conflict_logging_preserves_409_response():
    """Verify structured conflict logging cannot turn a fork conflict into HTTP 500."""
    print("🔍 Testing fork conflict logging response...")

    app, _message_container, restore = build_test_app(
        'user-owner',
        [
            {
                'id': 'conversation-owner',
                'user_id': 'user-owner',
                'chat_type': 'group-single-user',
            }
        ],
        [],
    )

    try:
        route_module = app.config['route_backend_conversations']
        logged_events = []

        def raise_fork_conflict(**kwargs):
            raise route_module.ConversationForkConflictError('Workspace access changed')

        def capture_log_event(
            message,
            extra=None,
            level=None,
            includeStack=False,
            stacklevel=2,
            exceptionTraceback=None,
            debug_only=False,
            category='INFO',
            flush=False,
            message_args=None,
        ):
            logged_events.append({'message': message, 'extra': extra, 'level': level})

        route_module.fork_personal_conversation_for_user = raise_fork_conflict
        route_module.log_event = capture_log_event

        with app.test_client() as client:
            response = client.post(
                '/api/conversations/conversation-owner/fork',
                json={'message_id': 'assistant-message'},
            )

        payload = response.get_json()
        assert response.status_code == 409, (
            f"Expected 409, got {response.status_code}: {payload}"
        )
        assert payload == {'error': 'Conversation fork conflict'}, (
            f"Expected fork conflict payload, got {payload}"
        )
        assert logged_events and logged_events[0]['extra'] == {
            'source_conversation_id': 'conversation-owner',
            'selected_message_id': 'assistant-message',
            'user_id': 'user-owner',
        }, f"Expected structured fork conflict context, got {logged_events}"

        print("✅ Fork conflict logging preserved the intended 409 response")
        return True if __name__ == '__main__' else None
    finally:
        restore()


if __name__ == '__main__':
    tests = [
        test_owner_can_read_messages,
        test_foreign_messages_return_forbidden_before_query,
        test_missing_conversation_preserves_empty_message_history_response,
        test_owner_can_read_image,
        test_owner_can_stream_blob_backed_image,
        test_foreign_image_return_forbidden_before_query,
        test_missing_image_preserves_not_found_response,
        test_mark_read_only_invalidates_cache_when_unread_state_changes,
        test_fork_conflict_logging_preserves_409_response,
    ]

    print('🧪 Running conversation read ownership authorization tests...')
    print('=' * 60)

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print('\n' + '=' * 60)
    print(f'📊 Test Results: {sum(results)}/{len(results)} tests passed')

    sys.exit(0 if success else 1)