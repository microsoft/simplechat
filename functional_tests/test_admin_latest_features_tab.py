#!/usr/bin/env python3
# test_admin_latest_features_tab.py
"""
Functional test for admin Latest Features tab.
Version: 0.260.001
Implemented in: 0.240.074; 0.240.085; 0.241.002; 0.241.164; 0.241.165; 0.241.166; 0.241.183; 0.241.184; 0.250.001; 0.250.026; 0.250.034; 0.250.036; 0.260.001

This test ensures that the Admin Settings page exposes a data-driven,
admin-only Latest Features tab while the user-facing support catalog remains
focused on features users can see and control.
"""

import re
import importlib.util
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.templates import resolve_template_includes
from test_support.nav import get_group_for_tab, get_tab_ids


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, '..'))

ADMIN_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', 'admin_settings.html')
SIDEBAR_TEMPLATE = os.path.join(REPO_ROOT, 'application', 'single_app', 'templates', '_sidebar_nav.html')
ADMIN_JS = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'js', 'admin', 'admin_settings.js')
SUPPORT_CONFIG = os.path.join(REPO_ROOT, 'application', 'single_app', 'support_menu_config.py')
FEATURE_IMAGE_DIR = os.path.join(REPO_ROOT, 'application', 'single_app', 'static', 'images', 'features')

USER_CURRENT_FEATURE_IDS = [
    'release_260_enhanced_extraction',
    'release_260_office_embedded_images',
    'release_260_workflow_task_sequences',
    'release_260_mcp_platform',
    'release_260_yamcs_action',
    'release_260_rocksdb_action',
    'release_260_agent_instruction_references',
    'release_260_action_test_connection',
    'release_260_azure_blob_file_sync',
    'release_260_terms_of_use',
    'release_260_audio_file_support',
    'release_260_completion_notifications',
    'release_260_chat_ai_notice',
    'release_260_conversation_context_grounding',
    'release_260_used_documents_fork',
    'release_260_conversation_contents_drawer',
    'release_260_font_size_zoom',
    'release_260_message_audio_export',
    'release_260_public_workspace_display_name',
    'release_260_chat_scroll_508',
]

ADMIN_CURRENT_FEATURE_IDS = [
    'admin_release_260_data_management',
    'admin_release_260_keyvault_reminders',
    'admin_release_260_governance_block_lists',
    'admin_release_260_model_identity_header',
    'admin_release_260_per_model_response_length',
    'admin_release_260_control_center_refresh',
    'admin_release_260_feedback_safety_lifecycle',
    'admin_release_260_log_cleanup',
    'admin_release_260_redis_explorer',
    'admin_release_260_index_auto_login',
    'admin_release_260_enhanced_extraction',
    'admin_release_260_mcp_platform',
    'admin_release_260_azure_blob_file_sync',
    'admin_release_260_terms_of_use',
    'admin_release_260_chat_ai_notice',
    'admin_release_260_public_workspace_display_name',
]

