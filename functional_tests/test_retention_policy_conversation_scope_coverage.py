# test_retention_policy_conversation_scope_coverage.py
"""
Functional test for retention policy conversation scope coverage.
Version: 0.261.260
Implemented in: 0.250.103
Public workspace conversation retention added in: 0.261.260

This test verifies the retention ownership matrix, timestamp safeguards,
collaboration cleanup, archival behavior, race handling, new-group defaults, and
that chats grounded in a public workspace follow that workspace's policy while it
exists, return to their owner's policy once it is deleted, and never reach anyone
but their owner by title.
"""

import ast
import copy
from datetime import datetime, timedelta, timezone
import os
import sys
import types
import uuid


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
RETENTION_FILE = os.path.join(APP_ROOT, 'functions_retention_policy.py')
COLLABORATION_FILE = os.path.join(APP_ROOT, 'functions_collaboration.py')
GROUP_FILE = os.path.join(APP_ROOT, 'functions_group.py')


class FakeCosmosResourceNotFoundError(Exception):
    """Minimal Cosmos not-found exception for isolated behavior tests."""


class FakeContainer:
    """In-memory Cosmos container with the operations used by cleanup helpers."""

    def __init__(self, items=None):
        self.items = {
            item['id']: copy.deepcopy(item)
            for item in (items or [])
        }
        self.deleted = []

    def read_item(self, item=None, partition_key=None):
        if item not in self.items:
            raise FakeCosmosResourceNotFoundError(item)
        return copy.deepcopy(self.items[item])

    def query_items(
        self,
        query=None,
        parameters=None,
        partition_key=None,
        enable_cross_partition_query=False,
    ):
        parameter_map = {
            parameter['name']: parameter['value']
            for parameter in (parameters or [])
        }
        conversation_id = parameter_map.get('@conversation_id')
        results = list(self.items.values())
        if conversation_id:
            results = [
                item
                for item in results
                if item.get('conversation_id') == conversation_id
            ]
        return copy.deepcopy(results)

    def upsert_item(self, item):
        persisted_item = copy.deepcopy(item)
        persisted_item['_etag'] = str(uuid.uuid4())
        self.items[item['id']] = persisted_item
        return copy.deepcopy(persisted_item)

    def replace_item(
        self,
        item=None,
        body=None,
        etag=None,
        match_condition=None,
    ):
        if item not in self.items:
            raise FakeCosmosResourceNotFoundError(item)
        if etag and self.items[item].get('_etag') != etag:
            conflict = RuntimeError('etag conflict')
            conflict.status_code = 412
            raise conflict
        return self.upsert_item(body)

    def create_item(self, item):
        return self.upsert_item(item)

    def delete_item(
        self,
        item=None,
        partition_key=None,
        etag=None,
        match_condition=None,
    ):
        if item not in self.items:
            raise FakeCosmosResourceNotFoundError(item)
        if etag and self.items[item].get('_etag') != etag:
            conflict = RuntimeError('etag conflict')
            conflict.status_code = 412
            raise conflict
        self.deleted.append((item, partition_key))
        del self.items[item]


def load_source_members(path, function_names, assignment_names=None, namespace=None):
    """Load selected source members without importing the application's config."""
    with open(path, 'r', encoding='utf-8') as handle:
        tree = ast.parse(handle.read(), filename=path)

    selected_nodes = []
    assignment_names = set(assignment_names or [])
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in function_names:
                selected_nodes.append(node)
            continue
        if not isinstance(node, ast.Assign):
            continue
        assigned_names = {
            target.id
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        if assigned_names & assignment_names:
            selected_nodes.append(node)

    loaded_namespace = dict(namespace or {})
    loaded_namespace.setdefault('__builtins__', __builtins__)
    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(module, path, 'exec'), loaded_namespace)
    return loaded_namespace


def build_retention_namespace():
    container_names = (
        'cosmos_conversations_container',
        'cosmos_messages_container',
        'cosmos_group_conversations_container',
        'cosmos_group_messages_container',
        'cosmos_collaboration_conversations_container',
    )
    namespace = {
        'datetime': datetime,
        'timezone': timezone,
    }
    namespace.update({
        container_name: object()
        for container_name in container_names
    })
    return load_source_members(
        RETENTION_FILE,
        {
            'resolve_retention_value',
            '_parse_retention_timestamp',
            '_get_primary_group_id',
            '_is_group_single_user_conversation',
            '_get_primary_public_workspace_id',
            '_is_governed_by_public_workspace',
            '_is_converted_conversation_source',
            '_is_aged_conversation',
            '_build_group_scope_query',
            '_build_public_scope_query',
            '_build_conversation_retention_sources',
        },
        assignment_names={
            'GROUP_SINGLE_USER_CHAT_TYPES',
            'PERSONAL_MULTI_USER_CHAT_TYPE',
            'GROUP_MULTI_USER_CHAT_TYPE',
        },
        namespace=namespace,
    )


