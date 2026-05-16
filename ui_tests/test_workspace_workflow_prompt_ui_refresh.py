# test_workspace_workflow_prompt_ui_refresh.py
"""
UI test for the workspace workflow and prompt UI refresh.
Version: 0.241.032
Implemented in: 0.241.032

This test ensures the personal workspace workflows tab uses the refreshed
workflow toolbar and card overflow menu, switches into card views, and the
prompts tab exposes list/card rendering, prompt Chat links, and the read-only
prompt view modal.
"""

import json
import os
import re
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


def _route_workflow_api(page):
    payload = {
        "workflows": [
            {
                "id": "workflow-001",
                "name": "Daily Summary",
                "description": "Build a short digest of new workspace activity.",
                "task_prompt": "Summarize the newest workflow activity.",
                "runner_type": "model",
                "trigger_type": "interval",
                "schedule": {"value": 10, "unit": "seconds"},
                "is_enabled": True,
                "model_binding_summary": {"label": "Default app model"},
                "alert_priority": "low",
                "last_run_status": "completed",
                "last_run_at": "2025-01-01T10:00:00+00:00",
                "last_run_response_preview": "Digest completed.",
                "conversation_id": "workflow-conversation-001",
                "status": "idle",
                "next_run_at": "2025-01-01T10:00:10+00:00",
            }
        ]
    }

    page.route(
        "**/api/user/workflows**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        ),
    )


def _route_prompt_api(page):
    prompt_list_payload = {
        "prompts": [
            {
                "id": "prompt-001",
                "name": "Workspace Summary",
            }
        ],
        "page": 1,
        "page_size": 10,
        "total_count": 1,
    }
    prompt_detail_payload = {
        "id": "prompt-001",
        "name": "Workspace Summary",
        "content": "Summarize the newest workflow activity in three bullets.",
    }

    def handler(route):
        url = route.request.url
        if "/api/prompts/prompt-001" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(prompt_detail_payload),
            )
            return

        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(prompt_list_payload),
        )

    page.route("**/api/prompts**", handler)


def _route_agent_api(page):
    page.route(
        "**/api/user/agents",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([]),
        ),
    )


@pytest.mark.ui
def test_workspace_workflow_prompt_ui_refresh(playwright):
    """Validate the refreshed workflows toolbar/buttons and prompt view modal."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    _route_workflow_api(page)
    _route_prompt_api(page)
    _route_agent_api(page)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")

        assert response is not None, "Expected a navigation response when loading /workspace."
        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        page.locator("#workflows-tab-btn").evaluate("button => button.click()")
        expect(page.locator("#workflows-tab")).to_be_visible()
        expect(page.locator("#workflows-tab h5")).to_have_count(0)

        new_workflow_button = page.locator("#create-workflow-btn")
        workflows_grid_toggle = page.locator("label[for='workflows-view-grid']")
        expect(new_workflow_button).to_be_visible()
        expect(workflows_grid_toggle).to_be_visible()

        new_button_box = new_workflow_button.bounding_box()
        grid_toggle_box = workflows_grid_toggle.bounding_box()
        assert new_button_box is not None and grid_toggle_box is not None
        assert new_button_box["x"] < grid_toggle_box["x"], "Expected New Workflow button to be left of the view toggle."

        workflow_row = page.locator("#workflows-table-body tr").filter(has_text="Daily Summary")
        expect(workflow_row).to_be_visible()
        expect(workflow_row.get_by_role("button", name="Run")).to_be_visible()
        expect(workflow_row.get_by_role("button", name="History")).to_be_visible()
        expect(workflow_row.get_by_role("button", name="Activity")).to_be_visible()
        expect(workflow_row.locator('button[title="Edit workflow"]')).to_be_visible()
        expect(workflow_row.locator('button[title="Delete workflow"]')).to_be_visible()

        workflows_grid_toggle.click()
        workflow_card = page.locator("#workflows-grid-view .workflow-item-card").first
        expect(workflow_card).to_be_visible()
        expect(workflow_card).to_contain_text("Daily Summary")
        expect(workflow_card.get_by_role("button", name="Run workflow")).to_be_visible()
        expect(workflow_card.get_by_role("button", name="Open activity view")).to_be_visible()
        expect(workflow_card.get_by_role("button", name="History")).to_be_hidden()

        workflow_card.get_by_role("button", name="Workflow actions").click()
        expect(page.get_by_role("button", name="History")).to_be_visible()
        expect(page.get_by_role("button", name="Edit")).to_be_visible()
        expect(page.get_by_role("button", name="Delete")).to_be_visible()
        page.keyboard.press("Escape")

        workflow_card.locator(".card-title").click()
        expect(page.locator("#workflowModal")).to_be_visible()
        expect(page.locator("#workflow-name")).to_have_value("Daily Summary")
        page.locator("#workflowModal .btn-close").click()

        page.locator("#prompts-tab-btn").evaluate("button => button.click()")
        expect(page.locator("#prompts-tab")).to_be_visible()

        prompt_row = page.locator("#prompts-table tbody tr").filter(has_text="Workspace Summary")
        expect(prompt_row).to_be_visible()
        expect(prompt_row.locator('button[title="Chat with Prompt"]')).to_be_visible()
        expect(prompt_row.locator('button[title="View Prompt"]')).to_be_visible()
        expect(prompt_row.locator('button[title="Edit Prompt"]')).to_be_visible()
        expect(prompt_row.locator('button[title="Delete Prompt"]')).to_be_visible()

        page.locator('label[for="prompts-view-grid"]').click()
        prompt_card = page.locator("#prompts-card-view .prompt-item-card").first
        expect(prompt_card).to_be_visible()
        expect(prompt_card).to_contain_text("Workspace Summary")
        expect(prompt_card.get_by_role("button", name="Chat with Prompt")).to_be_visible()
        expect(prompt_card.get_by_role("button", name="View Prompt")).to_be_visible()
        expect(prompt_card.get_by_role("button", name="Edit Prompt")).to_be_visible()
        expect(prompt_card.get_by_role("button", name="Delete Prompt")).to_be_visible()

        prompt_card.locator(".card-title").click()
        expect(page.locator("#item-view-modal")).to_be_visible()
        expect(page.locator("#item-view-modal .modal-title")).to_have_text("Prompt Details")
        expect(page.locator("#item-view-modal")).to_contain_text("Workspace Summary")
        expect(page.locator("#item-view-modal")).to_contain_text("Summarize the newest workflow activity in three bullets.")
        expect(page.locator("#item-view-modal").get_by_role("button", name="Chat")).to_be_visible()

        dialog_class = page.locator("#item-view-modal .modal-dialog").get_attribute("class") or ""
        assert "modal-lg" not in dialog_class, "Expected the prompt details modal to use the smaller dialog size."

        page.locator("#item-view-modal .btn-secondary").click()
        prompt_card.get_by_role("button", name="Chat with Prompt").click()
        expect(page).to_have_url(re.compile(r".*/chats\?(?=.*prompt_id=prompt-001)(?=.*prompt_scope=personal)(?=.*openPrompt=1).*"))
    finally:
        context.close()
        browser.close()
