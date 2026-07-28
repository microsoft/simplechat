# test_workflow_document_action_modal.py
"""
UI test for workflow document action modal.
Version: 0.250.065
Implemented in: 0.250.063
Enhanced in: 0.250.065

This test ensures the workflow modal supports generic no-document automation,
uses Source/Target wording for comparison, and submits version-aware comparison
and per-document Analyze payloads.
"""

import json
import os
from pathlib import Path

import pytest

expect = None


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _require_playwright():
    global expect
    playwright_sync = pytest.importorskip("playwright.sync_api", reason="Install Playwright to run this UI test.")
    expect = playwright_sync.expect
    return playwright_sync


def _route_workflow_api(page, workflow_state):
    def handler(route):
        request = route.request
        if request.method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"workflows": workflow_state["items"]}),
            )
            return

        if request.method == "POST":
            payload = json.loads(request.post_data or "{}")
            workflow_state["saved_payloads"].append(payload)
            workflow_state["items"] = [
                {
                    "id": "workflow-compare-1",
                    "name": payload.get("name"),
                    "description": payload.get("description"),
                    "task_prompt": payload.get("task_prompt"),
                    "runner_type": payload.get("runner_type"),
                    "trigger_type": payload.get("trigger_type"),
                    "status": "idle",
                }
            ]
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({"success": True, "workflow": workflow_state["items"][0]}),
            )
            return

        route.fulfill(status=405, content_type="application/json", body=json.dumps({"error": "Unsupported"}))

    page.route("**/api/user/workflows**", handler)


def _route_agent_api(page, agents=None):
    page.route(
        "**/api/user/agents",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(list(agents or [])),
        ),
    )


def _route_document_apis(page):
    page.route(
        "**/api/documents?*",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "documents": [
                    {
                        "id": "doc-current",
                        "title": "Master Services Agreement",
                        "file_name": "msa.docx",
                    }
                ],
                "page": 1,
                "page_size": 10,
                "total_count": 1,
            }),
        ),
    )
    page.route(
        "**/api/documents/doc-current/versions",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "document_id": "doc-current",
                "versions": [
                    {
                        "id": "doc-v3",
                        "title": "Master Services Agreement",
                        "file_name": "msa.docx",
                        "version": 3,
                        "upload_date": "2025-02-10T00:00:00Z",
                        "is_current_version": True,
                    },
                    {
                        "id": "doc-v2",
                        "title": "Master Services Agreement",
                        "file_name": "msa.docx",
                        "version": 2,
                        "upload_date": "2025-01-22T00:00:00Z",
                        "is_current_version": False,
                    },
                    {
                        "id": "doc-v1",
                        "title": "Master Services Agreement",
                        "file_name": "msa.docx",
                        "version": 1,
                        "upload_date": "2025-01-05T00:00:00Z",
                        "is_current_version": False,
                    },
                ],
            }),
        ),
    )


def _open_workflows_tab(page):
    expect(page.locator("#personal-workspace-submenu [data-tab='workflows-tab']")).to_have_count(1)
    page.locator("#workflows-tab-btn").evaluate("button => button.click()")
    expect(page.locator("#workflows-tab")).to_be_visible()


def _advance_workflow_builder_to_tasks(page, workflow_name, instructions):
    """Complete General and Trigger, then initialize the first task."""
    expect(page.locator("[data-workflow-step-target='general']")).to_have_class("workflow-step-nav__item is-active")
    expect(page.locator("#workflow-trigger-settings-card")).to_be_hidden()
    page.fill("#workflow-name", workflow_name)
    page.click("#workflow-step-next-btn")
    expect(page.locator("#workflow-trigger-settings-card")).to_be_visible()
    page.click("#workflow-step-next-btn")
    expect(page.locator("#workflow-task-list .workflow-task-item")).to_have_count(1)
    page.fill("#workflow-task-name", "Primary task")
    page.fill("#workflow-task-prompt", instructions)


def _advance_workflow_builder_to_review(page):
    """Advance from Tasks through Reliability to Review."""
    page.click("#workflow-step-next-btn")
    expect(page.locator("#workflow-task-retry-count")).to_be_visible()
    page.click("#workflow-step-next-btn")
    expect(page.locator("#workflow-review-summary")).to_be_visible()
    expect(page.locator("#workflow-save-btn")).to_be_visible()