def test_policy_matrix_and_retention_values():
    """Verify each conversation shape maps to exactly one governing policy."""
    namespace = build_retention_namespace()
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    personal_sources = {
        source['name']: source
        for source in namespace['_build_conversation_retention_sources'](
            'personal',
            cutoff.isoformat(),
            user_id='user-1',
        )
    }
    group_sources = {
        source['name']: source
        for source in namespace['_build_conversation_retention_sources'](
            'group',
            cutoff.isoformat(),
            group_id='group-1',
        )
    }

    personal_single = {
        'id': 'personal-single',
        'user_id': 'user-1',
        'chat_type': 'personal_single_user',
        'last_updated': '2025-01-01T00:00:00Z',
    }
    group_single = {
        'id': 'group-single',
        'user_id': 'user-1',
        'chat_type': 'group-single-user',
        'last_updated': '2025-01-01T00:00:00Z',
        'context': [
            {'type': 'primary', 'scope': 'group', 'id': 'group-1'},
        ],
    }
    personal_multi = {
        'id': 'personal-multi',
        'chat_type': 'personal_multi_user',
        'created_by_user_id': 'user-1',
        'updated_at': '2025-01-01T00:00:00Z',
    }
    group_multi = {
        'id': 'group-multi',
        'chat_type': 'group_multi_user',
        'created_by_user_id': 'user-1',
        'updated_at': '2025-01-01T00:00:00Z',
        'scope': {'type': 'group', 'group_id': 'group-1'},
    }
    legacy_group = {
        'id': 'legacy-group',
        'group_id': 'group-1',
        'last_updated': '2025-01-01T00:00:00Z',
    }

    assert personal_sources['personal_single_user']['matches_scope'](personal_single)
    assert not personal_sources['personal_single_user']['matches_scope'](group_single)
    assert personal_sources['personal_multi_user']['matches_scope'](personal_multi)
    assert group_sources['group_single_user']['matches_scope'](group_single)
    assert group_sources['group_multi_user']['matches_scope'](group_multi)
    assert group_sources['legacy_group']['matches_scope'](legacy_group)

    # A chat grounded in a public workspace is a personal conversation that follows
    # the workspace's policy, the way a group-grounded chat follows its group's.
    public_sources = namespace['_build_conversation_retention_sources'](
        'public',
        cutoff.isoformat(),
        public_workspace_id='public-1',
    )
    assert [source['name'] for source in public_sources] == ['public_single_user']
    public_source = public_sources[0]
    assert public_source['container'] is namespace['cosmos_conversations_container']
    assert public_source['messages_container'] is namespace['cosmos_messages_container']
    assert "context_item.scope = 'public'" in public_source['query']
    assert {'name': '@scope_id', 'value': 'public-1'} in public_source['parameters']

    public_single = {
        'id': 'public-single',
        'user_id': 'user-1',
        'chat_type': 'public',
        'last_updated': '2025-01-01T00:00:00Z',
        'context': [
            {'type': 'primary', 'scope': 'public', 'id': 'public-1'},
            {'type': 'secondary', 'scope': 'personal', 'id': 'user-1'},
        ],
    }
    other_public = copy.deepcopy(public_single)
    other_public['context'][0]['id'] = 'public-2'
    assert public_source['matches_scope'](public_single)
    assert not public_source['matches_scope'](other_public)
    assert not public_source['matches_scope'](personal_single)
    assert not public_source['matches_scope'](group_single)
    assert not personal_sources['personal_single_user']['matches_scope'](public_single)
    assert not group_sources['group_single_user']['matches_scope'](public_single)

    converted_public = dict(public_single)
    converted_public['collaboration_conversation_id'] = 'personal-multi'
    assert not public_source['matches_scope'](converted_public)

    # A grounded chat with no workspace id stays under its owner's personal policy rather
    # than falling outside every policy.
    unresolved_public = {
        'id': 'unresolved-public',
        'user_id': 'user-1',
        'chat_type': 'public',
        'last_updated': '2025-01-01T00:00:00Z',
        'context': [{'type': 'primary', 'scope': 'public', 'id': ''}],
    }
    assert personal_sources['personal_single_user']['matches_scope'](unresolved_public)
    assert not public_source['matches_scope'](unresolved_public)

    # A grounded chat follows its workspace only while the workspace exists. Deleting the
    # workspace returns the chat to its owner's personal policy, since no public run will
    # ever reach it again. When the workspaces could not be listed, the personal run
    # leaves every grounded chat alone rather than risk the wrong policy.
    orphaned_public = copy.deepcopy(public_single)
    orphaned_public['id'] = 'orphaned-public'
    orphaned_public['context'][0]['id'] = 'public-deleted'

    def personal_single_source(existing_public_workspace_ids):
        return next(
            source
            for source in namespace['_build_conversation_retention_sources'](
                'personal',
                cutoff.isoformat(),
                user_id='user-1',
                existing_public_workspace_ids=existing_public_workspace_ids,
            )
            if source['name'] == 'personal_single_user'
        )

    listed = personal_single_source(frozenset({'public-1'}))
    assert not listed['matches_scope'](public_single)
    assert listed['matches_scope'](orphaned_public)
    assert listed['matches_scope'](personal_single)
    assert listed['matches_scope'](unresolved_public)
    assert not listed['matches_scope'](group_single)
    assert not public_source['matches_scope'](orphaned_public)

    every_workspace_deleted = personal_single_source(frozenset())
    assert every_workspace_deleted['matches_scope'](public_single)

    listing_failed = personal_single_source(None)
    assert not listing_failed['matches_scope'](public_single)
    assert not listing_failed['matches_scope'](orphaned_public)
    assert listing_failed['matches_scope'](personal_single)
    assert listing_failed['matches_scope'](unresolved_public)

    converted_personal = dict(personal_single)
    converted_personal['collaboration_conversation_id'] = 'personal-multi'
    converted_group = dict(legacy_group)
    converted_group['collaboration_conversation_id'] = 'group-multi'
    assert not personal_sources['personal_single_user']['matches_scope'](
        converted_personal
    )
    assert not group_sources['legacy_group']['matches_scope'](converted_group)

    is_aged = namespace['_is_aged_conversation']
    assert is_aged(personal_single, 'last_updated', cutoff)
    assert is_aged(personal_multi, 'updated_at', cutoff)
    assert not is_aged(
        {'last_updated': '2027-01-01T00:00:00Z'},
        'last_updated',
        cutoff,
    )
    for invalid_value in (None, '', 'not-a-date', 123):
        assert not is_aged(
            {'last_updated': invalid_value},
            'last_updated',
            cutoff,
        )

    resolve_value = namespace['resolve_retention_value']
    settings = {
        'default_retention_conversation_personal': '30',
        'default_retention_conversation_group': '90',
        'default_retention_conversation_public': '60',
    }
    assert resolve_value('default', 'personal', 'conversation', settings) == 30
    assert resolve_value(None, 'group', 'conversation', settings) == 90
    assert resolve_value('default', 'public', 'conversation', settings) == 60
    assert resolve_value('7', 'personal', 'conversation', settings) == 7
    assert resolve_value('none', 'group', 'conversation', settings) == 'none'
    return True


