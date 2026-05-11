#!/usr/bin/env python3
"""
Functional test for new conversation agent/model refresh.
Version: 0.236.066
Implemented in: 0.236.066

This test ensures new conversations refresh both agent and model lists and
use activeGroupOid from user settings when loading group agents.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _read_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _assert_contains(text, snippet, file_label):
    if snippet not in text:
        raise AssertionError(f"Missing '{snippet}' in {file_label}")


def test_new_conversation_agent_model_refresh():
    """Verify refresh logic and activeGroupOid usage exist in UI code."""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    chat_agents_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "static",
        "js",
        "chat",
        "chat-agents.js",
    )
    chat_retry_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "static",
        "js",
        "chat",
        "chat-retry.js",
    )
    chat_conversations_path = os.path.join(
        repo_root,
        "application",
        "single_app",
        "static",
        "js",
        "chat",
        "chat-conversations.js",
    )

    chat_agents_js = _read_file(chat_agents_path)
    chat_retry_js = _read_file(chat_retry_path)
    chat_conversations_js = _read_file(chat_conversations_path)

    _assert_contains(chat_agents_js, "activeGroupOid", "chat-agents.js")
    _assert_contains(chat_agents_js, "fetchGroupAgentsForActiveGroup(activeGroupId)", "chat-agents.js")
    _assert_contains(chat_retry_js, "activeGroupOid", "chat-retry.js")
    _assert_contains(chat_conversations_js, "refreshModelSelection", "chat-conversations.js")

    print("✅ New conversation agent/model refresh logic verified")
    return True


if __name__ == "__main__":
    success = test_new_conversation_agent_model_refresh()
    sys.exit(0 if success else 1)
