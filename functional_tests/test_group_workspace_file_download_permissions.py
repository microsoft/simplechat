#!/usr/bin/env python3
# test_group_workspace_file_download_permissions.py
"""
Functional test for group workspace file download permissions.
Version: 0.241.195
Implemented in: 0.241.195

This test ensures group workspace file downloads remain limited to owners,
admins, and document managers when downloads are enabled, while regular users
cannot see or invoke download controls.
"""

import re
import sys
from pathlib import Path


IMPLEMENTED_VERSION = "0.241.195"
REPO_ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    """Read a UTF-8 text file from the repository."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def version_tuple(version):
    """Convert a dotted version string into a comparable tuple."""
    return tuple(int(part) for part in version.split("."))


def get_config_version():
    """Extract the application version from config.py."""
    config_text = read_text("application/single_app/config.py")
    match = re.search(r'VERSION\s*=\s*"(?P<version>\d+\.\d+\.\d+)"', config_text)
    assert match, "Could not locate VERSION in config.py"
    return match.group("version")


def extract_between(content, start_marker, end_marker):
    """Return the source block between two markers."""
    start_index = content.find(start_marker)
    assert start_index != -1, f"Could not locate start marker: {start_marker}"

    end_index = content.find(end_marker, start_index)
    assert end_index != -1, f"Could not locate end marker: {end_marker}"

    return content[start_index:end_index]


def assert_contains(source, snippets, description):
    """Assert all snippets exist in a source string."""
    missing = [snippet for snippet in snippets if snippet not in source]
    assert not missing, f"Missing {description} snippets: {missing}"


def test_config_version_includes_group_download_permission_fix():
    """Verify config.py was bumped for this permission fix."""
    print("Testing config version for group download permission fix...")

    current_version = get_config_version()
    assert version_tuple(current_version) >= version_tuple(IMPLEMENTED_VERSION), (
        f"Expected config.py VERSION to be at least {IMPLEMENTED_VERSION}, "
        f"found {current_version}"
    )

    print("config version check passed")


def test_group_download_backend_is_manager_only():
    """Verify group document download endpoints reject regular group users."""
    print("Testing backend group document download role guard...")

    route_text = read_text("application/single_app/route_backend_group_documents.py")
    authorizer_block = extract_between(
        route_text,
        "    def _authorize_group_document_download(user_id, document_id):",
        "    @app.route('/api/group_documents/<document_id>/download', methods=['GET'])",
    )

    assert_contains(
        route_text,
        [
            'GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")',
            "validated_group_roles = {}",
            "validated_group_roles[gid] = role",
            "validated_group_roles[active_group_id] = role",
            "validated_group_roles.get(group_id) in GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES",
        ],
        "group document download role policy",
    )
    assert "allowed_roles=GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES" in authorizer_block
    assert '"User"' not in authorizer_block, "Download authorizer must not allow regular User role"

    print("backend group document download role guard check passed")


def test_group_workspace_ui_hides_downloads_for_users():
    """Verify the group workspace page only exposes download actions to managers."""
    print("Testing group workspace download permission UI wiring...")

    template_text = read_text("application/single_app/templates/group_workspaces.html")
    can_download_block = extract_between(
        template_text,
        "  function canDownloadGroupDocuments() {",
        "  async function downloadGroupDocumentFile(documentId, event) {",
    )

    assert_contains(
        template_text,
        [
            'const GROUP_DOCUMENT_DOWNLOAD_MANAGER_ROLES = ["Owner", "Admin", "DocumentManager"]',
            "function canManageGroupDocumentDownloads()",
            "!canManageGroupDocumentDownloads()",
            "function getGroupDownloadUnavailableMessage()",
            "You do not have permission to download files from this group workspace.",
            "downloadBtn.classList.toggle(\"d-none\", !canDownloadGroupDocuments())",
        ],
        "group workspace download UI role guard",
    )
    assert can_download_block.find("!canManageGroupDocumentDownloads()") < can_download_block.find("groupFileDownloadEnabledGroupIds.includes(activeGroupId)"), (
        "Expected role guard to run before group assignment checks"
    )

    print("group workspace download permission UI wiring check passed")


if __name__ == "__main__":
    tests = [
        test_config_version_includes_group_download_permission_fix,
        test_group_download_backend_is_manager_only,
        test_group_workspace_ui_hides_downloads_for_users,
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