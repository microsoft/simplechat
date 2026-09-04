# test_workspace_family_document_revision_delete_modal.py
"""
UI test for workspace-family document revision delete modals.
Version: 0.250.032
Implemented in: 0.241.004

This test ensures the personal, group, and public workspace pages use a
Bootstrap revision delete modal instead of a native browser confirm dialog,
and fail closed with user-visible feedback if the modal wiring is unavailable.
"""

import os
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}
DELETE_MODAL_UNAVAILABLE_MESSAGE = "Delete confirmation dialog is unavailable. Refresh the page and try again."


def _require_ui_env():
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")
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

    modal = page.locator(modal_selector)
    expect(modal).to_have_count(1)
    expect(modal).to_be_hidden()

    page.evaluate(trigger_script)

    expect(modal).to_be_visible()
    expect(modal.get_by_role("button", name="Delete Current Version")).to_be_visible()
    expect(modal.get_by_role("button", name="Delete All Versions")).to_be_visible()
    assert dialogs == [], f"Expected {page_path} to use a Bootstrap modal instead of a browser dialog. Saw: {dialogs}"

    modal.get_by_role("button", name="Cancel").click()
    expect(modal).to_be_hidden()
    return True


def _assert_delete_modal_fails_closed(page, page_path, ready_selector, modal_remove_script, trigger_script):
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

    page.evaluate(
        """
        () => {
            window.__deleteRequestCount = 0;
            const originalFetch = window.fetch.bind(window);
            window.fetch = (...args) => {
                window.__deleteRequestCount += 1;
                return originalFetch(...args);
            };
        }
        """
    )
    page.evaluate(modal_remove_script)
    page.evaluate(trigger_script)

    expect(page.get_by_text(DELETE_MODAL_UNAVAILABLE_MESSAGE)).to_be_visible()
    assert dialogs == [], f"Expected {page_path} to fail closed without opening a browser dialog. Saw: {dialogs}"
    assert page.evaluate("() => window.__deleteRequestCount") == 0
    return True


@pytest.mark.ui
def test_workspace_family_document_revision_delete_modal():
    """Validate workspace-family document delete flows use revision-choice modals."""
    _require_ui_env()

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})

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
        playwright_context.stop()


@pytest.mark.ui
def test_workspace_family_document_revision_delete_modal_fails_closed_when_modal_missing():
    """Validate workspace-family delete flows fail closed when modal wiring is unavailable."""
    _require_ui_env()

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})

    checked_pages = 0
    try:
        for page_path, ready_selector, modal_remove_script, trigger_script in [
            (
                "/workspace",
                "#documents-tab",
                "() => { document.getElementById('documentDeleteModal')?.remove(); }",
                "() => window.deleteDocument('doc-1')",
            ),
            (
                "/group_workspaces",
                "#groupWorkspaceTabContent",
                "() => { document.getElementById('groupDocumentDeleteModal')?.remove(); }",
                "() => { userRoleInActiveGroup = 'Owner'; return window.deleteGroupDocument('doc-1'); }",
            ),
            (
                "/public_workspaces",
                "#publicWorkspaceTabContent",
                "() => { document.getElementById('publicDocumentDeleteModal')?.remove(); }",
                "() => window.deletePublicDocument('doc-1')",
            ),
        ]:
            page = context.new_page()
            try:
                if _assert_delete_modal_fails_closed(page, page_path, ready_selector, modal_remove_script, trigger_script):
                    checked_pages += 1
            finally:
                page.close()

        if checked_pages == 0:
            pytest.skip("No workspace-family pages were available in this environment.")
    finally:
        context.close()
        browser.close()
        playwright_context.stop()


@pytest.mark.ui
def test_personal_workspace_document_delete_modal_releases_focus_before_hide():
    """Validate the personal document delete modal hides without retained-focus warnings."""
    _require_ui_env()

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(storage_state=STORAGE_STATE, viewport={"width": 1440, "height": 900})
    page = context.new_page()
    aria_hidden_warnings = []

    def track_console(message):
        if "Blocked aria-hidden" in message.text:
            aria_hidden_warnings.append(message.text)

    page.on("console", track_console)
    page.route(
        "**/api/documents/doc-1?**",
        lambda route: route.fulfill(status=200, content_type="application/json", body='{"success": true}'),
    )

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /workspace."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Workspace page unavailable in this environment (HTTP {response.status}).")

        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."
        expect(page.locator("#documents-tab")).to_be_visible()

        page.evaluate("() => { window.deleteDocument('doc-1'); }")
        modal = page.locator("#documentDeleteModal")
        expect(modal).to_be_visible()
        modal.get_by_role("button", name="Delete All Versions").click()
        expect(modal).to_be_hidden()

        assert aria_hidden_warnings == [], (
            "Expected the personal document delete modal to release focus before Bootstrap applies aria-hidden."
        )
    finally:
        context.close()
        browser.close()
        playwright_context.stop()