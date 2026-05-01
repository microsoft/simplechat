# test_collaboration_shared_conversation_management_fix.py
"""
Functional test for collaboration shared conversation management fixes.
Version: 0.241.012
Implemented in: 0.241.012

This test ensures shared personal conversations now expose admin-role support,
shared delete or leave actions, collaboration-aware export and metadata paths,
and collaboration thought fallback for converted assistant transcripts.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / 'application' / 'single_app' / 'route_backend_collaboration.py'
HELPER_FILE = REPO_ROOT / 'application' / 'single_app' / 'functions_collaboration.py'
FRONTEND_ROUTE_FILE = REPO_ROOT / 'application' / 'single_app' / 'route_frontend_conversations.py'
THOUGHT_ROUTE_FILE = REPO_ROOT / 'application' / 'single_app' / 'route_backend_thoughts.py'
EXPORT_ROUTE_FILE = REPO_ROOT / 'application' / 'single_app' / 'route_backend_conversation_export.py'
CHAT_COLLABORATION_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-collaboration.js'
CHAT_CONVERSATIONS_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-conversations.js'
CHAT_DETAILS_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-conversation-details.js'
CHAT_EXPORT_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-export.js'
TEMPLATE_FILE = REPO_ROOT / 'application' / 'single_app' / 'templates' / 'chats.html'


def read_text(path):
    return path.read_text(encoding='utf-8')


def test_shared_conversation_management_fix():
    route_source = read_text(ROUTE_FILE)
    helper_source = read_text(HELPER_FILE)
    frontend_route_source = read_text(FRONTEND_ROUTE_FILE)
    thought_route_source = read_text(THOUGHT_ROUTE_FILE)
    export_route_source = read_text(EXPORT_ROUTE_FILE)
    collaboration_source = read_text(CHAT_COLLABORATION_FILE)
    conversation_source = read_text(CHAT_CONVERSATIONS_FILE)
    details_source = read_text(CHAT_DETAILS_FILE)
    export_source = read_text(CHAT_EXPORT_FILE)
    template_source = read_text(TEMPLATE_FILE)

    assert 'MEMBERSHIP_ROLE_ADMIN' in helper_source
    assert 'def update_personal_collaboration_member_role' in helper_source
    assert 'def leave_personal_collaboration_conversation' in helper_source
    assert 'def delete_personal_collaboration_conversation' in helper_source
    assert 'def get_accessible_collaboration_message_thoughts' in helper_source

    assert "/api/collaboration/conversations/<conversation_id>/members/<member_user_id>/role" in route_source
    assert "/api/collaboration/conversations/<conversation_id>/delete-action" in route_source
    assert 'collaboration.member.role_updated' in route_source
    assert 'collaboration.deleted' in route_source

    assert 'get_collaboration_message' in frontend_route_source
    assert 'assert_user_can_view_collaboration_conversation' in frontend_route_source

    assert 'get_accessible_collaboration_message_thoughts' in thought_route_source
    assert 'get_collaboration_message' in thought_route_source

    assert 'list_collaboration_messages' in export_route_source
    assert 'is_collaboration_conversation' in export_route_source
    assert 'get_accessible_collaboration_message_thoughts' in export_route_source

    assert 'reconcilePendingCollaborativeUserMessage' in collaboration_source
    assert 'updateParticipantRole' in collaboration_source
    assert 'window.hideConversationDetails?.();' in collaboration_source

    assert 'delete-conversation-modal' in conversation_source
    assert 'removeConversationFromUi' in conversation_source
    assert '/api/collaboration/conversations/${conversationId}/delete-action' in conversation_source

    assert 'toggle-participant-role' in details_source
    assert 'data-conversation-action="export"' in details_source
    assert 'data-conversation-action="delete"' in details_source
    assert 'hideConversationDetails' in details_source

    assert 'fetchCollaborationConversationList' in export_source

    assert 'conversation-details-actions' in template_source
    assert 'delete-conversation-modal' in template_source
    assert 'delete-conversation-new-owner-select' in template_source


if __name__ == '__main__':
    test_shared_conversation_management_fix()
    print('shared conversation management regression checks passed')