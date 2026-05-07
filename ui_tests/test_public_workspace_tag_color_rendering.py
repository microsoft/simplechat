# test_public_workspace_tag_color_rendering.py
"""
UI test for public workspace tag color XSS hardening.
Version: 0.241.022
Implemented in: 0.241.022

This test ensures malicious tag color payloads remain inert in the public
workspace grid, tag-management rows, tag-selection rows, and selected-tag chips.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")
SKIP_RESPONSE_CODES = {401, 403, 404}
TAG_NAME = "reviewed"
MALICIOUS_COLOR = (
    '#ff0000"; onclick="window.__publicTagColorXss = true" '
    'onmouseover="window.__publicTagColorXss = true'
)


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
        pytest.skip(
            "Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file."
        )


@pytest.mark.ui
def test_public_workspace_tag_color_payloads_render_inertly(playwright):
    """Validate malicious tag color payloads do not become live browser attributes."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    page.add_init_script(
        """() => {
            localStorage.setItem('publicWorkspaceViewPreference', 'grid');
            window.__publicTagColorXss = false;
        }"""
    )

    documents_payload = {
        "documents": [
            {
                "id": "doc-1",
                "file_name": "reviewed-spec.pdf",
                "title": "Reviewed Spec",
                "tags": [TAG_NAME],
                "status": "Complete",
                "percentage_complete": 100,
                "document_classification": "Public",
                "classification": "Public",
                "version": "1",
                "authors": "Owner User",
                "number_of_pages": 3,
                "enhanced_citations": False,
                "publication_date": "2024-01-01",
                "keywords": "reviewed",
                "abstract": "Regression coverage",
            }
        ],
        "page": 1,
        "page_size": 1000,
        "total_count": 1,
    }
    tag_payload = [{"name": TAG_NAME, "color": MALICIOUS_COLOR, "count": 1}]

    try:
        page.route(
            "**/api/public_documents*",
            lambda route: _fulfill_json(route, documents_payload),
        )
        page.route(
            "**/api/public_workspace_documents/tags*",
            lambda route: _fulfill_json(route, tag_payload),
        )

        response = page.goto(
            f"{BASE_URL}/public_workspaces/public-1",
            wait_until="networkidle",
        )
        assert response is not None, (
            "Expected a navigation response when loading /public_workspaces/public-1."
        )

        if response.status in SKIP_RESPONSE_CODES:
            pytest.skip(
                f"/public_workspaces/public-1 returned HTTP {response.status} in this environment."
            )

        assert response.ok, (
            "Expected /public_workspaces/public-1 to load successfully, "
            f"got HTTP {response.status}."
        )

        expect(page.locator("#public-tag-folders-container")).to_contain_text(TAG_NAME)
        page.locator("#public-tag-folders-container .tag-folder-icon i").first.hover()

        audit = page.evaluate(
            """(tagName) => {
                refreshPublicTagManagementTable();
                renderPublicTagSelectionList();
                window.eval(`publicDocSelectedTags.add(${JSON.stringify(tagName)});`);
                updatePublicDocTagsDisplay();

                const selectors = [
                    '#public-tag-folders-container',
                    '#public-existing-tags-tbody',
                    '#public-tag-selection-list',
                    '#public-doc-selected-tags-container',
                ];

                const attributes = selectors.flatMap((selector) =>
                    Array.from(document.querySelectorAll(`${selector} *`)).flatMap((node) =>
                        Array.from(node.attributes)
                            .filter((attr) => attr.name.toLowerCase().startsWith('on') || String(attr.value).includes('__publicTagColorXss'))
                            .map((attr) => ({
                                selector,
                                tagName: node.tagName,
                                attribute: attr.name,
                                value: attr.value,
                            }))
                    )
                );

                return {
                    attributes,
                    selectedTagsText: document.getElementById('public-doc-selected-tags-container')?.textContent || '',
                    managementText: document.getElementById('public-existing-tags-tbody')?.textContent || '',
                    selectionText: document.getElementById('public-tag-selection-list')?.textContent || '',
                    gridText: document.getElementById('public-tag-folders-container')?.textContent || '',
                    xssTriggered: !!window.__publicTagColorXss,
                };
            }""",
            TAG_NAME,
        )

        assert TAG_NAME in audit["gridText"]
        assert TAG_NAME in audit["managementText"]
        assert TAG_NAME in audit["selectionText"]
        assert TAG_NAME in audit["selectedTagsText"]
        assert audit["attributes"] == []
        assert audit["xssTriggered"] is False
    finally:
        context.close()
        browser.close()