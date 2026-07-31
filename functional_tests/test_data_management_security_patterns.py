#!/usr/bin/env python3
# test_data_management_security_patterns.py
"""
Functional test for Data Management security patterns.
Version: 0.250.108
Implemented in: 0.241.211
Updated in: 0.250.102
Updated in: 0.250.103
Updated in: 0.250.104
Updated in: 0.250.105
Updated in: 0.250.106
Updated in: 0.250.108

This test ensures Data Management admin routes require authenticated admin
access, secrets stay redacted in frontend responses, and the admin browser
controller avoids XSS-prone rendering sinks. It also verifies the migration
target database name is fixed to SimpleChat and the Cosmos DB JSON editor
uses SELECT-only, paged, ETag-protected writes with Activity Log audit records.
Version 0.250.049 adds selected page-size enforcement for empty browse mode
and moves results/editing into a scrollable modal.
Version 0.250.050 verifies Cosmos editor saves do not pass unsupported
partition_key kwargs into the Python Cosmos SDK replace_item call.
Version 0.250.051 keeps version coverage aligned with the Cosmos editor
results-pane scroll refinement.
Version 0.250.076 adds bounded parallel backup checkpoints, source capacity recovery, generic
admin cancellation/retry controls, and latest-only sidecar state sanitization.
Version 0.250.103 verifies paginated migration catalogs and sanitized
server-owned review results.
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
TERRAFORM_FILE = REPO_ROOT / "deployers" / "terraform" / "main.tf"


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

    assert 'VERSION = "0.250.108"' in config_source
    assert 'cosmos_data_management_jobs_container_name = "data_management_jobs"' in config_source
    assert 'partition_key=PartitionKey(path="/id")' in config_source
    assert 'cosmos_data_management_job_items_container_name = "data_management_job_items"' in config_source
    assert 'partition_key=PartitionKey(path="/job_id")' in config_source
    assert 'cosmos_data_management_backup_item_states_container_name = "data_management_backup_item_states"' in config_source
    assert 'partition_key=PartitionKey(path="/source_scope")' in config_source
    terraform_source = read_text(TERRAFORM_FILE)
    assert re.search(r'data_management_jobs\s+= \{ partition_key_path = "/id", default_ttl = null \}', terraform_source)
    assert re.search(r'data_management_job_items\s+= \{ partition_key_path = "/job_id", default_ttl = null \}', terraform_source)
    assert re.search(r'data_management_backup_item_states\s+= \{ partition_key_path = "/source_scope", default_ttl = null \}', terraform_source)
    assert 'resource "azurerm_role_definition" "simplechat_cosmos_throughput_operator"' in terraform_source
    assert 'managed_identity_cosmos_throughput_operator' in terraform_source
    assert 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/throughputSettings/write' in terraform_source
    assert 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/throughputSettings/write' in terraform_source


def test_admin_routes_require_login_admin_and_swagger_security():
    """Validate every Data Management route has the required admin security stack."""
    routes = route_functions_with_decorators()
    assert len(routes) == 29

    for function_name, decorators in routes:
        assert "swagger_route" in decorators, f"{function_name} missing swagger_route"
        assert "login_required" in decorators, f"{function_name} missing login_required"
        assert "admin_required" in decorators, f"{function_name} missing admin_required"

    source = read_text(ROUTE_FILE)
    route_tree = ast.parse(source)
    create_job_function = next(
        node
        for node in ast.walk(route_tree)
        if isinstance(node, ast.FunctionDef) and
        node.name == "create_admin_data_management_job"
    )
    assert any(
        isinstance(node, ast.Assign) and
        any(
            isinstance(target, ast.Name) and
            target.id == "review_reservation"
            for target in node.targets
        )
        for node in create_job_function.body
    )
    assert 'from swagger_wrapper import get_auth_security, swagger_route' in source
    assert '/api/admin/data-management/settings' in source
    assert '/api/admin/data-management/jobs' in source
    assert '/api/admin/data-management/jobs/<job_id>' in source
    assert '/api/admin/data-management/backups' in source
    assert '/api/admin/data-management/migration/catalog/<target_type>' in source
    assert '/api/admin/data-management/migration/summary' in source
    assert '/api/admin/data-management/migration/review' in source
    assert '/api/admin/data-management/target/cosmos/test' in source
    assert '/api/admin/data-management/target/search/test' in source
    assert '/api/admin/data-management/target/enhanced-citation-storage/test' in source
    assert '/api/admin/data-management/cosmos-editor/containers' in source
    assert '/api/admin/data-management/cosmos-editor/danger-acknowledgement' in source
    assert '/api/admin/data-management/cosmos-editor/query' in source
    assert '/api/admin/data-management/cosmos-editor/document' in source
    assert 'save_data_management_cosmos_editor_document(' in source
    assert 'current_app._get_current_object()' in source
    assert '/api/admin/data-management/jobs/<job_id>/retry' in source
    assert '/api/admin/data-management/jobs/<job_id>/cancel' in source
    assert '/api/admin/data-management/jobs/<job_id>/migration-manifest' in source
    assert '/api/admin/data-management/jobs/<job_id>/migration-manifest/items/<item_ref>' in source
    assert '/api/admin/data-management/jobs/<job_id>/progress' in source
    assert 'retry_data_management_migration_job(job_id)' in source
    assert 'retry_data_management_backup_job(job_id)' in source
    assert 'request_data_management_job_cancellation(' in source


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
    assert 'preview_data_management_migration_plan' in source
    assert 'test_target_cosmos_connection' in source
    assert 'test_target_search_connection' in source
    assert 'test_target_enhanced_citation_storage_connection' in source
    assert 'DATA_MANAGEMENT_REDACTED_VALUE = "***REDACTED***"' in source
    assert 'sanitize_data_management_settings_for_admin' in source
    assert 'sanitize_data_management_job_item_for_admin' in source
    assert 'get_data_management_job_detail' in source
    assert 'get_data_management_backup_summary' in source
    assert 'get_data_management_jobs_page' in source
    assert 'DATA_MANAGEMENT_HISTORY_TOKEN_TTL_SECONDS = 3600' in source
    assert 'hmac.compare_digest(canonical_token, safe_token)' in source
    assert 'ORDER BY c.created_at DESC, c.id DESC' in source
    assert '"Continuation token is invalid or expired."' in source
    assert 'activity_type": "data_management"' in source
    assert 'summarize_backup_artifacts(artifacts)' in source
    assert 'sanitized[field_name] = DATA_MANAGEMENT_REDACTED_VALUE' in source
    assert 'if payload.get(secret_field) == DATA_MANAGEMENT_REDACTED_VALUE:' in source
    assert '_run_data_management_migration_preflight' in source
    assert '_apply_temporary_destination_capacity' in source
    assert '_restore_temporary_destination_capacity' in source
    assert '_preflight_target_cosmos_migration_access' in source
    assert '_preflight_target_ai_search_migration_access' in source
    assert '_preflight_target_blob_migration_access' in source
    assert '_acquire_migration_destination_lock' in source
    assert '_assert_migration_job_lease' in source
    assert '_validate_target_cosmos_container_partition_key' in source
    assert 'recover_data_management_migration_jobs' in source
    assert 'DataManagementMigrationCanceledError' in source
    assert 'contains an unowned record that conflicts' in source
    assert 'contains an unowned document that conflicts' in source
    assert 'Destination blob exists without successful migration provenance' in source
    assert 'create_migration_provenance_context' in source
    assert 'add_cosmos_migration_provenance' in source
    assert 'add_search_migration_provenance' in source
    assert 'merge_blob_migration_metadata' in source
    assert 'migration_max_parallel_operations' in source
    assert 'backup_max_parallel_operations' in source
    assert 'backup_temporary_source_ru_enabled' in source
    assert 'backup_capacity_failure_policy' in source
    assert '_execute_parallel_backup_cosmos_resource' in source
    assert '_apply_temporary_backup_source_capacity' in source
    assert '_restore_temporary_backup_source_capacity' in source
    assert '_sanitize_data_management_backup_state_for_admin' in source
    assert '"source_capacity": public_source_capacity' in source
    assert 'migration_temporary_destination_ru_enabled' in source
    assert 'DATA_MANAGEMENT_MIGRATION_MAX_DESTINATION_RU = 10000' in source
    assert 'DATA_MANAGEMENT_MIGRATION_MODE_DELTA_UPSERT = "delta_upsert"' in source
    assert 'DATA_MANAGEMENT_MIGRATION_MODE_MIRROR = "mirror_with_deletions"' in source
    assert 'DATA_MANAGEMENT_MIRROR_CONFIRMATION = "MAKE DESTINATION MATCH SOURCE"' in source
    assert 'DATA_MANAGEMENT_SEARCH_WRITE_FREEZE_CONFIRMATION_ERROR' in source
    assert '_validate_target_ai_search_migration_write_safety' in source
    assert '_get_target_data_management_search_write_gate_container' in source
    assert 'acquire_data_management_search_write_fence' in source
    assert 'renew_data_management_search_write_fence' in source
    assert 'release_data_management_search_write_fence' in source
    assert 'acquire_data_management_target_migration_coordinator' in source
    assert 'renew_data_management_target_migration_coordinator' in source
    assert 'release_data_management_target_migration_coordinator' in source
    assert '_acquire_target_migration_coordinator' in source
    assert '_iter_search_document_pages' in source
    assert 'order_by=["id asc"]' not in source
    assert '"order_by": ["id asc"]' in source
    assert '_run_data_management_migration_reconciliation' in source
    assert 'preview_actual_divergence' in source
    assert 'DATA_MANAGEMENT_BACKUP_LATEST_ITEM_STATE_TYPE' in source
    assert 'DATA_MANAGEMENT_BACKUP_LOCK_TYPE' in source
    assert 'DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_TYPE' in source
    assert '_acquire_backup_source_lock' in source
    assert '_assert_backup_job_lease' in source
    assert '_run_backup_transfer_with_heartbeat' in source
    assert '_build_backup_lineage_id' in source
    assert '_resolve_backup_encryption_reference' in source
    assert '_sanitize_data_management_job_item_details' in source
    assert 'recover_data_management_jobs' in source
    assert '_sanitize_data_management_backup_state_for_admin' in source
    assert 'source_mutation": "none"' in source
    assert 'deletion_policy": "none"' in source
    assert 'sig=' in source


def test_cosmos_editor_backend_safety_contract():
    """Validate the Cosmos DB JSON editor backend uses read paging, guarded saves, and audit logs."""
    source = read_text(FUNCTIONS_FILE)
    route_source = read_text(ROUTE_FILE)

    for marker in [
        'DATA_MANAGEMENT_COSMOS_EDITOR_EMPTY_QUERY = "SELECT * FROM c"',
        'DATA_MANAGEMENT_COSMOS_EDITOR_EMPTY_QUERY_LIMIT = 100',
        'DATA_MANAGEMENT_COSMOS_EDITOR_MAX_PAGE_SIZE = 100',
        'DATA_MANAGEMENT_COSMOS_EDITOR_CONFIRMATION_PHRASE = "I understand this can damage system data"',
        'DATA_MANAGEMENT_COSMOS_EDITOR_CONTAINER_DEFINITIONS',
        'def get_data_management_cosmos_editor_containers',
        'def query_data_management_cosmos_editor_documents',
        'def get_data_management_cosmos_editor_document',
        'def save_data_management_cosmos_editor_document',
        'def log_data_management_cosmos_editor_activity',
        'if not re.match(r"^\\s*SELECT\\b", query, re.IGNORECASE):',
        'safe_page_size = _safe_int(',
        'safe_continuation_token = None if is_empty_query else _safe_text(continuation_token) or None',
        'page_iterator = query_iterable.by_page(continuation_token=safe_continuation_token)',
        '"empty_query_limit_applied": is_empty_query',
        '"selectable": document_id is not None and partition_key_value is not None',
        'Document id cannot be changed in the Cosmos DB editor.',
        'Document partition key value cannot be changed in the Cosmos DB editor.',
        'replace_target = safe_document_id',
        'if isinstance(original_document, dict) and original_document.get("_self"):',
        'replace_target = original_document',
        'item=replace_target,',
        'match_condition=MatchConditions.IfNotModified',
        '"cosmos_editor_document_saved"',
        '"changed_paths": change_summary["changed_paths"]',
        '"activity_type": "data_management"',
    ]:
        assert marker in source
    replace_call = re.search(
        r"saved_document = container\.replace_item\((?P<args>.*?)\n    \)",
        source,
        flags=re.DOTALL,
    )
    assert replace_call
    assert "partition_key=" not in replace_call.group("args")

    for marker in [
        'cosmos_editor_danger_acknowledged',
        'cosmos_editor_query_rejected',
        'cosmos_editor_save_rejected',
        'Cosmos DB document changed after it was opened. Refresh before saving again.',
    ]:
        assert marker in route_source


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
        'loadMigrationCatalog(targetType, "reset")',
        'renderMigrationSummary(review.summary || {}, review.preview || null)',
        'testTargetCosmos',
        'testMigrationAccess',
        'testTargetSearch',
        'testTargetEnhancedCitationStorage',
        'Migration preflight review is ready for confirmation.',
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
        'buildHistoryListUrl(listKind, filters)',
        'new AbortController()',
        'requestGeneration !== state.requestGeneration',
        'setStorageAuthVisibility',
        'updateConnectionStringStatus',
        'storedBackupConnectionStringAvailable = settings.backup_storage_connection_string === redactedValue;',
        'Stored connection string saved. You can test storage without re-entering it.',
        'backup_storage_blob_endpoint: backupStorageAuthenticationType === backupStorageAuthManagedIdentity ? getValue(elements.datamanagementblobendpoint) : "",',
        'backup_storage_connection_string: backupStorageAuthenticationType === backupStorageAuthConnectionString ? getValue(elements.datamanagementconnectionstring) : "",',
        'loadCosmosEditorContainers',
        'queryCosmosEditorDocuments(false)',
        'cosmosEditorContinuationToken',
        'showCosmosEditorResultsModal',
        'dataManagementCosmosEditorResultsModal',
        'openCosmosEditorSaveModal',
        'saveCosmosEditorDocument',
        'confirmation_phrase: cosmosEditorConfirmationPhrase',
        'closest("[data-ignore-data-management-change',
            'retryDataManagementJob',
        'getMigrationLiveMetrics',
        'getBackupLiveMetrics',
        'updateBackupCapacityVisibility',
        'backup_max_parallel_operations',
        'backup_blob_max_parallel_operations',
        'backup_blob_chunk_size_mib',
        'backup_blob_retry_count',
        'backup_temporary_source_ru_enabled',
        'updateMigrationCapacityVisibility',
        'updateMigrationModeVisibility',
        'updateMigrationSearchWriteFreezeVisibility',
        'createMigrationPreviewOutcomes',
        'migrationMirrorConfirmationPhrase',
        'target_ai_search_writes_frozen',
        'Collisions',
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
        'id="data-management-migration-title"',
        'id="data-management-target-cosmos-heading"',
        'id="data_management_full_frequency"',
        'id="data_management_scheduled_time_utc" value="03:00"',
        'id="data_management_partial_enabled"',
        'id="data-management-blob-endpoint-field"',
        'id="data-management-connection-string-field"',
        'id="data-management-connection-string-status"',
        'id="data_management_target_cosmos_endpoint"',
        'id="data_management_target_cosmos_database" value="SimpleChat" readonly aria-readonly="true"',
        'id="data-management-target-cosmos-key-field"',
        'id="data_management_target_cosmos_subscription_id"',
        'id="data_management_target_cosmos_resource_group"',
        'id="data-management-migration-mode-section"',
        'id="data_management_migration_mode_new_only"',
        'id="data_management_migration_mode_delta_upsert"',
        'id="data_management_migration_mode_mirror_with_deletions"',
        'id="data_management_migration_baseline_job_id"',
        'id="data_management_migration_mirror_confirmation_phrase"',
        'id="data-management-migration-search-write-freeze"',
        'id="data_management_migration_target_search_writes_frozen"',
        'I confirm external destination AI Search writers are frozen',
        'id="data-management-test-target-cosmos-btn"',
        'id="data-management-target-ai-search-section"',
        'id="data-management-test-target-search-btn"',
        'id="data-management-target-enhanced-citations-section"',
        'id="data-management-test-target-ec-storage-btn"',
        'id="data-management-migration-workflow-section"',
        'id="data-management-test-migration-access-btn"',
        'Validate Cosmos Access',
        'id="data_management_migration_max_parallel_operations"',
        'id="data_management_backup_max_parallel_operations"',
        'id="data_management_backup_retry_count"',
        'id="data_management_backup_blob_max_parallel_operations"',
        'id="data_management_backup_blob_chunk_size_mib"',
        'id="data_management_backup_blob_retry_count"',
        'id="data_management_backup_capacity_failure_policy"',
        'id="data_management_backup_temporary_source_ru_enabled"',
        'id="data_management_backup_temporary_source_ru"',
        'id="data-management-backup-temporary-ru-field"',
        'id="data_management_migration_retry_count"',
        'id="data_management_migration_skip_recent_within_hours"',
        'id="data_management_migration_temporary_destination_ru_enabled"',
        'id="data_management_migration_temporary_destination_ru"',
        'max="10000"',
        'id="data-management-migration-summary"',
        'id="data-management-execute-migration-btn"',
        'id="data-management-cosmos-editor-section"',
        'id="data-management-cosmos-editor-open-danger-btn"',
        'id="data-management-cosmos-editor-locked-message"',
        'id="data-management-cosmos-editor-workspace"',
        'id="data_management_cosmos_editor_container"',
        'id="data_management_cosmos_editor_query"',
        'id="data-management-cosmos-editor-run-query-btn"',
        'id="data-management-cosmos-editor-results-modal"',
        'id="data-management-cosmos-editor-modal-status"',
        'id="data-management-cosmos-editor-next-page-btn"',
        'id="data_management_cosmos_editor_document_json"',
        'id="data-management-cosmos-editor-danger-modal"',
        'id="data_management_cosmos_editor_danger_accept"',
        'id="data-management-cosmos-editor-save-modal"',
        'id="data_management_cosmos_editor_confirmation_phrase"',
        'Cosmos DB JSON Editor',
        'I understand this editor can damage overall system health.',
        'I understand this can damage system data',
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
        'id="data_management_backup_status_filter"',
        'id="data-management-backup-previous-page-btn"',
        'id="data-management-backup-next-page-btn"',
        'id="data_management_job_operation_filter"',
        'id="data-management-job-previous-page-btn"',
        'id="data-management-job-next-page-btn"',
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
    assert 'state.abortController?.abort();' in read_text(ADMIN_JS)
    assert 'requestGeneration !== state.requestGeneration' in read_text(ADMIN_JS)
    assert 'params.set("continuation_token", state.currentToken);' in read_text(ADMIN_JS)
    assert 'DataManagementSettingsValidationError as exc' in read_text(ROUTE_FILE)
    route_source = read_text(ROUTE_FILE)
    assert 'continuation_token=continuation_token' in route_source
    assert '@bp.route("/api/admin/data-management/migration/review", methods=["POST"])' in route_source
    assert '@bp.route("/api/admin/data-management/target/cosmos/ru-boost/test", methods=["POST"])' in route_source
    assert '@bp.route("/api/admin/data-management/restore/review", methods=["POST"])' in route_source
    assert 'review_data_management_migration(' in route_source
    assert 'review_data_management_restore(' in route_source
    assert '"workflow_step": "review"' in route_source
    assert 'hmac.compare_digest(' in route_source
    assert 'get_data_management_migration_review_fingerprint(' in route_source
    assert 'create_data_management_migration_review_authorization(' in route_source
    assert 'reserve_data_management_migration_review_authorization(' in route_source
    assert 'release_data_management_migration_review_reservation' in route_source
    assert 'except DataManagementHistoryPaginationError:' in route_source
    assert 'DATA_MANAGEMENT_HISTORY_VALIDATION_ERROR' in route_source
    assert 'except DataManagementHistoryPaginationError as exc:' not in route_source
    assert 'data-management-restore-dry-run-btn' not in template
    assert 'id="data-management-restore-modal"' in template
    assert 'id="data-management-test-target-cosmos-ru-boost-btn"' in template
    assert 'MAKE DESTINATION MATCH SOURCE' in template
    assert 'data-management-migration-dry-run-btn' not in template
    admin_settings_js = read_text(APP_ROOT / "static" / "js" / "admin" / "admin_settings.js")
    assert "closest('[data-ignore-settings-change=\"true\"]')" in admin_settings_js
    assert "saveButton.classList.toggle('d-none', isDataManagementActive);" in admin_settings_js
    assert "window.updateAdminSettingsSaveButtonState = updateSaveButtonState;" in admin_settings_js
    assert '<span class="nav-text">Target Cosmos</span>' not in sidebar
    assert '<span class="nav-text">Migration</span>' in sidebar
    assert '<span class="nav-text">Backup, Migrate &amp; Restore</span>' in sidebar
    assert 'cdn.jsdelivr.net' not in read_text(ADMIN_JS)
    assert 'data-tab="data-management"' in sidebar
    assert 'data-section="data-management-readiness-section"' in sidebar
    assert 'data-section="data-management-backup-section"' in sidebar
    assert 'data-section="data-management-cosmos-editor-section"' in sidebar
    assert 'data-section="data-management-backup-inventory-section"' in sidebar
    assert 'data-section="data-management-migration-section"' in sidebar


if __name__ == "__main__":
    test_version_and_container_registration()
    test_admin_routes_require_login_admin_and_swagger_security()
    test_settings_secrets_are_redacted_for_frontend()
    test_cosmos_editor_backend_safety_contract()
    test_admin_javascript_uses_safe_dom_patterns()
    test_admin_ui_exposes_data_management_without_external_assets()
    print("Data Management security pattern tests passed")