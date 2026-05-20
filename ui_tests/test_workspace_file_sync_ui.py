# test_workspace_file_sync_ui.py
"""
UI test for workspace File Sync tab.
Version: 0.241.052
Implemented in: 0.241.042

This test ensures the workspace Sync tab renders, loads source rows, opens the
SMB source form, and queues a manual sync without browser console errors.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_workspace_file_sync_tab(playwright):
    """Validate the personal workspace File Sync tab behavior."""
    _require_ui_env()
    browser = playwright.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    console_errors = []

    source_state = {
        "sources": [
            {
                "id": "source-1",
                "name": "Finance Share",
                "enabled": True,
                "connection": {"unc_path": "\\\\fileserver\\finance"},
                "credentials": {"username": "svc-sync", "domain": "CONTOSO", "password_stored": True},
                "filters": {"include_patterns": ["*.pdf"], "exclude_patterns": [], "allowed_extensions": ["pdf"], "fixed_tags": ["finance"], "folder_tag_mode": "parent"},
                "schedule": {"enabled": True, "interval_minutes": 60},
                "remote_delete_policy": "ignore",
                "last_run_status": "completed",
                "last_run_counts": {"queued": 2, "unchanged": 4, "skipped": 1, "failed": 0},
            }
        ]
    }

    def handle_file_sync(route):
        request = route.request
        if request.method == "GET" and request.url.endswith("/sources"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(source_state))
            return
        if request.method == "GET" and request.url.endswith("/runs"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"runs": [{"status": "completed", "trigger": "manual", "started_at": "2025-01-01T00:00:00+00:00", "completed_at": "2025-01-01T00:01:00+00:00", "counts": {"queued": 2}}]}),
            )
            return
        if request.method == "POST" and request.url.endswith("/sync"):
            route.fulfill(status=202, content_type="application/json", body=json.dumps({"run": {"id": "run-2", "status": "queued"}}))
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"source": source_state["sources"][0]}))

    page.route("**/api/file-sync/personal/**", handle_file_sync)
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        if page.locator("#sync-tab-btn").count() == 0:
            pytest.skip("File Sync is not enabled for this environment.")

        if page.locator('[data-target="personal-workspace-submenu"]').count() > 0:
            page.locator('[data-target="personal-workspace-submenu"]').click()
            expect(page.locator('#personal-workspace-submenu [data-tab="sync-tab"]')).to_be_visible()

        page.locator("#sync-tab-btn").click()
        expect(page.get_by_role("heading", name="Sync Sources")).to_be_visible()
        expect(page.get_by_text("Finance Share")).to_be_visible()
        expect(page.get_by_text("queued 2, unchanged 4, skipped 1, failed 0")).to_be_visible()

        page.get_by_role("button", name="Add Source").click()
        expect(page.get_by_label("UNC path")).to_be_visible()

        page.get_by_role("button", name="History").click()
        expect(page.get_by_role("heading", name="Sync History")).to_be_visible()

        page.get_by_role("button", name="Sync").click()
        expect(page.get_by_text("Sync run queued.")).to_be_visible()
        assert console_errors == []
    finally:
        context.close()
        browser.close()