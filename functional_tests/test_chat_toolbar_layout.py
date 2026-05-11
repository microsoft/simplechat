# test_chat_toolbar_layout.py
#!/usr/bin/env python3
"""
Functional test for compact chat toolbar layout.
Version: 0.241.019
Implemented in: 0.241.019

This test ensures the chats toolbar keeps a mobile quick-action rail, exposes a
primary model selector, and routes secondary selectors and toggles through a
collapsible tools panel without changing the existing selector IDs.
"""

import os
import re
import sys


sys.path.append(os.path.dirname(os.path.abspath(__file__)))


def _read_text(relative_path):
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    with open(os.path.join(repo_root, relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def test_chat_toolbar_mobile_tools_panel_is_wired():
    """Verify the compact toolbar markup, CSS, and mobile coordination script exist."""
    print("🔍 Testing compact chat toolbar wiring...")

    try:
        template_text = _read_text("application/single_app/templates/chats.html")
        css_text = _read_text("application/single_app/static/css/chats.css")
        js_text = _read_text("application/single_app/static/js/chat/chat-mobile-toolbar.js")

        required_template_snippets = [
            'class="chat-toolbar-primary-row"',
            'class="chat-toolbar-actions chat-toolbar-action-rail"',
            'id="chat-mobile-tools-toggle"',
            'id="chat-mobile-tools-panel" class="collapse d-lg-flex chat-toolbar-secondary-panel"',
            'class="chat-toolbar-primary-selector"',
            'id="model-select-container" class="chat-toolbar-selector"',
            'id="prompt-selection-container" class="chat-toolbar-selector"',
            'id="agent-select-container" class="chat-toolbar-selector"',
        ]

        missing_template = [snippet for snippet in required_template_snippets if snippet not in template_text]
        if missing_template:
            print(f"❌ Missing compact toolbar template snippets: {', '.join(missing_template)}")
            return False

        required_css_snippets = [
            ".chat-toolbar {",
            ".chat-toolbar-primary-row {",
            ".chat-toolbar-action-rail {",
            ".chat-toolbar-primary-selector {",
            ".chat-toolbar-secondary-panel {",
            ".chat-mobile-tools-toggle {",
            "overflow-x: auto;",
            "scrollbar-width: none;",
            "@media (max-width: 991.98px) {",
            ".chat-toolbar-action-rail .search-btn-text,",
            "#search-documents-container .flex-shrink-0,",
        ]

        missing_css = [snippet for snippet in required_css_snippets if snippet not in css_text]
        if missing_css:
            print(f"❌ Missing toolbar layout CSS snippets: {', '.join(missing_css)}")
            return False

        required_js_snippets = [
            "function initializeChatMobileToolbar()",
            "const mobileToolsToggle = document.getElementById('chat-mobile-tools-toggle');",
            "const mobileToolsPanel = document.getElementById('chat-mobile-tools-panel');",
            "new MutationObserver(syncMobileToolsPanel)",
            "bootstrap.Collapse.getOrCreateInstance(panelElement, { toggle: false })",
            "window.requestAnimationFrame(syncMobileToolsPanel);",
        ]

        missing_js = [snippet for snippet in required_js_snippets if snippet not in js_text]
        if missing_js:
            print(f"❌ Missing mobile toolbar coordination snippets: {', '.join(missing_js)}")
            return False

        print("✅ Compact chat toolbar wiring passed")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_chat_toolbar_mobile_tools_panel_is_wired()
    print(f"\n📊 Results: {1 if success else 0}/1 tests passed")
    sys.exit(0 if success else 1)