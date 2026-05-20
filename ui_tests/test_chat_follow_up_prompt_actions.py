# test_chat_follow_up_prompt_actions.py
"""
UI test for chat follow-up prompt actions.
Version: 0.241.051
Implemented in: 0.241.050

This test ensures assistant suggested next steps can appear as buttons and stage
a prompt in the chat input with a send countdown affordance, while capping the
button set and removing duplicate suggestion text from the message body.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
CHAT_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_chat_follow_up_prompt_actions_render_without_duplicate_source_text():
    """Validate capped follow-up prompt actions on a configured chat page."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if CHAT_STORAGE_STATE and not Path(CHAT_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated storage state file.")
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context_kwargs = {"viewport": {"width": 1440, "height": 1000}}
    if CHAT_STORAGE_STATE:
        context_kwargs["storage_state"] = CHAT_STORAGE_STATE
    context = browser.new_context(**context_kwargs)
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response for chat."
        if response.status in {401, 403, 404}:
            pytest.skip("Configured storage state cannot access chat.")
        assert response.ok, f"Expected chat to load, got HTTP {response.status}."

        suggestions = page.evaluate(
            """
            async () => {
                const chatbox = document.querySelector('#chatbox');
                if (!chatbox) {
                    throw new Error('chatbox not found');
                }

                const chatMessages = await import('/static/js/chat/chat-messages.js');
                const markdown = `Bottom line

Suggested follow-ups:
- A shorter 5-slide executive deck
- A more polished board-style version
- A copy-paste outline with speaker notes
- A VBA script that creates the slides`;

                document.querySelectorAll('.assistant-follow-up-actions').forEach(element => element.remove());
                const existingMessage = document.querySelector('[data-message-id="test-follow-up-question-message"]');
                if (existingMessage) {
                    existingMessage.remove();
                }

                chatMessages.appendMessage(
                    'AI',
                    markdown,
                    null,
                    'test-follow-up-question-message',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    { id: 'test-follow-up-question-message', role: 'assistant', content: markdown },
                    true
                );

                return chatMessages.extractSuggestedFollowUpPrompts(markdown);
            }
            """
        )

        action_locator = page.locator('[data-message-id="test-follow-up-question-message"] .assistant-follow-up-action')
        expect(action_locator).to_have_count(3)
        expect(action_locator.nth(0)).to_contain_text("A shorter 5-slide executive deck")
        expect(action_locator.nth(1)).to_contain_text("A more polished board-style version")
        expect(action_locator.nth(2)).to_contain_text("A copy-paste outline with speaker notes")
        assert len(suggestions) == 3
        assert "vba script" not in " ".join(suggestion["label"].lower() for suggestion in suggestions)

        rendered_message_text = page.locator('[data-message-id="test-follow-up-question-message"] .message-text').inner_text()
        assert "Bottom line" in rendered_message_text
        assert "Suggested follow-ups" not in rendered_message_text
        assert "A shorter 5-slide executive deck" not in rendered_message_text

        action_locator.nth(0).click()
        staged_prompt = page.locator('#user-input').input_value()
        assert "shorter 5-slide executive deck" in staged_prompt.lower()
    finally:
        context.close()
        browser.close()
        playwright.stop()
