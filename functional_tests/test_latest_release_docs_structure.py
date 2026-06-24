#!/usr/bin/env python3
"""
Functional test for latest-release documentation structure.
Version: 0.250.034
Implemented in: 0.241.002; 0.241.003; 0.241.164; 0.241.165; 0.241.166; 0.241.167; 0.241.183; 0.241.184; 0.250.001; 0.250.034

This test ensures the docs/latest-release landing page is driven by the latest
release YAML data, exposes current, previous, and earlier release sections, and
that every configured latest-feature guide exists as an individual markdown page.
"""

from pathlib import Path
import sys

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
LATEST_RELEASE_DATA = REPO_ROOT / "docs" / "_data" / "latest_release_features.yml"
LATEST_RELEASE_INDEX = REPO_ROOT / "docs" / "latest-release" / "index.md"
LATEST_RELEASE_DIR = REPO_ROOT / "docs" / "latest-release"
LATEST_RELEASE_IMAGE_DIR = REPO_ROOT / "docs" / "images" / "latest-release"
ADMIN_CONFIGURATION_DOC = REPO_ROOT / "docs" / "admin_configuration.md"
ADMIN_SETTINGS_IMAGE_DIR = REPO_ROOT / "docs" / "images" / "admin-settings"

CURRENT_GUIDES = {
    'release-250-ai-access.md': 'Personalized Model and Agent Access',
    'release-250-tabular-analysis.md': 'Improved Tabular Analysis',
    'release-250-custom-pages.md': 'Custom Pages',
    'release-250-tableau-action.md': 'Tableau Action',
    'release-250-workflows.md': 'Personal and Group Workflows',
    'release-250-voice-assisted-inputs.md': 'Voice-Assisted Form Inputs',
    'release-250-m365-actions.md': 'Microsoft 365 Actions',
    'release-250-chat-uploads.md': 'Workspace-Backed Chat Uploads and Paste Support',
    'release-250-document-intelligence.md': 'Enhanced Document Intelligence',
    'release-250-file-sync.md': 'File Sync for SMB and Azure Files',
    'release-250-conversation-feed.md': 'Faster Conversation Lists',
    'release-250-group-file-sharing.md': 'Group File Sharing and Approvals',
    'release-250-profile-stats.md': 'Profile, Stats, and Preferences',
    'release-250-databricks-action.md': 'Databricks Action',
    'release-250-layered-masking.md': 'Layered Message Masking',
    'release-250-visio-msg-ingestion.md': 'Visio and Outlook MSG File Support',
    'release-250-assigned-knowledge.md': 'Assigned Knowledge for Agents',
    'release-250-deep-research.md': 'Deep Research and Source Review',
    'release-250-url-access.md': 'URL Access in Chat',
    'release-250-source-continuity.md': 'Conversation Source Continuity',
    'release-250-generated-documents.md': 'Generated Markdown, Word, and PowerPoint Files',
    'release-250-multi-inline-image-gen.md': 'Multi Inline Image Generation',
    'release-250-workspace-views.md': 'Workspace Cards and Folder Views',
    'release-250-follow-up-actions.md': 'Assistant Follow-Up Actions',
    'release-250-model-agent-avatars.md': 'Model and Agent Avatars',
}

CURRENT_GUIDE_IMAGES = {
    'release-250-ai-access': ['release_250_ai_access.png'],
    'release-250-tabular-analysis': ['release_250_tabular_analysis.png'],
    'release-250-custom-pages': ['release_250_custom_pages.png'],
    'release-250-tableau-action': ['release_250_tableau_action.png'],
    'release-250-workflows': ['release_250_workflows.png'],
    'release-250-voice-assisted-inputs': ['release_250_voice_assisted_inputs.png'],
    'release-250-m365-actions': ['release_250_m365_actions.png'],
    'release-250-chat-uploads': ['release_250_chat_uploads.png'],
    'release-250-document-intelligence': ['release_250_document_intelligence.png'],
    'release-250-file-sync': ['release_250_file_sync.png'],
    'release-250-conversation-feed': ['release_250_conversation_feed.png'],
    'release-250-group-file-sharing': ['release_250_group_file_sharing.png'],
    'release-250-profile-stats': ['release_250_profile_stats.png'],
    'release-250-databricks-action': ['release_250_databricks_action.png'],
    'release-250-layered-masking': ['release_250_layered_masking.png'],
    'release-250-visio-msg-ingestion': ['release_250_visio_msg_ingestion.png'],
    'release-250-assigned-knowledge': ['release_250_assigned_knowledge.png'],
    'release-250-deep-research': ['release_250_deep_research.png'],
    'release-250-url-access': ['release_250_url_access.png'],
    'release-250-source-continuity': ['release_250_source_continuity.png'],
    'release-250-generated-documents': ['release_250_generated_documents.png'],
    'release-250-multi-inline-image-gen': ['release_250_multi_inline_image_gen.png'],
    'release-250-workspace-views': ['release_250_workspace_views.png'],
    'release-250-follow-up-actions': ['release_250_follow_up_actions.png'],
    'release-250-model-agent-avatars': ['release_250_model_agent_avatars.png'],
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

    assert 'VERSION = "0.250.034"' in config_content, "Config version marker is not current."

    required_index_markers = [
        'layout: latest-release-index',
        'title: "Latest Release Highlights"',
        'SimpleChat v0.250.001',
        'v0.241.001-v0.241.007',
        'v0.239.001',
    ]
    missing_index_markers = [marker for marker in required_index_markers if marker not in index_content]
    assert not missing_index_markers, f"Missing latest-release index markers: {missing_index_markers}"

    assert release_data["current_release"]["slugs"] == [
        'release-250-ai-access',
        'release-250-tabular-analysis',
        'release-250-custom-pages',
        'release-250-tableau-action',
        'release-250-workflows',
        'release-250-voice-assisted-inputs',
        'release-250-m365-actions',
        'release-250-chat-uploads',
        'release-250-document-intelligence',
        'release-250-file-sync',
        'release-250-conversation-feed',
        'release-250-group-file-sharing',
        'release-250-profile-stats',
        'release-250-databricks-action',
        'release-250-layered-masking',
        'release-250-visio-msg-ingestion',
        'release-250-assigned-knowledge',
        'release-250-deep-research',
        'release-250-url-access',
        'release-250-source-continuity',
        'release-250-generated-documents',
        'release-250-multi-inline-image-gen',
        'release-250-workspace-views',
        'release-250-follow-up-actions',
        'release-250-model-agent-avatars',
    ]

    previous_groups = release_data["previous_release_groups"]
    assert previous_groups[0]["release_version"] == "0.241.001 - 0.241.007"
    assert previous_groups[1]["release_version"] == "0.239.001"
    assert "guided-tutorials" in previous_groups[0]["slugs"]
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
            if not image_path.name.startswith("release_250_"):
                assert image_path.exists(), f"Missing docs image asset: {image['path']}"

    admin_configuration_content = read_text(ADMIN_CONFIGURATION_DOC)
    assert "## Admin Settings Execution Guide" in admin_configuration_content, "Admin execution guide missing."
    for image_name in ADMIN_SETTINGS_IMAGES:
        image_path = ADMIN_SETTINGS_IMAGE_DIR / image_name
        image_reference = f"./images/admin-settings/{image_name}"
        assert image_path.exists(), f"Missing admin settings docs image: {image_name}"
        assert image_reference in admin_configuration_content, f"Admin settings doc missing image reference: {image_name}"

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