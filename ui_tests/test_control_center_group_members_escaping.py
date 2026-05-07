# test_control_center_group_members_escaping.py
"""
UI test for Control Center group member escaping.
Version: 0.241.010
Implemented in: 0.241.010

This test ensures malicious group member names and emails render as inert text
in the Control Center group-members modal instead of executing as HTML.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_control_center_group_member_metadata_is_escaped(playwright):
    """Validate malicious group member metadata renders as inert text."""
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

    member_name = '<img src=x onerror="window.__controlCenterMemberNameXss = true">'
    member_email = '<svg onload="window.__controlCenterMemberEmailXss = true"></svg>@example.com'

    payload = {
        "id": "group-1",
        "name": "Escaping Test Group",
        "owner": {
            "id": "owner-1",
            "displayName": "Owner",
            "email": "owner@example.com",
        },
        "admins": [],
        "documentManagers": [],
        "users": [
            {
                "userId": "member-1",
                "displayName": member_name,
                "email": member_email,
            }
        ],
    }

    def fulfill_group_details(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    try:
        page.route("**/api/admin/control-center/groups/group-1", fulfill_group_details)

        page.goto(f"{BASE_URL}/admin/control-center", wait_until="networkidle")
        page.evaluate(
            """async () => {
                document.getElementById('groupManagementModal').setAttribute('data-group-id', 'group-1');
                await window.GroupManager.loadGroupMembers();
            }"""
        )

        table_body = page.locator("#groupMembersTableBody")
        expect(table_body).to_contain_text(member_name)
        expect(table_body).to_contain_text(member_email)
        expect(page.locator("#groupMembersTableBody img[src='x']")).to_have_count(0)
        expect(page.locator("#groupMembersTableBody svg")).to_have_count(0)

        flags = page.evaluate(
            """() => ({
                name: !!window.__controlCenterMemberNameXss,
                email: !!window.__controlCenterMemberEmailXss,
            })"""
        )
        assert flags == {"name": False, "email": False}
    finally:
        context.close()
        browser.close()