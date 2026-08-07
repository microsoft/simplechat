# test_chat_orchestration_interaction_modes.py
"""
UI tests for Phase 12 orchestration interaction mode controls.
Version: 0.250.127
Implemented in: 0.250.127

This test ensures that the chat composer and Admin Settings expose governed
execution mode and review visibility controls without unsafe rendering paths.
"""

import os
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
CHAT_MESSAGES_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-messages.js"
CHAT_THOUGHTS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-thoughts.js"
INTERACTION_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-orchestration-interaction.js"


def read_text(path):
    """Read a UTF-8 source file."""
    return path.read_text(encoding="utf-8")


def test_orchestration_interaction_source_contract():
    """Validate static UI wiring for Phase 12 controls."""
    chat_template = read_text(CHAT_TEMPLATE)
    admin_template = read_text(ADMIN_TEMPLATE)
    messages_source = read_text(CHAT_MESSAGES_JS)
    thoughts_source = read_text(CHAT_THOUGHTS_JS)
    interaction_source = read_text(INTERACTION_JS)

    assert 'id="orchestration-mode-container"' in chat_template
    assert 'id="orchestration-mode-dropdown-button"' in chat_template
    assert 'id="orchestration-review-visibility-toggle"' in chat_template
    assert 'id="orchestration-save-conversation-default-btn"' in chat_template
    assert 'id="orchestration-save-user-default-btn"' in chat_template
    assert 'orchestrationInteractionPolicy' in chat_template
    assert "js/chat/chat-orchestration-interaction.js" in chat_template

    assert 'id="orchestration-interaction-section"' in admin_template
    assert 'name="orchestration_execution_modes_enabled"' in admin_template
    assert 'name="orchestration_review_visibility_levels_enabled"' in admin_template
    assert "('personal', 'Personal')" in admin_template
    assert "('group', 'Group')" in admin_template
    assert "('public', 'Public')" in admin_template
    assert "('external', 'External')" in admin_template
    assert 'name="orchestration_context_modes_{{ context_name }}"' in admin_template

    assert 'getOrchestrationInteractionRequest' in messages_source
    assert 'requestPayload.orchestration_interaction = orchestrationInteraction;' in messages_source
    assert 'markOrchestrationInteractionSubmitted();' in messages_source
    assert 'review_visibility ||' in messages_source
    assert 'expanded: reviewVisibility === \'expanded\'' in messages_source

    assert 'createThoughtsToggleHtml(messageId, options = {})' in thoughts_source
    assert "options.expanded === true" in thoughts_source
    assert "loadIfNeeded(initialContainer);" in thoughts_source

    assert "optionsContainer.replaceChildren();" in interaction_source
    assert "label.textContent = EXECUTION_MODE_LABELS[mode] || mode;" in interaction_source
    assert "description.textContent = EXECUTION_MODE_DESCRIPTIONS[mode] || '';" in interaction_source
    assert "saveUserSetting({ orchestration_interaction: preference });" in interaction_source
    assert "/orchestration-interaction" in interaction_source
    assert "payload.execution_mode = getSelectedExecutionMode();" in interaction_source
    assert "payload.review_visibility = getSelectedReviewVisibility();" in interaction_source


def _chat_url():
    base_url = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
    if not base_url:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run orchestration interaction UI tests.")
    return f"{base_url}/chats"


@pytest.mark.ui
@pytest.mark.parametrize(
    "viewport",
    [
        {"width": 1280, "height": 900},
        {"width": 390, "height": 844},
    ],
)
def test_orchestration_mode_dropdown_renders_in_chat(viewport):
    """Validate the composer mode dropdown in a live authenticated browser."""
    chat_url = _chat_url()
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context_kwargs = {"viewport": viewport, "ignore_https_errors": True}
        storage_state = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "").strip()
        if storage_state:
            context_kwargs["storage_state"] = storage_state
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.goto(chat_url)

        dropdown = page.locator("#orchestration-mode-dropdown-button")
        expect(dropdown).to_be_visible()
        dropdown.click()
        expect(page.locator("#orchestration-mode-options")).to_be_visible()
        expect(page.get_by_role("button", name="Manual Ask before optional tools or artifacts.")).to_be_visible()
        expect(page.get_by_role("button", name="Balanced Use safe automation, ask when needed.")).to_be_visible()
        expect(page.get_by_role("button", name="Auto Run governed plans until approval is required.")).to_be_visible()
        page.get_by_role("button", name="Auto Run governed plans until approval is required.").click()
        expect(dropdown).to_have_text("Auto")
        expect(page.locator("#orchestration-review-visibility-toggle")).to_be_visible()

        context.close()
        browser.close()