def build_collaboration_cleanup_namespace(
    collaboration_item,
    collaboration_messages,
    state_items,
    source_item,
    source_messages,
    source_kind='personal',
):
    """Create isolated cleanup dependencies and capture all side effects."""
    collaboration_container = FakeContainer([collaboration_item])
    collaboration_message_container = FakeContainer(collaboration_messages)
    state_container = FakeContainer(state_items)
    personal_source_container = FakeContainer(
        [source_item] if source_kind == 'personal' else []
    )
    personal_source_messages = FakeContainer(
        source_messages if source_kind == 'personal' else []
    )
    group_source_container = FakeContainer(
        [source_item] if source_kind == 'group' else []
    )
    group_source_messages = FakeContainer(
        source_messages if source_kind == 'group' else []
    )
    archived_conversations = FakeContainer()
    archived_messages = FakeContainer()
    effects = {
        'blob_message_ids': [],
        'archived_thoughts': [],
        'deleted_thoughts': [],
        'sharing_syncs': [],
        'cache_invalidations': [],
        'archival_logs': [],
        'deletion_logs': [],
        'cancelled_delivery_conversations': [],
    }

    namespace = {
        'deepcopy': copy.deepcopy,
        'datetime': datetime,
        'timezone': timezone,
        'CosmosResourceNotFoundError': FakeCosmosResourceNotFoundError,
        'PERSONAL_MULTI_USER_CHAT_TYPE': 'personal_multi_user',
        'GROUP_MULTI_USER_CHAT_TYPE': 'group_multi_user',
        'cosmos_collaboration_conversations_container': collaboration_container,
        'cosmos_collaboration_messages_container': collaboration_message_container,
        'cosmos_collaboration_user_state_container': state_container,
        'cosmos_conversations_container': personal_source_container,
        'cosmos_messages_container': personal_source_messages,
        'cosmos_group_conversations_container': group_source_container,
        'cosmos_group_messages_container': group_source_messages,
        'cosmos_archived_conversations_container': archived_conversations,
        'cosmos_archived_messages_container': archived_messages,
        'log_event': lambda *args, **kwargs: None,
        'cancel_m365_conversation_deliveries': effects['cancelled_delivery_conversations'].append,
        'log_conversation_archival': (
            lambda **kwargs: effects['archival_logs'].append(copy.deepcopy(kwargs))
        ),
        'log_conversation_deletion': (
            lambda **kwargs: effects['deletion_logs'].append(copy.deepcopy(kwargs))
        ),
        '_delete_blob_backed_collaboration_files': (
            lambda messages, conversation=None: effects['blob_message_ids'].extend(
                message.get('id')
                for message in messages
            )
        ),
        'archive_thoughts_for_conversation': (
            lambda conversation_id, user_id, **kwargs: effects['archived_thoughts'].append(
                (conversation_id, user_id)
            )
        ),
        'delete_thoughts_for_conversation': (
            lambda conversation_id, user_id, **kwargs: effects['deleted_thoughts'].append(
                (conversation_id, user_id)
            )
        ),
        'sync_chat_upload_workspace_document_sharing_for_collaboration': (
            lambda conversation: effects['sharing_syncs'].append(
                copy.deepcopy(conversation)
            )
        ),
        'invalidate_conversation_cache_for_item': (
            lambda item, reason: effects['cache_invalidations'].append(
                (item.get('id'), reason)
            )
        ),
        'is_personal_collaboration_conversation': (
            lambda item: item.get('chat_type') == 'personal_multi_user'
        ),
        'get_collaboration_conversation': (
            lambda conversation_id: collaboration_container.read_item(
                item=conversation_id,
                partition_key=conversation_id,
            )
        ),
    }
    loaded = load_source_members(
        COLLABORATION_FILE,
        {
            '_archive_collaboration_item',
            '_delete_item_if_present',
            '_collaboration_retention_identity',
            '_read_collaboration_conversation_for_retention',
            '_cleanup_collaboration_thoughts',
            '_read_linked_collaboration_source',
            '_cancel_collaboration_pending_deliveries',
            '_cleanup_linked_collaboration_source',
            '_delete_collaboration_conversation_records',
            'delete_collaboration_conversation_for_retention',
        },
        namespace=namespace,
    )
    loaded['effects'] = effects
    loaded['containers'] = {
        'collaboration': collaboration_container,
        'collaboration_messages': collaboration_message_container,
        'states': state_container,
        'personal_source': personal_source_container,
        'personal_source_messages': personal_source_messages,
        'group_source': group_source_container,
        'group_source_messages': group_source_messages,
        'archived_conversations': archived_conversations,
        'archived_messages': archived_messages,
    }
    return loaded


