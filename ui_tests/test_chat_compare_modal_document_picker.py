# test_chat_compare_modal_document_picker.py
"""
UI test for the chat compare modal document picker.
Version: 0.241.021
Implemented in: 0.241.021

This test ensures the compare modal exposes the same scope, tag, and document
picker controls as grounded search, and that documents selected in the modal
populate the Source and Target comparison board.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


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


def _handle_document_versions(route):
    request_url = route.request.url
    if "compare-baseline-doc" in request_url:
        _fulfill_json(
            route,
            {
                "versions": [
                    {
                        "id": "compare-baseline-v2",
                        "title": "Baseline Policy",
                        "file_name": "baseline-policy.md",
                        "version": 2,
                        "upload_date": "2026-05-15T12:00:00Z",
                        "is_current_version": True,
                    }
                ]
            },
        )
        return

    if "compare-target-doc" in request_url:
        _fulfill_json(
            route,
            {
                "versions": [
                    {
                        "id": "compare-target-v4",
                        "title": "Updated Policy",
                        "file_name": "updated-policy.md",
                        "version": 4,
                        "upload_date": "2026-05-16T12:00:00Z",
                        "is_current_version": True,
                    }
                ]
            },
        )
        return

    _fulfill_json(route, {"versions": []})


@pytest.mark.ui
def test_compare_modal_hosts_document_picker_and_populates_board(playwright):
    """Validate compare setup can select workspace documents inside the modal."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    personal_docs_payload = {
        "documents": [
            {
                "id": "compare-baseline-doc",
                "title": "Baseline Policy",
                "file_name": "baseline-policy.md",
                "tags": ["policy"],
                "document_classification": "",
            },
            {
                "id": "compare-target-doc",
                "title": "Updated Policy",
                "file_name": "updated-policy.md",
                "tags": ["policy"],
                "document_classification": "",
            },
        ]
    }

    def handle_user_settings(route):
        if route.request.method == "GET":
            _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}})
            return

        if route.request.method == "POST":
            _fulfill_json(route, {"success": True})
            return

        route.continue_()

    page.route("**/api/user/settings", handle_user_settings)
    page.route(
        "**/api/get_conversations",
        lambda route: _fulfill_json(
            route,
            {
                "conversations": [
                    {
                        "id": "compare-modal-convo-1",
                        "title": "Compare Modal Regression",
                        "last_updated": "2026-05-16T10:00:00Z",
                        "classification": [],
                        "context": [],
                        "chat_type": "new",
                        "is_pinned": False,
                        "is_hidden": False,
                        "has_unread_assistant_response": False,
                    }
                ]
            },
        ),
    )
    page.route("**/conversation/compare-modal-convo-1/messages?*", lambda route: _fulfill_json(route, {"messages": []}))
    page.route("**/api/documents?page_size=1000", lambda route: _fulfill_json(route, personal_docs_payload))
    page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/public_workspace_documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": [{"name": "policy", "count": 2}]}))
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/public_workspace_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/documents/*/versions", _handle_document_versions)
    page.route("**/api/chat/stream/client-event", lambda route: _fulfill_json(route, {"success": True}))
    page.route(
        "**/api/conversations/compare-modal-convo-1/mark-read",
        lambda route: _fulfill_json(route, {"success": True}),
    )

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        search_button = page.locator("#search-documents-btn")
        if search_button.count() == 0:
            pytest.skip("Grounded search is not enabled for this environment.")

        compare_option = page.locator("#document-action-select option[value='comparison']")
        if compare_option.count() == 0:
            pytest.skip("Document comparison is not enabled for this environment.")

        search_button.click()
        expect(page.locator("#search-documents-container")).to_be_visible()

        page.select_option("#document-action-select", "comparison")
        expect(page.locator("#document-comparison-summary-bar")).to_be_visible()
        expect(page.locator("#document-comparison-edit-btn-label")).to_have_text("Set Up Compare")

        page.locator("#document-comparison-edit-btn").click()
        expect(page.locator("#document-comparison-modal.show")).to_be_visible()

        picker = page.locator("#document-comparison-picker-controls")
        expect(picker.locator("#scope-dropdown-button")).to_be_visible()
        expect(picker.locator("#tags-dropdown-button")).to_be_visible()
        expect(picker.locator("#document-dropdown-button")).to_be_visible()
        expect(page.locator("#document-comparison-available-list")).to_contain_text("No workspace documents")

        picker.locator("#document-dropdown-button").click()
        picker.locator("#document-dropdown-items .dropdown-item[data-document-id='compare-baseline-doc']").click()
        picker.locator("#document-dropdown-items .dropdown-item[data-document-id='compare-target-doc']").click()

        expect(page.locator("#document-comparison-source-dropzone [data-comparison-drag-id='compare-baseline-v2']")).to_be_visible()
        expect(page.locator("#document-comparison-selection-list [data-comparison-drag-id='compare-target-v4']")).to_be_visible()
        expect(page.locator("#document-comparison-selection-summary")).to_contain_text("1 Target selected")

        page.locator("#document-comparison-modal .modal-footer [data-bs-dismiss='modal']").click()
        expect(page.locator("#document-comparison-modal")).to_be_hidden()
        expect(page.locator("#search-documents-container [data-chat-document-picker-field='scope'] #scope-dropdown-button")).to_be_visible()
        expect(page.locator("#search-documents-container [data-chat-document-picker-field='tags'] #tags-dropdown-button")).to_be_visible()
        expect(page.locator("#search-documents-container [data-chat-document-picker-field='document'] #document-dropdown-button")).to_be_visible()
    finally:
        context.close()
        browser.close()