# test_workflow_per_document_analysis_mode.py
#!/usr/bin/env python3
"""
Functional test for workflow per-document analysis mode.
Version: 0.241.182
Implemented in: 0.241.182

This test ensures Analyze workflows can persist the Run each document separately
option, expose the shared UI control, combine per-document execution results,
and open workflow conversation actions in new tabs.
"""

import importlib
import os
import sys
import types
from pathlib import Path


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

if 'functions_document_analysis' not in sys.modules:
    document_analysis_stub = types.ModuleType('functions_document_analysis')
    document_analysis_stub.CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS = 3
    document_analysis_stub.WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS = 10
    def normalize_document_analysis_targets(document_ids=None, max_documents=None, **kwargs):
        normalized_document_ids = [str(value).strip() for value in (document_ids or []) if str(value).strip()]
        if max_documents:
            normalized_document_ids = normalized_document_ids[:max_documents]
        return {
            'document_ids': normalized_document_ids,
            'doc_scope': kwargs.get('doc_scope') or 'all',
            'active_group_ids': kwargs.get('active_group_ids') or [],
            'active_public_workspace_id': kwargs.get('active_public_workspace_id') or [],
            'window_unit': kwargs.get('window_unit') or 'pages',
            'window_size': kwargs.get('window_size'),
            'window_percent': kwargs.get('window_percent'),
            'max_retries_per_window': kwargs.get('max_retries_per_window') or 1,
        }

    document_analysis_stub.normalize_document_analysis_targets = normalize_document_analysis_targets
    document_analysis_stub.build_document_analysis_progress_snapshot = lambda coverage=None: dict(coverage or {})
    document_analysis_stub.run_document_analysis = lambda *args, **kwargs: {}
    sys.modules['functions_document_analysis'] = document_analysis_stub

if 'functions_search' not in sys.modules:
    search_stub = types.ModuleType('functions_search')
    search_stub.normalize_search_id_list = lambda values=None: [str(value).strip() for value in (values or []) if str(value).strip()]
    sys.modules['functions_search'] = search_stub

if 'functions_search_service' not in sys.modules:
    search_service_stub = types.ModuleType('functions_search_service')
    search_service_stub.resolve_document_context = lambda *args, **kwargs: {}
    sys.modules['functions_search_service'] = search_service_stub

if 'semantic_kernel_loader' not in sys.modules:
    semantic_kernel_loader_stub = types.ModuleType('semantic_kernel_loader')
    semantic_kernel_loader_stub.load_user_semantic_kernel = lambda *args, **kwargs: None
    sys.modules['semantic_kernel_loader'] = semantic_kernel_loader_stub


def _read(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding='utf-8')


def test_document_action_analysis_mode_normalization():
    """Document action helpers should normalize and preserve analysis_mode."""
    document_actions = importlib.import_module('functions_document_actions')

    assert document_actions.normalize_document_action_analysis_mode('per-document') == 'per_document'
    assert document_actions.normalize_document_action_analysis_mode('individual') == 'per_document'
    assert document_actions.normalize_document_action_analysis_mode('unexpected') == 'combined'

    normalized_action = document_actions.normalize_document_action_config({
        'type': 'analyze',
        'document_ids': ['doc-a', 'doc-b'],
        'analysis_mode': 'per_document',
    })
    assert normalized_action['analysis_mode'] == 'per_document'

    legacy_analyze = document_actions.build_analyze_config(normalized_action)
    assert legacy_analyze['analysis_mode'] == 'per_document'


