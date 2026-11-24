# test_chat_launch_link_modal.py
"""
UI regression for the Classic chat-link creation and revocation modal.
Version: 0.261.473
Implemented in: 0.261.473

This test verifies the default lifetime, plain-text link inventory, and
confirmation-based revocation without depending on a specific workspace seed.
"""

import json
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.ui
BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def fulfill_json(route, payload, status=200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


def test_classic_chat_link_modal_defaults_to_ninety_days_and_revokes_with_confirmation():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    revoked = []

    def handle_links(route):
        request = route.request
        if request.method == "DELETE":
            revoked.append(request.url.rsplit("/", 1)[-1])
            route.fulfill(status=204, body="")
            return
        fulfill_json(route, {
            "links": [{
                "reference": "CLASSIC1234567890abcde",
                "path": "/l/CLASSIC1234567890abcde",
                "created_at": "2026-11-24T12:00:00Z",
                "expires_at": None,
                "lifetime_days": None,
                "routing": {
                    "kind": "model",
                    "selection_key": "global:global:endpoint:model",
                },
                "workspace": {"kind": "personal"},
                "document_count": 2,
            }],
            "continuation_token": None,
            "has_more": False,
        })

    page.route("**/api/chat-links*", handle_links)

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None and response.ok
        page.locator("#create-chat-link-btn").click()
        modal = page.locator("#chat-link-modal")
        expect(modal).to_be_visible()
        expect(page.locator("#chat-link-lifetime")).to_have_value("90")
        expect(page.locator("#chat-link-own-list")).to_contain_text("Never expires")

        page.locator("#chat-link-own-list [data-chat-link-reference]").click()
        revoke_modal = page.locator("#chat-link-revoke-modal")
        expect(revoke_modal).to_be_visible()
        page.locator("#chat-link-revoke-confirm-btn").click()
        expect(revoke_modal).to_be_hidden()
        assert revoked == ["CLASSIC1234567890abcde"]
    finally:
        context.close()
        browser.close()
        playwright.stop()
