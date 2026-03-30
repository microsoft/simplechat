# test_chat_scope_selector_sync.py
"""
UI test for chat scope selector synchronization.
Version: 0.239.194
Implemented in: 0.239.194

This test ensures that browser-side scope changes immediately filter chat
agent and model selectors and that conversation metadata updates render the
workspace badge without requiring a page reload.
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
def test_chat_scope_selector_sync(playwright):
    """Validate selector filtering and immediate badge updates in the chat UI."""
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

    def handle_user_settings(route):
        if route.request.method == "GET":
            _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}})
        else:
            _fulfill_json(route, {"success": True})

    def handle_test_messages(route):
        if "conversation_id=test-convo" in route.request.url:
            _fulfill_json(route, {"messages": []})
            return
        route.continue_()

    page.route("**/api/user/settings", handle_user_settings)
    page.route("**/api/get_messages?*", handle_test_messages)
    page.route(
        "**/api/conversations/test-convo/metadata",
        lambda route: _fulfill_json(
            route,
            {
                "title": "New Conversation",
                "classification": [],
                "context": [],
                "chat_type": "new",
                "scope_locked": False,
                "locked_contexts": [],
            },
        ),
    )

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="networkidle")

        page.evaluate(
            """
            async () => {
                window.userGroups = [
                    { id: 'group-a', name: 'Alpha' },
                    { id: 'group-b', name: 'Beta' },
                ];
                window.userVisiblePublicWorkspaces = [];
                window.chatAgentOptions = [
                    { id: 'personal-agent', name: 'personal_agent', display_name: 'Personal Analyst', is_global: false, is_group: false, group_id: null, group_name: null },
                    { id: 'global-agent', name: 'global_agent', display_name: 'Global Concierge', is_global: true, is_group: false, group_id: null, group_name: null },
                    { id: 'group-agent-a', name: 'group_agent_alpha', display_name: 'Alpha Agent', is_global: false, is_group: true, group_id: 'group-a', group_name: 'Alpha' },
                    { id: 'group-agent-b', name: 'group_agent_beta', display_name: 'Beta Agent', is_global: false, is_group: true, group_id: 'group-b', group_name: 'Beta' },
                ];
                window.chatModelOptions = [
                    { selection_key: 'global::endpoint-global:gpt-4o', model_id: 'gpt-4o', display_name: 'Global Model', deployment_name: 'gpt-4o-global', endpoint_id: 'endpoint-global', provider: 'aoai', scope_type: 'global', scope_id: null, scope_name: 'Global' },
                    { selection_key: 'personal:user-1:endpoint-personal:gpt-4.1-mini', model_id: 'gpt-4.1-mini', display_name: 'Personal Model', deployment_name: 'gpt-4.1-mini-personal', endpoint_id: 'endpoint-personal', provider: 'aoai', scope_type: 'personal', scope_id: 'user-1', scope_name: 'Personal' },
                    { selection_key: 'group:group-a:endpoint-alpha:gpt-4.1', model_id: 'gpt-4.1', display_name: 'Alpha Model', deployment_name: 'gpt-4.1-alpha', endpoint_id: 'endpoint-alpha', provider: 'aoai', scope_type: 'group', scope_id: 'group-a', scope_name: 'Alpha' },
                    { selection_key: 'group:group-b:endpoint-beta:gpt-4.1', model_id: 'gpt-4.1', display_name: 'Beta Model', deployment_name: 'gpt-4.1-beta', endpoint_id: 'endpoint-beta', provider: 'aoai', scope_type: 'group', scope_id: 'group-b', scope_name: 'Beta' },
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
                    modelContainer.style.display = 'block';
                }

                const documentsModule = await import('/static/js/chat/chat-documents.js');
                const agentsModule = await import('/static/js/chat/chat-agents.js');
                const modelModule = await import('/static/js/chat/chat-model-selector.js');

                await documentsModule.setEffectiveScopes(
                    {
                        personal: true,
                        groupIds: ['group-a', 'group-b'],
                        publicWorkspaceIds: [],
                    },
                    {
                        reload: false,
                        source: 'test',
                    }
                );

                await agentsModule.populateAgentDropdown();
                await modelModule.populateModelDropdown({ preserveCurrentSelection: false });
            }
            """
        )

        initial_agent_options = page.locator("#agent-select option").all_text_contents()
        initial_model_options = page.locator("#model-select option").all_text_contents()
        assert "Personal Analyst" in initial_agent_options
        assert "Global Concierge" in initial_agent_options
        assert "Alpha Agent" in initial_agent_options
        assert "Beta Agent" in initial_agent_options
        assert "Global Model" in initial_model_options
        assert "Personal Model" in initial_model_options
        assert "Alpha Model" in initial_model_options
        assert "Beta Model" in initial_model_options

        page.evaluate(
            """
            async () => {
                const documentsModule = await import('/static/js/chat/chat-documents.js');
                await documentsModule.setEffectiveScopes(
                    {
                        personal: false,
                        groupIds: ['group-a'],
                        publicWorkspaceIds: [],
                    },
                    {
                        reload: false,
                        source: 'workspace',
                    }
                );
            }
            """
        )

        page.wait_for_function(
            """
            () => {
                const agentOptions = Array.from(document.querySelectorAll('#agent-select option')).map(option => ({
                    text: option.textContent.trim(),
                    disabled: option.disabled,
                }));
                const modelOptions = Array.from(document.querySelectorAll('#model-select option')).map(option => ({
                    text: option.textContent.trim(),
                    disabled: option.disabled,
                }));

                const hasEnabledAgent = text => agentOptions.some(option => option.text === text && option.disabled === false);
                const hasDisabledAgent = text => agentOptions.some(option => option.text === text && option.disabled === true);
                const hasEnabledModel = text => modelOptions.some(option => option.text === text && option.disabled === false);
                const hasDisabledModel = text => modelOptions.some(option => option.text === text && option.disabled === true);

                return hasEnabledAgent('Alpha Agent')
                    && hasEnabledAgent('Global Concierge')
                    && hasDisabledAgent('Personal Analyst')
                    && hasDisabledAgent('Beta Agent')
                    && hasEnabledModel('Alpha Model')
                    && hasEnabledModel('Global Model')
                    && hasDisabledModel('Personal Model')
                    && hasDisabledModel('Beta Model');
            }
            """
        )

        page.evaluate("() => { window.chatConversations.addConversationToList('test-convo', 'New Conversation'); }")
        page.evaluate("() => window.chatConversations.selectConversation('test-convo')")
        page.evaluate(
            """
            async () => {
                const conversationsModule = await import('/static/js/chat/chat-conversations.js');
                conversationsModule.applyConversationMetadataUpdate('test-convo', {
                    title: 'Scoped Chat',
                    classification: [],
                    context: [
                        {
                            type: 'primary',
                            scope: 'group',
                            id: 'group-a',
                            name: 'Alpha',
                        },
                    ],
                    chat_type: 'group-single-user',
                });
            }
            """
        )

        expect(page.locator("#current-conversation-title")).to_have_text("Scoped Chat")
        expect(page.locator("#current-conversation-classifications")).to_contain_text("Alpha")
    finally:
        context.close()
        browser.close()