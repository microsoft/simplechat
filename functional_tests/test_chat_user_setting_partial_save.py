#!/usr/bin/env python3
# test_chat_user_setting_partial_save.py
"""
Functional test for chat user setting partial saves.
Version: 0.242.051
Implemented in: 0.242.051

This test ensures chat preference saves post only the changed keys so stale
active workspace settings cannot break unrelated preference updates.
"""

import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_repo_file(*parts):
    """Read a UTF-8 text file from the repository."""
    path = os.path.join(ROOT_DIR, *parts)
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_chat_layout_posts_partial_user_setting_updates():
    """Verify saveUserSetting does not re-post the full settings document."""
    print('Testing chat partial user setting saves...')

    layout_source = read_repo_file(
        'application', 'single_app', 'static', 'js', 'chat', 'chat-layout.js'
    )
    save_function_source = layout_source[layout_source.index('export function saveUserSetting'):]

    assert "return fetch('/api/user/settings', {" in save_function_source
    assert 'body: JSON.stringify({ settings: settingUpdate })' in save_function_source
    assert 'const updatedSettings' not in save_function_source
    assert '{ ...currentSettings, ...settingUpdate }' not in save_function_source

    print('PASS: saveUserSetting posts only the provided setting update')


def test_chat_preference_keys_are_allowed_by_backend():
    """Verify chat preference keys saved by chat-layout callers are allowlisted."""
    print('Testing chat preference allowlist keys...')

    route_source = read_repo_file('application', 'single_app', 'route_backend_users.py')

    required_keys = [
        'preferredModelId',
        'preferredModelDeployment',
        'reasoningEffortSettings',
        'deepResearchDefaultEnabled',
        'microphonePermissionPreference',
        'microphonePermissionState',
    ]
    missing_keys = [
        key for key in required_keys
        if f"'{key}'" not in route_source and f'"{key}"' not in route_source
    ]

    assert missing_keys == [], f'Missing allowed user setting keys: {missing_keys}'

    print('PASS: chat preference keys are accepted by the backend allowlist')


if __name__ == '__main__':
    tests = [
        test_chat_layout_posts_partial_user_setting_updates,
        test_chat_preference_keys_are_allowed_by_backend,
    ]
    results = []

    for test in tests:
        print(f'\n🧪 Running {test.__name__}...')
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'FAIL: {test.__name__} -> {exc}')
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f'\nResults: {passed}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)