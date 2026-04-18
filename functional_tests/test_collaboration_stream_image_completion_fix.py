#!/usr/bin/env python3
# test_collaboration_stream_image_completion_fix.py
"""
Functional test for collaboration image stream completion.
Version: 0.241.024
Implemented in: 0.241.024

This test ensures collaborative image streaming completes through the shared
stream bridge without tripping the nested `updated_conversation_doc` scoping
bug, and that the final SSE payload emits a collaboration image URL instead of
an error event.
"""

import copy
import json
import os
import sys

from flask import Flask, Response


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


class FakeItemContainer:
    """Minimal in-memory container for collaboration message documents."""

    def __init__(self, items=None):
        self.items = {}
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        del partition_key, args, kwargs
        return copy.deepcopy(self.items[item])

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)


class FakeConversationContainer:
    """Minimal in-memory container for source conversation lookups."""

    def __init__(self, items=None):
        self.items = {}
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        del partition_key, args, kwargs
        return copy.deepcopy(self.items[item])

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)


class FakeEventRegistry:
    """Collects published collaboration events for assertions."""

    def __init__(self):
        self.events = []

    def publish(self, conversation_id, payload):
        self.events.append((conversation_id, copy.deepcopy(payload)))


def build_stream_fix_test_app():
    """Register the collaboration stream route with isolated fake dependencies."""
    import route_backend_collaboration
    from collaboration_models import MESSAGE_KIND_AI_REQUEST, MESSAGE_KIND_ASSISTANT

    conversation_id = 'shared-image-conversation-001'
    source_conversation_id = 'source-conversation-001'
    current_user = {
        'user_id': 'owner-user-001',
        'display_name': 'Owner User',
        'email': 'owner@example.com',
    }
    collaboration_conversation_doc = {
        'id': conversation_id,
        'title': 'Shared Image Conversation',
        'chat_type': 'personal_multi_user',
        'conversation_kind': 'collaborative',
        'created_by_user_id': current_user['user_id'],
        'created_by_display_name': current_user['display_name'],
        'participants': [
            {'user_id': current_user['user_id'], 'display_name': current_user['display_name'], 'status': 'accepted', 'role': 'owner'},
        ],
        'message_count': 1,
        'context': [],
        'tags': [],
        'classification': [],
        'locked_contexts': [],
        'scope_locked': False,
    }
    source_conversation_doc = {
        'id': source_conversation_id,
        'title': 'Hidden Source Conversation',
        'context': ['Aviation'],
        'tags': ['image'],
        'classification': [],
        'locked_contexts': [],
        'scope_locked': False,
        'strict': False,
        'summary': 'Source summary',
    }
    user_message_doc = {
        'id': 'shared-user-message-001',
        'conversation_id': conversation_id,
        'role': 'user',
        'message_kind': MESSAGE_KIND_AI_REQUEST,
        'content': 'plane landing',
        'timestamp': '2026-04-16T12:00:00Z',
        'metadata': {
            'sender': current_user,
            'last_message_preview': 'plane landing',
        },
    }
    source_message_doc = {
        'id': 'source-image-message-001',
        'conversation_id': source_conversation_id,
        'role': 'image',
        'content': 'data:image/png;base64,AAAA',
        'timestamp': '2026-04-16T12:00:01Z',
        'model_deployment_name': 'gpt-image-1.5',
        'metadata': {
            'is_user_upload': False,
        },
        'agent_display_name': 'AI',
    }
    mirrored_message_doc = {
        'id': 'shared-image-message-001',
        'conversation_id': conversation_id,
        'role': 'assistant',
        'message_kind': MESSAGE_KIND_ASSISTANT,
        'content': '[Generated image]',
        'timestamp': '2026-04-16T12:00:02Z',
        'model_deployment_name': 'gpt-image-1.5',
        'metadata': {
            'sender': {
                'user_id': 'assistant',
                'display_name': 'AI',
                'email': '',
            },
            'source_role': 'image',
            'source_message_id': source_message_doc['id'],
            'source_conversation_id': source_conversation_id,
            'last_message_preview': '[Generated image]',
        },
        'agent_display_name': 'AI',
    }
    final_conversation_doc = copy.deepcopy(collaboration_conversation_doc)
    final_conversation_doc['message_count'] = 2
    final_conversation_doc['last_message_preview'] = '[Generated image]'

    fake_message_container = FakeItemContainer([user_message_doc])
    fake_conversation_container = FakeConversationContainer([source_conversation_doc])
    fake_event_registry = FakeEventRegistry()

    original_values = {
        'login_required': route_backend_collaboration.login_required,
        'user_required': route_backend_collaboration.user_required,
        'swagger_route': route_backend_collaboration.swagger_route,
        'get_auth_security': route_backend_collaboration.get_auth_security,
        '_require_collaboration_feature_enabled': route_backend_collaboration._require_collaboration_feature_enabled,
        '_get_current_collaboration_user': route_backend_collaboration._get_current_collaboration_user,
        'get_collaboration_conversation': route_backend_collaboration.get_collaboration_conversation,
        'assert_user_can_participate_in_collaboration_conversation': route_backend_collaboration.assert_user_can_participate_in_collaboration_conversation,
        'ensure_collaboration_source_conversation': route_backend_collaboration.ensure_collaboration_source_conversation,
        'resolve_collaboration_mentions': route_backend_collaboration.resolve_collaboration_mentions,
        'persist_collaboration_message': route_backend_collaboration.persist_collaboration_message,
        'create_collaboration_message_notifications': route_backend_collaboration.create_collaboration_message_notifications,
        'serialize_collaboration_conversation': route_backend_collaboration.serialize_collaboration_conversation,
        'get_user_state_or_none': route_backend_collaboration.get_user_state_or_none,
        '_read_source_message_doc': route_backend_collaboration._read_source_message_doc,
        'sync_collaboration_conversation_metadata_from_source': route_backend_collaboration.sync_collaboration_conversation_metadata_from_source,
        'mirror_source_message_to_collaboration': route_backend_collaboration.mirror_source_message_to_collaboration,
        'COLLABORATION_EVENT_REGISTRY': route_backend_collaboration.COLLABORATION_EVENT_REGISTRY,
        'cosmos_collaboration_messages_container': route_backend_collaboration.cosmos_collaboration_messages_container,
        'cosmos_conversations_container': route_backend_collaboration.cosmos_conversations_container,
    }

    route_backend_collaboration.login_required = lambda func: func
    route_backend_collaboration.user_required = lambda func: func
    route_backend_collaboration.swagger_route = lambda **kwargs: (lambda func: func)
    route_backend_collaboration.get_auth_security = lambda: {}
    route_backend_collaboration._require_collaboration_feature_enabled = lambda: None
    route_backend_collaboration._get_current_collaboration_user = lambda: copy.deepcopy(current_user)
    route_backend_collaboration.get_collaboration_conversation = lambda requested_conversation_id: copy.deepcopy(collaboration_conversation_doc)
    route_backend_collaboration.assert_user_can_participate_in_collaboration_conversation = lambda user_id, conversation_doc: {'user_id': user_id, 'conversation_id': conversation_doc['id']}
    route_backend_collaboration.ensure_collaboration_source_conversation = (
        lambda conversation_doc, current_user_doc: (
            copy.deepcopy(source_conversation_doc),
            copy.deepcopy(conversation_doc),
        )
    )
    route_backend_collaboration.resolve_collaboration_mentions = lambda conversation_doc, raw_mentions: []
    route_backend_collaboration.persist_collaboration_message = (
        lambda conversation_doc, current_user_doc, message_content, reply_to_message_id=None, mentioned_participants=None, message_kind=None, extra_metadata=None: (
            copy.deepcopy(user_message_doc),
            copy.deepcopy(conversation_doc),
        )
    )
    route_backend_collaboration.create_collaboration_message_notifications = lambda conversation_doc, message_doc: []
    route_backend_collaboration.serialize_collaboration_conversation = (
        lambda conversation_doc, current_user_id=None, user_state=None: {
            'id': conversation_doc['id'],
            'title': conversation_doc.get('title'),
            'chat_type': conversation_doc.get('chat_type'),
            'classification': list(conversation_doc.get('classification', []) or []),
            'context': list(conversation_doc.get('context', []) or []),
            'scope_locked': bool(conversation_doc.get('scope_locked', False)),
            'locked_contexts': list(conversation_doc.get('locked_contexts', []) or []),
        }
    )
    route_backend_collaboration.get_user_state_or_none = lambda user_id, requested_conversation_id: None
    route_backend_collaboration._read_source_message_doc = lambda requested_source_conversation_id, requested_message_id: copy.deepcopy(source_message_doc)
    route_backend_collaboration.sync_collaboration_conversation_metadata_from_source = (
        lambda collaboration_doc, source_doc: (
            copy.deepcopy(source_doc),
            {
                **copy.deepcopy(collaboration_doc),
                'context': list(source_doc.get('context', []) or []),
                'tags': list(source_doc.get('tags', []) or []),
            },
        )
    )
    route_backend_collaboration.mirror_source_message_to_collaboration = (
        lambda collaboration_doc, source_message, default_sender_user, reply_to_message_id=None, extra_metadata=None: (
            copy.deepcopy(mirrored_message_doc),
            copy.deepcopy(final_conversation_doc),
            True,
        )
    )
    route_backend_collaboration.COLLABORATION_EVENT_REGISTRY = fake_event_registry
    route_backend_collaboration.cosmos_collaboration_messages_container = fake_message_container
    route_backend_collaboration.cosmos_conversations_container = fake_conversation_container

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.secret_key = 'test-secret'

    @app.route('/api/chat/stream', methods=['POST'])
    def chat_stream_api():
        payload = {
            'done': True,
            'message_id': source_message_doc['id'],
            'user_message_id': 'source-user-message-001',
            'image_url': '/api/image/source-image-message-001',
            'full_content': '',
        }
        return Response([f'data: {json.dumps(payload)}\n\n'], mimetype='text/event-stream')

    route_backend_collaboration.register_route_backend_collaboration(app)

    def restore():
        for attribute_name, original_value in original_values.items():
            setattr(route_backend_collaboration, attribute_name, original_value)

    return app, fake_message_container, fake_event_registry, restore


def test_collaboration_stream_image_completion_uses_reference_payload():
    """Verify the shared image stream completes with a collaboration image URL."""
    app, fake_message_container, fake_event_registry, restore = build_stream_fix_test_app()

    try:
        with app.test_client() as client:
            response = client.post(
                '/api/collaboration/conversations/shared-image-conversation-001/stream',
                json={'content': 'plane landing'},
                buffered=True,
            )

        assert response.status_code == 200

        response_body = response.get_data(as_text=True)
        assert 'Failed to stream collaborative AI response' not in response_body
        assert '/api/collaboration/conversations/shared-image-conversation-001/images/shared-image-message-001' in response_body
        assert 'cannot access local variable' not in response_body
        assert '"error":' not in response_body

        saved_user_message = fake_message_container.read_item('shared-user-message-001')
        assert saved_user_message['metadata']['source_message_id'] == 'source-user-message-001'
        assert fake_event_registry.events, 'Expected collaboration events to be published during streaming.'
    finally:
        restore()


if __name__ == '__main__':
    test_collaboration_stream_image_completion_uses_reference_payload()
    print('Collaboration stream image completion checks passed.')