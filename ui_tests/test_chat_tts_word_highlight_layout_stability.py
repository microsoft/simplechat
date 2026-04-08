# test_chat_tts_word_highlight_layout_stability.py
"""
UI test for TTS word highlight layout stability.
Version: 0.240.066
Implemented in: 0.240.066

This test ensures that moving the active TTS word highlight across a wrapped
AI response does not change line breaks or shift surrounding words, and that
the message content wrapper does not create its own vertical scrollbar.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_tts_word_highlight_does_not_reflow_wrapped_message(playwright):
    """Validate that TTS highlight changes do not alter wrapped line positions."""
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

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")

        assert response is not None, "Expected a navigation response when loading /chats."
        assert response.ok, f"Expected /chats to load successfully, got HTTP {response.status}."

        expect(page.locator("#chatbox")).to_be_visible()

        result = page.evaluate(
            """
            () => {
                const existingHost = document.getElementById('tts-layout-test-host');
                if (existingHost) {
                    existingHost.remove();
                }

                const host = document.createElement('div');
                host.id = 'tts-layout-test-host';
                host.style.position = 'fixed';
                host.style.top = '16px';
                host.style.right = '16px';
                host.style.width = '260px';
                host.style.zIndex = '2147483647';
                host.style.pointerEvents = 'none';

                host.innerHTML = `
                    <div class="message ai-message" data-message-id="tts-layout-test-message" style="width: 100%;">
                        <div class="message-content">
                            <div class="avatar" aria-hidden="true"></div>
                            <div class="message-bubble" style="width: 100%; max-width: 100%; min-width: 0;">
                                <div class="message-text" id="tts-layout-test-text"></div>
                            </div>
                        </div>
                    </div>
                `;

                document.body.appendChild(host);

                const messageContent = host.querySelector('.message-content');
                const textContainer = document.getElementById('tts-layout-test-text');
                const words = [
                    'Audio',
                    'voice',
                    'responses',
                    'should',
                    'keep',
                    'their',
                    'wrapped',
                    'lines',
                    'stable',
                    'even',
                    'while',
                    'the',
                    'highlight',
                    'moves',
                    'from',
                    'word',
                    'to',
                    'word',
                    'during',
                    'playback'
                ];

                words.forEach((word, index) => {
                    const span = document.createElement('span');
                    span.className = 'tts-word';
                    span.textContent = word;
                    textContainer.appendChild(span);

                    if (index < words.length - 1) {
                        textContainer.appendChild(document.createTextNode(' '));
                    }
                });

                const wordElements = Array.from(textContainer.querySelectorAll('.tts-word'));
                const snapshotPositions = () => wordElements.map((element) => Math.round(element.getBoundingClientRect().top));

                const baseline = snapshotPositions();
                const lineCount = new Set(baseline).size;

                const messageContentStyle = window.getComputedStyle(messageContent);
                const baseStyle = window.getComputedStyle(wordElements[0]);

                wordElements[0].classList.add('tts-current-word');
                const highlightedStyle = window.getComputedStyle(wordElements[0]);
                wordElements[0].classList.remove('tts-current-word');

                const mismatches = [];
                wordElements.forEach((element, index) => {
                    wordElements.forEach((wordElement) => wordElement.classList.remove('tts-current-word'));
                    element.classList.add('tts-current-word');

                    const current = snapshotPositions();
                    const changed = current.some((top, wordIndex) => top !== baseline[wordIndex]);

                    if (changed) {
                        mismatches.push({
                            index,
                            baseline,
                            current,
                        });
                    }
                });

                wordElements.forEach((wordElement) => wordElement.classList.remove('tts-current-word'));

                return {
                    lineCount,
                    baseline,
                    mismatches,
                    messageContentStyle: {
                        overflowX: messageContentStyle.overflowX,
                        overflowY: messageContentStyle.overflowY,
                    },
                    baseStyle: {
                        fontWeight: baseStyle.fontWeight,
                        paddingLeft: baseStyle.paddingLeft,
                        paddingRight: baseStyle.paddingRight,
                    },
                    highlightedStyle: {
                        fontWeight: highlightedStyle.fontWeight,
                        paddingLeft: highlightedStyle.paddingLeft,
                        paddingRight: highlightedStyle.paddingRight,
                    },
                };
            }
            """
        )

        assert result["lineCount"] > 1, (
            "Expected the injected TTS sample to wrap across multiple lines so the test can detect reflow. "
            f"Observed line count: {result['lineCount']}."
        )
        assert not result["mismatches"], (
            "Expected TTS current-word highlighting to preserve wrapped line positions. "
            f"Observed reflow snapshots: {result['mismatches'][:3]}"
        )
        assert result["messageContentStyle"]["overflowY"] == "visible"
        assert result["highlightedStyle"]["paddingLeft"] == result["baseStyle"]["paddingLeft"] == "0px"
        assert result["highlightedStyle"]["paddingRight"] == result["baseStyle"]["paddingRight"] == "0px"
        assert result["highlightedStyle"]["fontWeight"] == result["baseStyle"]["fontWeight"]
    finally:
        context.close()
        browser.close()
