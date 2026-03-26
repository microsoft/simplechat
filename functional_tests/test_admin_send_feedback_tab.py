#!/usr/bin/env python3
# test_admin_send_feedback_tab.py
"""
Functional test for admin Send Feedback tab.
Version: 0.240.010
Implemented in: 0.240.003

This test ensures that Admin Settings exposes the Send Feedback tab,
renders bug and feature request mailto forms, and logs the submission
intent through the admin settings backend before opening the email draft.
"""

import os
import sys

from bs4 import BeautifulSoup


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

ADMIN_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'admin_settings.html')
SIDEBAR_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', '_sidebar_nav.html')
ADMIN_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'admin', 'admin_settings.js')
BACKEND_SETTINGS = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_settings.py')
ACTIVITY_LOGGING = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_activity_logging.py')
FEATURE_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'features', 'SEND_FEEDBACK_ADMIN.md')


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_send_feedback_template_structure():
    """Admin Settings template must expose the Send Feedback tab and both forms."""
    print('🔍 Testing Send Feedback template structure...')

    template_content = read_text(ADMIN_TEMPLATE)

    required_markers = [
        'id="admin-settings-form" style="padding-bottom:80px;" novalidate autocomplete="off" data-lpignore="true" data-1p-ignore="true" data-bwignore="true"',
        'id="send-feedback-tab"',
        'data-bs-target="#send-feedback"',
        'id="send-feedback" role="tabpanel"',
        'id="send-feedback-overview-card"',
        'id="send-feedback-bug-card"',
        'id="send-feedback-feature-card"',
        'class="admin-send-feedback-form" data-feedback-type="bug_report"',
        'class="admin-send-feedback-form" data-feedback-type="feature_request"',
        'This opens a text-only email draft in your local mail client.',
        'data-ignore-settings-change="true"'
    ]

    missing_markers = [marker for marker in required_markers if marker not in template_content]
    if missing_markers:
        raise AssertionError(f'Missing Send Feedback template markers: {missing_markers}')

    assert template_content.count('id="send-feedback" role="tabpanel"') == 1, 'Send Feedback tab pane should appear exactly once'
    assert 'send_feedback_bug_screenshot' not in template_content, 'Send Feedback bug form should not expose screenshot upload'
    assert 'send_feedback_feature_screenshot' not in template_content, 'Send Feedback feature form should not expose screenshot upload'
    assert template_content.count('class="admin-send-feedback-form"') == 2, 'Send Feedback should use two utility sections, not nested HTML forms'
    assert 'name="send_feedback_bug_name" autocomplete="name"' in template_content, 'Bug report name field should include explicit autocomplete metadata'
    assert 'name="send_feedback_bug_email" autocomplete="email"' in template_content, 'Bug report email field should include explicit autocomplete metadata'
    assert 'name="send_feedback_bug_org" autocomplete="organization"' in template_content, 'Bug report organization field should include explicit autocomplete metadata'
    assert 'name="send_feedback_bug_details" autocomplete="off"' in template_content, 'Bug report details field should disable autofill hints'
    assert 'name="send_feedback_feature_name" autocomplete="name"' in template_content, 'Feature request name field should include explicit autocomplete metadata'
    assert 'name="send_feedback_feature_email" autocomplete="email"' in template_content, 'Feature request email field should include explicit autocomplete metadata'
    assert 'name="send_feedback_feature_org" autocomplete="organization"' in template_content, 'Feature request organization field should include explicit autocomplete metadata'
    assert 'name="send_feedback_feature_details" autocomplete="off"' in template_content, 'Feature request details field should disable autofill hints'

    soup = BeautifulSoup(template_content, 'html.parser')
    tab_content = soup.find(id='adminSettingsTabContent')
    assert tab_content is not None, 'Admin settings tab content container should exist'

    direct_tab_panes = [child.get('id') for child in tab_content.find_all('div', class_='tab-pane', recursive=False)]
    assert 'send-feedback' in direct_tab_panes, 'Send Feedback should be a direct tab pane under adminSettingsTabContent'

    send_feedback_pane = soup.find(id='send-feedback')
    assert send_feedback_pane is not None, 'Send Feedback pane should exist in template'
    assert send_feedback_pane.find_parent(id='search-extract') is None, 'Send Feedback pane should not be nested inside Search & Extract'

    print('✅ Send Feedback template structure is present')
    return True


