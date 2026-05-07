# test_workspace_document_cards_layout.py
"""
UI test for workspace document card layouts.
Version: 0.241.014
Implemented in: 0.241.014

This test ensures that personal and group workspaces can switch into the new
document card view and render quick actions, metadata, and status badges.
"""

import json
import os
import re
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")
    try:
        with urlopen(BASE_URL, timeout=5):
            return
    except URLError as ex:
        pytest.skip(f"UI server is not reachable at {BASE_URL}: {ex.reason}")


@pytest.mark.ui
def test_personal_workspace_document_cards_render_quick_actions(playwright):
    """Validate the personal workspace document card view."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    documents_payload = {
        "documents": [
            {
                "id": "doc-cards-1",
                "file_name": "Quarterly Strategy.pdf",
                "title": "Quarterly Strategy",
                "percentage_complete": 100,
                "status": "Complete",
                "authors": ["Ada Lovelace", "Grace Hopper"],
                "abstract": "A concise summary of the quarterly strategy plan.",
                "number_of_pages": 12,
                "tags": ["strategy", "roadmap"],
                "enhanced_citations": True,
                "user_id": "test-user",
            }
        ],
        "page": 1,
        "page_size": 20,
        "total_count": 1,
        "needs_legacy_update_check": False,
    }

    page.route(
        "**/api/documents*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(documents_payload)),
    )
    page.route(
        "**/api/documents/tags*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"tags": []})),
    )

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /workspace to load successfully."

        page.locator("#docs-view-cards").check()

        card = page.locator("#documents-card-view .document-item-card").first
        expect(card).to_be_visible()
        expect(card).to_contain_text("Quarterly Strategy")
        expect(card).to_contain_text("Enhanced citations")
        expect(card.get_by_role("button", name="Chat")).to_be_visible()
        expect(page.locator("#documents-list-view")).to_have_class(re.compile(r".*d-none.*"))
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_group_workspace_document_cards_render_quick_actions(playwright):
    """Validate the group workspace document card view."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    groups_payload = {
        "groups": [
            {
                "id": "group-alpha",
                "name": "Alpha Team",
                "isActive": True,
                "userRole": "Owner",
                "status": "active",
            }
        ]
    }
    group_documents_payload = {
        "documents": [
            {
                "id": "group-doc-1",
                "file_name": "Shared Research.pdf",
                "title": "Shared Research",
                "percentage_complete": 100,
                "status": "Complete",
                "authors": ["Katherine Johnson"],
                "abstract": "A shared research summary for the active group workspace.",
                "number_of_pages": 8,
                "tags": ["shared", "analysis"],
                "enhanced_citations": False,
                "shared_group_ids": ["group-alpha"],
            }
        ],
        "page": 1,
        "page_size": 10,
        "total_count": 1,
    }

    page.route(
        "**/api/groups?page_size=1000",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(groups_payload)),
    )
    page.route(
        "**/api/group_documents?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(group_documents_payload)),
    )
    page.route(
        "**/api/group_documents/tags?*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"tags": []})),
    )

    try:
        response = page.goto(f"{BASE_URL}/group_workspaces", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /group_workspaces to load successfully."

        page.locator("#group-docs-view-cards").check()

        card = page.locator("#group-documents-card-view .document-item-card").first
        expect(card).to_be_visible()
        expect(card).to_contain_text("Shared Research")
        expect(card).to_contain_text("Standard citations")
        expect(card.get_by_role("button", name="Chat")).to_be_visible()
        expect(page.locator("#group-documents-list-view")).to_have_class(re.compile(r".*d-none.*"))
    finally:
        context.close()
        browser.close()