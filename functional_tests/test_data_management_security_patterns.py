#!/usr/bin/env python3
# test_data_management_security_patterns.py
"""
Functional test for Data Management security patterns.
Version: 0.241.231
Implemented in: 0.241.211
Updated in: 0.241.231

This test ensures Data Management admin routes require authenticated admin
access, secrets stay redacted in frontend responses, and the admin browser
controller avoids XSS-prone rendering sinks. It also verifies the migration
target database name is fixed to SimpleChat.
"""

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
ROUTE_FILE = APP_ROOT / "route_backend_data_management.py"
FUNCTIONS_FILE = APP_ROOT / "functions_data_management.py"
ADMIN_JS = APP_ROOT / "static" / "js" / "admin" / "admin_data_management.js"
ADMIN_TEMPLATE = APP_ROOT / "templates" / "admin_settings.html"
CONTROL_CENTER_TEMPLATE = APP_ROOT / "templates" / "control_center.html"
SIDEBAR_TEMPLATE = APP_ROOT / "templates" / "_sidebar_nav.html"
CONTROL_CENTER_JS = APP_ROOT / "static" / "js" / "control-center.js"
CONFIG_FILE = APP_ROOT / "config.py"


def read_text(path):
    return path.read_text(encoding="utf-8")


def route_functions_with_decorators():
    parsed = ast.parse(read_text(ROUTE_FILE), filename=str(ROUTE_FILE))
    route_functions = []
    for node in ast.walk(parsed):
        if not isinstance(node, ast.FunctionDef):
            continue
        decorator_names = []
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute):
                if decorator.func.attr == "route":
                    decorator_names.append("app.route")
                elif decorator.func.attr:
                    decorator_names.append(decorator.func.attr)
            elif isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
                decorator_names.append(decorator.func.id)
            elif isinstance(decorator, ast.Name):
                decorator_names.append(decorator.id)
        if "app.route" in decorator_names:
            route_functions.append((node.name, decorator_names))
    return route_functions


def test_version_and_container_registration():
    """Validate the Data Management version and Cosmos job container registrations."""
    config_source = read_text(CONFIG_FILE)

    assert 'VERSION = "0.241.231"' in config_source
    assert 'cosmos_data_management_jobs_container_name = "data_management_jobs"' in config_source
    assert 'partition_key=PartitionKey(path="/id")' in config_source
    assert 'cosmos_data_management_job_items_container_name = "data_management_job_items"' in config_source
    assert 'partition_key=PartitionKey(path="/job_id")' in config_source


def test_admin_routes_require_login_admin_and_swagger_security():
    """Validate every Data Management route has the required admin security stack."""
    routes = route_functions_with_decorators()
    assert len(routes) == 13

    for function_name, decorators in routes:
        assert "swagger_route" in decorators, f"{function_name} missing swagger_route"
        assert "login_required" in decorators, f"{function_name} missing login_required"
        assert "admin_required" in decorators, f"{function_name} missing admin_required"

    source = read_text(ROUTE_FILE)
    assert 'from swagger_wrapper import get_auth_security, swagger_route' in source
    assert '/api/admin/data-management/settings' in source
    assert '/api/admin/data-management/jobs' in source
    assert '/api/admin/data-management/jobs/<job_id>' in source
    assert '/api/admin/data-management/backups' in source
    assert '/api/admin/data-management/migration/catalog/<target_type>' in source
    assert '/api/admin/data-management/migration/summary' in source
    assert '/api/admin/data-management/target/cosmos/test' in source
    assert '/api/admin/data-management/target/search/test' in source
    assert '/api/admin/data-management/target/enhanced-citation-storage/test' in source
    assert 'current_app._get_current_object()' in source


