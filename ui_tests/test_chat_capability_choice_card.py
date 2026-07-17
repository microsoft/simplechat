# test_chat_capability_choice_card.py
"""
UI test for governed capability choice cards in chat.
Version: 0.250.074
Implemented in: 0.250.067; option grid redesigned in 0.250.074

This test ensures persisted capability proposals hydrate on desktop and mobile,
expose accessible notices and controls, submit only allowlisted identifiers,
and resume through the server-authored stream endpoint.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_MESSAGES_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-messages.js'
CAPABILITY_CHOICE_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-capability-choice.js'
CHAT_STYLES_FILE = REPO_ROOT / 'application' / 'single_app' / 'static' / 'css' / 'chats.css'


def _get_chat_test_url():
    chat_url = os.getenv('SIMPLECHAT_PLAYWRIGHT_CHAT_URL', '').strip()
    if not chat_url:
        pytest.skip('Set SIMPLECHAT_PLAYWRIGHT_CHAT_URL to run capability choice UI tests.')
    return chat_url


def _create_context(browser, viewport):
    context_kwargs = {'viewport': viewport, 'ignore_https_errors': True}
    storage_state_path = os.getenv('SIMPLECHAT_PLAYWRIGHT_STORAGE_STATE', '').strip()
    if storage_state_path:
        context_kwargs['storage_state'] = storage_state_path
    return browser.new_context(**context_kwargs)


def _proposal_metadata(status='pending', resume_status='not_requested'):
    created_at = datetime.now(timezone.utc)
    return {
        'awaiting_user_choice': status == 'pending',
        'capability_proposal': {
            'version': 2,
            'proposal_id': 'ui-capability-proposal-1',
            'run_id': 'ui-parent-run-1',
            'conversation_id': 'ui-capability-conversation',
            'user_message_id': 'ui-capability-user-1',
            'assistant_message_id': 'ui-capability-proposal-1',
            'status': status,
            'requirement_ids': ['current_authoritative_sources'],
            'reason_codes': ['current_authoritative_sources'],
            'selected_context_labels': [
                'Workspace Search',
                'Selected <img src=x onerror=window.phase10bInjected=true>',
            ],
            'recommended_option_id': 'deep_research',
            'options': [
                {
                    'id': 'deep_research',
                    'capability_ids': ['deep_research'],
                    'effective_capability_ids': ['deep_research', 'web_search'],
                    'label': 'Deep Research',
                    'latency_class': 'minutes',
                    'cost_class': 'extended',
                    'external_data': True,
                    'read_only': True,
                    'risk_class': 'external_read',
                    'data_sensitivity': 'public',
                },
                {
                    'id': 'web_search',
                    'capability_ids': ['web_search'],
                    'effective_capability_ids': ['web_search'],
                    'label': 'Web Search',
                    'latency_class': 'seconds',
                    'cost_class': 'standard',
                    'external_data': True,
                },
                {
                    'id': 'continue_without_capabilities',
                    'capability_ids': [],
                    'effective_capability_ids': [],
                    'label': 'Continue without additional capabilities',
                    'latency_class': 'immediate',
                    'cost_class': 'none',
                    'external_data': False,
                },
            ],
            'decision': (
                {
                    'option_id': 'deep_research',
                    'status': 'approved',
                    'capability_ids': ['deep_research'],
                    'effective_capability_ids': ['deep_research', 'web_search'],
                }
                if status == 'approved'
                else None
            ),
            'resume': {
                'status': resume_status,
                'assistant_message_id': None,
            },
            'created_at': created_at.isoformat(),
            'expires_at': (created_at + timedelta(days=1)).isoformat(),
        },
    }


def _agent_proposal_metadata(
    proposal_id,
    *,
    status='pending',
    resume_status='not_requested',
):
    created_at = datetime.now(timezone.utc)
    agent_option_id = 'agent:group:0123456789abcdef0123456789abcdef'
    decision = None
    if status in {'approved', 'declined'}:
        decision = {
            'option_id': agent_option_id,
            'status': status,
            'capability_ids': [],
            'effective_capability_ids': [],
            'agent_ref': agent_option_id,
        }
    return {
        'awaiting_user_choice': status == 'pending',
        'capability_proposal': {
            'version': 1,
            'proposal_id': proposal_id,
            'run_id': f'{proposal_id}-run',
            'conversation_id': 'ui-capability-conversation',
            'user_message_id': f'{proposal_id}-user',
            'assistant_message_id': proposal_id,
            'status': status,
            'requirement_ids': ['specialized_organizational_knowledge'],
            'reason_codes': ['specialized_organizational_knowledge'],
            'recommended_option_id': agent_option_id,
            'options': [
                {
                    'id': agent_option_id,
                    'kind': 'agent',
                    'agent_ref': agent_option_id,
                    'capability_ids': [],
                    'effective_capability_ids': [],
                    'label': 'Benefits <img src=x onerror=window.phase8bInjected=true>',
                    'category': 'specialized_agent',
                    'scope_class': 'group',
                    'latency_class': 'seconds',
                    'cost_class': 'standard',
                    'external_data': True,
                    'read_only': True,
                    'risk_class': 'internal_read',
                    'data_sensitivity': 'internal',
                    'capability_tags': ['benefits', 'policy_lookup'],
                    'evidence_types': ['policy_documents'],
                },
                {
                    'id': 'continue_without_capabilities',
                    'kind': 'continue',
                    'capability_ids': [],
                    'effective_capability_ids': [],
                    'label': 'Continue without additional capabilities',
                    'latency_class': 'immediate',
                    'cost_class': 'none',
                    'external_data': False,
                },
            ],
            'decision': decision,
            'resume': {
                'status': resume_status,
                'assistant_message_id': (
                    f'{proposal_id}-completed-assistant'
                    if resume_status == 'completed'
                    else None
                ),
            },
            'created_at': created_at.isoformat(),
            'expires_at': (created_at + timedelta(days=1)).isoformat(),
        },
    }


def _append_proposal_message(page, message_id, metadata):
    page.evaluate(
        r"""
        async ({ messageId, metadata }) => {
            if (document.getElementById('chatbox')) {
                const chatMessages = window.chatMessages && typeof window.chatMessages.appendMessage === 'function'
                    ? window.chatMessages
                    : await import('/static/js/chat/chat-messages.js');
                chatMessages.appendMessage(
                    'AI',
                    'An additional capability could materially improve this answer. Choose how you want to continue.',
                    null,
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
                        conversation_id: 'ui-capability-conversation',
                        metadata,
                    },
                    false,
                );
                return;
            }

            if (!document.querySelector('link[data-capability-choice-test-css]')) {
                const stylesheet = document.createElement('link');
                stylesheet.rel = 'stylesheet';
                stylesheet.href = '/static/css/chats.css?capability-choice-test=1';
                stylesheet.dataset.capabilityChoiceTestCss = 'true';
                document.head.appendChild(stylesheet);
                await new Promise(resolve => {
                    stylesheet.addEventListener('load', resolve, { once: true });
                    stylesheet.addEventListener('error', resolve, { once: true });
                });
            }
            const capabilityChoice = await import('/static/js/chat/chat-capability-choice.js');
            let harness = document.getElementById('phase8a-capability-choice-harness');
            if (!harness) {
                harness = document.createElement('main');
                harness.id = 'phase8a-capability-choice-harness';
                harness.className = 'container py-3';
                document.body.replaceChildren(harness);
            }
            const messageElement = document.createElement('article');
            messageElement.className = 'message ai-message';
            messageElement.dataset.messageId = messageId;
            messageElement.dataset.conversationId = 'ui-capability-conversation';
            const messageText = document.createElement('div');
            messageText.className = 'message-text';
            messageText.textContent = 'An additional capability could materially improve this answer.';
            messageElement.appendChild(messageText);
            harness.appendChild(messageElement);
            capabilityChoice.hydrateCapabilityChoice(messageElement, metadata, {
                onResume: async ({ conversationId, proposalId, endpoint }) => {
                    const response = await fetch(endpoint, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        credentials: 'same-origin',
                        body: JSON.stringify({
                            conversation_id: conversationId,
                            capability_resume_proposal_id: proposalId,
                        }),
                    });
                    const streamText = await response.text();
                    const dataLine = streamText.split('\n').find(line => line.startsWith('data:'));
                    const payload = dataLine ? JSON.parse(dataLine.slice(5).trim()) : {};
                    const assistant = document.createElement('article');
                    assistant.dataset.messageId = payload.message_id || 'ui-capability-resumed-assistant';
                    assistant.textContent = payload.full_content || '';
                    harness.appendChild(assistant);
                },
            });
        }
        """,
        {'messageId': message_id, 'metadata': metadata},
    )


def test_capability_resume_waits_for_stream_terminal_event():
    source = CHAT_MESSAGES_FILE.read_text(encoding='utf-8')

    assert 'onResume: ({ conversationId, proposalId, endpoint }) => new Promise(' in source
    assert 'onDone: resolve,' in source
    assert "onError: errorMessage => reject(" in source


def test_capability_choice_uses_server_plan_option_grid_contract():
    choice_source = CAPABILITY_CHOICE_FILE.read_text(encoding='utf-8')
    style_source = CHAT_STYLES_FILE.read_text(encoding='utf-8')

    assert 'sc-capability-choice-option-grid' in choice_source
    assert 'sc-capability-choice-recommended-ribbon' in choice_source
    assert 'sc-capability-choice-includes-list' in choice_source
    assert '_complete_correlated_capability_resume_output' not in choice_source
    assert 'option_id: option.id' in choice_source
    assert 'selectedOptionIds' not in choice_source
    assert 'grid-template-columns: repeat(auto-fit' in style_source
    assert '.sc-capability-choice-option-card.is-recommended' in style_source
    assert '.sc-capability-choice-continue' in style_source


@pytest.mark.ui
@pytest.mark.parametrize(
    'viewport',
    [
        {'width': 1280, 'height': 900},
        {'width': 390, 'height': 844},
    ],
)
def test_capability_choice_card_decision_and_resume(viewport):
    from playwright.sync_api import expect, sync_playwright

    chat_url = _get_chat_test_url()
    decision_requests = []
    resume_requests = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = _create_context(browser, viewport)
        page = context.new_page()

        def handle_decision(route):
            decision_requests.append(json.loads(route.request.post_data or '{}'))
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({
                    'success': True,
                    'conversation_id': 'ui-capability-conversation',
                    'proposal_id': 'ui-capability-proposal-1',
                    'status': 'approved',
                    'decision': {
                        'option_id': 'deep_research',
                        'status': 'approved',
                    },
                    'resume_status': 'pending',
                    'resume_endpoint': '/api/chat/stream',
                }),
            )

        def handle_resume(route):
            resume_requests.append(json.loads(route.request.post_data or '{}'))
            route.fulfill(
                status=200,
                content_type='text/event-stream',
                body=(
                    'data: '
                    + json.dumps({
                        'done': True,
                        'conversation_id': 'ui-capability-conversation',
                        'message_id': 'ui-capability-resumed-assistant',
                        'user_message_id': 'ui-capability-user-1',
                        'full_content': 'Resumed with current official sources.',
                        'metadata': {},
                    })
                    + '\n\n'
                ),
            )

        page.route('**/api/chat/capability-proposals/*/decision', handle_decision)
        page.route('**/api/chat/stream', handle_resume)
        page.goto(chat_url, wait_until='domcontentloaded')

        _append_proposal_message(
            page,
            'ui-capability-proposal-1',
            _proposal_metadata(),
        )
        message = page.locator('[data-message-id="ui-capability-proposal-1"]')
        card = message.get_by_test_id('capability-choice-card')
        expect(card).to_be_visible()
        expect(card.get_by_role('heading', name='How would you like to continue?')).to_be_visible()
        expect(card.get_by_test_id('capability-external-data-notice')).to_contain_text(
            'Conversation history and workspace content are not included.'
        )
        expect(card.get_by_test_id('capability-selected-context')).to_contain_text(
            'Already included'
        )
        expect(card.get_by_test_id('capability-selected-context')).to_contain_text(
            'Workspace Search'
        )
        expect(card.get_by_test_id('capability-option-includes').first).to_contain_text(
            'Deep Research'
        )
        expect(card.get_by_test_id('capability-option-includes').first).to_contain_text(
            'Web Search'
        )
        expect(card.get_by_test_id('capability-recommended-ribbon')).to_have_text('Recommended')
        expect(card.get_by_test_id('capability-option-description').first).to_contain_text(
            'Exhaustive archive research'
        )
        expect(card.get_by_test_id('capability-option-summary').first).to_contain_text(
            'Minutes'
        )
        expect(card.get_by_test_id('capability-option-summary').first).to_contain_text(
            'Extended'
        )
        expect(card.locator('.sc-capability-choice-option-grid .badge')).to_have_count(0)
        assert card.locator('img').count() == 0
        assert page.evaluate('() => window.phase10bInjected === true') is False
        expect(card.get_by_role('button', name='Recommended: Deep Research')).to_be_enabled()
        expect(card.get_by_role('button', name='Web Search')).to_be_enabled()
        expect(card.get_by_role('button', name='Continue without additional capabilities')).to_be_enabled()
        status_id = card.get_by_role('button', name='Deep Research').get_attribute('aria-describedby')
        assert status_id
        expect(card.locator(f'#{status_id}')).to_have_attribute('aria-live', 'polite')

        layout = card.evaluate(
            """
            element => ({
                overflows: element.scrollWidth > element.clientWidth,
                right: element.getBoundingClientRect().right,
                viewportWidth: window.innerWidth,
                buttonHeights: Array.from(element.querySelectorAll('button')).map(button => button.getBoundingClientRect().height),
                optionWidths: Array.from(element.querySelectorAll('.sc-capability-choice-option-card')).map(option => option.getBoundingClientRect().width),
                optionHeights: Array.from(element.querySelectorAll('.sc-capability-choice-option-card')).map(option => option.getBoundingClientRect().height),
                continueWidth: element.querySelector('.sc-capability-choice-continue')?.getBoundingClientRect().width || 0,
                gridWidth: element.querySelector('.sc-capability-choice-option-grid')?.getBoundingClientRect().width || 0
            })
            """
        )
        assert layout['overflows'] is False
        assert layout['right'] <= layout['viewportWidth'] + 1
        assert all(height >= 44 for height in layout['buttonHeights'])
        assert max(layout['optionWidths']) - min(layout['optionWidths']) <= 1
        if viewport['width'] >= 576:
            assert max(layout['optionHeights']) - min(layout['optionHeights']) <= 1
        assert abs(layout['continueWidth'] - layout['gridWidth']) <= 1

        deep_research_button = card.get_by_role('button', name='Deep Research')
        deep_research_button.focus()
        deep_research_button.press('Enter')
        expect(page.locator('[data-message-id="ui-capability-resumed-assistant"]')).to_contain_text(
            'Resumed with current official sources.'
        )
        expect(card.get_by_role('status')).to_contain_text('Completed with Deep Research.')
        assert decision_requests == [{
            'conversation_id': 'ui-capability-conversation',
            'option_id': 'deep_research',
        }]
        assert resume_requests == [{
            'conversation_id': 'ui-capability-conversation',
            'capability_resume_proposal_id': 'ui-capability-proposal-1',
        }]

        _append_proposal_message(
            page,
            'ui-capability-proposal-refresh',
            _proposal_metadata(status='approved', resume_status='pending'),
        )
        refreshed_card = page.locator(
            '[data-message-id="ui-capability-proposal-refresh"]'
        ).get_by_test_id('capability-choice-card')
        expect(refreshed_card.get_by_role('button', name='Resume')).to_be_visible()
        expect(refreshed_card.get_by_role('status')).to_contain_text(
            'Deep Research is saved and ready to resume.'
        )

        expired_metadata = _proposal_metadata()
        expired_metadata['capability_proposal']['expires_at'] = (
            datetime.now(timezone.utc) - timedelta(minutes=1)
        ).isoformat()
        _append_proposal_message(
            page,
            'ui-capability-proposal-expired',
            expired_metadata,
        )
        expired_card = page.locator(
            '[data-message-id="ui-capability-proposal-expired"]'
        ).get_by_test_id('capability-choice-card')
        expect(expired_card.get_by_role('button')).to_have_count(0)
        expect(expired_card.get_by_role('status')).to_contain_text(
            'This capability choice has expired.'
        )

        context.close()
        browser.close()


@pytest.mark.ui
@pytest.mark.parametrize(
    'viewport',
    [
        {'width': 1280, 'height': 900},
        {'width': 390, 'height': 844},
    ],
)
def test_governed_agent_choice_is_inert_minimal_and_refreshable(viewport):
    from playwright.sync_api import expect, sync_playwright

    chat_url = _get_chat_test_url()
    decision_requests = []
    resume_requests = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = _create_context(browser, viewport)
        page = context.new_page()

        def handle_decision(route):
            decision_requests.append(json.loads(route.request.post_data or '{}'))
            route.fulfill(
                status=200,
                content_type='application/json',
                body=json.dumps({
                    'success': True,
                    'status': 'approved',
                    'resume_status': 'pending',
                    'resume_endpoint': '/api/chat/stream',
                }),
            )

        def handle_resume(route):
            resume_requests.append(json.loads(route.request.post_data or '{}'))
            route.fulfill(
                status=200,
                content_type='text/event-stream',
                body=(
                    'data: '
                    + json.dumps({
                        'done': True,
                        'message_id': 'ui-agent-resumed-assistant',
                        'full_content': 'Completed with governed agent evidence.',
                    })
                    + '\n\n'
                ),
            )

        page.route('**/api/chat/capability-proposals/*/decision', handle_decision)
        page.route('**/api/chat/stream', handle_resume)
        page.goto(chat_url, wait_until='domcontentloaded')

        proposal_id = 'ui-agent-proposal-pending'
        _append_proposal_message(
            page,
            proposal_id,
            _agent_proposal_metadata(proposal_id),
        )
        card = page.locator(
            f'[data-message-id="{proposal_id}"]'
        ).get_by_test_id('capability-choice-card')
        agent_button = card.get_by_role('button').filter(has_text='Benefits <img')
        expect(card).to_be_visible()
        expect(card.get_by_text('A specialized authorized agent could materially improve this answer.')).to_be_visible()
        expect(card.get_by_test_id('agent-external-data-notice')).to_be_visible()
        expect(agent_button).to_be_enabled()
        expect(agent_button.get_by_test_id('capability-option-description')).to_contain_text(
            'Group governed agent'
        )
        expect(agent_button.get_by_test_id('capability-option-summary')).to_contain_text('Seconds')
        expect(agent_button.get_by_test_id('capability-option-summary')).to_contain_text('Standard')
        expect(agent_button).not_to_contain_text('Risk:')
        expect(agent_button).not_to_contain_text('Data:')
        assert card.locator('img').count() == 0
        assert page.evaluate('() => window.phase8bInjected === true') is False

        status_id = agent_button.get_attribute('aria-describedby')
        assert status_id
        expect(card.locator(f'#{status_id}')).to_have_attribute('aria-live', 'polite')
        layout = card.evaluate(
            """
            element => ({
                overflows: element.scrollWidth > element.clientWidth,
                right: element.getBoundingClientRect().right,
                viewportWidth: window.innerWidth,
                buttonHeights: Array.from(element.querySelectorAll('button')).map(button => button.getBoundingClientRect().height),
                optionWidths: Array.from(element.querySelectorAll('.sc-capability-choice-option-card')).map(option => option.getBoundingClientRect().width),
                continueWidth: element.querySelector('.sc-capability-choice-continue')?.getBoundingClientRect().width || 0,
                gridWidth: element.querySelector('.sc-capability-choice-option-grid')?.getBoundingClientRect().width || 0
            })
            """
        )
        assert layout['overflows'] is False
        assert layout['right'] <= layout['viewportWidth'] + 1
        assert all(height >= 44 for height in layout['buttonHeights'])
        assert abs(layout['continueWidth'] - layout['gridWidth']) <= 1

        agent_button.focus()
        agent_button.press('Enter')
        expect(card.get_by_role('status')).to_contain_text('Completed with Benefits <img')
        assert decision_requests == [{
            'conversation_id': 'ui-capability-conversation',
            'option_id': 'agent:group:0123456789abcdef0123456789abcdef',
        }]
        assert resume_requests == [{
            'conversation_id': 'ui-capability-conversation',
            'capability_resume_proposal_id': proposal_id,
        }]

        refresh_cases = [
            ('approved', 'failed', 'Retry resume', 'remains approved for this turn.'),
            ('approved', 'completed', None, 'Completed with Benefits <img'),
            ('invalidated', 'failed', None, 'no longer available'),
        ]
        for index, (status, resume_status, button_name, status_text) in enumerate(refresh_cases):
            refresh_id = f'ui-agent-proposal-refresh-{index}'
            _append_proposal_message(
                page,
                refresh_id,
                _agent_proposal_metadata(
                    refresh_id,
                    status=status,
                    resume_status=resume_status,
                ),
            )
            refreshed_card = page.locator(
                f'[data-message-id="{refresh_id}"]'
            ).get_by_test_id('capability-choice-card')
            expect(refreshed_card.get_by_role('status')).to_contain_text(status_text)
            if button_name:
                expect(refreshed_card.get_by_role('button', name=button_name)).to_be_visible()
            else:
                expect(refreshed_card.get_by_role('button')).to_have_count(0)

        context.close()
        browser.close()