#!/usr/bin/env python3
# test_conversation_fork.py
"""
Functional test for personal conversation forking.
Version: 0.250.101
Implemented in: 0.250.074

This test ensures persisted personal conversation history is copied through an
assistant boundary with independent identifiers, deterministic ordering,
workspace-context authorization, concurrency protection, failed-write cleanup,
and stable conflict responses when structured logging is invoked.
"""

import ast
import copy
import importlib
import logging
import os
import sys
import types

import pytest
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import Blueprint, Flask, jsonify, request


sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        '..',
        'application',
        'single_app',
    ),
)

TEST_OPERATIONS_MODULE = None
ROUTE_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..',
    'application',
    'single_app',
    'route_backend_conversations.py',
)


def _stub_module(module_name, attributes):
    """Build a lightweight dependency module for isolated import."""
    module = types.ModuleType(module_name)
    for attribute_name, attribute_value in attributes.items():
        setattr(module, attribute_name, attribute_value)
    return module


def load_operations_module_for_test():
    """Import the operation module without loading the full application config."""
    global TEST_OPERATIONS_MODULE
    if TEST_OPERATIONS_MODULE is not None:
        return TEST_OPERATIONS_MODULE

    no_op = lambda *args, **kwargs: None
    dependency_stubs = {
        'collaboration_models': _stub_module(
            'collaboration_models',
            {'normalize_collaboration_user': lambda value: value},
        ),
        'config': _stub_module(
            'config',
            {
                'CLIENTS': {},
                'TABULAR_EXTENSIONS': set(),
                'cosmos_activity_logs_container': None,
                'cosmos_conversations_container': None,
                'cosmos_groups_container': None,
                'cosmos_messages_container': None,
                'storage_account_personal_chat_container_name': '',
            },
        ),
        'functions_activity_logging': _stub_module(
            'functions_activity_logging',
            {
                'log_chat_activity': no_op,
                'log_conversation_creation': no_op,
                'log_document_upload': no_op,
                'log_group_status_change': no_op,
                'log_workflow_creation': no_op,
            },
        ),
        'functions_appinsights': _stub_module(
            'functions_appinsights',
            {'log_event': no_op},
        ),
        'functions_authentication': _stub_module(
            'functions_authentication',
            {
                'get_current_user_info': lambda: None,
                'get_graph_endpoint': lambda: '',
                'get_valid_access_token': lambda: '',
            },
        ),
        'functions_collaboration': _stub_module(
            'functions_collaboration',
            {
                'assert_user_can_participate_in_collaboration_conversation': no_op,
                'create_collaboration_message_notifications': no_op,
                'create_group_collaboration_conversation_record': no_op,
                'create_personal_collaboration_conversation_record': no_op,
                'get_collaboration_conversation': no_op,
                'invite_personal_collaboration_participants': no_op,
                'is_group_collaboration_conversation': lambda value: False,
                'persist_collaboration_message': no_op,
            },
        ),
        'functions_documents': _stub_module(
            'functions_documents',
            {
                'allowed_file': no_op,
                'create_document': no_op,
                'process_document_upload_background': no_op,
                'update_document': no_op,
            },
        ),
        'functions_chat_bootstrap_cache': _stub_module(
            'functions_chat_bootstrap_cache',
            {'bump_chat_bootstrap_global_cache_version': no_op},
        ),
        'functions_group': _stub_module(
            'functions_group',
            {
                'assert_group_role': no_op,
                'check_group_status_allows_operation': no_op,
                'create_group': no_op,
                'find_group_by_id': no_op,
                'get_user_role_in_group': no_op,
                'require_active_group': no_op,
            },
        ),
        'functions_notifications': _stub_module(
            'functions_notifications',
            {'create_notification': no_op},
        ),
        'functions_personal_workflows': _stub_module(
            'functions_personal_workflows',
            {'save_personal_workflow': no_op},
        ),
        'functions_public_workspaces': _stub_module(
            'functions_public_workspaces',
            {
                'check_public_workspace_status_allows_operation': no_op,
                'find_public_workspace_by_id': no_op,
            },
        ),
        'functions_settings': _stub_module(
            'functions_settings',
            {
                'get_settings': lambda: {},
                'is_user_workflows_enabled_for_user': lambda user_id: False,
            },
        ),
        'utils_cache': _stub_module(
            'utils_cache',
            {
                'invalidate_group_search_cache': no_op,
                'invalidate_personal_search_cache': no_op,
            },
        ),
    }
    original_modules = {
        module_name: sys.modules.get(module_name)
        for module_name in dependency_stubs
    }
    original_operations_module = sys.modules.pop('functions_simplechat_operations', None)
    try:
        sys.modules.update(dependency_stubs)
        TEST_OPERATIONS_MODULE = importlib.import_module('functions_simplechat_operations')
    finally:
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module
        sys.modules.pop('functions_simplechat_operations', None)
        if original_operations_module is not None:
            sys.modules['functions_simplechat_operations'] = original_operations_module

    return TEST_OPERATIONS_MODULE