def test_destructive_collaboration_cleanup_and_race_handling():
    """Verify destructive retention removes collaboration and linked source data."""
    conversation_id = 'personal-multi-1'
    source_id = 'personal-source-1'
    collaboration_item = {
        'id': conversation_id,
        'title': 'Shared personal conversation',
        'chat_type': 'personal_multi_user',
        'created_by_user_id': 'owner-1',
        'updated_at': '2025-01-01T00:00:00Z',
        'source_conversation_id': source_id,
        'accepted_participant_ids': ['owner-1', 'member-1'],
        'participants': [
            {'user_id': 'owner-1'},
            {'user_id': 'member-1'},
        ],
        'owner_user_ids': ['owner-1'],
        'context': [],
        'tags': [],
    }
    source_item = {
        'id': source_id,
        'title': 'Hidden source',
        'user_id': 'owner-1',
        'collaboration_conversation_id': conversation_id,
    }
    namespace = build_collaboration_cleanup_namespace(
        collaboration_item,
        [{
            'id': 'collaboration-message-1',
            'conversation_id': conversation_id,
            'file_content_source': 'blob',
            'blob_container': 'generated',
            'blob_path': 'collaboration/file.txt',
        }],
        [
            {
                'id': 'owner-state',
                'conversation_id': conversation_id,
                'user_id': 'owner-1',
            },
            {
                'id': 'member-state',
                'conversation_id': conversation_id,
                'user_id': 'member-1',
            },
        ],
        source_item,
        [{
            'id': 'source-message-1',
            'conversation_id': source_id,
            'file_content_source': 'blob',
            'blob_container': 'generated',
            'blob_path': 'source/file.txt',
        }],
    )

    detail = namespace['delete_collaboration_conversation_for_retention'](
        collaboration_item,
        workspace_type='personal',
        archiving_enabled=False,
    )
    containers = namespace['containers']
    effects = namespace['effects']

    assert detail['id'] == conversation_id
    assert not containers['collaboration'].items
    assert not containers['collaboration_messages'].items
    assert not containers['states'].items
    assert not containers['personal_source'].items
    assert not containers['personal_source_messages'].items
    assert set(effects['blob_message_ids']) == {
        'collaboration-message-1',
        'source-message-1',
    }
    assert effects['sharing_syncs'][0]['accepted_participant_ids'] == []
    assert (conversation_id, 'owner-1') in effects['deleted_thoughts']
    assert (conversation_id, 'member-1') in effects['deleted_thoughts']
    assert (source_id, 'owner-1') in effects['deleted_thoughts']
    assert (source_id, 'member-1') in effects['deleted_thoughts']
    assert {item_id for item_id, _ in effects['cache_invalidations']} == {
        conversation_id,
        source_id,
    }
    assert effects['deletion_logs'][0]['is_bulk_operation'] is True

    race_detail = namespace['delete_collaboration_conversation_for_retention'](
        collaboration_item,
        workspace_type='personal',
        archiving_enabled=False,
    )
    assert race_detail['already_deleted'] is True
    return True


