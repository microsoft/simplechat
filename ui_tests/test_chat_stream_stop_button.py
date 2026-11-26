# test_chat_stream_stop_button.py
"""
UI test for chat stream stop button.
Version: 0.261.430
Implemented in: 0.241.105
Fixture compatibility updated in: 0.261.429

This test ensures the message-local Stop button posts to the cancellation
endpoint, uses the muted stop styling with enough live-message space, and
renders the server's cancelled terminal stream event as a stopped partial
response.
"""

from contextlib import contextmanager
from copy import deepcopy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from threading import Thread

import pytest
from playwright.sync_api import expect
from ui_tests.fixtures.chat_stop_runtime import stop_modules, stop_world  # noqa: F401


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
def test_chat_stream_stop_button_posts_cancel_and_renders_stopped_state(page):
    """Validate Stop button cancellation and stopped-message rendering."""
    page.set_viewport_size({"width": 1440, "height": 900})
    with _start_static_test_server() as server_base_url:
        response = page.goto(f"{server_base_url}/{HARNESS_PATH}", wait_until="domcontentloaded")
        assert response is not None and response.ok

        result = page.evaluate(
            r"""
                    async () => {
                    window.appSettings = {
                        enable_thoughts: false,
                        enable_text_to_speech: false,
                        documentActionCapabilities: {},
                    };
                    window.enable_document_classification = false;
                    window.currentConversationId = 'ui-stop-conversation';
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
                    const calls = [];

                    window.fetch = (url, options = {}) => {
                        const requestUrl = String(url);
                        calls.push({ url: requestUrl, method: options.method || 'GET', body: options.body || null });

                        if (requestUrl === '/api/chat/stream') {
                            const body = new ReadableStream({
                                start(controller) {
                                    streamController = controller;
                                    controller.enqueue(encoder.encode('data: {"type":"conversation_metadata","conversation_id":"ui-stop-conversation"}\n\n'));
                                    controller.enqueue(encoder.encode('data: {"content":"Partial answer"}\n\n'));
                                },
                            });
                            return Promise.resolve(new Response(body, {
                                status: 200,
                                headers: { 'Content-Type': 'text/event-stream' },
                            }));
                        }

                        if (requestUrl === '/api/chat/stream/cancel/ui-stop-conversation') {
                            if (streamController) {
                                streamController.enqueue(encoder.encode('data: {"type":"cancelled","done":true,"cancelled":true,"cancel_reason":"user_requested","conversation_id":"ui-stop-conversation","user_message_id":"user-final","partial_content":"Partial answer","full_content":"Partial answer","message_persisted":false}\n\n'));
                                streamController.close();
                            }
                            return Promise.resolve(new Response(JSON.stringify({ success: true, outcome: 'accepted' }), {
                                status: 200,
                                headers: { 'Content-Type': 'application/json' },
                            }));
                        }

                        return Promise.resolve(new Response(JSON.stringify({ success: true }), {
                            status: 200,
                            headers: { 'Content-Type': 'application/json' },
                        }));
                    };

                    const streamingModule = await import('/application/single_app/static/js/chat/chat-streaming.js');
                    streamingModule.sendMessageWithStreaming(
                        { message: 'Please stream slowly', conversation_id: 'ui-stop-conversation' },
                        'temp-user-stop',
                        'ui-stop-conversation',
                    );

                    await new Promise(resolve => setTimeout(resolve, 100));
                    const stopButton = document.querySelector('.stream-stop-btn');
                    const beforeClick = {
                        exists: Boolean(stopButton),
                        text: stopButton?.textContent.trim() || '',
                        ariaLabel: stopButton?.getAttribute('aria-label') || '',
                        title: stopButton?.getAttribute('title') || '',
                        className: stopButton?.className || '',
                        width: stopButton?.style.width || '',
                        height: stopButton?.style.height || '',
                        disabled: Boolean(stopButton?.disabled),
                        backgroundColor: stopButton ? getComputedStyle(stopButton).backgroundColor : '',
                        messageHasStreamingClass: Boolean(stopButton?.closest('.message')?.classList.contains('streaming-message')),
                        bubbleMinWidth: stopButton ? getComputedStyle(stopButton.closest('.message')?.querySelector('.message-bubble')).minWidth : '',
                        bubblePadding: stopButton ? getComputedStyle(stopButton.closest('.message')?.querySelector('.message-bubble')).paddingTop : '',
                    };

                    stopButton?.click();
                    await new Promise(resolve => setTimeout(resolve, 150));

                    const messageElement = document.querySelector('[data-message-id^="temp_ai_"]');
                    return {
                        beforeClick,
                        cancelCall: calls.find(call => call.url === '/api/chat/stream/cancel/ui-stop-conversation') || null,
                        textContent: messageElement?.textContent || '',
                        stopButtonStillVisible: Boolean(document.querySelector('.stream-stop-btn')),
                        stoppedBannerVisible: Boolean(document.querySelector('.stream-stopped-banner')),
                    };
                    }
            """
        )

    assert result["beforeClick"]["exists"] is True
    assert result["beforeClick"]["text"] == ""
    assert result["beforeClick"]["ariaLabel"] == "Stop generating response"
    assert result["beforeClick"]["title"] == "Stop generating"
    assert "rounded-circle" in result["beforeClick"]["className"]
    assert "btn-danger" not in result["beforeClick"]["className"]
    assert result["beforeClick"]["backgroundColor"] == "rgb(164, 90, 90)"
    assert result["beforeClick"]["messageHasStreamingClass"] is True
    assert result["beforeClick"]["bubbleMinWidth"] == "min(360px, 95%)"
    assert result["beforeClick"]["bubblePadding"] == "12px"
    assert result["beforeClick"]["disabled"] is False
    assert result["cancelCall"] is not None
    assert result["cancelCall"]["method"] == "POST"
    assert '"reason":"user_requested"' in result["cancelCall"]["body"].replace(" ", "")
    assert "Partial answer" in result["textContent"]
    assert "Stopped by you." in result["textContent"]
    assert result["stoppedBannerVisible"] is True
    assert result["stopButtonStillVisible"] is False


