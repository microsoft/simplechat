# test_group_workspace_prompt_role_ui_resilience.py
"""
UI test for group workspace prompt role UI resilience.
Version: 0.241.003
Implemented in: 0.241.003

This test ensures the group workspace can refresh active group context without
raising client-side errors when the prompt role warning and create button
containers are absent from the DOM.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip(
            "Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file."
        )


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_group_workspace_group_change_tolerates_missing_prompt_role_elements(playwright):
    """Validate that a group change does not raise prompt role UI null errors."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    group_payloads = [
        {
            "groups": [
                {
                    "id": "group-alpha",
                    "name": "Alpha Team",
                    "isActive": True,
                    "userRole": "Owner",
                    "status": "active",
                },
                {
                    "id": "group-beta",
                    "name": "Beta Team",
                    "isActive": False,
                    "userRole": "Admin",
                    "status": "active",
                },
            ]
        },
        {
            "groups": [
                {
                    "id": "group-alpha",
                    "name": "Alpha Team",
                    "isActive": False,
                    "userRole": "Owner",
                    "status": "active",
                },
                {
                    "id": "group-beta",
                    "name": "Beta Team",
                    "isActive": True,
                    "userRole": "Admin",
                    "status": "active",
                },
            ]
        },
    ]

    def handle_groups(route):
        payload = group_payloads[0]
        if len(group_payloads) > 1:
            payload = group_payloads.pop(0)
        _fulfill_json(route, payload)

    page.route("**/api/groups?page_size=1000", handle_groups)
    page.route(
        "**/api/groups/setActive",
        lambda route: _fulfill_json(route, {"success": True}),
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

        page.evaluate(
            """
            () => {
                document.getElementById('create-group-prompt-section')?.remove();
                document.getElementById('group-prompts-role-warning')?.remove();

                const select = document.getElementById('group-select');
                if (select) {
                    select.value = 'group-beta';
                }

                const selectedText = document.querySelector('#group-dropdown-button .selected-group-text');
                if (selectedText) {
                    selectedText.textContent = 'Beta Team';
                }
            }
            """
        )

        page.locator("#btn-change-group").click()
        page.wait_for_function(
            """
            () => {
                const role = document.getElementById('user-role');
                return role && role.textContent.trim() === 'Admin';
            }
            """
        )

        null_style_errors = [
            error
            for error in page_errors
            if "Cannot read properties of null (reading 'style')" in error
        ]

        assert not null_style_errors, f"Unexpected prompt role UI errors: {null_style_errors}"
    finally:
        context.close()
        browser.close()