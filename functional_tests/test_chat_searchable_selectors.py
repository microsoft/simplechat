#!/usr/bin/env python3
# test_chat_searchable_selectors.py
"""
Functional test for searchable chat selectors.
Version: 0.239.124
Implemented in: 0.239.124

This test ensures that the chat page adds search support for workspace scope,
tags, prompts, models, and agents, and that prompt loading fetches all pages so
the searchable prompt picker is not capped at the first prompt page. It also
verifies that the chat action buttons and selector controls use a responsive
toolbar layout instead of compressing active buttons into narrow columns.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHATS_TEMPLATE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'templates',
    'chats.html',
)
CHAT_DOCUMENTS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-documents.js',
)
CHAT_PROMPTS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-prompts.js',
)
CHAT_SEARCHABLE_SELECT_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-searchable-select.js',
)
CHAT_MODEL_SELECTOR_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-model-selector.js',
)
CHAT_AGENTS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-agents.js',
)
CHAT_CSS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'css',
    'chats.css',
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


def test_chat_template_contains_searchable_selectors():
    """Verify the chat template contains search inputs and custom selector shells."""
    print('🔍 Testing chat template searchable selector markup...')

    try:
        content = read_file(CHATS_TEMPLATE)

        required_snippets = [
            'id="scope-search-input"',
            'id="tags-search-input"',
            'class="chat-toolbar mb-2"',
            'class="chat-toolbar-actions"',
            'class="chat-toolbar-controls"',
            'class="chat-toolbar-toggles"',
            'class="chat-toolbar-selectors"',
            'id="prompt-dropdown"',
            'id="prompt-search-input"',
            'id="model-dropdown"',
            'id="model-search-input"',
            'id="agent-dropdown"',
            'id="agent-search-input"',
            'id="prompt-selection-container" class="chat-toolbar-selector"',
            'id="agent-select-container" class="chat-toolbar-selector"',
            'id="model-select-container" class="chat-toolbar-selector"',
            'chat-searchable-select',
            'id="prompt-select"',
            'id="model-select"',
            'id="agent-select"',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing searchable selector markup: {missing}'

        print('✅ Chat template searchable selector markup passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_chat_toolbar_layout_supports_wrapping_without_button_compression():
    """Verify the chat toolbar uses responsive layout rules for buttons and selectors."""
    print('🔍 Testing chat toolbar layout wiring...')

    try:
        content = read_file(CHAT_CSS_FILE)

        required_snippets = [
            '.chat-toolbar {',
            '.chat-toolbar-actions,',
            '.chat-toolbar-controls {',
            '.chat-toolbar-selectors {',
            '.chat-toolbar-selector {',
            '.chat-toolbar-selector .chat-searchable-select {',
            '.search-btn,',
            '.file-btn {',
            '@media (max-width: 1200px) {',
            '@media (max-width: 768px) {',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing responsive toolbar layout rules: {missing}'

        print('✅ Chat toolbar layout wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_shared_search_helper_supports_dropdown_filtering_and_single_selects():
    """Verify the shared helper supports both filterable dropdowns and searchable single-selects."""
    print('🔍 Testing shared searchable select helper...')

    try:
        content = read_file(CHAT_SEARCHABLE_SELECT_FILE)

        required_snippets = [
            'export function initializeFilterableDropdownSearch',
            'export function createSearchableSingleSelect',
            'updateDropdownStructure(itemsContainerEl);',
            "itemsContainerEl.appendChild(createNoMatchesElement(emptyMessage));",
            "selectEl.dispatchEvent(new Event('change', { bubbles: true }));",
            'const observer = new MutationObserver(() => {',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing shared helper logic: {missing}'

        print('✅ Shared searchable select helper passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_scope_tag_and_document_search_are_wired_in_chat_documents():
    """Verify scope, tags, and documents all use the shared filter helper."""
    print('🔍 Testing scope/tag/document search wiring...')

    try:
        content = read_file(CHAT_DOCUMENTS_FILE)

        required_snippets = [
            'const scopeSearchInput = document.getElementById("scope-search-input");',
            'const tagsSearchInput = document.getElementById("tags-search-input");',
            'const documentSearchController = initializeFilterableDropdownSearch({',
            'const scopeSearchController = initializeFilterableDropdownSearch({',
            'const tagsSearchController = initializeFilterableDropdownSearch({',
            "allItem.setAttribute('data-search-role', 'action');",
            "item.setAttribute('data-search-role', 'item');",
            "documentSearchController?.applyFilter(docSearchInput ? docSearchInput.value : '');",
            "tagsSearchController?.applyFilter(tagsSearchInput ? tagsSearchInput.value : '');",
            "scopeSearchController?.applyFilter(scopeSearchInput ? scopeSearchInput.value : '');",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing scope/tag/document search wiring: {missing}'

        print('✅ Scope/tag/document search wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_prompt_selector_pages_all_prompts_and_uses_searchable_select():
    """Verify prompt loading walks all pages and renders through the shared searchable select."""
    print('🔍 Testing prompt selector pagination and search wiring...')

    try:
        content = read_file(CHAT_PROMPTS_FILE)

        required_snippets = [
            'import { createSearchableSingleSelect } from "./chat-searchable-select.js";',
            'const promptPageSize = 100;',
            'async function fetchAllPromptPages(endpoint, emptyStatuses = []) {',
            'page_size: String(promptPageSize)',
            'prompts.length >= totalCount',
            'promptSelectorController = createSearchableSingleSelect({',
            'promptSelect.dispatchEvent(new Event("change", { bubbles: true }));',
            'loadAllPromptsPromise = Promise.all([loadUserPrompts(), loadGroupPrompts(), loadPublicPrompts()])',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing prompt searchable selector logic: {missing}'

        print('✅ Prompt selector pagination and search wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_model_and_agent_selectors_use_searchable_wrapper():
    """Verify model and agent selectors initialize the shared searchable wrapper."""
    print('🔍 Testing model and agent searchable selector wiring...')

    try:
        model_content = read_file(CHAT_MODEL_SELECTOR_FILE)
        agent_content = read_file(CHAT_AGENTS_FILE)

        model_snippets = [
            "import { createSearchableSingleSelect } from './chat-searchable-select.js';",
            'export function initializeModelSelector()',
            'modelSelectorController = createSearchableSingleSelect({',
        ]
        agent_snippets = [
            "import { createSearchableSingleSelect } from './chat-searchable-select.js';",
            'function initializeAgentSelector() {',
            'agentSelectorController = createSearchableSingleSelect({',
            'agentSelectorController?.refresh();',
        ]

        missing_model = [snippet for snippet in model_snippets if snippet not in model_content]
        missing_agent = [snippet for snippet in agent_snippets if snippet not in agent_content]
        assert not missing_model, f'Missing model selector wiring: {missing_model}'
        assert not missing_agent, f'Missing agent selector wiring: {missing_agent}'

        print('✅ Model and agent searchable selector wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_version_bumped_for_searchable_chat_selector_change():
    """Verify config version was bumped for the searchable selector feature."""
    print('🔍 Testing config version bump...')

    try:
        config_content = read_file(CONFIG_FILE)
        assert 'VERSION = "0.239.124"' in config_content, 'Expected config.py version 0.239.124'

        print('✅ Config version bump passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_chat_template_contains_searchable_selectors,
        test_chat_toolbar_layout_supports_wrapping_without_button_compression,
        test_shared_search_helper_supports_dropdown_filtering_and_single_selects,
        test_scope_tag_and_document_search_are_wired_in_chat_documents,
        test_prompt_selector_pages_all_prompts_and_uses_searchable_select,
        test_model_and_agent_selectors_use_searchable_wrapper,
        test_version_bumped_for_searchable_chat_selector_change,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)