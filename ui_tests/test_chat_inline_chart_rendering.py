# test_chat_inline_chart_rendering.py
"""
UI test for inline chart rendering in chat.
Version: 0.241.146
Implemented in: 0.241.047; YAML and pending-source rendering fixed in 0.241.126; final metadata rendering fixed in 0.241.134; streaming chart stability fixed in 0.241.141; chart color editor added in 0.241.145; edited chart export override added in 0.241.146

This test ensures that assistant messages can render inline Chart.js visualizations
in the chat page, that the optional data table is accessible in desktop and mobile layouts,
that YAML-style chart blocks do not leak raw chart source while streaming, and that
final assistant metadata rendering does not blank hydrated chart canvases. It also
validates the chart-level color editor updates rendered charts without creating a new message
and that exports send the edited chart markdown to the backend.
"""

import os
import time

import pytest


def _get_chat_test_url():
    chat_url = os.getenv('SIMPLECHAT_PLAYWRIGHT_CHAT_URL', '').strip()
    if not chat_url:
        pytest.skip('Set SIMPLECHAT_PLAYWRIGHT_CHAT_URL to run inline chart UI tests.')
    return chat_url


def _create_context(browser, viewport):
    context_kwargs = {'viewport': viewport, 'ignore_https_errors': True}
    storage_state_path = os.getenv('SIMPLECHAT_PLAYWRIGHT_STORAGE_STATE', '').strip()
    if storage_state_path:
        context_kwargs['storage_state'] = storage_state_path
    return browser.new_context(**context_kwargs)


def _get_playwright_helpers():
    playwright_sync_api = pytest.importorskip('playwright.sync_api')
    return playwright_sync_api.expect, playwright_sync_api.sync_playwright


def _append_custom_ai_message(page, message_id, chart_message, full_message_object=None):
    page.evaluate(
        """
        async ({ messageId, content, fullMessageObject }) => {
            const chatMessages = window.chatMessages && typeof window.chatMessages.appendMessage === 'function'
                ? window.chatMessages
                : await import('/static/js/chat/chat-messages.js');
            chatMessages.appendMessage(
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
                fullMessageObject,
                false
            );
        }
        """,
        {'messageId': message_id, 'content': chart_message, 'fullMessageObject': full_message_object},
    )


def _append_inline_chart_message(page, message_id):
    chart_message = (
        'Quarterly revenue is trending above target.\n\n'
        '```simplechart\n'
        '{"version":1,"kind":"line","chartType":"line","chartId":"ui-inline-chart","title":"Quarterly Revenue Trend","subtitle":"Actual versus target","description":"Interactive inline chart regression test.","summary":"Line with 2 series across 4 categories.","options":{"legendPosition":"top","showLegend":true,"showDataTable":true,"beginAtZero":true,"horizontal":false,"fill":false,"smooth":true,"stacked":false,"xAxisLabel":"Quarter","yAxisLabel":"Revenue"},"data":{"labels":["Q1","Q2","Q3","Q4"],"datasets":[{"label":"Revenue","data":[120,142,159,171],"borderColor":"#1c6ea4","backgroundColor":"rgba(28,110,164,0.18)","borderWidth":2,"fill":false,"tension":0.35},{"label":"Target","data":[110,135,150,165],"borderColor":"#d75b35","backgroundColor":"rgba(215,91,53,0.18)","borderWidth":2,"fill":false,"tension":0.35}]},"table":{"columns":["Label","Revenue","Target"],"rows":[["Q1",120,110],["Q2",142,135],["Q3",159,150],["Q4",171,165]]}}\n'
        '```'
    )
    _append_custom_ai_message(page, message_id, chart_message)


def _append_yaml_inline_chart_message(page, message_id):
    chart_message = (
        'Fruit distribution chart.\n\n'
        '```simplechart\n'
        'version: 1\n'
        'kind: chart\n'
        'chartType: pie\n'
        'title: Fruit Distribution\n'
        'data:\n'
        '  labels: [Apples, Oranges, Pears]\n'
        '  datasets:\n'
        '    - label: Share\n'
        '      data: [33, 33, 34]\n'
        'options:\n'
        '  responsive: true\n'
        '  plugins:\n'
        '    legend:\n'
        '      display: true\n'
        '      position: right\n'
        'summary: Apples 33%, Oranges 33%, Pears 34%.\n'
        '```'
    )
    _append_custom_ai_message(page, message_id, chart_message)


