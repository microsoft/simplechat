# test_chat_collaboration_mention_tab_selection.py
"""
UI test for Tab autocomplete in the collaborative @ mention menu.

Version: 0.260.005
Implemented in: 0.260.005

This test ensures that pressing Tab while the chat composer's @ mention menu is
open accepts the highlighted suggestion and keeps focus in the message box, that
Shift+Tab still moves focus backwards without inserting a mention, and that the
menu exposes listbox semantics so the highlighted suggestion is announced.

Refs: https://github.com/microsoft/simplechat/issues/1299
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')

MOCK_CONVERSATION_ID = 'mock-mention-tab-conversation'

# Seeds two deterministic agent mention targets and points the composer at a mock
# conversation. The mock conversation item deliberately omits `data-chat-type` so
# `canUseParticipantFlow()` returns false and the suggestion lookup stays offline.
SETUP_SCRIPT = """
    () => {
        const conversationId = 'mock-mention-tab-conversation';

        window.appSettings = window.appSettings || {};
        window.__mentionTabPreviousCollaborationFlag = window.appSettings.enable_collaborative_conversations;
        window.appSettings.enable_collaborative_conversations = true;

        const agentSelect = document.getElementById('agent-select');
        const modelSelect = document.getElementById('model-select');
        window.__mentionTabPreviousAgentOptions = agentSelect ? agentSelect.innerHTML : null;
        window.__mentionTabPreviousModelOptions = modelSelect ? modelSelect.innerHTML : null;
        if (agentSelect) {
            agentSelect.innerHTML = '';
        }
        if (modelSelect) {
            modelSelect.innerHTML = '';
        }

        window.chatAgentOptions = [
            { id: 'ui-test-agent-alpha', name: 'UiTestAgentAlpha', display_name: 'UiTestAgentAlpha' },
            { id: 'ui-test-agent-bravo', name: 'UiTestAgentBravo', display_name: 'UiTestAgentBravo' },
        ];
        window.chatModelOptions = [];

        const conversationItem = document.createElement('div');
        conversationItem.className = 'conversation-item';
        conversationItem.id = 'mention-tab-mock-conversation-item';
        conversationItem.dataset.conversationId = conversationId;
        document.body.appendChild(conversationItem);

        window.__mentionTabPreviousGetCurrentConversationId = window.chatConversations.getCurrentConversationId;
        window.chatConversations.getCurrentConversationId = () => conversationId;
    }
"""

TEARDOWN_SCRIPT = """
    () => {
        if (window.__mentionTabPreviousGetCurrentConversationId) {
            window.chatConversations.getCurrentConversationId = window.__mentionTabPreviousGetCurrentConversationId;
        }

        const agentSelect = document.getElementById('agent-select');
        const modelSelect = document.getElementById('model-select');
        if (agentSelect && window.__mentionTabPreviousAgentOptions !== null) {
            agentSelect.innerHTML = window.__mentionTabPreviousAgentOptions;
        }
        if (modelSelect && window.__mentionTabPreviousModelOptions !== null) {
            modelSelect.innerHTML = window.__mentionTabPreviousModelOptions;
        }

        if (window.appSettings) {
            window.appSettings.enable_collaborative_conversations = window.__mentionTabPreviousCollaborationFlag;
        }

        document.getElementById('mention-tab-mock-conversation-item')?.remove();

        const userInput = document.getElementById('user-input');
        if (userInput) {
            userInput.value = '';
        }
    }
