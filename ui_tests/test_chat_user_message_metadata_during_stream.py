# test_chat_user_message_metadata_during_stream.py
"""
UI test for user-message metadata during assistant streaming.
Version: 0.250.197
Implemented in: 0.250.197

This test ensures an expanded temporary user-message drawer loads persisted
metadata as soon as the stream acknowledges storage, while the AI remains active.
"""

from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from threading import Thread

import pytest

from functional_tests.test_support.versioning import assert_app_version_at_least


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
def test_user_metadata_loads_before_assistant_stream_finishes(playwright):
    """Reconcile a temp user ID and load its open metadata drawer mid-stream."""
    assert_app_version_at_least("0.250.197")
    browser = playwright.chromium.launch()
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    try:
        with _start_static_test_server() as server_base_url:
            response = page.goto(
                f"{server_base_url}/{HARNESS_PATH}",
                wait_until="domcontentloaded",
            )
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
                    window.currentConversationId = 'metadata-stream-conversation';
                    window.marked = { parse: value => String(value || '') };
                    window.DOMPurify = { sanitize: value => String(value || '') };
                    window.scrollChatToBottom = () => {};

                    const root = document.getElementById('test-root');
                    root.innerHTML = `
                        <div id="chat-messages-container"><div id="chatbox"></div></div>
                        <textarea id="user-input"></textarea>
                        <button id="send-btn" type="button"></button>
                        <select id="prompt-select"></select>
                        <div id="prompt-selection-container"></div>
                        <select id="model-select"><option value="gpt-4o">gpt-4o</option></select>
                    `;

                    const tempUserMessageId = 'temp_user_metadata_stream';
                    const persistedUserMessageId = 'metadata-stream-conversation_user_1';
                    const metadataRequests = [];
                    const metadataResponseCounts = {};
                    const encoder = new TextEncoder();
                    let streamController = null;
                    let reattachController = null;
                    let recoveryMode = false;
                    let manualReattachMode = false;

                    window.fetch = (url, options = {}) => {
                        const requestUrl = String(url);
                        if (requestUrl === '/api/chat/stream') {
                            const body = new ReadableStream({
                                start(controller) {
                                    streamController = controller;
                                    options.signal?.addEventListener('abort', () => {
                                        controller.error(new DOMException('Aborted', 'AbortError'));
                                    }, { once: true });
                                },
                            });
                            return Promise.resolve(new Response(body, {
                                status: 200,
                                headers: { 'Content-Type': 'text/event-stream' },
                            }));
                        }

                        if (requestUrl.includes('/api/chat/stream/status/')) {
                            return Promise.resolve(new Response(JSON.stringify({
                                pending: recoveryMode || manualReattachMode,
                                reattachable: recoveryMode || manualReattachMode,
                                status: recoveryMode || manualReattachMode ? 'running' : 'idle',
                            }), {
                                status: 200,
                                headers: { 'Content-Type': 'application/json' },
                            }));
                        }

                        if (requestUrl.includes('/api/chat/stream/reattach/')) {
                            if (manualReattachMode) {
                                const body = new ReadableStream({
                                    start(controller) {
                                        reattachController = controller;
                                    },
                                });
                                return Promise.resolve(new Response(body, {
                                    status: 200,
                                    headers: { 'Content-Type': 'text/event-stream' },
                                }));
                            }
                            return Promise.resolve(new Response(JSON.stringify({
                                error: 'No active stream is available.',
                            }), {
                                status: recoveryMode ? 404 : 200,
                                headers: { 'Content-Type': 'application/json' },
                            }));
                        }

                        if (
                            requestUrl.startsWith('/api/message/')
                            && requestUrl.endsWith('/metadata')
                        ) {
                            const messageId = requestUrl.slice(
                                '/api/message/'.length,
                                -'/metadata'.length
                            );
                            metadataRequests.push(requestUrl);
                            metadataResponseCounts[messageId] = (
                                metadataResponseCounts[messageId] || 0
                            ) + 1;
                            if (
                                messageId === 'metadata-stream-conversation_user_retry'
                                && metadataResponseCounts[messageId] === 1
                            ) {
                                return Promise.resolve(new Response(JSON.stringify({
                                    error: 'Message not found yet.',
                                }), {
                                    status: 404,
                                    headers: { 'Content-Type': 'application/json' },
                                }));
                            }
                            return Promise.resolve(new Response(JSON.stringify({
                                message_details: {
                                    message_id: messageId,
                                    conversation_id: 'metadata-stream-conversation',
                                    role: 'user',
                                    display_role: metadataResponseCounts[messageId] > 1
                                        ? 'Finalized'
                                        : null,
                                    timestamp: '2026-08-14T16:03:45Z',
                                },
                            }), {
                                status: 200,
                                headers: { 'Content-Type': 'application/json' },
                            }));
                        }

                        return Promise.resolve(new Response(JSON.stringify({ success: true }), {
                            status: 200,
                            headers: { 'Content-Type': 'application/json' },
                        }));
                    };

                    const messagesModule = await import('/application/single_app/static/js/chat/chat-messages.js');
                    const streamingModule = await import('/application/single_app/static/js/chat/chat-streaming.js');
                    const mutatingActionsDisabled = messageElement => {
                        const messageId = messageElement.getAttribute('data-message-id');
                        const actions = Array.from(document.querySelectorAll(
                            '.dropdown-edit-btn, .dropdown-delete-btn, .dropdown-retry-btn, .mask-add-btn, .mask-remove-btn'
                        )).filter(action => action.getAttribute('data-message-id') === messageId);
                        return actions.length === 5 && actions.every(action => (
                            action.dataset.streamingDisabled === 'true'
                            && action.getAttribute('aria-disabled') === 'true'
                            && (!(action instanceof HTMLButtonElement) || action.disabled)
                        ));
                    };

                    messagesModule.appendMessage(
                        'You',
                        'Inspect this message while the assistant is still running.',
                        null,
                        tempUserMessageId
                    );
                    streamingModule.sendMessageWithStreaming(
                        {
                            message: 'Inspect this message while the assistant is still running.',
                            conversation_id: 'metadata-stream-conversation',
                        },
                        tempUserMessageId,
                        'metadata-stream-conversation',
                        { allowRecovery: false }
                    );

                    await new Promise(resolve => setTimeout(resolve, 75));
                    const pendingMessage = document.querySelector(
                        `[data-message-id="${tempUserMessageId}"]`
                    );
                    pendingMessage.querySelector('.metadata-toggle-btn').click();
                    await new Promise(resolve => setTimeout(resolve, 25));

                    const pendingContainer = pendingMessage.querySelector('.metadata-container');
                    const beforePersistence = {
                        messageId: pendingMessage.getAttribute('data-message-id'),
                        metadataState: pendingContainer.dataset.metadataState || '',
                        textContent: pendingContainer.textContent || '',
                        assistantActive: Boolean(document.querySelector('[data-message-id^="temp_ai_"]')),
                        metadataRequestCount: metadataRequests.length,
                    };

                    streamController.enqueue(encoder.encode(
                        `data: ${JSON.stringify({
                            type: 'user_message_persisted',
                            conversation_id: 'metadata-stream-conversation',
                            user_message_id: persistedUserMessageId,
                            message_persisted: true,
                        })}\n\n`
                    ));
                    await new Promise(resolve => setTimeout(resolve, 100));

                    const persistedMessage = document.querySelector(
                        `[data-message-id="${persistedUserMessageId}"]`
                    );
                    const persistedContainer = persistedMessage.querySelector('.metadata-container');
                    const metadataButton = persistedMessage.querySelector('.metadata-toggle-btn');
                    const afterPersistence = {
                        temporaryMessageExists: Boolean(document.querySelector(
                            `[data-message-id="${tempUserMessageId}"]`
                        )),
                        messageId: persistedMessage.getAttribute('data-message-id'),
                        buttonMessageId: metadataButton.getAttribute('data-message-id'),
                        controlledContainerId: metadataButton.getAttribute('aria-controls'),
                        containerId: persistedContainer.id,
                        metadataState: persistedContainer.dataset.metadataState || '',
                        textContent: persistedContainer.textContent || '',
                        assistantActive: Boolean(document.querySelector('[data-message-id^="temp_ai_"]')),
                        mutatingActionsDisabled: mutatingActionsDisabled(persistedMessage),
                        metadataRequests: [...metadataRequests],
                    };

                    const actionDropdownToggle = persistedMessage.querySelector(
                        ".message-footer .dropdown button[data-bs-toggle='dropdown']"
                    );
                    const actionDropdownMenu = persistedMessage.querySelector(
                        '.message-footer .dropdown-menu'
                    );
                    actionDropdownToggle.dispatchEvent(new Event('show.bs.dropdown'));
                    const actionMenuReparented = actionDropdownMenu.parentElement?.id === 'chatbox';
                    metadataButton.click();
                    streamController.enqueue(encoder.encode(
                        `data: ${JSON.stringify({
                            done: true,
                            conversation_id: 'metadata-stream-conversation',
                            user_message_id: persistedUserMessageId,
                            message_id: 'metadata-stream-assistant-1',
                            full_content: 'Completed response.',
                            role: 'assistant',
                            model_deployment_name: 'gpt-4o',
                            augmented: false,
                            hybrid_citations: [],
                            web_search_citations: [],
                            agent_citations: [],
                            metadata: {},
                        })}\n\n`
                    ));
                    streamController.close();
                    await new Promise(resolve => setTimeout(resolve, 100));

                    const finalizedContainer = persistedMessage.querySelector('.metadata-container');
                    const afterTerminalWhileHidden = {
                        metadataState: finalizedContainer.dataset.metadataState || '',
                        isHidden: finalizedContainer.style.display === 'none',
                        metadataRequests: [...metadataRequests],
                        actionMenuReparented,
                        actionMenuStillExternal: actionDropdownMenu.parentElement?.id === 'chatbox',
                        mutatingActionsDisabled: mutatingActionsDisabled(persistedMessage),
                    };
                    actionDropdownToggle.dispatchEvent(new Event('hidden.bs.dropdown'));
                    metadataButton.click();
                    await new Promise(resolve => setTimeout(resolve, 100));
                    const afterCompletion = {
                        metadataState: finalizedContainer.dataset.metadataState || '',
                        textContent: finalizedContainer.textContent || '',
                        metadataRequests: [...metadataRequests],
                        assistantActive: Boolean(document.querySelector('[data-message-id^="temp_ai_"]')),
                        mutatingActionsDisabled: mutatingActionsDisabled(persistedMessage),
                        actionMenuReturned: actionDropdownMenu.closest(
                            `[data-message-id="${persistedUserMessageId}"]`
                        ) === persistedMessage,
                    };

                    manualReattachMode = true;
                    await streamingModule.reattachStreamingConversation(
                        'metadata-stream-conversation',
                        { statusLabel: 'Reconnecting metadata stream' }
                    );
                    await new Promise(resolve => setTimeout(resolve, 50));
                    reattachController.enqueue(encoder.encode(
                        `data: ${JSON.stringify({
                            type: 'user_message_persisted',
                            conversation_id: 'metadata-stream-conversation',
                            user_message_id: persistedUserMessageId,
                            message_persisted: true,
                        })}\n\n`
                    ));
                    await new Promise(resolve => setTimeout(resolve, 50));
                    const manualReattachActive = {
                        mutatingActionsDisabled: mutatingActionsDisabled(persistedMessage),
                    };
                    reattachController.enqueue(encoder.encode(
                        `data: ${JSON.stringify({
                            done: true,
                            conversation_id: 'metadata-stream-conversation',
                            user_message_id: persistedUserMessageId,
                            message_id: 'metadata-stream-assistant-reattached',
                            full_content: 'Reattached response complete.',
                            role: 'assistant',
                            model_deployment_name: 'gpt-4o',
                            augmented: false,
                            hybrid_citations: [],
                            web_search_citations: [],
                            agent_citations: [],
                            metadata: {},
                        })}\n\n`
                    ));
                    reattachController.close();
                    await new Promise(resolve => setTimeout(resolve, 100));
                    manualReattachMode = false;
                    const manualReattachCompleted = {
                        metadataState: finalizedContainer.dataset.metadataState || '',
                        textContent: finalizedContainer.textContent || '',
                        metadataRequests: metadataRequests.filter(
                            requestUrl => requestUrl.includes(persistedUserMessageId)
                        ),
                        mutatingActionsDisabled: mutatingActionsDisabled(persistedMessage),
                    };

                    const postAckTempMessageId = 'temp_user_metadata_error_after_ack';
                    const postAckPersistedMessageId = 'metadata-stream-conversation_user_2';
                    messagesModule.appendMessage(
                        'You',
                        'This message persists before a later stream error.',
                        null,
                        postAckTempMessageId
                    );
                    streamingModule.sendMessageWithStreaming(
                        {
                            message: 'This message persists before a later stream error.',
                            conversation_id: 'metadata-stream-conversation',
                        },
                        postAckTempMessageId,
                        'metadata-stream-conversation',
                        { allowRecovery: false }
                    );
                    await new Promise(resolve => setTimeout(resolve, 50));
                    const postAckPendingMessage = document.querySelector(
                        `[data-message-id="${postAckTempMessageId}"]`
                    );
                    postAckPendingMessage.querySelector('.metadata-toggle-btn').click();
                    streamController.enqueue(encoder.encode(
                        `data: ${JSON.stringify({
                            type: 'user_message_persisted',
                            conversation_id: 'metadata-stream-conversation',
                            user_message_id: postAckPersistedMessageId,
                            message_persisted: true,
                        })}\n\n`
                    ));
                    await new Promise(resolve => setTimeout(resolve, 75));
                    streamController.enqueue(encoder.encode(
                        'data: {"error":"Generation failed after persistence."}\n\n'
                    ));
                    streamController.close();
                    await new Promise(resolve => setTimeout(resolve, 100));
                    const postAckMessage = document.querySelector(
                        `[data-message-id="${postAckPersistedMessageId}"]`
                    );
                    const postAckContainer = postAckMessage.querySelector('.metadata-container');
                    const postAckError = {
                        metadataState: postAckContainer.dataset.metadataState || '',
                        textContent: postAckContainer.textContent || '',
                        metadataRequests: metadataRequests.filter(
                            requestUrl => requestUrl.includes(postAckPersistedMessageId)
                        ),
                        mutatingActionsDisabled: mutatingActionsDisabled(postAckMessage),
                    };

                    const retryTempMessageId = 'temp_user_metadata_retry';
                    const retryPersistedMessageId = 'metadata-stream-conversation_user_retry';
                    messagesModule.appendMessage(
                        'You',
                        'This metadata request retries while terminal metadata refreshes.',
                        null,
                        retryTempMessageId
                    );
                    streamingModule.sendMessageWithStreaming(
                        {
                            message: 'This metadata request retries while terminal metadata refreshes.',
                            conversation_id: 'metadata-stream-conversation',
                        },
                        retryTempMessageId,
                        'metadata-stream-conversation',
                        { allowRecovery: false }
                    );
                    await new Promise(resolve => setTimeout(resolve, 50));
                    const retryPendingMessage = document.querySelector(
                        `[data-message-id="${retryTempMessageId}"]`
                    );
                    retryPendingMessage.querySelector('.metadata-toggle-btn').click();
                    streamController.enqueue(encoder.encode(
                        `data: ${JSON.stringify({
                            type: 'user_message_persisted',
                            conversation_id: 'metadata-stream-conversation',
                            user_message_id: retryPersistedMessageId,
                            message_persisted: true,
                        })}\n\n`
                    ));
                    await new Promise(resolve => setTimeout(resolve, 50));
                    streamController.enqueue(encoder.encode(
                        `data: ${JSON.stringify({
                            done: true,
                            conversation_id: 'metadata-stream-conversation',
                            user_message_id: retryPersistedMessageId,
                            message_id: 'metadata-stream-assistant-retry',
                            full_content: 'Completed retry response.',
                            role: 'assistant',
                            model_deployment_name: 'gpt-4o',
                            augmented: false,
                            hybrid_citations: [],
                            web_search_citations: [],
                            agent_citations: [],
                            metadata: {},
                        })}\n\n`
                    ));
                    streamController.close();
                    await new Promise(resolve => setTimeout(resolve, 650));
                    const retryMessage = document.querySelector(
                        `[data-message-id="${retryPersistedMessageId}"]`
                    );
                    const retryContainer = retryMessage.querySelector('.metadata-container');
                    const staleRetry = {
                        metadataState: retryContainer.dataset.metadataState || '',
                        textContent: retryContainer.textContent || '',
                        metadataRequests: metadataRequests.filter(
                            requestUrl => requestUrl.includes(retryPersistedMessageId)
                        ),
                        mutatingActionsDisabled: mutatingActionsDisabled(retryMessage),
                    };

                    const detachedTempMessageId = 'temp_user_metadata_detached';
                    const detachedPersistedMessageId = 'metadata-stream-conversation_user_3';
                    messagesModule.appendMessage(
                        'You',
                        'This persisted message detaches before terminal enrichment.',
                        null,
                        detachedTempMessageId
                    );
                    streamingModule.sendMessageWithStreaming(
                        {
                            message: 'This persisted message detaches before terminal enrichment.',
                            conversation_id: 'metadata-stream-conversation',
                        },
                        detachedTempMessageId,
                        'metadata-stream-conversation',
                        { allowRecovery: false }
                    );
                    await new Promise(resolve => setTimeout(resolve, 50));
                    const detachedPendingMessage = document.querySelector(
                        `[data-message-id="${detachedTempMessageId}"]`
                    );
                    detachedPendingMessage.querySelector('.metadata-toggle-btn').click();
                    streamController.enqueue(encoder.encode(
                        `data: ${JSON.stringify({
                            type: 'user_message_persisted',
                            conversation_id: 'metadata-stream-conversation',
                            user_message_id: detachedPersistedMessageId,
                            message_persisted: true,
                        })}\n\n`
                    ));
                    await new Promise(resolve => setTimeout(resolve, 75));
                    streamingModule.sendMessageWithStreaming(
                        {
                            message: 'Replace the detached response.',
                            conversation_id: 'metadata-stream-conversation',
                        },
                        null,
                        'metadata-stream-conversation',
                        { allowRecovery: false }
                    );
                    await new Promise(resolve => setTimeout(resolve, 75));
                    const detachedMessage = document.querySelector(
                        `[data-message-id="${detachedPersistedMessageId}"]`
                    );
                    const detachedContainer = detachedMessage.querySelector('.metadata-container');
                    const detachedStream = {
                        metadataState: detachedContainer.dataset.metadataState || '',
                        textContent: detachedContainer.textContent || '',
                        metadataRequests: metadataRequests.filter(
                            requestUrl => requestUrl.includes(detachedPersistedMessageId)
                        ),
                        mutatingActionsDisabled: mutatingActionsDisabled(detachedMessage),
                    };

                    const recoveryTempMessageId = 'temp_user_metadata_recovery';
                    const recoveryPersistedMessageId = 'metadata-stream-conversation_user_recovery';
                    messagesModule.appendMessage(
                        'You',
                        'This persisted message fails during stream reattachment.',
                        null,
                        recoveryTempMessageId
                    );
                    streamingModule.sendMessageWithStreaming(
                        {
                            message: 'This persisted message fails during stream reattachment.',
                            conversation_id: 'metadata-stream-conversation',
                        },
                        recoveryTempMessageId,
                        'metadata-stream-conversation',
                        { allowRecovery: true }
                    );
                    await new Promise(resolve => setTimeout(resolve, 50));
                    const recoveryPendingMessage = document.querySelector(
                        `[data-message-id="${recoveryTempMessageId}"]`
                    );
                    recoveryPendingMessage.querySelector('.metadata-toggle-btn').click();
                    streamController.enqueue(encoder.encode(
                        `data: ${JSON.stringify({
                            type: 'user_message_persisted',
                            conversation_id: 'metadata-stream-conversation',
                            user_message_id: recoveryPersistedMessageId,
                            message_persisted: true,
                        })}\n\n`
                    ));
                    await new Promise(resolve => setTimeout(resolve, 75));
                    recoveryMode = true;
                    streamController.error(new Error('Simulated network interruption.'));
                    await new Promise(resolve => setTimeout(resolve, 200));
                    recoveryMode = false;
                    const recoveryMessage = document.querySelector(
                        `[data-message-id="${recoveryPersistedMessageId}"]`
                    );
                    const recoveryContainer = recoveryMessage.querySelector('.metadata-container');
                    const failedRecovery = {
                        metadataState: recoveryContainer.dataset.metadataState || '',
                        textContent: recoveryContainer.textContent || '',
                        metadataRequests: metadataRequests.filter(
                            requestUrl => requestUrl.includes(recoveryPersistedMessageId)
                        ),
                        mutatingActionsDisabled: mutatingActionsDisabled(recoveryMessage),
                    };

                    const failedTempMessageId = 'temp_user_metadata_failed';
                    messagesModule.appendMessage(
                        'You',
                        'This message fails before persistence.',
                        null,
                        failedTempMessageId
                    );
                    streamingModule.sendMessageWithStreaming(
                        {
                            message: 'This message fails before persistence.',
                            conversation_id: 'metadata-stream-conversation',
                        },
                        failedTempMessageId,
                        'metadata-stream-conversation',
                        { allowRecovery: false }
                    );
                    await new Promise(resolve => setTimeout(resolve, 50));
                    const failedMessage = document.querySelector(
                        `[data-message-id="${failedTempMessageId}"]`
                    );
                    failedMessage.querySelector('.metadata-toggle-btn').click();
                    streamController.enqueue(encoder.encode(
                        'data: {"error":"Validation failed before persistence."}\n\n'
                    ));
                    streamController.close();
                    await new Promise(resolve => setTimeout(resolve, 75));
                    const failedContainer = failedMessage.querySelector('.metadata-container');
                    const failedPersistence = {
                        metadataState: failedContainer.dataset.metadataState || '',
                        textContent: failedContainer.textContent || '',
                        metadataRequestCount: metadataRequests.filter(
                            requestUrl => requestUrl.includes(failedTempMessageId)
                        ).length,
                        mutatingActionsDisabled: mutatingActionsDisabled(failedMessage),
                    };

                    return {
                        beforePersistence,
                        afterPersistence,
                        afterTerminalWhileHidden,
                        afterCompletion,
                        manualReattachActive,
                        manualReattachCompleted,
                        postAckError,
                        staleRetry,
                        detachedStream,
                        failedRecovery,
                        failedPersistence,
                    };
                }
                """
            )

        before = snapshots["beforePersistence"]
        assert before["messageId"] == "temp_user_metadata_stream"
        assert before["metadataState"] == "pending"
        assert "Saving message metadata..." in before["textContent"]
        assert "temporary ID not updated" not in before["textContent"]
        assert before["assistantActive"] is True
        assert before["metadataRequestCount"] == 0

        after = snapshots["afterPersistence"]
        assert after["temporaryMessageExists"] is False
        assert after["messageId"] == "metadata-stream-conversation_user_1"
        assert after["buttonMessageId"] == "metadata-stream-conversation_user_1"
        assert after["controlledContainerId"] == after["containerId"]
        assert "metadata-stream-conversation_user_1" in after["containerId"]
        assert after["metadataState"] == "loaded"
        assert "Message Details" in after["textContent"]
        assert "metadata-stream-conversation_user_1" in after["textContent"]
        assert after["assistantActive"] is True
        assert after["mutatingActionsDisabled"] is True
        assert after["metadataRequests"] == [
            "/api/message/metadata-stream-conversation_user_1/metadata"
        ]

        hidden = snapshots["afterTerminalWhileHidden"]
        assert hidden["metadataState"] == "stale"
        assert hidden["isHidden"] is True
        assert hidden["metadataRequests"] == [
            "/api/message/metadata-stream-conversation_user_1/metadata"
        ]
        assert hidden["actionMenuReparented"] is True
        assert hidden["actionMenuStillExternal"] is True
        assert hidden["mutatingActionsDisabled"] is False

        completed = snapshots["afterCompletion"]
        assert completed["metadataState"] == "loaded"
        assert "Finalized" in completed["textContent"]
        assert completed["metadataRequests"] == [
            "/api/message/metadata-stream-conversation_user_1/metadata",
            "/api/message/metadata-stream-conversation_user_1/metadata",
        ]
        assert completed["assistantActive"] is False
        assert completed["mutatingActionsDisabled"] is False
        assert completed["actionMenuReturned"] is True

        manual_active = snapshots["manualReattachActive"]
        assert manual_active["mutatingActionsDisabled"] is True

        manual_completed = snapshots["manualReattachCompleted"]
        assert manual_completed["metadataState"] == "loaded"
        assert "Finalized" in manual_completed["textContent"]
        assert manual_completed["metadataRequests"] == [
            "/api/message/metadata-stream-conversation_user_1/metadata",
            "/api/message/metadata-stream-conversation_user_1/metadata",
            "/api/message/metadata-stream-conversation_user_1/metadata",
        ]
        assert manual_completed["mutatingActionsDisabled"] is False

        post_ack_error = snapshots["postAckError"]
        assert post_ack_error["metadataState"] == "loaded"
        assert "Finalized" in post_ack_error["textContent"]
        assert post_ack_error["metadataRequests"] == [
            "/api/message/metadata-stream-conversation_user_2/metadata",
            "/api/message/metadata-stream-conversation_user_2/metadata",
        ]
        assert post_ack_error["mutatingActionsDisabled"] is False

        stale_retry = snapshots["staleRetry"]
        assert stale_retry["metadataState"] == "loaded"
        assert "Finalized" in stale_retry["textContent"]
        assert stale_retry["metadataRequests"] == [
            "/api/message/metadata-stream-conversation_user_retry/metadata",
            "/api/message/metadata-stream-conversation_user_retry/metadata",
        ]
        assert stale_retry["mutatingActionsDisabled"] is False

        detached = snapshots["detachedStream"]
        assert detached["metadataState"] == "finalization-unconfirmed"
        assert "may still be updating" in detached["textContent"]
        assert detached["metadataRequests"] == [
            "/api/message/metadata-stream-conversation_user_3/metadata"
        ]
        assert detached["mutatingActionsDisabled"] is True

        recovery = snapshots["failedRecovery"]
        assert recovery["metadataState"] == "finalization-unconfirmed"
        assert "may still be updating" in recovery["textContent"]
        assert recovery["metadataRequests"] == [
            "/api/message/metadata-stream-conversation_user_recovery/metadata"
        ]
        assert recovery["mutatingActionsDisabled"] is True

        failed = snapshots["failedPersistence"]
        assert failed["metadataState"] == "unconfirmed"
        assert "persistence could not be confirmed" in failed["textContent"]
        assert "Saving message metadata..." not in failed["textContent"]
        assert failed["metadataRequestCount"] == 0
        assert failed["mutatingActionsDisabled"] is True
    finally:
        context.close()
        browser.close()
