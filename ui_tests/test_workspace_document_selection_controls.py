# test_workspace_document_selection_controls.py
"""
UI test for workspace document selection controls.
Version: 0.241.125
Implemented in: 0.241.087; 0.241.125

This test ensures personal and group workspaces expose select-all controls in
list and folder-grid document tables, and that the 100/250 page-size options
work through the browser-rendered experience. It also validates that header
select-all checkboxes are enabled immediately after entering multi-select mode.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}


def _require_ui_env() -> None:
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _fulfill_json(route, payload, status=200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


def _option_values(page, selector: str) -> list[str]:
    return page.locator(f"{selector} option").evaluate_all("elements => elements.map(element => element.value)")


def _open_select_action(page, dropdown_button_selector: str) -> None:
    page.locator(dropdown_button_selector).first().click()
    page.get_by_role("link", name="Select").click()


def _workspace_documents_payload() -> dict:
    return {
        "documents": [
            {
                "id": "doc-alpha",
                "title": "Alpha Brief",
                "file_name": "alpha-brief.md",
                "status": "complete",
                "percentage_complete": 100,
                "user_id": "user-1",
                "shared_user_ids": [],
                "tags": ["alpha"],
                "document_classification": "",
                "authors": [],
                "keywords": [],
            },
            {
                "id": "doc-beta",
                "title": "Beta Summary",
                "file_name": "beta-summary.md",
                "status": "complete",
                "percentage_complete": 100,
                "user_id": "user-1",
                "shared_user_ids": [],
                "tags": ["alpha"],
                "document_classification": "",
                "authors": [],
                "keywords": [],
            },
        ],
        "page": 1,
        "page_size": 10,
        "total_count": 2,
    }


@pytest.mark.ui
def test_personal_workspace_document_selection_controls(playwright):
    """Validate personal workspace select-all behavior in list and folder-grid views."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    docs_payload = _workspace_documents_payload()
    tags_payload = {"tags": [{"name": "alpha", "color": "#0d6efd", "count": 2}]}

    page.route("**/api/documents?*", lambda route: _fulfill_json(route, docs_payload))
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, tags_payload))

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /workspace."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        page.wait_for_function(
            """
            () => document.querySelectorAll('#documents-table tbody tr.document-row').length === 2
            """
        )

        assert "100" in _option_values(page, "#docs-page-size-select")
        assert "250" in _option_values(page, "#docs-page-size-select")
        assert "100" in _option_values(page, "#grid-page-size-select")
        assert "250" in _option_values(page, "#grid-page-size-select")

        page.locator("#workspace-toggle-selection-btn").click()
        select_all = page.locator("#docs-select-all-checkbox")
        expect(select_all).to_be_visible()
        expect(select_all).to_be_enabled()
        select_all.check()
        expect(page.locator("#selectedCount")).to_have_text("2")

        page.evaluate("window.toggleSelectionMode()")
        page.locator('label[for="docs-view-grid"]').click()

        page.wait_for_function(
            """
            () => document.querySelector('#tag-folders-container .tag-folder-card[data-tag="alpha"]') !== null
            """
        )
        page.locator('#tag-folders-container .tag-folder-card[data-tag="alpha"]').click()

        page.wait_for_function(
            """
            () => document.querySelector('#folder-docs-table') !== null
            """
        )

        assert "100" in _option_values(page, "#folder-page-size-select")
        assert "250" in _option_values(page, "#folder-page-size-select")

        _open_select_action(page, "#folder-docs-table tbody .action-dropdown button")

        folder_select_all = page.locator("#folder-docs-table .document-select-all-checkbox")
        expect(folder_select_all).to_be_visible()
        expect(folder_select_all).to_be_enabled()
        folder_select_all.check()
        expect(page.locator("#selectedCount")).to_have_text("2")
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_group_workspace_document_selection_controls(playwright):
    """Validate group workspace select-all behavior in list and folder-grid views."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    docs_payload = _workspace_documents_payload()
    tags_payload = {"tags": [{"name": "alpha", "color": "#0d6efd", "count": 2}]}

    page.route(
        "**/api/groups?page_size=1000",
        lambda route: _fulfill_json(
            route,
            {
                "groups": [
                    {
                        "id": "group-alpha",
                        "name": "Alpha Team",
                        "isActive": True,
                        "userRole": "Owner",
                        "status": "active",
                    }
                ]
            },
        ),
    )
    page.route("**/api/group_documents?*", lambda route: _fulfill_json(route, docs_payload))
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, tags_payload))

    try:
        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /group_workspaces."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Group workspace page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        page.wait_for_function(
            """
            () => document.querySelectorAll('#group-documents-table tbody tr.document-row').length === 2
            """
        )

        assert "100" in _option_values(page, "#group-docs-page-size-select")
        assert "250" in _option_values(page, "#group-docs-page-size-select")
        assert "100" in _option_values(page, "#group-grid-page-size-select")
        assert "250" in _option_values(page, "#group-grid-page-size-select")

        page.locator("#group-toggle-selection-btn").click()
        group_select_all = page.locator("#group-docs-select-all-checkbox")
        expect(group_select_all).to_be_visible()
        expect(group_select_all).to_be_enabled()
        group_select_all.check()
        expect(page.locator("#groupSelectedCount")).to_have_text("2")

        page.evaluate("window.toggleGroupSelectionMode()")
        page.locator('label[for="group-docs-view-grid"]').click()

        page.wait_for_function(
            """
            () => document.querySelector('#group-tag-folders-container .tag-folder-card[data-tag="alpha"]') !== null
            """
        )
        page.locator('#group-tag-folders-container .tag-folder-card[data-tag="alpha"]').click()

        page.wait_for_function(
            """
            () => document.querySelector('#group-folder-docs-table') !== null
            """
        )

        assert "100" in _option_values(page, "#group-folder-page-size-select")
        assert "250" in _option_values(page, "#group-folder-page-size-select")

        _open_select_action(page, "#group-folder-docs-table tbody .action-dropdown button")

        folder_select_all = page.locator("#group-folder-docs-table .document-select-all-checkbox")
        expect(folder_select_all).to_be_visible()
        expect(folder_select_all).to_be_enabled()
        folder_select_all.check()
        expect(page.locator("#groupSelectedCount")).to_have_text("2")
    finally:
        context.close()
        browser.close()