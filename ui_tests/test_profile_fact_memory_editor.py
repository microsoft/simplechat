# test_profile_fact_memory_editor.py
"""
UI test for the profile fact-memory editor.
Version: 0.240.077
Implemented in: 0.240.077

This test ensures a signed-in user can create, edit, and delete fact-memory
entries from the profile page.
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
        response = page.goto(f'{BASE_URL}/profile', wait_until='domcontentloaded')
        assert response is not None, 'Expected a navigation response when loading /profile.'
        if response.status in {401, 403, 404}:
            pytest.skip('Profile page was not available for the configured session.')

        assert response.ok, f'Expected /profile to load successfully, got HTTP {response.status}.'
        expect(page.get_by_role('heading', name='Fact Memory')).to_be_visible()
        expect(page.locator('#fact-memory-status')).to_contain_text(re.compile(r'Fact memory is'))

        items = page.locator('[data-fact-memory-id]')
        initial_count = items.count()
        created_value = f'UI fact memory {uuid.uuid4().hex[:8]}'
        updated_value = f'{created_value} updated'

        page.locator('#fact-memory-new-value').fill(created_value)
        page.locator('#fact-memory-add-btn').click()
        expect(page.locator('#fact-memory-status')).to_contain_text('saved')
        expect(items).to_have_count(initial_count + 1)

        created_item = page.locator('[data-fact-memory-id]').first
        created_fact_id = created_item.get_attribute('data-fact-memory-id')
        assert created_fact_id, 'Expected a fact-memory item id after creating an entry.'
        expect(created_item.locator('textarea[aria-label="Fact memory value"]')).to_have_value(created_value)

        created_item.locator('textarea[aria-label="Fact memory value"]').fill(updated_value)
        created_item.get_by_role('button', name='Save memory').click()
        expect(page.locator('#fact-memory-status')).to_contain_text('updated')

        updated_item = page.locator(f'[data-fact-memory-id="{created_fact_id}"]')
        expect(updated_item.locator('textarea[aria-label="Fact memory value"]')).to_have_value(updated_value)

        updated_item.get_by_role('button', name='Delete memory').click()
        expect(page.get_by_role('dialog', name='Delete Fact Memory')).to_be_visible()
        page.locator('#confirm-delete-fact-memory-btn').click()
        expect(page.locator('#fact-memory-status')).to_contain_text('deleted')
        expect(page.locator(f'[data-fact-memory-id="{created_fact_id}"]')).to_have_count(0)
        assert page.locator('[data-fact-memory-id]').count() == initial_count
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