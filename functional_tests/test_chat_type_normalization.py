#!/usr/bin/env python3
"""
Functional test for chat type normalization.
Version: 0.261.047
Implemented in: 0.236.065; expanded in 0.261.047

This test ensures new conversations are marked with chat_type "new" and
personal conversations normalize to "personal_single_user" across the UI
and backend metadata paths, including collaboration participant eligibility
before a freshly created personal chat is reloaded.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least


def _read_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _assert_contains(text, snippet, file_label):
    if snippet not in text:
        raise AssertionError(f"Missing '{snippet}' in {file_label}")


def test_chat_type_normalization():
    """Verify chat_type normalization is wired across UI and backend."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    js_conversations_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "static",
        "js",
        "chat",
        "chat-conversations.js",
    )
    js_sidebar_conversations_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "static",
        "js",
        "chat",
        "chat-sidebar-conversations.js",
    )
    js_collaboration_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "static",
        "js",
        "chat",
        "chat-collaboration.js",
    )
    js_details_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "static",
        "js",
        "chat",
        "chat-conversation-details.js",
    )
    backend_conversations_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "route_backend_conversations.py",
    )
    backend_chats_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "route_backend_chats.py",
    )
    metadata_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "functions_conversation_metadata.py",
    )

    js_conversations = _read_file(js_conversations_path)
    js_sidebar_conversations = _read_file(js_sidebar_conversations_path)
    js_collaboration = _read_file(js_collaboration_path)
    js_details = _read_file(js_details_path)
    backend_conversations = _read_file(backend_conversations_path)
    backend_chats = _read_file(backend_chats_path)
    metadata = _read_file(metadata_path)

    assert_app_version_at_least("0.261.047", repo_root)

    _assert_contains(js_conversations, 'chat_type: "new"', "chat-conversations.js")
    _assert_contains(js_conversations, "['personal', 'new'].includes(convo.chat_type)", "chat-conversations.js")
    _assert_contains(js_sidebar_conversations, "chatType === 'personal' || chatType === 'new'", "chat-sidebar-conversations.js")
    _assert_contains(js_collaboration, "normalizedChatType === 'personal' || normalizedChatType === 'new'", "chat-collaboration.js")
    _assert_contains(js_conversations, 'personal_single_user', "chat-conversations.js")
    _assert_contains(js_details, "function canManageLegacyConversationParticipants", "chat-conversation-details.js")
    _assert_contains(js_details, "canInviteParticipants", "chat-conversation-details.js")
    _assert_contains(js_details, 'personal_single_user', "chat-conversation-details.js")
    _assert_contains(backend_conversations, "chat_type in ('personal', 'new')", "route_backend_conversations.py")
    _assert_contains(backend_conversations, "personal_single_user", "route_backend_conversations.py")
    _assert_contains(backend_chats, "personal_single_user", "route_backend_chats.py")
    _assert_contains(metadata, "personal_single_user", "functions_conversation_metadata.py")

    print("✅ Chat type normalization verified")
    return True


if __name__ == "__main__":
    success = test_chat_type_normalization()
    sys.exit(0 if success else 1)
