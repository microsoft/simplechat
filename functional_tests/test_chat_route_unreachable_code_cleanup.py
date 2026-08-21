#!/usr/bin/env python3
# test_chat_route_unreachable_code_cleanup.py
"""
Functional test for chat route unreachable-code cleanup.
Version: 0.250.116
Implemented in: 0.250.116

This test ensures the stale, locally disabled kernel persistence branch that
triggered the PR #1145 CodeQL unreachable-code alert remains removed from the
chat route.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "application" / "single_app" / "config.py"
CHAT_ROUTE_FILE = ROOT / "application" / "single_app" / "route_backend_chats.py"
EXPECTED_VERSION = "0.250.116"


def read_text(path):
    """Return UTF-8 source text for simple route contract assertions."""
    return path.read_text(encoding="utf-8")


def read_current_version():
    """Return the application version declared in config.py."""
    for line in read_text(CONFIG_FILE).splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith('VERSION = '):
            return stripped_line.split('"')[1]
    raise AssertionError("Expected config.py to define VERSION")


def test_stale_kernel_persistence_branch_removed():
    """Validate the unreachable per-user kernel persistence branch is gone."""
    print("Testing chat route unreachable-code cleanup...")

    current_version = read_current_version()
    chat_route_content = read_text(CHAT_ROUTE_FILE)

    assert current_version == EXPECTED_VERSION, (
        f"Expected config.py version {EXPECTED_VERSION} for the unreachable-code cleanup."
    )
    assert "enable_redis_for_kernel" not in chat_route_content, (
        "Expected the locally disabled enable_redis_for_kernel guard to remain removed."
    )
    assert "save_user_kernel(" not in chat_route_content, (
        "Expected the unreachable save_user_kernel call to remain removed from the chat route."
    )

    print("Chat route unreachable-code cleanup checks passed")


if __name__ == "__main__":
    test_stale_kernel_persistence_branch_removed()