def _append_pending_inline_chart_message(page, message_id):
    chart_message = (
        'Fruit distribution chart.\n\n'
        '```simplechart\n'
        'version: 1\n'
        'kind: chart\n'
        'chartType: pie\n'
    )
    _append_custom_ai_message(page, message_id, chart_message)


def _build_streaming_inline_chart_message(suffix=''):
    return (
        'Population growth transformed colonial society.\n\n'
        '```simplechart\n'
        '{"version":1,"kind":"bar","chartType":"bar","chartId":"ui-stream-stable-chart","title":"Approximate Colonial Population Growth","summary":"The chart shows strong population growth in British North America from 1700 to 1750.","options":{"legendPosition":"top","showLegend":false,"showDataTable":false,"beginAtZero":true,"xAxisLabel":"Year","yAxisLabel":"Population"},"data":{"labels":["1700","1725","1750"],"datasets":[{"label":"Population","data":[50000,100000,275000],"borderColor":"#1c6ea4","backgroundColor":"rgba(28,110,164,0.18)"}]}}\n'
        '```'
        f'{suffix}'
    )


def _get_inline_chart_pixel_stats(page, message_id):
    return page.evaluate(
        """
        (messageId) => {
            const message = document.querySelector(`[data-message-id="${messageId}"]`);
            const chart = message?.querySelector('.sc-inline-chart');
            const canvas = chart?.querySelector('canvas');
            const chartInstance = canvas && window.Chart ? window.Chart.getChart(canvas) : null;
            if (!canvas) {
                return { hasCanvas: false };
            }

            const context = canvas.getContext('2d');
            const imageData = context.getImageData(0, 0, canvas.width, canvas.height).data;
            let nonTransparent = 0;
            let nonWhite = 0;
            for (let index = 0; index < imageData.length; index += 16) {
                const alpha = imageData[index + 3];
                if (alpha > 0) {
                    nonTransparent += 1;
                }
                if (alpha > 0 && !(imageData[index] > 245 && imageData[index + 1] > 245 && imageData[index + 2] > 245)) {
                    nonWhite += 1;
                }
            }

            return {
                hasCanvas: true,
                hasChartInstance: Boolean(chartInstance),
                hydrated: chart?.getAttribute('data-chart-hydrated') || '',
                width: canvas.width,
                height: canvas.height,
                nonTransparent,
                nonWhite,
            };
        }
        """,
        message_id,
    )


