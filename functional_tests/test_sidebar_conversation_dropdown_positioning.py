#!/usr/bin/env python3
"""
Functional test for sidebar conversation dropdown positioning.
Version: 0.239.159
Implemented in: 0.239.159

This test ensures that sidebar conversation dropdown menus use non-static
positioning so they can render above scrolling containers during normal use
and during the chat tutorial.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
SIDEBAR_CONVERSATIONS_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-sidebar-conversations.js"
TUTORIAL_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-tutorial.js"


def test_sidebar_dropdown_positioning() -> bool:
    """Validate sidebar conversation dropdown positioning safeguards."""
    print("Testing sidebar conversation dropdown positioning...")

    sidebar_content = SIDEBAR_CONVERSATIONS_FILE.read_text(encoding="utf-8")
    tutorial_content = TUTORIAL_FILE.read_text(encoding="utf-8")

    required_sidebar_guards = [
        "function getSidebarConversationDropdownInstance(dropdownBtn)",
        "strategy: 'fixed'",
        "fallbackPlacements: ['top-end', 'bottom-end']",
    ]

    required_tutorial_guards = [
        'strategy: "fixed"',
        'fallbackPlacements: ["top-end", "bottom-end"]',
        'tutorial-force-popup',
    ]

    removed_sidebar_patterns = [
        'data-bs-display="static"',
    ]

    for guard in required_sidebar_guards:
        if guard not in sidebar_content:
            print(f"Missing sidebar dropdown guard: {guard}")
            return False

    for guard in required_tutorial_guards:
        if guard not in tutorial_content:
            print(f"Missing tutorial dropdown guard: {guard}")
            return False

    for pattern in removed_sidebar_patterns:
        if pattern in sidebar_content:
            print(f"Stale static dropdown positioning still present: {pattern}")
            return False

    print("Sidebar conversation dropdown positioning test passed!")
    return True


if __name__ == "__main__":
    success = test_sidebar_dropdown_positioning()
    sys.exit(0 if success else 1)
