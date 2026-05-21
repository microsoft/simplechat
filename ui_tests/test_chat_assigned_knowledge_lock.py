# test_chat_assigned_knowledge_lock.py
"""
UI test for chat Assigned Knowledge lock behavior.
Version: 0.241.071
Implemented in: 0.241.068

This test ensures that selecting an agent with Assigned Knowledge keeps the
assigned corpus out of the editable workspace picker, while creator-approved
user workspace context remains interactive.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_chat_assigned_knowledge_locks_document_controls():
    """Validate selected agent Assigned Knowledge controls chat document search state."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        def handle_user_settings(route):
            if route.request.method == "GET":
                _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": True}})
            else:
                _fulfill_json(route, {"success": True})

        page.route("**/api/user/settings", handle_user_settings)
        page.route("**/api/user/settings/selected_agent", lambda route: _fulfill_json(route, {"success": True}))
        page.route("**/api/documents?page_size=1000", lambda route: _fulfill_json(route, {"documents": []}))
        page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": []}))
        page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, {"documents": []}))
        page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
        page.route(
            "**/api/public_workspace_documents?page_size=1000",
            lambda route: _fulfill_json(
                route,
                {
                    "documents": [
                        {
                            "id": "public-doc",
                            "file_name": "Public Guide.pdf",
                            "title": "Public Guide",
                            "public_workspace_id": "public-1",
                            "tags": ["Finance"],
                        }
                    ]
                },
            ),
        )
        page.route(
            "**/api/public_workspace_documents/tags?*",
            lambda route: _fulfill_json(route, {"tags": [{"name": "Finance", "count": 1}]}),
        )

        try:
            page.goto(f"{BASE_URL}/chats", wait_until="networkidle")
            expect(page.locator("#agent-select")).to_be_attached()
            expect(page.locator("#search-documents-btn")).to_be_attached()

            page.evaluate(
                """
                async () => {
                    window.userGroups = [];
                    window.userVisiblePublicWorkspaces = [
                        { id: 'public-1', name: 'Public One' },
                    ];
                    window.chatAgentOptions = [
                        {
                            id: 'assigned-agent',
                            name: 'assigned_agent',
                            display_name: 'Assigned Analyst',
                            is_global: false,
                            is_group: false,
                            group_id: null,
                            group_name: null,
                            assigned_knowledge: {
                                enabled: true,
                                scopes: {
                                    personal: false,
                                    group_ids: [],
                                    public_workspace_ids: ['public-1'],
                                },
                                document_ids: ['public-doc'],
                                tags: ['Finance'],
                            },
                        },
                        {
                            id: 'open-agent',
                            name: 'open_agent',
                            display_name: 'Open Analyst',
                            is_global: false,
                            is_group: false,
                            group_id: null,
                            group_name: null,
                            assigned_knowledge: { enabled: false },
                        },
                        {
                            id: 'context-agent',
                            name: 'context_agent',
                            display_name: 'Context Analyst',
                            is_global: false,
                            is_group: false,
                            group_id: null,
                            group_name: null,
                            assigned_knowledge: {
                                enabled: true,
                                allow_user_workspace_context: true,
                                allowed_user_workspace_actions: ['search', 'analyze'],
                                scopes: {
                                    personal: false,
                                    group_ids: [],
                                    public_workspace_ids: ['public-1'],
                                },
                                document_ids: ['public-doc'],
                                tags: ['Finance'],
                            },
                        },
                    ];

                    const enableAgentsBtn = document.getElementById('enable-agents-btn');
                    const agentContainer = document.getElementById('agent-select-container');
                    const modelContainer = document.getElementById('model-select-container');
                    if (enableAgentsBtn) {
                        enableAgentsBtn.classList.add('active');
                    }
                    if (agentContainer) {
                        agentContainer.style.display = 'block';
                    }
                    if (modelContainer) {
                        modelContainer.style.display = 'none';
                    }

                    const documentsModule = await import('/static/js/chat/chat-documents.js');
                    const agentsModule = await import('/static/js/chat/chat-agents.js');
                    await documentsModule.setEffectiveScopes(
                        {
                            personal: true,
                            groupIds: [],
                            publicWorkspaceIds: [],
                        },
                        {
                            reload: false,
                            source: 'test',
                        }
                    );
                    await agentsModule.populateAgentDropdown();
                }
                """
            )

            page.select_option("#agent-select", value="personal_assigned-agent")
            page.dispatch_event("#agent-select", "change")

            page.wait_for_function(
                """
                async () => {
                    const documentsModule = await import('/static/js/chat/chat-documents.js');
                    const docSelect = document.getElementById('document-select');
                    const tagsSelect = document.getElementById('chat-tags-filter');
                    const selectedDocs = Array.from(docSelect?.selectedOptions || []).map(option => option.value);
                    const selectedTags = Array.from(tagsSelect?.selectedOptions || []).map(option => option.value);
                    return documentsModule.isAssignedKnowledgeActive()
                        && !documentsModule.isUserWorkspaceContextEnabled()
                        && document.getElementById('search-documents-btn')?.disabled === false
                        && document.getElementById('scope-dropdown-button')?.disabled === true
                        && document.getElementById('document-dropdown-button')?.disabled === true
                        && document.getElementById('tags-dropdown-button')?.disabled === true
                        && selectedDocs.length === 0
                        && selectedTags.length === 0;
                }
                """
            )

            search_button_classes = page.locator("#search-documents-btn").get_attribute("class") or ""
            assert "active" in search_button_classes
            expect(page.locator("#scope-dropdown-button")).not_to_contain_text("Public One")
            expect(page.locator("#document-dropdown-button")).not_to_contain_text("Public Guide.pdf")
            expect(page.locator("#tags-dropdown-button")).not_to_contain_text("Finance")

            page.select_option("#agent-select", value="personal_context-agent")
            page.dispatch_event("#agent-select", "change")

            page.wait_for_function(
                """
                async () => {
                    const documentsModule = await import('/static/js/chat/chat-documents.js');
                    const actions = documentsModule.getAssignedKnowledgeAllowedUserActions();
                    return documentsModule.isAssignedKnowledgeActive()
                        && !documentsModule.isUserWorkspaceContextEnabled()
                        && actions.includes('search')
                        && actions.includes('analyze')
                        && !actions.includes('compare')
                        && document.getElementById('search-documents-btn')?.disabled === false
                        && document.getElementById('scope-dropdown-button')?.disabled === false
                        && document.getElementById('document-dropdown-button')?.disabled === false
                        && document.getElementById('tags-dropdown-button')?.disabled === false;
                }
                """
            )

            page.locator("#search-documents-btn").click()
            page.wait_for_function(
                """
                async () => {
                    const documentsModule = await import('/static/js/chat/chat-documents.js');
                    return documentsModule.isAssignedKnowledgeActive()
                        && documentsModule.isUserWorkspaceContextEnabled();
                }
                """
            )
            expect(page.locator("#document-action-select option[value='comparison']")).to_be_disabled()

            page.select_option("#agent-select", value="personal_open-agent")
            page.dispatch_event("#agent-select", "change")

            page.wait_for_function(
                """
                async () => {
                    const documentsModule = await import('/static/js/chat/chat-documents.js');
                    return !documentsModule.isAssignedKnowledgeActive()
                        && document.getElementById('search-documents-btn')?.disabled === false
                        && document.getElementById('scope-dropdown-button')?.disabled === false
                        && document.getElementById('document-dropdown-button')?.disabled === false
                        && document.getElementById('tags-dropdown-button')?.disabled === false;
                }
                """
            )
        finally:
            context.close()
            browser.close()
