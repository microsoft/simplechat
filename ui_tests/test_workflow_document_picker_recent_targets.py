# test_workflow_document_picker_recent_targets.py
"""
UI test for workflow document picker and recent workflow document targets.
Version: 0.241.188
Implemented in: 0.241.188

This test ensures the workflow modal exposes the shared document picker, hides
raw document ID entry, and saves Recent documents Search, Analyze, and Compare
payloads, and uses the chat-style Edit Compare popup for selected Compare
source and target selection.
"""

import json
import os
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


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
            saved_workflow = {
                "id": "workflow-recent-documents",
                "name": payload.get("name"),
                "description": payload.get("description"),
                "task_prompt": payload.get("task_prompt"),
                "runner_type": payload.get("runner_type"),
                "trigger_type": payload.get("trigger_type"),
                "document_action": payload.get("document_action", {}),
                "status": "idle",
            }
            workflow_state["items"] = [saved_workflow]
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({"success": True, "workflow": saved_workflow}),
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
    def personal_documents_handler(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "documents": [
                    {
                        "id": "doc-current",
                        "title": "Quarterly Review",
                        "file_name": "quarterly-review.docx",
                    },
                    {
                        "id": "doc-target",
                        "title": "Quarterly Review Draft",
                        "file_name": "quarterly-review-draft.docx",
                    },
                ],
                "page": 1,
                "page_size": 10,
                "total_count": 2,
            }),
        )

    def versions_handler(route):
        request_url = route.request.url
        if "/api/documents/doc-current/versions" in request_url:
            versions = [
                {
                    "id": "doc-current-v2",
                    "title": "Quarterly Review",
                    "file_name": "quarterly-review.docx",
                    "version": 2,
                    "is_current_version": True,
                    "upload_date": "2025-01-01T12:00:00Z",
                },
                {
                    "id": "doc-current-v1",
                    "title": "Quarterly Review",
                    "file_name": "quarterly-review.docx",
                    "version": 1,
                    "is_current_version": False,
                    "upload_date": "2024-12-01T12:00:00Z",
                },
            ]
        else:
            versions = [
                {
                    "id": "doc-target-v1",
                    "title": "Quarterly Review Draft",
                    "file_name": "quarterly-review-draft.docx",
                    "version": 1,
                    "is_current_version": True,
                    "upload_date": "2024-11-01T12:00:00Z",
                }
            ]

        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"versions": versions}),
        )

    page.route("**/api/documents/*/versions", versions_handler)
    page.route(
        "**/api/documents/tags",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"tags": []}),
        ),
    )
    page.route("**/api/documents?*", personal_documents_handler)
    page.route(
        "**/api/group_documents**",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"documents": [], "tags": []})),
    )
    page.route(
        "**/api/public_workspace_documents**",
        lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps({"documents": [], "tags": []})),
    )


def _select_picker_document(page, expect, document_id):
    page.locator("#document-dropdown-button").click()
    document_item = page.locator(f"#document-dropdown-items [data-document-id='{document_id}']")
    expect(document_item).to_be_visible()
    document_item.click()


def _open_workflows_tab(page, expect):
    if page.locator("#workflows-tab-btn").count() == 0:
        pytest.skip("Personal workflows are disabled or unavailable for this authenticated user.")
    expect(page.locator("#personal-workspace-submenu [data-tab='workflows-tab']")).to_have_count(1)
    page.locator("#workflows-tab-btn").evaluate("button => button.click()")
    expect(page.locator("#workflows-tab")).to_be_visible()


