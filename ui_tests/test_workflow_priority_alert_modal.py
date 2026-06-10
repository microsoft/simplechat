# test_workflow_priority_alert_modal.py
"""
UI test for the workflow priority alert modal.
Version: 0.241.182
Implemented in: 0.241.055

This test ensures unread workflow alerts open in the global modal, show the
configured priority, prefer alert-focused enrichment copy over legacy preview
text, render linked conversations, open conversation targets in a new tab, and
can be marked as read from the browser workflow.
"""

import json
import os
import re
from pathlib import Path

import pytest

expect = None


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _require_playwright():
    global expect
    playwright_sync = pytest.importorskip("playwright.sync_api", reason="Install Playwright to run this UI test.")
    expect = playwright_sync.expect
    return playwright_sync


@pytest.mark.ui
def test_workflow_priority_alert_modal():
    """Validate the global workflow alert modal renders queued workflow alerts."""
    _require_ui_env()
    playwright_sync = _require_playwright()

    alert_payload = {
        "success": True,
        "notifications": [
            {
                "id": "workflow-alert-001",
                "title": "High priority workflow alert: Critical Security Event",
                "message": "I can't reliably create a Teams meeting for this alert from the current workflow permissions.",
                "created_at": "2025-01-01T10:00:00+00:00",
                "priority": "high",
                "link_url": "/chats?conversationId=group-conversation-001",
                "link_context": {
                    "workspace_type": "group",
                    "group_id": "group-001",
                    "conversation_id": "group-conversation-001",
                    "conversation_kind": "collaborative",
                },
                "metadata": {
                    "workflow_name": "Security Events",
                    "priority": "high",
                    "trigger_source": "scheduled",
                    "alert_title": "eGuardian Alert, Potential Suspect Travel from Atlanta to Pittsburgh",
                    "alert_summary": "Potential Suspect Travel from Atlanta to Pittsburgh. Coordination conversation and Teams briefing are ready.",
                    "alert_detail": "Focus\nPotential Suspect Travel from Atlanta to Pittsburgh\n\nReady now\n- Coordination conversation created\n- Teams briefing prepared\n\nSupporting items\n- Briefing document saved",
                    "response_preview": "I can't reliably create a Teams meeting for this alert from the current workflow permissions.",
                    "link_targets": [
                        {
                            "label": "Open created conversation",
                            "link_url": "/chats?conversationId=personal-conversation-001",
                            "link_context": {
                                "workspace_type": "personal",
                                "conversation_id": "personal-conversation-001",
                                "chat_type": "personal_single_user",
                            },
                        },
                        {
                            "label": "Open created conversation",
                            "link_url": "/chats?conversationId=group-conversation-001",
                            "link_context": {
                                "workspace_type": "group",
                                "group_id": "group-001",
                                "conversation_id": "group-conversation-001",
                                "conversation_kind": "collaboration",
                                "chat_type": "group_multi_user",
                            },
                        },
                        {
                            "label": "Open workflow",
                            "link_url": "/chats?conversationId=workflow-conversation-001",
                            "link_context": {
                                "workspace_type": "personal",
                                "conversation_id": "workflow-conversation-001",
                            },
                        },
                    ],
                },
                "type_config": {"icon": "bi-exclamation-triangle", "color": "danger"},
                "is_read": False,
                "is_dismissed": False,
            }
        ],
    }

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        read_requests = []

        page.route("**/api/notifications/count", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "count": 1}),
        ))
        page.route("**/api/notifications/workflow-alerts**", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(alert_payload),
        ))
        page.route("**/api/notifications?*", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "success": True,
                "notifications": [],
                "total": 0,
                "page": 1,
                "per_page": 20,
                "has_more": False,
            }),
        ))

        def handle_mark_read(route):
            read_requests.append(route.request.url)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"success": True}),
            )

        page.route("**/api/notifications/*/read", handle_mark_read)
        page.route("**/api/notifications/*/dismiss", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True}),
        ))

        try:
            response = page.goto(f"{BASE_URL}/notifications", wait_until="networkidle")
            assert response is not None, "Expected a navigation response when loading /notifications."

            if response.status in SKIP_RESPONSE_CODES:
                pytest.skip(f"Notifications page unavailable in this environment (HTTP {response.status}).")

            assert response.ok, f"Expected /notifications to load successfully, got HTTP {response.status}."

            page.evaluate("window.dispatchEvent(new CustomEvent('workflow-alert-refresh-requested'))")

            modal = page.locator("#workflowAlertModal")
            expect(modal).to_be_visible()
            expect(page.locator("#workflow-alert-priority-badge")).to_have_text("HIGH PRIORITY")
            expect(page.locator("#workflowAlertModalLabel")).to_have_text("eGuardian Alert, Potential Suspect Travel from Atlanta to Pittsburgh")
            expect(page.locator("#workflow-alert-type-card")).to_be_visible()
            expect(page.locator("#workflow-alert-type-value")).to_have_text("Security Events")
            expect(page.locator("#workflow-alert-triggered-at")).to_contain_text("Triggered:")
            expect(page.locator("#workflow-alert-meta")).to_contain_text("Trigger: scheduled")
            expect(page.locator("#workflow-alert-message")).to_have_text("Potential Suspect Travel from Atlanta to Pittsburgh. Coordination conversation and Teams briefing are ready.")
            expect(page.locator("#workflow-alert-response-preview-card")).to_be_visible()
            expect(page.locator("#workflow-alert-response-preview")).to_contain_text("Focus")
            expect(page.locator("#workflow-alert-response-preview")).to_contain_text("Potential Suspect Travel from Atlanta to Pittsburgh")
            expect(page.locator("#workflow-alert-response-preview")).to_contain_text("Ready now")
            expect(page.locator("#workflow-alert-response-preview")).to_contain_text("Coordination conversation created")
            expect(page.locator("#workflow-alert-response-preview")).to_contain_text("Teams briefing prepared")
            expect(page.locator("#workflow-alert-response-preview")).to_contain_text("Supporting items")
            expect(page.locator("#workflow-alert-response-preview")).to_contain_text("Briefing document saved")
            expect(page.locator("#workflow-alert-response-preview")).not_to_contain_text("can't reliably create a Teams meeting")
            expect(page.locator("#workflow-alert-links")).to_contain_text("Open created conversation")
            expect(page.locator("#workflow-alert-links")).to_contain_text("Open workflow")
            expect(page.locator("#workflow-alert-links button")).to_have_count(2)
            expect(page.locator("#workflow-alert-links button").nth(0)).to_have_class(re.compile(r"btn-success"))
            expect(page.locator("#workflow-alert-links button").nth(1)).to_have_class(re.compile(r"btn-outline-secondary"))

            with context.expect_page() as new_page_info:
                page.locator("#workflow-alert-links button").nth(0).click()

            new_page = new_page_info.value
            new_page.wait_for_load_state("domcontentloaded")
            assert "conversationId=group-conversation-001" in new_page.url
            new_page.close()

            expect(modal).not_to_be_visible()
            assert any(request_url.endswith('/api/notifications/workflow-alert-001/read') for request_url in read_requests)

            read_requests.clear()
            page.evaluate("window.dispatchEvent(new CustomEvent('workflow-alert-refresh-requested'))")
            expect(modal).to_be_visible()
            page.locator("#workflow-alert-mark-read-btn").click()
            expect(modal).not_to_be_visible()
            assert any(request_url.endswith('/api/notifications/workflow-alert-001/read') for request_url in read_requests)
        finally:
            context.close()
            browser.close()