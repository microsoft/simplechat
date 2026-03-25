# test_agent_modal_dual_foundry_modes.py
"""
UI test for dual Foundry agent modal modes.
Version: 0.239.154
Implemented in: 0.239.154

This test ensures that the agent modal exposes both Foundry modes and that the
mode-specific form sections toggle correctly in the browser.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_agent_modal_dual_foundry_modes(playwright):
    """Validate Foundry mode toggling in the agent modal."""
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

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        expect(page.locator("#agentModal")).to_be_attached()

        page.evaluate(
            """
            () => {
                const modalEl = document.getElementById('agentModal');
                if (!modalEl || !window.bootstrap) {
                    return;
                }
                const modal = new bootstrap.Modal(modalEl);
                modal.show();
            }
            """
        )

        expect(page.get_by_label("Foundry (classic)")).to_be_visible()
        expect(page.get_by_label("New Foundry")).to_be_visible()

        page.get_by_label("New Foundry").check()
        expect(page.locator("#agent-foundry-fetch-btn-label")).to_have_text("Fetch Applications")
        expect(page.locator("#agent-foundry-select-label")).to_have_text("New Foundry Application")
        expect(page.locator("#agent-new-foundry-only")).to_be_visible()
        expect(page.locator("#agent-classic-foundry-only")).to_be_hidden()

        page.get_by_label("Foundry (classic)").check()
        expect(page.locator("#agent-foundry-fetch-btn-label")).to_have_text("Fetch Agents")
        expect(page.locator("#agent-foundry-select-label")).to_have_text("Foundry Agent")
        expect(page.locator("#agent-classic-foundry-only")).to_be_visible()
        expect(page.locator("#agent-new-foundry-only")).to_be_hidden()
    finally:
        context.close()
        browser.close()
