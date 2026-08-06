# test_chat_mixed_source_selection_payload.py
"""
UI test for explicit mixed-source Chat payload consistency.
Version: 0.250.064
Implemented in: 0.250.064

This test ensures Phase 2 issue #1057 sends the Phase 1 #1056 selection
contract with the Search Documents panel open and closed. Parent: #1055.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _fulfill_stream(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
        body=f"data: {json.dumps(payload)}\n\n",
    )


def _select_mixed_documents(page):
    page.locator("#document-select").evaluate(
        """
        select => {
            const selectedIds = ['narrative-pdf', 'table-xlsx'];
            Array.from(select.options).forEach(option => {
                option.selected = selectedIds.includes(option.value);
            });
            select.dispatchEvent(new Event('change', { bubbles: true }));
            window.dispatchEvent(new CustomEvent('chat:document-selection-changed', {
                detail: { documentIds: selectedIds },
            }));
        }
        """
    )


@pytest.mark.ui
def test_selected_documents_request_context_with_panel_open_and_closed():
    """Validate that panel state changes retrieval preference, not selected context."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    playwright_module = pytest.importorskip("playwright.sync_api")
    expect = playwright_module.expect
    playwright_context = playwright_module.sync_playwright().start()

    browser = playwright_context.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    captured_payloads = []

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
                "conversations": [{
                    "id": "mixed-source-payload-conversation",
                    "title": "Mixed Source Payload",
                    "last_updated": "2026-07-22T10:00:00Z",
                    "classification": [],
                    "context": [],
                    "chat_type": "new",
                    "is_pinned": False,
                    "is_hidden": False,
                    "has_unread_assistant_response": False,
                }]
            },
        ),
    )
    page.route(
        "**/conversation/mixed-source-payload-conversation/messages?*",
        lambda route: _fulfill_json(route, {"messages": []}),
    )
    page.route(
        "**/api/documents?page_size=1000",
        lambda route: _fulfill_json(
            route,
            {
                "documents": [
                    {
                        "id": "narrative-pdf",
                        "title": "Narrative Report",
                        "file_name": "narrative-report.pdf",
                        "tags": [],
                        "document_classification": "",
                    },
                    {
                        "id": "table-xlsx",
                        "title": "Source Data",
                        "file_name": "source-data.xlsx",
                        "tags": [],
                        "document_classification": "",
                    },
                ]
            },
        ),
    )
    page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/public_workspace_documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/public_workspace_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/chat/stream/client-event", lambda route: _fulfill_json(route, {"success": True}))
    page.route(
        "**/api/conversations/mixed-source-payload-conversation/mark-read",
        lambda route: _fulfill_json(route, {"success": True}),
    )

    def handle_standard_stream(route):
        payload = route.request.post_data_json or {}
        captured_payloads.append(payload)
        response_index = len(captured_payloads)
        _fulfill_stream(
            route,
            {
                "content": f"Mixed source response {response_index}",
                "full_content": f"Mixed source response {response_index}",
                "done": True,
                "conversation_id": "mixed-source-payload-conversation",
                "message_id": f"mixed-source-assistant-{response_index}",
                "role": "assistant",
            },
        )

    page.route("**/api/chat/stream", handle_standard_stream)

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok
        expect(page.locator("#user-input")).to_be_visible()

        workspace_toggle = page.locator("#search-documents-btn")
        workspace_toggle.click()
        expect(page.locator("#search-documents-container")).to_be_visible()
        _select_mixed_documents(page)

        page.locator("#user-input").fill("Summarize the report and calculate the table total")
        page.locator("#send-btn").click()
        expect(page.locator("[data-message-id='mixed-source-assistant-1']")).to_be_visible()

        workspace_toggle.click()
        expect(page.locator("#search-documents-container")).to_be_hidden()
        page.locator("#user-input").fill("Repeat the same mixed-source request")
        page.locator("#send-btn").click()
        expect(page.locator("[data-message-id='mixed-source-assistant-2']")).to_be_visible()

        assert len(captured_payloads) == 2
        open_payload, closed_payload = captured_payloads
        for payload in (open_payload, closed_payload):
            assert payload["selection_mode"] == "selected"
            assert payload["selected_document_ids"] == ["narrative-pdf", "table-xlsx"]
            assert payload["selected_document_id"] == "narrative-pdf"
            assert payload["document_context_requested"] is True

        assert open_payload["hybrid_search"] is True
        assert closed_payload["hybrid_search"] is False
    finally:
        context.close()
        browser.close()
        playwright_context.stop()
