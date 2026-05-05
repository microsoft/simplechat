#!/usr/bin/env python3
# test_collaboration_conversation_summary_export_fix.py
"""
Functional test for the collaborative conversation summary and export fix.
Version: 0.241.074
Implemented in: 0.241.074

This test ensures collaborative conversations generate summaries from the
collaboration store and persist export summary metadata back to the shared
conversation container instead of failing against the legacy personal store.
"""

import ast
import copy
import os
import re
import sys
import traceback
from datetime import datetime


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, 'application', 'single_app')
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)


CONFIG_FILE = os.path.join(APP_ROOT, 'config.py')
FUNCTIONS_CONVERSATION_METADATA_FILE = os.path.join(APP_ROOT, 'functions_conversation_metadata.py')
ROUTE_BACKEND_CONVERSATIONS_FILE = os.path.join(APP_ROOT, 'route_backend_conversations.py')
ROUTE_BACKEND_CONVERSATION_EXPORT_FILE = os.path.join(APP_ROOT, 'route_backend_conversation_export.py')
FIX_DOC_FILE = os.path.join(
    REPO_ROOT,
    'docs',
    'explanation',
    'fixes',
    'COLLABORATION_CONVERSATION_SUMMARY_EXPORT_FIX.md',
)


class FakeCosmosResourceNotFoundError(Exception):
    """Minimal stand-in for CosmosResourceNotFoundError."""


class FailingLegacyConversationContainer:
    """Legacy store stub that forces collaboration fallback."""

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        raise FakeCosmosResourceNotFoundError(f'{item or partition_key} not found')


class FakeCollaborationConversationContainer:
    """In-memory collaboration store for metadata update tests."""

    def __init__(self, items=None):
        self.items = {}
        for item in items or []:
            self.items[item['id']] = copy.deepcopy(item)

    def upsert_item(self, item):
        self.items[item['id']] = copy.deepcopy(item)
        return copy.deepcopy(item)


def _read(path):
    with open(path, encoding='utf-8') as file_handle:
        return file_handle.read()


