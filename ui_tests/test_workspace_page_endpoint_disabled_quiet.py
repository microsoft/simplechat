# test_workspace_page_endpoint_disabled_quiet.py
"""
UI test for workspace endpoint-disabled UX.
Version: 0.240.005
Implemented in: 0.240.005

This test ensures a workspace page that does not expose the endpoints tab does
not request the disabled endpoint API or show the disabled-feature error.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_workspace_page_endpoint_disabled_quiet(playwright):
    """Validate that workspace loads quietly when endpoints are disabled."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    endpoint_requests = []
    console_errors = []

    def track_request(request):
        if "/api/user/model-endpoints" in request.url:
            endpoint_requests.append(request.url)

    def track_console(message):
        if message.type == "error":
            console_errors.append(message.text)

    page.on("request", track_request)
    page.on("console", track_console)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")

        assert response is not None, "Expected a navigation response when loading /workspace."
        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        if page.locator("#endpoints-tab-btn").count() > 0:
            pytest.skip("Personal endpoint management is enabled in this environment.")

        expect(page.locator("#documents-tab")).to_be_visible()
        expect(page.get_by_text("Allow User Custom Endpoints is disabled.")).to_have_count(0)
        assert endpoint_requests == [], "Expected no user model-endpoints request when the endpoints tab is hidden."
        assert not any("Failed to load endpoints" in message for message in console_errors), (
            "Expected the workspace page to avoid endpoint-load console errors when personal endpoints are disabled."
        )
    finally:
        context.close()
        browser.close()