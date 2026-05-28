# test_group_workspace_shared_document_approval.py
"""
UI test for group workspace shared-document approval.
Version: 0.241.111
Implemented in: 0.241.111

This test ensures owning-group document rows keep Share/Delete controls while
received group shares render Approve or Remove without exposing owner-only
sharing details.
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


@pytest.mark.ui
def test_group_shared_documents_render_approve_and_remove_actions(playwright) -> None:
    """Validate group shared-document rows distinguish owner and receiver actions."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    page.route(
        "**/api/groups?page_size=1000",
        lambda route: _fulfill_json(
            route,
            {
                "groups": [
                    {
                        "id": "receiving-group",
                        "name": "Receiving Group",
                        "isActive": True,
                        "userRole": "Owner",
                        "status": "active",
                    }
                ]
            },
        ),
    )
    page.route(
        "**/api/group_documents?*",
        lambda route: _fulfill_json(
            route,
            {
                "documents": [],
                "page": 1,
                "page_size": 10,
                "total_count": 0,
            },
        ),
    )
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    try:
        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /group_workspaces."
        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Group workspace unavailable in this environment (HTTP {response.status}).")
        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        page.wait_for_function(
            """
            () => typeof renderGroupDocumentRow === 'function'
                && document.querySelector('#groupSharedDocumentApprovalModal') !== null
            """
        )

        page.evaluate(
            """
            () => {
                activeGroupId = 'receiving-group';
                userRoleInActiveGroup = 'Owner';
                window.currentGroupStatus = 'active';
                window.enable_extract_meta_data = false;
                groupSelectedDocuments = new Set();
                groupLastFetchedDocs = [
                    {
                        id: 'owner-doc',
                        file_name: 'owner.pdf',
                        title: '',
                        status: 'Complete',
                        percentage_complete: 100,
                        group_id: 'receiving-group',
                        shared_group_ids: ['other-group,approved'],
                    },
                    {
                        id: 'pending-shared-doc',
                        file_name: 'pending.pdf',
                        title: '',
                        status: 'Complete',
                        percentage_complete: 100,
                        group_id: 'source-group',
                        owner_group_id: 'source-group',
                        owner_group_name: 'Source Group',
                        shared_group_ids: ['receiving-group,not_approved'],
                        shared_approval_status: 'not_approved',
                    },
                    {
                        id: 'approved-shared-doc',
                        file_name: 'approved.pdf',
                        title: '',
                        status: 'Complete',
                        percentage_complete: 100,
                        group_id: 'source-group',
                        owner_group_id: 'source-group',
                        owner_group_name: 'Source Group',
                        shared_group_ids: ['receiving-group,approved'],
                        shared_approval_status: 'approved',
                    },
                ];
                if (groupDocumentsTableBody) {
                    groupDocumentsTableBody.innerHTML = '';
                }
                groupLastFetchedDocs.forEach(doc => renderGroupDocumentRow(doc, 'Owner'));
            }
            """
        )

        owner_row = page.locator('#group-doc-row-owner-doc')
        pending_row = page.locator('#group-doc-row-pending-shared-doc')
        approved_row = page.locator('#group-doc-row-approved-shared-doc')

        owner_row.locator('.dropdown-toggle').click()
        expect(owner_row.get_by_text('Share')).to_be_visible()
        expect(owner_row.get_by_text('Delete')).to_be_visible()
        assert owner_row.get_by_text('Remove').count() == 0

        expect(pending_row.get_by_role('button', name='Approve')).to_be_visible()
        assert pending_row.get_by_role('button', name='Chat').count() == 0
        pending_row.locator('.dropdown-toggle').click()
        assert pending_row.get_by_text('Share').count() == 0
        assert pending_row.get_by_text('Delete').count() == 0

        pending_row.get_by_role('button', name='Approve').click()
        expect(page.locator('#groupSharedDocumentApprovalModal')).to_be_visible()
        expect(page.locator('#groupSharedDocumentApprovalOwnerName')).to_have_text('Source Group')
        expect(page.locator('#groupSharedDocumentApproveBtn')).to_be_visible()
        expect(page.locator('#groupSharedDocumentDenyBtn')).to_be_visible()
        page.locator('#groupSharedDocumentCancelBtn').click()

        approved_row.locator('.dropdown-toggle').click()
        expect(approved_row.get_by_role('button', name='Chat')).to_be_visible()
        expect(approved_row.get_by_text('Remove')).to_be_visible()
        assert approved_row.get_by_text('Share').count() == 0
        assert approved_row.get_by_text('Delete').count() == 0
    finally:
        context.close()
        browser.close()