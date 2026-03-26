#!/usr/bin/env python3
# test_admin_latest_features_tab.py
"""
Functional test for admin Latest Features tab.
Version: 0.240.007
Implemented in: 0.240.002

This test ensures that the Admin Settings page exposes the Latest Features tab,
renders the expected grouped cards, and includes the mirrored controls and
JavaScript synchronization needed to keep shared settings aligned.
"""

import os
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

ADMIN_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'admin_settings.html')
SIDEBAR_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', '_sidebar_nav.html')
ADMIN_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'admin', 'admin_settings.js')
FEATURE_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'features', 'LATEST_FEATURES_ADMIN_TAB.md')
FEATURE_IMAGE_DIR = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'images', 'features')


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def test_latest_features_template_structure():
    """Admin Settings template must expose the Latest Features tab and grouped cards."""
    print('🔍 Testing Latest Features tab structure in admin_settings.html...')

    template_content = read_text(ADMIN_TEMPLATE)

    required_markers = [
        'id="latest-features-tab"',
        'data-bs-target="#latest-features"',
        'id="latest-features"',
        'id="latest-features-guided-tutorials-card"',
        'id="latest-features-background-chat-card"',
        'id="latest-features-tabular-card"',
        'id="latest-features-export-card"',
        'id="latest-features-agent-ops-card"',
        'id="latest-features-thoughts-card"',
        'id="latest-features-deployment-card"',
        'id="latest-features-redis-card"',
        'id="latest-features-send-feedback-card"',
        'static/images/features/guided_tutorials_chat.png',
        'static/images/features/gunicorn_startup_guidance.png',
        'static/images/features/redis_key_vault.png'
    ]

    missing_markers = [marker for marker in required_markers if marker not in template_content]
    if missing_markers:
        raise AssertionError(f'Missing Latest Features template markers: {missing_markers}')

    assert template_content.count('id="latest-features" role="tabpanel"') == 1, 'Latest Features tab pane should appear exactly once'

    print('✅ Latest Features tab structure is present')
    return True


def test_latest_features_mirrored_controls():
    """Latest Features tab must expose mirrored control ids with proxy metadata for autofill safety."""
    print('🔍 Testing mirrored Latest Features controls...')

    template_content = read_text(ADMIN_TEMPLATE)

    required_ids = [
        'id="latest_features_enable_thoughts"',
        'id="latest_features_enable_enhanced_citations"',
        'id="latest_features_office_docs_authentication_type"',
        'id="latest_features_office_docs_storage_account_url"',
        'id="latest_features_office_docs_storage_account_blob_endpoint"',
        'id="latest_features_tabular_preview_max_blob_size_mb"'
    ]

    for marker in required_ids:
        assert marker in template_content, f'Missing mirrored control: {marker}'

    required_proxy_markers = [
        'name="latest_features_enable_thoughts_proxy"',
        'name="latest_features_enable_enhanced_citations_proxy"',
        'name="latest_features_office_docs_authentication_type_proxy"',
        'name="latest_features_office_docs_storage_account_url_proxy"',
        'name="latest_features_office_docs_storage_account_blob_endpoint_proxy"',
        'name="latest_features_tabular_preview_max_blob_size_mb_proxy"',
        'autocomplete="off"',
        'data-ignore-settings-change="true"',
        'data-lpignore="true"',
        'data-1p-ignore="true"',
        'data-bwignore="true"'
    ]

    missing_proxy_markers = [marker for marker in required_proxy_markers if marker not in template_content]
    if missing_proxy_markers:
        raise AssertionError(f'Missing proxy metadata on mirrored controls: {missing_proxy_markers}')

    disallowed_names = [
        'name="latest_features_enable_thoughts"',
        'name="latest_features_enable_enhanced_citations"',
        'name="latest_features_office_docs_authentication_type"',
        'name="latest_features_office_docs_storage_account_url"',
        'name="latest_features_office_docs_storage_account_blob_endpoint"',
        'name="latest_features_tabular_preview_max_blob_size_mb"'
    ]

    duplicates = [marker for marker in disallowed_names if marker in template_content]
    if duplicates:
        raise AssertionError(f'Mirrored controls should not submit canonical names: {duplicates}')

    print('✅ Mirrored controls are present with explicit proxy autofill metadata')
    return True


