# test_workspace_workflow_alert_rules.py
"""
UI test for the workflow alert rules editor.
Version: 0.250.209
Implemented in: 0.250.209

This test ensures the workflow modal exposes the alert mode selector, shows the
rules editor only in rules mode, lets an owner build a condition-based rule, and
sends alert_mode, alert_rules and alert_evaluation in the save payload. It also
verifies a legacy workflow carrying only alert_priority loads as editable
migrated rules.
"""

import json
import os
import re
from pathlib import Path

import pytest


BASE_URL = os.getenv("SIMPLECHAT_UI_BASE_URL", "").rstrip("/")
STORAGE_STATE = os.getenv("SIMPLECHAT_UI_STORAGE_STATE", "")


def _get_playwright_sync():
    return pytest.importorskip("playwright.sync_api", reason="Install Playwright to run this UI test.")


def _require_ui_env():
    if not BASE_URL:
        pytest.skip("Set SIMPLECHAT_UI_BASE_URL to run this UI test.")
    if not STORAGE_STATE or not Path(STORAGE_STATE).exists():
        pytest.skip("Set SIMPLECHAT_UI_STORAGE_STATE to a valid authenticated Playwright storage state file.")


def _build_workflow_state():
    return {
        "items": [
            {
                "id": "workflow-legacy-1",
                "name": "Legacy Noisy Workflow",
                "description": "Created before alert rules existed.",
                "task_prompt": "Summarize the latest documents.",
                "runner_type": "model",
                "trigger_type": "manual",
                "is_enabled": True,
                "model_binding_summary": {"label": "Default app model"},
                "alert_priority": "medium",
                "status": "idle",
                "tasks": [
                    {
                        "id": "task-1",
                        "type": "instructions",
                        "name": "Summarize",
                        "instructions": "Summarize the latest documents.",
                        "order": 1,
                        "runner": {"type": "inherit"},
                    }
                ],
            },
        ],
        "saved_payloads": [],
    }


def _route_workflow_api(page, workflow_state):
    def handler(route):
        request = route.request
        method = request.method

        if method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"workflows": workflow_state["items"]}),
            )
            return

        if method in {"POST", "PUT", "PATCH"}:
            payload = json.loads(request.post_data or "{}")
            workflow_state["saved_payloads"].append(payload)
            saved_workflow = {
                "id": payload.get("id") or "workflow-new",
                "name": payload.get("name"),
                "description": payload.get("description"),
                "task_prompt": payload.get("task_prompt"),
                "runner_type": payload.get("runner_type"),
                "trigger_type": payload.get("trigger_type"),
                "alert_mode": payload.get("alert_mode"),
                "alert_rules": payload.get("alert_rules", []),
                "alert_priority": payload.get("alert_priority"),
                "is_enabled": payload.get("is_enabled", True),
                "status": "idle",
            }
            workflow_state["items"] = [saved_workflow, *workflow_state["items"]]
            route.fulfill(
                status=201,
                content_type="application/json",
                body=json.dumps({"success": True, "workflow": saved_workflow}),
            )
            return

        route.fulfill(status=405, content_type="application/json", body=json.dumps({"error": "Unsupported"}))

    page.route("**/api/user/workflows**", handler)


def _route_agent_api(page):
    page.route("**/api/user/agents", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps([]),
    ))


def _open_workflows_tab(page, expect):
    if page.locator("#workflows-tab-btn").count() == 0:
        pytest.skip("Personal workflows are disabled or unavailable for this authenticated user.")
    page.locator("#workflows-tab-btn").evaluate("button => button.click()")
    expect(page.locator("#workflows-tab")).to_be_visible()


