# test_admin_azure_files_index_action_modal_static.py
"""
UI test for the V1 Azure Files Search action modal on a local static harness.

Version: 0.261.293
Implemented in: 0.261.293

This test runs the real `_plugin_modal.html` partial and the real `plugin_modal_stepper.js`
module in Chromium, served from a local static server with mocked API routes, so it needs no
running app, sign-in, or Azure access. It ensures that an administrator can configure an
Azure Files Search global action (layout presets, the permission-check acknowledgment, storage
share rows, and an Azure Government search endpoint), that the connection test renders pass,
warn, and fail checks as text with matching status badges, that invalid endpoints are refused
before any request is sent, and that editing a saved action keeps its stored values while
showing the layout defaults for blank field names.
"""

import json
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURES_DIR))

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Install Playwright to run this UI test.")

from agent_delegation_classic.harness import (  # noqa: E402
    build_plugin_modal_page,
    read_partial,
    register_static_passthrough,
    start_static_test_server,
)

expect = playwright_sync.expect

AZURE_FILES_TYPE = {
    "type": "azure_files_index",
    "display": "Azure Files Search",
    "description": "Search an existing Azure AI Search index built from Azure Files.",
}
FINANCE_ACCOUNT = (
    "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/rg-finance"
    "/providers/Microsoft.Storage/storageAccounts/financefiles"
)
HR_ACCOUNT = (
    "/subscriptions/11111111-2222-3333-4444-555555555555/resourceGroups/rg-hr"
    "/providers/Microsoft.Storage/storageAccounts/hrfiles"
)
SCRIPT_NAME = "Search index <script>window.__xssFired=true</script>"


