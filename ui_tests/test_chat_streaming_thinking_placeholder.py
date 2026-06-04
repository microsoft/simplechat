# test_chat_streaming_thinking_placeholder.py
"""
UI test for chat streaming thinking placeholder.
Version: 0.241.125
Implemented in: 0.241.125

This test ensures the assistant's initial streaming placeholder uses a
thought-style rotating status chip before live processing thoughts arrive,
then yields to the first thought update without showing the old dots and
Streaming text.
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
def test_chat_streaming_thinking_placeholder_replaced_by_thought():
    """Validate the initial assistant streaming state before thought updates arrive."""
    playwright_sync_api = pytest.importorskip('playwright.sync_api')

    with playwright_sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        page = context.new_page()

        try:
            with _start_static_test_server() as server_base_url:
                response = page.goto(f'{server_base_url}/{HARNESS_PATH}', wait_until='domcontentloaded')
                assert response is not None and response.ok

                snapshots = page.evaluate(
                    r"""
                    async () => {
                        window.appSettings = {
                            enable_thoughts: true,
                            enable_text_to_speech: false,
                            documentActionCapabilities: {},
                        };
                        window.enable_document_classification = false;
                        window.currentConversationId = 'ui-thinking-conversation';
                        window.marked = { parse: value => String(value || '') };
                        window.DOMPurify = { sanitize: value => String(value || '') };
                        window.scrollChatToBottom = () => {};

                        const root = document.getElementById('test-root');
                        root.innerHTML = `
                            <div id="chatbox"></div>
                            <textarea id="user-input"></textarea>
                            <button id="send-btn" type="button"></button>
                            <select id="prompt-select"></select>
                            <div id="prompt-selection-container"></div>
                            <select id="model-select"><option value="gpt-4o">gpt-4o</option></select>
                        `;

                        const encoder = new TextEncoder();
                        let streamController = null;

                        window.fetch = (url, options = {}) => {
                            const requestUrl = String(url);

                            if (requestUrl === '/api/chat/stream') {
                                const body = new ReadableStream({
                                    start(controller) {
                                        streamController = controller;
                                    },
                                });
                                return Promise.resolve(new Response(body, {
                                    status: 200,
                                    headers: { 'Content-Type': 'text/event-stream' },
                                }));
                            }

                            return Promise.resolve(new Response(JSON.stringify({ success: true }), {
                                status: 200,
                                headers: { 'Content-Type': 'application/json' },
                            }));
                        };

                        const streamingModule = await import('/application/single_app/static/js/chat/chat-streaming.js');
                        streamingModule.sendMessageWithStreaming(
                            { message: 'Show the first loading state', conversation_id: 'ui-thinking-conversation' },
                            'temp-user-thinking',
                            'ui-thinking-conversation',
                            { allowRecovery: false },
                        );

                        await new Promise(resolve => setTimeout(resolve, 75));
                        const messageElement = document.querySelector('[data-message-id^="temp_ai_"]');
                        const placeholder = messageElement?.querySelector('.streaming-thinking-placeholder');
                        const icon = placeholder?.querySelector('.streaming-thinking-icon i');

                        const initial = {
                            exists: Boolean(placeholder),
                            role: placeholder?.getAttribute('role') || '',
                            ariaLive: placeholder?.getAttribute('aria-live') || '',
                            ariaLabel: placeholder?.getAttribute('aria-label') || '',
                            textContent: messageElement?.textContent || '',
                            iconClass: icon?.className || '',
                            iconAnimationName: icon ? getComputedStyle(icon).animationName : '',
                            hasVerticalDotsIcon: Boolean(messageElement?.querySelector('.bi-three-dots-vertical')),
                        };

                        streamController.enqueue(encoder.encode('data: {"type":"thought","message_id":"assistant-thinking","step_index":0,"step_type":"search","content":"Searching assigned knowledge"}\n\n'));
                        await new Promise(resolve => setTimeout(resolve, 75));

                        const afterThought = {
                            hasThinkingPlaceholder: Boolean(messageElement?.querySelector('.streaming-thinking-placeholder')),
                            hasThoughtDisplay: Boolean(messageElement?.querySelector('.streaming-thought-display .badge')),
                            iconClass: messageElement?.querySelector('.streaming-thought-display .badge i')?.className || '',
                            textContent: messageElement?.textContent || '',
                        };

                        return { initial, afterThought };
                    }
                    """
                )

            assert snapshots['initial']['exists'] is True
            assert snapshots['initial']['role'] == 'status'
            assert snapshots['initial']['ariaLive'] == 'polite'
            assert snapshots['initial']['ariaLabel'] == 'Thinking while the response starts'
            assert snapshots['initial']['textContent'].strip().startswith('AI')
            assert 'Thinking' in snapshots['initial']['textContent']
            assert 'Streaming' not in snapshots['initial']['textContent']
            assert snapshots['initial']['hasVerticalDotsIcon'] is False
            assert 'bi-stars' in snapshots['initial']['iconClass']
            assert snapshots['initial']['iconAnimationName'] == 'streaming-thinking-spin'

            assert snapshots['afterThought']['hasThinkingPlaceholder'] is False
            assert snapshots['afterThought']['hasThoughtDisplay'] is True
            assert 'bi-search' in snapshots['afterThought']['iconClass']
            assert 'Searching assigned knowledge' in snapshots['afterThought']['textContent']
        finally:
            context.close()
            browser.close()