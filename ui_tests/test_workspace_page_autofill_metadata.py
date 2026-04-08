# test_workspace_page_autofill_metadata.py
"""
UI test for workspace autofill metadata hardening.
Version: 0.240.007
Implemented in: 0.240.007

This test ensures the workspace page applies autofill ignore metadata to the
non-login controls that are rendered in hidden modals and builder surfaces.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_workspace_page_autofill_metadata(playwright):
    """Validate workspace runtime metadata for non-login modal fields."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    field_expectations = {
        "#prompt-form": {"autocomplete": "off", "data-bwignore": "true"},
        "#prompt-name": {"autocomplete": "off", "data-bwignore": "true"},
        "#doc-title": {"autocomplete": "off", "data-bwignore": "true"},
        "#newUserEmail": {"autocomplete": "off", "data-bwignore": "true"},
        "#agent-display-name": {"autocomplete": "off", "data-bwignore": "true"},
        "#plugin-display-name": {"autocomplete": "off", "data-bwignore": "true"},
        "#model-endpoint-client-secret": {"autocomplete": "new-password", "data-bwignore": "true"},
        "#model-endpoint-api-key": {"autocomplete": "new-password", "data-bwignore": "true"},
    }

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")

        assert response is not None, "Expected a navigation response when loading /workspace."
        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."
        expect(page.locator("#documents-tab")).to_be_visible()

        for selector, attributes in field_expectations.items():
            locator = page.locator(selector)
            expect(locator).to_have_count(1)
            for attribute_name, expected_value in attributes.items():
                actual_value = locator.get_attribute(attribute_name)
                assert actual_value == expected_value, (
                    f"Expected {selector} to expose {attribute_name}={expected_value!r}, got {actual_value!r}."
                )
    finally:
        context.close()
        browser.close()