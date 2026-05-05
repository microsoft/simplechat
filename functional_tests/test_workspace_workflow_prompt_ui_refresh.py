#!/usr/bin/env python3
# test_workspace_workflow_prompt_ui_refresh.py
"""
Functional test for the workspace workflow and prompt UI refresh.
Version: 0.241.045
Implemented in: 0.241.044

This test ensures the personal workspace workflows tab exposes the refreshed
list and grid views with consistent workflow actions, prompts expose the new
read-only view action, and agent chat buttons use the filled chat treatment.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE_TEMPLATE_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'templates',
    'workspace.html',
)
WORKFLOWS_JS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'workspace',
    'workspace_workflows.js',
)
PROMPTS_JS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'workspace',
    'workspace-prompts.js',
)
AGENTS_JS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'workspace',
    'workspace_agents.js',
)
VIEW_UTILS_JS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'workspace',
    'view-utils.js',
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'config.py',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_workspace_workflow_prompt_ui_refresh_contract():
    """Verify the refreshed workspace workflow and prompt UI contract exists in source."""
    print('🔍 Testing workspace workflow and prompt UI refresh contract...')

    try:
        template_content = read_file(WORKSPACE_TEMPLATE_FILE)
        workflows_content = read_file(WORKFLOWS_JS_FILE)
        prompts_content = read_file(PROMPTS_JS_FILE)
        agents_content = read_file(AGENTS_JS_FILE)
        view_utils_content = read_file(VIEW_UTILS_JS_FILE)
        config_content = read_file(CONFIG_FILE)

        required_template_snippets = [
            'id="workflows-view-list"',
            'id="workflows-view-grid"',
            'id="workflows-list-view"',
            'id="workflows-grid-view"',
            'Create personal workflows that run a selected agent or model manually or on an interval schedule.',
        ]
        missing_template = [snippet for snippet in required_template_snippets if snippet not in template_content]
        assert not missing_template, f'Missing workflow template refresh snippets: {missing_template}'
        assert '<h5 class="mb-1"><i class="bi bi-diagram-3 me-2"></i>Your Workflows</h5>' not in template_content, (
            'Expected the redundant workflows heading to be removed from the workspace tab.'
        )
        print('✅ Workflow workspace template now supports the refreshed toolbar and grid container')

        required_workflow_snippets = [
            'function renderWorkflowGrid(items) {',
            'setupViewToggle("workflows", "workflowsViewPreference"',
            'data-action="activity"',
            'btn btn-sm btn-primary',
            'btn btn-sm btn-outline-secondary" data-action="history"',
            'btn btn-sm btn-outline-danger" data-action="delete"',
            'Run in progress. Open Activity to follow the live timeline.',
        ]
        missing_workflows = [snippet for snippet in required_workflow_snippets if snippet not in workflows_content]
        assert not missing_workflows, f'Missing workflow renderer refresh snippets: {missing_workflows}'
        print('✅ Workflow renderer exposes list/grid views and the refreshed action vocabulary')

        required_prompt_snippets = [
            'window.onViewPrompt = function (promptId) {',
            "openViewModal(data, 'prompt'",
            'title="View Prompt"',
            'btn btn-sm btn-outline-info',
            'btn btn-sm btn-outline-secondary',
            'btn btn-sm btn-outline-danger',
        ]
        missing_prompts = [snippet for snippet in required_prompt_snippets if snippet not in prompts_content]
        assert not missing_prompts, f'Missing prompt view refresh snippets: {missing_prompts}'
        print('✅ Prompt rows expose the new view, edit, and delete icon buttons')

        assert 'bi bi-chat-dots-fill me-1' in agents_content, 'Expected filled chat icon in workspace agents list view.'
        assert 'type === "prompt"' in view_utils_content, 'Expected prompt support in the shared item view modal.'
        print('✅ Agent chat buttons and shared item view modal were refreshed')

        assert 'VERSION = "0.241.045"' in config_content, 'Expected config.py version 0.241.045'
        print('✅ Version properly updated to 0.241.045 in config.py')

        print('✅ Workspace workflow/prompt UI refresh checks passed!')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print('🧪 Running Workspace Workflow/Prompt UI Refresh Tests...\n')

    tests = [
        test_workspace_workflow_prompt_ui_refresh_contract,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
