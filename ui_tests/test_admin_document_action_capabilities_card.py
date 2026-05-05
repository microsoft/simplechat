# test_admin_document_action_capabilities_card.py
"""
UI test for admin document action capabilities placement.
Version: 0.241.089
Implemented in: 0.241.089

This test ensures the Document Action Capabilities card is visible at the top
of the Agents and Actions tab and explains that it controls the Action
dropdown in Chat and Workflow.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "") or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_base_url() -> None:
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _require_storage_state() -> None:
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_admin_document_action_capabilities_card_is_top_of_agents_tab(playwright):
    """Validate the document action capabilities card is visible at the top of the Agents and Actions tab."""
    _require_base_url()
    _require_storage_state()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = context.new_page()
        page.add_init_script(
            """
            () => {
                sessionStorage.removeItem('adminSettingsActiveTab');
            }
            """
        )

        response = page.goto(f"{BASE_URL}/admin/settings#agents", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /admin/settings."
        if response.status in {401, 403, 404}:
            pytest.skip("Admin settings page was not available for the configured admin session.")

        assert response.ok, f"Expected /admin/settings to load successfully, got HTTP {response.status}."

        agents_tab = page.locator("#agents-tab")
        card = page.locator("#document-action-capabilities-card")
        agents_config = page.locator("#agents-configuration")

        agents_tab.click()

        expect(card).to_be_visible()
        expect(card).to_contain_text("Document Action Capabilities")
        expect(card).to_contain_text("Action")
        expect(card).to_contain_text("Chat and Workflow")
        expect(card).to_contain_text("global agent and custom action cards below")

        card_top = card.bounding_box()["y"]
        agents_config_top = agents_config.bounding_box()["y"]

        assert card_top < agents_config_top, (
            "Expected the document action capabilities card to render before the main configuration cards in the Agents and Actions tab."
        )
    finally:
        context.close()
        browser.close()