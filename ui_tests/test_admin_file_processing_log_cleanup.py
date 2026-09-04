# test_admin_file_processing_log_cleanup.py
"""
UI test for Admin Settings file processing log cleanup.
Version: 0.250.075
Implemented in: 0.250.075

This test validates safe cleanup controls, confirmation behavior, request
payloads, exact deletion feedback, cancellation, and visible API failures.
"""

import json
import os
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / 'application' / 'single_app' / 'templates' / 'admin_settings.html'
ADMIN_JS = REPO_ROOT / 'application' / 'single_app' / 'static' / 'js' / 'admin' / 'admin_settings.js'
BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_ADMIN_STORAGE_STATE') or os.getenv(
    'SIMPLECHAT_UI_STORAGE_STATE',
    '',
)


def test_file_processing_log_cleanup_controls_are_safe_and_accessible():
    """Validate the static UI and client contract."""
    template = ADMIN_TEMPLATE.read_text(encoding='utf-8')
    js_source = ADMIN_JS.read_text(encoding='utf-8')

    required_ids = [
        'file-processing-log-cleanup-heading',
        'file-processing-log-cleanup-age',
        'file-processing-log-cleanup-unit',
        'delete-old-file-processing-logs-btn',
        'delete-all-file-processing-logs-btn',
        'fileProcessingLogCleanupModal',
        'file-processing-log-cleanup-confirmation',
        'confirm-file-processing-log-cleanup-btn',
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert 'data-ignore-settings-change="true"' in template
    assert 'This action cannot be undone.' in template
    assert 'One month is treated as 30 days.' in template
    assert 'aria-describedby="file-processing-log-cleanup-confirmation"' in template
    assert (
        '                    </div>\n\n'
        '                    <hr class="my-4" />\n'
        '                    <section aria-labelledby="file-processing-log-cleanup-heading"'
    ) in template
    assert 'onclick=' not in template[
        template.index('id="file-processing-logs-section"'):
        template.index('id="general"')
    ]
    assert "elements.confirmationText.textContent = message" in js_source
    assert "'/api/admin/settings/file-processing-logs/cleanup'" in js_source
    assert '{ delete_all: false, age, unit }' in js_source
    assert '{ delete_all: true }' in js_source
    assert 'confirmed: true' in js_source
    assert "credentials: 'same-origin'" in js_source
    assert 'setupFileProcessingLogCleanup();' in js_source


@pytest.mark.ui
def test_file_processing_log_cleanup_browser_workflow():
    """Exercise cancellation, scoped deletion, and visible delete-all failure."""
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid admin storage state file.')
    if expect is None or sync_playwright is None:
        pytest.skip('Install playwright to run this UI test.')

    requests = []

    def handle_cleanup(route):
        payload = route.request.post_data_json
        requests.append(payload)
        if payload.get('delete_all'):
            route.fulfill(
                status=500,
                content_type='application/json',
                body=json.dumps({
                    'success': False,
                    'error': 'File processing log cleanup did not complete.',
                    'deleted_count': 1,
                }),
            )
            return
        route.fulfill(
            status=200,
            content_type='application/json',
            body=json.dumps({
                'success': True,
                'deleted_count': 2,
                'delete_all': False,
                'cutoff': '2026-07-16T12:00:00+00:00',
            }),
        )

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={'width': 1440, 'height': 900})
    page = context.new_page()
    page.route('**/api/admin/settings/file-processing-logs/cleanup', handle_cleanup)

    try:
        response = page.goto(f'{BASE_URL}/admin/settings#logging', wait_until='networkidle')
        if response and response.status >= 400:
            pytest.skip('Admin settings are not accessible with the configured storage state.')
        if page.locator('#logging-tab').count() == 0:
            pytest.skip('Admin settings are not accessible with the configured storage state.')

        page.locator('#logging-tab').click()
        page.locator('#file-processing-log-cleanup-age').fill('2')
        page.locator('#file-processing-log-cleanup-unit').select_option('weeks')
        page.locator('#delete-old-file-processing-logs-btn').click()
        expect(page.locator('#file-processing-log-cleanup-confirmation')).to_have_text(
            'Delete every file processing log older than 2 weeks?'
        )
        page.get_by_role('button', name='Cancel').click()
        expect(page.locator('#fileProcessingLogCleanupModal')).to_be_hidden()
        assert requests == []

        page.locator('#delete-old-file-processing-logs-btn').click()
        page.locator('#confirm-file-processing-log-cleanup-btn').click()
        expect(page.get_by_text('2 file processing logs deleted.')).to_be_visible()
        assert requests[0] == {
            'delete_all': False,
            'age': 2,
            'unit': 'weeks',
            'confirmed': True,
        }

        page.locator('#delete-all-file-processing-logs-btn').click()
        expect(page.locator('#file-processing-log-cleanup-confirmation')).to_have_text(
            'Delete every stored file processing log?'
        )
        page.locator('#confirm-file-processing-log-cleanup-btn').click()
        expect(
            page.get_by_text(
                'File processing log cleanup did not complete. '
                '1 log was deleted before the operation stopped.'
            )
        ).to_be_visible()
        assert requests[1] == {'delete_all': True, 'confirmed': True}
    finally:
        context.close()
        browser.close()
        playwright_context.stop()
