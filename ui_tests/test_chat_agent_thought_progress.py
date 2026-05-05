# test_chat_agent_thought_progress.py
"""
UI test for agent streaming thought progress.
Version: 0.241.073
Implemented in: 0.241.073

This test ensures live agent thought updates render a progress card while
tool activity is running and finish at 100% when the agent response is ready.
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
def test_chat_agent_thought_progress(playwright):
    """Validate that agent thought updates render a live progress card."""
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
                    wrapper.setAttribute('data-message-id', 'temp-agent-progress');
                    wrapper.innerHTML = '<div class="message-text">Streaming...</div>';
                    document.getElementById('test-root').appendChild(wrapper);

                    const readSnapshot = () => {
                        const card = wrapper.querySelector('.agent-progress-card');
                        const progressBar = card?.querySelector('.progress-bar');

                        return {
                            exists: Boolean(card),
                            state: card?.getAttribute('data-agent-progress-state') || '',
                            percent: card?.getAttribute('data-agent-progress-percent') || '',
                            textContent: card?.textContent || '',
                            width: progressBar?.style.width || '',
                        };
                    };

                    beginStreamingThoughtSession('temp-agent-progress');
                    handleStreamingThought({
                        message_id: 'assistant-agent-progress',
                        step_index: 0,
                        step_type: 'agent_tool_call',
                        content: "Sending to agent 'Research Agent'",
                    }, 'temp-agent-progress');
                    handleStreamingThought({
                        message_id: 'assistant-agent-progress',
                        step_index: 1,
                        step_type: 'generation',
                        content: "Sending to 'gpt-4o'",
                    }, 'temp-agent-progress');
                    handleStreamingThought({
                        message_id: 'assistant-agent-progress',
                        step_index: 2,
                        step_type: 'agent_tool_call',
                        content: 'Invoking DocumentSearch.search',
                        activity: {
                            activity_key: 'DocumentSearch.search#1',
                            kind: 'tool_invocation',
                            title: 'DocumentSearch.search',
                            status: 'running',
                            state: 'running',
                            lane_key: 'DocumentSearch',
                            lane_label: 'DocumentSearch',
                            plugin_name: 'DocumentSearch',
                            function_name: 'search',
                        },
                    }, 'temp-agent-progress');
                    const running = readSnapshot();

                    handleStreamingThought({
                        message_id: 'assistant-agent-progress',
                        step_index: 3,
                        step_type: 'agent_tool_call',
                        content: 'Agent executed DocumentSearch.search (187ms)',
                        activity: {
                            activity_key: 'DocumentSearch.search#1',
                            kind: 'tool_invocation',
                            title: 'DocumentSearch.search',
                            status: 'completed',
                            state: 'completed',
                            lane_key: 'DocumentSearch',
                            lane_label: 'DocumentSearch',
                            plugin_name: 'DocumentSearch',
                            function_name: 'search',
                        },
                    }, 'temp-agent-progress');
                    handleStreamingThought({
                        message_id: 'assistant-agent-progress',
                        step_index: 4,
                        step_type: 'generation',
                        content: "'gpt-4o' responded (4.2s from initial message)",
                    }, 'temp-agent-progress');
                    const completed = readSnapshot();

                    return { running, completed };
                }
                """
            )

        assert snapshots['running']['exists'] is True
        assert snapshots['running']['state'] == 'running'
        assert snapshots['running']['percent'] == '45'
        assert snapshots['running']['width'] == '45%'
        assert 'Current tool: DocumentSearch.search' in snapshots['running']['textContent']
        assert '0/1 tool' in snapshots['running']['textContent']
        assert '1 running' in snapshots['running']['textContent']

        assert snapshots['completed']['exists'] is True
        assert snapshots['completed']['state'] == 'completed'
        assert snapshots['completed']['percent'] == '100'
        assert snapshots['completed']['width'] == '100%'
        assert '1/1 tool' in snapshots['completed']['textContent']
        assert 'Response ready' in snapshots['completed']['textContent']
    finally:
        context.close()
        browser.close()
