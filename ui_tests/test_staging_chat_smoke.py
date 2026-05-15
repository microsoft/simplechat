# test_staging_chat_smoke.py
"""
UI smoke test for staging chat deployment.
Version: 0.241.018
Implemented in: 0.241.014; 0.241.018

This test ensures that a deployed staging SimpleChat environment can load the
chat UI with authenticated browser state, create a conversation, submit a
message, receive an assistant response, and clean up the created conversation.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = (
    os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
    or os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")
)
ACCESS_TOKEN = os.getenv("SIMPLECHAT_UI_ACCESS_TOKEN", "")
ARTIFACT_DIR = Path(os.getenv("SIMPLECHAT_UI_ARTIFACT_DIR", Path(__file__).parent / "artifacts"))
SMOKE_PROMPT = os.getenv(
    "SIMPLECHAT_UI_SMOKE_PROMPT",
    "CI smoke test. Reply with one short greeting.",
)
RESPONSE_TIMEOUT_MS = int(os.getenv("SIMPLECHAT_UI_SMOKE_RESPONSE_TIMEOUT_MS", "180000"))


def _require_staging_settings():
    """Skip when the staging URL or authenticated browser state is not configured."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this staging UI smoke test.")
    if not ACCESS_TOKEN and (not STORAGE_STATE or not Path(STORAGE_STATE).exists()):
        pytest.skip("Set SIMPLECHAT_UI_ACCESS_TOKEN or a valid SIMPLECHAT_UI_STORAGE_STATE/SIMPLECHAT_UI_ADMIN_STORAGE_STATE file.")


@pytest.mark.ui
def test_staging_chat_can_create_conversation_and_receive_response(playwright):
    """Validate the basic staging chat loop against a deployed environment."""
    _require_staging_settings()
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    browser = playwright.chromium.launch()
    context_options = {"viewport": {"width": 1440, "height": 900}}
    auth_headers = {}
    if ACCESS_TOKEN:
        auth_headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
        context_options["extra_http_headers"] = auth_headers
    else:
        context_options["storage_state"] = STORAGE_STATE

    context = browser.new_context(**context_options)
    trace_path = ARTIFACT_DIR / "staging_chat_smoke_trace.zip"
    screenshot_path = ARTIFACT_DIR / "staging_chat_smoke_failure.png"
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    conversation_id = None

    try:
        if ACCESS_TOKEN:
            session_response = context.request.post(f"{BASE_URL}/ci-auth/session", headers=auth_headers, timeout=30000)
            assert session_response.ok, f"Expected CI bearer session setup to succeed, got HTTP {session_response.status}."

        response = page.goto(f"{BASE_URL}/chats", wait_until="networkidle", timeout=60000)
        assert response is not None, "Expected a navigation response when loading /chats."
        if response.status in (401, 403):
            pytest.fail("Authenticated storage state was rejected by the staging chat page.")
        assert response.ok, f"Expected /chats to load successfully, got HTTP {response.status}."

        expect(page.locator("#user-input")).to_be_visible(timeout=30000)
        expect(page.locator("#send-btn")).to_be_attached(timeout=30000)

        page.locator("#new-conversation-btn").click()
        page.locator("#user-input").fill(SMOKE_PROMPT)
        page.locator("#send-btn").click()

        expect(page.locator(".user-message .message-text").filter(has_text=SMOKE_PROMPT)).to_be_visible(timeout=15000)

        page.wait_for_function(
            """
            () => Array.from(document.querySelectorAll('.ai-message .message-text')).some(element => {
                const text = (element.textContent || '').trim();
                const messageElement = element.closest('.ai-message');
                return Boolean(
                    text
                    && !text.includes('Streaming...')
                    && !text.includes('Reconnecting')
                    && messageElement
                    && !messageElement.querySelector('.streaming-cursor, .spinner-border')
                );
            })
            """,
            timeout=RESPONSE_TIMEOUT_MS,
        )

        assistant_message = page.locator(".ai-message .message-text").last
        assistant_text = (assistant_message.text_content() or "").strip()
        assert assistant_text, "Expected the assistant response to contain text."

        conversation_id = page.evaluate(
            """
            () => window.chatConversations?.getCurrentConversationId?.()
                || window.currentConversationId
                || null
            """
        )
        assert conversation_id, "Expected the staging smoke test to create or select a conversation."

        assert page.locator(".toast.show .text-bg-danger, .toast.show.bg-danger, .toast.show .alert-danger").count() == 0
    except Exception:
        page.screenshot(path=screenshot_path, full_page=True)
        raise
    finally:
        if conversation_id:
            try:
                context.request.delete(f"{BASE_URL}/api/conversations/{conversation_id}", timeout=30000)
            except Exception:
                pass

        context.tracing.stop(path=trace_path)
        context.close()
        browser.close()
