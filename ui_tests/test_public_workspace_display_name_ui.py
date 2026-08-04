# test_public_workspace_display_name_ui.py
"""
UI test for configurable Public Workspace end-user display names.
Version: 0.250.110
Implemented in: 0.250.110

This test ensures admins can see the Public Workspace display-name setting and
end-user pages consume the same label context.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


@pytest.mark.ui
def test_public_workspace_display_name_admin_and_directory(playwright):
    """Validate the admin field and public directory label wiring."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated admin storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/admin/settings", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response for admin settings."
        if response.status in {401, 403}:
            pytest.skip("Configured admin storage state cannot access admin settings.")
        assert response.ok, f"Expected admin settings to load, got HTTP {response.status}."

        page.get_by_role("tab", name="Workspaces").click()
        display_name_input = page.locator("#public_workspace_display_name")
        expect(display_name_input).to_be_visible()
        expect(display_name_input).to_have_attribute("maxlength", "32")
        expect(page.get_by_text("Admin settings and internal references continue to use Public Workspace.")).to_be_visible()

        label_context = page.evaluate("window.publicWorkspaceLabels")
        assert label_context["singular"], "Expected singular Public Workspace label context."
        assert label_context["max_length"] == 32

        response = page.goto(f"{BASE_URL}/public_directory", wait_until="domcontentloaded")
        if response is None or response.status in {401, 403, 404}:
            pytest.skip("Configured storage state cannot access the public directory.")
        if not response.ok:
            pytest.skip(f"Public directory unavailable in this environment: HTTP {response.status}.")

        expect(page.get_by_role("heading", name=f"{label_context['singular']} Directory")).to_be_visible()
    finally:
        context.close()
        browser.close()