@pytest.mark.ui
def test_workflow_modal_recent_document_targets_use_picker_contract():
    """Validate Recent documents mode hides raw IDs and saves recent target fields."""
    _require_ui_env()
    try:
        from playwright.sync_api import expect, sync_playwright
    except ModuleNotFoundError:
        pytest.skip("Install ui_tests requirements to run Playwright UI tests.")

    workflow_state = {"items": [], "saved_payloads": []}
    playwright_context = sync_playwright().start()
    browser = playwright_context.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    _route_workflow_api(page, workflow_state)
    _route_agent_api(page)
    _route_document_apis(page)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None and response.ok, "Expected /workspace to load successfully."

        _open_workflows_tab(page, expect)
        page.get_by_role("button", name="New Workflow").click()
        expect(page.locator("#workflowModal")).to_be_visible()

        page.fill("#workflow-name", "Search Recent Uploads")
        page.fill("#workflow-task-prompt", "Find issues in documents uploaded during the recent window.")
        page.select_option("#workflow-document-action-type", "search")

        expect(page.locator("#workflow-document-picker-card")).to_be_visible()
        expect(page.locator("#document-select")).to_have_count(1)
        expect(page.locator("#workflow-analysis-per-document-group")).to_be_hidden()
        expect(page.locator("label[for='workflow-analysis-document-ids']")).to_have_count(0)
        expect(page.locator("#workflow-analysis-document-ids")).to_have_attribute("type", "hidden")

        page.select_option("#workflow-analysis-target-mode", "recent")
        expect(page.locator("#workflow-document-picker-card")).to_be_hidden()
        expect(page.locator("#workflow-analysis-recent-window-group")).to_be_visible()
        page.fill("#workflow-analysis-recent-minutes", "7")
        page.click("#workflow-save-btn")

        assert workflow_state["saved_payloads"], "Expected the workflow save handler to capture the modal payload."
        saved_payload = workflow_state["saved_payloads"][0]
        assert saved_payload["document_action"]["type"] == "search"
        assert saved_payload["document_action"]["target_mode"] == "recent"
        assert saved_payload["document_action"]["recent_window_minutes"] == 7
        assert saved_payload["document_action"]["document_ids"] == []
        assert saved_payload["analyze"]["enabled"] is False

        page.get_by_role("button", name="New Workflow").click()
        expect(page.locator("#workflowModal")).to_be_visible()

        page.fill("#workflow-name", "Analyze Recent Uploads")
        page.fill("#workflow-task-prompt", "Summarize documents uploaded during the recent window.")
        page.select_option("#workflow-document-action-type", "analyze")
        expect(page.locator("#workflow-analysis-per-document-group")).to_be_visible()
        page.select_option("#workflow-analysis-target-mode", "recent")
        expect(page.locator("#workflow-document-picker-card")).to_be_hidden()
        page.fill("#workflow-analysis-recent-minutes", "9")
        page.click("#workflow-save-btn")

        saved_payload = workflow_state["saved_payloads"][1]
        assert saved_payload["document_action"]["type"] == "analyze"
        assert saved_payload["document_action"]["target_mode"] == "recent"
        assert saved_payload["document_action"]["recent_window_minutes"] == 9
        assert saved_payload["document_action"]["document_ids"] == []
        assert saved_payload["analyze"]["target_mode"] == "recent"
        assert saved_payload["analyze"]["document_ids"] == []

        page.get_by_role("button", name="New Workflow").click()
        expect(page.locator("#workflowModal")).to_be_visible()

        page.fill("#workflow-name", "Compare Recent Uploads")
        page.fill("#workflow-task-prompt", "Compare the documents uploaded during the recent window.")
        page.select_option("#workflow-document-action-type", "comparison")
        expect(page.locator("#workflow-analysis-per-document-group")).to_be_hidden()
        page.select_option("#workflow-analysis-target-mode", "recent")
        expect(page.locator("#workflow-document-picker-card")).to_be_hidden()
        expect(page.locator("#workflow-comparison-target-fields")).to_be_hidden()
        page.fill("#workflow-analysis-recent-minutes", "11")
        page.click("#workflow-save-btn")

        saved_payload = workflow_state["saved_payloads"][2]
        assert saved_payload["document_action"]["type"] == "comparison"
        assert saved_payload["document_action"]["target_mode"] == "recent"
        assert saved_payload["document_action"]["recent_window_minutes"] == 11
        assert saved_payload["document_action"]["document_ids"] == []
        assert saved_payload["document_action"]["left_document_id"] == ""
        assert saved_payload["document_action"]["right_document_ids"] == []

        page.get_by_role("button", name="New Workflow").click()
        expect(page.locator("#workflowModal")).to_be_visible()

        page.fill("#workflow-name", "Compare Selected Uploads")
        page.fill("#workflow-task-prompt", "Compare the selected source and target versions.")
        page.select_option("#workflow-document-action-type", "comparison")
        expect(page.locator("#workflow-analysis-per-document-group")).to_be_hidden()
        expect(page.locator("#workflow-document-picker-card")).to_be_visible()
        expect(page.locator("#workflow-comparison-target-fields")).to_be_visible()
        expect(page.locator("#workflow-comparison-target-document-ids")).to_have_class(r".*d-none.*")
        expect(page.locator("#workflow-comparison-left-document-id")).to_have_class(r".*d-none.*")

        _select_picker_document(page, expect, "doc-current")
        _select_picker_document(page, expect, "doc-target")
        page.locator("#workflow-comparison-edit-btn").click()
        expect(page.locator("#workflow-comparison-modal")).to_be_visible()
        expect(page.locator("#workflow-comparison-available-list")).to_contain_text("Quarterly Review")
        expect(page.locator("#workflow-comparison-source-dropzone")).to_contain_text("Quarterly Review")
        expect(page.locator("#workflow-comparison-selection-list")).to_contain_text("Quarterly Review Draft")

        page.locator("[data-workflow-comparison-set-source-id='doc-target-v1']").click()
        expect(page.locator("#workflow-comparison-source-dropzone")).to_contain_text("Quarterly Review Draft")
        expect(page.locator("#workflow-comparison-selection-list")).to_contain_text("Quarterly Review")
        page.locator("#workflow-comparison-modal").get_by_role("button", name="Done").click()
        expect(page.locator("#workflow-comparison-modal")).to_be_hidden()

        expect(page.locator("#workflow-comparison-inline-source-tags")).to_contain_text("Quarterly Review Draft")
        expect(page.locator("#workflow-comparison-inline-target-tags")).to_contain_text("Quarterly Review")
        page.click("#workflow-save-btn")

        saved_payload = workflow_state["saved_payloads"][3]
        assert saved_payload["document_action"]["type"] == "comparison"
        assert saved_payload["document_action"]["target_mode"] == "selected"
        assert saved_payload["document_action"]["left_document_id"] == "doc-target-v1"
        assert saved_payload["document_action"]["right_document_ids"] == ["doc-current-v2"]
        assert saved_payload["document_action"]["document_ids"] == ["doc-current-v2", "doc-target-v1"]
    finally:
        context.close()
        browser.close()
        playwright_context.stop()
