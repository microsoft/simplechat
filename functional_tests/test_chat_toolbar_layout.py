# test_chat_toolbar_layout.py
#!/usr/bin/env python3
"""
Functional test for chat toolbar layout separation.
Version: 0.239.170
Implemented in: 0.239.170

This test ensures the chat selectors and toggle buttons remain separate sibling
groups, stay aligned on wide layouts, and switch to clean full-width toolbar
rows before overlap occurs on narrower layouts.
"""

import os
import re
import sys


sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _read_text(relative_path):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(repo_root, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def test_chat_toolbar_groups_are_responsive_without_overlap():
    """Verify the toolbar layout has both desktop and medium-width guardrails."""
    print("🔍 Testing chat toolbar group alignment...")

    try:
        template_text = _read_text("application/single_app/templates/chats.html")
        css_text = _read_text("application/single_app/static/css/chats.css")

        structure_pattern = re.compile(
            r'<div class="chat-toolbar-controls">.*?<div class="chat-toolbar-selectors">.*?</div>\s*<div class="chat-toolbar-toggles">',
            re.DOTALL,
        )

        if not structure_pattern.search(template_text):
            print("❌ Chat toolbar selectors and toggles are not separate sibling groups")
            return False

        required_css_snippets = [
            ".chat-toolbar {",
            "flex-wrap: nowrap;",
            "align-items: flex-end;",
            ".chat-toolbar-controls {",
            "flex-wrap: nowrap;",
            "align-items: flex-end;",
            ".chat-toolbar-toggles {",
            ".chat-toolbar-selectors {",
            "@media (max-width: 1200px) {",
            "flex: 1 1 100%;",
            "justify-content: flex-start;",
            "@media (max-width: 768px) {",
        ]

        missing_css = [snippet for snippet in required_css_snippets if snippet not in css_text]
        if missing_css:
            print(f"❌ Missing toolbar layout CSS snippets: {', '.join(missing_css)}")
            return False

        print("✅ Chat toolbar selectors and toggles remain aligned without medium-width overlap")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_chat_toolbar_groups_are_responsive_without_overlap()
    print(f"\n📊 Results: {1 if success else 0}/1 tests passed")
    sys.exit(0 if success else 1)