# test_collaboration_invite_access_and_actions_fix.py
"""
Functional test for collaboration invite access and personal shared chat actions.
Version: 0.241.011
Implemented in: 0.241.011

This test ensures pending invitees retain read-only access to collaborative
message/event loading and that converted personal shared conversations keep the
supported title, pin, and hide action wiring in the chat UI.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = REPO_ROOT / 'application' / 'single_app' / 'route_backend_collaboration.py'
HELPER_FILE = REPO_ROOT / 'application' / 'single_app' / 'functions_collaboration.py'
CHAT_CONVERSATIONS_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-conversations.js'
CHAT_SIDEBAR_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-sidebar-conversations.js'
CHAT_COLLABORATION_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-collaboration.js'


def read_text(path):
    return path.read_text(encoding='utf-8')


def test_pending_invite_access_and_actions_fix():
    route_source = read_text(ROUTE_FILE)
    helper_source = read_text(HELPER_FILE)
    conversation_source = read_text(CHAT_CONVERSATIONS_FILE)
    sidebar_source = read_text(CHAT_SIDEBAR_FILE)
    collaboration_source = read_text(CHAT_COLLABORATION_FILE)

    assert route_source.count('allow_pending=True') >= 2
    assert "/api/collaboration/conversations/<conversation_id>/pin" in route_source
    assert "/api/collaboration/conversations/<conversation_id>/hide" in route_source
    assert "def update_personal_collaboration_title" in helper_source
    assert "def toggle_personal_collaboration_pin" in helper_source
    assert "def toggle_personal_collaboration_hide" in helper_source

    assert "showPendingInviteToast" in collaboration_source
    assert "notifyPendingInvites" in collaboration_source

    assert "personal_multi_user" in conversation_source
    assert "sharedBadge.textContent = 'shared'" in conversation_source
    assert "/api/collaboration/conversations/${conversationId}/pin" in conversation_source
    assert "/api/collaboration/conversations/${conversationId}/hide" in conversation_source
    assert "/api/collaboration/conversations/${conversationId}" in conversation_source

    assert "/api/collaboration/conversations/${convo.id}/pin" in sidebar_source
    assert "/api/collaboration/conversations/${convo.id}/hide" in sidebar_source
    assert "Edit title" in sidebar_source


if __name__ == '__main__':
    test_pending_invite_access_and_actions_fix()
    print('collaboration invite access and action regression checks passed')