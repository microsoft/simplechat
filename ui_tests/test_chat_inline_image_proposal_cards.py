# test_chat_inline_image_proposal_cards.py
"""
UI test for inline image proposal approval cards in chat.
Version: 0.250.064
Implemented in: 0.250.064

This test ensures assistant-authored simpleimage blocks render as opt-in image
proposal cards with clean streaming placeholders, evidence review, approval
gating, hidden prompts, approve-all, edit, cancel, inline result, saved-result
hydration, and responsive bulk-action alignment workflows.
"""

import base64
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


def _proposal_block(index, title=None, prompt=None, metadata=None):
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
    proposal.update(metadata or {})
    return f"```simpleimage\n{json.dumps(proposal)}\n```"


def _append_custom_ai_message(page, message_id, content, generated_image_proposals=None, metadata=None):
    page.evaluate(
        r"""
        async ({ messageId, content, generatedImageProposals, metadata }) => {
            if (document.getElementById('chatbox')) {
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
                        generated_image_proposals: generatedImageProposals || [],
                        metadata: metadata || {}
                    },
                    false
                );
                return;
            }

            const proposals = await import('/static/js/chat/chat-inline-image-proposals.js');
            let harness = document.getElementById('phase7-chat-harness');
            if (!harness) {
                harness = document.createElement('main');
                harness.id = 'phase7-chat-harness';
                harness.className = 'container py-3';
                document.body.replaceChildren(harness);
            }

            const messageElement = document.createElement('article');
            messageElement.className = 'message ai-message';
            messageElement.dataset.messageId = messageId;
            messageElement.dataset.conversationId = 'ui-image-proposal-conversation';
            messageElement.dataset.messageComplete = 'true';
            const messageText = document.createElement('div');
            messageText.className = 'message-text';
            const extracted = proposals.extractInlineImageProposalBlocks(content);
            const escapedMarkdown = extracted.markdown
                .replace(/[&<>"']/g, character => ({
                    '&': '&amp;',
                    '<': '&lt;',
                    '>': '&gt;',
                    '"': '&quot;',
                    "'": '&#39;'
                })[character])
                .replace(/\n/g, '<br>');
            const safeProposalHtml = DOMPurify.sanitize(
                proposals.injectInlineImageProposalHtml(
                    escapedMarkdown,
                    extracted.blocks,
                ),
            );
            messageText.innerHTML = safeProposalHtml;
            messageElement.appendChild(messageText);
            harness.appendChild(messageElement);
            proposals.attachGeneratedImageProposalResults(
                messageElement,
                generatedImageProposals || [],
            );
            proposals.hydrateInlineImageProposals(messageElement, metadata || {});
        }
        """,
        {
            'messageId': message_id,
            'content': content,
            'generatedImageProposals': generated_image_proposals or [],
            'metadata': metadata or {},
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


def _install_image_route(page):
    transparent_png = base64.b64decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
    )

    def handle_image(route):
        route.fulfill(status=200, content_type='image/png', body=transparent_png)

    page.route('**/api/image/*', handle_image)


def _orchestration_metadata(status='ready', runtime_status='succeeded'):
    requirement_status = 'satisfied' if status == 'ready' else 'unsatisfied'
    return {
        'evidence_ledger': {
            'version': 1,
            'status': status,
            'requirements': [
                {
                    'id': 'profile_evidence',
                    'description': 'Verified profile evidence',
                    'required': True,
                    'status': requirement_status,
                },
            ],
            'sources': [
                {
                    'id': 'selected_agent',
                    'type': 'selected_agent',
                    'status': 'succeeded' if status == 'ready' else 'partial',
                    'required': True,
                },
                {
                    'id': 'web_search',
                    'type': 'web_search',
                    'status': 'not_found' if status == 'partial' else 'succeeded',
                    'required': status == 'partial',
                },
            ],
            'facts': [
                {
                    'id': 'fact-profile-role',
                    'source_ids': ['selected_agent'],
                },
            ],
            'results': [],
            'citations': [],
            'artifacts': [
                {
                    'id': 'artifact-headshot',
                    'type': 'image_reference',
                    'name': 'Selected headshot',
                    'reference': 'ui-image-proposal-conversation_image_1_2_3',
                    'message_id': 'ui-image-proposal-conversation_image_1_2_3',
                    'source_ids': ['selected_agent'],
                },
            ],
            'missing_or_failed': ([
                {
                    'status': 'not_found',
                    'message': 'LinkedIn profile was requested but not verified. <img src=x onerror=fail()>',
                },
            ] if status == 'partial' else []),
        },
        'orchestration_runtime': {
            'version': 1,
            'status': runtime_status,
        },
    }


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
        _install_image_route(page)
        page.goto(chat_url, wait_until='domcontentloaded')
        if page.locator('link[href="/static/css/chats.css"]').count() == 0:
            page.add_style_tag(url='/static/css/chats.css')
        if page.evaluate("typeof window.DOMPurify === 'undefined'"):
            page.add_script_tag(url='/static/js/chat/purify.min.js')

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
            'One editable visual.\n\n' + _proposal_block(
                4,
                prompt='Original prompt',
                metadata={
                    'evidenceIds': [
                        'fact-profile-role',
                        'fact profile role',
                        'fact-profile-role',
                    ],
                    'sourceSummary': 'Profile agent\n and selected headshot.',
                    'missingEvidence': [
                        'LinkedIn profile was not verified.',
                        'LinkedIn profile was not verified.',
                    ],
                    'referenceImageIds': ['artifact-headshot', '<photo-reference>'],
                },
            ),
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
        assert requests[-1]['proposal']['evidenceIds'] == [
            'fact-profile-role',
            'fact_profile_role',
        ]
        assert requests[-1]['proposal']['sourceSummary'] == 'Profile agent and selected headshot.'
        assert requests[-1]['proposal']['missingEvidence'] == [
            'LinkedIn profile was not verified.',
        ]
        assert requests[-1]['proposal']['referenceImageIds'] == [
            'artifact-headshot',
            'photo-reference',
        ]

        partial_message_id = 'ui-image-proposal-partial-evidence'
        _append_custom_ai_message(
            page,
            partial_message_id,
            'A grounded visual with partial evidence.\n\n' + _proposal_block(
                7,
                metadata={
                    'evidenceIds': ['fact-profile-role'],
                    'sourceSummary': 'Selected agent evidence and an authorized headshot.',
                    'missingEvidence': ['A public profile could not be verified.'],
                    'referenceImageIds': ['artifact-headshot'],
                },
            ),
            metadata=_orchestration_metadata(status='partial', runtime_status='partial'),
        )
        partial_message = page.locator(f'[data-message-id="{partial_message_id}"]')
        expect(partial_message.locator('.sc-inline-image-proposal-source-badge')).to_contain_text([
            'Selected Agent · used',
            'Web Search · unavailable',
        ])
        expect(partial_message.locator('.sc-inline-image-proposal-missing')).to_contain_text(
            'LinkedIn profile was requested but not verified.'
        )
        expect(partial_message.locator('.sc-inline-image-proposal-reference-image')).to_have_attribute(
            'src',
            '/api/image/ui-image-proposal-conversation_image_1_2_3',
        )
        expect(partial_message.locator('.sc-inline-image-proposal-reference-image')).to_have_attribute(
            'alt',
            'Reference image: Selected headshot',
        )
        expect(partial_message.locator('img[src="x"]')).to_have_count(0)
        expect(partial_message.locator('.sc-inline-image-proposal-evidence-details')).to_contain_text(
            'Review evidence details'
        )
        partial_approve = partial_message.locator('.sc-inline-image-proposal-approve')
        expect(partial_approve).to_be_disabled()
        partial_message.locator('.sc-inline-image-proposal-confirm-partial').check()
        expect(partial_approve).to_be_enabled()
        expect(partial_approve).to_have_attribute('aria-disabled', 'false')
        notice_id = partial_approve.get_attribute('aria-describedby')
        assert notice_id
        expect(partial_message.locator(f'#{notice_id}')).to_have_attribute('aria-live', 'polite')
        expect(partial_message.locator('.sc-inline-image-proposal-approval-live')).to_contain_text(
            'Approval is now available'
        )
        partial_layout = partial_message.locator('.sc-inline-image-proposal-card').evaluate(
            """
            element => ({
                overflows: element.scrollWidth > element.clientWidth,
                right: element.getBoundingClientRect().right,
                viewportWidth: window.innerWidth,
                actionOverflows: element.querySelector('.sc-inline-image-proposal-actions').scrollWidth
                    > element.querySelector('.sc-inline-image-proposal-actions').clientWidth,
                actionHeights: Array.from(
                    element.querySelectorAll('.sc-inline-image-proposal-actions .btn')
                ).map(button => button.getBoundingClientRect().height)
            })
            """
        )
        assert partial_layout['overflows'] is False
        assert partial_layout['actionOverflows'] is False
        assert partial_layout['right'] <= partial_layout['viewportWidth'] + 1
        if viewport['width'] <= 575:
            assert all(height >= 44 for height in partial_layout['actionHeights'])
        partial_approve.click()
        expect(partial_message.locator('.sc-inline-image-proposal-approved')).to_have_count(1)
        assert requests[-1]['confirm_partial'] is True

        blocked_message_id = 'ui-image-proposal-blocked-evidence'
        blocked_metadata = _orchestration_metadata(status='collecting', runtime_status='running')
        blocked_metadata['evidence_ledger']['requirements'][0]['status'] = 'pending'
        blocked_metadata['evidence_ledger']['sources'][0]['status'] = 'running'
        _append_custom_ai_message(
            page,
            blocked_message_id,
            'A proposal waiting for evidence.\n\n' + _proposal_block(8),
            metadata=blocked_metadata,
        )
        blocked_message = page.locator(f'[data-message-id="{blocked_message_id}"]')
        expect(blocked_message.locator('.sc-inline-image-proposal-approve')).to_be_disabled()
        expect(blocked_message.locator('.sc-inline-image-proposal-approval-notice')).to_contain_text(
            'Evidence collection is still in progress.'
        )
        expect(blocked_message.locator('.sc-inline-image-proposal-confirm-partial')).to_have_count(0)
        expect(blocked_message.locator('.sc-inline-image-proposal-reference')).to_have_count(0)

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
