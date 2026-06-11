#!/usr/bin/env python3
# test_workflow_document_picker_recent_targets.py
"""
Functional test for workflow document picker and recent workflow document targets.
Version: 0.241.188
Implemented in: 0.241.188

This test ensures workflow Search, Analyze, and Compare configuration uses the
shared chat document picker instead of visible raw ID fields, and recent
document workflows can be saved and resolved at run time.
"""

import importlib
import os
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(APP_ROOT))


if 'functions_document_analysis' not in sys.modules:
    document_analysis_stub = types.ModuleType('functions_document_analysis')
    document_analysis_stub.CHAT_DOCUMENT_ANALYSIS_MAX_DOCUMENTS = 3
    document_analysis_stub.WORKFLOW_DOCUMENT_ANALYSIS_MAX_DOCUMENTS = 10

    def normalize_document_analysis_targets(document_ids=None, max_documents=None, **kwargs):
        normalized_document_ids = []
        for value in document_ids or []:
            normalized_value = str(value or '').strip()
            if normalized_value and normalized_value not in normalized_document_ids:
                normalized_document_ids.append(normalized_value)
        if not normalized_document_ids:
            raise ValueError('At least one document id is required for analysis.')
        if max_documents is not None and len(normalized_document_ids) > max_documents:
            raise ValueError(f'Document analysis supports up to {max_documents} documents at a time.')
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
    sys.modules['functions_document_analysis'] = document_analysis_stub

if 'functions_search' not in sys.modules:
    search_stub = types.ModuleType('functions_search')

    def normalize_search_id_list(values=None):
        if values is None:
            return []
        if isinstance(values, str):
            raw_values = values.split(',')
        elif isinstance(values, list):
            raw_values = values
        else:
            raw_values = [values]
        normalized_values = []
        for value in raw_values:
            normalized_value = str(value or '').strip()
            if normalized_value and normalized_value not in normalized_values:
                normalized_values.append(normalized_value)
        return normalized_values

    def normalize_search_scope(value=None):
        normalized_value = str(value or 'all').strip().lower()
        return normalized_value if normalized_value in {'all', 'personal', 'group', 'public'} else 'all'

    def normalize_search_top_n(top_n, default_top_n=12, max_top_n=50):
        try:
            normalized_top_n = int(top_n)
        except (TypeError, ValueError):
            return default_top_n
        if normalized_top_n < 1:
            return default_top_n
        return min(normalized_top_n, max_top_n)

    search_stub.normalize_search_id_list = normalize_search_id_list
    search_stub.normalize_search_scope = normalize_search_scope
    search_stub.normalize_search_top_n = normalize_search_top_n
    sys.modules['functions_search'] = search_stub


WORKSPACE_TEMPLATE = APP_ROOT / 'templates' / 'workspace.html'
GROUP_TEMPLATE = APP_ROOT / 'templates' / 'group_workspaces.html'
WORKFLOW_JS = APP_ROOT / 'static' / 'js' / 'workspace' / 'workspace_workflows.js'
CHAT_DOCUMENTS_JS = APP_ROOT / 'static' / 'js' / 'chat' / 'chat-documents.js'
DOCUMENT_ACTIONS_PY = APP_ROOT / 'functions_document_actions.py'
WORKFLOW_RUNNER_PY = APP_ROOT / 'functions_workflow_runner.py'
CONFIG_PY = APP_ROOT / 'config.py'


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def test_workflow_modals_use_picker_contracts() -> None:
    print('Testing workflow modal picker contracts...')
    workspace_template = read_text(WORKSPACE_TEMPLATE)
    group_template = read_text(GROUP_TEMPLATE)

    for template_content in (workspace_template, group_template):
        assert 'id="workflow-document-picker-card"' in template_content
        assert 'id="document-action-select"' in template_content
        assert 'id="scope-dropdown"' in template_content
        assert 'id="tags-dropdown"' in template_content
        assert 'id="document-dropdown"' in template_content
        assert 'id="document-select"' in template_content
        assert 'id="workflow-analysis-target-mode"' in template_content
        assert '<option value="recent">Recent documents</option>' in template_content
        assert 'id="workflow-analysis-recent-minutes"' in template_content
        assert 'type="hidden" id="workflow-analysis-document-ids"' in template_content
        assert 'id="workflow-analysis-per-document-group"' in template_content
        assert 'id="workflow-comparison-inline-source-tags"' in template_content
        assert 'id="workflow-comparison-inline-target-tags"' in template_content
        assert 'id="workflow-comparison-edit-btn"' in template_content
        assert 'id="workflow-comparison-modal"' in template_content
        assert 'id="workflow-comparison-board"' in template_content
        assert 'id="workflow-comparison-available-list"' in template_content
        assert 'id="workflow-comparison-source-dropzone"' in template_content
        assert 'id="workflow-comparison-selection-list"' in template_content
        assert 'class="d-none" id="workflow-comparison-target-document-ids"' in template_content
        assert 'class="d-none" id="workflow-comparison-left-document-id"' in template_content
        assert 'label for="workflow-analysis-document-ids"' not in template_content
        assert 'Target Versions' not in template_content
        assert 'Source Version' not in template_content
        assert 'Group Scope Hints' not in template_content
        assert 'Public Workspace Hints' not in template_content

    assert 'window.userGroups = {{ user_groups|default([], true)|tojson|safe }};' in workspace_template
    assert 'window.userVisiblePublicWorkspaces = {{ user_visible_public_workspaces|default([], true)|tojson|safe }};' in workspace_template
    assert 'window.userGroups = activeGroupId' in group_template
    assert 'window.userVisiblePublicWorkspaces = [];' in group_template
    assert 'Active Group Workspace' in group_template
    assert 'id="scope-dropdown-button"' in group_template and 'disabled' in group_template


