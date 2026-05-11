# test_public_workspace_projection_non_member_ui.py
"""
UI test for public workspace projection hardening.
Version: 0.241.013
Implemented in: 0.241.013

This test ensures the public directory renders owner display names without
falling back to owner email addresses, and that non-members who open the
workspace details page see the public summary view without member-only tabs.
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


def _handle_public_workspace_projection_api(route):
    request = route.request
    parsed_url = urlparse(request.url)
    path = parsed_url.path

    if path == "/api/user/settings":
        _fulfill_json(
            route,
            {
                "settings": {
                    "publicDirectorySettings": {
                        "public-1": True,
                    }
                }
            },
        )
        return

    if path == "/api/public_workspaces/discover":
        _fulfill_json(
            route,
            [
                {
                    "id": "public-1",
                    "name": "Projection Workspace",
                    "description": "Directory summary only",
                }
            ],
        )
        return

    if path == "/api/public_workspaces/public-1":
        _fulfill_json(
            route,
            {
                "id": "public-1",
                "name": "Projection Workspace",
                "description": "Directory summary only",
                "owner": {
                    "displayName": "Directory Owner",
                },
                "status": "active",
                "heroColor": "#224466",
                "userRole": None,
                "isMember": False,
            },
        )
        return

    if path == "/api/public_workspaces/public-1/fileCount":
        _fulfill_json(route, {"fileCount": 7})
        return

    if path == "/api/public_workspaces/public-1/promptCount":
        _fulfill_json(route, {"promptCount": 3})
        return

    route.continue_()


def _require_ui_environment():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip(
            "Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file."
        )


@pytest.mark.ui
def test_public_directory_owner_display_and_non_member_workspace_fallback(playwright):
    """Validate the public directory and non-member workspace details view use the safe payload."""
    _require_ui_environment()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    page.route("**/api/user/settings", _handle_public_workspace_projection_api)
    page.route("**/api/public_workspaces*", _handle_public_workspace_projection_api)

    try:
        directory_response = page.goto(f"{BASE_URL}/public_directory", wait_until="networkidle")
        assert directory_response is not None, "Expected a navigation response when loading /public_directory."

        if directory_response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"/public_directory returned HTTP {directory_response.status} in this environment.")

        assert directory_response.ok, (
            f"Expected /public_directory to load successfully, got HTTP {directory_response.status}."
        )

        expect(page.locator("#public-directory-table tbody")).to_contain_text("Projection Workspace")
        page.locator('button.expand-btn[data-id="public-1"]').click()
        expect(page.locator("#owner-public-1")).to_have_text("Directory Owner")
        assert "@" not in page.locator("#owner-public-1").inner_text()

        manage_response = page.goto(f"{BASE_URL}/public_workspaces/public-1", wait_until="networkidle")
        assert manage_response is not None, "Expected a navigation response when loading /public_workspaces/public-1."

        if manage_response.status in SKIP_RESPONSE_CODES:
            pytest.skip(
                f"/public_workspaces/public-1 returned HTTP {manage_response.status} in this environment."
            )

        assert manage_response.ok, (
            "Expected /public_workspaces/public-1 to load successfully, "
            f"got HTTP {manage_response.status}."
        )

        expect(page.locator("#workspaceHeroName")).to_have_text("Projection Workspace")
        expect(page.locator("#workspaceOwnerName")).to_have_text("Directory Owner")
        expect(page.locator("#workspace-access-alert")).to_be_visible()
        expect(page.locator("#workspace-access-alert")).to_contain_text(
            "Membership, statistics, and workspace settings are only available to workspace members."
        )
        expect(page.locator("#membership-tab")).to_be_hidden()
        expect(page.locator("#stats-tab")).to_be_hidden()
        expect(page.locator("#settings-tab-item")).to_be_hidden()
    finally:
        context.close()
        browser.close()