# test_group_collaboration_source_storage_fix.py
#!/usr/bin/env python3
"""
Functional regression for group conversation source storage.
Version: 0.261.106
Implemented in: 0.261.024
Ported to the React branch in: 0.261.106
Related issue: microsoft/simplechat#1472

Exercise production conversion and route helpers against isolated Cosmos stores.
Group context must not imply group-container storage or weaken authorization.
No application config, Azure clients, or deployed services are initialized.
The route is shared by v1 and v2; React interaction coverage lives in ui_tests.
"""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
import runpy
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional
import unittest

from flask import Blueprint, Flask, jsonify, request

from test_retention_policy_conversation_scope_coverage import (
    FakeContainer,
    FakeCosmosResourceNotFoundError,
    load_source_members,
)


APP_ROOT = Path(__file__).resolve().parents[1] / 'application' / 'single_app'
COLLABORATION_FILE = APP_ROOT / 'functions_collaboration.py'
ROUTE_FILE = APP_ROOT / 'route_backend_collaboration.py'
SOURCE_ID = 'source-conversation'
GROUP_ID = 'group-1'
OWNER = {
    'user_id': 'conversation-owner',
    'display_name': 'Conversation Owner',
    'email': 'owner@example.com',
}
INVITEE = {
    'user_id': 'group-member',
    'display_name': 'Group Member',
    'email': 'member@example.com',
}
SECOND_INVITEE = {
    'user_id': 'second-member',
    'display_name': 'Second Member',
    'email': 'second@example.com',
}

# These modules are pure helpers; loading by path avoids application bootstrap.
MODEL_HELPERS = runpy.run_path(str(APP_ROOT / 'collaboration_models.py'))
MASK_HELPERS = runpy.run_path(str(APP_ROOT / 'functions_message_masking.py'))
ARTIFACT_HELPERS = load_source_members(
    str(APP_ROOT / 'functions_message_artifacts.py'),
    {'is_assistant_artifact_role', 'filter_assistant_artifact_items'},
    assignment_names={'ASSISTANT_ARTIFACT_ROLE', 'ASSISTANT_ARTIFACT_CHUNK_ROLE'},
    namespace={'Any': Any, 'Dict': Dict, 'List': List, 'Optional': Optional},
)
COLLABORATION_FUNCTIONS = {
    '_copy_citation_tracking_conversation_fields',
    'is_collaboration_conversation',
    'is_personal_collaboration_conversation',
    'is_group_collaboration_conversation',
    'get_collaboration_visibility_mode',
    'is_invited_group_collaboration_conversation',
    'is_explicit_membership_collaboration',
    'get_collaboration_conversation',
    'get_collaboration_user_state',
    'get_collaboration_user_state_or_none',
    'get_personal_collaboration_participant',
    'get_personal_collaboration_role',
    '_build_group_member_lookup',
    '_normalize_group_conversation_participants',
    'ensure_collaboration_user_state_for_participant',
    '_bootstrap_collaboration_user_state_from_participant',
    'serialize_collaboration_conversation',
    'get_personal_collaboration_conversation_by_source_conversation',
    '_is_eligible_legacy_personal_conversation',
    '_copy_legacy_personal_messages_to_collaboration',
    'ensure_personal_collaboration_for_legacy_conversation',
    '_is_eligible_legacy_group_conversation',
    '_copy_legacy_group_messages_to_collaboration',
    'ensure_group_collaboration_for_legacy_conversation',
    'create_personal_collaboration_conversation_record',
    'create_group_collaboration_conversation_record',
    'assert_user_can_view_collaboration_conversation',
    'invite_personal_collaboration_participants',
    'sync_collaboration_conversation_metadata_from_source',
    'ensure_collaboration_source_conversation',
    '_archive_collaboration_item',
    '_delete_item_if_present',
    '_collaboration_retention_identity',
    '_read_collaboration_conversation_for_retention',
    '_cleanup_collaboration_thoughts',
    '_cleanup_linked_collaboration_source',
    '_delete_collaboration_conversation_records',
    'delete_collaboration_conversation_for_retention',
    'delete_personal_collaboration_conversation',
}


class StorageFailure(RuntimeError):
    """A service failure that must not be mistaken for a missing document."""


class TrackingContainer(FakeContainer):
    """Reuse the retention fake with partition checks and observable operations."""

    def __init__(self, partition_field):
        super().__init__()
        self.partition_field = partition_field
        self.calls = []
        self.failures = {}

    def _record(self, operation, **details):
        self.calls.append((operation, deepcopy(details)))
        if operation in self.failures:
            raise self.failures[operation]

    def read_item(self, item=None, partition_key=None):
        self._record('read', item=item, partition_key=partition_key)
        result = super().read_item(item=item, partition_key=partition_key)
        assert result[self.partition_field] == partition_key
        return result

    def query_items(self, query=None, parameters=None, partition_key=None,
                    enable_cross_partition_query=False):
        self._record('query', query=query, parameters=parameters, partition_key=partition_key)
        assert partition_key is not None or enable_cross_partition_query
        results = super().query_items(query=query, parameters=parameters)
        for parameter in parameters or []:
            field = parameter['name'].removeprefix('@')
            if field in {'conversation_kind', 'chat_type', 'source_conversation_id'}:
                results = [item for item in results if item.get(field) == parameter['value']]
        if partition_key is not None:
            results = [item for item in results if item[self.partition_field] == partition_key]
        if 'ORDER BY c.timestamp ASC' in (query or ''):
            results.sort(key=lambda item: item['timestamp'])
        return results

    def upsert_item(self, item):
        self._record('upsert', item=item)
        assert item.get(self.partition_field)
        return super().upsert_item(item)

    def delete_item(self, item=None, partition_key=None):
        self._record('delete', item=item, partition_key=partition_key)
        if item in self.items:
            assert self.items[item][self.partition_field] == partition_key
        return super().delete_item(item=item, partition_key=partition_key)


