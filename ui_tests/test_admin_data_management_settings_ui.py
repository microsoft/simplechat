# test_admin_data_management_settings_ui.py
"""
UI test for Admin Settings Data Management controls.
Version: 0.241.221
Implemented in: 0.241.211
Updated in: 0.241.221

This test ensures admins can discover the Data Management tab, see the
operational-business-hours warning, and access the backup, encryption,
migration, backup inventory, and job-history controls without unsafe frontend rendering.
"""

import os
import re
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
ADMIN_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_data_management.js"
BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE") or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def test_admin_data_management_controls_render_from_template():
    """Validate the Data Management controls are present in the admin template."""
    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    js_source = ADMIN_JS.read_text(encoding="utf-8")

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
        "data-management-migration-section",
        "data-management-target-cosmos-section",
        "data_management_target_cosmos_auth",
        "data_management_target_cosmos_endpoint",
        "data_management_target_cosmos_database",
        "data-management-target-cosmos-key-field",
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
        "data-management-backup-operations-section",
        "data-management-run-full-backup-btn",
        "data-management-run-partial-backup-btn",
        "data-management-backup-inventory-section",
        "data-management-full-backup-count",
        "data-management-partial-backup-count",
        "data-management-available-backup-count",
        "data-management-backups-tbody",
        "data-management-jobs-tbody",
        "data-management-job-detail-modal",
        "data-management-job-detail-refresh-state",
        "data-management-job-detail-progress",
        "data-management-job-items-tbody",
        "data-management-job-artifacts-tbody",
        "data-management-job-manifest-detail",
        "data-management-job-warnings",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert "We suggest not running backups, restores, or migrations during your operational business hours." in template
    assert 'id="data-management" role="tabpanel" aria-labelledby="data-management-tab" data-testid="data-management-tab-pane" data-ignore-settings-change="true"' in template
    assert 'id="data-management-save-settings-btn" disabled aria-disabled="true"' in template
    assert '<h4 class="mb-1">Backup</h4>' in template
    assert '<h4 class="mb-1">Migration</h4>' in template
    assert '<h4 class="mb-1">Backup Inventory</h4>' in template
    assert 'aria-label="Backup inventory filters"' in template
    assert '<span>Available backups</span>' in template
    assert '<th scope="col">Backup</th>' in template
    assert '<th scope="col">Contents</th>' in template
    assert '<th scope="col">Protection</th>' in template
    assert 'Backup Contents' in template
    assert 'Storage and Manifest' in template
    assert '<h5 class="mb-1">Target Cosmos Database</h5>' in template
    assert '<h5 class="mb-1">Target Search</h5>' in template
    assert '<h5 class="mb-1">Target Enhanced Citation Storage</h5>' in template
    assert '<h5 class="mb-1">Migration Workflow</h5>' in template
    assert "Use migration when moving SimpleChat data into another SimpleChat environment" in template
    assert "Full backups run on the selected cadence; partial backups run daily only." in template
    assert "Advanced backup scope" in template
    assert "Modify them at your own risk" in template
    assert "Use a dedicated backup storage account" in template
    assert "Open Key Vault settings" in template
    assert "For managed identity, assign this App Service identity Cosmos DB Data Contributor" in template
    assert "Paste a connection string to save or replace it" in template
    assert 'id="data-management-connection-string-status"' in template
    assert 'id="data_management_target_cosmos_database" value="SimpleChat" readonly aria-readonly="true"' in template
    assert 'setStorageAuthVisibility' in js_source
    assert 'updateConnectionStringStatus' in js_source
    assert 'updateSourceBlobBackupAvailability' in js_source
    assert 'updateKeyStorageExperience' in js_source
    assert 'openKeyVaultSettings' in js_source
    assert 'setMigrationTargetVisibility' in js_source
    assert 'buildMigrationPlan' in js_source
    assert 'queueMigration(false)' in js_source
    assert 'loadMigrationCatalog(targetType)' in js_source
    assert 'testTargetCosmos' in js_source
    assert 'testTargetSearch' in js_source
    assert 'testTargetEnhancedCitationStorage' in js_source
    assert 'Migration preview refreshed.' in js_source
    assert 'Enhanced Citations is off, so source document blob backups are unavailable.' in js_source
    assert 'Stored connection string saved. You can test storage without re-entering it.' in js_source
    assert 'target_cosmos_database_name: targetCosmosDatabaseName' in js_source
    assert 'loadDataManagementBackups' in js_source
    assert 'loadDataManagementJobDetail' in js_source
    assert 'renderJobArtifacts' in js_source
    assert 'createDetailChipGroup' in js_source
    assert 'startJobDetailAutoRefresh' in js_source
    assert 'Live updates on -' in js_source
    assert 'View Log' in js_source
    assert "admin_data_management.js') }}?v={{ config['VERSION'] }}" in template
    assert "innerHTML" not in js_source
    assert "insertAdjacentHTML" not in js_source
    assert "data-management-restore-dry-run-btn" not in template
    assert "data-management-migration-dry-run-btn" not in template


@pytest.mark.ui
def test_admin_data_management_tab_browser_workflow():
    """Validate the rendered admin tab in an authenticated browser session when configured."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid admin Playwright storage state file.")
    if expect is None or sync_playwright is None:
        pytest.skip("Install playwright to run this UI test.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()

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
        expect(page.locator("#data-management-target-ai-search-section")).to_be_visible()
        expect(page.locator("#data-management-test-target-search-btn")).to_be_visible()
        expect(page.locator("#data-management-migration-workflow-section")).to_be_visible()
        expect(page.locator("#data-management-execute-migration-btn")).to_be_visible()
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
    finally:
        context.close()
        browser.close()
        playwright_context.stop()