# test_profile_workspace_tabs.py
"""
UI test for profile workspace tabs.
Version: 0.241.031
Implemented in: 0.241.028

This test ensures authenticated users can open the profile-hosted Groups and
Public Workspaces tabs and switch between list and card views when the features
are enabled.
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


def _get_storage_state_path():
    for candidate in (STORAGE_STATE, ADMIN_STORAGE_STATE):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _assert_workspace_tab(page, tab_slug, tab_id, list_radio_id, cards_radio_id, list_view_id, card_view_id):
    response = page.goto(f"{BASE_URL}/profile?tab={tab_slug}", wait_until="domcontentloaded")
    assert response is not None, f"Expected a navigation response when loading /profile?tab={tab_slug}."
    if response.status in {401, 403, 404}:
        pytest.skip("Profile page was not available for the configured session.")

    assert response.ok, f"Expected profile tab {tab_slug} to load successfully, got HTTP {response.status}."
    tab = page.locator(f"#{tab_id}")
    if tab.count() == 0:
        return False

    expect(tab).to_be_visible()
    class_attribute = tab.get_attribute("class") or ""
    assert "active" in class_attribute, f"Expected {tab_id} to be the active tab."

    page.locator(f"#{list_radio_id}").check(force=True)
    expect(page.locator(f"#{list_view_id}")).to_be_visible()
    expect(page.locator(f"#{card_view_id}")).not_to_be_visible()

    page.locator(f"#{cards_radio_id}").check(force=True)
    expect(page.locator(f"#{card_view_id}")).to_be_visible()
    expect(page.locator(f"#{list_view_id}")).not_to_be_visible()

    return True


@pytest.mark.ui
def test_profile_workspace_tabs_support_list_and_card_views(playwright):
    """Validate the profile workspace tab list/card toggles in a browser."""
    _require_base_url()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        checked_tabs = 0
        if _assert_workspace_tab(
            page,
            "groups",
            "profile-groups-tab",
            "profile-groups-view-list",
            "profile-groups-view-cards",
            "profile-groups-list-view",
            "profile-groups-card-view",
        ):
            checked_tabs += 1

        if _assert_workspace_tab(
            page,
            "public-workspaces",
            "profile-public-workspaces-tab",
            "profile-public-workspaces-view-list",
            "profile-public-workspaces-view-cards",
            "profile-public-workspaces-list-view",
            "profile-public-workspaces-card-view",
        ):
            checked_tabs += 1

        if checked_tabs == 0:
            pytest.skip("Group and public workspace profile tabs are disabled in this environment.")
    finally:
        context.close()
        browser.close()
