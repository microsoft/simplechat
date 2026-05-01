# test_chat_exhaustive_review_thought_progress.py
"""
UI test for exhaustive review streaming thought progress.
Version: 0.241.071
Implemented in: 0.241.071

This test ensures the streaming thought placeholder renders overall and
per-document progress bars for exhaustive review updates.
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
def test_chat_exhaustive_review_thought_progress(playwright):
    """Validate that exhaustive review thought updates render live progress bars."""
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
                    handleStreamingThought,
                } = thoughtsModule;

                const wrapper = document.createElement('div');
                wrapper.setAttribute('data-message-id', 'temp-progress');
                wrapper.innerHTML = '<div class="message-text">Streaming...</div>';
                document.body.appendChild(wrapper);

                beginStreamingThoughtSession('temp-progress');
                handleStreamingThought({
                    message_id: 'assistant-progress',
                    step_index: 2,
                    step_type: 'document_review',
                    content: 'Reviewing window 4 of 9 for Policy Handbook',
                    progress: {
                        overall: {
                            percent: 45,
                            completed_chunks: 81,
                            total_chunks: 180,
                            completed_windows: 7,
                            total_windows: 16,
                            completed_documents: 0,
                            document_count: 2,
                            failed_windows: 0,
                        },
                        documents: [
                            {
                                document_id: 'doc-1',
                                document_name: 'Policy Handbook',
                                percent: 63,
                                status: 'running',
                                status_text: 'Reviewing window 4 of 9',
                                completed_chunks: 63,
                                total_chunks: 100,
                                completed_windows: 4,
                                total_windows: 9,
                                failed_windows: 0,
                            },
                            {
                                document_id: 'doc-2',
                                document_name: 'Vendor Contract',
                                percent: 20,
                                status: 'pending',
                                status_text: 'Queued',
                                completed_chunks: 18,
                                total_chunks: 80,
                                completed_windows: 3,
                                total_windows: 7,
                                failed_windows: 0,
                            },
                        ],
                    },
                }, 'temp-progress');

                const messageText = wrapper.querySelector('.message-text');
                const progressBars = Array.from(messageText.querySelectorAll('.progress-bar')).map((element) => ({
                    text: element.textContent.trim(),
                    width: element.style.width,
                }));

                return {
                    textContent: messageText.textContent,
                    progressBarCount: progressBars.length,
                    widths: progressBars.map((entry) => entry.width),
                    labels: progressBars.map((entry) => entry.text),
                };
            }
            """
        )

        assert 'Policy Handbook' in result['textContent']
        assert 'Vendor Contract' in result['textContent']
        assert '81/180 chunks' in result['textContent']
        assert result['progressBarCount'] == 3
        assert result['widths'] == ['45%', '63%', '20%']
        assert result['labels'] == ['45%', '63%', '20%']
    finally:
        context.close()
        browser.close()