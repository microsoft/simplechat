# test_chat_document_progress_details_toggle.py
"""
UI test for chat document progress detail toggles.
Version: 0.241.037
Implemented in: 0.241.037

This test ensures document-analysis progress cards keep the overall progress
visible while document-level sub actions are collapsed by default, can be
expanded on demand, and preserve that expanded state across streaming updates.
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
def test_chat_document_progress_details_toggle(playwright):
    """Validate that document-level progress details collapse and re-expand cleanly."""
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
                    wrapper.setAttribute('data-message-id', 'temp-document-progress-details');
                    wrapper.innerHTML = '<div class="message-text">Streaming...</div>';
                    document.getElementById('test-root').appendChild(wrapper);

                    const buildThought = (percent, windowNumber) => ({
                        message_id: 'assistant-document-progress-details',
                        step_index: windowNumber,
                        step_type: 'document_analysis',
                        content: `Analyzing window ${windowNumber} of 5`,
                        progress: {
                            overall: {
                                percent,
                                status: 'running',
                                phase: 'analyzing',
                                phase_label: `Analyzing document windows`,
                                phase_detail: `Analyzing window ${windowNumber} of 5`,
                                completed_chunks: 54,
                                total_chunks: 271,
                                completed_windows: windowNumber - 1,
                                total_windows: 19,
                                completed_documents: 1,
                                document_count: 3,
                                failed_windows: 0,
                            },
                            documents: [
                                {
                                    document_id: 'doc-1',
                                    document_name: 'River Race Maps 2025.pdf',
                                    percent: 100,
                                    status: 'completed',
                                    status_text: 'Completed',
                                    completed_chunks: 42,
                                    total_chunks: 42,
                                    completed_windows: 5,
                                    total_windows: 5,
                                    failed_windows: 0,
                                },
                                {
                                    document_id: 'doc-2',
                                    document_name: 'books.csv',
                                    percent: 100,
                                    status: 'completed',
                                    status_text: 'Completed',
                                    completed_chunks: 1,
                                    total_chunks: 1,
                                    completed_windows: 1,
                                    total_windows: 1,
                                    failed_windows: 0,
                                },
                                {
                                    document_id: 'doc-3',
                                    document_name: '20120004266.pdf',
                                    percent,
                                    status: 'running',
                                    status_text: `Analyzing window ${windowNumber} of 5`,
                                    completed_chunks: 11,
                                    total_chunks: 228,
                                    completed_windows: windowNumber - 1,
                                    total_windows: 13,
                                    failed_windows: 0,
                                },
                            ],
                        },
                    });

                    const readSnapshot = () => {
                        const card = wrapper.querySelector('.document-analysis-progress-card');
                        const toggle = card?.querySelector('.action-progress-details-toggle');
                        const details = card?.querySelector('.document-analysis-progress-details');
                        const visibleProgressCount = Array.from(card?.querySelectorAll('.progress') || [])
                            .filter(progressElement => !progressElement.closest('.d-none'))
                            .length;

                        return {
                            exists: Boolean(card),
                            detailsHidden: details?.classList.contains('d-none') ?? null,
                            ariaExpanded: toggle?.getAttribute('aria-expanded') || '',
                            title: toggle?.getAttribute('title') || '',
                            iconClass: toggle?.querySelector('i')?.className || '',
                            visibleProgressCount,
                            textContent: card?.textContent || '',
                            detailsText: details?.textContent || '',
                        };
                    };

                    beginStreamingThoughtSession('temp-document-progress-details');
                    handleStreamingThought(buildThought(46, 3), 'temp-document-progress-details');
                    const collapsed = readSnapshot();

                    wrapper.querySelector('.action-progress-details-toggle').click();
                    const expanded = readSnapshot();

                    handleStreamingThought(buildThought(64, 4), 'temp-document-progress-details');
                    const afterUpdate = readSnapshot();

                    return { collapsed, expanded, afterUpdate };
                }
                """
            )

        assert snapshots['collapsed']['exists'] is True
        assert snapshots['collapsed']['detailsHidden'] is True
        assert snapshots['collapsed']['ariaExpanded'] == 'false'
        assert snapshots['collapsed']['title'] == 'Show document details'
        assert 'bi-chevron-down' in snapshots['collapsed']['iconClass']
        assert snapshots['collapsed']['visibleProgressCount'] == 1
        assert 'River Race Maps 2025.pdf' in snapshots['collapsed']['detailsText']

        assert snapshots['expanded']['detailsHidden'] is False
        assert snapshots['expanded']['ariaExpanded'] == 'true'
        assert snapshots['expanded']['title'] == 'Hide document details'
        assert 'bi-chevron-up' in snapshots['expanded']['iconClass']
        assert snapshots['expanded']['visibleProgressCount'] == 4
        assert 'River Race Maps 2025.pdf' in snapshots['expanded']['textContent']
        assert 'books.csv' in snapshots['expanded']['textContent']

        assert snapshots['afterUpdate']['detailsHidden'] is False
        assert snapshots['afterUpdate']['ariaExpanded'] == 'true'
        assert snapshots['afterUpdate']['visibleProgressCount'] == 4
        assert 'Analyzing window 4 of 5' in snapshots['afterUpdate']['textContent']
    finally:
        context.close()
        browser.close()