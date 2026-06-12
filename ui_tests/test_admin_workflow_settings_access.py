# test_admin_workflow_settings_access.py
"""
UI test for admin workflow access settings.
Version: 0.241.194
Implemented in: 0.241.106
Updated in: 0.241.110
Updated in: 0.241.179
Updated in: 0.241.193
Updated in: 0.241.194

This test ensures admins can see the dedicated Workspace settings sections with
consistent app-role labels for workflow, group workflow assignment, group creation,
public workspace creation, chat file uploads, and workflow action limits.
It also verifies capacity guidance for higher workflow action limits.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = (
    os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")
    or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
)


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated admin Playwright storage state file.")


@pytest.mark.ui
def test_admin_workflow_settings_section():
    """Validate the Admin Settings Workspace app-role controls."""
    _require_ui_env()

    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/admin/settings", wait_until="domcontentloaded")
        if response is not None and response.status in {401, 403}:
            pytest.skip("Admin Settings requires an authenticated admin storage state.")

        page.locator("#workspaces-tab").click()

        workflow_section = page.locator("#workflow-settings-section")
        expect(workflow_section).to_be_visible()
        expect(workflow_section).to_contain_text("Workflow")
        expect(workflow_section).to_contain_text("Enable Personal Workflows")
        expect(workflow_section).to_contain_text("Require WorkflowUser App Role")
        expect(workflow_section).to_contain_text("WorkflowUser")
        expect(workflow_section).to_contain_text("Workflow Agent Action Limit")
        expect(workflow_section).to_contain_text("Values above 100 are capacity-sensitive")
        expect(workflow_section).to_contain_text("Enable Cosmos DB Throughput automation in SimpleChat")
        expect(workflow_section).to_contain_text("Enable Group Workflows")
        expect(workflow_section).to_contain_text("Require Group Assignment to Use Workflow")
        expect(workflow_section).to_contain_text("Group Workflow Assignments")
        expect(workflow_section).to_contain_text("Require Owner to Manage Group Agents, Actions and Workflows")
        expect(page.locator("#allow_user_workflows")).to_have_count(1)
        expect(page.locator("#require_member_of_workflow_user")).to_have_count(1)
        workflow_action_limit = page.locator("#workflow_max_auto_invoke_attempts")
        expect(workflow_action_limit).to_have_count(1)
        expect(workflow_action_limit).to_have_attribute("type", "number")
        expect(workflow_action_limit).to_have_attribute("min", "1")
        expect(workflow_action_limit).to_have_attribute("max", "500")
        expect(page.locator("#allow_group_workflows")).to_have_count(1)
        expect(page.locator("#require_group_assignment_for_group_workflows")).to_have_count(1)
        expect(page.locator("#manage-group-workflow-groups-btn")).to_have_count(1)
        expect(page.locator("#group_workflow_allowed_group_ids")).to_have_count(1)

        group_section = page.locator("#group-workspaces-section")
        public_section = page.locator("#public-workspaces-section")
        chat_upload_section = page.locator("#chat-file-uploads-section")
        expect(group_section).to_contain_text("Require CreateGroups App Role")
        expect(group_section).to_contain_text("Required app role value: CreateGroups")
        expect(public_section).to_contain_text("Require CreatePublicWorkspaces App Role")
        expect(public_section).to_contain_text("Required app role value: CreatePublicWorkspaces")
        expect(chat_upload_section).to_contain_text("Require ChatFileUploadUser App Role")
        expect(chat_upload_section).to_contain_text("Required app role value: ChatFileUploadUser")
    finally:
        context.close()
        browser.close()
        playwright_context.stop()