# test_chat_scope_lock_and_conversation_details_escaping.py
"""
UI test for chat scope-lock and conversation-details escaping.
Version: 0.241.019
Implemented in: 0.241.019

This test ensures malicious workspace names and conversation metadata render as
inert text in the chat scope-lock modal and conversation-details modal.
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
def test_chat_scope_lock_and_conversation_details_escape_malicious_metadata(playwright):
    """Validate chat scope-lock and conversation-details metadata render as inert text."""
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

    scope_lock_name = '<img src=x onerror="window.__scopeLockXss = true"> Locked Scope'
    conversation_title = '<svg onload="window.__conversationTitleXss = true"></svg> Conversation'
    primary_context_name = '<img src=x onerror="window.__conversationContextXss = true"> Primary Context'
    participant_name = '<img src=x onerror="window.__participantNameXss = true"> Participant'
    participant_email = '<svg onload="window.__participantEmailXss = true"></svg>@example.com'
    document_title = '<img src=x onerror="window.__documentTitleXss = true"> Document'
    document_scope_name = '<img src=x onerror="window.__documentScopeXss = true"> Scope'
    classification_label = '<img src=x onerror="window.__classificationXss = true"> Secret'
    semantic_tag = '<svg onload="window.__semanticTagXss = true"></svg>Semantic'
    model_tag = '<img src=x onerror="window.__modelTagXss = true"> gpt-xss'
    agent_tag = '<svg onload="window.__agentTagXss = true"></svg>Agent'
    web_source = 'javascript:window.__webSourceXss = true'
    summary_model = '<img src=x onerror="window.__summaryModelXss = true"> summary-model'

    metadata_payload = {
        "title": conversation_title,
        "context": [
            {
                "type": "primary",
                "scope": "group",
                "id": "group-1",
                "name": primary_context_name,
            },
            {
                "type": "secondary",
                "scope": "public",
                "id": scope_lock_name,
                "name": scope_lock_name,
            },
        ],
        "tags": [
            {
                "category": "participant",
                "user_id": "user-1",
                "name": participant_name,
                "email": participant_email,
            },
            {
                "category": "document",
                "document_id": "doc-1",
                "title": document_title,
                "classification": classification_label,
                "chunk_ids": ["chunk_1_p1", "chunk_1_p2"],
                "scope": {
                    "type": "group",
                    "id": "group-1",
                    "name": document_scope_name,
                },
            },
            {
                "category": "semantic",
                "value": semantic_tag,
            },
            {
                "category": "model",
                "value": model_tag,
            },
            {
                "category": "agent",
                "value": agent_tag,
            },
            {
                "category": "web",
                "value": web_source,
            },
        ],
        "strict": False,
        "classification": [classification_label],
        "last_updated": "2026-05-05T12:00:00Z",
        "chat_type": "group-single-user",
        "is_pinned": False,
        "is_hidden": False,
        "scope_locked": True,
        "locked_contexts": [
            {"scope": "group", "id": scope_lock_name},
        ],
        "summary": {
            "content": "Safe summary text.",
            "generated_at": "2026-05-05T11:00:00Z",
            "model_deployment": summary_model,
        },
    }

    def fulfill_empty_docs_or_tags(route):
        if "/tags" in route.request.url:
            _fulfill_json(route, {"tags": []})
            return
        _fulfill_json(route, {"documents": []})

    try:
        page.route("**/api/user/settings*", lambda route: _fulfill_json(route, {"settings": {}, "selected_agent": None}))
        page.route("**/api/get_conversations*", lambda route: _fulfill_json(route, {"conversations": []}))
        page.route("**/api/documents*", fulfill_empty_docs_or_tags)
        page.route("**/api/group_documents*", fulfill_empty_docs_or_tags)
        page.route("**/api/public_workspace_documents*", fulfill_empty_docs_or_tags)
        page.route("**/api/user/profile-image/**", lambda route: route.fulfill(status=404, body=""))
        page.route(
            "**/api/conversations/conversation-xss/metadata",
            lambda route: _fulfill_json(route, metadata_payload),
        )

        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        page.wait_for_selector("#scopeLockModal")

        page.evaluate(
            """async (scopeLockName) => {
                window.__scopeLockXss = false;
                window.__conversationTitleXss = false;
                window.__conversationContextXss = false;
                window.__participantNameXss = false;
                window.__participantEmailXss = false;
                window.__documentTitleXss = false;
                window.__documentScopeXss = false;
                window.__classificationXss = false;
                window.__semanticTagXss = false;
                window.__modelTagXss = false;
                window.__agentTagXss = false;
                window.__webSourceXss = false;
                window.__summaryModelXss = false;

                const chatDocumentsModule = await import('/static/js/chat/chat-documents.js');
                chatDocumentsModule.restoreScopeLockState(true, [{ scope: 'group', id: scopeLockName }]);

                const scopeLockModal = document.getElementById('scopeLockModal');
                bootstrap.Modal.getOrCreateInstance(scopeLockModal).show();
            }""",
            scope_lock_name,
        )

        locked_list = page.locator("#locked-workspaces-list")
        expect(page.locator("#scopeLockModal")).to_be_visible()
        expect(locked_list).to_contain_text(scope_lock_name)
        expect(page.locator("#locked-workspaces-list img[src='x']")).to_have_count(0)
        expect(page.locator("#locked-workspaces-list svg")).to_have_count(0)

        page.evaluate(
            """() => {
                const scopeLockModal = bootstrap.Modal.getInstance(document.getElementById('scopeLockModal'));
                if (scopeLockModal) {
                    scopeLockModal.hide();
                }
            }"""
        )

        page.evaluate(
            """async () => {
                const detailsModule = await import('/static/js/chat/chat-conversation-details.js');
                await detailsModule.showConversationDetails('conversation-xss');
            }"""
        )

        details_modal = page.locator("#conversation-details-modal")
        details_content = page.locator("#conversation-details-content")
        expect(details_modal).to_be_visible()
        expect(page.locator("#conversation-details-modal .modal-title")).to_contain_text(conversation_title)
        expect(details_content).to_contain_text(primary_context_name)
        expect(details_content).to_contain_text(participant_name)
        expect(details_content).to_contain_text(participant_email)
        expect(details_content).to_contain_text(document_title)
        expect(details_content).to_contain_text(document_scope_name)
        expect(details_content).to_contain_text(classification_label)
        expect(details_content).to_contain_text(semantic_tag)
        expect(details_content).to_contain_text(model_tag)
        expect(details_content).to_contain_text(agent_tag)
        expect(details_content).to_contain_text(web_source)
        expect(details_content).to_contain_text(summary_model)
        expect(page.locator("#conversation-details-modal img[src='x']")).to_have_count(0)
        expect(page.locator("#conversation-details-modal svg")).to_have_count(0)
        expect(page.locator("#conversation-details-modal a[href^='javascript:']")).to_have_count(0)

        flags = page.evaluate(
            """() => ({
                scopeLock: !!window.__scopeLockXss,
                title: !!window.__conversationTitleXss,
                context: !!window.__conversationContextXss,
                participantName: !!window.__participantNameXss,
                participantEmail: !!window.__participantEmailXss,
                documentTitle: !!window.__documentTitleXss,
                documentScope: !!window.__documentScopeXss,
                classification: !!window.__classificationXss,
                semanticTag: !!window.__semanticTagXss,
                modelTag: !!window.__modelTagXss,
                agentTag: !!window.__agentTagXss,
                webSource: !!window.__webSourceXss,
                summaryModel: !!window.__summaryModelXss,
            })"""
        )
        assert flags == {
            "scopeLock": False,
            "title": False,
            "context": False,
            "participantName": False,
            "participantEmail": False,
            "documentTitle": False,
            "documentScope": False,
            "classification": False,
            "semanticTag": False,
            "modelTag": False,
            "agentTag": False,
            "webSource": False,
            "summaryModel": False,
        }
    finally:
        context.close()
        browser.close()