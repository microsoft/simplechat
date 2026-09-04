# test_chat_collaboration_conversation_load.py
"""
UI test for shared (multi-user) conversation message loading.
Version: 0.250.224
Implemented in: 0.250.224

This test ensures the shipped collaboration message loader fetches shared
conversation messages from the collaboration endpoint only, never from the
personal /conversation/<id>/messages endpoint that always returned 404 for
shared conversations, and that it still performs the search highlight, task
document, and comparison chat upload side effects the personal loader provided.

Regression coverage for issue #1281.
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import socket
from threading import Thread

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = "ui_tests/fixtures/collaboration_conversation_load_harness.html"
COLLABORATION_JS = (
    REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-collaboration.js"
)
CONVERSATION_ID = "9f615422-f4d8-4352-ad09-016cb3d735c1"

COLLABORATION_MESSAGES = [
    {
        "id": "shared-user-message-001",
        "conversation_id": CONVERSATION_ID,
        "role": "user",
        "content": "How many TM packets have arrived since startup?",
        "timestamp": "2026-08-18T14:00:00+00:00",
        "metadata": {"sender": {"user_id": "user-a", "display_name": "Ada"}},
    },
    {
        "id": "shared-assistant-message-001",
        "conversation_id": CONVERSATION_ID,
        "role": "assistant",
        "content": "4,182 telemetry packets have arrived since startup.",
        "timestamp": "2026-08-18T14:00:05+00:00",
        "metadata": {"sender": {"user_id": "assistant", "display_name": "AI"}},
    },
    {
        "id": "shared-file-message-001",
        "conversation_id": CONVERSATION_ID,
        "role": "file",
        "content": "",
        "filename": "telemetry-log.csv",
        "extracted_text": "packet_id,received_at",
        "timestamp": "2026-08-18T14:00:10+00:00",
        "metadata": {
            "sender": {"user_id": "user-a", "display_name": "Ada"},
            "workspace_attachment": {"document_id": "workspace-doc-001"},
        },
    },
]


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


def _extract_loader_source():
    """Slice the shipped loader functions out of chat-collaboration.js."""
    collaboration_source = COLLABORATION_JS.read_text(encoding="utf-8")

    start_marker = "function reapplyPendingSearchHighlight() {"
    end_marker = "    return messages;\n}"
    start_index = collaboration_source.find(start_marker)
    assert start_index != -1, "Expected reapplyPendingSearchHighlight() in chat-collaboration.js."

    end_index = collaboration_source.find(end_marker, start_index)
    assert end_index != -1, "Expected loadConversationMessages() to end with 'return messages;'."

    loader_source = collaboration_source[start_index:end_index + len(end_marker)]
    assert "async function loadConversationMessages(conversationId) {" in loader_source, (
        "Expected the extracted slice to contain loadConversationMessages()."
    )
    assert "const SEARCH_HIGHLIGHT_MAX_AGE_MS = 30000;" in collaboration_source, (
        "Expected the 30 second search highlight freshness window constant."
    )
    return loader_source


def _build_harness_script(loader_source):
    """Wrap the shipped loader with spies so browser behavior can be observed."""
    return (
        """
window.__spyCalls = [];

const SEARCH_HIGHLIGHT_MAX_AGE_MS = 30000;

function recordCall(name, payload) {
    window.__spyCalls.push({ name, ...payload });
}

function clearSearchHighlight() {
    recordCall('clearSearchHighlight', {});
}

function applySearchHighlight(term) {
    recordCall('applySearchHighlight', { term });
}

function clearTypingState() {
    recordCall('clearTypingState', {});
}

function clearMessageCache() {
    recordCall('clearMessageCache', {});
}

function updateConversationTaskDocumentsFromMessages(messages, conversationId) {
    recordCall('updateConversationTaskDocumentsFromMessages', {
        conversationId,
        workspaceAttachmentCount: messages.filter(
            message => message?.metadata?.workspace_attachment
        ).length,
    });
}

function updateComparisonChatUploadCatalog(messages) {
    recordCall('updateComparisonChatUploadCatalog', {
        uploadCount: messages.filter(message => message?.role === 'file').length,
    });
}

function groupGeneratedImageProposalMessages() {
    return new Map();
}

function getGeneratedImageProposalSourceMessageId() {
    return '';
}

function decorateReplyMessage(message) {
    return { ...message };
}