USER_CURRENT_FEATURE_IMAGE_FILES = {
    'release_260_enhanced_extraction': ['release_260_enhanced_extraction_1.png', 'release_260_enhanced_extraction_2.png', 'release_260_enhanced_extraction_3.png'],
    'release_260_office_embedded_images': ['release_260_office_embedded_images_1.png', 'release_260_office_embedded_images_2.png', 'release_260_office_embedded_images_3.png'],
    'release_260_workflow_task_sequences': ['release_260_workflow_task_sequences_1.png', 'release_260_workflow_task_sequences_2.png', 'release_260_workflow_task_sequences_3.png'],
    'release_260_mcp_platform': ['release_260_mcp_platform_1.png', 'release_260_mcp_platform_2.png', 'release_260_mcp_platform_3.png'],
    'release_260_yamcs_action': ['release_260_yamcs_action_1.png', 'release_260_yamcs_action_2.png', 'release_260_yamcs_action_3.png'],
    'release_260_rocksdb_action': ['release_260_rocksdb_action_1.png', 'release_260_rocksdb_action_2.png', 'release_260_rocksdb_action_3.png'],
    'release_260_agent_instruction_references': ['release_260_agent_instruction_references_1.png', 'release_260_agent_instruction_references_2.png', 'release_260_agent_instruction_references_3.png'],
    'release_260_action_test_connection': ['release_260_action_test_connection_1.png', 'release_260_action_test_connection_2.png', 'release_260_action_test_connection_3.png'],
    'release_260_azure_blob_file_sync': ['release_260_azure_blob_file_sync_1.png', 'release_260_azure_blob_file_sync_2.png', 'release_260_azure_blob_file_sync_3.png'],
    'release_260_terms_of_use': ['release_260_terms_of_use_1.png', 'release_260_terms_of_use_2.png', 'release_260_terms_of_use_3.png'],
    'release_260_audio_file_support': ['release_260_audio_file_support_1.png', 'release_260_audio_file_support_2.png', 'release_260_audio_file_support_3.png'],
    'release_260_completion_notifications': ['release_260_completion_notifications_1.png', 'release_260_completion_notifications_2.png', 'release_260_completion_notifications_3.png'],
    'release_260_chat_ai_notice': ['release_260_chat_ai_notice_1.png', 'release_260_chat_ai_notice_2.png', 'release_260_chat_ai_notice_3.png'],
    'release_260_conversation_context_grounding': ['release_260_conversation_context_grounding_1.png', 'release_260_conversation_context_grounding_2.png', 'release_260_conversation_context_grounding_3.png'],
    'release_260_used_documents_fork': ['release_260_used_documents_fork_1.png', 'release_260_used_documents_fork_2.png', 'release_260_used_documents_fork_3.png'],
    'release_260_conversation_contents_drawer': ['release_260_conversation_contents_drawer_1.png', 'release_260_conversation_contents_drawer_2.png', 'release_260_conversation_contents_drawer_3.png'],
    'release_260_font_size_zoom': ['release_260_font_size_zoom_1.png', 'release_260_font_size_zoom_2.png', 'release_260_font_size_zoom_3.png'],
    'release_260_message_audio_export': ['release_260_message_audio_export_1.png', 'release_260_message_audio_export_2.png', 'release_260_message_audio_export_3.png'],
    'release_260_public_workspace_display_name': ['release_260_public_workspace_display_name_1.png', 'release_260_public_workspace_display_name_2.png', 'release_260_public_workspace_display_name_3.png'],
    'release_260_chat_scroll_508': ['release_260_chat_scroll_508_1.png', 'release_260_chat_scroll_508_2.png', 'release_260_chat_scroll_508_3.png'],
}

ADMIN_CURRENT_FEATURE_IMAGE_FILES = {
    'admin_release_260_data_management': ['admin_release_260_data_management.png'],
    'admin_release_260_keyvault_reminders': ['admin_release_260_keyvault_reminders.png'],
    'admin_release_260_governance_block_lists': ['admin_release_260_governance_block_lists.png'],
    'admin_release_260_model_identity_header': ['admin_release_260_model_identity_header.png'],
    'admin_release_260_per_model_response_length': ['admin_release_260_per_model_response_length.png'],
    'admin_release_260_control_center_refresh': ['admin_release_260_control_center_refresh.png'],
    'admin_release_260_feedback_safety_lifecycle': ['admin_release_260_feedback_safety_lifecycle.png'],
    'admin_release_260_log_cleanup': ['admin_release_260_log_cleanup.png'],
    'admin_release_260_redis_explorer': ['admin_release_260_redis_explorer.png'],
    'admin_release_260_index_auto_login': ['admin_release_260_index_auto_login.png'],
    'admin_release_260_enhanced_extraction': ['admin_release_260_enhanced_extraction.png'],
    'admin_release_260_mcp_platform': ['admin_release_260_mcp_platform.png'],
    'admin_release_260_azure_blob_file_sync': ['admin_release_260_azure_blob_file_sync.png'],
    'admin_release_260_terms_of_use': ['admin_release_260_terms_of_use.png'],
    'admin_release_260_chat_ai_notice': ['admin_release_260_chat_ai_notice.png'],
    'admin_release_260_public_workspace_display_name': ['admin_release_260_public_workspace_display_name.png'],
}

