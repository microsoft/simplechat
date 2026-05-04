# test_chat_document_action_selector_labels.py
"""
UI test for chat document action selector labels.
Version: 0.241.097
Implemented in: 0.241.097

This test ensures the chat document action selector renders before scope,
uses the Search/Review/Compare labels, updates the hover description for
each selected action, and exposes version-aware comparison targets.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_chat_document_action_selector_labels(playwright):
    """Validate chat action ordering, labels, and hover descriptions."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    user_settings_payload = {
        "selected_agent": None,
        "settings": {
            "enable_agents": False,
        },
    }

    documents_payload = {
        "documents": [
            {
                "id": "personal-doc-1",
                "title": "Alpha Brief",
                "file_name": "alpha-brief.md",
                "tags": [],
                "document_classification": "",
            }
        ]
    }

    def handle_user_settings(route):
        if route.request.method == "GET":
            _fulfill_json(route, user_settings_payload)
            return

        if route.request.method == "POST":
            _fulfill_json(route, {"success": True})
            return

        route.continue_()

    page.route("**/api/user/settings", handle_user_settings)
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))
    page.route("**/api/documents?page_size=1000", lambda route: _fulfill_json(route, documents_payload))
    page.route(
        "**/api/documents/personal-doc-1/versions",
        lambda route: _fulfill_json(route, {
            "document_id": "personal-doc-1",
            "versions": [
                {
                    "id": "personal-doc-v2",
                    "title": "Alpha Brief",
                    "file_name": "alpha-brief.md",
                    "version": 2,
                    "upload_date": "2025-02-01T00:00:00Z",
                    "is_current_version": True,
                },
                {
                    "id": "personal-doc-v1",
                    "title": "Alpha Brief",
                    "file_name": "alpha-brief.md",
                    "version": 1,
                    "upload_date": "2025-01-15T00:00:00Z",
                    "is_current_version": False,
                },
            ],
        }),
    )
    page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/public_workspace_documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/public_workspace_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        page.locator("#search-documents-btn").click()
        expect(page.locator("#search-documents-container")).to_be_visible()

        field_labels = page.locator("#search-documents-container > .d-flex > div > label").evaluate_all(
            "elements => elements.map(element => element.textContent.replace(/\\s+/g, ' ').trim())"
        )
        assert field_labels[:4] == ["Action", "Scope", "Tags", "Document"]

        action_options = page.locator("#document-action-select option").all_text_contents()
        assert action_options[:3] == ["Search", "Review", "Compare"]

        action_select = page.locator("#document-action-select")
        expect(action_select).to_have_attribute(
            "title",
            "Find relevant information in the selected documents.",
        )

        page.select_option("#document-action-select", "exhaustive_review")
        expect(action_select).to_have_attribute(
            "title",
            "Perform an in-depth analysis across all selected documents based on your request.",
        )

        page.select_option("#document-action-select", "comparison")
        expect(action_select).to_have_attribute(
            "title",
            "Compare one selected document against the others to explain differences, relationships, or downstream impact.",
        )

        page.locator("#document-select").evaluate(
            """
            select => {
                Array.from(select.options).forEach(option => {
                    option.selected = option.value === 'personal-doc-1';
                });
                window.dispatchEvent(new CustomEvent('chat:document-selection-changed', {
                    detail: {
                        documentIds: ['personal-doc-1'],
                    },
                }));
            }
            """
        )

        expect(page.locator("#document-comparison-targets-container")).to_be_visible()
        expect(page.locator("#document-comparison-targets-select option")).to_have_count(2)
        page.select_option("#document-comparison-targets-select", ["personal-doc-v2", "personal-doc-v1"])
        expect(page.locator("#document-comparison-left-select option")).to_have_count(2)
        page.select_option("#document-comparison-left-select", "personal-doc-v1")
        expect(page.locator("#document-comparison-left-select")).to_have_value("personal-doc-v1")
    finally:
        context.close()
        browser.close()