# test_workflow_activity_dark_mode_layout.py
"""
UI test for workflow activity dark mode and expanded-sidebar layout.
Version: 0.241.043
Implemented in: 0.241.043

This test ensures the workflow activity view remains readable in dark mode and
expands beyond the shared container width so the timeline and detail panels fit
comfortably when the left navigation sidebar is visible.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_workflow_activity_dark_mode_and_sidebar_layout(playwright):
    """Validate the workflow activity page stays readable in dark mode and roomy with sidebar padding."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1600, "height": 960},
    )
    page = context.new_page()

    activity_payload = {
        "workflow": {
            "id": "workflow-001",
            "name": "Security Events",
        },
        "conversation": {
            "id": "workflow-conversation-001",
            "title": "Workflow: Security Events",
            "chat_type": "workflow",
        },
        "run": {
            "id": "workflow-run-001",
            "conversation_id": "workflow-conversation-001",
            "status": "completed",
            "started_at": "2026-04-19T04:00:00+00:00",
            "trigger_source": "manual",
            "agent_display_name": "Executive Agent",
            "response_preview": "Processed relevant unread security-related emails only.",
        },
        "activities": [
            {
                "id": "activity-001",
                "kind": "workflow_run",
                "title": "Workflow run",
                "summary": "Workflow run completed.",
                "detail": "trigger_source=manual",
                "status": "completed",
                "lane_label": "Main",
                "lane_index": 0,
                "started_at": "2026-04-19T04:00:00+00:00",
                "duration_ms": 1800,
                "events": [
                    {
                        "content": "Workflow run completed",
                        "detail": "assistant_message_id=assistant-message-1",
                        "timestamp": "2026-04-19T04:00:02+00:00",
                    }
                ],
            },
            {
                "id": "activity-002",
                "kind": "tool_invocation",
                "title": "MSGraphPlugin.search_users",
                "summary": "Workflow agent executed MSGraphPlugin.search_users.",
                "detail": "query=Paul Microsoft; top=5",
                "status": "completed",
                "lane_label": "MSGraphPlugin",
                "lane_index": 1,
                "started_at": "2026-04-19T04:00:01+00:00",
                "duration_ms": 1051,
                "events": [
                    {
                        "content": "Invoking MSGraphPlugin.search_users",
                        "detail": "query=Paul Microsoft; top=5",
                        "timestamp": "2026-04-19T04:00:01+00:00",
                    }
                ],
            },
        ],
        "lane_count": 2,
        "live": False,
    }

    page.route(
        "**/api/user/workflows/activity**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(activity_payload),
        ),
    )

    try:
        response = page.goto(
            f"{BASE_URL}/workflow-activity?conversationId=workflow-conversation-001&runId=workflow-run-001",
            wait_until="networkidle",
        )
        assert response is not None, "Expected a navigation response when loading workflow activity."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Workflow activity page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected /workflow-activity to load successfully, got HTTP {response.status}."

        page.evaluate(
            """
            () => {
                document.documentElement.setAttribute('data-bs-theme', 'dark');
                const mainContent = document.getElementById('main-content');
                if (mainContent) {
                    mainContent.classList.add('sidebar-padding');
                    mainContent.style.setProperty('--sidebar-width', '280px');
                }
            }
            """
        )

        expect(page.locator("#workflow-activity-title")).to_have_text("Security Events")
        expect(page.locator("#workflow-activity-response-toggle")).to_be_visible()
        expect(page.locator(".workflow-activity-card").first).to_be_visible()

        theme_metrics = page.locator(".workflow-activity-card").first.evaluate(
            """
            node => {
                const styles = getComputedStyle(node);
                return {
                    background: styles.backgroundColor,
                    color: styles.color,
                    border: styles.borderColor,
                };
            }
            """
        )

        assert theme_metrics["background"] != "rgb(255, 255, 255)"
        assert theme_metrics["background"] != theme_metrics["color"]

        layout_metrics = page.locator("#main-content").evaluate(
            """
            node => {
                const styles = getComputedStyle(node);
                const rect = node.getBoundingClientRect();
                return {
                    maxWidth: styles.maxWidth,
                    width: rect.width,
                    paddingLeft: parseFloat(styles.paddingLeft || '0'),
                };
            }
            """
        )

        detail_width = page.locator(".workflow-activity-detail-panel").evaluate(
            "node => node.getBoundingClientRect().width"
        )

        assert layout_metrics["maxWidth"] == "none"
        assert layout_metrics["width"] > 1400
        assert layout_metrics["paddingLeft"] >= 280
        assert detail_width >= 320
    finally:
        context.close()
        browser.close()