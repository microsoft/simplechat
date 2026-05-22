# test_advanced_conversation_search_match_mode.py
"""
UI test for advanced conversation search match mode selection.
Version: 0.241.097
Implemented in: 0.241.097

This test ensures the advanced search modal sends the selected partial-match
mode to the backend when a user searches conversation titles and messages.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.')


@pytest.mark.ui
def test_advanced_conversation_search_sends_match_mode(playwright):
    """Validate that the modal posts the selected match mode."""
    _require_authenticated_chat_env()

    from playwright.sync_api import expect

    captured_payload = {}

    browser = playwright.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE)
    page = context.new_page()

    def handle_classifications(route):
        route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({'success': True, 'classifications': []}),
        )

    def handle_search_history(route):
        if route.request.method == 'GET':
            body = {'success': True, 'history': []}
        else:
            body = {'success': True, 'history': []}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body))

    def handle_search(route):
        nonlocal captured_payload
        captured_payload = route.request.post_data_json
        route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'total_results': 0,
                'page': 1,
                'total_pages': 1,
                'per_page': 20,
                'results': [],
            }),
        )

    try:
        page.route('**/api/conversations/classifications', handle_classifications)
        page.route('**/api/user-settings/search-history', handle_search_history)
        page.route('**/api/search_conversations', handle_search)

        response = page.goto(f'{BASE_URL}/chats', wait_until='networkidle')
        assert response is not None and response.ok, 'Expected /chats to load successfully.'

        page.wait_for_function('window.chatSearchModal && window.chatSearchModal.openAdvancedSearchModal')
        page.evaluate('window.chatSearchModal.openAdvancedSearchModal()')

        expect(page.locator('#advancedSearchModal.show')).to_be_visible()
        page.locator('#searchMessageInput').fill('Chase')
        page.locator('#searchMatchMode').select_option('contains')

        with page.expect_response(lambda response: '/api/search_conversations' in response.url):
            page.locator('#performSearchBtn').click()

        assert captured_payload.get('search_term') == 'Chase'
        assert captured_payload.get('match_mode') == 'contains'
        assert 'personal' in captured_payload.get('chat_types', [])
        assert 'group_multi_user' in captured_payload.get('chat_types', [])
    finally:
        context.close()
        browser.close()