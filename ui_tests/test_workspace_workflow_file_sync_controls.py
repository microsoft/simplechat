# test_workspace_workflow_file_sync_controls.py
"""
UI test for workflow File Sync controls.
Version: 0.241.133
Implemented in: 0.241.133

This test ensures the workflow modal can select File Sync sources, switch to
Monitor File Sync Changes mode, and submit the expected File Sync payload.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _route_workflow_apis(page, state):
    def workflows_handler(route):
        request = route.request
        if request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"workflows": state["workflows"]}))
            return
        if request.method == "POST":
            payload = json.loads(request.post_data or "{}")
            state["saved_payloads"].append(payload)
            saved_workflow = {
                "id": "workflow-file-sync-monitor",
                "name": payload.get("name"),
                "description": payload.get("description"),
                "task_prompt": payload.get("task_prompt"),
                "runner_type": payload.get("runner_type"),
                "trigger_type": payload.get("trigger_type"),
                "schedule": payload.get("schedule", {}),
                "file_sync": payload.get("file_sync", {}),
                "is_enabled": payload.get("is_enabled", True),
                "model_binding_summary": {"label": "Default app model"},
                "status": "idle",
            }
            state["workflows"] = [saved_workflow, *state["workflows"]]
            route.fulfill(status=201, content_type="application/json", body=json.dumps({"success": True, "workflow": saved_workflow}))
            return
        route.fulfill(status=405, content_type="application/json", body=json.dumps({"error": "Unsupported"}))

    def file_sync_sources_handler(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "sources": [
                        {
                            "scope_type": "personal",
                            "scope_id": "user-1",
                            "source_id": "source-1",
                            "name": "Finance Incoming",
                            "source_type": "smb",
                            "enabled": True,
                            "label": "Finance Incoming (Personal)",
                        }
                    ]
                }
            ),
        )

    page.route("**/api/user/workflows/file-sync-sources", file_sync_sources_handler)
    page.route("**/api/user/workflows", workflows_handler)
    page.route("**/api/user/agents", lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps([])))


@pytest.mark.ui
def test_workspace_workflow_file_sync_controls():
    """Validate File Sync workflow controls and submitted payload."""
    _require_ui_env()
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install playwright to run this UI test.")

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    state = {"workflows": [], "saved_payloads": []}
    _route_workflow_apis(page, state)

    try:
        page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        if page.locator("#workflows-tab-btn").count() == 0:
            pytest.skip("Personal workflows are disabled or unavailable for this authenticated user.")

        page.locator("#workflows-tab-btn").evaluate("button => button.click()")
        expect(page.locator("#workflows-tab")).to_be_visible()
        page.get_by_role("button", name="New Workflow").click()
        expect(page.locator("#workflowModal")).to_be_visible()

        page.fill("#workflow-name", "Monitor Finance Drop")
        page.fill("#workflow-description", "Runs when Finance Incoming sync detects changed files.")
        page.fill("#workflow-task-prompt", "Summarize every changed finance document into one combined result.")
        page.select_option("#workflow-trigger-type", "file_sync")
        expect(page.locator("#workflow-file-sync-enabled")).to_be_checked()
        expect(page.locator("#workflow-file-sync-wait-mode")).to_have_value("complete")
        expect(page.locator("#workflow-file-sync-continue-mode")).to_have_value("changed")
        page.select_option("#workflow-file-sync-sources", "personal:user-1:source-1")
        page.fill("#workflow-schedule-value", "10")
        page.select_option("#workflow-schedule-unit", "minutes")
        page.get_by_role("button", name="Save Workflow").click()

        expect(page.locator("#workflowModal")).to_be_hidden()
        assert state["saved_payloads"], "Expected workflow save payload to be captured."
        payload = state["saved_payloads"][-1]
        assert payload["trigger_type"] == "file_sync"
        assert payload["schedule"] == {"value": 10, "unit": "minutes"}
        assert payload["file_sync"]["enabled"] is True
        assert payload["file_sync"]["wait_mode"] == "complete"
        assert payload["file_sync"]["continue_mode"] == "changed"
        assert payload["file_sync"]["use_changed_documents"] is True
        assert payload["file_sync"]["sources"] == [
            {"scope_type": "personal", "scope_id": "user-1", "source_id": "source-1"}
        ]
    finally:
        context.close()
        browser.close()
        playwright_context.stop()
