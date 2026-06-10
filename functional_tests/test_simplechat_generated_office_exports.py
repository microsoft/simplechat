# test_simplechat_generated_office_exports.py
#!/usr/bin/env python3
"""
Functional test for SimpleChat generated Word and PowerPoint exports.
Version: 0.241.182
Implemented in: 0.241.182

This test ensures SimpleChat exposes generated Word and PowerPoint upload tools,
keeps legacy upload capability restrictions, and defaults workflow agent uploads
to the current group workspace when group context is available.
"""

import importlib
import os
import sys
import types
from pathlib import Path

from flask import Flask


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'application' / 'single_app'))

if 'olefile' not in sys.modules:
    sys.modules['olefile'] = types.ModuleType('olefile')

if 'semantic_kernel_plugins.mcp_plugin_factory' not in sys.modules:
    mcp_plugin_factory_stub = types.ModuleType('semantic_kernel_plugins.mcp_plugin_factory')

    class McpPluginFactory:
        pass

    mcp_plugin_factory_stub.McpPluginFactory = McpPluginFactory
    sys.modules['semantic_kernel_plugins.mcp_plugin_factory'] = mcp_plugin_factory_stub

if 'semantic_kernel_plugins.logged_plugin_loader' not in sys.modules:
    logged_plugin_loader_stub = types.ModuleType('semantic_kernel_plugins.logged_plugin_loader')

    def create_logged_plugin_loader(*args, **kwargs):
        return None

    logged_plugin_loader_stub.create_logged_plugin_loader = create_logged_plugin_loader
    sys.modules['semantic_kernel_plugins.logged_plugin_loader'] = logged_plugin_loader_stub


def _has_office_export_dependencies():
    try:
        import docx  # noqa: F401
        import pptx  # noqa: F401
        return True
    except ImportError:
        return False


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


def _build_operations_patches(operations_module, create_calls, update_calls, invalidations, upload_logs, asserted_roles):
    return PatchSet(
        operations_module,
        {
            'get_current_user_info': lambda: {
                'userId': 'user-123',
                'userPrincipalName': 'user@example.com',
                'displayName': 'Test User',
                'email': 'user@example.com',
            },
            'allowed_file': lambda filename, allowed_extensions=None: filename.lower().endswith(('.docx', '.pptx')),
            'find_group_by_id': lambda group_id: {
                'id': group_id,
                'name': 'Workflow Group',
                'status': 'active',
                'owner': {'id': 'user-123'},
                'admins': [],
                'documentManagers': [],
                'users': [{'userId': 'user-123'}],
            },
            'check_group_status_allows_operation': lambda group_doc, operation_type: (True, ''),
            'assert_group_role': lambda user_id, group_id, allowed_roles=('Owner', 'Admin'): asserted_roles.append({
                'user_id': user_id,
                'group_id': group_id,
                'allowed_roles': tuple(allowed_roles),
            }) or 'Owner',
            'create_document': lambda **kwargs: create_calls.append(dict(kwargs)),
            'update_document': lambda **kwargs: update_calls.append(dict(kwargs)),
            'invalidate_group_search_cache': lambda group_id: invalidations.append(group_id),
            'invalidate_personal_search_cache': lambda user_id: invalidations.append(user_id),
            'log_document_upload': lambda **kwargs: upload_logs.append(dict(kwargs)),
            'require_active_group': lambda user_id: (_ for _ in ()).throw(AssertionError('default_group_id should avoid active group lookup')),
        },
    )


def test_word_and_powerpoint_upload_helpers_queue_supported_files():
    """Generated DOCX/PPTX helpers should render bytes and queue normal document processing."""
    if not _has_office_export_dependencies():
        print('SKIP: python-docx and python-pptx are required for Office byte rendering in this local environment.')
        return

    operations_module = importlib.import_module('functions_simplechat_operations')
    create_calls = []
    update_calls = []
    invalidations = []
    upload_logs = []
    asserted_roles = []
    fake_executor = FakeExecutor()
    app = Flask(__name__)
    app.extensions['executor'] = fake_executor
    temp_paths = []

    with _build_operations_patches(operations_module, create_calls, update_calls, invalidations, upload_logs, asserted_roles):
        with app.app_context():
            word_result = operations_module.upload_word_document_for_current_user(
                file_name='Incident Brief',
                title='Incident Brief',
                markdown_content='# Summary\n\n- First finding\n- Second finding',
                workspace_scope='group',
                default_group_id='group-123',
            )
            ppt_result = operations_module.upload_powerpoint_document_for_current_user(
                file_name='Incident Slides',
                title='Incident Slides',
                markdown_content='# Summary\n\n- First finding\n- Second finding',
                workspace_scope='group',
                default_group_id='group-123',
            )

    try:
        assert word_result['document']['file_name'] == 'Incident Brief.docx'
        assert ppt_result['document']['file_name'] == 'Incident Slides.pptx'
        assert word_result['document']['workspace_scope'] == 'group'
        assert ppt_result['document']['workspace_scope'] == 'group'
        assert len(create_calls) == 2
        assert create_calls[0]['file_name'] == 'Incident Brief.docx'
        assert create_calls[1]['file_name'] == 'Incident Slides.pptx'
        assert all(call['group_id'] == 'group-123' for call in create_calls)
        assert len(update_calls) == 2
        assert invalidations == ['group-123', 'group-123']
        assert [log['file_type'] for log in upload_logs] == ['.docx', '.pptx']
        assert len(asserted_roles) == 2
        assert all(item['allowed_roles'] == ('Owner', 'Admin', 'DocumentManager') for item in asserted_roles)
        assert len(fake_executor.calls) == 2
        assert fake_executor.calls[0]['kwargs']['original_filename'] == 'Incident Brief.docx'
        assert fake_executor.calls[1]['kwargs']['original_filename'] == 'Incident Slides.pptx'
        assert fake_executor.calls[0]['kwargs']['group_id'] == 'group-123'
        assert fake_executor.calls[1]['kwargs']['group_id'] == 'group-123'
        temp_paths = [call['kwargs']['temp_file_path'] for call in fake_executor.calls]
        for temp_path in temp_paths:
            assert os.path.exists(temp_path)
            assert os.path.getsize(temp_path) > 0
    finally:
        for temp_path in temp_paths:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)


