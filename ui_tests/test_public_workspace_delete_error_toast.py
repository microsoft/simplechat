# test_public_workspace_delete_error_toast.py
"""
UI test for public workspace delete error toast.
Version: 0.240.056
Implemented in: 0.240.056

This test ensures a failed public document delete shows a Bootstrap toast
instead of a blocking browser alert dialog.
"""

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv('SIMPLECHAT_UI_BASE_URL', '').rstrip('/')
STORAGE_STATE = os.getenv('SIMPLECHAT_UI_STORAGE_STATE', '')
SKIP_RESPONSE_CODES = {401, 403, 404}


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type='application/json',
        body=json.dumps(payload),
    )


def _handle_public_workspace_api(route):
    request = route.request
    parsed_url = urlparse(request.url)
    path = parsed_url.path

    if path == '/api/public_workspaces':
        _fulfill_json(
            route,
            {
                'workspaces': [
                    {
                        'id': 'public-1',
                        'name': 'Toast Regression Workspace',
                        'isActive': True,
                        'userRole': 'Owner',
                    }
                ]
            },
        )
        return

    if path == '/api/public_workspaces/public-1':
        _fulfill_json(
            route,
            {
                'id': 'public-1',
                'name': 'Toast Regression Workspace',
                'status': 'active',
                'userRole': 'Owner',
            },
        )
        return

    if path == '/api/public_documents' and request.method == 'GET':
        _fulfill_json(
            route,
            {
                'documents': [
                    {
                        'id': 'doc-1',
                        'file_name': 'Toast Regression Doc.pdf',
                        'title': 'Toast Regression Doc',
                        'status': 'Complete',
                        'percentage_complete': 100,
                        'authors': 'Regression Tester',
                        'version': '1',
                        'number_of_pages': '1',
                        'enhanced_citations': False,
                        'publication_date': '2026-04-03',
                        'keywords': 'toast, delete',
                        'abstract': 'Regression coverage for delete errors.',
                        'tags': [],
                        'document_classification': 'Public',
                    }
                ],
                'page': 1,
                'page_size': 10,
                'total_count': 1,
            },
        )
        return

    if path == '/api/public_documents/doc-1' and request.method == 'DELETE':
        _fulfill_json(route, {'error': 'Delete failed for regression test.'}, status=500)
        return

    if path == '/api/public_workspace_documents/tags':
        _fulfill_json(route, {'tags': []})
        return

    route.continue_()


@pytest.mark.ui
def test_public_workspace_delete_failure_uses_toast(playwright):
    """Validate that failed public document deletes show a toast instead of a browser alert."""
    if not BASE_URL:
        pytest.skip('Set SIMPLECHAT_UI_BASE_URL to run this UI test.')
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip('Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.')

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={'width': 1440, 'height': 900},
    )
    page = context.new_page()
    dialogs = []

    def on_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on('dialog', on_dialog)
    page.route('**/api/public_workspaces*', _handle_public_workspace_api)
    page.route('**/api/public_documents*', _handle_public_workspace_api)
    page.route('**/api/public_workspace_documents*', _handle_public_workspace_api)

    try:
        response = page.goto(f'{BASE_URL}/public_workspaces', wait_until='networkidle')
        assert response is not None, 'Expected a navigation response when loading /public_workspaces.'

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f'/public_workspaces returned HTTP {response.status} in this environment.')

        assert response.ok, f'Expected /public_workspaces to load successfully, got HTTP {response.status}.'
        expect(page.locator('#publicWorkspaceTabContent')).to_be_visible()
        expect(page.locator('#public-documents-table tbody')).to_contain_text('Toast Regression Doc')

        page.evaluate("() => { window.deletePublicDocument('doc-1'); }")

        delete_modal = page.locator('#publicDocumentDeleteModal')
        expect(delete_modal).to_be_visible()
        delete_modal.get_by_role('button', name='Delete All Versions').click()

        toast = page.locator('#toast-container .toast').last
        expect(toast).to_be_visible()
        expect(toast).to_contain_text('Error deleting: Delete failed for regression test.')
        assert dialogs == [], f'Expected delete failures to avoid browser alerts. Saw: {dialogs}'
    finally:
        context.close()
        browser.close()