# test_admin_workflow_settings_access.py
"""
UI test for admin workflow access settings.
Version: 0.241.106
Implemented in: 0.241.106

This test ensures admins can see the dedicated Workflow settings section with
the personal workflow enable toggle and optional WorkflowUser role gate.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated admin Playwright storage state file.")


@pytest.mark.ui
def test_admin_workflow_settings_section(playwright):
    """Validate the Admin Settings Workflow section and role-gate controls."""
    _require_ui_env()

    from playwright.sync_api import expect

    browser = playwright.chromium.launch()
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
        expect(page.locator("#allow_user_workflows")).to_have_count(1)
        expect(page.locator("#require_member_of_workflow_user")).to_have_count(1)
    finally:
        context.close()
        browser.close()