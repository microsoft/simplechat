# test_admin_data_management_settings_ui.py
"""
UI test for Admin Settings Data Management controls.
Version: 0.241.211
Implemented in: 0.241.211

This test ensures admins can discover the Data Management tab, see the
operational-business-hours warning, and access the backup, encryption,
target Cosmos, and job-history controls without unsafe frontend rendering.
"""

import os
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
        "data-management-schedule-section",
        "data_management_enabled",
        "data_management_full_frequency",
        "data_management_scheduled_time_utc",
        "data_management_partial_enabled",
        "data_management_storage_auth",
        "data_management_blob_endpoint",
        "data_management_container_name",
        "data-management-generate-key-btn",
        "data_management_encryption_enabled",
        "data-management-target-cosmos-section",
        "data_management_target_cosmos_auth",
        "data_management_target_cosmos_endpoint",
        "data_management_target_cosmos_database",
        "data-management-run-full-backup-btn",
        "data-management-run-partial-backup-btn",
        "data-management-restore-dry-run-btn",
        "data-management-migration-dry-run-btn",
        "data-management-jobs-tbody",
    ]

    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert "We suggest not running backups, restores, or migrations during your operational business hours." in template
    assert "Full backups run on the selected cadence; partial backups run daily only." in template
    assert "For managed identity, assign this App Service identity Cosmos DB Data Contributor" in template
    assert "admin_data_management.js') }}?v={{ config['VERSION'] }}" in template
    assert "innerHTML" not in js_source
    assert "insertAdjacentHTML" not in js_source


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
        expect(page.locator("#data-management-operational-warning")).to_contain_text(
            "We suggest not running backups, restores, or migrations during your operational business hours."
        )
        expect(page.get_by_label("Enable scheduled backups")).to_be_visible()
        expect(page.get_by_label("Full backup frequency")).to_be_visible()
        expect(page.locator("#data_management_scheduled_time_utc")).to_have_value("03:00")
        expect(page.get_by_label("Run partial backups daily between full backups")).to_be_visible()
        expect(page.locator("#data-management-save-settings-btn")).to_be_visible()
        expect(page.locator("#data-management-jobs-tbody")).to_be_visible()
    finally:
        context.close()
        browser.close()
        playwright_context.stop()