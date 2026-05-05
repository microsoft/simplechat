# test_control_center_public_workspace_members_escaping.py
"""
UI test for Control Center public workspace member escaping.
Version: 0.241.016
Implemented in: 0.241.016

This test ensures malicious public workspace member names and emails render as
inert text in the Control Center workspace-members modal instead of executing
as HTML.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_control_center_public_workspace_member_metadata_is_escaped(playwright):
    """Validate malicious public workspace member metadata renders as inert text."""
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

    member_name = '<img src=x onerror="window.__controlCenterWorkspaceMemberNameXss = true">'
    member_email = '<svg onload="window.__controlCenterWorkspaceMemberEmailXss = true"></svg>@example.com'

    payload = {
        "success": True,
        "workspace_name": "Escaping Test Workspace",
        "members": [
            {
                "userId": "owner-1",
                "displayName": member_name,
                "email": member_email,
                "role": "owner",
            }
        ],
    }

    def fulfill_workspace_members(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    try:
        page.route(
            "**/api/admin/control-center/public-workspaces/workspace-1/members",
            fulfill_workspace_members,
        )

        page.goto(f"{BASE_URL}/admin/control-center", wait_until="networkidle")
        page.evaluate(
            """async () => {
                document.getElementById('publicWorkspaceManagementModal').setAttribute('data-workspace-id', 'workspace-1');
                document.getElementById('modalWorkspaceName').textContent = 'Escaping Test Workspace';
                await window.WorkspaceManager.loadWorkspaceMembers();
            }"""
        )

        table_body = page.locator("#workspaceMembersTableBody")
        expect(table_body).to_contain_text(member_name)
        expect(table_body).to_contain_text(member_email)
        expect(page.locator("#workspaceMembersTableBody img[src='x']")).to_have_count(0)
        expect(page.locator("#workspaceMembersTableBody svg")).to_have_count(0)

        flags = page.evaluate(
            """() => ({
                name: !!window.__controlCenterWorkspaceMemberNameXss,
                email: !!window.__controlCenterWorkspaceMemberEmailXss,
            })"""
        )
        assert flags == {"name": False, "email": False}
    finally:
        context.close()
        browser.close()