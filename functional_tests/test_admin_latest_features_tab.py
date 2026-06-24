#!/usr/bin/env python3
# test_admin_latest_features_tab.py
"""
Functional test for admin Latest Features tab.
Version: 0.250.036
Implemented in: 0.240.074; 0.240.085; 0.241.002; 0.241.164; 0.241.165; 0.241.166; 0.241.183; 0.241.184; 0.250.001; 0.250.026; 0.250.034; 0.250.036

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
    'release_250_ai_access',
    'release_250_agents_catalog',
    'release_250_tabular_analysis',
    'release_250_charts',
    'release_250_custom_pages',
    'release_250_tableau_action',
    'release_250_workflows',
    'release_250_voice_assisted_inputs',
    'release_250_m365_actions',
    'release_250_chat_uploads',
    'release_250_document_intelligence',
    'release_250_file_sync',
    'release_250_conversation_feed',
    'release_250_group_file_sharing',
    'release_250_profile_stats',
    'release_250_databricks_action',
    'release_250_layered_masking',
    'release_250_visio_msg_ingestion',
    'release_250_assigned_knowledge',
    'release_250_deep_research',
    'release_250_url_access',
    'release_250_source_continuity',
    'release_250_generated_documents',
    'release_250_multi_inline_image_gen',
    'release_250_workspace_views',
    'release_250_follow_up_actions',
    'release_250_model_agent_avatars',
]

ADMIN_CURRENT_FEATURE_IDS = [
    'admin_release_250_azure_openai_identity',
    'admin_release_250_model_endpoint_setup',
    'admin_release_250_governance',
    'admin_release_250_cache_performance',
    'admin_release_250_custom_pages',
    'admin_release_250_action_catalog',
    'admin_release_250_agents_catalog',
    'admin_release_250_workflows',
    'admin_release_250_document_intelligence',
    'admin_release_250_cosmos_scaling',
    'admin_release_250_file_sync',
    'admin_release_250_group_sharing',
    'admin_release_250_global_identities',
    'admin_release_250_deep_research',
    'admin_release_250_url_access',
    'admin_release_250_model_endpoint_branding',
    'admin_release_250_bug_fixes',
]

USER_CURRENT_FEATURE_IMAGE_FILES = {
    'release_250_ai_access': ['release_250_ai_access.png'],
    'release_250_agents_catalog': ['release_250_agents_catalog.png'],
    'release_250_tabular_analysis': ['release_250_tabular_analysis.png'],
    'release_250_charts': ['release_250_charts.png'],
    'release_250_custom_pages': ['release_250_custom_pages.png'],
    'release_250_tableau_action': ['release_250_tableau_action.png'],
    'release_250_workflows': ['release_250_workflows.png'],
    'release_250_voice_assisted_inputs': ['release_250_voice_assisted_inputs.png'],
    'release_250_m365_actions': ['release_250_m365_actions.png'],
    'release_250_chat_uploads': ['release_250_chat_uploads.png'],
    'release_250_document_intelligence': ['release_250_document_intelligence.png'],
    'release_250_file_sync': ['release_250_file_sync.png'],
    'release_250_conversation_feed': ['release_250_conversation_feed.png'],
    'release_250_group_file_sharing': ['release_250_group_file_sharing.png'],
    'release_250_profile_stats': ['release_250_profile_stats.png'],
    'release_250_databricks_action': ['release_250_databricks_action.png'],
    'release_250_layered_masking': ['release_250_layered_masking.png'],
    'release_250_visio_msg_ingestion': ['release_250_visio_msg_ingestion.png'],
    'release_250_assigned_knowledge': ['release_250_assigned_knowledge.png'],
    'release_250_deep_research': ['release_250_deep_research.png'],
    'release_250_url_access': ['release_250_url_access.png'],
    'release_250_source_continuity': ['release_250_source_continuity.png'],
    'release_250_generated_documents': ['release_250_generated_documents.png'],
    'release_250_multi_inline_image_gen': ['release_250_multi_inline_image_gen.png'],
    'release_250_workspace_views': ['release_250_workspace_views.png'],
    'release_250_follow_up_actions': ['release_250_follow_up_actions.png'],
    'release_250_model_agent_avatars': ['release_250_model_agent_avatars.png'],
}

ADMIN_CURRENT_FEATURE_IMAGE_FILES = {
    'admin_release_250_agents_catalog': ['admin_release_250_agents_catalog.png'],
    'admin_release_250_deep_research': ['admin_release_250_deep_research.png'],
    'admin_release_250_url_access': ['admin_release_250_url_access.png'],
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
        'archive_release',
    ]
    assert release_groups[0]['release_version'] == '0.250.001'
    assert release_groups[1]['release_version'] == '0.241.001 - 0.241.007'

    current_feature_ids = [feature['id'] for feature in release_groups[0]['features']]
    assert current_feature_ids == USER_CURRENT_FEATURE_IDS
    assert 'cosmos_autoscale' not in current_feature_ids

    default_visibility = support_config.get_default_support_latest_features_visibility()
    assert 'cosmos_autoscale' not in default_visibility
    assert default_visibility['deployment'] is False
    assert default_visibility['redis_key_vault'] is False
    assert default_visibility['release_250_ai_access'] is True

    first_feature = release_groups[0]['features'][0]
    assert first_feature['id'] == 'release_250_ai_access'
    assert first_feature['title'] == 'Personalized Model and Agent Access'

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
    assert release_groups[0]['release_version'] == '0.250.001'
    assert release_groups[1]['release_version'] == '0.241.001 - 0.241.007'

    current_feature_ids = [feature['id'] for feature in release_groups[0]['features']]
    assert current_feature_ids == ADMIN_CURRENT_FEATURE_IDS

    previous_feature_ids = [
        feature['id']
        for group in release_groups[1:]
        for feature in group['features']
    ]
    for feature_id in PREVIOUS_ADMIN_FEATURE_IDS:
        assert feature_id in previous_feature_ids, f'Missing previous admin feature: {feature_id}'

    for feature in release_groups[0]['features']:
        guidance = ' '.join(feature.get('guidance', []))
        if feature.get('images'):
            assert 'Screenshot idea:' in guidance, f"Missing screenshot guidance for {feature['id']}"
        else:
            assert not feature.get('image'), f"No-media admin feature should not define a primary image: {feature['id']}"
        assert feature.get('actions'), f"Missing action link for {feature['id']}"
        assert len(feature.get('actions', [])) >= 2, f"Expected multiple admin action links for {feature['id']}"
        assert any(action.get('admin_tab') for action in feature.get('actions', [])), f"Expected an admin tab link for {feature['id']}"
        if feature['id'] in ADMIN_CURRENT_FEATURE_IMAGE_FILES:
            expected_files = ADMIN_CURRENT_FEATURE_IMAGE_FILES[feature['id']]
            expected_paths = [f'images/features/{image_name}' for image_name in expected_files]
            images = feature.get('images', [])
            assert feature.get('image') == expected_paths[0], f"Primary admin image mismatch for {feature['id']}"
            assert [image['path'] for image in images] == expected_paths, f"Admin gallery image paths mismatch for {feature['id']}"

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
        '{% else %}',
        "{% set feature_card_id = 'latest-features-' ~ feature.id|replace('_', '-') ~ '-card' %}",
        '<i class="bi {{ feature.icon }} me-2"></i>{{ feature.title }}',
        '{{ feature.summary }}',
        'Screenshot and rollout notes',
        'data-open-admin-tab="{{ action.admin_tab }}"',
        'data-open-admin-section="{{ action.admin_section }}"',
        'latest-features-previous-release-card',
        '{% set release_collapse_id = release_group.collapse_id %}',
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
    """Current release screenshots referenced by the catalogs must exist."""
    print('Testing supporting assets for Latest Features...')

    assert os.path.isdir(FEATURE_IMAGE_DIR), 'Missing image directory for Latest Features'

    current_placeholder_images = [
        image_name
        for image_names in USER_CURRENT_FEATURE_IMAGE_FILES.values()
        for image_name in image_names
    ]
    current_admin_images = [
        image_name
        for image_names in ADMIN_CURRENT_FEATURE_IMAGE_FILES.values()
        for image_name in image_names
    ]
    assert all(image_name.startswith('release_250_') for image_name in current_placeholder_images), 'Current screenshots should be 0.250.001 placeholder filenames'
    assert 'admin_release_250_deep_research_url_access.png' not in current_admin_images, 'Deep Research and URL Access must use separate admin screenshot assets'

    required_images = [
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

    required_images.extend(current_admin_images)

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
