# test_web_search_notice_copy.py
"""
UI test for web search disclosure copy.
Version: 0.241.008
Implemented in: 0.241.008

This test ensures the admin settings page shows the updated current-message-only
web-search disclosure copy for the user notice placeholder and the admin
consent modal warning text.
"""

import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')


@pytest.mark.ui
def test_admin_settings_shows_current_message_only_web_search_notice(playwright):
    """Validate the admin-facing web-search disclosure copy."""
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.')

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={'width': 1440, 'height': 900},
    )
    page = context.new_page()

    try:
        page.goto(f'{BASE_URL}/admin/settings', wait_until='networkidle')

        notice_textarea = page.locator('#web_search_user_notice_text')
        expect(notice_textarea).to_have_count(1)
        expect(notice_textarea).to_have_attribute(
            'placeholder',
            re.compile(r'Your current message will be sent to Microsoft Bing for web search', re.IGNORECASE),
        )

        consent_modal = page.locator('#web-search-consent-modal')
        expect(consent_modal).to_have_count(1)
        consent_text = consent_modal.text_content() or ''
        assert 'Only the user\'s current message is sent for web search.' in consent_text
        assert 'Users should avoid including sensitive content in any message that uses web search.' in consent_text
    finally:
        context.close()
        browser.close()