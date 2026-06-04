# test_chat_inline_image_proposal_cards.py
"""
UI test for inline image proposal approval cards in chat.
Version: 0.241.142
Implemented in: 0.241.137

This test ensures assistant-authored simpleimage blocks render as opt-in image
proposal cards with clean streaming placeholders, hidden prompts, approve,
approve-all, edit, cancel, inline result, saved-result hydration, and bulk-action alignment workflows.
"""

import json
import os

import pytest


def _get_chat_test_url():
    chat_url = os.getenv('SIMPLECHAT_PLAYWRIGHT_CHAT_URL', '').strip()
    if not chat_url:
        pytest.skip('Set SIMPLECHAT_PLAYWRIGHT_CHAT_URL to run inline image proposal UI tests.')
    return chat_url


def _create_context(browser, viewport):
    context_kwargs = {'viewport': viewport, 'ignore_https_errors': True}
    storage_state_path = os.getenv('SIMPLECHAT_PLAYWRIGHT_STORAGE_STATE', '').strip()
    if storage_state_path:
        context_kwargs['storage_state'] = storage_state_path
    return browser.new_context(**context_kwargs)


def _proposal_block(index, title=None, prompt=None):
    proposal = {
        'version': 1,
        'visualId': f'proposal_{index}',
        'title': title or f'Image proposal {index}',
        'description': f'Illustrated visual proposal {index}.',
        'prompt': prompt or f'Create a concise classroom illustration for proposal {index}.',
        'visualType': 'illustration',
        'slideNumber': index,
        'context': 'UI proposal test',
    }
    return f"```simpleimage\n{json.dumps(proposal)}\n```"


def _append_custom_ai_message(page, message_id, content, generated_image_proposals=None):
    page.evaluate(
        """
        async ({ messageId, content, generatedImageProposals }) => {
            const chatMessages = window.chatMessages && typeof window.chatMessages.appendMessage === 'function'
                ? window.chatMessages
                : await import('/static/js/chat/chat-messages.js');
            chatMessages.appendMessage(
                'AI',
                content,
                'image-proposal-ui-test',
                messageId,
                false,
                [],
                [],
                [],
                null,
                null,
                {
                    id: messageId,
                    role: 'assistant',
                    content,
                    conversation_id: 'ui-image-proposal-conversation',
                    generated_image_proposals: generatedImageProposals || []
                },
                false
            );
        }
        """,
        {
            'messageId': message_id,
            'content': content,
            'generatedImageProposals': generated_image_proposals or [],
        },
    )


def _install_approval_route(page, requests):
    def handle_approval(route):
        payload = json.loads(route.request.post_data or '{}')
        requests.append(payload)
        message_id = f"mock-image-{len(requests)}"
        proposal = payload.get('proposal') or {}
        route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'reply': 'Image loading...',
                'image_url': f'/api/image/{message_id}',
                'conversation_id': payload.get('conversation_id'),
                'conversation_title': 'UI proposal test',
                'model_deployment_name': 'mock-image-model',
                'message_id': message_id,
                'image_message': {
                    'id': message_id,
                    'conversation_id': payload.get('conversation_id'),
                    'role': 'image',
                    'content': f'/api/image/{message_id}',
                    'model_deployment_name': 'mock-image-model',
                    'metadata': {
                        'image_proposal': {
                            **proposal,
                            'source_assistant_message_id': payload.get('assistant_message_id'),
                        }
                    },
                },
            }),
        )

    page.route('**/api/chat/image-proposals/generate', handle_approval)


