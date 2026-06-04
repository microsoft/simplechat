# test_chat_model_dropdown_width.py
"""
UI test for compact chat model and agent dropdown alignment.
Version: 0.241.126
Implemented in: 0.241.126

This test ensures that the chat model and agent searchable dropdowns remain
bounded to their compact toolbar selectors instead of expanding across the full
browser window or detaching from their trigger buttons.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
DESKTOP_VIEWPORT = {"width": 1600, "height": 900}


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_chat_model_dropdown_stays_compact_on_desktop(playwright):
    """Validate that the model dropdown menu is bounded to its toolbar selector."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=DESKTOP_VIEWPORT,
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda exception: page_errors.append(str(exception)))

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        page.evaluate(
            """
            async () => {
                window.userGroups = [];
                window.userVisiblePublicWorkspaces = [];
                window.chatModelOptions = [
                    { selection_key: 'global::endpoint-global:gpt-4o', model_id: 'gpt-4o', display_name: 'gpt-4o', deployment_name: 'gpt-4o', endpoint_id: 'endpoint-global', provider: 'aoai', scope_type: 'global', scope_id: null, scope_name: 'Global' },
                    { selection_key: 'global::endpoint-global:gpt-5.4', model_id: 'gpt-5.4', display_name: 'gpt-5.4', deployment_name: 'gpt-5.4', endpoint_id: 'endpoint-global', provider: 'aoai', scope_type: 'global', scope_id: null, scope_name: 'Global' },
                ];
                window.appSettings = {
                    ...(window.appSettings || {}),
                    enable_multi_model_endpoints: true,
                };

                const modelContainer = document.getElementById('model-select-container');
                if (modelContainer) {
                    modelContainer.style.display = 'block';
                }

                const agentContainer = document.getElementById('agent-select-container');
                if (agentContainer) {
                    agentContainer.style.display = 'none';
                }

                const modelModule = await import('/static/js/chat/chat-model-selector.js');
                await modelModule.populateModelDropdown({ preserveCurrentSelection: false });
            }
            """
        )

        model_button = page.locator("#model-dropdown-button")
        model_menu = page.locator("#model-dropdown-menu")

        expect(model_button).to_be_visible()
        model_button.click()
        expect(model_menu).to_be_visible()

        metrics = page.evaluate(
            """
            () => {
                const button = document.getElementById('model-dropdown-button');
                const menu = document.getElementById('model-dropdown-menu');
                const searchInput = document.getElementById('model-search-input');
                const buttonRect = button.getBoundingClientRect();
                const menuRect = menu.getBoundingClientRect();
                const searchRect = searchInput.getBoundingClientRect();

                return {
                    viewportWidth: window.innerWidth,
                    buttonWidth: buttonRect.width,
                    buttonLeft: buttonRect.left,
                    buttonRight: buttonRect.right,
                    menuWidth: menuRect.width,
                    menuLeft: menuRect.left,
                    menuRight: menuRect.right,
                    searchWidth: searchRect.width,
                };
            }
            """
        )

        assert metrics["menuWidth"] >= metrics["buttonWidth"] - 1, "Expected menu to be at least as wide as the model button."
        assert metrics["menuWidth"] <= 380, "Expected menu width to stay within the compact selector limit."
        assert metrics["menuWidth"] < metrics["viewportWidth"] * 0.5, "Expected menu not to span the browser window."
        assert metrics["menuLeft"] >= 0, "Expected menu to stay inside the left viewport edge."
        assert metrics["menuRight"] <= metrics["viewportWidth"] + 1, "Expected menu to stay inside the right viewport edge."
        assert metrics["menuRight"] >= metrics["buttonLeft"] - 1, "Expected menu to overlap the model button horizontally."
        assert metrics["menuLeft"] <= metrics["buttonRight"] + 1, "Expected menu to overlap the model button horizontally."
        assert min(
            abs(metrics["menuLeft"] - metrics["buttonLeft"]),
            abs(metrics["menuRight"] - metrics["buttonRight"]),
        ) <= 8, "Expected menu to stay anchored to the model button."
        assert metrics["searchWidth"] <= metrics["menuWidth"], "Expected search input to be contained by the menu."
        assert not page_errors, f"Expected no uncaught page errors, got: {page_errors}"
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_agent_dropdown_stays_anchored_on_desktop(playwright):
    """Validate that the agent dropdown menu stays aligned to its toolbar selector."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=DESKTOP_VIEWPORT,
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda exception: page_errors.append(str(exception)))

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /chats to load successfully."

        setup_result = page.evaluate(
            """
            async () => {
                const agentButton = document.getElementById('agent-dropdown-button');
                const agentSelect = document.getElementById('agent-select');
                const agentContainer = document.getElementById('agent-select-container');
                if (!agentButton || !agentSelect || !agentContainer) {
                    return { hasAgentSelector: false };
                }

                const modelContainer = document.getElementById('model-select-container');
                if (modelContainer) {
                    modelContainer.style.display = 'none';
                }
                agentContainer.style.display = 'block';

                agentSelect.innerHTML = '';
                ['Research Agent', 'Wildland Fire Risk'].forEach((label, index) => {
                    const option = document.createElement('option');
                    option.value = label.toLowerCase().replaceAll(' ', '-');
                    option.textContent = label;
                    option.selected = index === 1;
                    agentSelect.appendChild(option);
                });

                if (window.bootstrap?.Dropdown) {
                    window.bootstrap.Dropdown.getInstance(agentButton)?.dispose();
                }

                const searchableSelectModule = await import('/static/js/chat/chat-searchable-select.js');
                if (!window.__agentDropdownAlignmentController) {
                    window.__agentDropdownAlignmentController = searchableSelectModule.createSearchableSingleSelect({
                        selectEl: agentSelect,
                        dropdownEl: document.getElementById('agent-dropdown'),
                        buttonEl: agentButton,
                        buttonTextEl: agentButton.querySelector('.chat-searchable-select-text'),
                        menuEl: document.getElementById('agent-dropdown-menu'),
                        searchInputEl: document.getElementById('agent-search-input'),
                        itemsContainerEl: document.getElementById('agent-dropdown-items'),
                        placeholderText: 'Select an Agent',
                        emptyMessage: 'No agents available',
                        emptySearchMessage: 'No matching agents found',
                        dropdownConfig: searchableSelectModule.createFloatingSearchableSelectDropdownConfig(),
                    });
                }

                window.__agentDropdownAlignmentController?.refresh?.();
                agentSelect.dispatchEvent(new Event('change', { bubbles: true }));
                return { hasAgentSelector: true };
            }
            """
        )

        if not setup_result["hasAgentSelector"]:
            pytest.skip("Agents are not enabled for this environment.")

        agent_button = page.locator("#agent-dropdown-button")
        agent_menu = page.locator("#agent-dropdown-menu")

        expect(agent_button).to_be_visible()
        agent_button.click()
        expect(agent_menu).to_be_visible()

        metrics = page.evaluate(
            """
            () => {
                const button = document.getElementById('agent-dropdown-button');
                const menu = document.getElementById('agent-dropdown-menu');
                const searchInput = document.getElementById('agent-search-input');
                const buttonRect = button.getBoundingClientRect();
                const menuRect = menu.getBoundingClientRect();
                const searchRect = searchInput.getBoundingClientRect();

                return {
                    viewportWidth: window.innerWidth,
                    buttonWidth: buttonRect.width,
                    buttonLeft: buttonRect.left,
                    buttonRight: buttonRect.right,
                    menuWidth: menuRect.width,
                    menuLeft: menuRect.left,
                    menuRight: menuRect.right,
                    searchWidth: searchRect.width,
                };
            }
            """
        )

        assert metrics["menuWidth"] >= metrics["buttonWidth"] - 1, "Expected menu to be at least as wide as the agent button."
        assert metrics["menuWidth"] <= 380, "Expected menu width to stay within the compact selector limit."
        assert metrics["menuWidth"] < metrics["viewportWidth"] * 0.5, "Expected menu not to span the browser window."
        assert metrics["menuLeft"] >= 0, "Expected menu to stay inside the left viewport edge."
        assert metrics["menuRight"] <= metrics["viewportWidth"] + 1, "Expected menu to stay inside the right viewport edge."
        assert metrics["menuRight"] >= metrics["buttonLeft"] - 1, "Expected menu to overlap the agent button horizontally."
        assert metrics["menuLeft"] <= metrics["buttonRight"] + 1, "Expected menu to overlap the agent button horizontally."
        assert min(
            abs(metrics["menuLeft"] - metrics["buttonLeft"]),
            abs(metrics["menuRight"] - metrics["buttonRight"]),
        ) <= 8, "Expected menu to stay anchored to the agent button."
        assert metrics["searchWidth"] <= metrics["menuWidth"], "Expected search input to be contained by the menu."
        assert not page_errors, f"Expected no uncaught page errors, got: {page_errors}"
    finally:
        context.close()
        browser.close()