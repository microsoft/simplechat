# test_control_center_public_workspace_escaping.py
"""
UI test for Control Center public workspace escaping.
Version: 0.241.007
Implemented in: 0.241.007

This test ensures malicious public workspace metadata renders as inert text
in the Control Center public workspace table instead of executing as HTML.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_control_center_public_workspace_metadata_is_escaped(playwright):
    """Validate malicious public workspace metadata renders as inert text."""
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

    workspace_name = '<img src=x onerror="window.__controlCenterNameXss = true">'
    workspace_description = '<svg onload="window.__controlCenterDescriptionXss = true"></svg>'
    owner_name = '<script>window.__controlCenterOwnerXss = true</script>'

    payload = {
        "workspaces": [
            {
                "id": "workspace-1",
                "name": workspace_name,
                "description": workspace_description,
                "owner": {
                    "displayName": owner_name,
                    "email": "owner@example.com",
                },
                "member_count": 2,
                "status": "active",
                "activity": {
                    "document_metrics": {
                        "total_documents": 1,
                        "ai_search_size": 0,
                        "storage_account_size": 0,
                    }
                },
            }
        ]
    }

    def fulfill_public_workspaces(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    try:
        page.route("**/api/admin/control-center/public-workspaces?*", fulfill_public_workspaces)

        page.goto(f"{BASE_URL}/admin/control-center", wait_until="networkidle")

        with page.expect_response(lambda response: "/api/admin/control-center/public-workspaces?" in response.url):
            if page.locator("#workspaces-tab").count() > 0:
                page.locator("#workspaces-tab").click()
            else:
                page.locator('[onclick*="workspaces-tab"]').first.click()

        table_body = page.locator("#publicWorkspacesTableBody")
        expect(table_body).to_contain_text(workspace_name)
        expect(table_body).to_contain_text(workspace_description)
        expect(table_body).to_contain_text(owner_name)
        expect(page.locator("#publicWorkspacesTableBody img[src='x']")).to_have_count(0)
        expect(page.locator("#publicWorkspacesTableBody svg")).to_have_count(0)

        flags = page.evaluate(
            """() => ({
                name: !!window.__controlCenterNameXss,
                description: !!window.__controlCenterDescriptionXss,
                owner: !!window.__controlCenterOwnerXss,
            })"""
        )
        assert flags == {"name": False, "description": False, "owner": False}
    finally:
        context.close()
        browser.close()