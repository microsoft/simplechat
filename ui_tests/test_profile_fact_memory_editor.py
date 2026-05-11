# test_profile_fact_memory_editor.py
"""
UI test for the profile fact-memory editor.
Version: 0.241.008
Implemented in: 0.240.079; 0.240.082; 0.240.083; 0.241.003; 0.241.004; 0.241.008

This test ensures a signed-in user can create, edit, retag, and delete
fact-memory entries from the profile page using the compact summary and modal editor
without browser parse or runtime errors breaking the workflow.
"""

import os
import re
import uuid
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')
ADMIN_STORAGE_STATE = os.getenv('SIMPLECHAT_UI_ADMIN_STORAGE_STATE', '')


def _require_base_url():
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')


def _get_storage_state_path():
    for candidate in (STORAGE_STATE, ADMIN_STORAGE_STATE):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.')


@pytest.mark.ui
def test_profile_fact_memory_editor(playwright):
    """Validate that profile users can create, edit, and delete fact memories."""
    _require_base_url()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={'width': 1440, 'height': 900},
    )

    created_fact_id = None
    try:
        page = context.new_page()
        page_errors = []
        console_errors = []

        page.on('pageerror', lambda error: page_errors.append(str(error)))
        page.on(
            'console',
            lambda message: console_errors.append(message.text) if message.type == 'error' else None,
        )

        response = page.goto(f'{BASE_URL}/profile', wait_until='domcontentloaded')
        assert response is not None, 'Expected a navigation response when loading /profile.'
        if response.status in {401, 403, 404}:
            pytest.skip('Profile page was not available for the configured session.')

        assert response.ok, f'Expected /profile to load successfully, got HTTP {response.status}.'
        expect(page.get_by_role('heading', name='Fact Memory')).to_be_visible()
        expect(page.locator('#fact-memory-status')).to_contain_text(re.compile(r'Fact memory is'))
        expect(page.locator('#tutorial-preferences')).to_have_count(1)
        expect(page.locator('#fact-memory-settings')).to_have_count(1)
        expect(page.locator('#factMemoryDeleteModal')).to_have_count(1)
        expect(page.locator('#factMemoryManagerModal')).to_have_count(1)
        if page.locator('#tts-preview-btn').count():
            expect(page.locator('#tts-preview-btn')).to_be_visible()
            expect(page.locator('#tts-stop-btn')).to_be_hidden()
            tts_stop_classes = page.locator('#tts-stop-btn').get_attribute('class') or ''
            assert 'd-none' in tts_stop_classes, 'Expected the hidden TTS stop button to use Bootstrap d-none.'
        assert not page_errors, f'Unexpected profile page errors: {page_errors}'
        duplicate_declaration_errors = [
            message for message in console_errors
            if 'factMemoryEntries' in message
            or 'factMemorySearchInput' in message
            or 'already been declared' in message
            or 'Identifier' in message
            or 'SyntaxError' in message
        ]
        assert not duplicate_declaration_errors, (
            'Unexpected profile console errors during page load: '
            f'{duplicate_declaration_errors}'
        )
        count_before_text = page.locator('#fact-memory-count').text_content() or '0'
        initial_count = int(count_before_text.strip())

        created_value = f'UI fact memory {uuid.uuid4().hex[:8]}'
        updated_value = f'{created_value} updated'

        page.locator('#fact-memory-new-value').fill(created_value)
        page.locator('#fact-memory-new-type').select_option('instruction')
        page.locator('#fact-memory-add-btn').click()
        expect(page.locator('#fact-memory-status')).to_contain_text('saved')
        expect(page.locator('#fact-memory-count')).to_have_text(str(initial_count + 1))

        page.locator('#open-fact-memory-modal-btn').click()
        manager_dialog = page.get_by_role('dialog', name='Manage Fact Memories')
        expect(manager_dialog).to_be_visible()

        search_input = page.locator('#fact-memory-search-input')
        search_input.fill(created_value)

        items = page.locator('#fact-memory-modal-list [data-fact-memory-id]')
        expect(items).to_have_count(1)

        created_item = items.first
        created_fact_id = created_item.get_attribute('data-fact-memory-id')
        assert created_fact_id, 'Expected a fact-memory item id after creating an entry.'
        expect(created_item.locator('textarea[aria-label="Fact memory value"]')).to_have_value(created_value)
        expect(created_item).to_contain_text('Instruction')
        expect(created_item.locator('select[aria-label="Fact memory type"]')).to_have_value('instruction')

        created_item.locator('textarea[aria-label="Fact memory value"]').fill(updated_value)
        created_item.locator('select[aria-label="Fact memory type"]').select_option('fact')
        created_item.get_by_role('button', name='Save memory').click()
        expect(page.locator('#fact-memory-status')).to_contain_text('updated')

        search_input.fill(updated_value)
        updated_item = page.locator(f'#fact-memory-modal-list [data-fact-memory-id="{created_fact_id}"]')
        expect(updated_item.locator('textarea[aria-label="Fact memory value"]')).to_have_value(updated_value)
        expect(updated_item.locator('select[aria-label="Fact memory type"]')).to_have_value('fact')
        expect(updated_item).to_contain_text('Fact')

        updated_item.get_by_role('button', name='Delete memory').click()
        delete_dialog = page.get_by_role('dialog', name='Delete Fact Memory')
        expect(manager_dialog).to_be_visible()
        expect(delete_dialog).to_be_visible()

        stacking_state = page.evaluate(
            """
            () => {
                const managerModal = document.getElementById('factMemoryManagerModal');
                const deleteModal = document.getElementById('factMemoryDeleteModal');
                const backdrops = Array.from(document.querySelectorAll('.modal-backdrop'));
                const latestBackdrop = backdrops.length ? backdrops[backdrops.length - 1] : null;
                return {
                    managerZ: Number(window.getComputedStyle(managerModal).zIndex || 0),
                    deleteZ: Number(window.getComputedStyle(deleteModal).zIndex || 0),
                    deleteClasses: deleteModal.className,
                    latestBackdropClasses: latestBackdrop ? latestBackdrop.className : '',
                };
            }
            """
        )
        assert stacking_state['deleteZ'] > stacking_state['managerZ'], (
            'Expected the delete confirm modal to stack above the manager modal. '
            f'Saw manager z-index {stacking_state["managerZ"]} and delete z-index {stacking_state["deleteZ"]}.'
        )
        assert 'fact-memory-delete-modal-stacked' in stacking_state['deleteClasses']
        assert 'fact-memory-delete-backdrop-stacked' in stacking_state['latestBackdropClasses']

        page.locator('#confirm-delete-fact-memory-btn').click()
        expect(page.locator('#fact-memory-status')).to_contain_text('deleted')
        expect(delete_dialog).to_be_hidden()
        expect(manager_dialog).to_be_visible()
        assert page.evaluate("() => document.body.classList.contains('modal-open')"), (
            'Expected the manager modal to keep the page in modal-open state after the delete confirm closes.'
        )
        search_input.fill('')
        expect(search_input).to_have_value('')
        expect(page.locator(f'#fact-memory-modal-list [data-fact-memory-id="{created_fact_id}"]')).to_have_count(0)
        expect(page.locator('#fact-memory-count')).to_have_text(str(initial_count))
        created_fact_id = None
    finally:
        if created_fact_id:
            page.evaluate(
                """
                async ({ baseUrl, factId }) => {
                    await fetch(`${baseUrl}/api/profile/fact-memory/${encodeURIComponent(factId)}`, {
                        method: 'DELETE',
                        credentials: 'same-origin'
                    });
                }
                """,
                {'baseUrl': BASE_URL, 'factId': created_fact_id},
            )
        context.close()
        browser.close()