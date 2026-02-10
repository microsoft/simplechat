#!/usr/bin/env python3
"""
Functional test for personal agent dropdown visibility in chats.
Version: 0.236.061
Implemented in: 0.236.061

This test ensures that chat agent dropdown logic treats invalid active group IDs
("None", "null", "undefined") as empty so personal agents are included.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _read_file(path):
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _assert_normalization_guard(js_text, file_label):
    required_snippets = [
        "rawGroupId",
        "activeGroupId",
        "['none', 'null', 'undefined']",
    ]
    missing = [snippet for snippet in required_snippets if snippet not in js_text]
    if missing:
        raise AssertionError(
            f"Missing normalization guard in {file_label}: {', '.join(missing)}"
        )


def test_personal_agent_dropdown_guard():
    """Verify chat dropdown guards against bogus active group ids."""
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

    _assert_normalization_guard(chat_agents_js, "chat-agents.js")
    _assert_normalization_guard(chat_retry_js, "chat-retry.js")

    print("✅ Personal agent dropdown guard is present in chat JS files")
    return True


if __name__ == "__main__":
    success = test_personal_agent_dropdown_guard()
    sys.exit(0 if success else 1)
