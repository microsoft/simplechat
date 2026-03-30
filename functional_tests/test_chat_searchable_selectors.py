#!/usr/bin/env python3
# test_chat_searchable_selectors.py
"""
Functional test for grouped searchable chat selectors.
Version: 0.239.195
Implemented in: 0.239.195

This test ensures that the chat page exposes grouped searchable selectors for
documents, prompts, models, and agents, that grouped headers are preserved by
the shared renderer during search, and that chat prompt data is preloaded for
personal, group, and public workspace scopes.
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
ROUTE_FRONTEND_CHATS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'route_frontend_chats.py',
)
PROMPTS_FUNCTIONS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'functions_prompts.py',
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
            'window.chatPromptOptions = JSON.parse',
            'window.chatAgentOptions = JSON.parse',
            'window.chatModelOptions = JSON.parse',
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


def test_shared_search_helper_supports_grouped_single_selects():
    """Verify the shared helper supports grouped searchable single-select sections."""
    print('🔍 Testing shared searchable select helper grouped rendering...')

    try:
        content = read_file(CHAT_SEARCHABLE_SELECT_FILE)

        required_snippets = [
            'export function initializeFilterableDropdownSearch',
            'export function createSearchableSingleSelect',
            'function createDropdownHeader(label) {',
            'const getTopLevelEntries = () => Array.from(selectEl.children)',
            "if (entry.tagName === 'OPTGROUP') {",
            'updateDropdownStructure(itemsContainerEl);',
            "itemsContainerEl.appendChild(createNoMatchesElement(emptyMessage));",
            "selectEl.dispatchEvent(new Event('change', { bubbles: true }));",
            'const observer = new MutationObserver(() => {',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing shared helper logic: {missing}'

        print('✅ Shared grouped searchable select helper passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_scope_tag_and_document_search_are_wired_in_chat_documents():
    """Verify scope, tags, and documents all use grouped searchable dropdown wiring."""
    print('🔍 Testing scope/tag/document grouped search wiring...')

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
            'function appendDocumentSection(sectionLabel, documents, sectionIndex) {',
            "docDropdownItems.appendChild(createDropdownHeader(sectionLabel));",
            "label: `[Group] ${group.name || 'Unnamed Group'}`",
            "label: `[Public] ${workspace.name || 'Unnamed Workspace'}`",
            'appendDocumentSection(section.label, section.documents, sectionIndex);',
            "documentSearchController?.applyFilter(docSearchInput ? docSearchInput.value : '');",
            "tagsSearchController?.applyFilter(tagsSearchInput ? tagsSearchInput.value : '');",
            "scopeSearchController?.applyFilter(scopeSearchInput ? scopeSearchInput.value : '');",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing scope/tag/document search wiring: {missing}'

        print('✅ Scope/tag/document grouped search wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_prompt_selector_uses_preloaded_grouped_catalog():
    """Verify prompt loading uses preloaded grouped chat prompt catalogs."""
    print('🔍 Testing prompt selector grouped preloaded catalog wiring...')

    try:
        content = read_file(CHAT_PROMPTS_FILE)

        required_snippets = [
            'import { createSearchableSingleSelect } from "./chat-searchable-select.js";',
            'function getPreloadedPromptOptions() {',
            'window.chatPromptOptions',
            'function buildPromptSections(scopes) {',
            'promptSelectorController = createSearchableSingleSelect({',
            'const optGroup = document.createElement("optgroup");',
            'optGroup.label = section.label;',
            'window.addEventListener("chat:scope-changed", () => {',
            'promptSelect.dispatchEvent(new Event("change", { bubbles: true }));',
            'loadAllPromptsPromise = Promise.all([loadUserPrompts(), loadGroupPrompts(), loadPublicPrompts()])',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing prompt searchable selector logic: {missing}'

        print('✅ Prompt selector grouped preloaded catalog wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_model_and_agent_selectors_use_grouped_scope_sections():
    """Verify model and agent selectors build grouped sections and clear-scope actions."""
    print('🔍 Testing model and agent grouped selector wiring...')

    try:
        model_content = read_file(CHAT_MODEL_SELECTOR_FILE)
        agent_content = read_file(CHAT_AGENTS_FILE)

        model_snippets = [
            "import { createSearchableSingleSelect } from './chat-searchable-select.js';",
            'export function initializeModelSelector()',
            'modelSelectorController = createSearchableSingleSelect({',
            "[Group] ${group.name || 'Unnamed Group'}",
            "actionButton.textContent = 'Use all available workspaces';",
            "const optGroup = document.createElement('optgroup');",
            'modelOption.disabled = option.disabled;',
        ]
        agent_snippets = [
            "import { createSearchableSingleSelect } from './chat-searchable-select.js';",
            'function initializeAgentSelector() {',
            'agentSelectorController = createSearchableSingleSelect({',
            "[Group] ${group.name || 'Unnamed Group'}",
            "actionButton.textContent = 'Use all available workspaces';",
            "const optGroup = document.createElement('optgroup');",
            'option.disabled = agent.disabled;',
            'agentSelectorController?.refresh();',
        ]

        missing_model = [snippet for snippet in model_snippets if snippet not in model_content]
        missing_agent = [snippet for snippet in agent_snippets if snippet not in agent_content]
        assert not missing_model, f'Missing model selector wiring: {missing_model}'
        assert not missing_agent, f'Missing agent selector wiring: {missing_agent}'

        print('✅ Model and agent grouped selector wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_chat_prompt_catalog_is_bootstrapped_from_backend_scope_data():
    """Verify chat prompt catalogs are built on the chats route from scoped prompt data."""
    print('🔍 Testing backend chat prompt catalog bootstrap...')

    try:
        route_content = read_file(ROUTE_FRONTEND_CHATS_FILE)
        prompt_functions_content = read_file(PROMPTS_FUNCTIONS_FILE)

        required_route_snippets = [
            'def _serialize_chat_prompt_option(prompt, *, scope_type, scope_id=None, scope_name=None):',
            'def _build_chat_prompt_catalog(*, user_id, settings, user_groups_raw, user_visible_public_workspaces):',
            "list_all_prompts_for_scope(user_id, 'user_prompt')",
            "'group_prompt',",
            "public_workspace_id=workspace_id",
            'chat_prompt_options=chat_prompt_options,',
        ]
        required_prompt_function_snippets = [
            'def list_all_prompts_for_scope(user_id, prompt_type, group_id=None, public_workspace_id=None):',
            'cosmos_public_prompts_container',
            'cosmos_group_prompts_container',
            'cosmos_user_prompts_container',
        ]

        missing_route = [snippet for snippet in required_route_snippets if snippet not in route_content]
        missing_prompt_functions = [snippet for snippet in required_prompt_function_snippets if snippet not in prompt_functions_content]
        assert not missing_route, f'Missing chats route prompt bootstrap snippets: {missing_route}'
        assert not missing_prompt_functions, f'Missing prompt helper snippets: {missing_prompt_functions}'

        print('✅ Backend chat prompt catalog bootstrap passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_version_bumped_for_grouped_chat_selector_change():
    """Verify config version was bumped for the grouped selector feature."""
    print('🔍 Testing config version bump...')

    try:
        config_content = read_file(CONFIG_FILE)
        assert 'VERSION = "0.239.195"' in config_content, 'Expected config.py version 0.239.195'

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
        test_shared_search_helper_supports_grouped_single_selects,
        test_scope_tag_and_document_search_are_wired_in_chat_documents,
        test_prompt_selector_uses_preloaded_grouped_catalog,
        test_model_and_agent_selectors_use_grouped_scope_sections,
        test_chat_prompt_catalog_is_bootstrapped_from_backend_scope_data,
        test_version_bumped_for_grouped_chat_selector_change,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)