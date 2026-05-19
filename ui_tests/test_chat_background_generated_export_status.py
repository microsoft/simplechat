# test_chat_background_generated_export_status.py
"""
UI test for chat background generated export status cards.
Version: 0.241.046
Implemented in: 0.241.046

This test ensures queued tabular generated exports render progress in chat and
turn into a downloadable artifact when the status API reports completion.
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
def test_chat_background_generated_export_status_card_refreshes_to_download(playwright) -> None:
    """Validate queued background generated exports show progress and completion state."""
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
        expect(message.get_by_role("button", name="Refresh Status")).to_be_visible()
        assert message.get_by_role("button", name="Download JSON").count() == 0

        message.get_by_role("button", name="Refresh Status").click()
        expect(message.get_by_role("button", name="Download JSON")).to_be_visible()
        expect(message.get_by_text("Saved to this chat for download in this conversation.")).to_be_visible()
    finally:
        context.close()
        browser.close()