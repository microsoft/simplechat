# test_workspace_family_document_revision_delete_modal.py
"""
UI test for workspace-family document revision delete modals.
Version: 0.240.021
Implemented in: 0.240.021

This test ensures the personal, group, and public workspace pages use a
Bootstrap revision delete modal instead of a native browser confirm dialog.
"""

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


def _assert_delete_modal(page, page_path, ready_selector, trigger_script, modal_selector):
    dialogs = []

    def on_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", on_dialog)

    response = page.goto(f"{BASE_URL}{page_path}", wait_until="networkidle")
    assert response is not None, f"Expected a navigation response when loading {page_path}."

    if response.status in SKIP_RESPONSE_CODES:
        return False

    assert response.ok, f"Expected {page_path} to load successfully, got HTTP {response.status}."
    expect(page.locator(ready_selector)).to_be_visible()

    page.evaluate(trigger_script)

    modal = page.locator(modal_selector)
    expect(modal).to_be_visible()
    expect(modal.get_by_role("button", name="Delete Current Version")).to_be_visible()
    expect(modal.get_by_role("button", name="Delete All Versions")).to_be_visible()
    assert dialogs == [], f"Expected {page_path} to use a Bootstrap modal instead of a browser dialog. Saw: {dialogs}"

    modal.get_by_role("button", name="Cancel").click()
    expect(modal).to_be_hidden()
    return True


@pytest.mark.ui
def test_workspace_family_document_revision_delete_modal(playwright):
    """Validate workspace-family document delete flows use revision-choice modals."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    checked_pages = 0
    try:
        for page_path, ready_selector, trigger_script, modal_selector in [
            (
                "/workspace",
                "#documents-tab",
                "() => { window.deleteDocument('doc-1'); }",
                "#documentDeleteModal",
            ),
            (
                "/group_workspaces",
                "#groupWorkspaceTabContent",
                "() => { userRoleInActiveGroup = 'Owner'; window.deleteGroupDocument('doc-1'); }",
                "#groupDocumentDeleteModal",
            ),
            (
                "/public_workspaces",
                "#publicWorkspaceTabContent",
                "() => { window.deletePublicDocument('doc-1'); }",
                "#publicDocumentDeleteModal",
            ),
        ]:
            page = context.new_page()
            try:
                if _assert_delete_modal(page, page_path, ready_selector, trigger_script, modal_selector):
                    checked_pages += 1
            finally:
                page.close()

        if checked_pages == 0:
            pytest.skip("No workspace-family pages were available in this environment.")
    finally:
        context.close()
        browser.close()