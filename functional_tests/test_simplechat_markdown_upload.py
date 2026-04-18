# test_simplechat_markdown_upload.py
#!/usr/bin/env python3
"""
Functional test for SimpleChat Markdown workspace uploads.
Version: 0.241.029
Implemented in: 0.241.029

This test ensures SimpleChat can queue Markdown documents into personal and
group workspaces through the normal document-processing pipeline and forward
default group context from the plugin surface.
"""

import importlib
import os
import sys
import traceback

from flask import Flask


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def submit_stored(self, *args, **kwargs):
        document_id = args[0]
        callback = args[1]
        self.calls.append({
            'document_id': document_id,
            'callback': callback,
            'kwargs': dict(kwargs),
        })
        return {'document_id': document_id}


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


def test_upload_markdown_document_to_personal_workspace():
    """SimpleChat should queue personal Markdown uploads through the document background processor."""
    print('🔍 Testing personal Markdown workspace upload...')

    operations_module = importlib.import_module('functions_simplechat_operations')
    create_calls = []
    update_calls = []
    invalidations = []
    upload_logs = []
    fake_executor = FakeExecutor()
    app = Flask(__name__)
    app.extensions['executor'] = fake_executor
    temp_file_path = ''

    with PatchSet(
        operations_module,
        {
            'get_current_user_info': lambda: {
                'userId': 'user-123',
                'userPrincipalName': 'user@example.com',
                'displayName': 'Test User',
                'email': 'user@example.com',
            },
            'allowed_file': lambda filename, allowed_extensions=None: True,
            'create_document': lambda **kwargs: create_calls.append(dict(kwargs)),
            'update_document': lambda **kwargs: update_calls.append(dict(kwargs)),
            'invalidate_personal_search_cache': lambda user_id: invalidations.append(user_id),
            'log_document_upload': lambda **kwargs: upload_logs.append(dict(kwargs)),
        },
    ):
        with app.app_context():
            result = operations_module.upload_markdown_document_for_current_user(
                file_name='Quarterly Summary',
                markdown_content='# Quarterly Summary\n\n- Revenue increased',
            )

    try:
        assert result['document']['workspace_scope'] == 'personal'
        assert result['document']['file_name'] == 'Quarterly Summary.md'
        assert len(create_calls) == 1
        assert create_calls[0]['file_name'] == 'Quarterly Summary.md'
        assert create_calls[0]['user_id'] == 'user-123'
        assert 'group_id' not in create_calls[0] or create_calls[0]['group_id'] is None
        assert len(update_calls) == 1
        assert update_calls[0]['percentage_complete'] == 0
        assert invalidations == ['user-123']
        assert upload_logs and upload_logs[0]['container_type'] == 'personal'
        assert len(fake_executor.calls) == 1

        queued_call = fake_executor.calls[0]
        assert queued_call['document_id'] == result['document']['id']
        assert queued_call['kwargs']['original_filename'] == 'Quarterly Summary.md'
        assert queued_call['kwargs']['user_id'] == 'user-123'
        temp_file_path = queued_call['kwargs']['temp_file_path']
        assert os.path.exists(temp_file_path)
        with open(temp_file_path, 'r', encoding='utf-8') as saved_file:
            assert saved_file.read() == '# Quarterly Summary\n\n- Revenue increased'
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

    print('✅ Personal Markdown workspace upload verified.')


