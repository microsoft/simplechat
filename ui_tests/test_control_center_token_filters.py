# test_control_center_token_filters.py
"""
UI test for control center token filters.
Version: 0.239.164
Implemented in: 0.239.164

This test ensures the token filter controls appear on the Control Center
dashboard and that applying them forwards the selected values to the
activity-trends request.
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_control_center_token_filters_forward_query_params(playwright):
    """Validate token filter controls toggle correctly and update the trends request."""
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

    def handle_token_filters(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body="""
            {
                "success": true,
                "filters": {
                    "users": [{"id": "user-1", "label": "Ada Lovelace", "display_name": "Ada Lovelace", "email": "ada@example.com"}],
                    "groups": [{"id": "group-1", "name": "Research Group"}],
                    "public_workspaces": [{"id": "workspace-1", "name": "Public Knowledge"}],
                    "models": [{"value": "gpt-4o", "label": "gpt-4o"}],
                    "workspace_types": [
                        {"value": "personal", "label": "Personal"},
                        {"value": "group", "label": "Group"},
                        {"value": "public", "label": "Public"}
                    ],
                    "token_types": [
                        {"value": "chat", "label": "Chat"},
                        {"value": "embedding", "label": "Embedding"}
                    ]
                }
            }
            """
        )

    def handle_activity_trends(route):
        query = parse_qs(urlparse(route.request.url).query)
        captured_queries.append(query)
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true, "activity_data": {"logins": {}, "chats": {}, "documents": {}, "personal_documents": {}, "group_documents": {}, "public_documents": {}, "tokens": {}}, "period": "30 days", "start_date": "2026-03-01T00:00:00", "end_date": "2026-03-30T23:59:59"}'
        )

    try:
        page.route("**/api/admin/control-center/token-filters", handle_token_filters)
        page.route("**/api/admin/control-center/activity-trends*", handle_activity_trends)

        page.goto(f"{BASE_URL}/admin/control-center", wait_until="networkidle")

        expect(page.locator("#tokenUserFilter")).to_be_visible()
        expect(page.locator("#tokenWorkspaceTypeFilter")).to_be_visible()
        expect(page.locator("#tokenModelFilter")).to_be_visible()
        expect(page.locator("#tokenTypeFilter")).to_be_visible()

        page.locator("#tokenWorkspaceTypeFilter").select_option("group")
        expect(page.locator("#tokenGroupFilterContainer")).to_be_visible()
        expect(page.locator("#tokenPublicWorkspaceFilterContainer")).to_be_hidden()

        page.locator("#tokenUserFilter").select_option("user-1")
        page.locator("#tokenGroupFilter").select_option("group-1")
        page.locator("#tokenModelFilter").select_option("gpt-4o")
        page.locator("#tokenTypeFilter").select_option("chat")

        with page.expect_response(lambda response: "/api/admin/control-center/activity-trends?" in response.url):
            page.locator("#tokenApplyFiltersBtn").click()

        assert captured_queries, "Expected at least one activity trends request"
        applied_query = captured_queries[-1]
        assert applied_query.get("user_id") == ["user-1"]
        assert applied_query.get("workspace_type") == ["group"]
        assert applied_query.get("group_id") == ["group-1"]
        assert applied_query.get("model") == ["gpt-4o"]
        assert applied_query.get("token_type") == ["chat"]
    finally:
        context.close()
        browser.close()