def _json_route(route, payload, status=200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


@pytest.fixture
def harness():
    """Open a page hosting the real action modal in the admin (global) action scope."""
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        connection_requests = []
        try:
            with start_static_test_server() as server_base_url:
                # Routes run newest first, so this catch-all only answers API calls no test mocks.
                page.route("**/api/**", lambda route: _json_route(route, {"error": "Not mocked."}, status=404))
                register_static_passthrough(page)
                page.route("**/api/admin/plugins/types", lambda route: _json_route(route, [AZURE_FILES_TYPE]))
                page.route("**/api/admin/workspace-identities/global**", lambda route: _json_route(route, []))
                response = page.goto(server_base_url, wait_until="domcontentloaded")
                assert response is not None and response.ok
                page.set_content(build_plugin_modal_page(read_partial("_plugin_modal.html")))
                page.wait_for_function("() => window.__pluginModalHarnessReady === true && !!window.pluginModalStepper")
                page.evaluate(
                    "(cfg) => window.pluginModalStepper.setActionScope(cfg)",
                    {"scope": "global", "apiBase": "/api/admin/workspace-identities/global"},
                )
                yield page, page_errors, connection_requests
        finally:
            browser.close()


def _mock_connection_test(page, connection_requests, payload, status=200):
    def handler(route):
        connection_requests.append(json.loads(route.request.post_data or "{}"))
        _json_route(route, payload, status=status)

    page.route("**/api/plugins/test-azure-files-index-connection", handler)


def _show_modal(page, plugin=None):
    page.evaluate("async (plugin) => { await window.pluginModalStepper.showModal(plugin); return true; }", plugin)
    expect(page.locator("#plugin-modal")).to_be_visible()


def _open_new_azure_files_action(page):
    modal = page.locator("#plugin-modal")
    _show_modal(page)
    page.locator('.action-type-card[data-type="azure_files_index"]').click()
    modal.get_by_role("button", name="Next").click()
    page.locator("#plugin-display-name").fill("Finance Files Search")
    modal.get_by_role("button", name="Next").click()
    expect(page.locator("#step-3-title")).to_have_text("Azure Files Search Configuration")
    expect(page.locator("#azure-files-index-config-section")).to_be_visible()
    return modal


def _fill_required_fields(page, endpoint):
    page.locator("#azure-files-index-endpoint").fill(endpoint)
    page.locator("#azure-files-index-name").fill("finance-files")
    page.locator(".azure-files-index-share-resource-id").first.fill(FINANCE_ACCOUNT)
    page.locator(".azure-files-index-share-name").first.fill("finance-share")


@pytest.mark.ui
def test_admin_configures_azure_files_search_action(harness):
    """Create flow: presets, acknowledgment, share rows, Government endpoint, checks, manifest, summary."""
    page, page_errors, connection_requests = harness
    _mock_connection_test(page, connection_requests, {
        "success": True,
        "message": "Azure Files Search can query the index and check file permissions.",
        "details": {"checks": [
            {"name": SCRIPT_NAME, "status": "pass", "message": "SimpleChat queried the index."},
            {"name": "file_permissions:financefiles/finance-share", "status": "warn",
             "message": "No sample document came from financefiles/finance-share."},
        ]},
    })
    modal = _open_new_azure_files_action(page)

    expect(page.locator("#generic-config-section")).to_be_hidden()
    expect(page.locator("#azure-files-index-content-field")).to_have_value("content")
    expect(page.locator("#azure-files-index-path-field")).to_have_value("metadata_storage_path")
    expect(page.locator("#azure-files-index-select-content")).not_to_be_checked()

    page.locator("#azure-files-index-layout").select_option("chunked")
    expect(page.locator("#azure-files-index-content-field")).to_have_value("chunk")
    expect(page.locator("#azure-files-index-title-field")).to_have_value("title")
    expect(page.locator("#azure-files-index-vector-field")).to_have_value("text_vector")
    expect(page.locator("#azure-files-index-select-content")).to_be_checked()

    # Azure Government search endpoints use the search.azure.us suffix.
    _fill_required_fields(page, "https://contoso-search.search.azure.us")

    page.locator("#azure-files-index-permission-mode").select_option("none")
    expect(page.locator("#azure-files-index-permission-none-warning")).to_be_visible()
    modal.get_by_role("button", name="Next").click()
    expect(page.locator("#plugin-modal-error")).to_contain_text("Acknowledge")
    page.locator("#azure-files-index-permission-none-ack").check()

    shares = page.locator("#azure-files-index-shares-list .azure-files-index-share-row")
    expect(shares).to_have_count(1)
    page.locator("#azure-files-index-add-share-btn").click()
    expect(shares).to_have_count(2)
    page.locator("#azure-files-index-shares-list .azure-files-index-remove-share-btn").last.click()
    expect(shares).to_have_count(1)

    page.locator("#azure-files-index-query-mode").select_option("hybrid")

    page.locator("#azure-files-index-test-connection-btn").click()
    alert = page.locator("#azure-files-index-test-connection-alert")
    expect(alert).to_contain_text("Azure Files Search can query the index and check file permissions.")
    expect(alert).to_have_class("alert alert-success mb-0 py-2 px-3 small")
    expect(alert).to_contain_text(SCRIPT_NAME)
    expect(alert.locator(".badge.text-bg-success")).to_have_count(1)
    expect(alert.locator(".badge.text-bg-warning")).to_have_count(1)
    expect(alert.locator(".badge.text-bg-danger")).to_have_count(0)
    assert "<script>" not in alert.inner_html()
    assert page.evaluate("window.__xssFired !== true")

    assert len(connection_requests) == 1
    submitted = connection_requests[0]
    assert submitted["type"] == "azure_files_index"
    assert submitted["action_scope"] == "global"
    assert submitted["endpoint"] == "https://contoso-search.search.azure.us"

    manifest = page.evaluate("window.pluginModalStepper.getFormData()")
    fields = manifest["additionalFields"]
    assert manifest["type"] == "azure_files_index"
    assert manifest["endpoint"] == "https://contoso-search.search.azure.us"
    assert manifest["auth"] == {"type": "identity", "identity": "managed_identity"}
    assert fields["index_name"] == "finance-files"
    assert fields["index_layout"] == "chunked"
    assert fields["content_field"] == "chunk" and fields["vector_field"] == "text_vector"
    assert fields["select_content"] is True
    assert fields["query_mode"] == "hybrid"
    assert fields["permission_mode"] == "none" and fields["permission_mode_none_acknowledged"] is True
    assert fields["storage_shares"] == [{"storage_account_resource_id": FINANCE_ACCOUNT, "share_name": "finance-share"}]

    page.locator("#plugin-modal-skip").click()
    expect(page.locator("#summary-azure-files-index-section")).to_be_visible()
    expect(page.locator("#summary-azure-files-index-layout")).to_have_text("Chunked with vectors")
    assert page_errors == []


@pytest.mark.ui
def test_connection_test_failures_are_visible_and_invalid_endpoints_are_refused(harness):
    """Failure states: a failed check renders a danger badge, and a non-Search endpoint never calls the server."""
    page, page_errors, connection_requests = harness
    _mock_connection_test(page, connection_requests, {
        "success": False,
        "error": "Give SimpleChat's managed identity the Search Index Data Reader role on this search service.",
        "details": {"checks": [
            {"name": "configuration", "status": "pass", "message": "The configuration is valid."},
            {"name": "search_access", "status": "fail",
             "message": "Give SimpleChat's managed identity the Search Index Data Reader role on this search service."},
        ]},
    }, status=400)
    _open_new_azure_files_action(page)
    alert = page.locator("#azure-files-index-test-connection-alert")

    _fill_required_fields(page, "https://contoso.blob.core.windows.net")
    page.locator("#azure-files-index-test-connection-btn").click()
    expect(alert).to_contain_text("Azure AI Search URL")
    assert connection_requests == []

    page.locator("#azure-files-index-endpoint").fill("https://contoso-search.search.windows.net")
    page.locator("#azure-files-index-test-connection-btn").click()
    expect(alert).to_contain_text("Search Index Data Reader")
    expect(alert).to_have_class("alert alert-danger mb-0 py-2 px-3 small")
    expect(alert.locator(".badge.text-bg-success")).to_have_count(1)
    expect(alert.locator(".badge.text-bg-danger")).to_have_count(1)
    assert len(connection_requests) == 1
    assert page_errors == []


@pytest.mark.ui
def test_editing_keeps_stored_values_and_shows_layout_defaults(harness):
    """Edit flow: stored values win, blank field names show the layout defaults the server uses."""
    page, page_errors, _connection_requests = harness
    stored = {
        "id": "action-1",
        "name": "finance_files",
        "displayName": "Finance Files",
        "description": "Finance share search",
        "type": "azure_files_index",
        "endpoint": "https://contoso-search.search.windows.net",
        "auth": {"type": "identity", "identity": "managed_identity"},
        "metadata": {},
        "additionalFields": {
            "index_name": "finance-chunks",
            "index_layout": "chunked",
            "content_field": "body_text",
            "title_field": "",
            "path_field": "",
            "name_field": "metadata_storage_name",
            "last_modified_field": "",
            "vector_field": "",
            "select_content": False,
            "query_mode": "semantic",
            "semantic_configuration": "default",
            "default_top_n": 7,
            "max_candidates": 60,
            "max_snippet_chars": 900,
            "time_budget_seconds": 30,
            "permission_mode": "live_acl",
            "permission_mode_none_acknowledged": False,
            "share_access_check": "skip",
            "treat_builtin_users_as_member": True,
            "storage_shares": [
                {"storage_account_resource_id": FINANCE_ACCOUNT, "share_name": "finance-share"},
                {"storage_account_resource_id": HR_ACCOUNT, "share_name": "hr-share"},
            ],
        },
    }
    modal = page.locator("#plugin-modal")
    _show_modal(page, stored)
    modal.get_by_role("button", name="Next").click()
    expect(page.locator("#azure-files-index-config-section")).to_be_visible()

    expect(page.locator("#azure-files-index-layout")).to_have_value("chunked")
    expect(page.locator("#azure-files-index-content-field")).to_have_value("body_text")
    expect(page.locator("#azure-files-index-title-field")).to_have_value("title")
    expect(page.locator("#azure-files-index-path-field")).to_have_value("metadata_storage_path")
    expect(page.locator("#azure-files-index-vector-field")).to_have_value("text_vector")
    expect(page.locator("#azure-files-index-select-content")).not_to_be_checked()
    expect(page.locator("#azure-files-index-query-mode")).to_have_value("semantic")
    expect(page.locator("#azure-files-index-share-access-check")).to_have_value("skip")
    expect(page.locator("#azure-files-index-builtin-users")).to_be_checked()
    expect(page.locator("#azure-files-index-default-top-n")).to_have_value("7")
    expect(page.locator("#azure-files-index-shares-list .azure-files-index-share-row")).to_have_count(2)

    fields = page.evaluate("window.pluginModalStepper.getFormData()")["additionalFields"]
    assert fields["content_field"] == "body_text"
    assert fields["title_field"] == "title" and fields["path_field"] == "metadata_storage_path"
    assert fields["vector_field"] == "text_vector"
    assert fields["select_content"] is False
    assert fields["share_access_check"] == "skip" and fields["treat_builtin_users_as_member"] is True
    assert fields["default_top_n"] == 7 and fields["time_budget_seconds"] == 30
    assert fields["storage_shares"] == stored["additionalFields"]["storage_shares"]

    # A record saved before select_content existed opens with the layout's default.
    older = json.loads(json.dumps(stored))
    del older["additionalFields"]["select_content"]
    _show_modal(page, older)
    modal.get_by_role("button", name="Next").click()
    expect(page.locator("#azure-files-index-select-content")).to_be_checked()
    assert page_errors == []
