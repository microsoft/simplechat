# test_stats_time_windows_and_exports.py
"""
UI test for stats time windows and exports.

Version: 0.241.111
Implemented in: 0.241.111

This test ensures personal, group, and public stats pages expose 7/30/90/custom
window controls and an export action when an authenticated UI test environment is available.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
GROUP_ID = os.getenv("SIMPLECHAT_UI_GROUP_ID", "")
PUBLIC_WORKSPACE_ID = os.getenv("SIMPLECHAT_UI_PUBLIC_WORKSPACE_ID", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")
    if not GROUP_ID:
        pytest.skip("Set SIMPLECHAT_UI_GROUP_ID to a group the test user can administer.")
    if not PUBLIC_WORKSPACE_ID:
        pytest.skip("Set SIMPLECHAT_UI_PUBLIC_WORKSPACE_ID to a public workspace the test user can manage.")


def _assert_stats_controls(page, export_modal_id):
    page.get_by_role("button", name="7 Days").first.wait_for(state="visible")
    page.get_by_role("button", name="30 Days").first.wait_for(state="visible")
    page.get_by_role("button", name="90 Days").first.wait_for(state="visible")
    page.get_by_role("button", name="Custom").first.wait_for(state="visible")
    page.get_by_role("button", name="Export").first.click()
    page.locator(export_modal_id).wait_for(state="visible")
    page.get_by_label("Last 7 Days").wait_for(state="visible")
    page.get_by_label("Last 30 Days").wait_for(state="visible")
    page.get_by_label("Last 90 Days").wait_for(state="visible")
    page.get_by_label("Custom Range").wait_for(state="visible")
    page.keyboard.press("Escape")


@pytest.mark.ui
def test_stats_time_windows_and_export_controls():
    """Validate stats window controls and export modals across stats pages."""
    _require_ui_env()

    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        page.goto(f"{BASE_URL}/profile?tab=stats")
        _assert_stats_controls(page, "#exportActivityModal")

        page.goto(f"{BASE_URL}/groups/{GROUP_ID}")
        page.locator("#stats-tab").wait_for(state="visible")
        page.locator("#stats-tab").click()
        _assert_stats_controls(page, "#groupStatsExportModal")

        page.goto(f"{BASE_URL}/public_workspaces/{PUBLIC_WORKSPACE_ID}")
        page.locator("#stats-tab").wait_for(state="visible")
        page.locator("#stats-tab").click()
        _assert_stats_controls(page, "#publicStatsExportModal")
    finally:
        context.close()
        browser.close()
        playwright.stop()