def _read_version():
    config_source = _read(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    if not version_match:
        raise AssertionError('VERSION assignment not found in config.py')
    return version_match.group(1)


def _load_metadata_helpers():
    metadata_source = _read(FUNCTIONS_CONVERSATION_METADATA_FILE)
    metadata_tree = ast.parse(metadata_source)
    helper_names = {
        '_get_conversation_item_with_source',
        'update_conversation_with_metadata',
        'get_conversation_metadata',
    }
    selected_nodes = [
        node for node in metadata_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in helper_names
    ]

    loaded_names = {node.name for node in selected_nodes}
    missing_names = helper_names - loaded_names
    if missing_names:
        raise AssertionError(f'Missing metadata helpers: {sorted(missing_names)}')

    helper_module = ast.Module(body=selected_nodes, type_ignores=[])
    ast.fix_missing_locations(helper_module)

    namespace = {
        'datetime': datetime,
        'CosmosResourceNotFoundError': FakeCosmosResourceNotFoundError,
        'debug_print': lambda *args, **kwargs: None,
        'cosmos_conversations_container': None,
        'cosmos_collaboration_conversations_container': None,
        'get_collaboration_conversation': None,
    }
    exec(compile(helper_module, FUNCTIONS_CONVERSATION_METADATA_FILE, 'exec'), namespace)
    return namespace


def test_update_conversation_metadata_supports_collaboration_conversations():
    """Summary metadata updates must persist to the collaboration container."""
    print('Testing collaboration metadata update fallback...')

    metadata_helpers = _load_metadata_helpers()
    baseline_doc = {
        'id': 'shared-summary-001',
        'title': 'Shared Summary Conversation',
        'updated_at': '2026-04-24T09:00:00',
        'summary': None,
    }
    collaboration_container = FakeCollaborationConversationContainer([baseline_doc])

    metadata_helpers['cosmos_conversations_container'] = FailingLegacyConversationContainer()
    metadata_helpers['cosmos_collaboration_conversations_container'] = collaboration_container
    metadata_helpers['get_collaboration_conversation'] = lambda conversation_id: copy.deepcopy(
        collaboration_container.items[conversation_id]
    )

    summary_payload = {
        'content': 'Shared conversation summary.',
        'model_deployment': 'gpt-4o',
        'generated_at': '2026-04-24T10:15:00',
    }
    update_result = metadata_helpers['update_conversation_with_metadata'](
        'shared-summary-001',
        {'summary': summary_payload},
    )

    if not update_result:
        raise AssertionError('Expected collaboration metadata update to succeed')

    stored_doc = collaboration_container.items['shared-summary-001']
    if stored_doc.get('summary', {}).get('content') != 'Shared conversation summary.':
        raise AssertionError('Collaboration summary metadata was not written to the shared container')
    if stored_doc.get('updated_at') == baseline_doc['updated_at']:
        raise AssertionError('Collaboration metadata update did not refresh updated_at')

    loaded_doc = metadata_helpers['get_conversation_metadata']('shared-summary-001')
    if loaded_doc.get('id') != 'shared-summary-001':
        raise AssertionError('get_conversation_metadata did not return the collaboration conversation')

    print('  Collaboration metadata update checks passed.')
    return True


def test_summary_route_and_export_source_support_collaboration():
    """The summary route and export helper must branch to collaboration-aware paths."""
    print('Testing collaboration summary route and export source contracts...')

    route_source = _read(ROUTE_BACKEND_CONVERSATIONS_FILE)
    export_source = _read(ROUTE_BACKEND_CONVERSATION_EXPORT_FILE)

    route_fragments = [
        'assert_user_can_view_collaboration_conversation',
        'list_collaboration_messages',
        'is_collaboration_summary = False',
        'conversation_item = get_collaboration_conversation(conversation_id)',
        'allow_pending=True',
        'if is_collaboration_summary:',
        'raw_messages = list_collaboration_messages(conversation_id)',
    ]
    missing_route_fragments = [fragment for fragment in route_fragments if fragment not in route_source]
    if missing_route_fragments:
        raise AssertionError(f'Missing collaboration summary route fragments: {missing_route_fragments}')

    export_fragments = [
        "summary_persisted = update_conversation_with_metadata(conversation_id, {'summary': summary_data})",
        'if summary_persisted:',
        'Conversation summary persistence returned false for',
    ]
    missing_export_fragments = [fragment for fragment in export_fragments if fragment not in export_source]
    if missing_export_fragments:
        raise AssertionError(f'Missing collaboration export fragments: {missing_export_fragments}')

    print('  Collaboration summary route and export checks passed.')
    return True


def test_version_and_fix_documentation_alignment():
    """Config version and fix documentation must stay aligned for this fix."""
    print('Testing version and fix documentation alignment...')

    version = _read_version()
    fix_doc_source = _read(FIX_DOC_FILE)

    if version != '0.241.074':
        raise AssertionError(f'Expected config VERSION to be 0.241.074, found {version}')
    if 'Fixed/Implemented in version: **0.241.074**' not in fix_doc_source:
        raise AssertionError('Fix documentation is missing the current version header.')
    if '/api/conversations/<conversation_id>/summary' not in fix_doc_source:
        raise AssertionError('Fix documentation is missing the summary route reference.')
    if 'collaboration store' not in fix_doc_source.lower():
        raise AssertionError('Fix documentation is missing the collaboration storage context.')

    print('  Version and fix documentation alignment checks passed.')
    return True


if __name__ == '__main__':
    tests = [
        test_update_conversation_metadata_supports_collaboration_conversations,
        test_summary_route_and_export_source_support_collaboration,
        test_version_and_fix_documentation_alignment,
    ]
    results = []

    for test in tests:
        print(f'\n{"=" * 60}')
        print(f'Running {test.__name__}...')
        print('=' * 60)
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f'ERROR: {exc}')
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f'\n{"=" * 60}')
    print(f'Results: {passed}/{total} tests passed')
    print('=' * 60)
    sys.exit(0 if all(results) else 1)