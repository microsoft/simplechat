#!/usr/bin/env python3
"""
Functional test for latest-release documentation structure.
Version: 0.260.001
Implemented in: 0.241.002; 0.241.003; 0.241.164; 0.241.165; 0.241.166; 0.241.167; 0.241.183; 0.241.184; 0.250.001; 0.250.034; 0.250.035; 0.250.036; 0.250.041; 0.250.042; 0.250.043; 0.250.044; 0.250.045; 0.250.046; 0.250.047

This test ensures the docs/latest-release landing page is driven by the latest
release YAML data, exposes current, previous, and earlier release sections, and
that every configured latest-feature guide exists as an individual markdown page.
"""

from pathlib import Path
import sys

import yaml
from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
LATEST_RELEASE_DATA = REPO_ROOT / "docs" / "_data" / "latest_release_features.yml"
LATEST_RELEASE_INDEX = REPO_ROOT / "docs" / "latest-release" / "index.md"
LATEST_RELEASE_DIR = REPO_ROOT / "docs" / "latest-release"
LATEST_RELEASE_IMAGE_DIR = REPO_ROOT / "docs" / "images" / "latest-release"
ADMIN_CONFIGURATION_DOC = REPO_ROOT / "docs" / "admin_configuration.md"
ADMIN_DOCS_DIR = REPO_ROOT / "docs" / "admin"
ADMIN_SETTINGS_IMAGE_DIR = REPO_ROOT / "docs" / "images" / "admin-settings"

CURRENT_GUIDES = {
    'release-260-enhanced-extraction.md': 'Sharper Document Extraction with Figure Descriptions',
    'release-260-office-embedded-images.md': 'Pictures Inside Word and PowerPoint Are Now Searchable',
    'release-260-workflow-task-sequences.md': 'Multi-Step Workflows With Alert Rules',
    'release-260-mcp-platform.md': 'Model Context Protocol Connections',
    'release-260-yamcs-action.md': 'Yamcs Mission Control Integration',
    'release-260-rocksdb-action.md': 'RocksDB Key-Value Store Action',
    'release-260-agent-instruction-references.md': 'Reference Actions and Knowledge Directly in Agent Instructions',
    'release-260-action-test-connection.md': 'Test Connection Before You Save an Action',
    'release-260-azure-blob-file-sync.md': 'Sync Documents From Azure Blob Storage',
    'release-260-terms-of-use.md': 'Terms of Use Acceptance',
    'release-260-audio-file-support.md': 'Upload Almost Any Audio File',
    'release-260-completion-notifications.md': 'Know When a Long Answer Finishes',
    'release-260-chat-ai-notice.md': 'AI Usage Guidance in Chat',
    'release-260-conversation-context-grounding.md': 'See Exactly What Shaped Each Answer',
    'release-260-used-documents-fork.md': 'Used Documents View and Conversation Forking',
    'release-260-conversation-contents-drawer.md': 'Jump Back to Any Earlier Prompt',
    'release-260-font-size-zoom.md': 'Choose Your Text Size',
    'release-260-message-audio-export.md': 'Download a Response as Audio',
    'release-260-public-workspace-display-name.md': 'Public Workspace Can Carry Your Own Name',
    'release-260-chat-scroll-508.md': 'Chat Stops Yanking You to the Bottom',
}

