# test_workspace_file_sync_ui.py
"""
UI test for workspace File Sync tab.
Version: 0.241.061
Implemented in: 0.241.042

This test ensures the workspace Sync tab renders, loads source rows, opens the
SMB source form, and queues a manual sync without browser console errors.
"""

import json
import os
import re
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_workspace_file_sync_tab():
    """Validate the personal workspace File Sync tab behavior."""
    _require_ui_env()
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    console_errors = []

    source_state = {
        "sources": [
            {
                "id": "source-1",
                "name": "Finance Share",
                "enabled": True,
                "recursive": True,
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
    synced_document = {
        "id": "doc-sync-1",
        "file_name": "synced-plan.pdf",
        "title": "Synced Plan",
        "status": "Processing Complete",
        "percentage_complete": 100,
        "version": 3,
        "authors": ["File Sync"],
        "number_of_pages": 8,
        "enhanced_citations": True,
        "tags": ["finance"],
        "file_sync": {
            "source_id": "source-1",
            "source_name": "Finance Share",
            "remote_path": "\\\\fileserver\\finance\\synced-plan.pdf",
            "relative_path": "synced-plan.pdf",
            "synced_at": "2025-01-01T00:01:00+00:00",
        },
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

    def handle_documents(route):
        request = route.request
        if "/api/documents/tags" in request.url:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"tags": []}))
            return
        if request.method == "GET" and re.search(r"/api/documents/doc-sync-1(\?|$)", request.url):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(synced_document))
            return
        if request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"documents": [synced_document], "page": 1, "page_size": 10, "total_count": 1}),
            )
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps({}))

    page.route("**/api/file-sync/personal/**", handle_file_sync)
    page.route("**/api/documents**", handle_documents)
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        if page.locator("#documents-tab-btn").count() > 0:
            page.locator("#documents-tab-btn").click()
        expect(page.get_by_text("synced-plan.pdf")).to_be_visible()
        expect(page.locator("#documents-table .badge", has_text="Synced").first).to_be_visible()

        page.wait_for_function("typeof window.onEditDocument === 'function'")
        page.evaluate("window.onEditDocument('doc-sync-1')")
        expect(page.locator("#doc-sync-status")).to_contain_text("Synced:")
        expect(page.locator("#doc-sync-status")).to_contain_text("Yes")
        expect(page.locator("#doc-sync-status")).to_contain_text("Finance Share")
        page.locator("#docMetadataModal .btn-close").click()

        if page.locator("#sync-tab-btn").count() == 0:
            pytest.skip("File Sync is not enabled for this environment.")

        if page.locator('[data-target="personal-workspace-submenu"]').count() > 0:
            page.locator('[data-target="personal-workspace-submenu"]').click()
            expect(page.locator('#personal-workspace-submenu [data-tab="sync-tab"]')).to_be_visible()

        page.locator("#sync-tab-btn").click()
        expect(page.get_by_role("heading", name="Sync Sources")).to_be_visible()
        expect(page.get_by_text("Finance Share")).to_be_visible()
        expect(page.get_by_text("queued 2, unchanged 4, skipped 1, failed 0")).to_be_visible()

        page.get_by_role("button", name="Delete").click()
        expect(page.get_by_role("heading", name="Delete File Sync Source")).to_be_visible()
        expect(page.get_by_role("button", name="Delete Sync Source")).to_be_visible()
        expect(page.get_by_role("button", name="Delete All Files")).to_be_visible()
        page.get_by_role("button", name="Cancel").click()

        page.get_by_role("button", name="Add Source").click()
        expect(page.get_by_label("UNC path")).to_be_visible()
        expect(page.locator("#file-sync-recursive")).to_be_visible()
        expect(page.get_by_role("button", name="Test Connection")).to_be_visible()

        page.get_by_role("button", name="History").click()
        expect(page.get_by_role("heading", name="Sync History")).to_be_visible()

        page.get_by_role("button", name="Sync").click()
        expect(page.get_by_text("Sync run queued.")).to_be_visible()
        assert console_errors == []
    finally:
        context.close()
        browser.close()
        playwright_context.stop()