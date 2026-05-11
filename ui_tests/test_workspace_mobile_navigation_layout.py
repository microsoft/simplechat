# test_workspace_mobile_navigation_layout.py
"""
UI test for mobile workspace navigation layout.
Version: 0.241.012
Implemented in: 0.241.012

This test ensures that mobile top navigation uses the drawer pattern in top-nav
mode and that the responsive workspace section switcher can move between
sections while showing card-style agent views for personal and group workspaces.
"""

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
MOBILE_VIEWPORT = {"width": 430, "height": 932}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _get_user_settings(page):
    return page.evaluate(
        """
        async () => {
            const response = await fetch('/api/user/settings');
            const data = await response.json();
            return data.settings || {};
        }
        """
    )


def _set_user_settings(page, settings):
    return page.evaluate(
        """
        async (nextSettings) => {
            const response = await fetch('/api/user/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: nextSettings })
            });
            return response.ok;
        }
        """,
        settings,
    )


@pytest.mark.ui
def test_personal_workspace_mobile_drawer_and_switcher(playwright):
    """Validate the mobile drawer and section switcher in the personal workspace."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=MOBILE_VIEWPORT,
    )
    page = context.new_page()
    original_settings = None

    documents_payload = {
        "documents": [
            {
                "id": "doc-1",
                "file_name": "Quarterly Strategy.pdf",
                "title": "Quarterly Strategy",
                "percentage_complete": 100,
                "status": "Complete",
                "authors": ["Ada Lovelace"],
                "tags": ["strategy"],
                "enhanced_citations": True,
            }
        ],
        "page": 1,
        "page_size": 20,
        "total_count": 1,
        "needs_legacy_update_check": False,
    }
    agents_payload = [
        {
            "name": "research_companion",
            "display_name": "Research Companion",
            "description": "Summarizes uploaded documents and keeps a clean mobile card layout.",
            "is_global": False,
        }
    ]

    page.route(
        "**/api/documents*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(documents_payload)),
    )
    page.route(
        "**/api/user/agents",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(agents_payload)),
    )

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        original_settings = _get_user_settings(page)
        top_nav_settings = dict(original_settings)
        top_nav_settings["navLayout"] = "top"
        assert _set_user_settings(page, top_nav_settings), "Expected nav layout update to succeed."

        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")

        drawer_button = page.get_by_role("button", name="Open navigation")
        workspace_switcher = page.locator("#workspace-section-select")

        expect(drawer_button).to_be_visible()
        expect(workspace_switcher).to_be_visible()
        expect(page.locator("#workspaceTab")).to_be_hidden()

        drawer_button.click()
        mobile_drawer = page.locator("#topNavMobileMenu.show")
        expect(mobile_drawer).to_be_visible()
        expect(mobile_drawer.get_by_role("link", name="Personal")).to_be_visible()
        expect(mobile_drawer.get_by_role("link", name="Chat")).to_be_visible()
        mobile_drawer.get_by_role("button", name="Close").click()
        expect(page.locator("#topNavMobileMenu.show")).to_have_count(0)

        document_row_display = page.evaluate(
            "() => getComputedStyle(document.querySelector('#documents-table tr.document-row')).display"
        )
        assert document_row_display == "block", "Expected mobile document rows to render as stacked cards."

        if page.locator("#workspace-section-select option[value='agents-tab-btn']").count() == 0:
            pytest.skip("Personal agents are disabled in the current UI environment.")

        workspace_switcher.select_option("agents-tab-btn")
        agent_card = page.locator("#agents-grid-view .item-card").first
        expect(agent_card).to_be_visible()
        expect(page.locator("#agents-list-view")).to_have_class(re.compile(r".*d-none.*"))
    finally:
        if original_settings is not None:
            _set_user_settings(page, original_settings)
        context.close()
        browser.close()


@pytest.mark.ui
def test_group_workspace_mobile_switcher_prefers_agent_cards(playwright):
    """Validate that the group workspace switcher uses the mobile card layout for agents."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport=MOBILE_VIEWPORT,
    )
    page = context.new_page()
    original_settings = None

    group_agents_payload = {
        "agents": [
            {
                "id": "group-agent-1",
                "name": "group_researcher",
                "display_name": "Group Researcher",
                "description": "Works with shared documents and shared actions.",
                "is_global": False,
            }
        ]
    }

    page.route(
        "**/api/group/agents",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(group_agents_payload)),
    )

    try:
        page.goto(f"{BASE_URL}/group_workspaces", wait_until="domcontentloaded")
        original_settings = _get_user_settings(page)
        top_nav_settings = dict(original_settings)
        top_nav_settings["navLayout"] = "top"
        assert _set_user_settings(page, top_nav_settings), "Expected nav layout update to succeed."

        page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")

        group_switcher = page.locator("#group-workspace-section-select")
        expect(group_switcher).to_be_visible()
        expect(page.locator("#groupWorkspaceTab")).to_be_hidden()

        if page.locator("#group-workspace-section-select option[value='group-agents-tab-btn']").count() == 0:
            pytest.skip("Group agents are disabled in the current UI environment.")

        group_switcher.select_option("group-agents-tab-btn")
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

        group_card = page.locator("#group-agents-grid-view .item-card").first
        expect(group_card).to_be_visible()
        expect(page.locator("#group-agents-list-view")).to_have_class(re.compile(r".*d-none.*"))
    finally:
        if original_settings is not None:
            _set_user_settings(page, original_settings)
        context.close()
        browser.close()