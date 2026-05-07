# test_chat_messages_authorization_error.py
"""
UI test for chat message authorization error handling.
Version: 0.241.012
Implemented in: 0.241.012

This test ensures the chat message loader renders a controlled access-denied
message when the conversation messages endpoint returns 403.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')


@pytest.mark.ui
def test_chat_loader_shows_forbidden_message(playwright):
    """Validate chat message loading handles a forbidden response cleanly."""
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

    def fulfill_forbidden_messages(route):
        route.fulfill(
            status=403,
            content_type='application/json',
            body=json.dumps({'error': 'Forbidden'}),
        )

    try:
        page.route('**/conversation/blocked-conversation/messages', fulfill_forbidden_messages)
        page.goto(f'{BASE_URL}/chats', wait_until='networkidle')
        page.wait_for_function(
            "() => window.chatMessages && typeof window.chatMessages.loadMessages === 'function'"
        )

        page.evaluate(
            """async () => {
                await window.chatMessages.loadMessages('blocked-conversation');
            }"""
        )

        expect(page.locator('#chatbox')).to_contain_text(
            'You do not have access to this conversation.'
        )
    finally:
        context.close()
        browser.close()