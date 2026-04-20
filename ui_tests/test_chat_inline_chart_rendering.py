# test_chat_inline_chart_rendering.py
"""
UI test for inline chart rendering in chat.
Version: 0.241.047
Implemented in: 0.241.047

This test ensures that assistant messages can render inline Chart.js visualizations
in the chat page and that the optional data table is accessible in desktop and mobile layouts.
"""

import os
import time

import pytest


playwright_sync_api = pytest.importorskip('playwright.sync_api')
expect = playwright_sync_api.expect
sync_playwright = playwright_sync_api.sync_playwright


def _get_chat_test_url():
    chat_url = os.getenv('SIMPLECHAT_PLAYWRIGHT_CHAT_URL', '').strip()
    if not chat_url:
        pytest.skip('Set SIMPLECHAT_PLAYWRIGHT_CHAT_URL to run inline chart UI tests.')
    return chat_url


def _create_context(browser, viewport):
    context_kwargs = {'viewport': viewport}
    storage_state_path = os.getenv('SIMPLECHAT_PLAYWRIGHT_STORAGE_STATE', '').strip()
    if storage_state_path:
        context_kwargs['storage_state'] = storage_state_path
    return browser.new_context(**context_kwargs)


def _append_inline_chart_message(page, message_id):
    chart_message = (
        'Quarterly revenue is trending above target.\n\n'
        '```simplechart\n'
        '{"version":1,"kind":"line","chartType":"line","chartId":"ui-inline-chart","title":"Quarterly Revenue Trend","subtitle":"Actual versus target","description":"Interactive inline chart regression test.","summary":"Line with 2 series across 4 categories.","options":{"legendPosition":"top","showLegend":true,"showDataTable":true,"beginAtZero":true,"horizontal":false,"fill":false,"smooth":true,"stacked":false,"xAxisLabel":"Quarter","yAxisLabel":"Revenue"},"data":{"labels":["Q1","Q2","Q3","Q4"],"datasets":[{"label":"Revenue","data":[120,142,159,171],"borderColor":"#1c6ea4","backgroundColor":"rgba(28,110,164,0.18)","borderWidth":2,"fill":false,"tension":0.35},{"label":"Target","data":[110,135,150,165],"borderColor":"#d75b35","backgroundColor":"rgba(215,91,53,0.18)","borderWidth":2,"fill":false,"tension":0.35}]},"table":{"columns":["Label","Revenue","Target"],"rows":[["Q1",120,110],["Q2",142,135],["Q3",159,150],["Q4",171,165]]}}\n'
        '```'
    )

    page.wait_for_function("() => window.chatMessages && typeof window.chatMessages.appendMessage === 'function'")
    page.evaluate(
        """
        ({ messageId, content }) => {
            window.chatMessages.appendMessage(
                'AI',
                content,
                'chart-inline-test',
                messageId,
                false,
                [],
                [],
                [],
                null,
                null,
                null,
                false
            );
        }
        """,
        {'messageId': message_id, 'content': chart_message},
    )


@pytest.mark.ui
def test_chat_inline_chart_rendering_desktop():
    """Validate desktop inline chart rendering and data-table toggling inside chat."""
    chat_url = _get_chat_test_url()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = _create_context(browser, {'width': 1440, 'height': 900})
        page = context.new_page()
        page.goto(chat_url, wait_until='domcontentloaded')

        if 'login' in page.url.lower():
            pytest.skip('Inline chart UI test requires an authenticated chat session.')

        message_id = f'inline-chart-desktop-{int(time.time())}'
        _append_inline_chart_message(page, message_id)

        chart_container = page.locator(f'[data-message-id="{message_id}"] .sc-inline-chart canvas')
        expect(chart_container).to_be_visible()

        table_toggle = page.locator(f'[data-message-id="{message_id}"] .sc-inline-chart-table-toggle')
        expect(table_toggle).to_be_visible()
        table_toggle.click()
        expect(page.locator(f'[data-message-id="{message_id}"] table')).to_be_visible()

        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_inline_chart_rendering_mobile():
    """Validate that inline charts still render in a mobile viewport."""
    chat_url = _get_chat_test_url()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = _create_context(browser, {'width': 390, 'height': 844})
        page = context.new_page()
        page.goto(chat_url, wait_until='domcontentloaded')

        if 'login' in page.url.lower():
            pytest.skip('Inline chart UI test requires an authenticated chat session.')

        message_id = f'inline-chart-mobile-{int(time.time())}'
        _append_inline_chart_message(page, message_id)

        chart_container = page.locator(f'[data-message-id="{message_id}"] .sc-inline-chart canvas')
        expect(chart_container).to_be_visible()

        table_toggle = page.locator(f'[data-message-id="{message_id}"] .sc-inline-chart-table-toggle')
        expect(table_toggle).to_be_visible()

        context.close()
        browser.close()