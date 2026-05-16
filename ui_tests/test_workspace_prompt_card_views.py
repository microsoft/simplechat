# test_workspace_prompt_card_views.py
"""
UI test for prompt list and card views across workspace scopes.
Version: 0.241.032
Implemented in: 0.241.032

This test ensures group and public workspace prompt tabs can switch from list
view to card view, expose prompt Chat actions, and open a prompt details modal
from the card surface.
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


def _route_group_workspace(page):
    page.route(
        "**/api/groups?page_size=1000",
        lambda route: _fulfill_json(
            route,
            {
                "groups": [
                    {
                        "id": "group-alpha",
                        "name": "Alpha Team",
                        "isActive": True,
                        "userRole": "Owner",
                        "status": "active",
                    }
                ]
            },
        ),
    )
    page.route(
        "**/api/group_documents?*",
        lambda route: _fulfill_json(
            route,
            {"documents": [], "page": 1, "page_size": 10, "total_count": 0},
        ),
    )
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    prompt_list_payload = {
        "prompts": [
            {
                "id": "group-prompt-001",
                "name": "Group Standup",
                "content": "Summarize shared group workspace updates.",
            }
        ],
        "page": 1,
        "page_size": 10,
        "total_count": 1,
    }
    prompt_detail_payload = prompt_list_payload["prompts"][0]

    def handle_group_prompts(route):
        if "/api/group_prompts/group-prompt-001" in route.request.url:
            _fulfill_json(route, prompt_detail_payload)
            return
        _fulfill_json(route, prompt_list_payload)

    page.route("**/api/group_prompts**", handle_group_prompts)


def _route_public_workspace(page):
    page.route(
        "**/api/public_workspaces?page_size=1000",
        lambda route: _fulfill_json(
            route,
            {
                "workspaces": [
                    {
                        "id": "public-alpha",
                        "name": "Public Alpha",
                        "isActive": True,
                        "userRole": "Owner",
                        "status": "active",
                        "description": "Public test workspace",
                        "owner": {"displayName": "Test Owner"},
                    }
                ]
            },
        ),
    )
    page.route(
        "**/api/public_workspaces/public-alpha",
        lambda route: _fulfill_json(
            route,
            {
                "id": "public-alpha",
                "name": "Public Alpha",
                "status": "active",
                "description": "Public test workspace",
                "owner": {"displayName": "Test Owner"},
            },
        ),
    )
    page.route(
        "**/api/public_documents?*",
        lambda route: _fulfill_json(
            route,
            {"documents": [], "page": 1, "page_size": 10, "total_count": 0},
        ),
    )
    page.route("**/api/public_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    prompt_list_payload = {
        "prompts": [
            {
                "id": "public-prompt-001",
                "name": "Public Release Note",
                "content": "Draft a short public workspace release update.",
            }
        ],
        "page": 1,
        "page_size": 10,
        "total_count": 1,
    }
    prompt_detail_payload = prompt_list_payload["prompts"][0]

    def handle_public_prompts(route):
        if "/api/public_prompts/public-prompt-001" in route.request.url:
            _fulfill_json(route, prompt_detail_payload)
            return
        _fulfill_json(route, prompt_list_payload)

    page.route("**/api/public_prompts**", handle_public_prompts)


@pytest.mark.ui
def test_group_and_public_prompt_card_views(playwright):
    """Validate prompt card view and card-open details behavior for shared scopes."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    _route_group_workspace(page)
    _route_public_workspace(page)

    try:
        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /group_workspaces."
        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        page.locator("#prompts-tab-btn").evaluate("button => button.click()")
        expect(page.locator("#prompts-tab")).to_be_visible()
        expect(page.locator("#group-prompts-table tbody")).to_contain_text("Group Standup")
        group_prompt_row = page.locator("#group-prompts-table tbody tr").filter(has_text="Group Standup")
        expect(group_prompt_row.locator('button[title="Chat with Prompt"]')).to_be_visible()

        page.locator('label[for="group-prompts-view-grid"]').click()
        group_prompt_card = page.locator("#group-prompts-card-view .prompt-item-card").first
        expect(group_prompt_card).to_be_visible()
        expect(group_prompt_card).to_contain_text("Group Standup")
        expect(group_prompt_card.get_by_role("button", name="Chat with Prompt")).to_be_visible()
        expect(group_prompt_card.get_by_role("button", name="View Prompt")).to_be_visible()
        group_prompt_card.locator(".card-title").click()
        expect(page.locator("#item-view-modal")).to_be_visible()
        expect(page.locator("#item-view-modal .modal-title")).to_have_text("Prompt Details")
        expect(page.locator("#item-view-modal")).to_contain_text("Summarize shared group workspace updates.")
        expect(page.locator("#item-view-modal").get_by_role("button", name="Chat")).to_be_visible()
        page.locator("#item-view-modal .btn-secondary").click()

        response = page.goto(f"{BASE_URL}/public_workspaces", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /public_workspaces."
        assert response.ok, f"Expected /public_workspaces to load successfully, got HTTP {response.status}."

        page.locator("#public-prompts-tab-btn").evaluate("button => button.click()")
        expect(page.locator("#public-prompts-tab")).to_be_visible()
        expect(page.locator("#public-prompts-table tbody")).to_contain_text("Public Release Note")
        public_prompt_row = page.locator("#public-prompts-table tbody tr").filter(has_text="Public Release Note")
        expect(public_prompt_row.locator('button[title="Chat with Prompt"]')).to_be_visible()

        page.locator('label[for="public-prompts-view-grid"]').click()
        public_prompt_card = page.locator("#public-prompts-card-view .prompt-item-card").first
        expect(public_prompt_card).to_be_visible()
        expect(public_prompt_card).to_contain_text("Public Release Note")
        expect(public_prompt_card.get_by_role("button", name="Chat with Prompt")).to_be_visible()
        expect(public_prompt_card.get_by_role("button", name="View Prompt")).to_be_visible()
        public_prompt_card.locator(".card-title").click()
        expect(page.locator("#publicPromptViewModal")).to_be_visible()
        expect(page.locator("#publicPromptViewModalLabel")).to_have_text("Prompt Details")
        expect(page.locator("#publicPromptViewModal")).to_contain_text("Draft a short public workspace release update.")
        expect(page.locator("#publicPromptViewModal").get_by_role("button", name="Chat")).to_be_visible()

        prompt_errors = [error for error in page_errors if "prompt" in error.lower()]
        assert not prompt_errors, f"Unexpected prompt UI page errors: {prompt_errors}"
    finally:
        context.close()
        browser.close()
