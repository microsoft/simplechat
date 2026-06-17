#!/usr/bin/env python3
# test_chat_searchable_selectors.py
"""
Functional test for grouped searchable chat selectors.
Version: 0.242.017
Implemented in: 0.242.017

This test ensures that the chat page exposes grouped searchable selectors for
documents, prompts, models, and agents, that grouped headers are preserved by
the shared renderer during search, and that chat prompt data is preloaded for
personal, group, and public workspace scopes while locked conversations hide
unavailable agents and models while grounded search becomes a mobile drawer
with an explicit mobile close control, a visible loading state for tags, and
responsive scope, tag, and document dropdown menu sizing.
It also verifies that the document dropdown opens upward on desktop and down in
the mobile grounded-search drawer.
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
CHAT_MOBILE_TOOLBAR_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-mobile-toolbar.js',
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
            'id="search-documents-container" class="chat-search-panel card p-0 mb-2 offcanvas-lg offcanvas-end"',
            'id="searchDocumentsDrawerLabel"',
            'class="chat-search-panel-grid"',
            'id="search-documents-mobile-close"',
            'class="chat-search-panel-mobile-footer d-lg-none"',
            'chat-search-filter-menu',
            'id="tags-dropdown-loading-spinner"',
            'Loading tags...',
            'class="chat-toolbar mb-2"',
            'class="chat-toolbar-primary-row"',
            'id="chat-toolbar-desktop-tools-slot"',
            'id="chat-toolbar-tools-surface" class="chat-toolbar-secondary-panel chat-toolbar-tools-surface"',
            'class="chat-toolbar-actions chat-toolbar-action-rail"',
            'class="chat-toolbar-controls"',
            'id="chat-toolbar-desktop-primary-slot" class="chat-toolbar-primary-selector"',
            'id="chat-toolbar-primary-surface" class="chat-toolbar-primary-surface"',
            'id="chat-toolbar-desktop-selectors-slot"',
            'id="chat-toolbar-selectors-surface" class="chat-toolbar-selectors"',
            'id="chat-mobile-tools-panel" class="chat-toolbar-mobile-panel offcanvas-lg offcanvas-bottom"',
            'id="chatMobileToolsLabel"',
            'chat-toolbar-tools-header',
            'id="chat-mobile-tools-close"',
            'id="chat-toolbar-mobile-tools-slot"',
            'id="chat-toolbar-mobile-primary-slot"',
            'id="chat-toolbar-mobile-selectors-slot"',
            'class="chat-toolbar-toggles"',
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
            'data-bs-toggle="offcanvas"',
            'window.chatPromptOptions =',
            'window.chatAgentOptions =',
            'window.chatModelOptions =',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing searchable selector markup: {missing}'
        assert 'search-btn-text d-none d-md-inline' not in content, 'Expected mobile drawer labels to rely on CSS visibility instead of Bootstrap d-none utilities'
        assert 'file-btn-text d-none d-md-inline' not in content, 'Expected mobile drawer file label to rely on CSS visibility instead of Bootstrap d-none utilities'

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
            '#chat-toolbar-desktop-tools-slot,',
            '.chat-toolbar-actions,',
            '.chat-toolbar-controls {',
            '.chat-toolbar-tools-surface {',
            '.chat-toolbar-mobile-panel {',
            '.chat-toolbar-selectors-slot {',
            '.chat-toolbar-selector {',
            '.chat-toolbar-selector .chat-searchable-select {',
            '.chat-toolbar-primary-surface {',
            '.chat-toolbar-primary-surface .chat-toolbar-selector {',
            '.chat-toolbar-mobile-panel .offcanvas-body {',
            '.chat-toolbar-mobile-primary-slot,',
            '.chat-toolbar-mobile-tools-slot .chat-toolbar-tools-surface {',
            '.chat-toolbar-mobile-tools-slot .search-btn:not(.active) .search-btn-text,',
            '#chat-toolbar-mobile-tools-slot .search-btn .search-btn-text,',
            '.search-btn,',
            '.file-btn {',
            '@media (max-width: 1200px) {',
            '@media (max-width: 991.98px) {',
            '@media (min-width: 992px) {',
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


def test_mobile_toolbar_safe_close_and_selector_reveal_wiring():
    """Verify the mobile tools drawer safely closes and reveals selectors on activation."""
    print('🔍 Testing mobile toolbar selector reveal and safe close wiring...')

    try:
        toolbar_content = read_file(CHAT_MOBILE_TOOLBAR_FILE)
        prompts_content = read_file(CHAT_PROMPTS_FILE)
        agents_content = read_file(CHAT_AGENTS_FILE)

        required_toolbar_snippets = [
            "const mobileToolsClose = document.getElementById('chat-mobile-tools-close');",
            "const primarySurface = document.getElementById('chat-toolbar-primary-surface');",
            "const desktopPrimarySlot = document.getElementById('chat-toolbar-desktop-primary-slot');",
            "const mobilePrimarySlot = document.getElementById('chat-toolbar-mobile-primary-slot');",
            "function closeOpenMobileSelectorDropdowns() {",
            "hideMobileSelectorDropdown('model-dropdown-button');",
            "function revealSelectorInMobileDrawer({ selectorId, dropdownButtonId }) {",
            "selectorElement.scrollIntoView({ behavior: 'smooth', block: 'nearest' });",
            "window.addEventListener('chat:toolbar-selector-activated', (event) => {",
            "bootstrap.Dropdown.getOrCreateInstance(dropdownButton, {",
            "mobileToolsClose?.addEventListener('click', (event) => {",
            "moveSurfaceToSlot(primarySurface, mobilePrimarySlot);",
            "moveSurfaceToSlot(primarySurface, desktopPrimarySlot);",
        ]
        required_prompt_snippets = [
            'function notifyMobileSelectorActivated(selectorId, dropdownButtonId) {',
            'loadAllPrompts().finally(() => {',
            'notifyMobileSelectorActivated("prompt-selection-container", "prompt-dropdown-button");',
        ]
        required_agent_snippets = [
            "function notifyMobileSelectorActivated(selectorId, dropdownButtonId) {",
            "notifyMobileSelectorActivated('agent-select-container', 'agent-dropdown-button');",
        ]

        missing_toolbar = [snippet for snippet in required_toolbar_snippets if snippet not in toolbar_content]
        missing_prompts = [snippet for snippet in required_prompt_snippets if snippet not in prompts_content]
        missing_agents = [snippet for snippet in required_agent_snippets if snippet not in agents_content]

        assert not missing_toolbar, f'Missing mobile toolbar wiring: {missing_toolbar}'
        assert not missing_prompts, f'Missing prompt reveal wiring: {missing_prompts}'
        assert not missing_agents, f'Missing agent reveal wiring: {missing_agents}'

        print('✅ Mobile toolbar selector reveal and safe close wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_grounded_search_mobile_drawer_uses_explicit_close_wiring():
    """Verify grounded search mobile close uses explicit JS instead of Bootstrap auto-dismiss."""
    print('🔍 Testing grounded search mobile drawer close wiring...')

    try:
        template_content = read_file(CHATS_TEMPLATE)
        documents_content = read_file(CHAT_DOCUMENTS_FILE)

        search_container_start = template_content.index('id="search-documents-container"')
        search_container_end = template_content.index('{% endif %}', search_container_start)
        search_container_markup = template_content[search_container_start:search_container_end]

        required_template_snippets = [
            'id="search-documents-mobile-close"',
            'class="chat-search-panel-mobile-footer d-lg-none"',
        ]
        required_js_snippets = [
            'const searchDocumentsMobileClose = document.getElementById("search-documents-mobile-close");',
            'function closeSearchDocumentsDropdowns() {',
            "return bootstrap.Offcanvas.getOrCreateInstance(searchDocumentsContainer, { toggle: false });",
            'closeSearchDocumentsDropdowns();',
            "searchDocumentsMobileClose?.addEventListener('click', (event) => {",
            'event.preventDefault();',
            'event.stopPropagation();',
            'hideSearchDocumentsPanel();',
        ]

        missing_template = [snippet for snippet in required_template_snippets if snippet not in search_container_markup]
        missing_js = [snippet for snippet in required_js_snippets if snippet not in documents_content]

        assert 'data-bs-dismiss="offcanvas"' not in search_container_markup, 'Expected grounded search drawer to avoid Bootstrap auto-dismiss wiring'
        assert not missing_template, f'Missing grounded search mobile drawer markup: {missing_template}'
        assert not missing_js, f'Missing grounded search mobile drawer JS wiring: {missing_js}'

        print('✅ Grounded search mobile drawer close wiring passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_tags_dropdown_loading_state_is_visible_before_tag_results_arrive():
    """Verify the tags filter exposes visible loading and empty states instead of hiding itself."""
    print('🔍 Testing tags dropdown loading-state wiring...')

    try:
        template_content = read_file(CHATS_TEMPLATE)
        documents_content = read_file(CHAT_DOCUMENTS_FILE)
        css_content = read_file(CHAT_CSS_FILE)

        required_template_snippets = [
            'id="tags-dropdown-loading-spinner"',
            'aria-disabled="true"',
            'disabled',
            'Loading tags...',
        ]
        required_js_snippets = [
            "let hasResolvedTagsState = false;",
            "let tagsDropdownState = 'loading';",
            'function setTagsDropdownLoadingState(message = \'Loading tags...\') {',
            'function setTagsDropdownReadyState() {',
            "function setTagsDropdownEmptyState(message = 'No tags available for this scope') {",
            'function refreshDocumentsAndTags({ source = null, showLoading = true } = {}) {',
            'await refreshDocumentsAndTags({ showLoading: !hasResolvedTagsState });',
            "if (tagsDropdownState !== 'ready' || !tagsDropdownItems || !tagsDropdownItems.children.length) {",
            "hideTagsDropdown('Unable to load tags');",
        ]
        required_css_snippets = [
            '.chat-search-dropdown-button-content {',
            '.chat-search-dropdown-loading-spinner {',
        ]

        missing_template = [snippet for snippet in required_template_snippets if snippet not in template_content]
        missing_js = [snippet for snippet in required_js_snippets if snippet not in documents_content]
        missing_css = [snippet for snippet in required_css_snippets if snippet not in css_content]

        assert 'id="tags-dropdown" style="display: none;"' not in template_content, 'Expected tags dropdown to stay visible while loading or empty'
        assert not missing_template, f'Missing tags loading template wiring: {missing_template}'
        assert not missing_js, f'Missing tags loading JS wiring: {missing_js}'
        assert not missing_css, f'Missing tags loading CSS wiring: {missing_css}'

        print('✅ Tags dropdown loading-state wiring passed')
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
            'dropdownConfig,',
            "const resolvedDropdownConfig = dropdownConfig || {",
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
            'const SEARCH_DOCUMENTS_MOBILE_MEDIA_QUERY = \u0027(max-width: 991.98px)\u0027;',
            'const SEARCH_DROPDOWN_VIEWPORT_PADDING = 16;',
            'const SEARCH_FILTER_DESKTOP_MIN_WIDTH = 320;',
            'const SEARCH_FILTER_DESKTOP_MAX_WIDTH = 640;',
            'function initializeSearchFilterDropdown({',
            'openUpOnDesktop = false,',
            'function getSearchDocumentsDropdownConfig({ openUpOnDesktop = false } = {}) {',
            "placement: shouldOpenUp ? 'top-start' : 'bottom-start',",
            "name: 'flip',",
            'enabled: !shouldOpenUp,',
            'const isMobileDrawer = isSearchDocumentsMobileDrawerViewport();',
            "const popperPlacement = menuEl.getAttribute('data-popper-placement') || '';",
            "const opensUp = popperPlacement.startsWith('top') && !isMobileDrawer;",
            '? buttonRect.top - SEARCH_DROPDOWN_VIEWPORT_PADDING',
            "bootstrap.Dropdown.getInstance(buttonEl)?.update();",
            "menuEl.style.width = isMobileDrawer ? `${Math.round(minWidth)}px` : 'max-content';",
            'menuEl.style.minWidth = `${Math.round(minWidth)}px`;',
            'menuEl.style.maxWidth = `${Math.round(maxWidth)}px`;',
            "boundary: 'viewport',",
            "strategy: 'fixed',",
            'export async function showSearchDocumentsPanel() {',
            'export function hideSearchDocumentsPanel() {',
            "bootstrap.Offcanvas.getOrCreateInstance(searchDocumentsContainer, { toggle: false });",
            'const documentSearchController = initializeFilterableDropdownSearch({',
            'const scopeSearchController = initializeFilterableDropdownSearch({',
            'const tagsSearchController = initializeFilterableDropdownSearch({',
            'searchController: scopeSearchController,',
            'searchController: tagsSearchController,',
            'searchController: documentSearchController,',
            'openUpOnDesktop: true,',
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
        assert 'menuEl.style.maxWidth = `${containerWidth}px`;' not in content, 'Expected dropdown max width to avoid being capped to the trigger container'

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
            'const FLOATING_SELECTOR_DROPDOWN_CONFIG = {',
            'export function initializeModelSelector()',
            'modelSelectorController = createSearchableSingleSelect({',
            'dropdownConfig: FLOATING_SELECTOR_DROPDOWN_CONFIG,',
            "[Group] ${group.name || 'Unnamed Group'}",
            "actionButton.textContent = 'Use all available workspaces';",
            "const optGroup = document.createElement('optgroup');",
            'const hideUnavailableOptions = !filteringContext.isNewConversation;',
            'options: hideUnavailableOptions',
            'filter(option => !option.disabled)',
        ]
        agent_snippets = [
            "import { createSearchableSingleSelect } from './chat-searchable-select.js';",
            'const FLOATING_SELECTOR_DROPDOWN_CONFIG = {',
            'function initializeAgentSelector() {',
            'agentSelectorController = createSearchableSingleSelect({',
            'dropdownConfig: FLOATING_SELECTOR_DROPDOWN_CONFIG,',
            "[Group] ${group.name || 'Unnamed Group'}",
            "actionButton.textContent = 'Use all available workspaces';",
            "const optGroup = document.createElement('optgroup');",
            'const hideUnavailableOptions = !filteringContext.isNewConversation;',
            'agents: hideUnavailableOptions',
            'filter(agent => !agent.disabled)',
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
        assert 'VERSION = "0.242.017"' in config_content, 'Expected config.py version 0.242.017'

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
        test_mobile_toolbar_safe_close_and_selector_reveal_wiring,
        test_grounded_search_mobile_drawer_uses_explicit_close_wiring,
        test_tags_dropdown_loading_state_is_visible_before_tag_results_arrive,
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