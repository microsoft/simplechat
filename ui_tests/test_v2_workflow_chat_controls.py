# test_v2_workflow_chat_controls.py
"""
Real-bundle workflow capability, result audience, and group Ask AI regressions.
Version: 0.261.343
Implemented in: 0.261.343

Uses the existing closed API fixture and Azure Playwright connect_options with its local
fallback. No workflow runs, directory changes, invitations, or model calls are made.
"""

import copy
import json
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.workflow_editor import GROUP_ID, WORKFLOW_ID, connect_options, workflow_ui  # noqa: E402,F401
from ui_tests.fixtures.workflow_workbench import create_workflow, edit_workflow, workflow_editor  # noqa: E402

pytestmark = pytest.mark.ui
RECIPIENT_ID = "00000000-0000-4000-8000-000000000042"
HOSTILE_NAME = '<img src=x onerror="window.__workflowXss=1">'
AUTOMATIC = {"version": 1, "mode": "orchestration", "required_capabilities": [], "visual_requirements": []}


def options(group=False):
    """The sanitized projection supplied by the production editor-options endpoint."""
    return {
        "default_model": {"label": "Default model", "valid": True},
        "workflow_assist_available": True,
        "chat_execution": {
            "modes": [
                {"id": "orchestration", "label": "Orchestration (automatic)", "available": True},
                {"id": "selected", "label": "Selected capabilities", "available": True},
                {"id": "off", "label": "Off", "available": True},
            ],
            "capabilities": [
                {"id": "web_search", "label": "Web search", "available": True},
                {"id": "deep_research", "label": "Deep research", "available": False, "reason": "Deep research is not enabled."},
            ],
            "visual_requirements": [{"id": "chart", "label": "Charts", "available": True}],
            "default": copy.deepcopy(AUTOMATIC),
        },
        "results_delivery": {
            "modes": [{"id": "history"}, {"id": "conversation"}, {"id": "task"}],
            "conversation_types": [{"id": "group" if group else "personal"}, {"id": "group_shared" if group else "shared"}],
            "recipient_choices": [{"id": RECIPIENT_ID, "label": HOSTILE_NAME}],
            "allow_all_group_members": group,
            "default": {
                "version": 1, "mode": "conversation", "conversation_type": "group" if group else "personal",
                "recipient_ids": [], "all_group_members": False,
            },
        },
    }


def saved_body(ui):
    writes = [entry for entry in ui.workflow_writes if entry.method in {"POST", "PATCH", "PUT"}]
    assert writes, "Expected a workflow save."
    return writes[-1].body


@pytest.mark.parametrize("width", [1440, 390])
def test_defaults_task_override_inheritance_and_results_audience(workflow_ui, width):
    ui, page = workflow_ui, workflow_ui.page
    ui.editor_option_overrides = options()
    page.route("**/api/user/collaboration-suggestions?*", lambda route: route.fulfill(
        content_type="application/json",
        body=json.dumps({"results": [{"user_id": RECIPIENT_ID, "display_name": HOSTILE_NAME}]}),
    ))
    ui.open("/workspace/workflows", width=width)
    editor = create_workflow(page)
    expect(editor.get_by_label("Chat capabilities", exact=True)).to_have_value("orchestration")
    expect(editor.get_by_label("Results audience", exact=True)).to_have_value("personal")
    expect(editor.get_by_label("Task chat capabilities", exact=True)).to_have_value("inherit")
    editor.get_by_label("Workflow name", exact=False).fill("Current events report")
    editor.get_by_label("Task name", exact=False).fill("Find current facts")
    editor.get_by_role("textbox", name="Instructions", exact=True).fill("Search current facts and chart them.")
    editor.get_by_label("Task chat capabilities", exact=True).select_option("selected")
    expect(editor.get_by_text("Choose at least one required capability or output before saving.", exact=True)).to_be_visible()
    expect(editor.get_by_role("checkbox", name="Deep research", exact=False)).to_be_disabled()
    editor.get_by_role("checkbox", name="Web search", exact=True).check()
    editor.get_by_role("checkbox", name="Charts", exact=True).check()
    editor.get_by_label("Task chat capabilities", exact=True).select_option("inherit")
    expect(editor.get_by_role("checkbox", name="Web search", exact=True)).to_have_count(0)
    editor.get_by_label("Chat capabilities", exact=True).select_option("selected")
    editor.get_by_role("checkbox", name="Web search", exact=True).check()
    expect(editor.get_by_text("Inherited: Selected capabilities · Web search", exact=True)).to_be_visible()
    editor.get_by_label("Results audience", exact=True).select_option("shared")
    editor.get_by_label("Search results recipients", exact=True).fill("Reviewer")
    editor.get_by_role("button", name=f"Add recipient {HOSTILE_NAME}", exact=True).click()
    expect(editor.get_by_text("Shared personal results · 1 named recipient", exact=True).last).to_be_visible()
    assert page.evaluate("window.__workflowXss || 0") == 0
    assert editor.locator("img[src=x]").count() == 0
    ui.assert_no_overflow()
    artifacts = ROOT / "ui_tests" / "artifacts" / "workflow-chat-controls"
    artifacts.mkdir(parents=True, exist_ok=True)
    editor.get_by_label("Results delivery", exact=True).scroll_into_view_if_needed()
    page.screenshot(path=str(artifacts / f"results-{width}.png"))
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(workflow_editor(page, "Create workflow")).to_have_count(0)
    body = saved_body(ui)
    assert body["chat_execution"]["required_capabilities"] == ["web_search"]
    assert "chat_execution" not in body["tasks"][0]
    assert body["results_delivery"]["recipient_ids"] == [RECIPIENT_ID]
    assert body["results_delivery"]["conversation_type"] == "shared"


