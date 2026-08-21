# test_admin_document_action_capabilities_card.py
"""
UI test for admin document action capabilities placement.
Version: 0.260.019
Implemented in: 0.241.089
Updated in: 0.260.019

This test ensures the Document Action Capabilities card is visible at the top of
the Actions tab, explains that it controls the Action dropdown in Chat and
Workflow, and renders its configured limits.

The limit assertions are the regression guard for the Admin Settings 500: the
card reads values that used to be set in the Agents pane, and sibling
{% include %} panes do not share scope, so the whole page raised
jinja2.exceptions.UndefinedError before the values moved into this pane.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import expect


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
ADMIN_STORAGE_STATE = os.getenv("SIMPLECHAT_UI_ADMIN_STORAGE_STATE", "") or os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_base_url() -> None:
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")


def _require_storage_state() -> None:
    if not ADMIN_STORAGE_STATE or not Path(ADMIN_STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_ADMIN_STORAGE_STATE or SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _open_admin_settings(context, tab_id):
    """Open Admin Settings on a tab and return the page, or skip when unavailable."""
    page = context.new_page()
    page.add_init_script(
        """
        () => {
            sessionStorage.removeItem('adminSettingsActiveTab');
        }
        """
    )

    response = page.goto(f"{BASE_URL}/admin/settings#{tab_id}", wait_until="domcontentloaded")
    assert response is not None, "Expected a navigation response when loading /admin/settings."
    if response.status in {401, 403, 404}:
        pytest.skip("Admin settings page was not available for the configured admin session.")

    assert response.ok, (
        f"Expected /admin/settings to load successfully, got HTTP {response.status}. "
        "A 500 here usually means a pane uses a value that a different pane sets."
    )

    page.locator(f"#{tab_id}-tab").click()
    return page


@pytest.mark.ui
def test_admin_document_action_capabilities_card_is_top_of_actions_tab(playwright):
    """Validate the document action capabilities card renders at the top of the Actions tab."""
    _require_base_url()
    _require_storage_state()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = _open_admin_settings(context, "actions")

        card = page.locator("#document-action-capabilities-card")
        expect(card).to_be_visible()
        expect(card).to_contain_text("Document Action Capabilities")
        expect(card).to_contain_text("Action")
        expect(card).to_contain_text("Chat and Workflow")
        expect(card).to_contain_text("global agent and custom action cards below")

        card_top = card.bounding_box()["y"]
        pane_top = page.locator("#actions").bounding_box()["y"]
        assert card_top - pane_top < 200, (
            "Expected the document action capabilities card to render at the top of the Actions tab."
        )

        # Each limit input has to carry a value. An unresolved capability value
        # takes the whole page down rather than rendering an empty box, so these
        # also prove the values are read in the pane that renders them.
        limit_input_ids = (
            "document_action_analyze_chat_max_documents",
            "document_action_analyze_workflow_max_documents",
            "document_action_comparison_chat_max_documents",
            "document_action_comparison_workflow_max_documents",
        )
        for input_id in limit_input_ids:
            limit_input = page.locator(f"#{input_id}")
            expect(limit_input).to_be_visible()
            assert (limit_input.input_value() or "").strip(), (
                f"Expected #{input_id} to render a configured limit."
            )

        for toggle_id in ("document_action_analyze_enabled", "document_action_comparison_enabled"):
            expect(page.locator(f"#{toggle_id}")).to_be_visible()
    finally:
        context.close()
        browser.close()


@pytest.mark.ui
def test_admin_agents_tab_still_renders_its_own_configuration(playwright):
    """The Agents tab keeps its own cards now that the capabilities card has moved."""
    _require_base_url()
    _require_storage_state()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=ADMIN_STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )

    try:
        page = _open_admin_settings(context, "agents")

        expect(page.locator("#agents-configuration")).to_be_visible()
        expect(page.locator("#document-action-capabilities-card")).not_to_be_visible()
    finally:
        context.close()
        browser.close()
