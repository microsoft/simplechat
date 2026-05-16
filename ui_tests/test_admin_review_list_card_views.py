# test_admin_review_list_card_views.py
"""
UI tests for admin feedback and safety violation list/card views.
Version: 0.241.032
Implemented in: 0.241.032

These tests ensure the admin review tables stay compact, card views render
from the same data, safety category tags hide severity 0 entries, and the
view modals remain usable for saving review notes.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _get_storage_state_path():
    for candidate in (ADMIN_STORAGE_STATE, STORAGE_STATE):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _new_admin_page(playwright):
    _require_base_url()
    storage_state = _get_storage_state_path()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    return browser, context, page


def _skip_unavailable(response, page_name):
    assert response is not None, f"Expected a navigation response when loading {page_name}."
    if response.status in {401, 403, 404}:
        pytest.skip(f"{page_name} was not available for the configured admin session.")
    assert response.ok, f"Expected {page_name} to load successfully, got HTTP {response.status}."


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _mock_user_lookup(page):
    page.route(
        "**/api/user/info/**",
        lambda route: _fulfill_json(
            route,
            {
                "display_name": "Review Admin Target",
                "email": "target@example.com",
            },
        ),
    )


@pytest.mark.ui
def test_admin_feedback_compact_list_and_card_view(playwright):
    """Validate feedback list columns, card toggle, and view modal behavior."""
    browser, context, page = _new_admin_page(playwright)

    try:
        _mock_user_lookup(page)
        page.route(
            "**/feedback/review/stats?*",
            lambda route: _fulfill_json(
                route,
                {
                    "total_count": 1,
                    "positive_count": 1,
                    "negative_count": 0,
                    "neutral_count": 0,
                    "acknowledged_count": 0,
                    "unacknowledged_count": 1,
                    "recent_30_day_count": 1,
                    "latest_timestamp": "2026-05-16T12:30:00Z",
                },
            ),
        )
        page.route(
            "**/feedback/review?*",
            lambda route: _fulfill_json(
                route,
                {
                    "feedback": [
                        {
                            "id": "feedback-1",
                            "userId": "user-1",
                            "timestamp": "2026-05-16T12:30:00Z",
                            "prompt": "Summarize the quarterly launch feedback.",
                            "aiResponse": "The response was too brief.",
                            "feedbackType": "Negative",
                            "reason": "The answer missed key customer segments.",
                            "adminReview": {
                                "acknowledged": False,
                                "analysisNotes": "",
                                "responseToUser": "",
                                "actionTaken": "",
                            },
                        }
                    ],
                    "page": 1,
                    "page_size": 10,
                    "total_count": 1,
                },
            ),
        )

        response = page.goto(f"{BASE_URL}/admin/feedback_review", wait_until="domcontentloaded")
        _skip_unavailable(response, "/admin/feedback_review")
        expect(page.get_by_role("heading", name="Feedback Review")).to_be_visible()

        page.get_by_role("tab", name="All Data").click()
        feedback_table = page.locator("#feedback-table")
        expect(feedback_table.locator("thead")).to_contain_text("Timestamp")
        expect(feedback_table.locator("thead")).to_contain_text("Prompt")
        expect(feedback_table.locator("thead")).to_contain_text("Feedback")
        expect(feedback_table.locator("thead")).to_contain_text("Acknowledged")
        expect(feedback_table.locator("thead")).not_to_contain_text("AI Response")
        expect(feedback_table.locator("thead")).not_to_contain_text("Retest")
        expect(feedback_table.get_by_role("button", name="View")).to_be_visible()

        list_metrics = page.locator("#feedback-list-view").evaluate(
            "node => ({ scrollWidth: node.scrollWidth, clientWidth: node.clientWidth })"
        )
        assert list_metrics["scrollWidth"] <= list_metrics["clientWidth"] + 1

        page.locator('label[for="feedback-view-cards"]').click()
        assert page.locator("#feedback-list-view").evaluate("node => node.classList.contains('d-none')")
        assert not page.locator("#feedback-card-view").evaluate("node => node.classList.contains('d-none')")
        expect(page.locator("#feedback-card-view")).to_contain_text("Summarize the quarterly launch feedback.")
        page.locator("#feedback-card-view").get_by_role("button", name="View").click()
        expect(page.get_by_role("heading", name="View Feedback Entry")).to_be_visible()
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_admin_safety_violations_tags_cards_and_view_save(playwright):
    """Validate safety category badges, compact columns, cards, and notes save."""
    browser, context, page = _new_admin_page(playwright)
    captured_payload = {}

    try:
        _mock_user_lookup(page)
        safety_stats_payload = {
            "total_count": 1,
            "new_count": 1,
            "in_review_count": 0,
            "resolved_count": 0,
            "dismissed_count": 0,
            "warn_user_count": 0,
            "suspend_user_count": 0,
            "escalate_count": 0,
            "block_user_count": 0,
            "none_action_count": 1,
            "recent_30_day_count": 1,
        }

        safety_payload = {
            "logs": [
                {
                    "id": "safety-1",
                    "user_id": "user-1",
                    "message": "Unsafe request sample for review.",
                    "triggered_categories": [
                        {"category": "Hate", "severity": 0},
                        {"category": "Violence", "severity": 2},
                        {"category": "SelfHarm", "severity": 4},
                    ],
                    "status": "New",
                    "action": "None",
                    "notes": "",
                    "created_at": "2026-05-16T12:30:00Z",
                    "last_updated": "2026-05-16T12:30:00Z",
                }
            ],
            "page": 1,
            "page_size": 10,
            "total_count": 1,
        }

        def handle_safety_logs(route, request):
            if "/stats" in request.url:
                _fulfill_json(route, safety_stats_payload)
                return
            if request.method == "PATCH":
                captured_payload["json"] = request.post_data_json
                _fulfill_json(route, {"message": "Safety log updated successfully."})
                return
            _fulfill_json(route, safety_payload)

        page.route("**/api/safety/logs**", handle_safety_logs)

        response = page.goto(f"{BASE_URL}/admin/safety_violations", wait_until="domcontentloaded")
        _skip_unavailable(response, "/admin/safety_violations")
        expect(page.get_by_role("heading", name="Safety Violations")).to_be_visible()

        page.get_by_role("tab", name="All Data").click()
        safety_table = page.locator("#safetyLogsTable")
        expect(safety_table.locator("thead")).to_contain_text("Message")
        expect(safety_table.locator("thead")).to_contain_text("Triggered Categories")
        expect(safety_table.locator("thead")).to_contain_text("Status")
        expect(safety_table.locator("thead")).to_contain_text("Action")
        expect(safety_table.locator("thead")).not_to_contain_text("User")
        expect(safety_table.locator("thead")).not_to_contain_text("Notes")
        expect(safety_table.locator("tbody")).to_contain_text("Violence")
        expect(safety_table.locator("tbody")).to_contain_text("SelfHarm")
        expect(safety_table.locator("tbody")).not_to_contain_text("Hate")

        page.locator('label[for="safety-view-cards"]').click()
        assert page.locator("#safety-list-view").evaluate("node => node.classList.contains('d-none')")
        assert not page.locator("#safety-card-view").evaluate("node => node.classList.contains('d-none')")
        expect(page.locator("#safety-card-view")).to_contain_text("Unsafe request sample for review.")
        expect(page.locator("#safety-card-view")).not_to_contain_text("Hate")

        page.locator("#safety-card-view").get_by_role("button", name="View").click()
        expect(page.get_by_role("heading", name="View Violation")).to_be_visible()
        page.locator("#editNotes").fill("Reviewed from the card view.")
        page.get_by_role("button", name="Save Review").click()
        expect(page.locator("#safetyPageStatusAlert")).to_contain_text("Safety log updated successfully")
        assert captured_payload["json"]["notes"] == "Reviewed from the card view."
    finally:
        context.close()
        browser.close()