@pytest.mark.ui
def test_workflow_modal_saves_generic_automation_without_documents():
    """Validate a workflow can be saved with instructions and a runner only."""
    _require_ui_env()
    playwright_sync = _require_playwright()

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        workflow_state = {"items": [], "saved_payloads": []}

        _route_workflow_api(page, workflow_state)
        _route_agent_api(page)
        _route_document_apis(page)

        try:
            response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
            assert response is not None and response.ok, "Expected /workspace to load successfully."

            _open_workflows_tab(page)
            page.get_by_role("button", name="New Workflow").click()
            expect(page.locator("#workflowModal")).to_be_visible()

            action_options = page.locator("#workflow-document-action-type option").all_text_contents()
            assert action_options[:2] == ["No document action", "Search"]
            expect(page.locator("#workflow-document-action-type")).to_have_value("none")
            _advance_workflow_builder_to_tasks(
                page,
                "Scheduled Status Summary",
                "Summarize the current status and propose next steps.",
            )
            expect(page.locator("#workflow-document-targets-fields")).to_be_hidden()
            page.click("#workflow-add-task-btn")
            page.fill("#workflow-task-name", "Recommend actions")
            page.fill("#workflow-task-prompt", "Turn the summary into ordered next actions.")
            expect(page.locator("#workflow-task-list .workflow-task-item")).to_have_count(2)
            page.click("#workflow-step-next-btn")
            page.check("#workflow-error-strategy-continue")
            page.fill("#workflow-task-retry-count", "2")
            page.click("#workflow-step-next-btn")
            page.select_option("#workflow-alert-priority", "high")
            page.click("#workflow-save-btn")

            assert workflow_state["saved_payloads"], "Expected the workflow save handler to capture the modal payload."
            saved_payload = workflow_state["saved_payloads"][0]
            assert saved_payload["runner_type"] == "model"
            assert saved_payload["chat_capabilities_enabled"] is True
            assert [task["name"] for task in saved_payload["tasks"]] == ["Primary task", "Recommend actions"]
            assert saved_payload["task_prompt"] == "Summarize the current status and propose next steps."
            assert saved_payload["error_handling"] == {"strategy": "continue", "retry_count": 2}
            assert saved_payload["alert_priority"] == "high"
            assert saved_payload["document_action"]["type"] == "none"
            assert saved_payload["document_action"]["document_ids"] == []
            assert saved_payload["analyze"]["enabled"] is False
        finally:
            context.close()
            browser.close()


@pytest.mark.ui
def test_workflow_document_action_modal_comparison():
    """Validate the workflow modal shows the updated action labels and saves compare payloads."""
    _require_ui_env()
    playwright_sync = _require_playwright()

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        workflow_state = {"items": [], "saved_payloads": []}

        _route_workflow_api(page, workflow_state)
        _route_agent_api(page)
        _route_document_apis(page)

        try:
            response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
            assert response is not None and response.ok, "Expected /workspace to load successfully."

            _open_workflows_tab(page)

            page.get_by_role("button", name="New Workflow").click()
            expect(page.locator("#workflowModal")).to_be_visible()

            action_options = page.locator("#workflow-document-action-type option").all_text_contents()
            assert action_options[:4] == ["No document action", "Search", "Analyze", "Compare"]
            expect(page.locator("#workflow-document-action-type")).to_have_attribute(
                "title",
                "Run the workflow instructions without workspace document context.",
            )

            _advance_workflow_builder_to_tasks(
                page,
                "Compare Contract Baseline",
                "Compare the baseline contract against the latest amendments.",
            )
            page.select_option("#workflow-document-action-type", "comparison")

            expect(page.locator("#workflow-document-action-type")).to_have_attribute(
                "title",
                "Compare one source document against the selected target documents to explain differences, relationships, or downstream impact.",
            )
            expect(page.locator("#workflow-document-action-help")).to_contain_text(
                "Compare one source document against the selected target documents to explain differences, relationships, or downstream impact."
            )

            expect(page.locator("#workflow-comparison-target-fields")).to_be_visible()
            expect(page.locator("#workflow-analysis-target-fields")).to_be_hidden()
            expect(page.get_by_label("Target Versions")).to_be_visible()
            expect(page.get_by_label("Source Version")).to_be_visible()

            page.evaluate(
                """
                () => {
                    window.selectedDocuments = new Set(['doc-current']);
                }
                """
            )
            page.click("#workflow-use-selected-documents-btn")

            expect(page.locator("#workflow-comparison-target-document-ids option")).to_have_count(3)
            page.select_option("#workflow-comparison-target-document-ids", ["doc-v2", "doc-v1"])
            expect(page.locator("#workflow-comparison-left-document-id option")).to_have_count(2)
            page.select_option("#workflow-comparison-left-document-id", "doc-v1")
            _advance_workflow_builder_to_review(page)
            page.click("#workflow-save-btn")

            assert workflow_state["saved_payloads"], "Expected the workflow save handler to capture the modal payload."
            saved_payload = workflow_state["saved_payloads"][0]
            assert saved_payload["document_action"]["type"] == "comparison"
            assert saved_payload["document_action"]["document_ids"] == ["doc-v2", "doc-v1"]
            assert saved_payload["document_action"]["left_document_id"] == "doc-v1"
            assert saved_payload["document_action"]["right_document_ids"] == ["doc-v2"]
            assert saved_payload["analyze"]["enabled"] is False
        finally:
            context.close()
            browser.close()


