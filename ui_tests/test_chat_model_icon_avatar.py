# test_chat_model_icon_avatar.py
"""
UI test for chat model icon avatars.
Version: 0.242.071
Implemented in: 0.242.070

This test ensures model endpoint icons can render as chat assistant avatars
when a response is model-only and does not have an agent icon, while agent
responses keep agent/default avatar precedence over model icons.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_model_icon_renders_as_chat_avatar():
    """Validate a model icon payload renders in the assistant avatar slot."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        try:
            page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
            message_id = "ui-model-icon-avatar"
            page.evaluate(
                """
                async (messageId) => {
                    document.querySelector(`[data-message-id="${messageId}"]`)?.remove();
                    const chatMessages = await import('/static/js/chat/chat-messages.js');
                    const modelIcon = { kind: 'bootstrap', value: 'bi-robot' };
                    chatMessages.appendMessage(
                        'AI',
                        'Model icon avatar test',
                        'gpt-icon',
                        messageId,
                        false,
                        [],
                        [],
                        [],
                        null,
                        null,
                        {
                            id: messageId,
                            role: 'assistant',
                            content: 'Model icon avatar test',
                            model_deployment_name: 'gpt-icon',
                            model_icon: modelIcon,
                            metadata: {
                                model_selection: {
                                    selected_model: 'gpt-icon',
                                    model_icon: modelIcon
                                }
                            }
                        },
                        false
                    );
                }
                """,
                message_id,
            )

            message = page.locator(f"[data-message-id='{message_id}']")
            expect(message.locator(".model-avatar .bi-robot")).to_be_visible()

            agent_message_id = "ui-agent-model-icon-avatar"
            page.evaluate(
                """
                async (messageId) => {
                    document.querySelector(`[data-message-id="${messageId}"]`)?.remove();
                    const chatMessages = await import('/static/js/chat/chat-messages.js');
                    const modelIcon = { kind: 'bootstrap', value: 'bi-robot' };
                    chatMessages.appendMessage(
                        'AI',
                        'Agent response should not use model avatar',
                        'gpt-icon',
                        messageId,
                        false,
                        [],
                        [],
                        [],
                        'Simple Chat',
                        'simple_chat',
                        {
                            id: messageId,
                            role: 'assistant',
                            content: 'Agent response should not use model avatar',
                            model_deployment_name: 'gpt-icon',
                            model_icon: modelIcon,
                            agent_display_name: 'Simple Chat',
                            agent_name: 'simple_chat',
                            metadata: {
                                model_selection: {
                                    selected_model: 'gpt-icon',
                                    model_icon: modelIcon
                                }
                            }
                        },
                        false
                    );
                }
                """,
                agent_message_id,
            )

            agent_message = page.locator(f"[data-message-id='{agent_message_id}']")
            expect(agent_message.locator(".model-avatar .bi-robot")).to_have_count(0)
            expect(agent_message.locator("img.avatar")).to_be_visible()
        finally:
            context.close()
            browser.close()