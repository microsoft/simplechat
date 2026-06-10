#!/usr/bin/env python3
# test_admin_app_role_settings_consistency.py
"""
Functional test for Admin Settings app-role copy and deployer role definitions.
Version: 0.241.180
Implemented in: 0.241.110
Updated in: 0.241.180

This test ensures admin-facing app-role settings use consistent role-value-first
labels and that the Azure CLI app registration role manifest contains every
active app role surfaced by those settings.
"""

import json
import os
import re
import sys
import traceback


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
ADMIN_TEMPLATE_FILE = os.path.join(APP_ROOT, "templates", "admin_settings.html")
CONFIG_FILE = os.path.join(APP_ROOT, "config.py")
APP_ROLES_FILE = os.path.join(REPO_ROOT, "deployers", "azurecli", "appRegistrationRoles.json")
CURRENT_VERSION = "0.241.180"

REQUIRED_ADMIN_ROLE_SNIPPETS = [
    "Require ControlCenterAdmin App Role",
    "Required app role value: <code>ControlCenterAdmin</code>.",
    "Allow ControlCenterDashboardReader App Role",
    "Dashboard-only app role value: <code>ControlCenterDashboardReader</code>.",
    "Require PersonalFileSyncUser App Role",
    "Required app role value: <code>PersonalFileSyncUser</code>.",
    "Require WorkflowUser App Role",
    "Required app role value: <code>WorkflowUser</code>.",
    "Require CreateGroups App Role",
    "Required app role value: <code>CreateGroups</code>.",
    "Require CreatePublicWorkspaces App Role",
    "Required app role value: <code>CreatePublicWorkspaces</code>.",
    "Require ChatFileUploadUser App Role",
    "Required app role value: <code>ChatFileUploadUser</code>.",
    "Require SafetyViolationAdmin App Role",
    "Required app role value: <code>SafetyViolationAdmin</code>.",
    "Require FeedbackAdmin App Role",
    "Required app role value: <code>FeedbackAdmin</code>.",
    "Require UrlAccessUser App Role",
    "Required app role value: <code>UrlAccessUser</code>.",
    "Require DeepResearchUser App Role",
    "Required app role value: <code>DeepResearchUser</code>.",
]

DISALLOWED_ADMIN_COPY_SNIPPETS = [
    "Require Membership to Create Groups",
    "Require Membership to Create Public Workspaces",
    "Require Membership for Safety Violation Admin View",
    "Require Membership for Feedback Admin View",
    "members of the 'CreateGroups' role",
    "members of the 'CreatePublicWorkspaces' role",
    "members of the 'SafetyViolationAdmin' role",
    "members of the 'FeedbackAdmin' role",
    "Require GroupFileSyncUser App Role",
    "Required app role value: <code>GroupFileSyncUser</code>.",
    "Require PublicWorkspaceFileSyncUser App Role",
    "Required app role value: <code>PublicWorkspaceFileSyncUser</code>.",
]

REQUIRED_APP_ROLE_VALUES = {
    "Admin",
    "User",
    "FeedbackAdmin",
    "SafetyViolationAdmin",
    "ExternalApi",
    "ControlCenterAdmin",
    "ControlCenterDashboardReader",
    "CreateGroups",
    "CreatePublicWorkspaces",
    "WorkflowUser",
    "ChatFileUploadUser",
    "UrlAccessUser",
    "DeepResearchUser",
    "PersonalFileSyncUser",
}

LEGACY_APP_ROLE_VALUES = {
    "GroupFileSyncUser",
    "PublicWorkspaceFileSyncUser",
}


def read_file(path):
    """Read a UTF-8 text file from the repo."""
    with open(path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def read_current_version():
    """Read the current SimpleChat application version from config.py."""
    config_source = read_file(CONFIG_FILE)
    version_match = re.search(r'VERSION = "([0-9.]+)"', config_source)
    if not version_match:
        raise AssertionError("VERSION assignment not found in config.py")
    return version_match.group(1)


def test_admin_settings_app_role_copy():
    """Verify Admin Settings uses consistent app-role wording."""
    print("Testing Admin Settings app-role copy...")

    template_source = read_file(ADMIN_TEMPLATE_FILE)

    missing = [snippet for snippet in REQUIRED_ADMIN_ROLE_SNIPPETS if snippet not in template_source]
    stale = [snippet for snippet in DISALLOWED_ADMIN_COPY_SNIPPETS if snippet in template_source]

    assert not missing, f"Missing admin app-role copy snippets: {missing}"
    assert not stale, f"Stale admin role membership copy remains: {stale}"

    print("Admin Settings app-role copy passed")


def test_azurecli_app_role_manifest_contains_settings_roles():
    """Verify the Azure CLI app-registration manifest includes every settings role."""
    print("Testing Azure CLI app-role manifest...")

    roles = json.loads(read_file(APP_ROLES_FILE))
    values = {role.get("value") for role in roles}
    ids = [role.get("id") for role in roles]

    missing_values = sorted(REQUIRED_APP_ROLE_VALUES - values)
    duplicate_ids = sorted({role_id for role_id in ids if ids.count(role_id) > 1})

    assert not missing_values, f"Missing app role values: {missing_values}"
    assert not duplicate_ids, f"Duplicate app role ids: {duplicate_ids}"

    for legacy_value in LEGACY_APP_ROLE_VALUES:
        assert legacy_value in values, f"Legacy app role value should remain deployer-compatible: {legacy_value}"

    print("Azure CLI app-role manifest passed")


def test_versions_are_updated():
    """Verify app and deployer versions were bumped for this change."""
    print("Testing version updates...")

    current_version = read_current_version()

    assert current_version == CURRENT_VERSION, f"Expected config VERSION {CURRENT_VERSION}, found {current_version}"

    print("Version updates passed")


if __name__ == "__main__":
    tests = [
        test_admin_settings_app_role_copy,
        test_azurecli_app_role_manifest_contains_settings_roles,
        test_versions_are_updated,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as ex:
            print(f"Test failed: {ex}")
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)