#!/usr/bin/env python3
# test_profile_and_admin_review_tabs.py
"""
Functional test for profile and admin review tabs.
Version: 0.241.119
Implemented in: 0.241.115; 0.241.118; 0.241.119

This test ensures the profile page and the admin feedback and safety review pages
expose the new tabbed layout, legacy entry points deep-link into the profile
experience, and the supporting stats and export endpoints remain wired.
"""

import ast
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent

PROFILE_ROUTE = ROOT_DIR / 'application' / 'single_app' / 'route_frontend_profile.py'
FRONTEND_FEEDBACK_ROUTE = ROOT_DIR / 'application' / 'single_app' / 'route_frontend_feedback.py'
FRONTEND_SAFETY_ROUTE = ROOT_DIR / 'application' / 'single_app' / 'route_frontend_safety.py'
BACKEND_FEEDBACK_ROUTE = ROOT_DIR / 'application' / 'single_app' / 'route_backend_feedback.py'
BACKEND_SAFETY_ROUTE = ROOT_DIR / 'application' / 'single_app' / 'route_backend_safety.py'
PROFILE_TEMPLATE = ROOT_DIR / 'application' / 'single_app' / 'templates' / 'profile.html'
TOP_NAV_TEMPLATE = ROOT_DIR / 'application' / 'single_app' / 'templates' / '_top_nav.html'
SIDEBAR_TEMPLATE = ROOT_DIR / 'application' / 'single_app' / 'templates' / '_sidebar_nav.html'
SIDEBAR_SHORT_TEMPLATE = ROOT_DIR / 'application' / 'single_app' / 'templates' / '_sidebar_short_nav.html'
ADMIN_FEEDBACK_TEMPLATE = ROOT_DIR / 'application' / 'single_app' / 'templates' / 'admin_feedback_review.html'
ADMIN_SAFETY_TEMPLATE = ROOT_DIR / 'application' / 'single_app' / 'templates' / 'admin_safety_violations.html'
PROFILE_JS = ROOT_DIR / 'application' / 'single_app' / 'static' / 'js' / 'profile' / 'profile-tabs.js'
ADMIN_FEEDBACK_JS = ROOT_DIR / 'application' / 'single_app' / 'static' / 'js' / 'admin' / 'admin-feedback-review.js'
ADMIN_SAFETY_JS = ROOT_DIR / 'application' / 'single_app' / 'static' / 'js' / 'admin' / 'admin-safety-violations.js'
FEATURE_DOC = ROOT_DIR / 'docs' / 'explanation' / 'features' / 'v0.241.115' / 'PROFILE_AND_ADMIN_REVIEW_TABS.md'


def read_text(path):
    return path.read_text(encoding='utf-8')


def assert_markers(source_text, markers, label):
    missing_markers = [marker for marker in markers if marker not in source_text]
    assert not missing_markers, f'Missing {label} markers: {missing_markers}'


def test_profile_tabs_and_legacy_routes():
    """Profile page should expose the four-tab layout and keep legacy links working."""
    print('🔍 Testing profile tab shell and legacy deep links...')

    profile_route = read_text(PROFILE_ROUTE)
    feedback_route = read_text(FRONTEND_FEEDBACK_ROUTE)
    safety_route = read_text(FRONTEND_SAFETY_ROUTE)
    profile_template = read_text(PROFILE_TEMPLATE)
    profile_js = read_text(PROFILE_JS)

    assert_markers(
        profile_route,
        [
            "request.args.get('tab', 'stats')",
            "initial_tab=initial_tab",
        ],
        'profile route',
    )

    assert_markers(
        feedback_route,
        ["return redirect(url_for('profile', tab='feedback'))"],
        'frontend feedback redirect',
    )
    assert_markers(
        safety_route,
        ["return redirect(url_for('profile', tab='violations'))"],
        'frontend safety redirect',
    )

    assert_markers(
        profile_template,
        [
            'id="profile-stats-tab"',
            'id="profile-settings-tab"',
            'id="profile-feedback-tab"',
            'id="profile-violations-tab"',
            'id="profile-feedback-export-btn"',
            'id="profile-violations-export-btn"',
            'window.profilePageConfig = {',
            "<script src=\"{{ url_for('static', filename='js/profile/profile-tabs.js') }}\"></script>",
        ],
        'profile template',
    )

    config_position = profile_template.index('window.profilePageConfig = {')
    include_position = profile_template.index("<script src=\"{{ url_for('static', filename='js/profile/profile-tabs.js') }}\"></script>")
    previous_page_marker = "const previousPageButton = document.getElementById('fact-memory-prev-page');"
    previous_page_position = profile_template.index(previous_page_marker)
    assert config_position < include_position, 'profilePageConfig must be initialized before profile-tabs.js loads'
    assert profile_template.find('window.profilePageConfig = {', previous_page_position) == -1, (
        'profilePageConfig should not be assigned inside the delayed fact-memory pager block'
    )

    assert_markers(
        profile_js,
        [
            '/feedback/my/stats',
            '/feedback/my/export',
            '/api/safety/logs/my/stats',
            '/api/safety/logs/my/export',
            'function refreshProfileFeedback()',
            'function refreshProfileViolations()',
        ],
        'profile tab script',
    )

    print('✅ Profile tab shell and legacy deep links are present')
    return True


