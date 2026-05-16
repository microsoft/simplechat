# test_approvals_api_load_fix.py
#!/usr/bin/env python3
"""
Functional test for approvals API load resilience.
Version: 0.241.021
Implemented in: 0.241.021

This test ensures the approvals list can load without Cosmos ORDER BY support
and without crashing on legacy approval records with missing metadata or roles.
"""

import ast
import copy
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
FUNCTIONS_FILE = os.path.join(SINGLE_APP_ROOT, 'functions_approvals.py')
CONFIG_FILE = os.path.join(SINGLE_APP_ROOT, 'config.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'v0.241.021',
    'APPROVALS_API_LOAD_FIX.md',
)

TARGET_FUNCTIONS = {
    'get_approval_roles_for_request_type',
    '_normalize_user_roles',
    '_get_approval_metadata',
    '_get_approval_sort_value',
    'get_pending_approvals',
    '_can_user_view',
    '_can_user_approve',
}


class FakeApprovalsContainer:
    """In-memory Cosmos-like container for approval list tests."""

    def __init__(self, items):
        self.items = copy.deepcopy(items)
        self.queries = []

    def query_items(self, query=None, parameters=None, enable_cross_partition_query=False):
        self.queries.append(query)
        if 'ORDER BY' in (query or '').upper():
            raise AssertionError('Approvals query should sort locally without ORDER BY')
        if not enable_cross_partition_query:
            raise AssertionError('Approvals query must remain cross-partition')

        parameter_map = {param['name']: param['value'] for param in (parameters or [])}
        results = copy.deepcopy(self.items)

        if '@status' in parameter_map:
            results = [item for item in results if item.get('status') == parameter_map['@status']]

        if '@request_type' in parameter_map:
            results = [item for item in results if item.get('request_type') == parameter_map['@request_type']]

        return results


def read_file_text(file_path):
    """Read a repository file used by this regression test."""
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    """Read the current application version from config.py."""
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_approval_helpers(container=None):
    """Load approval helper functions without importing the full Flask app config."""
    source = read_file_text(FUNCTIONS_FILE)
    parsed = ast.parse(source, filename=FUNCTIONS_FILE)
    selected_nodes = [
        node for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name in TARGET_FUNCTIONS
    ]

    found_names = {node.name for node in selected_nodes}
    missing_names = TARGET_FUNCTIONS - found_names
    assert not missing_names, f'Missing approval helper functions: {sorted(missing_names)}'

    namespace = {
        'Any': Any,
        'Dict': Dict,
        'List': List,
        'Optional': Optional,
        'datetime': datetime,
        'logging': logging,
        'STATUS_PENDING': 'pending',
        'TYPE_DELETE_USER_DOCUMENTS': 'delete_user_documents',
        'TYPE_WARN_USER': 'warn_user',
        'TYPE_SUSPEND_USER': 'suspend_user',
        'TYPE_BLOCK_USER': 'block_user',
        'SAFETY_USER_APPROVAL_TYPES': {'warn_user', 'suspend_user', 'block_user'},
        'cosmos_approvals_container': container,
        'get_settings': lambda: {'require_member_of_control_center_admin': False},
        'log_event': lambda *args, **kwargs: None,
        'debug_print': lambda *args, **kwargs: None,
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(module, FUNCTIONS_FILE, 'exec'), namespace)
    return namespace


def test_approvals_query_sorts_locally_without_order_by():
    """Verify approval listing avoids Cosmos ORDER BY and still returns newest first."""
    print('Testing approvals API query and local sorting...')

    approvals = [
        {
            'id': 'older-user-docs',
            'group_id': 'user-1',
            'status': 'pending',
            'request_type': 'delete_user_documents',
            'requester_id': 'requester-1',
            'group_owner_id': None,
            'created_at': '2026-01-01T00:00:00',
            'metadata': None,
        },
        {
            'id': 'newer-group-delete',
            'group_id': 'group-1',
            'status': 'pending',
            'request_type': 'delete_group',
            'requester_id': 'requester-2',
            'group_owner_id': 'owner-1',
            'created_at': '2026-05-10T00:00:00',
            'metadata': {},
        },
    ]
    container = FakeApprovalsContainer(approvals)
    namespace = load_approval_helpers(container)

    result = namespace['get_pending_approvals'](
        user_id='admin-1',
        user_roles=['Admin'],
        page=1,
        per_page=20,
        status_filter='pending',
    )

    assert container.queries, 'Expected approvals query to execute'
    assert 'ORDER BY' not in container.queries[0].upper()
    assert [item['id'] for item in result['approvals']] == [
        'newer-group-delete',
        'older-user-docs',
    ]
    assert result['total'] == 2

    print('Approvals query sorts locally without ORDER BY')


def test_approval_visibility_handles_missing_roles_and_metadata():
    """Verify direct authorization checks tolerate legacy metadata and role shapes."""
    print('Testing approval authorization normalization...')

    namespace = load_approval_helpers()
    approval = {
        'id': 'legacy-approval',
        'request_type': 'delete_user_documents',
        'requester_id': 'requester-1',
        'approved_by_id': None,
        'group_owner_id': 'owner-1',
        'metadata': None,
    }

    assert namespace['_can_user_approve'](approval, 'owner-1', None) is True
    assert namespace['_can_user_view'](approval, 'owner-1', None) is True
    assert namespace['_can_user_approve'](approval, 'admin-1', 'Admin') is True

    print('Approval authorization normalization passed')


def test_fix_documentation_and_version():
    """Verify fix documentation and version tracking are present."""
    print('Testing approvals API fix documentation and version...')

    assert read_config_version() == '0.241.021'
    fix_doc_content = read_file_text(FIX_DOC)
    assert 'Fixed/Implemented in version: **0.241.021**' in fix_doc_content
    assert 'functional_tests/test_approvals_api_load_fix.py' in fix_doc_content

    print('Approvals API fix documentation and version passed')


if __name__ == '__main__':
    tests = [
        test_approvals_query_sorts_locally_without_order_by,
        test_approval_visibility_handles_missing_roles_and_metadata,
        test_fix_documentation_and_version,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'Test failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)