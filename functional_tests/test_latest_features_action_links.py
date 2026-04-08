#!/usr/bin/env python3
# test_latest_features_action_links.py
"""
Functional test for latest-features action links.
Version: 0.241.003
Implemented in: 0.241.003

This test ensures the latest-features configuration exposes direct in-app
action links, the admin-controlled documentation toggle, and the launch-intent
handlers that open the requested Chat, Workspace, and Profile workflows.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
FUNCTIONS_SETTINGS_FILE = REPO_ROOT / "application" / "single_app" / "functions_settings.py"
SUPPORT_MENU_CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "support_menu_config.py"
ADMIN_ROUTE_FILE = REPO_ROOT / "application" / "single_app" / "route_frontend_admin_settings.py"
ADMIN_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
CHAT_ONLOAD_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-onload.js"
CHAT_DOCUMENTS_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-documents.js"
WORKSPACE_INIT_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-init.js"
WORKSPACE_TAGS_FILE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace-tags.js"
PROFILE_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "profile.html"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def assert_markers(file_path: Path, markers: list[str]) -> None:
    content = read_text(file_path)
    missing = [marker for marker in markers if marker not in content]
    assert not missing, f"Missing markers in {file_path.name}: {missing}"


def test_latest_features_action_links() -> bool:
    print("Testing latest-features action links and launch intents...")

    assert 'VERSION = "0.241.003"' in read_text(CONFIG_FILE), "Config version marker is not current."

    assert_markers(
        FUNCTIONS_SETTINGS_FILE,
        [
            "'enable_support_latest_feature_documentation_links': False",
        ],
    )

    assert_markers(
        SUPPORT_MENU_CONFIG_FILE,
        [
            "_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY = 'enable_support_latest_feature_documentation_links'",
            "'/chats?feature_action=conversation_export'",
            "'/profile?feature_action=retention_policy#retention-policy-settings'",
            "'/workspace?feature_action=document_tag_system'",
            "'/workspace?feature_action=workspace_folder_view'",
            "'/chats?feature_action=multi_workspace_scope_management'",
            "'/chats?feature_action=chat_document_and_tag_filtering'",
            "'requires_settings': [_SUPPORT_LATEST_FEATURE_DOCS_SETTING_KEY]",
            "def get_support_latest_feature_release_groups_for_settings(settings):",
        ],
    )

    assert_markers(
        ADMIN_ROUTE_FILE,
        [
            "if 'enable_support_latest_feature_documentation_links' not in settings:",
            "enable_support_latest_feature_documentation_links = (",
            "support_latest_feature_release_groups_preview=get_support_latest_feature_release_groups_for_settings(settings)",
            "'enable_support_latest_feature_documentation_links': enable_support_latest_feature_documentation_links",
        ],
    )

    assert_markers(
        ADMIN_TEMPLATE_FILE,
        [
            'id="enable_support_latest_feature_documentation_links"',
            'Show Simple Chat Documentation Guide Links',
            'support_latest_feature_release_groups_preview',
        ],
    )

    assert_markers(
        CHAT_DOCUMENTS_FILE,
        [
            'export async function ensureSearchDocumentsVisible()',
            'export function openScopeDropdown()',
            'export function openTagsDropdown()',
        ],
    )

    assert_markers(
        CHAT_ONLOAD_FILE,
        [
            'function clearFeatureActionParam()',
            'async function handleLatestFeatureLaunch(featureAction)',
            "case 'conversation_export':",
            "case 'multi_workspace_scope_management':",
            "case 'chat_document_and_tag_filtering':",
            "const featureAction = getUrlParameter('feature_action') || ''",
        ],
    )

    assert_markers(
        WORKSPACE_TAGS_FILE,
        [
            'export function setWorkspaceView(view)',
        ],
    )

    assert_markers(
        WORKSPACE_INIT_FILE,
        [
            'function handleWorkspaceFeatureAction()',
            "featureAction === 'document_tag_system'",
            "featureAction === 'workspace_folder_view'",
            "showTagManagementModal();",
            "setWorkspaceView('grid');",
        ],
    )

    assert_markers(
        PROFILE_TEMPLATE_FILE,
        [
            'id="retention-policy-settings"',
            'function handleProfileFeatureAction()',
            "featureAction !== 'retention_policy'",
        ],
    )

    print("Latest-features action link test passed!")
    return True


if __name__ == "__main__":
    success = test_latest_features_action_links()
    sys.exit(0 if success else 1)