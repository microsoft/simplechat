#!/usr/bin/env python3
# test_file_sync_capability.py
"""
Functional test for File Sync capability wiring.
Version: 0.241.180
Implemented in: 0.241.042
Updated in: 0.241.180

This test ensures File Sync storage, settings, routes, scheduler hooks, and
credential redaction are wired without requiring live Cosmos DB or SMB access.
"""

import ast
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def read_text(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_config_version_and_containers():
    """Validate version bump and File Sync Cosmos containers."""
    config_text = read_text("application/single_app/config.py")
    assert 'VERSION = "0.241.180"' in config_text

    expected_containers = [
        "personal_file_sync_sources",
        "group_file_sync_sources",
        "public_file_sync_sources",
        "personal_workspace_identities",
        "group_workspace_identities",
        "public_workspace_identities",
        "global_workspace_identities",
        "personal_file_sync_items",
        "group_file_sync_items",
        "public_file_sync_items",
        "personal_file_sync_runs",
        "group_file_sync_runs",
        "public_file_sync_runs",
    ]
    missing = [container for container in expected_containers if container not in config_text]
    assert not missing, f"Missing File Sync containers: {missing}"
    assert 'PartitionKey(path="/source_id")' in config_text


def test_file_sync_settings_and_routes():
    """Validate settings defaults and route registration."""
    settings_text = read_text("application/single_app/functions_settings.py")
    route_text = read_text("application/single_app/route_backend_file_sync.py")
    identity_route_text = read_text("application/single_app/route_backend_workspace_identities.py")
    app_text = read_text("application/single_app/app.py")

    for key in [
        "enable_file_sync",
        "enable_file_sync_personal",
        "enable_file_sync_group",
        "enable_file_sync_public",
        "file_sync_personal_require_app_role",
        "require_group_assignment_for_file_sync",
        "file_sync_allowed_group_ids",
        "require_public_workspace_assignment_for_file_sync",
        "file_sync_allowed_public_workspace_ids",
        "file_sync_personal_admin_only",
        "file_sync_group_admin_only",
        "file_sync_public_admin_only",
        "file_sync_visible_source_types",
        "file_sync_allow_recursive_sources",
    ]:
        assert key in settings_text

    for removed_key in [
        "file_sync_allowed_users",
        "file_sync_allowed_groups",
        "file_sync_allowed_public_workspaces",
    ]:
        assert removed_key not in settings_text

    route_count = len(re.findall(r"@app\.route\(", route_text))
    swagger_count = route_text.count("@swagger_route(security=get_auth_security())")
    assert route_count > 0
    assert route_count == swagger_count
    identity_route_count = len(re.findall(r"@app\.route\(", identity_route_text))
    identity_swagger_count = identity_route_text.count("@swagger_route(security=get_auth_security())")
    assert identity_route_count > 0
    assert identity_route_count == identity_swagger_count
    assert "register_route_backend_file_sync(app)" in app_text
    assert "register_route_backend_workspace_identities(app)" in app_text


def test_file_sync_service_security_shapes():
    """Validate the service module has authorization and redaction safeguards."""
    file_sync_path = APP_ROOT / "functions_file_sync.py"
    file_sync_text = file_sync_path.read_text(encoding="utf-8")
    identity_text = read_text("application/single_app/functions_workspace_identities.py")
    parsed = ast.parse(file_sync_text)
    function_names = {node.name for node in ast.walk(parsed) if isinstance(node, ast.FunctionDef)}

    expected_functions = {
        "get_authorized_sync_source",
        "assert_public_workspace_role",
        "sanitize_file_sync_source",
        "create_file_sync_source",
        "update_file_sync_source",
        "_delete_associated_synced_documents",
        "queue_file_sync_source_run",
        "test_file_sync_source_connection",
        "check_due_file_sync_sources_once",
        "_is_scheduled_source_allowed",
        "build_synced_document_delete_guard",
        "apply_synced_document_delete_action",
        "is_file_sync_source_type_visible",
        "_read_file_sync_source_for_document_action",
    }
    assert expected_functions.issubset(function_names)
    assert "assert_group_role" in file_sync_text
    assert "get_user_role_in_public_workspace" in file_sync_text
    assert "password_secret_name" in file_sync_text
    assert "sanitized_source.pop(\"auth\", None)" in file_sync_text
    assert "sanitize_workspace_identity" in identity_text
    assert "sanitized_identity.pop(\"auth\", None)" in identity_text
    assert "WORKSPACE_IDENTITY_SCOPE_GLOBAL" in identity_text
    assert "WORKSPACE_IDENTITY_USAGE_ALIASES" in identity_text
    assert "WORKSPACE_IDENTITY_USAGE_AUTH_TYPES" in identity_text
    assert "WORKSPACE_IDENTITY_USAGE_SOURCE_TYPES" in identity_text
    assert "allowed_auth_types" in identity_text
    assert "Selected authentication type is not available for the selected identity uses" in identity_text
    assert "allowed_usage_contexts = {\"file_sync\", \"action\"}" in identity_text
    assert "allowed_usage_contexts = {\"file_sync\"}" in identity_text
    assert "FILE_SYNC_IDENTITY_AUTH_TYPES" in file_sync_text
    assert "WORKSPACE_IDENTITY_AUTH_TYPES" in identity_text
    assert "identity_supports_usage" in file_sync_text
    assert "identity_id" in file_sync_text
    assert "admin_management" in file_sync_text
    assert "_user_info_has_admin_role" in file_sync_text
    assert "_user_info_has_app_role" in file_sync_text
    assert "PersonalFileSyncUser" in file_sync_text
    assert "GroupFileSyncUser" not in file_sync_text
    assert "PublicWorkspaceFileSyncUser" not in file_sync_text
    assert "require_group_assignment_for_file_sync" in file_sync_text
    assert "file_sync_allowed_group_ids" in file_sync_text
    assert "require_public_workspace_assignment_for_file_sync" in file_sync_text
    assert "file_sync_allowed_public_workspace_ids" in file_sync_text
    assert "_is_scheduled_source_allowed" in file_sync_text
    assert "FILE_SYNC_KNOWN_SOURCE_TYPES" in file_sync_text
    assert "FILE_SYNC_SOURCE_TYPE_AZURE_FILES" in file_sync_text
    assert "FILE_SYNC_SOURCE_TYPE_ONEDRIVE" in file_sync_text
    assert "FILE_SYNC_ADMIN_VISIBLE_SOURCE_TYPES" in file_sync_text
    assert "file_sync_visible_source_types" in file_sync_text
    assert "file_sync_allowed_users" not in file_sync_text
    assert "file_sync_allowed_groups" not in file_sync_text
    assert "file_sync_allowed_public_workspaces" not in file_sync_text
    assert "file_sync_blocked_users" not in file_sync_text
    assert "file_sync_blocked_groups" not in file_sync_text
    assert "file_sync_blocked_public_workspaces" not in file_sync_text


def test_file_sync_delete_guards():
    """Validate document delete routes call the synced-document guard."""
    route_files = [
        "application/single_app/route_backend_documents.py",
        "application/single_app/route_backend_group_documents.py",
        "application/single_app/route_backend_public_documents.py",
    ]
    for route_file in route_files:
        route_text = read_text(route_file)
        assert "build_synced_document_delete_guard" in route_text
        assert "apply_synced_document_delete_action" in route_text
        assert "file_sync_delete_action" in route_text


def test_file_sync_delete_prompt_frontend_wiring():
    """Validate workspace delete flows can resolve synced document delete actions."""
    frontend_files = [
        "application/single_app/static/js/workspace/workspace-documents.js",
        "application/single_app/templates/group_workspaces.html",
        "application/single_app/static/js/public/public_workspace.js",
    ]
    for frontend_file in frontend_files:
        frontend_text = read_text(frontend_file)
        assert "synced_document_delete_requires_action" in frontend_text
        assert "file_sync_delete_action" in frontend_text
        assert "ignore_remote" in frontend_text
        assert "let selectedValue = null" in frontend_text
        assert "resolve(selectedValue)" in frontend_text
        assert "hideWithValue" in frontend_text


def test_file_sync_stale_source_delete_wiring():
    """Validate synced-document delete handling tolerates deleted sync sources."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")

    assert "def _read_file_sync_source_for_document_action" in file_sync_text
    assert "except CosmosResourceNotFoundError" in file_sync_text
    assert "source = _read_file_sync_source_for_document_action" in file_sync_text
    assert "if not source:\n        return None" in file_sync_text
    assert "if not source:\n        return\n    set_file_sync_path_ignored" in file_sync_text


def test_file_sync_activity_log_display_wiring():
    """Validate Control Center recognizes File Sync activity records."""
    control_center_template = read_text("application/single_app/templates/control_center.html")
    control_center_js = read_text("application/single_app/static/js/control-center.js")
    control_center_backend = read_text("application/single_app/route_backend_control_center.py")
    activity_logging_text = read_text("application/single_app/functions_activity_logging.py")

    assert "log_file_sync_activity" in activity_logging_text
    assert "activity_type': 'file_sync'" in activity_logging_text
    assert '<option value="file_sync">File Sync</option>' in control_center_template
    assert "'file_sync': 'File Sync'" in control_center_js
    assert "case 'file_sync':" in control_center_js
    assert "activity_type == 'file_sync'" in control_center_backend


def test_file_sync_admin_and_sidebar_discovery():
    """Validate admins and workspace managers can discover File Sync controls."""
    admin_template = read_text("application/single_app/templates/admin_settings.html")
    admin_route = read_text("application/single_app/route_frontend_admin_settings.py")
    backend_route = read_text("application/single_app/route_backend_file_sync.py")
    admin_js = read_text("application/single_app/static/js/admin/admin_settings.js")
    sidebar_template = read_text("application/single_app/templates/_sidebar_nav.html")

    for field_name in [
        "enable_file_sync",
        "enable_file_sync_personal",
        "enable_file_sync_group",
        "enable_file_sync_public",
        "file_sync_personal_require_app_role",
        "require_group_assignment_for_file_sync",
        "file_sync_allowed_group_ids",
        "require_public_workspace_assignment_for_file_sync",
        "file_sync_allowed_public_workspace_ids",
        "file_sync_personal_admin_only",
        "file_sync_group_admin_only",
        "file_sync_public_admin_only",
        "file_sync_visible_source_types",
        "file_sync_max_sources_per_scope",
        "file_sync_min_schedule_interval_minutes",
        "file_sync_max_files_per_run",
        "file_sync_max_gb_per_run",
        "file_sync_max_concurrent_runs",
        "file_sync_allow_recursive_sources",
    ]:
        assert f'name="{field_name}"' in admin_template
        assert field_name in admin_route

    assert 'name="file_sync_default_remote_delete_policy"' not in admin_template
    assert 'name="file_sync_debug_logging"' not in admin_template
    assert "file_sync_allowed_users" not in admin_template
    assert "file_sync_allowed_groups" not in admin_template
    assert "file_sync_allowed_public_workspaces" not in admin_template
    assert "file_sync_blocked_users" not in admin_template
    assert "file_sync_blocked_groups" not in admin_template
    assert "file_sync_blocked_public_workspaces" not in admin_template
    assert "data-file-sync-access-list" not in admin_template
    assert "PersonalFileSyncUser" in admin_template
    assert "GroupFileSyncUser" not in admin_template
    assert "PublicWorkspaceFileSyncUser" not in admin_template
    assert "fileSyncGroupAssignmentModal" in admin_template
    assert "fileSyncPublicWorkspaceAssignmentModal" in admin_template
    assert "Manage Groups" in admin_template
    assert "Manage Public Workspaces" in admin_template
    assert "file-sync-app-role-setup-modal" in admin_template
    assert "Visible Source Types" in admin_template
    assert "file_sync_visible_source_type_smb" in admin_template
    assert "file_sync_visible_source_type_azure_files" in admin_template
    assert "file_sync_visible_source_type_onedrive" in admin_template
    assert "file_sync_visible_source_type_sharepoint_on_prem" in admin_template
    assert "file_sync_visible_source_type_google_workspace" in admin_template
    assert 'id="file_sync_visible_source_type_onedrive" value="onedrive" disabled' in admin_template
    assert 'id="file_sync_visible_source_type_sharepoint_on_prem" value="sharepoint_on_prem" disabled' in admin_template
    assert 'id="file_sync_visible_source_type_google_workspace" value="google_workspace" disabled' in admin_template
    assert 'name="file_sync_visible_source_types" value="onedrive"' not in admin_template
    assert "OneDrive, SharePoint, and Google Workspace connectors are coming soon" in admin_template
    assert admin_template.count("Coming Soon.") >= 3
    assert "data-file-sync-admin-target" in admin_template
    assert "file-sync-admin-manager-modal" in admin_template
    assert "/api/admin/file-sync/users/search" in backend_route
    assert "/api/admin/file-sync/groups/search" in backend_route
    assert "/api/admin/file-sync/public-workspaces/search" in backend_route
    assert "/api/admin/file-sync/personal/<target_user_id>/sources" in backend_route
    assert "/api/admin/file-sync/group/<group_id>/sources" in backend_route
    assert "/api/admin/file-sync/public/<public_workspace_id>/sources" in backend_route
    workspace_identity_route = read_text("application/single_app/route_backend_workspace_identities.py")
    assert "/api/admin/workspace-identities/<scope_type>/<scope_id>/identities" in workspace_identity_route
    assert "/api/admin/workspace-identities/global/identities" in workspace_identity_route
    assert "/api/workspace-identities/personal/identities" in workspace_identity_route
    assert "/api/workspace-identities/group/identities" in workspace_identity_route
    assert "/api/workspace-identities/public/<public_workspace_id>/identities" in workspace_identity_route
    assert "search_directory_users" in backend_route
    assert "search_all_groups" in backend_route
    assert "search_all_public_workspaces" in backend_route

    assert 'id="file-sync-tab"' in admin_template
    assert 'id="file-sync"' in admin_template
    assert 'id="workspace-identities-tab"' in admin_template
    assert 'id="workspace-identities"' in admin_template
    assert 'id="global-workspace-identities-root"' in admin_template
    assert 'data-identity-api-base="/api/admin/workspace-identities/global"' in admin_template
    assert 'id="file-sync-section"' in admin_template
    assert 'id="file_sync_settings"' in admin_template
    assert "Redis Cache must be enabled" in admin_template
    assert "get_file_sync_config" in admin_route
    assert "parse_file_sync_list" not in admin_route
    assert "file_sync_allowed_users" not in admin_route
    assert "file_sync_allowed_groups" not in admin_route
    assert "file_sync_allowed_public_workspaces" not in admin_route
    assert "file_sync_blocked_users" not in admin_route
    assert "file_sync_blocked_groups" not in admin_route
    assert "file_sync_blocked_public_workspaces" not in admin_route
    assert "fileSyncSettings.classList.toggle('d-none'" in admin_js
    assert "setupFileSyncAccessLists" not in admin_js
    assert "setupFileSyncAssignments" in admin_js
    assert "fileSyncAssignmentManagers" in admin_js
    assert "setupFileSyncAdminTargets" in admin_js
    assert "openFileSyncAdminManager" in admin_js
    assert "getSelectedFileSyncVisibleSourceTypes" in admin_js
    assert "root.dataset.visibleSourceTypes" in admin_js
    assert 'data-tab="file-sync"' in sidebar_template
    assert 'data-tab="workspace-identities"' in sidebar_template
    assert "Global Identities" in sidebar_template
    assert 'data-tab="workspaces" data-section="file-sync-section"' not in sidebar_template
    assert 'data-tab="sync-tab"' in sidebar_template
    assert 'data-tab="identities-tab"' in sidebar_template
    assert "file_sync_enabled" in sidebar_template


def test_file_sync_recursive_and_connection_test_wiring():
    """Validate recursive source controls, tag UI, and SMB connection testing."""
    settings_text = read_text("application/single_app/functions_settings.py")
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    route_text = read_text("application/single_app/route_backend_file_sync.py")
    file_sync_js = read_text("application/single_app/static/js/workspace/workspace-file-sync.js")
    identities_js = read_text("application/single_app/static/js/workspace/workspace-identities.js")
    workspace_template = read_text("application/single_app/templates/workspace.html")
    group_template = read_text("application/single_app/templates/group_workspaces.html")
    public_template = read_text("application/single_app/templates/manage_public_workspace.html")

    assert "'file_sync_allow_recursive_sources': True" in settings_text
    assert '"file_sync_allow_recursive_sources": True' in file_sync_text
    assert '"recursive": _as_bool' in file_sync_text
    assert "recursive_enabled = bool" in file_sync_text
    assert "if recursive_enabled:\n                    walk_directory(entry_path)" in file_sync_text
    assert "relative_path = remote_file.get" in file_sync_text
    assert "folder_parts = [part for part in relative_path.split" in file_sync_text

    assert "def test_file_sync_source_connection" in file_sync_text
    assert "_prepare_connection_test_auth" in file_sync_text
    assert "/sources/test-connection" in route_text
    assert "/sources/<source_id>/test-connection" in route_text
    assert "_assert_new_source_type_visible" in route_text
    assert "is_file_sync_source_type_visible" in route_text

    for template_text in [workspace_template, group_template, public_template]:
        assert "data-recursive-allowed" in template_text
        assert "data-tags-api" in template_text

    assert "file-sync-recursive" in file_sync_js
    assert "Include subfolders" in file_sync_js
    assert "data-file-sync-source-modal" in file_sync_js
    assert "initializeWorkspaceIdentityRoot" in identities_js
    assert "openIdentityModal" in identities_js
    assert "getCapabilitiesFromIdentity" in identities_js
    assert "getCapabilityPayloadValues" in identities_js
    assert "Identity Details" in identities_js
    assert "Used For" in identities_js
    assert "File Sync" in identities_js
    assert "Actions" in identities_js
    assert "Model Endpoints" in identities_js
    assert "type: 'checkbox'" in identities_js
    assert "usage_contexts: capabilityPayload.usageContexts" in identities_js
    assert "supported_source_types: capabilityPayload.sourceTypes" in identities_js
    assert "Client ID" in identities_js
    assert "Domain (optional)" in identities_js
    assert "Leave this blank when the account signs in without a domain." in identities_js
    assert "aria-describedby" in identities_js
    assert "selectedAuthType === 'client_secret'" in identities_js
    assert "data-bs-toggle': 'tooltip'" in identities_js
    assert "View" in identities_js
    assert "Edit" in identities_js
    assert "data-workspace-identity-root" in workspace_template
    assert "data-workspace-identity-root" in group_template
    assert "data-workspace-identity-root" in public_template
    assert "data-capability-options" in workspace_template
    assert "data-capability-options" in group_template
    assert "data-capability-options=\"file_sync\"" in public_template
    assert "data-identity-title" not in workspace_template
    assert "data-usage-context-options" not in workspace_template
    assert "data-provider-options" not in workspace_template
    assert "identityApiBase" in file_sync_js
    assert "/api/workspace-identities/" in file_sync_js
    assert "Reusable identity" in file_sync_js
    assert "identitySupportsFileSync" in file_sync_js
    assert "Path patterns" in file_sync_js
    assert "Add Pattern" in file_sync_js
    assert "Add File Type" in file_sync_js
    assert "Choose Existing Tags" in file_sync_js
    assert "Create Tag" in file_sync_js
    assert "data-visible-source-types" in workspace_template
    assert "data-visible-source-types" in group_template
    assert "data-visible-source-types" in public_template
    assert "Source Type" in file_sync_js
    assert "Configure Source" in file_sync_js
    assert "SMB Share" in file_sync_js
    assert "Azure Files" in file_sync_js
    assert "File service URL" in file_sync_js
    assert "Share name" in file_sync_js
    assert "sharepoint_on_prem" in file_sync_js
    assert "google_workspace" in file_sync_js
    assert "visibleSourceTypeValues" in file_sync_js
    assert "getVisibleSourceTypes" in file_sync_js
    assert "No source types are visible" in file_sync_js
    assert "source_type: selectedSourceType" in file_sync_js
    assert "['Source', 'Type', 'Status', 'Schedule', 'Last run', 'Counts', 'Actions']" in file_sync_js
    assert "Test Connection" in file_sync_js
    assert "buildFixedTagSelector" in file_sync_js
    assert "showFallbackTagPicker" in file_sync_js
    assert "Schedule interval minutes" in file_sync_js
    assert "btn btn-success btn-sm" in file_sync_js
    assert "Sync Sources" not in file_sync_js
    assert "text: 'Identities'" not in file_sync_js
    assert "text: 'Refresh'" not in file_sync_js


def test_file_sync_source_delete_options_wiring():
    """Validate File Sync source deletion offers keep-files and delete-files options."""
    file_sync_text = read_text("application/single_app/functions_file_sync.py")
    route_text = read_text("application/single_app/route_backend_file_sync.py")
    file_sync_js = read_text("application/single_app/static/js/workspace/workspace-file-sync.js")

    assert "def _delete_associated_synced_documents" in file_sync_text
    assert "delete_associated_files" in file_sync_text
    assert "_delete_synced_document(source, document_id)" in file_sync_text
    assert "documents_deleted" in file_sync_text
    assert "documents_failed" in file_sync_text

    assert "delete_associated_files=bool(payload.get(\"delete_associated_files\"))" in route_text
    assert '"delete_result": delete_result' in route_text

    assert "showDeleteSourceModal" in file_sync_js
    assert "Delete Sync Source" in file_sync_js
    assert "Delete All Files" in file_sync_js
    assert "deleteChoice === 'delete_all_files'" in file_sync_js
    assert "deleteButton.dataset.confirm" not in file_sync_js


def test_file_sync_document_indicator_wiring():
    """Validate synced documents render a system indicator without using tags."""
    file_sync_service = read_text("application/single_app/functions_file_sync.py")
    workspace_utils = read_text("application/single_app/static/js/workspace/workspace-utils.js")
    workspace_documents = read_text("application/single_app/static/js/workspace/workspace-documents.js")
    workspace_tags = read_text("application/single_app/static/js/workspace/workspace-tags.js")
    group_template = read_text("application/single_app/templates/group_workspaces.html")
    public_template = read_text("application/single_app/templates/public_workspaces.html")
    public_js = read_text("application/single_app/static/js/public/public_workspace.js")
    workspace_template = read_text("application/single_app/templates/workspace.html")

    assert "doc.file_sync" in workspace_utils
    assert "getDocumentSyncBadgeHtml" in workspace_utils
    assert "getDocumentSyncDetailsHtml" in workspace_utils
    assert "setDocumentSyncStatusElement" in workspace_utils
    assert '"source_type": source.get("source_type", FILE_SYNC_SOURCE_TYPE_SMB)' in file_sync_service

    for frontend_text in [workspace_documents, group_template, public_js]:
        assert "file_sync" in frontend_text

    for frontend_text in [workspace_utils, group_template, public_js]:
        assert "source_type || 'smb'" in frontend_text
        assert "bi bi-arrow-repeat me-1" in frontend_text
        assert "SMB" in frontend_text
        assert "Azure Files" in frontend_text
        assert "m365sp" in frontend_text
        assert "M365SP" in frontend_text
        assert "one_drive" in frontend_text
        assert "OneDrive" in frontend_text
        assert "google" in frontend_text
        assert "Google" in frontend_text
        assert "spo" in frontend_text
        assert "SPO" in frontend_text
        assert "bg-primary text-white" in frontend_text
        assert "bg-warning text-dark" in frontend_text
        assert "bg-success text-white" in frontend_text

    assert "getDocumentSyncBadgeHtml(doc, true)" in workspace_documents
    assert "getDocumentSyncBadgeHtml(doc, true)" in workspace_tags
    assert "getGroupDocumentSyncBadgeHtml(doc, true)" in group_template
    assert "getPublicDocumentSyncBadgeHtml(doc, true)" in public_js

    assert 'id="doc-sync-status"' in workspace_template
    assert 'id="group-doc-sync-status"' in group_template
    assert 'id="public-doc-sync-status"' in public_template

    assert "doc.tags" not in workspace_utils
    assert "folder_tag_mode" not in workspace_utils


def run_tests():
    """Run all tests in this file."""
    tests = [
        test_config_version_and_containers,
        test_file_sync_settings_and_routes,
        test_file_sync_service_security_shapes,
        test_file_sync_delete_guards,
        test_file_sync_delete_prompt_frontend_wiring,
        test_file_sync_stale_source_delete_wiring,
        test_file_sync_activity_log_display_wiring,
        test_file_sync_admin_and_sidebar_discovery,
        test_file_sync_recursive_and_connection_test_wiring,
        test_file_sync_source_delete_options_wiring,
        test_file_sync_document_indicator_wiring,
    ]
    failures = []
    for test in tests:
        try:
            print(f"Running {test.__name__}...")
            test()
            print(f"Passed {test.__name__}")
        except Exception as error:
            failures.append((test.__name__, error))
            print(f"Failed {test.__name__}: {error}")

    if failures:
        return False
    return True


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)