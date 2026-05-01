# test_workspace_simplechat_action_modal.py
"""
UI test for the workspace SimpleChat action modal.
Version: 0.241.038
Implemented in: 0.241.038

This test ensures users can select the SimpleChat action type, configure its
default capabilities without a URL field, review the capability summary,
and complete validation plus save without calling the admin-only validation
endpoint.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_workspace_simplechat_action_modal(playwright):
    """Validate the workspace action modal exposes the dedicated SimpleChat flow."""
    _require_ui_env()

    validation_requests = []
    admin_validation_requests = []
    saved_payloads = []

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    def handle_plugins(route):
        request = route.request
        if request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body="[]")
            return

        saved_payloads.append(json.loads(request.post_data or "[]"))
        route.fulfill(status=200, content_type="application/json", body='{"success": true}')

    def handle_validation(route):
        validation_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"valid": true, "errors": [], "warnings": []}',
        )

    def handle_admin_validation(route):
        admin_validation_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=418,
            content_type="application/json",
            body='{"error": "unexpected admin validation route"}',
        )

    page.route("**/api/user/plugins", handle_plugins)
    page.route("**/api/plugins/validate", handle_validation)
    page.route("**/api/admin/plugins/validate", handle_admin_validation)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /workspace."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."
        expect(page.locator("#documents-tab")).to_be_visible()

        plugins_tab_button = page.locator("#plugins-tab-btn")
        if plugins_tab_button.count() == 0:
            pytest.skip("Workspace actions are not enabled in this environment.")

        plugins_tab_button.click()

        create_button = page.locator("#create-plugin-btn")
        if create_button.count() == 0:
            pytest.skip("Workspace action creation is not available in this environment.")

        expect(create_button).to_be_visible()
        create_button.click()

        modal = page.locator("#plugin-modal")
        expect(modal).to_be_visible()

        simplechat_card = page.locator('.action-type-card[data-type="simplechat"]')
        expect(simplechat_card).to_have_count(1)
        simplechat_card.click()

        modal.get_by_role("button", name="Next").click()
        page.locator("#plugin-display-name").fill("SimpleChat Workspace Tools")
        modal.get_by_role("button", name="Next").click()

        expect(page.locator("#simplechat-config-section")).to_be_visible()
        expect(page.locator("#generic-config-section")).to_be_hidden()
        expect(page.locator("#sql-config-section")).to_be_hidden()
        expect(page.locator("#cosmos-config-section")).to_be_hidden()
        expect(page.locator("#simplechat-config-section")).to_contain_text("does not require a URL or external credentials")

        create_group_toggle = page.locator("#simplechat-capability-create_group")
        add_group_member_toggle = page.locator("#simplechat-capability-add_group_member")
        make_group_inactive_toggle = page.locator("#simplechat-capability-make_group_inactive")
        invite_group_conversation_members_toggle = page.locator("#simplechat-capability-invite_group_conversation_members")
        add_conversation_message_toggle = page.locator("#simplechat-capability-add_conversation_message")
        upload_markdown_document_toggle = page.locator("#simplechat-capability-upload_markdown_document")
        create_personal_workflow_toggle = page.locator("#simplechat-capability-create_personal_workflow")
        create_group_toggle.uncheck()
        add_group_member_toggle.uncheck()
        expect(make_group_inactive_toggle).to_be_checked()
        expect(invite_group_conversation_members_toggle).to_be_checked()
        expect(add_conversation_message_toggle).to_be_checked()
        expect(upload_markdown_document_toggle).to_be_checked()
        expect(create_personal_workflow_toggle).to_be_checked()

        page.locator("#plugin-modal-skip").click()

        expect(page.locator("#summary-simplechat-section")).to_be_visible()
        expect(page.locator("#summary-plugin-database-type")).to_have_text("Built-in SimpleChat action")
        expect(page.locator("#summary-plugin-endpoint-row")).to_be_hidden()
        expect(page.locator("#summary-simplechat-enabled-list")).to_contain_text("Make groups inactive")
        expect(page.locator("#summary-simplechat-enabled-list")).to_contain_text("Create group multi-user conversations")
        expect(page.locator("#summary-simplechat-enabled-list")).to_contain_text("Invite group conversation members")
        expect(page.locator("#summary-simplechat-enabled-list")).to_contain_text("Add conversation messages")
        expect(page.locator("#summary-simplechat-enabled-list")).to_contain_text("Upload markdown documents")
        expect(page.locator("#summary-simplechat-enabled-list")).to_contain_text("Create personal conversations")
        expect(page.locator("#summary-simplechat-enabled-list")).to_contain_text("Create personal workflows")
        expect(page.locator("#summary-simplechat-disabled-list")).to_contain_text("Create groups")
        expect(page.locator("#summary-simplechat-disabled-list")).to_contain_text("Add users to groups")

        modal.get_by_role("button", name="Save Action").click()

        expect(modal).to_be_hidden()
        assert len(validation_requests) == 1, "Expected the shared validation endpoint to be called once."
        assert not admin_validation_requests, "Workspace action save should not call the admin validation endpoint."
        assert len(saved_payloads) == 1, "Expected the workspace action save request to be submitted once."

        saved_plugin = saved_payloads[0][0]
        assert saved_plugin["type"] == "simplechat"
        assert saved_plugin["name"] == "simplechat_workspace_tools"
        capabilities = saved_plugin["additionalFields"]["simplechat_capabilities"]
        assert capabilities["create_group"] is False
        assert capabilities["add_group_member"] is False
        assert capabilities["make_group_inactive"] is True
        assert capabilities["create_group_conversation"] is True
        assert capabilities["invite_group_conversation_members"] is True
        assert capabilities["add_conversation_message"] is True
        assert capabilities["upload_markdown_document"] is True
        assert capabilities["create_personal_workflow"] is True
    finally:
        context.close()
        browser.close()