@pytest.mark.ui
def test_chat_inline_chart_rendering_desktop():
    """Validate desktop inline chart rendering and data-table toggling inside chat."""
    chat_url = _get_chat_test_url()
    expect, sync_playwright = _get_playwright_helpers()

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

        message_count_before = page.locator('[data-message-id]').count()
        color_toggle = page.locator(f'[data-message-id="{message_id}"] .sc-inline-chart-colors-toggle')
        expect(color_toggle).to_be_visible()
        color_toggle.click()
        color_panel = page.locator(f'[data-message-id="{message_id}"] .sc-inline-chart-color-panel')
        expect(color_panel).to_be_visible()
        expect(color_panel.locator('.sc-inline-chart-palette-btn')).to_have_count(5)
        first_color_input = color_panel.locator('.sc-inline-chart-color-input').first
        first_color_input.fill('#9333ea')
        color_state = page.evaluate(
            """
            (messageId) => {
                const message = document.querySelector(`[data-message-id="${messageId}"]`);
                const chart = message?.querySelector('.sc-inline-chart');
                const canvas = chart?.querySelector('canvas');
                const chartInstance = canvas && window.Chart ? window.Chart.getChart(canvas) : null;
                const hiddenMarkdown = message?.querySelector('textarea[id^="copy-md-"]')?.value || '';
                const storedSpec = JSON.parse(decodeURIComponent(chart?.getAttribute('data-chart-spec') || ''));
                return {
                    chartColor: chartInstance?.data?.datasets?.[0]?.borderColor || '',
                    storedColor: storedSpec?.data?.datasets?.[0]?.borderColor || '',
                    markdownHasColor: hiddenMarkdown.includes('#9333ea'),
                };
            }
            """,
            message_id,
        )
        assert color_state['chartColor'] == '#9333ea', color_state
        assert color_state['storedColor'] == '#9333ea', color_state
        assert color_state['markdownHasColor'] is True, color_state
        assert page.locator('[data-message-id]').count() == message_count_before

        export_payload = page.evaluate(
            """
            async (messageId) => {
                const message = document.querySelector(`[data-message-id="${messageId}"]`);
                const exportModule = await import('/static/js/chat/chat-message-export.js');
                const originalFetch = window.fetch;
                const payloads = [];
                window.currentConversationId = 'ui-chart-export-conversation';
                window.fetch = async (url, options = {}) => {
                    if (String(url).includes('/api/message/export-powerpoint')) {
                        payloads.push(JSON.parse(options.body || '{}'));
                        return new Response(new Blob(['pptx'], { type: 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }), {
                            status: 200,
                            headers: { 'Content-Type': 'application/vnd.openxmlformats-officedocument.presentationml.presentation' }
                        });
                    }
                    return originalFetch(url, options);
                };

                try {
                    await exportModule.exportMessageAsPowerPoint(message, messageId, 'assistant');
                } finally {
                    window.fetch = originalFetch;
                }
                return payloads[0] || null;
            }
            """,
            message_id,
        )
        assert export_payload is not None
        assert export_payload['message_id'] == message_id
        assert export_payload['conversation_id'] == 'ui-chart-export-conversation'
        assert '#9333ea' in export_payload['message_content_override']

        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_inline_chart_rendering_mobile():
    """Validate that inline charts still render in a mobile viewport."""
    chat_url = _get_chat_test_url()
    expect, sync_playwright = _get_playwright_helpers()

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


