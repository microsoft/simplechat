# test_chat_background_generated_export_status.py
"""
UI test for chat background generated export status cards.
Version: 0.250.061
Implemented in: 0.241.046; cancellation in 0.250.060; automatic-only refresh in 0.250.061

This test ensures queued tabular generated exports render progress in chat and
turn into a downloadable artifact when complete or a visible canceled state.
"""

import os
from pathlib import Path

import pytest


playwright_sync_api = pytest.importorskip("playwright.sync_api")
expect = playwright_sync_api.expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


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
                    'The large export is continuing in the background.',
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
                                    source_file_name: 'query_data.xlsx'
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
        expect(message.get_by_text("Background export")).to_be_visible()
        expect(message.get_by_text("Running")).to_be_visible()
        expect(message.get_by_text("298 of 1,592 batches")).to_be_visible()
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
        expect(message.get_by_text("No partial CSV was created.")).to_be_visible()
        expect(message.get_by_role("button", name="Continue")).to_have_count(0)
        expect(message.get_by_role("button", name="Cancel background export")).to_have_count(0)
        expect(message.get_by_role("button", name="Refresh Status")).to_have_count(0)
        expect(message.get_by_role("button", name="Download JSON")).to_have_count(0)
        assert page_errors == []
    finally:
        context.close()
        browser.close()