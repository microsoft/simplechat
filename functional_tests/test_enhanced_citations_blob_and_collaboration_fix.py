# test_enhanced_citations_blob_and_collaboration_fix.py
"""
Functional test for enhanced citations blob resolution and collaboration artifact hydration.
Version: 0.241.048
Implemented in: 0.241.048

This test ensures enhanced citations resolve persisted blob references for
historical documents and that agent citation artifacts continue to hydrate
inside collaborative conversations after the inline visualization changes.
"""

import os
import re


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_ROOT = os.path.join(ROOT_DIR, 'application', 'single_app')
ROUTE_ENHANCED_CITATIONS_FILE = os.path.join(SINGLE_APP_ROOT, 'route_enhanced_citations.py')
ROUTE_FRONTEND_CONVERSATIONS_FILE = os.path.join(SINGLE_APP_ROOT, 'route_frontend_conversations.py')
CHAT_MESSAGES_FILE = os.path.join(SINGLE_APP_ROOT, 'static', 'js', 'chat', 'chat-messages.js')
CONFIG_FILE = os.path.join(SINGLE_APP_ROOT, 'config.py')
FIX_DOC = os.path.join(ROOT_DIR, 'docs', 'explanation', 'fixes', 'ENHANCED_CITATIONS_BLOB_AND_COLLABORATION_FIX.md')


def read_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    config_source = read_text(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    assert version_match, 'VERSION assignment not found in config.py'
    return version_match.group(1)


def test_enhanced_citations_use_persisted_blob_references_for_preview_and_rendering():
    """Verify enhanced citation routes resolve the persisted blob metadata helper."""
    print('🔍 Testing enhanced citation blob resolution...')

    route_source = read_text(ROUTE_ENHANCED_CITATIONS_FILE)

    required_snippets = [
        'from functions_documents import get_document_blob_storage_info',
        'def _resolve_document_blob_reference(raw_doc):',
        'container_name, blob_name = get_document_blob_storage_info(raw_doc)',
        'container_name, blob_name = _resolve_document_blob_reference(raw_doc)',
        'Blob reference is incomplete for this document',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in route_source]
    assert not missing, f'Missing blob-resolution snippets: {missing}'

    print('✅ Enhanced citation blob resolution passed')


def test_agent_citation_artifacts_support_collaboration_conversations():
    """Verify the agent citation artifact route falls back to collaboration source conversations."""
    print('🔍 Testing collaboration artifact hydration path...')

    route_source = read_text(ROUTE_FRONTEND_CONVERSATIONS_FILE)

    required_snippets = [
        'conversation = get_collaboration_conversation(conversation_id)',
        'assert_user_can_view_collaboration_conversation(user_id, conversation)',
        "artifact_lookup_conversation_id = str(conversation.get('source_conversation_id') or '').strip()",
        'conversation_messages = list_collaboration_messages(conversation_id)',
        'artifact_lookup_conversation_id != conversation_id',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in route_source]
    assert not missing, f'Missing collaboration artifact snippets: {missing}'

    print('✅ Collaboration artifact hydration path passed')


def test_chat_renderer_uses_message_scoped_conversation_ids_for_agent_artifacts():
    """Verify agent citation links and inline maps use the message conversation id."""
    print('🔍 Testing message-scoped conversation id propagation...')

    chat_messages_source = read_text(CHAT_MESSAGES_FILE)

    required_snippets = [
        'function resolveMessageConversationId(fullMessageObject = null)',
        'const messageConversationId = resolveMessageConversationId(fullMessageObject);',
        'data-conversation-id="${escapeHtml(messageConversationId)}"',
        'messageConversationId\n    );',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in chat_messages_source]
    assert not missing, f'Missing message conversation-id snippets: {missing}'

    print('✅ Message-scoped conversation id propagation passed')


def test_version_and_fix_documentation_alignment():
    """Verify config.py and the fix documentation reference the shipped version."""
    print('🔍 Testing version and documentation alignment...')

    version = read_config_version()
    fix_doc_source = read_text(FIX_DOC)

    assert version == '0.241.048', version
    assert 'Fixed/Implemented in version: **0.241.048**' in fix_doc_source
    assert 'persisted blob references' in fix_doc_source.lower()
    assert 'collaborative conversations' in fix_doc_source.lower()

    print('✅ Version and documentation alignment passed')


if __name__ == '__main__':
    tests = [
        test_enhanced_citations_use_persisted_blob_references_for_preview_and_rendering,
        test_agent_citation_artifacts_support_collaboration_conversations,
        test_chat_renderer_uses_message_scoped_conversation_ids_for_agent_artifacts,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'❌ Test failed: {exc}')
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)