"""


def open_mention_menu(page, query='@UiTest'):
    """Clear the composer, type a mention query, and wait for suggestions."""
    page.fill('#user-input', '')
    page.click('#user-input')
    page.keyboard.type(query)
    expect(page.locator('#collaboration-mention-menu')).to_be_visible()
    expect(page.locator('#collaboration-mention-menu [role="option"]').first).to_be_visible()


@pytest.mark.ui
def test_chat_collaboration_mention_tab_selection(playwright):
    """Validate Tab, Shift+Tab, and listbox semantics for the @ mention menu."""
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
    console_errors = []

    page.on('pageerror', lambda error: page_errors.append(str(error)))
    page.on('console', lambda message: console_errors.append(message.text) if message.type == 'error' else None)

    try:
        response = page.goto(f'{BASE_URL}/chats', wait_until='domcontentloaded')

        assert response is not None, 'Expected a navigation response when loading /chats.'
        assert response.ok, f'Expected /chats to load successfully, got HTTP {response.status}.'

        expect(page.locator('#user-input')).to_be_visible()
        expect(page.locator('#collaboration-mention-menu')).to_have_count(1)

        page.evaluate(SETUP_SCRIPT)

        # The mention menu must expose listbox options with the first one highlighted.
        open_mention_menu(page)
        options = page.locator('#collaboration-mention-menu [role="option"]')
        assert options.count() >= 2, (
            'Expected the seeded agent targets to produce at least two mention suggestions, '
            f'found {options.count()}.'
        )
        expect(options.nth(0)).to_have_attribute('aria-selected', 'true')
        expect(options.nth(1)).to_have_attribute('aria-selected', 'false')

        first_option_id = options.nth(0).get_attribute('id')
        assert first_option_id, 'Mention suggestions need stable ids for aria-activedescendant.'
        expect(page.locator('#user-input')).to_have_attribute('aria-activedescendant', first_option_id)
        # ARIA 1.2 only resolves aria-activedescendant from a textbox when the option
        # lives inside the element named by aria-controls.
        expect(page.locator('#user-input')).to_have_attribute('aria-controls', 'collaboration-mention-menu')
        expect(page.locator('#user-input')).to_have_attribute('aria-autocomplete', 'list')
        assert page.locator(f'#collaboration-mention-menu #{first_option_id}').count() == 1, \
            'The referenced option must live inside the controlled mention menu.'

        # Tab accepts the highlighted suggestion and keeps focus in the composer.
        page.keyboard.press('Tab')
        expect(page.locator('#user-input')).to_have_value('@UiTestAgentAlpha ')
        expect(page.locator('#collaboration-mention-menu')).to_be_hidden()
        assert page.evaluate('() => document.activeElement?.id') == 'user-input', \
            'Tab must accept the suggestion instead of moving focus out of the composer.'
        assert page.evaluate(
            "() => document.getElementById('user-input').hasAttribute('aria-activedescendant')"
        ) is False, 'Closing the mention menu must drop the stale option reference.'

        # Arrow keys still move the highlight, and Tab accepts whatever is highlighted.
        open_mention_menu(page)
        page.keyboard.press('ArrowDown')
        options = page.locator('#collaboration-mention-menu [role="option"]')
        expect(options.nth(0)).to_have_attribute('aria-selected', 'false')
        expect(options.nth(1)).to_have_attribute('aria-selected', 'true')

        second_option_id = options.nth(1).get_attribute('id')
        expect(page.locator('#user-input')).to_have_attribute('aria-activedescendant', second_option_id)

        page.keyboard.press('Tab')
        expect(page.locator('#user-input')).to_have_value('@UiTestAgentBravo ')

        # Enter keeps working exactly as before.
        open_mention_menu(page)
        page.keyboard.press('Enter')
        expect(page.locator('#user-input')).to_have_value('@UiTestAgentAlpha ')

        # Shift+Tab is left alone so it keeps moving focus backwards.
        open_mention_menu(page)
        page.keyboard.press('Shift+Tab')
        expect(page.locator('#user-input')).to_have_value('@UiTest')
        assert page.evaluate('() => document.activeElement?.id') != 'user-input', \
            'Shift+Tab must keep its normal focus-backwards behavior.'

        page.evaluate(TEARDOWN_SCRIPT)

        syntax_errors = [message for message in page_errors if 'SyntaxError' in message]
        mention_page_errors = [message for message in page_errors if 'mention' in message.lower()]
        mention_console_errors = [message for message in console_errors if 'mention' in message.lower()]

        assert not syntax_errors, (
            'Expected /chats to boot without JavaScript syntax errors. '
            f'Observed: {syntax_errors}'
        )
        assert not mention_page_errors, (
            'Expected the mention menu workflow to run without page errors. '
            f'Observed: {mention_page_errors}'
        )
        assert not mention_console_errors, (
            'Expected the mention menu workflow to run without console errors. '
            f'Observed: {mention_console_errors}'
        )
    finally:
        context.close()
        browser.close()
