#!/usr/bin/env python3
# test_reasoning_effort_initial_sync.py
"""
Functional test for reasoning effort initial state sync.
Version: 0.240.010
Implemented in: 0.240.010

This test ensures that the chat page restores the saved preferred model through
the shared selector logic before initializing reasoning effort state so the
reasoning button reflects the saved level on first load instead of waiting for
a manual change.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHAT_REASONING_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-reasoning.js',
)
CHAT_ONLOAD_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-onload.js',
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
CONFIG_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'config.py',
)


def read_file(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_reasoning_toggle_uses_applied_startup_settings():
    """Verify reasoning initialization can consume already-loaded user settings."""
    print('🔍 Testing reasoning toggle startup settings handling...')

    try:
        content = read_file(CHAT_REASONING_FILE)

        required_snippets = [
            'function applyReasoningSettings(settings = {}) {',
            'export function initializeReasoningToggle(initialSettings = null) {',
            'applyReasoningSettings(initialSettings);',
            'loadUserSettings().then(settings => {',
            'syncReasoningStateForCurrentModel();',
            "modelSelect.addEventListener('change', () => {",
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing reasoning startup sync logic: {missing}'

        print('✅ Reasoning toggle startup settings handling passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_chat_onload_sets_model_before_reasoning_initialization():
    """Verify chat startup restores the preferred model before reasoning init."""
    print('🔍 Testing chat onload reasoning initialization order...')

    try:
        content = read_file(CHAT_ONLOAD_FILE)

        required_snippets = [
            'const userSettingsPromise = loadUserSettings();',
            'const userSettings = await userSettingsPromise;',
            'initializeModelSelector();',
            'await populateModelDropdown({',
            'preferredModelId,',
            'preferredModelDeployment,',
            'preserveCurrentSelection: false,',
            'initializeReasoningToggle(userSettings);',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing onload startup ordering logic: {missing}'

        preferred_model_index = content.index('await populateModelDropdown({')
        reasoning_init_index = content.index('initializeReasoningToggle(userSettings);')
        assert preferred_model_index < reasoning_init_index, (
            'Expected preferred model to be applied before reasoning initialization'
        )

        print('✅ Chat onload reasoning initialization order passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_model_selector_restores_legacy_preferred_model_before_refresh():
    """Verify legacy mode restores the saved preferred deployment before refresh."""
    print('🔍 Testing legacy model restore in shared selector...')

    try:
        content = read_file(CHAT_MODEL_SELECTOR_FILE)

        required_snippets = [
            'function restoreLegacyPreferredModelSelection(preferredModelDeployment) {',
            'const matchingOption = Array.from(modelSelect.options).find(option => (',
            'option.value === preferredModelDeployment',
            'modelSelect.value = matchingOption.value;',
            'restoreLegacyPreferredModelSelection(restoreOptions.preferredModelDeployment || null);',
        ]

        missing = [snippet for snippet in required_snippets if snippet not in content]
        assert not missing, f'Missing legacy preferred model restore logic: {missing}'

        restore_index = content.index('restoreLegacyPreferredModelSelection(restoreOptions.preferredModelDeployment || null);')
        refresh_index = content.index('modelSelectorController?.refresh();')
        assert restore_index < refresh_index, (
            'Expected legacy preferred model restoration to occur before the selector refresh'
        )

        print('✅ Legacy model restore in shared selector passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


def test_config_version_bumped_for_reasoning_sync_fix():
    """Verify config version was bumped for the reasoning startup sync fix."""
    print('🔍 Testing config version bump...')

    try:
        content = read_file(CONFIG_FILE)
        assert 'VERSION = "0.240.010"' in content, 'Expected config.py version 0.240.010'

        print('✅ Config version bump passed')
        return True

    except Exception as exc:
        print(f'❌ Test failed: {exc}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    tests = [
        test_reasoning_toggle_uses_applied_startup_settings,
        test_chat_onload_sets_model_before_reasoning_initialization,
        test_model_selector_restores_legacy_preferred_model_before_refresh,
        test_config_version_bumped_for_reasoning_sync_fix,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)