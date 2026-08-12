# test_chat_background_generated_export_status.py
"""
UI test for chat background generated export status cards.
Version: 0.250.168
Implemented in: 0.241.046; cancellation in 0.250.060; automatic-only refresh in 0.250.061; combined progress and large-run confirmation in 0.250.131; throughput and concurrency status in 0.250.136; truthful background handoff in 0.250.138; collapsed operational details in 0.250.150; confirmation deduplication in 0.250.168

This test ensures queued tabular generated exports render progress in chat and
turn into a downloadable artifact when complete or a visible canceled state.
"""

import os
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
from threading import Thread

import pytest


playwright_sync_api = pytest.importorskip("playwright.sync_api")
expect = playwright_sync_api.expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = "ui_tests/fixtures/chat_thought_progress_harness.html"


def _get_free_local_port() -> int:
    """Reserve an available local port for a static test server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def _start_static_test_server():
    """Serve repository browser assets for self-contained UI tests."""
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


def _require_ui_env() -> None:
    """Skip unless an authenticated UI target is configured."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip(
            "Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file."
        )


@pytest.mark.ui
def test_chat_background_generated_export_status_card_auto_refreshes_to_download(playwright) -> None:
    """Validate queued exports transition automatically without a manual refresh control."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.route(
            "**/api/tabular/generated-output/runs/run-ui-test",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                json={
                    "success": True,
                    "run": {
                        "run_id": "run-ui-test",
                        "status": "completed",
                        "row_count": 3539,
                        "processed_rows": 3539,
                        "batch_count": 1592,
                        "completed_batches": 1592,
                        "progress_percent": 100,
                        "generated_artifact": {
                            "capability": "tabular",
                            "artifact_message_id": "artifact-ui-test",
                            "conversation_id": "conversation-ui-test",
                            "file_name": "generated-output.json",
                            "output_format": "json",
                            "row_count": 3539,
                            "storage_scope": "chat",
                        },
                    },
                },
            ),
        )
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        page.evaluate(
            """
            async () => {
                const module = await import('/static/js/chat/chat-messages.js');
                window.currentConversationId = 'conversation-ui-test';
                module.appendMessage(
                    'AI',
                    'Understood. I am generating the complete JSON for all 3,539 rows. The rows shown here are a sample; the rest is being generated in the background, and the complete file will appear in this chat when ready.',
                    null,
                    'message-ui-test',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        metadata: {
                            generated_tabular_outputs: [
                                {
                                    capability: 'tabular',
                                    background_export: true,
                                    export_run_id: 'run-ui-test',
                                    run_id: 'run-ui-test',
                                    status: 'running',
                                    file_name: 'generated-output.json',
                                    output_format: 'json',
                                    row_count: 3539,
                                    processed_rows: 652,
                                    batch_count: 1592,
                                    completed_batches: 298,
                                    source_file_name: 'query_data.xlsx',
                                    preview_rows: [
                                        { account_id: 'sample-001', risk: 'review' },
                                        { account_id: 'sample-002', risk: 'clear' }
                                    ]
                                }
                            ]
                        }
                    },
                    false
                );
            }
            """
        )

        message = page.locator('[data-message-id="message-ui-test"]')
        expect(message.get_by_text("Understood. I am generating the complete JSON for all 3,539 rows.")).to_be_visible()
        expect(message.get_by_text("The rows shown here are a sample")).to_be_visible()
        expect(message.get_by_text("Preview", exact=True)).to_be_hidden()
        expect(message.get_by_text("Background export")).to_be_visible()
        expect(message.get_by_text("Running")).to_be_visible()
        details = message.locator('[data-generated-export-details="true"]')
        expect(details).not_to_have_attribute("open", "")
        expect(message.get_by_text("298 of 1,592 batches")).to_be_hidden()
        expect(message.get_by_text("Continuing in the background.", exact=False)).to_be_hidden()
        details.get_by_text("View details", exact=True).click()
        expect(message.get_by_text("298 of 1,592 batches")).to_be_visible()
        expect(message.get_by_text("Preview", exact=True)).to_be_visible()
        rendered_text = message.inner_text().lower()
        assert "can only" not in rendered_text
        assert "schema preview" not in rendered_text
        assert "if you want, i can" not in rendered_text
        expect(message.get_by_role("button", name="Refresh Status")).to_have_count(0)
        assert message.get_by_role("button", name="Download JSON").count() == 0

        expect(message.get_by_role("button", name="Download JSON")).to_be_visible(timeout=15000)
        expect(message.get_by_text("Saved to this chat for download in this conversation.")).to_be_visible()
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_background_generated_export_can_be_canceled(playwright) -> None:
    """Validate a running export exposes Cancel and renders the durable canceled state."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page_errors = []
    cancel_requests = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    try:
        page.route(
            "**/api/tabular/generated-output/runs/run-cancel-test/cancel",
            lambda route: (
                cancel_requests.append(route.request.method),
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    json={
                        "success": True,
                        "canceled": True,
                        "message": "Background export canceled.",
                        "run": {
                            "run_id": "run-cancel-test",
                            "status": "canceled",
                            "status_label": "Canceled",
                            "status_tone": "secondary",
                            "status_detail": "Export was canceled.",
                            "row_count": 30000,
                            "processed_rows": 1250,
                            "batch_count": 600,
                            "completed_batches": 25,
                            "progress_percent": 4.17,
                            "checkpoint_summary": "25 of 600 batches checkpointed; 1,250 of 30,000 rows processed",
                            "can_resume": False,
                            "can_cancel": False,
                            "background_export": True,
                        },
                    },
                ),
            ),
        )
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        page.evaluate(
            """
            async () => {
                const module = await import('/static/js/chat/chat-messages.js');
                window.currentConversationId = 'conversation-cancel-test';
                module.appendMessage(
                    'AI',
                    'The exhaustive export is running.',
                    null,
                    'message-cancel-test',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        metadata: {
                            generated_tabular_outputs: [
                                {
                                    capability: 'tabular',
                                    background_export: true,
                                    export_run_id: 'run-cancel-test',
                                    run_id: 'run-cancel-test',
                                    status: 'running',
                                    status_label: 'Running',
                                    can_cancel: true,
                                    can_resume: false,
                                    file_name: 'generated-output.csv',
                                    output_format: 'csv',
                                    row_count: 30000,
                                    processed_rows: 1250,
                                    batch_count: 600,
                                    completed_batches: 25,
                                    source_file_name: 'large-source.csv'
                                }
                            ]
                        }
                    },
                    false
                );
            }
            """
        )

        message = page.locator('[data-message-id="message-cancel-test"]')
        details = message.locator('[data-generated-export-details="true"]')
        expect(message.get_by_text("25 of 600 batches", exact=False)).to_be_hidden()
        details.get_by_text("View details", exact=True).click()
        cancel_button = message.get_by_role("button", name="Cancel background export")
        expect(cancel_button).to_be_visible()
        cancel_button.click()

        expect(message.get_by_text("Canceled", exact=True)).to_be_visible()
        expect(message.get_by_text("25 of 600 batches checkpointed")).to_be_visible()
        expect(cancel_button).to_be_hidden()
        assert cancel_requests == ["POST"]
        assert page_errors == []
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_combined_background_status_shows_reduce_progress(playwright) -> None:
    """Validate combined runs show map/reduce phase and remaining work."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    try:
        page.route(
            "**/api/tabular/generated-output/runs/run-combined-progress",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                json={
                    "success": True,
                    "run": {
                        "run_id": "run-combined-progress",
                        "task_type": "combined",
                        "status": "running",
                        "status_label": "Running",
                        "status_tone": "info",
                        "status_detail": "Combined run is reducing checkpointed chunk summaries.",
                        "analysis_phase": "reducing",
                        "analysis_reduce_level": 1,
                        "analysis_reduce_node": 2,
                        "analysis_reduce_node_count": 4,
                        "row_count": 3000,
                        "processed_rows": 2400,
                        "batch_count": 60,
                        "completed_batches": 48,
                        "total_chunk_count": 60,
                        "processed_chunk_count": 48,
                        "failed_chunk_count": 0,
                        "progress_percent": 80,
                        "estimated_remaining_seconds": 120,
                        "rows_per_minute": 1200.5,
                        "batch_concurrency": 16,
                        "effective_batch_concurrency": 16,
                        "background_export": True,
                    },
                },
            ),
        )
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        page.evaluate(
            """
            async () => {
                const module = await import('/static/js/chat/chat-messages.js');
                window.currentConversationId = 'conversation-combined-progress';
                module.appendMessage(
                    'AI',
                    'The combined run is continuing in the background.',
                    null,
                    'message-combined-progress',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        metadata: {
                            generated_tabular_outputs: [
                                {
                                    capability: 'tabular',
                                    background_export: true,
                                    export_run_id: 'run-combined-progress',
                                    run_id: 'run-combined-progress',
                                    task_type: 'combined',
                                    status: 'running',
                                    status_label: 'Running',
                                    status_detail: 'Combined run is reducing checkpointed chunk summaries.',
                                    analysis_phase: 'reducing',
                                    analysis_reduce_level: 1,
                                    analysis_reduce_node: 2,
                                    analysis_reduce_node_count: 4,
                                    row_count: 3000,
                                    processed_rows: 2400,
                                    batch_count: 60,
                                    completed_batches: 48,
                                    total_chunk_count: 60,
                                    processed_chunk_count: 48,
                                    progress_percent: 80,
                                    estimated_remaining_seconds: 120,
                                    rows_per_minute: 1200.5,
                                    batch_concurrency: 16,
                                    effective_batch_concurrency: 16,
                                    file_name: 'combined-output.csv',
                                    output_format: 'csv',
                                    source_file_name: 'large-source.csv'
                                }
                            ]
                        }
                    },
                    false
                );
            }
            """
        )

        message = page.locator('[data-message-id="message-combined-progress"]')
        expect(message.get_by_text("Background analysis + export")).to_be_visible()
        expect(message.get_by_text("Running", exact=True)).to_be_visible()
        expect(message.get_by_role("progressbar")).to_be_visible()
        details = message.locator('[data-generated-export-details="true"]')
        expect(message.get_by_text("File: combined-output.csv", exact=True)).to_be_hidden()
        expect(message.get_by_text("Rows: 3,000", exact=True)).to_be_hidden()
        expect(message.get_by_text("Source: large-source.csv", exact=True)).to_be_hidden()
        expect(message.get_by_text("Reduce phase level 1 node 2 of 4")).to_be_hidden()
        expect(message.get_by_text("Remaining batches: 12")).to_be_hidden()
        expect(message.get_by_text("Model concurrency: 16")).to_be_hidden()
        details.get_by_text("View details", exact=True).click()
        expect(message.get_by_text("File: combined-output.csv", exact=True)).to_be_visible()
        expect(message.get_by_text("Rows: 3,000", exact=True)).to_be_visible()
        expect(message.get_by_text("Source: large-source.csv", exact=True)).to_be_visible()
        expect(message.get_by_text("Reduce phase level 1 node 2 of 4")).to_be_visible()
        expect(message.get_by_text("Remaining batches: 12")).to_be_visible()
        expect(message.get_by_text("Remaining chunks: 12")).to_be_visible()
        expect(message.get_by_text("Estimated remaining: 2m")).to_be_visible()
        expect(message.get_by_text("Throughput: 1,200.5 rows/min")).to_be_visible()
        expect(message.get_by_text("Model concurrency: 16")).to_be_visible()
        assert page_errors == []
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_large_tabular_run_confirmation_prompt(playwright) -> None:
    """Validate repeated large-run sends share one guarded confirmation window."""
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

            result = page.evaluate(
                r"""
                async () => {
                window.appSettings = {
                    enable_tabular_durable_run_confirmation: true,
                    tabular_durable_run_confirmation_threshold_rows: 500,
                    tabular_durable_run_confirmation_threshold_batches: 75,
                    tabular_generated_output_max_batch_rows: 50,
                    enable_text_to_speech: false,
                    enable_thoughts: false,
                    documentActionCapabilities: {},
                };
                window.enable_document_classification = false;
                window.currentConversationId = 'large-tabular-confirmation-ui-test';
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

                const modalInstances = new WeakMap();
                class TestModal {
                    constructor(element) {
                        this.element = element;
                    }

                    show() {
                        this.element.classList.add('show');
                    }

                    hide() {
                        this.element.classList.remove('show');
                        this.element.dispatchEvent(new Event('hidden.bs.modal'));
                    }

                    static getOrCreateInstance(element) {
                        if (!modalInstances.has(element)) {
                            modalInstances.set(element, new TestModal(element));
                        }
                        return modalInstances.get(element);
                    }
                }
                window.bootstrap = { Modal: TestModal };

                const calls = [];
                const encoder = new TextEncoder();
                window.fetch = (url, options = {}) => {
                    const requestUrl = String(url);
                    calls.push({
                        url: requestUrl,
                        method: options.method || 'GET',
                        body: options.body || null,
                    });
                    if (requestUrl === '/api/chat/stream') {
                        const body = new ReadableStream({
                            start(controller) {
                                controller.enqueue(encoder.encode(
                                    'data: {"done":true,"conversation_id":"large-tabular-confirmation-ui-test","message_id":"assistant-ui-test","content":""}\n\n'
                                ));
                                controller.close();
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

                const module = await import('/application/single_app/static/js/chat/chat-messages.js');
                const prompt = 'For each row in 3,000 rows, answer each question and generate a CSV.';
                const input = document.getElementById('user-input');
                const smallEstimate = module.estimateLargeTabularRunForPrompt(
                    'For each row in 30 rows, generate a CSV.'
                );

                input.value = prompt;
                const firstSend = module.sendMessage();
                let repeatedSettled = false;
                await module.sendMessage().then(() => {
                    repeatedSettled = true;
                });

                const modal = document.getElementById('large-tabular-run-confirmation-modal');
                const summary = modal.querySelector('[data-large-tabular-run-summary="true"]');
                const continueButton = modal.querySelector('[data-large-tabular-run-continue="true"]');
                const firstModal = {
                    visible: modal.classList.contains('show'),
                    summary: summary.textContent,
                };

                continueButton.click();
                await firstSend;
                await new Promise(resolve => setTimeout(resolve, 100));

                const streamCallsAfterContinue = calls.filter(
                    call => call.url === '/api/chat/stream'
                ).length;
                const matchingUserMessages = Array.from(
                    document.querySelectorAll('.user-message .message-text')
                ).filter(element => element.textContent.includes(prompt)).length;

                input.value = prompt;
                const canceledSend = module.sendMessage();
                const secondModalVisible = modal.classList.contains('show');
                modal.querySelector('[data-large-tabular-run-cancel="true"]').click();
                await canceledSend;

                return {
                    smallShouldConfirm: smallEstimate.shouldConfirm,
                    repeatedSettled,
                    firstModal,
                    streamCallsAfterContinue,
                    matchingUserMessages,
                    secondModalVisible,
                    inputAfterCancel: input.value,
                    finalStreamCalls: calls.filter(
                        call => call.url === '/api/chat/stream'
                    ).length,
                };
                }
                """
            )

        assert result["smallShouldConfirm"] is False
        assert result["repeatedSettled"] is True
        assert result["firstModal"]["visible"] is True
        assert "3,000 rows" in result["firstModal"]["summary"]
        assert "60 batches" in result["firstModal"]["summary"]
        assert result["streamCallsAfterContinue"] == 1
        assert result["matchingUserMessages"] == 1
        assert result["secondModalVisible"] is True
        assert result["inputAfterCancel"] == (
            "For each row in 3,000 rows, answer each question and generate a CSV."
        )
        assert result["finalStreamCalls"] == 1
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_chat_failed_exhaustive_export_without_run_id_remains_visible(playwright) -> None:
    """Validate terminal failure metadata renders even when queue creation never produced a run."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    try:
        page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        page.evaluate(
            """
            async () => {
                const module = await import('/static/js/chat/chat-messages.js');
                window.currentConversationId = 'conversation-failed-export';
                module.appendMessage(
                    'AI',
                    'The exhaustive export could not be prepared.',
                    null,
                    'message-failed-export',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        metadata: {
                            generated_tabular_outputs: [
                                {
                                    capability: 'tabular',
                                    background_export: true,
                                    status: 'failed',
                                    status_label: 'Failed',
                                    status_tone: 'danger',
                                    status_detail: 'The source query could not be replayed. No partial CSV was created.',
                                    suppress_assistant_table_export: true,
                                    file_name: 'source_generated.json',
                                    output_format: 'json',
                                    row_count: 30000,
                                    processed_rows: 0,
                                    can_resume: false,
                                    can_cancel: false
                                }
                            ]
                        }
                    },
                    false
                );
            }
            """
        )

        message = page.locator('[data-message-id="message-failed-export"]')
        expect(message.get_by_text("Background export")).to_be_visible()
        expect(message.get_by_text("Failed", exact=True)).to_be_visible()
        expect(message.get_by_text("No partial CSV was created.")).to_be_hidden()
        message.get_by_text("View details", exact=True).click()
        expect(message.get_by_text("No partial CSV was created.")).to_be_visible()
        expect(message.get_by_role("button", name="Continue")).to_have_count(0)
        expect(message.get_by_role("button", name="Cancel background export")).to_have_count(0)
        expect(message.get_by_role("button", name="Refresh Status")).to_have_count(0)
        expect(message.get_by_role("button", name="Download JSON")).to_have_count(0)
        assert page_errors == []
    finally:
        context.close()
        browser.close()