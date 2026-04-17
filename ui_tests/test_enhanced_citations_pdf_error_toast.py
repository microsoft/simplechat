# test_enhanced_citations_pdf_error_toast.py
"""
UI test for enhanced citations PDF error reporting.

Version: 0.241.010
Implemented in: 0.241.010

This test ensures that a failed enhanced citations PDF request surfaces the
backend error message in a toast instead of failing silently behind the PDF
iframe workflow, and that the toast container stays below the floating chat
tutorial launcher.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_enhanced_citation_pdf_failure_shows_backend_toast(playwright):
    """Validate failed PDF enhanced citations show the backend error toast."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))
    page.route(
        "**/api/enhanced_citations/pdf**",
        lambda route: _fulfill_json(route, {"error": "Backend PDF citation failed for test doc."}, status=500),
    )

    try:
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        page.wait_for_selector("#chatbox")
        page.wait_for_selector("#chat-toast-container")
        page.wait_for_function("() => Boolean(window.bootstrap && window.bootstrap.Modal)")
        page.evaluate(
            """
            () => {
                const tutorialLaunch = document.getElementById('chat-tutorial-launch');
                if (tutorialLaunch) {
                    tutorialLaunch.classList.add('is-ready');
                }
            }
            """
        )

        with page.expect_response("**/api/enhanced_citations/pdf**"):
            page.evaluate(
                """
                async () => {
                    const module = await import('/static/js/chat/chat-enhanced-citations.js');
                    await module.showPdfModal('doc-123', 3, null);
                }
                """
            )

        toast_container = page.locator("#chat-toast-container")
        toast_body = toast_container.locator(".toast .toast-body").last
        expect(toast_body).to_contain_text("Backend PDF citation failed for test doc.")
        expect(page.locator("#pdfModal.show")).to_have_count(0)

        tutorial_launch = page.locator("#chat-tutorial-launch")
        expect(tutorial_launch).to_be_visible()

        position_data = page.evaluate(
            """
            () => {
                const toastContainer = document.getElementById('chat-toast-container');
                const tutorialLaunch = document.getElementById('chat-tutorial-launch');
                if (!toastContainer || !tutorialLaunch) {
                    return null;
                }

                const toastRect = toastContainer.getBoundingClientRect();
                const tutorialRect = tutorialLaunch.getBoundingClientRect();
                return {
                    toastTop: toastRect.top,
                    tutorialBottom: tutorialRect.bottom,
                };
            }
            """
        )

        assert position_data is not None, 'Expected chat toast container and tutorial launcher to be present.'
        assert position_data['toastTop'] >= position_data['tutorialBottom'] - 1, (
            'Expected chat toast container to render below the tutorial launcher.'
        )
    finally:
        context.close()
        browser.close()