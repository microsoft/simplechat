# test_v2_workflow_change_tracking.py
"""
Offline real-bundle browser regressions for change tracking in the V2 workflow editor.
Version: 0.261.203
Implemented in: 0.261.203

Covers the highlight on each unsaved change (its author badge, Previously value and Revert),
Removed · Restore rows on the List and Flow surfaces, and the side panel's Changes tab with
Jump, Revert and Restore to here. Also checks that Undo and Redo keep the highlights in step,
that saving your own edits stays one click, the Run as note, that read-only editors show
nothing (including one opened read-only for a stored schedule it can't show), group workflows,
and the light, dark, keyboard and narrow layouts. Fields whose
highlight frames several controls (the schedule, Run when, an output contract, final outputs)
keep focus and every keystroke as the highlight appears and goes.

Reuses the closed Flow authoring harness, the local production assets and the real compiler.
No live app, model, workflow admission, publication or Azure browser is contacted. Run with
PLAYWRIGHT_SERVICE_URL='' and PYTHONPATH including ui_tests/fixtures.
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

# The shared fixtures import pure application helpers after setting their paths.
from ui_tests import test_v2_workflow_flow_authoring as authoring
from ui_tests.fixtures.workflow_editor import OWNER_ID, WORKFLOW_ID
from ui_tests.fixtures.workflow_flow import GROUP_ID, FLOW_WORKFLOW_ID, MALICIOUS_LABEL
from ui_tests.test_v2_workflow_flow_authoring import authoring_ui, connect_options  # noqa: F401


pytestmark = pytest.mark.ui

LONG_INSTRUCTIONS = " ".join(
    f"Step {index}: collect every source record for the quarter, note its owner and date, and keep the wording."
    for index in range(1, 7)
)
PREVIOUS_CLIP = 280
RUN_AS_NOTE = "Saving requires re-approving Run as."
EVERY_30_MINUTES = {"unit": "minutes", "value": 30}
DAILY_LONDON = {
    "kind": "calendar", "frequency": "daily", "days_of_week": [], "day_of_month": None,
    "time_of_day": "09:00", "timezone": "Europe/London",
}
# A schedule kind this editor doesn't define, which opens the editor read-only from 0.261.202.
UNSUPPORTED_SCHEDULE = {"kind": "cron", "expression": "0 8 * * 1", "timezone": "America/New_York"}
UNSUPPORTED_SCHEDULE_NOTE = "This workflow's schedule can't be shown or changed in this editor."

# Resolves alpha against the actual ancestor surfaces, as the admin visual hierarchy test does.
CONTRAST = """
(element, property) => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 1;
    const context = canvas.getContext('2d', {willReadFrequently: true});
    const rgba = (color) => {
        context.clearRect(0, 0, 1, 1);
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
        const pixel = context.getImageData(0, 0, 1, 1).data;
        return [pixel[0], pixel[1], pixel[2], pixel[3] / 255];
    };
    const over = (top, bottom) => {
        const alpha = top[3] + bottom[3] * (1 - top[3]);
        return [0, 1, 2].map((index) =>
            (top[index] * top[3] + bottom[index] * bottom[3] * (1 - top[3])) / alpha
        ).concat(alpha);
    };
    let background = [0, 0, 0, 0];
    for (let parent = element; parent; parent = parent.parentElement) {
        const color = rgba(getComputedStyle(parent).backgroundColor);
        if (color[3]) {
            background = over(background, color);
        }
        if (background[3] === 1) break;
    }
    if (background[3] !== 1) throw new Error('Contrast requires an opaque ancestor');
    const foreground = over(rgba(getComputedStyle(element)[property]), background);
    const luminance = (color) => color.slice(0, 3).reduce((sum, value, index) => {
        const channel = value / 255;
        const linear = channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
        return sum + linear * [0.2126, 0.7152, 0.0722][index];
    }, 0);
    const light = Math.max(luminance(background), luminance(foreground));
    const dark = Math.min(luminance(background), luminance(foreground));
    return (light + 0.05) / (dark + 0.05);
}
"""

# A visible label that wraps inside its button has more than one line box.
SINGLE_LINE_BUTTONS = """
footer => [...footer.querySelectorAll('button')].filter((button) => button.getClientRects().length).every((button) => {
    const walker = document.createTreeWalker(button, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        if (!node.textContent.trim() || node.parentElement.closest('.sr-only')) continue;
        const range = document.createRange();
        range.selectNodeContents(node);
        if (range.getClientRects().length > 1) return false;
    }
    return true;
})
"""


def open_classic(ui, **options):
    ui.open(f"/workspace/workflows?workflow_id={WORKFLOW_ID}", **options)
    editor = ui.page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(editor).to_be_visible()
    expect(editor.get_by_label("Workflow name", exact=True)).to_have_value(ui.personal_workflows[WORKFLOW_ID]["name"])
    return editor


def open_scheduled(ui, schedule):
    """The saved classic workflow on the Schedule trigger, so its schedule fields are enabled."""
    ui.personal_workflows[WORKFLOW_ID].update(trigger_type="interval", schedule=copy.deepcopy(schedule))
    return open_classic(ui)


def changed(scope, key):
    return scope.locator(f"[data-workflow-change-key='{key}']")


def author(frame):
    return frame.locator("[data-workflow-change-author]").first


def previously(frame):
    toggle = frame.get_by_role("button", name="Previously", exact=True)
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    panel = frame.locator(f"[id='{toggle.get_attribute('aria-controls')}']")
    expect(panel).to_be_visible()
    return panel


def task_item(scope, task_id):
    return scope.locator(f"[data-workflow-change-item='task:{task_id}']")


def task_items(scope):
    return scope.locator("[data-workflow-change-item^='task:']")


def changes_toggle(editor):
    return editor.get_by_role("button", name=re.compile(r"^Changes"))


def side_panel(editor):
    return editor.locator("aside[aria-label='Workflow editor side panel']")


def open_panel(editor):
    toggle = changes_toggle(editor)
    toggle.focus()
    toggle.press("Enter")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    panel = side_panel(editor)
    expect(panel.get_by_role("tab", name="Changes", exact=True)).to_be_focused()
    return panel


def change_row(panel, key):
    return panel.locator(f"li[data-workflow-change-row='{key}']")


def history_step(page, panel, label):
    return panel.locator("li[data-workflow-history-step]").filter(has=page.get_by_text(label, exact=True))


def unsaved_heading(panel, count):
    return panel.get_by_role("heading", name=f"Unsaved changes ({count})", exact=True)


def announced(editor, text):
    return editor.locator("p[role='status']").filter(has_text=text)


def confirm_if(page, title, button):
    """Structured drafts confirm a change that affects references; the others apply at once."""
    dialog = page.get_by_role("dialog", name=title, exact=True)
    if not dialog.count():
        return False
    dialog.get_by_role("button", name=button, exact=True).click()
    expect(dialog).to_have_count(0)
    return True


def replay(ui, editor, direction):
    editor.get_by_role("button", name=f"{direction} workflow edit", exact=True).click()
    confirm_if(ui.page, f"{direction} workflow edit?", f"{direction} change")


def assert_readable(*elements):
    for element in elements:
        ratio = element.evaluate(CONTRAST, "color")
        assert ratio >= 4.5, f"Contrast {ratio:.2f} is below AA for {element}."


def assert_dialog_fits(ui, editor):
    ui.assert_no_overflow()
    modal = editor.locator(".glass-modal")
    footer = modal.locator(":scope > div").last
    for part in (modal, footer):
        assert part.evaluate("element => element.scrollWidth <= element.clientWidth + 1"), "The editor overflows."
    assert footer.evaluate(SINGLE_LINE_BUTTONS), "A footer button label wraps."


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_classic_edits_show_author_previous_value_revert_and_item_rows(authoring_ui, theme):
    ui = authoring_ui
    ui.personal_workflows[WORKFLOW_ID]["tasks"][0]["instructions"] = LONG_INSTRUCTIONS
    editor = open_classic(ui, theme=theme)
    expect(editor.locator("[data-workflow-change-key]")).to_have_count(0)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (0 unsaved)")
    basics = editor.locator("section[aria-label='Workflow basics']")

    name = editor.get_by_label("Workflow name", exact=True)
    name.fill("Quarterly review workflow, revised")
    name_frame = changed(editor, "name")
    expect(name_frame).to_have_accessible_name("Edited")
    expect(author(name_frame)).to_have_text("Edited")
    expect(author(name_frame)).to_have_attribute("data-workflow-change-author", "user")
    expect(name).to_be_focused()
    expect(previously(name_frame)).to_have_text("Quarterly review workflow")

    editor.get_by_label("Trigger", exact=True).select_option("interval")
    schedule_frame = changed(editor, "schedule")
    expect(author(schedule_frame)).to_have_text("Edited")
    expect(previously(schedule_frame)).to_have_text("Manual")

    task_a = task_item(editor, "task-a")
    task_a.get_by_label("Instructions", exact=True).fill("Collect only the signed evidence.")
    instructions_frame = changed(task_a, "task:task-a:instructions")
    expect(author(instructions_frame)).to_have_text("Edited")
    expect(task_a.get_by_text("This item has unsaved changes.", exact=True)).to_have_count(1)
    previous = previously(instructions_frame)
    expect(previous.locator("p")).to_have_text(f"{LONG_INSTRUCTIONS[:PREVIOUS_CLIP].rstrip()}…")
    previous.get_by_role("button", name="Show more", exact=True).click()
    expect(previous.locator("p")).to_have_text(LONG_INSTRUCTIONS)
    expect(previous.get_by_role("button", name="Show less", exact=True)).to_have_attribute("aria-expanded", "true")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (3 unsaved)")

    assert_readable(
        author(name_frame), name_frame.get_by_role("button", name="Previously", exact=True),
        name_frame.get_by_role("button", name="Revert", exact=True), previous.locator("p"),
    )
    # The AI assist colors, measured on the same surface, since nothing in 3a applies an assist yet.
    basics.evaluate("""section => {
        const frame = document.createElement('div');
        frame.dataset.contrastSample = 'ai';
        frame.className = 'rounded-lg border p-2 border-change-ai/50 bg-change-ai-soft';
        const badge = document.createElement('span');
        badge.className = 'rounded-full px-2 py-0.5 text-xs font-semibold bg-change-ai-soft text-change-ai';
        badge.textContent = 'AI assist';
        frame.append(badge);
        section.append(frame);
    }""")
    assert_readable(basics.locator("[data-contrast-sample='ai'] span"))
    basics.evaluate("section => section.querySelector('[data-contrast-sample]').remove()")

    name_frame.get_by_role("button", name="Revert", exact=True).click()
    expect(name).to_have_value("Quarterly review workflow")
    expect(changed(editor, "name")).to_have_count(0)
    expect(name).to_be_focused()

    editor.get_by_role("button", name="Move Summarize evidence up", exact=True).click()
    order = changed(editor, "tasks:order")
    expect(order).to_contain_text("Task order changed")
    expect(author(order)).to_have_text("Edited")
    expect(task_items(editor).first).to_have_attribute("data-workflow-change-item", "task:task-b")
    expect(editor.locator("[data-workflow-change-key]")).to_have_count(3)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (3 unsaved)")
    order.get_by_role("button", name="Revert", exact=True).click()
    expect(changed(editor, "tasks:order")).to_have_count(0)
    expect(task_items(editor).first).to_have_attribute("data-workflow-change-item", "task:task-a")

    editor.get_by_role("button", name="Add task", exact=True).click()
    expect(task_items(editor)).to_have_count(3)
    added = task_items(editor).last
    added_key = added.get_attribute("data-workflow-change-item")
    assert added_key not in {"task:task-a", "task:task-b"}
    header = changed(added, added_key)
    expect(header).to_contain_text("Added · by you")
    added_name = changed(added, f"{added_key}:name")
    expect(author(added_name)).to_have_text("Edited")
    expect(added_name.get_by_role("button", name="Revert", exact=True)).to_have_count(0)
    expect(added_name.get_by_role("button", name="Previously", exact=True)).to_have_count(0)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (3 unsaved)")
    header.get_by_role("button", name="Revert", exact=True).click()
    expect(task_items(editor)).to_have_count(2)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (2 unsaved)")

    editor.get_by_role("button", name="Remove Collect evidence", exact=True).click()
    removed = changed(editor, "task:task-a")
    expect(removed).to_contain_text("Removed task · Collect evidence")
    expect(removed).to_have_class(re.compile(r"\bborder-dashed\b"))
    expect(changed(editor, "tasks:order")).to_have_count(0)
    assert removed.evaluate("""row => Boolean(row.compareDocumentPosition(
        document.querySelector("[data-workflow-change-item='task:task-b']")) & Node.DOCUMENT_POSITION_FOLLOWING)""")
    assert_dialog_fits(ui, editor)
    removed.get_by_role("button", name="Restore", exact=True).click()
    expect(changed(editor, "task:task-a")).to_have_count(0)
    first = task_items(editor).first
    expect(first).to_have_attribute("data-workflow-change-item", "task:task-a")
    expect(first.get_by_label("Task name", exact=True)).to_be_focused()
    expect(first.get_by_label("Instructions", exact=True)).to_have_value(LONG_INSTRUCTIONS)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")
    assert not ui.workflow_writes


def test_structured_highlights_follow_undo_and_redo(authoring_ui):
    ui = authoring_ui
    stored = next(task for task in ui.personal_workflows[FLOW_WORKFLOW_ID]["tasks"] if task["id"] == "evaluate")["name"]
    editor = authoring.open_editor(ui)
    evaluate = authoring.list_block(editor, "evaluate")
    name = evaluate.get_by_label("Task name", exact=True)
    expect(name).to_have_value(stored)
    name.fill("Evaluate the request")
    name.press("Tab")
    expect(author(changed(evaluate, "task:evaluate:name"))).to_have_text("Edited")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")
    editor.get_by_role("button", name="Move Optional note up", exact=True).click()
    confirm_if(ui.page, "Move this flow block?", "Move block")
    order = changed(editor, "region:root:order")
    expect(order).to_contain_text("Block order changed")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (2 unsaved)")

    replay(ui, editor, "Undo")
    expect(changed(editor, "region:root:order")).to_have_count(0)
    expect(changed(evaluate, "task:evaluate:name")).to_have_count(1)
    replay(ui, editor, "Undo")
    expect(changed(evaluate, "task:evaluate:name")).to_have_count(0)
    expect(name).to_have_value(stored)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (0 unsaved)")
    replay(ui, editor, "Redo")
    expect(changed(evaluate, "task:evaluate:name")).to_have_count(1)
    expect(changed(editor, "region:root:order")).to_have_count(0)
    replay(ui, editor, "Redo")
    expect(changed(editor, "region:root:order")).to_have_count(1)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (2 unsaved)")
    assert not ui.workflow_writes


def test_structured_alert_edits_apply_and_undo(authoring_ui):
    """Before 0.261.203 a structured draft rejected alert edits as a change to saved identity."""
    ui = authoring_ui
    editor = authoring.open_editor(ui)
    region = editor.get_by_role("region", name="Alerts", exact=True)
    mode = region.get_by_label("When to alert", exact=True)
    expect(mode).to_have_value("off")
    mode.select_option("rules")
    expect(mode).to_have_value("rules")
    expect(region.get_by_role("button", name="Add alert rule", exact=True)).to_be_visible()
    expect(editor.get_by_text("cannot change saved identity", exact=False)).to_have_count(0)
    expect(author(changed(editor, "alerts"))).to_have_text("Edited")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")
    replay(ui, editor, "Undo")
    expect(mode).to_have_value("off")
    expect(changed(editor, "alerts")).to_have_count(0)
    replay(ui, editor, "Redo")
    expect(mode).to_have_value("rules")
    assert not ui.workflow_writes


def test_flow_removed_block_can_be_restored_from_either_surface(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    editor = authoring.open_editor(ui)
    view = authoring.switch_surface(editor, "Flow")
    fields = authoring.select_node(view, "finish")
    task_name = fields.get_by_label("Task name", exact=True)
    task_name.fill("Finish the review")
    task_name.press("Tab")
    frame = changed(fields, "task:finish:name")
    expect(author(frame)).to_have_text("Edited")
    expect(previously(frame)).to_have_text("Finish")

    authoring.select_node(view, "note")
    view.get_by_role("button", name="Remove selected block", exact=True).click()
    confirmation = page.get_by_role("dialog", name="Remove this flow block?", exact=True)
    confirmation.get_by_role("button", name="Remove block", exact=True).click()
    expect(authoring.node_button(view, "note")).to_have_count(0)
    expect(view.get_by_text("Removed blocks", exact=True)).to_be_visible()
    row = changed(view, "task:note")
    expect(row).to_contain_text("Removed task · Optional note")
    expect(row).to_have_class(re.compile(r"\bborder-dashed\b"))

    authoring.switch_surface(editor, "List")
    list_row = changed(editor, "task:note")
    expect(list_row).to_contain_text("Removed task · Optional note")
    assert list_row.evaluate("""row => {
        const route = document.querySelector("section[data-workflow-authoring-id='bypass-note']");
        const finish = document.querySelector("section[data-workflow-authoring-id='finish']");
        return Boolean(route.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING)
            && Boolean(row.compareDocumentPosition(finish) & Node.DOCUMENT_POSITION_FOLLOWING);
    }""")

    view = authoring.switch_surface(editor, "Flow")
    changed(view, "task:note").get_by_role("button", name="Restore", exact=True).click()
    confirmed = confirm_if(page, "Restore this item?", "Restore")
    expect(authoring.node_button(view, "note")).to_have_attribute("aria-pressed", "true")
    expect(changed(view, "task:note")).to_have_count(0)
    if not confirmed:
        expect(authoring.node_button(view, "note")).to_be_focused()
    assert not ui.workflow_writes


def test_changes_tab_lists_every_change_with_jump_revert_and_restore(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    ui.personal_workflows[WORKFLOW_ID]["tasks"][1]["name"] = MALICIOUS_LABEL
    editor = open_classic(ui)
    name = editor.get_by_label("Workflow name", exact=True)
    name.fill("Quarterly review, revised")
    description = editor.locator("section[aria-label='Workflow basics']").get_by_label("Description", exact=True)
    description.fill("Runs the revised review.")
    task_b = task_item(editor, "task-b")
    instructions = task_b.get_by_label("Instructions", exact=True)
    instructions.fill("Summarize the signed findings.")

    panel = open_panel(editor)
    expect(panel.locator("li[data-workflow-change-row]")).to_have_count(3)
    expect(unsaved_heading(panel, 3)).to_be_visible()
    expect(change_row(panel, "name").locator("p")).to_have_text(
        "Before: Quarterly review workflow After: Quarterly review, revised")
    expect(change_row(panel, "description").locator("p")).to_have_text(
        "Before: Runs the recurring review. After: Runs the revised review.")
    instructions_row = change_row(panel, "task:task-b:instructions")
    expect(instructions_row).to_contain_text(f"{MALICIOUS_LABEL} · Instructions")
    expect(instructions_row.locator("p")).to_have_text("Before: Summarize findings. After: Summarize the signed findings.")
    expect(author(instructions_row)).to_have_text("Edited")
    assert not page.evaluate("Boolean(window.flowLabelExecuted)")
    expect(editor.locator("img[src='x']")).to_have_count(0)

    page.keyboard.press("Tab")
    expect(change_row(panel, "name").get_by_role("button", name="Jump", exact=True)).to_be_focused()
    instructions_row.get_by_role("button", name="Jump", exact=True).click()
    expect(instructions).to_be_focused()

    change_row(panel, "name").get_by_role("button", name="Revert", exact=True).click()
    expect(unsaved_heading(panel, 2)).to_be_visible()
    expect(name).to_have_value("Quarterly review workflow")
    expect(announced(editor, "Revert Workflow name. The workflow has not been saved.")).to_have_count(1)
    expect(change_row(panel, "description").get_by_role("button", name="Jump", exact=True)).to_be_focused()

    steps = panel.locator("li[data-workflow-history-step]")
    expect(steps).to_have_count(5)
    name_step = history_step(page, panel, "Edit Workflow name")
    restore = name_step.get_by_role("button", name="Restore to here", exact=True)
    restore.click()
    expect(unsaved_heading(panel, 1)).to_be_visible()
    expect(name).to_have_value("Quarterly review, revised")
    expect(description).to_have_value("Runs the recurring review.")
    expect(instructions).to_have_value("Summarize findings.")
    expect(steps).to_have_count(6)
    expect(steps.first).to_contain_text("Restore to after “Edit Workflow name”")
    expect(steps.first).to_contain_text("Current")
    expect(announced(editor, "Your later steps stay in history.")).to_have_count(1)
    expect(restore).to_be_focused()

    opened = panel.locator("li[data-workflow-history-step='opened']")
    expect(opened).to_contain_text("Opened version")
    opened.get_by_role("button", name="Restore to here", exact=True).click()
    expect(panel.get_by_text("No unsaved changes.", exact=True)).to_be_visible()
    expect(unsaved_heading(panel, 0)).to_be_visible()
    expect(name).to_have_value("Quarterly review workflow")
    expect(steps).to_have_count(7)
    expect(steps.first).to_contain_text("Restore to the opened version")
    expect(opened.get_by_role("button", name="Restore to here", exact=True)).to_be_focused()

    page.keyboard.press("Escape")
    expect(side_panel(editor)).to_have_count(0)
    expect(changes_toggle(editor)).to_be_focused()
    expect(editor).to_be_visible()
    assert not ui.workflow_writes


def test_jump_on_flow_selects_the_changed_block_and_restore_to_opened(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    editor = authoring.open_editor(ui)
    view = authoring.switch_surface(editor, "Flow")
    fields = authoring.select_node(view, "finish")
    fields.get_by_label("Task name", exact=True).fill("Finish the review")
    fields.get_by_label("Task name", exact=True).press("Tab")
    authoring.select_node(view, "evaluate")

    panel = open_panel(editor)
    row = change_row(panel, "task:finish:name")
    expect(row).to_contain_text("Finish the review · Task name")
    row.get_by_role("button", name="Jump", exact=True).click()
    expect(authoring.node_button(view, "finish")).to_have_attribute("aria-pressed", "true")
    expect(authoring.configuration(view).get_by_label("Task name", exact=True)).to_be_focused()

    panel.locator("li[data-workflow-history-step='opened']").get_by_role(
        "button", name="Restore to here", exact=True,
    ).click()
    confirm_if(page, "Restore this version?", "Restore version")
    expect(panel.get_by_text("No unsaved changes.", exact=True)).to_be_visible()
    expect(authoring.node_button(view, "finish")).to_have_accessible_name("Select Finish (Task)")
    assert not ui.workflow_writes


@pytest.mark.parametrize("kind", ["classic", "structured"])
def test_saving_only_your_own_edits_takes_one_click(authoring_ui, kind):
    ui = authoring_ui
    editor = open_classic(ui) if kind == "classic" else authoring.open_editor(ui)
    editor.get_by_label("Workflow name", exact=True).fill("Saved in one click")
    expect(author(changed(editor, "name"))).to_have_text("Edited")
    payload = authoring.save(ui, editor)
    assert payload["name"] == "Saved in one click"
    expect(ui.page.locator("aside[aria-label='Workflow editor side panel']")).to_have_count(0)


def test_saving_as_your_own_run_as_account_needs_no_reapproval(authoring_ui):
    ui = authoring_ui
    ui.personal_workflows[WORKFLOW_ID]["m365_run_as_user_id"] = OWNER_ID
    editor = open_classic(ui)
    expect(editor.get_by_label("Microsoft 365 Run as", exact=True)).to_have_value(OWNER_ID)
    expect(editor.get_by_label("Microsoft 365 Run as", exact=True)).to_have_accessible_description(
        re.compile(r"A revision they saved themselves needs no separate approval\."))
    editor.locator("section[aria-label='Workflow basics']").get_by_label("Description", exact=True).fill(
        "Only the description changed.")
    panel = open_panel(editor)
    expect(change_row(panel, "description")).to_have_count(1)
    expect(panel.get_by_text(RUN_AS_NOTE, exact=True)).to_have_count(0)

    # A change Run as covers, saved by the Run as account itself, is that person's own revision.
    task_item(editor, "task-a").get_by_label("Instructions", exact=True).fill("Collect only signed evidence.")
    expect(change_row(panel, "task:task-a:instructions")).to_have_count(1)
    expect(panel.get_by_text(RUN_AS_NOTE, exact=True)).to_have_count(0)
    payload = authoring.save(ui, editor)
    assert payload["m365_run_as_user_id"] == OWNER_ID
    assert payload["tasks"][0]["instructions"] == "Collect only signed evidence."


def test_run_as_note_names_the_reapproval_when_someone_else_must_approve(authoring_ui):
    ui = authoring_ui
    ui.group_workflows[GROUP_ID][FLOW_WORKFLOW_ID]["m365_run_as_user_id"] = OWNER_ID
    editor = authoring.open_editor(ui, group_id=GROUP_ID)
    run_as = editor.get_by_label("Microsoft 365 Run as", exact=True)
    expect(run_as).to_have_value(OWNER_ID)
    panel = open_panel(editor)
    expect(panel.get_by_text(RUN_AS_NOTE, exact=True)).to_have_count(0)

    # Handing Run as to another member means they approve this revision before it runs as them.
    run_as.select_option("group-reviewer")
    note = panel.get_by_text(RUN_AS_NOTE, exact=True)
    expect(note).to_be_visible()
    assert_readable(note)
    payload = authoring.save(ui, editor)
    assert payload["m365_run_as_user_id"] == "group-reviewer"
    assert ui.workflow_writes[-1].path == "/api/group/workflows"


@pytest.mark.parametrize("restriction", ["reader", "unsupported", "schedule"])
def test_read_only_editors_show_no_change_tracking(authoring_ui, restriction):
    ui, page = authoring_ui, authoring_ui.page
    if restriction == "reader":
        ui.group_can_manage = False
        ui.open("/groups")
        ui.select_group(GROUP_ID)
        page.get_by_role("button", name="View Alpha read-only Flow", exact=True).click()
    elif restriction == "unsupported":
        ui.personal_workflows[FLOW_WORKFLOW_ID]["flow"]["nodes"][0]["future_executor"] = {"unchanged": True}
        ui.open(f"/workspace/workflows?workflow_id={FLOW_WORKFLOW_ID}")
    else:
        ui.personal_workflows[WORKFLOW_ID].update(
            trigger_type="interval", schedule=copy.deepcopy(UNSUPPORTED_SCHEDULE))
        ui.open(f"/workspace/workflows?workflow_id={WORKFLOW_ID}")
    editor = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(editor).to_contain_text("This workflow is read-only.")
    if restriction == "schedule":
        expect(editor.get_by_role("status").filter(has_text=UNSUPPORTED_SCHEDULE_NOTE)).to_be_visible()
    expect(editor.get_by_role("button", name="Close", exact=True).last).to_be_visible()
    expect(changes_toggle(editor)).to_have_count(0)
    expect(editor.locator("[data-workflow-change-key]")).to_have_count(0)
    expect(editor.locator("aside")).to_have_count(0)
    expect(editor.get_by_role("button", name="Revert", exact=True)).to_have_count(0)
    expect(editor.get_by_role("button", name="Previously", exact=True)).to_have_count(0)
    assert not ui.workflow_writes


def test_group_workflow_changes_are_tracked_and_saved_to_the_group(authoring_ui):
    ui = authoring_ui
    editor = authoring.open_editor(ui, group_id=GROUP_ID)
    editor.get_by_label("Workflow name", exact=True).fill("Alpha Flow, revised")
    expect(author(changed(editor, "name"))).to_have_text("Edited")
    panel = open_panel(editor)
    expect(change_row(panel, "name").locator("p")).to_have_text(
        "Before: Alpha read-only Flow After: Alpha Flow, revised")
    payload = authoring.save(ui, editor)
    assert payload["name"] == "Alpha Flow, revised"
    assert ui.workflow_writes[-1].path == "/api/group/workflows"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_narrow_editor_shows_the_changes_panel_in_place_of_the_fields(authoring_ui, theme):
    ui = authoring_ui
    editor = open_classic(ui, theme=theme, width=390, height=844)
    name = editor.get_by_label("Workflow name", exact=True)
    name.fill("Narrow revision")
    expect(author(changed(editor, "name"))).to_have_text("Edited")
    assert_dialog_fits(ui, editor)

    panel = open_panel(editor)
    expect(name).to_be_hidden()
    assert_dialog_fits(ui, editor)
    row = change_row(panel, "name")
    expect(row.locator("p")).to_have_text("Before: Quarterly review workflow After: Narrow revision")
    assert_readable(author(row), row.locator("p"), row.get_by_role("button", name="Jump", exact=True))
    row.get_by_role("button", name="Jump", exact=True).click()
    expect(side_panel(editor)).to_have_count(0)
    expect(changes_toggle(editor)).to_have_attribute("aria-expanded", "false")
    expect(name).to_be_focused()
    assert_dialog_fits(ui, editor)
    assert not ui.workflow_writes


def test_new_workflow_points_out_nothing_until_it_is_saved(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Create workflow", exact=True).click()
    editor = page.get_by_role("dialog", name="Create workflow", exact=True)
    editor.get_by_label("Workflow name", exact=True).fill("Brand new workflow")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (0 unsaved)")
    expect(editor.locator("[data-workflow-change-key]")).to_have_count(0)
    panel = open_panel(editor)
    expect(panel).to_contain_text("This workflow hasn't been saved yet")
    expect(unsaved_heading(panel, 0)).to_be_visible()
    expect(panel.get_by_text("No unsaved changes.", exact=True)).to_have_count(0)
    expect(panel.locator("li[data-workflow-history-step='opened']")).to_contain_text("New workflow")
    assert not ui.workflow_writes


# Keys go through page.keyboard, which types into whatever has focus, as a person's keyboard does.
# A field that remounts when its highlight appears or goes loses focus, and the keys after it land
# nowhere.


@pytest.mark.parametrize("kind", ["interval", "calendar"])
def test_typing_through_a_schedule_highlight_keeps_focus_and_every_character(authoring_ui, kind):
    ui, page = authoring_ui, authoring_ui.page
    if kind == "interval":
        editor = open_scheduled(ui, EVERY_30_MINUTES)
        field, opened, first, rest = editor.get_by_label("Interval value", exact=True), "30", "4", "52"
    else:
        editor = open_scheduled(ui, DAILY_LONDON)
        field, opened, first, rest = editor.get_by_label("Time zone", exact=True), "Europe/London", "A", "sia/Tokyo"
    expect(field).to_have_value(opened)
    expect(changed(editor, "schedule")).to_have_count(0)

    field.focus()
    page.keyboard.press("Control+A")
    page.keyboard.type(first)
    frame = changed(editor, "schedule")
    expect(author(frame)).to_have_text("Edited")
    expect(field).to_be_focused()
    page.keyboard.type(rest)
    expect(field).to_have_value(first + rest)
    expect(field).to_be_focused()
    expect(frame).to_have_count(1)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")
    assert not ui.workflow_writes


def test_arrow_keys_on_repeats_keep_focus_as_the_highlight_appears_and_goes(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    editor = open_scheduled(ui, EVERY_30_MINUTES)
    repeats = editor.get_by_label("Repeats", exact=True)
    expect(repeats).to_have_value("interval")

    repeats.focus()
    page.keyboard.press("ArrowDown")
    expect(repeats).to_have_value("daily")
    expect(author(changed(editor, "schedule"))).to_have_text("Edited")
    expect(editor.get_by_label("Time zone", exact=True)).to_be_visible()
    expect(repeats).to_be_focused()

    page.keyboard.press("ArrowUp")
    expect(repeats).to_have_value("interval")
    expect(changed(editor, "schedule")).to_have_count(0)
    expect(editor.get_by_label("Interval value", exact=True)).to_have_value("30")
    expect(repeats).to_be_focused()
    assert not ui.workflow_writes


def test_run_when_toggled_with_space_keeps_focus_and_shows_its_condition(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    editor = authoring.open_editor(ui)
    finish = authoring.list_block(editor, "finish")
    toggle = finish.get_by_role("checkbox", name=re.compile("^Run when"))
    condition = finish.get_by_label("Run when for Finish left input", exact=True)
    expect(toggle).not_to_be_checked()

    toggle.focus()
    page.keyboard.press("Space")
    expect(toggle).to_be_checked()
    expect(author(changed(finish, "task:finish:run_when"))).to_have_text("Edited")
    expect(condition).to_be_visible()
    expect(toggle).to_be_focused()

    page.keyboard.press("Space")
    expect(toggle).not_to_be_checked()
    expect(changed(finish, "task:finish:run_when")).to_have_count(0)
    expect(condition).to_have_count(0)
    expect(toggle).to_be_focused()
    assert not ui.workflow_writes


def test_typing_a_value_back_clears_its_highlight_and_keeps_focus(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    editor = open_scheduled(ui, DAILY_LONDON)
    zone = editor.get_by_label("Time zone", exact=True)
    zone.focus()
    page.keyboard.press("End")
    page.keyboard.type("x")
    expect(zone).to_have_value("Europe/Londonx")
    expect(author(changed(editor, "schedule"))).to_have_text("Edited")
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (1 unsaved)")

    # Focus is placed again, so this checks only the highlight going away.
    zone.focus()
    page.keyboard.press("End")
    page.keyboard.press("Backspace")
    expect(zone).to_have_value("Europe/London")
    expect(changed(editor, "schedule")).to_have_count(0)
    expect(changes_toggle(editor)).to_have_accessible_name("Changes (0 unsaved)")
    expect(zone).to_be_focused()
    page.keyboard.type("x")
    expect(zone).to_have_value("Europe/Londonx")
    assert not ui.workflow_writes


@pytest.mark.parametrize("field", ["output_contract", "final_outputs"])
def test_other_highlights_around_several_controls_keep_focus(authoring_ui, field):
    ui, page = authoring_ui, authoring_ui.page
    if field == "output_contract":
        editor = open_classic(ui)
        item = task_item(editor, "task-b")
        authoring.open_details(item)
        control, key = item.get_by_label("Output contract for Summarize evidence", exact=True), "task:task-b:output_contract"
        expect(control).to_have_value("")
        control.focus()
        page.keyboard.press("ArrowDown")
        expect(control).to_have_value("any")
    else:
        editor = authoring.open_editor(ui)
        control, key = editor.get_by_label("Final outputs input 1 name", exact=True), "region:root:outputs"
        expect(control).to_have_value("report")
        control.focus()
        page.keyboard.press("End")
        page.keyboard.type("_")
    expect(author(changed(editor, key))).to_have_text("Edited")
    expect(control).to_be_focused()

    if field == "output_contract":
        page.keyboard.press("ArrowUp")
        expect(control).to_have_value("")
        expect(changed(editor, key)).to_have_count(0)
    else:
        page.keyboard.type("final")
        expect(control).to_have_value("report_final")
    expect(control).to_be_focused()
    assert not ui.workflow_writes
