# test_workspace_workflows_tab.py
"""
UI test for personal workflows workspace tab.
Version: 0.241.036
Implemented in: 0.241.029

This test ensures the personal workspace workflows tab renders the left-hand
menu entry, shows workflow rows, opens run history with direct workflow
conversation links, and submits new agent-based interval workflows with alert
priorities from the modal on desktop and mobile viewports.
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


def _build_workflow_state():
    return {
        "items": [
            {
                "id": "workflow-model-1",
                "name": "Daily Summary",
                "description": "Build a short digest of new workspace activity.",
                "task_prompt": "Summarize new activity from the last run.",
                "runner_type": "model",
                "trigger_type": "interval",
                "schedule": {"value": 10, "unit": "seconds"},
                "is_enabled": True,
                "model_binding_summary": {"label": "Default app model"},
                "alert_priority": "low",
                "last_run_status": "completed",
                "last_run_at": "2025-01-01T10:00:00+00:00",
                "last_run_response_preview": "Digest completed.",
                "conversation_id": "conv-123",
                "status": "idle",
                "next_run_at": "2025-01-01T10:00:10+00:00",
            },
            {
                "id": "workflow-agent-1",
                "name": "Research Agent Sweep",
                "description": "Ask the personal research agent to inspect the newest documents.",
                "task_prompt": "Inspect the latest documents and call out high-priority changes.",
                "runner_type": "agent",
                "trigger_type": "manual",
                "is_enabled": True,
                "alert_priority": "none",
                "selected_agent": {
                    "id": "agent-1",
                    "name": "researcher_agent",
                    "display_name": "Researcher",
                    "is_global": False,
                },
                "last_run_status": "failed",
                "last_run_error": "API unavailable",
                "status": "idle",
            },
        ],
        "saved_payloads": [],
    }


def _route_workflow_api(page, workflow_state):
    def handler(route):
        request = route.request
        url = request.url
        method = request.method

        if url.endswith("/runs") and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "workflow_id": "workflow-model-1",
                        "runs": [
                            {
                                "status": "completed",
                                "started_at": "2025-01-01T10:00:00+00:00",
                                "completed_at": "2025-01-01T10:00:02+00:00",
                                "trigger_source": "manual",
                                "conversation_id": "conv-123",
                                "response_preview": "Digest completed.",
                            }
                        ],
                    }
                ),
            )
            return

        if method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"workflows": workflow_state["items"]}),
            )
            return

        if method == "POST":
            payload = json.loads(request.post_data or "{}")
            workflow_state["saved_payloads"].append(payload)
            saved_workflow = {
                "id": "workflow-agent-new",
                "name": payload.get("name"),
                "description": payload.get("description"),
                "task_prompt": payload.get("task_prompt"),
                "runner_type": payload.get("runner_type"),
                "trigger_type": payload.get("trigger_type"),
                "schedule": payload.get("schedule", {}),
                "is_enabled": payload.get("is_enabled", True),
                "selected_agent": payload.get("selected_agent", {}),
                "status": "idle",
                "last_run_status": None,
            }
            workflow_state["items"] = [saved_workflow, *workflow_state["items"]]
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({"success": True, "workflow": saved_workflow}),
            )
            return

        route.fulfill(status=405, content_type="application/json", body=json.dumps({"error": "Unsupported"}))

    page.route("**/api/user/workflows**", handler)


def _route_agent_api(page):
    def handler(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                [
                    {
                        "id": "agent-1",
                        "name": "researcher_agent",
                        "display_name": "Researcher",
                        "description": "Personal research agent",
                        "is_global": False,
                    }
                ]
            ),
        )

    page.route("**/api/user/agents", handler)


def _open_workflows_tab(page):
    expect(page.locator("#personal-workspace-submenu [data-tab='workflows-tab']")).to_have_count(1)
    page.locator("#workflows-tab-btn").evaluate("button => button.click()")
    expect(page.locator("#workflows-tab")).to_be_visible()


@pytest.mark.ui
def test_workspace_workflows_tab_desktop(playwright):
    """Validate workflow listing, history, and modal submission on desktop."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    workflow_state = _build_workflow_state()

    _route_workflow_api(page, workflow_state)
    _route_agent_api(page)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")

        assert response is not None, "Expected a navigation response when loading /workspace."
        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        _open_workflows_tab(page)

        summary_row = page.locator("#workflows-table-body tr").filter(has_text="Daily Summary")
        expect(summary_row).to_be_visible()
        expect(summary_row).to_contain_text("Default app model")
        expect(summary_row).to_contain_text("Every 10 seconds")
        expect(summary_row).to_contain_text("Alert: Low priority")
        expect(summary_row).to_contain_text("Digest completed.")

        summary_row.get_by_role("button", name="History").click()
        expect(page.locator("#workflowHistoryModal")).to_be_visible()
        expect(page.locator("#workflow-history-conversation-id")).to_contain_text("conv-123")
        expect(page.locator("#workflow-history-open-conversation-link")).to_have_attribute("href", "/chats?conversationId=conv-123")
        expect(page.locator("#workflow-history-body")).to_contain_text("Digest completed.")
        expect(page.locator("#workflow-history-body a", has_text="Open workflow conversation")).to_have_attribute("href", "/chats?conversationId=conv-123")
        page.locator("#workflowHistoryModal .btn-secondary").click()

        page.get_by_role("button", name="New Workflow").click()
        expect(page.locator("#workflowModal")).to_be_visible()
        page.fill("#workflow-name", "Ten Second Agent Sweep")
        page.fill("#workflow-description", "Runs the personal research agent every ten seconds.")
        page.fill("#workflow-task-prompt", "Check the latest workspace updates.")
        page.select_option("#workflow-runner-type", "agent")
        expect(page.locator("#workflow-agent-select option")).to_have_count(1)
        page.select_option("#workflow-trigger-type", "interval")
        page.fill("#workflow-schedule-value", "10")
        page.select_option("#workflow-schedule-unit", "seconds")
        page.select_option("#workflow-alert-priority", "high")
        page.click("#workflow-save-btn")

        expect(page.locator("#workflows-table-body")).to_contain_text("Ten Second Agent Sweep")
        assert workflow_state["saved_payloads"], "Expected the save handler to capture the new workflow payload."
        saved_payload = workflow_state["saved_payloads"][0]
        assert saved_payload["runner_type"] == "agent"
        assert saved_payload["trigger_type"] == "interval"
        assert saved_payload["alert_priority"] == "high"
        assert saved_payload["schedule"] == {"value": 10, "unit": "seconds"}
        assert saved_payload["selected_agent"]["name"] == "researcher_agent"
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_workspace_workflows_tab_mobile(playwright):
    """Validate the workflows tab still renders at a mobile viewport."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 390, "height": 844},
        is_mobile=True,
    )
    page = context.new_page()
    workflow_state = _build_workflow_state()

    _route_workflow_api(page, workflow_state)
    _route_agent_api(page)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")

        assert response is not None, "Expected a navigation response when loading /workspace."
        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        _open_workflows_tab(page)

        expect(page.locator("#create-workflow-btn")).to_be_visible()
        expect(page.locator("#workflows-search")).to_be_visible()
        expect(page.locator("#workflows-table-body tr").first).to_be_visible()
    finally:
        context.close()
        browser.close()