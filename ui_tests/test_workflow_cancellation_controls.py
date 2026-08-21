# test_workflow_cancellation_controls.py
"""
UI test for workflow cancellation controls.
Version: 0.250.062
Implemented in: 0.250.062

This test ensures personal and group workflow views expose a cancel control for
active runs, send the cancellation request to the scoped API, and keep the
control disabled while cancellation is in progress.
"""

from pathlib import Path
from urllib.parse import urlparse

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_MODULE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workspace" / "workspace_workflows.js"
ACTIVITY_MODULE = REPO_ROOT / "application" / "single_app" / "static" / "js" / "workflow" / "workflow-activity.js"
HARNESS_ORIGIN = "http://workflow-cancellation.test"

TOAST_MODULE = "export function showToast() {}"
DOCUMENTS_MODULE = "export async function ensureDocumentPickerReady() { return null; } export function setEffectiveScopes() {}"
VIEW_UTILS_MODULE = """
export function escapeHtml(value) {
    return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;').replace(/'/g, '&#39;');
}
export function truncateDescription(value, maxLength) {
    return String(value || '').slice(0, Number(maxLength) || 0);
}
export function setupViewToggle() {}
export function switchViewContainers() {}
"""


def _require_playwright():
    return pytest.importorskip("playwright.sync_api", reason="Install Playwright to run workflow cancellation UI tests.")


def _scope_api_base(scope):
    return "/api/group/workflows" if scope == "group" else "/api/user/workflows"


def _active_workflow(status):
    return {
        "id": "workflow-active",
        "name": "Active Workflow",
        "description": "A workflow that is currently running.",
        "task_prompt": "Continue processing until cancelled.",
        "runner_type": "model",
        "trigger_type": "manual",
        "is_enabled": True,
        "status": status,
        "active_run_id": "run-active",
        "last_run_status": status,
        "last_run_started_at": "2026-07-27T12:00:00+00:00",
        "conversation_id": "conversation-active",
        "alert_priority": "none",
    }


def _workspace_harness_html(scope):
    api_base = _scope_api_base(scope)
    active_group_function = "getActiveGroupId: () => 'group-1'," if scope == "group" else "getActiveGroupId: () => '',"
    return f"""<!doctype html>
<html>
<head><meta charset="utf-8"></head>
<body>
    <script>
        window.workflowWorkspaceConfig = {{
            scope: "{scope}",
            apiBase: "{api_base}",
            activityScope: "{scope}",
            {active_group_function}
        }};
        window.documentActionCapabilities = {{}};
        window.urlAccessSettings = {{}};
    </script>
    <div id="workflows-list-view"><table><tbody id="workflows-table-body"></tbody></table></div>
    <div id="workflows-grid-view"></div>
    <input id="workflows-search" type="search">
    <div id="workflows-summary"></div>
    <script type="module" src="/static/js/workspace/workspace_workflows.js"></script>
</body>
</html>"""


def _activity_harness_html():
    return """<!doctype html>
<html>
<head><meta charset="utf-8"></head>
<body>
    <script>window.EventSource = class { close() {} };</script>
    <main id="main-content">
        <div class="workflow-activity-page">
            <h1 id="workflow-activity-title"></h1>
            <span id="workflow-activity-status"></span>
            <p id="workflow-activity-caption"></p>
            <a id="workflow-activity-conversation-link" class="d-none" href="#">Open workflow</a>
            <button id="workflow-activity-cancel-btn" type="button" class="d-none"><i></i><span>Cancel run</span></button>
            <button id="workflow-activity-refresh-btn" type="button">Refresh</button>
            <button id="workflow-activity-response-toggle" type="button" class="d-none"><i></i><span id="workflow-activity-response-toggle-label"></span></button>
            <div id="workflow-activity-response" class="d-none"></div>
            <div id="workflow-activity-stat-run"></div>
            <div id="workflow-activity-stat-total"></div>
            <div id="workflow-activity-stat-tools"></div>
            <div id="workflow-activity-stat-started"></div>
            <div id="workflow-activity-empty"></div>
            <div id="workflow-activity-timeline-viewport"><div id="workflow-activity-timeline"></div></div>
            <h2 id="workflow-activity-detail-title"></h2>
            <div id="workflow-activity-detail-meta"></div>
            <p id="workflow-activity-detail-summary"></p>
            <div id="workflow-activity-pending-action-controls" class="d-none"></div>
            <pre id="workflow-activity-detail-text"></pre>
            <div id="workflow-activity-event-history"></div>
        </div>
    </main>
    <script type="module" src="/static/js/workflow/workflow-activity.js"></script>
</body>
</html>"""


def _route_workspace_modules(page):
    page.route(
        "**/static/js/workspace/workspace_workflows.js",
        lambda route: route.fulfill(status=200, content_type="text/javascript", body=WORKSPACE_MODULE.read_text(encoding="utf-8")),
    )
    page.route(
        "**/static/js/chat/chat-toast.js",
        lambda route: route.fulfill(status=200, content_type="text/javascript", body=TOAST_MODULE),
    )
    page.route(
        "**/static/js/chat/chat-documents.js",
        lambda route: route.fulfill(status=200, content_type="text/javascript", body=DOCUMENTS_MODULE),
    )
    page.route(
        "**/static/js/workspace/view-utils.js",
        lambda route: route.fulfill(status=200, content_type="text/javascript", body=VIEW_UTILS_MODULE),
    )


