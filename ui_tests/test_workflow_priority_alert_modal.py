# test_workflow_priority_alert_modal.py
"""
UI test for the workflow priority alert modal.
Version: 0.241.036
Implemented in: 0.241.029

This test ensures unread workflow alerts open in the global modal, show the
configured priority and linked conversations, and can be marked as read from
the browser workflow.
"""

import json
import os
import re
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
def test_workflow_priority_alert_modal(playwright):
    """Validate the global workflow alert modal renders queued workflow alerts."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    read_requests = []

    alert_payload = {
        "success": True,
        "notifications": [
            {
                "id": "workflow-alert-001",
                "title": "High priority workflow alert: Critical Security Event",
                "message": "Processed 2 relevant unread emails. 1. Security Incident - Sender: Microsoft Defender for Cloud <DefenderCloudnoreply@microsoft.com> - Subject: Microsoft Defender for Cloud has detected suspicious activity in your environment.",
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
                    "response_preview": "Processed 2 relevant unread emails. 1. Security Incident - Sender: Microsoft Defender for Cloud <DefenderCloudnoreply@microsoft.com> - Subject: Microsoft Defender for Cloud has detected suspicious activity in your environment.",
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
        expect(page.locator("#workflowAlertModalLabel")).to_have_text("Critical Security Event")
        expect(page.locator("#workflow-alert-type-card")).to_be_visible()
        expect(page.locator("#workflow-alert-type-value")).to_have_text("Security Events")
        expect(page.locator("#workflow-alert-triggered-at")).to_contain_text("Triggered:")
        expect(page.locator("#workflow-alert-meta")).to_contain_text("Trigger: scheduled")
        expect(page.locator("#workflow-alert-message")).to_have_text("Processed 2 relevant unread emails.")
        expect(page.locator("#workflow-alert-response-preview-card")).to_be_visible()
        expect(page.locator("#workflow-alert-response-preview")).to_contain_text("Security Incident")
        expect(page.locator("#workflow-alert-links")).to_contain_text("Open created conversation")
        expect(page.locator("#workflow-alert-links")).to_contain_text("Open workflow")
        expect(page.locator("#workflow-alert-links button")).to_have_count(2)
        expect(page.locator("#workflow-alert-links button").nth(0)).to_have_class(re.compile(r"btn-success"))
        expect(page.locator("#workflow-alert-links button").nth(1)).to_have_class(re.compile(r"btn-outline-secondary"))

        page.locator("#workflow-alert-mark-read-btn").click()
        expect(modal).not_to_be_visible()
        assert any(request_url.endswith('/api/notifications/workflow-alert-001/read') for request_url in read_requests)
    finally:
        context.close()
        browser.close()