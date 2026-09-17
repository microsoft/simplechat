# test_workflow_artifact_publication.py
"""
UI tests for explicit classic-workflow artifact publication.
Version: 0.261.109
Implemented in: 0.261.109

Use the production shared controls and workflow JavaScript with closed local
HTTP doubles. Validate opt-in, fixed destination persistence, and disabled model
controls without starting a workflow or contacting Azure.
"""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
ORIGIN = "http://publication.test"
WORKFLOWS = APP / "static" / "js" / "workspace" / "workspace_workflows.js"
FIELDS = APP / "templates" / "_workflow_publication_fields.html"


def install_harness(page, scope):
    errors = []
    requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    modules = {
        "/static/js/chat/chat-toast.js": "export function showToast(text) { document.getElementById('feedback').textContent = text; }",
        "/static/js/agents_common.js": "export function isChatModelAvailable() { return true; }",
        "/static/js/chat/chat-documents.js": (
            "export async function ensureDocumentPickerReady() { return null; } export function setEffectiveScopes() {}"
        ),
        "/static/js/workspace/view-utils.js": (
            "export function escapeHtml(text) { return String(text || ''); }"
            "export function truncateDescription(text) { return String(text || ''); }"
            "export function setupViewToggle() {} export function switchViewContainers() {}"
        ),
    }
    bridge = """
window.publicationHarness = {
    load: workflow => initializeWorkflowTasks(workflow),
    payload: () => buildWorkflowPayload()
};
"""
    html = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<style>.d-none { display: none !important; } input, select, textarea { max-width: 100%; }
