# test_approvals_route_helper_import.py
#!/usr/bin/env python3
"""
Functional test for approvals route authorization helper import and requester action boundaries.
Version: 0.241.030
Implemented in: 0.241.030

This test ensures approval routes explicitly import their authorization helper
and preserve requester view/deny access without allowing requester approval.
"""

import ast
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
CONFIG_FILE = os.path.join(SINGLE_APP_ROOT, 'config.py')
FUNCTIONS_FILE = os.path.join(SINGLE_APP_ROOT, 'functions_approvals.py')
ROUTE_FILE = os.path.join(SINGLE_APP_ROOT, 'route_backend_control_center.py')
FIX_DOC = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'v0.241.030',
    'APPROVAL_REQUESTER_ACTION_BOUNDARY_FIX.md',
)

TARGET_FUNCTIONS = {
    'get_approval_roles_for_request_type',
    '_normalize_user_roles',
    '_get_approval_metadata',
    'approve_request',
    'get_authorized_approval',
    '_can_user_view',
    '_can_user_approve',
    '_can_user_deny',
}


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


def load_approval_helpers():
    """Load approval authorization helpers without importing the full Flask app."""
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
        'STATUS_PENDING': 'pending',
        'STATUS_APPROVED': 'approved',
        'TYPE_DELETE_USER_DOCUMENTS': 'delete_user_documents',
        'TYPE_WARN_USER': 'warn_user',
        'TYPE_SUSPEND_USER': 'suspend_user',
        'TYPE_BLOCK_USER': 'block_user',
        'SAFETY_USER_APPROVAL_TYPES': {'warn_user', 'suspend_user', 'block_user'},
        'cosmos_approvals_container': None,
        'get_settings': lambda: {'require_member_of_control_center_admin': False},
        'log_event': lambda *args, **kwargs: None,
        'debug_print': lambda *args, **kwargs: None,
        '_clear_pending_admin_notifications': lambda *args, **kwargs: None,
        '_format_request_type': lambda request_type: request_type,
        'create_notification': lambda *args, **kwargs: None,
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(module, FUNCTIONS_FILE, 'exec'), namespace)
    return namespace


def test_route_explicitly_imports_private_approval_helper():
    """Verify the route imports the underscore helper that star imports skip."""
    print('Testing approvals route helper import...')

    source = read_file_text(ROUTE_FILE)
    parsed = ast.parse(source, filename=ROUTE_FILE)
    imported_names = []
    for node in parsed.body:
        if isinstance(node, ast.ImportFrom) and node.module == 'functions_approvals':
            imported_names.extend(alias.name for alias in node.names)

    assert '_can_user_approve' in imported_names
    assert '_can_user_deny' in imported_names
    assert "approval_copy['can_approve'] = (approval.get('requester_id') != user_id)" not in source
    assert "approval_copy['can_deny'] = _can_user_deny(approval, user_id, user_roles)" in source

    def get_function_source(function_name):
        start_index = source.index(f'def {function_name}')
        next_route_index = source.find('\n    @app.route', start_index + 1)
        if next_route_index == -1:
            return source[start_index:]
        return source[start_index:next_route_index]

    for function_name in ['api_admin_approve_request', 'api_approve_request']:
        function_source = get_function_source(function_name)
        assert 'require_approval_rights=True' in function_source
        assert 'require_denial_rights=True' not in function_source

    for function_name in ['api_admin_deny_request', 'api_deny_request']:
        function_source = get_function_source(function_name)
        assert 'require_denial_rights=True' in function_source

    print('Approvals route helper import passed')


