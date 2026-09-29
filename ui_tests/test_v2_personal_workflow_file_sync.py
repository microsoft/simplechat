# test_v2_personal_workflow_file_sync.py
"""
UI tests for personal workflow File Sync authoring in native V2.
Version: 0.261.206
Implemented in: 0.261.206

These tests use the real V2 SPA bundle with the closed workflow fixture. The fixture answers the
personal source list (`/api/user/workflows/file-sync-sources`) with the real
`collect_personal_workflow_file_sync_sources` and `_serialize_workflow_file_sync_source`, and
validates personal saves with the real personal `_normalize_file_sync_config`, `_normalize_schedule`
and Monitor File Sync trigger rules. They cover:

* authoring a Monitor File Sync changes trigger on a personal workflow, checked on the POST body,
  with the list requested from the personal route and no source credential in it;
* the active group's sources offered to a personal workflow when the owner manages the group, and
  not offered to a member;
* File Sync off for the personal workspace: the owner's sources are not listed, a stored personal
  source stays selected without being called unavailable, and there is no Monitor trigger to add;
* a personal Monitor workflow with a schedule the editor can't show opens read-only (F1) and never
  asks for the source list;
* keyboard selection and focus, in light and dark themes, without horizontal overflow.
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
    FILE_SYNC_FIXTURE_SECRET,
    GROUP_ID,
    OWNER_ID,
    PERSONAL_FILE_SYNC_SOURCES_PATH,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_ui,  # noqa: F401
)
from test_v2_group_workflow_file_sync import (  # noqa: E402  (shared record and page helpers)
    PERSONAL_MONITOR_FILE_SYNC,
    before_run_toggle,
    labelled,
    source_checkbox,
    source_requests,
    trigger_options,
    workflow_post,
)


pytestmark = pytest.mark.ui
PERSONAL_SOURCE = {"scope_type": "personal", "scope_id": OWNER_ID, "source_id": "home-share"}
SELECT_A_SOURCE = "Select at least one File Sync source for this workflow."
PERSONAL_OFF = "File Sync is not enabled for your personal workspace, so your own sources cannot be listed."
UNSUPPORTED_SCHEDULE = "This workflow uses a schedule this editor does not support."


def create_dialog(page):
    return page.get_by_role("dialog", name="Create workflow", exact=True)


def edit_dialog(page):
    return page.get_by_role("dialog", name="Edit workflow", exact=True)


def open_personal_create(ui, **open_options):
    ui.open("/workspace/workflows", **open_options)
    ui.page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(create_dialog(ui.page)).to_be_visible()


def fill_required_basics(page, name):
    labelled(page, "Workflow name").fill(name)
    labelled(page, "Model").select_option(label="Workspace GPT · aoai")
    labelled(page, "Instructions").first.fill("Review every changed file.")


def personal_list_requests(ui):
    requests = source_requests(ui)
    assert all(request.path == PERSONAL_FILE_SYNC_SOURCES_PATH and not request.query for request in requests), requests
    return requests


def test_owner_authors_a_personal_monitor_trigger_and_posts_the_server_shape(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    open_personal_create(ui)
    home = source_checkbox(page, "Home share (Personal)")
    expect(home).to_be_visible()
    assert personal_list_requests(ui)
    # The list crosses the API boundary without the stored credential.
    listed = page.evaluate("(path) => fetch(path).then((response) => response.text())", PERSONAL_FILE_SYNC_SOURCES_PATH)
    assert FILE_SYNC_FIXTURE_SECRET not in listed and '"auth"' not in listed
    assert trigger_options(page) == ["Manual", "Schedule", "Monitor File Sync changes"]

    fill_required_basics(page, "Review new documents")
    labelled(page, "Trigger").select_option("file_sync")
    expect(before_run_toggle(page)).to_be_checked()
    expect(before_run_toggle(page)).to_be_disabled()
    expect(page.get_by_label("Wait for File Sync", exact=True)).to_have_value("complete")
    expect(page.get_by_label("Continue the workflow", exact=True)).to_have_value("changed")
    expect(page.get_by_text("Monitor workflows check the selected sources", exact=False)).to_be_visible()
    expect(page.get_by_role("status").filter(has_text=SELECT_A_SOURCE)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text=SELECT_A_SOURCE)).to_be_visible()
    assert not ui.workflow_writes

    labelled(page, "Interval unit").select_option("hours")
    labelled(page, "Interval value").fill("2")
    home.check()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(create_dialog(page)).to_have_count(0)

    write = workflow_post(ui)
    assert write.path == "/api/user/workflows" and not write.query
    assert write.body["trigger_type"] == "file_sync"
    assert write.body["schedule"] == {"unit": "hours", "value": 2}
    assert write.body["file_sync"] == {
        "enabled": True, "wait_mode": "complete", "continue_mode": "changed", "use_changed_documents": True,
        "sources": [PERSONAL_SOURCE],
    }
    # The real personal rules authorized the source the editor sent.
    assert ("personal", OWNER_ID, "home-share") in ui.file_sync_source_reads

    page.get_by_role("button", name="Edit Review new documents", exact=True).click()
    expect(labelled(page, "Trigger")).to_have_value("file_sync")
    expect(source_checkbox(page, "Home share (Personal)")).to_be_checked()
    expect(labelled(page, "Interval value")).to_have_value("2")
    expect(page.get_by_text("No longer available", exact=True)).to_have_count(0)


def test_the_active_group_sources_are_offered_only_to_a_manager(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.active_group_id = GROUP_ID
    open_personal_create(ui)
    expect(source_checkbox(page, "Home share (Personal)")).to_be_visible()
    finance = source_checkbox(page, "Finance share (Group)")
    expect(finance).to_be_visible()
    expect(source_checkbox(page, "Archive share (Group)")).to_be_visible()
    expect(create_dialog(page).get_by_text("Disabled", exact=True)).to_be_visible()
    # Only the active group is offered, never another group the owner belongs to.
    expect(source_checkbox(page, "Beta share (Group)")).to_have_count(0)

    fill_required_basics(page, "Sync the finance share first")
    before_run_toggle(page).check(force=True)
    finance.check()
    page.get_by_label("Continue the workflow", exact=True).select_option("always")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(create_dialog(page)).to_have_count(0)
    body = workflow_post(ui).body
    assert body["trigger_type"] == "manual"
    assert body["file_sync"] == {
        "enabled": True, "wait_mode": "complete", "continue_mode": "always", "use_changed_documents": True,
        "sources": [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"}],
    }
    assert ("group", GROUP_ID, "finance-share") in ui.file_sync_source_reads

    # A member of the active group gets only their own sources.
    ui.group_can_manage = False
    page.reload()
    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(source_checkbox(page, "Home share (Personal)")).to_be_visible()
    expect(source_checkbox(page, "Finance share (Group)")).to_have_count(0)
    personal_list_requests(ui)


def test_personal_file_sync_off_keeps_a_stored_source_without_calling_it_unavailable(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.personal_file_sync_enabled = False
    ui.personal_workflows[WORKFLOW_ID]["file_sync"] = copy.deepcopy(PERSONAL_MONITOR_FILE_SYNC)
    open_personal_create(ui)
    expect(page.get_by_role("status").filter(has_text=PERSONAL_OFF)).to_be_visible()
    expect(page.get_by_role("status").filter(has_text="No File Sync sources are available to you.")).to_be_visible()
    assert trigger_options(page) == ["Manual", "Schedule"]
    create_dialog(page).get_by_role("button", name="Cancel", exact=True).click()

    page.get_by_role("button", name="Edit Quarterly review workflow", exact=True).click()
    expect(page.get_by_role("status").filter(has_text=PERSONAL_OFF)).to_be_visible()
    # The list can't check a personal source while File Sync is off, so the selection is kept as is.
    expect(source_checkbox(page, "Home share (Personal)")).to_be_checked()
    expect(page.get_by_text("No longer available", exact=True)).to_have_count(0)
    labelled(page, "Description").first.fill("Edited while personal File Sync is off.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(edit_dialog(page)).to_have_count(0)
    body = workflow_post(ui).body
    assert body["file_sync"] == PERSONAL_MONITOR_FILE_SYNC
    assert body["description"] == "Edited while personal File Sync is off."


def test_a_personal_monitor_workflow_with_an_unsupported_schedule_opens_read_only(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    stored_schedule = {"unit": "fortnights", "value": 1}
    ui.personal_workflows[WORKFLOW_ID].update(
        trigger_type="file_sync",
        schedule=copy.deepcopy(stored_schedule),
        file_sync=copy.deepcopy(PERSONAL_MONITOR_FILE_SYNC),
    )
    ui.open("/workspace/workflows")
    page.get_by_role("button", name=re.compile(r"^(?:Edit|View) Quarterly review workflow$")).click()
    dialog = edit_dialog(page)
    expect(dialog.get_by_role("alert").filter(has_text=UNSUPPORTED_SCHEDULE)).to_be_visible()
    expect(dialog.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    home = source_checkbox(page, "Home share (Personal)")
    expect(home).to_be_checked()
    expect(home).to_be_disabled()
    assert not source_requests(ui)
    assert not ui.workflow_writes
    assert ui.personal_workflows[WORKFLOW_ID]["schedule"] == stored_schedule


@pytest.mark.parametrize("theme,width,height", [("light", 1440, 900), ("dark", 390, 844)], ids=["desktop-light", "mobile-dark"])
def test_personal_sources_are_chosen_by_keyboard_in_both_themes(workflow_ui, theme, width, height):
    ui, page = workflow_ui, workflow_ui.page
    ui.active_group_id = GROUP_ID
    open_personal_create(ui, theme=theme, width=width, height=height)
    fill_required_basics(page, "Keyboard monitor")
    labelled(page, "Trigger").select_option("file_sync")
    home = source_checkbox(page, "Home share (Personal)")
    finance = source_checkbox(page, "Finance share (Group)")
    home.focus()
    expect(home).to_be_focused()
    page.keyboard.press("Space")
    expect(home).to_be_checked()
    page.keyboard.press("Tab")
    expect(finance).to_be_focused()
    page.keyboard.press("Space")
    expect(finance).to_be_checked()
    expect(page.get_by_role("status").filter(has_text=SELECT_A_SOURCE)).to_have_count(0)
    page.get_by_role("region", name="File Sync").scroll_into_view_if_needed()
    clipped = page.evaluate("""() => [...document.querySelectorAll('[role="dialog"] *')]
        .filter((element) => element.scrollWidth > element.clientWidth + 1 && getComputedStyle(element).overflowX !== 'visible')
        .map((element) => element.tagName)""")
    assert clipped == [], clipped
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(create_dialog(page)).to_have_count(0)
    assert workflow_post(ui).body["file_sync"]["sources"] == [
        PERSONAL_SOURCE, {"scope_type": "group", "scope_id": GROUP_ID, "source_id": "finance-share"},
    ]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
