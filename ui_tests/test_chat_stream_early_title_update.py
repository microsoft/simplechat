# test_chat_stream_early_title_update.py
"""
UI test for early chat stream title updates.
Version: 0.241.042
Implemented in: 0.241.042

This test ensures early conversation metadata stream events update the active
conversation title in the chat UI while untrusted title text remains inert.
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from threading import Thread

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = "ui_tests/fixtures/chat_thought_progress_harness.html"


def _get_free_local_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _start_static_test_server():
    port = _get_free_local_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(REPO_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.ui
def test_chat_stream_metadata_updates_active_conversation_title_safely(playwright):
    """Validate early stream metadata updates the title without rendering HTML."""
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        with _start_static_test_server() as server_base_url:
            response = page.goto(f"{server_base_url}/{HARNESS_PATH}", wait_until="domcontentloaded")
            assert response is not None and response.ok

            result = page.evaluate(
                """
                async () => {
                    window.__xssFired = false;
                    window.currentConversationId = 'early-title-conversation';
                    window.enable_document_classification = false;

                    const root = document.getElementById('test-root');
                    root.innerHTML = `
                        <h1 id="current-conversation-title">New Conversation</h1>
                        <div id="current-conversation-classifications"></div>
                        <div id="conversations-list">
                            <div class="list-group-item conversation-item active" data-conversation-id="early-title-conversation" data-conversation-title="New Conversation" data-chat-type="new">
                                <span class="conversation-title-row">
                                    <span class="conversation-title">New Conversation</span>
                                </span>
                            </div>
                        </div>
                        <div id="chatbox"></div>
                    `;

                    const streamingModule = await import('/application/single_app/static/js/chat/chat-streaming.js');
                    streamingModule.applyStreamingConversationMetadata({
                        type: 'conversation_metadata',
                        conversation_id: 'early-title-conversation',
                        conversation_title: '<img src=x onerror="window.__xssFired = true"> Analyze 34 windows',
                    });

                    const listTitle = document.querySelector('.conversation-title');
                    const activeItem = document.querySelector('.conversation-item');
                    const headerTitle = document.getElementById('current-conversation-title');

                    return {
                        listTitleText: listTitle.textContent.trim(),
                        listTitleHtml: listTitle.innerHTML,
                        itemTitle: activeItem.getAttribute('data-conversation-title'),
                        headerTitleText: headerTitle.textContent.trim(),
                        renderedImages: document.querySelectorAll('img').length,
                        xssFired: window.__xssFired,
                    };
                }
                """
            )

        expected_title = '<img src=x onerror="window.__xssFired = true"> Analyze 34 windows'
        assert result["listTitleText"] == expected_title
        assert result["itemTitle"] == expected_title
        assert result["headerTitleText"] == expected_title
        assert "&lt;img" in result["listTitleHtml"]
        assert result["renderedImages"] == 0
        assert result["xssFired"] is False
    finally:
        context.close()
        browser.close()