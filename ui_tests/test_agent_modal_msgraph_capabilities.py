# test_agent_modal_msgraph_capabilities.py
"""
UI test for Microsoft Graph capability controls in the agent modal.
Version: 0.241.037
Implemented in: 0.241.037

This test ensures the agent modal renders per-agent capability toggles for the
Microsoft Graph action and persists those toggles into additional settings JSON.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_agent_modal_msgraph_capabilities(playwright):
    """Validate that selecting the Microsoft Graph action exposes per-agent capability toggles."""
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
                    "description": "Microsoft Graph workspace tools",
                    "is_global": False,
                    "additionalFields": {
                        "msgraph_capabilities": {
                            "get_my_profile": True,
                            "get_my_timezone": True,
                            "get_my_events": True,
                            "create_calendar_invite": True,
                            "get_my_messages": True,
                            "mark_message_as_read": True,
                            "search_users": True,
                            "get_user_by_email": True,
                            "list_drive_items": True,
                            "get_my_security_alerts": False,
                        }
                    }
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

        msgraph_card = page.locator('.action-card[data-action-type="msgraph"]')
        expect(msgraph_card).to_be_visible()
        msgraph_card.click()

        capability_panel = page.locator("#agent-msgraph-capabilities")
        expect(capability_panel).to_be_visible()
        expect(capability_panel).to_contain_text("Read my profile")
        expect(capability_panel).to_contain_text("Create calendar invites")
        expect(capability_panel).to_contain_text("Read my mail")
        expect(capability_panel).to_contain_text("Read my security alerts")

        first_checkbox = page.locator("#agent-msgraph-capabilities input[type='checkbox']").first
        first_checkbox.uncheck()

        settings_value = page.evaluate("() => document.getElementById('agent-additional-settings').value")
        assert '"action_capabilities"' in settings_value
        assert '"get_my_profile": false' in settings_value

        msgraph_card.click()
        expect(capability_panel).to_be_hidden()
    finally:
        context.close()
        browser.close()