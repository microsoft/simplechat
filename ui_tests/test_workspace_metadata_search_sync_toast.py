# test_workspace_metadata_search_sync_toast.py
"""
UI test for saving workspace document metadata with a queued search index sync.
Version: 0.261.268
Implemented in: 0.261.268

This test ensures the classic personal workspace Save Metadata dialog sends a single PATCH
request, closes immediately, and shows an informational toast only when the server reports
that the search index update was queued in the background.
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
SKIP_RESPONSE_CODES = {401, 403, 404}
DOCUMENT_ID = "doc-large-xml"
PENDING_TOAST_TEXT = "Search and chat results will reflect the change once the search index finishes updating."


def _require_ui_env() -> None:
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")


def _fulfill_json(route, payload, status=200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _large_document() -> dict:
    return {
        "id": DOCUMENT_ID,
        "title": "Large XML Export",
        "file_name": "large-export.xml",
        "status": "Processing Complete",
        "percentage_complete": 100,
        "num_chunks": 12000,
        "user_id": "user-1",
        "shared_user_ids": [],
        "tags": [],
        "document_classification": "",
        "authors": [],
        "keywords": [],
        "abstract": "",
        "publication_date": "",
    }


def _save_metadata(search_sync, edit_field, edit_value):
    """Open the metadata dialog, edit one field, save, and return the observed PATCH payloads."""
    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    document = _large_document()
    patch_payloads = []
    console_errors = []

    def handle_documents(route) -> None:
        request = route.request
        document_url = re.search(rf"/api/documents/{DOCUMENT_ID}(\?|$)", request.url)
        if "/api/documents/tags" in request.url:
            _fulfill_json(route, {"tags": [{"name": "bills", "color": "#0d6efd", "count": 0}]})
            return
        if request.method == "PATCH" and document_url:
            patch_payloads.append(json.loads(request.post_data or "{}"))
            _fulfill_json(route, {
                "message": "Document metadata updated successfully",
                "search_sync": search_sync,
            })
            return
        if request.method == "GET" and document_url:
            _fulfill_json(route, document)
            return
        if request.method == "GET":
            _fulfill_json(route, {"documents": [document], "page": 1, "page_size": 10, "total_count": 1})
            return
        _fulfill_json(route, {})

    page.route("**/api/documents**", handle_documents)
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /workspace."
        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")
        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        page.wait_for_function("typeof window.onEditDocument === 'function'")
        page.evaluate(f"window.onEditDocument('{DOCUMENT_ID}')")
        expect(page.locator("#docMetadataModal")).to_be_visible()

        page.locator(edit_field).fill(edit_value)
        page.locator("#doc-save-btn").click()

        page.wait_for_function(
            """
            () => {
                const modal = document.getElementById('docMetadataModal');
                return modal && !modal.classList.contains('show');
            }
            """
        )
        pending_toast = page.get_by_text(PENDING_TOAST_TEXT, exact=False)
        if search_sync.get("status") == "pending":
            expect(pending_toast.first).to_be_visible()
        else:
            expect(pending_toast).to_have_count(0)

        metadata_errors = [error for error in console_errors if "updating document" in error.lower()]
        assert not metadata_errors, f"Unexpected metadata save console errors: {metadata_errors!r}"
        return patch_payloads
    finally:
        context.close()
        browser.close()
        playwright_context.stop()


@pytest.mark.ui
def test_workspace_metadata_save_reports_queued_search_sync():
    """A queued search index sync closes the dialog after one PATCH and shows an info toast."""
    _require_ui_env()

    patch_payloads = _save_metadata(
        {"status": "pending", "revision": 1, "fields": ["title"]}, "#doc-title", "Large XML Export (2026)",
    )

    assert len(patch_payloads) == 1, f"Expected one metadata PATCH, got {patch_payloads!r}."
    assert patch_payloads[0].get("title") == "Large XML Export (2026)"


@pytest.mark.ui
def test_workspace_metadata_save_without_search_fields_shows_no_sync_toast():
    """Saving fields that are not mirrored on search chunks does not announce a search sync."""
    _require_ui_env()

    patch_payloads = _save_metadata({"status": "not_required"}, "#doc-abstract", "Updated summary only.")

    assert len(patch_payloads) == 1, f"Expected one metadata PATCH, got {patch_payloads!r}."
    assert patch_payloads[0].get("abstract") == "Updated summary only."