def load_route_registrar_for_test(route_globals):
    """Compile the production route registrar with isolated dependencies."""
    with open(ROUTE_MODULE_PATH, 'r', encoding='utf-8-sig') as file_handle:
        route_tree = ast.parse(file_handle.read(), filename=ROUTE_MODULE_PATH)

    registrar_node = next(
        node
        for node in route_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == 'register_route_backend_conversations'
    )
    isolated_tree = ast.Module(body=[registrar_node], type_ignores=[])
    ast.fix_missing_locations(isolated_tree)
    namespace = dict(route_globals)
    exec(compile(isolated_tree, ROUTE_MODULE_PATH, 'exec'), namespace)
    return namespace['register_route_backend_conversations']


class FakeConversationContainer:
    """In-memory personal conversation storage."""

    def __init__(self, source_conversation):
        self.items = {source_conversation['id']: copy.deepcopy(source_conversation)}
        self.upserts = []
        self.deleted_ids = []

    def read_item(self, item, partition_key):
        if item not in self.items:
            raise CosmosResourceNotFoundError(message='Conversation not found')
        return copy.deepcopy(self.items[item])

    def upsert_item(self, item):
        stored_item = copy.deepcopy(item)
        self.items[stored_item['id']] = stored_item
        self.upserts.append(stored_item)
        return copy.deepcopy(stored_item)

    def delete_item(self, item, partition_key):
        if item not in self.items:
            raise CosmosResourceNotFoundError(message='Conversation not found')
        self.deleted_ids.append(item)
        del self.items[item]


class FakeMessageContainer:
    """In-memory partitioned message storage with failure and race controls."""

    def __init__(self, messages, fail_on_fork_upsert=None, mutate_on_second_query=False):
        self.items = [copy.deepcopy(message) for message in messages]
        self.fail_on_fork_upsert = fail_on_fork_upsert
        self.mutate_on_second_query = mutate_on_second_query
        self.query_count = 0
        self.fork_upsert_count = 0
        self.deleted_ids = []

    def query_items(self, query, parameters=None, partition_key=None):
        self.query_count += 1
        if self.mutate_on_second_query and self.query_count == 2:
            self.items.append({
                'id': 'source-conversation_late_user',
                'conversation_id': 'source-conversation',
                'role': 'user',
                'content': 'Concurrent update',
                'timestamp': '2026-07-30T12:00:05Z',
                'metadata': {},
            })
        return [
            copy.deepcopy(message)
            for message in self.items
            if message.get('conversation_id') == partition_key
        ]

    def read_item(self, item, partition_key):
        for message in self.items:
            if message.get('id') == item and message.get('conversation_id') == partition_key:
                return copy.deepcopy(message)
        raise CosmosResourceNotFoundError(message='Message not found')

    def upsert_item(self, item):
        if item.get('conversation_id') != 'source-conversation':
            self.fork_upsert_count += 1
            if self.fail_on_fork_upsert == self.fork_upsert_count:
                raise RuntimeError('Simulated message write failure')
        stored_item = copy.deepcopy(item)
        self.items.append(stored_item)
        return copy.deepcopy(stored_item)

    def delete_item(self, item, partition_key):
        self.deleted_ids.append(item)
        self.items = [
            message
            for message in self.items
            if not (
                message.get('id') == item
                and message.get('conversation_id') == partition_key
            )
        ]


