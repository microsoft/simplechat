# test_collaboration_reply_and_avatar_fix.py
"""
Functional test for collaboration reply, avatar, and replay suppression fixes.
Version: 0.241.014
Implemented in: 0.241.014

This test ensures shared conversations expose the reply preview scaffold,
persist reply linkage when posting shared messages, hydrate collaborator
avatars when profile images exist, and suppress replayed collaboration events
from showing the same join or role toasts each time a shared conversation is
 reopened.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_COLLABORATION_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-collaboration.js'
CHAT_MESSAGES_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-messages.js'
CHATS_TEMPLATE_FILE = REPO_ROOT / 'application' / 'single_app' / 'templates' / 'chats.html'
CHATS_CSS_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'css' / 'chats.css'


def read_text(path):
    return path.read_text(encoding='utf-8')


def test_collaboration_reply_and_avatar_fix():
    collaboration_source = read_text(CHAT_COLLABORATION_FILE)
    messages_source = read_text(CHAT_MESSAGES_FILE)
    template_source = read_text(CHATS_TEMPLATE_FILE)
    css_source = read_text(CHATS_CSS_FILE)

    assert 'collaboration-reply-preview' in template_source
    assert 'collaboration-reply-cancel-btn' in template_source

    assert 'activeReplyContext' in collaboration_source
    assert 'replyToMessage' in collaboration_source
    assert 'getPendingMessageContext' in collaboration_source
    assert 'reply_to_message_id: activeReplyContext?.message_id || null' in collaboration_source
    assert 'seenCollaborationEventKeys' in collaboration_source
    assert 'isReplayEvent' in collaboration_source

    assert 'renderReplyQuoteHtml' in messages_source
    assert 'createCollaboratorAvatarHtml' in messages_source
    assert 'hydrateCollaboratorAvatar' in messages_source
    assert 'class="avatar collaborator-avatar"' in messages_source
    assert 'avatarElement.replaceWith(imageElement)' in messages_source
    assert 'dropdown-reply-btn' in messages_source
    assert 'window.chatCollaboration?.replyToMessage?.' in messages_source

    assert '.collaboration-reply-preview' in css_source
    assert '.collaboration-quote-block' in css_source
    assert '.avatar.avatar-initials' in css_source
    assert 'flex: 0 0 30px;' in css_source
    assert '.collaborator-message .message-content' in css_source


if __name__ == '__main__':
    test_collaboration_reply_and_avatar_fix()
    print('collaboration reply and avatar regression checks passed')