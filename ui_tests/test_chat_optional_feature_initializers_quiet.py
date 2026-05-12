# test_chat_optional_feature_initializers_quiet.py
"""
UI test for quiet optional chat feature initialization.
Version: 0.241.152
Implemented in: 0.241.145

This test ensures the Chats page does not emit browser console errors or
warnings when optional agent or speech-input controls are not rendered.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')


def find_console_messages(console_messages, expected_text):
    """Return captured console messages containing expected text."""
    return [
        message for message in console_messages
        if expected_text in message['text']
    ]


@pytest.mark.ui
def test_chat_optional_feature_initializers_stay_quiet(playwright):
    """Validate optional chat initializers do not complain about absent controls."""
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.')

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={'width': 1440, 'height': 900},
    )
    page = context.new_page()
    page_errors = []
    console_messages = []

    def track_page_error(error):
        page_errors.append(str(error))

    def track_console(message):
        if message.type in ('error', 'warning'):
            console_messages.append({
                'type': message.type,
                'text': message.text,
            })

    page.on('pageerror', track_page_error)
    page.on('console', track_console)

    try:
        response = page.goto(f'{BASE_URL}/chats', wait_until='domcontentloaded')

        assert response is not None, 'Expected a navigation response when loading /chats.'
        assert response.ok, f'Expected /chats to load successfully, got HTTP {response.status}.'

        expect(page.locator('#chatbox')).to_be_visible()
        expect(page.locator('#user-input')).to_be_visible()
        page.wait_for_load_state('networkidle')

        agent_init_errors = find_console_messages(console_messages, 'Agent Init Error')
        speech_missing_warnings = find_console_messages(console_messages, 'Speech input button not found in DOM')
        page_agent_errors = [message for message in page_errors if 'Agent Init Error' in message]

        assert not agent_init_errors, (
            'Expected disabled or unavailable chat agents to initialize quietly. '
            f'Observed: {agent_init_errors}'
        )
        assert not speech_missing_warnings, (
            'Expected disabled or unavailable speech input to initialize quietly. '
            f'Observed: {speech_missing_warnings}'
        )
        assert not page_agent_errors, (
            'Expected agent initialization to avoid page-level errors. '
            f'Observed: {page_agent_errors}'
        )
    finally:
        context.close()
        browser.close()
