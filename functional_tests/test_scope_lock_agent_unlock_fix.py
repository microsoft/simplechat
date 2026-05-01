#!/usr/bin/env python3
# test_scope_lock_agent_unlock_fix.py
"""
Functional test for the scope lock agent unlock fix.
Version: 0.241.052
Implemented in: 0.241.052

This test ensures an explicitly unlocked scope refreshes the agent pickers and
stops conversation-metadata filtering from keeping agents locked out.
"""

import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAT_AGENTS_FILE = os.path.join(
    REPO_ROOT,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-agents.js',
)
CHAT_DOCUMENTS_FILE = os.path.join(
    REPO_ROOT,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-documents.js',
)
CHAT_RETRY_FILE = os.path.join(
    REPO_ROOT,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-retry.js',
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
    'SCOPE_LOCK_AGENT_UNLOCK_FIX.md',
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


def test_agent_dropdown_honors_explicit_scope_unlock():
    """The main agent picker should bypass conversation-only guards after explicit unlock."""
    print('Testing main agent dropdown unlock wiring...')
    chat_agents_source = _read(CHAT_AGENTS_FILE)

    required_fragments = [
        "import { getEffectiveScopes, isScopeLocked, setEffectiveScopes } from './chat-documents.js';",
        'function shouldUseConversationScopeGuard(filteringContext) {',
        'isScopeLocked() !== false',
        'if (shouldUseConversationScopeGuard(filteringContext) && filteringContext.conversationScope === \'group\') {',
        'const hideUnavailableOptions = shouldUseConversationScopeGuard(filteringContext);',
    ]

    missing_fragments = [fragment for fragment in required_fragments if fragment not in chat_agents_source]
    if missing_fragments:
        raise AssertionError(f'Missing main agent unlock fragments: {missing_fragments}')

    print('  Main agent dropdown checks passed.')
    return True


def test_scope_toggle_dispatches_agent_refresh():
    """Unlocking scope should notify scope listeners so agent options refresh immediately."""
    print('Testing scope toggle refresh dispatch...')
    chat_documents_source = _read(CHAT_DOCUMENTS_FILE)

    required_fragments = [
        "runScopeRefreshPipeline('scope-lock').catch(error => {",
        "console.error('Failed to refresh scope-dependent UI after toggling scope lock:', error);",
    ]

    missing_fragments = [fragment for fragment in required_fragments if fragment not in chat_documents_source]
    if missing_fragments:
        raise AssertionError(f'Missing scope refresh fragments: {missing_fragments}')

    print('  Scope refresh dispatch checks passed.')
    return True


def test_retry_agent_dropdown_honors_explicit_scope_unlock():
    """Retry agent selection should follow the same unlocked scope rules."""
    print('Testing retry agent dropdown unlock wiring...')
    chat_retry_source = _read(CHAT_RETRY_FILE)

    required_fragments = [
        "import { getEffectiveScopes, isScopeLocked } from './chat-documents.js';",
        'const isExplicitlyUnlocked = isScopeLocked() === false;',
        'const unlockedGroupIds = Array.from(new Set((scopes.groupIds || []).filter(Boolean)));',
        'orderedAgents = [',
        '...(scopes.personal ? personalAgents : []),',
    ]

    missing_fragments = [fragment for fragment in required_fragments if fragment not in chat_retry_source]
    if missing_fragments:
        raise AssertionError(f'Missing retry agent unlock fragments: {missing_fragments}')

    print('  Retry agent dropdown checks passed.')
    return True


def test_version_and_fix_documentation_alignment():
    """Config version and fix documentation must stay aligned for this fix."""
    print('Testing version and documentation alignment...')
    version = _read_version()
    fix_doc_source = _read(FIX_DOC_FILE)

    if version != '0.241.052':
        raise AssertionError(f'Expected config VERSION to be 0.241.052, found {version}')
    if 'Fixed in version: **0.241.052**' not in fix_doc_source:
        raise AssertionError('Fix documentation is missing the current version header.')
    if 'explicitly unlocked' not in fix_doc_source.lower():
        raise AssertionError('Fix documentation is missing explicit unlock context.')
    if 'chat-agents.js' not in fix_doc_source or 'chat-documents.js' not in fix_doc_source:
        raise AssertionError('Fix documentation is missing the primary changed files.')

    print('  Version and documentation alignment checks passed.')
    return True


if __name__ == '__main__':
    tests = [
        test_agent_dropdown_honors_explicit_scope_unlock,
        test_scope_toggle_dispatches_agent_refresh,
        test_retry_agent_dropdown_honors_explicit_scope_unlock,
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