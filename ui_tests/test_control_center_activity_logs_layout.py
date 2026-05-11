# test_control_center_activity_logs_layout.py
"""
UI test for control center activity logs layout and export wiring.

Version: 0.241.017
Implemented in: 0.241.017

This test ensures that the Activity Logs tab uses the responsive fixed-layout
table, renders the structured activity detail modal, keeps raw JSON copy
access behind the accordion section, and routes export through the dedicated
activity-log export endpoint.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_control_center_activity_logs_layout_and_export(playwright):
    """Validate the Activity Logs tab layout contract and dedicated export path."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1365, "height": 900},
        accept_downloads=True,
    )
    page = context.new_page()
    page.add_init_script(
        """
        Object.defineProperty(window, '__copiedActivityLog', {
            value: '',
            writable: true,
            configurable: true
        });

        Object.defineProperty(navigator, 'clipboard', {
            value: {
                writeText: async (text) => {
                    window.__copiedActivityLog = text;
                }
            },
            configurable: true
        });
        """
    )
    activity_log_requests = []
    export_requests = []

    empty_paginated_response = json.dumps({
        "users": [],
        "groups": [],
        "workspaces": [],
        "pagination": {
            "page": 1,
            "per_page": 50,
            "total_items": 0,
            "total_pages": 1,
            "has_prev": False,
            "has_next": False,
        },
    })

    def fulfill_activity_logs(route):
        activity_log_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "logs": [
                        {
                            "id": "log-1",
                            "timestamp": "2026-04-17T18:41:38.179505Z",
                            "activity_type": "token_usage",
                            "user_id": "user-1",
                            "workspace_type": "public",
                            "token_type": "chat",
                            "usage": {
                                "total_tokens": 7012,
                                "prompt_tokens": 6727,
                                "completion_tokens": 285,
                                "model": "gpt-5-nano"
                            },
                            "workspace_context": {
                                "group_id": "84ee868a-0d65-4d96-952c-bac3ba28c3d6",
                                "public_workspace_id": "ac29bb0b-4a8f-4bb9-b305-6972b2d35f9e",
                                "public_workspace_name": "Procurement"
                            },
                            "additional_context": {
                                "agent_name": None,
                                "augmented": True,
                                "reasoning_effort": "low"
                            },
                            "chat_details": {
                                "conversation_id": "a6d54b5b-f752-45c7-a8ee-49a2715b39fb",
                                "message_id": "a6d54b5b-f752-45c7-a8ee-49a2715b39fb_assistant_1776451261_8944"
                            },
                            "description": "Token usage captured for a grounded public workspace chat.",
                        }
                    ],
                    "user_map": {
                        "user-1": {
                            "email": "ada@example.com",
                            "display_name": "Ada Lovelace",
                        }
                    },
                    "pagination": {
                        "page": 1,
                        "per_page": 50,
                        "total_items": 1,
                        "total_pages": 1,
                        "has_prev": False,
                        "has_next": False,
                    },
                }
            ),
        )

    def fulfill_export(route):
        export_requests.append(route.request.url)
        route.fulfill(
            status=200,
            headers={
                "Content-Type": "text/csv; charset=utf-8",
                "Content-Disposition": 'attachment; filename="activity_logs_fixture.csv"',
            },
            body="Timestamp,Activity Type,User ID,User Email,User Name,Details,Workspace Type\n2026-04-08T16:40:24Z,document_deletion,user-1,ada@example.com,Ada Lovelace,Deleted fixture entry,personal\n",
        )

    def fulfill_token_filters(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body="""
            {
                "success": true,
                "filters": {
                    "users": [],
                    "groups": [],
                    "public_workspaces": [],
                    "models": [],
                    "workspace_types": [],
                    "token_types": []
                }
            }
            """,
        )

    def fulfill_activity_trends(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true, "activity_data": {"logins": {}, "chats": {}, "documents": {}, "personal_documents": {}, "group_documents": {}, "public_documents": {}, "tokens": {}}, "period": "30 days", "start_date": "2026-03-01T00:00:00", "end_date": "2026-03-30T23:59:59"}',
        )

    try:
        page.route("**/api/admin/control-center/activity-logs/export*", fulfill_export)
        page.route("**/api/admin/control-center/activity-logs?*", fulfill_activity_logs)
        page.route("**/api/admin/control-center/token-filters", fulfill_token_filters)
        page.route("**/api/admin/control-center/activity-trends*", fulfill_activity_trends)
        page.route("**/api/admin/control-center/users*", lambda route: route.fulfill(status=200, content_type="application/json", body=empty_paginated_response))
        page.route("**/api/admin/control-center/groups*", lambda route: route.fulfill(status=200, content_type="application/json", body=empty_paginated_response))
        page.route("**/api/admin/control-center/public-workspaces*", lambda route: route.fulfill(status=200, content_type="application/json", body=empty_paginated_response))

        page.goto(f"{BASE_URL}/admin/control-center", wait_until="networkidle")

        with page.expect_response(lambda response: "/api/admin/control-center/activity-logs?" in response.url):
            page.locator("#activity-logs-tab").click()

        table = page.locator("#activityLogsTable")
        expect(table).to_be_visible()
        expect(page.locator("#activityLogsTableBody .activity-log-details")).to_contain_text("Tokens: 7,012")

        desktop_table_layout = table.evaluate("el => getComputedStyle(el).tableLayout")
        assert desktop_table_layout == "fixed"

        page.set_viewport_size({"width": 680, "height": 900})

        table_metrics = page.locator("#activityLogsTable").evaluate(
            "el => ({ minWidth: getComputedStyle(el).minWidth, tableLayout: getComputedStyle(el).tableLayout, scrollWidth: el.parentElement.scrollWidth, clientWidth: el.parentElement.clientWidth })"
        )
        assert table_metrics["tableLayout"] == "fixed"
        assert table_metrics["minWidth"] == "940px"
        assert table_metrics["scrollWidth"] >= table_metrics["clientWidth"]

        details_styles = page.locator("#activityLogsTableBody .activity-log-details").evaluate(
            "el => ({ overflow: getComputedStyle(el).overflow, maxHeight: getComputedStyle(el).maxHeight })"
        )
        assert details_styles["overflow"] == "hidden"
        assert details_styles["maxHeight"] != "none"

        page.locator("#activityLogsTableBody tr").first.click()
        expect(page.locator("#rawLogModal")).to_be_visible()
        expect(page.locator("#rawLogModalBody")).to_contain_text("Overview")
        expect(page.locator("#rawLogModalBody")).to_contain_text("Activity Summary")
        expect(page.locator("#rawLogModalBody")).to_contain_text("Context & Related IDs")
        expect(page.locator("#rawLogModalBody")).to_contain_text("Additional Context")
        expect(page.locator("#rawLogModalBody")).to_contain_text("gpt-5-nano")
        expect(page.locator("#rawLogJsonToggle")).to_have_attribute("aria-expanded", "false")
        expect(page.locator("#rawLogModalJson")).to_be_hidden()

        page.locator("#rawLogJsonToggle").click()
        expect(page.locator("#rawLogJsonToggle")).to_have_attribute("aria-expanded", "true")
        expect(page.locator("#copyRawLogJsonBtn")).to_be_visible()
        expect(page.locator("#rawLogModalJson")).to_be_visible()
        expect(page.locator("#rawLogModalJson")).to_contain_text('"model": "gpt-5-nano"')

        page.locator("#copyRawLogJsonBtn").click()
        copied_text = page.evaluate("() => window.__copiedActivityLog")
        assert '"total_tokens": 7012' in copied_text
        assert '"public_workspace_id": "ac29bb0b-4a8f-4bb9-b305-6972b2d35f9e"' in copied_text

        page.locator("#rawLogModal .btn-close").click()

        with page.expect_request(lambda request: "/api/admin/control-center/activity-logs/export?" in request.url):
            page.locator("#exportActivityLogsBtn").click()

        assert export_requests[0].endswith("activity_type_filter=all")
        assert activity_log_requests, "Expected the Activity Logs tab to request paged activity logs"
    finally:
        context.close()
        browser.close()