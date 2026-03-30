# test_chat_scope_selector_sync.py
"""
Functional test for chat scope selector synchronization.
Version: 0.239.194
Implemented in: 0.239.194

This test ensures that chat scope changes synchronize the agent and model
selectors, that explicit scoped selections can narrow the workspace context,
and that conversation metadata now carries the context needed to render
workspace badges immediately.
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
CHAT_AGENTS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-agents.js',
)
CHAT_MODEL_SELECTOR_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-model-selector.js',
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
CHAT_CONVERSATIONS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-conversations.js',
)
CHAT_STREAMING_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-streaming.js',
)
CONVERSATION_METADATA_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'functions_conversation_metadata.py',
)
BACKEND_CHATS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'route_backend_chats.py',
)
BACKEND_CONVERSATIONS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'route_backend_conversations.py',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def assert_contains(content, snippet, label):
    if snippet not in content:
        raise AssertionError(f"Missing '{snippet}' in {label}")


def test_scope_change_pipeline_is_exported_for_selector_sync():
    """Verify the chat documents module exposes programmatic scope changes and emits sync events."""
    print('🔍 Testing chat scope change pipeline exports...')

    content = read_file(CHAT_DOCUMENTS_FILE)

    required_snippets = [
        "function dispatchScopeChanged(source = 'workspace')",
        "window.dispatchEvent(new CustomEvent('chat:scope-changed'",
        "export function setEffectiveScopes(nextScopes = {}, options = {})",
        "return runScopeRefreshPipeline(options.source || 'programmatic')",
        "dispatchScopeChanged('workspace');",
    ]

    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f'Missing scope synchronization snippets: {missing}'

    print('✅ chat-documents scope change pipeline passed')
    return True


def test_agent_and_model_selectors_use_preloaded_scope_catalogs():
    """Verify agent and model selectors filter preloaded options and narrow only on explicit scoped selection."""
    print('🔍 Testing agent/model selector synchronization wiring...')

    agents_content = read_file(CHAT_AGENTS_FILE)
    model_content = read_file(CHAT_MODEL_SELECTOR_FILE)
    messages_content = read_file(CHAT_MESSAGES_FILE)

    agent_snippets = [
        'window.chatAgentOptions',
        "source: 'agent'",
        'await setEffectiveScopes(',
        'getConversationFilteringContext()',
    ]
    model_snippets = [
        'window.chatModelOptions',
        "source: 'model'",
        'dataset.selectionKey',
        'pendingScopeNarrowingModel = {',
        "modelDropdown.addEventListener('hidden.bs.dropdown'",
    ]
    message_snippets = [
        'active_public_workspace_ids: scopes.publicWorkspaceIds,',
        'const selectionKey = selectedOption?.dataset?.selectionKey || selectedModel;',
        'modelId = selectedOption?.dataset?.modelId || selectedOption?.value || null;',
    ]

    missing = [
        snippet for snippet in agent_snippets if snippet not in agents_content
    ]
    missing.extend([
        snippet for snippet in model_snippets if snippet not in model_content
    ])
    missing.extend([
        snippet for snippet in message_snippets if snippet not in messages_content
    ])

    assert not missing, f'Missing selector synchronization snippets: {missing}'

    print('✅ Agent/model selector synchronization passed')
    return True


def test_conversation_metadata_is_returned_for_immediate_badges():
    """Verify backend and streaming responses now expose the metadata needed for immediate badge refresh."""
    print('🔍 Testing conversation metadata propagation for immediate badges...')

    conversations_content = read_file(CHAT_CONVERSATIONS_FILE)
    streaming_content = read_file(CHAT_STREAMING_FILE)
    metadata_content = read_file(CONVERSATION_METADATA_FILE)
    backend_chats_content = read_file(BACKEND_CHATS_FILE)
    backend_conversations_content = read_file(BACKEND_CONVERSATIONS_FILE)

    required_snippets = {
        'chat-conversations.js': [
            'export function applyConversationMetadataUpdate(conversationId, updates = {})',
            'renderConversationHeaderBadges(convoItem);',
            "convoItem.removeAttribute('data-chat-state');",
        ],
        'chat-streaming.js': [
            'applyConversationMetadataUpdate(finalData.conversation_id, {',
            'context: finalData.context || [],',
            'chat_type: finalData.chat_type || null,',
            'if (finalData.scope_locked === true && finalData.locked_contexts) {',
        ],
        'functions_conversation_metadata.py': [
            'def _build_primary_context_from_scope_selection(',
            'active_public_workspace_ids=None',
            'primary_context = _build_primary_context_from_scope_selection(',
        ],
        'route_backend_chats.py': [
            "'context': conversation_item.get('context', []),",
            "'chat_type': conversation_item.get('chat_type'),",
            "'scope_locked': conversation_item.get('scope_locked'),",
            "active_public_workspace_ids = data.get('active_public_workspace_ids', [])",
        ],
        'route_backend_conversations.py': [
            "'context': conversation_item.get('context', []),",
            "'chat_type': conversation_item.get('chat_type')",
        ],
    }

    file_map = {
        'chat-conversations.js': conversations_content,
        'chat-streaming.js': streaming_content,
        'functions_conversation_metadata.py': metadata_content,
        'route_backend_chats.py': backend_chats_content,
        'route_backend_conversations.py': backend_conversations_content,
    }

    missing = []
    for label, snippets in required_snippets.items():
        content = file_map[label]
        for snippet in snippets:
            if snippet not in content:
                missing.append(f'{label}: {snippet}')

    assert not missing, f'Missing immediate metadata badge snippets: {missing}'

    print('✅ Conversation metadata propagation passed')
    return True


if __name__ == '__main__':
    tests = [
        test_scope_change_pipeline_is_exported_for_selector_sync,
        test_agent_and_model_selectors_use_preloaded_scope_catalogs,
        test_conversation_metadata_is_returned_for_immediate_badges,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)