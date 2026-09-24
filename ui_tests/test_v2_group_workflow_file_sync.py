# test_v2_group_workflow_file_sync.py
"""
UI tests for group workflow File Sync triggers, stored alerts and approvals in native V2.
Version: 0.261.144
Implemented in: 0.261.141

These tests use the real V2 SPA bundle with the closed workflow fixture. The fixture answers the
group File Sync source list with the real `_serialize_workflow_file_sync_source`, and validates
group saves with the real `_normalize_file_sync_config`, `_normalize_schedule`, Monitor File Sync
trigger rules and, since 0.261.144, `normalize_workflow_alert_settings`. They cover:

* authoring a Monitor File Sync changes trigger and File Sync before run, checked on the POST body;
* editing an existing File Sync workflow, including a V2 round trip that keeps alerts, URL
  access, File Sync and document actions unchanged;
* the source list requested with the page's explicit `?group_id`, and never for members;
* client-side enforcement of the server rules, and the server's refusal text shown as returned;
* the read-only alert summary for members; managers edit alerts natively (0.261.144), so the M6
  classic alerts link is gone (`test_v2_workflow_alerts.py` covers the editor);
* approval decisions for a group durable run;
* personal workflows keep their File Sync unchanged, and since 0.261.144 personal Analyze tasks may
  rely on File Sync's changed files, as the server allows;
* the general personal-route trap on group workflow pages.
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.workflow_editor import (  # noqa: E402
    FILE_SYNC_SOURCES_PATH,
    GROUP_ID,
    OWNER_ID,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_record,
    workflow_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui
MONITOR_ID = "monitor-workflow"
GENERIC_SAVE_ERROR = "Invalid workflow settings. Review the task, runner, trigger, and document inputs."
ALERT_RULES = [
    {
        "id": "rule-changes", "name": "Files changed", "enabled": True, "severity": "high", "delivery": "popup",
        "scope": {"type": "final", "task_id": ""}, "condition": {"type": "file_sync", "outcome": "changes_found"},
        "order": 1,
    },
    {
        "id": "rule-risk", "name": "Risk mentioned", "enabled": False, "severity": "critical",
        "delivery": "notify_only", "scope": {"type": "task", "task_id": "summarize"},
        "condition": {
            "type": "text_match", "mode": "contains_any", "pattern": "", "values": ["penalty"], "case_sensitive": False,
        },
        "order": 2,
    },
]
SUMMARIZE_ACTION = {
    "type": "analyze", "doc_scope": "group", "active_group_ids": [GROUP_ID], "active_public_workspace_id": [],
    "window_unit": "pages", "window_size": None, "window_percent": None, "max_retries_per_window": 1,
    "document_ids": [], "left_document_id": "", "right_document_ids": [], "analysis_mode": "per_document",
    "target_mode": "selected", "recent_window_minutes": 10,
}
STORED_FINANCE_SOURCE = {
    "scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share",
    "name": "Finance share", "source_type": "smb",
}


def labelled(page, name):
    return page.get_by_label(re.compile(rf"^{re.escape(name)}(?:\s*\*)?\s*$"))


def monitored_workflow(identifier=MONITOR_ID, **overrides):
    """A group File Sync workflow in the shape the server stores it."""
    return workflow_record(
        identifier,
        name="Monitor finance drops",
        description="Summarize every changed finance file.",
        group_id=GROUP_ID,
        trigger_type="file_sync",
        schedule={"unit": "minutes", "value": 45},
        task_prompt="Summarize each changed finance file.",
        m365_run_as_user_id="",
        file_sync={
            "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
            "sources": [copy.deepcopy(STORED_FINANCE_SOURCE)],
        },
        alert_mode="rules",
        alert_priority="high",
        alert_evaluation={"on_error": "alert"},
        alert_rules=copy.deepcopy(ALERT_RULES),
        url_access_enabled=True,
        url_access_authorized=True,
        url_access_authorized_by=OWNER_ID,
        url_access_authorized_at="2026-09-20T09:00:00+00:00",
        reference_inputs=[],
        tasks=[
            {
                "id": "summarize", "type": "instructions", "name": "Summarize changes",
                "instructions": "Summarize each changed finance file.", "order": 1, "runner": {"type": "inherit"},
                "document_action": copy.deepcopy(SUMMARIZE_ACTION),
            },
            {
                "id": "update", "type": "instructions", "name": "Draft the update",
                "instructions": "Draft the team update from the summaries.", "order": 2, "runner": {"type": "inherit"},
                "document_action": {"type": "none"},
            },
        ],
        **overrides,
    )


def open_group_workflows(ui):
    ui.open("/groups")
    ui.select_group(GROUP_ID)
    expect(ui.page.get_by_role("heading", name="Workflows", exact=True)).to_be_visible()


def workflow_post(ui):
    writes = [request for request in ui.workflow_writes if request.method == "POST"]
    assert writes, "Expected a workflow save request."
    return writes[-1]


def source_requests(ui):
    return [request for request in ui.requests if request.path.endswith("/file-sync-sources")]


def trigger_options(page):
    return labelled(page, "Trigger").locator("option").all_inner_texts()


def before_run_toggle(page):
    return page.get_by_role("checkbox", name=re.compile(r"^Run File Sync before each run"))


def source_checkbox(page, label):
    return page.get_by_role("checkbox", name=f"Use File Sync source {label}", exact=True)


def fill_required_basics(page, name):
    labelled(page, "Workflow name").fill(name)
    labelled(page, "Model").select_option(label="Workspace GPT · aoai")
    labelled(page, "Instructions").first.fill("Summarize every changed finance file.")


def test_manager_authors_a_monitor_trigger_and_posts_the_server_shape(workflow_ui):
    """A group manager picks the trigger and a source; the POST carries what the server accepts."""
    ui, page = workflow_ui, workflow_ui.page
    open_group_workflows(ui)
    page.get_by_role("button", name="Create workflow", exact=True).click()
    dialog = page.get_by_role("dialog", name="Create workflow", exact=True)
    expect(dialog).to_be_visible()

    expect(source_checkbox(page, "Finance share (Group)")).to_be_visible()
    assert source_requests(ui) and all(
        request.path == FILE_SYNC_SOURCES_PATH and request.query == {"group_id": [GROUP_ID]}
        for request in source_requests(ui)
    )
    assert trigger_options(page) == ["Manual", "Interval", "Monitor File Sync changes"]
    fill_required_basics(page, "Monitor finance drops")
    labelled(page, "Trigger").select_option("file_sync")

    expect(before_run_toggle(page)).to_be_checked()
    expect(before_run_toggle(page)).to_be_disabled()
    expect(page.get_by_label("Wait for File Sync", exact=True)).to_have_value("complete")
    expect(page.get_by_label("Wait for File Sync", exact=True)).to_be_disabled()
    expect(page.get_by_label("Continue the workflow", exact=True)).to_have_value("changed")
    expect(page.get_by_label("Continue the workflow", exact=True)).to_be_disabled()
    expect(labelled(page, "Interval value")).to_be_enabled()
    expect(page.get_by_text("Monitor workflows check the selected sources", exact=False)).to_be_visible()
    expect(page.get_by_role("status").filter(
        has_text="Select at least one group File Sync source for this workflow."
    )).to_be_visible()

    labelled(page, "Interval unit").select_option("minutes")
    labelled(page, "Interval value").fill("90")
    expect(page.get_by_role("status").filter(has_text="Schedule value for minutes must be between 1 and 59.")).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Select at least one group File Sync source")).to_be_visible()
    assert not ui.workflow_writes

    labelled(page, "Interval value").fill("30")
    source_checkbox(page, "Finance share (Group)").check()
    expect(source_checkbox(page, "Archive share (Group)")).not_to_be_checked()
    expect(dialog.get_by_text("Disabled", exact=True)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(dialog).to_have_count(0)

    write = workflow_post(ui)
    assert write.path == "/api/group/workflows"
    assert write.query == {"group_id": [GROUP_ID]}
    assert write.body["group_id"] == GROUP_ID
    assert write.body["trigger_type"] == "file_sync"
    assert write.body["schedule"] == {"unit": "minutes", "value": 30}
    assert write.body["file_sync"] == {
        "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
        "sources": [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"}],
    }
    assert ("group", GROUP_ID, "finance-share") in ui.file_sync_source_reads
    saved_id = next(identifier for identifier in ui.group_workflows[GROUP_ID] if identifier.startswith("group-created"))
    assert ui.group_workflows[GROUP_ID][saved_id]["file_sync"]["sources"] == [STORED_FINANCE_SOURCE]

    page.get_by_role("button", name="Edit Monitor finance drops", exact=True).click()
    expect(labelled(page, "Trigger")).to_have_value("file_sync")
    expect(source_checkbox(page, "Finance share (Group)")).to_be_checked()
    expect(labelled(page, "Interval value")).to_have_value("30")


def test_editing_an_existing_file_sync_workflow_round_trips_every_modelled_family(workflow_ui):
    """An unrelated edit sends alerts, URL access, File Sync and document actions back exactly as loaded.

    The Analyze task has no document_ids: with File Sync on and changed files as targets, the server
    supplies its dynamic placeholder (`allow_empty_file_sync_targets`), so V2 must accept and resend it.
    """
    ui, page = workflow_ui, workflow_ui.page
    ui.group_workflows[GROUP_ID][MONITOR_ID] = monitored_workflow()
    loaded = copy.deepcopy(ui.group_workflows[GROUP_ID][MONITOR_ID])
    assert loaded["file_sync"]["use_changed_documents"] is True
    assert loaded["tasks"][0]["document_action"]["type"] == "analyze"
    assert loaded["tasks"][0]["document_action"]["document_ids"] == []
    open_group_workflows(ui)
    page.get_by_role("button", name="Edit Monitor finance drops", exact=True).click()
    expect(labelled(page, "Trigger")).to_have_value("file_sync")
    expect(source_checkbox(page, "Finance share (Group)")).to_be_checked()
    preserved = page.get_by_text("V2 does not edit these legacy settings", exact=False)
    expect(preserved).to_be_visible()
    for authored_or_summarized in ("file sync settings", "alert mode", "alert priority", "alert rules", "alert evaluation"):
        expect(preserved).not_to_contain_text(authored_or_summarized)
    # A truly unknown legacy key is still listed as preserved-only.
    expect(preserved).to_contain_text("alert settings")
    page.get_by_text("Runner, inputs, references and outputs", exact=True).first.click()
    expect(labelled(page, "Document action").first).to_have_value("analyze")
    changed_files_note = page.get_by_text(
        "No evidence is selected, so this task analyzes the files each File Sync run changed.", exact=True,
    )
    expect(changed_files_note).to_be_visible()
    missing_evidence = page.get_by_text("Select at least one evidence document for this document action.", exact=True)
    expect(missing_evidence).to_have_count(0)

    labelled(page, "Description").first.fill("Summarize and flag risky changes.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)

    body = workflow_post(ui).body
    assert body["description"] == "Summarize and flag risky changes."
    assert body["definition_revision"] == loaded["definition_revision"]
    assert set(loaded) <= set(body), sorted(set(loaded) - set(body))
    for field in (
        "file_sync", "trigger_type", "schedule", "is_enabled", "alert_mode", "alert_priority", "alert_rules",
        "alert_evaluation", "url_access_enabled", "url_access_authorized", "url_access_authorized_by",
        "url_access_authorized_at", "alert_settings", "publication_options", "metadata",
    ):
        assert body[field] == loaded[field], field
    assert [task["document_action"] for task in body["tasks"]] == [task["document_action"] for task in loaded["tasks"]]
    assert body["tasks"][0]["document_action"]["type"] == "analyze"
    assert body["tasks"][0]["document_action"]["document_ids"] == []
    # The fixture's real `_normalize_file_sync_config` and trigger rules accepted the resent record.
    assert ("group", GROUP_ID, "finance-share") in ui.file_sync_source_reads
    assert ui.group_workflows[GROUP_ID][MONITOR_ID]["file_sync"] == loaded["file_sync"]

    page.get_by_role("button", name="Edit Monitor finance drops", exact=True).click()
    changed_files = page.get_by_role("checkbox", name=re.compile(r"^Use changed files as Analyze targets"))
    changed_files.uncheck(force=True)
    # Without changed files as targets, the server would refuse an Analyze task with no documents.
    expect(page.get_by_role("status").filter(has_text="Summarize changes needs selected evidence for Analyze.")).to_be_visible()
    page.get_by_text("Runner, inputs, references and outputs", exact=True).first.click()
    expect(missing_evidence).to_be_visible()
    expect(changed_files_note).to_have_count(0)
    writes_before = len(ui.workflow_writes)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Summarize changes needs selected evidence for Analyze.")).to_be_visible()
    assert len(ui.workflow_writes) == writes_before
    changed_files.check(force=True)
    expect(missing_evidence).to_have_count(0)

    source_checkbox(page, "Archive share (Group)").check()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert workflow_post(ui).body["file_sync"] == {
        "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
        "sources": [
            {"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"},
            {"scope_type": "group", "scope_id": GROUP_ID, "source_id": "archive-share"},
        ],
    }
    assert [source["name"] for source in ui.group_workflows[GROUP_ID][MONITOR_ID]["file_sync"]["sources"]] == [
        "Finance share", "Archive share",
    ]


def test_file_sync_before_run_follows_the_server_rules_for_manual_triggers(workflow_ui):
    """File Sync before run is optional for manual workflows, and queued plus changed is refused locally."""
    ui, page = workflow_ui, workflow_ui.page
    open_group_workflows(ui)
    page.get_by_role("button", name="Create workflow", exact=True).click()
    fill_required_basics(page, "Sync first")
    expect(page.get_by_label("Wait for File Sync", exact=True)).to_be_disabled()
    before_run_toggle(page).check(force=True)
    expect(page.get_by_label("Wait for File Sync", exact=True)).to_be_enabled()
    source_checkbox(page, "Finance share (Group)").check()
    page.get_by_label("Wait for File Sync", exact=True).select_option("queued")
    page.get_by_label("Continue the workflow", exact=True).select_option("changed")
    message = "File Sync must wait for completion before a workflow can continue only when changes are found."
    expect(page.get_by_role("status").filter(has_text=message)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text=message)).to_be_visible()
    assert not ui.workflow_writes

    page.get_by_label("Wait for File Sync", exact=True).select_option("complete")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    body = workflow_post(ui).body
    assert body["trigger_type"] == "manual"
    assert body["file_sync"] == {
        "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
        "sources": [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"}],
    }

    page.get_by_role("button", name="Edit Sync first", exact=True).click()
    before_run_toggle(page).uncheck(force=True)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert workflow_post(ui).body["file_sync"] == {
        "enabled": False, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
        "sources": [],
    }


def test_unavailable_saved_sources_must_be_removed_before_saving(workflow_ui):
    """A saved source the group no longer offers blocks the save instead of failing on the server."""
    ui, page = workflow_ui, workflow_ui.page
    workflow = monitored_workflow()
    workflow["file_sync"]["sources"].append({
        "scope_type": "group", "scope_id": GROUP_ID, "source_id": "deleted-share",
        "name": "Deleted share", "source_type": "smb",
    })
    ui.group_workflows[GROUP_ID][MONITOR_ID] = workflow
    open_group_workflows(ui)
    page.get_by_role("button", name="Edit Monitor finance drops", exact=True).click()
    stale = source_checkbox(page, "Deleted share")
    expect(stale).to_be_checked()
    expect(page.get_by_text("No longer available", exact=True)).to_be_visible()
    message = "Remove File Sync sources that are no longer available before saving: Deleted share."
    expect(page.get_by_role("status").filter(has_text=message)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text=message)).to_be_visible()
    assert not ui.workflow_writes

    # Unchecking an unavailable source removes it, so the control itself disappears.
    stale.click()
    expect(source_checkbox(page, "Deleted share")).to_have_count(0)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert workflow_post(ui).body["file_sync"]["sources"] == [
        {"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"},
    ]


def test_no_sources_hides_the_monitor_trigger_and_server_refusals_are_shown_as_returned(workflow_ui):
    """Without sources there is no Monitor trigger; a save the server refuses shows its own text."""
    ui, page = workflow_ui, workflow_ui.page
    ui.group_file_sync_enabled[GROUP_ID] = False
    open_group_workflows(ui)
    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(page.get_by_text("No File Sync sources are available to this group.", exact=True)).to_be_visible()
    assert trigger_options(page) == ["Manual", "Interval"]
    page.get_by_role("dialog", name="Create workflow", exact=True).get_by_role("button", name="Cancel", exact=True).click()

    ui.group_file_sync_enabled[GROUP_ID] = True
    page.get_by_role("button", name="Create workflow", exact=True).click()
    fill_required_basics(page, "Refused monitor")
    labelled(page, "Trigger").select_option("file_sync")
    source_checkbox(page, "Finance share (Group)").check()
    # File Sync is turned off for the group after the list loaded, so only the real server rule refuses.
    ui.group_file_sync_enabled[GROUP_ID] = False
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text=GENERIC_SAVE_ERROR)).to_be_visible()
    expect(labelled(page, "Workflow name")).to_have_value("Refused monitor")
    assert not ui.workflow_writes


def test_members_see_a_read_only_summary_and_never_request_sources(workflow_ui):
    """A member views the saved trigger and alerts without asking for the manager-only source list."""
    ui, page = workflow_ui, workflow_ui.page
    ui.group_can_manage = False
    ui.group_workflows[GROUP_ID][MONITOR_ID] = monitored_workflow()
    open_group_workflows(ui)
    expect(page.get_by_role("button", name="Create workflow", exact=True)).to_have_count(0)
    page.get_by_role("button", name="View Monitor finance drops", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(dialog.get_by_text("You have read-only access to workflows in this scope.", exact=True)).to_be_visible()
    expect(labelled(page, "Trigger")).to_have_value("file_sync")
    expect(labelled(page, "Trigger")).to_be_disabled()
    expect(source_checkbox(page, "Finance share")).to_be_checked()
    expect(source_checkbox(page, "Finance share")).to_be_disabled()
    alerts = page.get_by_role("region", name="Alerts")
    expect(alerts.get_by_text("Only when a condition is met", exact=True)).to_be_visible()
    expect(alerts.get_by_role("button", name=re.compile(r"Edit alerts in the classic workspace"))).to_have_count(0)
    expect(dialog.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert not source_requests(ui)
    assert not ui.workflow_writes


def test_managers_edit_stored_alerts_natively_with_no_classic_link(workflow_ui):
    """The Alerts section opens on the stored configuration as the server resolves it, for every definition version."""
    ui, page = workflow_ui, workflow_ui.page
    ui.group_workflows[GROUP_ID][MONITOR_ID] = monitored_workflow()
    ui.group_workflows[GROUP_ID]["every-run"] = workflow_record(
        "every-run", name="Every run alerts", group_id=GROUP_ID, reference_inputs=[],
        alert_mode="every_run", alert_priority="low", alert_rules=[],
    )
    ui.group_workflows[GROUP_ID]["legacy-alerts"] = workflow_record(
        "legacy-alerts", name="Legacy alerts", group_id=GROUP_ID, reference_inputs=[],
        definition_version=1, alert_priority="medium",
    )
    open_group_workflows(ui)
    alerts = page.get_by_role("region", name="Alerts", exact=True)
    rules = page.get_by_role("list", name="Alert rules", exact=True).get_by_role("listitem")

    page.get_by_role("button", name="Edit Monitor finance drops", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(alerts.get_by_label("When to alert", exact=True)).to_have_value("rules")
    expect(rules).to_have_count(2)
    expect(alerts.get_by_role("heading", name="Rule 1: Files changed", exact=True)).to_be_visible()
    expect(alerts.get_by_label("Alert rule 2 task", exact=True)).to_have_value("summarize")
    expect(alerts.get_by_label("If a model evaluated condition cannot be judged", exact=True)).to_have_count(0)
    dialog.get_by_role("button", name="Cancel", exact=True).click()

    page.get_by_role("button", name="Edit Every run alerts", exact=True).click()
    expect(alerts.get_by_label("When to alert", exact=True)).to_have_value("every_run")
    expect(alerts.get_by_label("Pop-up alert priority", exact=True)).to_have_value("low")
    expect(rules).to_have_count(0)
    dialog.get_by_role("button", name="Cancel", exact=True).click()

    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(alerts.get_by_label("When to alert", exact=True)).to_have_value("off")
    page.get_by_role("dialog", name="Create workflow", exact=True).get_by_role("button", name="Cancel", exact=True).click()

    page.get_by_role("button", name="Edit Legacy alerts", exact=True).click()
    # A priority-only record resolves on the server to the two legacy rules; the editor shows them.
    expect(alerts.get_by_label("When to alert", exact=True)).to_have_value("rules")
    expect(alerts.get_by_role("heading", name="Rule 1: Run failed", exact=True)).to_be_visible()
    expect(alerts.get_by_role("heading", name="Rule 2: Run completed", exact=True)).to_be_visible()
    expect(alerts.get_by_label("Alert rule 2 severity", exact=True)).to_have_value("medium")
    expect(dialog.get_by_role("button", name=re.compile("classic", re.IGNORECASE))).to_have_count(0)
    expect(dialog.get_by_role("link", name=re.compile("classic", re.IGNORECASE))).to_have_count(0)
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    assert not ui.classic_visits
    assert not ui.workflow_writes


def test_group_durable_run_approval_decides_through_the_group_route(workflow_ui):
    """The runtime approval panel works for group runs and keeps the explicit group on the decision."""
    ui, page = workflow_ui, workflow_ui.page
    ui.group_workflows[GROUP_ID]["group-workflow"]["durable_execution"] = True
    ui.set_runtime("group-workflow", "group-run-1", ui.runtime_projection(
        state="waiting_approval", version=3,
        gate={
            "id": "group-approval-gate", "kind": "approval", "unit_id": "task-a",
            "input_digest": "sha256:group", "reason": "Approval is required before the group task starts.",
            "choices": ["approve", "reject"],
        },
    ), scope_type="group")
    open_group_workflows(ui)
    row = page.get_by_role("listitem").filter(has_text="Group review workflow").first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    expect(page.get_by_text("Approval is required before the group task starts.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Approve task", exact=True).click()
    expect(page.get_by_text("queued", exact=True).first).to_be_visible()

    decisions = [request for request in ui.writes if request.path.endswith("/runtime/decision")]
    assert len(decisions) == 1
    assert decisions[0].path == "/api/group/workflows/group-workflow/runs/group-run-1/runtime/decision"
    assert decisions[0].query == {"group_id": [GROUP_ID]}
    assert decisions[0].body["choice"] == "approve"
    assert decisions[0].body["expected_version"] == 3
    runtime_reads = [request for request in ui.requests if "/runs/group-run-1/runtime" in request.path]
    assert runtime_reads and all(request.query == {"group_id": [GROUP_ID]} for request in runtime_reads)


@pytest.mark.parametrize("theme,width,height", [("light", 1440, 900), ("dark", 390, 844)], ids=["desktop-light", "mobile-dark"])
def test_file_sync_and_alert_sections_fit_desktop_and_mobile(workflow_ui, theme, width, height):
    """The new sections render inside the editor without horizontal overflow in both themes."""
    ui, page = workflow_ui, workflow_ui.page
    ui.group_workflows[GROUP_ID][MONITOR_ID] = monitored_workflow()
    ui.open("/groups", theme=theme, width=width, height=height)
    ui.select_group(GROUP_ID)
    page.get_by_role("button", name="Edit Monitor finance drops", exact=True).click()
    file_sync = page.get_by_role("region", name="File Sync")
    alerts = page.get_by_role("region", name="Alerts")
    file_sync.scroll_into_view_if_needed()
    expect(source_checkbox(page, "Archive share (Group)")).to_be_visible()
    expect(page.get_by_label("Continue the workflow", exact=True)).to_be_visible()
    alerts.scroll_into_view_if_needed()
    expect(page.get_by_role("list", name="Alert rules", exact=True).get_by_role("listitem")).to_have_count(2)
    clipped = page.evaluate("""() => [...document.querySelectorAll('[role="dialog"] *')]
        .filter((element) => element.scrollWidth > element.clientWidth + 1 && getComputedStyle(element).overflowX !== 'visible')
        .map((element) => element.tagName)""")
    assert clipped == [], clipped
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_personal_workflows_keep_their_file_sync_unchanged(workflow_ui):
    """Personal editors keep their triggers, File Sync and payloads, and never list sources."""
    ui, page = workflow_ui, workflow_ui.page
    ui.personal_workflows[WORKFLOW_ID]["trigger_type"] = "file_sync"
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Create workflow", exact=True).click()
    assert trigger_options(page) == ["Manual", "Interval"]
    expect(page.get_by_role("region", name="File Sync")).to_have_count(0)
    # Alerts are authored natively in both scopes since 0.261.144.
    expect(page.get_by_role("region", name="Alerts", exact=True).get_by_label("When to alert", exact=True)).to_have_value("off")
    page.get_by_role("dialog", name="Create workflow", exact=True).get_by_role("button", name="Cancel", exact=True).click()
    expect(page.get_by_text(
        "Native V2 authoring is available for manual and interval workflows, and for their alerts. File sync and "
        "publication settings from existing workflows are preserved unchanged.",
        exact=True,
    )).to_be_visible()

    page.get_by_role("button", name="Edit Quarterly review workflow", exact=True).click()
    expect(labelled(page, "Trigger")).to_have_value("file_sync")
    assert trigger_options(page) == ["Manual", "Interval", "Existing file sync"]
    expect(labelled(page, "Interval value")).to_be_disabled()
    expect(page.get_by_text("file sync settings", exact=False)).to_be_visible()
    labelled(page, "Description").first.fill("Personal edit keeps legacy File Sync.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    body = workflow_post(ui).body
    assert body["trigger_type"] == "file_sync"
    assert body["file_sync"] == {"source_id": "legacy-source", "delete_policy": "preserve"}
    assert not source_requests(ui)


def test_personal_analyze_tasks_may_rely_on_file_sync_changed_files(workflow_ui):
    """0.261.144: a personal workflow with File Sync on changed files saves an Analyze task without evidence.

    Both saves allow it (`allow_empty_file_sync_targets`); `test_workflow_file_sync_analyze_targets.py`
    pins the real `save_personal_workflow` accepting exactly these payloads. Personal File Sync is
    not authored in V2, so the loaded configuration is carried unchanged.
    """
    ui, page = workflow_ui, workflow_ui.page
    personal_action = {**SUMMARIZE_ACTION, "doc_scope": "personal", "active_group_ids": []}
    personal_file_sync = {
        "enabled": True, "wait_mode": "complete", "continue_mode": "always", "use_changed_documents": True,
        "sources": [{"scope_type": "personal", "scope_id": OWNER_ID, "source_id": "home-share",
                     "name": "Home share", "source_type": "onedrive"}],
    }
    ui.personal_workflows["personal-sync"] = workflow_record(
        "personal-sync", name="Personal changed files", file_sync=copy.deepcopy(personal_file_sync),
        tasks=[{
            "id": "analyze", "type": "instructions", "name": "Analyze changes", "order": 1,
            "instructions": "Summarize each changed file.", "runner": {"type": "inherit"},
            "document_action": copy.deepcopy(personal_action),
        }],
    )
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Edit Personal changed files", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(page.get_by_role("region", name="File Sync")).to_have_count(0)
    page.get_by_text("Runner, inputs, references and outputs", exact=True).first.click()
    expect(labelled(page, "Document action").first).to_have_value("analyze")
    expect(page.get_by_text(
        "No evidence is selected, so this task analyzes the files each File Sync run changed.", exact=True,
    )).to_be_visible()
    expect(page.get_by_text("Select at least one evidence document for this document action.", exact=True)).to_have_count(0)
    expect(page.get_by_role("status").filter(has_text="needs selected evidence for Analyze")).to_have_count(0)

    labelled(page, "Description").first.fill("Edited in V2.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(dialog).to_have_count(0)
    body = workflow_post(ui).body
    assert body["file_sync"] == personal_file_sync
    assert body["tasks"][0]["document_action"] == personal_action
    assert not source_requests(ui)

    # Without changed files as targets the same draft needs evidence, as the server requires.
    ui.personal_workflows["personal-sync"]["file_sync"]["use_changed_documents"] = False
    page.reload()
    page.get_by_role("button", name="Edit Personal changed files", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Analyze changes needs selected evidence for Analyze.")).to_be_visible()


def test_group_workflow_pages_trap_personal_reads(workflow_ui):
    """The general personal-route trap is active on group workflow pages and inert on personal ones."""
    ui, page = workflow_ui, workflow_ui.page
    fetch_status = "(path) => fetch(path).then((response) => response.status)"
    ui.open("/workspace/workflows")
    assert page.evaluate(fetch_status, "/api/documents") == 200
    assert not ui.unexpected_requests

    open_group_workflows(ui)
    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(source_checkbox(page, "Finance share (Group)")).to_be_visible()
    assert not ui.unexpected_requests, ui.unexpected_requests
    assert page.evaluate(fetch_status, "/api/user/settings") == 200
    assert page.evaluate(fetch_status, "/api/documents") == 500
    assert page.evaluate(fetch_status, "/api/user/workflows") == 500
    assert ui.unexpected_requests == [
        "GET /api/documents (personal documents from a group page)",
        "GET /api/user/workflows (personal user resource from a group page)",
    ]
    # The two reads above were deliberate; clearing them keeps the rest of assert_clean meaningful.
    ui.unexpected_requests.clear()
