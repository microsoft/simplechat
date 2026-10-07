# test_admin_azure_files_index_action_modal.py
"""
UI test for the V1 Azure Files Search action modal.
Version: 0.261.294
Implemented in: 0.261.294

This test ensures that the admin-only Azure Files Search action modal renders
its dedicated fields, applies layout presets, enforces the permission warning,
manages storage share rows, collects the expected manifest, and safely renders
mocked connection-test checks.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}

AZURE_FILES_TYPE = {
    "type": "azure_files_index",
    "display": "Azure Files Search",
    "description": "Search an existing Azure AI Search index built from Azure Files.",
}


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _open_admin_actions_modal(page):
    response = page.goto(f"{BASE_URL}/admin/settings", wait_until="networkidle")
    assert response is not None, "Expected a navigation response when loading /admin/settings."

    if response.status in SKIP_RESPONSE_CODES:
        pytest.skip(f"Admin settings page unavailable in this environment (HTTP {response.status}).")

    assert response.ok, f"Expected /admin/settings to load successfully, got HTTP {response.status}."

    agents_group = page.locator('[data-admin-group-pill="agents-actions"]')
    if agents_group.count() > 0:
        agents_group.click()

    actions_tab = page.locator("#actions-tab")
    if actions_tab.count() > 0:
        actions_tab.click()

    add_button = page.locator("#add-plugin-btn")
    if add_button.count() == 0:
        pytest.skip("Global action creation is not available in this environment.")

    expect(add_button).to_be_visible()
    add_button.click()

    modal = page.locator("#plugin-modal")
    expect(modal).to_be_visible()
    return modal


@pytest.mark.ui
def test_admin_azure_files_index_action_modal():
    """Validate the admin Azure Files Search action modal workflow."""
    _require_ui_env()
    playwright_sync_api = pytest.importorskip("playwright.sync_api")
    expect = playwright_sync_api.expect

    connection_requests = []

    def handle_admin_plugins(route):
        if route.request.method == "GET":
            route.fulfill(status=200, content_type="application/json", body="[]")
            return
        route.fulfill(status=200, content_type="application/json", body='{"success": true}')

    def handle_types(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps([AZURE_FILES_TYPE]))

    def handle_connection_test(route):
        connection_requests.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "success": True,
                    "message": "Azure Files Search connection succeeded.",
                    "details": {
                        "checks": [
                            {
                                "name": "Search index <script>alert(1)</script>",
                                "status": "pass",
                                "message": "Index is reachable.",
                            },
                            {
                                "name": "Permissions",
                                "status": "warn",
                                "message": "One share needs role review.",
                            },
                        ]
                    },
                    "warnings": ["Review storage account role assignments."],
                }
            ),
        )

    with playwright_sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        page.route("**/api/admin/plugins", handle_admin_plugins)
        page.route("**/api/admin/plugins/types", handle_types)
        page.route("**/api/admin/workspace-identities/global**", lambda route: route.fulfill(status=200, content_type="application/json", body="[]"))
        page.route("**/api/plugins/test-azure-files-index-connection", handle_connection_test)

        try:
            modal = _open_admin_actions_modal(page)

            action_card = page.locator('.action-type-card[data-type="azure_files_index"]')
            expect(action_card).to_have_count(1)
            action_card.click()

            modal.get_by_role("button", name="Next").click()
            page.locator("#plugin-display-name").fill("Finance Files Search")
            modal.get_by_role("button", name="Next").click()

            expect(page.locator("#step-3-title")).to_have_text("Azure Files Search Configuration")
            expect(page.locator("#azure-files-index-config-section")).to_be_visible()
            expect(page.locator("#generic-config-section")).to_be_hidden()
            expect(page.locator("#cosmos-config-section")).to_be_hidden()
            expect(page.locator("#azure-files-index-content-field")).to_have_value("content")
            expect(page.locator("#azure-files-index-path-field")).to_have_value("metadata_storage_path")

            page.locator("#azure-files-index-layout").select_option("chunked")
            expect(page.locator("#azure-files-index-content-field")).to_have_value("chunk")
            expect(page.locator("#azure-files-index-vector-field")).to_have_value("text_vector")
            expect(page.locator("#azure-files-index-select-content")).to_be_checked()

            # Validation reports fields in form order, so fill the endpoint, index, and share first.
            page.locator("#azure-files-index-endpoint").fill("https://contoso-search.search.windows.net")
            page.locator("#azure-files-index-name").fill("finance-files")
            page.locator(".azure-files-index-share-resource-id").fill(
                "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/rg-finance/providers/Microsoft.Storage/storageAccounts/financefiles"
            )
            page.locator(".azure-files-index-share-name").fill("finance-share")

            page.locator("#azure-files-index-permission-mode").select_option("none")
            expect(page.locator("#azure-files-index-permission-none-warning")).to_be_visible()
            modal.get_by_role("button", name="Next").click()
            expect(page.locator("#plugin-modal-error")).to_contain_text("Acknowledge")

            page.locator("#azure-files-index-permission-none-ack").check()
            expect(page.locator("#azure-files-index-shares-list .azure-files-index-share-row")).to_have_count(1)
            page.locator("#azure-files-index-add-share-btn").click()
            expect(page.locator("#azure-files-index-shares-list .azure-files-index-share-row")).to_have_count(2)
            page.locator("#azure-files-index-shares-list .azure-files-index-remove-share-btn").last.click()
            expect(page.locator("#azure-files-index-shares-list .azure-files-index-share-row")).to_have_count(1)

            page.locator("#azure-files-index-query-mode").select_option("hybrid")

            page.locator("#azure-files-index-test-connection-btn").click()
            expect(page.locator("#azure-files-index-test-connection-alert")).to_have_class("alert alert-success mb-0 py-2 px-3 small")
            expect(page.locator("#azure-files-index-test-connection-alert")).to_contain_text("Azure Files Search connection succeeded")
            expect(page.locator("#azure-files-index-test-connection-alert")).to_contain_text("Search index <script>alert(1)</script>")
            assert "<script>alert(1)</script>" not in page.locator("#azure-files-index-test-connection-alert").inner_html()
            connection_alert = page.locator("#azure-files-index-test-connection-alert")
            expect(connection_alert.locator(".badge.text-bg-success")).to_have_count(1)
            expect(connection_alert.locator(".badge.text-bg-warning")).to_have_count(1)
            expect(connection_alert.locator(".badge.text-bg-danger")).to_have_count(0)
            assert len(connection_requests) == 1, "Expected one Azure Files Search connection test request."

            submitted_test = connection_requests[0]
            assert submitted_test["type"] == "azure_files_index"
            assert submitted_test["action_scope"] == "global"
            assert submitted_test["additionalFields"]["index_name"] == "finance-files"

            manifest = page.evaluate("window.pluginModalStepper.getFormData()")
            assert manifest["type"] == "azure_files_index"
            assert manifest["endpoint"] == "https://contoso-search.search.windows.net"
            assert manifest["auth"] == {"type": "identity", "identity": "managed_identity"}
            assert manifest["additionalFields"]["index_layout"] == "chunked"
            assert manifest["additionalFields"]["query_mode"] == "hybrid"
            assert manifest["additionalFields"]["permission_mode"] == "none"
            assert manifest["additionalFields"]["permission_mode_none_acknowledged"] is True
            assert manifest["additionalFields"]["storage_shares"] == [
                {
                    "storage_account_resource_id": "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/rg-finance/providers/Microsoft.Storage/storageAccounts/financefiles",
                    "share_name": "finance-share",
                }
            ]

            page.locator("#plugin-modal-skip").click()
            expect(page.locator("#summary-azure-files-index-section")).to_be_visible()
            expect(page.locator("#summary-plugin-database-type")).to_have_text("Azure AI Search index over Azure Files")
            expect(page.locator("#summary-plugin-auth")).to_have_text("Managed Identity")
            expect(page.locator("#summary-azure-files-index-layout")).to_have_text("Chunked with vectors")
        finally:
            context.close()
            browser.close()
