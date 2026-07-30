# test_chat_conversation_contents_drawer.py
"""
UI test for the conversation contents drawer.
Version: 0.250.074
Implemented in: 0.250.074

This test validates user-message filtering, safe labels, navigation, live
updates, conversation replacement, keyboard closing, and responsive layouts.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _set_drawer_preference(page, enabled):
    return page.evaluate(
        """
        async (nextValue) => {
            const response = await fetch('/api/user/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    settings: {
                        conversationContentsDrawerEnabled: nextValue
                    }
                })
            });
            return response.ok;
        }
        """,
        enabled,
    )


def _get_drawer_preference(page):
    return page.evaluate(
        """
        async () => {
            const response = await fetch('/api/user/settings');
            const data = await response.json();
            return data.settings?.conversationContentsDrawerEnabled !== false;
        }
        """
    )


def _seed_contents_messages(page):
    page.evaluate(
        """
        () => {
            const chatbox = document.getElementById('chatbox');
            chatbox.replaceChildren();

            const addMessage = (role, id, text, renderedText = text) => {
                const message = document.createElement('div');
                message.className = 'message mb-2';
                message.dataset.messageId = id;
                message.dataset.conversationContentsRole = role;
                message.conversationContentsText = text;
                message.tabIndex = -1;
                message.style.minHeight = '240px';

                const messageText = document.createElement('div');
                messageText.className = 'message-text';
                messageText.textContent = renderedText;
                message.appendChild(messageText);
                chatbox.appendChild(message);
                return message;
            };

            addMessage('user', 'user-1', '# First topic\\nMore detail');
            addMessage('other', 'assistant-1', 'Assistant response');
            addMessage(
                'user',
                'user-2',
                'A very long user prompt that should be truncated without overflowing the drawer controls or changing the surrounding chat layout because it exceeds the stable label length'
            );
            addMessage('user', 'user-3', '', '');
            addMessage('user', 'temp_user_123', 'Pending message');
        }
        """
    )


@pytest.mark.ui
@pytest.mark.parametrize(
    "viewport",
    [
        {"width": 1440, "height": 900},
        {"width": 430, "height": 932},
    ],
    ids=["desktop", "mobile"],
)
def test_chat_conversation_contents_drawer(playwright, viewport):
    """Validate the complete responsive conversation contents workflow."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport=viewport)
    page = context.new_page()
    page_errors = []
    original_preference = True
    page.on("pageerror", lambda exception: page_errors.append(str(exception)))

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        original_preference = _get_drawer_preference(page)
        assert _set_drawer_preference(page, False)
        page.reload(wait_until="networkidle")
        expect(page.locator("#conversation-contents-toggle")).to_have_count(0)

        assert _set_drawer_preference(page, True)
        page.reload(wait_until="networkidle")
        if page.locator("#conversation-contents-toggle").count() == 0:
            pytest.skip("The admin conversation contents drawer feature gate is disabled.")

        _seed_contents_messages(page)
        toggle = page.locator("#conversation-contents-toggle")
        entries = page.locator(".conversation-contents-entry")

        expect(toggle).to_be_visible()
        expect(entries).to_have_count(3)
        expect(entries.nth(0)).to_have_text("First topic")
        expect(entries.nth(1)).to_have_text("A very long user prompt that should be truncated without overflowing th…")
        expect(entries.nth(2)).to_have_text("User message 3")
        assert "<" not in entries.nth(0).inner_html()

        toggle.click()
        expect(page.locator("#conversation-contents-drawer")).to_be_visible()
        entries.nth(1).click()
        expect(page.locator('.message[data-message-id="user-2"]')).to_be_focused()
        page.evaluate(
            """
            () => {
                const container = document.getElementById('chat-messages-container');
                const message = document.querySelector('.message[data-message-id="user-2"]');
                container.scrollTop = message.offsetTop;
                container.dispatchEvent(new Event('scroll'));
            }
            """
        )
        expect(entries.nth(1)).to_have_attribute("aria-current", "location")
        entries.nth(1).focus()

        page.evaluate(
            """
            () => {
                const message = document.createElement('div');
                message.className = 'message';
                message.dataset.messageId = 'temp_user_456';
                message.dataset.conversationContentsRole = 'user';
                message.conversationContentsText = 'Live update topic';
                const text = document.createElement('div');
                text.className = 'message-text';
                text.textContent = 'Live update topic';
                message.appendChild(text);
                document.getElementById('chatbox').appendChild(message);
                message.dataset.messageId = 'user-4';
            }
            """
        )
        expect(entries).to_have_count(4)
        expect(entries.nth(3)).to_have_text("Live update topic")
        expect(entries.nth(1)).to_have_attribute("aria-current", "location")
        expect(entries.nth(1)).to_be_focused()

        page.evaluate(
            """
            () => {
                const chatbox = document.getElementById('chatbox');
                chatbox.replaceChildren();
                const message = document.createElement('div');
                message.className = 'message';
                message.dataset.messageId = 'next-conversation-user-1';
                message.dataset.conversationContentsRole = 'user';
                const text = document.createElement('div');
                text.className = 'message-text';
                text.textContent = 'Next conversation topic';
                message.appendChild(text);
                chatbox.appendChild(message);
            }
            """
        )
        expect(entries).to_have_count(1)
        expect(entries.nth(0)).to_have_text("Next conversation topic")

        toggle.click()
        page.keyboard.press("Escape")
        expect(page.locator("#conversation-contents-drawer")).to_be_hidden()
        assert not page_errors, f"Expected no uncaught page errors, got: {page_errors}"
    finally:
        _set_drawer_preference(page, original_preference)
        context.close()
        browser.close()
