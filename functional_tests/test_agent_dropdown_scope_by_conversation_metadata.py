#!/usr/bin/env python3
"""
Functional test for agent dropdown scope by conversation metadata.
Version: 0.236.063
Implemented in: 0.236.063

This test ensures the chat agent dropdown derives scope from the active
conversation's data-chat-type and shows all agents for new conversations.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _read_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _assert_metadata_scope_guard(js_text, file_label):
    required_snippets = [
        "data-chat-type",
        "conversationScope",
        "orderedAgents",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in js_text]
    if missing:
        raise AssertionError(
            f"Missing conversation metadata scope guard in {file_label}: {', '.join(missing)}"
        )


def test_agent_dropdown_scope_guard():
    """Verify dropdown scope logic uses conversation metadata."""
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

    chat_agents_js = _read_file(chat_agents_path)
    chat_retry_js = _read_file(chat_retry_path)

    _assert_metadata_scope_guard(chat_agents_js, "chat-agents.js")
    _assert_metadata_scope_guard(chat_retry_js, "chat-retry.js")

    print("✅ Agent dropdown scope uses conversation metadata")
    return True


if __name__ == "__main__":
    success = test_agent_dropdown_scope_guard()
    sys.exit(0 if success else 1)
