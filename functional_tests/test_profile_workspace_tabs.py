# test_profile_workspace_tabs.py
#!/usr/bin/env python3
"""
Functional test for profile workspace tabs.
Version: 0.241.031
Implemented in: 0.241.028

This test ensures that My Groups and My Public Workspaces are exposed as
Profile tabs with list/card views, menu deep links, legacy redirects, and
versioned documentation.
"""

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
CURRENT_VERSION = "0.241.031"
IMPLEMENTED_VERSION = "0.241.028"


def read_text(path):
    """Read a repository text file using UTF-8."""
    return path.read_text(encoding="utf-8")


def require_token(file_text, token, file_path):
    """Assert a token exists in a file, with a useful message."""
    assert token in file_text, f"Expected {token!r} in {file_path}"


def get_config_version():
    """Read the current application version from config.py."""
    config_text = read_text(APP_ROOT / "config.py")
    match = re.search(r'VERSION = "([^"]+)"', config_text)
    if not match:
        raise AssertionError("Could not find VERSION in application/single_app/config.py")
    return match.group(1)


def test_profile_workspace_tabs_static_contract():
    """Validate the static contract for profile workspace tabs."""
    assert get_config_version() == CURRENT_VERSION, f"Expected config VERSION {CURRENT_VERSION}"

    profile_route_text = read_text(APP_ROOT / "route_frontend_profile.py")
    for token in [
        "valid_tabs.add('groups')",
        "valid_tabs.add('public-workspaces')",
        "can_create_groups=can_create_groups",
        "can_create_public_workspaces=can_create_public_workspaces",
        "require_member_of_create_group",
        "require_member_of_create_public_workspace",
    ]:
        require_token(profile_route_text, token, "application/single_app/route_frontend_profile.py")

    groups_route_text = read_text(APP_ROOT / "route_frontend_groups.py")
    require_token(groups_route_text, "return redirect(url_for('profile', tab='groups'))", "application/single_app/route_frontend_groups.py")

    public_route_text = read_text(APP_ROOT / "route_frontend_public_workspaces.py")
    require_token(
        public_route_text,
        "return redirect(url_for('profile', tab='public-workspaces'))",
        "application/single_app/route_frontend_public_workspaces.py",
    )

    profile_template_text = read_text(APP_ROOT / "templates" / "profile.html")
    for token in [
        "id=\"profile-groups-tab\"",
        "id=\"profile-public-workspaces-tab\"",
        "id=\"profile-groups-pane\"",
        "id=\"profile-public-workspaces-pane\"",
        "id=\"profile-groups-view-list\"",
        "id=\"profile-groups-view-cards\"",
        "id=\"profile-public-workspaces-view-list\"",
        "id=\"profile-public-workspaces-view-cards\"",
        "id=\"profileCreateGroupModal\"",
        "id=\"profileFindGroupModal\"",
        "id=\"profileCreatePublicWorkspaceModal\"",
        "id=\"profileFindPublicWorkspaceModal\"",
        "groupWorkspacesEnabled",
        "publicWorkspacesEnabled",
        "profile_can_create_groups_from_settings",
        "profile_can_create_public_workspaces_from_settings",
        "{% set profile_can_create_groups = (can_create_groups | default(false)) or profile_can_create_groups_from_settings %}",
        "{% set profile_can_create_public_workspaces = (can_create_public_workspaces | default(false)) or profile_can_create_public_workspaces_from_settings %}",
        "{% if profile_can_create_groups %}",
        "{% if profile_can_create_public_workspaces %}",
        "canCreateGroups: {{ profile_can_create_groups | tojson }}",
        "canCreatePublicWorkspaces: {{ profile_can_create_public_workspaces | tojson }}",
        ".profile-workspace-card-clickable:hover",
    ]:
        require_token(profile_template_text, token, "application/single_app/templates/profile.html")

    profile_js_text = read_text(APP_ROOT / "static" / "js" / "profile" / "profile-tabs.js")
    for token in [
        "/api/groups",
        "/api/groups/discover",
        "/api/groups/setActive",
        "/api/public_workspaces",
        "/api/public_workspaces/discover",
        "/api/public_workspaces/setActive",
        "loadWorkspaceCollection(workspaceTabConfigs.groups)",
        "loadWorkspaceCollection(workspaceTabConfigs.publicWorkspaces)",
        "setWorkspaceViewMode(config, 'cards')",
        "requestWorkspaceAccess(config",
        "activateRequestedProfileTab()",
        "card.dataset.manageUrl = config.managePath(workspaceId)",
        "window.location.assign(card.dataset.manageUrl)",
    ]:
        require_token(profile_js_text, token, "application/single_app/static/js/profile/profile-tabs.js")

    for template_name in ["_top_nav.html", "_sidebar_nav.html", "_sidebar_short_nav.html"]:
        template_text = read_text(APP_ROOT / "templates" / template_name)
        require_token(template_text, "url_for('profile', tab='groups')", f"application/single_app/templates/{template_name}")
        require_token(template_text, "url_for('profile', tab='public-workspaces')", f"application/single_app/templates/{template_name}")
        require_token(template_text, "url_for('profile', tab='feedback')", f"application/single_app/templates/{template_name}")
        require_token(template_text, "url_for('profile', tab='violations')", f"application/single_app/templates/{template_name}")

    redirect_targets = {
        "application/single_app/templates/group_workspaces.html": "url_for('profile', tab='groups')",
        "application/single_app/static/js/group/manage_group.js": "/profile?tab=groups",
        "application/single_app/static/js/public/public_workspace.js": "/profile?tab=public-workspaces",
        "application/single_app/static/js/public/manage_public_workspace.js": "/profile?tab=public-workspaces",
    }
    for relative_path, token in redirect_targets.items():
        require_token(read_text(REPO_ROOT / relative_path), token, relative_path)

    docs_text = read_text(REPO_ROOT / "docs" / "explanation" / "features" / f"v{IMPLEMENTED_VERSION}" / "PROFILE_WORKSPACE_TABS.md")
    require_token(docs_text, f"Implemented in version: **{IMPLEMENTED_VERSION}**", "docs/explanation/features/v0.241.028/PROFILE_WORKSPACE_TABS.md")
    require_token(docs_text, f"Fixed/Implemented in version: **{IMPLEMENTED_VERSION}**", "docs/explanation/features/v0.241.028/PROFILE_WORKSPACE_TABS.md")

    print("Profile workspace tabs static contract validated.")
    return True


if __name__ == "__main__":
    try:
        test_profile_workspace_tabs_static_contract()
        sys.exit(0)
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
