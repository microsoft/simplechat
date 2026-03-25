# test_workspace_agent_views_consistency.py
"""
UI test for workspace agent view consistency.
Version: 0.239.158
Implemented in: 0.239.157

This test ensures that the personal workspace agents table uses the same
action ordering as the group workspace table and that group agent grid cards
show edit and delete actions when the current user can manage group agents.
"""

import os
import json
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


@pytest.mark.ui
def test_workspace_agent_views_consistency(playwright):
    """Validate personal table ordering and group grid management actions."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    user_agents_payload = [
        {
            "name": "researcher_agent",
            "display_name": "Researcher",
            "description": "Personal research agent",
            "is_global": False,
        }
    ]
    group_agents_payload = {
        "agents": [
            {
                "id": "group-agent-1",
                "name": "ga_ge",
                "display_name": "Ga Ge",
                "description": "A group agent using shared tools",
                "is_global": False,
            }
        ]
    }

    def handle_user_agents(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(user_agents_payload),
        )

    def handle_group_agents(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(group_agents_payload),
        )

    try:
        page.route("**/api/user/agents", handle_user_agents)
        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        page.get_by_role("tab", name="Your Agents").click()

        personal_row = page.locator("#agents-table-body tr").first
        expect(personal_row).to_be_visible()
        action_buttons = personal_row.locator("td").nth(2).locator("button")
        expect(action_buttons).to_have_count(4)
        button_classes = action_buttons.evaluate_all("elements => elements.map((element) => element.className)")
        assert "view-agent-btn" in button_classes[0]
        assert "chat-agent-btn" in button_classes[1]
        assert "edit-agent-btn" in button_classes[2]
        assert "delete-agent-btn" in button_classes[3]

        page.route("**/api/group/agents", handle_group_agents)
        page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")
        page.get_by_role("tab", name="Group Agents").click()
        page.evaluate(
            """
            () => {
                window.currentGroupStatus = 'active';
                window.groupWorkspaceContext = {
                    activeGroupId: 'test-group-1',
                    activeGroupName: 'Test Group',
                    userRole: 'Owner',
                    requireOwnerForAgentManagement: false
                };
                window.dispatchEvent(new CustomEvent('groupWorkspace:context-changed', {
                    detail: window.groupWorkspaceContext
                }));
                if (typeof window.fetchGroupAgents === 'function') {
                    return window.fetchGroupAgents();
                }
                return null;
            }
            """
        )

        page.locator("label[for='groupAgents-view-grid']").click()
        group_card = page.locator("#group-agents-grid-view .item-card").first
        expect(group_card).to_be_visible()
        expect(group_card.locator(".item-card-chat-btn")).to_be_visible()
        expect(group_card.locator(".item-card-view-btn")).to_be_visible()
        expect(group_card.locator(".item-card-edit-btn")).to_be_visible()
        expect(group_card.locator(".item-card-delete-btn")).to_be_visible()
    finally:
        context.close()
        browser.close()