def test_send_feedback_navigation_order():
    """Send Feedback should be the last top-nav tab and the last admin sidebar item."""
    print('🔍 Testing Send Feedback navigation order...')

    template_content = read_text(ADMIN_TEMPLATE)
    sidebar_content = read_text(SIDEBAR_TEMPLATE)

    send_feedback_tab_index = template_content.index('id="send-feedback-tab"')
    logging_tab_index = template_content.index('id="logging-tab"')
    assert send_feedback_tab_index > logging_tab_index, 'Send Feedback should appear after Logging in top nav'

    send_feedback_sidebar_index = sidebar_content.index('data-tab="send-feedback"')
    search_extract_sidebar_index = sidebar_content.index('data-tab="search-extract"')
    assert send_feedback_sidebar_index > search_extract_sidebar_index, 'Send Feedback should be the last admin sidebar item'

    assert 'data-section="latest-features-send-feedback-card"' in sidebar_content, 'Latest Features submenu should expose the Send Feedback callout'

    print('✅ Send Feedback navigation order is correct')
    return True


def test_send_feedback_javascript_and_backend():
    """Send Feedback JavaScript and backend route must support logged mailto submission."""
    print('🔍 Testing Send Feedback JavaScript and backend integration...')

    js_content = read_text(ADMIN_JS)
    backend_content = read_text(BACKEND_SETTINGS)
    logging_content = read_text(ACTIVITY_LOGGING)
    sidebar_nav_content = read_text(os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'admin', 'admin_sidebar_nav.js'))

    js_markers = [
        'setupAdminFormAutofillMetadata()',
        'function setupAdminFormAutofillMetadata() {',
        'setupSendFeedbackForms()',
        'async function submitAdminFeedbackForm(form)',
        "fetch('/api/admin/settings/send_feedback_email'",
        'function buildAdminFeedbackMailtoUrl(',
        'function updateSendFeedbackStatus(',
        "const submitButton = form.querySelector('.admin-send-feedback-submit');",
        "field.setAttribute('autocomplete', 'off');",
        'querySelectorAll(\'input:not([data-ignore-settings-change="true"]), select:not([data-ignore-settings-change="true"]), textarea:not([data-ignore-settings-change="true"])\')'
    ]
    missing_js = [marker for marker in js_markers if marker not in js_content]
    if missing_js:
        raise AssertionError(f'Missing Send Feedback JavaScript markers: {missing_js}')

    assert 'Admin Settings URL:' not in js_content, 'Send Feedback mailto body should not include the admin settings URL'

    sidebar_markers = [
        'function showAdminTab(tabId)',
        'button.nav-link[data-bs-target="#${tabId}"]',
        'bootstrap.Tab.getOrCreateInstance(bootstrapTabButton)',
        'window.location.hash = tabId;'
    ]
    missing_sidebar = [marker for marker in sidebar_markers if marker not in sidebar_nav_content]
    if missing_sidebar:
        raise AssertionError(f'Missing sidebar tab activation markers: {missing_sidebar}')

    backend_markers = [
        "@app.route('/api/admin/settings/send_feedback_email', methods=['POST'])",
        'def send_feedback_email():',
        'log_admin_feedback_email_submission('
    ]
    missing_backend = [marker for marker in backend_markers if marker not in backend_content]
    if missing_backend:
        raise AssertionError(f'Missing Send Feedback backend markers: {missing_backend}')

    logging_markers = [
        'def log_admin_feedback_email_submission(',
        "'activity_type': 'admin_feedback_email_submission'",
        "'submission_channel': 'mailto'"
    ]
    missing_logging = [marker for marker in logging_markers if marker not in logging_content]
    if missing_logging:
        raise AssertionError(f'Missing Send Feedback activity logging markers: {missing_logging}')

    print('✅ Send Feedback JavaScript and backend integration is present')
    return True


def test_send_feedback_documentation():
    """Feature documentation for Send Feedback must exist and carry the current version."""
    print('🔍 Testing Send Feedback feature documentation...')

    assert os.path.exists(FEATURE_DOC), 'Missing Send Feedback feature documentation'

    doc_content = read_text(FEATURE_DOC)
    assert 'Documentation Version: 0.240.010' in doc_content, 'Send Feedback documentation current version header missing or incorrect'
    assert 'Version Implemented: 0.240.005' in doc_content, 'Send Feedback documentation implementation version missing or incorrect'
    assert 'mailto' in doc_content.lower(), 'Send Feedback documentation should describe the mailto workflow'
    assert 'text-only email draft' in doc_content.lower(), 'Send Feedback documentation should explain the simplified email-only workflow'
    assert 'screenshot' not in doc_content.lower(), 'Send Feedback documentation should not mention screenshot upload after removal'
    assert 'admin settings url' not in doc_content.lower(), 'Send Feedback documentation should not mention including the admin settings URL'

    print('✅ Send Feedback documentation is present')
    return True


if __name__ == '__main__':
    print('🧪 Running Send Feedback Admin Tab tests...\n')

    tests = [
        test_send_feedback_template_structure,
        test_send_feedback_navigation_order,
        test_send_feedback_javascript_and_backend,
        test_send_feedback_documentation,
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