PREVIOUS_ADMIN_FEATURE_IDS = [
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


def read_text(path):
    with open(path, 'r', encoding='utf-8') as file_handle:
        content = file_handle.read()

    # Admin Settings is composed from per-tab partials, so structural
    # assertions have to see the fully composed markup.
    if os.path.basename(str(path)) == 'admin_settings.html':
        return resolve_template_includes(content, os.path.dirname(str(path)))
    return content


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
    assert release_groups[0]['release_version'] == '0.260.001'
    assert release_groups[1]['release_version'] == '0.250.001'
    assert release_groups[2]['release_version'] == '0.239.001 - 0.241.007'

    current_feature_ids = [feature['id'] for feature in release_groups[0]['features']]
    assert current_feature_ids == USER_CURRENT_FEATURE_IDS
    assert 'cosmos_autoscale' not in current_feature_ids

    previous_feature_ids = [feature['id'] for feature in release_groups[1]['features']]
    assert 'release_250_ai_access' in previous_feature_ids, 'v0.250.001 cards should move to the previous tier'

    default_visibility = support_config.get_default_support_latest_features_visibility()
    assert 'cosmos_autoscale' not in default_visibility
    assert default_visibility['deployment'] is False
    assert default_visibility['redis_key_vault'] is False
    assert default_visibility['release_250_ai_access'] is True
    assert all(default_visibility[feature_id] is False for feature_id in USER_CURRENT_FEATURE_IDS), 'v0.260.001 cards ship hidden until their placeholder screenshots are replaced'

    first_feature = release_groups[0]['features'][0]
    assert first_feature['id'] == 'release_260_enhanced_extraction'
    assert first_feature['title'] == 'Sharper Document Extraction with Figure Descriptions'

    for feature in release_groups[0]['features']:
        expected_files = USER_CURRENT_FEATURE_IMAGE_FILES[feature['id']]
        expected_paths = [f'images/features/{image_name}' for image_name in expected_files]
        images = feature.get('images', [])
        assert feature.get('image') == expected_paths[0], f"Primary image mismatch for {feature['id']}"
        assert feature.get('image_alt'), f"Missing primary image alt text for {feature['id']}"
        assert [image['path'] for image in images] == expected_paths, f"Gallery image paths mismatch for {feature['id']}"
        assert len(images) == 3, f"Expected three gallery images for {feature['id']}"
        assert len(feature.get('guidance', [])) >= 5, f"Expected at least five how-to steps for {feature['id']}"

    print('User-facing Latest Features catalog release groups are current')
    return True


def test_admin_latest_features_catalog_release_groups():
    """Admin Latest Features catalog must expose admin-only current cards and previous archive."""
    print('Testing admin Latest Features catalog release groups...')

    support_config = load_module(SUPPORT_CONFIG, 'support_menu_config_for_admin_latest_features_test')
    release_groups = support_config.get_admin_latest_feature_release_groups_for_settings({})

    assert [group['id'] for group in release_groups] == ['current_release', 'previous_release', 'archive_release']
    assert release_groups[0]['label'] == 'Admin-Managed Latest Features'
    assert release_groups[1]['label'] == 'Previous Release Features'
    assert release_groups[2]['label'] == 'Archive Release Features'
    assert release_groups[0]['release_version'] == '0.260.001'
    assert release_groups[1]['release_version'] == '0.250.001'
    assert release_groups[2]['release_version'] == '0.241.001 - 0.241.007'

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
        assert feature.get('guidance'), f"Missing admin guidance for {feature['id']}"
        assert len(feature.get('guidance', [])) >= 4, f"Expected at least four admin steps for {feature['id']}"
        assert feature.get('actions'), f"Missing action link for {feature['id']}"
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
        "{% set preview_card_id = 'latest-features-user-preview-' ~ release_group.id|replace('_', '-') ~ '-card' %}",
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
        "{{ release_group.label|replace(' Features', '') }}",
    ]

    missing_markers = [marker for marker in required_markers if marker not in sidebar_content]
    if missing_markers:
        raise AssertionError(f'Missing Latest Features sidebar markers: {missing_markers}')

    latest_features_index = sidebar_content.index('data-tab="latest-features"')
    assert '<span class="badge bg-warning text-dark text-uppercase ms-2">New</span>' in sidebar_content, 'Sidebar Latest Features item should include a New badge'

    # Tab order is defined once in the nav map, which the sidebar renders from,
    # so ordering is asserted there rather than against the rendered markup.
    tab_ids = get_tab_ids()
    assert tab_ids.index('latest-features') > tab_ids.index('general'), 'Latest Features should appear after General'
    assert tab_ids.index('latest-features') > tab_ids.index('send-feedback'), 'Latest Features should be the last destination, after Send Feedback'

    print('Latest Features sidebar navigation is present')
    return True


