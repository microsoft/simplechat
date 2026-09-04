# test_voice_assisted_form_inputs.py
"""
UI test for voice-assisted form input controls.
Version: 0.250.028
Implemented in: 0.241.177; 0.250.028

This test ensures speech-to-text enabled workspaces render voice controls for
agent authoring, workflow authoring, action authoring, document metadata, and
tag name fields without requiring live microphone capture or Azure Speech calls.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_voice_assisted_workspace_controls():
    """Validate voice controls render on speech-enabled workspace forms."""
    _require_ui_env()

    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError:
        pytest.skip("Install Playwright to run this UI test.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        try:
            response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
            assert response is not None and response.ok, "Expected /workspace to load successfully."

            speech_enabled = page.evaluate(
                "Boolean(window.appSettings?.enable_speech_to_text_input && window.SimpleChatVoiceInput)"
            )
            if not speech_enabled:
                pytest.skip("Speech-to-text input is disabled for this UI environment.")

            expected_fields = [
                "#agent-display-name",
                "#agent-description",
                "#agent-instruction-brief",
                "#doc-title",
                "#doc-abstract",
                "#doc-keywords",
                "#new-tag-name",
            ]
            optional_fields = [
                "#workflow-name",
                "#workflow-description",
                "#workflow-task-brief",
                "#workflow-task-prompt",
                "#plugin-display-name",
                "#plugin-name",
                "#plugin-description",
            ]
            expected_fields.extend(
                selector for selector in optional_fields if page.locator(selector).count() > 0
            )
            missing = page.evaluate(
                """
                (selectors) => selectors.filter((selector) => {
                    const field = document.querySelector(selector);
                    if (!field) return true;
                    const inputGroupButton = field.closest('.input-group')?.querySelector('.simplechat-voice-input-btn');
                    const nextToolbarButton = field.nextElementSibling?.querySelector?.('.simplechat-voice-input-btn');
                    return !(inputGroupButton || nextToolbarButton);
                })
                """,
                expected_fields,
            )
            assert missing == [], f"Expected voice input buttons for fields: {missing}"

            expect(page.locator("#agent-draft-instructions-btn")).to_have_count(1)
            expect(page.locator("#agent-instruction-brief")).to_have_count(1)
            if page.locator("#workflow-task-brief").count() > 0:
                expect(page.locator("#workflow-draft-instructions-btn")).to_have_count(1)
                expect(page.locator("#workflow-task-brief")).to_have_count(1)
                expect(page.locator("label[for='workflow-task-prompt']")).to_have_text("Workflow or Task Instructions")
        finally:
            context.close()
            browser.close()