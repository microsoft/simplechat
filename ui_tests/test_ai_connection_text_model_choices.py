# test_ai_connection_text_model_choices.py
"""Browser regressions for Classic agent, workflow, and task model choices.

Version: 0.261.105
Implemented in: 0.261.105

All app routes and assets are fulfilled from this checkout. The shared browser
fixture supports local/Azure Playwright; local execution requires no Azure calls.
"""

import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest


pytest.importorskip("playwright.sync_api")
pytest.importorskip("azure.mgmt.playwright")
STATIC_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app" / "static"
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
# Register the existing optional Azure connection fixture; never provision resources.
from playwright_connection import connect_options  # noqa: E402, F401
from playwright.sync_api import expect  # noqa: E402


PAGE_HTML = """<!doctype html><html lang="en"><body>
<label for="agent-model">Agent model</label><select id="agent-model"></select>
<label for="workflow-model-endpoint-select">Workflow endpoint</label><select id="workflow-model-endpoint-select"></select>
<label for="workflow-model-select">Workflow model</label><select id="workflow-model-select"></select>
<label for="workflow-task-model-source">Task model source</label>
<select id="workflow-task-model-source"><option value="global">Global</option><option value="workspace">Workspace</option></select>
<label for="workflow-task-model-endpoint">Task endpoint</label><select id="workflow-task-model-endpoint"></select>
<label for="workflow-task-model">Task model</label><select id="workflow-task-model"></select>
</body></html>"""


def _serve_local_asset(route):
    path = urlsplit(route.request.url).path
    if path == "/":
        route.fulfill(content_type="text/html", body=PAGE_HTML)
        return
    if path == "/static/js/chat/chat-documents.js":
        route.fulfill(
            content_type="text/javascript",
            body="export function ensureDocumentPickerReady() {} export function setEffectiveScopes() {}",
        )
        return
    if not path.startswith("/static/"):
        route.abort()
        return
    asset = STATIC_ROOT.joinpath(*path.removeprefix("/static/").split("/")).resolve()
    if not asset.is_relative_to(STATIC_ROOT) or not asset.is_file():
        route.abort()
        return
    content = asset.read_text(encoding="utf-8")
    if path.endswith("/workspace/workspace_workflows.js"):
        # Expose existing internal renderers without changing their implementation.
        content += """
export { populateEndpointSelect, populateModelSelect,
    populateWorkflowTaskModelSourceSelect, populateWorkflowTaskModelEndpointSelect,
    populateWorkflowTaskModelSelect };
"""
    route.fulfill(content_type="text/javascript", body=content)


def _models():
    return [
        {"id": "text", "displayName": "Text model", "capability_status": {"chat": {"available": True}}},
        {"id": "legacy", "displayName": "Legacy chat alias"},
        {"id": "image", "displayName": "Image model", "capability_status": {"chat": {"available": False}}},
        {"id": "imported", "displayName": "Imported image model", "enabled_capabilities": ["image_generation"]},
    ]


@pytest.mark.ui
@pytest.mark.parametrize("scope", ["personal", "group"])
def test_text_consumers_hide_image_choices_and_preserve_workspace_scope(page, scope):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/*", _serve_local_asset)
    page.goto("http://simplechat.test/")
    state = {
        "globalModelEndpoints": [
            {"id": "global", "name": "Global connection", "provider": "aoai", "models": _models()},
            {"id": "project", "provider": "new_foundry", "models": []},
        ],
        "workspaceModelEndpoints": [
            {"id": "workspace", "name": "Workspace connection", "provider": "new_foundry", "models": _models()},
        ],
        "workflowWorkspaceConfig": {
            "scope": scope,
            "workspaceEndpointScope": "group" if scope == "group" else "user",
            "workspaceEndpointLabel": "Group" if scope == "group" else "Workspace",
        },
    }
    page.evaluate("(state) => Object.assign(window, state)", state)
    page.evaluate("""async () => {
        const agents = await import('/static/js/agents_common.js');
        const workflows = await import('/static/js/workspace/workspace_workflows.js');
        window.textConsumerModules = { agents, workflows };
        const choices = agents.getAvailableModels({
            settings: { enable_multi_model_endpoints: true,
                model_endpoints: [...window.globalModelEndpoints, ...window.workspaceModelEndpoints] },
            agent: { agent_type: 'local' }
        });
        agents.populateGlobalModelDropdown(document.getElementById('agent-model'), choices.models, null);
        workflows.populateEndpointSelect('workspace');
        workflows.populateModelSelect('workspace');
        workflows.populateWorkflowTaskModelSourceSelect('workspace');
        workflows.populateWorkflowTaskModelEndpointSelect('workspace');
        workflows.populateWorkflowTaskModelSelect();
    }""")
    expect(page.locator("#agent-model option")).to_have_text([
        "Text model", "Legacy chat alias", "Text model", "Legacy chat alias",
    ])
    expect(page.locator("#workflow-model-select option")).to_have_text(["Text model", "Legacy chat alias"])
    expect(page.locator("#workflow-task-model option")).to_have_text(["Text model", "Legacy chat alias"])
    expect(page.locator("#workflow-task-model-source")).to_have_value("workspace")
    expect(page.locator("#workflow-task-model-endpoint")).to_have_value("workspace")
    page.locator("#workflow-task-model").select_option("legacy")
    expect(page.locator("#workflow-task-model")).to_have_value("legacy")
    page.evaluate("() => window.textConsumerModules.workflows.populateWorkflowTaskModelSelect('image')")
    expect(page.locator('#workflow-task-model option[value="image"]')).to_have_text("image (Unavailable)")
    expect(page.locator('#workflow-task-model option[value="image"]')).to_be_disabled()
    retained = page.evaluate("""() => ({
        globalModelEndpoints: window.globalModelEndpoints,
        workspaceModelEndpoints: window.workspaceModelEndpoints,
        workflowWorkspaceConfig: window.workflowWorkspaceConfig
    })""")
    assert json.dumps(retained, sort_keys=True) == json.dumps(state, sort_keys=True)
    assert errors == []


@pytest.mark.ui
def test_image_only_connections_do_not_hide_legacy_chat_or_supply_a_chat_model(page):
    page.route("**/*", _serve_local_asset)
    page.goto("http://simplechat.test/")
    settings = {
        "enable_multi_model_endpoints": False,
        "gpt_model": {"selected": [{"deploymentName": "legacy-chat", "display_name": "Legacy chat"}]},
        "model_endpoints": [{
            "id": "image-only", "models": [{
                "id": "image", "capability_status": {"chat": {"available": False}},
            }],
        }],
    }
    page.evaluate("""async (settings) => {
        window.agentChoices = await import('/static/js/agents_common.js');
        window.agentSettings = settings;
        const { models } = window.agentChoices.getAvailableModels({ settings, agent: {} });
        window.agentChoices.populateGlobalModelDropdown(document.getElementById('agent-model'), models, null);
    }""", settings)
    expect(page.locator("#agent-model option")).to_have_text(["Legacy chat"])
    expect(page.locator("#agent-model")).to_be_enabled()
    page.evaluate("""() => {
        const settings = { ...window.agentSettings, enable_multi_model_endpoints: true };
        const { models } = window.agentChoices.getAvailableModels({ settings, agent: {} });
        window.agentChoices.populateGlobalModelDropdown(document.getElementById('agent-model'), models, null);
    }""")
    expect(page.locator("#agent-model")).to_be_disabled()
    expect(page.locator("#agent-model option")).to_have_text(["No models available"])
