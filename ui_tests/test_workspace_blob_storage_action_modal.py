# test_workspace_blob_storage_action_modal.py
"""
UI test for the workspace Blob Storage action modal.
Version: 0.241.061
Implemented in: 0.241.061

This test ensures users can select the Blob Storage action type, configure a
container-scoped connection string plus prefix, review the capability summary,
and save the action through the shared workspace validation flow.
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
def test_workspace_blob_storage_action_modal(playwright):
    """Validate the workspace action modal exposes the Blob Storage-specific flow."""
    _require_ui_env()

    validation_requests = []
    admin_validation_requests = []
    saved_payloads = []
    connection_string = (
        "DefaultEndpointsProtocol=https;"
        "AccountName=sampleacct;"
        "AccountKey=ZmFrZUtleQ==;"
        "EndpointSuffix=core.windows.net"
    )

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    def handle_plugins(route):
        request = route.request
        if request.method == "GET":
          route.fulfill(status=200, content_type="application/json", body="[]")
          return

        saved_payloads.append(json.loads(request.post_data or "[]"))
        route.fulfill(status=200, content_type="application/json", body='{"success": true}')

    def handle_validation(route):
        validation_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"valid": true, "errors": [], "warnings": []}',
        )

    def handle_admin_validation(route):
        admin_validation_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=418,
            content_type="application/json",
            body='{"error": "unexpected admin validation route"}',
        )

    page.route("**/api/user/plugins", handle_plugins)
    page.route("**/api/plugins/validate", handle_validation)
    page.route("**/api/admin/plugins/validate", handle_admin_validation)

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

        blob_card = page.locator('.action-type-card[data-type="blob_storage"]')
        expect(blob_card).to_have_count(1)
        blob_card.click()

        modal.get_by_role("button", name="Next").click()
        page.locator("#plugin-display-name").fill("Markdown Blob Reader")
        modal.get_by_role("button", name="Next").click()

        expect(page.locator("#blob-storage-config-section")).to_be_visible()
        expect(page.locator("#generic-config-section")).to_be_hidden()
        expect(page.locator("#sql-config-section")).to_be_hidden()
        expect(page.locator("#cosmos-config-section")).to_be_hidden()

        page.locator("#blob-storage-connection-string").fill(connection_string)
        page.locator("#blob-storage-container-name").fill("knowledge-base")
        page.locator("#blob-storage-blob-prefix").fill("docs/markdown")

        list_toggle = page.locator("#blob-storage-capability-list_container_contents")
        read_toggle = page.locator("#blob-storage-capability-read_file_content")
        upload_toggle = page.locator("#blob-storage-capability-upload_file_to_container")
        expect(list_toggle).to_be_checked()
        expect(read_toggle).to_be_checked()
        expect(upload_toggle).not_to_be_checked()

        expect(page.locator("#blob-storage-read-file-types-section")).to_be_visible()
        expect(page.locator("#blob-storage-upload-file-types-section")).to_be_hidden()
        list_toggle.uncheck()
        upload_toggle.check()
        expect(page.locator("#blob-storage-upload-file-types-section")).to_be_visible()
        expect(page.locator("#blob-storage-read-file-type-markdown")).to_be_checked()
        expect(page.locator("#blob-storage-upload-file-type-markdown")).to_be_checked()

        page.locator("#plugin-modal-skip").click()

        expect(page.locator("#summary-blob-storage-section")).to_be_visible()
        expect(page.locator("#summary-plugin-database-type")).to_have_text("Azure Blob Storage container")
        expect(page.locator("#summary-plugin-auth")).to_have_text("Connection String")
        expect(page.locator("#summary-plugin-endpoint")).to_have_text("https://sampleacct.blob.core.windows.net")
        expect(page.locator("#summary-blob-storage-container-name")).to_have_text("knowledge-base")
        expect(page.locator("#summary-blob-storage-blob-prefix")).to_have_text("docs/markdown")
        expect(page.locator("#summary-blob-storage-enabled-list")).to_contain_text("Read file content")
        expect(page.locator("#summary-blob-storage-enabled-list")).to_contain_text("Upload file to container")
        expect(page.locator("#summary-blob-storage-disabled-list")).to_contain_text("List container contents")
        expect(page.locator("#summary-blob-storage-read-file-types")).to_have_text("Markdown")
        expect(page.locator("#summary-blob-storage-upload-file-types")).to_have_text("Markdown")

        modal.get_by_role("button", name="Save Action").click()

        expect(modal).to_be_hidden()
        assert len(validation_requests) == 1, "Expected the shared validation endpoint to be called once."
        assert not admin_validation_requests, "Workspace action save should not call the admin validation endpoint."
        assert len(saved_payloads) == 1, "Expected the workspace action save request to be submitted once."

        saved_plugin = saved_payloads[0][0]
        assert saved_plugin["type"] == "blob_storage"
        assert saved_plugin["name"] == "markdown_blob_reader"
        assert saved_plugin["endpoint"] == "https://sampleacct.blob.core.windows.net"
        assert saved_plugin["auth"]["type"] == "connection_string"
        assert saved_plugin["auth"]["key"] == connection_string

        additional_fields = saved_plugin["additionalFields"]
        assert additional_fields["container_name"] == "knowledge-base"
        assert additional_fields["blob_prefix"] == "docs/markdown"
        assert additional_fields["blob_storage_capabilities"]["list_container_contents"] is False
        assert additional_fields["blob_storage_capabilities"]["read_file_content"] is True
        assert additional_fields["blob_storage_capabilities"]["upload_file_to_container"] is True
        assert additional_fields["blob_storage_read_file_types"]["markdown"] is True
        assert additional_fields["blob_storage_upload_file_types"]["markdown"] is True
    finally:
        context.close()
        browser.close()