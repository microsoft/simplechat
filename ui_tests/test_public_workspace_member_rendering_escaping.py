# test_public_workspace_member_rendering_escaping.py
"""
UI test for public workspace member rendering escaping.
Version: 0.241.017
Implemented in: 0.241.017

This test ensures malicious member, request, and user-search display names and
emails render as inert text in the public workspace member-management UI.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


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
def test_public_workspace_member_management_escapes_malicious_fields(playwright):
    """Validate public workspace member-management views render malicious fields inertly."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    member_name = '<img src=x onerror="window.__publicMemberNameXss = true">'
    member_email = '<svg onload="window.__publicMemberEmailXss = true"></svg>@example.com'
    request_name = '<img src=x onerror="window.__publicRequestNameXss = true">'
    request_email = '<svg onload="window.__publicRequestEmailXss = true"></svg>@example.com'
    search_name = '<img src=x onerror="window.__publicSearchNameXss = true">'
    search_email = '<svg onload="window.__publicSearchEmailXss = true"></svg>@example.com'

    def handle_public_workspace_api(route):
        path = urlparse(route.request.url).path

        if path == "/api/public_workspaces/public-1":
            _fulfill_json(
                route,
                {
                    "id": "public-1",
                    "name": "Escaping Workspace",
                    "description": "Regression coverage",
                    "owner": {
                        "displayName": "Owner User",
                        "email": "owner@example.com",
                    },
                    "status": "active",
                    "heroColor": "#225577",
                    "userRole": "Owner",
                    "isMember": True,
                },
            )
            return

        if path == "/api/public_workspaces/public-1/members":
            _fulfill_json(
                route,
                [
                    {
                        "userId": "member-1",
                        "displayName": member_name,
                        "email": member_email,
                        "role": "Admin",
                    }
                ],
            )
            return

        if path == "/api/public_workspaces/public-1/requests":
            _fulfill_json(
                route,
                [
                    {
                        "userId": "request-1",
                        "displayName": request_name,
                        "email": request_email,
                    }
                ],
            )
            return

        route.continue_()

    try:
        page.route("**/api/public_workspaces/public-1*", handle_public_workspace_api)
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

        response = page.goto(f"{BASE_URL}/public_workspaces/public-1", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /public_workspaces/public-1."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(
                f"/public_workspaces/public-1 returned HTTP {response.status} in this environment."
            )

        assert response.ok, (
            "Expected /public_workspaces/public-1 to load successfully, "
            f"got HTTP {response.status}."
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
                memberName: !!window.__publicMemberNameXss,
                memberEmail: !!window.__publicMemberEmailXss,
                requestName: !!window.__publicRequestNameXss,
                requestEmail: !!window.__publicRequestEmailXss,
                searchName: !!window.__publicSearchNameXss,
                searchEmail: !!window.__publicSearchEmailXss,
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