# test_control_center_activity_logs_auto_refresh.py
"""
UI test for Control Center Activity Logs auto-refresh.

Version: 0.241.028
Implemented in: 0.241.028

This test ensures that admins can enable Activity Logs auto-refresh, adjust the
interval with the preset and numeric controls, persist settings in localStorage,
and trigger repeated Activity Logs API requests without leaving the tab.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_control_center_activity_logs_auto_refresh(playwright):
    """Validate Activity Logs auto-refresh controls, persistence, and polling."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1365, "height": 900},
    )
    page = context.new_page()
    activity_log_requests = []

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
                            "id": f"log-{len(activity_log_requests)}",
                            "timestamp": "2026-05-16T18:41:38Z",
                            "activity_type": "user_login",
                            "user_id": "user-1",
                            "workspace_type": "personal",
                            "login_method": "authenticated_request",
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
            body='{"success": true, "activity_data": {"logins": {}, "chats": {}, "documents": {}, "personal_documents": {}, "group_documents": {}, "public_documents": {}, "tokens": {}}, "period": "30 days", "start_date": "2026-04-17T00:00:00", "end_date": "2026-05-16T23:59:59"}',
        )

    try:
        page.route("**/api/admin/control-center/activity-logs?*", fulfill_activity_logs)
        page.route("**/api/admin/control-center/token-filters", fulfill_token_filters)
        page.route("**/api/admin/control-center/activity-trends*", fulfill_activity_trends)
        page.route("**/api/admin/control-center/users*", lambda route: route.fulfill(status=200, content_type="application/json", body=empty_paginated_response))
        page.route("**/api/admin/control-center/groups*", lambda route: route.fulfill(status=200, content_type="application/json", body=empty_paginated_response))
        page.route("**/api/admin/control-center/public-workspaces*", lambda route: route.fulfill(status=200, content_type="application/json", body=empty_paginated_response))

        page.add_init_script(
            """
            window.localStorage.removeItem('simplechat_activityLogsAutoRefreshEnabled');
            window.localStorage.removeItem('simplechat_activityLogsAutoRefreshIntervalSeconds');
            """
        )

        page.goto(f"{BASE_URL}/admin/control-center", wait_until="networkidle")

        with page.expect_response(lambda response: "/api/admin/control-center/activity-logs?" in response.url):
            page.locator("#activity-logs-tab").click()

        auto_refresh_toggle = page.locator("#activityLogsAutoRefreshToggle")
        interval_range = page.locator("#activityLogsAutoRefreshIntervalRange")
        interval_input = page.locator("#activityLogsAutoRefreshIntervalInput")
        interval_value = page.locator("#activityLogsAutoRefreshIntervalValue")
        status = page.locator("#activityLogsAutoRefreshStatus")

        expect(auto_refresh_toggle).not_to_be_checked()
        expect(interval_range).to_have_value("30")
        expect(interval_input).to_have_value("30")
        expect(interval_value).to_have_text("30 sec")

        page.locator("[data-activity-logs-refresh-preset='1']").click()
        expect(interval_range).to_have_value("1")
        expect(interval_input).to_have_value("1")
        expect(interval_value).to_have_text("1 sec")

        with page.expect_response(lambda response: "/api/admin/control-center/activity-logs?" in response.url):
            auto_refresh_toggle.check()

        expect(auto_refresh_toggle).to_be_checked()
        expect(status).to_contain_text("Every 1 sec")

        page.wait_for_response(lambda response: "/api/admin/control-center/activity-logs?" in response.url)
        assert len(activity_log_requests) >= 3, "Expected initial load, enable refresh, and timer refresh requests."

        interval_input.fill("300")
        expect(interval_range).to_have_value("300")
        expect(interval_value).to_have_text("5 min")
        expect(status).to_contain_text("Every 5 min")

        assert page.evaluate("() => window.localStorage.getItem('simplechat_activityLogsAutoRefreshEnabled')") == "true"
        assert page.evaluate("() => window.localStorage.getItem('simplechat_activityLogsAutoRefreshIntervalSeconds')") == "300"

        page.reload(wait_until="networkidle")

        with page.expect_response(lambda response: "/api/admin/control-center/activity-logs?" in response.url):
            page.locator("#activity-logs-tab").click()

        expect(page.locator("#activityLogsAutoRefreshToggle")).to_be_checked()
        expect(page.locator("#activityLogsAutoRefreshIntervalInput")).to_have_value("300")
        expect(page.locator("#activityLogsAutoRefreshIntervalValue")).to_have_text("5 min")
    finally:
        context.close()
        browser.close()