def test_collaboration_archival_covers_group_source_records():
    """Verify archival preserves collaboration and linked legacy group records."""
    conversation_id = 'group-multi-1'
    source_id = 'legacy-group-source-1'
    collaboration_item = {
        'id': conversation_id,
        'title': 'Shared group conversation',
        'chat_type': 'group_multi_user',
        'created_by_user_id': 'owner-1',
        'updated_at': '2025-01-01T00:00:00Z',
        'legacy_source_conversation_id': source_id,
        'participants': [{'user_id': 'owner-1'}],
        'scope': {'type': 'group', 'group_id': 'group-1'},
        'context': [],
        'tags': [],
    }
    source_item = {
        'id': source_id,
        'title': 'Legacy group source',
        'user_id': 'owner-1',
        'group_id': 'group-1',
        'collaboration_conversation_id': conversation_id,
    }
    namespace = build_collaboration_cleanup_namespace(
        collaboration_item,
        [{
            'id': 'group-collaboration-message',
            'conversation_id': conversation_id,
        }],
        [{
            'id': 'group-owner-state',
            'conversation_id': conversation_id,
            'user_id': 'owner-1',
        }],
        source_item,
        [{
            'id': 'legacy-group-message',
            'conversation_id': source_id,
        }],
        source_kind='group',
    )

    namespace['delete_collaboration_conversation_for_retention'](
        collaboration_item,
        workspace_type='group',
        archiving_enabled=True,
    )
    containers = namespace['containers']
    effects = namespace['effects']

    assert set(containers['archived_conversations'].items) == {
        conversation_id,
        source_id,
    }
    assert set(containers['archived_messages'].items) == {
        'group-collaboration-message',
        'legacy-group-message',
    }
    archived_conversation = containers['archived_conversations'].items[
        conversation_id
    ]
    assert archived_conversation['collaboration_user_states'][0]['id'] == (
        'group-owner-state'
    )
    assert not effects['blob_message_ids']
    assert effects['archival_logs'][0]['workspace_type'] == 'group'
    assert effects['archival_logs'][0]['group_id'] == 'group-1'
    assert (conversation_id, 'owner-1') in effects['archived_thoughts']
    assert (source_id, 'owner-1') in effects['archived_thoughts']
    return True


def test_collaboration_revalidation_and_cleanup_failure_safety():
    """Verify changed conversations are skipped and failed cleanup preserves records."""
    conversation_id = 'personal-multi-safety'
    collaboration_item = {
        'id': conversation_id,
        'title': 'Safety test',
        'chat_type': 'personal_multi_user',
        'created_by_user_id': 'owner-1',
        'updated_at': '2025-01-01T00:00:00Z',
        'participants': [{'user_id': 'owner-1'}],
        'accepted_participant_ids': ['owner-1'],
        'context': [],
        'tags': [],
    }
    namespace = build_collaboration_cleanup_namespace(
        collaboration_item,
        [{
            'id': 'safety-message',
            'conversation_id': conversation_id,
            'file_content_source': 'blob',
            'blob_container': 'generated',
            'blob_path': 'safety/file.txt',
        }],
        [{
            'id': 'safety-state',
            'conversation_id': conversation_id,
            'user_id': 'owner-1',
        }],
        {'id': 'unused-source', 'user_id': 'owner-1'},
        [],
    )
    containers = namespace['containers']

    changed_item = copy.deepcopy(
        containers['collaboration'].items[conversation_id]
    )
    changed_item['updated_at'] = '2026-01-02T00:00:00Z'
    containers['collaboration'].upsert_item(changed_item)
    skipped_detail = namespace['delete_collaboration_conversation_for_retention'](
        collaboration_item,
        workspace_type='personal',
        archiving_enabled=False,
    )
    assert skipped_detail is None
    assert conversation_id in containers['collaboration'].items
    assert 'safety-message' in containers['collaboration_messages'].items

    containers['collaboration'].upsert_item(collaboration_item)
    namespace['_delete_blob_backed_collaboration_files'] = (
        lambda messages, conversation=None: (_ for _ in ()).throw(RuntimeError('blob cleanup failed'))
    )
    try:
        namespace['delete_collaboration_conversation_for_retention'](
            collaboration_item,
            workspace_type='personal',
            archiving_enabled=False,
        )
        raise AssertionError('Expected blob cleanup failure')
    except RuntimeError as error:
        assert str(error) == 'blob cleanup failed'

    assert conversation_id in containers['collaboration'].items
    assert 'safety-message' in containers['collaboration_messages'].items
    assert 'safety-state' in containers['states'].items
    return True


def test_new_groups_persist_default_retention_values():
    """Verify create_group writes explicit default retention settings."""
    group_container = FakeContainer()
    cache_reasons = []
    namespace = load_source_members(
        GROUP_FILE,
        {'create_group'},
        namespace={
            'uuid': uuid,
            'datetime': datetime,
            'DEFAULT_WORKSPACE_HERO_COLOR': '#0d6efd',
            'functions_authentication': types.SimpleNamespace(
                get_current_user_info=lambda: {
                    'userId': 'owner-1',
                    'email': 'owner@example.com',
                    'displayName': 'Owner User',
                }
            ),
            'cosmos_groups_container': group_container,
            'bump_chat_bootstrap_global_cache_version': (
                lambda reason: cache_reasons.append(reason)
            ),
        },
    )

    created_group = namespace['create_group']('Retention Group', 'Test group')
    assert created_group['retention_policy'] == {
        'conversation_retention_days': 'default',
        'document_retention_days': 'default',
    }
    assert group_container.items[created_group['id']]['retention_policy'] == (
        created_group['retention_policy']
    )
    assert cache_reasons == ['group_created']
    return True


