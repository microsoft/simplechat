# test_chat_generated_tabular_output_card.py
"""
UI test for chat generated tabular output cards.
Version: 0.241.121
Implemented in: 0.241.121

This test ensures assistant replies with generated tabular output metadata
render a reusable export card, preserve untrusted values as text, and trigger
the chat artifact download endpoint when the user clicks the download button.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_chat_generated_tabular_output_card(playwright):
    """Validate generated tabular output cards render preview data and trigger downloads."""
    _require_ui_env()

    download_requests = []

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
        accept_downloads=True,
    )
    page = context.new_page()

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))

    def handle_generated_download(route):
        download_requests.append(route.request.url)
        route.fulfill(
            status=200,
            headers={
                "Content-Type": "application/json",
                "Content-Disposition": 'attachment; filename="comments.json"',
            },
            body=b"[]",
        )

    page.route(
        "**/api/chat_artifacts/download?conversation_id=generated-tabular-output-test&message_id=generated-export-123",
        handle_generated_download,
    )

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        page.wait_for_selector("#chatbox")
        page.wait_for_function("() => window.chatMessages && typeof window.chatMessages.appendMessage === 'function'")

        page.evaluate(
            """
            async () => {
                const conversationId = 'generated-tabular-output-test';
                currentConversationId = conversationId;
                window.currentConversationId = conversationId;

                const messagesModule = await import('/static/js/chat/chat-messages.js');

                messagesModule.appendMessage(
                    'AI',
                    'I prepared a reusable export for every comment row.',
                    null,
                    'assistant-generated-output',
                    false,
                    [],
                    [],
                    [],
                    null,
                    null,
                    {
                        id: 'assistant-generated-output',
                        role: 'assistant',
                        content: 'I prepared a reusable export for every comment row.',
                        metadata: {
                            generated_tabular_outputs: [
                                {
                                    artifact_message_id: 'generated-export-123',
                                    conversation_id: 'generated-tabular-output-test',
                                    storage_scope: 'chat',
                                    file_name: 'comments<script>alert(1)</script>.json',
                                    output_format: 'json',
                                    row_count: 124,
                                    source_file_name: 'feedback_comments.xlsx',
                                    selected_sheet: 'Comments',
                                    summary: 'The full export is saved separately so the reply can stay concise. <review>',
                                    preview_rows: [
                                        {
                                            comment_id: '001',
                                            author: 'Alicia <Admin>',
                                            comment: 'First <tag> comment',
                                        },
                                        {
                                            comment_id: '002',
                                            author: 'Ben',
                                            comment: 'Second comment',
                                        },
                                    ],
                                },
                            ],
                        },
                    },
                    true
                );
            }
            """
        )

        card = page.locator('.generated-tabular-output-card')
        expect(card).to_be_visible()
        expect(card).to_contain_text('Generated JSON export')
        expect(card).to_contain_text('Saved to this chat for download in this conversation.')
        expect(card).to_contain_text('124 rows')
        expect(card).to_contain_text('Source: feedback_comments.xlsx | Sheet: Comments')
        expect(card).to_contain_text('comments<script>alert(1)</script>.json')
        expect(card).to_contain_text('The full export is saved separately so the reply can stay concise. <review>')
        expect(card).to_contain_text('Alicia <Admin>')
        expect(card).to_contain_text('First <tag> comment')

        assert page.locator('.generated-tabular-output-card script').count() == 0

        with page.expect_download() as download_info:
            page.get_by_role('button', name='Download JSON').click()
        download = download_info.value

        assert download.suggested_filename == 'comments.json'
        assert download_requests == [
            f'{BASE_URL}/api/chat_artifacts/download?conversation_id=generated-tabular-output-test&message_id=generated-export-123'
        ]
    finally:
        context.close()
        browser.close()