class FakeBlobProperties:
    """Minimal blob property payload."""

    def __init__(self, metadata=None, content_settings=None):
        self.metadata = copy.deepcopy(metadata or {})
        self.content_settings = content_settings


class FakeBlobDownload:
    """Minimal blob download payload."""

    def __init__(self, content):
        self.content = content

    def readall(self):
        return self.content


class FakeBlobClient:
    """In-memory blob client."""

    def __init__(self, service, container, blob_path):
        self.service = service
        self.target = (container, blob_path)

    def get_blob_properties(self):
        if self.target not in self.service.blobs:
            raise CosmosResourceNotFoundError(message='Blob not found')
        blob_record = self.service.blobs[self.target]
        return FakeBlobProperties(
            metadata=blob_record.get('metadata'),
            content_settings=blob_record.get('content_settings'),
        )

    def download_blob(self):
        if self.target not in self.service.blobs:
            raise CosmosResourceNotFoundError(message='Blob not found')
        return FakeBlobDownload(self.service.blobs[self.target]['content'])

    def upload_blob(self, content, overwrite=False, metadata=None, content_settings=None):
        if self.target in self.service.blobs and not overwrite:
            raise RuntimeError('Blob already exists')
        self.service.blobs[self.target] = {
            'content': content,
            'metadata': copy.deepcopy(metadata or {}),
            'content_settings': content_settings,
        }

    def delete_blob(self):
        self.service.deleted_targets.append(self.target)
        self.service.blobs.pop(self.target, None)


class FakeBlobService:
    """In-memory blob service for fork copy and cleanup checks."""

    def __init__(self):
        self.blobs = {
            (
                'personal-chat',
                'owner/source-conversation/generated/message-003-generated-file/report.docx',
            ): {
                'content': b'generated report bytes',
                'metadata': {
                    'conversation_id': 'source-conversation',
                    'generated_artifact': 'true',
                },
                'content_settings': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            },
        }
        self.deleted_targets = []

    def get_blob_client(self, container, blob):
        return FakeBlobClient(self, container, blob)


class PatchSet:
    """Temporarily replace module attributes."""

    def __init__(self, module, replacements):
        self.module = module
        self.replacements = replacements
        self.originals = {}

    def __enter__(self):
        for attribute_name, replacement in self.replacements.items():
            self.originals[attribute_name] = getattr(self.module, attribute_name)
            setattr(self.module, attribute_name, replacement)
        return self

    def __exit__(self, exc_type, exc, traceback):
        for attribute_name, original in self.originals.items():
            setattr(self.module, attribute_name, original)
        return False


def build_source_conversation(user_id='owner-user', chat_type='personal_single_user'):
    """Build a stable source conversation fixture."""
    return {
        'id': 'source-conversation',
        'user_id': user_id,
        'title': 'Quarterly planning',
        'chat_type': chat_type,
        'context': [{'type': 'primary', 'scope': 'personal', 'id': 'doc-1'}],
        'tags': ['planning'],
        'strict': True,
        'last_updated': '2026-07-30T12:00:04Z',
        '_etag': 'conversation-etag-1',
    }