def test_upload_markdown_document_to_group_workspace_uses_group_permissions():
    """SimpleChat should queue group Markdown uploads only after the standard group upload checks succeed."""
    print('🔍 Testing group Markdown workspace upload...')

    operations_module = importlib.import_module('functions_simplechat_operations')
    create_calls = []
    update_calls = []
    invalidations = []
    upload_logs = []
    asserted_roles = []
    fake_executor = FakeExecutor()
    app = Flask(__name__)
    app.extensions['executor'] = fake_executor
    temp_file_path = ''

    with PatchSet(
        operations_module,
        {
            'get_current_user_info': lambda: {
                'userId': 'user-123',
                'userPrincipalName': 'user@example.com',
                'displayName': 'Test User',
                'email': 'user@example.com',
            },
            'allowed_file': lambda filename, allowed_extensions=None: True,
            'find_group_by_id': lambda group_id: {
                'id': group_id,
                'name': 'Planning Group',
                'status': 'active',
                'owner': {'id': 'user-123'},
                'admins': [],
                'documentManagers': [],
                'users': [{'userId': 'user-123', 'email': 'user@example.com', 'displayName': 'Test User'}],
            },
            'check_group_status_allows_operation': lambda group_doc, operation_type: (True, ''),
            'assert_group_role': lambda user_id, group_id, allowed_roles=('Owner', 'Admin'): asserted_roles.append(
                {
                    'user_id': user_id,
                    'group_id': group_id,
                    'allowed_roles': tuple(allowed_roles),
                }
            ) or 'Owner',
            'create_document': lambda **kwargs: create_calls.append(dict(kwargs)),
            'update_document': lambda **kwargs: update_calls.append(dict(kwargs)),
            'invalidate_group_search_cache': lambda group_id: invalidations.append(group_id),
            'log_document_upload': lambda **kwargs: upload_logs.append(dict(kwargs)),
            'require_active_group': lambda user_id: (_ for _ in ()).throw(AssertionError('Active group lookup should not be used when default_group_id is provided')),
        },
    ):
        with app.app_context():
            result = operations_module.upload_markdown_document_for_current_user(
                file_name='Planning Notes.txt',
                markdown_content='## Decisions\n\n1. Ship the feature',
                workspace_scope='group',
                default_group_id='group-123',
            )

    try:
        assert result['document']['workspace_scope'] == 'group'
        assert result['document']['group_id'] == 'group-123'
        assert result['document']['file_name'] == 'Planning Notes.md'
        assert len(create_calls) == 1
        assert create_calls[0]['group_id'] == 'group-123'
        assert len(update_calls) == 1
        assert update_calls[0]['group_id'] == 'group-123'
        assert invalidations == ['group-123']
        assert upload_logs and upload_logs[0]['container_type'] == 'group'
        assert asserted_roles == [
            {
                'user_id': 'user-123',
                'group_id': 'group-123',
                'allowed_roles': ('Owner', 'Admin', 'DocumentManager'),
            }
        ]
        assert len(fake_executor.calls) == 1

        queued_call = fake_executor.calls[0]
        temp_file_path = queued_call['kwargs']['temp_file_path']
        assert queued_call['kwargs']['group_id'] == 'group-123'
        assert os.path.exists(temp_file_path)
        with open(temp_file_path, 'r', encoding='utf-8') as saved_file:
            assert saved_file.read() == '## Decisions\n\n1. Ship the feature'
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)

    print('✅ Group Markdown workspace upload verified.')


def test_simplechat_plugin_upload_markdown_document_uses_default_group_context():
    """SimpleChat plugin should forward the action's default group context into the Markdown upload helper."""
    print('🔍 Testing SimpleChat plugin Markdown upload forwarding...')

    plugin_module = importlib.import_module('semantic_kernel_plugins.simplechat_plugin')
    helper_calls = []

    with PatchSet(
        plugin_module,
        {
            'upload_markdown_document_for_current_user': lambda **kwargs: helper_calls.append(dict(kwargs)) or {
                'document': {
                    'id': 'document-123',
                    'file_name': kwargs['file_name'],
                    'workspace_scope': kwargs['workspace_scope'],
                    'group_id': kwargs.get('group_id') or kwargs.get('default_group_id'),
                    'status': 'Queued for processing',
                }
            },
        },
    ):
        plugin = plugin_module.SimpleChatPlugin(
            {
                'id': 'simplechat-action-id',
                'name': 'simplechat_tools',
                'type': 'simplechat',
                'default_group_id': 'group-123',
                'enabled_functions': [
                    'upload_markdown_document',
                ],
            }
        )
        result = plugin.upload_markdown_document(
            file_name='Research Summary',
            markdown_content='# Summary',
            workspace_scope='group',
        )

    assert result['success'] is True
    assert helper_calls == [
        {
            'file_name': 'Research Summary',
            'markdown_content': '# Summary',
            'workspace_scope': 'group',
            'group_id': '',
            'default_group_id': 'group-123',
        }
    ]
    assert result['document']['group_id'] == 'group-123'

    print('✅ SimpleChat plugin Markdown upload forwarding verified.')


if __name__ == '__main__':
    tests = [
        test_upload_markdown_document_to_personal_workspace,
        test_upload_markdown_document_to_group_workspace_uses_group_permissions,
        test_simplechat_plugin_upload_markdown_document_uses_default_group_context,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'❌ Test failed: {exc}')
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)