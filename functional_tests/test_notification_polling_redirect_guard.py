#!/usr/bin/env python3
# test_notification_polling_redirect_guard.py
"""
Functional test for notification polling redirect guards.
Version: 0.250.015
Implemented in: 0.250.015

This test ensures notification polling only loads for authenticated sessions and
stops after auth-like or repeated fetch failures so the browser does not spam
redirect-loop errors in the console or 401s in the backend log stream.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_notification_polling_redirect_guard_contract() -> None:
    config_content = read_text('application/single_app/config.py')
    base_template_content = read_text('application/single_app/templates/base.html')
    notifications_js_content = read_text('application/single_app/static/js/notifications.js')

    assert 'VERSION = "0.250.015"' in config_content
    assert "{% if session.get('user') %}\n  <!-- Notifications JavaScript (for badge polling on authenticated pages) -->" in base_template_content
    assert "<script src=\"{{ url_for('static', filename='js/notifications.js') }}\"></script>" in base_template_content
    assert 'const MAX_NOTIFICATION_POLL_FAILURES = 3;' in notifications_js_content
    assert 'let notificationPollingDisabled = false;' in notifications_js_content
    assert 'function disableNotificationPolling(reason) {' in notifications_js_content
    assert 'function parseNotificationJsonResponse(response, endpointLabel) {' in notifications_js_content
    assert "Expected JSON from ${endpointLabel}" in notifications_js_content
    assert 'error?.shouldDisableNotificationPolling || consecutivePollFailures >= MAX_NOTIFICATION_POLL_FAILURES' in notifications_js_content
    assert 'if (notificationPollingDisabled || isPolling) return;' in notifications_js_content
    assert 'scheduleNotificationPoll();' in notifications_js_content
    assert 'window.simpleChatNotifications = {' in notifications_js_content
    assert 'isPollingDisabled: () => notificationPollingDisabled,' in notifications_js_content
