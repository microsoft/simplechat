# test_broken_access_control_findings_fix.py
#!/usr/bin/env python3
"""
Functional test for Broken Access Control audit findings.
Version: 0.242.068
Implemented in: 0.242.049

This test ensures workflow conversation IDs, SimpleChat plugin conversation
lookups, and group document deletion paths enforce object-level authorization
and collapse foreign object identifiers to generic not-found/access-denied
responses.
"""

import ast
import importlib
import os
import sys
import types
import traceback
from copy import deepcopy

from azure.cosmos.exceptions import CosmosResourceNotFoundError


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
CONFIG_FILE = os.path.join(APP_DIR, 'config.py')
PERSONAL_WORKFLOWS_FILE = os.path.join(APP_DIR, 'functions_personal_workflows.py')
GROUP_WORKFLOWS_FILE = os.path.join(APP_DIR, 'functions_group_workflows.py')
WORKFLOW_RUNNER_FILE = os.path.join(APP_DIR, 'functions_workflow_runner.py')
SIMPLECHAT_OPERATIONS_FILE = os.path.join(APP_DIR, 'functions_simplechat_operations.py')
COLLABORATION_FILE = os.path.join(APP_DIR, 'functions_collaboration.py')
GROUP_DOCUMENTS_ROUTE_FILE = os.path.join(APP_DIR, 'route_backend_group_documents.py')

sys.path.insert(0, APP_DIR)


class FakeNotFoundError(Exception):
    """Minimal not-found exception for AST-loaded workflow helpers."""


class FakeConversationContainer:
    def __init__(self, conversations=None, not_found_error=FakeNotFoundError):
        self.conversations = {item['id']: deepcopy(item) for item in (conversations or [])}
        self.not_found_error = not_found_error

    def read_item(self, item, partition_key):
        if item != partition_key or item not in self.conversations:
            try:
                raise self.not_found_error(message='not found')
            except TypeError:
                raise self.not_found_error('not found')
        return deepcopy(self.conversations[item])


class PatchSet:
    def __init__(self, module, replacements):
        self.module = module
        self.replacements = replacements
        self.originals = {}

    def __enter__(self):
        for attribute_name, replacement in self.replacements.items():
            self.originals[attribute_name] = getattr(self.module, attribute_name)
            setattr(self.module, attribute_name, replacement)
        return self

    def __exit__(self, exc_type, exc, tb):
        for attribute_name, original in self.originals.items():
            setattr(self.module, attribute_name, original)
        return False


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def load_selected_module_items(file_path, names, namespace=None):
    source = read_file_text(file_path)
    parsed = ast.parse(source, filename=file_path)
    selected_nodes = []
    for node in parsed.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            selected_nodes.append(node)
        elif isinstance(node, ast.Assign):
            target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(target_name in names for target_name in target_names):
                selected_nodes.append(node)

    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec_namespace = dict(namespace or {})
    exec(compile(module, file_path, 'exec'), exec_namespace)
    return exec_namespace, source


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f'Function {function_name} not found')


def expect_exception(exception_type, callback, message_fragment=''):
    try:
        callback()
    except exception_type as exc:
        if message_fragment and message_fragment not in str(exc):
            raise AssertionError(f'Expected error to contain {message_fragment!r}, got {exc!r}') from exc
        return exc
    raise AssertionError(f'Expected {exception_type.__name__}')


