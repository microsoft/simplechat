# test_workflow_document_action_modal.py
"""
UI test for workflow document action modal.
Version: 0.241.182
Implemented in: 0.241.103

This test ensures the workflow modal exposes the renamed Search/Analyze/Compare
selector states, uses Source/Target wording, and submits version-aware
comparison payloads. It also validates the per-document Analyze mode payload.
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


def _route_agent_api(page):
    page.route(
        "**/api/user/agents",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps([])),
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
            assert action_options[:3] == ["Search", "Analyze", "Compare"]
            expect(page.locator("#workflow-document-action-type")).to_have_attribute(
                "title",
                "Find relevant information with the normal prompt flow instead of binding the workflow to fixed document targets.",
            )

            page.fill("#workflow-name", "Compare Contract Baseline")
            page.fill("#workflow-task-prompt", "Compare the baseline contract against the latest amendments.")
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

            page.fill("#workflow-name", "Analyze Each Policy")
            page.fill("#workflow-task-prompt", "Summarize each selected policy.")
            page.select_option("#workflow-document-action-type", "analyze")

            expect(page.locator("#workflow-analysis-target-fields")).to_be_visible()
            expect(page.locator("#workflow-analysis-per-document")).to_be_visible()
            expect(page.locator("label[for='workflow-analysis-per-document']")).to_have_text("Run each document separately")

            page.fill("#workflow-analysis-document-ids", "doc-alpha, doc-beta")
            page.check("#workflow-analysis-per-document")
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