def test_workflow_picker_javascript_contracts() -> None:
    print('Testing workflow picker JavaScript contracts...')
    workflow_js = read_text(WORKFLOW_JS)
    chat_documents_js = read_text(CHAT_DOCUMENTS_JS)

    assert 'from "../chat/chat-documents.js"' in workflow_js
    assert 'ensureDocumentPickerReady' in workflow_js
    assert 'setEffectiveScopes' in workflow_js
    assert 'workflowPickerDocumentIds' in workflow_js
    assert 'workflowSavedComparisonTargetIds' in workflow_js
    assert 'const workflowAnalysisPerDocumentGroup = document.getElementById("workflow-analysis-per-document-group");' in workflow_js
    assert 'setElementVisibility(workflowAnalysisPerDocumentGroup, actionType === DOCUMENT_ACTION_ANALYZE);' in workflow_js
    assert 'workflowAnalysisPerDocumentToggle.checked = false;' in workflow_js
    assert 'const workflowComparisonModalEl = document.getElementById("workflow-comparison-modal");' in workflow_js
    assert 'function renderWorkflowComparisonUi()' in workflow_js
    assert 'function assignWorkflowComparisonSource(versionId)' in workflow_js
    assert 'function assignWorkflowComparisonTarget(versionId)' in workflow_js
    assert 'workflowComparisonBoard?.addEventListener("click", handleWorkflowComparisonBoardClick);' in workflow_js
    assert 'workflowComparisonEditBtn?.addEventListener("click", () => {' in workflow_js
    assert 'workflowComparisonModal?.show();' in workflow_js
    assert 'window.addEventListener("chat:document-selection-changed"' in workflow_js
    assert 'window.addEventListener("chat:scope-changed"' in workflow_js
    assert 'const DOCUMENT_ACTION_SEARCH = "search";' in workflow_js
    assert 'target_mode: documentActionType !== DOCUMENT_ACTION_NONE ? analysisTargetMode : DOCUMENT_ANALYSIS_TARGET_SELECTED' in workflow_js
    assert 'recent_window_minutes: Number(rawRecentMinutes)' in workflow_js
    assert 'documentActionType === DOCUMENT_ACTION_SEARCH && analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_SELECTED' in workflow_js
    assert 'documentActionType === DOCUMENT_ACTION_COMPARISON && analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_SELECTED' in workflow_js
    assert 'documentActionType !== DOCUMENT_ACTION_NONE && analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_RECENT' in workflow_js
    assert 'const targetDocumentIds = analysisTargetMode === DOCUMENT_ANALYSIS_TARGET_RECENT' in workflow_js
    assert 'setEffectiveScopes(pickerScopes, {' in workflow_js
    assert 'force: workflowWorkspaceConfig.scope === "group"' in workflow_js
    assert 'if (docDropdownButton)' in chat_documents_js
    assert 'function syncWorkspaceNameMaps()' in chat_documents_js


