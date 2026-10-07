# test_v2_workflows_workbench_and_editor_layout.py
"""
UI tests for the V2 Workflows workbench and editor in the Admin Settings design language.
Version: 0.261.266
Implemented in: 0.261.266

These tests drive the real V2 SPA bundle against the closed workflow API fixture. They check the
layout the redesign promises, which the behavioural workflow suites don't: one-line rows beside a
detail pane, keyboard movement through the list and the tabs, a run link that selects its workflow
and opens the run, editor cards that carry Admin's status chips with an On this page index that
moves focus, fields beside their labels that stack on a narrow screen, independent switches
paired on a wide card, settings nested under the control that leads them, the leave prompt, the
return to the saved workflow, and no horizontal overflow at 390px, 1440px and 1920px, in light and
dark themes and at 200% text.
"""

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
    DURABLE_WORKFLOW_ID,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_ui,  # noqa: F401
)
from ui_tests.fixtures.workflow_workbench import (  # noqa: E402
    discard_and_leave,
    edit_workflow,
    leave_prompt,
    select_workflow,
    workflow_detail,
    workflow_editor,
    workflow_editor_path,
    workflow_list,
    workflow_row,
)


pytestmark = pytest.mark.ui

QUARTERLY = "Quarterly review workflow"
AGENT = "Agent review workflow"
ROW_NAMES = (
    QUARTERLY,
    AGENT,
    "Legacy prompt workflow",
    "Active running workflow",
    "Durable approval workflow",
    "Future workflow",
)


def box(locator):
    rectangle = locator.bounding_box()
    assert rectangle, "Expected a rendered element."
    return rectangle


def card(page, name):
    return workflow_editor(page).get_by_role("region", name=name, exact=True)


def assert_editor_fits(page):
    scroll = page.locator("[data-workflow-editor-scroll]")
    overflow = scroll.evaluate("element => element.scrollWidth - element.clientWidth")
    assert overflow <= 1, f"The editor overflows its scroll area by {overflow}px"


def use_text_size(ui, size):
    """Reload with the user's text size, as the account preference sets it."""
    ui.preferences["fontSizePreference"] = size
    ui.page.reload(wait_until="networkidle")
    expect(ui.page.locator("html")).to_have_attribute("data-font-size", size)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_rows_read_as_one_line_beside_the_selected_workflow(workflow_ui, theme):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows", theme=theme, width=1920, height=1080)

    for name in ROW_NAMES:
        row = workflow_row(page, name)
        expect(row).to_be_visible()
        assert box(row)["height"] < 56, f"{name} should read as a single line"
    # A row names its trigger in a word; the detail says it in full.
    quarterly = workflow_row(page, QUARTERLY)
    expect(quarterly).to_contain_text("Manual")
    expect(quarterly).not_to_contain_text("runs only when started")
    # The status leads the row in words, not only as an icon.
    expect(workflow_row(page, "Active running workflow")).to_contain_text("Running · Manual")

    # The first workflow is selected, and its detail sits beside the list rather than below it.
    expect(quarterly).to_have_attribute("aria-pressed", "true")
    detail = workflow_detail(page, QUARTERLY)
    expect(detail.locator("header").get_by_text("Manual · runs only when started", exact=True)).to_be_visible()
    assert box(workflow_list(page))["x"] + box(workflow_list(page))["width"] <= box(detail)["x"] + 1
    expect(detail.get_by_role("tab", name="Overview", exact=True)).to_have_attribute("aria-selected", "true")
    overview = detail.get_by_role("tabpanel", name="Overview", exact=True)
    for label in ("Runner", "Workflow enabled", "Trigger and schedule", "File Sync", "Execution",
                  "Shared references", "Tasks", "Alerts"):
        expect(overview.get_by_text(label, exact=True)).to_be_visible()
    # Only a structured workflow offers Flow.
    expect(detail.get_by_role("tab", name="Flow", exact=True)).to_have_count(0)

    active = workflow_row(page, "Active running workflow")
    expect(active).to_have_accessible_description(re.compile(r"^Running · Manual"))
    ui.assert_no_overflow()


