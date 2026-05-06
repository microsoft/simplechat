#!/usr/bin/env python3
# test_simplechat_group_creation_wrapper.py
"""
Functional test for SimpleChat group creation wrapper.
Version: 0.241.121
Implemented in: 0.241.121

This test ensures the shared SimpleChat operations module exports
create_group_for_current_user and keeps the wrapper behavior that route and
plugin callers depend on.
"""

import ast
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
OPERATIONS_FILE = ROOT_DIR / 'application' / 'single_app' / 'functions_simplechat_operations.py'
CONFIG_FILE = ROOT_DIR / 'application' / 'single_app' / 'config.py'


def read_text(path):
    return path.read_text(encoding='utf-8')


def read_version():
    for line in read_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_create_group_wrapper(call_log):
    module = ast.parse(read_text(OPERATIONS_FILE), filename=str(OPERATIONS_FILE))
    target_nodes = [
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == 'create_group_for_current_user'
    ]
    assert len(target_nodes) == 1, 'Expected exactly one create_group_for_current_user definition'

    actor_user = {
        'userId': 'user-1',
        'email': 'user@example.com',
        'displayName': 'User One',
    }

    namespace = {
        '__builtins__': __builtins__,
        'Dict': dict,
        'Any': object,
        '_require_group_workspaces_enabled': lambda: call_log.append(('require_group_workspaces_enabled', None)) or {'enabled': True},
        '_require_group_creation_enabled': lambda settings=None: call_log.append(('require_group_creation_enabled', settings)) or settings,
        '_require_current_user_info': lambda: call_log.append(('require_current_user_info', None)) or actor_user,
        'create_group': lambda name, description: call_log.append((
            'create_group',
            {'name': name, 'description': description},
        )) or {
            'id': 'group-1',
            'name': name,
            'description': description,
        },
        '_notify_group_created': lambda group_doc, actor_user: call_log.append((
            'notify_group_created',
            {'group_doc': group_doc, 'actor_user': actor_user},
        )),
    }

    compiled_module = ast.Module(body=target_nodes, type_ignores=[])
    ast.fix_missing_locations(compiled_module)
    exec(compile(compiled_module, str(OPERATIONS_FILE), 'exec'), namespace)
    return namespace['create_group_for_current_user'], actor_user


def test_create_group_wrapper_exists_and_normalizes_inputs():
    print('Testing SimpleChat group creation wrapper export and behavior...')

    call_log = []
    wrapper, actor_user = load_create_group_wrapper(call_log)
    created_group = wrapper('   ', '  Example description  ')

    assert created_group['id'] == 'group-1'
    assert created_group['name'] == 'Untitled Group'
    assert created_group['description'] == 'Example description'
    assert [entry[0] for entry in call_log] == [
        'require_group_workspaces_enabled',
        'require_group_creation_enabled',
        'require_current_user_info',
        'create_group',
        'notify_group_created',
    ]
    assert call_log[1][1] == {'enabled': True}
    assert call_log[3][1] == {
        'name': 'Untitled Group',
        'description': 'Example description',
    }
    assert call_log[4][1]['actor_user'] == actor_user
    assert call_log[4][1]['group_doc'] == created_group

    print('SimpleChat group creation wrapper behavior passed.')
    return True


def test_version_alignment():
    print('Testing version alignment...')
    assert read_version() == '0.241.121'
    print('Version alignment passed.')
    return True


if __name__ == '__main__':
    tests = [
        test_create_group_wrapper_exists_and_normalizes_inputs,
        test_version_alignment,
    ]

    results = []
    for test in tests:
        print(f'\nRunning {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\nResults: {sum(bool(result) for result in results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)