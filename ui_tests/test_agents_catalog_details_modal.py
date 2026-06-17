# test_agents_catalog_details_modal.py
"""
UI test for the Agents catalog details modal.
Version: 0.242.064
Implemented in: 0.242.061

This test ensures the Agents tab uses the shared workspace-style details modal,
opens details from the row/card surface, supports Popular time-window filters,
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
                "id": "agent-featured-1",
                "name": "featured_catalog_agent",
                "display_name": "Featured Catalog Agent",
                "description": "Seeded into Popular by an admin.",
                "instructions": "Featured helper.",
                "agent_type": "local",
                "is_global": True,
                "is_group": False,
                "scope_type": "global",
                "scope_id": "global",
                "scope_name": None,
                "model_id": "gpt-5-mini",
                "model_label": "GPT 5 Mini",
                "usage_count": 0,
                "usage_count_all_time": 0,
                "usage_count_30_days": 0,
                "actions_to_load": [],
                "action_labels": [],
                "tags": ["Featured"],
                "icon": {"kind": "bootstrap", "value": "bi-stars"},
                "catalog_key": "global:global:agent-featured-1",
                "is_promoted_popular": True,
                "promoted_popular_window": "both",
                "promoted_popular_rank": 0,
                "promoted_popular_order": "before",
                "promoted_popular_tag_enabled": True,
                "promoted_popular_tag_label": "Featured",
            },
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
                "usage_count": 2,
                "usage_count_all_time": 7,
                "usage_count_30_days": 2,
                "actions_to_load": ["document_search"],
                "action_labels": ["Document Search"],
                "tags": ["Markdown", "Catalog"],
                "icon": {"kind": "image", "value": icon_data_url},
                "catalog_key": "global:global:agent-markdown-1",
            },
            {
                "id": "agent-recent-1",
                "name": "recent_catalog_agent",
                "display_name": "Recent Catalog Agent",
                "description": "Shows the recent popularity window.",
                "instructions": "Recent usage helper.",
                "agent_type": "local",
                "is_global": True,
                "is_group": False,
                "scope_type": "global",
                "scope_id": "global",
                "scope_name": None,
                "model_id": "gpt-5-mini",
                "model_label": "GPT 5 Mini",
                "usage_count": 5,
                "usage_count_all_time": 3,
                "usage_count_30_days": 5,
                "actions_to_load": [],
                "action_labels": [],
                "tags": ["Recent"],
                "icon": {"kind": "bootstrap", "value": "bi-clock-history"},
                "catalog_key": "global:global:agent-recent-1",
            }
        ]
    }

    page.route("**/api/agents/catalog*", lambda route: _fulfill_json(route, agent_payload))

    try:
        response = page.goto(f"{BASE_URL}/agents", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /agents."
        assert response.ok, f"Expected /agents to load successfully, got HTTP {response.status}."

        expect(page.get_by_role("heading", name="Find your next AI partner")).to_be_visible()
        expect(page.get_by_role("button", name="Search")).to_be_visible()
        expect(page.locator("#agents-count-label")).to_have_count(0)
        expect(page.locator("#agents-results-count")).to_have_count(0)
        expect(page.locator("#agents-list-view .agent-row").first).to_contain_text("Featured Catalog Agent")
        expect(page.locator("#agents-list-view .agent-row").first).to_contain_text("Featured")
        expect(page.get_by_role("button", name="Most Popular All Time")).to_have_attribute("aria-pressed", "true")
        page.get_by_role("button", name="Last 30 Days").click()
        expect(page.get_by_role("button", name="Last 30 Days")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#agents-list-view .agent-row").first).to_contain_text("Featured Catalog Agent")
        page.get_by_role("button", name="Most Popular All Time").click()
        expect(page.locator("#agents-list-view .agent-row").first).to_contain_text("Featured Catalog Agent")
        agent_row = page.locator("#agents-list-view .agent-row").filter(has_text="Markdown Catalog Agent").first
        expect(agent_row.locator(".agent-icon img")).to_have_attribute("src", icon_data_url)
        expect(agent_row.locator(".agent-info-icon-btn")).to_have_attribute(
            "aria-label",
            "View details for Markdown Catalog Agent",
        )
        expect(agent_row.get_by_text("Details", exact=True)).to_have_count(0)

        agent_row.click()

        modal = page.locator("#item-view-modal")
        expect(modal).to_be_visible()
        expect(modal.locator(".modal-title")).to_have_text("Agent Details")
        expect(modal).to_contain_text("Basic Information")
        expect(modal).to_contain_text("Enterprise")
        expect(modal).to_contain_text("GPT 5 Mini")
        expect(modal).to_contain_text("Document Search")
        expect(modal).to_contain_text("Times Used All Time")
        expect(modal).to_contain_text("Times Used Last 30 Days")
        expect(modal).to_contain_text("7")
        expect(modal).to_contain_text("2")
        expect(modal.locator(".agent-view-icon img")).to_have_attribute("src", icon_data_url)

        markdown_heading = modal.locator(".rendered-markdown h1")
        expect(markdown_heading).to_have_text("Operating Guide")
        expect(modal.locator(".rendered-markdown strong")).to_have_text("markdown")
        expect(modal.locator(".rendered-markdown")).not_to_contain_text("# Operating Guide")

        page.evaluate("""
            () => {
                const directory = document.querySelector('.agents-directory');
                if (directory) {
                    directory.dataset.showInstructionsInDetails = 'false';
                }
            }
        """)
        page.keyboard.press("Escape")
        expect(modal).not_to_be_visible()
        agent_row.click()
        expect(modal).to_be_visible()
        expect(modal).to_contain_text("Basic Information")
        expect(modal).not_to_contain_text("Instructions")
        expect(modal.locator(".rendered-markdown")).to_have_count(0)

        assert not page_errors, f"Unexpected Agents catalog page errors: {page_errors}"
    finally:
        context.close()
        browser.close()