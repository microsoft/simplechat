#!/usr/bin/env python3
"""
Functional test for latest-release documentation structure.
Version: 0.241.184
Implemented in: 0.241.002; 0.241.003; 0.241.164; 0.241.165; 0.241.166; 0.241.167; 0.241.183; 0.241.184

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
    "document-intelligence.md": "Document Intelligence Auto Mode",
    "cloud-anthropic-models.md": "Cloud and Anthropic Model Support",
    "file-sync.md": "File Sync Connectors",
    "group-workflows.md": "Group Workflow Support",
    "source-review.md": "Source Review and Deep Research",
    "analyze-compare.md": "Analyze and Compare",
    "agent-knowledge-actions.md": "Agent Knowledge and Actions",
    "generated-artifacts.md": "Generated Artifacts",
    "chat-productivity.md": "Chat Productivity",
    "chat-upload-workspace-parity.md": "Chat Upload Workspace Parity",
    "workspace-experience.md": "Workspace Experience",
    "workflow-automation.md": "Workflow Automation",
    "visio-ingestion.md": "Visio Ingestion and Previews",
    "stats-reporting.md": "Profile, Stats, and Preferences",
}

CURRENT_GUIDE_IMAGES = {
    "document-intelligence": ["document_intelligence_admin_controls.png", "document_intelligence_user_details.png"],
    "cloud-anthropic-models": ["model_selection_multi_endpoint_admin.png", "model_selection_chat_selector.png"],
    "file-sync": ["file_sync_admin_scope_controls.png", "file_sync_user_sources.png", "file_sync_user_identities.png"],
    "group-workflows": ["workflow_automation_admin_controls.png", "workflow_automation_user_list.png"],
    "source-review": ["source_review_admin_policy.png", "source_review_user_grounded_search.png", "source_review_user_deep_research.png"],
    "analyze-compare": ["document_revision_delete_compare.png", "chat_productivity_user_chat.png"],
    "agent-knowledge-actions": ["agent_knowledge_actions_assigned_knowledge.png", "agent_knowledge_user_agents.png", "agent_knowledge_user_actions.png"],
    "generated-artifacts": ["generated_artifacts_chat_artifacts.png", "generated_artifacts_user_chat_output.png"],
    "chat-productivity": ["chat_productivity_chat_toolbar.png", "chat_productivity_user_chat.png"],
    "chat-upload-workspace-parity": ["chat_productivity_chat_toolbar.png", "chat_productivity_user_chat.png", "workspace_experience_document_cards.png"],
    "workspace-experience": ["workspace_experience_document_cards.png", "workspace_experience_user_list_view.png", "workspace_experience_user_cards_view.png", "workspace_experience_user_folders_view.png", "workspace_experience_user_folders_cards_view.png"],
    "workflow-automation": ["workflow_automation_admin_controls.png", "workflow_automation_user_list.png", "workflow_automation_user_file_sync_trigger.png"],
    "visio-ingestion": ["visio_ingestion_workspace_upload.png", "visio_ingestion_user_upload.png"],
    "stats-reporting": ["stats_reporting_user_profile.png", "facts_memory_view_profile.png", "stats_reporting_profile_dashboard.png"],
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

    assert 'VERSION = "0.241.184"' in config_content, "Config version marker is not current."

    required_index_markers = [
        'layout: latest-release-index',
        'title: "Latest Release Highlights"',
        'since v0.241.008',
        'v0.241.001-v0.241.008',
        'v0.239.001',
    ]
    missing_index_markers = [marker for marker in required_index_markers if marker not in index_content]
    assert not missing_index_markers, f"Missing latest-release index markers: {missing_index_markers}"

    assert release_data["current_release"]["slugs"] == [
        "document-intelligence",
        "cloud-anthropic-models",
        "file-sync",
        "group-workflows",
        "source-review",
        "analyze-compare",
        "agent-knowledge-actions",
        "generated-artifacts",
        "chat-productivity",
        "chat-upload-workspace-parity",
        "workspace-experience",
        "workflow-automation",
        "visio-ingestion",
        "stats-reporting",
    ]

    previous_groups = release_data["previous_release_groups"]
    assert previous_groups[0]["release_version"] == "0.241.001 - 0.241.008"
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