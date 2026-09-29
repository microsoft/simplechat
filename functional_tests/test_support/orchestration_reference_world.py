# orchestration_reference_world.py
"""
A deterministic, in-memory world for testing `#` reference authorization.

``resolve_elicitation_references`` (the question card) and ``resolve_scope_references``
(the plan editor's Ask AI, and later the workflow assistant) reach the same lazily
imported boundaries: document contexts, the authorized source manifest, workspace tags,
group membership, public workspace visibility, and the conversation and message
containers. This module stands in for all of them with small fakes that keep the access
rules authorization depends on -- a personal document belongs to one user, a group
document is only reachable through a group the user belongs to, a public document
through a workspace the user can see -- and records every call, so a test can pin the
data-access pattern as well as the result.

The golden parity fixture for the question card was captured against this world.
Changing an existing entry changes that fixture's inputs; add new entries instead.

Version: 0.261.201
Implemented in: 0.261.201
"""

import importlib
import sys
import types
from contextlib import contextmanager
from copy import deepcopy

from azure.cosmos import exceptions

from test_support.app_stubs import stubbed_config

_MISSING = object()

OWNER = 'owner'
INTRUDER = 'intruder'

ALL_ENABLED = {
    'enable_user_workspace': True,
    'enable_group_workspaces': True,
    'enable_public_workspaces': True,
}


def _ready(**extra):
    document = {'status': 'Processing complete', 'percentage_complete': 100}
    document.update(extra)
    return document


# Where each document lives. `scope_id` is the owning user, group, public workspace or
# conversation; `document` is the stored record the readiness check reads.
DOCUMENTS = {
    'own': {'scope': 'personal', 'scope_id': OWNER, 'display_name': 'Own report',
            'file_name': 'own.pdf', 'document': _ready()},
    'own-2': {'scope': 'personal', 'scope_id': OWNER, 'display_name': 'Second report',
              'file_name': 'second.pdf', 'document': _ready()},
    'own-processing': {'scope': 'personal', 'scope_id': OWNER, 'display_name': 'Draft in progress',
                       'file_name': 'draft.pdf',
                       'document': {'status': 'Processing', 'percentage_complete': 40}},
    'own-failed': {'scope': 'personal', 'scope_id': OWNER, 'display_name': 'Broken upload',
                   'file_name': 'broken.pdf',
                   'document': {'status': 'Error: extraction failed', 'percentage_complete': 100}},
    'own-legacy': {'scope': 'personal', 'scope_id': OWNER, 'display_name': 'Legacy memo',
                   'file_name': 'legacy.doc', 'document': {'status': ''}},
    'own-bad-progress': {'scope': 'personal', 'scope_id': OWNER, 'display_name': 'Odd progress',
                         'file_name': 'odd.pdf',
                         'document': {'status': 'Processing complete', 'percentage_complete': 'abc'}},
    'own-file-only': {'scope': 'personal', 'scope_id': OWNER, 'display_name': '',
                      'file_name': 'file-only.docx', 'document': _ready()},
    'own-unnamed': {'scope': 'personal', 'scope_id': OWNER, 'display_name': None,
                    'file_name': None, 'document': _ready()},
    'own-long-name': {'scope': 'personal', 'scope_id': OWNER, 'display_name': 'L' * 300,
                      'file_name': 'long.pdf', 'document': _ready()},
    'intruder-doc': {'scope': 'personal', 'scope_id': INTRUDER, 'display_name': 'Secret merger plan',
                     'file_name': 'merger.pdf', 'document': _ready()},
    'grp-doc': {'scope': 'group', 'scope_id': 'group-a', 'display_name': 'Group budget',
                'file_name': 'budget.xlsx', 'document': _ready()},
    'grp-doc-2': {'scope': 'group', 'scope_id': 'group-a', 'display_name': 'Group roadmap',
                  'file_name': 'roadmap.pptx', 'document': _ready()},
    'grp-b-doc': {'scope': 'group', 'scope_id': 'group-b', 'display_name': 'Design review',
                  'file_name': 'design.pdf', 'document': _ready()},
    'grp-left-doc': {'scope': 'group', 'scope_id': 'group-left', 'display_name': 'Former team notes',
                     'file_name': 'former.pdf', 'document': _ready()},
    'pub-doc': {'scope': 'public', 'scope_id': 'public-a', 'display_name': 'Public handbook',
                'file_name': 'handbook.pdf', 'document': _ready()},
    'pub-hidden-doc': {'scope': 'public', 'scope_id': 'public-hidden', 'display_name': 'Hidden guide',
                       'file_name': 'hidden.pdf', 'document': _ready()},
    'att-ready': {'scope': 'chat', 'scope_id': 'conv', 'display_name': 'Uploaded notes',
                  'file_name': 'notes.txt', 'document': _ready()},
    'att-wrapper': {'scope': 'chat', 'scope_id': 'conv', 'display_name': 'Workspace upload',
                    'file_name': 'wrapper.pdf', 'document': _ready()},
    'att-processing': {'scope': 'chat', 'scope_id': 'conv', 'display_name': 'Slow upload',
                       'file_name': 'slow.pdf', 'document': _ready()},
    'att-no-row': {'scope': 'chat', 'scope_id': 'conv', 'display_name': 'Vanished upload',
                   'file_name': 'vanished.pdf', 'document': _ready()},
}