def test_settings_secrets_are_redacted_for_frontend():
    """Validate backup settings secrets are redacted before returning to the browser."""
    source = read_text(FUNCTIONS_FILE)

    for field_name in [
        '"backup_storage_connection_string"',
        '"encryption_key_reference"',
        '"target_cosmos_key"',
    ]:
        assert field_name in source

    assert 'DATA_MANAGEMENT_FRONTEND_SECRET_FIELDS' in source
    assert 'DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME = "SimpleChat"' in source
    assert 'source["target_cosmos_database_name"] = DATA_MANAGEMENT_TARGET_COSMOS_DATABASE_NAME' in source
    assert 'if source["backup_storage_authentication_type"] == "connection_string":' in source
    assert 'source["backup_storage_blob_endpoint"] = ""' in source
    assert 'source["backup_storage_connection_string"] = ""' in source
    assert 'DataManagementSettingsValidationError' in source
    assert 'validate_data_management_storage_is_dedicated(updated, application_settings=application_settings)' in source
    assert 'office_docs_storage_account_url' in source
    assert 'office_docs_storage_account_blob_endpoint' in source
    assert 'not source.get("last_settings_update_at") and not isinstance(payload, dict)' in source
    assert 'source["include_source_blobs"] = False' in source
    assert 'include_source_blobs_manageable' in source
    assert 'key_vault_secret_storage_enabled' in source
    assert 'target_ai_search_authentication_type' in source
    assert 'target_enhanced_citations_storage_authentication_type' in source
    assert 'execute_migration_job' in source
    assert '_copy_cosmos_records_to_target' in source
    assert '_copy_ai_search_to_target' in source
    assert '_copy_source_blobs_to_target' in source
    assert 'get_data_management_migration_catalog' in source
    assert 'summarize_data_management_migration_plan' in source
    assert 'test_target_cosmos_connection' in source
    assert 'test_target_search_connection' in source
    assert 'test_target_enhanced_citation_storage_connection' in source
    assert 'DATA_MANAGEMENT_REDACTED_VALUE = "***REDACTED***"' in source
    assert 'sanitize_data_management_settings_for_admin' in source
    assert 'sanitize_data_management_job_item_for_admin' in source
    assert 'get_data_management_job_detail' in source
    assert 'get_data_management_backup_summary' in source
    assert 'activity_type": "data_management"' in source
    assert 'summarize_backup_artifacts(artifacts)' in source
    assert 'sanitized[field_name] = DATA_MANAGEMENT_REDACTED_VALUE' in source
    assert 'if payload.get(secret_field) == DATA_MANAGEMENT_REDACTED_VALUE:' in source


def test_admin_javascript_uses_safe_dom_patterns():
    """Validate Data Management browser code avoids common XSS sinks."""
    source = read_text(ADMIN_JS)
    forbidden_patterns = [
        r"\.innerHTML\b",
        r"\.outerHTML\b",
        r"insertAdjacentHTML\s*\(",
        r"setAttribute\s*\(\s*['\"]on",
        r"javascript:",
        r"\bonclick\b",
        r"\bonerror\b",
        r"\bonload\b",
    ]

    for pattern in forbidden_patterns:
        assert not re.search(pattern, source), f"Unsafe browser sink found: {pattern}"

    for required_snippet in [
        'document.createElement("tr")',
        'document.createElement("td")',
        'openKeyVaultSettings',
        'buildMigrationPlan()',
        'queueMigration(false)',
        'loadMigrationCatalog(targetType)',
        'renderMigrationSummary(data.summary || {})',
        'testTargetCosmos',
        'testTargetSearch',
        'testTargetEnhancedCitationStorage',
        'Migration preview refreshed.',
        'setMigrationTargetVisibility()',
        'updateSourceBlobBackupAvailability(settings)',
        'updateKeyStorageExperience(settings)',
        'Enhanced Citations is off, so source document blob backups are unavailable.',
        'showToast(error.message || "Data Management settings could not be saved.", "danger");',
        'createStatusBadge(status)',
        'createDetailChipGroup(item.details)',
        'startJobDetailAutoRefresh()',
        'stopJobDetailAutoRefresh({ clearJob: true })',
        'contentType.toLowerCase().includes("application/json")',
        'cell.textContent = text ?? "";',
        'addEventListener("click"',
        'credentials: "same-origin"',
        'loadDataManagementJobDetail',
        'renderJobItems',
        'renderJobArtifacts',
        'data-management/backups?limit=100',
        'setStorageAuthVisibility',
        'updateConnectionStringStatus',
        'storedBackupConnectionStringAvailable = settings.backup_storage_connection_string === redactedValue;',
        'Stored connection string saved. You can test storage without re-entering it.',
        'backup_storage_blob_endpoint: backupStorageAuthenticationType === backupStorageAuthManagedIdentity ? getValue(elements.datamanagementblobendpoint) : "",',
        'backup_storage_connection_string: backupStorageAuthenticationType === backupStorageAuthConnectionString ? getValue(elements.datamanagementconnectionstring) : "",',
    ]:
        assert required_snippet in source