button { min-height: 24px; min-width: 24px; }</style></head><body>
<script>window.documentActionCapabilities = {}; window.urlAccessSettings = {};
window.workflowWorkspaceConfig = { scope: "__SCOPE__", getActiveGroupId: () => window.activeGroupId || "active-group" };
</script>
<div id="feedback" role="status"></div>
<table><tbody id="workflows-table-body"></tbody></table><div id="workflows-grid-view"></div>
<form id="workflow-form">
<input id="workflow-name" value="Publish accepted analysis" aria-label="Workflow name">
<div id="workflow-task-list"></div><button type="button" id="workflow-add-task-btn">Add Task</button>
<label for="workflow-task-name">Task Name</label><input id="workflow-task-name">
__FIELDS__
<label for="workflow-task-runner-type">Runner</label>
<select id="workflow-task-runner-type"><option value="inherit">Workflow default</option></select>
<label for="workflow-task-prompt">Task Instructions</label><textarea id="workflow-task-prompt"></textarea>
<textarea id="workflow-task-brief" aria-label="Task brief"></textarea>
<button type="button" id="workflow-draft-instructions-btn">Draft Workflow Instructions</button>
<label for="workflow-document-action-type">Document action</label>
<select id="workflow-document-action-type"><option value="none">No document action</option></select>
</form>
<script type="module" src="/static/js/workspace/workspace_workflows.js"></script>
</body></html>""".replace("__SCOPE__", scope).replace("__FIELDS__", FIELDS.read_text(encoding="utf-8"))

    def handle(route):
        path = urlsplit(route.request.url).path
        if path == "/":
            route.fulfill(status=200, content_type="text/html", body=html)
        elif path == "/static/js/workspace/workspace_workflows.js":
            route.fulfill(status=200, content_type="text/javascript", body=WORKFLOWS.read_text(encoding="utf-8") + bridge)
        elif path in modules:
            route.fulfill(status=200, content_type="text/javascript", body=modules[path])
        elif path.startswith("/api/"):
            requests.append((route.request.method, path))
            route.fulfill(status=200, content_type="application/json", json={"workflows": [], "agents": [], "documents": []})
        else:
            route.fulfill(status=404, body="")

    page.route("**/*", handle)
    page.goto(ORIGIN, wait_until="networkidle")
    page.wait_for_function("Boolean(window.publicationHarness)")
    return errors, requests


@pytest.mark.ui
@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("width", [390, 1280])
def test_classic_publication_requires_opt_in_and_retains_fixed_destination(page, scope, width):
    template = "group_workspaces.html" if scope == "group" else "workspace.html"
    assert '{% include "_workflow_publication_fields.html" %}' in (APP / "templates" / template).read_text(encoding="utf-8")
    page.set_viewport_size({"width": width, "height": 900})
    errors, requests = install_harness(page, scope)
    page.evaluate("""() => window.publicationHarness.load({tasks: [
        {id: 'analysis', name: 'Analyze', instructions: 'Explain the risks.'},
        {id: 'publication', name: 'Publish', instructions: ''}
    ]})""")
    page.get_by_role("button", name="Edit Publish", exact=True).click()
    checkbox = page.get_by_role("checkbox", name="Publish an existing analysis artifact")
    expect(checkbox).not_to_be_checked()
    expect(page.locator("#workflow-task-publication-fields")).to_be_hidden()
    checkbox.focus()
    page.keyboard.press("Space")
    expect(checkbox).to_be_checked()
    expect(page.get_by_label("Task Instructions", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Draft Workflow Instructions")).to_be_disabled()
    expect(page.get_by_label("Runner", exact=True)).to_be_disabled()
    page.get_by_label("Existing artifact format", exact=True).select_option("md")
    page.get_by_label("Publication destination", exact=True).select_option("group")
    page.get_by_label("Destination workspace ID", exact=True).fill("fixed-destination")
    payload = page.evaluate("window.publicationHarness.payload()")
    assert "publication" not in payload["tasks"][0]
    assert payload["tasks"][1]["publication"] == {
        "artifact_format": "md", "workspace_scope": "group", "group_id": "fixed-destination",
    }
    assert payload["tasks"][1]["document_action"]["type"] == "none"
    assert payload["tasks"][1]["runner"] == {"type": "inherit"}
    page.evaluate("window.activeGroupId = 'different-active-group'")
    assert page.evaluate("window.publicationHarness.payload().tasks[1].publication.group_id") == "fixed-destination"
    page.evaluate("payload => window.publicationHarness.load(payload)", payload)
    page.get_by_role("button", name="Edit Publish", exact=True).click()
    expect(checkbox).to_be_checked()
    expect(page.get_by_label("Destination workspace ID", exact=True)).to_have_value("fixed-destination")
    checkbox.uncheck()
    expect(page.get_by_label("Task Instructions", exact=True)).to_be_enabled()
    assert "publication" not in page.evaluate("window.publicationHarness.payload().tasks[1]")
    assert not any(method == "POST" for method, _ in requests)
    assert not errors


@pytest.mark.ui
def test_publication_editor_never_guesses_a_destination(page):
    errors, _ = install_harness(page, "personal")
    page.evaluate("""() => window.publicationHarness.load({tasks: [
        {id: 'analysis', name: 'Analyze', instructions: 'Explain the risks.'},
        {id: 'publication', name: 'Publish', instructions: ''}
    ]})""")
    page.get_by_role("button", name="Edit Publish", exact=True).click()
    page.get_by_role("checkbox", name="Publish an existing analysis artifact").check()
    assert page.evaluate("""() => {
        try { window.publicationHarness.payload(); return ''; }
        catch (error) { return error.message; }
    }""") == "Choose an explicit publication destination for task 2."
    page.get_by_label("Publication destination", exact=True).select_option("public")
    assert "fixed destination workspace ID" in page.evaluate("""() => {
        try { window.publicationHarness.payload(); return ''; }
        catch (error) { return error.message; }
    }""")
    page.get_by_label("Destination workspace ID", exact=True).fill("fixed-public")
    assert page.evaluate("window.publicationHarness.payload().tasks[1].publication.public_workspace_id") == "fixed-public"
    assert not errors