def test_navigation_links_point_to_profile_tabs():
    """Navigation entry points should route user feedback and violations through profile tabs."""
    print('🔍 Testing navigation links for profile tab deep links...')

    expected_feedback_link = "url_for('profile', tab='feedback')"
    expected_violations_link = "url_for('profile', tab='violations')"

    for template_path in [TOP_NAV_TEMPLATE, SIDEBAR_TEMPLATE, SIDEBAR_SHORT_TEMPLATE]:
        template_text = read_text(template_path)
        assert expected_feedback_link in template_text, f'Missing feedback profile link in {template_path.name}'
        assert expected_violations_link in template_text, f'Missing violations profile link in {template_path.name}'

    print('✅ Navigation links point to the profile feedback and violations tabs')
    return True


def test_admin_review_tabs_and_scripts():
    """Admin feedback and safety pages should expose tabbed shells backed by dedicated scripts."""
    print('🔍 Testing admin feedback and safety tabbed review shells...')

    admin_feedback_template = read_text(ADMIN_FEEDBACK_TEMPLATE)
    admin_safety_template = read_text(ADMIN_SAFETY_TEMPLATE)
    admin_feedback_js = read_text(ADMIN_FEEDBACK_JS)
    admin_safety_js = read_text(ADMIN_SAFETY_JS)

    assert_markers(
        admin_feedback_template,
        [
            'id="feedback-stats-tab"',
            'id="feedback-data-tab"',
            'id="feedbackExportBtn"',
            'id="feedbackEditStatus"',
            "<script src=\"{{ url_for('static', filename='js/admin/admin-feedback-review.js') }}\"></script>",
        ],
        'admin feedback template',
    )
    assert_markers(
        admin_feedback_js,
        [
            '/feedback/review/stats',
            '/feedback/review/export',
            "document.getElementById('feedbackEditStatus')",
            'async function saveFeedbackChanges()',
        ],
        'admin feedback script',
    )
    assert 'alert(' not in admin_feedback_js, 'Admin feedback script should not use alert() fallbacks'

    assert_markers(
        admin_safety_template,
        [
            'id="safety-stats-tab"',
            'id="safety-data-tab"',
            'id="safetyExportBtn"',
            'id="safetyEditStatus"',
            "<script src=\"{{ url_for('static', filename='js/admin/admin-safety-violations.js') }}\"></script>",
        ],
        'admin safety template',
    )
    assert_markers(
        admin_safety_js,
        [
            '/api/safety/logs/stats',
            '/api/safety/logs/export',
            "document.getElementById('safetyEditStatus')",
            'async function saveSafetyChanges()',
        ],
        'admin safety script',
    )
    assert 'alert(' not in admin_safety_js, 'Admin safety script should not use alert() fallbacks'

    print('✅ Admin feedback and safety tabbed shells are present')
    return True