def source_fixture():
    primary_context = {
        'type': 'primary', 'scope': 'group', 'id': GROUP_ID, 'name': 'Operations',
    }
    return {
        'id': SOURCE_ID,
        'user_id': OWNER['user_id'],
        'chat_type': 'group-single-user',
        'title': 'Group agent investigation',
        'context': [primary_context, {'type': 'secondary', 'scope': 'Model', 'id': 'N/A'}],
        'tags': [{'category': 'document', 'document_id': 'document-1', 'value': 'Runbook'}],
        'classification': ['Internal'],
        'used_documents_tracking_version': 1,
        'legacy_used_documents': [{'document_id': 'older-document'}],
        'used_documents': [{'document_id': 'document-1', 'group_id': GROUP_ID}],
        'strict': True,
        'summary': 'Existing incident summary',
        'scope_locked': True,
        'locked_contexts': [deepcopy(primary_context)],
        'is_hidden': False,
        'last_updated': '2026-09-01T10:00:00+00:00',
    }


def history_fixture():
    messages = [
        {'id': 'user-message', 'role': 'user', 'content': 'Review the group runbook.'},
        {
            'id': 'assistant-message', 'role': 'assistant', 'content': 'Runbook response.',
            'agent_display_name': 'Group Agent', 'model_deployment_name': 'test-model',
            'hybrid_citations': [{'document_id': 'document-1', 'chunk_id': 'chunk-1'}],
            'citation_tracking_version': 1,
            'cited_hybrid_citations': [{'document_id': 'document-1', 'chunk_id': 'chunk-1'}],
        },
        {
            'id': 'uploaded-file', 'role': 'file', 'content': 'runbook contents',
            'filename': 'runbook.txt', 'extracted_text': 'runbook contents',
            'workspace_document_id': 'document-1',
            'metadata': {'is_user_upload': True, 'user_info': deepcopy(OWNER)},
        },
        {
            'id': 'uploaded-image', 'role': 'image', 'content': '/api/image/uploaded-image',
            'filename': 'diagram.png', 'vision_analysis': 'Architecture diagram',
            'metadata': {'is_user_upload': True, 'user_info': deepcopy(OWNER)},
        },
        {
            'id': 'generated-image', 'role': 'image', 'content': '/api/image/generated-image',
            'metadata': {'image_proposal': {
                'visualId': 'visual-1', 'source_assistant_message_id': 'assistant-message',
            }},
        },
        {'id': 'artifact', 'role': 'assistant_artifact', 'content': 'artifact payload'},
        {'id': 'artifact-chunk', 'role': 'assistant_artifact_chunk', 'content': 'chunk payload'},
    ]
    for index, message in enumerate(messages):
        message['conversation_id'] = SOURCE_ID
        message['timestamp'] = f'2026-09-01T10:0{index}:00+00:00'
    return list(reversed(messages))