def test_legacy_defaults_stay_absent_when_an_unrelated_field_is_saved(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.editor_option_overrides = options()
    ui.open("/workspace/workflows")
    editor = edit_workflow(page, "Quarterly review workflow")
    expect(editor.get_by_label("Chat capabilities", exact=True)).to_have_value("legacy")
    expect(editor.get_by_label("Results delivery", exact=True)).to_have_value("legacy")
    editor.get_by_label("Description", exact=False).first.fill("An unrelated edit.")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(workflow_editor(page)).to_have_count(0)
    body = saved_body(ui)
    assert body.get("chat_execution") is None
    assert body.get("results_delivery") is None
    assert body["chat_capabilities_enabled"] is True


def test_group_assist_available_without_personal_flag_and_audience_undo(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.editor_option_overrides = options(group=True)
    ui.group_workflows[GROUP_ID]["group-workflow"]["results_delivery"] = options(group=True)["results_delivery"]["default"]
    received = []

    def assist(route):
        body = route.request.post_data_json
        received.append(body)
        candidate = copy.deepcopy(body["draft"])
        candidate["chat_execution"] = copy.deepcopy(AUTOMATIC)
        candidate["results_delivery"] = {
            "version": 1, "mode": "conversation", "conversation_type": "group_shared",
            "recipient_ids": [], "all_group_members": True,
        }
        route.fulfill(content_type="application/json", body=json.dumps({
            "submission_id": body["submission_id"], "outcome": "changed", "reply": "Updated group results.",
            "candidate": candidate, "changes": [], "warnings": [], "context_documents": [],
        }))

    page.route(f"**/api/groups/{GROUP_ID}/workflows/assist", assist)
    ui.open("/groups")
    ui.select_group(GROUP_ID)
    editor = edit_workflow(page, "Group review workflow")
    editor.get_by_role("button", name="Ask AI", exact=True).click()
    composer = editor.get_by_role("textbox", name="Message Ask AI", exact=True)
    composer.fill("Use automatic capabilities and share the result with all current group members.")
    composer.press("Enter")
    expect(editor.get_by_text("Updated group results.", exact=True)).to_be_visible()
    expect(editor.get_by_text("Changed 2 things in the draft. Review before saving.", exact=True)).to_be_visible()
    assert len(received) == 1
    assert received[0]["draft"]["group_id"] == GROUP_ID
    editor.get_by_role("button", name="Ask AI", exact=True).click()
    expect(editor.get_by_label("Results audience", exact=True)).to_have_value("group_shared")
    expect(editor.get_by_role("checkbox", name=re.compile(r"^All current group members"))).to_be_checked()
    expect(editor.get_by_text("Shared with all current group members", exact=True).last).to_be_visible()
    editor.get_by_role("button", name="Ask AI", exact=True).click()
    editor.get_by_role("button", name=re.compile(r"^Undo this change:")).click()
    expect(editor.get_by_text("These changes were undone.", exact=True)).to_be_visible()
    editor.get_by_role("button", name="Ask AI", exact=True).click()
    expect(editor.get_by_label("Results audience", exact=True)).to_have_value("group")
    ui.assert_no_overflow()


def test_group_named_recipients_use_only_current_group_lookup(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.editor_option_overrides = options(group=True)
    ui.group_workflows[GROUP_ID]["group-workflow"]["results_delivery"] = options(group=True)["results_delivery"]["default"]
    lookups = []

    def members(route):
        lookups.append(route.request.url)
        route.fulfill(content_type="application/json", body=json.dumps([
            {"userId": RECIPIENT_ID, "displayName": "Group reviewer"},
        ]))

    page.route(f"**/api/groups/{GROUP_ID}/members*", members)
    ui.open("/groups")
    ui.select_group(GROUP_ID)
    editor = edit_workflow(page, "Group review workflow")
    editor.get_by_label("Results audience", exact=True).select_option("group_shared")
    expect(editor.get_by_label("Results audience", exact=True).locator("option[value=shared]")).to_have_count(0)
    editor.get_by_role("button", name="Add recipient Group reviewer", exact=True).click()
    all_members = editor.get_by_role("checkbox", name=re.compile(r"^All current group members"))
    all_members.focus()
    all_members.press("Space")
    expect(all_members).to_be_checked()
    expect(editor.get_by_role("button", name="Remove recipient Group reviewer", exact=True)).to_have_count(0)
    all_members.press("Space")
    expect(all_members).not_to_be_checked()
    editor.get_by_role("button", name="Add recipient Group reviewer", exact=True).click()
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(workflow_editor(page)).to_have_count(0)
    body = saved_body(ui)
    assert body["group_id"] == GROUP_ID
    assert body["results_delivery"]["conversation_type"] == "group_shared"
    assert body["results_delivery"]["recipient_ids"] == [RECIPIENT_ID]
    assert body["results_delivery"]["all_group_members"] is False
    assert lookups
    assert all(f"/api/groups/{GROUP_ID}/members" in url for url in lookups)
