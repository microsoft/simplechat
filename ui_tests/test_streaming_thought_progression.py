# test_streaming_thought_progression.py
"""
UI test for streaming thought progression.
Version: 0.239.185
Implemented in: 0.239.185

This test ensures the live streaming placeholder keeps advancing to the latest
thought for the active assistant message and does not inherit stale thought
state when a new message starts.
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
def test_streaming_thought_progression_and_session_isolation(playwright):
    """Validate live thought progression and stale-session isolation in the browser."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")

        result = page.evaluate(
            """
            async () => {
                const thoughtsModule = await import('/static/js/chat/chat-thoughts.js');
                const {
                    beginStreamingThoughtSession,
                    clearStreamingThoughtSession,
                    handleStreamingThought,
                    markStreamingThoughtContentStarted,
                } = thoughtsModule;

                function createPlaceholder(messageId, initialText = 'Streaming...') {
                    const wrapper = document.createElement('div');
                    wrapper.setAttribute('data-message-id', messageId);
                    wrapper.innerHTML = `<div class="message-text">${initialText}</div>`;
                    document.body.appendChild(wrapper);
                    return wrapper;
                }

                const oldPlaceholder = createPlaceholder('temp-old');
                beginStreamingThoughtSession('temp-old');
                handleStreamingThought({
                    message_id: 'assistant-old',
                    step_index: 0,
                    step_type: 'generation',
                    content: 'Old thought'
                }, 'temp-old');

                clearStreamingThoughtSession('temp-old');

                const newPlaceholder = createPlaceholder('temp-new');
                beginStreamingThoughtSession('temp-new');
                const beforeThought = newPlaceholder.querySelector('.message-text').textContent;

                handleStreamingThought({
                    message_id: 'assistant-new',
                    step_index: 0,
                    step_type: 'search',
                    content: 'Searching for current reply'
                }, 'temp-new');
                const afterFirstThought = newPlaceholder.querySelector('.message-text').textContent;

                handleStreamingThought({
                    message_id: 'assistant-new',
                    step_index: 1,
                    step_type: 'generation',
                    content: 'Preparing final answer'
                }, 'temp-new');
                const afterSecondThought = newPlaceholder.querySelector('.message-text').textContent;

                markStreamingThoughtContentStarted('temp-new');
                handleStreamingThought({
                    message_id: 'assistant-new',
                    step_index: 2,
                    step_type: 'generation',
                    content: 'Late thought should be ignored'
                }, 'temp-new');
                const afterContentStarted = newPlaceholder.querySelector('.message-text').textContent;

                return {
                    beforeThought,
                    afterFirstThought,
                    afterSecondThought,
                    afterContentStarted,
                    oldPlaceholderText: oldPlaceholder.querySelector('.message-text').textContent,
                    serverMessageId: newPlaceholder.dataset.streamingServerMessageId || null,
                    thoughtIndexAfterContent: newPlaceholder.dataset.streamingThoughtIndex || null,
                };
            }
            """
        )

        assert result['beforeThought'] == 'Streaming...'
        assert 'Searching for current reply' in result['afterFirstThought']
        assert 'Old thought' not in result['afterFirstThought']
        assert 'Preparing final answer' in result['afterSecondThought']
        assert 'Searching for current reply' not in result['afterSecondThought']
        assert result['afterContentStarted'] == result['afterSecondThought']
        assert result['oldPlaceholderText'] != result['afterFirstThought']
        assert result['serverMessageId'] == 'assistant-new'
        assert result['thoughtIndexAfterContent'] is None
    finally:
        context.close()
        browser.close()