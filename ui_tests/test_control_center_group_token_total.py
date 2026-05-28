# test_control_center_group_token_total.py
"""
UI test for Control Center group token totals.
Version: 0.241.112
Implemented in: 0.241.112

This test ensures the Group Management tab renders the group token total column
and shows the same total in the group management modal.
"""

import json
import os
import re
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "") or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
TEST_GROUP_ID = "group-token-total"
TEST_TOKEN_TOTAL = 1234567


def _require_base_url() -> None:
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _require_storage_state() -> None:
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _mock_group_payload():
    return {
        "id": TEST_GROUP_ID,
        "name": "Token Total Group",
        "description": "Group with token usage for UI validation",
        "owner": {
            "displayName": "Control Center Owner",
            "email": "owner@example.com",
        },
        "owner_name": "Control Center Owner",
        "owner_email": "owner@example.com",
        "created_by": "Control Center Owner",
        "created_at": "2026-05-28T00:00:00Z",
        "createdDate": "2026-05-28T00:00:00Z",
        "member_count": 3,
        "document_count": 2,
        "status": "active",
        "users": [],
        "token_total": TEST_TOKEN_TOTAL,
        "total_tokens": TEST_TOKEN_TOTAL,
        "activity": {
            "document_metrics": {
                "total_documents": 2,
                "ai_search_size": 4096,
                "storage_account_size": 8192,
            },
            "token_metrics": {
                "total_tokens": TEST_TOKEN_TOTAL,
            },
        },
    }


@pytest.mark.ui
def test_control_center_group_management_displays_token_total():
    """Validate that group token totals render in the table and management modal."""
    _require_base_url()
    _require_storage_state()

    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    try:
        group_payload = _mock_group_payload()
        page = context.new_page()

        page.route(
            "**/api/admin/control-center/groups?**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "groups": [group_payload],
                    "pagination": {
                        "page": 1,
                        "per_page": 25,
                        "total_items": 1,
                        "total_pages": 1,
                        "has_prev": False,
                        "has_next": False,
                    },
                }),
            ),
        )
        page.route(
            f"**/api/admin/control-center/groups/{TEST_GROUP_ID}",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(group_payload),
            ),
        )
        page.route(
            f"**/api/admin/control-center/groups/{TEST_GROUP_ID}/members",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"members": []}),
            ),
        )

        response = page.goto(f"{BASE_URL}/admin/control-center", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /admin/control-center."
        if response.status in {401, 403, 404}:
            pytest.skip("Control Center was not available for the configured admin session.")
        assert response.ok, f"Expected /admin/control-center to load successfully, got HTTP {response.status}."

        page.wait_for_function("() => window.controlCenter && typeof window.controlCenter.loadGroups === 'function'")
        page.evaluate(
            """
            async () => {
                const groupsPane = document.getElementById('groups');
                if (groupsPane) {
                    groupsPane.classList.add('show', 'active');
                }
                await window.controlCenter.loadGroups();
            }
            """
        )

        groups_table = page.locator("#groupsTable")
        first_group_row = page.locator("#groupsTableBody tr").first

        expect(groups_table.locator("thead")).to_contain_text("Token Total")
        expect(first_group_row).to_contain_text("Token Total Group")
        expect(first_group_row).to_contain_text("1,234,567 tokens")

        first_group_row.get_by_role("button", name=re.compile("Manage", re.IGNORECASE)).click()
        expect(page.locator("#modalGroupTokens")).to_contain_text("1,234,567 tokens")
    finally:
        context.close()
        browser.close()
        playwright_context.stop()