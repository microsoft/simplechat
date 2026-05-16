# test_approvals_requester_action_buttons.py
"""
UI test for approval requester action boundaries.
Version: 0.241.030
Implemented in: 0.241.030

This test ensures a requester viewing their own pending approval request can
deny the request but cannot approve and execute it.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_approval_requester_can_deny_but_not_approve(playwright):
    """Validate requester-owned pending approvals show Deny without Approve."""
    _require_ui_env()

    approval = {
        "id": "approval-1",
        "group_id": "target-user",
        "group_name": "Target User",
        "request_type": "delete_user_documents",
        "status": "pending",
        "requester_id": "requesting-admin",
        "requester_name": "Requesting Admin",
        "requester_email": "admin@example.com",
        "created_at": "2026-05-16T15:35:38Z",
        "reason": "Cancel if needed",
        "can_approve": False,
        "can_deny": True,
    }
    approvals_payload = {
        "success": True,
        "approvals": [approval],
        "total_count": 1,
        "page": 1,
        "page_size": 20,
        "total_pages": 1,
    }

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1280, "height": 900},
    )
    page = context.new_page()

    try:
        page.route(
            "**/api/approvals?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(approvals_payload),
            ),
        )
        page.route(
            "**/api/approvals/approval-1?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(approval),
            ),
        )

        page.goto(f"{BASE_URL}/approvals", wait_until="networkidle")
        page.get_by_role("button", name="View").click()

        expect(page.locator("#approvalActionModal")).to_be_visible()
        expect(page.locator("#approvalDenyBtn")).to_be_visible()
        expect(page.locator("#approvalApproveBtn")).to_be_hidden()
        expect(page.locator("#approvalActionComment")).to_be_visible()
        expect(page.locator("#approvalActionComment")).to_have_attribute("required", "")
        expect(page.locator("#approvalCommentRequired")).to_be_visible()
        expect(page.locator("#cannotApproveAlert")).to_be_hidden()
    finally:
        context.close()
        browser.close()