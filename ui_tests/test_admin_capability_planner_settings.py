# test_admin_capability_planner_settings.py
"""Azure Playwright UI tests for governed capability planner settings.

Version: 0.250.072
Implemented in: 0.250.072

This test verifies that administrators can select off, shadow, or assist mode
and edit bounded planner controls without layout overflow.
"""

import os

import pytest


def _admin_settings_url():
    url = os.getenv('SIMPLECHAT_PLAYWRIGHT_ADMIN_SETTINGS_URL', '').strip()
    if not url:
        pytest.skip(
            'Set SIMPLECHAT_PLAYWRIGHT_ADMIN_SETTINGS_URL to run planner settings UI tests.'
        )
    return url


@pytest.mark.ui
@pytest.mark.parametrize(
    'viewport',
    [
        {'width': 1280, 'height': 900},
        {'width': 390, 'height': 844},
    ],
)
def test_capability_planner_settings_are_accessible_and_responsive(viewport):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context_kwargs = {'viewport': viewport, 'ignore_https_errors': True}
        storage_state = os.getenv('SIMPLECHAT_PLAYWRIGHT_STORAGE_STATE', '').strip()
        if storage_state:
            context_kwargs['storage_state'] = storage_state
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.goto(f"{_admin_settings_url().split('#', 1)[0]}#ai-models")

        panel = page.get_by_test_id('chat-capability-planner-settings')
        expect(panel).to_be_visible()
        expect(panel.get_by_role('radio', name='Off')).to_be_visible()
        expect(panel.get_by_role('radio', name='Shadow')).to_be_visible()
        expect(panel.get_by_role('radio', name='Assist')).to_be_visible()
        panel.get_by_role('radio', name='Assist').check()
        expect(panel.get_by_role('radio', name='Assist')).to_be_checked()

        timeout = panel.get_by_label('Timeout (ms)')
        timeout.fill('5000')
        expect(timeout).to_have_value('5000')
        layout = panel.evaluate(
            """
            element => ({
                overflows: element.scrollWidth > element.clientWidth,
                right: element.getBoundingClientRect().right,
                viewportWidth: window.innerWidth,
            })
            """
        )
        assert layout['overflows'] is False
        assert layout['right'] <= layout['viewportWidth'] + 1

        context.close()
        browser.close()