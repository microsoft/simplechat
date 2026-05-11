# test_profile_tutorial_visibility_preference.py
"""
UI test for profile tutorial visibility preference.
Version: 0.240.068
Implemented in: 0.240.068

This test ensures a signed-in user can hide guided tutorial launchers from the
profile page and that Chat no longer renders the floating tutorial button after
the preference is saved.
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
def test_profile_can_hide_tutorial_buttons(playwright):
    """Validate that hiding tutorial buttons from profile removes the chat launcher."""
    _require_base_url()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = context.new_page()
        response = page.goto(f"{BASE_URL}/profile", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /profile."
        if response.status in {401, 403, 404}:
            pytest.skip("Profile page was not available for the configured session.")

        assert response.ok, f"Expected /profile to load successfully, got HTTP {response.status}."
        expect(page.get_by_role("heading", name="Tutorial Preferences")).to_be_visible()

        toggle = page.locator("#show-tutorial-buttons-toggle")
        save_button = page.locator("#save-tutorial-preferences-btn")

        original_value = toggle.is_checked()

        try:
            if original_value:
                toggle.uncheck()
                save_button.click()
                expect(page.locator("#tutorial-preference-status")).to_contain_text("hidden for your account")

                chat_response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
                assert chat_response is not None, "Expected a navigation response when loading /chats."
                if chat_response.status in {401, 403, 404}:
                    pytest.skip("Chat page was not available for the configured session.")

                assert chat_response.ok, f"Expected /chats to load successfully, got HTTP {chat_response.status}."
                expect(page.locator("#chat-tutorial-launch")).to_have_count(0)

                workspace_response = page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
                if workspace_response is not None and workspace_response.ok:
                    expect(page.locator("#workspace-tutorial-launch")).to_have_count(0)
            else:
                toggle.check()
                save_button.click()
                expect(page.locator("#tutorial-preference-status")).to_contain_text("stay visible")

                chat_response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
                assert chat_response is not None, "Expected a navigation response when loading /chats."
                if chat_response.status in {401, 403, 404}:
                    pytest.skip("Chat page was not available for the configured session.")

                assert chat_response.ok, f"Expected /chats to load successfully, got HTTP {chat_response.status}."
                expect(page.locator("#chat-tutorial-launch")).to_be_visible()
        finally:
            page.goto(f"{BASE_URL}/profile", wait_until="domcontentloaded")
            expect(page.get_by_role("heading", name="Tutorial Preferences")).to_be_visible()
            restored_toggle = page.locator("#show-tutorial-buttons-toggle")
            if original_value:
                restored_toggle.check()
            else:
                restored_toggle.uncheck()
            page.locator("#save-tutorial-preferences-btn").click()
            expect(page.locator("#tutorial-preference-status")).to_contain_text(
                "stay visible" if original_value else "hidden for your account"
            )
    finally:
        context.close()
        browser.close()