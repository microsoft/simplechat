#!/usr/bin/env python3
# test_workspace_scope_prompts_fix.py
"""
Functional test for workspace scope affecting prompts functionality.
Version: 0.239.123
Implemented in: 0.239.123

This test ensures that chat prompt loading remains scope-aware for personal,
group, and public prompt sources, and that the prompt picker uses the current
searchable single-select implementation.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAT_PROMPTS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-prompts.js',
)
CHAT_GLOBAL_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-global.js',
)
CHAT_TEMPLATE_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'templates',
    'chats.html',
)
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'config.py',
)
PUBLIC_PROMPTS_ROUTE_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'route_backend_public_prompts.py',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_prompt_scope_filtering_and_searchable_picker_implementation():
    """Verify prompt scope filtering now uses effective scopes and searchable dropdown UI."""
    print('🔍 Testing workspace scope prompts implementation...')

    try:
        prompts_content = read_file(CHAT_PROMPTS_FILE)
        global_content = read_file(CHAT_GLOBAL_FILE)
        template_content = read_file(CHAT_TEMPLATE_FILE)
        config_content = read_file(CONFIG_FILE)

        required_global_snippets = [
            'let publicPrompts = [];',
        ]
        missing_global = [snippet for snippet in required_global_snippets if snippet not in global_content]
        assert not missing_global, f'Missing global prompt state: {missing_global}'
        print('✅ publicPrompts variable properly declared in chat-global.js')

        required_prompt_snippets = [
            'import { docScopeSelect, getEffectiveScopes } from "./chat-documents.js";',
            'import { createSearchableSingleSelect } from "./chat-searchable-select.js";',
            'function initializePromptSelector() {',
            'promptSelectorController = createSearchableSingleSelect({',
            'async function fetchAllPromptPages(endpoint, emptyStatuses = []) {',
            'const promptPageSize = 100;',
            'scopes.personal',
            'scopes.groupIds.length > 0',
            'scopes.publicWorkspaceIds.length > 0',
            'scope: "Personal"',
            'scope: "Group"',
            'scope: "Public"',
            'loadAllPromptsPromise = Promise.all([loadUserPrompts(), loadGroupPrompts(), loadPublicPrompts()])',
            'docScopeSelect.addEventListener("change", function() {',
        ]
        missing_prompt = [snippet for snippet in required_prompt_snippets if snippet not in prompts_content]
        assert not missing_prompt, f'Missing prompt scope/search snippets: {missing_prompt}'
        print('✅ Prompt scope filtering and searchable selector logic implemented')

        required_template_snippets = [
            'id="prompt-dropdown"',
            'id="prompt-search-input"',
            'id="prompt-dropdown-items"',
        ]
        missing_template = [snippet for snippet in required_template_snippets if snippet not in template_content]
        assert not missing_template, f'Missing prompt dropdown template markup: {missing_template}'
        print('✅ Prompt dropdown template markup implemented')

        assert 'VERSION = "0.239.123"' in config_content, 'Expected config.py version 0.239.123'
        print('✅ Version properly updated to 0.239.123 in config.py')

        print('✅ Workspace scope prompt implementation checks passed!')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_public_prompt_api_endpoints_exist():
    """Verify public prompt API endpoints still exist for scope-aware prompt loading."""
    print('\n🔍 Testing public prompt API endpoints...')

    try:
        route_content = read_file(PUBLIC_PROMPTS_ROUTE_FILE)

        required_endpoints = [
            "'/api/public_prompts', methods=['GET']",
            "'/api/public_prompts', methods=['POST']",
            "'/api/public_prompts/<prompt_id>', methods=['GET']",
        ]

        missing = [endpoint for endpoint in required_endpoints if endpoint not in route_content]
        assert not missing, f'Missing public prompt API endpoints: {missing}'

        print('✅ All required API endpoints exist for public prompts')
        return True

    except Exception as exc:
        print(f'❌ API endpoint test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print('🧪 Running Workspace Scope Prompts Fix Tests...\n')

    tests = [
        test_prompt_scope_filtering_and_searchable_picker_implementation,
        test_public_prompt_api_endpoints_exist,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)