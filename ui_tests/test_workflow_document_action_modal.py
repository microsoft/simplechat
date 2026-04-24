# test_workflow_document_action_modal.py
"""
UI test for workflow document action modal.
Version: 0.241.072
Implemented in: 0.241.072

This test ensures the workflow modal exposes the document action selector and
submits one-left-to-many-right comparison payloads.
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


def _route_workflow_api(page, workflow_state):
    def handler(route):
        request = route.request
        if request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"workflows": workflow_state["items"]}),
            )
            return

        if request.method == "POST":
            payload = json.loads(request.post_data or "{}")
            workflow_state["saved_payloads"].append(payload)
            workflow_state["items"] = [
                {
                    "id": "workflow-compare-1",
                    "name": payload.get("name"),
                    "description": payload.get("description"),
                    "task_prompt": payload.get("task_prompt"),
                    "runner_type": payload.get("runner_type"),
                    "trigger_type": payload.get("trigger_type"),
                    "status": "idle",
                }
            ]
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({"success": True, "workflow": workflow_state["items"][0]}),
            )
            return

        route.fulfill(status=405, content_type="application/json", body=json.dumps({"error": "Unsupported"}))

    page.route("**/api/user/workflows**", handler)


def _route_agent_api(page):
    page.route(
        "**/api/user/agents",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps([])),
    )


def _open_workflows_tab(page):
    expect(page.locator("#personal-workspace-submenu [data-tab='workflows-tab']")).to_have_count(1)
    page.locator("#workflows-tab-btn").evaluate("button => button.click()")
    expect(page.locator("#workflows-tab")).to_be_visible()


@pytest.mark.ui
def test_workflow_document_action_modal_comparison(playwright):
    """Validate the workflow modal saves comparison document actions."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    workflow_state = {"items": [], "saved_payloads": []}

    _route_workflow_api(page, workflow_state)
    _route_agent_api(page)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /workspace to load successfully."

        _open_workflows_tab(page)

        page.get_by_role("button", name="New Workflow").click()
        expect(page.locator("#workflowModal")).to_be_visible()

        page.fill("#workflow-name", "Compare Contract Baseline")
        page.fill("#workflow-task-prompt", "Compare the baseline contract against the latest amendments.")
        page.select_option("#workflow-document-action-type", "comparison")

        expect(page.locator("#workflow-comparison-target-fields")).to_be_visible()
        expect(page.locator("#workflow-exhaustive-target-fields")).to_be_hidden()

        page.fill("#workflow-comparison-left-document-id", "baseline-doc")
        page.fill("#workflow-comparison-right-document-ids", "amendment-a, amendment-b")
        page.click("#workflow-save-btn")

        assert workflow_state["saved_payloads"], "Expected the workflow save handler to capture the modal payload."
        saved_payload = workflow_state["saved_payloads"][0]
        assert saved_payload["document_action"]["type"] == "comparison"
        assert saved_payload["document_action"]["left_document_id"] == "baseline-doc"
        assert saved_payload["document_action"]["right_document_ids"] == ["amendment-a", "amendment-b"]
        assert saved_payload["exhaustive_review"]["enabled"] is False
    finally:
        context.close()
        browser.close()