@pytest.mark.ui
def test_chat_inline_chart_yaml_and_pending_source_rendering():
    """Validate YAML-style chart blocks render and pending chart source stays hidden."""
    chat_url = _get_chat_test_url()
    expect, sync_playwright = _get_playwright_helpers()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = _create_context(browser, {'width': 1280, 'height': 820})
        page = context.new_page()
        page.goto(chat_url, wait_until='domcontentloaded')

        if 'login' in page.url.lower():
            pytest.skip('Inline chart UI test requires an authenticated chat session.')

        yaml_message_id = f'inline-chart-yaml-{int(time.time())}'
        _append_yaml_inline_chart_message(page, yaml_message_id)

        yaml_message = page.locator(f'[data-message-id="{yaml_message_id}"] .message-text')
        expect(yaml_message.locator('.sc-inline-chart canvas')).to_be_visible()
        expect(yaml_message.get_by_text('version: 1')).not_to_be_visible()

        pending_message_id = f'inline-chart-pending-{int(time.time())}'
        _append_pending_inline_chart_message(page, pending_message_id)

        pending_message = page.locator(f'[data-message-id="{pending_message_id}"] .message-text')
        expect(pending_message.locator('.sc-inline-chart')).to_be_visible()
        expect(pending_message.get_by_text('Preparing chart...')).to_be_visible()
        expect(pending_message.get_by_text('version: 1')).not_to_be_visible()

        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_inline_chart_final_metadata_keeps_canvas_rendered():
    """Validate final assistant metadata rendering keeps Chart.js canvases hydrated."""
    chat_url = _get_chat_test_url()
    expect, sync_playwright = _get_playwright_helpers()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = _create_context(browser, {'width': 1280, 'height': 820})
        page = context.new_page()
        page.goto(chat_url, wait_until='domcontentloaded')

        if 'login' in page.url.lower():
            pytest.skip('Inline chart UI test requires an authenticated chat session.')

        message_id = f'inline-chart-final-metadata-{int(time.time())}'
        chart_message = (
            'Fruit distribution chart.\n\n'
            '```simplechart\n'
            '{"version":1,"kind":"pie","chartType":"pie","chartId":"ui-final-chart","title":"Fruit Share","description":"Final metadata chart regression test.","summary":"Pie with 3 segments.","options":{"legendPosition":"top","showLegend":true,"showDataTable":true},"data":{"labels":["Apples","Oranges","Pears"],"datasets":[{"label":"Fruit Share","data":[33,33,34]}]},"table":{"columns":["Label","Fruit Share"],"rows":[["Apples",33],["Oranges",33],["Pears",34]]}}\n'
            '```'
        )
        _append_custom_ai_message(
            page,
            message_id,
            chart_message,
            {
                'id': message_id,
                'role': 'assistant',
                'content': chart_message,
                'metadata': {'reasoning_effort': None},
            },
        )

        chart_canvas = page.locator(f'[data-message-id="{message_id}"] .sc-inline-chart canvas')
        expect(chart_canvas).to_be_visible()
        expect(page.locator(f'[data-message-id="{message_id}"] .message-text')).not_to_contain_text('```simplechart')

        pixel_stats = _get_inline_chart_pixel_stats(page, message_id)
        assert pixel_stats['hasCanvas'] is True, pixel_stats
        assert pixel_stats['hasChartInstance'] is True, pixel_stats
        assert pixel_stats['hydrated'] == 'true', pixel_stats
        assert pixel_stats['nonTransparent'] > 0, pixel_stats
        assert pixel_stats['nonWhite'] > 0, pixel_stats

        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_inline_chart_streaming_updates_keep_canvas_stable():
    """Validate streaming updates preserve an already rendered inline chart canvas."""
    chat_url = _get_chat_test_url()
    expect, sync_playwright = _get_playwright_helpers()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = _create_context(browser, {'width': 1280, 'height': 820})
        page = context.new_page()
        page.goto(chat_url, wait_until='domcontentloaded')

        if 'login' in page.url.lower():
            pytest.skip('Inline chart UI test requires an authenticated chat session.')

        message_id = f'inline-chart-stream-stability-{int(time.time())}'
        first_content = _build_streaming_inline_chart_message()
        second_content = _build_streaming_inline_chart_message(
            '\n\nAdditional streamed narration after the chart should not recreate the canvas.'
        )

        stability = page.evaluate(
            """
            async ({ messageId, firstContent, secondContent }) => {
                const chatMessages = window.chatMessages && typeof window.chatMessages.appendMessage === 'function'
                    ? window.chatMessages
                    : await import('/static/js/chat/chat-messages.js');
                const streamingModule = await import('/static/js/chat/chat-streaming.js');
                chatMessages.appendMessage(
                    'AI',
                    'Preparing chart...',
                    'chart-inline-test',
                    messageId,
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    { id: messageId, role: 'assistant', content: '', conversation_id: 'ui-chart-stream-stability' },
                    false
                );

                streamingModule.updateStreamingMessage(messageId, firstContent);
                await new Promise(resolve => requestAnimationFrame(resolve));
                const messageElement = document.querySelector(`[data-message-id="${messageId}"]`);
                const firstCanvas = messageElement?.querySelector('.sc-inline-chart canvas');
                const firstChart = firstCanvas && window.Chart ? window.Chart.getChart(firstCanvas) : null;
                if (firstCanvas) {
                    firstCanvas.dataset.stabilityMarker = 'preserved';
                }

                streamingModule.updateStreamingMessage(messageId, secondContent);
                await new Promise(resolve => requestAnimationFrame(resolve));
                const secondCanvas = messageElement?.querySelector('.sc-inline-chart canvas');
                const secondChart = secondCanvas && window.Chart ? window.Chart.getChart(secondCanvas) : null;

                return {
                    hasCanvas: Boolean(secondCanvas),
                    sameCanvas: firstCanvas === secondCanvas,
                    sameChart: firstChart === secondChart,
                    marker: secondCanvas?.dataset?.stabilityMarker || '',
                    hydrated: secondCanvas?.closest('.sc-inline-chart')?.getAttribute('data-chart-hydrated') || '',
                    rawSourceVisible: messageElement?.innerText?.includes('```simplechart') || false,
                };
            }
            """,
            {
                'messageId': message_id,
                'firstContent': first_content,
                'secondContent': second_content,
            },
        )

        assert stability['hasCanvas'] is True, stability
        assert stability['sameCanvas'] is True, stability
        assert stability['sameChart'] is True, stability
        assert stability['marker'] == 'preserved', stability
        assert stability['hydrated'] == 'true', stability
        assert stability['rawSourceVisible'] is False, stability

        context.close()
        browser.close()