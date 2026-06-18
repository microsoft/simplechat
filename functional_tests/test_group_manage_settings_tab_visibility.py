# test_group_manage_settings_tab_visibility.py
"""
Functional test for group manage settings tab visibility.
Version: 0.242.071
Implemented in: 0.241.204

This test ensures the group manage Settings pane is unhidden for group owners
and admins, and that group/public download settings PATCH responses match the
frontend success contract. Updated in 0.242.057 to ensure local file download
disable settings are hidden unless administrators enable downloads for the
specific group or public workspace.
"""

import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
CURRENT_VERSION = "0.242.071"
FIX_DOC = REPO_ROOT / "docs" / "explanation" / "fixes" / "GROUP_PUBLIC_WORKSPACE_DOWNLOAD_SETTINGS_VISIBILITY_FIX.md"


def read_text(path: Path) -> str:
    """Read a repository file using UTF-8."""
    return path.read_text(encoding="utf-8")


def read_config_version() -> str:
    """Read the current application version from config.py."""
    config_text = read_text(APP_ROOT / "config.py")
    match = re.search(r'VERSION = "([^"]+)"', config_text)
    if not match:
        raise AssertionError("Could not find VERSION in application/single_app/config.py")
    return match.group(1)


def require_token(source: str, token: str, label: str) -> None:
    """Assert that a token exists in a source string."""
    assert token in source, f"Expected {token!r} in {label}"


def require_ordered_tokens(source: str, tokens: list[str], label: str) -> None:
    """Assert that tokens appear in source in order."""
    previous_index = -1
    for token in tokens:
        current_index = source.find(token, previous_index + 1)
        assert current_index != -1, f"Expected {token!r} in {label}"
        assert current_index > previous_index, f"Expected {token!r} after prior token in {label}"
        previous_index = current_index


def test_group_manage_settings_pane_unhides_for_admin_roles() -> None:
    """Verify the group manage Settings tab button and pane are both unhidden."""
    manage_group_script = read_text(APP_ROOT / "static" / "js" / "group" / "manage_group.js")
    manage_group_template = read_text(APP_ROOT / "templates" / "manage_group.html")

    require_token(
        manage_group_template,
        '<div class="tab-pane fade d-none" id="settings" role="tabpanel">',
        "application/single_app/templates/manage_group.html",
    )
    require_ordered_tokens(
        manage_group_script,
        [
            'if (currentUserRole === "Admin" || currentUserRole === "Owner") {',
            '$("#settings-tab-item").removeClass("d-none");',
            '$("#settings").removeClass("d-none");',
            'loadGroupDownloadSettings(group);',
            'loadGroupRetentionSettings();',
            '} else {',
            '$("#settings-tab-item").addClass("d-none");',
            '$("#settings").addClass("d-none");',
        ],
        "application/single_app/static/js/group/manage_group.js",
    )


def test_download_settings_patch_responses_match_frontend_contract() -> None:
    """Verify download settings PATCH APIs return success only when admin-enabled."""
    group_routes = read_text(APP_ROOT / "route_backend_groups.py")
    public_routes = read_text(APP_ROOT / "route_backend_public_workspaces.py")
    group_script = read_text(APP_ROOT / "static" / "js" / "group" / "manage_group.js")
    public_script = read_text(APP_ROOT / "static" / "js" / "public" / "manage_public_workspace.js")

    for source, label in [
        (group_script, "application/single_app/static/js/group/manage_group.js"),
        (public_script, "application/single_app/static/js/public/manage_public_workspace.js"),
    ]:
        require_token(source, "if (response.ok && data.success) {", label)

    require_ordered_tokens(
        group_routes,
        [
            '@app.route("/api/groups/<group_id>/download-settings", methods=["PATCH"])',
            'assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin"))',
            'if not is_group_workspace_file_download_admin_enabled(get_settings(), group_doc):',
            '"success": True,',
            '"disable_file_downloads": group_doc["disable_file_downloads"],',
        ],
        "application/single_app/route_backend_groups.py",
    )
    require_ordered_tokens(
        public_routes,
        [
            '@app.route("/api/public_workspaces/<ws_id>/download-settings", methods=["PATCH"])',
            'if not is_public_workspace_file_download_admin_enabled(get_settings(), ws):',
            '"success": True,',
            '"disable_file_downloads": ws["disable_file_downloads"],',
        ],
        "application/single_app/route_backend_public_workspaces.py",
    )


