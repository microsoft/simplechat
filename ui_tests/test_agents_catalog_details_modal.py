# test_agents_catalog_details_modal.py
"""
UI test for the Agents catalog details modal.
Version: 0.241.227
Implemented in: 0.241.225

This test ensures the Agents tab uses the shared workspace-style details modal
and renders agent instructions as sanitized Markdown.
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
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _fulfill_json(route, payload, status=200):
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(payload),
    )


@pytest.mark.ui
def test_agents_catalog_details_modal_renders_markdown(playwright):
    """Validate catalog agent details reuse the shared modal and Markdown renderer."""
    _require_ui_env()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1280, "height": 900},
    )
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    icon_data_url = "data:image/png;base64,iVBORw0KGgo="

    agent_payload = {
        "agents": [
            {
                "id": "agent-markdown-1",
                "name": "markdown_catalog_agent",
                "display_name": "Markdown Catalog Agent",
                "description": "Shows rendered instructions in the shared modal.",
                "instructions": "# Operating Guide\n\n- Review **markdown** safely\n- Keep links inert unless trusted",
                "agent_type": "local",
                "is_global": True,
                "is_group": False,
                "scope_type": "global",
                "scope_id": "global",
                "scope_name": None,
                "model_id": "gpt-5-mini",
                "model_label": "GPT 5 Mini",
                "usage_count": 4,
                "actions_to_load": ["document_search"],
                "action_labels": ["Document Search"],
                "tags": ["Markdown", "Catalog"],
                "icon": {"kind": "image", "value": icon_data_url},
                "catalog_key": "global:global:agent-markdown-1",
            }
        ]
    }

    page.route("**/api/agents/catalog*", lambda route: _fulfill_json(route, agent_payload))

    try:
        response = page.goto(f"{BASE_URL}/agents", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /agents."
        assert response.ok, f"Expected /agents to load successfully, got HTTP {response.status}."

        expect(page.locator("#agents-list-view .agent-row .agent-icon img")).to_have_attribute("src", icon_data_url)

        page.locator("#agents-list-view .agent-row").first.click()

        modal = page.locator("#item-view-modal")
        expect(modal).to_be_visible()
        expect(modal.locator(".modal-title")).to_have_text("Agent Details")
        expect(modal).to_contain_text("Basic Information")
        expect(modal).to_contain_text("Enterprise")
        expect(modal).to_contain_text("GPT 5 Mini")
        expect(modal).to_contain_text("Document Search")
        expect(modal).to_contain_text("Times Used")
        expect(modal.locator(".agent-view-icon img")).to_have_attribute("src", icon_data_url)

        markdown_heading = modal.locator(".rendered-markdown h1")
        expect(markdown_heading).to_have_text("Operating Guide")
        expect(modal.locator(".rendered-markdown strong")).to_have_text("markdown")
        expect(modal.locator(".rendered-markdown")).not_to_contain_text("# Operating Guide")

        assert not page_errors, f"Unexpected Agents catalog page errors: {page_errors}"
    finally:
        context.close()
        browser.close()