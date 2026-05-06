# test_manage_public_workspace_page_load.py
"""
UI test for manage public workspace page load.
Version: 0.241.114
Implemented in: 0.241.114

This test ensures the manage public workspace page loads without JavaScript
parse errors and that pending request actions remain bound after the page
initializes.
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
def test_manage_public_workspace_loads_without_script_parse_errors(playwright):
    """Validate the manage public workspace page initializes and binds request actions."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page_errors = []
    request_actions = []
    pending_requests = [
        {
            "userId": "request-1",
            "displayName": "Requester User",
            "email": "requester@example.com",
        }
    ]

    def handle_page_error(error):
        page_errors.append(str(error))

    def handle_public_workspace_api(route):
        request = route.request
        parsed_url = urlparse(request.url)
        path = parsed_url.path

        if path == "/api/public_workspaces/public-1":
            _fulfill_json(
                route,
                {
                    "id": "public-1",
                    "name": "Manage Workspace Regression",
                    "description": "Regression coverage for the manage page script.",
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
                        "displayName": "Member User",
                        "email": "member@example.com",
                        "role": "Admin",
                    }
                ],
            )
            return

        if path == "/api/public_workspaces/public-1/requests" and request.method == "GET":
            _fulfill_json(route, pending_requests)
            return

        if path == "/api/public_workspaces/public-1/requests/request-1" and request.method == "PATCH":
            payload = json.loads(request.post_data or "{}")
            request_actions.append(payload.get("action"))
            pending_requests.clear()
            _fulfill_json(route, {"success": True})
            return

        route.continue_()

    try:
        page.on("pageerror", handle_page_error)
        page.route("**/api/public_workspaces/public-1*", handle_public_workspace_api)
        page.route(
            "**/api/retention-policy/defaults/public",
            lambda route: _fulfill_json(
                route,
                {
                    "success": True,
                    "default_conversation_label": "30 days",
                    "default_document_label": "90 days",
                },
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

        expect(page.locator("#membersTable tbody")).to_contain_text("Member User")
        expect(page.locator("#pendingRequestsTable tbody")).to_contain_text("Requester User")

        page.locator("#pendingRequestsTable .reject-request-btn").click()

        expect(page.locator("#pendingRequestsTable tbody")).not_to_contain_text("Requester User")
        assert request_actions == ["reject"], (
            "Expected the pending request reject action to be wired after page initialization."
        )
        assert page_errors == [], f"Expected no page errors while loading the manage page. Saw: {page_errors}"
    finally:
        context.close()
        browser.close()