@pytest.mark.ui
@pytest.mark.parametrize("scope", ["personal", "group"])
def test_shared_workspace_cancel_control_uses_scoped_api(scope):
    """Validate active personal and group workflow rows issue scoped cancel requests."""
    playwright_sync = _require_playwright()
    expect = playwright_sync.expect
    cancel_paths = []
    state = {"status": "running"}
    api_base = _scope_api_base(scope)

    def api_handler(route):
        request = route.request
        path = urlparse(request.url).path
        if request.method == "GET" and path == api_base:
            route.fulfill(status=200, content_type="application/json", json={"workflows": [_active_workflow(state["status"])]})
            return
        if request.method == "POST" and path == f"{api_base}/workflow-active/cancel":
            cancel_paths.append(path)
            state["status"] = "cancelling"
            route.fulfill(
                status=202,
                content_type="application/json",
                json={"success": True, "workflow": _active_workflow("cancelling"), "run": {"id": "run-active", "status": "cancelling"}},
            )
            return
        route.fulfill(status=404, content_type="application/json", json={"error": f"Unexpected API request: {path}"})

    playwright_manager = playwright_sync.sync_playwright().start()
    browser = playwright_manager.chromium.launch()
    context = browser.new_context()
    page = context.new_page()
    _route_workspace_modules(page)
    page.route("**/api/**", api_handler)
    page.route(
        f"{HARNESS_ORIGIN}/",
        lambda route: route.fulfill(status=200, content_type="text/html", body=_workspace_harness_html(scope)),
    )

    try:
        page.goto(f"{HARNESS_ORIGIN}/", wait_until="domcontentloaded")
        workflow_row = page.locator("#workflows-table-body tr").filter(has_text="Active Workflow")
        cancel_button = workflow_row.get_by_role("button", name="Cancel workflow run")
        expect(cancel_button).to_be_visible()
        cancel_button.click()

        expect(workflow_row).to_contain_text("Cancelling")
        expect(workflow_row.get_by_role("button", name="Cancel workflow run")).to_be_disabled()
        assert cancel_paths == [f"{api_base}/workflow-active/cancel"]
    finally:
        context.close()
        browser.close()
        playwright_manager.stop()


@pytest.mark.ui
@pytest.mark.parametrize("scope", ["personal", "group"])
def test_activity_cancel_control_uses_scoped_api(scope):
    """Validate the activity page cancels the exact active personal or group run."""
    playwright_sync = _require_playwright()
    expect = playwright_sync.expect
    cancel_paths = []
    state = {"status": "running"}
    api_base = _scope_api_base(scope)
    activity_api = f"{api_base}/activity"

    def api_handler(route):
        request = route.request
        path = urlparse(request.url).path
        if request.method == "GET" and path == activity_api:
            route.fulfill(
                status=200,
                content_type="application/json",
                json={
                    "workflow": {"id": "workflow-active", "name": "Active Workflow"},
                    "conversation": {"id": "conversation-active"},
                    "run": {"id": "run-active", "status": state["status"], "trigger_source": "manual", "started_at": "2026-07-27T12:00:00+00:00"},
                    "activities": [],
                    "lane_count": 1,
                    "live": state["status"] in {"running", "cancelling"},
                },
            )
            return
        if request.method == "POST" and path == f"{api_base}/workflow-active/runs/run-active/cancel":
            cancel_paths.append(path)
            state["status"] = "cancelling"
            route.fulfill(status=202, content_type="application/json", json={"success": True, "run": {"id": "run-active", "status": "cancelling"}})
            return
        route.fulfill(status=404, content_type="application/json", json={"error": f"Unexpected API request: {path}"})

    playwright_manager = playwright_sync.sync_playwright().start()
    browser = playwright_manager.chromium.launch()
    context = browser.new_context()
    page = context.new_page()
    page.route(
        "**/static/js/workflow/workflow-activity.js",
        lambda route: route.fulfill(status=200, content_type="text/javascript", body=ACTIVITY_MODULE.read_text(encoding="utf-8")),
    )
    page.route("**/api/**", api_handler)
    page.route(
        f"{HARNESS_ORIGIN}/workflow-activity**",
        lambda route: route.fulfill(status=200, content_type="text/html", body=_activity_harness_html()),
    )

    try:
        group_query = "&scope=group&groupId=group-1" if scope == "group" else ""
        page.goto(
            f"{HARNESS_ORIGIN}/workflow-activity?workflowId=workflow-active&runId=run-active{group_query}",
            wait_until="domcontentloaded",
        )
        cancel_button = page.locator("#workflow-activity-cancel-btn")
        expect(cancel_button).to_be_visible()
        cancel_button.click()

        expect(cancel_button).to_be_disabled()
        assert cancel_paths == [f"{api_base}/workflow-active/runs/run-active/cancel"]
    finally:
        context.close()
        browser.close()
        playwright_manager.stop()
