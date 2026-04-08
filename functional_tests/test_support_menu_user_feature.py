#!/usr/bin/env python3
"""
Functional test for support menu sidebar visibility, access behavior, and
latest-feature image preview support.
Version: 0.240.084
Implemented in: 0.240.061; 0.240.084

This test ensures the Support menu renders for signed-in app users when enabled,
the sidebar and top-nav templates expose the expected links, and the user-facing
Latest Features page supports clickable image previews, richer guidance, action
links, and feature parity with the admin latest-features catalog.
"""

import os
import sys
import importlib.util


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

FUNCTIONS_SETTINGS = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_settings.py')
ADMIN_ROUTE = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_frontend_admin_settings.py')
SUPPORT_ROUTE = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_frontend_support.py')
BACKEND_SETTINGS = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_settings.py')
ACTIVITY_LOGGING = os.path.join(REPO_ROOT, 'application', 'single_app', 'functions_activity_logging.py')
SUPPORT_CONFIG = os.path.join(REPO_ROOT, 'application', 'single_app', 'support_menu_config.py')
ADMIN_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'admin_settings.html')
SIDEBAR_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', '_sidebar_nav.html')
SHORT_SIDEBAR_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', '_sidebar_short_nav.html')
TOP_NAV_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', '_top_nav.html')
LATEST_FEATURES_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'latest_features.html')
SUPPORT_FEEDBACK_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'support_send_feedback.html')
ADMIN_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'admin', 'admin_settings.js')
LATEST_FEATURES_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'support', 'latest_features.js')
SUPPORT_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'support', 'support_feedback.js')


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def load_module(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_support_menu_settings_defaults_and_persistence():
    print('🔍 Testing support menu settings defaults and persistence markers...')

    settings_content = read_text(FUNCTIONS_SETTINGS)
    admin_route_content = read_text(ADMIN_ROUTE)
    config_content = read_text(SUPPORT_CONFIG)
    support_config = load_module(SUPPORT_CONFIG, 'support_menu_config_test')

    settings_markers = [
        "'enable_support_menu': False",
        "'support_menu_name': 'Support'",
        "'enable_support_send_feedback': True",
        "'support_feedback_recipient_email': ''",
        "'enable_support_latest_features': True",
        "'support_latest_features_visibility': get_default_support_latest_features_visibility()",
        "support_feedback_recipient_configured",
        "support_latest_features_has_visible_items",
    ]
    missing_settings = [marker for marker in settings_markers if marker not in settings_content]
    assert not missing_settings, f'Missing support menu settings markers: {missing_settings}'

    default_visibility = support_config.get_default_support_latest_features_visibility()
    assert default_visibility['deployment'] is False, 'Deployment should be hidden by default for user-facing latest features'
    assert default_visibility['redis_key_vault'] is False, 'Redis and Key Vault should be hidden by default for user-facing latest features'

    normalized_visibility = support_config.normalize_support_latest_features_visibility({})
    assert normalized_visibility['deployment'] is False, 'Normalized defaults should keep Deployment hidden by default'
    assert normalized_visibility['redis_key_vault'] is False, 'Normalized defaults should keep Redis and Key Vault hidden by default'

    route_markers = [
        "get_support_latest_feature_catalog",
        "normalize_support_latest_features_visibility",
        "enable_support_menu = form_data.get('enable_support_menu') == 'on'",
        "support_menu_name = form_data.get('support_menu_name', 'Support').strip()",
        "enable_support_send_feedback = form_data.get('enable_support_send_feedback') == 'on'",
        "support_feedback_recipient_email = form_data.get('support_feedback_recipient_email', '').strip()",
        "enable_support_latest_features = form_data.get('enable_support_latest_features') == 'on'",
        "'support_latest_features_visibility': support_latest_features_visibility",
    ]
    missing_route = [marker for marker in route_markers if marker not in admin_route_content]
    assert not missing_route, f'Missing admin route persistence markers: {missing_route}'

    config_markers = [
        "'id': 'guided_tutorials'",
        "'id': 'background_chat'",
        "'id': 'gpt_selection'",
        "'id': 'tabular_analysis'",
        "'id': 'citation_improvements'",
        "'id': 'document_versioning'",
        "'id': 'summaries_export'",
        "'id': 'agent_operations'",
        "'id': 'ai_transparency'",
        "'id': 'fact_memory'",
        "'id': 'deployment'",
        "'id': 'redis_key_vault'",
        "'id': 'send_feedback'",
        "'id': 'support_menu'",
        "'path': 'images/features/facts_memory_view_profile.png'",
        "'path': 'images/features/fact_memory_management.png'",
        "'path': 'images/features/facts_citation_and_thoughts.png'",
        "'path': 'images/features/guided_tutorials_workspace.png'",
        "'path': 'images/features/background_completion_notifications-02.png'",
        "'path': 'images/features/model_selection_multi_endpoint_admin.png'",
        "'path': 'images/features/model_selection_chat_selector.png'",
        "'path': 'images/features/tabular_analysis_enhanced_citations.png'",
        "'path': 'images/features/citation_improvements_history_replay.png'",
        "'path': 'images/features/citation_improvements_amplified_results.png'",
        "'path': 'images/features/document_revision_workspace.png'",
        "'path': 'images/features/document_revision_delete_compare.png'",
        "'path': 'images/features/conversation_summary_card.png'",
        "'path': 'images/features/pdf_export_option.png'",
        "'path': 'images/features/per_message_export_menu.png'",
        "'path': 'images/features/agent_action_grid_view.png'",
        "'path': 'images/features/sql_test_connection.png'",
        "'path': 'images/features/thoughts_visibility.png'",
        "'path': 'images/features/support_menu_entry.png'",
        "'fragment': 'fact-memory-settings'",
        "'why': 'This matters because the fastest way to learn a new workflow is usually inside the workflow itself, with the right controls highlighted as you go, while still letting each user hide the launcher once they are comfortable with the app.'",
        "'endpoint': 'chats'",
        "'fragment': 'workspace-tutorial-launch'",
        "'fragment': 'upload-area'",
        "'requires_settings': ['enable_user_workspace']",
        'def get_visible_support_latest_features(settings):',
        'def _normalize_feature_media(feature):',
    ]
    missing_config = [marker for marker in config_markers if marker not in config_content]
    assert not missing_config, f'Missing support feature catalog markers: {missing_config}'

    print('✅ Support menu settings and catalog markers are present')


def test_support_menu_admin_template_and_js():
    print('🔍 Testing support menu admin template and JavaScript...')

    template_content = read_text(ADMIN_TEMPLATE)
    js_content = read_text(ADMIN_JS)

    template_markers = [
        'id="support-menu-section"',
        'id="enable_support_menu"',
        'id="support_menu_name"',
        'id="enable_support_send_feedback"',
        'id="support_feedback_recipient_email"',
        'id="enable_support_latest_features"',
        'id="support_latest_feature_{{ feature.id }}"',
        'name="support_latest_feature_{{ feature.id }}"',
        '{{ feature.title }}',
        'Enable Support Menu for End Users',
        'Deployment and Redis start unchecked because they are mainly admin-facing rollout and infrastructure topics.',
        '<i class="bi bi-life-preserver me-2"></i>Support Menu',
    ]
    missing_template = [marker for marker in template_markers if marker not in template_content]
    assert not missing_template, f'Missing support menu admin template markers: {missing_template}'

    js_markers = [
        'setupSupportMenuSettings();',
        'function setupSupportMenuSettings() {',
        'function toggleSupportMenuSettingsVisibility() {',
        'function toggleSupportFeedbackRecipientVisibility() {',
        'function toggleSupportLatestFeaturesVisibility() {',
        "const enableSupportMenuToggle = document.getElementById('enable_support_menu');",
    ]
    missing_js = [marker for marker in js_markers if marker not in js_content]
    assert not missing_js, f'Missing support menu admin JavaScript markers: {missing_js}'

    print('✅ Support menu admin template and JavaScript markers are present')


def test_support_menu_navigation_and_routes():
    print('🔍 Testing support menu navigation and routes...')

    sidebar_content = read_text(SIDEBAR_TEMPLATE)
    short_sidebar_content = read_text(SHORT_SIDEBAR_TEMPLATE)
    top_nav_content = read_text(TOP_NAV_TEMPLATE)
    support_route_content = read_text(SUPPORT_ROUTE)

    sidebar_markers = [
        'data-section="support-menu-section"',
        'id="support-menu-toggle"',
        "url_for('support_latest_features')",
        "url_for('support_send_feedback')",
        "app_settings.support_menu_name or 'Support'",
    ]
    missing_sidebar = [marker for marker in sidebar_markers if marker not in sidebar_content]
    assert not missing_sidebar, f'Missing support menu sidebar markers: {missing_sidebar}'

    assert sidebar_content.index('id="support-menu-toggle"') < sidebar_content.index('id="external-links-toggle"'), 'Support menu should render before external links in the sidebar'

    short_sidebar_markers = [
        'id="support-menu-toggle"',
        "url_for('support_latest_features')",
        "url_for('support_send_feedback')",
        "app_settings.support_menu_name or 'Support'",
    ]
    missing_short_sidebar = [marker for marker in short_sidebar_markers if marker not in short_sidebar_content]
    assert not missing_short_sidebar, f'Missing support menu short-sidebar markers: {missing_short_sidebar}'

    top_nav_markers = [
        'id="supportMenuDropdown"',
        "url_for('support_latest_features')",
        "url_for('support_send_feedback')",
        "app_settings.support_menu_name or 'Support'",
    ]
    missing_top_nav = [marker for marker in top_nav_markers if marker not in top_nav_content]
    assert not missing_top_nav, f'Missing support menu top-nav markers: {missing_top_nav}'
    assert top_nav_content.index('id="supportMenuDropdown"') < top_nav_content.index('id="externalLinksDropdown"'), 'Support menu should render before external links in top navigation'

    route_markers = [
        "@app.route('/support/latest-features')",
        "def support_latest_features():",
        "render_template(",
        "'latest_features.html'",
        "@app.route('/support/send-feedback')",
        "def support_send_feedback():",
        "render_template('support_send_feedback.html')",
        "@enabled_required('enable_support_menu')",
        "return 'Forbidden', 403",
    ]
    missing_routes = [marker for marker in route_markers if marker not in support_route_content]
    assert not missing_routes, f'Missing support route markers: {missing_routes}'

    print('✅ Support menu navigation and routes are present')


def test_support_menu_feedback_backend_and_templates():
    print('🔍 Testing support menu feedback backend and user templates...')

    backend_content = read_text(BACKEND_SETTINGS)
    logging_content = read_text(ACTIVITY_LOGGING)
    latest_features_content = read_text(LATEST_FEATURES_TEMPLATE)
    support_feedback_content = read_text(SUPPORT_FEEDBACK_TEMPLATE)
    latest_features_js_content = read_text(LATEST_FEATURES_JS)
    support_js_content = read_text(SUPPORT_JS)

    backend_markers = [
        "@app.route('/api/support/send_feedback_email', methods=['POST'])",
        'def send_support_feedback_email():',
        "return jsonify({'error': 'Support menu is available to signed-in app users only'}), 403",
        'log_user_support_feedback_email_submission(',
        "'[SimpleChat User Support]",
    ]
    missing_backend = [marker for marker in backend_markers if marker not in backend_content]
    assert not missing_backend, f'Missing support feedback backend markers: {missing_backend}'

    logging_markers = [
        'def log_user_support_feedback_email_submission(',
        "'activity_type': 'user_support_feedback_email_submission'",
        "message='[Support Feedback] Mailto draft prepared'",
    ]
    missing_logging = [marker for marker in logging_markers if marker not in logging_content]
    assert not missing_logging, f'Missing support feedback logging markers: {missing_logging}'

    latest_features_markers = [
        'A curated view of recent updates your admins have chosen to share with end users.',
        '{% if support_latest_features %}',
        'support-feature-card',
        'support-feature-gallery',
        'support-feature-thumbnail-trigger',
        'support-feature-thumbnail-title',
        'support-feature-callout',
        'support-feature-guidance-list',
        'support-feature-action-grid',
        'support-feature-action-card',
        'support-feature-action-label',
        'data-latest-feature-image-src=',
        '{% if feature.images %}',
        '{{ image.label }}',
        '{{ feature.why }}',
        '{% if feature.guidance %}',
        '{% if feature.actions %}',
        'Why It Matters',
        'How To Try It',
        'Open The Right Page',
        "url_for(action.endpoint)",
        'latestFeatureImageModal',
        'latestFeatureImageModalImage',
        '{{ feature.title }}',
    ]
    missing_latest = [marker for marker in latest_features_markers if marker not in latest_features_content]
    assert not missing_latest, f'Missing latest features template markers: {missing_latest}'

    latest_features_js_markers = [
        'function setupLatestFeatureImageModal() {',
        "document.getElementById('latestFeatureImageModal')",
        "document.querySelectorAll('[data-latest-feature-image-src]')",
        'imageModal.show();',
    ]
    missing_latest_features_js = [marker for marker in latest_features_js_markers if marker not in latest_features_js_content]
    assert not missing_latest_features_js, f'Missing latest features JavaScript markers: {missing_latest_features_js}'

    support_feedback_markers = [
        'id="support-send-feedback-pane"',
        'class="support-send-feedback-form" data-feedback-type="bug_report"',
        'class="support-send-feedback-form" data-feedback-type="feature_request"',
        'support-send-feedback-status',
        'support_feedback_bug_name',
        'support_feedback_feature_details',
    ]
    missing_feedback_template = [marker for marker in support_feedback_markers if marker not in support_feedback_content]
    assert not missing_feedback_template, f'Missing support feedback template markers: {missing_feedback_template}'

    support_js_markers = [
        "fetch('/api/support/send_feedback_email'",
        'function buildSupportFeedbackMailtoUrl(',
        'support-send-feedback-pane',
        'support-send-feedback-submit',
    ]
    missing_support_js = [marker for marker in support_js_markers if marker not in support_js_content]
    assert not missing_support_js, f'Missing support feedback JavaScript markers: {missing_support_js}'

    print('✅ Support feedback backend and user templates are present')


if __name__ == '__main__':
    tests = [
        test_support_menu_settings_defaults_and_persistence,
        test_support_menu_admin_template_and_js,
        test_support_menu_navigation_and_routes,
        test_support_menu_feedback_backend_and_templates,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f'❌ {test.__name__} failed: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)
        print()

    passed = sum(1 for result in results if result)
    print(f'📊 Results: {passed}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)