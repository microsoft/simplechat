#!/usr/bin/env python3
# test_latest_features_action_launchers.py
"""
UI test for latest-features action launchers.
Version: 0.241.003
Implemented in: 0.241.003

This test ensures the latest-feature deep links can open the intended
workspace, profile, and chat workflows directly from their destination pages.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _get_storage_state_path() -> str:
    for candidate in (STORAGE_STATE, ADMIN_STORAGE_STATE):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_latest_features_action_launchers(playwright):
    """Validate that launch-intent links open the requested workspace, profile, and chat workflows."""
    _require_base_url()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 960},
    )

    try:
        page = context.new_page()

        workspace_response = page.goto(f"{BASE_URL}/workspace?feature_action=workspace_folder_view", wait_until="domcontentloaded")
        assert workspace_response is not None, "Expected a navigation response when loading /workspace."
        if workspace_response.status in {401, 403, 404}:
            pytest.skip("Personal Workspace page was not available for the configured session.")

        grid_radio = page.locator("#docs-view-grid")
        if grid_radio.count() == 0:
            pytest.skip("Workspace grid-view controls were not available in this environment.")

        expect(grid_radio).to_be_checked()
        expect(page.locator("#documents-grid-view")).to_be_visible()
        assert "feature_action=" not in page.url, "Workspace feature_action parameter should be consumed after launch."

        workspace_tags_response = page.goto(f"{BASE_URL}/workspace?feature_action=document_tag_system", wait_until="domcontentloaded")
        assert workspace_tags_response is not None, "Expected a navigation response when reloading /workspace."
        if workspace_tags_response.status in {401, 403, 404}:
            pytest.skip("Personal Workspace tag-management flow was not available for the configured session.")

        tag_management_modal = page.locator("#tagManagementModal")
        if tag_management_modal.count() == 0:
            pytest.skip("Workspace tag-management modal was not available in this environment.")

        expect(tag_management_modal).to_be_visible()
        assert "feature_action=" not in page.url, "Workspace tag-management feature_action parameter should be consumed after launch."

        profile_response = page.goto(f"{BASE_URL}/profile?feature_action=retention_policy#retention-policy-settings", wait_until="domcontentloaded")
        assert profile_response is not None, "Expected a navigation response when loading /profile."
        if profile_response.status in {401, 403, 404}:
            pytest.skip("Profile page was not available for the configured session.")

        retention_section = page.locator("#retention-policy-settings")
        if retention_section.count() == 0:
            pytest.skip("Retention policy settings were not enabled in this environment.")

        expect(retention_section).to_be_visible()
        expect(page.locator("#conversation_retention_days")).to_be_focused()
        assert "feature_action=" not in page.url, "Profile feature_action parameter should be consumed after launch."

        chat_response = page.goto(f"{BASE_URL}/chats?feature_action=multi_workspace_scope_management", wait_until="domcontentloaded")
        assert chat_response is not None, "Expected a navigation response when loading /chats."
        if chat_response.status in {401, 403, 404}:
            pytest.skip("Chat page was not available for the configured session.")

        search_documents_container = page.locator("#search-documents-container")
        if search_documents_container.count() == 0:
            pytest.skip("Chat grounded-search controls were not available in this environment.")

        expect(search_documents_container).to_be_visible()
        expect(page.locator("#scope-dropdown-button")).to_have_attribute("aria-expanded", "true")
        assert "feature_action=" not in page.url, "Chat feature_action parameter should be consumed after launch."
    finally:
        context.close()
        browser.close()