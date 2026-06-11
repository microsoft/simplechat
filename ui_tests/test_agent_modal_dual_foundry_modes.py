# test_agent_modal_dual_foundry_modes.py
"""
UI test for dual Foundry agent modal modes.
Version: 0.241.185
Implemented in: 0.239.176

This test ensures that the agent modal exposes both Foundry modes and that the
mode-specific form sections toggle correctly in the browser.
"""

import os
from pathlib import Path

import pytest

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Install Playwright to run this UI test.")


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


@pytest.mark.ui
def test_agent_modal_dual_foundry_modes():
    """Validate Foundry mode toggling in the agent modal."""
    expect = playwright_sync.expect

    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()

        try:
            page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
            expect(page.locator("#agentModal")).to_be_attached()

            page.evaluate(
                """
                () => {
                    const modalEl = document.getElementById('agentModal');
                    if (!modalEl || !window.bootstrap) {
                        return;
                    }
                    const modal = new bootstrap.Modal(modalEl);
                    modal.show();
                }
                """
            )

            expect(page.get_by_label("Foundry (classic)")).to_be_visible()
            expect(page.get_by_label("New Foundry")).to_be_visible()
            expect(page.locator("#agent-foundry-mode-note")).to_contain_text("run as the signed-in user")

            page.get_by_label("New Foundry").check()
            expect(page.locator("#agent-foundry-fetch-btn-label")).to_have_text("Fetch Applications")
            expect(page.locator("#agent-foundry-select-label")).to_have_text("New Foundry Application")
            expect(page.locator("#agent-new-foundry-only")).to_be_visible()
            expect(page.locator("#agent-classic-foundry-only")).to_be_hidden()

            page.get_by_label("Foundry (classic)").check()
            expect(page.locator("#agent-foundry-fetch-btn-label")).to_have_text("Fetch Agents")
            expect(page.locator("#agent-foundry-select-label")).to_have_text("Foundry Agent")
            expect(page.locator("#agent-classic-foundry-only")).to_be_visible()
            expect(page.locator("#agent-new-foundry-only")).to_be_hidden()
        finally:
            context.close()
            browser.close()


@pytest.mark.ui
def test_agent_modal_foundry_auth_required_link():
    """Validate delegated Foundry discovery failures render a safe auth link."""
    expect = playwright_sync.expect

    repo_root = Path(__file__).resolve().parents[1]
    partial_path = repo_root / "application" / "single_app" / "templates" / "_agent_modal.html"
    module_path = repo_root / "application" / "single_app" / "static" / "js" / "agent_modal_stepper.js"
    partial_html = partial_path.read_text(encoding="utf-8")

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            page.route(
                "**/api/models/foundry/agents",
                lambda route: route.fulfill(
                    status=401,
                    content_type="application/json",
                    body=(
                        '{"error":"Foundry access requires consent",'
                        '"auth_required":true,'
                        '"auth_url":"https://login.microsoftonline.com/common/oauth2/v2.0/authorize?scope=https%3A%2F%2Fai.azure.com%2F.default",'
                        '"scopes":["https://ai.azure.com/.default"]}'
                    ),
                ),
            )

            page.set_content(
                f"""
                <html>
                  <body>
                    <div id="toast-container"></div>
                    {partial_html}
                    <script type="module">
                      import {{ AgentModalStepper }} from "file:///{module_path.as_posix()}";
                      window.agentStepper = new AgentModalStepper();
                    </script>
                  </body>
                </html>
                """
            )
            page.wait_for_function("window.agentStepper !== undefined")

            page.locator("#agent-type-aifoundry").check()
            page.locator("#agent-foundry-endpoint-select").evaluate(
                """
                (select) => {
                    const option = document.createElement('option');
                    option.value = 'foundry-endpoint';
                    option.textContent = 'Foundry Endpoint';
                    option.dataset.scope = 'global';
                    select.appendChild(option);
                    select.value = 'foundry-endpoint';
                }
                """
            )

            page.locator("#agent-foundry-fetch-btn").click()

            status = page.locator("#agent-foundry-fetch-status")
            expect(status).to_contain_text("Foundry access requires sign-in or consent.")
            auth_link = status.get_by_role("link", name="Sign in or grant Foundry access")
            expect(auth_link).to_have_attribute("href", "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?scope=https%3A%2F%2Fai.azure.com%2F.default")
            expect(auth_link).to_have_attribute("rel", "noopener noreferrer")
        finally:
            browser.close()
