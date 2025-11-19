#!/usr/bin/env python3
# test_sidebar_group_badge_fix.py
"""
Functional test for sidebar group badge display.
Version: 0.233.162
Implemented in: 0.233.162

This test ensures that the sidebar conversation list injects a group badge
between the conversation title and dropdown whenever the conversation has
primary group context metadata.
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def test_sidebar_group_badge_script_update():
    """Verify sidebar script includes group badge markup and classes."""
    print("🔍 Testing sidebar group badge script update...")
    try:
        script_path = os.path.join(
            os.path.dirname(__file__),
            "../application/single_app/static/js/chat/chat-sidebar-conversations.js"
        )
        with open(script_path, "r", encoding="utf-8") as script_file:
            content = script_file.read()

        required_snippets = [
            "sidebar-conversation-group-badge",
            "badge.textContent = 'group'",
            "badge.classList.add('badge', 'bg-info', 'sidebar-conversation-group-badge')",
            "titleWrapper.appendChild(badge)"
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        if missing:
            print(f"❌ Missing expected code snippets: {missing}")
            return False

        print("✅ Sidebar script updated with group badge logic")
        return True
    except Exception as exc:  # pragma: no cover - defensive logging
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("🧪 Testing Sidebar Group Badge Fix...")
    print("=" * 70)

    tests = [
        test_sidebar_group_badge_script_update,
    ]

    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(tests)} tests passed")

    if success:
        print("✅ Sidebar group badge tests passed! Group conversations are clearly labeled in the sidebar.")
    else:
        print("❌ Some sidebar badge tests failed. Please review the implementation.")

    sys.exit(0 if success else 1)
