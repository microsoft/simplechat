# test_profile_feedback_table_no_scroll.py
"""
UI test for profile feedback table overflow prevention.
Version: 0.241.034
Implemented in: 0.241.034

This test ensures the My Feedback table omits wide AI response and admin action
columns, fits within its card without horizontal scrolling, and keeps full
details available from the row detail modal.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _get_storage_state_path():
    if STORAGE_STATE and Path(STORAGE_STATE).exists():
        return STORAGE_STATE
    pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _fulfill_json(route, payload):
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_profile_feedback_table_fits_without_wide_columns(playwright):
    """Validate My Feedback table columns and horizontal overflow behavior."""
    _require_base_url()
    storage_state = _get_storage_state_path()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 768, "height": 820},
    )

    feedback_payload = {
        "feedback": [
            {
                "id": "feedback-compact-1",
                "timestamp": "2026-05-16T14:45:29Z",
                "prompt": "what events are on my calendar",
                "aiResponse": "You have 2 upcoming calendar events with a deliberately long response body that should stay out of the table.",
                "feedbackType": "Negative",
                "reason": "The response missed the important event context and should wrap without forcing horizontal scrolling.",
                "adminReview": {
                    "acknowledged": False,
                    "analysisNotes": "Admin reviewed the issue.",
                    "responseToUser": "Thanks for the feedback.",
                    "actionTaken": "This long admin action should be visible only in the detail modal.",
                },
            }
        ],
        "page": 1,
        "page_size": 10,
        "total_count": 1,
    }
    stats_payload = {
        "total_count": 1,
        "positive_count": 0,
        "negative_count": 1,
        "neutral_count": 0,
        "acknowledged_count": 0,
    }

    def handle_feedback_route(route, request):
        if "/stats" in request.url:
            _fulfill_json(route, stats_payload)
            return
        _fulfill_json(route, feedback_payload)

    page = context.new_page()
    page.route("**/feedback/my**", handle_feedback_route)

    try:
        response = page.goto(f"{BASE_URL}/profile?tab=feedback", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /profile?tab=feedback."
        if response.status in {401, 403, 404}:
            pytest.skip("Profile feedback tab was not available for the configured session.")
        assert response.ok, f"Expected profile feedback tab to load successfully, got HTTP {response.status}."

        if page.locator("#profile-feedback-table").count() == 0:
            pytest.skip("User feedback is not enabled for the configured environment.")

        expect(page.get_by_role("heading", name="My Feedback")).to_be_visible()
        table = page.locator("#profile-feedback-table")
        expect(table.locator("thead")).to_contain_text("Timestamp")
        expect(table.locator("thead")).to_contain_text("Prompt")
        expect(table.locator("thead")).to_contain_text("Feedback")
        expect(table.locator("thead")).to_contain_text("Reason")
        expect(table.locator("thead")).to_contain_text("Acknowledged")
        expect(table.locator("thead")).not_to_contain_text("AI Response")
        expect(table.locator("thead")).not_to_contain_text("Admin Action")
        expect(table.locator("tbody")).to_contain_text("what events are on my calendar")
        expect(table.locator("tbody")).not_to_contain_text("deliberately long response body")
        expect(table.locator("tbody")).not_to_contain_text("long admin action")

        wrapper_metrics = page.locator(".profile-feedback-table-wrapper").evaluate(
            "node => ({ scrollWidth: node.scrollWidth, clientWidth: node.clientWidth })"
        )
        assert wrapper_metrics["scrollWidth"] <= wrapper_metrics["clientWidth"] + 1

        table.get_by_role("button", name="View").click()
        expect(page.get_by_role("heading", name="Feedback Details")).to_be_visible()
        expect(page.locator("#profile-feedback-detail-response")).to_contain_text("deliberately long response body")
        expect(page.locator("#profile-feedback-detail-action")).to_contain_text("long admin action")
    finally:
        context.close()
        browser.close()