def test_stats_and_export_endpoints_and_documentation():
    """Backend routes and feature documentation should capture the new tabbed review experience."""
    print('🔍 Testing backend stats/export endpoints and feature documentation...')

    backend_feedback_route = read_text(BACKEND_FEEDBACK_ROUTE)
    backend_safety_route = read_text(BACKEND_SAFETY_ROUTE)

    assert_markers(
        backend_feedback_route,
        [
            '@app.route("/feedback/review/stats", methods=["GET"])',
            '@app.route("/feedback/review/export", methods=["GET"])',
            '@app.route("/feedback/my/stats", methods=["GET"])',
            '@app.route("/feedback/my/export", methods=["GET"])',
        ],
        'backend feedback route',
    )
    assert_markers(
        backend_safety_route,
        [
            "@app.route('/api/safety/logs/stats', methods=['GET'])",
            "@app.route('/api/safety/logs/export', methods=['GET'])",
            "@app.route('/api/safety/logs/my/stats', methods=['GET'])",
            "@app.route('/api/safety/logs/my/export', methods=['GET'])",
        ],
        'backend safety route',
    )

    assert FEATURE_DOC.exists(), 'Missing profile/admin review tab feature documentation'
    feature_doc = read_text(FEATURE_DOC)
    assert_markers(
        feature_doc,
        [
            '# Profile And Admin Review Tabs',
            'Documentation Version: 0.241.119',
            'Version Implemented: 0.241.115',
            'Related Config Update: `application/single_app/config.py` -> `VERSION = "0.241.119"`',
            '## Testing and Validation',
        ],
        'feature documentation',
    )

    print('✅ Backend endpoints and feature documentation are present')
    return True


def test_feedback_stats_normalize_lowercase_feedback_types():
    """Feedback stats should count lowercase legacy values the same as canonical values."""
    print('🔍 Testing feedback stat normalization for lowercase feedback types...')

    source = read_text(BACKEND_FEEDBACK_ROUTE)
    module = ast.parse(source)
    wanted_symbols = {
        'FEEDBACK_TYPE_NORMALIZATION',
        '_normalize_feedback_type',
        '_serialize_feedback_item',
        '_build_feedback_stats',
    }

    selected_nodes = []
    for node in module.body:
        if isinstance(node, ast.Assign):
            target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(target_name in wanted_symbols for target_name in target_names):
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_symbols:
            selected_nodes.append(node)

    namespace = {}
    exec('from datetime import datetime, timedelta', namespace)
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), 'feedback_subset', 'exec'), namespace)

    positive_item = namespace['_serialize_feedback_item']({
        'feedbackType': 'positive',
        'adminReview': {},
        'timestamp': '2026-05-01T00:00:00',
    })
    negative_item = namespace['_serialize_feedback_item']({
        'feedbackType': 'negative',
        'adminReview': {},
        'timestamp': '2026-05-01T00:00:00',
    })
    neutral_item = namespace['_serialize_feedback_item']({
        'feedbackType': 'Neutral',
        'adminReview': {'acknowledged': True},
        'timestamp': '2026-05-01T00:00:00',
    })
    stats = namespace['_build_feedback_stats']([positive_item, negative_item, neutral_item])

    assert positive_item['feedbackType'] == 'Positive', 'Lowercase positive feedback should normalize to Positive'
    assert negative_item['feedbackType'] == 'Negative', 'Lowercase negative feedback should normalize to Negative'
    assert stats['positive_count'] == 1, 'Positive count should include lowercase positive values'
    assert stats['negative_count'] == 1, 'Negative count should include lowercase negative values'
    assert stats['neutral_count'] == 1, 'Neutral count should still count canonical values'

    print('✅ Feedback stat normalization handles lowercase legacy values')
    return True


if __name__ == '__main__':
    print('🧪 Running profile and admin review tab tests...\n')

    tests = [
        test_profile_tabs_and_legacy_routes,
        test_navigation_links_point_to_profile_tabs,
        test_admin_review_tabs_and_scripts,
        test_stats_and_export_endpoints_and_documentation,
        test_feedback_stats_normalize_lowercase_feedback_types,
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
    raise SystemExit(0 if all(results) else 1)
