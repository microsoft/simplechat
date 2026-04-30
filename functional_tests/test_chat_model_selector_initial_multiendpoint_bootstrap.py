#!/usr/bin/env python3
# test_chat_model_selector_initial_multiendpoint_bootstrap.py
"""
Functional test for chat model selector initial multi-endpoint bootstrap.
Version: 0.240.069
Implemented in: 0.240.069

This test ensures the chats page renders the preferred multi-endpoint model
selection on first paint instead of showing a legacy GPT default until the
client-side selector restore finishes.
"""

import os
import sys


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
        'def _build_initial_chat_model_selection(*, chat_model_options, preferred_model_id=None, preferred_model_deployment=None):',
        "preferred_model_id=user_settings_dict.get('preferredModelId')",
        "preferred_model_deployment=user_settings_dict.get('preferredModelDeployment')",
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
    ]

    missing = [snippet for snippet in required_snippets if snippet not in template_content]
    assert not missing, f'Missing chats template bootstrap snippets: {missing}'

    print('✅ Chats template initial multi-endpoint render passed')
    return True


def test_config_version_bumped_for_initial_model_bootstrap_fix():
    """Verify config version was bumped for the initial model bootstrap fix."""
    print('🔍 Testing config version bump...')

    config_content = read_file(CONFIG_FILE)
    assert 'VERSION = "0.240.069"' in config_content, 'Expected config.py version 0.240.069'

    print('✅ Config version bump passed')
    return True


if __name__ == '__main__':
    tests = [
        test_chats_route_builds_initial_multi_endpoint_selection,
        test_chats_template_renders_initial_multi_endpoint_selection,
        test_config_version_bumped_for_initial_model_bootstrap_fix,
    ]

    results = []
    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        results.append(test())

    success = all(results)
    print(f'\n📊 Results: {sum(results)}/{len(results)} tests passed')
    sys.exit(0 if success else 1)