def test_per_document_result_combines_replies_coverage_and_artifacts():
    """Workflow runner should keep individual document outputs inside one combined response."""
    workflow_runner = importlib.import_module('functions_workflow_runner')

    combined = workflow_runner._combine_per_document_analysis_results([
        {
            'document_id': 'doc-a',
            'result': {
                'reply': 'Answer for A',
                'analysis_coverage': {
                    'document_count': 1,
                    'processed_windows': 2,
                    'failed_windows': 0,
                    'documents': [{'document_id': 'doc-a', 'file_name': 'alpha.docx'}],
                },
                'generated_analysis_artifacts': [{'id': 'artifact-a'}],
                'generated_tabular_outputs': [{'id': 'tabular-a'}],
                'agent_citations': [{'function_name': 'upload_word_document'}],
                'token_usage': {
                    'prompt_tokens': 10,
                    'completion_tokens': 5,
                    'total_tokens': 15,
                    'request_count': 1,
                },
                'provider': 'azure_openai',
                'model_deployment_name': 'gpt-4o',
            },
        },
        {
            'document_id': 'doc-b',
            'result': {
                'reply': 'Answer for B',
                'analysis_coverage': {
                    'document_count': 1,
                    'processed_windows': 1,
                    'failed_windows': 1,
                    'documents': [{'document_id': 'doc-b', 'file_name': 'beta.docx'}],
                },
                'generated_analysis_artifacts': [{'id': 'artifact-b'}],
                'agent_citations': [{'function_name': 'upload_powerpoint_document'}],
                'token_usage': {
                    'prompt_tokens': 20,
                    'completion_tokens': 7,
                    'total_tokens': 27,
                    'request_count': 1,
                },
            },
        },
    ])

    assert '# Per-document workflow results' in combined['reply']
    assert '## 1. alpha.docx' in combined['reply']
    assert 'Answer for A' in combined['reply']
    assert '## 2. beta.docx' in combined['reply']
    assert 'Answer for B' in combined['reply']
    assert combined['analysis_result']['per_document'] is True
    assert len(combined['analysis_result']['document_results']) == 2
    assert combined['analysis_coverage']['document_count'] == 2
    assert combined['analysis_coverage']['processed_windows'] == 3
    assert combined['analysis_coverage']['failed_windows'] == 1
    assert combined['generated_analysis_artifacts'] == [{'id': 'artifact-a'}, {'id': 'artifact-b'}]
    assert combined['generated_tabular_outputs'] == [{'id': 'tabular-a'}]
    assert len(combined['agent_citations']) == 2
    assert combined['token_usage'] == {
        'prompt_tokens': 30,
        'completion_tokens': 12,
        'total_tokens': 42,
        'request_count': 2,
    }


def test_workflow_per_document_ui_and_new_tab_contracts():
    """Static UI contracts should expose the mode switch and new-tab conversation actions."""
    config = _read('application/single_app/config.py')
    workflow_js = _read('application/single_app/static/js/workspace/workspace_workflows.js')
    notifications_js = _read('application/single_app/static/js/notifications.js')
    workspace_template = _read('application/single_app/templates/workspace.html')
    group_template = _read('application/single_app/templates/group_workspaces.html')

    assert 'VERSION = "0.241.182"' in config
    assert 'id="workflow-analysis-per-document"' in workspace_template
    assert 'Run each document separately' in workspace_template
    assert 'id="workflow-analysis-per-document"' in group_template
    assert 'Run each document separately' in group_template
    assert 'const DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT = "per_document";' in workflow_js
    assert 'analysis_mode: documentActionType === DOCUMENT_ACTION_ANALYZE ? analysisMode : DOCUMENT_ANALYSIS_MODE_COMBINED' in workflow_js
    assert 'workflowAnalysisPerDocumentToggle.checked = documentAction.analysis_mode === DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT' in workflow_js
    assert 'target="_blank" rel="noopener"' in workflow_js
    assert 'element.target = conversationUrl ? "_blank" : "";' in workflow_js
    assert "const targetWindow = window.open('about:blank', '_blank');" in notifications_js
    assert "targetWindow.opener = null;" in notifications_js
    assert 'targetWindow.location.href = target.link_url;' in notifications_js


def run_tests():
    tests = [
        test_document_action_analysis_mode_normalization,
        test_per_document_result_combines_replies_coverage_and_artifacts,
        test_workflow_per_document_ui_and_new_tab_contracts,
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
