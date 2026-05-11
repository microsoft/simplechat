# test_chat_ai_message_min_width_fix.py
"""
Functional test for AI message minimum width.
Version: 0.240.084
Implemented in: 0.240.084

This test ensures short AI messages keep a larger minimum bubble width so
message actions have enough room to remain visible.
"""

import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')
CHAT_CSS_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'static', 'css', 'chats.css')
FIX_DOC_FILE = os.path.join(
    ROOT_DIR,
    'docs',
    'explanation',
    'fixes',
    'AI_MESSAGE_MIN_WIDTH_FIX.md',
)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def test_ai_message_min_width_rule_present():
    """Verify AI message bubbles reserve extra minimum width for short responses."""
    print('🔍 Testing AI message minimum width rule...')

    chat_css = read_file_text(CHAT_CSS_FILE)
    ai_bubble_marker = '.ai-message .message-bubble {'
    ai_bubble_index = chat_css.find(ai_bubble_marker)

    assert ai_bubble_index != -1, 'Expected to find the AI message bubble CSS block.'

    ai_bubble_block = chat_css[ai_bubble_index:ai_bubble_index + 220]
    assert 'min-width: min(320px, 90%);' in ai_bubble_block

    print('✅ AI message minimum width rule passed')
    return True


def test_version_and_fix_documentation_alignment():
    """Verify version bump and fix documentation stay aligned."""
    print('🔍 Testing version and fix documentation alignment...')

    fix_doc_content = read_file_text(FIX_DOC_FILE)

    assert read_config_version() == '0.240.084'
    assert 'Fixed/Implemented in version: **0.240.084**' in fix_doc_content
    assert 'VERSION = "0.240.084"' in fix_doc_content
    assert 'min(320px, 90%)' in fix_doc_content
    assert 'short ai messages' in fix_doc_content.lower()

    print('✅ Version and fix documentation alignment passed')
    return True


if __name__ == '__main__':
    tests = [
        test_ai_message_min_width_rule_present,
        test_version_and_fix_documentation_alignment,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    raise SystemExit(0 if success else 1)