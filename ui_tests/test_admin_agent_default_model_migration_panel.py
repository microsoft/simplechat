# test_admin_agent_default_model_migration_panel.py
"""
UI test for admin agent default-model migration panel.

Version: 0.240.073
Implemented in: 0.240.073

This test ensures the admin settings page renders the AI Models migration
controls for reviewing and selectively rebinding legacy agents.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_admin_agent_default_model_migration_panel(playwright):
    """Validate that the admin AI Models page includes the migration workflow controls."""
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

    try:
        response = page.goto(f"{BASE_URL}/admin/settings#ai-models", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /admin/settings."
        assert response.ok, f"Expected /admin/settings to load successfully, got HTTP {response.status}."

        ai_models_nav = page.locator('[data-bs-target="#ai-models"], [data-tab="ai-models"]').first
        if ai_models_nav.count() > 0:
            ai_models_nav.click()

        expect(page.locator("#multi-endpoint-configuration")).to_be_visible()
        expect(page.locator("#preview-agent-default-model-migration-btn")).to_have_count(1)
        expect(page.locator("#agentDefaultModelMigrationModal")).to_have_count(1)
        expect(page.locator("#agent-default-model-migration-search")).to_have_count(1)
        expect(page.locator("#run-agent-default-model-migration-btn")).to_have_count(1)
    finally:
        context.close()
        browser.close()