def test_workflow_save_helpers_authorize_conversation_ids():
    """Workflow save helpers should reject foreign or mismatched workflow conversations."""
    print('Testing workflow conversation save authorization...')

    personal_namespace, _ = load_selected_module_items(
        PERSONAL_WORKFLOWS_FILE,
        {
            'WORKFLOW_CONVERSATION_ACCESS_ERROR',
            '_normalize_text',
            '_normalize_personal_workflow_conversation_id',
        },
        {
            'exceptions': types.SimpleNamespace(CosmosResourceNotFoundError=FakeNotFoundError),
            'cosmos_conversations_container': FakeConversationContainer([
                {'id': 'personal-owned-workflow', 'user_id': 'user-1', 'chat_type': 'workflow'},
                {'id': 'personal-foreign-workflow', 'user_id': 'user-2', 'chat_type': 'workflow'},
                {'id': 'personal-normal-chat', 'user_id': 'user-1', 'chat_type': 'personal_single_user'},
                {'id': 'personal-group-workflow', 'user_id': 'user-1', 'group_id': 'group-1', 'chat_type': 'workflow'},
            ]),
        },
    )
    normalize_personal = personal_namespace['_normalize_personal_workflow_conversation_id']

    assert normalize_personal('user-1', {'conversation_id': 'personal-owned-workflow'}) == 'personal-owned-workflow'
    expect_exception(
        PermissionError,
        lambda: normalize_personal('user-1', {'conversation_id': 'personal-foreign-workflow'}),
        'not found or access denied',
    )
    expect_exception(
        ValueError,
        lambda: normalize_personal('user-1', {'conversation_id': 'personal-normal-chat'}),
        'not found or access denied',
    )
    expect_exception(
        PermissionError,
        lambda: normalize_personal('user-1', {'conversation_id': 'personal-group-workflow'}),
        'not found or access denied',
    )
    expect_exception(
        ValueError,
        lambda: normalize_personal('user-1', {'conversation_id': 'missing-workflow'}),
        'not found or access denied',
    )

    group_namespace, _ = load_selected_module_items(
        GROUP_WORKFLOWS_FILE,
        {
            'WORKFLOW_CONVERSATION_ACCESS_ERROR',
            '_normalize_text',
            '_normalize_group_workflow_conversation_id',
        },
        {
            'exceptions': types.SimpleNamespace(CosmosResourceNotFoundError=FakeNotFoundError),
            'cosmos_conversations_container': FakeConversationContainer([
                {'id': 'group-owned-workflow', 'group_id': 'group-1', 'chat_type': 'workflow'},
                {'id': 'group-foreign-workflow', 'group_id': 'group-2', 'chat_type': 'workflow'},
                {'id': 'group-normal-chat', 'group_id': 'group-1', 'chat_type': 'group'},
            ]),
            '_normalize_text': personal_namespace['_normalize_text'],
        },
    )
    normalize_group = group_namespace['_normalize_group_workflow_conversation_id']

    assert normalize_group('group-1', {'conversation_id': 'group-owned-workflow'}) == 'group-owned-workflow'
    expect_exception(
        PermissionError,
        lambda: normalize_group('group-1', {'conversation_id': 'group-foreign-workflow'}),
        'not found or access denied',
    )
    expect_exception(
        ValueError,
        lambda: normalize_group('group-1', {'conversation_id': 'group-normal-chat'}),
        'not found or access denied',
    )

    print('Workflow conversation save authorization verified.')


def test_workflow_runner_refuses_foreign_persisted_conversation_ids():
    """Workflow runner backstop should refuse stale foreign conversation bindings."""
    print('Testing workflow runner conversation authorization backstop...')

    namespace, runner_source = load_selected_module_items(
        WORKFLOW_RUNNER_FILE,
        {
            '_get_workflow_scope',
            '_get_workflow_group_id',
            '_is_authorized_workflow_conversation',
        },
    )
    is_authorized = namespace['_is_authorized_workflow_conversation']

    assert is_authorized(
        {'id': 'conv-personal', 'user_id': 'user-1', 'chat_type': 'workflow'},
        {'user_id': 'user-1'},
    )
    assert not is_authorized(
        {'id': 'conv-personal', 'user_id': 'user-2', 'chat_type': 'workflow'},
        {'user_id': 'user-1'},
    )
    assert not is_authorized(
        {'id': 'conv-personal', 'user_id': 'user-1', 'group_id': 'group-1', 'chat_type': 'workflow'},
        {'user_id': 'user-1'},
    )
    assert is_authorized(
        {'id': 'conv-group', 'group_id': 'group-1', 'chat_type': 'workflow'},
        {'user_id': 'user-1', 'group_id': 'group-1'},
    )
    assert not is_authorized(
        {'id': 'conv-group', 'group_id': 'group-2', 'chat_type': 'workflow'},
        {'user_id': 'user-1', 'group_id': 'group-1'},
    )

    ensure_source = extract_function_source(runner_source, '_ensure_workflow_conversation')
    assert "raise PermissionError(WORKFLOW_CONVERSATION_ACCESS_ERROR)" in ensure_source
    assert "cleaned['group_id'] = group_id" not in ensure_source

    print('Workflow runner conversation authorization backstop verified.')