def test_a_finished_run_reads_from_the_last_run_status_the_server_records(workflow_ui):
    """The server sets a workflow back to idle when a run ends and records the outcome in
    last_run_status, so that is what the row, the detail, Last run and Needs attention read."""
    ui, page = workflow_ui, workflow_ui.page
    ui.personal_workflows["agent-workflow"].update(
        status="idle", last_run_status="failed", last_run_at="2026-09-16T12:00:00Z",
    )
    ui.personal_workflows[WORKFLOW_ID].update(status="idle", last_run_status="completed")
    ui.open("/workspace/workflows", width=1440, height=900)

    expect(workflow_row(page, AGENT)).to_contain_text("Failed · Manual")
    expect(workflow_row(page, QUARTERLY)).to_contain_text("Completed · Manual")
    expect(page.get_by_text("1 needs attention", exact=True)).to_be_visible()

    detail = select_workflow(page, AGENT)
    expect(detail.locator("header").get_by_text("Failed", exact=True)).to_be_visible()
    last_run = detail.get_by_role("tabpanel", name="Overview", exact=True).get_by_text(re.compile(r"^Failed · "))
    expect(last_run).to_be_visible()

    page.get_by_label("Status", exact=True).select_option("attention")
    expect(workflow_list(page).get_by_role("button")).to_have_count(1)
    expect(workflow_row(page, AGENT)).to_be_visible()
    page.get_by_label("Status", exact=True).select_option("completed")
    expect(workflow_row(page, QUARTERLY)).to_be_visible()
    expect(workflow_row(page, AGENT)).to_have_count(0)