def test_admin_ui_exposes_data_management_without_external_assets():
    """Validate the admin UI has the tab, warning, controls, and local asset reference."""
    template = read_text(ADMIN_TEMPLATE)
    sidebar = read_text(SIDEBAR_TEMPLATE)

    for marker in [
        'id="data-management-tab"',
        'id="data-management"',
        'id="data-management" role="tabpanel" aria-labelledby="data-management-tab" data-testid="data-management-tab-pane" data-ignore-settings-change="true"',
        'id="data-management-save-settings-btn"',
        'id="data-management-save-settings-btn" disabled aria-disabled="true"',
        'id="data-management-operational-warning"',
        'id="data-management-backup-section"',
        'id="data-management-migration-section"',
        'id="data-management-backup-inventory-section"',
        'We suggest not running backups, restores, or migrations during your operational business hours.',
        '<h4 class="mb-1">Backup</h4>',
        '<h4 class="mb-1">Migration</h4>',
        '<h5 class="mb-1">Target Cosmos Database</h5>',
        'id="data_management_full_frequency"',
        'id="data_management_scheduled_time_utc" value="03:00"',
        'id="data_management_partial_enabled"',
        'id="data-management-blob-endpoint-field"',
        'id="data-management-connection-string-field"',
        'id="data-management-connection-string-status"',
        'id="data_management_target_cosmos_endpoint"',
        'id="data_management_target_cosmos_database" value="SimpleChat" readonly aria-readonly="true"',
        'id="data-management-target-cosmos-key-field"',
        'id="data-management-test-target-cosmos-btn"',
        'id="data-management-target-ai-search-section"',
        'id="data-management-test-target-search-btn"',
        'id="data-management-target-enhanced-citations-section"',
        'id="data-management-test-target-ec-storage-btn"',
        'id="data-management-migration-workflow-section"',
        'id="data-management-migration-summary"',
        'id="data-management-execute-migration-btn"',
        'id="data-management-advanced-scope-drawer"',
        'Advanced backup scope',
        'Modify them at your own risk',
        'id="data-management-include-cosmos-help"',
        'id="data-management-include-ai-search-help"',
        'id="data-management-include-source-blobs-help"',
        'id="data-management-source-blobs-lock-message"',
        'id="data-management-storage-isolation-notice"',
        'id="data-management-key-storage-alert"',
        'id="data-management-key-vault-link"',
        'id="data-management-full-backup-count"',
        'id="data-management-partial-backup-count"',
        'id="data-management-available-backup-count"',
        'id="data-management-backups-tbody"',
        'id="data-management-jobs-tbody"',
        'id="data-management-job-detail-modal"',
        'id="data-management-job-detail-refresh-state"',
        'id="data-management-job-detail-progress"',
        'id="data-management-job-items-tbody"',
        'id="data-management-job-artifacts-tbody"',
        'id="data-management-job-manifest-detail"',
        'id="data-management-job-warnings"',
        'aria-label="Backup inventory filters"',
        '<span>Available backups</span>',
        '<th scope="col">Backup</th>',
        '<th scope="col">Contents</th>',
        '<th scope="col">Storage</th>',
        '<th scope="col">Protection</th>',
        'Storage and Manifest',
        'Backup Contents',
        "static', filename='js/admin/admin_data_management.js'",
    ]:
        assert marker in template

    assert '<option value="data_management">Data Management</option>' in read_text(CONTROL_CENTER_TEMPLATE)
    assert "'data_management': 'Data Management'" in read_text(CONTROL_CENTER_JS)

    assert 'target_cosmos_database_name: targetCosmosDatabaseName' in read_text(ADMIN_JS)
    assert 'DataManagementSettingsValidationError as exc' in read_text(ROUTE_FILE)
    assert 'get_data_management_migration_catalog(target_type, search_text=search, limit=limit)' in read_text(ROUTE_FILE)
    assert 'data-management-restore-dry-run-btn' not in template
    assert 'data-management-migration-dry-run-btn' not in template
    admin_settings_js = read_text(APP_ROOT / "static" / "js" / "admin" / "admin_settings.js")
    assert "closest('[data-ignore-settings-change=\"true\"]')" in admin_settings_js
    assert "saveButton.classList.toggle('d-none', isDataManagementActive);" in admin_settings_js
    assert "window.updateAdminSettingsSaveButtonState = updateSaveButtonState;" in admin_settings_js
    assert '<span class="nav-text">Target Cosmos</span>' not in sidebar
    assert '<span class="nav-text">Migration</span>' in sidebar
    assert 'cdn.jsdelivr.net' not in read_text(ADMIN_JS)
    assert 'data-tab="data-management"' in sidebar
    assert 'data-section="data-management-backup-section"' in sidebar
    assert 'data-section="data-management-backup-inventory-section"' in sidebar
    assert 'data-section="data-management-migration-section"' in sidebar


if __name__ == "__main__":
    test_version_and_container_registration()
    test_admin_routes_require_login_admin_and_swagger_security()
    test_settings_secrets_are_redacted_for_frontend()
    test_admin_javascript_uses_safe_dom_patterns()
    test_admin_ui_exposes_data_management_without_external_assets()
    print("Data Management security pattern tests passed")