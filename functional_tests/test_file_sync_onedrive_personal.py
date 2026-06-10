#!/usr/bin/env python3
# test_file_sync_onedrive_personal.py
"""
Functional test for personal OneDrive File Sync support.
Version: 0.241.178
Implemented in: 0.241.128

This test ensures OneDrive sync source code remains wired as personal-only File
Sync support while the admin source-type control keeps OneDrive marked as coming
soon until validation is complete.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def parse_app(relative_path):
    """Parse an application module with AST."""
    return ast.parse(read_text(f"application/single_app/{relative_path}"))


def function_names(parsed):
    """Return function names from a parsed module."""
    return {node.name for node in ast.walk(parsed) if isinstance(node, ast.FunctionDef)}


def test_version_and_source_defaults():
    """Validate OneDrive code remains present while admin defaults exclude it."""
    config_text = read_text("application/single_app/config.py")
    settings_text = read_text("application/single_app/functions_settings.py")
    file_sync_text = read_text("application/single_app/functions_file_sync.py")

    assert 'VERSION = "0.241.178"' in config_text
    assert "FILE_SYNC_SOURCE_TYPE_ONEDRIVE = \"onedrive\"" in file_sync_text
    assert "FILE_SYNC_SOURCE_TYPE_ONEDRIVE" in file_sync_text
    assert "FILE_SYNC_SOURCE_TYPE_ONEDRIVE: {\"client_secret\"}" in file_sync_text
    assert "'file_sync_visible_source_types': ['smb', 'azure_files']" in settings_text


def test_onedrive_backend_provider_wiring():
    """Validate OneDrive provider helpers and personal-only guards exist."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    parsed = parse_app("functions_file_sync.py")
    names = function_names(parsed)

    expected_functions = {
        "_normalize_onedrive_connection",
        "_get_graph_app_token",
        "_get_global_file_sync_identity_auth",
        "_resolve_graph_app_credentials",
        "_graph_get_json",
        "_browse_onedrive_path",
        "_test_onedrive_connection",
        "_list_onedrive_files",
        "_stage_onedrive_file",
        "browse_file_sync_source_path",
        "_normalize_selected_paths",
        "_browse_smb_path",
        "_browse_azure_files_path",
    }
    assert expected_functions.issubset(names)
    assert "OneDrive File Sync sources can only be added to personal workspaces" in file_sync_text
    assert "admin-managed global File Sync identity" in file_sync_text
    assert "WORKSPACE_IDENTITY_SCOPE_GLOBAL" in file_sync_text
    assert "list_workspace_identities" in file_sync_text
    assert "remote_change_token" in file_sync_text
    assert "selected_paths" in file_sync_text
    assert "onedrive://" in file_sync_text
    assert "requests.get(download_url" in file_sync_text


def test_global_connector_identity_supports_cloud_drive_sync():
    """Validate global workspace identities can manage cloud drive File Sync credentials."""
    identity_text = read_text("application/single_app/functions_workspace_identities.py")
    identity_js = read_text("application/single_app/static/js/workspace/workspace-identities.js")
    admin_template = read_text("application/single_app/templates/admin_settings.html")

    assert '"file_sync": ["smb", "azure_files", "onedrive", "google_drive", "google_shared_drive"]' in identity_text
    assert 'allowed_usage_contexts = {"file_sync", "action"}' in identity_text
    assert "admin/workspace-identities/global" in admin_template
    assert 'data-capability-options="file_sync,action"' in admin_template
    assert "Cloud drive connector identities" in admin_template
    assert "OneDrive, SharePoint, and Google Workspace File Sync connectors are coming soon" in admin_template
    assert "admin-approved cloud drive connectors" in identity_js
    assert "'smb', 'azure_files', 'onedrive', 'google_drive', 'google_shared_drive'" in identity_js


def test_file_sync_browse_routes_are_registered():
    """Validate browse APIs are available for source creation and editing."""
    route_text = read_text("application/single_app/route_backend_file_sync.py")

    assert "browse_file_sync_source_path" in route_text
    assert "sources/browse" in route_text
    assert "sources/<source_id>/browse" in route_text
    assert "api_admin_file_sync_source_browse_new" in route_text
    assert "api_file_sync_source_browse_new" in route_text
    assert "api_file_sync_public_source_browse_new" in route_text


def test_frontend_source_selection_supports_onedrive():
    """Validate the source modal exposes OneDrive and selected-path UX."""
    file_sync_js = read_text("application/single_app/static/js/workspace/workspace-file-sync.js")
    admin_template = read_text("application/single_app/templates/admin_settings.html")
    workspace_template = read_text("application/single_app/templates/workspace.html")
    group_template = read_text("application/single_app/templates/group_workspaces.html")
    public_template = read_text("application/single_app/templates/manage_public_workspace.html")

    for marker in [
        "value: 'onedrive'",
        "label: 'OneDrive'",
        "scopes: ['personal']",
        "onedrive: ['global_identity']",
        "Global connector identity",
        "Selected folders and files",
        "Selection, Subfolders, and Filters",
        "selected_paths: selectedPaths",
        "sources/${state.editingSourceId}/browse",
        "sources/browse",
    ]:
        assert marker in file_sync_js

    assert "file_sync_visible_source_type_onedrive" in admin_template
    assert "OneDrive" in admin_template
    assert 'id="file_sync_visible_source_type_onedrive" value="onedrive" disabled' in admin_template
    assert 'name="file_sync_visible_source_types" value="onedrive"' not in admin_template
    assert "OneDrive, SharePoint, and Google Workspace connectors are coming soon" in admin_template
    assert "Coming Soon." in admin_template
    for template_text in [workspace_template, group_template, public_template]:
        assert "default(['smb', 'azure_files'])" in template_text


def test_synced_document_badges_include_onedrive():
    """Validate synced-document source badges include OneDrive."""
    workspace_utils = read_text("application/single_app/static/js/workspace/workspace-utils.js")
    group_template = read_text("application/single_app/templates/group_workspaces.html")
    public_js = read_text("application/single_app/static/js/public/public_workspace.js")

    for frontend_text in [workspace_utils, group_template, public_js]:
        assert "onedrive" in frontend_text
        assert "Managed by File Sync from OneDrive" in frontend_text


def run_tests():
    """Run all tests in this file."""
    tests = [
        test_version_and_source_defaults,
        test_onedrive_backend_provider_wiring,
        test_global_connector_identity_supports_cloud_drive_sync,
        test_file_sync_browse_routes_are_registered,
        test_frontend_source_selection_supports_onedrive,
        test_synced_document_badges_include_onedrive,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            results.append(False)
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
