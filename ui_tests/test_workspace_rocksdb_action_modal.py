# test_workspace_rocksdb_action_modal.py
"""
UI test for the workspace RocksDB action modal.
Version: 0.250.216
Implemented in: 0.250.216

This test ensures users can select the RocksDB action type, complete the RocksDB HTTP
service configuration, switch authentication schemes, run the browser-side connection
test, see inline validation errors, and review the RocksDB summary card before saving.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _open_rocksdb_config_step(page):
    """Navigate the action modal to the RocksDB configuration step."""
    response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
    assert response is not None, "Expected a navigation response when loading /workspace."

    if response.status in SKIP_RESPONSE_CODES:
        pytest.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")

    assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."
    expect(page.locator("#documents-tab")).to_be_visible()

    plugins_tab_button = page.locator("#plugins-tab-btn")
    if plugins_tab_button.count() == 0:
        pytest.skip("Workspace actions are not enabled in this environment.")

    plugins_tab_button.click()

    create_button = page.locator("#create-plugin-btn")
    if create_button.count() == 0:
        pytest.skip("Workspace action creation is not available in this environment.")

    expect(create_button).to_be_visible()
    create_button.click()

    modal = page.locator("#plugin-modal")
    expect(modal).to_be_visible()

    rocksdb_card = page.locator('.action-type-card[data-type="rocksdb"]')
    if rocksdb_card.count() == 0:
        pytest.skip("The RocksDB action type is not available in this environment.")

    rocksdb_card.click()
    modal.get_by_role("button", name="Next").click()

    page.locator("#plugin-display-name").fill("RocksDB Reader")
    modal.get_by_role("button", name="Next").click()

    expect(page.locator("#rocksdb-config-section")).to_be_visible()
    expect(page.locator("#cosmos-config-section")).to_be_hidden()
    expect(page.locator("#generic-config-section")).to_be_hidden()

    return modal


@pytest.mark.ui
def test_workspace_rocksdb_action_modal_configuration(playwright):
    """Validate the RocksDB service flow, connection test, and summary card."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        captured_payload = {}

        def handle_rocksdb_test(route):
            request_body = route.request.post_data or "{}"
            captured_payload.clear()
            captured_payload.update(json.loads(request_body))
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": true, "message": "Successfully reached the RocksDB service at https://rocksdb.example.com/api."}'
            )

        page.route("**/api/plugins/test-rocksdb-connection", handle_rocksdb_test)

        _open_rocksdb_config_step(page)

        page.locator("#rocksdb-base-url").fill("https://rocksdb.example.com/api")

        # Selecting a token-based scheme reveals the token and header fields.
        expect(page.locator("#rocksdb-auth-key-group")).to_be_hidden()
        expect(page.locator("#rocksdb-api-key-header-group")).to_be_hidden()
        page.locator("#rocksdb-auth-scheme").select_option("api_key")
        expect(page.locator("#rocksdb-auth-key-group")).to_be_visible()
        expect(page.locator("#rocksdb-api-key-header-group")).to_be_visible()

        page.locator("#rocksdb-auth-key").fill("service-token-value")
        page.locator("#rocksdb-api-key-header").fill("X-Rocks-Key")
        page.locator("#rocksdb-column-family").fill("events")
        page.locator("#rocksdb-key-prefix-hints").fill("user:\nevent:")
        page.locator("#rocksdb-max-results").fill("50")
        page.locator("#rocksdb-max-value-bytes").fill("8192")
        page.locator("#rocksdb-timeout").fill("20")

        page.locator("#rocksdb-test-connection-btn").click()
        expect(page.locator("#rocksdb-test-connection-result")).to_be_visible()
        expect(page.locator("#rocksdb-test-connection-alert")).to_contain_text("Successfully reached the RocksDB service")

        assert captured_payload.get("base_url") == "https://rocksdb.example.com/api"
        assert captured_payload.get("auth_scheme") == "api_key"
        assert captured_payload.get("api_key_header") == "X-Rocks-Key"
        assert captured_payload.get("auth_key") == "service-token-value"

        page.locator("#plugin-modal-skip").click()

        expect(page.locator("#summary-rocksdb-section")).to_be_visible()
        expect(page.locator("#summary-plugin-database-type")).to_have_text("RocksDB HTTP service")
        expect(page.locator("#summary-plugin-auth")).to_have_text("API Key Header")
        expect(page.locator("#summary-rocksdb-target")).to_have_text("https://rocksdb.example.com/api")
        expect(page.locator("#summary-rocksdb-auth-scheme")).to_have_text("API Key Header")
        expect(page.locator("#summary-rocksdb-access")).to_have_text("Read-only")
        expect(page.locator("#summary-rocksdb-column-family")).to_have_text("events")
        expect(page.locator("#summary-rocksdb-max-results")).to_have_text("50")
        expect(page.locator("#summary-rocksdb-key-prefix-hints")).to_contain_text("event:")
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_workspace_rocksdb_action_modal_write_mode_and_errors(playwright):
    """Validate write-mode summary text and a failing connection test."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        def handle_rocksdb_test(route):
            route.fulfill(
                status=400,
                content_type="application/json",
                body='{"success": false, "error": "The RocksDB service returned HTTP 502."}'
            )

        page.route("**/api/plugins/test-rocksdb-connection", handle_rocksdb_test)

        _open_rocksdb_config_step(page)

        page.locator("#rocksdb-base-url").fill("https://rocksdb.internal/api")
        page.locator("#rocksdb-auth-scheme").select_option("bearer")
        page.locator("#rocksdb-auth-key").fill("bearer-token")
        page.locator("#rocksdb-read-only").select_option("false")

        page.locator("#rocksdb-test-connection-btn").click()
        expect(page.locator("#rocksdb-test-connection-result")).to_be_visible()
        expect(page.locator("#rocksdb-test-connection-alert")).to_contain_text("returned HTTP 502")

        page.locator("#plugin-modal-skip").click()

        expect(page.locator("#summary-rocksdb-section")).to_be_visible()
        expect(page.locator("#summary-rocksdb-access")).to_have_text("Reads and writes")
        expect(page.locator("#summary-rocksdb-auth-scheme")).to_have_text("Bearer Token")
        expect(page.locator("#summary-rocksdb-target")).to_have_text("https://rocksdb.internal/api")
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_workspace_rocksdb_action_modal_validation_messages(playwright):
    """Validate that incomplete RocksDB configurations surface inline errors."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        _open_rocksdb_config_step(page)

        # A missing base URL is rejected before any request is sent.
        page.locator("#rocksdb-test-connection-btn").click()
        expect(page.locator("#rocksdb-test-connection-result")).to_be_visible()
        expect(page.locator("#rocksdb-test-connection-alert")).to_contain_text(
            "RocksDB service base URL is required"
        )

        # A non-HTTP base URL is rejected.
        page.locator("#rocksdb-base-url").fill("ftp://rocks.example.com")
        page.locator("#rocksdb-test-connection-btn").click()
        expect(page.locator("#rocksdb-test-connection-alert")).to_contain_text(
            "must start with http:// or https://"
        )

        # A token-based scheme without a token is rejected.
        page.locator("#rocksdb-base-url").fill("https://rocksdb.example.com/api")
        page.locator("#rocksdb-auth-scheme").select_option("bearer")
        page.locator("#rocksdb-test-connection-btn").click()
        expect(page.locator("#rocksdb-test-connection-alert")).to_contain_text(
            "service token is required"
        )

        # Out-of-range numeric caps are rejected.
        page.locator("#rocksdb-auth-key").fill("token")
        page.locator("#rocksdb-max-results").fill("0")
        page.locator("#rocksdb-test-connection-btn").click()
        expect(page.locator("#rocksdb-test-connection-alert")).to_contain_text(
            "Max results must be between 1 and 1000"
        )
    finally:
        context.close()
        browser.close()