def test_public_grounded_deletion_logs_the_governing_workspace():
    """A public-grounded chat is archived, logged against its workspace, and owned."""
    conversation_item = {
        'id': 'public-chat-1',
        'user_id': 'owner-a',
        'title': 'Benefits questions',
        'chat_type': 'public',
        'last_updated': '2025-01-01T00:00:00Z',
        'context': [{'type': 'primary', 'scope': 'public', 'id': 'public-1'}],
        'tags': [],
    }
    message_item = {
        'id': 'public-chat-1-message-1',
        'conversation_id': 'public-chat-1',
        'role': 'user',
        'content': 'What is the leave policy?',
    }
    conversations = FakeContainer([conversation_item])
    messages = FakeContainer([message_item])
    archived_conversations = FakeContainer()
    archived_messages = FakeContainer()
    effects = {'archival_logs': [], 'deletion_logs': [], 'archived_thoughts': []}

    namespace = {
        'datetime': datetime,
        'timezone': timezone,
        'CosmosResourceNotFoundError': FakeCosmosResourceNotFoundError,
        'cosmos_conversations_container': conversations,
        'cosmos_messages_container': messages,
        'cosmos_group_conversations_container': FakeContainer(),
        'cosmos_group_messages_container': FakeContainer(),
        'cosmos_collaboration_conversations_container': FakeContainer(),
        'cosmos_archived_conversations_container': archived_conversations,
        'cosmos_archived_messages_container': archived_messages,
        'cancel_m365_conversation_deliveries': lambda conversation_id: None,
        'log_conversation_archival': (
            lambda **kwargs: effects['archival_logs'].append(copy.deepcopy(kwargs))
        ),
        'log_conversation_deletion': (
            lambda **kwargs: effects['deletion_logs'].append(copy.deepcopy(kwargs))
        ),
        'delete_blob_backed_chat_message_files': lambda *args, **kwargs: None,
        'archive_thoughts_for_conversation': (
            lambda conversation_id, user_id, **kwargs: effects['archived_thoughts'].append(
                (conversation_id, user_id)
            )
        ),
        'delete_thoughts_for_conversation': lambda *args, **kwargs: None,
        'invalidate_conversation_cache_for_item': lambda item, reason: None,
        'debug_print': lambda *args, **kwargs: None,
    }
    loaded = load_source_members(
        RETENTION_FILE,
        {
            '_parse_retention_timestamp',
            '_get_primary_group_id',
            '_is_group_single_user_conversation',
            '_get_primary_public_workspace_id',
            '_is_governed_by_public_workspace',
            '_is_converted_conversation_source',
            '_is_aged_conversation',
            '_build_group_scope_query',
            '_build_public_scope_query',
            '_build_conversation_retention_sources',
            '_delete_standard_conversation_for_retention',
        },
        assignment_names={
            'GROUP_SINGLE_USER_CHAT_TYPES',
            'PERSONAL_MULTI_USER_CHAT_TYPE',
            'GROUP_MULTI_USER_CHAT_TYPE',
        },
        namespace=namespace,
    )

    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    source = loaded['_build_conversation_retention_sources'](
        'public',
        cutoff.isoformat(),
        public_workspace_id='public-1',
    )[0]
    detail = loaded['_delete_standard_conversation_for_retention'](
        copy.deepcopy(conversation_item),
        source,
        'public',
        True,
        cutoff,
    )

    assert detail['id'] == 'public-chat-1'
    assert detail['user_id'] == 'owner-a'
    assert 'public-chat-1' not in conversations.items
    assert message_item['id'] not in messages.items
    archived = archived_conversations.items['public-chat-1']
    assert archived['retention_source'] == 'public_single_user'
    assert archived['archived_by_retention_policy'] is True
    assert message_item['id'] in archived_messages.items
    assert effects['archived_thoughts'] == [('public-chat-1', 'owner-a')]
    assert effects['archival_logs'][0]['public_workspace_id'] == 'public-1'
    assert effects['deletion_logs'][0]['public_workspace_id'] == 'public-1'
    assert effects['deletion_logs'][0]['workspace_type'] == 'public'
    return True


