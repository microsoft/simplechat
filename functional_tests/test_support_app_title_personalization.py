# test_support_app_title_personalization.py
"""
Functional test for support application-title personalization.
Version: 0.241.002
Implemented in: 0.241.002

This test ensures that user-facing Support pages replace hard-coded SimpleChat
copy with the configured application title for latest-feature content and the
Send Feedback experience.
"""

import importlib.util
import os
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

SUPPORT_CONFIG = os.path.join(REPO_ROOT, 'application', 'single_app', 'support_menu_config.py')
SUPPORT_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'support_send_feedback.html')
BACKEND_SETTINGS = os.path.join(REPO_ROOT, 'application', 'single_app', 'route_backend_settings.py')


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def load_module(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _collect_strings(value):
    if isinstance(value, str):
        return [value]

    if isinstance(value, list):
        strings = []
        for item in value:
            strings.extend(_collect_strings(item))
        return strings

    if isinstance(value, dict):
        strings = []
        for item in value.values():
            strings.extend(_collect_strings(item))
        return strings

    return []


def test_support_latest_features_use_application_title():
    print('🔍 Testing support latest-features app-title personalization...')

    support_config = load_module(SUPPORT_CONFIG, 'support_app_title_personalization_test')
    settings = {
        'app_title': 'Contoso Assist',
        'enable_support_send_feedback': True,
        'enable_support_latest_feature_documentation_links': True,
        'enable_user_workspace': True,
        'enable_semantic_kernel': True,
        'per_user_semantic_kernel': True,
        'support_latest_features_visibility': support_config.get_default_support_latest_features_visibility(),
    }

    visible_groups = support_config.get_visible_support_latest_feature_groups(settings)
    visible_strings = _collect_strings(visible_groups)

    assert visible_groups, 'Expected visible support feature groups for personalized copy testing'
    assert any('Contoso Assist admins' in value for value in visible_strings), 'Expected Send Feedback copy to use the configured application title'
    assert any('inside Contoso Assist' in value for value in visible_strings), 'Expected previous-release copy to use the configured application title'
    assert not any('SimpleChat administrators' in value for value in visible_strings), 'Found hard-coded SimpleChat administrators copy in visible support features'
    assert not any('inside SimpleChat' in value for value in visible_strings), 'Found hard-coded SimpleChat copy in previous-release support features'

    print('✅ Support latest-features content uses the configured application title')


def test_support_send_feedback_template_and_subject_are_dynamic():
    print('🔍 Testing Send Feedback application-title markers...')

    template_content = read_text(SUPPORT_TEMPLATE)
    backend_content = read_text(BACKEND_SETTINGS)

    assert '{{ app_settings.app_title }} administrators' in template_content, 'Send Feedback template should use the configured application title in its intro copy'
    assert "application_title = str(settings.get('app_title') or '').strip() or 'Simple Chat'" in backend_content, 'Support feedback mailto generation should resolve the configured application title'
    assert "subject_line = f'[{application_title} User Support] {feedback_label} - {organization}'" in backend_content, 'Support feedback subject should use the configured application title'

    print('✅ Send Feedback template and draft subject use the configured application title')


if __name__ == '__main__':
    tests = [
        test_support_latest_features_use_application_title,
        test_support_send_feedback_template_and_subject_are_dynamic,
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