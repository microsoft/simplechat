# test_workspace_shared_document_approval_modal.py
"""
UI test for workspace shared-document approval modal.
Version: 0.241.133
Implemented in: 0.241.133

This test ensures pending shared-document rows render a single green approve
launcher, avoid an inline cancel button, and open the approval modal with
approve, deny, and cancel actions.
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
def test_workspace_pending_shared_document_uses_modal_approval(playwright):
    """Validate pending shared-document rows show one approve launcher and the shared approval modal."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    page.route(
        "**/api/documents?*",
        lambda route: _fulfill_json(route, {"documents": [], "page": 1, "page_size": 10, "total_count": 0}),
    )
    page.route("**/api/documents/tags", lambda route: _fulfill_json(route, {"tags": []}))
    page.route(
        "**/api/user/info/*",
        lambda route: _fulfill_json(
            route,
            {
                "display_name": "Paul Retroburn",
                "email": "paullizer@retroburn.cloud",
            },
        ),
    )

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /workspace."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        workspace_documents_src = page.locator('script[src*="workspace-documents.js"]').first.get_attribute('src') or ''
        assert '?v=' in workspace_documents_src, 'Expected workspace-documents.js to be cache-busted with a version query.'

        page.wait_for_function(
            """
            () => typeof renderDocumentRow === 'function' && document.querySelector('#approveSharedModal') !== null
            """
        )

        page.evaluate(
            """
            () => {
                window.current_user_id = 'requester-user';
                selectedDocuments = new Set();
                if (documentsTableBody) {
                    documentsTableBody.innerHTML = '';
                }

                renderDocumentRow({
                    id: 'pending-shared-doc',
                    title: '',
                    file_name: 'pending-shared.xlsx',
                    status: 'Complete',
                    percentage_complete: 100,
                    user_id: 'owner-user',
                    owner_id: 'owner-user',
                    shared_user_ids: ['requester-user,not_approved'],
                    tags: [],
                    document_classification: '',
                    authors: [],
                    keywords: [],
                });
            }
            """
        )

        pendingRow = page.locator('#doc-row-pending-shared-doc')
        approveButton = pendingRow.get_by_role('button', name='Approve')

        expect(approveButton).to_be_visible()
        expect(pendingRow.locator('.action-dropdown button')).to_be_visible()
        expect(approveButton).to_have_class(r'.*btn-success.*')
        assert 'action-btn-wide' not in (approveButton.get_attribute('class') or '')
        assert pendingRow.get_by_role('button', name='Cancel').count() == 0

        approveButton.click()

        modal = page.locator('#approveSharedModal')
        expect(modal).to_be_visible()
        expect(page.locator('#approveSharedModalOwnerName')).to_have_text('Paul Retroburn')
        expect(page.locator('#approveSharedModalOwnerEmail')).to_have_text('paullizer@retroburn.cloud')
        expect(page.locator('#approveSharedModalApproveBtn')).to_be_visible()
        expect(page.locator('#approveSharedModalDenyBtn')).to_be_visible()
        expect(page.locator('#approveSharedModalCancelBtn')).to_be_visible()
    finally:
        context.close()
        browser.close()