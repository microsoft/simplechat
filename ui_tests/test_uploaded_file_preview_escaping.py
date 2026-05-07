# test_uploaded_file_preview_escaping.py
"""
UI test for uploaded file preview body escaping.
Version: 0.241.022
Implemented in: 0.241.022

This test ensures uploaded file preview content renders attacker-controlled
plain text, CSV cells, and legacy HTML table payloads as inert text.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}

def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )

def _show_file_preview(page, file_content, filename, is_table, flag_name):
    page.evaluate(
        """
        async ({ fileContent, filename, isTable, flagName }) => {
            window[flagName] = false;

            const fileActionsModule = await import('/static/js/chat/chat-input-actions.js');
            fileActionsModule.showFileContentPopup(
                fileContent,
                filename,
                isTable,
                'database',
                null,
                null,
            );
        }
        """,
        {
            "fileContent": file_content,
            "filename": filename,
            "isTable": is_table,
            "flagName": flag_name,
        },
    )

@pytest.mark.ui
def test_uploaded_file_preview_renders_untrusted_content_as_inert_text(playwright):
    """Validate uploaded file previews do not turn attacker-controlled content into DOM."""
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    plain_text_payload = '<img src=x onerror="window.__filePreviewPlainXss = true"> plain text body'
    csv_payload = 'column_a,column_b\n<img src=x onerror="window.__filePreviewCsvXss = true">,safe'
    legacy_table_payload = (
        '<table><tbody><tr><td><svg onload="window.__filePreviewLegacyXss = true"></svg>'
        '</td></tr></tbody></table>'
    )

    page.route(
        "**/api/user/settings",
        lambda route: _fulfill_json(route, {"selected_agent": None, "settings": {"enable_agents": False}}),
    )
    page.route("**/api/get_conversations", lambda route: _fulfill_json(route, {"conversations": []}))

    try:
        response = page.goto(f"{BASE_URL}/chats", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /chats."

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"/chats returned HTTP {response.status} in this environment.")

        assert response.ok, f"Expected /chats to load successfully, got HTTP {response.status}."
        page.wait_for_selector("#chatbox")

        _show_file_preview(
            page,
            plain_text_payload,
            "plain-preview.txt",
            False,
            "__filePreviewPlainXss",
        )
        expect(page.locator("#file-modal")).to_be_visible()
        expect(page.locator("#file-content pre")).to_have_text(plain_text_payload)
        expect(page.locator("#file-modal img[src='x']")).to_have_count(0)
        expect(page.locator("#file-modal svg")).to_have_count(0)
        expect(page.locator("#file-modal script")).to_have_count(0)

        _show_file_preview(
            page,
            csv_payload,
            "table-preview.csv",
            True,
            "__filePreviewCsvXss",
        )
        expect(page.locator("#file-content table")).to_be_visible()
        expect(page.locator("#file-content")).to_contain_text(
            '<img src=x onerror="window.__filePreviewCsvXss = true">'
        )
        expect(page.locator("#file-modal img[src='x']")).to_have_count(0)
        expect(page.locator("#file-modal svg")).to_have_count(0)
        expect(page.locator("#file-modal script")).to_have_count(0)

        _show_file_preview(
            page,
            legacy_table_payload,
            "legacy-table-preview.html",
            True,
            "__filePreviewLegacyXss",
        )
        expect(page.locator("#file-content pre")).to_contain_text("<table><tbody><tr><td><svg")
        expect(page.locator("#file-content table")).to_have_count(0)
        expect(page.locator("#file-modal img[src='x']")).to_have_count(0)
        expect(page.locator("#file-modal svg")).to_have_count(0)
        expect(page.locator("#file-modal script")).to_have_count(0)

        flags = page.evaluate(
            """() => ({
                plain: !!window.__filePreviewPlainXss,
                csv: !!window.__filePreviewCsvXss,
                legacy: !!window.__filePreviewLegacyXss,
            })"""
        )
        assert flags == {"plain": False, "csv": False, "legacy": False}
    finally:
        context.close()
        browser.close()