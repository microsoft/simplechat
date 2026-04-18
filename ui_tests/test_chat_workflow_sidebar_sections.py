# test_chat_workflow_sidebar_sections.py
"""
UI test for chat workflow sidebar sections.
Version: 0.241.036
Implemented in: 0.241.036

This test ensures the chat sidebar keeps using the standard conversations API,
renders workflow conversations only in the dedicated Workflows section,
defaults that section to five items, and lets the shared sidebar search find
workflow conversations through a dedicated collapsible scrollable menu aligned
with the other sidebar headers.
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
def test_chat_workflow_sidebar_sections(playwright):
    """Validate workflow chats render in their own sidebar section without a new API."""
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

    workflow_conversations = [
        {
            "id": f"workflow-convo-{index}",
            "title": f"Workflow: Daily Summary {index}",
            "last_updated": f"2026-04-17T10:{index:02d}:00Z",
            "classification": [],
            "context": [],
            "chat_type": "workflow",
            "is_pinned": False,
            "is_hidden": False,
            "has_unread_assistant_response": False,
        }
        for index in range(1, 8)
    ]
    conversations_payload = {
        "conversations": [
            {
                "id": "conversation-standard-1",
                "title": "Product Discussion",
                "last_updated": "2026-04-17T12:10:00Z",
                "classification": [],
                "context": [],
                "chat_type": "personal_single_user",
                "is_pinned": False,
                "is_hidden": False,
                "has_unread_assistant_response": False,
            },
            {
                "id": "conversation-standard-2",
                "title": "Incident Follow-up",
                "last_updated": "2026-04-17T12:05:00Z",
                "classification": [],
                "context": [],
                "chat_type": "personal_single_user",
                "is_pinned": False,
                "is_hidden": False,
                "has_unread_assistant_response": False,
            },
            *workflow_conversations,
        ]
    }

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, conversations_payload))
    page.route("**/api/collaboration/conversations?*", lambda route: _fulfill_json(route, []))

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")

        regular_list = page.locator("#sidebar-conversations-list")
        workflow_section = page.locator("#sidebar-workflow-section")
        workflows_menu_toggle = page.locator("#sidebar-workflows-toggle")
        workflow_list_container = page.locator("#sidebar-workflow-list-container")
        workflow_list = page.locator("#sidebar-workflow-conversations-list")
        workflow_toggle = page.locator("#sidebar-workflow-show-more-btn")

        page.wait_for_function(
            """
            () => {
                const regularItems = document.querySelectorAll('#sidebar-conversations-list .sidebar-conversation-item').length;
                const workflowItems = document.querySelectorAll('#sidebar-workflow-conversations-list .sidebar-conversation-item').length;
                return regularItems === 2 && workflowItems === 5;
            }
            """
        )

        expect(regular_list).to_contain_text("Product Discussion")
        expect(regular_list).to_contain_text("Incident Follow-up")
        expect(regular_list).not_to_contain_text("Workflow: Daily Summary 1")
        expect(workflow_section).to_be_visible()
        expect(workflows_menu_toggle).to_contain_text("Workflows")
        expect(workflow_list).to_contain_text("Workflow: Daily Summary 1")
        expect(workflow_list).to_contain_text("Workflow: Daily Summary 5")
        expect(workflow_list).not_to_contain_text("Workflow: Daily Summary 6")
        expect(workflow_toggle).to_be_visible()

        workflows_menu_toggle.click()
        expect(workflow_list_container).to_be_hidden()
        expect(workflows_menu_toggle).to_have_attribute("aria-expanded", "false")

        workflows_menu_toggle.click()
        expect(workflow_list_container).to_be_visible()
        expect(workflows_menu_toggle).to_have_attribute("aria-expanded", "true")

        workflow_toggle.click()
        page.wait_for_function(
            """
            () => document.querySelectorAll('#sidebar-workflow-conversations-list .sidebar-conversation-item').length === 7
            """
        )
        expect(workflow_list).to_contain_text("Workflow: Daily Summary 7")

        page.locator("#sidebar-search-btn").click()
        expect(page.locator("#sidebar-search-container")).to_be_visible()
        page.locator("#sidebar-search-input").fill("Daily Summary 7")

        page.wait_for_function(
            """
            () => {
                const regularText = document.getElementById('sidebar-conversations-list')?.textContent || '';
                const workflowItems = document.querySelectorAll('#sidebar-workflow-conversations-list .sidebar-conversation-item').length;
                const workflowText = document.getElementById('sidebar-workflow-conversations-list')?.textContent || '';
                return regularText.includes('No matching standard conversations.')
                    && workflowItems === 1
                    && workflowText.includes('Workflow: Daily Summary 7');
            }
            """
        )

        expect(regular_list).not_to_contain_text("Product Discussion")
        expect(workflow_list).to_contain_text("Workflow: Daily Summary 7")
        expect(workflow_list).not_to_contain_text("Workflow: Daily Summary 6")
        expect(workflow_toggle).to_be_hidden()
    finally:
        context.close()
        browser.close()