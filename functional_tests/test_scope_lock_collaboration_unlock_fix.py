#!/usr/bin/env python3
# test_scope_lock_collaboration_unlock_fix.py
"""
Functional test for the collaboration scope lock unlock fix.
Version: 0.241.052
Implemented in: 0.241.051

This test ensures the scope lock toggle route supports collaborative
conversations, preserves locked contexts, and syncs the hidden source
conversation metadata instead of returning a 404 for collaboration ids.
"""

import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(
    REPO_ROOT,
    'application',
    'single_app',
    'route_backend_conversations.py',
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
    'SCOPE_LOCK_COLLABORATION_UNLOCK_FIX.md',
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


def test_scope_lock_route_supports_collaboration_conversations():
    """The scope lock route must resolve collaborative conversations before returning 404."""
    print('Testing collaboration fallback in scope lock route...')
    route_source = _read(ROUTE_FILE)

    required_fragments = [
        'assert_user_can_participate_in_collaboration_conversation',
        'ensure_collaboration_source_conversation',
        'get_collaboration_conversation',
        'def _load_scope_lock_conversation(conversation_id, user_id):',
        "return conversation_item, 'collaboration'",
        'conversation_item, conversation_kind = _load_scope_lock_conversation(conversation_id, user_id)',
        "if conversation_kind == 'collaboration':",
        'cosmos_collaboration_conversations_container.upsert_item(conversation_item)',
        'ensure_collaboration_source_conversation(conversation_item, current_user)',
    ]

    missing_fragments = [fragment for fragment in required_fragments if fragment not in route_source]
    if missing_fragments:
        raise AssertionError(f'Missing collaboration scope-lock fragments: {missing_fragments}')

    print('  Collaboration fallback checks passed.')
    return True


def test_scope_lock_route_preserves_locked_contexts_in_response():
    """The route must keep returning locked_contexts after the update path changes."""
    print('Testing locked_context response contract...')
    route_source = _read(ROUTE_FILE)

    required_fragments = [
        'conversation_item.get(\'locked_contexts\', [])',
        'conversation_item = _persist_scope_lock_update(',
        'conversation_item[\'scope_locked\'] = new_value',
    ]

    missing_fragments = [fragment for fragment in required_fragments if fragment not in route_source]
    if missing_fragments:
        raise AssertionError(f'Missing locked-context fragments: {missing_fragments}')

    print('  Locked context response checks passed.')
    return True


def test_version_and_fix_documentation_alignment():
    """Config version and fix documentation must stay aligned for this fix."""
    print('Testing version and documentation alignment...')
    version = _read_version()
    fix_doc_source = _read(FIX_DOC_FILE)

    if version != '0.241.052':
        raise AssertionError(f'Expected config VERSION to be 0.241.052, found {version}')
    if 'Fixed in version: **0.241.051**' not in fix_doc_source:
        raise AssertionError('Fix documentation is missing the current version header.')
    if '/api/conversations/<conversation_id>/scope_lock' not in fix_doc_source:
        raise AssertionError('Fix documentation is missing the affected route reference.')
    if 'collaborative conversations' not in fix_doc_source.lower():
        raise AssertionError('Fix documentation is missing collaboration scope context.')

    print('  Version and documentation alignment checks passed.')
    return True


if __name__ == '__main__':
    tests = [
        test_scope_lock_route_supports_collaboration_conversations,
        test_scope_lock_route_preserves_locked_contexts_in_response,
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