class ConversionHarness:
    """Load actual helpers with in-memory storage and controlled external effects."""

    def __init__(self, storage='regular', history=True):
        self.storage = storage
        self.user = deepcopy(OWNER)
        self.feature_enabled = True
        self.group = {
            'id': GROUP_ID, 'name': 'Operations', 'status': 'active',
            'owner': {'id': 'group-owner', 'displayName': 'Group Owner'},
            'users': [
                {'userId': user['user_id'], 'displayName': user['display_name'], 'email': user['email']}
                for user in (OWNER, INVITEE, SECOND_INVITEE)
            ],
        }
        self.containers = {}
        for name in (
            'conversations', 'messages', 'group_conversations', 'group_messages',
            'collaboration_conversations', 'collaboration_messages',
            'collaboration_user_state', 'archived_conversations', 'archived_messages',
        ):
            partition_field = 'conversation_id' if name.endswith('messages') else 'id'
            if name == 'collaboration_user_state':
                partition_field = 'user_id'
            self.containers[name] = TrackingContainer(partition_field)
        prefix = 'group_' if storage == 'group' else ''
        self.source = self.containers[f'{prefix}conversations']
        self.messages = self.containers[f'{prefix}messages']
        self.other_source = self.containers['conversations' if prefix else 'group_conversations']
        self.other_messages = self.containers['messages' if prefix else 'group_messages']
        self.source.items[SOURCE_ID] = source_fixture()
        self.source.items['unrelated-source'] = {'id': 'unrelated-source', 'user_id': 'another-owner'}
        self.messages.items = {item['id']: item for item in history_fixture()} if history else {}
        self.messages.items['unrelated-message'] = {
            'id': 'unrelated-message', 'conversation_id': 'unrelated-source',
            'role': 'user', 'content': 'Unrelated', 'timestamp': '2026-09-01T00:00:00+00:00',
        }
        self.other_messages.items['wrong-store-message'] = {
            'id': 'wrong-store-message', 'conversation_id': SOURCE_ID,
            'role': 'user', 'content': 'Wrong store', 'timestamp': '2026-09-01T00:00:00+00:00',
        }
        self.invalidations = []
        self.events = []
        self.logs = []
        self.thought_cleanup = []
        self.blob_cleanup = []
        group_helpers = load_source_members(
            str(APP_ROOT / 'functions_group.py'),
            {'get_user_role_in_group', 'assert_group_role', 'check_group_status_allows_operation'},
            namespace={'Iterable': Iterable, 'find_group_by_id': self.find_group},
        )
        namespace = {
            **MODEL_HELPERS,
            **group_helpers,
            'deepcopy': deepcopy,
            'datetime': datetime,
            'timezone': timezone,
            'logging': logging,
            'CosmosResourceNotFoundError': FakeCosmosResourceNotFoundError,
            'filter_assistant_artifact_items': ARTIFACT_HELPERS['filter_assistant_artifact_items'],
            'invalidate_conversation_cache_for_item': self.invalidate,
            'log_event': lambda *args, **kwargs: self.logs.append((args, kwargs)),
            'log_conversation_archival': lambda **kwargs: None,
            'log_conversation_deletion': lambda **kwargs: None,
            'sync_chat_upload_workspace_document_sharing_for_collaboration': lambda item: None,
            '_delete_blob_backed_collaboration_files': lambda messages: self.blob_cleanup.extend(
                message['id'] for message in messages
            ),
            'archive_thoughts_for_conversation': lambda conversation_id, user_id, **kwargs: (
                self.thought_cleanup.append(('archive', conversation_id, user_id))
            ),
            'delete_thoughts_for_conversation': lambda conversation_id, user_id, **kwargs: (
                self.thought_cleanup.append(('delete', conversation_id, user_id))
            ),
        }
        namespace.update({
            f'cosmos_{name}_container': container
            for name, container in self.containers.items()
        })
        self.namespace = load_source_members(
            str(COLLABORATION_FILE),
            COLLABORATION_FUNCTIONS,
            assignment_names={'CITATION_TRACKING_CONVERSATION_FIELDS', 'PERSONAL_COLLABORATION_MANAGER_ROLES'},
            namespace=namespace,
        )

    def find_group(self, group_id):
        return deepcopy(self.group) if self.group and self.group['id'] == group_id else None

    def invalidate(self, item, reason):
        self.invalidations.append({
            'item': deepcopy(item),
            'reason': reason,
            'persisted': {
                name: deepcopy(container.items.get(item['id']))
                for name, container in self.containers.items()
                if item['id'] in container.items
            },
        })

    def snapshot(self):
        return {name: deepcopy(container.items) for name, container in self.containers.items()}

    def convert(self, participants=None):
        return self.namespace['ensure_group_collaboration_for_legacy_conversation'](
            SOURCE_ID, self.user,
            invited_participants=[INVITEE] if participants is None else participants,
        )

    def build_route_app(self):
        bp = Blueprint('collaboration_test', __name__)
        namespace = load_source_members(
            str(ROUTE_FILE),
            {
                'get_user_state_or_none', '_build_collaboration_event',
                '_normalize_participant_payload', '_require_collaboration_feature_enabled',
                '_get_current_collaboration_user', '_sync_collaboration_mask_metadata_to_source',
            },
            namespace={
                **self.namespace,
                'bp': bp,
                'jsonify': jsonify,
                'request': request,
                'get_settings': lambda: {'enable_collaborative_conversations': self.feature_enabled},
                'get_current_user_info': lambda: self.user,
                'swagger_route': lambda **kwargs: (lambda function: function),
                'get_auth_security': lambda: {},
                'login_required': lambda function: function,
                'user_required': lambda function: function,
                'copy_message_mask_metadata': MASK_HELPERS['copy_message_mask_metadata'],
                'COLLABORATION_EVENT_REGISTRY': SimpleNamespace(
                    publish=lambda conversation_id, event: self.events.append((conversation_id, deepcopy(event))),
                ),
            },
        )
        tree = ast.parse(ROUTE_FILE.read_text(encoding='utf-8'), filename=str(ROUTE_FILE))
        handler_names = {
            'convert_group_conversation_to_collaboration_api',
            'convert_personal_conversation_to_collaboration_api',
            'invite_collaboration_members_api',
        }
        handlers = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name in handler_names
        ]
        assert len(handlers) == len(handler_names)
        exec(compile(ast.Module(body=handlers, type_ignores=[]), str(ROUTE_FILE), 'exec'), namespace)
        self.route_namespace = namespace
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(bp)
        return app

    def post(self, payload, path=None):
        app = self.build_route_app()
        path = path or f'/api/collaboration/conversations/from-group/{SOURCE_ID}/members'
        with app.test_request_context(path, method='POST', json=payload):
            return app.full_dispatch_request()


