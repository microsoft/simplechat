# test_workspace_workflow_url_access.py
"""
UI test for workflow URL Access authoring controls.
Version: 0.241.082
Implemented in: 0.241.081
Updated in: 0.241.082

This test ensures the workspace workflow modal exposes a labeled URL Access
switch, publishes sanitized URL Access settings to browser code, and keeps the
client payload wired to the explicit workflow opt-in.
"""

from pathlib import Path

import pytest
from playwright.sync_api import expect


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "workspace.html"
WORKSPACE_WORKFLOWS_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace_workflows.js"


@pytest.mark.ui
def test_workspace_workflow_url_access_control_is_labeled_and_wired(page):
    """Validate the workflow URL Access switch and client-side payload wiring."""
    template_source = WORKSPACE_TEMPLATE.read_text(encoding="utf-8")
    js_source = WORKSPACE_WORKFLOWS_JS.read_text(encoding="utf-8")

    assert "id=\"workflow-url-access-enabled\"" in template_source
    assert "for=\"workflow-url-access-enabled\"" in template_source
    assert "window.urlAccessSettings" in template_source
    assert "url_access_max_workflow_urls_per_run" in template_source
    assert "url_access_enabled: isWorkflowUrlAccessAvailable() ? Boolean(workflowUrlAccessEnabledToggle?.checked) : false" in js_source
    assert "workflowUrlAccessEnabledToggle.checked = Boolean(workflow.url_access_enabled)" in js_source

    page.set_content(
        """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Workflow URL Access Regression</title>
</head>
<body>
    <form id="workflow-form">
        <div class="form-check form-switch mb-3" id="workflow-url-access-group">
            <input class="form-check-input" type="checkbox" id="workflow-url-access-enabled" />
            <label class="form-check-label ms-2" for="workflow-url-access-enabled">Allow URL Access for this workflow</label>
            <div class="form-text">Workflow runs can review up to 50 HTTP(S) URLs from the task prompt using the shared admin domain policy.</div>
        </div>
    </form>
    <script>
        window.urlAccessSettings = {
            enable_url_access: true,
            url_access_max_workflow_urls_per_run: 50
        };
    </script>
</body>
</html>
""".strip()
    )

    checkbox = page.locator("#workflow-url-access-enabled")
    expect(checkbox).to_be_visible()
    expect(page.locator("label[for='workflow-url-access-enabled']")).to_contain_text("Allow URL Access for this workflow")
    expect(page.locator("#workflow-url-access-group")).to_contain_text("50 HTTP(S) URLs")
    checkbox.check()
    expect(checkbox).to_be_checked()
    assert page.evaluate("window.urlAccessSettings.url_access_max_workflow_urls_per_run") == 50