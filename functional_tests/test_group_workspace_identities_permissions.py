#!/usr/bin/env python3
# test_group_workspace_identities_permissions.py
"""
Functional test for group workspace identities permission UI.
Version: 0.241.114
Implemented in: 0.241.114

This test ensures group workspace identities stay manager-only while regular
users receive a clear no-permission state instead of a blank Identities tab.
"""

import re
import sys
from pathlib import Path


IMPLEMENTED_VERSION = "0.241.114"
REPO_ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def version_tuple(version):
    return tuple(int(part) for part in version.split("."))


def extract_between(content, start_marker, end_marker):
    start_index = content.find(start_marker)
    assert start_index != -1, f"Could not locate start marker: {start_marker}"

    end_index = content.find(end_marker, start_index)
    assert end_index != -1, f"Could not locate end marker: {end_marker}"

    return content[start_index:end_index]


def get_config_version():
    config_text = read_text("application/single_app/config.py")
    match = re.search(r'VERSION\s*=\s*"(?P<version>\d+\.\d+\.\d+)"', config_text)
    assert match, "Could not locate VERSION in config.py"
    return match.group("version")


def test_config_version_includes_group_identities_permission_fix():
    """Verify config.py was bumped for this permission UI fix."""
    print("Testing config version for group identities permission UI fix...")

    current_version = get_config_version()
    assert version_tuple(current_version) >= version_tuple(IMPLEMENTED_VERSION), (
        f"Expected config.py VERSION to be at least {IMPLEMENTED_VERSION}, "
        f"found {current_version}"
    )

    print("config version check passed")


def test_group_identity_routes_remain_manager_only():
    """Verify group identity APIs still require manager-level group roles."""
    print("Testing backend group identity manager roles...")

    route_text = read_text("application/single_app/route_backend_workspace_identities.py")

    assert 'WORKSPACE_IDENTITY_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")' in route_text
    assert "require_active_group(user_id, allowed_roles=WORKSPACE_IDENTITY_MANAGER_ROLES)" in route_text
    assert "assert_group_role(user_id, group_id, allowed_roles=WORKSPACE_IDENTITY_MANAGER_ROLES)" in route_text
    assert "def api_workspace_identities_group_list" in route_text

    print("backend group identity role check passed")


def test_group_workspace_identities_navigation_is_permission_aware():
    """Verify the group page hides Identities navigation until a manager role is active."""
    print("Testing group identities navigation permission wiring...")

    group_template = read_text("application/single_app/templates/group_workspaces.html")
    sidebar_template = read_text("application/single_app/templates/_sidebar_nav.html")

    expected_group_markers = [
        'data-group-identities-section-option hidden disabled',
        'class="nav-item d-none" role="presentation" data-group-identities-tab-nav',
        'data-can-manage="false"',
        'data-permission-message="You do not have permission to manage or view identities for this group."',
        'const GROUP_WORKSPACE_IDENTITY_MANAGER_ROLES = ["Owner", "Admin", "DocumentManager"]',
        'function updateGroupIdentitiesPermissionUI()',
        'canManageIdentities: canManageGroupWorkspaceIdentities()',
        'workspace-identities:permissions-changed',
        'workspace-identities:refresh',
    ]
    missing_group_markers = [marker for marker in expected_group_markers if marker not in group_template]
    assert not missing_group_markers, f"Missing group template markers: {missing_group_markers}"

    assert 'data-group-identities-sidebar-nav' in sidebar_template
    assert '<li class="nav-item d-none" data-group-identities-sidebar-nav>' in sidebar_template

    print("group identities navigation permission wiring check passed")


def test_workspace_identity_component_renders_permission_state_without_fetching():
    """Verify the shared identity component can render a no-permission state."""
    print("Testing workspace identities permission state wiring...")

    identities_js = read_text("application/single_app/static/js/workspace/workspace-identities.js")

    expected_markers = [
        "root.dataset.canManage !== 'false'",
        "renderPermissionNotice",
        "You do not have permission to manage or view identities for this workspace.",
        "data-workspace-identity-permission-message",
        "if (!state.canManage)",
        "workspace-identities:permissions-changed",
        "workspace-identities:refresh",
        "root.workspaceIdentityRefresh = refreshIdentities",
    ]
    missing_markers = [marker for marker in expected_markers if marker not in identities_js]
    assert not missing_markers, f"Missing workspace identities JS markers: {missing_markers}"

    load_identities_block = extract_between(
        identities_js,
        "    const loadIdentities = async () => {",
        "    const openDeleteIdentityModal =",
    )
    assert load_identities_block.find("if (!state.canManage)") < load_identities_block.find("const payload = await fetchJson"), (
        "Expected permission checks to run before identity API fetches"
    )

    print("workspace identities permission state check passed")


if __name__ == "__main__":
    tests = [
        test_config_version_includes_group_identities_permission_fix,
        test_group_identity_routes_remain_manager_only,
        test_group_workspace_identities_navigation_is_permission_aware,
        test_workspace_identity_component_renders_permission_state_without_fetching,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
        except Exception as ex:
            print(f"Test failed: {ex}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
