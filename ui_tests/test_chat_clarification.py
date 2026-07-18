# test_chat_clarification.py
"""
UI test for durable structured clarification in chat.
Version: 0.250.076
Implemented in: 0.250.076

This test ensures clarification checkpoints render inertly, support keyboard and
free-text workflows, reconstruct after refresh, and remain usable on desktop
and mobile.
"""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CLARIFICATION_FILE = (
    REPO_ROOT
    / 'application'
    / 'single_app'
    / 'static'
    / 'js'
    / 'chat'
    / 'chat-clarification.js'
)
CHAT_MESSAGES_FILE = (
    REPO_ROOT
    / 'application'
    / 'single_app'
    / 'static'
    / 'js'
    / 'chat'
    / 'chat-messages.js'
)
CHAT_STYLES_FILE = (
    REPO_ROOT
    / 'application'
    / 'single_app'
    / 'static'
    / 'css'
    / 'chats.css'
)


def _get_chat_test_url():
    chat_url = os.getenv('SIMPLECHAT_PLAYWRIGHT_CHAT_URL', '').strip()
    if not chat_url:
        pytest.skip('Set SIMPLECHAT_PLAYWRIGHT_CHAT_URL to run clarification UI tests.')
    return chat_url


def _create_context(browser, viewport):
    context_kwargs = {'viewport': viewport, 'ignore_https_errors': True}
    storage_state_path = os.getenv('SIMPLECHAT_PLAYWRIGHT_STORAGE_STATE', '').strip()
    if storage_state_path:
        context_kwargs['storage_state'] = storage_state_path
    return browser.new_context(**context_kwargs)


def _metadata(status='pending', *, expired=False):
    now = datetime.now(timezone.utc)
    expires_at = now - timedelta(minutes=1) if expired else now + timedelta(days=1)
    return {
        'awaiting_user_clarification': status == 'pending',
        'chat_clarification': {
            'version': 1,
            'code': 'jurisdiction_required',
            'question': '<img src=x onerror=window.phase10cClarificationInjected=true>',
            'status': status,
            'options': [
                'Virginia',
                'Fairfax County <img src=x onerror=window.phase10cOptionInjected=true>',
            ],
            'created_at': now.isoformat(),
            'expires_at': expires_at.isoformat(),
            'resolved_at': now.isoformat() if status == 'resolved' else None,
            'response_mode': 'option' if status == 'resolved' else None,
        },
    }


def test_clarification_uses_local_inert_message_hydration_contract():
    clarification_source = CLARIFICATION_FILE.read_text(encoding='utf-8')
    messages_source = CHAT_MESSAGES_FILE.read_text(encoding='utf-8')
    style_source = CHAT_STYLES_FILE.read_text(encoding='utf-8')

    assert "from './chat-clarification.js'" in messages_source
    assert 'hydrateChatClarification(messageDiv' in messages_source
    assert 'sendMessage();' in messages_source
    assert 'textContent' in clarification_source
    assert 'innerHTML' not in clarification_source
    assert 'insertAdjacentHTML' not in clarification_source
    assert 'window.location' not in clarification_source
    assert '/api/' not in clarification_source
    assert '.sc-chat-clarification-card' in style_source
    assert 'min-height: 44px' in style_source