@pytest.mark.ui
def test_workflow_alert_rules_editor_builds_a_conditional_alert():
    """An owner can choose rules mode and save a condition-based alert rule."""
    _require_ui_env()
    playwright_sync = _get_playwright_sync()
    expect = playwright_sync.expect
    playwright_manager = playwright_sync.sync_playwright()
    playwright = playwright_manager.start()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    workflow_state = _build_workflow_state()

    _route_workflow_api(page, workflow_state)
    _route_agent_api(page)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /workspace."
        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        _open_workflows_tab(page, expect)

        page.get_by_role("button", name="New Workflow").click()
        expect(page.locator("#workflowModal")).to_be_visible()
        page.fill("#workflow-name", "Certificate Watch")
        page.fill("#workflow-description", "Alert only when certificates are expiring.")
        page.fill("#workflow-task-prompt", "List certificates expiring in the next 30 days.")

        # Alerts default to off, so neither the priority nor the rules editor shows.
        expect(page.locator("#workflow-alert-mode")).to_have_value("off")
        expect(page.locator("#workflow-alert-rules-group")).to_have_class(re.compile(r"\bd-none\b"))

        page.select_option("#workflow-alert-mode", "rules")
        expect(page.locator("#workflow-alert-rules-group")).not_to_have_class(re.compile(r"\bd-none\b"))
        expect(page.locator("#workflow-alert-priority-group")).to_have_class(re.compile(r"\bd-none\b"))

        # Switching to rules seeds a starter rule so the editor is never empty.
        rule_rows = page.locator("#workflow-alert-rules-list .workflow-alert-rule")
        expect(rule_rows).to_have_count(1)

        page.locator("#workflow-alert-rule-add-btn").click()
        expect(rule_rows).to_have_count(2)

        second_rule = rule_rows.nth(1)
        second_rule.locator("input[type='text']").first.fill("Expiring certificates")
        second_rule.locator("select").nth(0).select_option("text_match")
        second_rule.locator("select").nth(1).select_option("critical")
        second_rule.locator("input[type='text']").last.fill("EXPIRING")

        page.click("#workflow-save-btn")

        assert workflow_state["saved_payloads"], "Expected the save handler to capture the workflow payload."
        saved_payload = workflow_state["saved_payloads"][-1]
        assert saved_payload["alert_mode"] == "rules"
        assert isinstance(saved_payload["alert_rules"], list)
        assert len(saved_payload["alert_rules"]) == 2
        assert saved_payload["alert_evaluation"]["on_error"] == "skip"

        rule_names = [rule["name"] for rule in saved_payload["alert_rules"]]
        assert "Expiring certificates" in rule_names

        text_rule = next(
            rule for rule in saved_payload["alert_rules"]
            if rule["condition"]["type"] == "text_match"
        )
        assert text_rule["severity"] == "critical"
        assert text_rule["condition"]["values"] == ["EXPIRING"]
        assert text_rule["scope"]["type"] == "final"
    finally:
        context.close()
        browser.close()
        playwright_manager.stop()


@pytest.mark.ui
def test_legacy_workflow_loads_as_editable_migrated_rules():
    """A workflow carrying only alert_priority opens with its migrated rules."""
    _require_ui_env()
    playwright_sync = _get_playwright_sync()
    expect = playwright_sync.expect
    playwright_manager = playwright_sync.sync_playwright()
    playwright = playwright_manager.start()

    browser = playwright.chromium.launch()
    context = browser.new_context(
        storage_state=STORAGE_STATE,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    workflow_state = _build_workflow_state()

    _route_workflow_api(page, workflow_state)
    _route_agent_api(page)

    try:
        response = page.goto(f"{BASE_URL}/workspace", wait_until="networkidle")
        assert response is not None, "Expected a navigation response when loading /workspace."
        assert response.ok, f"Expected /workspace to load successfully, got HTTP {response.status}."

        _open_workflows_tab(page, expect)

        legacy_row = page.locator("#workflows-table-body tr").filter(has_text="Legacy Noisy Workflow")
        expect(legacy_row).to_be_visible()
        expect(legacy_row).to_contain_text("Alert: Every run (medium)")

        legacy_row.get_by_role("button", name="Edit").click()
        expect(page.locator("#workflowModal")).to_be_visible()

        # The legacy priority is materialized as two editable rules.
        expect(page.locator("#workflow-alert-mode")).to_have_value("rules")
        rule_rows = page.locator("#workflow-alert-rules-list .workflow-alert-rule")
        expect(rule_rows).to_have_count(2)
        expect(page.locator("#workflow-alert-rules-list")).to_contain_text("Run failed")
        expect(page.locator("#workflow-alert-rules-list")).to_contain_text("Run completed")
    finally:
        context.close()
        browser.close()
        playwright_manager.stop()
