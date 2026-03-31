# test_approvals_agent_template_admin_section.py
"""
UI test for approvals page agent template admin section.
Version: 0.239.163
Implemented in: 0.239.159

This test ensures that the shared approvals page shows the agent template
approval queue for admins, keeps that section hidden for non-admin users,
and uses a Bootstrap confirmation modal for template deletion.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")
NON_ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_NON_ADMIN_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")
    if not NON_ADMIN_STORAGE_STATE or not Path(NON_ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_NON_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_approvals_agent_template_admin_section(playwright):
    """Validate admin visibility and Bootstrap delete confirmation behavior on /approvals."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    admin_context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    user_context = browser.new_context(
        storage_state=NON_ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    admin_page = admin_context.new_page()
    user_page = user_context.new_page()

    approvals_payload = {
        "success": True,
        "approvals": [],
        "total_count": 0,
        "page": 1,
        "page_size": 20,
        "total_pages": 0,
    }
    templates_payload = {
        "templates": [
            {
                "id": "template-1",
                "title": "Pending Template",
                "display_name": "Pending Template",
                "helper_text": "A pending admin review template",
                "description": "Pending admin review template",
                "status": "pending",
                "created_by_name": "Template Submitter",
                "created_by_email": "template-user@example.com",
                "updated_at": "2026-03-24T10:00:00Z",
            }
        ]
    }
    template_detail_payload = {
        "template": {
            "id": "template-1",
            "title": "Pending Template",
            "display_name": "Pending Template",
            "helper_text": "A pending admin review template",
            "description": "Pending admin review template",
            "instructions": "Review these instructions.",
            "status": "pending",
            "created_by_name": "Template Submitter",
            "created_by_email": "template-user@example.com",
            "created_at": "2026-03-24T09:00:00Z",
            "updated_at": "2026-03-24T10:00:00Z",
            "tags": ["approval"],
            "actions_to_load": []
        }
    }

    def fulfill_approvals(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(approvals_payload))

    def fulfill_templates(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(templates_payload))

    def fulfill_template_detail(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(template_detail_payload))

    try:
        dialog_seen = {"value": False}

        def on_dialog(dialog):
            dialog_seen["value"] = True
            dialog.dismiss()

        admin_page.on("dialog", on_dialog)
        admin_page.route("**/api/approvals?*", fulfill_approvals)
        admin_page.route("**/api/admin/agent-templates?*", fulfill_templates)
        admin_page.route("**/api/admin/agent-templates/template-1", fulfill_template_detail)
        admin_page.goto(f"{BASE_URL}/approvals", wait_until="networkidle")

        admin_section = admin_page.locator("#agent-template-approvals")
        expect(admin_section).to_be_visible()
        expect(admin_page.locator("#agent-template-table-body")).to_contain_text("Pending Template")

        admin_page.get_by_role("button", name="Delete").first.click()
        expect(admin_page.locator("#agentTemplateDeleteConfirmModal")).to_be_visible()
        expect(admin_page.locator("#agent-template-delete-confirm-name")).to_have_text("Pending Template")
        expect(admin_page.locator("#agentTemplateDeleteConfirmModal")).to_contain_text("This action cannot be undone.")
        assert dialog_seen["value"] is False
        admin_page.locator("#agentTemplateDeleteConfirmModal").get_by_role("button", name="Cancel").click()
        expect(admin_page.locator("#agentTemplateDeleteConfirmModal")).to_be_hidden()

        admin_page.get_by_role("button", name="View").click()
        expect(admin_page.locator("#agentTemplateReviewModal")).to_be_visible()
        admin_page.locator("#agent-template-delete-btn").click()
        expect(admin_page.locator("#agentTemplateDeleteConfirmModal")).to_be_visible()
        expect(admin_page.locator("#agentTemplateReviewModal")).to_be_hidden()
        assert dialog_seen["value"] is False
        admin_page.locator("#agentTemplateDeleteConfirmModal").get_by_role("button", name="Cancel").click()
        expect(admin_page.locator("#agentTemplateDeleteConfirmModal")).to_be_hidden()
        expect(admin_page.locator("#agentTemplateReviewModal")).to_be_visible()

        user_page.route("**/api/approvals?*", fulfill_approvals)
        user_page.goto(f"{BASE_URL}/approvals", wait_until="networkidle")

        expect(user_page.locator("#agent-template-approvals")).to_have_count(0)
    finally:
        admin_context.close()
        user_context.close()
        browser.close()