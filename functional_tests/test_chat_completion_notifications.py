#!/usr/bin/env python3
# test_chat_completion_notifications.py
"""
Functional test for chat completion notifications.
Version: 0.239.136
Implemented in: 0.239.128

This test ensures that personal chat completions create deep-link notifications,
conversation unread state is normalized for list/detail responses, and the
mark-read flow clears both the unread marker and the related notification.
"""

import copy
import os
import re
import sys

from flask import Flask

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class FakeConversationContainer:
    """In-memory container for conversation route tests."""

    def __init__(self, items=None):
        self.items = {}
        for item in items or []:
            self.upsert_item(item)

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        if item_id not in self.items:
            raise KeyError(item_id)
        return copy.deepcopy(self.items[item_id])

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)

    def query_items(self, query=None, enable_cross_partition_query=False, partition_key=None, parameters=None):
        results = [copy.deepcopy(item) for item in self.items.values()]

        if parameters:
            parameter_map = {param['name']: param['value'] for param in parameters}
            if '@user_id' in parameter_map:
                results = [item for item in results if item.get('user_id') == parameter_map['@user_id']]
        elif query:
            user_match = re.search(r"c\.user_id = '([^']+)'", query)
            if user_match:
                results = [item for item in results if item.get('user_id') == user_match.group(1)]

        if query and 'ORDER BY c.last_updated DESC' in query:
            results.sort(key=lambda item: item.get('last_updated', ''), reverse=True)

        return results


class FakeNotificationContainer:
    """In-memory container for notification helper tests."""

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


def build_test_app(test_user_id, conversation_container, notification_container):
    """Register the conversation routes with fake auth/container dependencies."""
    import functions_notifications
    import route_backend_conversations

    original_notification_container = functions_notifications.cosmos_notifications_container
    original_conversation_container = route_backend_conversations.cosmos_conversations_container
    original_login_required = route_backend_conversations.login_required
    original_user_required = route_backend_conversations.user_required
    original_swagger_route = route_backend_conversations.swagger_route
    original_get_auth_security = route_backend_conversations.get_auth_security
    original_get_current_user_id = route_backend_conversations.get_current_user_id

    functions_notifications.cosmos_notifications_container = notification_container
    route_backend_conversations.cosmos_conversations_container = conversation_container
    route_backend_conversations.login_required = lambda func: func
    route_backend_conversations.user_required = lambda func: func
    route_backend_conversations.swagger_route = lambda **kwargs: (lambda func: func)
    route_backend_conversations.get_auth_security = lambda: {}
    route_backend_conversations.get_current_user_id = lambda: test_user_id

    app = Flask(__name__)
    app.config['TESTING'] = True
    route_backend_conversations.register_route_backend_conversations(app)

    def restore():
        functions_notifications.cosmos_notifications_container = original_notification_container
        route_backend_conversations.cosmos_conversations_container = original_conversation_container
        route_backend_conversations.login_required = original_login_required
        route_backend_conversations.user_required = original_user_required
        route_backend_conversations.swagger_route = original_swagger_route
        route_backend_conversations.get_auth_security = original_get_auth_security
        route_backend_conversations.get_current_user_id = original_get_current_user_id

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


def test_chat_response_notification_creation_and_deep_link():
    """Verify helper-created notifications include the chat completion deep link and metadata."""
    print("🔍 Testing chat completion notification creation...")

    import functions_notifications

    fake_container = FakeNotificationContainer()
    original_container = functions_notifications.cosmos_notifications_container
    functions_notifications.cosmos_notifications_container = fake_container

    try:
        notification = functions_notifications.create_chat_response_notification(
            user_id='test-user-chat-notification',
            conversation_id='conversation-123',
            message_id='assistant-message-456',
            conversation_title='Quarterly Planning',
            response_preview='The plan is ready for review.'
        )

        if not notification:
            print("❌ Notification helper did not return a document")
            return False

        if notification.get('notification_type') != 'chat_response_complete':
            print("❌ Notification type was not chat_response_complete")
            return False

        if notification.get('link_url') != '/chats?conversationId=conversation-123':
            print(f"❌ Unexpected deep link: {notification.get('link_url')}")
            return False

        metadata = notification.get('metadata', {})
        if metadata.get('conversation_id') != 'conversation-123' or metadata.get('message_id') != 'assistant-message-456':
            print(f"❌ Notification metadata mismatch: {metadata}")
            return False

        print("✅ Chat completion notification helper created the expected deep link and metadata")
        return True
    finally:
        functions_notifications.cosmos_notifications_container = original_container


