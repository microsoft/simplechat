# test_workspace_cosmos_action_modal.py
"""
UI test for the workspace Cosmos action modal.
Version: 0.241.024
Implemented in: 0.241.024

This test ensures users can select the Cosmos query action type, complete the
dedicated Cosmos configuration form, switch to account-key authentication, run
the browser-side connection test, and see the Cosmos summary card before saving.
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


@pytest.mark.ui
def test_workspace_cosmos_action_modal(playwright):
    """Validate the workspace action modal exposes the Cosmos-specific flow."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
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

        captured_payload = {}

        def handle_cosmos_test(route):
            request_body = route.request.post_data or "{}"
            captured_payload.clear()
            captured_payload.update(json.loads(request_body))
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"success": true, "message": "Successfully connected to Cosmos DB container documents in database SimpleChat."}'
            )

        page.route(
            "**/api/plugins/test-cosmos-connection",
            handle_cosmos_test
        )

        create_button.click()

        modal = page.locator("#plugin-modal")
        expect(modal).to_be_visible()

        cosmos_card = page.locator('.action-type-card[data-type="cosmos_query"]')
        expect(cosmos_card).to_have_count(1)
        cosmos_card.click()

        modal.get_by_role("button", name="Next").click()

        page.locator("#plugin-display-name").fill("Cosmos Reader")
        modal.get_by_role("button", name="Next").click()

        expect(page.locator("#cosmos-config-section")).to_be_visible()
        expect(page.locator("#sql-config-section")).to_be_hidden()
        expect(page.locator("#generic-config-section")).to_be_hidden()

        page.locator("#cosmos-endpoint").fill("https://contoso.documents.azure.com:443/")
        page.locator("#cosmos-database-name").fill("SimpleChat")
        page.locator("#cosmos-container-name").fill("documents")
        page.locator("#cosmos-partition-key-path").fill("/tenant_id")
        page.locator("#cosmos-auth-type").select_option("key")
        expect(page.locator("#cosmos-auth-key-group")).to_be_visible()
        page.locator("#cosmos-auth-key").fill("primary-key-value")
        page.locator("#cosmos-field-hints").fill("id\ntitle\ntenant_id")
        page.locator("#cosmos-max-items").fill("50")
        page.locator("#cosmos-timeout").fill("20")

        page.locator("#cosmos-test-connection-btn").click()
        expect(page.locator("#cosmos-test-connection-result")).to_be_visible()
        expect(page.locator("#cosmos-test-connection-alert")).to_contain_text("Successfully connected to Cosmos DB container documents")
        assert captured_payload.get("auth_type") == "key"
        assert captured_payload.get("auth_key") == "primary-key-value"

        page.locator("#plugin-modal-skip").click()

        expect(page.locator("#summary-cosmos-section")).to_be_visible()
        expect(page.locator("#summary-plugin-database-type")).to_have_text("Cosmos DB for NoSQL")
        expect(page.locator("#summary-plugin-auth")).to_have_text("Account Key")
        expect(page.locator("#summary-cosmos-auth-type")).to_have_text("Account Key")
        expect(page.locator("#summary-cosmos-database-name")).to_have_text("SimpleChat")
        expect(page.locator("#summary-cosmos-container-name")).to_have_text("documents")
        expect(page.locator("#summary-cosmos-partition-key-path")).to_have_text("/tenant_id")
        expect(page.locator("#summary-cosmos-field-hints")).to_contain_text("tenant_id")
    finally:
        context.close()
        browser.close()