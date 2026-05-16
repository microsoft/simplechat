# test_control_center_chat_activity_logs.py
"""
UI test for control center chat activity logs.
Version: 0.241.102
Implemented in: 0.241.102

This test ensures the Control Center Activity Logs tab exposes the
chat activity filter and renders document-action chat rows with
human-readable details.
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_control_center_chat_activity_logs_surface_filter_and_details(playwright):
    """Validate chat activity rows can be filtered and rendered in Activity Logs."""
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
    captured_queries = []

    def handle_activity_logs(route):
        query = parse_qs(urlparse(route.request.url).query)
        captured_queries.append(query)
        route.fulfill(
            status=200,
            content_type="application/json",
            body='''
            {
                "logs": [
                    {
                        "id": "chat-log-1",
                        "activity_type": "chat_activity",
                        "user_id": "user-1",
                        "timestamp": "2026-05-04T12:00:00Z",
                        "conversation_id": "conversation-123",
                        "message_type": "user_message",
                        "message_length": 128,
                        "chat_context": "personal",
                        "workspace_type": "personal",
                        "additional_context": {
                            "conversation_source": "document_action_chat",
                            "document_action_type": "analyze"
                        }
                    }
                ],
                "user_map": {
                    "user-1": {
                        "display_name": "Ada Lovelace",
                        "email": "ada@example.com"
                    }
                },
                "pagination": {
                    "page": 1,
                    "per_page": 50,
                    "total_items": 1,
                    "total_pages": 1,
                    "has_prev": false,
                    "has_next": false
                }
            }
            '''
        )

    try:
        page.route("**/api/admin/control-center/activity-logs*", handle_activity_logs)

        page.goto(f"{BASE_URL}/admin/control-center", wait_until="networkidle")
        page.locator("#activity-logs-tab").click()

        expect(page.locator("#activityTypeFilterSelect option[value='chat_activity']")).to_be_attached()
        expect(page.locator("#activityLogsTableBody")).to_contain_text("Chat Activity")
        expect(page.locator("#activityLogsTableBody")).to_contain_text("Analyze")
        expect(page.locator("#activityLogsTableBody")).to_contain_text("Conversation: conversation-123")

        with page.expect_response(lambda response: "/api/admin/control-center/activity-logs?" in response.url):
            page.locator("#activityTypeFilterSelect").select_option("chat_activity")

        assert captured_queries, "Expected at least one activity logs request"
        assert captured_queries[-1].get("activity_type_filter") == ["chat_activity"]
    finally:
        context.close()
        browser.close()