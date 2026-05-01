# test_chat_generated_image_rendering.py
"""
UI test for chat generated image rendering.
Version: 0.241.022
Implemented in: 0.241.022

This test ensures that image messages appended through the shared chat renderer
keep their visible image bubble markup for both the single-user image endpoint
and the collaboration image endpoint, preventing the message body from being
suppressed when it contains only an image element.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')
TINY_PNG_BYTES = bytes.fromhex(
    '89504e470d0a1a0a0000000d4948445200000001000000010804000000b51c0c02'
    '0000000b4944415478da63fcff1f0003030200ef9a17db0000000049454e44ae426082'
)


@pytest.mark.ui
def test_chat_generated_image_rendering(playwright):
    """Validate that generated image bubbles stay visible in chat."""
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

    page.route(
        '**/api/image/*',
        lambda route: route.fulfill(status=200, content_type='image/png', body=TINY_PNG_BYTES),
    )
    page.route(
        '**/api/collaboration/conversations/*/images/*',
        lambda route: route.fulfill(status=200, content_type='image/png', body=TINY_PNG_BYTES),
    )

    try:
        response = page.goto(f'{BASE_URL}/chats', wait_until='domcontentloaded')

        assert response is not None, 'Expected a navigation response when loading /chats.'
        assert response.ok, f'Expected /chats to load successfully, got HTTP {response.status}.'

        page.wait_for_selector('#chatbox')

        page.evaluate(
            """
            async () => {
                currentConversationId = 'test-conversation';
                window.currentConversationId = 'test-conversation';
                const messagesModule = await import('/static/js/chat/chat-messages.js');

                messagesModule.appendMessage(
                    'image',
                    '/api/image/generated-image-message',
                    'gpt-image-1.5',
                    'generated-image-message',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'generated-image-message',
                        role: 'image',
                        content: '/api/image/generated-image-message',
                        metadata: {
                            is_user_upload: false,
                        },
                    },
                    true,
                );

                messagesModule.appendMessage(
                    'image',
                    '/api/collaboration/conversations/test-collaboration/images/collaboration-image-message',
                    'gpt-image-1.5',
                    'collaboration-image-message',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'collaboration-image-message',
                        role: 'image',
                        content: '/api/collaboration/conversations/test-collaboration/images/collaboration-image-message',
                        metadata: {
                            is_user_upload: false,
                        },
                    },
                    true,
                );
            }
            """
        )

        generated_image = page.locator('[data-message-id="generated-image-message"] img.generated-image')
        collaboration_image = page.locator('[data-message-id="collaboration-image-message"] img.generated-image')

        expect(generated_image).to_be_visible()
        expect(collaboration_image).to_be_visible()
        expect(page.locator('[data-message-id="generated-image-message"] .message-text')).to_have_count(1)
        expect(page.locator('[data-message-id="collaboration-image-message"] .message-text')).to_have_count(1)
    finally:
        context.close()
        browser.close()