def test_targeted_delete_approval_visibility_boundaries():
    """Verify targeted document deletion approvals stay visible only to eligible users."""
    print('Testing targeted approval authorization boundaries...')

    namespace = load_approval_helpers()
    approval = {
        'id': 'targeted-delete-docs',
        'request_type': 'delete_user_documents',
        'requester_id': 'requesting-admin',
        'approved_by_id': None,
        'group_owner_id': None,
        'metadata': {
            'user_id': 'target-user',
        },
    }

    assert namespace['_can_user_view'](approval, 'requesting-admin', ['Admin']) is True
    assert namespace['_can_user_approve'](approval, 'requesting-admin', ['Admin']) is False
    assert namespace['_can_user_deny'](approval, 'requesting-admin', ['Admin']) is True
    assert namespace['_can_user_view'](approval, 'target-user', []) is True
    assert namespace['_can_user_approve'](approval, 'target-user', []) is True
    assert namespace['_can_user_deny'](approval, 'target-user', []) is True
    assert namespace['_can_user_view'](approval, 'unrelated-user', []) is False
    assert namespace['_can_user_approve'](approval, 'unrelated-user', []) is False
    assert namespace['_can_user_deny'](approval, 'unrelated-user', []) is False

    print('Targeted approval authorization boundaries passed')


def test_authorized_approval_splits_approve_and_deny_rights():
    """Verify route authorization can allow requester denial without approval."""
    print('Testing approval versus denial route authorization...')

    namespace = load_approval_helpers()
    approval = {
        'id': 'targeted-delete-docs',
        'group_id': 'target-user',
        'status': 'pending',
        'request_type': 'delete_user_documents',
        'requester_id': 'requesting-admin',
        'approved_by_id': None,
        'group_owner_id': None,
        'metadata': {
            'user_id': 'target-user',
        },
    }
    namespace['get_approval_by_id'] = lambda approval_id, group_id: approval

    returned = namespace['get_authorized_approval'](
        approval_id='targeted-delete-docs',
        group_id='target-user',
        user_id='requesting-admin',
        user_roles=['Admin'],
        require_denial_rights=True,
    )
    assert returned is approval

    try:
        namespace['get_authorized_approval'](
            approval_id='targeted-delete-docs',
            group_id='target-user',
            user_id='requesting-admin',
            user_roles=['Admin'],
            require_approval_rights=True,
        )
    except PermissionError:
        pass
    else:
        raise AssertionError('Requester approval authorization should be denied')

    print('Approval versus denial route authorization passed')


def test_approve_request_rejects_requester_execution():
    """Verify direct approval execution blocks the original requester."""
    print('Testing direct requester approval rejection...')

    namespace = load_approval_helpers()
    approval = {
        'id': 'targeted-delete-docs',
        'group_id': 'target-user',
        'status': 'pending',
        'request_type': 'delete_user_documents',
        'requester_id': 'requesting-admin',
        'group_name': 'Target User',
        'metadata': {
            'user_id': 'target-user',
        },
    }

    try:
        namespace['approve_request'](
            approval_id='targeted-delete-docs',
            group_id='target-user',
            approver_id='requesting-admin',
            approver_email='admin@example.com',
            approver_name='Requesting Admin',
            comment='self approval should fail',
            approval=approval,
        )
    except PermissionError as exc:
        assert 'cannot approve' in str(exc)
    else:
        raise AssertionError('Requester approval execution should be denied')

    print('Direct requester approval rejection passed')


def test_fix_documentation_and_version():
    """Verify fix documentation and version tracking are present."""
    print('Testing approvals route fix documentation and version...')

    assert read_config_version() == '0.241.030'
    fix_doc_content = read_file_text(FIX_DOC)
    assert 'Fixed/Implemented in version: **0.241.030**' in fix_doc_content
    assert 'functional_tests/test_approvals_route_helper_import.py' in fix_doc_content
    assert 'application/single_app/config.py' in fix_doc_content

    print('Approvals route fix documentation and version passed')


if __name__ == '__main__':
    tests = [
        test_route_explicitly_imports_private_approval_helper,
        test_targeted_delete_approval_visibility_boundaries,
        test_authorized_approval_splits_approve_and_deny_rights,
        test_approve_request_rejects_requester_execution,
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