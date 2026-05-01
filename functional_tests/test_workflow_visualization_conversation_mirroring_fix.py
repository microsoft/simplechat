#!/usr/bin/env python3
# test_workflow_visualization_conversation_mirroring_fix.py
"""
Functional test for workflow visualization conversation mirroring.
Version: 0.241.052
Implemented in: 0.241.052

This test ensures workflow agent runs persist tool citations on the workflow
assistant message and mirror visualization outputs into any conversations the
workflow creates during the same run.
"""

import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_RUNNER_FILE = os.path.join(
    REPO_ROOT,
    'application',
    'single_app',
    'functions_workflow_runner.py',
)
CONFIG_FILE = os.path.join(
    REPO_ROOT,
    'application',
    'single_app',
    'config.py',
)
FIX_DOC_FILE = os.path.join(
    REPO_ROOT,
    'docs',
    'explanation',
    'fixes',
    'WORKFLOW_VISUALIZATION_CONVERSATION_MIRROR_FIX.md',
)


def _read(path):
    with open(path, encoding='utf-8') as file_handle:
        return file_handle.read()


def _read_version():
    config_source = _read(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    if not version_match:
        raise AssertionError('VERSION assignment not found in config.py')
    return version_match.group(1)


def test_workflow_runner_persists_agent_citations_on_workflow_messages():
    """Workflow assistant messages must now keep agent citations for renderable outputs."""
    print('Testing workflow assistant citation persistence...')
    workflow_runner_source = _read(WORKFLOW_RUNNER_FILE)

    required_fragments = [
        'def _build_agent_citations_from_invocations(user_id, conversation_id):',
        "'agent_citations': prepared_agent_citations,",
        "'agent_display_name': result.get('agent_display_name'),",
        "'agent_name': result.get('agent_name'),",
        "'agent_citations': agent_citations,",
    ]

    missing_fragments = [fragment for fragment in required_fragments if fragment not in workflow_runner_source]
    if missing_fragments:
        raise AssertionError(f'Missing workflow citation persistence fragments: {missing_fragments}')

    print('  Workflow assistant citation persistence checks passed.')
    return True


def test_workflow_runner_mirrors_visualizations_into_created_conversations():
    """Created conversations should receive the mirrored visualization assistant message."""
    print('Testing workflow-created conversation mirroring...')
    workflow_runner_source = _read(WORKFLOW_RUNNER_FILE)

    required_fragments = [
        'def _mirror_workflow_visualizations_to_created_conversations(workflow, source_assistant_doc, execution_result):',
        "'create_group_conversation',",
        "'create_personal_collaboration_conversation',",
        "'create_personal_conversation',",
        'mirror_source_message_to_collaboration(',
        '_mirror_assistant_message_to_personal_conversation(',
        '_filter_visualization_agent_citations(raw_agent_citations)',
        '_mirror_workflow_visualizations_to_created_conversations(',
    ]

    missing_fragments = [fragment for fragment in required_fragments if fragment not in workflow_runner_source]
    if missing_fragments:
        raise AssertionError(f'Missing workflow visualization mirroring fragments: {missing_fragments}')

    print('  Workflow-created conversation mirroring checks passed.')
    return True


def test_version_and_fix_documentation_alignment():
    """The shipped version and fix documentation should stay aligned."""
    print('Testing version and documentation alignment...')
    version = _read_version()
    fix_doc_source = _read(FIX_DOC_FILE)

    if version != '0.241.052':
        raise AssertionError(f'Expected config VERSION to be 0.241.052, found {version}')
    if 'Fixed in version: **0.241.052**' not in fix_doc_source:
        raise AssertionError('Fix documentation is missing the current version header.')
    if 'workflow conversation' not in fix_doc_source.lower():
        raise AssertionError('Fix documentation should mention the workflow conversation render path.')
    if 'created conversation' not in fix_doc_source.lower():
        raise AssertionError('Fix documentation should mention created conversation mirroring.')

    print('  Version and documentation alignment checks passed.')
    return True


if __name__ == '__main__':
    tests = [
        test_workflow_runner_persists_agent_citations_on_workflow_messages,
        test_workflow_runner_mirrors_visualizations_into_created_conversations,
        test_version_and_fix_documentation_alignment,
    ]
    results = []

    for test in tests:
        print(f'\n{"=" * 60}')
        print(f'Running {test.__name__}...')
        print('=' * 60)
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f'ERROR: {exc}')
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f'\n{"=" * 60}')
    print(f'Results: {passed}/{total} tests passed')
    print('=' * 60)
    sys.exit(0 if all(results) else 1)