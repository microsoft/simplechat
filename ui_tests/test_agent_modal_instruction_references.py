# test_agent_modal_instruction_references.py
"""
UI test for the agent modal Instructions step reference workflow.

Version: 0.250.209
Implemented in: 0.250.209

This test ensures that the agent modal presents Instructions after Actions and
Assigned Knowledge, that the Instructions step summarizes what was selected, and
that the "#" autocomplete inserts #action: and #knowledge: reference tokens with
keyboard and mouse interaction.

Refs: https://github.com/microsoft/simplechat/issues/1257
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")

PLUGINS_RESPONSE = [
    {
        "id": "simplechat-action-id",
        "name": "simplechat_tools",
        "display_name": "Simple Chat Tools",
        "type": "simplechat",
        "description": "SimpleChat native workspace tools",
        "is_global": False,
    },
    {
        "id": "weather-action-id",
        "name": "weather_api",
        "display_name": "Weather API",
        "type": "openapi",
        "description": "Reference action without sub-capabilities",
        "is_global": False,
    },
]

ASSIGNED_KNOWLEDGE_CATALOG = {
    "sources": [{"scope": "personal", "id": "personal", "label": "Personal workspace"}],
    "documents": [
        {
            "id": "handbook-doc",
            "file_name": "Employee Handbook.pdf",
            "title": "Employee Handbook.pdf",
            "scope": "personal",
            "source_id": "personal",
            "source_name": "Personal workspace",
            "tags": ["policy"],
        }
    ],
    "tags": ["policy"],
}


def _register_routes(page):
    page.route(
        "**/api/user/plugins",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(PLUGINS_RESPONSE),
        ),
    )
    page.route(
        "**/api/agents/assigned-knowledge/catalog*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(ASSIGNED_KNOWLEDGE_CATALOG),
        ),
    )


def _open_modal_at(page, step_key):
    page.evaluate(
        """
        async (stepKey) => {
            if (!window.agentModalStepper.isEditMode) {
                await window.agentModalStepper.showModal();
            }
            window.agentModalStepper.goToStep(window.agentModalStepper.getStepNumber(stepKey));
        }
        """,
        step_key,
    )


@pytest.mark.ui
def test_agent_modal_instruction_references(playwright):
    """Validate the reordered Instructions step and its "#" reference autocomplete."""
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
    console_errors = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)

    _register_routes(page)

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        expect(page.locator("#agentModal")).to_be_attached()
        page.wait_for_function(
            "() => window.agentModalStepper && typeof window.agentModalStepper.showModal === 'function'"
        )

        # --- Step order -------------------------------------------------
        page.evaluate("async () => { await window.agentModalStepper.showModal(); }")
        step_labels = page.evaluate(
            "() => Array.from(document.querySelectorAll('#agentModal .step-label')).map(el => el.textContent.trim())"
        )
        assert step_labels == [
            "Basic Info",
            "Model & Connection",
            "Actions",
            "Knowledge",
            "Instructions",
            "Advanced",
            "Summary",
        ], step_labels

        # --- Select an action with capabilities -------------------------
        _open_modal_at(page, "actions")
        simplechat_card = page.locator('.action-card[data-action-type="simplechat"]')
        expect(simplechat_card).to_be_visible()
        simplechat_card.click()
        expect(page.locator("#agent-simplechat-capabilities")).to_be_visible()

        weather_card = page.locator('.action-card[data-action-id="weather-action-id"]')
        weather_card.click()

        # --- Assign knowledge -------------------------------------------
        _open_modal_at(page, "knowledge")
        knowledge_toggle = page.locator("#agent-assigned-knowledge-enabled")
        expect(knowledge_toggle).to_be_visible()
        knowledge_toggle.check()
        expect(page.locator("#agent-assigned-knowledge-controls")).to_be_visible()

        # --- Instructions step reference panel ---------------------------
        _open_modal_at(page, "instructions")
        expect(page.locator("#agent-instructions-container")).to_be_visible()

        context_panel = page.locator("#agent-instructions-context-panel")
        expect(context_panel).to_be_visible()
        expect(page.locator("#agent-instructions-context-actions-count")).to_contain_text("2 actions")

        # The panel body is collapsed until the author opens it.
        expect(page.locator("#agent-instructions-context-body")).to_be_hidden()
        page.locator("#agent-instructions-context-toggle").click()
        expect(page.locator("#agent-instructions-context-body")).to_be_visible()

        actions_list = page.locator("#agent-instructions-context-actions")
        expect(actions_list).to_contain_text("Simple Chat Tools")
        expect(actions_list).to_contain_text("Weather API")
        expect(actions_list).to_contain_text("create_group")

        knowledge_list = page.locator("#agent-instructions-context-knowledge")
        expect(knowledge_list).to_contain_text("Personal workspace")

        # --- "#" autocomplete in the Instruction Brief -------------------
        brief = page.locator("#agent-instruction-brief")
        brief.click()
        brief.type("Use #")

        menu = page.locator(".agent-mention-menu")
        expect(menu).to_be_visible()
        expect(menu).to_have_attribute("role", "listbox")
        expect(menu).to_contain_text("action")
        expect(menu).to_contain_text("knowledge")

        # Keyboard drill-down: namespace -> action -> capability.
        page.keyboard.press("Enter")
        expect(menu).to_contain_text("Simple Chat Tools")
        page.keyboard.press("Enter")
        expect(menu).to_contain_text("create_group")
        page.keyboard.press("Enter")

        brief_value = brief.input_value()
        assert brief_value.startswith("Use #action:"), brief_value
        assert "create_group" in brief_value, brief_value
        expect(menu).to_be_hidden()

        # Escape dismisses the menu without inserting anything.
        brief.type(" and #")
        expect(menu).to_be_visible()
        page.keyboard.press("Escape")
        expect(menu).to_be_hidden()

        # --- "#knowledge:" resolves assigned documents --------------------
        brief.fill("")
        brief.type("Search #knowledge:")
        expect(menu).to_be_visible()
        expect(menu).to_contain_text("Employee Handbook.pdf")
        expect(menu).to_contain_text("document")

        # A document title with spaces stays searchable.
        brief.type("Employee Hand")
        expect(menu).to_be_visible()
        expect(menu).to_contain_text("Employee Handbook.pdf")

        # Mouse selection inserts the quoted token.
        menu.locator(".agent-mention-menu-item").first.click()
        assert brief.input_value().strip() == 'Search #knowledge:doc:"Employee Handbook.pdf"', brief.input_value()
        expect(menu).to_be_hidden()

        # --- "#" autocomplete in the markdown instructions editor ---------
        editor_area = page.locator("#agent-instructions-container .CodeMirror textarea")
        if editor_area.count():
            page.locator("#agent-instructions-container .CodeMirror").click()
            page.keyboard.type("Use #")
            expect(menu).to_be_visible()
            page.keyboard.press("Escape")
            expect(menu).to_be_hidden()

        assert not console_errors, f"Unexpected console errors: {console_errors}"
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_agent_modal_instruction_references_hidden_for_foundry(playwright):
    """Foundry agents manage instructions in Foundry, so the references stay inert."""
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

    _register_routes(page)

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        expect(page.locator("#agentModal")).to_be_attached()
        page.wait_for_function(
            "() => window.agentModalStepper && typeof window.agentModalStepper.showModal === 'function'"
        )

        page.evaluate("async () => { await window.agentModalStepper.showModal(); }")
        page.locator("#agent-type-new-foundry").check()
        _open_modal_at(page, "instructions")

        expect(page.locator("#agent-instructions-foundry-note")).to_be_visible()
        expect(page.locator("#agent-instructions-container")).to_be_hidden()
        expect(page.locator("#agent-instructions-context-panel")).to_be_hidden()

        # No mention menu should ever be rendered for a Foundry agent.
        assert page.locator(".agent-mention-menu:not(.d-none)").count() == 0
    finally:
        context.close()
        browser.close()
