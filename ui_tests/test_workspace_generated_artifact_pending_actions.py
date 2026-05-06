# test_workspace_generated_artifact_pending_actions.py
"""
UI test for pending generated artifact workspace actions.
Version: 0.241.134
Implemented in: 0.241.134

This test ensures group workspace pending generated artifact rows collapse to a
single modal launcher while public workspace rows retain their inline pending
actions.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env() -> None:
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip(
            "Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file."
        )


@pytest.mark.ui
def test_pending_generated_artifact_actions_render_for_group_and_public_workspaces(playwright) -> None:
    """Validate manager and requester pending-action button combinations in workspace views."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.goto(f"{BASE_URL}/group_workspaces", wait_until="domcontentloaded")
        page.wait_for_function("() => typeof renderGroupDocumentRow === 'function'")
        page.evaluate(
            """
            () => {
                window.current_user_id = 'requester-user';
                window.currentGroupStatus = 'active';
                window.enable_document_classification = false;
                window.enable_extract_meta_data = false;
                groupSelectedDocuments = new Set();
                if (groupDocumentsTableBody) {
                    groupDocumentsTableBody.innerHTML = '';
                }

                renderGroupDocumentRow(
                    {
                        id: 'group-managed',
                        file_name: 'managed.json',
                        title: '',
                        status: 'Pending approval',
                        percentage_complete: 0,
                        generated_artifact_promotion_status: 'pending_approval',
                        generated_artifact_requested_by_user_id: 'other-user',
                    },
                    'Owner'
                );

                renderGroupDocumentRow(
                    {
                        id: 'group-requester',
                        file_name: 'requester.json',
                        title: '',
                        status: 'Pending approval',
                        percentage_complete: 0,
                        generated_artifact_promotion_status: 'pending_approval',
                        generated_artifact_requested_by_user_id: 'requester-user',
                    },
                    'User'
                );
            }
            """
        )

        managed_group_row = page.locator('#group-doc-row-group-managed')
        requester_group_row = page.locator('#group-doc-row-group-requester')

        managed_group_action_button = managed_group_row.get_by_role('button', name='Approve')
        requester_group_action_button = requester_group_row.get_by_role('button', name='Review')

        expect(managed_group_action_button).to_be_visible()
        expect(managed_group_action_button).to_have_class(r'.*btn-success.*')
        assert managed_group_row.get_by_role('button', name='Deny').count() == 0
        assert managed_group_row.get_by_role('button', name='Cancel').count() == 0

        managed_group_action_button.click()
        expect(page.locator('#groupGeneratedArtifactApprovalModal')).to_be_visible()
        expect(page.locator('#groupGeneratedArtifactApprovalModalApproveBtn')).to_be_visible()
        expect(page.locator('#groupGeneratedArtifactApprovalModalSecondaryActionBtn')).to_have_text('Deny')
        page.locator('#groupGeneratedArtifactApprovalModalCancelBtn').click()

        expect(requester_group_action_button).to_be_visible()
        expect(requester_group_action_button).to_have_class(r'.*btn-success.*')
        assert requester_group_row.get_by_role('button', name='Cancel').count() == 0
        assert requester_group_row.get_by_role('button', name='Approve').count() == 0
        assert requester_group_row.get_by_role('button', name='Deny').count() == 0

        requester_group_action_button.click()
        expect(page.locator('#groupGeneratedArtifactApprovalModal')).to_be_visible()
        expect(page.locator('#groupGeneratedArtifactApprovalModalApproveBtn')).to_be_hidden()
        expect(page.locator('#groupGeneratedArtifactApprovalModalSecondaryActionBtn')).to_have_text('Cancel Request')
        page.locator('#groupGeneratedArtifactApprovalModalCancelBtn').click()

        page.goto(f"{BASE_URL}/public_workspaces", wait_until="domcontentloaded")
        page.wait_for_function("() => typeof renderPublicDocumentRow === 'function'")
        page.evaluate(
            """
            () => {
                window.current_user_id = 'requester-user';
                window.currentPublicStatus = 'active';
                if (publicDocsTableBody) {
                    publicDocsTableBody.innerHTML = '';
                }

                userRoleInActivePublic = 'Owner';
                renderPublicDocumentRow({
                    id: 'public-managed',
                    file_name: 'managed.json',
                    title: '',
                    status: 'Pending approval',
                    percentage_complete: 0,
                    generated_artifact_promotion_status: 'pending_approval',
                    generated_artifact_requested_by_user_id: 'other-user',
                });

                userRoleInActivePublic = 'User';
                renderPublicDocumentRow({
                    id: 'public-requester',
                    file_name: 'requester.json',
                    title: '',
                    status: 'Pending approval',
                    percentage_complete: 0,
                    generated_artifact_promotion_status: 'pending_approval',
                    generated_artifact_requested_by_user_id: 'requester-user',
                });
            }
            """
        )

        managed_public_row = page.locator('#public-doc-row-public-managed')
        requester_public_row = page.locator('#public-doc-row-public-requester')

        expect(managed_public_row.get_by_role('button', name='Approve')).to_be_visible()
        expect(managed_public_row.get_by_role('button', name='Deny')).to_be_visible()
        assert managed_public_row.get_by_role('button', name='Cancel').count() == 0

        expect(requester_public_row.get_by_role('button', name='Cancel')).to_be_visible()
        assert requester_public_row.get_by_role('button', name='Approve').count() == 0
        assert requester_public_row.get_by_role('button', name='Deny').count() == 0
    finally:
        context.close()
        browser.close()