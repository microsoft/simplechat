# test_workspace_workflow_tab_labels.py
"""
UI test for workspace workflow tab labels.
Version: 0.250.014
Implemented in: 0.250.014

This test ensures personal and group workspace navigation controls label the
workflow tabs as Workflows instead of scope-prefixed workflow labels.
"""

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ROOT = REPO_ROOT / "application" / "single_app" / "templates"


def _extract_workflow_controls(template_name):
    """Return the workflow option and tab button fragments from a workspace template."""
    template_text = (TEMPLATE_ROOT / template_name).read_text(encoding="utf-8")
    workflow_option = re.search(
        r'<option value="workflows-tab-btn">.*?</option>',
        template_text,
        flags=re.DOTALL,
    )
    workflow_button = re.search(
        r'<button\s+class="nav-link"\s+id="workflows-tab-btn".*?</button>',
        template_text,
        flags=re.DOTALL,
    )

    assert workflow_option is not None, f"Expected a workflows section option in {template_name}."
    assert workflow_button is not None, f"Expected a workflows tab button in {template_name}."

    return f"<select>{workflow_option.group(0)}</select>{workflow_button.group(0)}"


@pytest.mark.ui
def test_workspace_workflow_tabs_use_neutral_label():
    """Validate personal and group workspace workflow tabs are labeled Workflows."""
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    controls_html = "".join(
        [
            _extract_workflow_controls("workspace.html"),
            _extract_workflow_controls("group_workspaces.html"),
        ]
    )

    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    page = browser.new_page()

    try:
        page.set_content(f"<main>{controls_html}</main>")

        expect(page.locator('option[value="workflows-tab-btn"]')).to_have_text([
            "Workflows",
            "Workflows",
        ])
        expect(page.locator('button#workflows-tab-btn')).to_have_text([
            "Workflows",
            "Workflows",
        ])
        expect(page.locator("main")).not_to_contain_text("Personal Workflows")
        expect(page.locator("main")).not_to_contain_text("Group Workflows")
    finally:
        browser.close()
        playwright_context.stop()