def test_recent_target_backend_normalization() -> None:
    print('Testing recent workflow target backend normalization...')
    document_actions = importlib.import_module('functions_document_actions')

    search_action = document_actions.normalize_document_action_config({
        'type': 'search',
        'document_ids': [],
        'target_mode': 'recent_documents',
        'recent_window_minutes': '5',
        'doc_scope': 'personal',
    })

    assert search_action['type'] == 'search'
    assert search_action['target_mode'] == 'recent'
    assert search_action['recent_window_minutes'] == 5
    assert search_action['document_ids'] == []

    selected_search_action = document_actions.normalize_document_action_config(
        {
            'type': 'search',
            'document_ids': ['doc-a', 'doc-b'],
            'target_mode': 'selected',
        },
        max_documents_by_type={'search': 2},
    )

    assert selected_search_action['type'] == 'search'
    assert selected_search_action['document_ids'] == ['doc-a', 'doc-b']

    try:
        document_actions.normalize_document_action_config(
            {
                'type': 'search',
                'document_ids': ['doc-a', 'doc-b', 'doc-c'],
                'target_mode': 'selected',
            },
            max_documents_by_type={'search': 2},
        )
    except ValueError as exc:
        assert 'Document search supports up to 2 documents' in str(exc)
    else:
        raise AssertionError('Expected selected Search document limits to be enforced.')

    normalized_action = document_actions.normalize_document_action_config({
        'type': 'analyze',
        'document_ids': [],
        'target_mode': 'recent_documents',
        'recent_window_minutes': '7',
        'doc_scope': 'group',
        'active_group_ids': ['group-a'],
    })

    assert normalized_action['type'] == 'analyze'
    assert normalized_action['target_mode'] == 'recent'
    assert normalized_action['recent_window_minutes'] == 7
    assert normalized_action['document_ids'] == []
    assert normalized_action['doc_scope'] == 'group'
    assert normalized_action['active_group_ids'] == ['group-a']

    resolved_action = document_actions.normalize_document_action_config({
        'type': 'analyze',
        'document_ids': ['doc-new'],
        'target_mode': 'recent',
        'recent_targets_resolved': True,
    })

    assert resolved_action['document_ids'] == ['doc-new']
    assert resolved_action['target_mode'] == 'recent'
    assert resolved_action['recent_targets_resolved'] is True

    recent_comparison_action = document_actions.normalize_document_action_config({
        'type': 'comparison',
        'document_ids': [],
        'target_mode': 'recent',
        'recent_window_minutes': '11',
        'doc_scope': 'group',
        'active_group_ids': ['group-a'],
    })

    assert recent_comparison_action['type'] == 'comparison'
    assert recent_comparison_action['target_mode'] == 'recent'
    assert recent_comparison_action['recent_window_minutes'] == 11
    assert recent_comparison_action['document_ids'] == []
    assert recent_comparison_action['active_group_ids'] == ['group-a']

    resolved_comparison_action = document_actions.normalize_document_action_config({
        'type': 'comparison',
        'left_document_id': 'doc-newest',
        'right_document_ids': ['doc-older'],
        'target_mode': 'recent',
        'recent_targets_resolved': True,
    })

    assert resolved_comparison_action['document_ids'] == ['doc-newest', 'doc-older']
    assert resolved_comparison_action['left_document_id'] == 'doc-newest'
    assert resolved_comparison_action['right_document_ids'] == ['doc-older']
    assert resolved_comparison_action['recent_targets_resolved'] is True


def test_recent_target_runner_hooks() -> None:
    print('Testing recent target runner hooks...')
    workflow_runner = read_text(WORKFLOW_RUNNER_PY)
    document_actions = read_text(DOCUMENT_ACTIONS_PY)
    config = read_text(CONFIG_PY)

    assert 'VERSION = "0.241.188"' in config
    assert "DOCUMENT_ACTION_TYPE_SEARCH = 'search'" in document_actions
    assert "DOCUMENT_ACTION_TYPE_SEARCH: get_document_action_max_documents(" in document_actions
    assert 'DOCUMENT_ACTION_TARGET_MODE_RECENT' in document_actions
    assert 'normalize_recent_document_window_minutes' in document_actions
    assert "source_action['document_ids'] = ['__recent_document_window__']" in document_actions
    assert "normalized_action['recent_targets_resolved'] = True" in document_actions
    assert "if target_mode == DOCUMENT_ACTION_TARGET_MODE_RECENT and not recent_targets_resolved:" in document_actions
    assert 'def _resolve_recent_document_action_targets(' in workflow_runner
    assert 'def _prepare_workflow_search_context(' in workflow_runner
    assert 'def _build_workflow_search_prompt(' in workflow_runner
    assert 'cosmos_user_documents_container' in workflow_runner
    assert 'cosmos_group_documents_container' in workflow_runner
    assert 'cosmos_public_documents_container' in workflow_runner
    assert "c._ts >= @cutoff_ts" in workflow_runner
    assert "doc_scope = 'group'" in workflow_runner
    assert "'recent_targets_resolved': True" in workflow_runner
    assert 'if document_action.get(\'type\') == DOCUMENT_ACTION_TYPE_SEARCH:' in workflow_runner
    assert "document_action.get('type') in {DOCUMENT_ACTION_TYPE_ANALYZE, DOCUMENT_ACTION_TYPE_COMPARISON}" in workflow_runner
    assert "resolved_action['left_document_id'] = document_ids[0]" in workflow_runner
    assert "resolved_action['right_document_ids'] = document_ids[1:]" in workflow_runner
    assert 'search_documents(' in workflow_runner
    assert "'hybrid_citations': workflow_search_context.get('citations') or []" in workflow_runner
    assert 'workflow = _apply_runtime_document_action_config(workflow, action_config)' in workflow_runner


def run_tests() -> bool:
    tests = [
        test_workflow_modals_use_picker_contracts,
        test_workflow_picker_javascript_contracts,
        test_recent_target_backend_normalization,
        test_recent_target_runner_hooks,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            print('PASS')
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f'\nResults: {sum(results)}/{len(results)} tests passed')
    return all(results)


if __name__ == '__main__':
    sys.exit(0 if run_tests() else 1)
