# test_chat_capability_metadata_drawer.py
"""
UI test for chat capability metadata drawer labels.
Version: 0.241.123
Implemented in: 0.241.123

This test ensures user and assistant message metadata drawers render explicit
workspace action, Web Search, and Deep Research usage flags.
"""

import json
import os
from pathlib import Path

import pytest

playwright_sync_api = pytest.importorskip('playwright.sync_api')
expect = playwright_sync_api.expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')


def _require_ui_env():
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.')


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type='application/json',
        body=json.dumps(payload),
    )


def _build_capability_usage():
    return {
        'actions': {
            'search': True,
            'analyze': False,
            'compare': False,
        },
        'workspace': {
            'enabled': True,
            'used': True,
            'action': 'search',
            'document_action_type': 'none',
            'search_enabled': True,
            'search_used': True,
            'result_count': 3,
            'document_scope': 'all',
            'selected_document_count': 0,
            'active_group_count': 0,
            'active_public_workspace_count': 0,
        },
        'web_search': {
            'enabled': True,
            'used': True,
            'citation_count': 2,
            'run_count': 2,
        },
        'url_access': {
            'enabled': True,
            'used': False,
            'source_review_enabled': True,
        },
        'deep_research': {
            'enabled': True,
            'used': True,
            'query_count': 2,
            'source_review_enabled': True,
        },
    }


@pytest.mark.ui
def test_chat_metadata_drawers_show_capability_usage(playwright):
    """Validate user and assistant metadata drawers show explicit capability flags."""
    _require_ui_env()

    capability_usage = _build_capability_usage()
    user_metadata = {
        'button_states': {
            'image_generation': False,
            'document_search': True,
            'web_search': True,
            'url_access': True,
            'deep_research': True,
        },
        'workspace_search': {
            'search_enabled': True,
            'document_scope': 'all',
        },
        'capability_usage': capability_usage,
        'chat_context': {
            'conversation_id': 'capability-convo',
            'chat_type': 'personal_single_user',
        },
    }
    assistant_payload = {
        'id': 'assistant-capability-1',
        'conversation_id': 'capability-convo',
        'role': 'assistant',
        'content': 'Research response with explicit capability metadata.',
        'timestamp': '2026-05-28T12:00:00Z',
        'augmented': True,
        'hybrid_citations': [],
        'web_search_citations': [
            {'title': 'Example Source', 'url': 'https://example.com/source'},
        ],
        'agent_citations': [],
        'model_deployment_name': 'gpt-4o',
        'metadata': {
            'capability_usage': capability_usage,
            'deep_research': {
                'enabled': True,
                'query_count': 2,
            },
        },
    }

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={'width': 1440, 'height': 900},
    )
    page = context.new_page()

    page.route(
        '**/api/user/settings',
        lambda route: _fulfill_json(route, {'selected_agent': None, 'settings': {'enable_agents': False}}),
    )
    page.route('**/api/get_conversations', lambda route: _fulfill_json(route, {'conversations': []}))
    page.route('**/api/message/user-capability-1/metadata', lambda route: _fulfill_json(route, user_metadata))
    page.route('**/api/message/assistant-capability-1/metadata', lambda route: _fulfill_json(route, assistant_payload))

    try:
        page.goto(f'{BASE_URL}/chats', wait_until='domcontentloaded')
        page.wait_for_selector('#chatbox')

        page.evaluate(
            """
            async ({ userMetadata, assistantPayload }) => {
                currentConversationId = 'capability-convo';
                window.currentConversationId = 'capability-convo';

                const messagesModule = await import('/static/js/chat/chat-messages.js');
                messagesModule.appendMessage(
                    'You',
                    'Please search and run deep research.',
                    null,
                    'user-capability-1',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'user-capability-1',
                        conversation_id: 'capability-convo',
                        role: 'user',
                        metadata: userMetadata,
                    },
                    true
                );
                messagesModule.appendMessage(
                    'AI',
                    assistantPayload.content,
                    assistantPayload.model_deployment_name,
                    assistantPayload.id,
                    assistantPayload.augmented,
                    assistantPayload.hybrid_citations,
                    assistantPayload.web_search_citations,
                    assistantPayload.agent_citations,
                    assistantPayload.agent_display_name,
                    assistantPayload.agent_name,
                    assistantPayload,
                    true
                );
            }
            """,
            {'userMetadata': user_metadata, 'assistantPayload': assistant_payload},
        )

        user_message = page.locator('.message[data-message-id="user-capability-1"]')
        assistant_message = page.locator('.message[data-message-id="assistant-capability-1"]')

        user_message.locator('button.metadata-toggle-btn').click()
        user_metadata_container = user_message.locator('.metadata-container')
        expect(user_metadata_container).to_contain_text('Capability Usage')
        expect(user_metadata_container).to_contain_text('Deep Research')
        expect(user_metadata_container).to_contain_text('Web Search Used')

        assistant_message.locator('button.metadata-info-btn').click()
        assistant_metadata_container = assistant_message.locator('.metadata-container')
        expect(assistant_metadata_container).to_contain_text('Workspace Action')
        expect(assistant_metadata_container).to_contain_text('Web Search Used')
        expect(assistant_metadata_container).to_contain_text('Deep Research Used')
    finally:
        context.close()
        browser.close()