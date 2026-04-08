#!/usr/bin/env python3
# test_user_tutorial_visibility_preference.py
"""
Functional test for user tutorial visibility preference.
Version: 0.241.003
Implemented in: 0.240.068; 0.241.002; 0.241.003

This test ensures that guided tutorial launchers remain visible by default,
users can manage the preference from the profile page, and the Latest Features
experience points users back to profile settings when they want to hide or
restore tutorial buttons.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "config.py"
SETTINGS_FILE = REPO_ROOT / "application" / "single_app" / "functions_settings.py"
USERS_ROUTE_FILE = REPO_ROOT / "application" / "single_app" / "route_backend_users.py"
SUPPORT_CONFIG_FILE = REPO_ROOT / "application" / "single_app" / "support_menu_config.py"
PROFILE_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "profile.html"
CHAT_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
WORKSPACE_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "workspace.html"
LATEST_FEATURES_TEMPLATE_FILE = REPO_ROOT / "application" / "single_app" / "templates" / "latest_features.html"
FEATURE_DOC_FILE = REPO_ROOT / "docs" / "explanation" / "features" / "v0.241.001" / "USER_TUTORIAL_VISIBILITY_PREFERENCE.md"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_user_tutorial_visibility_preference() -> bool:
    """Validate persistence, profile UI, and launcher gating for tutorial visibility."""
    print("Testing user tutorial visibility preference...")

    config_content = read_text(CONFIG_FILE)
    settings_content = read_text(SETTINGS_FILE)
    users_route_content = read_text(USERS_ROUTE_FILE)
    support_config_content = read_text(SUPPORT_CONFIG_FILE)
    profile_content = read_text(PROFILE_TEMPLATE_FILE)
    chat_content = read_text(CHAT_TEMPLATE_FILE)
    workspace_content = read_text(WORKSPACE_TEMPLATE_FILE)
    latest_features_content = read_text(LATEST_FEATURES_TEMPLATE_FILE)

    required_config_markers = [
        'VERSION = "0.241.003"',
    ]
    missing_config = [marker for marker in required_config_markers if marker not in config_content]
    assert not missing_config, f"Missing config markers: {missing_config}"

    required_settings_markers = [
        "doc['settings']['showTutorialButtons'] = True",
        'if \'showTutorialButtons\' not in doc[\'settings\']:',
    ]
    missing_settings = [marker for marker in required_settings_markers if marker not in settings_content]
    assert not missing_settings, f"Missing settings markers: {missing_settings}"

    required_users_route_markers = [
        "'showTutorialButtons',",
    ]
    missing_users_route = [marker for marker in required_users_route_markers if marker not in users_route_content]
    assert not missing_users_route, f"Missing user settings allow-list markers: {missing_users_route}"

    required_profile_markers = [
        'id="tutorial-preferences"',
        'id="show-tutorial-buttons-toggle"',
        'id="save-tutorial-preferences-btn"',
        'onclick="saveTutorialPreferences()"',
        "function loadTutorialPreferences()",
        "function saveTutorialPreferences()",
        "showTutorialButtons: toggle.checked",
        "These launchers are shown by default.",
    ]
    missing_profile = [marker for marker in required_profile_markers if marker not in profile_content]
    assert not missing_profile, f"Missing profile preference markers: {missing_profile}"

    required_template_guards = [
        "{% if user_settings.get('settings', {}).get('showTutorialButtons', True) %}",
        'id="chat-tutorial-launch"',
        'id="workspace-tutorial-launch"',
    ]
    if required_template_guards[0] not in chat_content:
        raise AssertionError('Chat tutorial launcher is not guarded by the user tutorial visibility preference.')
    if required_template_guards[0] not in workspace_content:
        raise AssertionError('Workspace tutorial launcher is not guarded by the user tutorial visibility preference.')

    required_support_markers = [
        "'label': 'Manage Tutorial Visibility'",
        "'endpoint': 'profile'",
        "'fragment': 'tutorial-preferences'",
        "'description': 'Open your profile page to show or hide the tutorial launch buttons for your account.'",
    ]
    missing_support = [marker for marker in required_support_markers if marker not in support_config_content]
    assert not missing_support, f"Missing support catalog markers: {missing_support}"

    required_latest_features_markers = [
        "Guided tutorial buttons are shown by default.",
        "profile shortcut above",
    ]
    missing_latest_features = [marker for marker in required_latest_features_markers if marker not in latest_features_content]
    assert not missing_latest_features, f"Missing latest-features guidance markers: {missing_latest_features}"

    assert FEATURE_DOC_FILE.exists(), "Missing feature documentation for user tutorial visibility preference"

    print("User tutorial visibility preference test passed!")
    return True


if __name__ == "__main__":
    success = test_user_tutorial_visibility_preference()
    sys.exit(0 if success else 1)