def test_download_settings_visibility_is_admin_gated() -> None:
    """Verify local disable controls stay hidden until admin downloads apply."""
    settings_helpers = read_text(APP_ROOT / "functions_settings.py")
    group_routes = read_text(APP_ROOT / "route_backend_groups.py")
    public_routes = read_text(APP_ROOT / "route_backend_public_workspaces.py")
    group_template = read_text(APP_ROOT / "templates" / "manage_group.html")
    public_template = read_text(APP_ROOT / "templates" / "manage_public_workspace.html")
    group_script = read_text(APP_ROOT / "static" / "js" / "group" / "manage_group.js")
    public_script = read_text(APP_ROOT / "static" / "js" / "public" / "manage_public_workspace.js")

    for token in [
        "def is_group_workspace_file_download_admin_enabled(settings, group_doc_or_id):",
        "def is_public_workspace_file_download_admin_enabled(settings, workspace_doc_or_id):",
        "if source_settings.get('require_group_assignment_for_file_downloads', False):",
        "if source_settings.get('require_public_workspace_assignment_for_file_downloads', False):",
    ]:
        require_token(settings_helpers, token, "application/single_app/functions_settings.py")

    require_token(
        group_routes,
        'response_doc["file_downloads_admin_enabled"] = is_group_workspace_file_download_admin_enabled(',
        "application/single_app/route_backend_groups.py",
    )
    require_token(
        public_routes,
        'payload["file_downloads_admin_enabled"] = is_public_workspace_file_download_admin_enabled(',
        "application/single_app/route_backend_public_workspaces.py",
    )
    require_token(
        group_template,
        '<div class="section-card d-none" id="group-file-download-settings-section">',
        "application/single_app/templates/manage_group.html",
    )
    require_token(
        public_template,
        '<div class="section-card d-none" id="public-file-download-settings-section">',
        "application/single_app/templates/manage_public_workspace.html",
    )
    require_ordered_tokens(
        group_script,
        [
            "function setGroupDownloadSettingsVisibility(isAvailable) {",
            "settingsSection.classList.toggle('d-none', !isAvailable);",
            "const downloadsAdminEnabled = Boolean(group.file_downloads_admin_enabled);",
            "setGroupDownloadSettingsVisibility(downloadsAdminEnabled);",
            "if (!downloadsAdminEnabled) {",
            "disableDownloadsInput.checked = false;",
            "return;",
        ],
        "application/single_app/static/js/group/manage_group.js",
    )
    require_ordered_tokens(
        public_script,
        [
            "function setPublicDownloadSettingsVisibility(isAvailable) {",
            "settingsSection.classList.toggle('d-none', !isAvailable);",
            "const downloadsAdminEnabled = Boolean(workspace.file_downloads_admin_enabled);",
            "setPublicDownloadSettingsVisibility(downloadsAdminEnabled);",
            "if (!downloadsAdminEnabled) {",
            "disableDownloadsInput.checked = false;",
            "return;",
        ],
        "application/single_app/static/js/public/manage_public_workspace.js",
    )


def test_fix_documentation_and_version_are_in_sync() -> None:
    """Verify the version bump and fix documentation landed together."""
    assert read_config_version() == CURRENT_VERSION, f"Expected config VERSION {CURRENT_VERSION}"
    assert FIX_DOC.exists(), f"Expected fix documentation at {FIX_DOC}"

    fix_doc = read_text(FIX_DOC)
    require_token(fix_doc, "Fixed/Implemented in version: **0.242.057**", str(FIX_DOC))
    require_token(fix_doc, "application/single_app/static/js/group/manage_group.js", str(FIX_DOC))
    require_token(fix_doc, "application/single_app/static/js/public/manage_public_workspace.js", str(FIX_DOC))
    require_token(fix_doc, "functional_tests/test_group_manage_settings_tab_visibility.py", str(FIX_DOC))
    require_token(fix_doc, "application/single_app/config.py", str(FIX_DOC))


if __name__ == "__main__":
    tests = [
        test_group_manage_settings_pane_unhides_for_admin_roles,
        test_download_settings_patch_responses_match_frontend_contract,
        test_download_settings_visibility_is_admin_gated,
        test_fix_documentation_and_version_are_in_sync,
    ]
    failures = []
    for test in tests:
        try:
            print(f"Running {test.__name__}...")
            test()
            print(f"{test.__name__} passed")
        except Exception as exc:
            failures.append((test.__name__, exc))
            print(f"{test.__name__} failed: {exc}")

    if failures:
        sys.exit(1)
    sys.exit(0)