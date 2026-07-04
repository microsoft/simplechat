# test_chat_image_reference_tray.py
"""
UI test for chat image reference tray.
Version: 0.250.021
Implemented in: 0.250.015

This test ensures users can collect an existing chat image as a saved reference
and that inline image proposal approval sends the selected reference metadata.
"""

import json
import os

import pytest


def _get_chat_test_url():
    chat_url = os.getenv('SIMPLECHAT_PLAYWRIGHT_CHAT_URL', '').strip()
    if not chat_url:
        pytest.skip('Set SIMPLECHAT_PLAYWRIGHT_CHAT_URL to run image reference tray UI tests.')
    return chat_url


def _create_context(browser, viewport):
    context_kwargs = {'viewport': viewport, 'ignore_https_errors': True}
    storage_state_path = os.getenv('SIMPLECHAT_PLAYWRIGHT_STORAGE_STATE', '').strip()
    if storage_state_path:
        context_kwargs['storage_state'] = storage_state_path
    return browser.new_context(**context_kwargs)


def _append_image_message(page):
    page.evaluate(
        """
        async () => {
            const chatMessages = window.chatMessages && typeof window.chatMessages.appendMessage === 'function'
                ? window.chatMessages
                : await import('/static/js/chat/chat-messages.js');
            chatMessages.appendMessage(
                'image',
                '/api/image/ui-reference-image',
                null,
                'ui-reference-image',
                false,
                [],
                [],
                [],
                null,
                null,
                {
                    id: 'ui-reference-image',
                    role: 'image',
                    conversation_id: 'ui-image-reference-conversation',
                    content: '/api/image/ui-reference-image',
                    filename: 'uploaded-logo.png',
                    metadata: { is_user_upload: true }
                },
                false
            );
        }
        """
    )


def _append_proposal_message(page):
    proposal = {
        'version': 1,
        'visualId': 'reference_visual',
        'title': 'Reference visual',
        'description': 'Uses the selected reference image.',
        'prompt': 'Create a polished image using the selected logo reference.',
        'visualType': 'illustration',
    }
    page.evaluate(
        """
        async ({ proposal }) => {
            const chatMessages = window.chatMessages && typeof window.chatMessages.appendMessage === 'function'
                ? window.chatMessages
                : await import('/static/js/chat/chat-messages.js');
            chatMessages.appendMessage(
                'AI',
                `Ready to create.\n\n```simpleimage\n${JSON.stringify(proposal)}\n````,
                'image-reference-ui-test',
                'ui-reference-proposal',
                false,
                [],
                [],
                [],
                null,
                null,
                {
                    id: 'ui-reference-proposal',
                    role: 'assistant',
                    conversation_id: 'ui-image-reference-conversation',
                    content: ''
                },
                false
            );
        }
        """,
        {'proposal': proposal},
    )


def _install_approval_route(page, requests):
    def handle_approval(route):
        payload = json.loads(route.request.post_data or '{}')
        requests.append(payload)
        route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'reply': 'Image loading...',
                'image_url': '/api/image/mock-reference-output',
                'conversation_id': payload.get('conversation_id'),
                'conversation_title': 'UI reference test',
                'model_deployment_name': 'mock-image-model',
                'message_id': 'mock-reference-output',
                'image_references': payload.get('image_references', []),
                'image_message': {
                    'id': 'mock-reference-output',
                    'conversation_id': payload.get('conversation_id'),
                    'role': 'image',
                    'content': '/api/image/mock-reference-output',
                    'metadata': {
                        'image_references': payload.get('image_references', []),
                    },
                },
            }),
        )

    page.route('**/api/chat/image-proposals/generate', handle_approval)


@pytest.mark.ui
@pytest.mark.parametrize('viewport', [{'width': 1440, 'height': 900}, {'width': 390, 'height': 844}])
def test_chat_image_reference_tray(viewport):
    """Validate collecting and sending a chat image reference."""
    chat_url = _get_chat_test_url()
    playwright_sync_api = pytest.importorskip('playwright.sync_api')
    expect = playwright_sync_api.expect
    sync_playwright = playwright_sync_api.sync_playwright
    requests = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = _create_context(browser, viewport)
        page = context.new_page()
        _install_approval_route(page, requests)
        page.goto(chat_url, wait_until='domcontentloaded')

        _append_image_message(page)
        image_message = page.locator('[data-message-id="ui-reference-image"]')
        image_message.locator('.message-footer .dropdown button').click()
        image_message.get_by_role('button', name='Use as image reference').click()

        expect(page.locator('#image-reference-panel')).to_be_visible()
        expect(page.locator('#image-reference-list')).to_contain_text('uploaded-logo.png')
        page.locator('#image-reference-list').get_by_role('button', name='Save').click()
        expect(page.locator('#image-reference-status')).to_contain_text('ready')

        _append_proposal_message(page)
        proposal_message = page.locator('[data-message-id="ui-reference-proposal"]')
        proposal_message.locator('.sc-inline-image-proposal-approve').click()
        expect(proposal_message.locator('.sc-inline-image-proposal-approved')).to_have_count(1)

        assert len(requests) == 1
        assert requests[0]['image_references'] == [
            {
                'source_type': 'chat_image',
                'message_id': 'ui-reference-image',
            }
        ]
        assert requests[0]['image_reference_target']['scope_type'] in {'personal', 'group'}

        context.close()
        browser.close()