CURRENT_GUIDE_IMAGES = {
    'release-260-enhanced-extraction': ['release_260_enhanced_extraction_1.png', 'release_260_enhanced_extraction_2.png', 'release_260_enhanced_extraction_3.png'],
    'release-260-office-embedded-images': ['release_260_office_embedded_images_1.png', 'release_260_office_embedded_images_2.png', 'release_260_office_embedded_images_3.png'],
    'release-260-workflow-task-sequences': ['release_260_workflow_task_sequences_1.png', 'release_260_workflow_task_sequences_2.png', 'release_260_workflow_task_sequences_3.png'],
    'release-260-mcp-platform': ['release_260_mcp_platform_1.png', 'release_260_mcp_platform_2.png', 'release_260_mcp_platform_3.png'],
    'release-260-yamcs-action': ['release_260_yamcs_action_1.png', 'release_260_yamcs_action_2.png', 'release_260_yamcs_action_3.png'],
    'release-260-rocksdb-action': ['release_260_rocksdb_action_1.png', 'release_260_rocksdb_action_2.png', 'release_260_rocksdb_action_3.png'],
    'release-260-agent-instruction-references': ['release_260_agent_instruction_references_1.png', 'release_260_agent_instruction_references_2.png', 'release_260_agent_instruction_references_3.png'],
    'release-260-action-test-connection': ['release_260_action_test_connection_1.png', 'release_260_action_test_connection_2.png', 'release_260_action_test_connection_3.png'],
    'release-260-azure-blob-file-sync': ['release_260_azure_blob_file_sync_1.png', 'release_260_azure_blob_file_sync_2.png', 'release_260_azure_blob_file_sync_3.png'],
    'release-260-terms-of-use': ['release_260_terms_of_use_1.png', 'release_260_terms_of_use_2.png', 'release_260_terms_of_use_3.png'],
    'release-260-audio-file-support': ['release_260_audio_file_support_1.png', 'release_260_audio_file_support_2.png', 'release_260_audio_file_support_3.png'],
    'release-260-completion-notifications': ['release_260_completion_notifications_1.png', 'release_260_completion_notifications_2.png', 'release_260_completion_notifications_3.png'],
    'release-260-chat-ai-notice': ['release_260_chat_ai_notice_1.png', 'release_260_chat_ai_notice_2.png', 'release_260_chat_ai_notice_3.png'],
    'release-260-conversation-context-grounding': ['release_260_conversation_context_grounding_1.png', 'release_260_conversation_context_grounding_2.png', 'release_260_conversation_context_grounding_3.png'],
    'release-260-used-documents-fork': ['release_260_used_documents_fork_1.png', 'release_260_used_documents_fork_2.png', 'release_260_used_documents_fork_3.png'],
    'release-260-conversation-contents-drawer': ['release_260_conversation_contents_drawer_1.png', 'release_260_conversation_contents_drawer_2.png', 'release_260_conversation_contents_drawer_3.png'],
    'release-260-font-size-zoom': ['release_260_font_size_zoom_1.png', 'release_260_font_size_zoom_2.png', 'release_260_font_size_zoom_3.png'],
    'release-260-message-audio-export': ['release_260_message_audio_export_1.png', 'release_260_message_audio_export_2.png', 'release_260_message_audio_export_3.png'],
    'release-260-public-workspace-display-name': ['release_260_public_workspace_display_name_1.png', 'release_260_public_workspace_display_name_2.png', 'release_260_public_workspace_display_name_3.png'],
    'release-260-chat-scroll-508': ['release_260_chat_scroll_508_1.png', 'release_260_chat_scroll_508_2.png', 'release_260_chat_scroll_508_3.png'],
}

