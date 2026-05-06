# test_chat_tabular_thought_progress.py
"""
UI test for tabular streaming thought progress.
Version: 0.241.114
Implemented in: 0.241.114

This test ensures live tabular thought updates render a workbook-focused
progress card while tool activity is running and move to completion once
the tabular tool pass finishes.
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from threading import Thread

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = 'ui_tests/fixtures/chat_thought_progress_harness.html'


def _get_free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@contextmanager
def _start_static_test_server():
    port = _get_free_local_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.ui
def test_chat_tabular_thought_progress(playwright):
    """Validate that tabular thought updates render a live workbook progress card."""
    browser = playwright.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        with _start_static_test_server() as server_base_url:
            response = page.goto(f'{server_base_url}/{HARNESS_PATH}', wait_until='domcontentloaded')
            assert response is not None and response.ok

            snapshots = page.evaluate(
                """
                async () => {
                    const thoughtsModule = await import('/application/single_app/static/js/chat/chat-thoughts.js');
                    const {
                        beginStreamingThoughtSession,
                        handleStreamingThought,
                    } = thoughtsModule;

                    const wrapper = document.createElement('div');
                    wrapper.setAttribute('data-message-id', 'temp-tabular-progress');
                    wrapper.innerHTML = '<div class="message-text">Streaming...</div>';
                    document.getElementById('test-root').appendChild(wrapper);

                    const readSnapshot = () => {
                        const card = wrapper.querySelector('.agent-progress-card');
                        const progressBar = card?.querySelector('.progress-bar');
                        const heading = card?.querySelector('.fw-semibold');
                        const icon = card?.querySelector('.bi');

                        return {
                            exists: Boolean(card),
                            state: card?.getAttribute('data-agent-progress-state') || '',
                            percent: card?.getAttribute('data-agent-progress-percent') || '',
                            heading: heading?.textContent || '',
                            iconClass: icon?.className || '',
                            textContent: card?.textContent || '',
                            width: progressBar?.style.width || '',
                        };
                    };

                    beginStreamingThoughtSession('temp-tabular-progress');
                    handleStreamingThought({
                        message_id: 'assistant-tabular-progress',
                        step_index: 0,
                        step_type: 'tabular_analysis',
                        content: 'Starting tabular analysis across 1 file(s)',
                    }, 'temp-tabular-progress');
                    handleStreamingThought({
                        message_id: 'assistant-tabular-progress',
                        step_index: 1,
                        step_type: 'tabular_analysis',
                        content: 'Starting tabular tool search_rows on irs_treasury_multi_tab_workbook.xlsx',
                        activity: {
                            activity_key: 'tabular.search_rows#1',
                            kind: 'tabular_tool_invocation',
                            title: 'search_rows',
                            status: 'running',
                            state: 'running',
                            lane_key: 'tabular',
                            lane_label: 'Tabular',
                            plugin_name: 'TabularProcessingPlugin',
                            function_name: 'search_rows',
                        },
                    }, 'temp-tabular-progress');
                    const running = readSnapshot();

                    handleStreamingThought({
                        message_id: 'assistant-tabular-progress',
                        step_index: 2,
                        step_type: 'tabular_analysis',
                        content: 'Tabular tool search_rows on irs_treasury_multi_tab_workbook.xlsx (702ms)',
                        activity: {
                            activity_key: 'tabular.search_rows#1',
                            kind: 'tabular_tool_invocation',
                            title: 'search_rows',
                            status: 'completed',
                            state: 'completed',
                            lane_key: 'tabular',
                            lane_label: 'Tabular',
                            plugin_name: 'TabularProcessingPlugin',
                            function_name: 'search_rows',
                        },
                    }, 'temp-tabular-progress');
                    const completed = readSnapshot();

                    return { running, completed };
                }
                """
            )

        assert snapshots['running']['exists'] is True
        assert snapshots['running']['state'] == 'running'
        assert snapshots['running']['percent'] == '45'
        assert snapshots['running']['width'] == '45%'
        assert snapshots['running']['heading'] == 'Tabular analysis'
        assert 'bi-table' in snapshots['running']['iconClass']
        assert 'Current tabular step: search_rows' in snapshots['running']['textContent']
        assert '0/1 tool call' in snapshots['running']['textContent']
        assert '1 running' in snapshots['running']['textContent']

        assert snapshots['completed']['exists'] is True
        assert snapshots['completed']['state'] == 'completed'
        assert snapshots['completed']['percent'] == '100'
        assert snapshots['completed']['width'] == '100%'
        assert snapshots['completed']['heading'] == 'Tabular analysis'
        assert '1/1 tool call' in snapshots['completed']['textContent']
        assert 'Workbook evidence ready' in snapshots['completed']['textContent']
    finally:
        context.close()
        browser.close()