#!/usr/bin/env python3
# test_file_sync_azure_files_identity.py
"""
Functional test for Azure Files File Sync identity support.
Version: 0.241.178
Implemented in: 0.241.127

This test ensures Azure Files sync sources are wired to managed identity,
service principal, and connection string authentication without requiring live
Azure Storage or Cosmos DB access.
"""

import ast
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def read_text(relative_path):
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def parse_app(relative_path):
    """Parse an application module with AST."""
    return ast.parse(read_text(f"application/single_app/{relative_path}"))


def function_names(parsed):
    """Return function names from a parsed module."""
    return {node.name for node in ast.walk(parsed) if isinstance(node, ast.FunctionDef)}


def test_version_and_dependency_pin():
    """Validate the app version and Azure Files SDK dependency pin."""
    config_text = read_text("application/single_app/config.py")
    requirements_text = read_text("application/single_app/requirements.txt")

    assert 'VERSION = "0.241.178"' in config_text
    assert "azure-storage-file-share==12.25.0" in requirements_text


def test_file_sync_backend_azure_files_wiring():
    """Validate Azure Files connector helpers and auth dispatch exist."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    parsed = parse_app("functions_file_sync.py")
    names = function_names(parsed)

    expected_functions = {
        "_normalize_azure_files_connection",
        "_prepare_azure_files_auth_payload",
        "_prepare_connection_test_azure_files_auth",
        "_test_azure_files_connection",
        "_get_azure_files_service_client",
        "_get_azure_files_share_client",
        "_list_azure_files",
        "_stage_azure_files_file",
        "_list_remote_files",
        "_stage_remote_file",
    }
    assert expected_functions.issubset(names)
    assert 'FILE_SYNC_SOURCE_TYPE_AZURE_FILES = "azure_files"' in file_sync_text
    assert 'FILE_SYNC_SOURCE_TYPE_AZURE_FILES: {"managed_identity", "client_secret", "connection_string"}' in file_sync_text
    assert "ShareServiceClient.from_connection_string" in file_sync_text
    assert "DefaultAzureCredential(managed_identity_client_id=" in file_sync_text
    assert "ClientSecretCredential(" in file_sync_text
    assert '"remote_path": _build_azure_files_url' in file_sync_text
    assert "azure_file_path" in file_sync_text


def test_workspace_identity_catalog_supports_azure_files():
    """Validate reusable identities can describe Azure Files File Sync support."""
    identity_text = read_text("application/single_app/functions_workspace_identities.py")

    assert '"file_sync": ["smb", "azure_files", "onedrive", "google_drive", "google_shared_drive"]' in identity_text
    assert '"file_sync": {"anonymous", "client_secret", "connection_string", "managed_identity", "username_password"}' in identity_text
    assert "managed_identity_client_id" in identity_text
    assert "tenant_id" in identity_text


def test_frontend_source_workflow_supports_azure_files():
    """Validate the source workflow exposes Azure Files fields and auth filtering."""
    file_sync_js = read_text("application/single_app/static/js/workspace/workspace-file-sync.js")
    identities_js = read_text("application/single_app/static/js/workspace/workspace-identities.js")
    admin_template = read_text("application/single_app/templates/admin_settings.html")
    workspace_template = read_text("application/single_app/templates/workspace.html")
    group_template = read_text("application/single_app/templates/group_workspaces.html")
    public_template = read_text("application/single_app/templates/manage_public_workspace.html")

    for marker in [
        "value: 'azure_files'",
        "label: 'Azure Files'",
        "azure_files: ['managed_identity', 'client_secret', 'connection_string']",
        "File service URL",
        "Share name",
        "Directory path",
        "account_url: accountUrlField.input.value.trim()",
        "share_name: shareNameField.input.value.trim()",
        "directory_path: directoryPathField.input.value.trim()",
        "identitySupportsFileSync(identity, selectedSourceType)",
    ]:
        assert marker in file_sync_js

    assert "Use this identity for File Sync sources" in identities_js
    assert "sourceTypes: ['smb', 'azure_files', 'onedrive', 'google_drive', 'google_shared_drive']" in identities_js
    assert "authTypes: ['username_password', 'anonymous', 'managed_identity', 'client_secret', 'connection_string']" in identities_js
    assert "file_sync_visible_source_type_azure_files" in admin_template
    assert "Azure Files" in admin_template
    for template_text in [workspace_template, group_template, public_template]:
        assert "default(['smb', 'azure_files'])" in template_text


def test_synced_document_badges_include_azure_files():
    """Validate synced-document source badges know the Azure Files type."""
    workspace_utils = read_text("application/single_app/static/js/workspace/workspace-utils.js")
    group_template = read_text("application/single_app/templates/group_workspaces.html")
    public_js = read_text("application/single_app/static/js/public/public_workspace.js")

    for frontend_text in [workspace_utils, group_template, public_js]:
        assert "azure_files" in frontend_text
        assert "Managed by File Sync from Azure Files" in frontend_text


def run_tests():
    """Run all tests in this file."""
    tests = [
        test_version_and_dependency_pin,
        test_file_sync_backend_azure_files_wiring,
        test_workspace_identity_catalog_supports_azure_files,
        test_frontend_source_workflow_supports_azure_files,
        test_synced_document_badges_include_azure_files,
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