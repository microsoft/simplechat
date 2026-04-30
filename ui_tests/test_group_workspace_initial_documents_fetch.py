# test_group_workspace_initial_documents_fetch.py
"""
UI test for group workspace initial document fetch.
Version: 0.240.027
Implemented in: 0.240.027

This test ensures that the first visit to the group workspace loads the active
group document table without raising the old params ReferenceError or showing a
bulk-delete confirmation dialog.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_group_workspace_first_visit_loads_documents_without_load_time_errors(playwright):
    """Validate first-load group document fetch behavior."""
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

    page_errors = []
    dialog_messages = []

    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def handle_dialog(dialog):
        dialog_messages.append(dialog.message)
        dialog.dismiss()

    page.on("dialog", handle_dialog)

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
    page.route(
        "**/api/group_documents/tags?*",
        lambda route: _fulfill_json(route, {"tags": []}),
    )

    try:
        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")

        assert response is not None, "Expected a navigation response when loading /group_workspaces."
        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        page.wait_for_function(
            """
            () => {
                const tbody = document.querySelector('#group-documents-table tbody');
                return tbody && tbody.textContent.includes('No documents found in this group.');
            }
            """
        )

        expect(page.locator("#group-documents-table tbody")).to_contain_text(
            "No documents found in this group."
        )

        params_errors = [error for error in page_errors if "params is not defined" in error]
        delete_dialogs = [
            message for message in dialog_messages if "delete 0 selected document(s)" in message.lower()
        ]

        assert not params_errors, f"Unexpected page errors: {params_errors}"
        assert not delete_dialogs, f"Unexpected delete confirmation dialogs: {delete_dialogs}"
    finally:
        context.close()
        browser.close()