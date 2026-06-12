# test_group_workspace_file_download_permissions.py
"""
UI test for group workspace file download permissions.
Version: 0.241.195
Implemented in: 0.241.195

This test ensures regular group users do not see or invoke group document
download controls, even when the document API reports downloads as enabled.
"""

import json
import os
import re
from pathlib import Path

import pytest


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
def test_regular_group_user_download_controls_remain_hidden_when_downloads_enabled() -> None:
    """Validate regular group users cannot see or invoke group document downloads."""
    _require_ui_env()
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    context.add_init_script("localStorage.setItem('groupWorkspaceViewPreference', 'list');")
    page = context.new_page()
    download_requests = []

    page.route(
        "**/api/groups?page_size=1000",
        lambda route: _fulfill_json(
            route,
            {
                "groups": [
                    {
                        "id": "download-user-group",
                        "name": "Download User Group",
                        "isActive": True,
                        "userRole": "User",
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
                "documents": [
                    {
                        "id": "group-download-doc",
                        "file_name": "policy-enabled.pdf",
                        "title": "Policy Enabled",
                        "status": "Complete",
                        "percentage_complete": 100,
                        "group_id": "download-user-group",
                    }
                ],
                "page": 1,
                "page_size": 10,
                "total_count": 1,
                "file_downloads_enabled": True,
                "file_download_enabled_group_ids": ["download-user-group"],
            },
        ),
    )
    page.route("**/api/group_documents/tags?*", lambda route: _fulfill_json(route, {"tags": []}))

    def capture_download_request(route) -> None:
        download_requests.append(route.request.url)
        _fulfill_json(route, {"error": "Download should not be requested"}, status=403)

    page.route("**/api/group_documents/*/download", capture_download_request)
    page.route("**/api/group_documents/download", capture_download_request)

    try:
        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="domcontentloaded")
        assert response is not None, "Expected a navigation response when loading /group_workspaces."
        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(f"Group workspace unavailable in this environment (HTTP {response.status}).")
        assert response.ok, f"Expected /group_workspaces to load successfully, got HTTP {response.status}."

        page.wait_for_function(
            """
            () => {
                const row = document.querySelector('#group-doc-row-group-download-doc');
                return row && typeof canDownloadGroupDocuments === 'function';
            }
            """,
            timeout=10000,
        )

        assert page.evaluate("() => canDownloadGroupDocuments()") is False

        row = page.locator("#group-doc-row-group-download-doc")
        row.locator(".dropdown-toggle").click()
        assert row.get_by_text("Download file").count() == 0

        row.locator(".select-btn").click()
        row.locator(".document-checkbox").check()
        expect(page.locator("#group-download-selected-btn")).to_have_class(re.compile(r"\bd-none\b"))

        warning = page.evaluate(
            """
            async () => {
                window.__groupDownloadWarnings = [];
                window.showToast = (message, variant) => {
                    window.__groupDownloadWarnings.push({ message, variant });
                };
                await downloadGroupDocumentFile('group-download-doc');
                return window.__groupDownloadWarnings;
            }
            """
        )

        assert warning == [
            {
                "message": "You do not have permission to download files from this group workspace.",
                "variant": "warning",
            }
        ]
        assert download_requests == [], "Regular group users should not send group document download requests."
    finally:
        context.close()
        browser.close()
        playwright.stop()