@pytest.mark.ui
def test_workflow_document_action_modal_per_document_analysis():
    """Validate the workflow modal saves Analyze mode as per-document when selected."""
    _require_ui_env()
    playwright_sync = _require_playwright()

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        workflow_state = {"items": [], "saved_payloads": []}

        _route_workflow_api(page, workflow_state)
        _route_agent_api(page)
        _route_document_apis(page)

        try:
            response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
            assert response is not None and response.ok, "Expected /workspace to load successfully."

            _open_workflows_tab(page)

            page.get_by_role("button", name="New Workflow").click()
            expect(page.locator("#workflowModal")).to_be_visible()

            _advance_workflow_builder_to_tasks(
                page,
                "Analyze Each Policy",
                "Summarize each selected policy.",
            )
            page.select_option("#workflow-document-action-type", "analyze")

            expect(page.locator("#workflow-analysis-target-fields")).to_be_visible()
            expect(page.locator("#workflow-analysis-per-document")).to_be_visible()
            expect(page.locator("label[for='workflow-analysis-per-document']")).to_have_text("Run each document separately")

            page.fill("#workflow-analysis-document-ids", "doc-alpha, doc-beta")
            page.check("#workflow-analysis-per-document")
            _advance_workflow_builder_to_review(page)
            page.click("#workflow-save-btn")

            assert workflow_state["saved_payloads"], "Expected the workflow save handler to capture the modal payload."
            saved_payload = workflow_state["saved_payloads"][0]
            assert saved_payload["document_action"]["type"] == "analyze"
            assert saved_payload["document_action"]["document_ids"] == ["doc-alpha", "doc-beta"]
            assert saved_payload["document_action"]["analysis_mode"] == "per_document"
            assert saved_payload["analyze"]["enabled"] is True
            assert saved_payload["analyze"]["analysis_mode"] == "per_document"
        finally:
            context.close()
            browser.close()


