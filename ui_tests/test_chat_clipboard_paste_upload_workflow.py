# test_chat_clipboard_paste_upload_workflow.py
"""
UI test for chat clipboard paste upload support.
Version: 0.241.056
Implemented in: 0.241.056

This test ensures that pasting a clipboard image into the main chat input
routes the file through the existing upload flow, auto-creates a conversation,
normalizes an empty clipboard filename, preserves later text paste events, and
uploads dropped files through the same chat flow.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_chat_paste_uploads_clipboard_image_with_normalized_filename(playwright):
    """Validate that pasting a nameless clipboard image uploads it through chat upload flow."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    user_settings_payload = {
        "selected_agent": None,
        "settings": {
            "enable_agents": False,
        },
    }
    created_conversation_id = "clipboard-conversation-1"
    create_conversation_calls = []

    def handle_user_settings(route):
        if route.request.method == "GET":
            _fulfill_json(route, user_settings_payload)
            return

        if route.request.method == "POST":
            _fulfill_json(route, {"success": True})
            return

        route.continue_()

    def handle_create_conversation(route):
        create_conversation_calls.append(route.request.url)
        _fulfill_json(
            route,
            {
                "conversation_id": created_conversation_id,
                "title": "Clipboard Upload Conversation",
            },
        )

    def handle_get_conversations(route):
        _fulfill_json(
            route,
            {
                "conversations": [
                    {
                        "id": created_conversation_id,
                        "title": "Clipboard Upload Conversation",
                        "last_updated": "2026-05-05T12:00:00Z",
                        "context": [],
                        "tags": [],
                        "strict": False,
                    }
                ]
            },
        )

    page.add_init_script(
        """
        (() => {
            const originalFetch = window.fetch.bind(window);
            window.__uploadCapture = [];

            window.fetch = async (input, init = {}) => {
                const requestUrl = typeof input === 'string' ? input : (input && input.url) || '';
                if (requestUrl.endsWith('/upload') && init && init.body instanceof FormData) {
                    const file = init.body.get('file');
                    window.__uploadCapture.push({
                        url: requestUrl,
                        conversationId: String(init.body.get('conversation_id') || ''),
                        fileName: file ? String(file.name || '') : '',
                        fileType: file ? String(file.type || '') : '',
                    });
                }

                return originalFetch(input, init);
            };
        })();
        """
    )

    page.route("**/api/user/settings", handle_user_settings)
    page.route("**/api/get_conversations", handle_get_conversations)
    page.route("**/api/create_conversation", handle_create_conversation)
    page.route("**/api/documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/public_workspace_documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/public_workspace_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/conversation/*/messages?*", lambda route: _fulfill_json(route, {"messages": []}))
    page.route(
        "**/upload",
        lambda route: _fulfill_json(
            route,
            {
                "conversation_id": created_conversation_id,
                "title": "Clipboard Upload Conversation",
            },
        ),
    )

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="networkidle")

        expect(page.locator("#user-input")).to_be_visible()
        upload_enabled = page.evaluate("() => window.appSettings?.enable_chat_file_uploads === true")
        if not upload_enabled:
            pytest.skip("Chat file uploads are disabled for the authenticated UI test user.")

        page.locator("#user-input").evaluate(
            """
            (element) => {
                const clipboardImage = new File(
                    [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])],
                    '',
                    { type: 'image/png' }
                );
                const pasteEvent = new Event('paste', { bubbles: true, cancelable: true });
                Object.defineProperty(pasteEvent, 'clipboardData', {
                    value: {
                        items: [
                            {
                                kind: 'file',
                                getAsFile: () => clipboardImage,
                            },
                        ],
                        files: [clipboardImage],
                    },
                });

                element.dispatchEvent(pasteEvent);
            }
            """
        )

        page.wait_for_function("() => Array.isArray(window.__uploadCapture) && window.__uploadCapture.length === 1")
        page.wait_for_function(
            """
            () => {
                const buttonText = document.querySelector('#choose-file-btn .file-btn-text');
                return buttonText && buttonText.textContent.trim() === 'File';
            }
            """
        )

        upload_capture = page.evaluate("() => window.__uploadCapture")
        assert len(create_conversation_calls) == 1, "Expected paste upload to create a single conversation."
        assert len(upload_capture) == 1, "Expected exactly one upload request from paste flow."
        assert upload_capture[0]["conversationId"] == created_conversation_id
        assert upload_capture[0]["fileType"] == "image/png"
        assert upload_capture[0]["fileName"].startswith("pasted_file_")
        assert upload_capture[0]["fileName"].endswith(".png")

        text_paste_result = page.locator("#user-input").evaluate(
            """
            async (element) => {
                const staleClipboardImage = new File(
                    [new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])],
                    '',
                    { type: 'image/png' }
                );
                const pasteEvent = new Event('paste', { bubbles: true, cancelable: true });
                Object.defineProperty(pasteEvent, 'clipboardData', {
                    value: {
                        getData: (type) => type === 'text/plain' || type === 'Text'
                            ? 'normal text after image paste'
                            : '',
                        items: [
                            {
                                kind: 'string',
                                type: 'text/plain',
                            },
                            {
                                kind: 'file',
                                type: 'image/png',
                                getAsFile: () => staleClipboardImage,
                            },
                        ],
                        files: [staleClipboardImage],
                    },
                });

                element.dispatchEvent(pasteEvent);
                await Promise.resolve();
                await new Promise((resolve) => requestAnimationFrame(resolve));

                return {
                    defaultPrevented: pasteEvent.defaultPrevented,
                    uploadCount: window.__uploadCapture.length,
                };
            }
            """
        )
        assert text_paste_result["defaultPrevented"] is False
        assert text_paste_result["uploadCount"] == 1

        page.locator("#user-input").evaluate(
            """
            (element) => {
                const droppedFile = new File(['dropped notes'], 'drop-notes.txt', { type: 'text/plain' });
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(droppedFile);
                const dropEvent = new DragEvent('drop', {
                    bubbles: true,
                    cancelable: true,
                    dataTransfer,
                });

                element.dispatchEvent(dropEvent);
            }
            """
        )

        page.wait_for_function("() => Array.isArray(window.__uploadCapture) && window.__uploadCapture.length === 2")
        upload_capture = page.evaluate("() => window.__uploadCapture")
        assert upload_capture[1]["conversationId"] == created_conversation_id
        assert upload_capture[1]["fileName"] == "drop-notes.txt"
        assert upload_capture[1]["fileType"] == "text/plain"

        expect(page.locator("#current-conversation-title")).to_have_text("Clipboard Upload Conversation")
    finally:
        context.close()
        browser.close()