def build_source_messages():
    """Build active, inactive, artifact, and post-boundary records."""
    return [
        {
            'id': 'message-001-user',
            'conversation_id': 'source-conversation',
            'role': 'user',
            'content': 'Start',
            'timestamp': '2026-07-30T12:00:00Z',
            'metadata': {
                'chat_context': {'conversation_id': 'source-conversation'},
                'thread_info': {'thread_id': 'thread-1', 'active_thread': True},
            },
            '_etag': 'message-etag-1',
        },
        {
            'id': 'message-002-inactive',
            'conversation_id': 'source-conversation',
            'role': 'assistant',
            'content': 'Old attempt',
            'timestamp': '2026-07-30T12:00:01Z',
            'metadata': {
                'thread_info': {'thread_id': 'thread-old', 'active_thread': False},
            },
            '_etag': 'message-etag-2',
        },
        {
            'id': 'message-003-target',
            'conversation_id': 'source-conversation',
            'role': 'assistant',
            'content': 'Fork here',
            'timestamp': '2026-07-30T12:00:02Z',
            'reply_to_message_id': 'message-001-user',
            'metadata': {
                'chat_context': {'conversation_id': 'source-conversation'},
                'thread_info': {
                    'thread_id': 'thread-1',
                    'previous_thread_id': 'thread-0',
                    'active_thread': True,
                },
                'agent_citations': [{'artifact_id': 'message-003-target_artifact_1'}],
                'generated_analysis_artifacts': [{
                    'artifact_message_id': 'message-003-generated-file',
                    'conversation_id': 'source-conversation',
                    'file_name': 'report.docx',
                }],
            },
            '_etag': 'message-etag-3',
        },
        {
            'id': 'message-003-target_artifact_1',
            'conversation_id': 'source-conversation',
            'role': 'assistant_artifact',
            'content': 'Citation payload',
            'parent_message_id': 'message-003-target',
            'timestamp': '2026-07-30T12:00:02Z',
            'metadata': {
                'is_generated_chat_artifact': True,
                'root_message_id': 'message-003-target',
            },
            '_etag': 'message-etag-4',
        },
        {
            'id': 'message-003-target_artifact_1_chunk_1',
            'conversation_id': 'source-conversation',
            'role': 'assistant_artifact_chunk',
            'content': 'Citation payload continuation',
            'parent_message_id': 'message-003-target_artifact_1',
            'timestamp': '2026-07-30T12:00:02Z',
            'metadata': {
                'is_generated_chat_artifact': True,
                'root_message_id': 'message-003-target',
                'parent_message_id': 'message-003-target_artifact_1',
            },
            '_etag': 'message-etag-5',
        },
        {
            'id': 'message-003-generated-file',
            'conversation_id': 'source-conversation',
            'role': 'file',
            'filename': 'report.docx',
            'file_content_source': 'blob',
            'blob_container': 'personal-chat',
            'blob_path': 'owner/source-conversation/generated/message-003-generated-file/report.docx',
            'timestamp': '2026-07-30T12:00:02Z',
            'metadata': {
                'is_generated_chat_artifact': True,
                'generated_artifact_capability': 'analysis',
                'thread_info': {'thread_id': 'thread-file', 'active_thread': False},
            },
            '_etag': 'message-etag-5-file',
        },
        {
            'id': 'message-004-later-user',
            'conversation_id': 'source-conversation',
            'role': 'user',
            'content': 'Later question',
            'timestamp': '2026-07-30T12:00:03Z',
            'metadata': {'thread_info': {'thread_id': 'thread-2', 'active_thread': True}},
            '_etag': 'message-etag-6',
        },
        {
            'id': 'message-005-later-assistant',
            'conversation_id': 'source-conversation',
            'role': 'assistant',
            'content': 'Later response',
            'timestamp': '2026-07-30T12:00:04Z',
            'metadata': {'thread_info': {'thread_id': 'thread-2', 'active_thread': True}},
            '_etag': 'message-etag-7',
        },
    ]


def run_fork(
    source_conversation=None,
    source_messages=None,
    user_id='owner-user',
    selected_message_id='message-003-target',
    access_replacements=None,
    **message_container_options,
):
    """Execute the fork helper with isolated fake storage."""
    operations_module = load_operations_module_for_test()
    conversation = copy.deepcopy(source_conversation or build_source_conversation())
    source_snapshot = copy.deepcopy(conversation)
    messages = copy.deepcopy(source_messages or build_source_messages())
    message_snapshot = copy.deepcopy(messages)
    conversation_container = FakeConversationContainer(conversation)
    message_container = FakeMessageContainer(messages, **message_container_options)
    blob_service = FakeBlobService()

    replacements = {
        'cosmos_conversations_container': conversation_container,
        'cosmos_messages_container': message_container,
        'CLIENTS': {'storage_account_office_docs_client': blob_service},
        'log_conversation_creation': lambda **kwargs: None,
        'log_event': lambda *args, **kwargs: None,
    }
    replacements.update(access_replacements or {})

    with PatchSet(operations_module, replacements):
        result = operations_module.fork_personal_conversation_for_user(
            source_conversation=conversation,
            selected_message_id=selected_message_id,
            user_id=user_id,
        )

    return {
        'module': operations_module,
        'result': result,
        'conversation_container': conversation_container,
        'message_container': message_container,
        'blob_service': blob_service,
        'source_snapshot': source_snapshot,
        'message_snapshot': message_snapshot,
    }


