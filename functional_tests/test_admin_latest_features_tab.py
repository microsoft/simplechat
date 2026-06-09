#!/usr/bin/env python3
# test_admin_latest_features_tab.py
"""
Functional test for admin Latest Features tab.
Version: 0.241.167
Implemented in: 0.240.074; 0.240.085; 0.241.002; 0.241.164; 0.241.165; 0.241.166

This test ensures that the Admin Settings page exposes the Latest Features tab,
renders the expected catalog-driven release groups, uses the saved feature
screenshots, and includes the mirrored controls and JavaScript synchronization
needed to keep shared settings aligned.
"""

import importlib.util
import os
import sys


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

ADMIN_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'admin_settings.html')
SIDEBAR_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', '_sidebar_nav.html')
ADMIN_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'admin', 'admin_settings.js')
SUPPORT_CONFIG = os.path.join(REPO_ROOT, 'application', 'single_app', 'support_menu_config.py')
FEATURE_DOC = os.path.join(REPO_ROOT, 'docs', 'explanation', 'features', 'v0.241.002', 'LATEST_FEATURES_ADMIN_TAB.md')
FEATURE_IMAGE_DIR = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'images', 'features')

CURRENT_FEATURE_IMAGE_FILES = {
    'document_intelligence': ['document_intelligence_admin_controls.png'],
    'cosmos_autoscale': ['cosmos_autoscale_admin_controls.png'],
    'file_sync': ['file_sync_admin_scope_controls.png'],
    'source_review': ['source_review_admin_policy.png'],
    'agent_knowledge_actions': ['agent_knowledge_actions_assigned_knowledge.png'],
    'generated_artifacts': ['generated_artifacts_chat_artifacts.png'],
    'chat_productivity': ['chat_productivity_chat_toolbar.png'],
    'workspace_experience': ['workspace_experience_document_cards.png'],
    'workflow_automation': ['workflow_automation_admin_controls.png'],
    'visio_ingestion': ['visio_ingestion_workspace_upload.png'],
    'stats_reporting': ['stats_reporting_profile_dashboard.png'],
}


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def load_module(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_latest_features_catalog_release_groups():
    """Latest Features catalog must expose current, previous, and earlier release groups."""
    print('🔍 Testing Latest Features catalog release groups...')

    support_config = load_module(SUPPORT_CONFIG, 'support_menu_config_for_admin_latest_features_test')
    release_groups = support_config.get_support_latest_feature_release_groups()

    assert [group['id'] for group in release_groups] == [
        'current_release',
        'previous_release',
        'earlier_release',
    ]

    current_feature_ids = [feature['id'] for feature in release_groups[0]['features']]
    assert current_feature_ids == [
        'document_intelligence',
        'cosmos_autoscale',
        'file_sync',
        'source_review',
        'agent_knowledge_actions',
        'generated_artifacts',
        'chat_productivity',
        'workspace_experience',
        'workflow_automation',
        'visio_ingestion',
        'stats_reporting',
    ]

    assert release_groups[1]['release_version'] == '0.241.001 - 0.241.008'
    assert release_groups[2]['release_version'] == '0.239.001'
    assert len(release_groups[1]['features']) == 14
    assert len(release_groups[2]['features']) == 8

    default_visibility = support_config.get_default_support_latest_features_visibility()
    assert default_visibility['cosmos_autoscale'] is False
    assert default_visibility['deployment'] is False
    assert default_visibility['redis_key_vault'] is False
    assert default_visibility['document_intelligence'] is True

    for feature in release_groups[0]['features']:
        expected_files = CURRENT_FEATURE_IMAGE_FILES[feature['id']]
        expected_paths = [f'images/features/{image_name}' for image_name in expected_files]
        images = feature.get('images', [])
        assert feature.get('image') == expected_paths[0], f"Primary image mismatch for {feature['id']}"
        assert feature.get('image_alt'), f"Missing primary image alt text for {feature['id']}"
        assert [image['path'] for image in images] == expected_paths, f"Gallery image paths mismatch for {feature['id']}"
        assert all(image.get('caption') for image in images), f"Gallery captions missing for {feature['id']}"
        assert all(image.get('label') for image in images), f"Gallery labels missing for {feature['id']}"
        assert not any(image.get('label') == 'Feature Guide' for image in images), f"Redundant Feature Guide image remains for {feature['id']}"
        assert not any('feature_card' in image['path'] for image in images), f"Redundant feature-card asset remains for {feature['id']}"

    print('✅ Latest Features catalog release groups are current')
    return True


def test_latest_features_template_structure():
    """Admin Settings template must expose the Latest Features tab and grouped cards."""
    print('🔍 Testing Latest Features tab structure in admin_settings.html...')

    template_content = read_text(ADMIN_TEMPLATE)

    required_markers = [
        'id="latest-features-tab"',
        'data-bs-target="#latest-features"',
        'id="latest-features"',
        'support_latest_feature_release_groups_preview',
        "release_group.id == 'current_release'",
        "{% set feature_card_id = 'latest-features-' ~ feature.id|replace('_', '-') ~ '-card' %}",
        "{% set feature_collapse_id = 'latestFeatures-' ~ feature.id|replace('_', '-') %}",
        'id="{{ feature_card_id }}"',
        '<i class="bi {{ feature.icon }} me-2"></i>{{ feature.title }}',
        '{{ feature.summary }}',
        "release_group.id != 'current_release'",
        'latest-features-previous-release-card',
        'latestFeaturesPreviousRelease',
        "'latest-features-' ~ release_group.id|replace('_', '-') ~ '-card'",
        "'latestFeatures-' ~ release_group.id|replace('_', '-')",
        'id="latestFeatureImageModal"',
        'class="latest-feature-image-frame"',
        "release_group.id == 'previous_release'",
        '<i class="bi bi-clock-history me-2"></i>{{ release_group.label }}',
        'Keeping them here gives admins a simple archive view',
        'Shared with Users',
        'Hidden from Users',
        '{% if feature.images %}',
        'data-latest-feature-image-src="{{ url_for(\'static\', filename=image.path) }}"',
        '{{ image.label }}',
        'General &gt; User-Facing Latest Features',
        'User-Facing Latest Features'
    ]

    missing_markers = [marker for marker in required_markers if marker not in template_content]
    if missing_markers:
        raise AssertionError(f'Missing Latest Features template markers: {missing_markers}')

    assert template_content.count('id="latest-features" role="tabpanel"') == 1, 'Latest Features tab pane should appear exactly once'
    assert template_content.index("release_group.id == 'current_release'") < template_content.index("release_group.id != 'current_release'"), 'Current release cards should render before archive release cards'

    print('✅ Latest Features tab structure is present')
    return True


def test_latest_features_optional_mirror_javascript():
    """Latest Features JavaScript must tolerate optional mirrored controls."""
    print('🔍 Testing optional Latest Features mirror JavaScript...')

    js_content = read_text(ADMIN_JS)

    required_markers = [
        'function setupLatestFeaturesMirrors() {',
        "document.getElementById('enable_thoughts')",
        "document.getElementById('latest_features_enable_thoughts')",
        'if (canonicalThoughts && mirroredThoughts) {',
        'if (canonicalEnhancedCitations && mirroredEnhancedCitations) {',
        'if (canonicalOfficeAuthType && mirroredOfficeAuthType) {',
        'if (canonicalRedisToggle && mirroredRedisToggle) {',
    ]

    missing_markers = [marker for marker in required_markers if marker not in js_content]
    if missing_markers:
        raise AssertionError(f'Missing optional mirror JavaScript guards: {missing_markers}')

    print('✅ Latest Features mirror JavaScript handles optional controls')
    return True


def test_latest_features_sync_javascript():
    """Admin settings JS must synchronize mirrored controls with canonical fields."""
    print('🔍 Testing Latest Features sync JavaScript...')

    js_content = read_text(ADMIN_JS)

    required_markers = [
        'setupAdminFormAutofillMetadata()',
        'function setupAdminFormAutofillMetadata() {',
        'setupLatestFeaturesMirrors()',
        'setupLatestFeatureImageModal()',
        'function setupLatestFeaturesMirrors()',
        'function setupLatestFeatureImageModal() {',
        'function syncMirroredField(',
        'function updateLatestFeaturesEnhancedCitationMirror()',
        'function updateLatestFeaturesRedisMirror()',
        'function updateOfficeStorageMirrorVisibility(',
        'function updateRedisCanonicalAuthVisibility(',
        'function updateRedisMirrorVisibility(',
        'latest_features_enable_thoughts',
        'latest_features_enable_enhanced_citations',
        'latest_features_enable_redis_cache',
        'latest_features_redis_auth_type',
        'data-latest-feature-image-src',
        'latestFeatureImageModal',
        "field.setAttribute('autocomplete', 'off');",
        'toggle_latest_features_office_conn_str',
        'toggle_latest_features_office_url',
        'toggle_latest_features_redis_key'
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
        'data-section="release-notifications-status-badge"',
        'support_latest_feature_release_groups_preview',
        "release_group.id == 'current_release'",
        "{% set feature_card_id = 'latest-features-' ~ feature.id|replace('_', '-') ~ '-card' %}",
        'data-section="{{ feature_card_id }}"',
        '{{ feature.title }}',
        "release_group.id != 'current_release'",
        'data-section="{{ release_card_id }}"',
        'latest-features-previous-release-card',
        "{{ release_group.label|replace(' Features', '') }}"
    ]

    missing_markers = [marker for marker in required_markers if marker not in sidebar_content]
    if missing_markers:
        raise AssertionError(f'Missing Latest Features sidebar markers: {missing_markers}')

    latest_features_index = sidebar_content.index('data-tab="latest-features"')
    general_index = sidebar_content.index('data-tab="general"')
    assert sidebar_content.index('data-section="release-notifications-status-badge"') < sidebar_content.index('data-section="{{ feature_card_id }}"'), 'Release notifications link should stay first in the Latest Features submenu'
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
    """Feature documentation and saved feature screenshots must exist."""
    print('🔍 Testing supporting assets for Latest Features...')

    assert os.path.isdir(FEATURE_IMAGE_DIR), 'Missing placeholder image directory for Latest Features'

    if os.path.exists(FEATURE_DOC):
        doc_content = read_text(FEATURE_DOC)
        assert 'Previous Release Features' in doc_content, 'Feature documentation should describe the previous release grouping'

    required_images = [
        image_name
        for image_names in CURRENT_FEATURE_IMAGE_FILES.values()
        for image_name in image_names
    ] + [
        'agent_default_model_review_action.png',
        'agent_default_model_review_summary.png',
        'agent_action_grid_view.png',
        'background_completion_notifications-01.png',
        'background_completion_notifications-02.png',
        'citation_improvements_amplified_results.png',
        'citation_improvements_history_replay.png',
        'conversation_summary_card.png',
        'document_revision_delete_compare.png',
        'document_revision_workspace.png',
        'enable_support_menu_for_end_users.png',
        'facts_citation_and_thoughts.png',
        'facts_memory_view_profile.png',
        'fact_memory_management.png',
        'guided_tutorials_chat.png',
        'guided_tutorials_workspace.png',
        'gunicorn_startup_guidance.png',
        'model_selection_multi_endpoint_admin.png',
        'pdf_export_option.png',
        'per_message_export_menu.png',
        'redis_key_vault.png',
        'sql_test_connection.png',
        'support_menu_entry.png',
        'tabular_analysis_enhanced_citations.png',
        'thoughts_visibility.png'
    ]

    missing_images = [image_name for image_name in required_images if not os.path.exists(os.path.join(FEATURE_IMAGE_DIR, image_name))]
    if missing_images:
        raise AssertionError(f'Missing Latest Features screenshot assets: {missing_images}')

    print('✅ Supporting documentation and image directory are present')
    return True


if __name__ == '__main__':
    print('🧪 Running Latest Features Admin Tab tests...\n')

    tests = [
        test_latest_features_catalog_release_groups,
        test_latest_features_template_structure,
        test_latest_features_optional_mirror_javascript,
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
