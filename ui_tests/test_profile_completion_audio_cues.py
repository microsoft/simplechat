# test_profile_completion_audio_cues.py
"""
UI test for configurable AI response completion audio cues.
Version: 0.250.102
Implemented in: 0.250.102

This test verifies admin gating, profile persistence and preview controls, plus
foreground suppression and duplicate-free background playback.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


def get_storage_state_path():
    """Return an available authenticated storage state path."""
    for candidate in (STORAGE_STATE, ADMIN_STORAGE_STATE):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip(
        "Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE "
        "to a valid authenticated Playwright storage state file."
    )


def get_user_settings(page):
    """Fetch current user settings through the authenticated browser context."""
    return page.evaluate(
        """
        async () => {
            const response = await fetch('/api/user/settings');
            const data = await response.json();
            return data.settings || {};
        }
        """
    )


def set_user_settings(page, settings):
    """Persist selected user settings through the normal API."""
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
def test_profile_completion_audio_preferences_and_runtime(playwright):
    """Validate the admin gate, saved controls, preview, and playback rules."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=get_storage_state_path(),
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    original_settings = None

    page.add_init_script(
        """
        window.__completionAudioPlays = [];
        window.Audio = class FakeAudio {
            constructor(url) {
                this.url = url;
                this.volume = 1;
                this.listeners = {};
                this.currentTime = 0;
            }
            addEventListener(name, callback) {
                this.listeners[name] = callback;
            }
            pause() {}
            play() {
                window.__completionAudioPlays.push({
                    url: this.url,
                    volume: this.volume
                });
                queueMicrotask(() => this.listeners.ended?.());
                return Promise.resolve();
            }
        };
        """
    )

    try:
        response = page.goto(
            f"{BASE_URL}/profile?tab=settings",
            wait_until="domcontentloaded",
        )
        assert response is not None and response.ok

        admin_enabled = page.evaluate(
            "window.appSettings?.enable_chat_completion_audio_cues === true"
        )
        controls = page.locator("#completion-audio-preferences")
        if not admin_enabled:
            expect(controls).to_have_count(0)
            return

        expect(controls).to_be_visible()
        expect(page.locator("#completion-audio-sound-select option")).to_have_count(10)
        original_settings = get_user_settings(page)

        page.locator("#completion-audio-enabled-toggle").check()
        page.locator("#completion-audio-muted-toggle").uncheck()
        page.locator("#completion-audio-sound-select").select_option("spark")
        page.locator("#completion-audio-volume-range").fill("8")
        expect(page.locator("#completion-audio-volume-value")).to_have_text("8")

        page.locator("#preview-completion-audio-btn").click()
        expect(page.locator("#completion-audio-preference-status")).to_contain_text(
            "Preview played"
        )
        preview = page.evaluate("window.__completionAudioPlays.at(-1)")
        assert preview["url"].endswith("/spark.wav")
        assert preview["volume"] == 0.8

        page.locator("#save-completion-audio-preferences-btn").click()
        expect(page.locator("#completion-audio-preference-status")).to_contain_text(
            "preferences saved"
        )
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#completion-audio-enabled-toggle")).to_be_checked()
        expect(page.locator("#completion-audio-muted-toggle")).not_to_be_checked()
        expect(page.locator("#completion-audio-sound-select")).to_have_value("spark")
        expect(page.locator("#completion-audio-volume-range")).to_have_value("8")

        runtime_result = page.evaluate(
            """
            async () => {
                const manager = window.simpleChatCompletionAudio;
                manager.resetTestState();
                window.__completionAudioPlays = [];
                window.currentConversationId = 'active-conversation';

                await manager.processPolledEvents([{
                    id: 'baseline',
                    metadata: {
                        message_id: 'baseline-message',
                        conversation_id: 'other-conversation'
                    }
                }]);
                await manager.handleCompletion({
                    messageId: 'foreground-message',
                    conversationId: 'active-conversation'
                });
                await manager.handleCompletion({
                    messageId: 'background-message',
                    conversationId: 'other-conversation'
                });
                await manager.handleCompletion({
                    messageId: 'background-message',
                    conversationId: 'other-conversation'
                });

                return window.__completionAudioPlays;
            }
            """
        )
        assert len(runtime_result) == 1
        assert runtime_result[0]["url"].endswith("/spark.wav")
        assert runtime_result[0]["volume"] == 0.8
    finally:
        if original_settings is not None:
            set_user_settings(
                page,
                {
                    "chatCompletionAudioEnabled": original_settings.get(
                        "chatCompletionAudioEnabled",
                        False,
                    ),
                    "chatCompletionAudioMuted": original_settings.get(
                        "chatCompletionAudioMuted",
                        False,
                    ),
                    "chatCompletionAudioSound": original_settings.get(
                        "chatCompletionAudioSound",
                        "aurora",
                    ),
                    "chatCompletionAudioVolume": original_settings.get(
                        "chatCompletionAudioVolume",
                        5,
                    ),
                },
            )
        context.close()
        browser.close()
