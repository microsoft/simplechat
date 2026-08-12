# test_chat_conversation_contents_drawer.py
"""
UI test for the conversation contents drawer.
Version: 0.250.171
Implemented in: 0.250.074
Documents mode added in: 0.250.159
Compact overflow-safe layout added in: 0.250.171

This test validates user-message filtering, cited-document mode, safe labels,
navigation, live updates, conversation replacement, keyboard closing, and
responsive layouts without horizontal overflow.
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


def _require_authenticated_chat_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _assert_no_horizontal_overflow(locator, label):
    metrics = locator.evaluate(
        """
        node => ({
            scrollWidth: node.scrollWidth,
            clientWidth: node.clientWidth,
        })
        """
    )
    assert metrics["scrollWidth"] <= metrics["clientWidth"] + 1, (
        f"Expected no horizontal overflow in {label}, got "
        f"scrollWidth={metrics['scrollWidth']} and clientWidth={metrics['clientWidth']}"
    )


def _set_drawer_preference(page, enabled):
    return page.evaluate(
        """
        async (nextValue) => {
            const response = await fetch('/api/user/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    settings: {
                        conversationContentsDrawerEnabled: nextValue
                    }
                })
            });
            return response.ok;
        }
        """,
        enabled,
    )


def _get_drawer_preference(page):
    return page.evaluate(
        """
        async () => {
            const response = await fetch('/api/user/settings');
            const data = await response.json();
            return data.settings?.conversationContentsDrawerEnabled !== false;
        }
        """
    )


def _seed_contents_messages(page):
    page.evaluate(
        """
        () => {
            const chatbox = document.getElementById('chatbox');
            chatbox.replaceChildren();

            const addMessage = (role, id, text, renderedText = text) => {
                const message = document.createElement('div');
                message.className = 'message mb-2';
                message.dataset.messageId = id;
                message.dataset.conversationContentsRole = role;
                message.conversationContentsText = text;
                message.tabIndex = -1;
                message.style.minHeight = '240px';

                const messageText = document.createElement('div');
                messageText.className = 'message-text';
                messageText.textContent = renderedText;
                message.appendChild(messageText);
                chatbox.appendChild(message);
                return message;
            };

            addMessage('user', 'user-1', '# First topic\\nMore detail');
            addMessage('other', 'assistant-1', 'Assistant response');
            addMessage(
                'user',
                'user-2',
                'A very long user prompt that should be truncated without overflowing the drawer controls or changing the surrounding chat layout because it exceeds the stable label length'
            );
            addMessage('user', 'user-3', '', '');
            addMessage('user', 'temp_user_123', 'Pending message');
        }
        """
    )


@pytest.mark.ui
@pytest.mark.parametrize(
    "viewport",
    [
        {"width": 1440, "height": 900},
        {"width": 430, "height": 932},
    ],
    ids=["desktop", "mobile"],
)
def test_chat_conversation_contents_drawer(playwright, viewport):
    """Validate the complete responsive conversation contents workflow."""
    _require_authenticated_chat_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport=viewport)
    page = context.new_page()
    page_errors = []
    original_preference = True
    page.on("pageerror", lambda exception: page_errors.append(str(exception)))

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        original_preference = _get_drawer_preference(page)
        assert _set_drawer_preference(page, False)
        page.reload(wait_until="networkidle")
        expect(page.locator("#conversation-contents-toggle")).to_have_count(0)

        assert _set_drawer_preference(page, True)
        page.reload(wait_until="networkidle")
        if page.locator("#conversation-contents-toggle").count() == 0:
            pytest.skip("The admin conversation contents drawer feature gate is disabled.")

        _seed_contents_messages(page)
        toggle = page.locator("#conversation-contents-toggle")
        entries = page.locator(".conversation-contents-entry")

        expect(toggle).to_be_visible()
        expect(entries).to_have_count(3)
        expect(entries.nth(0)).to_have_text("First topic")
        expect(entries.nth(1)).to_have_text("A very long user prompt that…")
        expect(entries.nth(2)).to_have_text("User message 3")
        assert "<" not in entries.nth(0).inner_html()

        toggle.click()
        expect(page.locator("#conversation-contents-drawer")).to_be_visible()
        _assert_no_horizontal_overflow(
            page.locator("#conversation-contents-drawer .offcanvas-body"),
            "drawer body",
        )
        _assert_no_horizontal_overflow(
            page.locator("#conversation-contents-list"),
            "contents list",
        )
        _assert_no_horizontal_overflow(entries.nth(1), "contents entry")
        entries.nth(1).click()
        expect(page.locator('.message[data-message-id="user-2"]')).to_be_focused()
        page.evaluate(
            """
            () => {
                const container = document.getElementById('chat-messages-container');
                const message = document.querySelector('.message[data-message-id="user-2"]');
                container.scrollTop = message.offsetTop;
                container.dispatchEvent(new Event('scroll'));
            }
            """
        )
        expect(entries.nth(1)).to_have_attribute("aria-current", "location")
        entries.nth(1).focus()

        page.evaluate(
            """
            () => {
                const message = document.createElement('div');
                message.className = 'message';
                message.dataset.messageId = 'temp_user_456';
                message.dataset.conversationContentsRole = 'user';
                message.conversationContentsText = 'Live update topic';
                const text = document.createElement('div');
                text.className = 'message-text';
                text.textContent = 'Live update topic';
                message.appendChild(text);
                document.getElementById('chatbox').appendChild(message);
                message.dataset.messageId = 'user-4';
            }
            """
        )
        expect(entries).to_have_count(4)
        expect(entries.nth(3)).to_have_text("Live update topic")
        expect(entries.nth(1)).to_have_attribute("aria-current", "location")
        expect(entries.nth(1)).to_be_focused()

        page.evaluate(
            """
            () => {
                const chatbox = document.getElementById('chatbox');
                chatbox.replaceChildren();
                const message = document.createElement('div');
                message.className = 'message';
                message.dataset.messageId = 'next-conversation-user-1';
                message.dataset.conversationContentsRole = 'user';
                const text = document.createElement('div');
                text.className = 'message-text';
                text.textContent = 'Next conversation topic';
                message.appendChild(text);
                chatbox.appendChild(message);
            }
            """
        )
        expect(entries).to_have_count(1)
        expect(entries.nth(0)).to_have_text("Next conversation topic")

        document_title = "Policy Handbook <img src=x onerror='window.__documentsPaneXss = true'>"
        document_file_name = (
            "bank-treasury-operations-quarterly-reference-"
            "with-an-intentionally-long-filename.xlsx"
        )
        page.route(
            "**/api/conversations/conversation-documents-pane/metadata",
            lambda route: _fulfill_json(route, {
                "title": "Documents pane conversation",
                "tags": [
                    {
                        "category": "document",
                        "document_id": "doc-1",
                        "title": document_title,
                        "file_name": document_file_name,
                        "classification": "Confidential",
                        "chunk_ids": ["doc-1_1", "doc-1_2"],
                        "scope": {
                            "type": "group",
                            "id": "group-1",
                            "name": "Product Documentation Workspace With A Long Display Name",
                        },
                    },
                    {
                        "category": "document",
                        "document_id": "doc-2",
                        "title": "Release Plan",
                        "file_name": "release-plan.pdf",
                        "classification": "None",
                        "chunk_ids": ["doc-2_4"],
                        "scope": {
                            "type": "personal",
                            "id": "user-1",
                            "name": "Personal",
                        },
                    },
                ],
            }),
        )

        page.evaluate(
            """
            () => {
                window.__documentsPaneXss = false;
                window.currentConversationId = 'conversation-documents-pane';
                window.dispatchEvent(new CustomEvent('chat:conversation-documents-refresh', {
                    detail: {
                        conversationId: 'conversation-documents-pane',
                        autoOpen: true
                    }
                }));
            }
            """
        )

        documents_toggle = page.locator("#conversation-documents-toggle")
        documents_entries = page.locator(".conversation-documents-entry")
        expect(documents_toggle).to_be_visible()
        expect(page.locator("#conversation-contents-drawer")).to_be_visible()
        expect(page.locator("#conversation-contents-title")).to_have_text("Used documents")
        expect(documents_entries).to_have_count(2)
        expect(documents_entries.nth(0)).to_contain_text(document_title)
        expect(documents_entries.nth(0)).to_contain_text(document_file_name)
        expect(documents_entries.nth(0)).to_contain_text("Confidential")
        expect(documents_entries.nth(0)).to_contain_text("Pages: 1, 2")
        expect(documents_entries.nth(0)).to_contain_text(
            "group scope: Product Documentation Workspace With A Long Display Name"
        )
        expect(documents_entries.nth(0)).not_to_contain_text("chunks")
        expect(documents_entries.nth(0)).not_to_contain_text("ID:")
        expect(documents_entries.nth(1)).to_contain_text("Release Plan")
        expect(page.locator("#conversation-documents-count")).to_have_text("2")
        expect(page.locator("#conversation-documents-panel img[src='x']")).to_have_count(0)
        assert page.evaluate("() => window.__documentsPaneXss") is False
        _assert_no_horizontal_overflow(
            page.locator("#conversation-documents-list"),
            "documents list",
        )
        _assert_no_horizontal_overflow(documents_entries.nth(0), "document entry")

        page.locator("#conversation-contents-mode-contents").click()
        expect(page.locator("#conversation-contents-title")).to_have_text("Conversation contents")
        expect(page.locator("#conversation-contents-panel")).to_be_visible()
        expect(page.locator("#conversation-documents-panel")).to_be_hidden()

        toggle.click()
        page.keyboard.press("Escape")
        expect(page.locator("#conversation-contents-drawer")).to_be_hidden()
        assert not page_errors, f"Expected no uncaught page errors, got: {page_errors}"
    finally:
        _set_drawer_preference(page, original_preference)
        context.close()
        browser.close()
