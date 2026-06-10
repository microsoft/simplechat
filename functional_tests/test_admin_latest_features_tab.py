#!/usr/bin/env python3
# test_admin_latest_features_tab.py
"""
Functional test for admin Latest Features tab.
Version: 0.241.184
Implemented in: 0.240.074; 0.240.085; 0.241.002; 0.241.164; 0.241.165; 0.241.166; 0.241.183; 0.241.184

This test ensures that the Admin Settings page exposes a data-driven,
admin-only Latest Features tab while the user-facing support catalog remains
focused on features users can see and control.
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
FEATURE_IMAGE_DIR = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'images', 'features')

USER_CURRENT_FEATURE_IDS = [
    'document_intelligence',
    'cloud_anthropic_models',
    'file_sync',
    'group_workflows',
    'source_review',
    'analyze_compare',
    'agent_knowledge_actions',
    'generated_artifacts',
    'chat_productivity',
    'chat_upload_workspace_parity',
    'workspace_experience',
    'workflow_automation',
    'visio_ingestion',
    'stats_reporting',
]

ADMIN_CURRENT_FEATURE_IDS = [
    'admin_cloud_anthropic_models',
    'admin_document_action_capabilities',
    'admin_cosmos_throughput',
    'admin_workspace_workflows',
    'admin_chat_file_uploads',
    'admin_file_sync',
    'admin_global_identities',
    'admin_url_access_deep_research',
    'admin_document_intelligence_modes',
]

USER_CURRENT_FEATURE_IMAGE_FILES = {
    'document_intelligence': ['document_intelligence_admin_controls.png'],
    'cloud_anthropic_models': ['model_selection_multi_endpoint_admin.png'],
    'file_sync': ['file_sync_admin_scope_controls.png'],
    'group_workflows': ['workflow_automation_admin_controls.png'],
    'source_review': ['source_review_admin_policy.png'],
    'analyze_compare': ['document_revision_delete_compare.png'],
    'agent_knowledge_actions': ['agent_knowledge_actions_assigned_knowledge.png'],
    'generated_artifacts': ['generated_artifacts_chat_artifacts.png'],
    'chat_productivity': ['chat_productivity_chat_toolbar.png'],
    'chat_upload_workspace_parity': ['chat_productivity_chat_toolbar.png'],
    'workspace_experience': ['workspace_experience_document_cards.png'],
    'workflow_automation': ['workflow_automation_admin_controls.png'],
    'visio_ingestion': ['visio_ingestion_workspace_upload.png'],
    'stats_reporting': ['stats_reporting_profile_dashboard.png'],
}

PREVIOUS_ADMIN_FEATURE_IDS = [
    'release_notifications_status_badge',
    'guided_tutorials',
    'background_chat',
    'gpt_selection',
    'tabular_analysis',
    'citation_improvements',
    'document_versioning',
    'summaries_export',
    'agent_operations',
    'ai_transparency',
    'fact_memory',
    'deployment',
    'redis_key_vault',
    'send_feedback',
    'support_menu',
]


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def load_module(path, module_name):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_user_latest_features_catalog_release_groups():
    """User-facing Latest Features catalog must exclude admin-only Cosmos throughput."""
    print('Testing user-facing Latest Features catalog release groups...')

    support_config = load_module(SUPPORT_CONFIG, 'support_menu_config_for_user_latest_features_test')
    release_groups = support_config.get_support_latest_feature_release_groups()

    assert [group['id'] for group in release_groups] == [
        'current_release',
        'previous_release',
        'earlier_release',
    ]

    current_feature_ids = [feature['id'] for feature in release_groups[0]['features']]
    assert current_feature_ids == USER_CURRENT_FEATURE_IDS
    assert 'cosmos_autoscale' not in current_feature_ids

    default_visibility = support_config.get_default_support_latest_features_visibility()
    assert 'cosmos_autoscale' not in default_visibility
    assert default_visibility['deployment'] is False
    assert default_visibility['redis_key_vault'] is False
    assert default_visibility['document_intelligence'] is True

    stats_feature = next(feature for feature in release_groups[0]['features'] if feature['id'] == 'stats_reporting')
    assert stats_feature['title'] == 'Profile, Stats, and Preferences'
    stats_copy = ' '.join([stats_feature['summary']] + stats_feature.get('guidance', []))
    assert 'text-to-speech voice selection' in stats_copy
    assert 'feedback' in stats_copy
    assert 'safety violations' in stats_copy

    for feature in release_groups[0]['features']:
        expected_files = USER_CURRENT_FEATURE_IMAGE_FILES[feature['id']]
        expected_paths = [f'images/features/{image_name}' for image_name in expected_files]
        images = feature.get('images', [])
        assert feature.get('image') == expected_paths[0], f"Primary image mismatch for {feature['id']}"
        assert feature.get('image_alt'), f"Missing primary image alt text for {feature['id']}"
        assert [image['path'] for image in images] == expected_paths, f"Gallery image paths mismatch for {feature['id']}"

    print('User-facing Latest Features catalog release groups are current')
    return True


def test_admin_latest_features_catalog_release_groups():
    """Admin Latest Features catalog must expose admin-only current cards and previous archive."""
    print('Testing admin Latest Features catalog release groups...')

    support_config = load_module(SUPPORT_CONFIG, 'support_menu_config_for_admin_latest_features_test')
    release_groups = support_config.get_admin_latest_feature_release_groups_for_settings({})

    assert [group['id'] for group in release_groups] == ['current_release', 'previous_release']
    assert release_groups[0]['label'] == 'Admin-Managed Latest Features'
    assert release_groups[1]['label'] == 'Previous Release Features'

    current_feature_ids = [feature['id'] for feature in release_groups[0]['features']]
    assert current_feature_ids == ADMIN_CURRENT_FEATURE_IDS

    previous_feature_ids = [feature['id'] for feature in release_groups[1]['features']]
    for feature_id in PREVIOUS_ADMIN_FEATURE_IDS:
        assert feature_id in previous_feature_ids, f'Missing previous admin feature: {feature_id}'

    for feature in release_groups[0]['features']:
        guidance = ' '.join(feature.get('guidance', []))
        assert 'Screenshot idea:' in guidance, f"Missing screenshot guidance for {feature['id']}"
        assert feature.get('actions'), f"Missing action link for {feature['id']}"

    print('Admin Latest Features catalog release groups are current')
    return True


def test_latest_features_template_structure():
    """Admin Settings template must expose data-driven admin cards and archive cards."""
    print('Testing Latest Features tab structure in admin_settings.html...')

    template_content = read_text(ADMIN_TEMPLATE)

    required_markers = [
        'id="latest-features-tab"',
        'data-bs-target="#latest-features"',
        'id="latest-features"',
        'admin_latest_feature_release_groups',
        '{% for release_group in admin_latest_feature_release_groups %}',
        "release_group.id == 'current_release'",
        "release_group.id == 'previous_release'",
        "{% set feature_card_id = 'latest-features-' ~ feature.id|replace('_', '-') ~ '-card' %}",
        '<i class="bi {{ feature.icon }} me-2"></i>{{ feature.title }}',
        '{{ feature.summary }}',
        'Screenshot and rollout notes',
        'data-open-admin-tab="{{ action.admin_tab }}"',
        'data-open-admin-section="{{ action.admin_section }}"',
        'latest-features-previous-release-card',
        'latestFeaturesPreviousRelease',
        'id="latestFeatureImageModal"',
        'class="latest-feature-image-frame"',
        'data-latest-feature-image-src="{{ url_for(\'static\', filename=image.path) }}"',
        '{{ image.label }}',
        '{% if false %}',
        'User-Facing Latest Features',
    ]

    missing_markers = [marker for marker in required_markers if marker not in template_content]
    if missing_markers:
        raise AssertionError(f'Missing Latest Features template markers: {missing_markers}')

    assert template_content.count('id="latest-features" role="tabpanel"') == 1, 'Latest Features tab pane should appear exactly once'
    assert template_content.index('admin_latest_feature_release_groups') < template_content.index('{% if false %}'), 'Admin catalog cards should render before hidden legacy markup'

    print('Latest Features tab structure is present')
    return True


def test_latest_features_javascript_support():
    """Admin settings JS must support image modals, optional mirrors, and admin action links."""
    print('Testing Latest Features JavaScript support...')

    js_content = read_text(ADMIN_JS)

    required_markers = [
        'setupLatestFeaturesMirrors()',
        'setupLatestFeatureImageModal()',
        'function setupLatestFeaturesMirrors()',
        'function setupLatestFeatureImageModal() {',
        'function syncMirroredField(',
        'data-latest-feature-image-src',
        'latestFeatureImageModal',
        "function openAdminSettingsTab(targetHash, sectionId = '')",
        "trigger.getAttribute('data-open-admin-section')",
        "document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' });",
        'if (canonicalThoughts && mirroredThoughts) {',
        'if (canonicalEnhancedCitations && mirroredEnhancedCitations) {',
        'if (canonicalRedisToggle && mirroredRedisToggle) {',
    ]

    missing_markers = [marker for marker in required_markers if marker not in js_content]
    if missing_markers:
        raise AssertionError(f'Missing Latest Features JavaScript markers: {missing_markers}')

    print('Latest Features JavaScript support is present')
    return True


def test_latest_features_sidebar_navigation():
    """Admin sidebar must use the admin latest-feature release groups."""
    print('Testing Latest Features sidebar navigation...')

    sidebar_content = read_text(SIDEBAR_TEMPLATE)

    required_markers = [
        'data-tab="latest-features"',
        'id="latest-features-submenu"',
        'admin_latest_feature_release_groups',
        "release_group.id == 'current_release'",
        "{% set feature_card_id = 'latest-features-' ~ feature.id|replace('_', '-') ~ '-card' %}",
        'data-section="{{ feature_card_id }}"',
        '{{ feature.title }}',
        "release_group.id != 'current_release'",
        'data-section="{{ release_card_id }}"',
        'latest-features-previous-release-card',
        "{{ release_group.label|replace(' Features', '') }}",
    ]

    missing_markers = [marker for marker in required_markers if marker not in sidebar_content]
    if missing_markers:
        raise AssertionError(f'Missing Latest Features sidebar markers: {missing_markers}')

    latest_features_index = sidebar_content.index('data-tab="latest-features"')
    general_index = sidebar_content.index('data-tab="general"')
    assert latest_features_index < general_index, 'Latest Features should appear before General in the admin sidebar'
    assert '<span class="badge bg-warning text-dark text-uppercase ms-2">New</span>' in sidebar_content, 'Sidebar Latest Features item should include a New badge'

    print('Latest Features sidebar navigation is present')
    return True


def test_latest_features_top_nav_priority():
    """Latest Features should be the first top-nav tab and default active pane."""
    print('Testing Latest Features top-nav priority...')

    template_content = read_text(ADMIN_TEMPLATE)

    latest_features_tab_index = template_content.index('id="latest-features-tab"')
    general_tab_index = template_content.index('id="general-tab"')
    assert latest_features_tab_index < general_tab_index, 'Latest Features tab should appear before General in top nav'

    assert 'id="latest-features-tab" data-bs-toggle="tab" data-bs-target="#latest-features"' in template_content, 'Latest Features top-nav tab missing'
    assert 'Latest Features <span class="badge bg-warning text-dark text-uppercase ms-2 latest-feature-nav-badge">New</span>' in template_content, 'Latest Features top-nav tab should include a New badge'
    assert 'class="tab-pane fade show active" id="latest-features" role="tabpanel" aria-labelledby="latest-features-tab"' in template_content, 'Latest Features pane should be the default active tab'

    print('Latest Features is prioritized in top navigation')
    return True


def test_admin_settings_tab_uniqueness():
    """Admin settings template should not contain duplicate Security tab controls or extra active panes."""
    print('Testing admin settings tab uniqueness...')

    template_content = read_text(ADMIN_TEMPLATE)
    normalized_template = ''.join(template_content.split())

    assert template_content.count('id="security-tab"') == 1, 'Security tab button should appear exactly once'
    assert template_content.count('id="security" role="tabpanel"') == 1, 'Security tab pane should appear exactly once'
    assert template_content.count('tab-pane fade show active') == 1, 'Only one tab pane should be marked show active in top-nav markup'
    assert 'Managesecuritysettingsforkeyvaultandothersecurityconfigurations.</p>' in normalized_template, 'Security intro paragraph should be properly closed'

    print('Admin settings tab structure is unique and well-formed')
    return True


def test_latest_features_supporting_assets():
    """User-facing current release screenshots referenced by the catalog must exist."""
    print('Testing supporting assets for Latest Features...')

    assert os.path.isdir(FEATURE_IMAGE_DIR), 'Missing image directory for Latest Features'

    required_images = [
        image_name
        for image_names in USER_CURRENT_FEATURE_IMAGE_FILES.values()
        for image_name in image_names
    ] + [
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
        'thoughts_visibility.png',
    ]

    missing_images = [
        image_name
        for image_name in sorted(set(required_images))
        if not os.path.exists(os.path.join(FEATURE_IMAGE_DIR, image_name))
    ]
    if missing_images:
        raise AssertionError(f'Missing Latest Features screenshot assets: {missing_images}')

    print('Supporting image assets are present')
    return True


if __name__ == '__main__':
    print('Running Latest Features Admin Tab tests...\n')

    tests = [
        test_user_latest_features_catalog_release_groups,
        test_admin_latest_features_catalog_release_groups,
        test_latest_features_template_structure,
        test_latest_features_javascript_support,
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
            print(f'Failed {test.__name__}: {exc}')
            import traceback
            traceback.print_exc()
            results.append(False)
        print()

    passed = sum(1 for result in results if result)
    print(f'Results: {passed}/{len(results)} tests passed')
    sys.exit(0 if all(results) else 1)
