# test_v2_workflow_settings_errors.py
"""
UI tests for reviewed workflow settings errors, deleted File Sync sources and deleted workflows.
Version: 0.261.149
Implemented in: 0.261.149

These tests use the real V2 SPA bundle with the closed workflow fixture. The fixture validates both
save routes with the real File Sync normalizers, trigger rules and `_normalize_schedule`, returns
each reviewed error with its code, and refuses a save that names a deleted workflow with the
server's 409. They cover:

* a group File Sync source deleted after the editor opened: the reviewed 400 keeps the draft,
  the editor reloads the source list and marks the source, and removing it lets the save succeed;
* the same deletion in a personal workflow: the draft is kept and the server's message is shown.
  V2 does not author personal File Sync, so this is where the known limitation surfaces;
* a workflow deleted after the editor opened it: the 409 keeps the draft, says what to do, and
  neither recreates the workflow nor treats the editor as having lost access;
* personal schedules checked before saving with the server's message;
* group File Sync turned off: the editor applies the server's gate to a stored File Sync workflow
  and does not claim its sources are gone.
"""

import copy
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.workflow_editor import (  # noqa: E402
    GROUP_ID,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_record,
    workflow_ui,  # noqa: F401
)
from test_v2_group_workflow_file_sync import (  # noqa: E402  (shared record and page helpers)
    GROUP_FILE_SYNC_OFF,
    MONITOR_ID,
    PERSONAL_MONITOR_FILE_SYNC,
    before_run_toggle,
    labelled,
    monitored_workflow,
    open_group_workflows,
    source_checkbox,
    source_requests,
    workflow_post,
)


pytestmark = pytest.mark.ui
SOURCE_UNAVAILABLE = "A selected File Sync source is no longer available. Remove it and save again."
WORKFLOW_DELETED = (
    "This workflow was deleted after it was opened, so your changes were not saved. "
    "Your draft has been retained. Copy anything you need, then close this editor."
)
ACCESS_LOST = "Cached authoring details were removed"


def save(page):
    page.get_by_role("button", name="Save workflow", exact=True).click()


def edit_dialog(page):
    return page.get_by_role("dialog", name="Edit workflow", exact=True)


