# test_tableau_action_modal_workflow.py
"""
UI test for Tableau action modal workflow.
Version: 0.241.210
Implemented in: 0.241.210

This test ensures the action modal exposes a custom Tableau configuration flow
instead of reusing another action type's UI.
"""

import re
from pathlib import Path

import pytest

try:
    from playwright.sync_api import expect, sync_playwright
except ModuleNotFoundError:
    expect = None
    sync_playwright = None


REPO_ROOT = Path(__file__).resolve().parents[1]
MODAL_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "_plugin_modal.html"
MODAL_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "plugin_modal_stepper.js"
VIEW_UTILS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "view-utils.js"


def _extract_fragment(source: str, start_marker: str, end_marker: str) -> str:
    start_index = source.index(start_marker)
    end_index = source.index(end_marker, start_index)
    return source[start_index:end_index]


@pytest.mark.ui
def test_tableau_action_modal_custom_workflow_renders():
    """Validate the Tableau action modal fields and summary card render as a dedicated workflow."""
    if sync_playwright is None or expect is None:
        pytest.skip("Install playwright to run this UI test.")

    template = MODAL_TEMPLATE.read_text(encoding="utf-8")
    modal_js = MODAL_JS.read_text(encoding="utf-8")
    view_utils_js = VIEW_UTILS_JS.read_text(encoding="utf-8")

    required_ids = [
        "tableau-config-section",
        "tableau-server-url",
        "tableau-site-content-url",
        "tableau-action-identity-group",
        "tableau-identity-select",
        "tableau-auth-method",
        "tableau-pat-name",
        "tableau-pat-secret",
        "tableau-username-password-group",
        "tableau-page-size",
        "tableau-max-results",
        "tableau-timeout",
        "tableau-use-server-version",
        "summary-tableau-section",
        "summary-tableau-auth-method",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    for marker in [
        "TABLEAU_PLUGIN_TYPE = 'tableau'",
        "TABLEAU_ACTION_IDENTITY_AUTH_TYPES = ['api_key', 'username_password']",
        "populateActionIdentitySelector('tableau'",
        "isTableauType",
        "toggleTableauAuthFields",
        "getTableauConfiguration",
        "populateTableauSummary",
        "Tableau Configuration",
    ]:
        assert marker in modal_js

    assert 't.includes("tableau")' in view_utils_js
    assert re.search(r"tableau-config-section[\s\S]*databricks-token", template) is None

    config_fragment = _extract_fragment(
        template,
        '<div id="tableau-config-section" class="d-none">',
        '<div id="simplechat-config-section" class="d-none">',
    )
    summary_fragment = _extract_fragment(
        template,
        '<div class="card mb-3 border-0 shadow-sm d-none" id="summary-tableau-section">',
        '<div class="card mb-3 border-0 shadow-sm" id="summary-simplechat-section"',
    )

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        page.set_content(
            f"""
            <!doctype html>
            <html lang="en">
              <head>
                <style>.d-none {{ display: none !important; }}</style>
              </head>
              <body>{config_fragment}{summary_fragment}</body>
            </html>
            """,
            wait_until="domcontentloaded",
        )
        page.locator("#tableau-config-section").evaluate("element => element.classList.remove('d-none')")
        page.locator("#summary-tableau-section").evaluate("element => element.classList.remove('d-none')")

        expect(page.get_by_label("Server URL")).to_be_visible()
        expect(page.get_by_label("Site Content URL")).to_be_visible()
        expect(page.get_by_label("Reusable Identity")).to_be_attached()
        expect(page.get_by_label("Authentication Method")).to_be_visible()
        expect(page.get_by_label("PAT Name")).to_be_visible()
        expect(page.get_by_label("PAT Secret")).to_be_visible()
        expect(page.get_by_label("Page Size")).to_be_visible()
        expect(page.get_by_label("Max Results")).to_be_visible()
        expect(page.get_by_label("Timeout (seconds)")).to_be_visible()
        expect(page.get_by_label("Use Tableau server version negotiation")).to_be_checked()
        expect(page.locator("#summary-tableau-section")).to_contain_text("Tableau Configuration")
        expect(page.locator("#summary-tableau-section")).to_contain_text("Server Version Negotiation")
    finally:
        browser.close()
        playwright_context.stop()