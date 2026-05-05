# test_document_share_modal_escaping.py
"""
UI test for personal and group document share modal escaping.
Version: 0.241.020
Implemented in: 0.241.020

This test ensures malicious names, descriptions, emails, and toast messages
render as inert text in the personal and group document sharing modals.
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


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _new_page(playwright):
    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    return browser, context, page


def _assert_ok_or_skip(response, route_path: str) -> None:
    assert response is not None, f"Expected a navigation response when loading {route_path}."
    if response.status in SKIP_RESPONSE_CODES:
        pytest.skip(f"{route_path} returned HTTP {response.status} in this environment.")
    assert response.ok, f"Expected {route_path} to load successfully, got HTTP {response.status}."


@pytest.mark.ui
def test_workspace_share_modal_escapes_malicious_names_and_toasts(playwright):
    """Validate the personal workspace share modal renders malicious values inertly."""
    _require_ui_env()

    browser, context, page = _new_page(playwright)

    shared_name = '<img src=x onerror="window.__workspaceSharedNameXss = true">'
    shared_email = '<svg onload="window.__workspaceSharedEmailXss = true"></svg>@example.com'
    search_name = '<img src=x onerror="window.__workspaceSearchNameXss = true">'
    search_email = '<svg onload="window.__workspaceSearchEmailXss = true"></svg>@example.com'

    try:
        page.route(
            "**/api/documents/doc-1/shared-users",
            lambda route: _fulfill_json(
                route,
                {
                    "shared_users": [
                        {
                            "id": "shared-user-1",
                            "displayName": shared_name,
                            "email": shared_email,
                        }
                    ]
                },
            ),
        )
        page.route(
            "**/api/userSearch*",
            lambda route: _fulfill_json(
                route,
                [
                    {
                        "id": "search-user-1",
                        "displayName": search_name,
                        "email": search_email,
                    }
                ],
            ),
        )
        page.route(
            "**/api/documents/doc-1/share",
            lambda route: _fulfill_json(route, {"success": True}),
        )

        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        _assert_ok_or_skip(response, "/workspace")
        page.wait_for_function("() => typeof window.shareDocument === 'function'")

        page.evaluate(
            """() => {
                window.__workspaceSharedNameXss = false;
                window.__workspaceSharedEmailXss = false;
                window.__workspaceSearchNameXss = false;
                window.__workspaceSearchEmailXss = false;
                window.shareDocument('doc-1', 'Escaping Test Document.txt');
            }"""
        )

        expect(page.locator("#shareDocumentModal")).to_be_visible()
        expect(page.locator("#sharedUsersList")).to_contain_text(shared_name)
        expect(page.locator("#sharedUsersList")).to_contain_text(shared_email)
        expect(page.locator("#sharedUsersList img[src='x']")).to_have_count(0)
        expect(page.locator("#sharedUsersList svg")).to_have_count(0)

        page.locator("#userSearchTerm").fill("malicious")
        page.locator("#searchUsersBtn").click()

        expect(page.locator("#userSearchResultsTable tbody")).to_contain_text(search_name)
        expect(page.locator("#userSearchResultsTable tbody")).to_contain_text(search_email)
        expect(page.locator("#userSearchResultsTable tbody img[src='x']")).to_have_count(0)
        expect(page.locator("#userSearchResultsTable tbody svg")).to_have_count(0)

        page.locator("#userSearchResultsTable tbody .user-search-add-btn").click()

        expect(page.locator("#toastContainer")).to_contain_text(f"Document shared with {search_name}")
        expect(page.locator("#toastContainer img[src='x']")).to_have_count(0)
        expect(page.locator("#toastContainer svg")).to_have_count(0)

        flags = page.evaluate(
            """() => ({
                sharedName: !!window.__workspaceSharedNameXss,
                sharedEmail: !!window.__workspaceSharedEmailXss,
                searchName: !!window.__workspaceSearchNameXss,
                searchEmail: !!window.__workspaceSearchEmailXss,
            })"""
        )
        assert flags == {
            "sharedName": False,
            "sharedEmail": False,
            "searchName": False,
            "searchEmail": False,
        }
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_group_share_modal_escapes_malicious_names_descriptions_and_toasts(playwright):
    """Validate the group workspace share modal renders malicious values inertly."""
    _require_ui_env()

    browser, context, page = _new_page(playwright)

    shared_group_name = '<img src=x onerror="window.__sharedGroupNameXss = true">'
    shared_group_description = '<svg onload="window.__sharedGroupDescriptionXss = true"></svg> shared description'
    search_group_name = '<img src=x onerror="window.__searchGroupNameXss = true">'
    search_group_description = '<svg onload="window.__searchGroupDescriptionXss = true"></svg> search description'

    try:
        page.route(
            "**/api/group_documents/group-doc-1/shared-groups",
            lambda route: _fulfill_json(
                route,
                {
                    "shared_groups": [
                        {
                            "id": "shared-group-1",
                            "name": shared_group_name,
                            "description": shared_group_description,
                        }
                    ]
                },
            ),
        )
        page.route(
            "**/api/groups/discover*",
            lambda route: _fulfill_json(
                route,
                [
                    {
                        "id": "search-group-1",
                        "name": search_group_name,
                        "description": search_group_description,
                    }
                ],
            ),
        )
        page.route(
            "**/api/group_documents/group-doc-1/share-with-group",
            lambda route: _fulfill_json(route, {"success": True}),
        )

        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")
        _assert_ok_or_skip(response, "/group_workspaces")
        page.wait_for_function("() => typeof window.shareGroupDocument === 'function'")

        page.evaluate(
            """() => {
                window.__sharedGroupNameXss = false;
                window.__sharedGroupDescriptionXss = false;
                window.__searchGroupNameXss = false;
                window.__searchGroupDescriptionXss = false;
                window.shareGroupDocument('group-doc-1', 'Escaping Group Document.txt');
            }"""
        )

        expect(page.locator("#groupShareDocumentModal")).to_be_visible()
        expect(page.locator("#sharedGroupsList")).to_contain_text(shared_group_name)
        expect(page.locator("#sharedGroupsList")).to_contain_text(shared_group_description)
        expect(page.locator("#sharedGroupsList img[src='x']")).to_have_count(0)
        expect(page.locator("#sharedGroupsList svg")).to_have_count(0)

        page.locator("#groupSearchTerm").fill("malicious")
        page.locator("#searchGroupsBtn").click()

        expect(page.locator("#groupSearchResultsTable tbody")).to_contain_text(search_group_name)
        expect(page.locator("#groupSearchResultsTable tbody")).to_contain_text(search_group_description)
        expect(page.locator("#groupSearchResultsTable tbody img[src='x']")).to_have_count(0)
        expect(page.locator("#groupSearchResultsTable tbody svg")).to_have_count(0)

        page.locator("#groupSearchResultsTable tbody .group-search-add-btn").click()

        expect(page.locator("#toastContainer")).to_contain_text(
            f"Document shared with group: {search_group_name}"
        )
        expect(page.locator("#toastContainer img[src='x']")).to_have_count(0)
        expect(page.locator("#toastContainer svg")).to_have_count(0)

        flags = page.evaluate(
            """() => ({
                sharedName: !!window.__sharedGroupNameXss,
                sharedDescription: !!window.__sharedGroupDescriptionXss,
                searchName: !!window.__searchGroupNameXss,
                searchDescription: !!window.__searchGroupDescriptionXss,
            })"""
        )
        assert flags == {
            "sharedName": False,
            "sharedDescription": False,
            "searchName": False,
            "searchDescription": False,
        }
    finally:
        context.close()
        browser.close()