ADMIN_SETTINGS_IMAGES = [
    "general.png",
    "ai-models.png",
    "agents-actions.png",
    "logging.png",
    "scale.png",
    "control-center.png",
    "workspaces.png",
    "file-sync.png",
    "global-identity.png",
    "citation.png",
    "safety.png",
    "security.png",
    "search-extract.png",
    "send-feedback.png",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_latest_release_docs_structure() -> bool:
    print("Testing latest-release documentation structure...")

    config_content = read_text(CONFIG_FILE)
    index_content = read_text(LATEST_RELEASE_INDEX)
    release_data = yaml.safe_load(read_text(LATEST_RELEASE_DATA))

    assert_app_version_at_least("0.250.047")

    required_index_markers = [
        'layout: latest-release-index',
        'title: "Latest Release Highlights"',
        'SimpleChat v0.260.001',
        'v0.250.001',
        'v0.239.001',
    ]
    missing_index_markers = [marker for marker in required_index_markers if marker not in index_content]
    assert not missing_index_markers, f"Missing latest-release index markers: {missing_index_markers}"

    assert release_data["current_release"]["slugs"] == [
        'release-260-enhanced-extraction',
        'release-260-office-embedded-images',
        'release-260-workflow-task-sequences',
        'release-260-mcp-platform',
        'release-260-yamcs-action',
        'release-260-rocksdb-action',
        'release-260-agent-instruction-references',
        'release-260-action-test-connection',
        'release-260-azure-blob-file-sync',
        'release-260-terms-of-use',
        'release-260-audio-file-support',
        'release-260-completion-notifications',
        'release-260-chat-ai-notice',
        'release-260-conversation-context-grounding',
        'release-260-used-documents-fork',
        'release-260-conversation-contents-drawer',
        'release-260-font-size-zoom',
        'release-260-message-audio-export',
        'release-260-public-workspace-display-name',
        'release-260-chat-scroll-508',
    ]

    previous_groups = release_data["previous_release_groups"]
    assert previous_groups[0]["release_version"] == "0.250.001"
    assert previous_groups[1]["release_version"] == "0.239.001 - 0.241.007"
    assert "release-250-ai-access" in previous_groups[0]["slugs"]
    assert "guided-tutorials" in previous_groups[1]["slugs"]
    assert "export-conversation" in previous_groups[1]["slugs"]

    lookup = release_data["lookup"]
    missing_lookup_entries = [slug for slug in release_data["current_release"]["slugs"] if slug not in lookup]
    assert not missing_lookup_entries, f"Missing lookup entries: {missing_lookup_entries}"

    for slug in release_data["current_release"]["slugs"]:
        feature = lookup[slug]
        expected_files = CURRENT_GUIDE_IMAGES[slug]
        expected_paths = [f"/images/latest-release/{image_name}" for image_name in expected_files]
        assert feature.get("image") == expected_paths[0], f"Primary docs image mismatch: {slug}"
        assert feature.get("image_alt"), f"Missing primary docs image alt text: {slug}"
        assert [image["path"] for image in feature.get("images", [])] == expected_paths, f"Docs image gallery mismatch: {slug}"
        for image in feature["images"]:
            assert image.get("caption"), f"Missing docs image caption: {slug}"
            assert image.get("label"), f"Missing docs image label: {slug}"
            assert image.get("label") != "Feature Guide", f"Redundant docs Feature Guide image remains: {slug}"
            assert "feature_card" not in image["path"], f"Redundant docs feature-card asset remains: {slug}"
            image_path = LATEST_RELEASE_IMAGE_DIR / image["path"].replace("/images/latest-release/", "")
            assert image_path.exists(), f"Missing docs image asset: {image['path']}"

    admin_configuration_content = read_text(ADMIN_CONFIGURATION_DOC)
    admin_tab_content = "\n".join(read_text(path) for path in sorted(ADMIN_DOCS_DIR.glob("*.md")))
    admin_docs_content = f"{admin_configuration_content}\n{admin_tab_content}"
    assert "## Admin Settings Execution Guide" in admin_configuration_content, "Admin execution guide missing."
    for image_name in ADMIN_SETTINGS_IMAGES:
        image_path = ADMIN_SETTINGS_IMAGE_DIR / image_name
        image_references = [
            f"./images/admin-settings/{image_name}",
            f"admin-settings/{image_name}",
        ]
        assert image_path.exists(), f"Missing admin settings docs image: {image_name}"
        assert any(reference in admin_docs_content for reference in image_references), (
            f"Admin settings docs missing image reference: {image_name}"
        )

    for file_name, title in CURRENT_GUIDES.items():
        guide_path = LATEST_RELEASE_DIR / file_name
        assert guide_path.exists(), f"Missing latest-release guide: {file_name}"
        guide_content = read_text(guide_path)
        assert 'layout: latest-release-feature' in guide_content, f"Guide missing layout frontmatter: {file_name}"
        assert f'title: "{title}"' in guide_content, f"Guide missing title frontmatter: {file_name}"
        assert 'section: "Latest Release"' in guide_content, f"Guide missing Latest Release section marker: {file_name}"
        assert '## Why It Matters' in guide_content, f"Guide missing why section: {file_name}"
        assert '## How to Try It' in guide_content, f"Guide missing usage section: {file_name}"

    for slug, feature in lookup.items():
        guide_path = LATEST_RELEASE_DIR / f"{slug}.md"
        assert guide_path.exists(), f"Missing configured latest-release guide: {slug}.md"
        assert feature.get("title"), f"Lookup entry missing title: {slug}"
        assert feature.get("url") == f"/latest-release/{slug}/", f"Lookup entry URL mismatch: {slug}"

    print("Latest-release documentation structure test passed!")
    return True


if __name__ == "__main__":
    success = test_latest_release_docs_structure()
    sys.exit(0 if success else 1)