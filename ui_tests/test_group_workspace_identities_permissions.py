# test_group_workspace_identities_permissions.py
"""
UI test for group workspace identities permissions.
Version: 0.241.114
Implemented in: 0.241.114

This test ensures regular group users do not see manager-only Identities
navigation and that the identity panel renders an explicit permission message
without fetching the group identity catalog.
"""

import json
import os
import re
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_group_identities_hidden_for_regular_group_users():
    """Validate regular users get no manager identity catalog request or blank panel."""
    _require_ui_env()
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    identity_requests = []

    page.route(
        "**/api/groups?page_size=1000",
        lambda route: _fulfill_json(
            route,
            {
                "groups": [
                    {
                        "id": "regular-user-group",
                        "name": "Regular User Group",
                        "isActive": True,
                        "userRole": "User",
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
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    def capture_identity_request(route):
        identity_requests.append(route.request.url)
        _fulfill_json(route, {"error": "Insufficient permissions for this group"}, status=403)

    page.route("**/api/workspace-identities/group/identities", capture_identity_request)

    try:
        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /group_workspaces."
        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Group workspace unavailable in this environment (HTTP {response.status}).")
        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        if page.locator("#group-workspace-identities-root").count() == 0:
            pytest.skip("Group workspace identities are disabled in this environment.")

        page.wait_for_function(
            """
            () => {
                const role = document.getElementById('user-role');
                return role && role.textContent.trim() === 'User';
            }
            """,
            timeout=10000,
        )

        expect(page.locator("[data-group-identities-tab-nav]")).to_have_class(re.compile(r"\bd-none\b"))
        assert page.locator("[data-group-identities-section-option]").evaluate("option => option.hidden && option.disabled")

        sidebar_item = page.locator("[data-group-identities-sidebar-nav]")
        if sidebar_item.count() > 0:
            expect(sidebar_item).to_have_class(re.compile(r"\bd-none\b"))

        expect(page.locator("[data-workspace-identity-permission-message]")).to_have_text(
            "You do not have permission to manage or view identities for this group."
        )
        assert identity_requests == [], "Regular group users should not fetch the manager identity catalog."
    finally:
        context.close()
        browser.close()
        playwright.stop()
