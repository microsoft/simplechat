# test_chat_conversation_fork.py
"""
UI test for personal conversation forking.
Version: 0.250.074
Implemented in: 0.250.074

This test ensures only persisted completed assistant messages in personal
conversations expose the fork action and validates confirmation, failure
feedback, duplicate-click prevention, and successful fork activation.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')


@pytest.mark.ui
def test_personal_assistant_message_fork_workflow():
    """Validate the complete browser-side fork workflow."""
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.')

    playwright_sync_api = pytest.importorskip('playwright.sync_api')
    expect = playwright_sync_api.expect
    playwright = playwright_sync_api.sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={'width': 1440, 'height': 1000},
    )
    page = context.new_page()
    fork_requests = []

    def fulfill_synthetic_api(route):
        request_url = route.request.url
        if request_url.endswith('/api/conversations/fork-source/fork'):
            fork_requests.append(route.request.post_data_json)
            if len(fork_requests) == 1:
                route.fulfill(
                    status=500,
                    content_type='application/json',
                    body=json.dumps({'error': 'Simulated fork failure'}),
                )
                return
            route.fulfill(
                status=201,
                content_type='application/json',
                body=json.dumps({
                    'conversation_id': 'fork-created',
                    'title': 'Fork of UI source',
                    'message_count': 2,
                }),
            )
            return
        if '/api/get_messages' in request_url:
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({'messages': []}),
            )
            return
        if request_url.endswith('/metadata'):
            conversation_id = request_url.split('/api/conversations/', 1)[1].split('/', 1)[0]
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({
                    'id': conversation_id,
                    'title': 'Fork of UI source' if conversation_id == 'fork-created' else 'UI source',
                    'chat_type': 'personal_single_user',
                    'context': [],
                    'is_pinned': False,
                    'is_hidden': False,
                }),
            )
            return
        if '/api/conversations/feed' in request_url:
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({
                    'conversations': [{
                        'id': 'fork-created',
                        'title': 'Fork of UI source',
                        'chat_type': 'personal_single_user',
                        'last_updated': '2026-07-30T12:00:00Z',
                    }],
                    'next_cursor': None,
                    'has_more': False,
                    'hidden_count': 0,
                }),
            )
            return
        route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True}),
        )

    try:
        response = page.goto(f'{BASE_URL}/chats', wait_until='networkidle')
        assert response is not None and response.ok
        page.route('**/api/**', fulfill_synthetic_api)
        page.wait_for_function(
            "() => window.chatConversations && typeof window.chatConversations.selectConversation === 'function'"
        )

        visibility = page.evaluate(
            """async () => {
                const conversationsList = document.getElementById('conversations-list');
                conversationsList.replaceChildren();

                const sourceItem = document.createElement('div');
                sourceItem.className = 'conversation-item';
                sourceItem.dataset.conversationId = 'fork-source';
                sourceItem.dataset.conversationTitle = 'UI source';
                sourceItem.dataset.chatType = 'personal_single_user';
                const title = document.createElement('span');
                title.className = 'conversation-title';
                title.textContent = 'UI source';
                sourceItem.appendChild(title);
                conversationsList.appendChild(sourceItem);

                await window.chatConversations.selectConversation('fork-source');
                const chatMessages = await import('/static/js/chat/chat-messages.js');
                chatMessages.appendMessage(
                    'AI',
                    'Persisted response',
                    null,
                    'persisted-assistant',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'persisted-assistant',
                        conversation_id: 'fork-source',
                        role: 'assistant',
                        content: 'Persisted response',
                        metadata: {},
                    }
                );
                chatMessages.appendMessage(
                    'AI',
                    'Streaming response',
                    null,
                    'temp_ai_streaming',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'temp_ai_streaming',
                        conversation_id: 'fork-source',
                        role: 'assistant',
                        content: 'Streaming response',
                        metadata: { stream_status: 'streaming' },
                    }
                );

                sourceItem.dataset.chatType = 'group-single-user';
                chatMessages.appendMessage(
                    'AI',
                    'Group response',
                    null,
                    'group-assistant',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'group-assistant',
                        conversation_id: 'fork-source',
                        role: 'assistant',
                        content: 'Group response',
                        metadata: {},
                    }
                );
                sourceItem.dataset.chatType = 'personal_single_user';

                return {
                    persisted: Boolean(document.querySelector('[data-message-id="persisted-assistant"] .dropdown-fork-conversation-btn')),
                    streaming: Boolean(document.querySelector('[data-message-id="temp_ai_streaming"] .dropdown-fork-conversation-btn')),
                    group: Boolean(document.querySelector('[data-message-id="group-assistant"] .dropdown-fork-conversation-btn')),
                };
            }"""
        )

        assert visibility == {'persisted': True, 'streaming': False, 'group': False}

        fork_action = page.locator(
            '[data-message-id="persisted-assistant"] .dropdown-fork-conversation-btn'
        )
        fork_action.click()
        fork_modal = page.locator('#fork-conversation-modal')
        expect(fork_modal).to_be_visible()
        fork_modal.get_by_role('button', name='Cancel').click()
        expect(fork_modal).to_be_hidden()

        fork_action.click()
        confirm_button = fork_modal.get_by_role('button', name='Fork conversation')
        confirm_button.click()
        expect(page.locator('.toast')).to_contain_text('Simulated fork failure')
        expect(confirm_button).to_be_enabled()
        expect(fork_modal).to_be_visible()

        page.evaluate(
            """() => {
                const button = document.getElementById('confirm-fork-conversation-btn');
                button.click();
                button.click();
            }"""
        )
        expect(fork_modal).to_be_hidden()
        expect(page.locator('.conversation-item.active')).to_have_attribute(
            'data-conversation-id',
            'fork-created',
        )
        expect(page.locator('#current-conversation-title')).to_contain_text('Fork of UI source')
        assert fork_requests == [
            {'message_id': 'persisted-assistant'},
            {'message_id': 'persisted-assistant'},
        ]
    finally:
        context.close()
        browser.close()
        playwright.stop()
