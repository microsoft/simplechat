# test_control_center_activity_logs_layout_presets.py
"""
UI test for control center activity log layout presets.

Version: 0.241.016
Implemented in: 0.241.016

This test ensures that the Activity Logs tab exposes layout presets,
applies them client-side, persists them in localStorage, and restores
the selected preset after a page reload.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_control_center_activity_logs_layout_presets(playwright):
    """Validate Activity Logs layout presets and local persistence."""
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
                            "id": "log-1",
                            "timestamp": "2026-04-08T16:40:24Z",
                            "activity_type": "document_deletion",
                            "user_id": "user-1",
                            "workspace_type": "personal",
                            "document": {
                                "file_name": "Quarterly forecasting package for international staffing alignment and procurement planning.pdf",
                                "file_type": "pdf",
                            },
                            "description": "Deleted a long document entry for layout preset coverage.",
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
            body='{"success": true, "activity_data": {"logins": {}, "chats": {}, "documents": {}, "personal_documents": {}, "group_documents": {}, "public_documents": {}, "tokens": {}}, "period": "30 days", "start_date": "2026-03-01T00:00:00", "end_date": "2026-03-30T23:59:59"}',
        )

    try:
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
        expect(page.locator("#activityLogsLayoutPresetBalanced")).to_be_checked()
        expect(page.locator("#activityLogsLayoutHint")).to_contain_text("Switch to Details Focus")

        balanced_metrics = table.evaluate(
            "el => ({ preset: el.dataset.layoutPreset, minWidth: parseFloat(getComputedStyle(el).minWidth), detailsMaxHeight: parseFloat(getComputedStyle(el.querySelector('tbody .activity-log-details')).maxHeight) })"
        )
        assert balanced_metrics["preset"] == "balanced"

        page.locator("label[for='activityLogsLayoutPresetDetailsFocus']").click()
        expect(page.locator("#activityLogsLayoutPresetDetailsFocus")).to_be_checked()
        expect(page.locator("#activityLogsLayoutHint")).to_contain_text("widens the Details column")

        details_focus_metrics = table.evaluate(
            "el => ({ preset: el.dataset.layoutPreset, minWidth: parseFloat(getComputedStyle(el).minWidth), detailsMaxHeight: parseFloat(getComputedStyle(el.querySelector('tbody .activity-log-details')).maxHeight) })"
        )
        assert details_focus_metrics["preset"] == "details-focus"
        assert details_focus_metrics["minWidth"] > balanced_metrics["minWidth"]
        assert details_focus_metrics["detailsMaxHeight"] > balanced_metrics["detailsMaxHeight"]

        stored_preset = page.evaluate(
            "() => window.localStorage.getItem('simplechat_activityLogsLayoutPreset')"
        )
        assert stored_preset == "details-focus"

        page.locator("label[for='activityLogsLayoutPresetCompact']").click()
        expect(page.locator("#activityLogsLayoutPresetCompact")).to_be_checked()
        compact_metrics = table.evaluate(
            "el => ({ preset: el.dataset.layoutPreset, minWidth: parseFloat(getComputedStyle(el).minWidth) })"
        )
        assert compact_metrics["preset"] == "compact"
        assert compact_metrics["minWidth"] < balanced_metrics["minWidth"]

        page.locator("label[for='activityLogsLayoutPresetDetailsFocus']").click()
        page.reload(wait_until="networkidle")

        with page.expect_response(lambda response: "/api/admin/control-center/activity-logs?" in response.url):
            page.locator("#activity-logs-tab").click()

        reloaded_table = page.locator("#activityLogsTable")
        expect(page.locator("#activityLogsLayoutPresetDetailsFocus")).to_be_checked()
        reloaded_preset = reloaded_table.evaluate("el => el.dataset.layoutPreset")
        assert reloaded_preset == "details-focus"
        assert activity_log_requests, "Expected the Activity Logs tab to request paged activity logs"
    finally:
        context.close()
        browser.close()