def test_public_workspace_run_keeps_chat_titles_with_their_owners():
    """The workspace hears a count; each owner hears only about their own chats."""
    calls = {
        'conversations': [],
        'documents': [],
        'workspace_notifications': [],
        'user_notifications': [],
    }

    def fake_delete_aged_conversations(**kwargs):
        calls['conversations'].append(kwargs)
        return {
            'count': 3,
            'details': [
                {'id': 'chat-1', 'title': 'Budget draft', 'user_id': 'owner-a'},
                {'id': 'chat-2', 'title': 'Hiring notes', 'user_id': 'owner-b'},
                {
                    'id': 'chat-3',
                    'title': 'Removed elsewhere',
                    'user_id': 'owner-a',
                    'already_deleted': True,
                },
            ],
        }

    def fake_delete_aged_documents(**kwargs):
        calls['documents'].append(kwargs)
        return {'count': 0, 'details': []}

    namespace = {
        'datetime': datetime,
        'timezone': timezone,
        'logging': __import__('logging'),
        'get_all_public_workspaces': lambda: [
            {
                'id': 'public-1',
                'name': 'HR Policies',
                'retention_policy': {
                    'conversation_retention_days': 'default',
                    'document_retention_days': 'none',
                },
            },
            {
                'id': 'public-2',
                'name': 'Kept forever',
                'retention_policy': {
                    'conversation_retention_days': 'none',
                    'document_retention_days': 'none',
                },
            },
        ],
        'get_settings': lambda: {'default_retention_conversation_public': '30'},
        'delete_aged_conversations': fake_delete_aged_conversations,
        'delete_aged_documents': fake_delete_aged_documents,
        'send_retention_notification': (
            lambda workspace_id, summary, workspace_type: calls[
                'workspace_notifications'
            ].append((workspace_id, copy.deepcopy(summary), workspace_type))
        ),
        'create_notification': (
            lambda **kwargs: calls['user_notifications'].append(copy.deepcopy(kwargs))
        ),
        'log_event': lambda *args, **kwargs: None,
        'debug_print': lambda *args, **kwargs: None,
    }
    loaded = load_source_members(
        RETENTION_FILE,
        {
            'resolve_retention_value',
            'process_public_retention',
            'send_public_conversation_owner_notifications',
        },
        namespace=namespace,
    )

    results = loaded['process_public_retention']()

    assert calls['conversations'] == [{
        'public_workspace_id': 'public-1',
        'retention_days': 30,
        'workspace_type': 'public',
    }]
    assert calls['documents'] == []
    assert results['conversations'] == 3
    assert results['workspaces_affected'] == 1

    assert len(calls['workspace_notifications']) == 1
    workspace_id, summary, workspace_type = calls['workspace_notifications'][0]
    assert (workspace_id, workspace_type) == ('public-1', 'public')
    assert summary['conversations_deleted'] == 3
    assert summary['conversation_details'] == [], (
        "The workspace's managers must not be sent the titles of other users' chats."
    )

    by_owner = {
        notification['user_id']: notification
        for notification in calls['user_notifications']
    }
    assert set(by_owner) == {'owner-a', 'owner-b'}
    owner_a = by_owner['owner-a']['message']
    owner_b = by_owner['owner-b']['message']
    assert 'Budget draft' in owner_a and 'Hiring notes' not in owner_a
    assert 'Hiring notes' in owner_b and 'Budget draft' not in owner_b
    assert 'Removed elsewhere' not in owner_a
    assert 'HR Policies' in owner_a
    assert by_owner['owner-a']['metadata']['conversations_deleted'] == 1
    assert by_owner['owner-a']['metadata']['public_workspace_id'] == 'public-1'
    return True


def test_public_workspace_listing_never_reads_a_failure_as_no_workspaces():
    """A failed or partial listing is None, never a set that would release grounded chats."""

    class ListingContainer:
        def __init__(self, rows):
            self.rows = rows
            self.queries = []

        def query_items(self, query=None, enable_cross_partition_query=False, **kwargs):
            self.queries.append((query, enable_cross_partition_query))
            return self.rows()

    def list_workspace_ids(rows):
        container = ListingContainer(rows)
        loaded = load_source_members(
            RETENTION_FILE,
            {'_get_existing_public_workspace_ids'},
            namespace={
                'cosmos_public_workspaces_container': container,
                'logging': __import__('logging'),
                'log_event': lambda *args, **kwargs: None,
                'debug_print': lambda *args, **kwargs: None,
            },
        )
        return loaded['_get_existing_public_workspace_ids'](), container.queries

    def refused():
        raise RuntimeError('throttled')

    def interrupted():
        yield {'id': 'public-1'}
        raise RuntimeError('continuation failed')

    workspace_ids, queries = list_workspace_ids(
        lambda: iter([{'id': 'public-1'}, {'id': ' public-2 '}, {'id': ''}, {}])
    )
    assert workspace_ids == frozenset({'public-1', 'public-2'})
    assert queries == [('SELECT c.id FROM c', True)]
    assert list_workspace_ids(lambda: iter([]))[0] == frozenset()
    assert list_workspace_ids(refused)[0] is None
    assert list_workspace_ids(interrupted)[0] is None, (
        "A partial listing would hand chats in unlisted workspaces to personal retention."
    )
    return True


