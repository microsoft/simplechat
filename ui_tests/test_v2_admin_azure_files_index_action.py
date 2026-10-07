# test_v2_admin_azure_files_index_action.py
"""
UI test for the V2 Azure Files Search global action editor.
Version: 0.261.293
Implemented in: 0.261.293

This test ensures that the admin-only global action editor renders Azure Files
Search settings, enforces the permission-check warning flow, edits storage share
rows, and posts a global-scope connection test whose mocked checks are visible.
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

import v2_admin_global_editors as global_editors  # noqa: E402
from v2_admin_global_editors import GlobalEditorsFixture, ORIGIN  # noqa: E402


pytestmark = pytest.mark.ui
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app" / "static" / "json" / "schemas"


@pytest.fixture
def azure_ui(page, monkeypatch):
    def global_action_types():
        return [{
            "type": "azure_files_index",
            "display": "Azure Files Search",
            "description": "Search an existing Azure Files indexer index and return permitted files.",
            "allowed_auth_types": json.loads(
                (SCHEMA_ROOT / "azure_files_index.definition.json").read_text(encoding="utf-8")
            )["allowedAuthTypes"],
            "additional_fields_schema": json.loads(
                (SCHEMA_ROOT / "azure_files_index_plugin.additional_settings.schema.json").read_text(encoding="utf-8")
            ),
            "metadata_schema": {"type": "object", "properties": {}, "additionalProperties": True},
        }]

    monkeypatch.setattr(global_editors, "global_action_types", global_action_types)
    fixture = GlobalEditorsFixture(page)
    yield fixture
    fixture.assert_clean()


def _editor_section(page, label):
    page.get_by_role("navigation", name="Editor sections", exact=True).get_by_role(
        "button", name=label, exact=True
    ).click()


def _action_field(page, label):
    return page.get_by_label(re.compile(rf"^{re.escape(label)}(?:\s*\*)?\s*$"))


def test_admin_configures_azure_files_search_global_action(azure_ui):
    ui, page = azure_ui, azure_ui.page
    test_payloads = []

    def handle_connection(route):
        test_payloads.append(route.request.post_data_json)
        route.fulfill(
            json={
                "success": True,
                "message": "Azure Files Search connection checks completed.",
                "details": {
                    "checks": [
                        {"name": "Search index", "status": "pass", "message": "Index files-index is reachable."},
                        {"name": "Storage share", "status": "warn", "message": "RBAC check skipped in this test."},
                    ]
                },
                "warnings": ["Fixture warning shown to admins."],
            }
        )

    ui.extra_routes[("POST", "/api/plugins/test-azure-files-index-connection")] = handle_connection
    ui.open(ready_region="Global Actions")
    page.get_by_role("region", name="Global Actions", exact=True).get_by_role(
        "button", name="New action", exact=True
    ).click()
    expect(page).to_have_url(f"{ORIGIN}/v2/admin/actions/new")

    _action_field(page, "Action type").select_option("azure_files_index")
    _action_field(page, "Action name").fill("Azure Files handbook search")
    page.get_by_label("Description", exact=True).fill("Search indexed Azure Files with permission trimming.")
    _editor_section(page, "Configuration")

    _action_field(page, "Search service endpoint").fill("https://contoso.search.windows.net")
    _action_field(page, "Index name").fill("files-index")
    _action_field(page, "Index layout").select_option("chunked")
    _action_field(page, "Query mode").select_option("hybrid")
    expect(_action_field(page, "Vector field")).to_have_value("text_vector")

    _action_field(page, "Permission mode").select_option("none")
    expect(page.get_by_text("Everyone who can use this action can search every file in the index.").first).to_be_visible()
    page.get_by_role("button", name="Validate configuration", exact=True).click()
    expect(page.get_by_text("Acknowledge that everyone who can use this action can search every file in the index.").first).to_be_visible()
    page.get_by_role("checkbox", name="Everyone who can use this action can search every file in the index.").check()

    _action_field(page, "Permission mode").select_option("live_acl")
    page.get_by_role("button", name="Add storage share", exact=True).click()
    _action_field(page, "Storage account resource ID").fill(
        "/subscriptions/00000000-0000-4000-8000-000000000000/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/filesacct"
    )
    _action_field(page, "Share name").fill("documents")
    _action_field(page, "Share-level check").select_option("skip")
    page.get_by_text(re.compile(r"Treat BUILTIN")).click()

    _editor_section(page, "Authentication")
    page.get_by_role("button", name="Test connection", exact=True).click()
    authentication = page.get_by_label("Authentication", exact=True)
    expect(page.get_by_text("Azure Files Search connection checks completed.")).to_be_visible()
    expect(authentication.get_by_text("Search index")).to_be_visible()
    expect(authentication.get_by_text("Index files-index is reachable.")).to_be_visible()
    expect(authentication.get_by_text("Storage share")).to_be_visible()
    expect(authentication.get_by_text("RBAC check skipped in this test.")).to_be_visible()
    expect(page.get_by_text("Fixture warning shown to admins.")).to_be_visible()

    assert len(test_payloads) == 1
    payload = test_payloads[0]
    assert payload["action_scope"] == "global"
    assert payload["type"] == "azure_files_index"
    assert payload["endpoint"] == "https://contoso.search.windows.net"
    assert payload["auth"] == {"type": "identity", "identity": "managed_identity"}
    assert payload["additionalFields"]["query_mode"] == "hybrid"
    assert payload["additionalFields"]["permission_mode"] == "live_acl"
    assert payload["additionalFields"]["storage_shares"] == [{
        "storage_account_resource_id": "/subscriptions/00000000-0000-4000-8000-000000000000/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/filesacct",
        "share_name": "documents",
    }]
    assert urlsplit(page.url).path == "/v2/admin/actions/new"
