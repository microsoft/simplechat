# test_chat_upload_collaboration_workspace_sharing.py
#!/usr/bin/env python3
"""
Functional test for collaborative chat upload workspace sharing.
Version: 0.241.176
Implemented in: 0.241.175

This test ensures personal multi-user collaborative chat uploads resolve the
visible collaboration conversation to the hidden source conversation, share the
workspace-backed document with accepted participants, mirror the file message,
and reload the collaborative timeline in the browser.
"""

import sys
import traceback
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding='utf-8')


def assert_contains(source_text, expected_text, description):
    """Assert that a source file contains a required contract snippet."""
    if expected_text not in source_text:
        raise AssertionError(f"Missing {description}: {expected_text}")


def test_backend_collaboration_upload_contract():
    """Validate the upload route resolves, authorizes, shares, and mirrors collaborative uploads."""
    print("🔍 Testing backend collaborative upload contract...")
    route_source = read_repo_file('application/single_app/route_frontend_chats.py')

    required_snippets = [
        ('def _resolve_chat_upload_context(', 'upload context resolver'),
        ('def _resolve_collaboration_upload_context(', 'collaboration upload resolver'),
        ('assert_user_can_participate_in_collaboration_conversation(user_id, collaboration_conversation)', 'collaboration membership validation'),
        ('ensure_collaboration_source_conversation(', 'hidden source conversation resolution'),
        ("'chat_upload_collaboration_conversation_id': collaboration_conversation.get('id')", 'collaboration document metadata'),
        ("'chat_upload_collaboration_source_conversation_id': conversation_id", 'source conversation metadata'),
        ('sync_chat_upload_workspace_document_sharing_for_collaboration(collaboration_conversation)', 'workspace sharing sync'),
        ('mirror_source_message_to_collaboration(', 'source file message mirroring'),
        ('publish_collaboration_event(', 'live collaboration upload event publishing'),
        ("'conversation_id': response_conversation_id", 'visible conversation response id'),
        ("'source_conversation_id': conversation_id if is_collaboration_upload else None", 'source conversation response id'),
        ("'is_collaboration_upload': is_collaboration_upload", 'collaboration upload response flag'),
    ]

    for expected_text, description in required_snippets:
        assert_contains(route_source, expected_text, description)

    print("✅ Backend collaborative upload contract is present")
    return True


def test_document_sharing_sync_contract():
    """Validate collaboration sharing uses approved share entries and syncs search chunks."""
    print("🔍 Testing document sharing sync contract...")
    documents_source = read_repo_file('application/single_app/functions_documents.py')
    collaboration_source = read_repo_file('application/single_app/functions_collaboration.py')

    required_document_snippets = [
        ('def get_chat_upload_workspace_documents_for_collaboration(conversation_doc):', 'collaboration document lookup'),
        ("c.chat_upload_collaboration_conversation_id = @collaboration_conversation_id", 'collaboration metadata lookup'),
        ("c.conversation_id = @source_conversation_id", 'source conversation lookup'),
        ('def _merge_approved_shared_user_ids(', 'approved share merge helper'),
        ('approved_entry = f"{normalized_target_user_id},approved"', 'approved share entry format'),
        ('def _remove_shared_user_ids(', 'share revoke helper'),
        ("'chat_upload_auto_shared_user_ids': target_user_ids", 'auto managed share tracking'),
        ('set_document_chunk_visibility(', 'search chunk visibility propagation'),
        ("'revoked_user_ids': sorted(revoked_user_ids)", 'revoked user reporting'),
    ]

    for expected_text, description in required_document_snippets:
        assert_contains(documents_source, expected_text, description)

    required_lifecycle_snippets = [
        ('from functions_documents import sync_chat_upload_workspace_document_sharing_for_collaboration', 'collaboration sharing import'),
        ('if membership_status == MEMBERSHIP_STATUS_ACCEPTED and is_personal_collaboration_conversation(conversation_doc):', 'accepted invite sync trigger'),
        ('if is_personal_collaboration_conversation(conversation_doc):\n        sync_chat_upload_workspace_document_sharing_for_collaboration(conversation_doc)', 'member removal sync trigger'),
        ("revocation_conversation_doc['accepted_participant_ids'] = []", 'delete revocation participant reset'),
        ('def publish_collaboration_event(conversation_id, event_payload):', 'collaboration event publisher helper'),
    ]

    for expected_text, description in required_lifecycle_snippets:
        assert_contains(collaboration_source, expected_text, description)

    print("✅ Document sharing sync contract is present")
    return True


def test_collaboration_file_rendering_contract():
    """Validate mirrored workspace-backed file messages render as file cards in collaboration."""
    print("🔍 Testing collaboration file rendering contract...")
    models_source = read_repo_file('application/single_app/collaboration_models.py')
    collaboration_source = read_repo_file('application/single_app/functions_collaboration.py')
    chat_collaboration_js = read_repo_file('application/single_app/static/js/chat/chat-collaboration.js')
    chat_input_actions_js = read_repo_file('application/single_app/static/js/chat/chat-input-actions.js')

    required_snippets = [
        (models_source, "'role',", 'legacy mirror role copy'),
        (models_source, "'file_content_source',", 'legacy mirror file content source copy'),
        (models_source, "'workspace_document_id',", 'legacy mirror workspace document id copy'),
        (collaboration_source, "serialized_role = display_role if display_role in ('file', 'image') else message_doc.get('role')", 'serialized file display role'),
        (collaboration_source, "'file_content_source': message_doc.get('file_content_source')", 'serialized file content source'),
        (collaboration_source, "'workspace_document_id': message_doc.get('workspace_document_id')", 'serialized workspace document id'),
        (chat_collaboration_js, "message.role === 'file' || message.metadata?.source_role === 'file'", 'file source role detection'),
        (chat_collaboration_js, "const messageContent = senderType === 'File'", 'file message object rendering'),
        (chat_input_actions_js, 'const isCollaborationUpload = Boolean(', 'collaboration upload detection'),
        (chat_input_actions_js, 'window.chatCollaboration.activateConversation(uploadedConversationId)', 'collaboration timeline reload'),
        (chat_input_actions_js, 'watchChatWorkspaceUploadDocument(data.workspace_document_id, { autoSelect: true })', 'workspace progress watcher'),
    ]

    for source_text, expected_text, description in required_snippets:
        assert_contains(source_text, expected_text, description)

    print("✅ Collaboration file rendering contract is present")
    return True


def test_version_bump_contract():
    """Validate the feature version is recorded in config.py."""
    print("🔍 Testing version bump contract...")
    config_source = read_repo_file('application/single_app/config.py')
    assert_contains(config_source, 'VERSION = "0.241.176"', '0.241.176 version bump')
    print("✅ Version bump contract is present")
    return True


def run_all_tests():
    """Run all contract tests."""
    tests = [
        test_backend_collaboration_upload_contract,
        test_document_sharing_sync_contract,
        test_collaboration_file_rendering_contract,
        test_version_bump_contract,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:
            print(f"❌ {test.__name__} failed: {error}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f"\n📊 Results: {passed}/{len(tests)} tests passed")
    return all(results)


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)