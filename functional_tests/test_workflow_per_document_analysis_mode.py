# test_workflow_per_document_analysis_mode.py
#!/usr/bin/env python3
"""
Functional test for workflow per-document analysis mode.
Version: 0.261.109
Implemented in: 0.241.182

This test ensures Analyze workflows can persist the Run each document separately
option, expose the shared UI control, combine per-document execution results,
and open workflow conversation actions in new tabs.
"""

import ast
import copy
import sys
from pathlib import Path

import pytest

from test_document_analysis_lossless_artifacts import load_module_functions
from test_support.app_stubs import import_app_module
from test_support.document_analysis import document_analysis_runtime
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / 'application' / 'single_app'


def load_document_action_helpers():
    """Execute the real normalizers without importing the Azure-backed runner."""
    path = APP_ROOT / 'functions_document_actions.py'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    nodes = [node for node in tree.body if isinstance(node, (ast.Assign, ast.FunctionDef))]
    with document_analysis_runtime({}) as runtime:
        namespace = {
            'copy': copy,
            'CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS': runtime.producer.CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS,
            'WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS': runtime.producer.WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS,
            'normalize_document_analysis_targets': runtime.producer.normalize_document_analysis_targets,
            'normalize_analysis_options': runtime.results.normalize_analysis_options,
            'normalize_search_id_list': runtime.producer.normalize_search_id_list,
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def load_workflow_helpers():
    """Use production combination, attribution, token accounting and artifact deduplication."""
    mixed = import_app_module('functions_mixed_source_orchestration')
    results = import_app_module('functions_workflow_results')
    return load_module_functions(str(APP_ROOT / 'functions_workflow_runner.py'), {
        'get_workflow_result_text': results.get_workflow_result_text,
        'deduplicate_mixed_source_references': mixed.deduplicate_mixed_source_references,
        **{
            name: getattr(mixed, name) for name in (
                'EVIDENCE_STATUS_CANCELED', 'EVIDENCE_STATUS_COMPLETED',
                'EVIDENCE_STATUS_FAILED', 'EVIDENCE_STATUS_PENDING',
            )
        },
    })


def _read(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding='utf-8')


def test_document_action_analysis_mode_normalization():
    """Document action helpers should normalize and preserve analysis_mode."""
    document_actions = load_document_action_helpers()

    assert document_actions['normalize_document_action_analysis_mode']('per-document') == 'per_document'
    assert document_actions['normalize_document_action_analysis_mode']('individual') == 'per_document'
    assert document_actions['normalize_document_action_analysis_mode']('unexpected') == 'combined'

    normalized_action = document_actions['normalize_document_action_config']({
        'type': 'analyze',
        'document_ids': ['doc-a', 'doc-b'],
        'analysis_mode': 'per_document',
    })
    assert normalized_action['analysis_mode'] == 'per_document'

    legacy_analyze = document_actions['build_analyze_config'](normalized_action)
    assert legacy_analyze['analysis_mode'] == 'per_document'
    normalized_targets = document_actions['normalize_document_analysis_targets'](['doc-a', ' doc-a ', 'doc-b'])
    assert normalized_targets['document_ids'] == ['doc-a', 'doc-b']
    with pytest.raises(ValueError, match='supports up to'):
        document_actions['normalize_document_analysis_targets'](['doc-a', 'doc-b'], max_documents=1)


def test_per_document_result_combines_replies_coverage_and_artifacts():
    """Workflow runner should keep individual document outputs inside one combined response."""
    workflow_runner = load_workflow_helpers()

    combined = workflow_runner['_combine_per_document_analysis_results']([
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

    assert_app_version_at_least("0.241.182")
    assert 'id="workflow-analysis-per-document"' in workspace_template
    assert 'Run each document separately' in workspace_template
    assert 'id="workflow-analysis-per-document"' in group_template
    assert 'Run each document separately' in group_template
    assert 'const DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT = "per_document";' in workflow_js
    assert 'analysis_mode: actionType === DOCUMENT_ACTION_ANALYZE' in workflow_js
    assert 'normalizeWorkflowAnalysisMode(source.analysis_mode)' in workflow_js
    assert 'workflowAnalysisPerDocumentToggle.checked = action.analysis_mode === DOCUMENT_ANALYSIS_MODE_PER_DOCUMENT' in workflow_js
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