def test_fork_copies_inclusive_active_history_with_independent_ids():
    """Copy through the target once while excluding inactive and later messages."""
    test_state = run_fork()
    fork_conversation = test_state['result']['conversation']
    fork_id = fork_conversation['id']
    fork_documents = [
        message
        for message in test_state['message_container'].items
        if message.get('conversation_id') == fork_id
    ]
    visible_documents = [
        message
        for message in fork_documents
        if not str(message.get('role') or '').startswith('assistant_artifact')
        and not (message.get('metadata') or {}).get('is_generated_chat_artifact')
    ]

    assert fork_conversation['title'] == 'Fork of Quarterly planning'
    assert fork_conversation['id'] != 'source-conversation'
    assert fork_conversation['context'] == [{'type': 'primary', 'scope': 'personal', 'id': 'doc-1'}]
    assert fork_conversation['forked_from']['message_id'] == 'message-003-target'
    assert test_state['result']['message_count'] == 2
    assert [message['content'] for message in visible_documents] == ['Start', 'Fork here']
    assert len(fork_documents) == 5
    assert len({message['id'] for message in fork_documents}) == 5
    assert not {message['id'] for message in fork_documents}.intersection(
        {message['id'] for message in test_state['message_snapshot']}
    )
    assert [message['fork_sequence'] for message in fork_documents] == [1, 2, 3, 4, 5]

    fork_user = next(message for message in fork_documents if message.get('content') == 'Start')
    fork_target = next(message for message in fork_documents if message.get('content') == 'Fork here')
    fork_artifact = next(message for message in fork_documents if message.get('content') == 'Citation payload')
    fork_artifact_chunk = next(
        message
        for message in fork_documents
        if message.get('content') == 'Citation payload continuation'
    )
    fork_generated_file = next(
        message
        for message in fork_documents
        if message.get('filename') == 'report.docx'
    )
    assert fork_target['reply_to_message_id'] == fork_user['id']
    assert fork_target['metadata']['chat_context']['conversation_id'] == fork_id
    assert fork_target['metadata']['thread_info']['thread_id'] != 'thread-1'
    assert fork_artifact['parent_message_id'] == fork_target['id']
    assert fork_artifact['metadata']['root_message_id'] == fork_target['id']
    assert fork_artifact_chunk['parent_message_id'] == fork_artifact['id']
    assert fork_target['metadata']['agent_citations'][0]['artifact_id'] == fork_artifact['id']
    assert (
        fork_target['metadata']['generated_analysis_artifacts'][0]['artifact_message_id']
        == fork_generated_file['id']
    )
    assert fork_generated_file['blob_path'] != (
        'owner/source-conversation/generated/message-003-generated-file/report.docx'
    )
    fork_blob_target = ('personal-chat', fork_generated_file['blob_path'])
    assert test_state['blob_service'].blobs[fork_blob_target]['content'] == b'generated report bytes'
    assert (
        test_state['blob_service'].blobs[fork_blob_target]['metadata']['conversation_id']
        == fork_id
    )

    assert test_state['conversation_container'].items['source-conversation'] == test_state['source_snapshot']
    current_source_messages = [
        message
        for message in test_state['message_container'].items
        if message.get('conversation_id') == 'source-conversation'
    ]
    assert current_source_messages == test_state['message_snapshot']
    fork_target['content'] = 'Changed fork only'
    assert next(
        message
        for message in current_source_messages
        if message['id'] == 'message-003-target'
    )['content'] == 'Fork here'


@pytest.mark.parametrize(
    ('selected_message_id', 'expected_exception'),
    [
        ('missing-message', LookupError),
        ('message-001-user', ValueError),
        ('message-002-inactive', LookupError),
    ],
)
def test_fork_rejects_invalid_message_boundaries(selected_message_id, expected_exception):
    """Reject missing, non-assistant, and inactive fork points."""
    with pytest.raises(expected_exception):
        run_fork(selected_message_id=selected_message_id)


