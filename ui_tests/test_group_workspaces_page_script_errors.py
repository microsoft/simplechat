# test_group_workspaces_page_script_errors.py
"""
UI test for group workspaces page script loading.
Version: 0.241.113
Implemented in: 0.241.113

This test ensures the group workspaces page loads its inline document rendering
script without browser parse errors such as duplicate access declarations.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_group_workspaces_page_loads_without_script_parse_errors():
    """Validate /group_workspaces initializes document rendering functions."""
    _require_ui_env()
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page_errors = []

    page.on("pageerror", lambda error: page_errors.append(str(error)))

    try:
        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response for /group_workspaces."
        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Group workspace unavailable in this environment (HTTP {response.status}).")
        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        page.wait_for_function(
            """
            () => typeof renderGroupDocumentRow === 'function'
                && typeof buildGroupFolderDocumentsTable === 'function'
            """,
            timeout=10000,
        )
        assert not page_errors, f"Unexpected page script errors: {page_errors}"
    finally:
        context.close()
        browser.close()
        playwright.stop()