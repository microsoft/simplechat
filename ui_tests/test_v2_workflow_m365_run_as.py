# test_v2_workflow_m365_run_as.py
"""
Closed-browser tests for native V2 Microsoft 365 Run as authoring.
Version: 0.261.149
Implemented in: 0.261.122

Use the actual built SPA and existing scoped workflow fixtures. Cover explicit
selection and clearing, loading and lookup failures, unavailable saved accounts,
safe labels/errors, dirty/revision guards, and preserved loop/Repeat definitions.
Since 0.261.149, a group member's read-only editor never requests the manager-only account
list; the fixture refuses such a request and records it as unexpected.
No real Microsoft 365 account, workflow run, or application server is contacted.
"""

import copy
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

# Shared fixtures configure isolated production imports after local path setup.
from ui_tests.fixtures.workflow_editor import (
    GROUP_ID,
    OWNER_ID,
    UNSUPPORTED_WORKFLOW_ID,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_ui,  # noqa: F401
)
from ui_tests.fixtures.workflow_loops import LOOP_WORKFLOW_ID
from ui_tests.fixtures.workflow_repeat_until import (
    REPEAT_WORKFLOW_ID,
    workflow_repeat_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui
RUN_AS_PATH = "/api/workflows/m365-run-as-users"


def account_select(page):
    return page.get_by_label("Microsoft 365 Run as", exact=True)


def open_workflows(ui, *, group=False):
    ui.open("/groups" if group else "/workspace/workflows")
    if group:
        ui.select_group(GROUP_ID)


def edit_personal(ui):
    ui.page.get_by_role("button", name="Edit Quarterly review workflow", exact=True).click()
    expect(ui.page.get_by_role("dialog", name="Edit workflow", exact=True)).to_be_visible()


def save_workflow(ui, *, creating=False):
    ui.page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(ui.page.get_by_role(
        "dialog", name="Create workflow" if creating else "Edit workflow", exact=True
    )).to_have_count(0)
    assert ui.workflow_writes, "Expected a successful workflow save."
    return ui.workflow_writes[-1]


@pytest.mark.parametrize("group", [False, True], ids=["personal", "group"])
def test_account_loading_does_not_infer_consent_or_make_a_new_draft_dirty(workflow_ui, group):
    ui, page = workflow_ui, workflow_ui.page
    open_workflows(ui, group=group)
    page.get_by_role("button", name="Create workflow", exact=True).click()
    select = account_select(page)
    expect(select).to_be_enabled()
    expect(select).to_have_value("")
    expect(page.get_by_text("Selecting an account does not grant", exact=False)).to_be_visible()
    requests = [request for request in ui.requests if request.path == RUN_AS_PATH]
    assert requests
    expected = {"scope": ["group"], "group_id": [GROUP_ID]} if group else {"scope": ["personal"]}
    assert all(request.query == expected for request in requests)
    page.get_by_role("dialog", name="Create workflow", exact=True).get_by_role(
        "button", name="Cancel", exact=True
    ).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert not ui.workflow_writes


def test_personal_selection_and_explicit_clear_round_trip_without_losing_settings(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    original = copy.deepcopy(ui.personal_workflows[WORKFLOW_ID])
    open_workflows(ui)
    edit_personal(ui)
    select = account_select(page)
    expect(select).to_be_enabled()
    expect(select).to_have_value("")
    select.select_option(OWNER_ID)
    body = save_workflow(ui).body
    assert body["m365_run_as_user_id"] == OWNER_ID
    assert body["definition_revision"] == original["definition_revision"]
    for key in ("file_sync", "alert_settings", "publication_options", "metadata"):
        assert body[key] == original[key]

    edit_personal(ui)
    expect(select).to_be_enabled()
    expect(select).to_have_value(OWNER_ID)
    select.select_option("")
    assert save_workflow(ui).body["m365_run_as_user_id"] == ""
    edit_personal(ui)
    expect(select).to_be_enabled()
    expect(select).to_have_value("")


def test_group_selection_uses_its_scope_and_participates_in_the_dirty_guard(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    open_workflows(ui, group=True)
    page.get_by_role("button", name="Create workflow", exact=True).click()
    select = account_select(page)
    expect(select).to_be_enabled()
    select.select_option("group-reviewer")
    expect(page.get_by_label("Group workspace", exact=True)).to_be_disabled()
    expect(page.get_by_role("status").filter(has_text="group changes")).to_be_visible()
    page.get_by_label("Workflow name", exact=True).fill("Group Run as review")
    page.get_by_label("Model", exact=True).select_option(label="Workspace GPT · aoai")
    page.get_by_label("Instructions", exact=True).first.fill("Review the approved group records.")
    write = save_workflow(ui, creating=True)
    assert write.path == "/api/group/workflows"
    assert write.query == {"group_id": [GROUP_ID]}
    assert write.body["group_id"] == GROUP_ID
    assert write.body["m365_run_as_user_id"] == "group-reviewer"
    requests = [request for request in ui.requests if request.path == RUN_AS_PATH]
    assert requests and all(
        request.query == {"scope": ["group"], "group_id": [GROUP_ID]} for request in requests
    )
    page.get_by_role("button", name="Edit Group Run as review", exact=True).click()
    expect(select).to_be_enabled()
    expect(select).to_have_value("group-reviewer")
    select.select_option("")
    assert save_workflow(ui).body["m365_run_as_user_id"] == ""


def test_saved_selection_survives_loading_without_dirtying_the_editor(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.personal_workflows[WORKFLOW_ID]["m365_run_as_user_id"] = OWNER_ID
    ui.defer_next("GET", RUN_AS_PATH)
    open_workflows(ui)
    with page.expect_request(lambda request: urlsplit(request.url).path == RUN_AS_PATH):
        edit_personal(ui)
    select = account_select(page)
    expect(select).to_be_disabled()
    expect(select).to_have_attribute("aria-busy", "true")
    expect(select).to_have_value(OWNER_ID)
    expect(select.locator("option:checked")).to_have_text("Selected account (loading account list)")
    assert len(ui.pending_responses) == 1
    ui.release_responses()
    expect(select).to_be_enabled()
    expect(select).to_have_value(OWNER_ID)
    expect(select.locator("option:checked")).to_have_text("Workspace editor")
    page.get_by_role("dialog", name="Edit workflow", exact=True).get_by_role(
        "button", name="Cancel", exact=True
    ).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert not ui.workflow_writes


def test_account_absent_from_the_list_is_retained_on_unrelated_edits(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    saved_account = "previously-selected-account"
    ui.personal_workflows[WORKFLOW_ID]["m365_run_as_user_id"] = saved_account
    open_workflows(ui)
    edit_personal(ui)
    select = account_select(page)
    expect(select).to_be_enabled()
    expect(select).to_have_value(saved_account)
    expect(select.locator("option:checked")).to_have_text("Previously selected account (review required)")
    expect(page.get_by_role("status").filter(has_text="It has been retained")).to_be_visible()
    page.get_by_label("Description", exact=True).first.fill("An unrelated workflow description edit.")
    assert save_workflow(ui).body["m365_run_as_user_id"] == saved_account


@pytest.mark.parametrize("status", [403, 503, 200], ids=["forbidden", "unavailable", "malformed"])
def test_lookup_errors_preserve_the_choice_and_do_not_echo_server_details(workflow_ui, status):
    ui, page = workflow_ui, workflow_ui.page
    ui.personal_workflows[WORKFLOW_ID]["m365_run_as_user_id"] = OWNER_ID
    unsafe_message = "<img data-run-as-error src=x> internal-settings-diagnostic"
    ui.reject_next("GET", RUN_AS_PATH, status=status, error=unsafe_message, users=None)
    open_workflows(ui)
    edit_personal(ui)
    expect(page.get_by_role("alert").filter(
        has_text="Could not load eligible Microsoft 365 accounts."
    )).to_be_visible()
    select = account_select(page)
    expect(select).to_be_enabled()
    expect(select).to_have_value(OWNER_ID)
    expect(select.locator("option:checked")).to_have_text("Selected account (unable to verify)")
    expect(page.get_by_text("internal-settings-diagnostic", exact=False)).to_have_count(0)
    expect(page.locator("img[data-run-as-error]")).to_have_count(0)
    expect(page.get_by_role("button", name="Retry Microsoft 365 account list", exact=True)).to_be_enabled()
    page.get_by_role("dialog", name="Edit workflow", exact=True).get_by_role(
        "button", name="Cancel", exact=True
    ).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert not ui.workflow_writes


def test_retry_and_explicit_clear_do_not_reset_other_draft_fields(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.personal_workflows[WORKFLOW_ID]["m365_run_as_user_id"] = OWNER_ID
    ui.reject_next("GET", RUN_AS_PATH)
    open_workflows(ui)
    edit_personal(ui)
    retry = page.get_by_role("button", name="Retry Microsoft 365 account list", exact=True)
    expect(retry).to_be_visible()
    page.get_by_label("Workflow name", exact=True).fill("Retained Run as draft")
    account_select(page).select_option("")
    retry.click()
    expect(account_select(page)).to_be_enabled()
    expect(account_select(page)).to_have_value("")
    expect(page.get_by_label("Workflow name", exact=True)).to_have_value("Retained Run as draft")
    body = save_workflow(ui).body
    assert body["name"] == "Retained Run as draft"
    assert body["m365_run_as_user_id"] == ""


def test_selection_only_edits_survive_stale_save_and_require_explicit_discard(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    original_revision = ui.personal_workflows[WORKFLOW_ID]["definition_revision"]
    open_workflows(ui)
    edit_personal(ui)
    expect(account_select(page)).to_be_enabled()
    account_select(page).select_option(OWNER_ID)
    ui.mutate_revision(WORKFLOW_ID)
    with page.expect_response(
        lambda response: response.status == 409 and urlsplit(response.url).path == "/api/user/workflows"
    ):
        page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="draft has been retained")).to_be_visible()
    expect(account_select(page)).to_have_value(OWNER_ID)
    request = next(
        request for request in reversed(ui.requests)
        if request.method == "POST" and request.path == "/api/user/workflows"
    )
    assert request.body["definition_revision"] == original_revision
    assert request.body["m365_run_as_user_id"] == OWNER_ID
    page.get_by_role("dialog", name="Edit workflow", exact=True).get_by_role(
        "button", name="Cancel", exact=True
    ).click()
    expect(page.get_by_role("dialog", name="Discard unsaved workflow changes?", exact=True)).to_be_visible()
    page.get_by_role("button", name="Keep editing", exact=True).click()
    expect(account_select(page)).to_have_value(OWNER_ID)
    assert not ui.workflow_writes


def test_directory_labels_are_inert_and_read_only_definitions_cannot_change_accounts(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    label = '<img data-run-as-label src=x onerror="window.runAsInjected=true"> Reviewer'
    ui.m365_run_as_users["personal"] = [{"id": OWNER_ID, "display_name": label}]
    ui.personal_workflows[UNSUPPORTED_WORKFLOW_ID]["m365_run_as_user_id"] = OWNER_ID
    open_workflows(ui)
    page.get_by_role("button", name="Edit Future workflow", exact=True).click()
    select = account_select(page)
    expect(select.locator("option:checked")).to_have_text(label)
    expect(select).to_have_value(OWNER_ID)
    expect(select).to_be_disabled()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    expect(page.locator("img[data-run-as-label]")).to_have_count(0)
    assert page.evaluate("window.runAsInjected") is None
    assert not ui.workflow_writes


@pytest.mark.parametrize("workflow_id", [LOOP_WORKFLOW_ID, REPEAT_WORKFLOW_ID], ids=["for-each", "repeat-until"])
def test_account_edit_preserves_structured_flow_bindings_limits_and_revision(workflow_repeat_ui, workflow_id):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    original = copy.deepcopy(ui.personal_workflows[workflow_id])
    ui.open(f"/workspace/workflows?workflow_id={workflow_id}")
    expect(account_select(page)).to_be_enabled()
    account_select(page).select_option(OWNER_ID)
    body = save_workflow(ui).body
    assert body["m365_run_as_user_id"] == OWNER_ID
    assert body["definition_version"] == 3
    assert body["durable_execution"] is True
    assert body["definition_revision"] == original["definition_revision"]
    assert body["flow"] == original["flow"]
    assert body["limits"] == original["limits"]
    tasks = {task["id"]: task for task in body["tasks"]}
    assert set(tasks) == {task["id"] for task in original["tasks"]}
    for task in original["tasks"]:
        for key in ("instructions", "inputs", "reference_ids", "output_contract", "document_action"):
            if key in task:
                assert tasks[task["id"]][key] == task[key]


@pytest.mark.parametrize("stored", ["group-reviewer", ""], ids=["selected", "none"])
def test_a_members_read_only_editor_never_requests_accounts_and_shows_the_stored_state(workflow_ui, stored):
    """The account list is manager-only, so a member sees only whether an account is stored."""
    ui, page = workflow_ui, workflow_ui.page
    ui.group_can_manage = False
    ui.group_workflows[GROUP_ID]["group-workflow"]["m365_run_as_user_id"] = stored
    open_workflows(ui, group=True)
    page.get_by_role("button", name="View Group review workflow", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(dialog.get_by_text("You have read-only access to workflows in this scope.", exact=True)).to_be_visible()
    select = account_select(page)
    expect(select).to_be_disabled()
    expect(select).to_have_value(stored)
    expect(select.locator("option")).to_have_text(["Account selected" if stored else "No Microsoft 365 account selected"])
    expect(dialog.get_by_text(
        "Only workflow managers can see which account is selected or change it.", exact=True,
    )).to_be_visible()
    expect(dialog.get_by_text("Could not load eligible Microsoft 365 accounts", exact=False)).to_have_count(0)
    assert not [request for request in ui.requests if request.path == RUN_AS_PATH]
    if stored:
        assert stored not in dialog.inner_text()


def test_the_fixture_refuses_and_records_a_members_account_request(workflow_ui):
    """Anti-vacuity: a member's request would fail the suites, as the real route refuses it."""
    ui, page = workflow_ui, workflow_ui.page
    ui.group_can_manage = False
    open_workflows(ui, group=True)
    status = page.evaluate(
        "(path) => fetch(path).then((response) => response.status)",
        f"{RUN_AS_PATH}?scope=group&group_id={GROUP_ID}",
    )
    assert status == 403
    assert ui.unexpected_requests == [f"GET {RUN_AS_PATH} (a group member cannot list run-as accounts)"]
    ui.unexpected_requests.clear()
