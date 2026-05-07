# test_chat_mobile_toolbar_compaction.py
"""
UI test for compact mobile chat toolbar controls.
Version: 0.241.031
Implemented in: 0.241.031

This test ensures the chats page exposes a mobile-only tools toggle, keeps the
model, prompt, and agent selectors together inside the mobile drawer, and safely
opens and closes that drawer without throwing Bootstrap lifecycle errors while
the grounded search mobile drawer closes through its explicit footer control and
keeps the tags filter visible while it loads.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
MOBILE_VIEWPORT = {"width": 430, "height": 932}


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
def test_chat_mobile_toolbar_compaction(playwright):
    """Validate the compact mobile toolbar bottom-drawer behavior."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=MOBILE_VIEWPORT,
    )
    page = context.new_page()
    original_settings = None
    page_errors = []

    page.on("pageerror", lambda exception: page_errors.append(str(exception)))

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        original_settings = _get_user_settings(page)
        compact_toolbar_settings = dict(original_settings)
        compact_toolbar_settings["enable_agents"] = False
        assert _set_user_settings(page, compact_toolbar_settings), "Expected user settings update to succeed."

        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        tools_toggle = page.locator("#chat-mobile-tools-toggle")
        tools_panel = page.locator("#chat-mobile-tools-panel")
        tools_close = page.locator("#chat-mobile-tools-close")
        action_rail = page.locator("#chat-toolbar-mobile-tools-slot .chat-toolbar-action-rail")
        mobile_model_selector = page.locator("#chat-toolbar-mobile-primary-slot #model-select-container")

        expect(tools_toggle).to_be_visible()
        expect(mobile_model_selector).to_be_hidden()
        expect(tools_panel).to_be_hidden()
        expect(action_rail).to_be_hidden()

        tools_toggle.click()
        expect(tools_panel).to_be_visible()
        expect(action_rail).to_be_visible()
        expect(mobile_model_selector).to_be_visible()
        expect(tools_close).to_be_visible()

        tools_close.click()
        expect(tools_panel).to_be_hidden()

        search_documents_button = page.locator("#search-documents-btn")
        search_documents_panel = page.locator("#search-documents-container")
        search_documents_close = page.locator("#search-documents-mobile-close")
        tags_dropdown = page.locator("#tags-dropdown")
        tags_dropdown_button = page.locator("#tags-dropdown-button")

        if search_documents_button.count():
            search_documents_button.click()
            expect(search_documents_panel).to_be_visible()
            expect(tags_dropdown).to_be_visible()
            expect(tags_dropdown_button).to_be_visible()
            expect(search_documents_close).to_be_visible()
            search_documents_close.click()
            expect(search_documents_panel).to_be_hidden()

        prompt_button = page.locator("#search-prompts-btn")
        if prompt_button.count():
            tools_toggle.click()
            expect(tools_panel).to_be_visible()
            prompt_button.click()
            page.wait_for_function(
                """
                () => {
                    const panel = document.getElementById('chat-mobile-tools-panel');
                    const mobileSelectorSlot = document.getElementById('chat-toolbar-mobile-selectors-slot');
                    const promptContainer = document.getElementById('prompt-selection-container');
                    const promptDropdownMenu = document.getElementById('prompt-dropdown-menu');
                    if (!panel || !mobileSelectorSlot || !promptContainer) {
                        return false;
                    }
                    return panel.classList.contains('show')
                        && mobileSelectorSlot.contains(promptContainer)
                        && window.getComputedStyle(promptContainer).display !== 'none'
                        && !!promptDropdownMenu
                        && promptDropdownMenu.classList.contains('show');
                }
                """
            )
            expect(tools_panel).to_be_visible()

        assert not page_errors, f"Expected no uncaught page errors, got: {page_errors}"
    finally:
        if original_settings is not None:
            _set_user_settings(page, original_settings)
        context.close()
        browser.close()