def test_fork_rejects_foreign_and_unsupported_conversations():
    """Require source ownership and reject multi-user conversation kinds."""
    with pytest.raises(PermissionError):
        run_fork(user_id='different-user')

    group_conversation = build_source_conversation(chat_type='group_multi_user')
    group_conversation['context'] = [{'type': 'primary', 'scope': 'group', 'id': 'group-1'}]
    operations_module = load_operations_module_for_test()
    with pytest.raises(operations_module.ConversationForkConflictError):
        run_fork(source_conversation=group_conversation)


@pytest.mark.parametrize(
    ('chat_type', 'context', 'expected_chat_type', 'access_replacements'),
    [
        (
            'group-single-user',
            {'type': 'primary', 'scope': 'group', 'id': 'group-1'},
            'group-single-user',
            {
                'find_group_by_id': lambda group_id: {'id': group_id, 'status': 'active'},
                'check_group_status_allows_operation': lambda group, operation: (True, ''),
                'assert_group_role': lambda *args, **kwargs: 'User',
            },
        ),
        (
            'public',
            {'type': 'primary', 'scope': 'public', 'id': 'public-1'},
            'public',
            {
                'find_public_workspace_by_id': lambda workspace_id: {
                    'id': workspace_id,
                    'status': 'active',
                },
                'check_public_workspace_status_allows_operation': (
                    lambda workspace, operation: (True, '')
                ),
            },
        ),
    ],
)
def test_fork_revalidates_and_preserves_workspace_context(
    chat_type,
    context,
    expected_chat_type,
    access_replacements,
):
    """Fork supported workspace-grounded conversations after access checks."""
    conversation = build_source_conversation(chat_type=chat_type)
    conversation['context'] = [context]

    test_state = run_fork(
        source_conversation=conversation,
        access_replacements=access_replacements,
    )

    assert test_state['result']['conversation']['chat_type'] == expected_chat_type
    assert test_state['result']['conversation']['context'] == [context]


@pytest.mark.parametrize(
    ('conversation', 'access_replacements', 'error_match'),
    [
        (
            {
                **build_source_conversation(chat_type='group-single-user'),
                'context': [{'type': 'primary', 'scope': 'group', 'id': 'missing-group'}],
            },
            {'find_group_by_id': lambda group_id: None},
            'group is no longer available',
        ),
        (
            {
                **build_source_conversation(chat_type='group-single-user'),
                'context': [{'type': 'primary', 'scope': 'group', 'id': 'inactive-group'}],
            },
            {
                'find_group_by_id': lambda group_id: {'id': group_id, 'status': 'inactive'},
                'check_group_status_allows_operation': lambda group, operation: (False, 'inactive'),
            },
            'group no longer allows chat',
        ),
        (
            {
                **build_source_conversation(chat_type='group-single-user'),
                'context': [{'type': 'primary', 'scope': 'group', 'id': 'former-group'}],
            },
            {
                'find_group_by_id': lambda group_id: {'id': group_id, 'status': 'active'},
                'check_group_status_allows_operation': lambda group, operation: (True, ''),
                'assert_group_role': (
                    lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError('removed'))
                ),
            },
            'no longer available to this user',
        ),
        (
            {
                **build_source_conversation(chat_type='public'),
                'context': [{'type': 'primary', 'scope': 'public', 'id': 'missing-public'}],
            },
            {'find_public_workspace_by_id': lambda workspace_id: None},
            'public workspace is no longer available',
        ),
    ],
)
def test_fork_rejects_unavailable_workspace_context(
    conversation,
    access_replacements,
    error_match,
):
    """Reject stale workspace context before copying any fork records."""
    operations_module = load_operations_module_for_test()
    with pytest.raises(operations_module.ConversationForkConflictError, match=error_match):
        run_fork(
            source_conversation=conversation,
            access_replacements=access_replacements,
        )


