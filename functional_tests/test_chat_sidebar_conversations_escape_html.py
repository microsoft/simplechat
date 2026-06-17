#!/usr/bin/env python3
# test_chat_sidebar_conversations_escape_html.py
"""
Functional test for chat sidebar conversation escaping import.
Version: 0.242.051
Implemented in: 0.242.051

This test ensures that the chat sidebar conversations module imports the shared
escapeHtml helper it uses and continues to pass the XSS sink guardrail.
"""

import importlib.util
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SIDEBAR_CONVERSATIONS_FILE = (
    ROOT_DIR / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-sidebar-conversations.js'
)
CHAT_UTILS_FILE = ROOT_DIR / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-utils.js'
XSS_CHECKER_FILE = ROOT_DIR / 'scripts' / 'check_xss_sinks.py'


def read_text(path: Path) -> str:
    """Read a UTF-8 text file from the repository."""
    return path.read_text(encoding='utf-8')


def load_xss_checker_module():
    """Import the XSS checker module from disk without changing sys.path."""
    spec = importlib.util.spec_from_file_location('check_xss_sinks', XSS_CHECKER_FILE)
    assert spec is not None and spec.loader is not None, 'Expected a module spec for check_xss_sinks.py'
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sidebar_conversations_imports_escape_html_helper() -> None:
    """Verify escapeHtml calls have an in-module import boundary."""
    sidebar_source = read_text(SIDEBAR_CONVERSATIONS_FILE)
    utils_source = read_text(CHAT_UTILS_FILE)

    assert 'escapeHtml(' in sidebar_source
    assert 'import { escapeHtml } from "./chat-utils.js";' in sidebar_source
    assert 'export function escapeHtml' in utils_source


def test_sidebar_conversations_uses_safe_error_and_icon_rendering() -> None:
    """Verify fixed sidebar paths do not reintroduce risky HTML sinks."""
    sidebar_source = read_text(SIDEBAR_CONVERSATIONS_FILE)

    assert 'sidebarConversationsList.replaceChildren(errorMessage);' in sidebar_source
    assert 'errorMessage.textContent = `Error loading conversations:' in sidebar_source
    assert 'sidebarConversationsList.innerHTML = `<div class="text-center p-2 text-danger small">Error loading conversations:' not in sidebar_source
    assert 'indicator.innerHTML' not in sidebar_source


def test_sidebar_conversations_passes_xss_guardrail() -> None:
    """Verify the full sidebar conversations file passes the XSS checker."""
    module = load_xss_checker_module()
    issues = module.inspect_file(SIDEBAR_CONVERSATIONS_FILE)

    assert issues == [], [module.format_error_annotation(issue) for issue in issues]


if __name__ == '__main__':
    tests = [
        test_sidebar_conversations_imports_escape_html_helper,
        test_sidebar_conversations_uses_safe_error_and_icon_rendering,
        test_sidebar_conversations_passes_xss_guardrail,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            print('✅ PASS')
            results.append(True)
        except Exception as exc:  # pragma: no cover - standalone script reporting
            print(f'❌ FAIL: {exc}')
            results.append(False)

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)