# Group workspaces by id. `group-gone` passes the membership check but no longer exists.
GROUPS = {
    'group-a': {'name': 'Finance team'},
    'group-b': {'name': 'Design team'},
    'group-left': {'name': 'Former team'},
    'group-long': {'name': 'G' * 300},
}
MEMBERSHIPS = {OWNER: ['group-a', 'group-b', 'group-gone', 'group-long']}

# Public workspaces by id. `public-gone` is visible to the owner but no longer exists.
PUBLIC_WORKSPACES = {
    'public-a': {'name': 'Company handbook'},
    'public-hidden': {'name': 'Hidden space'},
}
VISIBLE_PUBLIC = {OWNER: ['public-a', 'public-gone']}

TAGS = {
    ('personal', None): ['review', 'budget'],
    ('group', 'group-a'): ['grp-tag'],
    ('public', 'public-a'): ['pub-tag'],
}

CONVERSATIONS = [
    {'id': 'conv', 'user_id': OWNER, 'title': 'Review'},
    {'id': 'conv-locked', 'user_id': OWNER, 'scope_locked': True,
     'locked_contexts': [{'scope': 'personal', 'id': OWNER}, {'scope': 'group', 'id': 'group-a'}]},
    {'id': 'conv-locked-context', 'user_id': OWNER, 'scope_locked': True,
     'context': [{'scope': 'public', 'id': 'public-a'}]},
    {'id': 'conv-locked-empty', 'user_id': OWNER, 'scope_locked': True},
    {'id': 'conv-foreign', 'user_id': INTRUDER},
]

MESSAGES = [
    {'id': 'att-ready', 'conversation_id': 'conv', 'status': 'complete', 'percentage_complete': 100},
    {'id': 'att-wrapper', 'conversation_id': 'conv', 'workspace_document_id': 'own',
     'file_content_source': 'workspace', 'percentage_complete': 100},
    {'id': 'att-processing', 'conversation_id': 'conv', 'status': 'processing', 'percentage_complete': 30},
]


def _jsonable(value):
    if callable(value):
        return '<callable>'
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _id_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return [str(item).strip() for item in value if str(item or '').strip()]


class RecordingContainer:
    """A Cosmos container over a dict, recording reads so a test can pin them."""

    def __init__(self, world, name, partition_field, items):
        self.world = world
        self.name = name
        self.partition_field = partition_field
        self.items = {(item[partition_field], item['id']): deepcopy(item) for item in items}

    def read_item(self, item, partition_key):
        self.world.record(f'{self.name}.read_item', item=item, partition_key=partition_key)
        document = self.items.get((partition_key, item))
        if document is None:
            raise exceptions.CosmosResourceNotFoundError(status_code=404)
        return deepcopy(document)

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        self.world.record(
            f'{self.name}.query_items', query=query, parameters=parameters,
            partition_key=partition_key, **kwargs,
        )
        if self.world.flags.get(f'{self.name}_raise'):
            raise RuntimeError(f'{self.name} query failed')
        values = {item['name']: item['value'] for item in parameters or []}
        rows = [deepcopy(document) for (partition, _), document in self.items.items()
                if partition_key is None or partition == partition_key]
        if '@document_id' in values:
            rows = [row for row in rows if row.get('id') == values['@document_id']]
        return rows


