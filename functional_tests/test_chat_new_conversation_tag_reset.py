# test_chat_new_conversation_tag_reset.py
"""
Functional test for chat tag reset on new conversation.
Version: 0.240.026
Implemented in: 0.240.026

This test ensures that rebuilding the chat tag list clears stale tag
selection UI state so starting a new conversation resets the tag selector
label and document filtering back to the default state.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAT_DOCUMENTS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-documents.js',
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'config.py',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_load_tags_for_scope_resets_tag_selection_state_before_rebuild():
    """Verify tag selection UI state is cleared before in-scope tags are rebuilt."""
    print('🔍 Testing chat tag reset before tag reload...')

    content = read_file(CHAT_DOCUMENTS_FILE)

    required_snippets = [
        'function resetTagSelectionState() {',
        'tagsSearchController?.resetFilter();',
        'syncTagsDropdownButtonText();',
        'filterDocumentsBySelectedTags();',
        "chatTagsFilter.innerHTML = '';",
        "if (tagsDropdownItems) tagsDropdownItems.innerHTML = '';",
        'resetTagSelectionState();',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in content]
    assert not missing, f'Missing tag reset snippets: {missing}'

    load_tags_block = """export async function loadTagsForScope() {
  if (!chatTagsFilter) return;

  // Clear existing options in both hidden select and custom dropdown
  chatTagsFilter.innerHTML = '';
  if (tagsDropdownItems) tagsDropdownItems.innerHTML = '';
  resetTagSelectionState();
"""
    assert load_tags_block in content, 'Expected loadTagsForScope to reset tag UI state immediately after clearing options.'

    print('✅ chat tag reset before reload passed')
    return True


def test_config_version_is_bumped_for_chat_tag_reset_fix():
    """Verify config version was bumped for the new conversation tag reset fix."""
    print('🔍 Testing config version bump...')

    config_content = read_file(CONFIG_FILE)
    assert 'VERSION = "0.240.026"' in config_content, 'Expected config.py version 0.240.026'

    print('✅ Config version bump passed')
    return True


if __name__ == '__main__':
    tests = [
        test_load_tags_for_scope_resets_tag_selection_state_before_rebuild,
        test_config_version_is_bumped_for_chat_tag_reset_fix,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
