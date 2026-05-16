# test_chat_document_action_workspace_toggle.py
"""
UI test for chat document action workspace toggle gating.
Version: 0.241.023
Implemented in: 0.241.111

This test ensures Analyze and Compare are ignored once workspace search is
turned off, even if the document action selector still holds one of those
values from an earlier workspace-enabled state.
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


def _fulfill_stream(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
        body=f"data: {json.dumps(payload)}\n\n",
    )


@pytest.mark.ui
def test_workspace_toggle_disables_analyze_and_uses_standard_chat_stream(playwright):
    """Validate that Analyze is ignored after workspace search is turned off."""
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

    stream_calls = {
        "standard": 0,
        "document_action": 0,
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
                        "id": "workspace-toggle-convo-1",
                        "title": "Workspace Toggle Regression",
                        "last_updated": "2026-05-05T10:00:00Z",
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
        "**/conversation/workspace-toggle-convo-1/messages?*",
        lambda route: _fulfill_json(route, {"messages": []}),
    )
    page.route(
        "**/api/documents?page_size=1000",
        lambda route: _fulfill_json(
            route,
            {
                "documents": [
                    {
                        "id": "personal-doc-1",
                        "title": "Workspace Analysis Doc",
                        "file_name": "workspace-analysis-doc.md",
                        "tags": [],
                        "document_classification": "",
                    }
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
        "**/api/conversations/workspace-toggle-convo-1/mark-read",
        lambda route: _fulfill_json(route, {"success": True}),
    )

    def handle_document_action_stream(route):
        stream_calls["document_action"] += 1
        _fulfill_stream(
            route,
            {
                "content": "Unexpected document action response",
                "full_content": "Unexpected document action response",
                "done": True,
                "conversation_id": "workspace-toggle-convo-1",
                "message_id": "assistant-doc-action-msg-1",
                "role": "assistant",
            },
        )

    def handle_standard_stream(route):
        stream_calls["standard"] += 1
        _fulfill_stream(
            route,
            {
                "content": "Workspace toggle regression response",
                "full_content": "Workspace toggle regression response",
                "done": True,
                "conversation_id": "workspace-toggle-convo-1",
                "message_id": "assistant-standard-msg-1",
                "role": "assistant",
            },
        )

    page.route("**/api/chat/document-action/stream", handle_document_action_stream)
    page.route("**/api/chat/stream", handle_standard_stream)

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        expect(page.locator("#user-input")).to_be_visible()

        workspace_toggle = page.locator("#search-documents-btn")
        workspace_toggle.click()
        expect(page.locator("#search-documents-container")).to_be_visible()

        page.locator("#document-select").evaluate(
            """
            select => {
                Array.from(select.options).forEach(option => {
                    option.selected = option.value === 'personal-doc-1';
                });
                select.dispatchEvent(new Event('change', { bubbles: true }));
                window.dispatchEvent(new CustomEvent('chat:document-selection-changed', {
                    detail: {
                        documentIds: ['personal-doc-1'],
                    },
                }));
            }
            """
        )
        page.select_option("#document-action-select", "analyze")

        workspace_toggle.click()
        expect(page.locator("#search-documents-container")).to_be_hidden()

        page.locator("#user-input").fill("Send without workspace analysis")
        page.locator("#send-btn").click()

        expect(page.locator("[data-message-id='assistant-standard-msg-1']")).to_be_visible()
        expect(page.locator("body")).not_to_contain_text("Select one or more documents before starting analysis.")

        assert stream_calls["standard"] == 1, "Expected the standard chat stream to run after workspace search was disabled."
        assert stream_calls["document_action"] == 0, "Document-action streaming should be skipped when workspace search is off."
    finally:
        context.close()
        browser.close()