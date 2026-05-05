# test_group_workspace_member_rendering_escaping.py
"""
UI test for group workspace member rendering escaping.
Version: 0.241.017
Implemented in: 0.241.017

This test ensures malicious member, request, and user-search display names and
emails render as inert text in the group workspace member-management UI.
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


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_group_workspace_member_management_escapes_malicious_fields(playwright):
    """Validate group workspace member-management views render malicious fields inertly."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    member_name = '<img src=x onerror="window.__groupMemberNameXss = true">'
    member_email = '<svg onload="window.__groupMemberEmailXss = true"></svg>@example.com'
    request_name = '<img src=x onerror="window.__groupRequestNameXss = true">'
    request_email = '<svg onload="window.__groupRequestEmailXss = true"></svg>@example.com'
    search_name = '<img src=x onerror="window.__groupSearchNameXss = true">'
    search_email = '<svg onload="window.__groupSearchEmailXss = true"></svg>@example.com'

    try:
        page.route(
            "**/api/groups?page_size=1000",
            lambda route: _fulfill_json(
                route,
                {
                    "groups": [
                        {
                            "id": "group-alpha",
                            "name": "Escaping Group",
                            "isActive": True,
                            "userRole": "Owner",
                            "status": "active",
                        }
                    ]
                },
            ),
        )
        page.route(
            "**/api/group_documents?*",
            lambda route: _fulfill_json(
                route,
                {
                    "documents": [],
                    "page": 1,
                    "page_size": 10,
                    "total_count": 0,
                },
            ),
        )
        page.route(
            "**/api/group_documents/tags?*",
            lambda route: _fulfill_json(route, {"tags": []}),
        )
        page.route(
            "**/api/groups/group-alpha/members*",
            lambda route: _fulfill_json(
                route,
                [
                    {
                        "userId": "member-1",
                        "displayName": member_name,
                        "email": member_email,
                        "role": "Admin",
                    }
                ],
            ),
        )
        page.route(
            "**/api/groups/group-alpha/requests*",
            lambda route: _fulfill_json(
                route,
                [
                    {
                        "userId": "request-1",
                        "displayName": request_name,
                        "email": request_email,
                    }
                ],
            ),
        )
        page.route(
            "**/api/userSearch*",
            lambda route: _fulfill_json(
                route,
                [
                    {
                        "id": "search-1",
                        "displayName": search_name,
                        "email": search_email,
                    }
                ],
            ),
        )

        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")

        assert response is not None, "Expected a navigation response when loading /group_workspaces."
        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        page.evaluate(
            """() => {
                if (typeof loadMembers === 'function') {
                    loadMembers();
                }
                if (typeof loadPendingRequests === 'function') {
                    loadPendingRequests();
                }
            }"""
        )

        expect(page.locator("#membersTable tbody")).to_contain_text(member_name)
        expect(page.locator("#membersTable tbody")).to_contain_text(member_email)
        expect(page.locator("#membersTable tbody img[src='x']")).to_have_count(0)
        expect(page.locator("#membersTable tbody svg")).to_have_count(0)

        expect(page.locator("#pendingRequestsTable tbody")).to_contain_text(request_name)
        expect(page.locator("#pendingRequestsTable tbody")).to_contain_text(request_email)
        expect(page.locator("#pendingRequestsTable tbody img[src='x']")).to_have_count(0)
        expect(page.locator("#pendingRequestsTable tbody svg")).to_have_count(0)

        page.locator("#addMemberBtn").click()
        page.locator("#userSearchTerm").fill("search")
        page.locator("#searchUsersBtn").click()

        expect(page.locator("#userSearchResultsTable tbody")).to_contain_text(search_name)
        expect(page.locator("#userSearchResultsTable tbody")).to_contain_text(search_email)
        expect(page.locator("#userSearchResultsTable tbody img[src='x']")).to_have_count(0)
        expect(page.locator("#userSearchResultsTable tbody svg")).to_have_count(0)

        page.locator("#userSearchResultsTable tbody .select-user-btn").click()
        expect(page.locator("#newUserDisplayName")).to_have_value(search_name)
        expect(page.locator("#newUserEmail")).to_have_value(search_email)

        flags = page.evaluate(
            """() => ({
                memberName: !!window.__groupMemberNameXss,
                memberEmail: !!window.__groupMemberEmailXss,
                requestName: !!window.__groupRequestNameXss,
                requestEmail: !!window.__groupRequestEmailXss,
                searchName: !!window.__groupSearchNameXss,
                searchEmail: !!window.__groupSearchEmailXss,
            })"""
        )
        assert flags == {
            "memberName": False,
            "memberEmail": False,
            "requestName": False,
            "requestEmail": False,
            "searchName": False,
            "searchEmail": False,
        }
    finally:
        context.close()
        browser.close()