def test_personal_run_takes_back_chats_from_deleted_public_workspaces():
    """A chat whose public workspace is gone follows its owner's policy again."""

    def aged_chat(conversation_id, public_workspace_id=None):
        chat = {
            'id': conversation_id,
            'user_id': 'owner-a',
            'title': conversation_id,
            'chat_type': 'public' if public_workspace_id else 'personal_single_user',
            'last_updated': '2000-01-01T00:00:00Z',
            'tags': [],
        }
        if public_workspace_id:
            chat['context'] = [
                {'type': 'primary', 'scope': 'public', 'id': public_workspace_id},
            ]
        return chat

    def run_personal_retention(existing_public_workspace_ids):
        conversations = FakeContainer([
            aged_chat('plain'),
            aged_chat('live-grounded', 'public-live'),
            aged_chat('orphaned', 'public-deleted'),
        ])
        deletion_logs = []
        namespace = {
            'datetime': datetime,
            'timezone': timezone,
            'timedelta': timedelta,
            'CosmosResourceNotFoundError': FakeCosmosResourceNotFoundError,
            'cosmos_conversations_container': conversations,
            'cosmos_messages_container': FakeContainer(),
            'cosmos_group_conversations_container': FakeContainer(),
            'cosmos_group_messages_container': FakeContainer(),
            'cosmos_collaboration_conversations_container': FakeContainer(),
            'get_settings': lambda: {'enable_conversation_archiving': False},
            'cancel_m365_conversation_deliveries': lambda conversation_id: None,
            'log_conversation_deletion': (
                lambda **kwargs: deletion_logs.append(copy.deepcopy(kwargs))
            ),
            'delete_blob_backed_chat_message_files': lambda *args, **kwargs: None,
            'delete_thoughts_for_conversation': lambda *args, **kwargs: None,
            'invalidate_conversation_cache_for_item': lambda item, reason: None,
            'log_event': lambda *args, **kwargs: None,
            'debug_print': lambda *args, **kwargs: None,
        }
        loaded = load_source_members(
            RETENTION_FILE,
            {
                '_parse_retention_timestamp',
                '_get_primary_group_id',
                '_is_group_single_user_conversation',
                '_get_primary_public_workspace_id',
                '_is_governed_by_public_workspace',
                '_is_converted_conversation_source',
                '_is_aged_conversation',
                '_build_group_scope_query',
                '_build_public_scope_query',
                '_build_conversation_retention_sources',
                '_delete_standard_conversation_for_retention',
                'delete_aged_conversations',
            },
            assignment_names={
                'GROUP_SINGLE_USER_CHAT_TYPES',
                'PERSONAL_MULTI_USER_CHAT_TYPE',
                'GROUP_MULTI_USER_CHAT_TYPE',
            },
            namespace=namespace,
        )
        result = loaded['delete_aged_conversations'](
            30,
            workspace_type='personal',
            user_id='owner-a',
            existing_public_workspace_ids=existing_public_workspace_ids,
        )
        return result, conversations, deletion_logs

    result, conversations, deletion_logs = run_personal_retention(
        frozenset({'public-live'})
    )
    assert sorted(detail['id'] for detail in result['details']) == ['orphaned', 'plain']
    assert set(conversations.items) == {'live-grounded'}, (
        "A chat grounded in a live public workspace must wait for that workspace's policy."
    )
    orphan_log = next(
        log for log in deletion_logs if log['conversation_id'] == 'orphaned'
    )
    assert orphan_log['workspace_type'] == 'personal'
    assert orphan_log['public_workspace_id'] == 'public-deleted'
    assert orphan_log['additional_context']['retention_source'] == 'personal_single_user'

    # Without a listing, grounded chats are left for a later run.
    result, conversations, _ = run_personal_retention(None)
    assert [detail['id'] for detail in result['details']] == ['plain']
    assert set(conversations.items) == {'live-grounded', 'orphaned'}
    return True


def test_personal_run_lists_public_workspaces_once_for_every_user():
    """One listing per run reaches every user's conversation pass."""
    listings = []
    conversation_calls = []

    def list_public_workspaces():
        listings.append(True)
        return frozenset({'public-live'})

    def fake_delete_aged_conversations(**kwargs):
        conversation_calls.append(kwargs)
        return {'count': 0, 'details': []}

    def user(user_id, conversation_retention_days):
        return {
            'id': user_id,
            'settings': {
                'retention_policy': {
                    'conversation_retention_days': conversation_retention_days,
                    'document_retention_days': 'none',
                },
            },
        }

    namespace = {
        'get_all_user_settings': lambda: [user('owner-a', '30'), user('owner-b', 'default')],
        'get_settings': lambda: {'default_retention_conversation_personal': '60'},
        '_get_existing_public_workspace_ids': list_public_workspaces,
        'delete_aged_conversations': fake_delete_aged_conversations,
        'log_event': lambda *args, **kwargs: None,
        'debug_print': lambda *args, **kwargs: None,
    }
    loaded = load_source_members(
        RETENTION_FILE,
        {'resolve_retention_value', 'process_personal_retention'},
        namespace=namespace,
    )

    loaded['process_personal_retention']()

    assert len(listings) == 1
    assert [
        (call['user_id'], call['retention_days'], call['existing_public_workspace_ids'])
        for call in conversation_calls
    ] == [
        ('owner-a', 30, frozenset({'public-live'})),
        ('owner-b', 60, frozenset({'public-live'})),
    ]
    return True


if __name__ == '__main__':
    tests = [
        test_policy_matrix_and_retention_values,
        test_destructive_collaboration_cleanup_and_race_handling,
        test_collaboration_archival_covers_group_source_records,
        test_collaboration_revalidation_and_cleanup_failure_safety,
        test_new_groups_persist_default_retention_values,
        test_public_grounded_deletion_logs_the_governing_workspace,
        test_public_workspace_run_keeps_chat_titles_with_their_owners,
        test_public_workspace_listing_never_reads_a_failure_as_no_workspaces,
        test_personal_run_takes_back_chats_from_deleted_public_workspaces,
        test_personal_run_lists_public_workspaces_once_for_every_user,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as error:
            print(f"FAIL: {test.__name__}: {error}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"{sum(results)}/{len(results)} retention scope tests passed")
    sys.exit(0 if all(results) else 1)
