# test_workspace_bulk_tag_progress.py
"""
UI test for workspace bulk tag progress feedback.
Version: 0.241.112
Implemented in: 0.241.112

This test ensures the bulk tag apply button shows per-document progress while
selected workspace documents are updated.
"""

import json
import os
import time
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env() -> None:
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _fulfill_json(route, payload, status=200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _workspace_documents_payload() -> dict:
    return {
        "documents": [
            {
                "id": "doc-alpha",
                "title": "Alpha Brief",
                "file_name": "alpha-brief.md",
                "status": "complete",
                "percentage_complete": 100,
                "user_id": "user-1",
                "shared_user_ids": [],
                "tags": ["alpha"],
                "document_classification": "",
                "authors": [],
                "keywords": [],
            },
            {
                "id": "doc-beta",
                "title": "Beta Summary",
                "file_name": "beta-summary.md",
                "status": "complete",
                "percentage_complete": 100,
                "user_id": "user-1",
                "shared_user_ids": [],
                "tags": ["alpha"],
                "document_classification": "",
                "authors": [],
                "keywords": [],
            },
        ],
        "page": 1,
        "page_size": 10,
        "total_count": 2,
    }


def _open_select_action(page) -> None:
    page.locator("#documents-table tbody .action-dropdown button").first.click()
    page.get_by_role("link", name="Select").click()


@pytest.mark.ui
def test_workspace_bulk_tag_button_shows_document_progress(playwright):
    """Validate the bulk tag button surfaces per-document progress while applying."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    docs_payload = _workspace_documents_payload()
    tags_payload = {
        "tags": [
            {"name": "alpha", "color": "#0d6efd", "count": 2},
            {"name": "review", "color": "#198754", "count": 0},
        ]
    }
    bulk_request_document_ids = []
    dialog_messages = []

    def handle_dialog(dialog) -> None:
        dialog_messages.append(dialog.message)
        dialog.accept()

    def handle_bulk_tag(route) -> None:
        payload = json.loads(route.request.post_data or "{}")
        bulk_request_document_ids.append(payload.get("document_ids", []))
        time.sleep(0.35)
        _fulfill_json(
            route,
            {
                "success": [
                    {
                        "document_id": payload["document_ids"][0],
                        "tags": ["alpha", "review"],
                    }
                ],
                "errors": [],
            },
        )

    page.on("dialog", handle_dialog)
    page.route("**/api/documents?*", lambda route: _fulfill_json(route, docs_payload))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, tags_payload))
    page.route("**/api/documents/bulk-tag", handle_bulk_tag)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /workspace."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        page.wait_for_function(
            """
            () => document.querySelectorAll('#documents-table tbody tr.document-row').length === 2
            """
        )

        _open_select_action(page)
        page.locator("#docs-select-all-checkbox").check()
        expect(page.locator("#selectedCount")).to_have_text("2")

        page.locator("#manage-tags-btn").click()
        expect(page.locator("#bulkTagModal")).to_be_visible()
        expect(page.locator("#bulk-tag-doc-count")).to_have_text("2")

        page.locator("#bulk-tags-list .tag-badge", has_text="review").click()
        page.locator("#bulk-tag-apply-btn").click()

        progress_label = page.locator("#bulk-tag-apply-btn .button-loading")
        expect(progress_label).to_contain_text("Applying 1/2...")
        expect(progress_label).to_contain_text("Applying 2/2...")

        page.wait_for_function(
            """
            () => {
                const modal = document.getElementById('bulkTagModal');
                return modal && !modal.classList.contains('show');
            }
            """
        )

        assert len(bulk_request_document_ids) == 2, (
            f"Expected two per-document bulk tag requests, got {bulk_request_document_ids!r}."
        )
        assert all(len(document_ids) == 1 for document_ids in bulk_request_document_ids), (
            f"Expected each bulk tag request to carry one document id, got {bulk_request_document_ids!r}."
        )
        assert {document_ids[0] for document_ids in bulk_request_document_ids} == {"doc-alpha", "doc-beta"}
        assert any("Tags updated for 2 document(s)" in message for message in dialog_messages), (
            f"Expected a success dialog after bulk tagging, got {dialog_messages!r}."
        )
    finally:
        context.close()
        browser.close()