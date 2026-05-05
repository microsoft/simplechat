#!/usr/bin/env python3
# test_chat_selected_document_metadata_authorization.py
"""
Functional test for chat selected-document metadata authorization.
Version: 0.241.022
Implemented in: 0.241.017; 0.241.022

This test ensures chat selected-document metadata resolution only returns
documents the current caller can access across personal, group, and public
scopes, and that the shared resolver remains wired into both chat handlers and
the tabular selected-document helper.
"""

import ast
import copy
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_backend_chats.py')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'v0.241.017',
    'CHAT_SELECTED_DOCUMENT_METADATA_AUTHORIZATION_FIX.md',
)
TARGET_FUNCTIONS = {
    '_normalize_requested_scope_ids',
    '_resolve_chat_selected_document_metadata',
}


class AccessAwareMockContainer:
    """Minimal Cosmos query stub that applies the resolver's access rules."""

    def __init__(self, documents=None):
        self.documents = {
            document['id']: copy.deepcopy(document)
            for document in (documents or [])
        }

    @staticmethod
    def _project(document):
        return {
            'id': document.get('id'),
            'file_name': document.get('file_name'),
            'title': document.get('title'),
            'group_id': document.get('group_id'),
            'public_workspace_id': document.get('public_workspace_id'),
        }

    @staticmethod
    def _matches_personal(document, user_id, user_id_prefix):
        shared_user_ids = [str(value) for value in document.get('shared_user_ids', [])]
        return (
            document.get('user_id') == user_id
            or user_id in shared_user_ids
            or any(value.startswith(user_id_prefix) for value in shared_user_ids)
        )

    @staticmethod
    def _matches_group(document, group_id, group_id_approved):
        shared_group_ids = [str(value) for value in document.get('shared_group_ids', [])]
        return (
            document.get('group_id') == group_id
            or group_id in shared_group_ids
            or group_id_approved in shared_group_ids
        )

    @staticmethod
    def _matches_public(document, public_workspace_id):
        return document.get('public_workspace_id') == public_workspace_id

    def query_items(self, query, parameters, enable_cross_partition_query=True):
        del query, enable_cross_partition_query

        parameter_map = {
            parameter.get('name'): parameter.get('value')
            for parameter in parameters
        }
        document = self.documents.get(parameter_map.get('@doc_id'))
        if not document:
            return []

        if '@user_id' in parameter_map:
            if self._matches_personal(
                document,
                parameter_map.get('@user_id'),
                parameter_map.get('@user_id_prefix', ''),
            ):
                return [self._project(document)]
            return []

        if '@group_id' in parameter_map:
            if self._matches_group(
                document,
                parameter_map.get('@group_id'),
                parameter_map.get('@group_id_approved'),
            ):
                return [self._project(document)]
            return []

        if '@public_workspace_id' in parameter_map:
            if self._matches_public(document, parameter_map.get('@public_workspace_id')):
                return [self._project(document)]
            return []

        return []


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text, filename=ROUTE_FILE)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f'Function {function_name} not found in route_backend_chats.py')


def load_helpers():
    """Load the selected-document resolver without importing the full Flask app."""
    source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(source, filename=ROUTE_FILE)
    selected_nodes = []

    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS:
            selected_nodes.append(node)

    assert len(selected_nodes) == len(TARGET_FUNCTIONS), (
        f'Expected helper set {sorted(TARGET_FUNCTIONS)}, '
        f'found {[node.name for node in selected_nodes]}'
    )

    module = ast.Module(body=selected_nodes, type_ignores=[])
    namespace = {
        'cosmos_user_documents_container': AccessAwareMockContainer(),
        'cosmos_group_documents_container': AccessAwareMockContainer(),
        'cosmos_public_documents_container': AccessAwareMockContainer(),
    }
    exec(compile(module, ROUTE_FILE, 'exec'), namespace)
    return namespace, source


def test_personal_foreign_document_is_not_resolved():
    """Verify personal selected-document metadata denies unrelated documents."""
    print('🔍 Testing personal foreign selected-document rejection...')

    helpers, _ = load_helpers()
    helpers['cosmos_user_documents_container'] = AccessAwareMockContainer([
        {
            'id': 'personal-foreign',
            'file_name': 'Foreign Workbook.xlsx',
            'user_id': 'other-user',
            'shared_user_ids': [],
        },
    ])

    resolved_document = helpers['_resolve_chat_selected_document_metadata'](
        'personal-foreign',
        user_id='current-user',
        document_scope='personal',
    )

    assert resolved_document is None


