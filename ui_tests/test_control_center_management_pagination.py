# test_control_center_management_pagination.py
"""
UI test for Control Center management pagination controls.
Version: 0.241.030
Implemented in: 0.241.030

This test ensures the user, group, and public workspace management views expose
consistent page-size controls, send the selected per-page value to the API, and
keep public workspace table controls aligned with group management. It also
validates ID-aware management search placeholders.
"""

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
EXPECTED_PAGE_SIZE_OPTIONS = ["10", "25", "50", "100", "250"]


@pytest.mark.ui
def test_control_center_management_page_size_controls(playwright):
    """Validate management page-size selectors and outgoing pagination params."""
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
    captured_queries = {
        "users": [],
        "groups": [],
        "public_workspaces": [],
    }

    def build_pagination(query):
        page_value = int(query.get("page", ["1"])[0])
        per_page = int(query.get("per_page", ["25"])[0])
        total_items = 260
        total_pages = (total_items + per_page - 1) // per_page
        page_value = min(max(page_value, 1), total_pages)
        return {
            "page": page_value,
            "per_page": per_page,
            "total_items": total_items,
            "total_count": total_items,
            "total_pages": total_pages,
            "has_prev": page_value > 1,
            "has_next": page_value < total_pages,
        }

    def parse_query(url):
        return parse_qs(urlparse(url).query)

    def fulfill_management_route(route, collection_name, payload_key):
        query = parse_query(route.request.url)
        captured_queries[collection_name].append(query)
        pagination = build_pagination(query)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({payload_key: [], "pagination": pagination}),
        )

    def handle_token_filters(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "filters": {
                    "users": [],
                    "workspace_types": ["personal", "group", "public"],
                    "groups": [],
                    "public_workspaces": [],
                    "models": [],
                    "token_types": [],
                }
            }),
        )

    def handle_activity_trends(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "activity_data": {
                    "logins": {},
                    "chats_created": {},
                    "chats_deleted": {},
                    "personal_documents_created": {},
                    "personal_documents_deleted": {},
                    "group_documents_created": {},
                    "group_documents_deleted": {},
                    "public_documents_created": {},
                    "public_documents_deleted": {},
                    "tokens": {},
                    "embedding_tokens": {},
                    "chat_tokens": {},
                    "web_search_tokens": {},
                }
            }),
        )

    try:
        page.route(
            "**/api/admin/control-center/users?*",
            lambda route: fulfill_management_route(route, "users", "users"),
        )
        page.route(
            "**/api/admin/control-center/groups?*",
            lambda route: fulfill_management_route(route, "groups", "groups"),
        )
        page.route(
            "**/api/admin/control-center/public-workspaces?*",
            lambda route: fulfill_management_route(route, "public_workspaces", "workspaces"),
        )
        page.route("**/api/admin/control-center/token-filters", handle_token_filters)
        page.route("**/api/admin/control-center/activity-trends?*", handle_activity_trends)

        page.goto(f"{BASE_URL}/admin/control-center", wait_until="networkidle")
        if page.locator("#userManagementPerPageSelect").count() == 0:
            pytest.skip("Authenticated test user cannot access Control Center management tabs.")

        expected_placeholders = {
            "#userSearchInput": "Search users by name, email, or ID...",
            "#groupSearchInput": "Search groups by name, owner, or ID...",
            "#publicWorkspaceSearchInput": "Search workspaces by name, description, owner, or ID...",
        }
        for selector, expected_placeholder in expected_placeholders.items():
            expect(page.locator(selector)).to_have_attribute("placeholder", expected_placeholder)

        for select_id in [
            "userManagementPerPageSelect",
            "groupManagementPerPageSelect",
            "publicWorkspaceManagementPerPageSelect",
        ]:
            values = page.locator(f"#{select_id} option").evaluate_all(
                "options => options.map(option => option.value)"
            )
            assert values == EXPECTED_PAGE_SIZE_OPTIONS

        with page.expect_response(lambda response: "/api/admin/control-center/users?" in response.url):
            page.locator("#userManagementPerPageSelect").select_option("250")
        assert captured_queries["users"][-1].get("per_page") == ["250"]
        assert captured_queries["users"][-1].get("page") == ["1"]
        expect(page.locator("#usersPaginationInfo")).to_contain_text("of 260 users")

        page.locator("#groups-tab").click()
        with page.expect_response(lambda response: "/api/admin/control-center/groups?" in response.url):
            page.locator("#groupManagementPerPageSelect").select_option("100")
        assert captured_queries["groups"][-1].get("per_page") == ["100"]
        assert captured_queries["groups"][-1].get("page") == ["1"]
        expect(page.locator("#groupsPaginationInfo")).to_contain_text("of 260 groups")

        page.locator("#workspaces-tab").click()
        with page.expect_response(lambda response: "/api/admin/control-center/public-workspaces?" in response.url):
            page.locator("#publicWorkspaceManagementPerPageSelect").select_option("50")
        assert captured_queries["public_workspaces"][-1].get("per_page") == ["50"]
        assert captured_queries["public_workspaces"][-1].get("page") == ["1"]
        expect(page.locator("#publicWorkspacesPaginationInfo")).to_contain_text("of 260 public workspaces")
        expect(page.locator("#workspaces .card #publicWorkspacesTable.group-table")).to_be_visible()
        assert page.locator("#publicWorkspacesTable th.sortable").count() == 5
        assert page.locator("#workspaces >> text=Disable Public Workspace Creation").count() == 0
    finally:
        context.close()
        browser.close()