def test_simplechat_plugin_exports_default_to_current_group_scope():
    """Plugin upload tools should resolve workspace_scope=current to group when default group context exists."""
    plugin_module = importlib.import_module('semantic_kernel_plugins.simplechat_plugin')
    helper_calls = []

    with PatchSet(
        plugin_module,
        {
            'upload_word_document_for_current_user': lambda **kwargs: helper_calls.append(('word', dict(kwargs))) or {
                'document': {'file_name': kwargs['file_name'], 'workspace_scope': kwargs['workspace_scope'], 'group_id': kwargs['default_group_id']}
            },
            'upload_powerpoint_document_for_current_user': lambda **kwargs: helper_calls.append(('powerpoint', dict(kwargs))) or {
                'document': {'file_name': kwargs['file_name'], 'workspace_scope': kwargs['workspace_scope'], 'group_id': kwargs['default_group_id']}
            },
        },
    ):
        plugin = plugin_module.SimpleChatPlugin({
            'type': 'simplechat',
            'default_group_id': 'group-123',
            'enabled_functions': ['upload_word_document', 'upload_powerpoint_document'],
        })
        word_result = plugin.upload_word_document(
            file_name='Brief',
            markdown_content='# Brief',
            workspace_scope='current',
        )
        ppt_result = plugin.upload_powerpoint_document(
            file_name='Slides',
            markdown_content='# Slides',
            workspace_scope='current',
        )

    assert word_result['success'] is True
    assert ppt_result['success'] is True
    assert helper_calls == [
        ('word', {
            'file_name': 'Brief',
            'title': '',
            'markdown_content': '# Brief',
            'workspace_scope': 'group',
            'group_id': '',
            'default_group_id': 'group-123',
        }),
        ('powerpoint', {
            'file_name': 'Slides',
            'title': '',
            'markdown_content': '# Slides',
            'workspace_scope': 'group',
            'group_id': '',
            'default_group_id': 'group-123',
        }),
    ]


def test_simplechat_capability_fallbacks_and_labels():
    """New Office export capabilities should respect legacy Markdown upload toggles and labels."""
    operations_module = importlib.import_module('functions_simplechat_operations')
    artifacts_module = importlib.import_module('functions_message_artifacts')

    disabled_uploads = operations_module.normalize_simplechat_capabilities({
        'upload_markdown_document': False,
    })
    assert disabled_uploads['upload_markdown_document'] is False
    assert disabled_uploads['upload_word_document'] is False
    assert disabled_uploads['upload_powerpoint_document'] is False

    enabled_uploads = operations_module.normalize_simplechat_capabilities({
        'upload_markdown_document': True,
    })
    assert enabled_uploads['upload_word_document'] is True
    assert enabled_uploads['upload_powerpoint_document'] is True

    enabled_functions = operations_module.get_simplechat_enabled_function_names({
        'upload_markdown_document': False,
    })
    assert 'upload_markdown_document' not in enabled_functions
    assert 'upload_word_document' not in enabled_functions
    assert 'upload_powerpoint_document' not in enabled_functions

    word_label = artifacts_module.build_agent_citation_tool_label(
        'SimpleChatPlugin',
        'upload_word_document',
        {'file_name': 'Brief.docx'},
        {'document': {'file_name': 'Brief.docx'}},
    )
    ppt_label = artifacts_module.build_agent_citation_tool_label(
        'SimpleChatPlugin',
        'upload_powerpoint_document',
        {'file_name': 'Slides.pptx'},
        {'document': {'file_name': 'Slides.pptx'}},
    )
    assert word_label == 'Word file: Brief.docx'
    assert ppt_label == 'PowerPoint file: Slides.pptx'


def test_simplechat_frontend_capability_contracts():
    """Static frontend contracts should expose generated Office upload capability toggles."""
    config = (REPO_ROOT / 'application' / 'single_app' / 'config.py').read_text(encoding='utf-8')
    plugin_js = (REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'plugin_modal_stepper.js').read_text(encoding='utf-8')
    agent_js = (REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'agent_modal_stepper.js').read_text(encoding='utf-8')

    assert 'VERSION = "0.241.182"' in config
    assert "key: 'upload_word_document'" in plugin_js
    assert "key: 'upload_powerpoint_document'" in plugin_js
    assert "key: 'upload_word_document'" in agent_js
    assert "key: 'upload_powerpoint_document'" in agent_js
    assert "['upload_word_document', 'upload_powerpoint_document']" in plugin_js
    assert "['upload_word_document', 'upload_powerpoint_document']" in agent_js


def run_tests():
    tests = [
        test_word_and_powerpoint_upload_helpers_queue_supported_files,
        test_simplechat_plugin_exports_default_to_current_group_scope,
        test_simplechat_capability_fallbacks_and_labels,
        test_simplechat_frontend_capability_contracts,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print('PASS')
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)
