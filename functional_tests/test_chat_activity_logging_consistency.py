# test_chat_activity_logging_consistency.py
#!/usr/bin/env python3
"""
Functional test for chat activity logging consistency.
Version: 0.241.102
Implemented in: 0.241.102

This test ensures standard chat activity writes to activity_logs and that
document-action plus multi-user collaboration message saves reuse the same
shared chat activity path.
"""

from copy import deepcopy
import importlib
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / 'application' / 'single_app'

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class FakeCreateItemContainer:
    def __init__(self):
        self.items = []

    def create_item(self, body):
        self.items.append(deepcopy(body))
        return deepcopy(body)


class FakeUpsertContainer:
    def __init__(self):
        self.items = []

    def upsert_item(self, item):
        self.items.append(deepcopy(item))
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


def test_log_chat_activity_persists_activity_record():
    """The shared logger should create an activity_logs record and emit telemetry."""
    print('🔍 Testing shared chat activity persistence...')

    activity_module = importlib.import_module('functions_activity_logging')
    fake_activity_container = FakeCreateItemContainer()
    logged_events = []

    with PatchSet(
        activity_module,
        {
            'cosmos_activity_logs_container': fake_activity_container,
            'log_event': lambda message, extra=None, level=None, **kwargs: logged_events.append({
                'message': message,
                'extra': deepcopy(extra or {}),
                'level': level,
            }),
            'debug_print': lambda *args, **kwargs: None,
        },
    ):
        activity_module.log_chat_activity(
            user_id='user-123',
            conversation_id='conversation-123',
            message_type='user_message',
            message_length=42,
            has_document_search=True,
            has_image_generation=False,
            document_scope='personal',
            chat_context='personal_single_user',
            workspace_type='personal',
            additional_context={'conversation_source': 'standard_chat'},
        )

    assert len(fake_activity_container.items) == 1, 'Expected a chat_activity record in activity_logs.'
    activity_record = fake_activity_container.items[0]
    assert activity_record['activity_type'] == 'chat_activity'
    assert activity_record['conversation_id'] == 'conversation-123'
    assert activity_record['message_type'] == 'user_message'
    assert activity_record['workspace_type'] == 'personal'
    assert activity_record['additional_context']['conversation_source'] == 'standard_chat'
    assert logged_events, 'Expected chat activity telemetry to be emitted.'
    assert logged_events[0]['extra']['activity_type'] == 'chat_activity'
    assert logged_events[0]['extra']['activity_log_persisted'] is True

    print('✅ Shared chat activity persistence verified.')


def test_collaboration_message_persistence_reuses_chat_activity_logger():
    """Collaborative user messages should emit the same shared chat activity event."""
    print('🔍 Testing collaboration chat activity wiring...')

    collaboration_module = importlib.import_module('functions_collaboration')
    fake_messages_container = FakeUpsertContainer()
    fake_conversations_container = FakeUpsertContainer()
    logged_activity = []
    conversation_doc = {
        'id': 'collab-conversation-123',
        'conversation_kind': 'collaboration',
        'chat_type': 'personal_multi_user',
        'message_count': 0,
    }
    message_doc = {
        'id': 'collab-message-123',
        'conversation_id': 'collab-conversation-123',
        'role': 'user',
        'message_kind': 'human_message',
        'content': 'Hello from a shared conversation.',
        'timestamp': '2026-05-04T12:00:00Z',
        'metadata': {
            'sender': {
                'user_id': 'user-123',
                'display_name': 'Test User',
                'email': 'user@example.com',
            },
            'last_message_preview': 'Hello from a shared conversation.',
        },
    }

    with PatchSet(
        collaboration_module,
        {
            'cosmos_collaboration_messages_container': fake_messages_container,
            'cosmos_collaboration_conversations_container': fake_conversations_container,
            'refresh_personal_participant_indexes': lambda conversation: None,
            'log_chat_activity': lambda **kwargs: logged_activity.append(deepcopy(kwargs)),
        },
    ):
        saved_message_doc, updated_conversation_doc = collaboration_module._save_collaboration_message_doc(
            deepcopy(conversation_doc),
            deepcopy(message_doc),
        )

    assert saved_message_doc['id'] == 'collab-message-123'
    assert updated_conversation_doc['message_count'] == 1
    assert len(fake_messages_container.items) == 1
    assert len(fake_conversations_container.items) == 1
    assert logged_activity, 'Expected collaboration message persistence to log shared chat activity.'
    assert logged_activity[0]['conversation_id'] == 'collab-conversation-123'
    assert logged_activity[0]['workspace_type'] == 'personal'
    assert logged_activity[0]['chat_context'] == 'personal_multi_user'
    assert logged_activity[0]['additional_context']['conversation_source'] == 'collaboration_chat'
    assert logged_activity[0]['additional_context']['message_kind'] == 'human_message'

    print('✅ Collaboration chat activity wiring verified.')


def test_document_action_route_uses_shared_chat_activity_logger():
    """Document-action chat requests should log through the shared chat activity path after persisting the user message."""
    print('🔍 Testing document-action chat activity wiring...')

    route_content = (APP_ROOT / 'route_backend_chats.py').read_text(encoding='utf-8')
    post_save_segment = route_content.split('cosmos_messages_container.upsert_item(user_message_doc)', 1)[1]

    assert 'document_action_activity_context' in post_save_segment, (
        'Expected the document-action request path to build shared chat activity context after saving the user message.'
    )
    assert "'conversation_source': 'document_action_chat'" in post_save_segment, (
        'Expected document-action chat requests to tag the shared activity record with their request source.'
    )
    assert 'log_chat_activity(' in post_save_segment, (
        'Expected document-action chat requests to call the shared chat activity logger after persisting the user message.'
    )

    print('✅ Document-action chat activity wiring verified.')


def test_control_center_activity_logs_surface_chat_activity():
    """Control Center should expose chat activity rows in filters, formatting, and search fields."""
    print('🔍 Testing Control Center chat activity surfacing...')

    template_content = (APP_ROOT / 'templates' / 'control_center.html').read_text(encoding='utf-8')
    javascript_content = (APP_ROOT / 'static' / 'js' / 'control-center.js').read_text(encoding='utf-8')
    route_content = (APP_ROOT / 'route_backend_control_center.py').read_text(encoding='utf-8')

    assert '<option value="chat_activity">Chat Activity</option>' in template_content, (
        'Expected the Activity Logs filter dropdown to expose chat_activity records.'
    )
    assert "'chat_activity': 'Chat Activity'" in javascript_content, (
        'Expected the Control Center formatter to present chat_activity with a friendly label.'
    )
    assert "case 'chat_activity':" in javascript_content, (
        'Expected the Control Center details formatter to render chat_activity rows explicitly.'
    )
    assert "additional_context.get('conversation_source', '')" in route_content, (
        'Expected the Activity Logs search path to include chat activity source fields.'
    )
    assert "additional_context.get('document_action_type', '')" in route_content, (
        'Expected the Activity Logs search path to include document-action chat labels.'
    )

    print('✅ Control Center chat activity surfacing verified.')


if __name__ == '__main__':
    test_log_chat_activity_persists_activity_record()
    test_collaboration_message_persistence_reuses_chat_activity_logger()
    test_document_action_route_uses_shared_chat_activity_logger()
    test_control_center_activity_logs_surface_chat_activity()
    print('✅ Chat activity logging consistency verified.')