@pytest.mark.ui
def test_v1_persisted_history_renders_truthful_interruption_after_reload(page, stop_world):
    world = stop_world
    store = world.store()
    store.begin({"message": "Question A"}, world.question)
    assert store.dispatch()
    world.app.test_client().post("/api/chat/stream/cancel/chat", json={"submission_id": "submission-a"})
    partial = deepcopy(world.reply)
    partial["metadata"].update(incomplete=True, canceled=True, cancel_reason="user_requested")
    store.commit(partial)
    provider = deepcopy(world.reply)
    provider.update(id="provider-interrupted", content="Provider partial text", timestamp="2026-11-16T20:01:00Z")
    provider["metadata"].update(incomplete=True)
    world.messages.create_item(body=provider)

    def history_request(route):
        response = world.app.test_client().get("/api/get_messages?conversation_id=chat")
        route.fulfill(status=response.status_code, content_type="application/json", body=response.get_data())

    page.route("**/api/get_messages?**", history_request)
    with _start_static_test_server() as origin:
        page.goto(f"{origin}/{HARNESS_PATH}", wait_until="domcontentloaded")

        def render_history():
            page.add_script_tag(url=f"{origin}/application/single_app/static/js/chat/marked.min.js")
            page.add_script_tag(url=f"{origin}/application/single_app/static/js/chat/purify.min.js")
            page.evaluate("""async () => {
                window.appSettings = { enable_thoughts: false, enable_text_to_speech: false, documentActionCapabilities: {} };
                window.currentConversationId = 'chat';
                window.enable_document_classification = false;
                window.scrollChatToBottom = () => {};
                document.getElementById('test-root').innerHTML = '<div id="chatbox"></div><textarea id="user-input"></textarea><button id="send-btn"></button><select id="prompt-select"></select><div id="prompt-selection-container"></div><select id="model-select"></select>';
                const { appendMessage } = await import('/application/single_app/static/js/chat/chat-messages.js');
                const response = await fetch('/api/get_messages?conversation_id=chat');
                const { messages } = await response.json();
                for (const message of messages) {
                    appendMessage(message.role === 'user' ? 'You' : 'AI', message.content, null, message.id,
                        false, [], [], [], null, null, message);
                }
            }""")

        render_history()
        expect(page.get_by_text("Stopped by you. Response may be incomplete.", exact=True)).to_have_count(1)
        expect(page.get_by_text("This response was interrupted. Response may be incomplete.", exact=True)).to_have_count(2)
        page.reload(wait_until="domcontentloaded")
        render_history()
        expect(page.locator(".message-text").get_by_text("Safe partial answer", exact=True)).to_be_visible()
        expect(page.get_by_text("Stopped by you. Response may be incomplete.", exact=True)).to_have_count(1)
        expect(page.locator(".message-text").get_by_text("Provider partial text", exact=True)).to_be_visible()