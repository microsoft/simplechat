# test_workspace_document_search_action_modal.py
"""
UI test for the workspace document search action modal.
Version: 0.241.024
Implemented in: 0.241.024

This test ensures users can select the internal document search action type,
configure search-specific defaults instead of an external URL, survive a 404
from the optional validation endpoint, and review the document-search summary
card before saving.
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
def test_workspace_document_search_action_modal(playwright):
    """Validate the workspace action modal exposes the document-search-specific flow."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    saved_payloads = []

    def handle_user_plugins(route):
        if route.request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body="[]"
            )
            return

        request_body = route.request.post_data or "[]"
        saved_payloads.clear()
        saved_payloads.extend(json.loads(request_body))
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"success": true}'
        )

    page.route("**/api/plugins/validate", lambda route: route.fulfill(
        status=404,
        content_type="text/html",
        body="<!doctype html><html lang=en><title>404 Not Found</title><h1>Not Found</h1>"
    ))
    page.route("**/api/user/plugins", handle_user_plugins)

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
        create_button.click()

        modal = page.locator("#plugin-modal")
        expect(modal).to_be_visible()

        search_card = page.locator('.action-type-card[data-type="search"]')
        if search_card.count() == 0:
            pytest.skip("Document search action type is not available in this environment.")

        search_card.click()
        modal.get_by_role("button", name="Next").click()

        page.locator("#plugin-display-name").fill("Workspace Search")
        modal.get_by_role("button", name="Next").click()

        expect(page.locator("#document-search-config-section")).to_be_visible()
        expect(page.locator("#generic-config-section")).to_be_hidden()
        expect(page.locator("#sql-config-section")).to_be_hidden()
        expect(page.locator("#cosmos-config-section")).to_be_hidden()

        expect(page.locator("#document-search-scope")).to_have_value("all")
        expect(page.locator("#document-search-top-n")).to_have_value("12")
        expect(page.locator("#document-search-window-unit")).to_have_value("pages")

        page.locator("#document-search-scope").select_option("group")
        page.locator("#document-search-top-n").fill("24")
        page.locator("#document-search-window-unit").select_option("chunks")
        page.locator("#document-search-window-size").fill("6")
        page.locator("#document-search-window-percent").fill("25")
        page.locator("#document-search-focus-instructions").fill("Compare versions and highlight differences that matter to the assigned knowledge set.")
        page.locator("#document-search-window-target-length").fill("1 page")
        page.locator("#document-search-final-target-length").fill("3 pages")

        page.locator("#plugin-modal-skip").click()

        expect(page.locator("#summary-plugin-endpoint-row")).to_be_hidden()
        expect(page.locator("#summary-plugin-auth")).to_have_text("Internal user context")
        expect(page.locator("#summary-plugin-database-type")).to_have_text("Internal document search")
        expect(page.locator("#summary-document-search-section")).to_be_visible()
        expect(page.locator("#summary-search-scope")).to_have_text("Group Workspaces")
        expect(page.locator("#summary-search-top-n")).to_have_text("24")
        expect(page.locator("#summary-search-chunk-behavior")).to_have_text("Returns all chunks by default")
        expect(page.locator("#summary-search-windowing")).to_have_text("Chunks (6 per window)")
        expect(page.locator("#summary-search-window-target-length")).to_have_text("1 page")
        expect(page.locator("#summary-search-final-target-length")).to_have_text("3 pages")
        expect(page.locator("#summary-search-focus-instructions")).to_contain_text("assigned knowledge set")

        page.locator("#save-plugin-btn").click()
        expect(page.locator("#plugin-modal")).to_be_hidden()
        assert len(saved_payloads) == 1
        saved_plugin = saved_payloads[0]
        assert saved_plugin["type"] in {"search", "document_search"}
        assert saved_plugin["endpoint"] == "internal://document-search"
        assert saved_plugin["auth"]["type"] == "NoAuth"
        assert saved_plugin["additionalFields"]["default_doc_scope"] == "group"
        assert saved_plugin["additionalFields"]["default_top_n"] == 24
        assert saved_plugin["additionalFields"]["default_window_unit"] == "chunks"
        assert saved_plugin["additionalFields"]["default_window_size"] == 6
        assert saved_plugin["additionalFields"]["default_window_percent"] == 25
    finally:
        context.close()
        browser.close()