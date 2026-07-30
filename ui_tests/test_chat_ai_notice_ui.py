# test_chat_ai_notice_ui.py
"""
UI tests for the configurable chat AI notice.

Version: 0.250.102
Implemented in: 0.250.102

These tests ensure administrators can configure the notice and that enabled
notices render accessibly below the chat composer at desktop and mobile sizes.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = (
    os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")
    or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
)
TEST_NOTICE_MESSAGE = "AI-generated content should be reviewed before use. UI test."
REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
CHAT_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "chats.html"
NOTICE_SCRIPT = REPO_ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-ai-notice.js"


def _require_ui_env(storage_state):
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not storage_state or not Path(storage_state).exists():
        pytest.skip("Set the required authenticated UI storage state file.")


def _open_browser(storage_state, viewport):
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(storage_state=storage_state, viewport=viewport)
    return playwright, browser, context, context.new_page()


def _save_ai_notice(page, enabled, message, frequency):
    page.goto(f"{BASE_URL}/admin/settings", wait_until="domcontentloaded")
    page.locator("#general-tab").click()
    page.locator("#enable_ai_notice").set_checked(enabled)
    page.locator("#ai_notice_message").fill(message)
    page.locator("#ai_notice_frequency").select_option(frequency)
    page.locator("#floating-save-btn").click()
    page.wait_for_load_state("domcontentloaded")


def _assert_notice_below_composer(page, expected_message):
    from playwright.sync_api import expect

    notice = page.locator("#ai-notice")
    expect(notice).to_be_visible()
    expect(notice.locator("#ai-notice-message")).to_have_text(expected_message)
    composer_box = page.locator(".chat-input-container").bounding_box()
    notice_box = notice.bounding_box()
    assert composer_box is not None and notice_box is not None
    assert notice_box["y"] >= composer_box["y"] + composer_box["height"] - 1
    return notice


@pytest.mark.ui
def test_ai_notice_ui_uses_safe_controls_and_below_composer_order():
    """Validate the templates and client module preserve safe UI boundaries."""
    admin_source = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    chat_source = CHAT_TEMPLATE.read_text(encoding="utf-8")
    script_source = NOTICE_SCRIPT.read_text(encoding="utf-8")

    assert 'id="enable_ai_notice"' in admin_source
    assert 'id="ai_notice_message"' in admin_source
    assert 'id="ai_notice_frequency"' in admin_source
    assert 'value="non_dismissible"' in admin_source
    assert 'value="every_session"' in admin_source
    assert 'value="daily"' in admin_source
    assert 'value="once"' in admin_source

    composer_index = chat_source.index('class="chat-input-container position-relative"')
    notice_index = chat_source.index('id="ai-notice"')
    drawer_index = chat_source.index('id="conversation-contents-drawer"')
    assert composer_index < notice_index < drawer_index
    assert "{{ ai_notice.message }}" in chat_source
    assert "{{ ai_notice.message|safe }}" not in chat_source
    assert "chat-ai-notice.js" in chat_source
    assert "innerHTML" not in script_source
    assert "aiNoticeDismissal" in script_source


@pytest.mark.ui
def test_admin_configuration_renders_ai_notice_below_chat_composer():
    """Save, render, responsively validate, and restore an AI notice."""
    _require_ui_env(ADMIN_STORAGE_STATE)
    playwright, browser, context, page = _open_browser(
        ADMIN_STORAGE_STATE,
        {"width": 1440, "height": 1000},
    )
    original_settings = None

    try:
        from playwright.sync_api import expect

        response = page.goto(f"{BASE_URL}/admin/settings", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.locator("#general-tab").click()

        section = page.locator("#ai-notice-section")
        expect(section).to_be_visible()
        enabled = page.locator("#enable_ai_notice")
        settings = page.locator("#ai_notice_settings")
        message = page.locator("#ai_notice_message")
        frequency = page.locator("#ai_notice_frequency")
        original_settings = {
            "enabled": enabled.is_checked(),
            "message": message.input_value(),
            "frequency": frequency.input_value(),
        }

        enabled.check()
        expect(settings).to_be_visible()
        expect(message).to_be_editable()
        expect(page.locator("#ai_notice_frequency option")).to_have_count(4)
        _save_ai_notice(page, True, TEST_NOTICE_MESSAGE, "non_dismissible")

        expect(page.locator("#enable_ai_notice")).to_be_checked()
        expect(page.locator("#ai_notice_message")).to_have_value(TEST_NOTICE_MESSAGE)
        expect(page.locator("#ai_notice_frequency")).to_have_value("non_dismissible")

        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None and response.ok
        notice = _assert_notice_below_composer(page, TEST_NOTICE_MESSAGE)
        expect(notice.locator("#ai-notice-dismiss")).to_have_count(0)

        page.set_viewport_size({"width": 390, "height": 844})
        _assert_notice_below_composer(page, TEST_NOTICE_MESSAGE)

        session_message = f"{TEST_NOTICE_MESSAGE} Session"
        _save_ai_notice(page, True, session_message, "every_session")
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        notice = _assert_notice_below_composer(page, session_message)
        notice.locator("#ai-notice-dismiss").click()
        expect(notice).to_be_hidden()
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#ai-notice")).to_be_hidden()

        session_context = browser.new_context(
            storage_state=ADMIN_STORAGE_STATE,
            viewport={"width": 390, "height": 844},
        )
        session_page = session_context.new_page()
        try:
            session_page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
            _assert_notice_below_composer(session_page, session_message)
        finally:
            session_context.close()

        daily_message = f"{TEST_NOTICE_MESSAGE} Daily"
        _save_ai_notice(page, True, daily_message, "daily")
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        notice = _assert_notice_below_composer(page, daily_message)
        notice.locator("#ai-notice-dismiss").click()
        expect(notice).to_be_hidden()
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#ai-notice")).to_be_hidden()

        once_message = f"{TEST_NOTICE_MESSAGE} Once"
        _save_ai_notice(page, True, once_message, "once")
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        notice = _assert_notice_below_composer(page, once_message)
        notice.locator("#ai-notice-dismiss").click()
        expect(notice).to_be_hidden()
        page.reload(wait_until="domcontentloaded")
        expect(page.locator("#ai-notice")).to_be_hidden()

        changed_once_message = f"{once_message} Updated"
        _save_ai_notice(page, True, changed_once_message, "once")
        page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        _assert_notice_below_composer(page, changed_once_message)
    finally:
        if original_settings is not None:
            _save_ai_notice(
                page,
                original_settings["enabled"],
                original_settings["message"],
                original_settings["frequency"],
            )
        context.close()
        browser.close()
        playwright.stop()
