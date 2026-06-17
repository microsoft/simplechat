# test_chat_tts_autoplay_toggle.py
"""
UI test for chat AI voice response autoplay toggle.
Version: 0.242.048
Implemented in: 0.242.048

This test ensures the chat toolbar AI voice response toggle persists both the
autoplay preference and the enabled playback state needed for automatic reading
of new assistant messages.
"""

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_chat_tts_autoplay_toggle_persists_enabled_state(playwright):
    """Validate enabling AI voice response saves TTS enabled state."""
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
    captured_payloads = []

    def handle_user_settings(route):
        request = route.request
        if request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                json={"settings": {"ttsEnabled": False, "ttsAutoplay": False}},
            )
            return

        if request.method == "POST":
            captured_payloads.append(json.loads(request.post_data or "{}"))
            route.fulfill(
                status=200,
                content_type="application/json",
                json={"message": "User settings updated successfully"},
            )
            return

        route.continue_()

    try:
        page.route("**/api/user/settings", handle_user_settings)
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")

        assert response is not None, "Expected a navigation response when loading /chats."
        assert response.ok, f"Expected /chats to load successfully, got HTTP {response.status}."

        toggle_button = page.locator("#tts-autoplay-toggle-btn")
        expect(toggle_button).to_be_visible()
        expect(toggle_button).to_have_attribute("class", re.compile(r"\bbtn-outline-secondary\b"))

        toggle_button.click()
        expect(toggle_button).to_have_attribute("class", re.compile(r"\bbtn-primary\b"))

        assert captured_payloads, "Expected the AI voice toggle to persist user settings."
        settings_payload = captured_payloads[-1].get("settings", {})
        assert settings_payload.get("ttsAutoplay") is True
        assert settings_payload.get("ttsEnabled") is True
    finally:
        context.close()
        browser.close()
