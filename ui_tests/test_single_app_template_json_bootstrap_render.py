# test_single_app_template_json_bootstrap_render.py
"""
UI test for single_app template JSON bootstrap rendering.
Version: 0.240.057
Implemented in: 0.240.020

This test ensures the affected single_app pages load without browser-side
syntax errors or JSON bootstrap failures after direct `tojson` normalization.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")

SKIP_RESPONSE_CODES = {401, 403, 404}
BOOTSTRAP_ERROR_TERMS = (
    "SyntaxError",
    "Bad control character",
    "JSON.parse",
    "Unexpected token",
)


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _require_storage_state(storage_state, env_name):
    if not storage_state or not Path(storage_state).exists():
        pytest.skip(f"Set {env_name} to a valid authenticated Playwright storage state file.")


def _assert_no_bootstrap_errors(page_errors, console_errors, page_path):
    relevant_page_errors = [
        message for message in page_errors if any(term in message for term in BOOTSTRAP_ERROR_TERMS)
    ]
    relevant_console_errors = [
        message for message in console_errors if any(term in message for term in BOOTSTRAP_ERROR_TERMS)
    ]

    assert not relevant_page_errors, (
        f"Expected {page_path} to avoid bootstrap page errors. Observed: {relevant_page_errors}"
    )
    assert not relevant_console_errors, (
        f"Expected {page_path} to avoid bootstrap console errors. Observed: {relevant_console_errors}"
    )


def _load_and_check_page(context, page_path, ready_selector, expected_selectors=None):
    page = context.new_page()
    page_errors = []
    console_errors = []

    def track_page_error(error):
        page_errors.append(str(error))

    def track_console(message):
        if message.type == "error":
            console_errors.append(message.text)

    page.on("pageerror", track_page_error)
    page.on("console", track_console)

    response = page.goto(f"{BASE_URL}{page_path}", wait_until="domcontentloaded")
    assert response is not None, f"Expected a navigation response when loading {page_path}."

    if response.status in SKIP_RESPONSE_CODES:
        page.close()
        return False

    assert response.ok, f"Expected {page_path} to load successfully, got HTTP {response.status}."
    expect(page.locator(ready_selector)).to_be_visible()
    page.wait_for_load_state("networkidle")
    for selector in expected_selectors or []:
        expect(page.locator(selector)).to_be_visible()
    _assert_no_bootstrap_errors(page_errors, console_errors, page_path)
    page.close()
    return True


@pytest.mark.ui
def test_workspace_family_pages_bootstrap_cleanly(playwright):
    """Validate workspace-family pages avoid JSON bootstrap errors."""
    _require_base_url()
    _require_storage_state(STORAGE_STATE, "SIMPLECHAT_UI_STORAGE_STATE")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    checked_pages = 0
    try:
        for page_path, ready_selector in [
            ("/workspace", "#documents-tab"),
            ("/group_workspaces", "#groupWorkspaceTabContent"),
            ("/public_workspaces", "#publicWorkspaceTabContent"),
        ]:
            if _load_and_check_page(context, page_path, ready_selector):
                checked_pages += 1

        if checked_pages == 0:
            pytest.skip("No workspace-family pages were available in this environment.")
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_admin_settings_page_bootstrap_cleanly(playwright):
    """Validate admin settings avoids JSON bootstrap errors for admin users."""
    _require_base_url()
    _require_storage_state(ADMIN_STORAGE_STATE, "SIMPLECHAT_UI_ADMIN_STORAGE_STATE")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    try:
        loaded = _load_and_check_page(
            context,
            "/admin/settings",
            "#adminSettingsTabContent",
            expected_selectors=[
                "#latest-features",
                "#latest-features-model-selection-card",
                "#latest-features-citation-improvements-card",
                "#latest-features-document-versioning-card",
                "#latest-features-support-menu-card",
            ],
        )
        if not loaded:
            pytest.skip("Admin settings page was not available for the configured admin session.")
    finally:
        context.close()
        browser.close()