def test_latest_features_top_nav_priority():
    """Latest Features should be the last tab and never default active."""
    print('Testing Latest Features navigation placement...')

    template_content = read_text(ADMIN_TEMPLATE)
    tab_ids = get_tab_ids()

    # Navigation order now comes from the nav map, which both the top tab strip
    # and the sidebar render from, so order is asserted there rather than
    # against either rendering.
    assert tab_ids[-1] == 'latest-features', (
        'Latest Features should be the last tab in the navigation map, '
        f'got {tab_ids[-1]}'
    )
    assert tab_ids.index('latest-features') > tab_ids.index('send-feedback'), (
        'Latest Features should come after Send Feedback'
    )

    group = get_group_for_tab('latest-features')
    assert group is not None and group['id'] == 'help', (
        f"Latest Features should sit in the Help group, got {group}"
    )

    # Latest Features opened on every visit to Admin Settings, which is why it
    # is pinned last and General is the landing tab instead.
    assert 'class="tab-pane fade" id="latest-features" role="tabpanel" aria-labelledby="latest-features-tab"' in template_content, 'Latest Features pane should not be the default active tab'
    assert 'class="tab-pane fade show active" id="general" role="tabpanel" aria-labelledby="general-tab"' in template_content, 'General pane should be the default active tab'
    assert tab_ids[0] == 'general', 'General should be the first tab in the navigation map'

    print('Latest Features is last in navigation and not default active')
    return True


def test_admin_settings_tab_uniqueness():
    """Every tab must appear exactly once, with exactly one default pane."""
    print('Testing admin settings tab uniqueness...')

    template_content = read_text(ADMIN_TEMPLATE)
    normalized_template = ''.join(template_content.split())
    tab_ids = get_tab_ids()

    duplicates = sorted({t for t in tab_ids if tab_ids.count(t) > 1})
    assert not duplicates, f'Tabs listed more than once in the nav map: {duplicates}'

    assert template_content.count('id="security" role="tabpanel"') == 1, 'Security tab pane should appear exactly once'
    assert template_content.count('tab-pane fade show active') == 1, 'Only one tab pane should be marked show active'
    assert 'Managesecuritysettingsforkeyvaultandothersecurityconfigurations.</p>' in normalized_template, 'Security intro paragraph should be properly closed'

    # Every tab in the map must have a pane to activate.
    panes = set(re.findall(r'<div class="tab-pane[^"]*" id="([^"]+)"', template_content))
    missing = sorted(set(tab_ids) - panes)
    assert not missing, f'Nav map lists tabs with no matching pane: {missing}'

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
    assert all(image_name.startswith('release_260_') for image_name in current_placeholder_images), 'Current screenshots should be 0.260.001 placeholder filenames'
    assert all(image_name.startswith('admin_release_260_') for image_name in current_admin_images), 'Current admin screenshots should be 0.260.001 placeholder filenames'
    assert 'admin_release_250_deep_research_url_access.png' not in current_admin_images, 'Deep Research and URL Access must use separate admin screenshot assets'

    for image_name in current_placeholder_images + current_admin_images:
        assert os.path.isfile(os.path.join(FEATURE_IMAGE_DIR, image_name)), f'Missing current release screenshot asset: {image_name}'

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