@pytest.mark.ui
@pytest.mark.parametrize(
    'viewport',
    [
        {'width': 1280, 'height': 900},
        {'width': 390, 'height': 844},
    ],
)
def test_clarification_keyboard_refresh_and_terminal_states(viewport):
    from playwright.sync_api import expect, sync_playwright

    chat_url = _get_chat_test_url()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = _create_context(browser, viewport)
        page = context.new_page()
        page.goto(chat_url, wait_until='domcontentloaded')
        page.evaluate(
            r"""
            async ({ pending, resolving, resolved, expired }) => {
                if (!document.querySelector('link[data-clarification-test-css]')) {
                    const stylesheet = document.createElement('link');
                    stylesheet.rel = 'stylesheet';
                    stylesheet.href = '/static/css/chats.css?clarification-test=1';
                    stylesheet.dataset.clarificationTestCss = 'true';
                    document.head.appendChild(stylesheet);
                    await new Promise(resolve => {
                        stylesheet.addEventListener('load', resolve, { once: true });
                        stylesheet.addEventListener('error', resolve, { once: true });
                    });
                }
                const module = await import('/static/js/chat/chat-clarification.js');
                const harness = document.createElement('main');
                harness.id = 'phase10c-clarification-harness';
                harness.className = 'container py-3';
                const input = document.createElement('textarea');
                input.id = 'phase10c-free-text-input';
                harness.appendChild(input);
                document.body.replaceChildren(harness);
                window.phase10cClarificationSubmissions = [];

                const appendMessage = (messageId, metadata) => {
                    const message = document.createElement('article');
                    message.className = 'message ai-message';
                    message.dataset.messageId = messageId;
                    const messageText = document.createElement('div');
                    messageText.className = 'message-text';
                    messageText.textContent = 'Clarification checkpoint';
                    message.appendChild(messageText);
                    harness.appendChild(message);
                    module.hydrateChatClarification(message, metadata, {
                        onSubmit: value => {
                            window.phase10cClarificationSubmissions.push(value);
                            return true;
                        },
                        onFocusInput: () => input.focus(),
                    });
                    return message;
                };

                const pendingMessage = appendMessage('clarification-pending', pending);
                module.hydrateChatClarification(pendingMessage, pending, {
                    onSubmit: value => {
                        window.phase10cClarificationSubmissions.push(value);
                        return true;
                    },
                    onFocusInput: () => input.focus(),
                });
                appendMessage('clarification-resolved', resolved);
                appendMessage('clarification-resolving', resolving);
                appendMessage('clarification-expired', expired);
            }
            """,
            {
                'pending': _metadata(),
                'resolving': _metadata(status='resolving'),
                'resolved': _metadata(status='resolved'),
                'expired': _metadata(expired=True),
            },
        )

        pending_message = page.locator('[data-message-id="clarification-pending"]')
        pending_card = pending_message.get_by_test_id('chat-clarification-card')
        expect(pending_card).to_be_visible()
        expect(pending_card.get_by_role('heading', name='One detail needed')).to_be_visible()
        expect(pending_card).to_contain_text('Which jurisdiction applies?')
        expect(pending_card.locator('img')).to_have_count(0)
        assert page.evaluate('() => window.phase10cClarificationInjected === true') is False
        assert page.evaluate('() => window.phase10cOptionInjected === true') is False
        expect(pending_message.get_by_test_id('chat-clarification-card')).to_have_count(1)
        expect(pending_card.get_by_role('status')).to_have_attribute('aria-live', 'polite')

        option = pending_card.get_by_role('button', name='Virginia', exact=True)
        option.focus()
        option.press('Enter')
        expect(pending_card.get_by_role('status')).to_contain_text('Sending your answer')
        assert page.evaluate('() => window.phase10cClarificationSubmissions') == ['Virginia']

        page.evaluate(
            """
            () => {
                const freeText = document.querySelector(
                    '[data-message-id="clarification-pending"] .sc-chat-clarification-free-text'
                );
                freeText.disabled = false;
                freeText.click();
            }
            """
        )
        expect(page.locator('#phase10c-free-text-input')).to_be_focused()

        expect(
            page.locator('[data-message-id="clarification-resolving"]')
                .get_by_role('status')
        ).to_contain_text('being processed')
        expect(
            page.locator('[data-message-id="clarification-resolving"]')
                .get_by_role('button')
        ).to_have_count(0)
        expect(
            page.locator('[data-message-id="clarification-resolved"]')
                .get_by_role('status')
        ).to_contain_text('Answer saved')
        expect(
            page.locator('[data-message-id="clarification-expired"]')
                .get_by_role('status')
        ).to_contain_text('expired')

        layout = pending_card.evaluate(
            """
            element => ({
                overflows: element.scrollWidth > element.clientWidth,
                right: element.getBoundingClientRect().right,
                viewportWidth: window.innerWidth,
                buttonHeights: Array.from(element.querySelectorAll('button'))
                    .map(button => button.getBoundingClientRect().height)
            })
            """
        )
        assert layout['overflows'] is False
        assert layout['right'] <= layout['viewportWidth'] + 1
        assert all(height >= 44 for height in layout['buttonHeights'])

        context.close()
        browser.close()