class GroupCollaborationSourceStorageTests(unittest.TestCase):
    def test_v1_regular_store_invite_returns_created(self):
        harness = ConversionHarness()
        response = harness.post({'participants': [INVITEE]})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertTrue(response.get_json()['created'])

    def test_conversion_preserves_history_metadata_and_storage_links(self):
        for storage in ('regular', 'group'):
            with self.subTest(storage=storage):
                harness = ConversionHarness(storage)
                original = deepcopy(harness.source.items[SOURCE_ID])
                before_messages = deepcopy(harness.messages.items)
                other_before = deepcopy(harness.other_messages.items)
                conversation, invite_states, created, source = harness.convert()
                self.assertTrue(created)
                self.assertEqual(conversation['chat_type'], 'group_multi_user')
                self.assertEqual(conversation['scope']['group_id'], GROUP_ID)
                self.assertEqual(conversation['scope']['visibility_mode'], 'invited_members')
                self.assertEqual(conversation['pending_participant_ids'], [INVITEE['user_id']])
                self.assertEqual(invite_states[0]['membership_status'], 'pending')
                for field in (
                    'title', 'context', 'tags', 'classification', 'used_documents_tracking_version',
                    'legacy_used_documents', 'used_documents', 'strict', 'summary',
                    'scope_locked', 'locked_contexts',
                ):
                    self.assertEqual(conversation[field], original[field], field)
                link_field = 'legacy_source_conversation_id' if storage == 'group' else 'source_conversation_id'
                wrong_field = 'source_conversation_id' if storage == 'group' else 'legacy_source_conversation_id'
                self.assertEqual(conversation[link_field], SOURCE_ID)
                self.assertNotIn(wrong_field, conversation)
                if storage == 'group':
                    self.assertEqual(conversation['legacy_source_scope'], 'group')
                else:
                    self.assertNotIn('legacy_source_scope', conversation)
                self.assertTrue(source['is_hidden'])
                self.assertEqual(source['collaboration_conversation_id'], conversation['id'])
                self.assertEqual(source['last_updated'], source['converted_to_collaboration_at'])
                self.assertTrue(harness.source.items[SOURCE_ID]['is_hidden'])
                self.assertNotIn(SOURCE_ID, harness.other_source.items)
                self.assertEqual(harness.messages.items, before_messages)
                self.assertEqual(harness.other_messages.items, other_before)
                self.assertFalse(harness.other_messages.calls)

                copied = list(harness.containers['collaboration_messages'].items.values())
                by_source = {message['metadata']['source_message_id']: message for message in copied}
                self.assertEqual(list(by_source), [
                    'user-message', 'assistant-message', 'uploaded-file', 'uploaded-image', 'generated-image',
                ])
                self.assertEqual(conversation['message_count'], len(copied))
                self.assertEqual(conversation['last_message_at'], copied[-1]['timestamp'])
                self.assertEqual(conversation['updated_at'], copied[-1]['timestamp'])
                self.assertEqual(conversation['last_message_preview'], copied[-1]['metadata']['last_message_preview'])
                for source_id, message in by_source.items():
                    self.assertEqual(message['timestamp'], before_messages[source_id]['timestamp'])
                    self.assertEqual(message['conversation_id'], conversation['id'])
                    self.assertEqual(message['metadata']['source_conversation_id'], SOURCE_ID)
                    self.assertEqual(message['metadata']['source_thought_user_id'], OWNER['user_id'])
                    self.assertEqual(message['metadata'].get('source_conversation_scope') == 'group', storage == 'group')
                assistant = by_source['assistant-message']
                for field in ('hybrid_citations', 'cited_hybrid_citations', 'citation_tracking_version', 'model_deployment_name'):
                    self.assertEqual(assistant[field], before_messages['assistant-message'][field])
                self.assertEqual(assistant['metadata']['sender']['user_id'], 'assistant')
                self.assertEqual(by_source['uploaded-file']['filename'], 'runbook.txt')
                self.assertEqual(by_source['uploaded-file']['extracted_text'], 'runbook contents')
                self.assertEqual(by_source['uploaded-file']['workspace_document_id'], 'document-1')
                self.assertEqual(by_source['uploaded-image']['metadata']['sender']['user_id'], OWNER['user_id'])
                self.assertTrue(by_source['uploaded-image']['metadata']['is_user_upload'])
                proposal = by_source['generated-image']['metadata']['image_proposal']
                self.assertEqual(proposal['source_assistant_message_id'], assistant['id'])
                self.assertEqual(proposal['legacy_source_assistant_message_id'], 'assistant-message')

    def test_conversion_invalidates_final_persisted_records(self):
        for storage in ('regular', 'group'):
            with self.subTest(storage=storage):
                harness = ConversionHarness(storage)
                conversation, _, _, _ = harness.convert()
                source_events = [event for event in harness.invalidations if event['item']['id'] == SOURCE_ID]
                self.assertTrue(source_events)
                source_store = 'group_conversations' if storage == 'group' else 'conversations'
                self.assertTrue(source_events[-1]['persisted'][source_store]['is_hidden'])
                self.assertEqual(
                    source_events[-1]['persisted'][source_store]['collaboration_conversation_id'],
                    conversation['id'],
                )
                collaboration_events = [
                    event for event in harness.invalidations if event['item']['id'] == conversation['id']
                ]
                self.assertEqual(collaboration_events[-1]['item']['message_count'], 5)
                self.assertEqual(collaboration_events[-1]['persisted']['collaboration_conversations']['message_count'], 5)

    def test_supported_group_scopes_and_chat_allowed_statuses(self):
        for storage in ('regular', 'group'):
            for chat_type in ('group-single-user', 'group_single_user', 'group', ''):
                for status in ('active', 'locked', 'upload_disabled'):
                    with self.subTest(storage=storage, chat_type=chat_type, status=status):
                        harness = ConversionHarness(storage, history=False)
                        harness.source.items[SOURCE_ID]['chat_type'] = chat_type
                        harness.group['status'] = status
                        if chat_type:
                            harness.source.items[SOURCE_ID]['group_id'] = GROUP_ID
                            harness.source.items[SOURCE_ID]['context'] = []
                        conversation, _, created, _ = harness.convert()
                        self.assertTrue(created)
                        self.assertEqual(conversation['message_count'], 0)
                        self.assertEqual(conversation['scope']['group_id'], GROUP_ID)

    def test_current_group_roles_remain_allowed(self):
        for storage in ('regular', 'group'):
            for role in ('Owner', 'Admin', 'DocumentManager', 'User'):
                with self.subTest(storage=storage, role=role):
                    harness = ConversionHarness(storage, history=False)
                    if role == 'Owner':
                        harness.group['owner']['id'] = OWNER['user_id']
                    elif role == 'Admin':
                        harness.group['admins'] = [OWNER['user_id']]
                    elif role == 'DocumentManager':
                        harness.group['documentManagers'] = [OWNER['user_id']]
                    self.assertEqual(
                        harness.namespace['get_user_role_in_group'](harness.group, OWNER['user_id']),
                        role,
                    )
                    self.assertTrue(harness.convert()[2])

    def test_rejections_do_not_read_history_or_mutate_stores(self):
        cases = {
            'non_owner': PermissionError,
            'no_identity': PermissionError,
            'personal_scope': PermissionError,
            'public_scope': PermissionError,
            'already_collaborative': PermissionError,
            'missing_group_context': LookupError,
            'missing_group': LookupError,
            'not_group_member': PermissionError,
            'inactive_group': PermissionError,
            'non_group_invitee': ValueError,
        }
        for storage in ('regular', 'group'):
            for case, exception_type in cases.items():
                with self.subTest(storage=storage, case=case):
                    harness = ConversionHarness(storage)
                    source = harness.source.items[SOURCE_ID]
                    participants = [INVITEE]
                    if case == 'non_owner':
                        harness.user = {'user_id': 'another-user'}
                    elif case == 'no_identity':
                        harness.user = {}
                    elif case in ('personal_scope', 'public_scope'):
                        scope = case.removesuffix('_scope')
                        source['chat_type'] = 'personal_single_user' if scope == 'personal' else 'public'
                        source['context'] = [{'type': 'primary', 'scope': scope, 'id': 'other-scope'}]
                    elif case == 'already_collaborative':
                        source['conversation_kind'] = 'collaborative'
                    elif case == 'missing_group_context':
                        source['context'] = []
                    elif case == 'missing_group':
                        harness.group = None
                    elif case == 'not_group_member':
                        harness.group['users'] = [
                            user for user in harness.group['users'] if user['userId'] != OWNER['user_id']
                        ]
                    elif case == 'inactive_group':
                        harness.group['status'] = 'inactive'
                    elif case == 'non_group_invitee':
                        participants.append({'user_id': 'outsider'})
                    before = harness.snapshot()
                    with self.assertRaises(exception_type):
                        harness.convert(participants)
                    self.assertEqual(harness.snapshot(), before)
                    self.assertFalse(harness.messages.calls)
                    self.assertFalse(harness.other_messages.calls)
                    self.assertFalse(harness.invalidations)

    def test_legacy_store_precedence_never_falls_back_after_rejection(self):
        for rejected in (False, True):
            with self.subTest(rejected=rejected):
                harness = ConversionHarness('group')
                harness.other_source.items[SOURCE_ID] = source_fixture()
                if rejected:
                    harness.source.items[SOURCE_ID]['user_id'] = 'another-owner'
                before_regular = deepcopy(harness.other_source.items)
                if rejected:
                    with self.assertRaises(PermissionError):
                        harness.convert()
                else:
                    conversation, _, _, _ = harness.convert()
                    self.assertEqual(conversation['legacy_source_conversation_id'], SOURCE_ID)
                self.assertEqual(harness.other_source.items, before_regular)
                self.assertFalse(harness.other_source.calls)
                self.assertFalse(harness.other_messages.calls)

    def test_source_lookup_failures_are_not_missing_data(self):
        for store_name in ('group_conversations', 'conversations'):
            for failure in (StorageFailure('service unavailable'), PermissionError('storage forbidden')):
                with self.subTest(store=store_name, failure=type(failure).__name__):
                    harness = ConversionHarness()
                    harness.containers[store_name].failures['read'] = failure
                    before = harness.snapshot()
                    with self.assertRaises(type(failure)) as raised:
                        harness.convert()
                    self.assertIs(raised.exception, failure)
                    self.assertEqual(harness.snapshot(), before)
                    self.assertFalse(harness.messages.calls)
                    self.assertFalse(harness.other_messages.calls)
                    if store_name == 'group_conversations':
                        self.assertFalse(harness.source.calls)

    def test_missing_sources_return_the_existing_404(self):
        harness = ConversionHarness()
        del harness.source.items[SOURCE_ID]
        before = harness.snapshot()
        response = harness.post({'participants': [INVITEE]})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {'error': 'Conversation not found'})
        self.assertEqual(harness.snapshot(), before)
        self.assertFalse(harness.events)

    def test_repeated_invites_reuse_history_after_ai_source_synchronization(self):
        for storage in ('regular', 'group'):
            with self.subTest(storage=storage):
                harness = ConversionHarness(storage)
                first = harness.post({'participants': [INVITEE]})
                self.assertEqual(first.status_code, 201, first.get_json())
                payload = first.get_json()
                self.assertEqual(set(payload), {
                    'conversation', 'invited_participants', 'created', 'source_conversation_id',
                })
                self.assertEqual(payload['source_conversation_id'], SOURCE_ID)
                self.assertEqual(payload['invited_participants'], [{
                    **INVITEE, 'membership_status': 'pending',
                }])
                conversation_id = payload['conversation']['id']
                copied_before = deepcopy(harness.containers['collaboration_messages'].items)
                source_messages_before = deepcopy(harness.messages.items)
                self.assertEqual(
                    [event['event_type'] for _, event in harness.events],
                    ['collaboration.created', 'collaboration.member.invited'],
                )

                conversation = harness.namespace['get_collaboration_conversation'](conversation_id)
                backing, conversation = harness.namespace['ensure_collaboration_source_conversation'](
                    conversation, OWNER,
                )
                self.assertEqual(conversation['source_conversation_id'], backing['id'])
                self.assertEqual(backing['conversation_kind'], 'collaboration_source')
                self.assertEqual(backing['chat_type'], 'group')
                self.assertEqual(backing['collaboration_conversation_id'], conversation_id)
                self.assertTrue(backing['is_hidden'])
                if storage == 'regular':
                    self.assertEqual(backing['id'], SOURCE_ID)
                else:
                    self.assertNotEqual(backing['id'], SOURCE_ID)
                    self.assertEqual(conversation['legacy_source_conversation_id'], SOURCE_ID)
                self.assertEqual(harness.messages.items, source_messages_before)

                repeated = harness.post({'participant': INVITEE})
                self.assertEqual(repeated.status_code, 200, repeated.get_json())
                self.assertFalse(repeated.get_json()['created'])
                self.assertEqual(repeated.get_json()['invited_participants'], [])
                self.assertEqual(repeated.get_json()['conversation']['id'], conversation_id)
                self.assertEqual(len(harness.events), 2)

                added = harness.post({'participants': [SECOND_INVITEE]})
                self.assertEqual(added.status_code, 200, added.get_json())
                self.assertFalse(added.get_json()['created'])
                self.assertEqual(added.get_json()['conversation']['id'], conversation_id)
                self.assertEqual(added.get_json()['conversation']['pending_invite_count'], 2)
                self.assertEqual(added.get_json()['conversation']['message_count'], 5)
                self.assertEqual(harness.events[-1][1]['event_type'], 'collaboration.member.invited')
                self.assertEqual(len(harness.events), 3)
                self.assertEqual(harness.containers['collaboration_messages'].items, copied_before)
                self.assertEqual(len(harness.containers['collaboration_conversations'].items), 1)
                self.assertEqual(sum(operation == 'query' for operation, _ in harness.messages.calls), 1)
                self.assertFalse(harness.other_messages.calls)
                for event_conversation_id, event in harness.events:
                    self.assertEqual(event_conversation_id, conversation_id)
                    self.assertEqual(event['payload']['source_conversation_id'], SOURCE_ID)

    def test_regular_source_metadata_remains_synchronized(self):
        harness = ConversionHarness()
        conversation, _, _, _ = harness.convert()
        backing, conversation = harness.namespace['ensure_collaboration_source_conversation'](
            conversation, OWNER,
        )
        backing_again, _ = harness.namespace['ensure_collaboration_source_conversation'](
            conversation, INVITEE,
        )
        self.assertEqual(backing_again['id'], SOURCE_ID)
        self.assertEqual(backing_again['user_id'], OWNER['user_id'])
        self.assertEqual(len(harness.containers['conversations'].items), 2)
        backing['summary'] = 'Updated shared summary'
        backing['used_documents'].append({'document_id': 'new-document', 'group_id': GROUP_ID})
        backing['tags'].append({'category': 'document', 'document_id': 'new-document'})
        updated, changed = harness.namespace['sync_collaboration_conversation_metadata_from_source'](
            conversation, backing,
        )
        self.assertTrue(changed)
        for field in ('summary', 'used_documents', 'tags', 'context', 'scope_locked', 'locked_contexts'):
            self.assertEqual(updated[field], backing[field])
        self.assertEqual(
            harness.containers['collaboration_conversations'].items[conversation['id']]['summary'],
            backing['summary'],
        )

    def test_source_message_masking_uses_storage_not_group_context(self):
        for storage in ('regular', 'group'):
            with self.subTest(storage=storage):
                harness = ConversionHarness(storage)
                harness.convert()
                message = next(
                    deepcopy(item) for item in harness.containers['collaboration_messages'].items.values()
                    if item['metadata']['source_message_id'] == 'assistant-message'
                )
                harness.other_messages.items['assistant-message'] = deepcopy(
                    harness.messages.items['assistant-message']
                )
                other_before = deepcopy(harness.other_messages.items)
                message['metadata'].update({
                    'masked': True,
                    'masked_by_user_id': OWNER['user_id'],
                    'masked_timestamp': '2026-09-08T19:00:00+00:00',
                })
                harness.build_route_app()
                harness.route_namespace['_sync_collaboration_mask_metadata_to_source'](message)
                source_metadata = harness.messages.items['assistant-message']['metadata']
                self.assertTrue(source_metadata['masked'])
                self.assertEqual(source_metadata['masked_by_user_id'], OWNER['user_id'])
                self.assertEqual(harness.other_messages.items, other_before)
                self.assertFalse(harness.other_messages.calls)

    def test_manual_and_retention_cleanup_follow_converted_source_links(self):
        for storage in ('regular', 'group'):
            for mode in ('manual', 'retention', 'archive'):
                with self.subTest(storage=storage, mode=mode):
                    harness = ConversionHarness(storage)
                    conversation, _, _, _ = harness.convert()
                    backing, conversation = harness.namespace['ensure_collaboration_source_conversation'](
                        conversation, OWNER,
                    )
                    decoy = {
                        'id': SOURCE_ID, 'user_id': 'another-owner',
                        'collaboration_conversation_id': 'unrelated-collaboration',
                    }
                    harness.other_source.items[SOURCE_ID] = deepcopy(decoy)
                    other_messages_before = deepcopy(harness.other_messages.items)
                    copied_ids = set(harness.containers['collaboration_messages'].items)
                    source_message_ids = set(harness.messages.items) - {'unrelated-message'}
                    if mode == 'manual':
                        harness.namespace['delete_personal_collaboration_conversation'](
                            conversation['id'], OWNER['user_id'],
                        )
                    else:
                        result = harness.namespace['delete_collaboration_conversation_for_retention'](
                            conversation, workspace_type='group', archiving_enabled=mode == 'archive',
                        )
                        self.assertEqual(result['id'], conversation['id'])
                    self.assertNotIn(SOURCE_ID, harness.source.items)
                    self.assertEqual(set(harness.source.items), {'unrelated-source'})
                    self.assertEqual(set(harness.messages.items), {'unrelated-message'})
                    self.assertEqual(harness.other_source.items[SOURCE_ID], decoy)
                    self.assertEqual(harness.other_messages.items, other_messages_before)
                    for name in (
                        'collaboration_conversations', 'collaboration_messages', 'collaboration_user_state',
                    ):
                        self.assertFalse(harness.containers[name].items, name)
                    if backing['id'] != SOURCE_ID:
                        self.assertNotIn(backing['id'], harness.containers['conversations'].items)
                    if mode == 'archive':
                        self.assertEqual(
                            set(harness.containers['archived_conversations'].items),
                            {conversation['id'], SOURCE_ID, backing['id']},
                        )
                        self.assertEqual(
                            set(harness.containers['archived_messages'].items),
                            copied_ids | source_message_ids,
                        )
                        self.assertTrue(all(
                            item['archived_by_retention_policy']
                            for item in harness.containers['archived_messages'].items.values()
                        ))
                        self.assertFalse(harness.blob_cleanup)
                    else:
                        self.assertFalse(harness.containers['archived_conversations'].items)
                        self.assertFalse(harness.containers['archived_messages'].items)
                        self.assertEqual(set(harness.blob_cleanup), copied_ids | source_message_ids)
                    thought_operation = 'archive' if mode == 'archive' else 'delete'
                    self.assertIn((thought_operation, SOURCE_ID, OWNER['user_id']), harness.thought_cleanup)

    def test_linked_source_cleanup_keeps_owner_and_backlink_guards(self):
        for storage in ('regular', 'group'):
            for mismatch in ('owner', 'backlink'):
                with self.subTest(storage=storage, mismatch=mismatch):
                    harness = ConversionHarness(storage)
                    conversation, _, _, _ = harness.convert()
                    field = 'user_id' if mismatch == 'owner' else 'collaboration_conversation_id'
                    harness.source.items[SOURCE_ID][field] = 'unrelated'
                    before = harness.snapshot()
                    message_calls_before = deepcopy(harness.messages.calls)
                    result = harness.namespace['_cleanup_linked_collaboration_source'](
                        conversation,
                        'legacy_source_conversation_id' if storage == 'group' else 'source_conversation_id',
                        harness.source, harness.messages,
                        archiving_enabled=False, retention_deletion=False,
                        expected_user_id=OWNER['user_id'],
                    )
                    self.assertIsNone(result)
                    self.assertEqual(harness.snapshot(), before)
                    self.assertEqual(harness.messages.calls, message_calls_before)

    def test_existing_personal_conversion_is_unchanged(self):
        harness = ConversionHarness()
        harness.group = None
        source = harness.source.items[SOURCE_ID]
        source['chat_type'] = 'personal_single_user'
        source['context'] = [{'type': 'primary', 'scope': 'personal', 'id': OWNER['user_id']}]
        source['locked_contexts'] = deepcopy(source['context'])
        convert = harness.namespace['ensure_personal_collaboration_for_legacy_conversation']
        conversation, _, created, source = convert(
            SOURCE_ID, OWNER, invited_participants=[INVITEE],
        )
        self.assertTrue(created)
        self.assertEqual(conversation['chat_type'], 'personal_multi_user')
        self.assertEqual(conversation['source_conversation_id'], SOURCE_ID)
        self.assertNotIn('legacy_source_conversation_id', conversation)
        self.assertTrue(source['is_hidden'])
        copied_before = deepcopy(harness.containers['collaboration_messages'].items)
        backing, conversation = harness.namespace['ensure_collaboration_source_conversation'](
            conversation, OWNER,
        )
        self.assertEqual(backing['id'], SOURCE_ID)
        repeated, states, created, _ = convert(
            SOURCE_ID, OWNER, invited_participants=[SECOND_INVITEE],
        )
        self.assertFalse(created)
        self.assertEqual(repeated['id'], conversation['id'])
        self.assertEqual(states[0]['user_id'], SECOND_INVITEE['user_id'])
        self.assertEqual(harness.containers['collaboration_messages'].items, copied_before)
        self.assertFalse(harness.other_source.calls)
        self.assertFalse(harness.other_messages.calls)

    def test_v1_route_preserves_rejection_statuses_without_mutation(self):
        cases = {
            'no_identity': 401, 'feature_disabled': 403, 'non_owner': 403,
            'personal_scope': 403, 'missing_group_context': 400,
            'not_group_member': 403, 'inactive_group': 403,
            'non_group_invitee': 400, 'missing_participants': 400,
        }
        for storage in ('regular', 'group'):
            for case, status in cases.items():
                with self.subTest(storage=storage, case=case):
                    harness = ConversionHarness(storage)
                    payload = {'participants': [INVITEE]}
                    if case == 'no_identity':
                        harness.user = None
                    elif case == 'feature_disabled':
                        harness.feature_enabled = False
                    elif case == 'non_owner':
                        harness.user = {'user_id': 'another-user'}
                    elif case == 'personal_scope':
                        harness.source.items[SOURCE_ID].update({'chat_type': 'personal_single_user', 'context': []})
                    elif case == 'missing_group_context':
                        harness.source.items[SOURCE_ID]['context'] = []
                    elif case == 'not_group_member':
                        harness.group['users'] = []
                    elif case == 'inactive_group':
                        harness.group['status'] = 'inactive'
                    elif case == 'non_group_invitee':
                        payload['participants'].append({'user_id': 'outsider'})
                    elif case == 'missing_participants':
                        payload = {}
                    before = harness.snapshot()
                    response = harness.post(payload)
                    self.assertEqual(response.status_code, status, response.get_json())
                    self.assertEqual(harness.snapshot(), before)
                    self.assertFalse(harness.messages.calls)
                    self.assertFalse(harness.events)

    def test_repeated_invites_recheck_current_group_restrictions(self):
        for storage in ('regular', 'group'):
            for case in ('membership_removed', 'inactive', 'non_group_invitee'):
                with self.subTest(storage=storage, case=case):
                    harness = ConversionHarness(storage)
                    harness.convert()
                    participants = [SECOND_INVITEE]
                    expected_status = 403
                    if case == 'membership_removed':
                        harness.group['users'] = [
                            user for user in harness.group['users'] if user['userId'] != OWNER['user_id']
                        ]
                    elif case == 'inactive':
                        harness.group['status'] = 'inactive'
                    else:
                        participants.append({'user_id': 'outsider'})
                        expected_status = 400
                    before = harness.snapshot()
                    message_calls_before = deepcopy(harness.messages.calls)
                    response = harness.post({'participants': participants})
                    self.assertEqual(response.status_code, expected_status, response.get_json())
                    self.assertEqual(harness.snapshot(), before)
                    self.assertEqual(harness.messages.calls, message_calls_before)
                    self.assertFalse(harness.events)

    def test_v1_storage_failures_surface_as_safe_500_responses(self):
        for storage in ('regular', 'group'):
            for operation in ('read', 'query', 'upsert'):
                with self.subTest(storage=storage, operation=operation):
                    harness = ConversionHarness(storage)
                    container = harness.messages if operation == 'query' else harness.source
                    container.failures[operation] = StorageFailure('internal service details')
                    response = harness.post({'participants': [INVITEE]})
                    self.assertEqual(response.status_code, 500, response.get_json())
                    self.assertEqual(response.get_json(), {
                        'error': 'Failed to convert group conversation to collaborative conversation',
                    })
                    self.assertFalse(harness.source.items[SOURCE_ID]['is_hidden'])
                    self.assertNotIn('collaboration_conversation_id', harness.source.items[SOURCE_ID])
                    self.assertFalse(harness.other_messages.calls)
                    self.assertFalse(harness.events)
                    self.assertTrue(harness.logs)


if __name__ == '__main__':
    unittest.main()
