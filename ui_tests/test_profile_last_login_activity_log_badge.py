# test_profile_last_login_activity_log_badge.py
"""
UI test for profile last login activity log badge display.
Version: 0.241.027
Implemented in: 0.241.027

This test ensures the profile last-login badge renders a clear fallback when
the activity log source returns no login timestamp.
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
    for candidate in (STORAGE_STATE, ADMIN_STORAGE_STATE):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE or SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _build_empty_login_settings_payload():
    return {
        "success": True,
        "settings": {
            "metrics": {
                "calculated_at": "2026-05-16T00:00:00Z",
                "login_metrics": {
                    "total_logins": 0,
                    "last_login": None,
                    "last_login_source": "activity_logs",
                },
                "chat_metrics": {
                    "total_conversations": 0,
                    "total_messages": 0,
                },
                "document_metrics": {
                    "total_documents": 0,
                },
            },
        },
        "metrics": {
            "calculated_at": "2026-05-16T00:00:00Z",
            "login_metrics": {
                "total_logins": 0,
                "last_login": None,
                "last_login_source": "activity_logs",
            },
            "chat_metrics": {
                "total_conversations": 0,
                "total_messages": 0,
            },
            "document_metrics": {
                "total_documents": 0,
            },
        },
    }


def _build_empty_activity_trends_payload():
    return {
        "success": True,
        "logins": [],
        "conversations": {
            "creates": [],
            "deletes": [],
        },
        "documents": {
            "uploads": [],
            "deletes": [],
        },
        "tokens": [],
        "storage": {
            "ai_search_size": 0,
            "storage_account_size": 0,
        },
    }


@pytest.mark.ui
def test_profile_last_login_empty_activity_logs_show_never(playwright):
    """Validate the profile hero does not leave the last-login badge loading."""
    _require_base_url()
    storage_state = _get_storage_state_path()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=storage_state,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.route(
            "**/api/user/settings",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_build_empty_login_settings_payload()),
            ),
        )
        page.route(
            "**/api/user/activity-trends**",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(_build_empty_activity_trends_payload()),
            ),
        )

        response = page.goto(f"{BASE_URL}/profile", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /profile."
        if response.status in {401, 403, 404}:
            pytest.skip("Profile page was not available for the configured session.")

        assert response.ok, f"Expected /profile to load successfully, got HTTP {response.status}."
        expect(page.locator("#last-login")).to_have_text("Never")
    finally:
        context.close()
        browser.close()