def test_choosing_a_workflow_on_a_narrow_screen_brings_its_detail_into_view(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    page.emulate_media(reduced_motion="reduce")
    ui.open("/workspace/workflows", width=390, height=844)
    row = workflow_row(page, "Future workflow")
    row.scroll_into_view_if_needed()
    row.click()
    heading = workflow_detail(page, "Future workflow").get_by_role("heading", name="Future workflow", level=3)
    expect(heading).to_be_in_viewport()
    # Choosing moves the view, not focus: the list keeps the keyboard.
    expect(row).to_be_focused()


def test_the_list_and_the_tabs_follow_the_keyboard(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows", width=1440, height=900)
    rows = workflow_list(page).get_by_role("button")
    expect(rows).to_have_count(len(ROW_NAMES))
    # One tab stop for the whole list.
    expect(workflow_list(page).locator("button[tabindex='0']")).to_have_count(1)

    first = workflow_row(page, QUARTERLY)
    first.focus()
    page.keyboard.press("ArrowDown")
    expect(workflow_row(page, AGENT)).to_be_focused()
    # Moving focus doesn't change the selection; choosing does.
    expect(first).to_have_attribute("aria-pressed", "true")
    page.keyboard.press("End")
    expect(workflow_row(page, ROW_NAMES[-1])).to_be_focused()
    page.keyboard.press("Home")
    expect(first).to_be_focused()
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Enter")
    expect(workflow_row(page, AGENT)).to_have_attribute("aria-pressed", "true")
    expect(workflow_list(page).locator("button[tabindex='0']")).to_have_count(1)

    detail = workflow_detail(page, AGENT)
    overview = detail.get_by_role("tab", name="Overview", exact=True)
    runs = detail.get_by_role("tab", name="Runs", exact=True)
    overview.focus()
    page.keyboard.press("ArrowRight")
    expect(runs).to_be_focused()
    expect(runs).to_have_attribute("aria-selected", "true")
    expect(detail.get_by_role("tabpanel", name="Runs", exact=True)).to_contain_text("The most recent runs.")
    page.keyboard.press("Home")
    expect(overview).to_be_focused()
    expect(overview).to_have_attribute("aria-selected", "true")
    page.keyboard.press("End")
    expect(runs).to_have_attribute("aria-selected", "true")
    page.keyboard.press("ArrowRight")
    expect(overview).to_have_attribute("aria-selected", "true")


def test_a_run_link_selects_its_workflow_and_opens_the_run(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open(f"/workspace/workflows?workflow_id={DURABLE_WORKFLOW_ID}&run_id=durable-run-1")

    name = "Durable approval workflow"
    expect(workflow_row(page, name)).to_have_attribute("aria-pressed", "true")
    detail = workflow_detail(page, name)
    expect(detail.get_by_role("heading", name=name, level=3)).to_be_focused()
    expect(detail.get_by_role("tab", name="Runs", exact=True)).to_have_attribute("aria-selected", "true")
    runs = detail.get_by_role("tabpanel", name="Runs", exact=True)
    # The linked run is expanded: its gate is on screen without asking for the task results.
    expect(runs.get_by_text("Approval is required before Approval task starts.", exact=False).first).to_be_visible()

    # A workflow link without a run shows the workflow's Overview.
    ui.open(f"/workspace/workflows?workflow_id={WORKFLOW_ID}")
    expect(workflow_row(page, QUARTERLY)).to_have_attribute("aria-pressed", "true")
    expect(workflow_detail(page, QUARTERLY).get_by_role("tab", name="Overview", exact=True)).to_have_attribute(
        "aria-selected", "true"
    )
    expect(workflow_editor(page)).to_have_count(0)


def test_editor_cards_carry_admin_status_and_the_index_moves_focus(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    page.emulate_media(reduced_motion="reduce")
    ui.open(workflow_editor_path(WORKFLOW_ID), width=1920, height=1080)
    editor = workflow_editor(page)
    expect(editor).to_be_visible()
    expect(editor.get_by_role("heading", name=QUARTERLY, level=2)).to_be_focused()

    for name in ("Workflow basics", "Trigger and schedule", "File Sync", "Execution",
                 "Workflow shared references", "Workflow tasks", "Alerts"):
        expect(card(page, name)).to_be_visible()
    expect(card(page, "Limits")).to_have_count(0)
    basics = card(page, "Workflow basics")
    expect(basics.get_by_text("Configured", exact=True)).to_be_visible()
    expect(card(page, "File Sync").get_by_text("Off", exact=True).first).to_be_visible()
    expect(card(page, "Execution").get_by_text("Halt on failure · 1 retry", exact=True)).to_be_visible()

    index = editor.get_by_role("navigation", name="On this page", exact=True)
    expect(index).to_be_visible()
    expect(index).to_contain_text("7 sections")
    entries = index.get_by_role("link")
    expect(entries).to_have_count(7)
    expect(index.get_by_role("link", name=re.compile(r"^Basics\b"))).to_contain_text("Configured")

    # A section that isn't ready says so on its card and in the index, as Admin's do.
    page.get_by_label(re.compile(r"^Workflow name")).fill("")
    expect(basics.get_by_text("Needs configuration", exact=True)).to_be_visible()
    expect(index.get_by_role("link", name=re.compile(r"^Basics\b"))).to_contain_text("Needs configuration")
    expect(index).to_contain_text("1 needs attention")
    page.get_by_label(re.compile(r"^Workflow name")).fill(QUARTERLY)
    expect(basics.get_by_text("Configured", exact=True)).to_be_visible()

    index.get_by_role("link", name=re.compile(r"^Alerts\b")).click()
    alerts_title = card(page, "Alerts").get_by_role("heading", name="Alerts", exact=True)
    expect(alerts_title).to_be_focused()
    expect(alerts_title).to_be_in_viewport()
    expect(index.get_by_role("link", name=re.compile(r"^Alerts\b"))).to_have_attribute("aria-current", "location")


def test_fields_sit_beside_their_labels_and_stack_when_narrow(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open(workflow_editor_path(WORKFLOW_ID), width=1920, height=1080)
    basics = card(page, "Workflow basics")
    label = basics.locator("label", has_text="Workflow name").first
    field = page.get_by_label(re.compile(r"^Workflow name"))
    label_box, field_box = box(label), box(field)
    assert label_box["x"] + label_box["width"] <= field_box["x"], "A wide card puts the label beside its control"
    assert abs(label_box["y"] - field_box["y"]) < field_box["height"], "A label and its control share a row"

    # The runner's model belongs to Runner type, so it sits indented under it.
    runner = page.get_by_label("Runner type", exact=True)
    dependent = basics.locator("[data-setting-emphasis='dependent']").filter(has=page.get_by_label("Model", exact=True))
    expect(dependent).to_have_count(1)
    assert box(dependent)["x"] > box(basics.locator("label", has_text="Runner type").first)["x"]
    assert box(dependent)["y"] > box(runner)["y"]

    # Independent switches pair up on a wide card.
    durable = page.get_by_role("checkbox", name=re.compile(r"^Durable execution"))
    capabilities = page.get_by_role("checkbox", name=re.compile(r"^Chat capabilities enabled"))
    durable_row = card(page, "Execution").locator(".admin-switch-row").filter(has=durable)
    capabilities_row = card(page, "Execution").locator(".admin-switch-row").filter(has=capabilities)
    assert abs(box(durable_row)["y"] - box(capabilities_row)["y"]) < 4, "Two switches share a row on a wide card"
    assert box(durable_row)["x"] < box(capabilities_row)["x"]

    # Reopened at phone width, so the shell collapses its rails as it does on a phone.
    ui.open(workflow_editor_path(WORKFLOW_ID), width=390, height=844)
    basics = card(page, "Workflow basics")
    label = basics.locator("label", has_text="Workflow name").first
    field = page.get_by_label(re.compile(r"^Workflow name"))
    expect(field).to_be_visible()
    label_box, field_box = box(label), box(field)
    assert label_box["y"] + label_box["height"] <= field_box["y"] + 1, "A narrow card stacks the label above its control"
    durable = page.get_by_role("checkbox", name=re.compile(r"^Durable execution"))
    capabilities = page.get_by_role("checkbox", name=re.compile(r"^Chat capabilities enabled"))
    durable_row = card(page, "Execution").locator(".admin-switch-row").filter(has=durable)
    capabilities_row = card(page, "Execution").locator(".admin-switch-row").filter(has=capabilities)
    assert abs(box(durable_row)["x"] - box(capabilities_row)["x"]) < 4, "Switches stack on a narrow card"
    assert box(durable_row)["y"] < box(capabilities_row)["y"]
    # The page header has room to name the Changes panel in words at every width.
    changes = workflow_editor(page).get_by_role("button", name=re.compile(r"^Changes \("))
    expect(changes.get_by_text("Changes", exact=True)).to_be_visible()
    ui.assert_no_overflow()
    assert_editor_fits(page)


def test_leaving_with_unsaved_changes_asks_and_saving_returns_to_the_workflow(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")
    editor = edit_workflow(page, AGENT)
    description = page.get_by_label(re.compile(r"^Description")).first
    description.fill("An unsaved description.")

    editor.get_by_role("button", name="Back", exact=True).click()
    prompt = leave_prompt(page)
    expect(prompt).to_be_visible()
    prompt.get_by_role("button", name="Keep editing", exact=True).click()
    expect(prompt).to_have_count(0)
    expect(description).to_have_value("An unsaved description.")

    editor.get_by_role("button", name="Cancel", exact=True).click()
    discard_and_leave(page)
    expect(workflow_editor(page)).to_have_count(0)
    expect(workflow_row(page, AGENT)).to_have_attribute("aria-pressed", "true")
    assert not ui.workflow_writes

    editor = edit_workflow(page, AGENT)
    page.get_by_label(re.compile(r"^Description")).first.fill("A saved description.")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(workflow_editor(page)).to_have_count(0)
    expect(leave_prompt(page)).to_have_count(0)
    expect(page).to_have_url(re.compile(r"/v2/workspace/workflows\?workflow_id=agent-workflow$"))
    expect(page.get_by_role("status").filter(has_text="Workflow saved.")).to_be_visible()
    expect(workflow_row(page, AGENT)).to_have_attribute("aria-pressed", "true")
    expect(workflow_detail(page, AGENT).get_by_role("heading", name=AGENT, level=3)).to_be_focused()
    writes = [entry for entry in ui.workflow_writes if entry.method == "POST"]
    assert len(writes) == 1
    assert writes[0].body["description"] == "A saved description."


@pytest.mark.parametrize("theme,width,height,text_size", [
    ("light", 390, 844, "m"),
    ("dark", 1440, 900, "m"),
    ("light", 1920, 1080, "xl"),
])
def test_the_workbench_and_editor_never_overflow(workflow_ui, theme, width, height, text_size):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows", theme=theme, width=width, height=height)
    if text_size != "m":
        use_text_size(ui, text_size)
    expect(workflow_row(page, QUARTERLY)).to_be_visible()
    ui.assert_no_overflow()
    detail = workflow_detail(page, QUARTERLY)
    detail.get_by_role("tab", name="Runs", exact=True).click()
    expect(detail.get_by_role("tabpanel", name="Runs", exact=True)).to_be_visible()
    ui.assert_no_overflow()

    detail.get_by_role("button", name=f"Edit {QUARTERLY}", exact=True).click()
    editor = workflow_editor(page)
    expect(editor).to_be_visible()
    ui.assert_no_overflow()
    assert_editor_fits(page)
    for name in ("Trigger and schedule", "Workflow tasks", "Alerts"):
        card(page, name).scroll_into_view_if_needed()
        ui.assert_no_overflow()
        assert_editor_fits(page)
