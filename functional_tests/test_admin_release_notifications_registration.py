#!/usr/bin/env python3
# test_admin_release_notifications_registration.py
"""
Functional test for admin release notifications registration.
Version: 0.240.011
Implemented in: 0.240.011

This test ensures that Admin Settings exposes the release notifications
registration badge and modal, persists the registration state in settings,
and prepares a logged mailto workflow to simplechat@microsoft.com.
"""

import os
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

ADMIN_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'admin_settings.html')
ADMIN_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'admin', 'admin_settings.js')
BACKEND_SETTINGS = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_settings.py')
FRONTEND_SETTINGS = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_frontend_admin_settings.py')
ACTIVITY_LOGGING = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_activity_logging.py')
SETTINGS_FUNCTIONS = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_settings.py')
FEATURE_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'features', 'RELEASE_NOTIFICATIONS_REGISTRATION.md')


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_release_notifications_template_markers():
    """Admin Settings template must expose the registration badge, modal, and hidden fields."""
    print('🔍 Testing release notifications template markers...')

    template_content = read_text(ADMIN_TEMPLATE)

    required_markers = [
        'id="releaseNotificationsModal"',
        'id="release-notifications-status-badge"',
        'id="release-notifications-read-view"',
        'id="release-notifications-edit-view"',
        'id="release-notifications-edit-btn"',
        'id="release-notifications-cancel-edit-btn"',
        'id="release-notifications-submit-btn"',
        'name="release_notifications_registered"',
        'name="release_notifications_name"',
        'name="release_notifications_email"',
        'name="release_notifications_org"',
        'name="release_notifications_registered_at"',
        'name="release_notifications_updated_at"',
        'simplechat@microsoft.com',
        'Register for latest release updates and community call notifications.'
    ]

    missing_markers = [marker for marker in required_markers if marker not in template_content]
    if missing_markers:
        raise AssertionError(f'Missing release notifications template markers: {missing_markers}')

    assert 'Release Notifications Registration' in template_content, 'Release notifications modal title should be present'
    assert 'Registered' in template_content and 'Unregistered' in template_content, 'Status badge states should be present in the template'

    print('✅ Release notifications template markers are present')
    return True


def test_release_notifications_backend_and_settings_markers():
    """Settings defaults, frontend persistence, backend endpoint, and activity logging must exist."""
    print('🔍 Testing release notifications backend and settings markers...')

    settings_content = read_text(SETTINGS_FUNCTIONS)
    frontend_content = read_text(FRONTEND_SETTINGS)
    backend_content = read_text(BACKEND_SETTINGS)
    logging_content = read_text(ACTIVITY_LOGGING)

    settings_markers = [
        "'release_notifications_registered': False",
        "'release_notifications_name': ''",
        "'release_notifications_email': ''",
        "'release_notifications_org': ''",
        "'release_notifications_registered_at': ''",
        "'release_notifications_updated_at': ''"
    ]
    missing_settings = [marker for marker in settings_markers if marker not in settings_content]
    if missing_settings:
        raise AssertionError(f'Missing release notifications settings markers: {missing_settings}')

    frontend_markers = [
        "if 'release_notifications_registered' not in settings:",
        "'release_notifications_registered': form_data.get('release_notifications_registered', 'false').lower() == 'true'",
        "'release_notifications_name': form_data.get('release_notifications_name'",
        "'release_notifications_email': form_data.get('release_notifications_email'",
        "'release_notifications_org': form_data.get('release_notifications_org'"
    ]
    missing_frontend = [marker for marker in frontend_markers if marker not in frontend_content]
    if missing_frontend:
        raise AssertionError(f'Missing release notifications frontend markers: {missing_frontend}')

    backend_markers = [
        "@app.route('/api/admin/settings/release_notifications_registration', methods=['POST'])",
        'def release_notifications_registration():',
        "'release_notifications_registered': True",
        'log_admin_release_notifications_registration(',
        "'recipientEmail': 'simplechat@microsoft.com'"
    ]
    missing_backend = [marker for marker in backend_markers if marker not in backend_content]
    if missing_backend:
        raise AssertionError(f'Missing release notifications backend markers: {missing_backend}')

    logging_markers = [
        'def log_admin_release_notifications_registration(',
        "'activity_type': 'admin_release_notifications_registration'",
        "'registration_channel': 'mailto'"
    ]
    missing_logging = [marker for marker in logging_markers if marker not in logging_content]
    if missing_logging:
        raise AssertionError(f'Missing release notifications activity logging markers: {missing_logging}')

    print('✅ Release notifications backend and settings markers are present')
    return True


def test_release_notifications_javascript_markers():
    """Admin JS must support modal state, persistence sync, and mailto submission."""
    print('🔍 Testing release notifications JavaScript markers...')

    js_content = read_text(ADMIN_JS)

    js_markers = [
        'setupReleaseNotificationsRegistration();',
        'function setupReleaseNotificationsRegistration() {',
        'async function submitReleaseNotificationsRegistration() {',
        "fetch('/api/admin/settings/release_notifications_registration'",
        'function buildReleaseNotificationsMailtoUrl({',
        'function syncReleaseNotificationsHiddenInputs() {',
        'function updateReleaseNotificationsBadge() {',
        'function showReleaseNotificationsReadView() {',
        'function showReleaseNotificationsEditView() {',
        'function formatIsoDateTime(value) {'
    ]

    missing_js = [marker for marker in js_markers if marker not in js_content]
    if missing_js:
        raise AssertionError(f'Missing release notifications JavaScript markers: {missing_js}')

    assert 'Release notifications registration prepared.' in js_content, 'Success toast message should be present'
    assert 'Please register this admin settings instance' in js_content, 'Mailto body should explain the registration intent'

    print('✅ Release notifications JavaScript markers are present')
    return True


def test_release_notifications_documentation():
    """Feature documentation must exist and reference the current version."""
    print('🔍 Testing release notifications feature documentation...')

    assert os.path.exists(FEATURE_DOC), 'Missing release notifications feature documentation'

    doc_content = read_text(FEATURE_DOC)
    assert 'Documentation Version: 0.240.011' in doc_content, 'Feature documentation current version header missing or incorrect'
    assert 'Version Implemented: 0.240.011' in doc_content, 'Feature documentation implementation version missing or incorrect'
    assert 'simplechat@microsoft.com' in doc_content, 'Feature documentation should mention the registration recipient'
    assert 'community call' in doc_content.lower(), 'Feature documentation should describe community call notifications'
    assert 'release notifications' in doc_content.lower(), 'Feature documentation should describe release notifications'

    print('✅ Release notifications feature documentation is present')
    return True


if __name__ == '__main__':
    print('🧪 Running release notifications registration tests...\n')

    tests = [
        test_release_notifications_template_markers,
        test_release_notifications_backend_and_settings_markers,
        test_release_notifications_javascript_markers,
        test_release_notifications_documentation,
    ]

    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f'❌ {test.__name__} failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)
        print()

    passed = sum(1 for result in results if result)
    print(f'📊 Results: {passed}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)