# test_admin_file_sync_settings_ui.py
"""
UI test for Admin Settings File Sync management.

Version: 0.241.073
Implemented in: 0.241.073

This test ensures the Admin Settings File Sync tab renders as its own section,
uses app-role gate controls, stacks scope cards as separate rows, and opens the
admin-managed source workflow modal for a target user.
"""

import json
import os
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _assert_scope_cards_are_stacked(page):
    personal_card = page.locator('[data-testid="file-sync-personal-card"]')
    group_card = page.locator('[data-testid="file-sync-group-card"]')
    public_card = page.locator('[data-testid="file-sync-public-card"]')

    expect(personal_card).to_be_visible()
    expect(group_card).to_be_visible()
    expect(public_card).to_be_visible()

    personal_box = personal_card.bounding_box()
    group_box = group_card.bounding_box()
    public_box = public_card.bounding_box()

    assert personal_box is not None
    assert group_box is not None
    assert public_box is not None
    assert group_box["y"] > personal_box["y"] + personal_box["height"] - 1
    assert public_box["y"] > group_box["y"] + group_box["height"] - 1
    assert abs(personal_box["x"] - group_box["x"]) <= 2
    assert abs(group_box["x"] - public_box["x"]) <= 2
    assert abs(personal_box["width"] - group_box["width"]) <= 4
    assert abs(group_box["width"] - public_box["width"]) <= 4


@pytest.mark.ui
def test_admin_file_sync_tab_and_target_manager():
    """Validate the admin File Sync settings and target source manager."""
    _require_ui_env()
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    console_errors = []

    def handle_user_search(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "users": [
                    {"id": "user-1", "displayName": "Ada Lovelace", "email": "ada@example.com"}
                ]
            }),
        )

    def handle_admin_file_sync(route):
        request = route.request
        if request.method == "GET" and request.url.endswith("/sources"):
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"sources": []}))
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps({}))

    page.route("**/api/admin/file-sync/users/search**", handle_user_search)
    page.route("**/api/admin/file-sync/personal/user-1/**", handle_admin_file_sync)
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    try:
        page.goto(f"{BASE_URL}/admin/settings", wait_until="networkidle")
        if page.locator("#file-sync-tab").count() > 0:
            page.locator("#file-sync-tab").click()
        elif page.locator('.admin-nav-tab[data-tab="file-sync"]').count() > 0:
            page.locator('.admin-nav-tab[data-tab="file-sync"]').click()
        else:
            pytest.skip("Admin File Sync settings are not visible for this session.")

        file_sync_section = page.locator("#file-sync-section")
        expect(file_sync_section).to_be_visible()
        expect(page.get_by_label("Enable File Sync")).to_be_visible()
        expect(page.get_by_label("Require app role for personal sync")).to_be_visible()
        expect(page.get_by_label("Require app role for group sync")).to_be_visible()
        expect(page.get_by_label("Require app role for public sync")).to_be_visible()
        expect(file_sync_section.get_by_text("PersonalFileSyncUser").first).to_be_visible()
        expect(file_sync_section.get_by_text("GroupFileSyncUser").first).to_be_visible()
        expect(file_sync_section.get_by_text("PublicWorkspaceFileSyncUser").first).to_be_visible()
        expect(file_sync_section.get_by_text("Visible Source Types")).to_be_visible()
        expect(page.get_by_label("SMB Share")).to_be_visible()
        expect(page.get_by_label("On-prem SharePoint")).to_be_visible()
        expect(page.get_by_label("Google Workspace")).to_be_visible()
        expect(file_sync_section.get_by_text("Blocked Users")).to_have_count(0)
        expect(file_sync_section.get_by_text("Allowed Users")).to_have_count(0)
        _assert_scope_cards_are_stacked(page)

        page.get_by_role("button", name="App Role Setup").click()
        setup_modal = page.locator("#file-sync-app-role-setup-modal")
        expect(setup_modal).to_be_visible()
        expect(setup_modal.get_by_role("heading", name="File Sync App Role Setup")).to_be_visible()
        expect(setup_modal.get_by_text("PersonalFileSyncUser").first).to_be_visible()
        expect(setup_modal.get_by_text("GroupFileSyncUser").first).to_be_visible()
        expect(setup_modal.get_by_text("PublicWorkspaceFileSyncUser").first).to_be_visible()
        setup_modal.get_by_label("Close").click()
        expect(setup_modal).to_be_hidden()

        target_panel = page.locator('[data-file-sync-admin-target][data-scope="personal"]')
        target_panel.locator('[data-file-sync-admin-target-query]').fill("ada")
        target_panel.locator('[data-file-sync-admin-target-search]').click()
        expect(target_panel.get_by_text("Ada Lovelace")).to_be_visible()
        target_panel.get_by_text("Ada Lovelace").click()
        expect(target_panel.locator('[data-file-sync-admin-target-id]')).to_have_value("user-1")
        target_panel.locator('[data-file-sync-admin-target-manage]').click()

        expect(page.locator("#file-sync-admin-manager-modal")).to_be_visible()
        expect(page.get_by_role("heading", name="Sync Sources")).to_be_visible()
        expect(page.get_by_text("No sync sources configured.")).to_be_visible()
        page.locator("#file-sync-admin-manager-modal").get_by_role("button", name="Add Source").click()
        source_modal = page.locator('[data-file-sync-source-modal="true"]').last
        expect(source_modal.get_by_role("heading", name="Add Sync Source")).to_be_visible()
        expect(source_modal.get_by_text("SMB Share")).to_be_visible()
        source_modal.get_by_role("button", name="Configure Source").click()
        expect(source_modal.get_by_label("UNC path")).to_be_visible()
        source_modal.get_by_label("Close").click()
        expect(source_modal).to_be_hidden()
        assert console_errors == []
    finally:
        context.close()
        browser.close()
        playwright_context.stop()
