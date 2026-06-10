# test_admin_file_sync_settings.py
"""
UI test for admin File Sync settings discovery.
Version: 0.241.180
Implemented in: 0.241.052
Updated in: 0.241.180

This test ensures admins can find the File Sync settings section, reveal the
scope controls, and see the group/public workspace assignment fields used to
manage File Sync access.
"""

import os
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE") or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid admin Playwright storage state file.")


@pytest.mark.ui
def test_admin_file_sync_settings_controls():
    """Validate that File Sync admin controls are discoverable."""
    _require_ui_env()
    if expect is None or sync_playwright is None:
        pytest.skip("Install playwright to run this UI test.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        page.goto(f"{BASE_URL}/admin/settings#workspaces", wait_until="networkidle")
        if page.locator("#file-sync-section").count() == 0:
            pytest.skip("Admin settings are not accessible with the configured storage state.")

        expect(page.locator("#file-sync-section")).to_be_visible()
        expect(page.get_by_label("Enable File Sync")).to_be_visible()

        page.get_by_label("Enable File Sync").check()
        expect(page.locator("#file_sync_settings")).to_be_visible()
        expect(page.get_by_label("Personal Workspaces")).to_be_visible()
        expect(page.get_by_label("Group Workspaces")).to_be_visible()
        expect(page.get_by_label("Public Workspaces")).to_be_visible()
        expect(page.get_by_label("Require Group Assignment to Use File Sync")).to_be_visible()
        expect(page.get_by_label("Require Public Workspace Assignment to Use File Sync")).to_be_visible()
        expect(page.locator("#file_sync_allowed_group_ids")).to_have_count(1)
        expect(page.locator("#file_sync_allowed_public_workspace_ids")).to_have_count(1)
    finally:
        context.close()
        browser.close()
        playwright_context.stop()