# test_notifications_polling_redirect_guard.py
"""
UI test for notification polling redirect guards.
Version: 0.241.095
Implemented in: 0.241.095

This test ensures an auth-like notification polling response disables further
notification polling for the current page session instead of retrying forever.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.')


@pytest.mark.ui
def test_notifications_polling_stops_after_auth_like_response(playwright):
    """Validate that notification polling disables itself after an auth-like response."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={'width': 1440, 'height': 900},
    )
    page = context.new_page()
    count_request_count = 0

    def handle_notification_count(route):
        nonlocal count_request_count
        count_request_count += 1
        route.fulfill(
            status=200,
            content_type='text/html',
            body='<html><body>Authentication required</body></html>',
        )

    page.route('**/api/notifications/count', handle_notification_count)
    page.route('**/api/notifications?*', lambda route: route.fulfill(
        status=200,
        content_type='application/json',
        body=json.dumps({
            'success': True,
            'notifications': [],
            'total': 0,
            'page': 1,
            'per_page': 20,
            'has_more': False,
        }),
    ))
    page.route('**/api/notifications/workflow-alerts?*', lambda route: route.fulfill(
        status=200,
        content_type='application/json',
        body=json.dumps({'success': True, 'notifications': []}),
    ))

    try:
        response = page.goto(f'{BASE_URL}/notifications', wait_until='networkidle')
        assert response is not None, 'Expected a navigation response when loading /notifications.'

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f'Notifications page unavailable in this environment (HTTP {response.status}).')

        assert response.ok, f'Expected /notifications to load successfully, got HTTP {response.status}.'

        page.wait_for_function(
            '() => Boolean(window.simpleChatNotifications?.isPollingDisabled && window.simpleChatNotifications.isPollingDisabled())'
        )
        page.wait_for_timeout(250)
        assert count_request_count == 1
    finally:
        context.close()
        browser.close()