def test_fork_rejects_concurrent_source_changes():
    """Abort when the authoritative source changes during the copy."""
    operations_module = load_operations_module_for_test()
    with pytest.raises(operations_module.ConversationForkConflictError):
        run_fork(mutate_on_second_query=True)


def test_fork_route_preserves_conflict_response_when_logging_metadata():
    """Return 409 after logging a fork eligibility conflict with canonical metadata."""
    operations_module = load_operations_module_for_test()
    logged_events = []

    def identity_decorator(function):
        return function

    def swagger_route(**kwargs):
        return identity_decorator

    def capture_log_event(
        message,
        extra=None,
        level=logging.INFO,
        exceptionTraceback=None,
    ):
        logged_events.append({
            'message': message,
            'extra': extra,
            'level': level,
            'exceptionTraceback': exceptionTraceback,
        })

    def raise_conflict(**kwargs):
        raise operations_module.ConversationForkConflictError(
            'Only personal conversations can be forked'
        )

    register_routes = load_route_registrar_for_test({
        'Blueprint': Blueprint,
        'ConversationForkConflictError': operations_module.ConversationForkConflictError,
        '_authorize_personal_conversation_read': lambda user_id, conversation_id: build_source_conversation(),
        'bump_conversation_cache_version': lambda *args, **kwargs: None,
        'fork_personal_conversation_for_user': raise_conflict,
        'get_auth_security': lambda: [],
        'get_current_user_id': lambda: 'owner-user',
        'jsonify': jsonify,
        'log_event': capture_log_event,
        'logging': logging,
        'login_required': identity_decorator,
        'request': request,
        'swagger_route': swagger_route,
        'user_required': identity_decorator,
    })
    app = Flask(__name__)
    app.config['TESTING'] = True
    blueprint = Blueprint('conversation_fork_contract', __name__)
    register_routes(blueprint)
    app.register_blueprint(blueprint)

    response = app.test_client().post(
        '/api/conversations/source-conversation/fork',
        json={'message_id': 'message-003-target'},
    )

    assert response.status_code == 409
    assert response.get_json() == {'error': 'Conversation fork conflict'}
    assert logged_events == [{
        'message': (
            '[ConversationFork] Conflict while creating conversation fork: '
            'Only personal conversations can be forked'
        ),
        'extra': {
            'source_conversation_id': 'source-conversation',
            'selected_message_id': 'message-003-target',
            'user_id': 'owner-user',
        },
        'level': logging.WARNING,
        'exceptionTraceback': None,
    }]


def test_fork_rejects_missing_generated_artifact_records():
    """Reject a fork that would preserve a dangling generated-file reference."""
    operations_module = load_operations_module_for_test()
    messages = [
        message
        for message in build_source_messages()
        if message.get('id') != 'message-003-generated-file'
    ]
    with pytest.raises(
        operations_module.ConversationForkConflictError,
        match='generated assistant artifact',
    ):
        run_fork(source_messages=messages)


def test_fork_cleans_up_partial_message_writes():
    """Delete destination records when a copy write fails."""
    operations_module = load_operations_module_for_test()
    conversation = build_source_conversation()
    messages = build_source_messages()
    conversation_container = FakeConversationContainer(conversation)
    message_container = FakeMessageContainer(messages, fail_on_fork_upsert=2)
    blob_service = FakeBlobService()

    with PatchSet(
        operations_module,
        {
            'cosmos_conversations_container': conversation_container,
            'cosmos_messages_container': message_container,
            'CLIENTS': {'storage_account_office_docs_client': blob_service},
            'log_conversation_creation': lambda **kwargs: None,
            'log_event': lambda *args, **kwargs: None,
        },
    ):
        with pytest.raises(RuntimeError, match='Simulated message write failure'):
            operations_module.fork_personal_conversation_for_user(
                source_conversation=conversation,
                selected_message_id='message-003-target',
                user_id='owner-user',
            )

    assert message_container.deleted_ids
    assert not [
        message
        for message in message_container.items
        if message.get('conversation_id') != 'source-conversation'
    ]
    assert list(conversation_container.items) == ['source-conversation']
    assert len(blob_service.blobs) == 1
    assert blob_service.deleted_targets