def test_simplechat_plugin_conversation_lookup_oracles_are_collapsed():
    """SimpleChat plugin helpers should not distinguish foreign conversations from missing ones."""
    print('Testing SimpleChat conversation oracle collapse...')

    operations_module = importlib.import_module('functions_simplechat_operations')

    foreign_personal_container = FakeConversationContainer(
        [{'id': 'foreign-personal', 'user_id': 'user-2', 'chat_type': 'personal_single_user'}],
        not_found_error=CosmosResourceNotFoundError,
    )
    with PatchSet(
        operations_module,
        {
            'get_current_user_info': lambda: {
                'userId': 'user-1',
                'email': 'user1@example.com',
                'displayName': 'User One',
            },
            'cosmos_conversations_container': foreign_personal_container,
        },
    ):
        expect_exception(
            LookupError,
            lambda: operations_module.add_conversation_message_for_current_user(
                conversation_id='foreign-personal',
                content='This should not be written.',
            ),
            'not found or access denied',
        )

    with PatchSet(
        operations_module,
        {
            'get_current_user_info': lambda: {
                'userId': 'user-1',
                'email': 'user1@example.com',
                'displayName': 'User One',
            },
            'cosmos_conversations_container': FakeConversationContainer(not_found_error=CosmosResourceNotFoundError),
            'get_collaboration_conversation': lambda conversation_id: {'id': conversation_id, 'chat_type': 'group'},
            'assert_user_can_participate_in_collaboration_conversation': lambda user_id, conversation_doc: (_ for _ in ()).throw(
                PermissionError('not a participant')
            ),
        },
    ):
        expect_exception(
            LookupError,
            lambda: operations_module.add_conversation_message_for_current_user(
                conversation_id='foreign-collaboration',
                content='This should not be written.',
            ),
            'not found or access denied',
        )

    simplechat_source = read_file_text(SIMPLECHAT_OPERATIONS_FILE)
    collaboration_source = read_file_text(COLLABORATION_FILE)
    assert 'CONVERSATION_ACCESS_ERROR = "Conversation not found or access denied"' in simplechat_source
    assert 'except (LookupError, PermissionError) as exc' in simplechat_source
    assert "raise LookupError('Conversation not found or access denied')" in collaboration_source
    assert 'assert_user_can_view_collaboration_conversation' in extract_function_source(
        collaboration_source,
        'invite_personal_collaboration_participants',
    )

    print('SimpleChat conversation oracle collapse verified.')


def test_group_document_delete_uses_scoped_lookup_before_delete():
    """Group delete route should collapse foreign document IDs before delete helpers run."""
    print('Testing group document delete scoped lookup...')

    route_source = read_file_text(GROUP_DOCUMENTS_ROUTE_FILE)
    delete_source = extract_function_source(route_source, 'api_delete_group_document')

    assert 'activeGroupOid' not in route_source
    assert 'def _require_active_group_document_context' in route_source
    assert 'cosmos_group_documents_container.read_item' not in delete_source
    assert 'WHERE c.id = @document_id AND c.group_id = @group_id' in delete_source
    assert "Document not found or access denied" in delete_source
    assert delete_source.find('owned_document_matches = list(') < delete_source.find('delete_document_revision(')

    print('Group document delete scoped lookup verified.')


def test_version_bumped_for_access_control_fixes():
    """Config version should identify the Broken Access Control fix release."""
    print('Testing fix version...')
    assert read_config_version() == '0.242.068'
    print('Fix version verified.')


def run_tests():
    tests = [
        test_workflow_save_helpers_authorize_conversation_ids,
        test_workflow_runner_refuses_foreign_persisted_conversation_ids,
        test_simplechat_plugin_conversation_lookup_oracles_are_collapsed,
        test_group_document_delete_uses_scoped_lookup_before_delete,
        test_version_bumped_for_access_control_fixes,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            print('Test passed')
            results.append(True)
        except Exception as exc:
            print(f'Test failed: {exc}')
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    return success


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)