#!/usr/bin/env python3
# test_chat_preserves_workspace_selection_on_auto_create.py
"""
Functional test for chat workspace selection preservation on implicit conversation creation.
Version: 0.239.105
Implemented in: 0.239.105

This test ensures that auto-creating a conversation from the chat input,
prompt picker, send flow, or file upload flow does not reset selected
workspace scope, tags, or documents back to the default state.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAT_DOCUMENTS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-documents.js',
)
CHAT_CONVERSATIONS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-conversations.js',
)
CHAT_ONLOAD_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-onload.js',
)
CHAT_INPUT_ACTIONS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-input-actions.js',
)
CHAT_MESSAGES_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-messages.js',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_scope_reset_supports_preserving_current_selections():
    """Verify scope reset can clear lock state without wiping active selections."""
    print('🔍 Testing resetScopeLock preserveSelections support...')

    try:
        content = read_file(CHAT_DOCUMENTS_FILE)

        required_snippets = [
            'export function resetScopeLock(options = {})',
            'const { preserveSelections = false } = options;',
            'if (preserveSelections) {',
            'buildScopeDropdown();',
            'updateScopeLockIcon();',
            'updateHeaderLockIcon();',
            'return;',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing preserveSelections reset support: {missing}'

        print('✅ resetScopeLock preserveSelections support passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_create_new_conversation_reuses_pending_request_and_respects_preserve_flag():
    """Verify createNewConversation preserves selections when requested and reuses in-flight creation."""
    print('🔍 Testing createNewConversation preserve path and in-flight reuse...')

    try:
        content = read_file(CHAT_CONVERSATIONS_FILE)

        required_snippets = [
            'let pendingConversationCreation = null;',
            'if (pendingConversationCreation) {',
            'await pendingConversationCreation;',
            'const { preserveSelections = false } = options;',
            'resetScopeLock({ preserveSelections });',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing createNewConversation preservation logic: {missing}'

        # Explicit New Conversation should still use the default full reset path.
        assert 'createNewConversation();' in content, (
            'Expected explicit New Conversation button flow to remain unchanged.'
        )

        print('✅ createNewConversation preserve path and in-flight reuse passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_implicit_conversation_creation_call_sites_preserve_workspace_filters():
    """Verify implicit create-conversation flows request preserved selections."""
    print('🔍 Testing implicit conversation creation call sites...')

    try:
        onload_content = read_file(CHAT_ONLOAD_FILE)
        input_actions_content = read_file(CHAT_INPUT_ACTIONS_FILE)
        messages_content = read_file(CHAT_MESSAGES_FILE)

        checks = {
            'input focus preserves selections': 'createNewConversation(null, { preserveSelections: true });' in onload_content,
            'prompt button preserves selections': onload_content.count('createNewConversation(null, { preserveSelections: true });') >= 2,
            'file button preserves selections': onload_content.count('createNewConversation(null, { preserveSelections: true });') >= 3,
            'file upload auto-create preserves selections': input_actions_content.count('}, { preserveSelections: true });') >= 2,
            'send flow preserves selections': '}, { preserveSelections: true });' in messages_content,
        }

        failed_checks = [name for name, passed in checks.items() if not passed]
        assert not failed_checks, f'Missing preserve-selection implicit creation paths: {failed_checks}'

        print('✅ Implicit conversation creation call sites passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_scope_reset_supports_preserving_current_selections,
        test_create_new_conversation_reuses_pending_request_and_respects_preserve_flag,
        test_implicit_conversation_creation_call_sites_preserve_workspace_filters,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)