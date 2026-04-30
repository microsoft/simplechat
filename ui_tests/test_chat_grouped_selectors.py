# test_chat_grouped_selectors.py
"""
UI test for grouped chat selectors.
Version: 0.239.197
Implemented in: 0.239.197

This test ensures that prompt and document selectors render grouped headers,
keep matching headers visible during search, and that agent/model selectors
disable out-of-scope options during new conversations before hiding them once
the conversation scope is locked.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _visible_texts(locator):
    return locator.evaluate_all(
        "elements => elements.filter(element => !element.classList.contains('d-none')).map(element => element.textContent.trim())"
    )


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_chat_grouped_selectors(playwright):
    """Validate grouped selector headers, search retention, and scoped option disabling."""
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

    def handle_user_settings(route):
        if route.request.method == "GET":
            _fulfill_json(route, user_settings_payload)
            return

        if route.request.method == "POST":
            post_data = json.loads(route.request.post_data or "{}")
            user_settings_payload["settings"].update(post_data)
            _fulfill_json(route, {"success": True})
            return

        route.continue_()

    def handle_selected_agent(route):
        payload = json.loads(route.request.post_data or "{}")
        user_settings_payload["selected_agent"] = payload.get("selected_agent")
        _fulfill_json(route, {"success": True})

    personal_docs_payload = {
        "documents": [
            {
                "id": "personal-doc-1",
                "title": "Personal Brief",
                "file_name": "personal-brief.md",
                "tags": [],
                "document_classification": "",
            }
        ]
    }
    group_docs_payload = {
        "documents": [
            {
                "id": "group-doc-a",
                "title": "Alpha Plan",
                "file_name": "alpha-plan.md",
                "group_id": "group-a",
                "tags": [],
                "document_classification": "",
            },
            {
                "id": "group-doc-b",
                "title": "Beta Notes",
                "file_name": "beta-notes.md",
                "group_id": "group-b",
                "tags": [],
                "document_classification": "",
            },
        ]
    }
    public_docs_payload = {
        "documents": [
            {
                "id": "public-doc-a",
                "title": "Shared Policy",
                "file_name": "shared-policy.md",
                "public_workspace_id": "public-a",
                "tags": [],
                "document_classification": "",
            }
        ]
    }

    page.route("**/api/user/settings", handle_user_settings)
    page.route("**/api/user/settings/selected_agent", handle_selected_agent)
    page.route("**/api/documents?page_size=1000", lambda route: _fulfill_json(route, personal_docs_payload))
    page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, group_docs_payload))
    page.route("**/api/public_workspace_documents?page_size=1000", lambda route: _fulfill_json(route, public_docs_payload))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))
    page.route("**/api/public_workspace_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="networkidle")

        page.evaluate(
            """
            async () => {
                window.userGroups = [
                    { id: 'group-a', name: 'Alpha' },
                    { id: 'group-b', name: 'Beta' },
                ];
                window.userVisiblePublicWorkspaces = [
                    { id: 'public-a', name: 'Shared Docs' },
                ];
                window.chatPromptOptions = [
                    { id: 'prompt-personal', name: 'Personal Kickoff', content: 'Personal prompt', scope_type: 'personal', scope_id: 'user-1', scope_name: 'Personal' },
                    { id: 'prompt-group-a', name: 'Alpha Prompt', content: 'Alpha prompt', scope_type: 'group', scope_id: 'group-a', scope_name: 'Alpha' },
                    { id: 'prompt-group-b', name: 'Beta Prompt', content: 'Beta prompt', scope_type: 'group', scope_id: 'group-b', scope_name: 'Beta' },
                    { id: 'prompt-public-a', name: 'Shared Prompt', content: 'Shared prompt', scope_type: 'public', scope_id: 'public-a', scope_name: 'Shared Docs' },
                ];
                window.chatAgentOptions = [
                    { id: 'global-agent', name: 'global_agent', display_name: 'Global Concierge', is_global: true, is_group: false, group_id: null, group_name: null },
                    { id: 'personal-agent', name: 'personal_agent', display_name: 'Personal Analyst', is_global: false, is_group: false, group_id: null, group_name: null },
                    { id: 'group-agent-a', name: 'group_agent_alpha', display_name: 'Alpha Agent', is_global: false, is_group: true, group_id: 'group-a', group_name: 'Alpha' },
                    { id: 'group-agent-b', name: 'group_agent_beta', display_name: 'Beta Agent', is_global: false, is_group: true, group_id: 'group-b', group_name: 'Beta' },
                ];
                window.chatModelOptions = [
                    { selection_key: 'global::endpoint-global:gpt-4o', model_id: 'gpt-4o', display_name: 'Global Model', deployment_name: 'gpt-4o-global', endpoint_id: 'endpoint-global', provider: 'aoai', scope_type: 'global', scope_id: null, scope_name: 'Global' },
                    { selection_key: 'personal:user-1:endpoint-personal:gpt-4.1-mini', model_id: 'gpt-4.1-mini', display_name: 'Personal Model', deployment_name: 'gpt-4.1-mini-personal', endpoint_id: 'endpoint-personal', provider: 'aoai', scope_type: 'personal', scope_id: 'user-1', scope_name: 'Personal' },
                    { selection_key: 'group:group-a:endpoint-alpha:gpt-4.1', model_id: 'gpt-4.1', display_name: 'Alpha Model', deployment_name: 'gpt-4.1-alpha', endpoint_id: 'endpoint-alpha', provider: 'aoai', scope_type: 'group', scope_id: 'group-a', scope_name: 'Alpha' },
                    { selection_key: 'group:group-b:endpoint-beta:gpt-4.1', model_id: 'gpt-4.1', display_name: 'Beta Model', deployment_name: 'gpt-4.1-beta', endpoint_id: 'endpoint-beta', provider: 'aoai', scope_type: 'group', scope_id: 'group-b', scope_name: 'Beta' },
                ];

                window.appSettings = {
                    ...(window.appSettings || {}),
                    enable_multi_model_endpoints: true,
                };

                const documentsModule = await import('/static/js/chat/chat-documents.js');
                const modelModule = await import('/static/js/chat/chat-model-selector.js');

                await documentsModule.setEffectiveScopes(
                    {
                        personal: true,
                        groupIds: ['group-a', 'group-b'],
                        publicWorkspaceIds: ['public-a'],
                    },
                    {
                        source: 'test',
                    }
                );

                await modelModule.populateModelDropdown({ preserveCurrentSelection: false });
            }
            """
        )

        page.get_by_role("button", name="Prompts").click()
        page.locator("#prompt-dropdown-button").click()

        prompt_headers = _visible_texts(page.locator("#prompt-dropdown-items .dropdown-header"))
        assert "Personal" in prompt_headers
        assert "[Group] Alpha" in prompt_headers
        assert "[Group] Beta" in prompt_headers
        assert "[Public] Shared Docs" in prompt_headers

        prompt_items = _visible_texts(page.locator("#prompt-dropdown-items .chat-searchable-select-item .chat-searchable-select-item-text"))
        assert "Alpha Prompt" in prompt_items
        assert "[Group] Alpha Alpha Prompt" not in prompt_items

        page.locator("#prompt-search-input").fill("Alpha")
        filtered_prompt_headers = _visible_texts(page.locator("#prompt-dropdown-items .dropdown-header"))
        assert filtered_prompt_headers == ["[Group] Alpha"]
        page.keyboard.press("Escape")

        page.get_by_role("button", name="Files").click()
        page.locator("#document-dropdown-button").click()

        document_headers = _visible_texts(page.locator("#document-dropdown-items .dropdown-header"))
        assert "Personal" in document_headers
        assert "[Group] Alpha" in document_headers
        assert "[Group] Beta" in document_headers
        assert "[Public] Shared Docs" in document_headers

        document_labels = _visible_texts(page.locator("#document-dropdown-items .dropdown-item span"))
        assert "Alpha Plan" in document_labels
        assert "[Group: Alpha] Alpha Plan" not in document_labels
        page.keyboard.press("Escape")

        page.get_by_role("button", name="Agents").click()
        page.locator("#agent-dropdown-button").click()
        page.locator("#agent-dropdown-items .chat-searchable-select-item", has_text="Alpha Agent").click()

        page.wait_for_function(
            """
            () => {
                const clearAction = document.querySelector('[data-agent-scope-action-container="true"]');
                const betaAgent = Array.from(document.querySelectorAll('#agent-select option')).find(option => option.textContent.trim() === 'Beta Agent');
                const betaModel = Array.from(document.querySelectorAll('#model-select option')).find(option => option.textContent.trim() === 'Beta Model');
                return clearAction && !clearAction.classList.contains('d-none') && betaAgent?.disabled === true && betaModel?.disabled === true;
            }
            """
        )

        page.locator("#agent-dropdown-button").click()
        expect(page.locator("[data-agent-scope-action-container='true']")).to_be_visible()
        beta_agent_disabled = page.locator("#agent-dropdown-items .chat-searchable-select-item", has_text="Beta Agent").evaluate("element => element.disabled")
        assert beta_agent_disabled is True
        page.keyboard.press("Escape")

        page.locator("#model-dropdown-button").click()
        expect(page.locator("[data-model-scope-action-container='true']")).to_be_visible()
        beta_model_disabled = page.locator("#model-dropdown-items .chat-searchable-select-item", has_text="Beta Model").evaluate("element => element.disabled")
        assert beta_model_disabled is True
        page.keyboard.press("Escape")

        page.evaluate(
            """
            async () => {
                document.querySelectorAll('.conversation-item.active').forEach(item => item.classList.remove('active'));

                const activeConversation = document.createElement('button');
                activeConversation.type = 'button';
                activeConversation.className = 'conversation-item active';
                activeConversation.setAttribute('data-chat-type', 'group');
                activeConversation.setAttribute('data-chat-state', 'existing');
                activeConversation.setAttribute('data-group-id', 'group-a');
                document.body.appendChild(activeConversation);

                const agentsModule = await import('/static/js/chat/chat-agents.js');
                const modelModule = await import('/static/js/chat/chat-model-selector.js');

                await agentsModule.populateAgentDropdown();
                await modelModule.populateModelDropdown({ preserveCurrentSelection: true });
            }
            """
        )

        page.wait_for_function(
            """
            () => {
                const hasBetaAgent = Array.from(document.querySelectorAll('#agent-select option')).some(option => option.textContent.trim() === 'Beta Agent');
                const hasBetaModel = Array.from(document.querySelectorAll('#model-select option')).some(option => option.textContent.trim() === 'Beta Model');
                const agentClearAction = document.querySelector('[data-agent-scope-action-container="true"]');
                const modelClearAction = document.querySelector('[data-model-scope-action-container="true"]');
                return !hasBetaAgent
                    && !hasBetaModel
                    && (!agentClearAction || agentClearAction.classList.contains('d-none'))
                    && (!modelClearAction || modelClearAction.classList.contains('d-none'));
            }
            """
        )

        page.locator("#agent-dropdown-button").click()
        expect(page.locator("[data-agent-scope-action-container='true']")).to_be_hidden()
        assert page.locator("#agent-dropdown-items .chat-searchable-select-item", has_text="Beta Agent").count() == 0
        page.keyboard.press("Escape")

        page.locator("#model-dropdown-button").click()
        expect(page.locator("[data-model-scope-action-container='true']")).to_be_hidden()
        assert page.locator("#model-dropdown-items .chat-searchable-select-item", has_text="Beta Model").count() == 0
    finally:
        context.close()
        browser.close()