class ReferenceWorld:
    """Fakes for every boundary reference authorization reaches, with a call log."""

    def __init__(self):
        self.flags = {}
        self.calls = []
        self.conversations = RecordingContainer(self, 'conversations', 'id', CONVERSATIONS)
        self.messages = RecordingContainer(self, 'messages', 'conversation_id', MESSAGES)
        self.documents = deepcopy(DOCUMENTS)
        self.context = None

    def reset(self, **flags):
        self.flags = dict(flags)
        self.calls = []

    def record(self, name, **arguments):
        self.calls.append({
            'fn': name,
            'arguments': {key: _jsonable(arguments[key]) for key in sorted(arguments)},
        })

    # ---- document boundaries -------------------------------------------------------

    def _authorized_groups(self, user_id, active_group_ids):
        memberships = MEMBERSHIPS.get(user_id, [])
        requested = _id_list(active_group_ids)
        if requested:
            return [group_id for group_id in requested if group_id in memberships]
        return list(memberships)

    def _authorized_publics(self, user_id, active_public_workspace_ids):
        visible = VISIBLE_PUBLIC.get(user_id, [])
        requested = _id_list(active_public_workspace_ids)
        if requested:
            return [workspace_id for workspace_id in requested if workspace_id in visible]
        return list(visible)

    def _context(self, document_id, user_id, doc_scope, groups, publics, conversation_id):
        entry = self.documents.get(document_id)
        if not entry:
            return None
        scope = entry['scope']
        if doc_scope not in ('all', scope) and scope != 'chat':
            return None
        document = dict(deepcopy(entry['document']), id=document_id)
        if scope == 'personal' and entry['scope_id'] == user_id:
            return {'scope': 'personal', 'document': dict(document, user_id=user_id)}
        if scope == 'group' and entry['scope_id'] in groups:
            return {'scope': 'group', 'group_id': entry['scope_id'],
                    'document': dict(document, group_id=entry['scope_id'])}
        if scope == 'public' and entry['scope_id'] in publics:
            return {'scope': 'public', 'public_workspace_id': entry['scope_id'],
                    'document': dict(document, public_workspace_id=entry['scope_id'])}
        if scope == 'chat' and conversation_id and entry['scope_id'] == conversation_id:
            return {'scope': 'chat', 'conversation_id': conversation_id,
                    'document': dict(document, conversation_id=conversation_id)}
        return None

    def resolve_document_contexts(
        self, document_ids, user_id, doc_scope='all', active_group_ids=None,
        active_public_workspace_id=None, conversation_id=None, include_content=True, **extra,
    ):
        self.record(
            'resolve_document_contexts', document_ids=list(document_ids), user_id=user_id,
            doc_scope=doc_scope, active_group_ids=active_group_ids,
            active_public_workspace_id=active_public_workspace_id,
            conversation_id=conversation_id, include_content=include_content, **extra,
        )
        if self.flags.get('contexts_raise'):
            raise RuntimeError('document context lookup failed')
        groups = self._authorized_groups(user_id, active_group_ids)
        publics = self._authorized_publics(user_id, active_public_workspace_id)
        contexts = [
            self._context(document_id, user_id, doc_scope, groups, publics, conversation_id)
            for document_id in document_ids
        ]
        if self.flags.get('short_contexts'):
            contexts = contexts[:-1]
        return contexts

    def _manifest_entry(self, document_id, user_id, context):
        unresolved = {
            'document_id': document_id, 'display_name': None, 'file_name': None,
            'source_kind': 'unresolved', 'scope': None, 'scope_id': None, 'group_id': None,
            'public_workspace_id': None, 'conversation_id': None,
            'authorization_status': 'unresolved',
        }
        if not isinstance(context, dict) or not isinstance(context.get('document'), dict):
            return unresolved
        if context['document'].get('id') != document_id:
            return unresolved
        scope = context.get('scope')
        entry = self.documents.get(document_id) or {}
        group_id = public_workspace_id = conversation_id = None
        if scope == 'personal':
            scope_id = context['document'].get('user_id')
            if scope_id != user_id:
                return unresolved
        elif scope == 'group':
            scope_id = group_id = context.get('group_id')
        elif scope == 'public':
            scope_id = public_workspace_id = context.get('public_workspace_id')
        elif scope == 'chat':
            scope_id = conversation_id = context.get('conversation_id')
        else:
            return unresolved
        if not scope_id:
            return unresolved
        return {
            'document_id': document_id, 'display_name': entry.get('display_name'),
            'file_name': entry.get('file_name'), 'source_kind': 'narrative', 'scope': scope,
            'scope_id': scope_id, 'group_id': group_id,
            'public_workspace_id': public_workspace_id, 'conversation_id': conversation_id,
            'authorization_status': 'authorized',
        }

    def resolve_authorized_source_manifest(
        self, requested_sources, user_id, selection_mode='selected', conversation_id=None,
        active_group_ids=None, active_public_workspace_ids=None, doc_scope='all',
        context_resolver=None, **extra,
    ):
        self.record(
            'resolve_authorized_source_manifest', requested_sources=list(requested_sources),
            user_id=user_id, selection_mode=selection_mode, conversation_id=conversation_id,
            active_group_ids=active_group_ids,
            active_public_workspace_ids=active_public_workspace_ids, doc_scope=doc_scope,
            context_resolver=context_resolver is not None, **extra,
        )
        if self.flags.get('manifest_raise'):
            raise RuntimeError('manifest failed')
        groups = self._authorized_groups(user_id, active_group_ids)
        publics = self._authorized_publics(user_id, active_public_workspace_ids)
        manifest = []
        for document_id in requested_sources:
            if context_resolver is not None:
                context = context_resolver(
                    document_id=document_id, user_id=user_id, doc_scope=doc_scope,
                    active_group_ids=active_group_ids,
                    active_public_workspace_id=active_public_workspace_ids,
                    conversation_id=conversation_id,
                )
            else:
                context = self._context(
                    document_id, user_id, doc_scope, groups, publics, conversation_id,
                )
            if isinstance(context, dict) and doc_scope != 'all' and context.get('scope') != doc_scope:
                context = None
            manifest.append(self._manifest_entry(document_id, user_id, context))
        return manifest

    # ---- workspace boundaries ------------------------------------------------------

    def get_workspace_tags(self, user_id, group_id=None, public_workspace_id=None, **extra):
        self.record(
            'get_workspace_tags', user_id=user_id, group_id=group_id,
            public_workspace_id=public_workspace_id, **extra,
        )
        if self.flags.get('tags_raise'):
            raise RuntimeError('tag lookup failed')
        if group_id:
            key = ('group', group_id)
        elif public_workspace_id:
            key = ('public', public_workspace_id)
        else:
            key = ('personal', None)
        return [{'name': name, 'count': 1, 'color': '#0d6efd'} for name in TAGS.get(key, [])]

    def assert_group_role(self, user_id, group_id, allowed_roles=None, **extra):
        self.record('assert_group_role', user_id=user_id, group_id=group_id,
                    allowed_roles=allowed_roles, **extra)
        if group_id not in MEMBERSHIPS.get(user_id, []):
            raise PermissionError('You are not a member of this group.')
        return 'User'

    def find_group_by_id(self, group_id, **extra):
        self.record('find_group_by_id', group_id=group_id, **extra)
        group = GROUPS.get(group_id)
        return dict(group, id=group_id) if group else None

    def get_user_visible_public_workspace_ids_from_settings(self, user_id, **extra):
        self.record('get_user_visible_public_workspace_ids_from_settings', user_id=user_id, **extra)
        return list(VISIBLE_PUBLIC.get(user_id, []))

    def find_public_workspace_by_id(self, workspace_id, **extra):
        self.record('find_public_workspace_by_id', workspace_id=workspace_id, **extra)
        workspace = PUBLIC_WORKSPACES.get(workspace_id)
        return dict(workspace, id=workspace_id) if workspace else None

    def modules(self):
        def module(name, **attributes):
            result = types.ModuleType(name)
            result.__dict__.update(attributes)
            return result

        return {
            'functions_search_service': module(
                'functions_search_service', resolve_document_contexts=self.resolve_document_contexts,
            ),
            'functions_mixed_source_orchestration': module(
                'functions_mixed_source_orchestration',
                resolve_authorized_source_manifest=self.resolve_authorized_source_manifest,
            ),
            'functions_documents': module(
                'functions_documents', get_workspace_tags=self.get_workspace_tags,
            ),
            'functions_group': module(
                'functions_group', assert_group_role=self.assert_group_role,
                find_group_by_id=self.find_group_by_id,
            ),
            'functions_public_workspaces': module(
                'functions_public_workspaces',
                get_user_visible_public_workspace_ids_from_settings=(
                    self.get_user_visible_public_workspace_ids_from_settings
                ),
                find_public_workspace_by_id=self.find_public_workspace_by_id,
            ),
        }


