# test_chat_prompt_desktop_toolbar_position.py
"""
UI test for desktop chat prompt selector placement.
Version: 0.241.030
Implemented in: 0.241.025

This test ensures the prompt selector appears in the larger desktop toolbar
canvas to the left of the model selector and modifier buttons, while staying
out of the mobile-only chat toolbar controls container.
"""

import os
from pathlib import Path

import pytest

playwright_sync_api = pytest.importorskip("playwright.sync_api")
expect = playwright_sync_api.expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
DESKTOP_VIEWPORT = {"width": 1600, "height": 900}


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


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


@pytest.mark.ui
def test_chat_prompt_selector_sits_left_of_model_controls_on_desktop(playwright):
    """Validate the larger-canvas prompt selector toolbar placement."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=DESKTOP_VIEWPORT,
    )
    page = context.new_page()
    original_settings = None

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        original_settings = _get_user_settings(page)
        model_toolbar_settings = dict(original_settings)
        model_toolbar_settings["enable_agents"] = False
        assert _set_user_settings(page, model_toolbar_settings), "Expected user settings update to succeed."

        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        prompt_button = page.locator("#search-prompts-btn")
        if prompt_button.count() == 0:
            pytest.skip("Prompt selection is disabled for this environment.")

        prompt_button.click()

        prompt_container = page.locator("#prompt-selection-container")
        model_container = page.locator("#model-select-container")
        modifier_toggles = page.locator("#chat-toolbar-tools-surface .chat-toolbar-toggles")

        expect(prompt_container).to_be_visible()
        expect(model_container).to_be_visible()
        expect(modifier_toggles).to_be_visible()

        layout = page.evaluate(
            """
            () => {
                const toolsSurface = document.getElementById('chat-toolbar-tools-surface');
                const controls = document.querySelector('.chat-toolbar-controls');
                const selectorsSlot = document.getElementById('chat-toolbar-desktop-selectors-slot');
                const primarySlot = document.getElementById('chat-toolbar-desktop-primary-slot');
                const promptContainer = document.getElementById('prompt-selection-container');
                const modelContainer = document.getElementById('model-select-container');
                const toggles = toolsSurface?.querySelector('.chat-toolbar-toggles');

                const promptRect = promptContainer.getBoundingClientRect();
                const modelRect = modelContainer.getBoundingClientRect();
                const togglesRect = toggles.getBoundingClientRect();

                return {
                    promptInToolsSurface: toolsSurface.contains(promptContainer),
                    selectorsInToolsSurface: toolsSurface.contains(selectorsSlot),
                    primaryInToolsSurface: toolsSurface.contains(primarySlot),
                    promptInToolbarControls: controls.contains(promptContainer),
                    promptLeft: promptRect.left,
                    promptRight: promptRect.right,
                    promptTop: promptRect.top,
                    modelLeft: modelRect.left,
                    modelRight: modelRect.right,
                    modelTop: modelRect.top,
                    togglesLeft: togglesRect.left,
                    togglesTop: togglesRect.top,
                };
            }
            """
        )

        assert layout["promptInToolsSurface"], "Expected prompt selector inside the desktop tools surface."
        assert layout["selectorsInToolsSurface"], "Expected desktop prompt slot inside the desktop tools surface."
        assert layout["primaryInToolsSurface"], "Expected desktop model slot inside the desktop tools surface."
        assert not layout["promptInToolbarControls"], "Expected prompt selector outside chat toolbar controls."
        assert layout["promptLeft"] < layout["modelLeft"], "Expected prompt selector left of the model selector."
        assert layout["modelRight"] <= layout["togglesLeft"], "Expected modifier buttons to stay right of the model selector."
        assert abs(layout["promptTop"] - layout["modelTop"]) <= 4, "Expected prompt and model selectors on the same desktop row."
        assert abs(layout["modelTop"] - layout["togglesTop"]) <= 4, "Expected model selector and modifier buttons on the same desktop row."
    finally:
        if original_settings is not None:
            _set_user_settings(page, original_settings)
        context.close()
        browser.close()