# test_model_endpoint_request_uses_endpoint_id.py
"""
UI test for model endpoint request identity wiring.
Version: 0.250.006
Implemented in: 0.250.003; updated in 0.250.006

This test ensures the admin multi-endpoint modal exposes the supported
providers, shows the APIM provider guidance, handles Foundry API version
selection and project endpoint parsing, exposes setup guidance and model icon
picker controls, and sends the endpoint ID in the test-model request payload so
the backend can resolve Key Vault-backed secrets.
"""

import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_model_endpoint_request_uses_endpoint_id():
    """Validate that the endpoint modal includes the endpoint ID in test requests."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
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
            expect(page.get_by_test_id("model-endpoint-identity-guide-open")).to_be_visible()

            page.get_by_test_id("model-endpoint-identity-guide-open").click()
            expect(page.locator("#modelEndpointIdentityGuideModal")).to_be_visible()
            expect(page.get_by_role("heading", name="Model Endpoint Setup Guide")).to_be_visible()
            expect(page.get_by_text("Reader", exact=True).first).to_be_visible()
            expect(page.get_by_text("Cognitive Services OpenAI User", exact=True).first).to_be_visible()
            page.locator("#modelEndpointIdentityGuideModal button[aria-label='Close']").click()
            expect(page.locator("#modelEndpointIdentityGuideModal")).to_be_hidden()

            page.route("**/api/models/test-model", handle_test_request)

            page.locator("#add-model-endpoint-btn").click()
            expect(page.locator("#modelEndpointModal")).to_be_visible()
            expect(page.get_by_test_id("model-endpoint-inline-guidance-toggle")).to_be_visible()

            page.get_by_test_id("model-endpoint-inline-guidance-toggle").click()
            expect(page.locator("#model-endpoint-inline-guidance")).to_be_visible()
            expect(page.get_by_text("Azure OpenAI", exact=True).first).to_be_visible()
            expect(page.get_by_text("Foundry (classic)", exact=True).first).to_be_visible()
            expect(page.get_by_text("Use separate endpoints when Grok, Meta/Llama, DeepSeek")).to_be_visible()

            provider_options = page.locator("#model-endpoint-provider option").all_text_contents()
            assert provider_options == ["Azure OpenAI", "Foundry (classic)", "New Foundry"]
            expect(page.get_by_text("If using classic Foundry, use Foundry (classic). If using the application-based runtime, use New Foundry.")).to_be_visible()

            page.locator("#model-endpoint-provider").select_option("aifoundry")
            expect(page.locator("#model-endpoint-openai-api-version")).to_have_value("v1")

            page.locator("#model-endpoint-provider").select_option("new_foundry")
            expect(page.locator("#model-endpoint-endpoint-label")).to_have_text("Project Endpoint")
            expect(page.locator("#model-endpoint-openai-api-version")).to_have_value("v1")
            expect(page.locator("#model-endpoint-project-api-version")).to_have_value("v1")

            page.locator("#model-endpoint-openai-api-version").select_option("custom")
            expect(page.locator("#model-endpoint-openai-api-version-custom")).to_be_visible()
            page.locator("#model-endpoint-openai-api-version-custom").fill("preview")
            page.locator("#model-endpoint-project-api-version").select_option("custom")
            expect(page.locator("#model-endpoint-project-api-version-custom")).to_be_visible()
            page.locator("#model-endpoint-project-api-version-custom").fill("v2025-01-01")

            page.locator("#model-endpoint-endpoint").fill("https://eastus2.services.ai.azure.com/api/projects/project-eastus2-dev")
            expect(page.locator("#model-endpoint-project-group")).to_be_hidden()
            expect(page.locator("#model-endpoint-project-name")).to_have_value("project-eastus2-dev")

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
            page.locator("#model-endpoint-provider").select_option("aoai")
            page.locator("#model-endpoint-name").fill("Stored Endpoint")
            page.locator("#model-endpoint-endpoint").fill("https://example.openai.azure.com")
            page.locator("#model-endpoint-auth-type").select_option("api_key")
            page.locator("#model-endpoint-api-key").fill("temporary-ui-secret")
            page.locator("#model-endpoint-add-model-btn").click()
            page.locator("input[data-deployment-name-for]").first.fill("gpt-4o")
            expect(page.locator(".model-icon-preview").first).to_be_visible()
            expect(page.locator(".model-icon-picker-button").first).to_contain_text("bi-stars")
            page.locator(".model-icon-picker-button").first.click()
            expect(page.locator(".model-icon-picker-search").first).to_be_visible()
            page.locator(".model-icon-picker-search").first.fill("robot")
            expect(page.locator(".agent-icon-picker-option[data-icon-class='bi-robot']").first).to_be_visible()
            page.locator(".agent-icon-picker-option[data-icon-class='bi-robot']").first.click()
            expect(page.locator(".model-icon-picker-button").first).to_contain_text("bi-robot")
            page.locator(".model-icon-type-image").first.check()
            expect(page.locator(".model-icon-image-file").first).to_be_visible()
            page.locator(".model-icon-type-bootstrap").first.check()
            page.locator("button[data-action='test-model']").first.click()

            expect(page.locator("#modelEndpointModal")).to_be_visible()
            assert captured_request.get("id") == "stored-endpoint-123"
            assert captured_request.get("model", {}).get("deploymentName") == "gpt-4o"
        finally:
            context.close()
            browser.close()