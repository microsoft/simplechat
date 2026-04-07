# test_support_send_feedback_field_selection.py
"""
UI test for support Send Feedback field selection stability.
Version: 0.240.064
Implemented in: 0.240.064

This test ensures the Send Feedback page targets fields by stable form metadata
even if an extra text input is inserted ahead of the intended controls.
"""

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
    for candidate in (STORAGE_STATE, ADMIN_STORAGE_STATE):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_support_send_feedback_uses_stable_field_selectors(playwright):
    """Validate Send Feedback submission survives additional text inputs in the form."""
    _require_base_url()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = context.new_page()
        response = page.goto(f"{BASE_URL}/support/send-feedback", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /support/send-feedback."
        if response.status in {401, 403, 404}:
            pytest.skip("Send Feedback page was not available for the configured session.")

        assert response.ok, f"Expected /support/send-feedback to load successfully, got HTTP {response.status}."
        expect(page.get_by_role("heading", name="Send Feedback")).to_be_visible()

        captured_payload = {}

        def handle_send_feedback_route(route, request):
            captured_payload["json"] = request.post_data_json
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"recipientEmail": "support@example.com", "subjectLine": "Support request"}',
            )

        page.route("**/api/support/send_feedback_email", handle_send_feedback_route)

        form = page.locator(".support-send-feedback-form").first
        form.evaluate(
            """
            (node) => {
                const wrapper = document.createElement('div');
                wrapper.className = 'mb-3';

                const label = document.createElement('label');
                label.className = 'form-label';
                label.textContent = 'Inserted field';
                label.setAttribute('for', 'support_feedback_injected_field');

                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'form-control';
                input.id = 'support_feedback_injected_field';
                input.name = 'support_feedback_injected_field';
                input.value = 'decoy value';

                wrapper.append(label, input);
                node.insertBefore(wrapper, node.firstElementChild);
            }
            """
        )

        form.locator('[data-feedback-field="name"]').fill("Stable Name")
        form.locator('[data-feedback-field="email"]').fill("stable@example.com")
        form.locator('[data-feedback-field="organization"]').fill("Stable Org")
        form.locator('[data-feedback-field="details"]').fill("Stable details body")

        form.locator(".support-send-feedback-submit").click()

        expect(form.locator(".support-send-feedback-status")).to_contain_text("Email draft prepared")
        assert captured_payload["json"] == {
            "feedbackType": "bug_report",
            "reporterName": "Stable Name",
            "reporterEmail": "stable@example.com",
            "organization": "Stable Org",
            "details": "Stable details body",
        }
    finally:
        context.close()
        browser.close()