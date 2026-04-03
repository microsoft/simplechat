#!/usr/bin/env python3
# test_tabular_all_scope_group_source_context.py
"""
Functional test for all-scope tabular group source context handling.
Version: 0.240.041
Implemented in: 0.240.032; 0.240.041

This test ensures mixed-scope workspace search keeps per-file group/public
source metadata so tabular analysis can open group and public workbooks even
when chat document scope is set to all.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
TARGET_FUNCTIONS = {
    'is_tabular_filename',
    'get_document_containers_for_scope',
    'build_tabular_file_context',
    'dedupe_tabular_file_contexts',
    'infer_tabular_source_context_from_document',
    'get_selected_workspace_tabular_file_contexts',
    'collect_workspace_tabular_file_contexts',
    'build_tabular_analysis_source_context',
}


class MockContainer:
    """Minimal query_items stub for selected-document resolution tests."""

    def __init__(self, rows_by_doc_id=None):
        self.rows_by_doc_id = rows_by_doc_id or {}

    def query_items(self, query, parameters, enable_cross_partition_query):
        del query, enable_cross_partition_query
        doc_id = None
        for parameter in parameters:
            if parameter.get('name') == '@doc_id':
                doc_id = parameter.get('value')
                break
        return list(self.rows_by_doc_id.get(doc_id, []))


def load_helpers():
    """Load targeted tabular helper functions without importing the full Flask app."""
    with open(ROUTE_FILE, 'r', encoding='utf-8') as file_handle:
        source = file_handle.read()

    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        'os': os,
        'Mapping': __import__('typing').Mapping,
        'TABULAR_EXTENSIONS': {'csv', 'tsv', 'xls', 'xlsx', 'xlsm'},
        'log_event': lambda *args, **kwargs: None,
        'logging': __import__('logging'),
        'cosmos_user_documents_container': MockContainer(),
        'cosmos_group_documents_container': MockContainer(),
        'cosmos_public_documents_container': MockContainer(),
    }
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, source


def read_config_version():
    """Extract the current application version from config.py."""
    with open(CONFIG_FILE, 'r', encoding='utf-8') as file_handle:
        for line in file_handle:
            if line.startswith('VERSION = '):
                return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def test_collect_workspace_tabular_file_contexts_preserves_group_and_public_sources_in_all_scope():
    """Verify mixed all-scope search results keep their original per-file source metadata."""
    print('🔍 Testing all-scope tabular file context preservation...')

    helpers, _ = load_helpers()
    collect_contexts = helpers['collect_workspace_tabular_file_contexts']

    contexts = collect_contexts(
        combined_documents=[
            {
                'file_name': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
                'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
            },
            {
                'file_name': 'Public Metrics.xlsx',
                'public_workspace_id': 'public-456',
            },
            {
                'file_name': 'notes.pdf',
                'group_id': 'ignored-group',
            },
        ],
        document_scope='all',
        active_group_id='different-active-group',
        active_public_workspace_id='different-public-workspace',
    )

    assert contexts == [
        {
            'file_name': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'source_hint': 'group',
            'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
        },
        {
            'file_name': 'Public Metrics.xlsx',
            'source_hint': 'public',
            'public_workspace_id': 'public-456',
        },
    ], contexts

    print('✅ All-scope tabular file context preservation passed')
    return True


def test_selected_tabular_document_lookup_checks_all_scope_containers():
    """Verify selected tabular docs in all scope can resolve from group/public containers."""
    print('🔍 Testing all-scope selected tabular document lookup...')

    helpers, _ = load_helpers()
    helpers['cosmos_group_documents_container'] = MockContainer({
        'group-doc-123': [{
            'file_name': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
        }],
    })
    helpers['cosmos_public_documents_container'] = MockContainer({
        'public-doc-456': [{
            'file_name': 'Public Metrics.xlsx',
            'public_workspace_id': 'public-456',
        }],
    })

    selected_contexts = helpers['get_selected_workspace_tabular_file_contexts'](
        selected_document_ids=['group-doc-123', 'public-doc-456'],
        document_scope='all',
    )

    assert selected_contexts == [
        {
            'file_name': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'source_hint': 'group',
            'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
        },
        {
            'file_name': 'Public Metrics.xlsx',
            'source_hint': 'public',
            'public_workspace_id': 'public-456',
        },
    ], selected_contexts

    print('✅ All-scope selected tabular document lookup passed')
    return True


def test_build_tabular_analysis_source_context_mentions_per_file_scope_metadata():
    """Verify the prompt helper emits per-file source instructions for mixed-scope workbooks."""
    print('🔍 Testing tabular analysis source-context prompt...')

    helpers, _ = load_helpers()
    source_context = helpers['build_tabular_analysis_source_context']([
        {
            'file_name': 'CCO-Legal File Plan 2025_Final Approved.xlsx',
            'source_hint': 'group',
            'group_id': '93aa364a-99ee-4cfd-8e4d-f37d175f00f5',
        },
        {
            'file_name': 'Public Metrics.xlsx',
            'source_hint': 'public',
            'public_workspace_id': 'public-456',
        },
    ])

    assert "CCO-Legal File Plan 2025_Final Approved.xlsx: source='group', group_id='93aa364a-99ee-4cfd-8e4d-f37d175f00f5'" in source_context, source_context
    assert "Public Metrics.xlsx: source='public', public_workspace_id='public-456'" in source_context, source_context

    print('✅ Tabular analysis source-context prompt passed')
    return True


def test_route_uses_context_aware_tabular_analysis_and_version_bump():
    """Verify the chat route passes per-file contexts into tabular analysis and bumps the version."""
    print('🔍 Testing route integration and version bump...')

    _, source = load_helpers()

    required_snippets = [
        'workspace_tabular_file_contexts = collect_workspace_tabular_file_contexts(',
        'tabular_file_contexts=workspace_tabular_file_contexts,',
        'doc_public_workspace_id = doc.get(\'public_workspace_id\', None)',
        '"public_workspace_id": doc_public_workspace_id,',
    ]
    missing = [snippet for snippet in required_snippets if snippet not in source]
    assert not missing, f'Missing route integration snippets: {missing}'
    assert read_config_version() == '0.240.041'

    print('✅ Route integration and version bump passed')
    return True


if __name__ == '__main__':
    tests = [
        test_collect_workspace_tabular_file_contexts_preserves_group_and_public_sources_in_all_scope,
        test_selected_tabular_document_lookup_checks_all_scope_containers,
        test_build_tabular_analysis_source_context_mentions_per_file_scope_metadata,
        test_route_uses_context_aware_tabular_analysis_and_version_bump,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)