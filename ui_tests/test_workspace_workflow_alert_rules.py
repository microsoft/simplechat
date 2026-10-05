# test_workspace_workflow_alert_rules.py
"""
UI test for the workflow alert rules editor.
Version: 0.250.213
Implemented in: 0.250.213

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
                "id": "workflow-popup-options-1",
                "name": "Critical Group Signal Workflow",
                "description": "Exercises stored pop-up options.",
                "task_prompt": "Watch for critical signals.",
                "runner_type": "model",
                "trigger_type": "manual",
                "is_enabled": True,
                "model_binding_summary": {"label": "Default app model"},
                "alert_mode": "rules",
                "alert_rules": [
                    {
                        "id": "stored-popup-rule",
                        "name": "Critical signal",
                        "enabled": True,
                        "severity": "critical",
                        "delivery": "popup",
                        "require_acknowledgment": True,
                        "sound": "repeat",
                        "size": "large",
                        "audience": "group",
                        "scope": {"type": "final", "task_id": ""},
                        "condition": {
                            "type": "agent_signal",
                            "signal_name": "critical-signal",
                            "min_severity": "high",
                        },
                    }
                ],
                "status": "idle",
                "tasks": [
                    {
                        "id": "task-stored",
                        "type": "instructions",
                        "name": "Watch",
                        "instructions": "Watch for critical signals.",
                        "order": 1,
                        "runner": {"type": "inherit"},
                    }
                ],
            },
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


def _select_values(locator):
    return locator.locator("option").evaluate_all("(options) => options.map((option) => option.value)")


def _repo_root():
    return Path(__file__).resolve().parents[1]


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
        expect(second_rule.get_by_text("Pop-up options")).to_be_visible()
        expect(second_rule.get_by_text("These apply when the rule pops up.")).to_be_visible()
        expect(second_rule.get_by_label("Require acknowledgment")).not_to_be_checked()
        expect(second_rule.get_by_text(
            "The alert keeps coming back, on every page and device, until someone acknowledges it."
        )).to_be_visible()

        sound_select = second_rule.locator('[data-alert-rule-field="sound"]')
        size_select = second_rule.locator('[data-alert-rule-field="size"]')
        expect(sound_select).to_have_value("off")
        assert _select_values(sound_select) == ["off", "once", "repeat"]
        assert _select_values(size_select) == ["small", "medium", "large"]
        expect(second_rule.locator('[data-alert-rule-field="audience"]')).to_have_count(0)

        sound_select.select_option("repeat")
        expect(second_rule.get_by_label("Require acknowledgment")).to_be_checked()
        second_rule.get_by_label("Require acknowledgment").uncheck()
        expect(sound_select).to_have_value("once")
        size_select.select_option("large")

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
        assert text_rule["sound"] == "once"
        assert text_rule["size"] == "large"
        assert "require_acknowledgment" not in text_rule
        assert "audience" not in text_rule
        assert text_rule["condition"]["values"] == ["EXPIRING"]
        assert text_rule["scope"]["type"] == "final"

        default_rule = next(
            rule for rule in saved_payload["alert_rules"]
            if rule["condition"]["type"] == "run_status"
        )
        assert "require_acknowledgment" not in default_rule
        assert "sound" not in default_rule
        assert "size" not in default_rule
        assert "audience" not in default_rule
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


@pytest.mark.ui
def test_workflow_alert_popup_options_load_from_stored_rule_and_show_admin_note():
    """Stored pop-up options load into controls and show the admin sound-disabled note."""
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
        page.evaluate("window.workflowSettings.enable_workflow_alert_sounds = false")

        stored_row = page.locator("#workflows-table-body tr").filter(has_text="Critical Group Signal Workflow")
        expect(stored_row).to_be_visible()
        expect(stored_row).to_contain_text("Must be acknowledged")
        expect(stored_row).to_contain_text("Repeats sound")
        expect(stored_row).to_contain_text("Large")

        stored_row.get_by_role("button", name="Edit").click()
        expect(page.locator("#workflowModal")).to_be_visible()

        rule = page.locator("#workflow-alert-rules-list .workflow-alert-rule").first
        expect(rule.get_by_label("Require acknowledgment")).to_be_checked()
        expect(rule.locator('[data-alert-rule-field="sound"]')).to_have_value("repeat")
        expect(rule.locator('[data-alert-rule-field="size"]')).to_have_value("large")
        expect(rule.locator('[data-alert-rule-field="audience"]')).to_have_count(0)
        expect(rule.locator('[data-alert-rule-field="sound-admin-note"]')).to_contain_text(
            "Your administrator has turned off workflow alert sounds. This setting is kept, but no sound plays."
        )
    finally:
        context.close()
        browser.close()
        playwright_manager.stop()


def test_workflow_alert_popup_options_static_contracts():
    """The shared workflow editor exposes group-only audience controls and settings bootstrap."""
    root = _repo_root()
    workflow_js = (root / "application/single_app/static/js/workspace/workspace_workflows.js").read_text(encoding="utf-8")
    workspace_template = (root / "application/single_app/templates/workspace.html").read_text(encoding="utf-8")
    group_template = (root / "application/single_app/templates/group_workspaces.html").read_text(encoding="utf-8")

    assert 'dataset.alertRuleField = "require_acknowledgment"' in workflow_js
    assert 'dataset.alertRuleField = "sound"' in workflow_js
    assert 'dataset.alertRuleField = "size"' in workflow_js
    assert 'dataset.alertRuleField = "audience"' in workflow_js
    assert 'textContent = "Pop-up options"' in workflow_js
    assert 'textContent = "These apply when the rule pops up."' in workflow_js
    assert 'textContent = "Require acknowledgment"' in workflow_js
    assert 'createWorkflowAlertField("Sound"' in workflow_js
    assert 'createWorkflowAlertField("Size"' in workflow_js
    assert 'createWorkflowAlertField("Who gets it"' in workflow_js
    assert '{ value: "repeat", label: "Repeat until acknowledged" }' in workflow_js
    assert '{ value: "large", label: "Large (full screen)" }' in workflow_js
    assert '{ value: "group", label: "Everyone in the group" }' in workflow_js
    assert 'workflowWorkspaceConfig.scope === "group"' in workflow_js
    assert 'rule.requireAcknowledgment = true;' in workflow_js
    assert 'rule.sound = "once";' in workflow_js
    assert 'payload.require_acknowledgment = true;' in workflow_js
    assert 'payload.sound = rule.sound;' in workflow_js
    assert 'payload.size = rule.size;' in workflow_js
    assert 'payload.audience = rule.audience;' in workflow_js
    assert "settings.get('enable_workflow_alert_sounds', True)|tojson" in workspace_template
    assert "settings.get('enable_workflow_alert_sounds', True)|tojson" in group_template
