# test_collaboration_metadata_and_mentions_fix.py
"""
Functional test for collaboration metadata and participant mention fixes.
Version: 0.241.017
Implemented in: 0.241.017

This test ensures collaborative conversations normalize metadata for shared
messages, expose metadata controls for collaborator bubbles, and treat @user
matches against existing conversation participants as in-message tags instead
of always opening the participant invite flow.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS_COLLABORATION_FILE = REPO_ROOT / 'application' / 'single_app' / 'functions_collaboration.py'
ROUTE_FRONTEND_CONVERSATIONS_FILE = REPO_ROOT / 'application' / 'single_app' / 'route_frontend_conversations.py'
ROUTE_BACKEND_COLLABORATION_FILE = REPO_ROOT / 'application' / 'single_app' / 'route_backend_collaboration.py'
CHAT_COLLABORATION_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-collaboration.js'
CHAT_MESSAGES_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-messages.js'
CHATS_CSS_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'css' / 'chats.css'


def read_text(path):
    return path.read_text(encoding='utf-8')


def test_collaboration_metadata_and_mentions_fix():
    functions_source = read_text(FUNCTIONS_COLLABORATION_FILE)
    frontend_route_source = read_text(ROUTE_FRONTEND_CONVERSATIONS_FILE)
    backend_route_source = read_text(ROUTE_BACKEND_COLLABORATION_FILE)
    collaboration_source = read_text(CHAT_COLLABORATION_FILE)
    messages_source = read_text(CHAT_MESSAGES_FILE)
    css_source = read_text(CHATS_CSS_FILE)

    assert 'def build_collaboration_message_metadata_payload' in functions_source
    assert 'def resolve_collaboration_mentions' in functions_source
    assert "'mentioned_participants'" in functions_source
    assert "'message_details'" in functions_source
    assert "'collaboration'" in functions_source

    assert 'build_collaboration_message_metadata_payload(message, conversation)' in frontend_route_source
    assert 'mentioned_participants = resolve_collaboration_mentions' in backend_route_source
    assert 'mentioned_participants=mentioned_participants' in backend_route_source

    assert 'action: \'tag\'' in collaboration_source
    assert 'function insertParticipantMention' in collaboration_source
    assert 'const mentionedParticipants = extractMentionedParticipantsFromMessage' in collaboration_source
    assert 'mentioned_participants: mentionedParticipants' in collaboration_source
    assert 'showToast(`${senderName} tagged you in a shared message.`' in collaboration_source

    assert 'function renderMentionTagsHtml' in messages_source
    assert 'function stripMentionTextFromMessageContent' in messages_source
    assert 'stripMentionTextFromMessageContent(messageContent, fullMessageObject)' in messages_source
    assert 'Tagged Participants' in messages_source
    assert 'Shared Conversation' in messages_source
    assert 'metadata-toggle-btn' in messages_source
    assert 'collaboration-mentions-block' in messages_source

    assert '.collaboration-mention-chip' in css_source
    assert '.collaboration-mention-chip-current-user' in css_source


if __name__ == '__main__':
    test_collaboration_metadata_and_mentions_fix()
    print('collaboration metadata and mention regression checks passed')