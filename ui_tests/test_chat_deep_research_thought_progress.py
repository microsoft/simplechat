# test_chat_deep_research_thought_progress.py
"""
UI test for Deep Research streaming thought progress.
Version: 0.241.096
Implemented in: 0.241.096

This test ensures Deep Research thought updates render a staged progress card
with visible source-review work instead of the generic pulsing thought badge.
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
from pathlib import Path
import socket
from threading import Thread

import pytest


try:
    HAS_PYTEST_PLAYWRIGHT = importlib.util.find_spec('pytest_playwright.pytest_playwright') is not None
except ModuleNotFoundError:
    HAS_PYTEST_PLAYWRIGHT = False


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


if not HAS_PYTEST_PLAYWRIGHT:
    @pytest.mark.ui
    def test_chat_deep_research_thought_progress():
        pytest.skip('pytest-playwright is required for chat thought progress UI harness tests')
else:
    @pytest.mark.ui
    def test_chat_deep_research_thought_progress(playwright):
        """Validate that Deep Research thought updates render a live progress card."""
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
                        wrapper.setAttribute('data-message-id', 'temp-deep-research-progress');
                        wrapper.innerHTML = '<div class="message-text">Streaming...</div>';
                        document.getElementById('test-root').appendChild(wrapper);

                        const readSnapshot = () => {
                            const card = wrapper.querySelector('.source-review-progress-card');
                            const progressBar = card?.querySelector('.progress-bar');
                            const genericPulse = wrapper.querySelector('.animate-pulse');

                            return {
                                exists: Boolean(card),
                                mode: card?.getAttribute('data-source-review-progress-mode') || '',
                                state: card?.getAttribute('data-source-review-progress-state') || '',
                                percent: card?.getAttribute('data-source-review-progress-percent') || '',
                                textContent: card?.textContent || '',
                                width: progressBar?.style.width || '',
                                hasGenericPulse: Boolean(genericPulse),
                            };
                        };

                        beginStreamingThoughtSession('temp-deep-research-progress');
                        handleStreamingThought({
                            message_id: 'assistant-deep-research-progress',
                            step_index: 0,
                            step_type: 'deep_research',
                            content: 'Planning Deep Research web searches',
                        }, 'temp-deep-research-progress');
                        const planning = readSnapshot();

                        handleStreamingThought({
                            message_id: 'assistant-deep-research-progress',
                            step_index: 1,
                            step_type: 'deep_research',
                            content: 'Ran 3 Deep Research web search queries',
                            detail: 'discovered_urls=9',
                        }, 'temp-deep-research-progress');
                        const searched = readSnapshot();

                        handleStreamingThought({
                            message_id: 'assistant-deep-research-progress',
                            step_index: 2,
                            step_type: 'deep_research',
                            content: 'Reviewing source pages for supporting evidence',
                        }, 'temp-deep-research-progress');
                        const reviewing = readSnapshot();

                        handleStreamingThought({
                            message_id: 'assistant-deep-research-progress',
                            step_index: 3,
                            step_type: 'deep_research',
                            content: 'Reviewed 5 URL source pages',
                            detail: 'seed=3, child=2, planner=used, load_more=1, skipped=4',
                        }, 'temp-deep-research-progress');
                        const evidence = readSnapshot();

                        handleStreamingThought({
                            message_id: 'assistant-deep-research-progress',
                            step_index: 4,
                            step_type: 'generation',
                            content: "'gpt-4o' responded (11.4s from initial message)",
                        }, 'temp-deep-research-progress');
                        const completed = readSnapshot();

                        return { planning, searched, reviewing, evidence, completed };
                    }
                    """
                )

            assert snapshots['planning']['exists'] is True
            assert snapshots['planning']['mode'] == 'deep_research'
            assert snapshots['planning']['state'] == 'running'
            assert snapshots['planning']['percent'] == '18'
            assert snapshots['planning']['width'] == '18%'
            assert snapshots['planning']['hasGenericPulse'] is False
            assert 'Deep Research' in snapshots['planning']['textContent']
            assert 'Plan search queries' in snapshots['planning']['textContent']
            assert 'Run web searches' in snapshots['planning']['textContent']
            assert 'Review source pages' in snapshots['planning']['textContent']
            assert 'Assemble evidence' in snapshots['planning']['textContent']

            assert snapshots['searched']['percent'] == '42'
            assert snapshots['searched']['width'] == '42%'
            assert '3 search queries' in snapshots['searched']['textContent']
            assert '9 URLs found' in snapshots['searched']['textContent']

            assert snapshots['reviewing']['percent'] == '68'
            assert snapshots['reviewing']['width'] == '68%'
            assert 'Reviewing source pages for supporting evidence' in snapshots['reviewing']['textContent']

            assert snapshots['evidence']['percent'] == '86'
            assert snapshots['evidence']['width'] == '86%'
            assert '5 reviewed' in snapshots['evidence']['textContent']
            assert '4 skipped' in snapshots['evidence']['textContent']
            assert '1 load-more click' in snapshots['evidence']['textContent']
            assert 'Planner: used' in snapshots['evidence']['textContent']

            assert snapshots['completed']['state'] == 'completed'
            assert snapshots['completed']['percent'] == '100'
            assert snapshots['completed']['width'] == '100%'
            assert 'Ready' in snapshots['completed']['textContent']
            assert 'Prepare response' in snapshots['completed']['textContent']
        finally:
            context.close()
            browser.close()