@pytest.mark.ui
def test_workflow_task_runner_controls_safe_summaries_and_mobile_layout():
    """Validate task runner overrides, safe labels, review output, payloads, and responsive layout."""
    _require_ui_env()
    playwright_sync = _require_playwright()

    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            storage_state=STORAGE_STATE,
            viewport={"width": 1440, "height": 900},
        )
        page = context.new_page()
        workflow_state = {"items": [], "saved_payloads": []}
        malicious_agent_name = '<img id="task-runner-xss" src=x onerror="window.taskRunnerXss=true">'
        malicious_endpoint_name = '<svg id="task-runner-endpoint-xss" onload="window.taskRunnerXss=true"></svg>'

        _route_workflow_api(page, workflow_state)
        _route_agent_api(page, [
            {
                "id": "research-agent",
                "name": "server_research",
                "display_name": malicious_agent_name,
                "is_global": False,
                "is_group": False,
            }
        ])
        _route_document_apis(page)

        try:
            response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
            assert response is not None and response.ok, "Expected /workspace to load successfully."
            page.evaluate(
                """
                ([endpointName]) => {
                    window.taskRunnerXss = false;
                    window.globalModelEndpoints = [{
                        id: "global-fast",
                        name: endpointName,
                        provider: "aoai",
                        enabled: true,
                        models: [{ id: "fast-model", displayName: "Fast model", enabled: true }],
                    }];
                    window.workspaceModelEndpoints = [{
                        id: "personal-reasoning",
                        name: "Reasoning endpoint",
                        provider: "openai",
                        enabled: true,
                        models: [{ id: "reasoning-model", displayName: "Reasoning model", enabled: true }],
                    }];
                }
                """,
                [malicious_endpoint_name],
            )

            _open_workflows_tab(page)
            page.get_by_role("button", name="New Workflow").click()
            expect(page.locator("#workflowModal")).to_be_visible()
            expect(page.get_by_label("Default Runner")).to_have_value("model")

            _advance_workflow_builder_to_tasks(
                page,
                "Multi-agent publication",
                "Extract the source facts.",
            )
            expect(page.locator("#workflow-task-runner-type")).to_have_value("inherit")
            expect(page.locator("#workflow-task-model-fields")).to_be_hidden()
            expect(page.locator("#workflow-task-agent-fields")).to_be_hidden()

            page.fill("#workflow-task-name", "Extract facts")
            page.select_option("#workflow-task-runner-type", "model")
            expect(page.locator("#workflow-task-model-fields")).to_be_visible()
            expect(page.locator("#workflow-task-agent-fields")).to_be_hidden()
            page.select_option("#workflow-task-model-source", "global")
            page.select_option("#workflow-task-model-endpoint", "global-fast")
            page.select_option("#workflow-task-model", "fast-model")

            page.click("#workflow-add-task-btn")
            page.fill("#workflow-task-name", "Research facts")
            page.fill("#workflow-task-prompt", "Enrich the facts with authorized tools.")
            page.select_option("#workflow-task-runner-type", "agent")
            expect(page.locator("#workflow-task-agent-fields")).to_be_visible()
            expect(page.locator("#workflow-task-model-fields")).to_be_hidden()
            page.select_option("#workflow-task-agent", "personal:research-agent")

            page.click("#workflow-add-task-btn")
            page.fill("#workflow-task-name", "Publish")
            page.fill("#workflow-task-prompt", "Create the final artifact.")
            expect(page.locator("#workflow-task-runner-type")).to_have_value("inherit")
            expect(page.locator("#workflow-task-list .workflow-task-item")).to_have_count(3)

            page.get_by_role("button", name="Move Research facts up").click()
            task_names = page.locator("#workflow-task-list .workflow-task-item__name").all_text_contents()
            assert task_names == ["Research facts", "Extract facts", "Publish"]
            expect(page.locator("#workflow-task-list")).to_contain_text("Workflow default: Direct Model")
            expect(page.locator("#workflow-task-list")).to_contain_text(malicious_agent_name)
            expect(page.locator("#workflow-task-list #task-runner-xss")).to_have_count(0)
            expect(page.locator("#workflow-task-list #task-runner-endpoint-xss")).to_have_count(0)
            assert page.evaluate("window.taskRunnerXss") is False

            _advance_workflow_builder_to_review(page)
            review_summary = page.locator("#workflow-review-summary")
            expect(review_summary).to_contain_text("Default Runner")
            expect(review_summary).to_contain_text("Research facts - Agent")
            expect(review_summary).to_contain_text("Extract facts - Direct Model")
            expect(review_summary).to_contain_text("Publish - Workflow default")

            page.set_viewport_size({"width": 390, "height": 844})
            page.locator('[data-workflow-step-target="tasks"]').click()
            page.get_by_role("button", name="Edit Extract facts").click()
            expect(page.locator("#workflow-task-model-fields")).to_be_visible()
            source_box = page.locator("#workflow-task-model-source").bounding_box()
            endpoint_box = page.locator("#workflow-task-model-endpoint").bounding_box()
            model_box = page.locator("#workflow-task-model").bounding_box()
            assert source_box and endpoint_box and model_box
            assert source_box["y"] < endpoint_box["y"] < model_box["y"]
            for box in (source_box, endpoint_box, model_box):
                assert box["x"] >= 0
                assert box["x"] + box["width"] <= 391

            page.locator('[data-workflow-step-target="review"]').click()
            page.click("#workflow-save-btn")
            assert workflow_state["saved_payloads"], "Expected the workflow save handler to capture the modal payload."
            saved_tasks = workflow_state["saved_payloads"][0]["tasks"]
            assert [task["name"] for task in saved_tasks] == ["Research facts", "Extract facts", "Publish"]
            assert [task["runner"]["type"] for task in saved_tasks] == ["agent", "model", "inherit"]
            assert saved_tasks[0]["runner"]["selected_agent"] == {
                "id": "research-agent",
                "name": "server_research",
                "is_global": False,
                "is_group": False,
                "group_id": "",
            }
            assert saved_tasks[1]["runner"] == {
                "type": "model",
                "model_endpoint_id": "global-fast",
                "model_id": "fast-model",
            }
            assert page.evaluate("window.taskRunnerXss") is False
        finally:
            context.close()
            browser.close()