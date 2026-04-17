# test_agent_modal_simplechat_capabilities.py
"""
UI test for SimpleChat capability controls in the agent modal.
Version: 0.241.023
Implemented in: 0.241.023

This test ensures the agent modal renders per-agent capability toggles for the
SimpleChat action and persists those toggles into additional settings JSON.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_agent_modal_simplechat_capabilities(playwright):
    """Validate that selecting the SimpleChat action exposes per-agent capability toggles."""
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

    page.route(
        "**/api/user/plugins",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([
                {
                    "id": "simplechat-action-id",
                    "name": "simplechat_tools",
                    "display_name": "Simple Chat Tools",
                    "type": "simplechat",
                    "description": "SimpleChat native workspace tools",
                    "is_global": False,
                },
                {
                    "id": "msgraph-action-id",
                    "name": "msgraph_tools",
                    "display_name": "Microsoft Graph Tools",
                    "type": "msgraph",
                    "description": "Reference action to keep the action list mixed",
                    "is_global": False,
                },
            ]),
        ),
    )

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        expect(page.locator("#agentModal")).to_be_attached()
        page.wait_for_function("() => window.agentModalStepper && typeof window.agentModalStepper.showModal === 'function'")

        page.evaluate(
            """
            async () => {
                await window.agentModalStepper.showModal();
                window.agentModalStepper.goToStep(4);
            }
            """
        )

        simplechat_card = page.locator('.action-card[data-action-type="simplechat"]')
        expect(simplechat_card).to_be_visible()
        simplechat_card.click()

        capability_panel = page.locator("#agent-simplechat-capabilities")
        expect(capability_panel).to_be_visible()
        expect(capability_panel).to_contain_text("Create groups")
        expect(capability_panel).to_contain_text("Create personal conversations")

        first_checkbox = page.locator("#agent-simplechat-capabilities input[type='checkbox']").first
        first_checkbox.uncheck()

        settings_value = page.evaluate("() => document.getElementById('agent-additional-settings').value")
        assert '"action_capabilities"' in settings_value
        assert '"create_group": false' in settings_value

        simplechat_card.click()
        expect(capability_panel).to_be_hidden()
    finally:
        context.close()
        browser.close()