# test_admin_multimedia_guidance.py
"""
UI test for admin multimedia guidance and shared Speech controls.

Version: 0.241.010
Implemented in: 0.241.010

This test ensures the Search & Extract admin tab exposes the Video Indexer
cloud selector, the AI Voice setup guide, and the shared Speech managed-identity fields.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "")


def _require_base_url():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _require_storage_state():
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE to a valid authenticated Playwright storage state file.")


@pytest.mark.ui
def test_admin_multimedia_guidance(playwright):
    """Validate the admin multimedia panel guidance and dynamic shared Speech fields."""
    _require_base_url()
    _require_storage_state()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = context.new_page()
        response = page.goto(f"{BASE_URL}/admin/settings#search-extract", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /admin/settings."
        if response.status in {401, 403, 404}:
            pytest.skip("Admin settings page was not available for the configured admin session.")

        assert response.ok, f"Expected /admin/settings to load successfully, got HTTP {response.status}."

        search_extract_nav = page.locator('[data-bs-target="#search-extract"], [data-tab="search-extract"]').first
        if search_extract_nav.count() > 0:
            search_extract_nav.click()

        expect(page.locator("#video_indexer_cloud")).to_have_count(1)
        expect(page.locator("#video_indexer_endpoint_display")).to_have_count(1)

        video_toggle = page.locator("#enable_video_file_support")
        if not video_toggle.is_checked():
            video_toggle.check(force=True)

        expect(page.locator("#video_indexer_settings")).to_be_visible()

        page.locator("#video_indexer_cloud").select_option("custom")
        expect(page.locator("#video_indexer_custom_endpoint_group")).to_be_visible()

        custom_endpoint = "https://video-indexer.contoso.example"
        page.locator("#video_indexer_custom_endpoint").fill(custom_endpoint)
        expect(page.locator("#video_indexer_endpoint_display")).to_have_value(custom_endpoint)

        modal_trigger = page.locator('[data-bs-target="#videoIndexerInfoModal"]').first
        expect(modal_trigger).to_have_count(1)
        modal_trigger.click()
        expect(page.locator("#videoIndexerInfoModal")).to_be_visible()
        expect(page.locator("#videoIndexerInfoModal")).to_contain_text("App Service system-assigned managed identity")
        page.locator('#videoIndexerInfoModal button[data-bs-dismiss="modal"]').click()

        tts_toggle = page.locator("#enable_text_to_speech")
        if not tts_toggle.is_checked():
            tts_toggle.check(force=True)

        expect(page.locator("#audio_service_settings")).to_be_visible()
        page.locator("#speech_service_authentication_type").select_option("managed_identity")
        expect(page.locator("#speech_service_resource_id_container")).to_be_visible()
        expect(page.locator("#speech_service_key_container")).not_to_be_visible()

        page.locator("#speech_service_subscription_id").fill("12345678-1234-1234-1234-123456789abc")
        page.locator("#speech_service_resource_group").fill("rg-speech-prod")
        page.locator("#speech_service_resource_name").fill("my-speech-resource")
        expect(page.locator("#speech_service_resource_id")).to_have_value(
            "/subscriptions/12345678-1234-1234-1234-123456789abc/resourceGroups/rg-speech-prod/providers/Microsoft.CognitiveServices/accounts/my-speech-resource"
        )

        page.locator('[data-bs-target="#speechServiceInfoModal"]').click()
        expect(page.locator("#speechServiceInfoModal")).to_be_visible()
        expect(page.locator("#speechServiceInfoModal")).to_contain_text("Cognitive Services Speech User")
        expect(page.locator("#speechServiceInfoModal")).to_contain_text("Generate Custom Domain Name")
        expect(page.locator("#speechServiceInfoModal")).to_contain_text("Keys and Endpoint")
        expect(page.locator("#speechServiceInfoModal")).to_contain_text("my-speech-resource")
    finally:
        context.close()
        browser.close()