def test_conversation_routes_normalize_unread_fields():
    """Verify list/detail conversation routes normalize unread fields for older documents."""
    print("🔍 Testing conversation unread field normalization...")

    test_user_id = 'test-user-unread-normalization'
    old_conversation = {
        'id': 'conversation-old-shape',
        'user_id': test_user_id,
        'title': 'Legacy Conversation',
        'last_updated': '2026-03-19T00:00:00Z',
        'context': [],
        'tags': [],
        'strict': False,
        'is_pinned': False,
        'is_hidden': False,
    }

    app, restore = build_test_app(
        test_user_id,
        FakeConversationContainer([old_conversation]),
        FakeNotificationContainer(),
    )

    try:
        with app.test_request_context('/api/get_conversations'):
            conversations_response, conversations_status = unwrap_response(
                app.view_functions['get_conversations']()
            )

        if conversations_status != 200:
            print(f"❌ Unexpected conversation list status: {conversations_status}")
            return False

        conversation_payload = conversations_response.get_json().get('conversations', [])[0]
        if conversation_payload.get('has_unread_assistant_response') is not False:
            print(f"❌ Conversation list did not normalize unread flag: {conversation_payload}")
            return False

        with app.test_request_context('/api/conversations/conversation-old-shape/metadata'):
            metadata_response, metadata_status = unwrap_response(
                app.view_functions['get_conversation_metadata_api']('conversation-old-shape')
            )

        if metadata_status != 200:
            print(f"❌ Unexpected conversation metadata status: {metadata_status}")
            return False

        metadata_payload = metadata_response.get_json()
        if metadata_payload.get('last_unread_assistant_message_id', 'missing') is not None:
            print(f"❌ Metadata route did not normalize unread message id: {metadata_payload}")
            return False

        print("✅ Conversation list and metadata routes normalize unread fields for older documents")
        return True
    finally:
        restore()


def test_mark_read_endpoint_clears_unread_state_and_notification():
    """Verify mark-read clears conversation unread state and marks matching notifications read."""
    print("🔍 Testing conversation mark-read lifecycle...")

    import functions_notifications

    test_user_id = 'test-user-mark-read'
    conversation_id = 'conversation-mark-read'
    assistant_message_id = 'assistant-message-mark-read'

    fake_conversations = FakeConversationContainer([
        {
            'id': conversation_id,
            'user_id': test_user_id,
            'title': 'Unread Conversation',
            'last_updated': '2026-03-19T00:00:00Z',
            'context': [],
            'tags': [],
            'strict': False,
            'is_pinned': False,
            'is_hidden': False,
            'has_unread_assistant_response': True,
            'last_unread_assistant_message_id': assistant_message_id,
            'last_unread_assistant_at': '2026-03-19T00:00:00Z',
        }
    ])
    fake_notifications = FakeNotificationContainer()

    original_notification_container = functions_notifications.cosmos_notifications_container
    functions_notifications.cosmos_notifications_container = fake_notifications
    functions_notifications.create_chat_response_notification(
        user_id=test_user_id,
        conversation_id=conversation_id,
        message_id=assistant_message_id,
        conversation_title='Unread Conversation',
        response_preview='The AI model responded while you were away.'
    )
    functions_notifications.cosmos_notifications_container = original_notification_container

    app, restore = build_test_app(test_user_id, fake_conversations, fake_notifications)

    try:
        with app.test_request_context(f'/api/conversations/{conversation_id}/mark-read', method='POST'):
            response, status_code = unwrap_response(
                app.view_functions['mark_conversation_read_api'](conversation_id)
            )

        if status_code != 200:
            print(f"❌ Unexpected mark-read status: {status_code}")
            return False

        response_payload = response.get_json()
        if not response_payload.get('success'):
            print(f"❌ Mark-read endpoint did not report success: {response_payload}")
            return False

        updated_conversation = fake_conversations.read_item(conversation_id, conversation_id)
        if updated_conversation.get('has_unread_assistant_response'):
            print(f"❌ Conversation unread flag still set: {updated_conversation}")
            return False

        if updated_conversation.get('last_unread_assistant_message_id') is not None:
            print(f"❌ Conversation unread message id was not cleared: {updated_conversation}")
            return False

        stored_notification = next(iter(fake_notifications.items.values()))
        if test_user_id not in stored_notification.get('read_by', []):
            print(f"❌ Notification was not marked read: {stored_notification}")
            return False

        print("✅ Mark-read endpoint cleared conversation unread state and related notification")
        return True
    finally:
        restore()