function renderCollaborationMessage(message) {
    const chatbox = document.getElementById('chatbox');
    const messageElement = document.createElement('div');
    messageElement.className = 'collaboration-message';
    messageElement.dataset.messageId = message.id;
    messageElement.textContent = message.content || message.filename || '';
    chatbox.appendChild(messageElement);
}

function cacheCollaborationMessage(message) {
    recordCall('cacheCollaborationMessage', { messageId: message.id });
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, { credentials: 'same-origin', ...options });
    if (!response.ok) {
        throw new Error(`Request failed with status ${response.status}`);
    }
    return response.json();
}

"""
        + loader_source
        + """

window.__loadConversationMessages = loadConversationMessages;
"""
    )


@pytest.mark.ui
def test_shared_conversation_loads_only_from_collaboration_endpoint(playwright):
    """Validate shared conversations never hit the personal messages endpoint."""
    loader_source = _extract_loader_source()
    harness_script = _build_harness_script(loader_source)

    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    personal_endpoint_requests = []
    collaboration_endpoint_requests = []
    console_errors = []

    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )

    def handle_personal_messages(route):
        personal_endpoint_requests.append(route.request.url)
        route.fulfill(
            status=404,
            content_type="application/json",
            body=json.dumps({"error": "Conversation not found"}),
        )

    def handle_collaboration_messages(route):
        collaboration_endpoint_requests.append(route.request.url)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"messages": COLLABORATION_MESSAGES}),
        )

    page.route("**/conversation/*/messages*", handle_personal_messages)
    page.route(
        "**/api/collaboration/conversations/*/messages",
        handle_collaboration_messages,
    )

    try:
        with _start_static_test_server() as base_url:
            page.goto(f"{base_url}/{HARNESS_PATH}", wait_until="domcontentloaded")
            page.add_script_tag(content=harness_script)

            page.evaluate(
                "() => { window.searchHighlight = { term: 'telemetry', timestamp: Date.now() }; }"
            )

            loaded_message_ids = page.evaluate(
                """
                async (conversationId) => {
                    const messages = await window.__loadConversationMessages(conversationId);
                    return messages.map(message => message.id);
                }
                """,
                CONVERSATION_ID,
            )

            # Highlight reapplication is scheduled on a 100ms timer.
            page.wait_for_function(
                "() => window.__spyCalls.some(call => call.name === 'applySearchHighlight')"
            )

            spy_calls = page.evaluate("() => window.__spyCalls")
            rendered_message_ids = page.eval_on_selector_all(
                "#chatbox .collaboration-message",
                "elements => elements.map(element => element.dataset.messageId)",
            )
    finally:
        context.close()
        browser.close()

    assert personal_endpoint_requests == [], (
        "Shared conversations must never request the personal /conversation/<id>/messages endpoint, "
        f"but saw: {personal_endpoint_requests}"
    )
    assert len(collaboration_endpoint_requests) == 1, (
        "Expected exactly one request to the collaboration messages endpoint, "
        f"saw: {collaboration_endpoint_requests}"
    )
    assert CONVERSATION_ID in collaboration_endpoint_requests[0]

    assert loaded_message_ids == [message["id"] for message in COLLABORATION_MESSAGES]
    assert rendered_message_ids == [message["id"] for message in COLLABORATION_MESSAGES]

    call_names = [call["name"] for call in spy_calls]
    assert call_names[0] == "clearSearchHighlight", (
        f"Expected stale highlights to be cleared before loading, got order: {call_names}"
    )

    task_document_calls = [
        call for call in spy_calls if call["name"] == "updateConversationTaskDocumentsFromMessages"
    ]
    assert len(task_document_calls) == 1, (
        "Expected conversation task documents to be rehydrated exactly once."
    )
    assert task_document_calls[0]["conversationId"] == CONVERSATION_ID, (
        "Task documents must be hydrated against the shared conversation id."
    )
    assert task_document_calls[0]["workspaceAttachmentCount"] == 1

    comparison_calls = [
        call for call in spy_calls if call["name"] == "updateComparisonChatUploadCatalog"
    ]
    assert len(comparison_calls) == 1, (
        "Expected the comparison chat upload catalog to be refreshed exactly once."
    )
    assert comparison_calls[0]["uploadCount"] == 1, (
        "Shared conversation chat uploads must reach the Compare/Analyze picker."
    )

    highlight_calls = [call for call in spy_calls if call["name"] == "applySearchHighlight"]
    assert highlight_calls and highlight_calls[0]["term"] == "telemetry", (
        "Expected a fresh pending search highlight to be reapplied after rendering."
    )

    assert console_errors == [], f"Unexpected browser console errors: {console_errors}"
