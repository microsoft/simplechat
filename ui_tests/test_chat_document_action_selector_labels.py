# test_chat_document_action_selector_labels.py
"""
UI test for chat document action selector labels.
Version: 0.241.030
Implemented in: 0.241.030

This test ensures the chat document action selector renders before scope,
uses the Search/Analyze/Compare labels, updates the hover description for
each selected action, keeps the Document picker full width for every action,
and exposes the compact Source/Target comparison summary as a full-width row
below the dropdowns plus the modal editor with both version history and
uploaded chat files.
"""

import json
import os
from pathlib import Path

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
expect = playwright_sync_api.expect


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
    page.route(
        "**/api/get_conversations",
        lambda route: _fulfill_json(
            route,
            {
                "conversations": [
                    {
                        "id": "compare-convo-1",
                        "title": "Compare Uploads",
                        "last_updated": "2026-05-03T12:00:00Z",
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
    page.route(
        "**/conversation/compare-convo-1/messages?*",
        lambda route: _fulfill_json(
            route,
            {
                "messages": [
                    {
                        "id": "upload-msg-1",
                        "role": "file",
                        "content": "Uploaded file ready for comparison",
                        "file_name": "chat-upload-notes.pdf",
                        "conversation_id": "compare-convo-1",
                        "timestamp": "2026-05-03T12:01:00Z",
                    }
                ]
            },
        ),
    )
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

        field_labels = page.locator("#search-documents-container .chat-search-panel-grid > .chat-search-panel-field > label").evaluate_all(
            "elements => elements.map(element => element.textContent.replace(/\\s+/g, ' ').trim())"
        )
        assert field_labels[:4] == ["Action", "Scope", "Tags", "Document"]

        def assert_document_picker_fills_remaining_row(action_value):
            page.select_option("#document-action-select", action_value)
            layout = page.locator("#search-documents-container").evaluate(
                """
                container => {
                    const grid = container.querySelector('.chat-search-panel-grid');
                    const documentField = container.querySelector('[data-chat-document-picker-field="document"]');
                    const documentButton = container.querySelector('#document-dropdown-button');
                    const tagsField = container.querySelector('[data-chat-document-picker-field="tags"]');
                    const gridRect = grid.getBoundingClientRect();
                    const documentFieldRect = documentField.getBoundingClientRect();
                    const documentButtonRect = documentButton.getBoundingClientRect();
                    const tagsFieldRect = tagsField.getBoundingClientRect();

                    return {
                        buttonFillsField: documentButtonRect.width >= documentFieldRect.width - 2,
                        fieldReachesGridRight: Math.abs(documentFieldRect.right - gridRect.right) <= 4,
                        documentWiderThanTags: documentFieldRect.width > tagsFieldRect.width * 1.25,
                        documentOnTagsRow: Math.abs(documentFieldRect.top - tagsFieldRect.top) <= 4,
                    };
                }
                """
            )
            assert layout == {
                "buttonFillsField": True,
                "fieldReachesGridRight": True,
                "documentWiderThanTags": True,
                "documentOnTagsRow": True,
            }, f"Expected full-width document picker layout for action {action_value}, got {layout}"

        action_options = page.locator("#document-action-select option").all_text_contents()
        assert action_options[:3] == ["Search", "Analyze", "Compare"]

        action_select = page.locator("#document-action-select")
        assert_document_picker_fills_remaining_row("none")
        expect(action_select).to_have_attribute(
            "title",
            "Find relevant information in the selected documents.",
        )

        assert_document_picker_fills_remaining_row("analyze")
        expect(action_select).to_have_attribute(
            "title",
            "Perform an in-depth analysis across all selected documents based on your request.",
        )

        assert_document_picker_fills_remaining_row("comparison")
        expect(action_select).to_have_attribute(
            "title",
            "Compare one selected Source document against the Target documents to explain differences, relationships, or downstream impact.",
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

        comparison_summary_bar = page.locator("#document-comparison-summary-bar")
        expect(comparison_summary_bar).to_be_visible()
        comparison_summary_layout = page.locator("#search-documents-container").evaluate(
            """
            container => {
                const grid = container.querySelector('.chat-search-panel-grid');
                const summary = container.querySelector('#document-comparison-summary-bar');
                const fieldRects = Array.from(grid.querySelectorAll(':scope > .chat-search-panel-field:not(.chat-search-panel-comparison-row)'))
                    .map(element => element.getBoundingClientRect());
                const summaryRect = summary.getBoundingClientRect();
                const gridRect = grid.getBoundingClientRect();
                const maxFieldBottom = Math.max(...fieldRects.map(rect => rect.bottom));

                return {
                    summaryParentIsGrid: summary.parentElement === grid,
                    summaryStartsBelowFields: summaryRect.top >= maxFieldBottom - 1,
                    summaryNearlyFullWidth: summaryRect.width >= gridRect.width * 0.95,
                };
            }
            """
        )
        assert comparison_summary_layout == {
            "summaryParentIsGrid": True,
            "summaryStartsBelowFields": True,
            "summaryNearlyFullWidth": True,
        }
        expect(page.locator("#document-comparison-inline-source-tags")).to_contain_text("Alpha Brief v2")
        expect(page.locator("#document-comparison-inline-target-tags")).to_contain_text("None selected")
        expect(page.locator("#document-comparison-edit-btn-label")).to_have_text("Edit Compare")

        page.get_by_role("button", name="Edit Compare").click()
        expect(page.locator("#document-comparison-modal")).to_be_visible()
        expect(page.locator("#document-comparison-available-list")).to_contain_text("Alpha Brief")
        expect(page.locator("#document-comparison-available-list")).to_contain_text("chat-upload-notes.pdf")

        page.locator("#document-comparison-available-list .border.rounded-3").filter(has_text="Version 1").get_by_role("button", name="Use as Source").click()
        expect(page.locator("#document-comparison-source-dropzone")).to_contain_text("Version 1")

        page.locator("#document-comparison-available-list .border.rounded-3").filter(has_text="Version 2").get_by_role("button", name="Add to Target").click()
        page.locator("#document-comparison-available-list .border.rounded-3").filter(has_text="chat-upload-notes.pdf").get_by_role("button", name="Add to Target").click()
        expect(page.locator("#document-comparison-selection-list")).to_contain_text("Version 2")
        expect(page.locator("#document-comparison-selection-list")).to_contain_text("chat-upload-notes.pdf")

        page.get_by_role("button", name="Done").click()
        expect(page.locator("#document-comparison-modal")).to_be_hidden()
        expect(page.locator("#document-comparison-inline-source-tags")).to_contain_text("Alpha Brief v1")
        expect(page.locator("#document-comparison-inline-target-tags")).to_contain_text("Alpha Brief v2")
        expect(page.locator("#document-comparison-inline-target-tags")).to_contain_text("chat-upload-notes.pdf")
    finally:
        context.close()
        browser.close()