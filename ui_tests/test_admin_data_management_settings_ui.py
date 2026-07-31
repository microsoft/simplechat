# test_admin_data_management_settings_ui.py
"""
UI test for Admin Settings Data Management controls.
Version: 0.250.106
Implemented in: 0.241.211
Updated in: 0.241.221
Updated in: 0.250.102
Updated in: 0.250.103
Updated in: 0.250.104
Updated in: 0.250.105
Updated in: 0.250.106

This test ensures admins can discover the Data Management tab, see the
operational-business-hours warning, and access the backup, encryption,
migration, Cosmos DB JSON editor, backup inventory, and job-history controls without unsafe frontend rendering.
Version 0.250.049 moves query results and document editing into a scrollable modal.
Version 0.250.050 keeps this coverage aligned with the Cosmos editor save-path fix.
Version 0.250.051 verifies the Cosmos editor results list scrolls independently.
Version 0.250.071 adds resilient migration provenance, incremental modes, cutover
reconciliation, and the external target Search writer freeze acknowledgement.
Version 0.250.076 adds bounded parallel backup and source capacity controls.
Version 0.250.102 adds independently bounded source-blob transfer controls.
Version 0.250.103 adds the staged migration workflow, scalable catalogs,
server-owned review, confirmation gating, and inline durable job progress.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
ADMIN_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_data_management.js"
STYLES_CSS = REPO_ROOT / "application" / "single_app" / "static" / "css" / "styles.css"
BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE") or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def test_admin_data_management_controls_render_from_template():
    """Validate the Data Management controls are present in the admin template."""
    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    js_source = ADMIN_JS.read_text(encoding="utf-8")
    css_source = STYLES_CSS.read_text(encoding="utf-8")

    required_ids = [
        "data-management-tab",
        "data-management",
        "data-management-save-settings-btn",
        "data-management-operational-warning",
        "data-management-backup-section",
        "data-management-schedule-section",
        "data_management_enabled",
        "data_management_full_frequency",
        "data_management_scheduled_time_utc",
        "data_management_partial_enabled",
        "data_management_low_impact_mode",
        "data-management-advanced-scope-drawer",
        "data-management-include-cosmos-help",
        "data-management-include-ai-search-help",
        "data-management-include-source-blobs-help",
        "data-management-source-blobs-lock-message",
        "data_management_storage_auth",
        "data-management-blob-endpoint-field",
        "data_management_blob_endpoint",
        "data_management_container_name",
        "data-management-connection-string-field",
        "data-management-storage-isolation-notice",
        "data-management-generate-key-btn",
        "data_management_encryption_enabled",
        "data-management-key-storage-alert",
        "data-management-key-vault-link",
        "data-management-backup-performance-section",
        "data_management_backup_max_parallel_operations",
        "data_management_backup_retry_count",
        "data-management-blob-backup-performance-section",
        "data_management_backup_blob_max_parallel_operations",
        "data_management_backup_blob_chunk_size_mib",
        "data_management_backup_blob_retry_count",
        "data_management_backup_capacity_failure_policy",
        "data_management_backup_temporary_source_ru_enabled",
        "data-management-backup-temporary-ru-field",
        "data_management_backup_temporary_source_ru",
        "data-management-migration-section",
        "data-management-target-cosmos-section",
        "data_management_target_cosmos_auth",
        "data_management_target_cosmos_endpoint",
        "data_management_target_cosmos_database",
        "data-management-target-cosmos-key-field",
        "data_management_target_cosmos_subscription_id",
        "data_management_target_cosmos_resource_group",
        "data-management-test-target-cosmos-btn",
        "data-management-target-ai-search-section",
        "data_management_target_ai_search_auth",
        "data_management_target_ai_search_endpoint",
        "data-management-target-ai-search-key-field",
        "data_management_target_ai_search_key",
        "data-management-test-target-search-btn",
        "data-management-target-enhanced-citations-section",
        "data_management_target_ec_storage_auth",
        "data-management-target-ec-blob-endpoint-field",
        "data_management_target_ec_blob_endpoint",
        "data-management-target-ec-connection-string-field",
        "data_management_target_ec_connection_string",
        "data-management-test-target-ec-storage-btn",
        "data-management-migration-workflow-section",
        "data-management-migration-readiness",
        "data-management-migration-step-error",
        "data-management-migration-scope-total",
        "data-management-migration-review-empty",
        "data-management-migration-review-checks",
        "data-management-migration-confirm-summary",
        "data_management_migration_final_confirmation",
        "data-management-migration-start-new-btn",
        "data-management-migration-view-job-btn",
        "data-management-migration-workflow-progress",
        "data-management-migration-workflow-progress-summary",
        "data-management-migration-workflow-progress-state",
        "data-management-migration-workflow-progress-actions",
        "data-management-migration-back-btn",
        "data-management-migration-next-btn",
        "data-management-migration-step-position",
        "data-management-test-migration-access-btn",
        "data-management-migration-mode-section",
        "data_management_migration_mode_new_only",
        "data_management_migration_mode_delta_upsert",
        "data_management_migration_mode_mirror_with_deletions",
        "data-management-migration-mode-description",
        "data-management-migration-baseline-field",
        "data_management_migration_baseline_job_id",
        "data-management-migration-mirror-confirmation",
        "data_management_migration_mirror_confirmation_phrase",
        "data-management-migration-search-write-freeze",
        "data_management_migration_target_search_writes_frozen",
        "data_management_migration_max_parallel_operations",
        "data_management_migration_retry_count",
        "data_management_migration_skip_recent_within_hours",
        "data_management_migration_temporary_destination_ru_enabled",
        "data-management-migration-temporary-ru-field",
        "data_management_migration_temporary_destination_ru",
        "data_management_migration_users_mode",
        "data-management-migration-users-available",
        "data-management-migration-users-selected",
        "data_management_migration_groups_mode",
        "data-management-migration-groups-available",
        "data-management-migration-groups-selected",
        "data_management_migration_public_workspaces_mode",
        "data-management-migration-public-workspaces-available",
        "data-management-migration-public-workspaces-selected",
        "data-management-migration-summary",
        "data-management-migration-preview-btn",
        "data-management-execute-migration-btn",
        "data-management-cosmos-editor-section",
        "data-management-cosmos-editor-open-danger-btn",
        "data-management-cosmos-editor-locked-message",
        "data-management-cosmos-editor-workspace",
        "data_management_cosmos_editor_container",
        "data-management-cosmos-editor-container-help",
        "data_management_cosmos_editor_page_size",
        "data_management_cosmos_editor_query",
        "data-management-cosmos-editor-run-query-btn",
        "data-management-cosmos-editor-results-modal",
        "data-management-cosmos-editor-modal-title",
        "data-management-cosmos-editor-modal-subtitle",
        "data-management-cosmos-editor-modal-status",
        "data-management-cosmos-editor-next-page-btn",
        "data-management-cosmos-editor-refresh-document-btn",
        "data-management-cosmos-editor-results-list",
        "data-management-cosmos-editor-document-meta",
        "data-management-cosmos-editor-save-btn",
        "data_management_cosmos_editor_document_json",
        "data-management-cosmos-editor-danger-modal",
        "data_management_cosmos_editor_danger_accept",
        "data-management-cosmos-editor-accept-danger-btn",
        "data-management-cosmos-editor-save-modal",
        "data-management-cosmos-editor-save-summary",
        "data_management_cosmos_editor_confirmation_phrase",
        "data-management-cosmos-editor-confirm-save-btn",
        "data-management-backup-operations-section",
        "data-management-run-full-backup-btn",
        "data-management-run-partial-backup-btn",
        "data-management-backup-inventory-section",
        "data-management-full-backup-count",
        "data-management-partial-backup-count",
        "data-management-available-backup-count",
        "data-management-backups-tbody",
        "data_management_backup_status_filter",
        "data_management_backup_scheduled_filter",
        "data_management_backup_created_from",
        "data_management_backup_created_to",
        "data_management_backup_page_size",
        "data-management-backup-pagination-status",
        "data-management-backup-previous-page-btn",
        "data-management-backup-next-page-btn",
        "data-management-restore-modal",
        "data-management-restore-title",
        "data-management-restore-backup-summary",
        "data_management_restore_policy",
        "data_management_restore_include_cosmos",
        "data_management_restore_include_ai_search",
        "data_management_restore_include_source_blobs",
        "data-management-restore-confirmation-section",
        "data_management_restore_overwrite_confirmation_phrase",
        "data-management-restore-review-btn",
        "data-management-restore-review-status",
        "data-management-restore-review-checks",
        "data_management_restore_final_confirmation",
        "data-management-restore-queue-btn",
        "data-management-jobs-tbody",
        "data_management_job_operation_filter",
        "data_management_job_status_filter",
        "data_management_job_scheduled_filter",
        "data_management_job_created_from",
        "data_management_job_created_to",
        "data_management_job_page_size",
        "data-management-job-pagination-status",
        "data-management-job-previous-page-btn",
        "data-management-job-next-page-btn",
        "data-management-job-detail-modal",
        "data-management-job-detail-refresh-state",
        "data-management-job-detail-progress",
        "data-management-job-detail-actions",
        "data-management-job-items-tbody",
        "data-management-job-artifacts-tbody",
        "data-management-job-manifest-detail",
        "data-management-job-warnings",
        "data-management-migration-cancel-modal",
        "data-management-migration-cancel-message",
        "data-management-confirm-migration-cancel-btn",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert "We suggest not running backups, restores, or migrations during your operational business hours." in template
    assert 'id="data-management" role="tabpanel" aria-labelledby="data-management-tab" data-testid="data-management-tab-pane" data-ignore-settings-change="true"' in template
    assert 'id="data-management-save-settings-btn" disabled aria-disabled="true"' in template
    assert '<h4 class="mb-1">Backup</h4>' in template
    assert 'id="data-management-migration-title"' in template
    assert "Cosmos DB JSON Editor" in template
    assert "Query results and the JSON editor open in a modal" in template
    assert "modal-xl modal-dialog-scrollable" in template
    assert "cosmos-editor-results-modal-body" in template
    assert "cosmos-editor-results-list" in template
    assert 'style="max-height: 62vh;"' not in template
    assert "#data-management-cosmos-editor-results-modal .cosmos-editor-results-modal-body" in css_source
    assert "#data-management-cosmos-editor-results-modal .cosmos-editor-results-list" in css_source
    assert "max-height: calc(100vh - 18rem);" in css_source
    assert "overflow-y: auto;" in css_source
    assert "I understand this editor can damage overall system health." in template
    assert "Required phrase: <code>I understand this can damage system data</code>" in template
    assert '<h4 class="mb-1">Backup Inventory</h4>' in template
    assert "Restore Backup" in template
    assert "Run Restore Review" in template
    assert "Queue Restore Job" in template
    assert "Required phrase: <code>RESTORE WITH OVERWRITE</code>" in template
    assert "openRestoreModal" in js_source
    assert 'requestJson("/api/admin/data-management/restore/review"' in js_source
    assert 'queueOperation("restore"' in js_source
    assert 'aria-label="Backup inventory filters"' in template
    assert '<span>Available backups</span>' in template
    assert '<th scope="col">Backup</th>' in template
    assert '<th scope="col">Contents</th>' in template
    assert '<th scope="col">Protection</th>' in template
    assert 'Backup Contents' in template
    assert 'Storage and Manifest' in template
    assert 'id="data-management-target-cosmos-heading"' in template
    assert 'id="data-management-target-search-heading"' in template
    assert 'id="data-management-target-storage-heading"' in template
    assert 'aria-label="Migration workflow"' in template
    assert "Move SimpleChat data through a reviewed, recoverable environment transfer." in template
    assert "Full backups run on the selected cadence; partial backups run daily only." in template
    assert "Advanced backup scope" in template
    assert "Modify them at your own risk" in template
    assert "Use a dedicated backup storage account" in template
    assert "Open Key Vault settings" in template
    assert "Cosmos Backup Performance" in template
    assert "Temporary source max RU/s" in template
    assert "continue_without_boost" in template
    assert "Managed identity requires Cosmos DB Data Contributor" in template
    assert "Paste a connection string to save or replace it" in template
    assert 'id="data-management-connection-string-status"' in template
    assert 'id="data_management_target_cosmos_database" value="SimpleChat" readonly aria-readonly="true"' in template
    assert 'max="10000"' in template
    assert 'Validate Cosmos Access' in template
    assert 'role="radiogroup" aria-label="Migration synchronization mode"' in template
    assert "MIRROR WITH DELETIONS" in template
    assert "I confirm external destination AI Search writers are frozen" in template
    assert 'data-migration-step-button="target"' in template
    assert 'data-migration-step-button="scope"' in template
    assert 'data-migration-step-button="options"' in template
    assert 'data-migration-step-button="review"' in template
    assert 'data-migration-step-button="confirm"' in template
    assert 'data-migration-step-button="progress"' in template
    assert 'data-migration-mode-option="users"' in template
    assert 'data-migration-page-next="users"' in template
    assert 'data-migration-page-previous="users"' in template
    assert 'data-migration-all-count="users"' in template
    assert ".migration-stepper" in css_source
    assert ".migration-catalog-workspace" in css_source
    assert ".migration-review-check" in css_source
    assert "@media (max-width: 767.98px)" in css_source
    assert 'setStorageAuthVisibility' in js_source
    assert 'updateConnectionStringStatus' in js_source
    assert 'updateSourceBlobBackupAvailability' in js_source
    assert 'updateKeyStorageExperience' in js_source
    assert 'openKeyVaultSettings' in js_source
    assert 'setMigrationTargetVisibility' in js_source
    assert 'updateBackupCapacityVisibility' in js_source
    assert 'getBackupLiveMetrics' in js_source
    assert 'Skipped / failed' in js_source
    assert 'label: "Elapsed"' in js_source
    assert 'backup_max_parallel_operations' in js_source
    assert 'backup_blob_max_parallel_operations' in js_source
    assert 'backup_blob_chunk_size_mib' in js_source
    assert 'backup_blob_retry_count' in js_source
    assert 'backup_temporary_source_ru_enabled' in js_source
    assert 'buildMigrationPlan' in js_source
    assert 'queueMigration(false)' in js_source
    assert 'loadMigrationCatalog(targetType, "reset")' in js_source
    assert 'migrationCatalogStates' in js_source
    assert 'requestGeneration' in js_source
    assert 'continuation_token=' in js_source
    assert 'runMigrationReview' in js_source
    assert '/api/admin/data-management/migration/review' in js_source
    assert 'reviewStale' in js_source
    assert 'reviewRequestGeneration' in js_source
    assert 'submissionInFlight' in js_source
    assert 'submissionAccepted' in js_source
    assert 'resetMigrationWorkflowForNewRun' in js_source
    assert 'attachMigrationWorkflowJob' in js_source
    assert 'refreshMigrationWorkflowProgress' in js_source
    assert 'loadCosmosEditorContainers' in js_source
    assert 'queryCosmosEditorDocuments(false)' in js_source
    assert 'cosmosEditorContinuationToken' in js_source
    assert 'showCosmosEditorResultsModal' in js_source
    assert 'setCosmosEditorQueryStatus' in js_source
    assert 'openCosmosEditorSaveModal' in js_source
    assert 'confirmation_phrase: cosmosEditorConfirmationPhrase' in js_source
    assert 'The edit was recorded in Activity Logs.' in js_source
    assert 'closest("[data-ignore-data-management-change' in js_source
    assert 'testTargetCosmos' in js_source
    assert 'testMigrationAccess' in js_source
    assert 'retryDataManagementJob' in js_source
    assert 'openDataManagementCancellationModal' in js_source
    assert 'requestDataManagementCancellation' in js_source
    assert 'getMigrationLiveMetrics' in js_source
    assert 'jobDetailRefreshIntervalMs = 2000' in js_source
    assert '/progress`' in js_source
    assert 'Observed transferred' in js_source
    assert 'Running - alive, no recent progress' in js_source
    assert 'updateMigrationCapacityVisibility' in js_source
    assert 'updateMigrationModeVisibility' in js_source
    assert 'updateMigrationSearchWriteFreezeVisibility' in js_source
    assert 'target_ai_search_writes_frozen' in js_source
    assert 'createMigrationPreviewOutcomes' in js_source
    assert 'settings: collectSettings()' in js_source
    assert 'review_fingerprint: migrationWorkflowState.review?.review_fingerprint' in js_source
    assert 'review_authorization_token: migrationWorkflowState.review?.authorization_token' in js_source
    assert 'Stage ${formatNumber(displayedStage)} of ${formatNumber(totalSteps)}' in js_source
    assert 'Active stage' in js_source
    assert 'Migration stage is active; measured throughput is shown below.' in js_source
    assert 'cancellation requested. The worker will stop at its next durable checkpoint.' in js_source
    assert 'Retry failures' in js_source
    assert 'testTargetSearch' in js_source
    assert 'testTargetEnhancedCitationStorage' in js_source
    assert 'Migration preflight review is ready for confirmation.' in js_source
    assert 'Enhanced Citations is off, so source document blob backups are unavailable.' in js_source
    assert 'Stored connection string saved. You can test storage without re-entering it.' in js_source
    assert 'target_cosmos_database_name: targetCosmosDatabaseName' in js_source
    assert 'loadDataManagementBackups' in js_source
    assert 'loadDataManagementJobDetail' in js_source
    assert 'renderJobArtifacts' in js_source
    assert 'renderJobDetailActions' in js_source
    assert 'createMigrationManifestDownloadLink' in js_source
    assert 'createDetailChipGroup' in js_source
    assert 'startJobDetailAutoRefresh' in js_source
    assert 'Live updates on -' in js_source
    assert 'View Log' in js_source
    assert "admin_data_management.js') }}?v={{ config['VERSION'] }}" in template
    assert "innerHTML" not in js_source
    assert "insertAdjacentHTML" not in js_source
    assert "data-management-restore-dry-run-btn" not in template
    assert "data-management-migration-dry-run-btn" not in template


def _run_admin_migration_browser_workflow(viewport):
    """Exercise the staged workflow with deterministic API responses."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid admin Playwright storage state file.")
    if expect is None or sync_playwright is None:
        pytest.skip("Install playwright to run this UI test.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport=viewport)
    page = context.new_page()
    job_submissions = []

    def fulfill_json(route, payload, status=200):
        route.fulfill(
            status=status,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def handle_data_management_api(route):
        request = route.request
        url = request.url
        if "/migration/catalog/users" in url:
            is_second_page = "continuation_token=next-page" in url
            fulfill_json(route, {
                "success": True,
                "type": "users",
                "items": [{
                    "id": "user-002" if is_second_page else "user-001",
                    "label": "Second User" if is_second_page else "Admin User",
                    "description": (
                        "second@example.com"
                        if is_second_page
                        else "admin@example.com"
                    ),
                    "document_count": 4 if is_second_page else 7,
                }],
                "total_count": 51,
                "page_size": 25,
                "has_more": not is_second_page,
                "continuation_token": "" if is_second_page else "next-page",
            })
            return
        if "/migration/catalog/" in url:
            fulfill_json(route, {
                "success": True,
                "items": [],
                "total_count": 0,
                "page_size": 1,
                "has_more": False,
                "continuation_token": "",
            })
            return
        if url.endswith("/api/admin/data-management/migration/review"):
            fulfill_json(route, {
                "success": True,
                "review": {
                    "ready": True,
                    "blocker_count": 0,
                    "warning_count": 1,
                    "review_fingerprint": "review-fingerprint",
                    "authorization_token": "review-authorization-token",
                    "authorization_expires_at": "2026-07-30T12:15:00+00:00",
                    "summary": {
                        "users": {
                            "mode": "all",
                            "count": 51,
                            "document_count": 357,
                            "include_documents": True,
                        },
                        "groups": {
                            "mode": "none",
                            "count": 0,
                            "document_count": 0,
                            "include_documents": False,
                        },
                        "public_workspaces": {
                            "mode": "none",
                            "count": 0,
                            "document_count": 0,
                            "include_documents": False,
                        },
                        "include_ai_search": False,
                        "include_source_blobs": False,
                        "migration_mode": "new_only",
                    },
                    "preview": {
                        "captured_at": "2026-07-30T12:00:00+00:00",
                        "estimated_outcomes": {
                            "create_count": 408,
                            "update_count": 0,
                            "unchanged_count": 0,
                            "delete_count": 0,
                            "not_applicable_count": 0,
                            "missing_count": 0,
                            "conflict_count": 0,
                        },
                    },
                    "checks": [
                        {
                            "id": "scope",
                            "label": "Migration scope",
                            "workflow_step": "scope",
                            "status": "pass",
                            "summary": "51 principal scopes are included.",
                        },
                        {
                            "id": "source_blob_access",
                            "label": "Enhanced Citation source blob readiness",
                            "workflow_step": "options",
                            "status": "warning",
                            "summary": "Enhanced Citation source blobs are excluded.",
                        },
                    ],
                },
            })
            return
        if (
            url.endswith("/api/admin/data-management/settings") and
            request.method == "PUT"
        ):
            settings = request.post_data_json or {}
            settings.update({
                "enhanced_citations_enabled": True,
                "key_vault_secret_storage_enabled": False,
                "key_vault_name_configured": False,
                "encryption_key_storage": "not_configured",
            })
            fulfill_json(route, {"success": True, "settings": settings})
            return
        if (
            url.endswith("/api/admin/data-management/jobs") and
            request.method == "POST"
        ):
            job_submissions.append(request.post_data_json)
            fulfill_json(route, {
                "success": True,
                "job": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "operation": "migration",
                    "status": "queued",
                    "created_at": "2026-07-30T12:00:00+00:00",
                    "progress": {
                        "completed_steps": 0,
                        "total_steps": 10,
                        "percent_complete": 0,
                        "current_step": "plan",
                    },
                    "can_cancel": True,
                    "can_retry": False,
                },
            }, status=202)
            return
        if url.endswith("/progress"):
            fulfill_json(route, {
                "success": True,
                "job": {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "operation": "migration",
                    "status": "running",
                    "progress": {
                        "completed_steps": 2,
                        "total_steps": 10,
                        "percent_complete": 20,
                        "current_step": "preflight",
                    },
                    "can_cancel": True,
                    "can_retry": False,
                },
            })
            return
        route.fallback()

    page.route("**/api/admin/data-management/**", handle_data_management_api)

    try:
        response = page.goto(f"{BASE_URL}/admin/settings#data-management", wait_until="networkidle")
        if response and response.status >= 400:
            pytest.skip("Admin settings are not accessible with the configured storage state.")
        if page.locator("#data-management-tab").count() == 0:
            pytest.skip("Admin settings are not accessible with the configured storage state.")

        page.locator("#data-management-tab").click()
        expect(page.locator("#data-management")).to_be_visible()
        expect(page.locator("#data-management-backup-section")).to_be_visible()
        expect(page.locator("#data-management-migration-section")).to_be_visible()
        expect(page.locator("#data-management-backup-inventory-section")).to_be_visible()
        expect(page.locator("#data-management-operational-warning")).to_contain_text(
            "We suggest not running backups, restores, or migrations during your operational business hours."
        )
        expect(page.get_by_label("Enable scheduled backups")).to_be_visible()
        expect(page.get_by_label("Full backup frequency")).to_be_visible()
        expect(page.locator("#data_management_scheduled_time_utc")).to_have_value("03:00")
        expect(page.get_by_label("Run partial backups daily between full backups")).to_be_visible()
        expect(page.get_by_role("button", name="Advanced backup scope")).to_be_visible()
        expect(page.locator("#data_management_target_cosmos_database")).to_have_value("SimpleChat")
        expect(page.locator("#data_management_target_cosmos_database")).to_have_attribute("readonly", "")
        expect(page.locator("#data_management_backup_max_parallel_operations")).to_be_visible()
        expect(page.locator("#data_management_backup_retry_count")).to_be_visible()
        expect(page.locator("#data_management_backup_blob_max_parallel_operations")).to_be_visible()
        expect(page.locator("#data_management_backup_blob_chunk_size_mib")).to_be_visible()
        expect(page.locator("#data_management_backup_blob_retry_count")).to_be_visible()
        expect(page.get_by_label("Temporarily increase local source Cosmos capacity for this backup")).to_be_visible()
        expect(page.locator("#data-management-target-ai-search-section")).to_be_visible()
        expect(page.locator("#data-management-test-target-search-btn")).to_be_visible()
        expect(page.locator("#data-management-migration-workflow-section")).to_be_visible()
        expect(page.locator('[data-migration-step-panel="target"]')).to_be_visible()
        expect(page.locator('[data-migration-step-panel="scope"]')).to_have_class(re.compile(r"\bd-none\b"))
        if not page.locator("#data_management_target_cosmos_endpoint").input_value():
            page.locator("#data_management_target_cosmos_endpoint").fill(
                "https://target.documents.azure.com:443/"
            )
        page.locator("#data-management-migration-next-btn").click()
        expect(page.locator('[data-migration-step-panel="scope"]')).to_be_visible()
        page.locator('[data-migration-mode-option="users"][value="selected"]').check()
        expect(page.locator("#data-management-migration-users-available")).to_contain_text(
            "Admin User"
        )
        page.locator("#data-management-migration-users-available").get_by_role(
            "button"
        ).click()
        expect(page.locator("#data-management-migration-users-selected")).to_contain_text(
            "Admin User"
        )
        page.locator('[data-migration-page-next="users"]').click()
        expect(page.locator("#data-management-migration-users-available")).to_contain_text(
            "Second User"
        )
        expect(page.locator("#data-management-migration-users-selected")).to_contain_text(
            "Admin User"
        )
        page.locator('[data-migration-mode-option="users"][value="all"]').check()
        expect(page.locator('[data-migration-all-count="users"]')).to_contain_text(
            "51 Users included"
        )
        page.locator("#data_management_migration_users_documents").check()
        page.locator("#data-management-migration-next-btn").click()
        expect(page.locator('[data-migration-step-panel="options"]')).to_be_visible()
        expect(page.get_by_label("New only")).to_be_checked()
        page.locator("#data_management_migration_include_ai_search").uncheck()
        page.locator("#data-management-migration-next-btn").click()
        expect(page.locator('[data-migration-step-panel="review"]')).to_be_visible()
        page.locator("#data-management-migration-preview-btn").click()
        expect(page.locator("#data-management-migration-readiness")).to_contain_text(
            "Ready with 1 warning"
        )
        expect(page.locator("#data-management-migration-review-checks")).to_contain_text(
            "Migration scope"
        )
        page.locator("#data-management-migration-next-btn").click()
        expect(page.locator('[data-migration-step-panel="confirm"]')).to_be_visible()
        page.locator("#data_management_migration_final_confirmation").check()
        expect(page.locator("#data-management-execute-migration-btn")).to_be_enabled()
        page.locator("#data-management-execute-migration-btn").evaluate(
            "(button) => { button.click(); button.click(); }"
        )
        expect(page.locator('[data-migration-step-panel="progress"]')).to_be_visible()
        expect(page.locator("#data-management-migration-workflow-progress")).to_be_visible()
        expect(page.locator("#data-management-migration-workflow-progress-summary")).to_contain_text(
            "11111111-1111-1111-1111-111111111111"
        )
        assert len(job_submissions) == 1
        workflow_box = page.locator("#data-management-migration-section").bounding_box()
        assert workflow_box
        assert workflow_box["width"] <= viewport["width"]
        expect(page.locator("#data-management-cosmos-editor-section")).to_be_visible()
        expect(page.locator("#data-management-cosmos-editor-locked-message")).to_be_visible()
        expect(page.locator("#data-management-cosmos-editor-workspace")).to_have_class(re.compile(r"\bd-none\b"))
        expect(page.locator("#data-management-cosmos-editor-danger-modal")).to_be_attached()
        expect(page.locator("#data-management-cosmos-editor-results-modal")).to_be_attached()
        expect(page.locator("#data-management-cosmos-editor-save-modal")).to_be_attached()
        expect(page.locator("#data-management-save-settings-btn")).to_be_visible()
        expect(page.locator("#data-management-save-settings-btn")).to_be_disabled()
        expect(page.locator("#data-management-save-settings-btn")).to_contain_text("Saved")
        expect(page.locator("#floating-save-btn")).to_have_class(re.compile(r"\bd-none\b"))
        page.locator("#data_management_storage_auth").select_option("connection_string")
        expect(page.locator("#data-management-blob-endpoint-field")).to_have_class(re.compile(r"\bd-none\b"))
        expect(page.locator("#data-management-connection-string-field")).to_be_visible()
        expect(page.locator("#data-management-save-settings-btn")).to_be_enabled()
        expect(page.locator("#data-management-full-backup-count")).to_be_visible()
        expect(page.locator("#data-management-partial-backup-count")).to_be_visible()
        expect(page.locator("#data-management-backups-tbody")).to_be_visible()
        expect(page.locator("#data-management-jobs-tbody")).to_be_visible()
        expect(page.locator("#data-management-job-detail-modal")).to_be_attached()
        expect(page.locator("#data-management-migration-cancel-modal")).to_be_attached()
    finally:
        context.close()
        browser.close()
        playwright_context.stop()


@pytest.mark.ui
def test_admin_data_management_tab_browser_workflow():
    """Validate the full migration workflow at a desktop viewport."""
    _run_admin_migration_browser_workflow({"width": 1440, "height": 900})


@pytest.mark.ui
def test_admin_data_management_tab_mobile_workflow():
    """Validate the full migration workflow at a mobile viewport."""
    _run_admin_migration_browser_workflow({"width": 390, "height": 844})


@pytest.mark.ui
def test_admin_data_management_history_pagination_browser_workflow():
    """Validate authenticated filters and opaque previous/next navigation."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid admin Playwright storage state file.")
    if expect is None or sync_playwright is None:
        pytest.skip("Install playwright to run this UI test.")

    captured_queries = {"jobs": [], "backups": []}
    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()

    def parse_query(url):
        return parse_qs(urlparse(url).query)

    def build_job(job_id, created_at, operation="backup"):
        return {
            "id": job_id,
            "created_at": created_at,
            "operation": operation,
            "backup_type": "full" if operation == "backup" else None,
            "status": "completed",
            "scheduled": False,
            "progress": {"percent_complete": 100},
            "last_message": "Completed",
        }

    def build_backup(backup_id, created_at, backup_type="full"):
        return {
            "id": backup_id,
            "created_at": created_at,
            "completed_at": created_at,
            "backup_type": backup_type,
            "status": "completed",
            "scheduled": False,
            "artifact_count": 1,
            "bytes": 100,
            "record_count": 1,
            "blob_count": 0,
            "warning_count": 0,
            "encrypted": True,
        }

    def handle_jobs(route):
        query = parse_query(route.request.url)
        captured_queries["jobs"].append(query)
        is_second_page = query.get("continuation_token") == ["jobs-page-2"]
        jobs = (
            [build_job("job-3", "2026-07-28T12:00:00+00:00", "migration")]
            if is_second_page
            else [
                build_job("job-1", "2026-07-30T12:00:00+00:00"),
                build_job("job-2", "2026-07-29T12:00:00+00:00"),
            ]
        )
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "success": True,
                "jobs": jobs,
                "pagination": {
                    "page_size": int(query.get("page_size", ["25"])[0]),
                    "returned_count": len(jobs),
                    "has_more": not is_second_page,
                    "next_token": None if is_second_page else "jobs-page-2",
                },
            }),
        )

    def handle_backups(route):
        query = parse_query(route.request.url)
        captured_queries["backups"].append(query)
        is_second_page = query.get("continuation_token") == ["backups-page-2"]
        backups = (
            [build_backup("backup-2", "2026-07-29T12:00:00+00:00", "partial")]
            if is_second_page
            else [build_backup("backup-1", "2026-07-30T12:00:00+00:00")]
        )
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "success": True,
                "backups": backups,
                "summary": {
                    "full": 5,
                    "partial": 4,
                    "available": 9,
                    "total": 12,
                },
                "pagination": {
                    "page_size": int(query.get("page_size", ["25"])[0]),
                    "returned_count": len(backups),
                    "has_more": not is_second_page,
                    "next_token": None if is_second_page else "backups-page-2",
                },
            }),
        )

    try:
        page.route("**/api/admin/data-management/jobs?*", handle_jobs)
        page.route("**/api/admin/data-management/backups?*", handle_backups)
        response = page.goto(f"{BASE_URL}/admin/settings#data-management", wait_until="networkidle")
        if response and response.status >= 400:
            pytest.skip("Admin settings are not accessible with the configured storage state.")
        if page.locator("#data-management-tab").count() == 0:
            pytest.skip("Admin settings are not accessible with the configured storage state.")

        page.locator("#data-management-tab").click()
        expect(page.locator("#data-management-job-pagination-status")).to_contain_text("Page 1 - 2 records")
        expect(page.locator("#data-management-job-next-page-btn")).to_be_enabled()
        page.locator("#data-management-job-next-page-btn").click()
        expect(page.locator("#data-management-job-pagination-status")).to_contain_text("Page 2 - 1 record - final page")
        assert captured_queries["jobs"][-1].get("continuation_token") == ["jobs-page-2"]
        expect(page.locator("#data-management-job-previous-page-btn")).to_be_enabled()

        page.locator("#data-management-refresh-jobs-btn").click()
        expect(page.locator("#data-management-job-pagination-status")).to_contain_text("Page 2 - 1 record")
        assert captured_queries["jobs"][-1].get("continuation_token") == ["jobs-page-2"]

        page.locator("#data_management_job_operation_filter").select_option("migration")
        expect(page.locator("#data-management-job-pagination-status")).to_contain_text("Page 1")
        assert captured_queries["jobs"][-1].get("operation") == ["migration"]
        assert "continuation_token" not in captured_queries["jobs"][-1]

        expect(page.locator("#data-management-backup-pagination-status")).to_contain_text("Page 1 - 1 record")
        page.locator("#data-management-backup-next-page-btn").click()
        expect(page.locator("#data-management-backup-pagination-status")).to_contain_text("Page 2 - 1 record - final page")
        assert captured_queries["backups"][-1].get("continuation_token") == ["backups-page-2"]

        page.locator("#data-management-view-full-backups-btn").click()
        expect(page.locator("#data-management-backup-pagination-status")).to_contain_text("Page 1")
        assert captured_queries["backups"][-1].get("backup_type") == ["full"]
        assert captured_queries["backups"][-1].get("status") == ["available"]
        assert "continuation_token" not in captured_queries["backups"][-1]
        expect(page.locator("#data-management-available-backup-count")).to_have_text("9")

        page.locator("#data_management_backup_page_size").select_option("50")
        assert captured_queries["backups"][-1].get("page_size") == ["50"]
        expect(page.locator("#data-management-backup-previous-page-btn")).to_be_disabled()

        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator("#data-management-backup-next-page-btn")).to_be_visible()
        expect(page.locator("#data-management-job-next-page-btn")).to_be_visible()
    finally:
        context.close()
        browser.close()
        playwright_context.stop()
