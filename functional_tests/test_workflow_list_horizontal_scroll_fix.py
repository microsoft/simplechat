#!/usr/bin/env python3
# test_workflow_list_horizontal_scroll_fix.py
"""
Functional test for workflow list horizontal scroll fix.
Version: 0.241.045
Implemented in: 0.241.045

This test ensures the personal workspace workflow list uses a fixed-width table
layout without the oversized action-column minimum width that previously forced
a desktop horizontal scrollbar.
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
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'config.py',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_workflow_list_horizontal_scroll_fix_contract():
    """Verify the workflow list layout no longer hard-codes desktop overflow."""
    print('🔍 Testing workflow list horizontal scroll fix...')

    try:
        template_content = read_file(WORKSPACE_TEMPLATE_FILE)
        workflows_content = read_file(WORKFLOWS_JS_FILE)
        config_content = read_file(CONFIG_FILE)

        required_template_snippets = [
            '#workflows-table {',
            'table-layout: fixed;',
            '.workflow-action-buttons {',
            'white-space: normal;',
            '@media (max-width: 991.98px) {',
            'table-layout: auto;',
        ]
        missing_template = [snippet for snippet in required_template_snippets if snippet not in template_content]
        assert not missing_template, f'Missing workflow no-scroll layout snippets: {missing_template}'
        assert 'min-width: 340px;' not in template_content, 'Did not expect the oversized workflow actions min-width to remain.'
        print('✅ Workflow table layout styles now avoid desktop overflow')

        assert 'workflow-action-buttons d-flex flex-wrap gap-1' in workflows_content, (
            'Expected workflow actions container to expose the workflow-action-buttons class.'
        )
        print('✅ Workflow action buttons expose the dedicated wrapping hook')

        assert 'VERSION = "0.241.045"' in config_content, 'Expected config.py version 0.241.045'
        print('✅ Version properly updated to 0.241.045 in config.py')

        print('✅ Workflow horizontal scroll fix checks passed!')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print('🧪 Running Workflow List Horizontal Scroll Fix Tests...\n')

    tests = [
        test_workflow_list_horizontal_scroll_fix_contract,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)