def test_frontend_wires_unread_dot_and_mark_read_flow():
    """Verify the chat UI files render the unread dot and call the mark-read API."""
    print("🔍 Testing frontend unread dot and mark-read wiring...")

    repo_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    main_list_js = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'chat', 'chat-conversations.js')
    sidebar_js = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'chat', 'chat-sidebar-conversations.js')
    streaming_js = os.path.join(repo_root, 'application', 'single_app', 'static', 'js', 'chat', 'chat-streaming.js')
    chats_css = os.path.join(repo_root, 'application', 'single_app', 'static', 'css', 'chats.css')

    required_checks = [
        (main_list_js, 'fetch(`/api/conversations/${conversationId}/mark-read`, {'),
        (main_list_js, 'function createUnreadDotElement() {'),
        (main_list_js, 'setSidebarConversationUnreadState(conversationId, hasUnread);'),
        (sidebar_js, "conversation-unread-dot', 'sidebar-conversation-unread-dot"),
        (streaming_js, "markConversationRead(finalData.conversation_id, { force: true, suppressErrorToast: true })"),
        (chats_css, '.conversation-unread-dot {'),
    ]

    for file_path, snippet in required_checks:
        with open(file_path, 'r', encoding='utf-8') as handle:
            content = handle.read()
        if snippet not in content:
            print(f"❌ Missing required unread-flow snippet in {os.path.basename(file_path)}: {snippet}")
            return False

    print("✅ Frontend files include unread-dot rendering and mark-read wiring")
    return True


def test_streaming_completion_wires_unread_state_and_notification_creation():
    """Verify the streaming completion branch persists unread state and notification creation."""
    print("🔍 Testing streaming completion unread-state wiring...")

    route_file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..',
        'application',
        'single_app',
        'route_backend_chats.py'
    )

    with open(route_file_path, 'r', encoding='utf-8') as handle:
        route_content = handle.read()

    required_snippets = [
        'from functions_conversation_unread import mark_conversation_unread',
        'from functions_notifications import create_chat_response_notification',
        'def is_personal_chat_conversation(conversation_item):',
        "return not chat_type.startswith('group') and not chat_type.startswith('public')",
        'if is_personal_chat_conversation(conversation_item):',
        'conversation_item = mark_conversation_unread(',
        'notification_doc = create_chat_response_notification(',
        "response_preview=accumulated_content",
    ]

    for snippet in required_snippets:
        if snippet not in route_content:
            print(f"❌ Missing streaming completion notification snippet: {snippet}")
            return False

    print("✅ Streaming completion branch marks unread state and creates notifications")
    return True


def test_version_updated_for_feature():
    """Verify config.py reflects the new chat completion notification version."""
    print("🔍 Testing version update for chat completion notifications...")

    config_file_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..',
        'application',
        'single_app',
        'config.py'
    )

    with open(config_file_path, 'r', encoding='utf-8') as handle:
        config_content = handle.read()

    if 'VERSION = "0.239.136"' not in config_content:
        print("❌ Version not updated to 0.239.136")
        return False

    print("✅ Version properly updated to 0.239.136")
    return True


if __name__ == '__main__':
    tests = [
        test_chat_response_notification_creation_and_deep_link,
        test_conversation_routes_normalize_unread_fields,
        test_mark_read_endpoint_clears_unread_state_and_notification,
        test_frontend_wires_unread_dot_and_mark_read_flow,
        test_streaming_completion_wires_unread_state_and_notification_creation,
        test_version_updated_for_feature,
    ]

    results = []
    for test in tests:
        print()
        results.append(test())

    success = all(results)
    print(f"\n📊 Test Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)