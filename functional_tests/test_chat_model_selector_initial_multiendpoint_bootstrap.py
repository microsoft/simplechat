#!/usr/bin/env python3
# test_chat_model_selector_initial_multiendpoint_bootstrap.py
"""
Functional test for chat model selector initial multi-endpoint bootstrap.
Version: 0.261.044
Implemented in: 0.240.069; updated in 0.261.044

This test ensures the chats page renders the preferred multi-endpoint model
selection on first paint instead of showing a legacy GPT default until the
client-side selector restore finishes. It also verifies that admin new-chat
defaults override the user's last selected model during initial bootstrap.
"""

import os
import sys
from test_support.versioning import assert_app_version_at_least


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'route_frontend_chats.py')
TEMPLATE_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'templates', 'chats.html')
CONFIG_FILE = os.path.join(ROOT_DIR, 'application', 'single_app', 'config.py')


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_chats_route_builds_initial_multi_endpoint_selection():
    """Verify the chats route resolves a preferred multi-endpoint selection for initial render."""
    print('🔍 Testing chats route initial multi-endpoint selection bootstrap...')

    route_content = read_file(ROUTE_FILE)
    required_snippets = [
        'def _build_initial_chat_model_selection(',
        'default_model_selection=None,',
        'use_admin_default=False,',
        'if use_admin_default and isinstance(default_model_selection, dict):',
        "preferred_model_id=user_settings_dict.get('preferredModelId')",
        "preferred_model_deployment=user_settings_dict.get('preferredModelDeployment')",
        "default_model_selection=settings.get('default_model_selection', {}),",
        "settings.get('enable_default_model_for_new_conversations', False)",
        'initial_chat_model_selection = _build_initial_chat_model_selection(',
        'initial_chat_model_selection=initial_chat_model_selection,',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in route_content]
    assert not missing, f'Missing chats route bootstrap snippets: {missing}'

    print('✅ Chats route initial multi-endpoint selection bootstrap passed')
    return True


def test_chats_template_renders_initial_multi_endpoint_selection():
    """Verify the chats template uses the bootstrapped multi-endpoint selection on first paint."""
    print('🔍 Testing chats template initial multi-endpoint render...')

    template_content = read_file(TEMPLATE_FILE)
    required_snippets = [
        '{% if enable_multi_model_endpoints and initial_chat_model_selection %}',
        '{{ initial_chat_model_selection.display_name }}',
        'data-selection-key="{{ initial_chat_model_selection.selection_key }}"',
        'data-endpoint-id="{{ initial_chat_model_selection.endpoint_id }}"',
        'data-provider="{{ initial_chat_model_selection.provider }}"',
        'window.initialChatModelSelection = {{ initial_chat_model_selection|default({}, true)|tojson|safe }};',
        'enable_default_model_for_new_conversations: {{ settings.enable_default_model_for_new_conversations|default(false, true)|tojson }},',
        'default_model_selection: {{ settings.default_model_selection|default({}, true)|tojson|safe }},',
        'default_reasoning_effort: {{ settings.default_reasoning_effort|default(\'\', true)|tojson }},',
        'window.adminNewConversationDefaultsActive = Boolean(',
    ]

    missing = [snippet for snippet in required_snippets if snippet not in template_content]
    assert not missing, f'Missing chats template bootstrap snippets: {missing}'

    print('✅ Chats template initial multi-endpoint render passed')
    return True


def test_existing_conversation_model_restore_wiring():
    """Verify loading an existing conversation restores its own saved model metadata."""
    print('🔍 Testing existing conversation model restore wiring...')

    model_selector_content = read_file(os.path.join(
        ROOT_DIR,
        'application', 'single_app', 'static', 'js', 'chat', 'chat-model-selector.js'
    ))
    messages_content = read_file(os.path.join(
        ROOT_DIR,
        'application', 'single_app', 'static', 'js', 'chat', 'chat-messages.js'
    ))
    searchable_select_content = read_file(os.path.join(
        ROOT_DIR,
        'application', 'single_app', 'static', 'js', 'chat', 'chat-searchable-select.js'
    ))
    conversations_content = read_file(os.path.join(
        ROOT_DIR,
        'application', 'single_app', 'static', 'js', 'chat', 'chat-conversations.js'
    ))

    required_snippets = [
        'const useAdminDefault = Boolean(',
        'window.adminNewConversationDefaultsActive',
        'preferredModelId: useAdminDefault ? window.initialChatModelSelection.selection_key : settings?.preferredModelId,',
        'preferredModelDeployment: useAdminDefault ? null : settings?.preferredModelDeployment,',
        'export function restoreModelSelectionFromConversationMetadata(modelSelection = {})',
        'export function restoreAdminDefaultModelSelection()',
        'modelSelection.model_endpoint_id || modelSelection.endpoint_id',
        'modelSelection.selected_model || modelSelection.request_model',
        "option.dataset.endpointId === endpointId",
        "option.dataset.modelId === modelId",
        'restoreAdminDefaultModelSelection,',
        'restoreModelSelectionFromConversationMetadata,',
        'function getLastConversationModelSelection(messages = [])',
        'const lastModelSelection = getLastConversationModelSelection(data.messages);',
        'if (lastModelSelection) {',
        '} else if ((Array.isArray(data.messages) ? data.messages : []).length === 0) {',
        'restoreAdminDefaultModelSelection();',
        "detail: { conversationRestore: true }",
        "detail: { userInitiated: true }",
    ]
    combined_content = '\n'.join([
        conversations_content,
        model_selector_content,
        messages_content,
        searchable_select_content,
    ])
    missing = [snippet for snippet in required_snippets if snippet not in combined_content]
    assert not missing, f'Missing existing conversation model restore snippets: {missing}'

    print('✅ Existing conversation model restore wiring passed')
    return True


def test_config_version_bumped_for_initial_model_bootstrap_fix():
    """Verify config version was bumped for the initial model bootstrap fix."""
    print('🔍 Testing config version bump...')

    assert_app_version_at_least("0.240.069")

    print('✅ Config version bump passed')
    return True


if __name__ == '__main__':
    tests = [
        test_chats_route_builds_initial_multi_endpoint_selection,
        test_chats_template_renders_initial_multi_endpoint_selection,
        test_existing_conversation_model_restore_wiring,
        test_config_version_bumped_for_initial_model_bootstrap_fix,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)