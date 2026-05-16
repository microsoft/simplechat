# test_workspace_sidebar_endpoint_links.py
"""
UI test for workspace sidebar endpoint links and rounded tab shape.
Version: 0.241.014
Implemented in: 0.241.014

This test ensures that workspace tabs keep their default rounded desktop edge and that the left-nav
workspace submenus include endpoint links whenever the corresponding endpoint
tabs are enabled for personal or group workspaces.
"""

import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")
    try:
        with urlopen(BASE_URL, timeout=5):
            return
    except URLError as ex:
        pytest.skip(f"UI server is not reachable at {BASE_URL}: {ex.reason}")


def _get_user_settings(page):
    return page.evaluate(
        """
        async () => {
            const response = await fetch('/api/user/settings');
            const data = await response.json();
            return data.settings || {};
        }
        """
    )


def _set_user_settings(page, settings):
    return page.evaluate(
        """
        async (nextSettings) => {
            const response = await fetch('/api/user/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: nextSettings })
            });
            return response.ok;
        }
        """,
        settings,
    )


def _ensure_submenu_visible(page, toggle_selector, submenu_selector):
    submenu = page.locator(submenu_selector)
    if submenu.is_visible():
        return submenu

    page.locator(toggle_selector).click()
    expect(submenu).to_be_visible()
    return submenu


@pytest.mark.ui
def test_workspace_tabs_restore_default_rounded_corners(playwright):
    """Validate that workspace tabs retain the default rounded desktop corners."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    original_settings = None

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        original_settings = _get_user_settings(page)
        top_nav_settings = dict(original_settings)
        top_nav_settings["navLayout"] = "top"
        assert _set_user_settings(page, top_nav_settings), "Expected nav layout update to succeed."

        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        if page.locator("#workspaceTab").count() == 0:
            pytest.skip("Workspace tabs are not available in the current UI environment.")

        border_radius = page.evaluate(
            "() => getComputedStyle(document.getElementById('documents-tab-btn')).borderTopLeftRadius"
        )
        assert border_radius != "0px", f"Expected rounded workspace tabs, observed border radius {border_radius}."
    finally:
        if original_settings is not None:
            _set_user_settings(page, original_settings)
        context.close()
        browser.close()


@pytest.mark.ui
def test_sidebar_workspace_submenus_include_endpoint_links_when_tabs_exist(playwright):
    """Validate that sidebar workspace submenus expose endpoint links when endpoint tabs are enabled."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    original_settings = None
    found_endpoint_feature = False

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        original_settings = _get_user_settings(page)
        sidebar_settings = dict(original_settings)
        sidebar_settings["navLayout"] = "sidebar"
        assert _set_user_settings(page, sidebar_settings), "Expected nav layout update to succeed."

        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        if page.locator("#endpoints-tab-btn").count() > 0:
            found_endpoint_feature = True
            submenu = _ensure_submenu_visible(
                page,
                "[data-target='personal-workspace-submenu']",
                "#personal-workspace-submenu",
            )
            expect(submenu.get_by_text("Your Endpoints", exact=True)).to_be_visible()

        page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")
        if page.locator("#group-endpoints-tab-btn").count() > 0:
            found_endpoint_feature = True
            submenu = _ensure_submenu_visible(
                page,
                "[data-target='group-workspace-submenu']",
                "#group-workspace-submenu",
            )
            expect(submenu.get_by_text("Group Endpoints", exact=True)).to_be_visible()

        if not found_endpoint_feature:
            pytest.skip("Endpoint tabs are disabled in the current UI environment.")
    finally:
        if original_settings is not None:
            _set_user_settings(page, original_settings)
        context.close()
        browser.close()