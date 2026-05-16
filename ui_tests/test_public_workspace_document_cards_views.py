# test_public_workspace_document_cards_views.py
"""
UI test for public workspace document cards and folder-card views.
Version: 0.241.029
Implemented in: 0.241.029

This test ensures public workspaces support cards, folders, folders plus cards,
card-click action menus, and visible-only select-all behavior.
"""

import json
import os
from pathlib import Path

import pytest


playwright_sync_api = pytest.importorskip("playwright.sync_api")
expect = playwright_sync_api.expect


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


def _public_workspace_payload() -> dict:
    return {
        "workspaces": [
            {
                "id": "public-alpha",
                "name": "Public Alpha",
                "isActive": True,
                "userRole": "Owner",
                "status": "active",
            }
        ]
    }


def _public_documents_payload(documents: list[dict]) -> dict:
    return {
        "documents": documents,
        "page": 1,
        "page_size": 10,
        "total_count": len(documents),
    }


def _public_document(document_id: str, title: str, tag: str) -> dict:
    return {
        "id": document_id,
        "file_name": f"{title.lower().replace(' ', '-')}.pdf",
        "title": title,
        "percentage_complete": 100,
        "status": "Complete",
        "authors": "Ada Lovelace",
        "abstract": f"Summary for {title}.",
        "number_of_pages": 7,
        "tags": [tag],
        "document_classification": "Public",
        "classification": "Public",
        "enhanced_citations": True,
        "version": "1",
    }


@pytest.mark.ui
def test_public_workspace_cards_folder_cards_and_visible_selection(playwright):
    """Validate public cards, folders plus cards, and visible select-all scope."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    all_documents = [
        _public_document("public-doc-alpha", "Alpha Report", "alpha"),
        _public_document("public-doc-beta", "Beta Report", "beta"),
    ]
    alpha_documents = [all_documents[0]]
    tags_payload = {
        "tags": [
            {"name": "alpha", "color": "#0d6efd", "count": 1},
            {"name": "beta", "color": "#198754", "count": 1},
        ]
    }

    def route_public_documents(route):
        if "tags=alpha" in route.request.url:
            _fulfill_json(route, _public_documents_payload(alpha_documents))
            return
        _fulfill_json(route, _public_documents_payload(all_documents))

    try:
        page.add_init_script("localStorage.setItem('publicWorkspaceViewPreference', 'cards');")
        page.route("**/api/public_workspaces?page_size=1000", lambda route: _fulfill_json(route, _public_workspace_payload()))
        page.route("**/api/public_documents*", route_public_documents)
        page.route("**/api/public_workspace_documents/tags*", lambda route: _fulfill_json(route, tags_payload))

        response = page.goto(f"{BASE_URL}/public_workspaces/public-alpha", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /public_workspaces/public-alpha."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Public workspace page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected /public_workspaces/public-alpha to load successfully, got HTTP {response.status}."

        card = page.locator("#public-documents-card-view .document-item-card").first
        expect(card).to_be_visible()
        expect(card).to_contain_text("Alpha Report")

        card.click(position={"x": 20, "y": 80})
        menu = page.locator("#public-documents-card-view .dropdown-menu.show").first
        expect(menu).to_be_visible()
        expect(menu).to_contain_text("Chat")
        expect(menu).to_contain_text("Edit Metadata")

        page.locator('label[for="public-docs-view-folders-cards"]').click()
        page.wait_for_function(
            """
            () => document.querySelector('#public-tag-folders-container .tag-folder-card[data-tag="alpha"]') !== null
            """
        )
        page.locator('#public-tag-folders-container .tag-folder-card[data-tag="alpha"]').click()
        page.wait_for_function(
            """
            () => document.querySelector('#public-folder-documents-card-view .document-item-card') !== null
            """
        )
        folder_card = page.locator("#public-folder-documents-card-view .document-item-card").first
        expect(folder_card).to_be_visible()
        expect(folder_card).to_contain_text("Alpha Report")

        page.locator('label[for="public-docs-view-list"]').click()
        page.wait_for_function(
            """
            () => document.querySelectorAll('#public-documents-table tbody tr.document-row').length === 2
            """
        )
        page.locator("#public-toggle-selection-btn").click()
        page.locator("#public-docs-select-all-checkbox").check()
        expect(page.locator("#publicSelectedCount")).to_have_text("2")

        page.locator('label[for="public-docs-view-grid"]').click()
        expect(page.locator("#publicBulkActionsBar")).not_to_be_visible()
        page.wait_for_function(
            """
            () => document.querySelector('#public-tag-folders-container .tag-folder-card[data-tag="alpha"]') !== null
            """
        )
        page.locator('#public-tag-folders-container .tag-folder-card[data-tag="alpha"]').click()
        page.wait_for_function(
            """
            () => document.querySelector('#public-folder-docs-table') !== null
            """
        )
        page.locator("#public-folder-docs-table .document-select-all-checkbox").check()
        expect(page.locator("#publicSelectedCount")).to_have_text("1")
    finally:
        context.close()
        browser.close()