@contextmanager
def reference_world():
    """Import ``functions_orchestration_context`` against the fakes, then undo everything.

    Every module added to ``sys.modules`` while the world is active is removed afterwards
    and every replaced one is restored, so a later test in the same process never sees a
    stub or a module bound to one.
    """
    world = ReferenceWorld()
    stubs = world.modules()
    before = set(sys.modules)
    replaced = {name: sys.modules.get(name, _MISSING) for name in [*stubs, 'functions_orchestration_context']}
    try:
        with stubbed_config(
            cosmos_conversations_container=world.conversations,
            cosmos_messages_container=world.messages,
            cognitive_services_scope='https://cognitiveservices.azure.com/.default',
        ):
            sys.modules.update(stubs)
            sys.modules.pop('functions_orchestration_context', None)
            world.context = importlib.import_module('functions_orchestration_context')
            yield world
    finally:
        for name in set(sys.modules) - before:
            sys.modules.pop(name, None)
        for name, original in replaced.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def outcome(call):
    """Run ``call`` and describe its result or error as JSON-ready data."""
    try:
        return {'result': call()}
    except Exception as exc:
        return {'error': {
            'type': type(exc).__name__,
            'message': getattr(exc, 'message', None),
            'field': getattr(exc, 'field', None),
            'args': [str(arg) for arg in exc.args],
            'str': str(exc),
        }}
