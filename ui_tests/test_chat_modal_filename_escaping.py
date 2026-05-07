# test_chat_modal_filename_escaping.py
"""
UI test for chat modal filename escaping.
Version: 0.241.018
Implemented in: 0.241.018

This test ensures citation and uploaded-file modal titles render malicious
filenames as inert text on first display.
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


@pytest.mark.ui
def test_chat_modals_escape_malicious_filenames_on_first_render(playwright):
    """Validate chat modal titles keep attacker-controlled filenames inert."""
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

    citation_filename = '<img src=x onerror="window.__citationModalTitleXss = true">.pdf'
    file_filename = '<svg onload="window.__fileModalTitleXss = true"></svg>.txt'

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

        page.evaluate(
            """
            async ({ citationFilename, fileFilename }) => {
                window.__citationModalTitleXss = false;
                window.__fileModalTitleXss = false;

                const citationsModule = await import('/static/js/chat/chat-citations.js');
                citationsModule.showCitedTextPopup('Citation body', citationFilename, 7);

                const fileActionsModule = await import('/static/js/chat/chat-input-actions.js');
                const citationModal = document.getElementById('citation-modal');
                const citationInstance = bootstrap.Modal.getInstance(citationModal);
                if (citationInstance) {
                    citationInstance.hide();
                }

                fileActionsModule.showFileContentPopup(
                    'Uploaded file body',
                    fileFilename,
                    false,
                    'database',
                    null,
                    null,
                );
            }
            """,
            {"citationFilename": citation_filename, "fileFilename": file_filename},
        )

        expect(page.locator("#citation-modal .modal-title")).to_have_text(
            f"Source: {citation_filename}, Page: 7"
        )
        expect(page.locator("#citation-modal img[src='x']")).to_have_count(0)
        expect(page.locator("#citation-modal svg")).to_have_count(0)

        expect(page.locator("#file-modal")).to_be_visible()
        expect(page.locator("#file-modal .modal-title")).to_have_text(
            f"Uploaded File: {file_filename}"
        )
        expect(page.locator("#file-modal img[src='x']")).to_have_count(0)
        expect(page.locator("#file-modal svg")).to_have_count(0)

        flags = page.evaluate(
            """() => ({
                citation: !!window.__citationModalTitleXss,
                file: !!window.__fileModalTitleXss,
            })"""
        )
        assert flags == {"citation": False, "file": False}
    finally:
        context.close()
        browser.close()