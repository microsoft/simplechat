# test_model_endpoint_request_uses_endpoint_id.py
"""
UI test for model endpoint request identity wiring.
Version: 0.239.155
Implemented in: 0.239.155

This test ensures the admin multi-endpoint modal sends the endpoint ID in the
test-model request payload so the backend can resolve Key Vault-backed secrets.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_model_endpoint_request_uses_endpoint_id(playwright):
    """Validate that the endpoint modal includes the endpoint ID in test requests."""
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
    captured_request = {}

    def handle_test_request(route):
        post_data = route.request.post_data_json or {}
        captured_request.update(post_data)
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true}',
        )

    try:
        page.goto(f"{BASE_URL}/admin/settings", wait_until="networkidle")
        expect(page.locator("#add-model-endpoint-btn")).to_be_visible()

        page.route("**/api/models/test-model", handle_test_request)

        page.locator("#add-model-endpoint-btn").click()
        expect(page.locator("#modelEndpointModal")).to_be_visible()

        page.evaluate(
            """
            () => {
                const endpointId = document.getElementById('model-endpoint-id');
                if (endpointId) {
                    endpointId.value = 'stored-endpoint-123';
                }
            }
            """
        )
        page.locator("#model-endpoint-name").fill("Stored Endpoint")
        page.locator("#model-endpoint-endpoint").fill("https://example.openai.azure.com")
        page.locator("#model-endpoint-auth-type").select_option("api_key")
        page.locator("#model-endpoint-api-key").fill("temporary-ui-secret")
        page.locator("#model-endpoint-add-model-btn").click()
        page.locator("input[data-deployment-name-for]").first.fill("gpt-4o")
        page.locator("button[data-action='test-model']").first.click()

        expect(page.locator("#modelEndpointModal")).to_be_visible()
        assert captured_request.get("id") == "stored-endpoint-123"
        assert captured_request.get("model", {}).get("deploymentName") == "gpt-4o"
    finally:
        context.close()
        browser.close()