def test_latest_features_sync_javascript():
    """Admin settings JS must synchronize mirrored controls with canonical fields."""
    print('🔍 Testing Latest Features sync JavaScript...')

    js_content = read_text(ADMIN_JS)

    required_markers = [
        'setupAdminFormAutofillMetadata()',
        'function setupAdminFormAutofillMetadata() {',
        'setupLatestFeaturesMirrors()',
        'function setupLatestFeaturesMirrors()',
        'function syncMirroredField(',
        'function updateLatestFeaturesEnhancedCitationMirror()',
        'function updateOfficeStorageMirrorVisibility(',
        'latest_features_enable_thoughts',
        'latest_features_enable_enhanced_citations',
        "field.setAttribute('autocomplete', 'off');",
        'toggle_latest_features_office_conn_str',
        'toggle_latest_features_office_url'
    ]

    missing_markers = [marker for marker in required_markers if marker not in js_content]
    if missing_markers:
        raise AssertionError(f'Missing Latest Features JavaScript markers: {missing_markers}')

    print('✅ Latest Features synchronization JavaScript is present')
    return True


def test_latest_features_sidebar_navigation():
    """Admin sidebar must expose Latest Features as a reachable tab with section links."""
    print('🔍 Testing Latest Features sidebar navigation...')

    sidebar_content = read_text(SIDEBAR_TEMPLATE)

    required_markers = [
        'data-tab="latest-features"',
        'id="latest-features-submenu"',
        'data-section="latest-features-guided-tutorials-card"',
        'data-section="latest-features-tabular-card"',
        'data-section="latest-features-thoughts-card"',
        'data-section="latest-features-deployment-card"'
    ]

    missing_markers = [marker for marker in required_markers if marker not in sidebar_content]
    if missing_markers:
        raise AssertionError(f'Missing Latest Features sidebar markers: {missing_markers}')

    latest_features_index = sidebar_content.index('data-tab="latest-features"')
    general_index = sidebar_content.index('data-tab="general"')
    assert latest_features_index < general_index, 'Latest Features should appear before General in the admin sidebar'
    assert '<span class="badge bg-warning text-dark text-uppercase ms-2">New</span>' in sidebar_content, 'Sidebar Latest Features item should include a New badge'

    print('✅ Latest Features sidebar navigation is present')
    return True


def test_latest_features_top_nav_priority():
    """Latest Features should be the first top-nav tab and default active pane when top navigation is shown."""
    print('🔍 Testing Latest Features top-nav priority...')

    template_content = read_text(ADMIN_TEMPLATE)

    latest_features_tab_index = template_content.index('id="latest-features-tab"')
    general_tab_index = template_content.index('id="general-tab"')
    assert latest_features_tab_index < general_tab_index, 'Latest Features tab should appear before General in top nav'

    assert 'id="latest-features-tab" data-bs-toggle="tab" data-bs-target="#latest-features"' in template_content, 'Latest Features top-nav tab missing'
    assert 'Latest Features <span class="badge bg-warning text-dark text-uppercase ms-2 latest-feature-nav-badge">New</span>' in template_content, 'Latest Features top-nav tab should include a New badge'
    assert 'class="tab-pane fade show active" id="latest-features" role="tabpanel" aria-labelledby="latest-features-tab"' in template_content, 'Latest Features pane should be the default active tab'

    print('✅ Latest Features is prioritized in top navigation')
    return True


def test_admin_settings_tab_uniqueness():
    """Admin settings template should not contain duplicate Security tab controls or extra active panes."""
    print('🔍 Testing admin settings tab uniqueness...')

    template_content = read_text(ADMIN_TEMPLATE)
    normalized_template = ''.join(template_content.split())

    assert template_content.count('id="security-tab"') == 1, 'Security tab button should appear exactly once'
    assert template_content.count('id="security" role="tabpanel"') == 1, 'Security tab pane should appear exactly once'
    assert template_content.count('tab-pane fade show active') == 1, 'Only one tab pane should be marked show active in top-nav markup'
    assert 'Managesecuritysettingsforkeyvaultandothersecurityconfigurations.</p>' in normalized_template, 'Security intro paragraph should be properly closed'

    print('✅ Admin settings tab structure is unique and well-formed')
    return True


def test_latest_features_supporting_assets():
    """Feature documentation and placeholder image directory must exist."""
    print('🔍 Testing supporting assets for Latest Features...')

    assert os.path.exists(FEATURE_DOC), 'Missing feature documentation for Latest Features tab'
    assert os.path.isdir(FEATURE_IMAGE_DIR), 'Missing placeholder image directory for Latest Features'

    doc_content = read_text(FEATURE_DOC)
    assert 'Version Implemented: 0.240.003' in doc_content, 'Feature documentation version header missing or incorrect'

    print('✅ Supporting documentation and image directory are present')
    return True


if __name__ == '__main__':
    print('🧪 Running Latest Features Admin Tab tests...\n')

    tests = [
        test_latest_features_template_structure,
        test_latest_features_mirrored_controls,
        test_latest_features_sync_javascript,
        test_latest_features_sidebar_navigation,
        test_latest_features_top_nav_priority,
        test_admin_settings_tab_uniqueness,
        test_latest_features_supporting_assets,
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
