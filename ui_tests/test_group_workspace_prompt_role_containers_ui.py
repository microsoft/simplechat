# test_group_workspace_prompt_role_containers_ui.py
"""
UI test for group workspace prompt role UI guard.
Version: 0.241.007
Implemented in: 0.241.007

This test ensures that missing prompt role containers do not break the group
workspace documents tab on first load.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


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
def test_group_workspace_load_tolerates_missing_prompt_role_containers(playwright):
    """Validate documents still render when prompt role containers are absent."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.add_init_script(
        """
        window.addEventListener('DOMContentLoaded', () => {
            document.getElementById('group-prompts-role-warning')?.remove();
            document.getElementById('create-group-prompt-section')?.remove();
        });
        """
    )

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

        prompt_role_errors = [
            error
            for error in page_errors
            if "Cannot read properties of null" in error
            or "create-group-prompt-section" in error
            or "group-prompts-role-warning" in error
        ]
        assert not prompt_role_errors, f"Unexpected prompt role UI page errors: {prompt_role_errors}"
    finally:
        context.close()
        browser.close()