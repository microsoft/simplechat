# test_agent_modal_foundry_workflow.py
"""
UI test for Foundry workflow agent modal controls.

Version: 0.241.196
Implemented in: 0.241.127

This test ensures that the agent modal exposes the generic Foundry Workflow
configuration controls without relying on hardcoded workflow names. Workflow
agents use Entra/RBAC auth and do not expose manual project API-key entry.
"""

from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Install Playwright to run this UI test.")


@pytest.mark.ui
def test_agent_modal_foundry_workflow_controls_render():
    """Validate workflow agent controls are present in the modal partial."""
    expect = playwright_sync.expect

    repo_root = Path(__file__).resolve().parents[1]
    partial_path = repo_root / "application" / "single_app" / "templates" / "_agent_modal.html"
    partial_html = partial_path.read_text(encoding="utf-8")

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.set_content(f"<html><body>{partial_html}</body></html>")

            assert page.locator("#agent-type-foundry-workflow").get_attribute("value") == "foundry_workflow"
            expect(page.locator("#agent-foundry-workflow-name")).to_be_attached()
            version_select = page.locator("#agent-foundry-workflow-responses-api-version")
            expect(version_select).to_be_attached()
            assert version_select.input_value() == "v1"
            assert version_select.locator("option").count() == 1
            expect(page.locator("#agent-foundry-workflow-include-document-context")).to_be_attached()
            expect(page.locator("#agent-foundry-workflow-max-context-chars")).to_be_attached()
            expect(page.locator("#agent-foundry-api-key")).to_have_count(0)
            expect(page.locator("#agent-foundry-mode-note")).to_contain_text("run as the signed-in user")
            expect(page.locator("#agent-foundry-mode-note")).to_contain_text("access to the Foundry project")
        finally:
            browser.close()
