# test_chat_document_dropdown_viewport_fit.py
"""
UI test for chat document dropdown viewport fitting.
Version: 0.241.009
Implemented in: 0.241.009

This test ensures the chat document selector opens within the visible viewport
when the grounded-search controls sit near the bottom of a short browser window.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SHORT_DESKTOP_VIEWPORT = {"width": 1024, "height": 260}


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_chat_document_dropdown_stays_in_short_viewport(playwright):
    """Validate the document dropdown flips or shrinks instead of leaving the viewport."""
    _require_authenticated_chat_env()

    personal_docs_payload = {
        "documents": [
            {
                "id": f"viewport-doc-{index}",
                "title": f"Viewport Test Document {index}",
                "file_name": f"viewport-test-document-{index}.md",
                "tags": [],
                "document_classification": "",
            }
            for index in range(1, 25)
        ]
    }

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=SHORT_DESKTOP_VIEWPORT,
    )
    page = context.new_page()

    page.route("**/api/documents?page_size=1000", lambda route: _fulfill_json(route, personal_docs_payload))
    page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/public_workspace_documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/public_workspace_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        search_button = page.locator("#search-documents-btn")
        if search_button.count() == 0:
            pytest.skip("Grounded search is not enabled for this environment.")

        expect(search_button).to_be_visible()
        search_button.click()

        document_button = page.locator("#document-dropdown-button")
        expect(document_button).to_be_visible()
        document_button.click()

        menu = page.locator("#document-dropdown-menu.show")
        expect(menu).to_be_visible()
        page.wait_for_function(
            """
            () => {
                const menu = document.getElementById('document-dropdown-menu');
                return !!menu && menu.classList.contains('show') && menu.getBoundingClientRect().height > 0;
            }
            """
        )

        metrics = page.evaluate(
            """
            () => {
                const button = document.getElementById('document-dropdown-button').getBoundingClientRect();
                const menu = document.getElementById('document-dropdown-menu').getBoundingClientRect();
                const items = document.getElementById('document-dropdown-items');
                const placement = document.getElementById('document-dropdown-menu').getAttribute('data-popper-placement') || '';

                return {
                    buttonTop: button.top,
                    menuBottom: menu.bottom,
                    menuTop: menu.top,
                    placement,
                    viewportHeight: window.innerHeight,
                    itemsClientHeight: items.clientHeight,
                    itemsScrollHeight: items.scrollHeight,
                };
            }
            """
        )

        assert metrics["menuTop"] >= -1, f"Document dropdown escaped above viewport: {metrics}"
        assert metrics["menuBottom"] <= metrics["viewportHeight"] + 1, (
            f"Document dropdown escaped below viewport: {metrics}"
        )
        assert metrics["itemsScrollHeight"] > metrics["itemsClientHeight"], (
            f"Expected document list to scroll within constrained dropdown: {metrics}"
        )
    finally:
        context.close()
        browser.close()
