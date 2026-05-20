# test_chat_deep_research_toggle.py
"""
UI test for chat Deep Research toggle visibility.
Version: 0.241.051
Implemented in: 0.241.051

This test ensures the Deep Research button is hidden until Web Search is active
or the prompt contains direct HTTP(S) URLs, then sends the user-facing state
through the existing chat toolbar control.
"""

import os
import re
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
CHAT_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_chat_deep_research_toggle_visibility():
    """Validate Deep Research only appears for web search or direct URL prompts."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if CHAT_STORAGE_STATE and not Path(CHAT_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated storage state file.")
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context_kwargs = {"viewport": {"width": 1440, "height": 1000}}
    if CHAT_STORAGE_STATE:
        context_kwargs["storage_state"] = CHAT_STORAGE_STATE
    context = browser.new_context(**context_kwargs)
    page = context.new_page()

    try:
        response = page.goto(f"{BASE_URL}/", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response for chat."
        if response.status in {401, 403, 404}:
            pytest.skip("Configured storage state cannot access chat.")
        assert response.ok, f"Expected chat to load, got HTTP {response.status}."

        deep_research_button = page.locator("#source-review-btn")
        if deep_research_button.count() == 0:
            pytest.skip("Deep Research is not enabled in this test environment.")

        expect(deep_research_button).to_have_attribute("aria-label", "Deep Research")
        expect(deep_research_button).to_have_class(re.compile(r".*\bd-none\b.*"))

        web_search_button = page.locator("#search-web-btn")
        if web_search_button.count() > 0:
            web_search_button.click()
            expect(deep_research_button).not_to_have_class(re.compile(r".*\bd-none\b.*"))
            deep_research_button.click()
            expect(deep_research_button).to_have_class(re.compile(r".*\bactive\b.*"))
            web_search_button.click()
            expect(deep_research_button).to_have_class(re.compile(r".*\bd-none\b.*"))
            expect(deep_research_button).not_to_have_class(re.compile(r".*\bactive\b.*"))

        prompt = page.locator("#user-input")
        prompt.fill("Review https://example.com/news for the latest announcement")
        expect(deep_research_button).not_to_have_class(re.compile(r".*\bd-none\b.*"))
    finally:
        context.close()
        browser.close()
        playwright.stop()