def test_personal_shared_document_is_resolved():
    """Verify personal selected-document metadata still honors shared-user access."""
    print('🔍 Testing personal shared selected-document resolution...')

    helpers, _ = load_helpers()
    helpers['cosmos_user_documents_container'] = AccessAwareMockContainer([
        {
            'id': 'personal-shared',
            'file_name': 'Shared Workbook.xlsx',
            'title': 'Shared Workbook',
            'user_id': 'other-user',
            'shared_user_ids': ['current-user,approved'],
        },
    ])

    resolved_document = helpers['_resolve_chat_selected_document_metadata'](
        'personal-shared',
        user_id='current-user',
        document_scope='personal',
    )

    assert resolved_document == {
        'id': 'personal-shared',
        'file_name': 'Shared Workbook.xlsx',
        'title': 'Shared Workbook',
        'group_id': None,
        'public_workspace_id': None,
        'source_hint': 'workspace',
    }


def test_group_raw_shared_document_is_resolved():
    """Verify group selected-document metadata allows raw shared-group entries."""
    print('🔍 Testing group raw-shared selected-document resolution...')

    helpers, _ = load_helpers()
    helpers['cosmos_group_documents_container'] = AccessAwareMockContainer([
        {
            'id': 'group-raw-shared',
            'file_name': 'Group Raw Shared.xlsx',
            'group_id': 'source-group',
            'shared_group_ids': ['active-group'],
        },
    ])

    resolved_document = helpers['_resolve_chat_selected_document_metadata'](
        'group-raw-shared',
        document_scope='group',
        active_group_ids=['active-group'],
    )

    assert resolved_document == {
        'id': 'group-raw-shared',
        'file_name': 'Group Raw Shared.xlsx',
        'title': None,
        'group_id': 'source-group',
        'public_workspace_id': None,
        'source_hint': 'group',
    }


def test_group_approved_shared_document_is_resolved():
    """Verify group selected-document metadata allows approved shared-group entries."""
    print('🔍 Testing group approved selected-document resolution...')

    helpers, _ = load_helpers()
    helpers['cosmos_group_documents_container'] = AccessAwareMockContainer([
        {
            'id': 'group-approved-shared',
            'file_name': 'Group Approved Shared.xlsx',
            'group_id': 'source-group',
            'shared_group_ids': ['active-group,approved'],
        },
    ])

    resolved_document = helpers['_resolve_chat_selected_document_metadata'](
        'group-approved-shared',
        document_scope='group',
        active_group_ids=['active-group'],
    )

    assert resolved_document == {
        'id': 'group-approved-shared',
        'file_name': 'Group Approved Shared.xlsx',
        'title': None,
        'group_id': 'source-group',
        'public_workspace_id': None,
        'source_hint': 'group',
    }


def test_public_visible_document_is_resolved():
    """Verify public selected-document metadata resolves visible workspaces only."""
    print('🔍 Testing visible public selected-document resolution...')

    helpers, _ = load_helpers()
    helpers['cosmos_public_documents_container'] = AccessAwareMockContainer([
        {
            'id': 'public-visible',
            'file_name': 'Visible Public Workbook.xlsx',
            'public_workspace_id': 'workspace-visible',
        },
    ])

    resolved_document = helpers['_resolve_chat_selected_document_metadata'](
        'public-visible',
        document_scope='public',
        active_public_workspace_ids=['workspace-visible'],
    )

    assert resolved_document == {
        'id': 'public-visible',
        'file_name': 'Visible Public Workbook.xlsx',
        'title': None,
        'group_id': None,
        'public_workspace_id': 'workspace-visible',
        'source_hint': 'public',
    }


def test_public_hidden_document_is_not_resolved():
    """Verify public selected-document metadata rejects hidden workspaces."""
    print('🔍 Testing hidden public selected-document rejection...')

    helpers, _ = load_helpers()
    helpers['cosmos_public_documents_container'] = AccessAwareMockContainer([
        {
            'id': 'public-hidden',
            'file_name': 'Hidden Public Workbook.xlsx',
            'public_workspace_id': 'workspace-hidden',
        },
    ])

    resolved_document = helpers['_resolve_chat_selected_document_metadata'](
        'public-hidden',
        document_scope='public',
        active_public_workspace_ids=['workspace-visible'],
    )

    assert resolved_document is None


def test_route_uses_shared_selected_document_resolver_everywhere():
    """Verify both chat handlers and tabular helper share the same resolver."""
    print('🔍 Testing shared selected-document resolver wiring...')

    _, source = load_helpers()
    tabular_helper_source = extract_function_source(
        source,
        'get_selected_workspace_tabular_file_contexts',
    )

    assert source.count('_resolve_chat_selected_document_metadata(') >= 4
    assert 'doc_info = _resolve_chat_selected_document_metadata(' in tabular_helper_source
    assert read_config_version() == '0.241.022'
    assert os.path.exists(FIX_DOC)


if __name__ == '__main__':
    tests = [
        test_personal_foreign_document_is_not_resolved,
        test_personal_shared_document_is_resolved,
        test_group_raw_shared_document_is_resolved,
        test_group_approved_shared_document_is_resolved,
        test_public_visible_document_is_resolved,
        test_public_hidden_document_is_not_resolved,
        test_route_uses_shared_selected_document_resolver_everywhere,
    ]

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        test()

    print(f'\n📊 Results: {len(tests)}/{len(tests)} tests passed')
    sys.exit(0)