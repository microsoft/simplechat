# test_workflow_classic_advanced_guard.py
"""
Source-backed browser coverage for the Classic advanced-workflow edit guard.
Version: 0.261.116
Implemented in: 0.261.116

The actual local edit function must stop before loading runners or resetting a
draft for advanced definitions. Legacy eligibility and Run/Cancel are unchanged.
"""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401


SOURCE = Path(__file__).resolve().parents[1] / "application" / "single_app" / "static" / "js" / "workspace" / "workspace_workflows.js"
ORIGIN = "http://workflow-guard.test"
pytestmark = pytest.mark.ui


def _function(source, name):
    start = re.search(rf"(?m)^(?:async )?function {name}\(", source)
    assert start, f"Missing production function {name}."
    following = re.search(r"(?m)^(?:async )?function ", source[start.end():])
    assert following, f"Missing end boundary for production function {name}."
    return source[start.start():start.end() + following.start()]


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("version", [2, 3, 4, "3"])
def test_classic_advanced_edit_stops_before_preparation(page, scope, version):
    source = SOURCE.read_text(encoding="utf-8")
    functions = "\n".join(_function(source, name) for name in ("workflowNeedsNativeEditor", "openWorkflowModal"))
    script = """
window.preparationCalls = 0;
const workflowModal = {show() { window.preparationCalls++; }};
const workflowWorkspaceConfig = {scope: 'personal'};
function getWorkflowActiveGroupId() { return 'group-1'; }
async function loadAgentOptions() { window.preparationCalls++; throw new Error('Unexpected runner loading'); }
async function loadFileSyncSourceOptions() { window.preparationCalls++; throw new Error('Unexpected source loading'); }
function resetWorkflowForm() { window.preparationCalls++; }
function showToast(message, tone) {
    const notice = document.createElement('div');
    notice.classList.add('alert', `alert-${tone}`);
    notice.setAttribute('role', 'alert');
    notice.textContent = message;
    document.body.appendChild(notice);
}
""" + functions + """
document.getElementById('edit').addEventListener('click', () => openWorkflowModal(window.testWorkflow));
window.configureScope = scope => { workflowWorkspaceConfig.scope = scope; };
"""
    unexpected = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def route(request):
        if request.request.url == f"{ORIGIN}/":
            request.fulfill(
                content_type="text/html",
                body='<html lang="en"><body><button id="edit" type="button">Edit workflow</button><script src="/guard.js"></script></body></html>',
            )
        elif request.request.url == f"{ORIGIN}/guard.js":
            request.fulfill(content_type="application/javascript", body=script)
        else:
            unexpected.append(request.request.url)
            request.abort()

    page.route("**/*", route)
    page.goto(f"{ORIGIN}/")
    page.evaluate("(scope) => window.configureScope(scope)", scope)
    page.evaluate("(version) => { window.testWorkflow = {id: 'workflow', definition_version: version}; }", version)
    page.get_by_role("button", name="Edit workflow", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Open V2 to edit")
    expect(page.get_by_role("alert")).to_contain_text("Run and Cancel remain available")
    assert page.evaluate("window.preparationCalls") == 0
    assert page.evaluate("workflowNeedsNativeEditor(null)") is False
    assert page.evaluate("workflowNeedsNativeEditor({id: 'legacy'})") is False
    assert page.evaluate("workflowNeedsNativeEditor({definition_version: 1})") is False
    assert page.evaluate("workflowNeedsNativeEditor({definition_version: 1, flow: {}})") is True
    assert not unexpected
    assert not errors
