# test_workspace_workflow_list_no_horizontal_scroll.py
"""
UI test for workflow list horizontal overflow.
Version: 0.241.045
Implemented in: 0.241.045

This test ensures the personal workspace workflow list fits its desktop card
width without showing a horizontal scrollbar while still exposing all workflow
actions in the list row.
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


def _route_workflow_api(page):
    payload = {
        "workflows": [
            {
                "id": "workflow-001",
                "name": "Security Events",
                "description": "Informs user of email based security events.",
                "task_prompt": "Review the inbox for security-related events.",
                "runner_type": "agent",
                "trigger_type": "manual",
                "is_enabled": True,
                "selected_agent": {
                    "id": "agent-001",
                    "name": "executive_agent",
                    "display_name": "Executive Agent",
                    "is_global": False,
                },
                "alert_priority": "high",
                "last_run_status": "completed",
                "last_run_at": "2026-04-19T19:27:00+00:00",
                "last_run_response_preview": "Processed relevant unread security-related emails only.",
                "conversation_id": "workflow-conversation-001",
                "status": "idle",
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


@pytest.mark.ui
def test_workspace_workflow_list_has_no_desktop_horizontal_scroll(playwright):
    """Validate the workflows list fits the card width on desktop without horizontal overflow."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1365, "height": 768},
    )
    page = context.new_page()

    _route_workflow_api(page)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")

        assert response is not None, "Expected a navigation response when loading /workspace."
        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        page.locator("#workflows-tab-btn").evaluate("button => button.click()")
        expect(page.locator("#workflows-tab")).to_be_visible()

        workflow_row = page.locator("#workflows-table-body tr").filter(has_text="Security Events")
        expect(workflow_row).to_be_visible()
        expect(workflow_row.get_by_role("button", name="Run")).to_be_visible()
        expect(workflow_row.get_by_role("button", name="Activity")).to_be_visible()
        expect(workflow_row.get_by_role("button", name="History")).to_be_visible()

        overflow_metrics = page.locator("#workflows-list-view .table-responsive").evaluate(
            """
            node => ({
                scrollWidth: node.scrollWidth,
                clientWidth: node.clientWidth,
                overflowX: getComputedStyle(node).overflowX,
            })
            """
        )

        assert overflow_metrics["scrollWidth"] <= overflow_metrics["clientWidth"] + 1, (
            f"Expected no horizontal overflow in workflow list, got scrollWidth={overflow_metrics['scrollWidth']} and clientWidth={overflow_metrics['clientWidth']}"
        )
    finally:
        context.close()
        browser.close()