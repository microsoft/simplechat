# test_admin_app_role_settings_copy.py
"""
UI test for Admin Settings app-role copy.

Version: 0.241.110
Implemented in: 0.241.110

This test ensures admin-facing app-role settings use consistent role-value-first
labels and helper text for Control Center, workspace creation, chat uploads,
Safety Violations, and User Feedback.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = (
    os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")
    or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
)


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated admin storage state file.")


@pytest.mark.ui
def test_admin_app_role_settings_copy():
    """Validate app-role setting labels and helper text in Admin Settings."""
    _require_ui_env()
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 1000},
    )
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/admin/settings", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response for admin settings."
        if response.status in {401, 403, 404}:
            pytest.skip("Configured admin storage state cannot access admin settings.")
        assert response.ok, f"Expected admin settings to load, got HTTP {response.status}."

        page.locator("#control-center-config-tab").click()
        control_center_section = page.locator("#control-center-overview-section")
        expect(control_center_section).to_be_visible()
        expect(page.locator("label[for='require_member_of_control_center_admin']")).to_contain_text("Require ControlCenterAdmin App Role")
        expect(control_center_section).to_contain_text("Required app role value: ControlCenterAdmin")
        expect(page.locator("label[for='require_member_of_control_center_dashboard_reader']")).to_contain_text("Allow ControlCenterDashboardReader App Role")
        expect(control_center_section).to_contain_text("Dashboard-only app role value: ControlCenterDashboardReader")

        page.locator("#workspaces-tab").click()
        expect(page.locator("label[for='require_member_of_create_group']")).to_contain_text("Require CreateGroups App Role")
        expect(page.locator("#group-workspaces-section")).to_contain_text("Required app role value: CreateGroups")
        expect(page.locator("label[for='require_member_of_create_public_workspace']")).to_contain_text("Require CreatePublicWorkspaces App Role")
        expect(page.locator("#public-workspaces-section")).to_contain_text("Required app role value: CreatePublicWorkspaces")
        expect(page.locator("label[for='require_member_of_chat_file_upload_user']")).to_contain_text("Require ChatFileUploadUser App Role")
        expect(page.locator("#chat-file-uploads-section")).to_contain_text("Required app role value: ChatFileUploadUser")

        page.locator("#safety-tab").click()
        permissions_section = page.locator("#permissions-section")
        expect(permissions_section).to_be_visible()
        expect(page.locator("label[for='require_member_of_safety_violation_admin']")).to_contain_text("Require SafetyViolationAdmin App Role")
        expect(permissions_section).to_contain_text("Required app role value: SafetyViolationAdmin")
        expect(page.locator("label[for='require_member_of_feedback_admin']")).to_contain_text("Require FeedbackAdmin App Role")
        expect(permissions_section).to_contain_text("Required app role value: FeedbackAdmin")
    finally:
        context.close()
        browser.close()
        playwright.stop()