@pytest.mark.ui
@pytest.mark.parametrize('viewport', [{'width': 1440, 'height': 900}, {'width': 390, 'height': 844}])
def test_chat_inline_image_proposal_cards(viewport):
    """Validate image proposal rendering and approval controls in chat."""
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

        bulk_message_id = 'ui-image-proposal-bulk'
        _append_custom_ai_message(
            page,
            bulk_message_id,
            'Here are useful visuals for the lesson.\n\n'
            + '\n\n'.join(_proposal_block(index) for index in range(1, 4)),
        )

        bulk_message = page.locator(f'[data-message-id="{bulk_message_id}"]')
        expect(bulk_message.locator('.sc-inline-image-proposal')).to_have_count(3)
        expect(bulk_message.locator('.sc-inline-image-proposal-prompt-preview')).to_have_count(0)
        expect(bulk_message.locator('.sc-inline-image-proposal-prompt-editor').first).to_be_hidden()
        expect(bulk_message.locator('.sc-inline-image-proposal-approve-all')).to_be_visible()
        bulk_alignment = bulk_message.locator('.sc-inline-image-proposal-bulk-actions').evaluate(
            """
            element => ({
                startsLeft: element.classList.contains('justify-content-start'),
                floatsRight: element.classList.contains('justify-content-end')
            })
            """
        )
        assert bulk_alignment == {'startsLeft': True, 'floatsRight': False}
        bulk_message.locator('.sc-inline-image-proposal-approve-all').click()
        expect(bulk_message.locator('.sc-inline-image-proposal-approved')).to_have_count(3)
        expect(bulk_message.locator('.sc-inline-image-proposal-result-image')).to_have_count(3)
        expect(page.locator('[data-message-id^="mock-image-"]')).to_have_count(0)
        assert len(requests) == 3

        streaming_message_id = 'ui-image-proposal-streaming'
        _append_custom_ai_message(
            page,
            streaming_message_id,
            'A visual is being planned.\n\n```simpleimage\n{"title":"Colonial North America map","description":"A long classroom map description that should wrap cleanly while the proposal is still streaming.",',
        )
        streaming_message = page.locator(f'[data-message-id="{streaming_message_id}"]')
        expect(streaming_message.locator('.sc-inline-image-proposal-status')).to_be_visible()
        expect(streaming_message.locator('.sc-inline-image-proposal-status-text')).to_contain_text('Image proposal is still streaming.')
        expect(streaming_message.locator('.alert-warning')).to_have_count(0)
        assert 'data-image-proposal' not in streaming_message.inner_text()

        edit_message_id = 'ui-image-proposal-edit'
        _append_custom_ai_message(
            page,
            edit_message_id,
            'One editable visual.\n\n' + _proposal_block(4, prompt='Original prompt'),
        )
        edit_message = page.locator(f'[data-message-id="{edit_message_id}"]')
        expect(edit_message.locator('.sc-inline-image-proposal-prompt-editor')).to_be_hidden()
        assert 'Original prompt' not in edit_message.inner_text()
        edit_message.locator('.sc-inline-image-proposal-edit').click()
        expect(edit_message.locator('.sc-inline-image-proposal-prompt-editor')).to_be_visible()
        edit_message.locator('.sc-inline-image-proposal-prompt-editor').fill('Edited prompt for approval')
        edit_message.locator('.sc-inline-image-proposal-approve').click()
        expect(edit_message.locator('.sc-inline-image-proposal-approved')).to_have_count(1)
        expect(edit_message.locator('.sc-inline-image-proposal-result-image')).to_have_count(1)
        assert requests[-1]['proposal']['prompt'] == 'Edited prompt for approval'

        completed_message_id = 'ui-image-proposal-completed'
        _append_custom_ai_message(
            page,
            completed_message_id,
            'A previously generated visual.\n\n' + _proposal_block(6, title='Completed visual', prompt='Saved prompt'),
            generated_image_proposals=[{
                'id': 'mock-image-completed',
                'conversation_id': 'ui-image-proposal-conversation',
                'role': 'image',
                'content': '/api/image/mock-image-completed',
                'model_deployment_name': 'mock-image-model',
                'metadata': {
                    'image_proposal': {
                        'visualId': 'proposal_6',
                        'title': 'Completed visual',
                        'prompt': 'Saved prompt',
                        'source_assistant_message_id': completed_message_id,
                    },
                },
            }],
        )
        completed_message = page.locator(f'[data-message-id="{completed_message_id}"]')
        expect(completed_message.locator('.sc-inline-image-proposal-approved')).to_have_count(1)
        expect(completed_message.locator('.sc-inline-image-proposal-result-image')).to_have_count(1)
        expect(completed_message.locator('.sc-inline-image-proposal-approve')).to_have_count(0)

        cancel_message_id = 'ui-image-proposal-cancel'
        _append_custom_ai_message(
            page,
            cancel_message_id,
            'One cancellable visual.\n\n' + _proposal_block(5),
        )
        cancel_message = page.locator(f'[data-message-id="{cancel_message_id}"]')
        cancel_message.locator('.sc-inline-image-proposal-cancel').click()
        expect(cancel_message.locator('.sc-inline-image-proposal-cancelled')).to_have_count(1)

        context.close()
        browser.close()