def test_a_group_source_deleted_after_opening_keeps_the_draft_and_marks_the_source(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.group_workflows[GROUP_ID][MONITOR_ID] = monitored_workflow()
    open_group_workflows(ui)
    page.get_by_role("button", name="Edit Monitor finance drops", exact=True).click()
    expect(source_checkbox(page, "Finance share (Group)")).to_be_checked()
    labelled(page, "Description").first.fill("Edited while the share was removed.")
    lists_before = len(source_requests(ui))
    # The share is deleted on the server after the editor loaded the group's sources.
    ui.group_file_sync_sources[GROUP_ID] = [
        source for source in ui.group_file_sync_sources[GROUP_ID] if source["id"] != "finance-share"
    ]

    save(page)

    expect(page.get_by_role("alert").filter(has_text=SOURCE_UNAVAILABLE)).to_be_visible()
    expect(edit_dialog(page)).to_be_visible()
    expect(labelled(page, "Description").first).to_have_value("Edited while the share was removed.")
    expect(page.get_by_text(ACCESS_LOST, exact=False)).to_have_count(0)
    assert ui.settings_refusals == [("file_sync_source_unavailable", SOURCE_UNAVAILABLE)]
    assert not ui.workflow_writes
    # The refusal's code alone reloads the list, which now marks the stored share.
    expect(page.get_by_text("No longer available", exact=True)).to_be_visible()
    assert len(source_requests(ui)) == lists_before + 1
    stale = source_checkbox(page, "Finance share")
    expect(stale).to_be_checked()

    stale.click()
    expect(page.get_by_role("status").filter(
        has_text="Select at least one group File Sync source for this workflow.",
    )).to_be_visible()
    source_checkbox(page, "Archive share (Group)").check()
    save(page)
    expect(edit_dialog(page)).to_have_count(0)
    body = workflow_post(ui).body
    assert body["file_sync"]["sources"] == [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": "archive-share"}]
    assert body["description"] == "Edited while the share was removed."


def test_a_personal_source_deleted_after_opening_keeps_the_draft(workflow_ui):
    """Known limitation: V2 cannot remove a personal source, so the reviewed 400 is where it surfaces."""
    ui, page = workflow_ui, workflow_ui.page
    ui.personal_workflows[WORKFLOW_ID]["file_sync"] = copy.deepcopy(PERSONAL_MONITOR_FILE_SYNC)
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Edit Quarterly review workflow", exact=True).click()
    labelled(page, "Description").first.fill("Edited after the personal share was removed.")
    ui.personal_file_sync_sources.clear()

    save(page)

    expect(page.get_by_role("alert").filter(has_text=SOURCE_UNAVAILABLE)).to_be_visible()
    expect(edit_dialog(page)).to_be_visible()
    expect(labelled(page, "Description").first).to_have_value("Edited after the personal share was removed.")
    expect(page.get_by_text(ACCESS_LOST, exact=False)).to_have_count(0)
    assert not ui.workflow_writes
    assert not source_requests(ui)


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_saving_a_workflow_deleted_after_opening_keeps_the_draft_and_explains_what_to_do(workflow_ui, scope):
    ui, page = workflow_ui, workflow_ui.page
    if scope == "group":
        workflows, name, workflow_id = ui.group_workflows[GROUP_ID], "Group review workflow", "group-workflow"
        open_group_workflows(ui)
    else:
        workflows, name, workflow_id = ui.personal_workflows, "Quarterly review workflow", WORKFLOW_ID
        ui.open("/workspace/workflows")
    page.get_by_role("button", name=f"Edit {name}", exact=True).click()
    labelled(page, "Description").first.fill("Edited after someone deleted the workflow.")
    del workflows[workflow_id]

    save(page)

    alert = page.get_by_role("alert").filter(has_text=WORKFLOW_DELETED)
    expect(alert).to_be_visible()
    expect(alert).not_to_contain_text("reload")
    expect(edit_dialog(page)).to_be_visible()
    expect(page.get_by_text(ACCESS_LOST, exact=False)).to_have_count(0)
    # Not treated as lost access: the draft stays readable and editable, so it can be copied.
    description = labelled(page, "Description").first
    expect(description).to_have_value("Edited after someone deleted the workflow.")
    expect(description).to_be_editable()
    assert workflow_id not in workflows
    assert not ui.workflow_writes


def test_personal_schedules_are_checked_before_saving_with_the_server_message(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Edit Quarterly review workflow", exact=True).click()
    labelled(page, "Trigger").select_option("interval")
    labelled(page, "Interval unit").select_option("minutes")
    labelled(page, "Interval value").fill("90")
    message = "Schedule value for minutes must be between 1 and 59."
    expect(page.get_by_role("status").filter(has_text=message)).to_be_visible()
    save(page)
    expect(page.get_by_role("alert").filter(has_text=message)).to_be_visible()
    assert not ui.workflow_writes

    labelled(page, "Interval value").fill("59")
    save(page)
    expect(edit_dialog(page)).to_have_count(0)
    body = workflow_post(ui).body
    assert body["trigger_type"] == "interval"
    assert body["schedule"] == {"unit": "minutes", "value": 59}


def test_group_file_sync_turned_off_applies_the_servers_gate_without_marking_sources_gone(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    record = monitored_workflow()
    record["trigger_type"] = "manual"
    record["file_sync"]["continue_mode"] = "always"
    # A plain task, so turning File Sync off leaves a valid draft; Analyze would need evidence then.
    record["tasks"][0]["document_action"] = {"type": "none"}
    ui.group_workflows[GROUP_ID][MONITOR_ID] = record
    ui.group_file_sync_enabled[GROUP_ID] = False
    open_group_workflows(ui)
    page.get_by_role("button", name="Edit Monitor finance drops", exact=True).click()
    expect(page.get_by_text(
        "Group File Sync is not enabled, so this group's sources cannot be listed. "
        "Your selection is kept, but it cannot be checked.", exact=True,
    )).to_be_visible()
    expect(source_checkbox(page, "Finance share")).to_be_checked()
    expect(page.get_by_text("No longer available", exact=True)).to_have_count(0)
    expect(page.get_by_role("status").filter(has_text=GROUP_FILE_SYNC_OFF)).to_be_visible()
    expect(page.get_by_role("status").filter(has_text=SOURCE_UNAVAILABLE)).to_have_count(0)
    save(page)
    expect(page.get_by_role("alert").filter(has_text=GROUP_FILE_SYNC_OFF)).to_be_visible()
    assert not ui.workflow_writes

    # Turning File Sync off for this workflow is the way forward, and the server accepts it.
    before_run_toggle(page).uncheck(force=True)
    save(page)
    expect(edit_dialog(page)).to_have_count(0)
    body = workflow_post(ui).body
    assert body["file_sync"]["enabled"] is False
    assert body["file_sync"]["sources"] == []
