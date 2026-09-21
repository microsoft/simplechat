# test_v2_workflow_authoring_history.py
"""
Offline real-bundle cross-surface workflow Undo/Redo regressions.
Version: 0.261.123
Implemented in: 0.261.123

Reuses the closed M5B authoring harness, local production assets, and actual
compiler. No live app, model, workflow admission, publication, or Azure browser.
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The shared fixture imports pure application helpers after setting their paths.
from ui_tests import test_v2_workflow_flow_authoring as authoring
from ui_tests.test_v2_workflow_flow_authoring import authoring_ui, connect_options  # noqa: F401


pytestmark = pytest.mark.ui


def undo_button(editor):
    return editor.get_by_role("button", name="Undo workflow edit", exact=True)


def redo_button(editor):
    return editor.get_by_role("button", name="Redo workflow edit", exact=True)


def replay(ui, editor, direction):
    (undo_button(editor) if direction == "Undo" else redo_button(editor)).click()
    confirmation = ui.page.get_by_role("dialog", name=f"{direction} workflow edit?", exact=True)
    if confirmation.count():
        confirmation.get_by_role("button", name=f"{direction} change", exact=True).click()
    expect(confirmation).to_have_count(0)


def open_seed(ui):
    original = authoring.install_seed(ui)
    return original, authoring.open_editor(ui, authoring.AUTHORING_ID)


def seed_fields(editor):
    fields = authoring.list_block(editor, "seed")
    authoring.open_details(fields)
    return fields


def install_two_tasks(ui):
    record = authoring.seed_record()
    second = copy.deepcopy(record["tasks"][0])
    second.update(id="second-catalogue", name="Other task", order=2)
    record["tasks"].append(second)
    record["flow"]["nodes"].append({"id": "second-node", "kind": "task", "task_id": second["id"]})
    record["definition_revision"] = authoring.workflow_definition_revision(record)
    authoring.compile_workflow_flow(record)
    ui.personal_workflows[authoring.AUTHORING_ID] = record
    return copy.deepcopy(record)


@pytest.mark.parametrize("surface", ["List", "Flow"])
def test_common_fields_group_typing_and_replay_across_surfaces(authoring_ui, surface):
    ui = authoring_ui
    original, editor = open_seed(ui)
    if surface == "Flow":
        authoring.switch_surface(editor, "Flow")
    name = editor.get_by_label("Workflow name", exact=True)
    name.click()
    name.press("End")
    name.press_sequentially(" revised")
    name.press("Tab")
    description = editor.get_by_label("Description", exact=True)
    description.fill("A separate committed field visit.")
    description.press("Tab")
    authoring.switch_surface(editor, "List" if surface == "Flow" else "Flow")
    replay(ui, editor, "Undo")
    expect(description).to_have_value(original["description"])
    expect(name).to_have_value(f"{original['name']} revised")
    replay(ui, editor, "Undo")
    expect(name).to_have_value(original["name"])
    expect(undo_button(editor)).to_be_disabled()
    replay(ui, editor, "Redo")
    expect(name).to_have_value(f"{original['name']} revised")
    payload = authoring.save(ui, editor)
    assert payload["name"] == f"{original['name']} revised"
    assert payload["definition_revision"] == original["definition_revision"]
    assert not {"history", "fields", "repeatRows"} & payload.keys()


def test_undo_to_opening_baseline_is_clean_and_reopening_starts_empty(authoring_ui):
    ui = authoring_ui
    original, editor = open_seed(ui)
    editor.get_by_label("Workflow name", exact=True).fill("Unsaved name")
    replay(ui, editor, "Undo")
    expect(editor.get_by_label("Workflow name", exact=True)).to_have_value(original["name"])
    editor.get_by_role("button", name="Cancel", exact=True).click()
    expect(ui.page.get_by_role("dialog")).to_have_count(0)
    ui.page.get_by_role("button", name=f"Edit {original['name']}", exact=True).click()
    editor = ui.page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(undo_button(editor)).to_be_disabled()
    expect(redo_button(editor)).to_be_disabled()
    assert not ui.workflow_writes


def test_invalid_raw_schema_replays_across_views_without_saving_last_valid_value(authoring_ui):
    ui = authoring_ui
    _, editor = open_seed(ui)
    fields = seed_fields(editor)
    authoring.open_details(fields, "Optional JSON schema")
    schema = fields.get_by_label("Optional JSON schema", exact=True)
    baseline = schema.input_value()
    schema.fill("{")
    view = authoring.switch_surface(editor, "Flow")
    fields = authoring.select_node(view, "seed")
    authoring.open_details(fields)
    authoring.open_details(fields, "Optional JSON schema")
    expect(fields.get_by_label("Optional JSON schema", exact=True)).to_have_value("{")
    replay(ui, editor, "Undo")
    expect(fields.get_by_label("Optional JSON schema", exact=True)).to_have_value(baseline)
    expect(undo_button(editor)).to_be_disabled()
    replay(ui, editor, "Redo")
    expect(fields.get_by_label("Optional JSON schema", exact=True)).to_have_value("{")
    expect(view.get_by_role("status").first).to_contain_text("Unvalidated draft")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(editor.get_by_role("alert").filter(has_text="JSON schema must be valid JSON.").first).to_be_visible()
    assert not [entry for entry in ui.writes if entry.path in authoring.SAVE_PATHS]


def test_schema_builder_and_buffer_cleanup_are_one_undo_step(authoring_ui):
    ui = authoring_ui
    _, editor = open_seed(ui)
    fields = seed_fields(editor)
    authoring.open_details(fields, "Optional JSON schema")
    fields.get_by_label("Optional JSON schema", exact=True).fill("{")
    fields.get_by_label("Decision field type", exact=True).select_option("enum")
    fields.get_by_label("Decision field name", exact=True).fill("pending_choice")
    fields.get_by_label("Decision enum values", exact=True).fill(" yes \n no \n")
    fields.get_by_role("button", name="Add decision field", exact=True).click()
    expect(fields.get_by_label("Decision field name", exact=True)).to_have_value("")
    expect(undo_button(editor)).to_have_attribute("title", "Undo: Add decision field")
    replay(ui, editor, "Undo")
    expect(fields.get_by_label("Decision field name", exact=True)).to_have_value("pending_choice")
    expect(fields.get_by_label("Decision enum values", exact=True)).to_have_value(" yes \n no \n")
    expect(fields.get_by_label("Optional JSON schema", exact=True)).to_have_value("{")
    replay(ui, editor, "Redo")
    expect(fields.get_by_label("Decision field name", exact=True)).to_have_value("")
    payload = authoring.save(ui, editor)
    assert payload["tasks"][0]["output_contract"]["schema"]["properties"]["pending_choice"] == {
        "type": "string", "enum": ["yes", "no"],
    }


def test_removal_restores_exact_owner_buffers_and_distinct_task_node_ids(authoring_ui):
    ui = authoring_ui
    original = install_two_tasks(ui)
    editor = authoring.open_editor(ui, authoring.AUTHORING_ID)
    fields = seed_fields(editor)
    authoring.open_details(fields, "Optional JSON schema")
    fields.get_by_label("Optional JSON schema", exact=True).fill("{")
    fields.get_by_label("Decision field name", exact=True).fill("unfinished")
    fields.get_by_role("button", name="Remove Seed decision block", exact=True).click()
    confirmation = ui.page.get_by_role("dialog", name="Remove this flow block?", exact=True)
    confirmation.get_by_role("button", name="Remove block", exact=True).click()
    expect(authoring.list_block(editor, "seed")).to_have_count(0)
    replay(ui, editor, "Undo")
    fields = seed_fields(editor)
    authoring.open_details(fields, "Optional JSON schema")
    expect(fields.get_by_label("Optional JSON schema", exact=True)).to_have_value("{")
    expect(fields.get_by_label("Decision field name", exact=True)).to_have_value("unfinished")
    expect(authoring.list_block(editor, "second-node")).to_be_visible()
    assert ui.personal_workflows[authoring.AUTHORING_ID] == original
    assert not ui.workflow_writes


def test_structural_replay_confirms_removal_and_restores_the_same_allocation(authoring_ui):
    ui = authoring_ui
    _, editor = open_seed(ui)
    view = authoring.switch_surface(editor, "Flow")
    before = set(view.locator("button[data-workflow-node-id]").evaluate_all(
        "elements => elements.map(element => element.dataset.workflowNodeId)"
    ))
    added_id, _ = authoring.add_block(view, "if")
    after = set(view.locator("button[data-workflow-node-id]").evaluate_all(
        "elements => elements.map(element => element.dataset.workflowNodeId)"
    ))
    assert len(after - before) == 4
    undo_button(editor).click()
    confirmation = ui.page.get_by_role("dialog", name="Undo workflow edit?", exact=True)
    expect(confirmation).to_be_visible()
    ui.page.keyboard.press("Escape")
    expect(confirmation).to_have_count(0)
    expect(editor).to_be_visible()
    expect(authoring.node_button(view, added_id)).to_be_visible()
    expect(redo_button(editor)).to_be_disabled()
    replay(ui, editor, "Undo")
    expect(authoring.node_button(view, added_id)).to_have_count(0)
    replay(ui, editor, "Redo")
    assert set(view.locator("button[data-workflow-node-id]").evaluate_all(
        "elements => elements.map(element => element.dataset.workflowNodeId)"
    )) == after
    assert not ui.workflow_writes


def test_repeat_row_removal_restores_unfinished_fields_and_row_identity(authoring_ui):
    ui = authoring_ui
    record = authoring.seed_record()
    repeat = {
        "id": "repeat", "kind": "repeat_until", "max_iterations": 2, "state": [],
        "body": {"id": "repeat-body", "nodes": [], "outputs": []},
        "until": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}}, "exports": [],
    }
    for index in range(2):
        name = f"state_{index}"
        repeat["state"].append({
            "name": name, "initial": {"kind": "node_output", "node_id": "seed", "output": "json", "scope": "current"},
            "next": f"next_{index}", "output_contract": copy.deepcopy(record["tasks"][0]["output_contract"]),
        })
        repeat["body"]["outputs"].append({
            "name": f"next_{index}", "source": {"kind": "repeat_state", "loop_id": "repeat", "state_name": name, "scope": "current"},
            "required": True, "expected_kind": "json", "allow_partial": False,
        })
    record["flow"]["nodes"].append(repeat)
    record["definition_revision"] = authoring.workflow_definition_revision(record)
    authoring.compile_workflow_flow(record)
    ui.personal_workflows[authoring.AUTHORING_ID] = record
    editor = authoring.open_editor(ui, authoring.AUTHORING_ID)
    view = authoring.switch_surface(editor, "Flow")
    fields = authoring.select_node(view, "repeat")
    first = fields.get_by_role("group", name="State 1", exact=True)
    second = fields.get_by_role("group", name="State 2", exact=True)
    first_id = first.get_attribute("data-workflow-history-row")
    second_id = second.get_attribute("data-workflow-history-row")
    first.get_by_label("Decision field name", exact=True).fill("first_pending")
    second.get_by_label("Decision field name", exact=True).fill("second_pending")
    first.get_by_role("button", name="Remove state 1", exact=True).click()
    remaining = fields.get_by_role("group", name="State 1", exact=True)
    expect(remaining).to_have_attribute("data-workflow-history-row", second_id)
    expect(undo_button(editor)).to_have_attribute("title", "Undo: Remove state 1")
    replay(ui, editor, "Undo")
    expect(first).to_have_attribute("data-workflow-history-row", first_id)
    expect(second).to_have_attribute("data-workflow-history-row", second_id)
    expect(first.get_by_label("Decision field name", exact=True)).to_have_value("first_pending")
    expect(second.get_by_label("Decision field name", exact=True)).to_have_value("second_pending")


@pytest.mark.parametrize("status", [400, 409, 503])
def test_failed_save_preserves_both_history_directions_and_original_cas(authoring_ui, status):
    ui = authoring_ui
    original, editor = open_seed(ui)
    editor.get_by_label("Description", exact=True).fill("Retain this edit")
    editor.get_by_label("Workflow name", exact=True).fill("Redo this name")
    replay(ui, editor, "Undo")
    if status == 409:
        ui.mutate_revision(authoring.AUTHORING_ID)
    else:
        ui.reject_next("POST", "/api/user/workflows", status=status, error="Fictional Save failure.")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(editor.get_by_role("alert").first).to_be_visible()
    expect(undo_button(editor)).to_be_enabled()
    expect(redo_button(editor)).to_be_enabled()
    replay(ui, editor, "Redo")
    expect(editor.get_by_label("Workflow name", exact=True)).to_have_value("Redo this name")
    requests = [entry for entry in ui.writes if entry.path in authoring.SAVE_PATHS]
    assert len(requests) == 1
    assert requests[0].body["definition_revision"] == original["definition_revision"]
    assert not ui.workflow_writes


@pytest.mark.parametrize("undo_key,redo_key,width", [
    ("Control+z", "Control+y", 1280),
    ("Control+z", "Control+Shift+z", 390),
    ("Meta+z", "Meta+Shift+z", 390),
])
def test_text_undo_stays_native_and_editor_shortcuts_work_outside_fields(authoring_ui, undo_key, redo_key, width):
    ui = authoring_ui
    original, editor = open_seed(ui)
    ui.page.set_viewport_size({"width": width, "height": 844})
    name = editor.get_by_label("Workflow name", exact=True)
    name.click()
    name.press("End")
    name.press_sequentially(" native")
    name.press("Control+z")
    expect(name).to_have_value(original["name"])
    name.press("Control+Shift+z")
    expect(name).to_have_value(f"{original['name']} native")
    undo_button(editor).focus()
    ui.page.keyboard.press(undo_key)
    expect(name).to_have_value(original["name"])
    expect(redo_button(editor)).to_be_enabled()
    expect(undo_button(editor)).to_be_focused()
    ui.page.keyboard.press(redo_key)
    expect(name).to_have_value(f"{original['name']} native")
    assert not ui.workflow_writes


def test_composition_is_one_group_and_composing_shortcuts_are_not_intercepted(authoring_ui):
    ui = authoring_ui
    original, editor = open_seed(ui)
    name = editor.get_by_label("Workflow name", exact=True)
    name.focus()
    name.dispatch_event("compositionstart", {"data": ""})
    name.fill("Composing")
    name.fill("\u7de8\u96c6")
    intercepted = undo_button(editor).evaluate("""element => {
        const event = new KeyboardEvent('keydown', {
            key: 'z', ctrlKey: true, isComposing: true, bubbles: true, cancelable: true,
        });
        element.dispatchEvent(event);
        return event.defaultPrevented;
    }""")
    assert intercepted is False
    expect(name).to_have_value("\u7de8\u96c6")
    name.dispatch_event("compositionend", {"data": "\u7de8\u96c6"})
    replay(ui, editor, "Undo")
    expect(name).to_have_value(original["name"])
    expect(undo_button(editor)).to_be_disabled()
    replay(ui, editor, "Redo")
    expect(name).to_have_value("\u7de8\u96c6")


def test_editable_and_shadow_text_targets_keep_native_shortcuts(authoring_ui):
    ui = authoring_ui
    _, editor = open_seed(ui)
    editor.get_by_label("Description", exact=True).fill("Keep workflow history unchanged")
    intercepted = editor.get_by_role("group", name="Workflow edit history", exact=True).evaluate("""toolbar => {
        const host = document.createElement('div');
        toolbar.appendChild(host);
        try {
            const editable = document.createElement('div');
            editable.contentEditable = 'true';
            host.appendChild(editable);
            const shadowHost = document.createElement('div');
            host.appendChild(shadowHost);
            const input = document.createElement('input');
            shadowHost.attachShadow({mode: 'open'}).appendChild(input);
            return [editable, input].map(target => {
                const event = new KeyboardEvent('keydown', {
                    key: 'z', ctrlKey: true, bubbles: true, composed: true, cancelable: true,
                });
                target.dispatchEvent(event);
                return event.defaultPrevented;
            });
        } finally {
            host.remove();
        }
    }""")
    assert intercepted == [False, False]
    expect(editor.get_by_label("Description", exact=True)).to_have_value("Keep workflow history unchanged")
    expect(undo_button(editor)).to_be_enabled()
    expect(redo_button(editor)).to_be_disabled()


def test_discrete_common_fields_replay_the_whole_authored_payload(authoring_ui):
    ui = authoring_ui
    original, editor = open_seed(ui)
    unit = "hours" if original["schedule"]["unit"] != "hours" else "minutes"
    editor.get_by_label("Trigger", exact=True).select_option("interval")
    editor.get_by_label("Interval value", exact=True).fill("17")
    editor.get_by_label("Interval unit", exact=True).select_option(unit)
    editor.get_by_label("Error handling", exact=True).select_option("continue")
    editor.get_by_label("Retry count", exact=True).fill("2")
    enabled = editor.get_by_role("checkbox", name=re.compile("^Workflow enabled"))
    chat = editor.get_by_role("checkbox", name=re.compile("^Chat capabilities enabled"))
    enabled.press("Space")
    chat.press("Space")
    for _ in range(7):
        replay(ui, editor, "Undo")
    expect(undo_button(editor)).to_be_disabled()
    expect(editor.get_by_label("Trigger", exact=True)).to_have_value(original["trigger_type"])
    expect(enabled).to_be_checked(checked=original["is_enabled"])
    expect(chat).to_be_checked(checked=original["chat_capabilities_enabled"])
    for _ in range(7):
        replay(ui, editor, "Redo")
    payload = authoring.save(ui, editor)
    assert payload["trigger_type"] == "interval"
    assert payload["schedule"]["value"] == 17
    assert payload["schedule"]["unit"] == unit
    assert payload["error_handling"] == {"strategy": "continue", "retry_count": 2}
    assert payload["is_enabled"] is not original["is_enabled"]
    assert payload["chat_capabilities_enabled"] is not original["chat_capabilities_enabled"]
    assert payload["definition_revision"] == original["definition_revision"]


def test_raw_tag_spacing_replays_without_a_semantically_identical_preview_request(authoring_ui):
    ui = authoring_ui
    _, editor = open_seed(ui)
    view = authoring.switch_surface(editor, "Flow")
    loop_id, fields = authoring.add_block(view, "for_each")
    fields.get_by_label("For each source", exact=True).select_option("workspace_query")
    tags = fields.get_by_label("Query tags", exact=True)
    tags.fill("finance, quarterly, ")
    tags.press("Tab")
    authoring.expect_compiled(view)
    before = len(ui.preview_requests)
    ui.page.clock.install()
    tags.fill(" finance, quarterly,  ")
    tags.press("Tab")
    ui.page.clock.run_for(1000)
    expect(tags).to_have_value(" finance, quarterly,  ")
    assert len(ui.preview_requests) == before
    replay(ui, editor, "Undo")
    expect(tags).to_have_value("finance, quarterly, ")
    replay(ui, editor, "Redo")
    expect(tags).to_have_value(" finance, quarterly,  ")
    authoring.switch_surface(editor, "List")
    expect(authoring.list_block(editor, loop_id).get_by_label("Query tags", exact=True)).to_have_value(" finance, quarterly,  ")
    assert not ui.workflow_writes


def test_delayed_a_b_a_preview_cannot_replace_the_replayed_candidate(authoring_ui):
    ui = authoring_ui
    editor = authoring.open_editor(ui)
    view = authoring.switch_surface(editor, "Flow")
    authoring.expect_compiled(view)
    fields = authoring.select_node(view, "evaluate")
    initial = fields.get_by_label("Task name", exact=True).input_value()
    ui.hold_next_flow(source_kind="draft")
    with ui.page.expect_request(lambda request: "/flow-preview" in request.url):
        fields.get_by_label("Task name", exact=True).fill("Delayed B candidate")
    try:
        replay(ui, editor, "Undo")
        authoring.expect_compiled(view)
        expect(authoring.node_button(view, "evaluate")).to_have_accessible_name(f"Select {initial} (Task)")
    finally:
        ui.release_flow_responses()
    ui.page.wait_for_load_state("networkidle")
    expect(authoring.node_button(view, "evaluate")).to_have_accessible_name(f"Select {initial} (Task)")
    expect(view.get_by_text("Delayed B candidate", exact=True)).to_have_count(0)
    replay(ui, editor, "Redo")
    authoring.expect_compiled(view)
    expect(authoring.node_button(view, "evaluate")).to_have_accessible_name("Select Delayed B candidate (Task)")


def test_pending_save_disables_history_and_save_success_resets_the_session(authoring_ui):
    ui = authoring_ui
    _, editor = open_seed(ui)
    editor.get_by_label("Description", exact=True).fill("Saved description")
    editor.get_by_label("Workflow name", exact=True).fill("Leave on Redo")
    replay(ui, editor, "Undo")
    ui.hold_save_response = True
    with ui.page.expect_request(lambda request: request.method == "POST" and request.url.endswith("/api/user/workflows")):
        editor.get_by_role("button", name="Save workflow", exact=True).click()
    try:
        expect(undo_button(editor)).to_be_disabled()
        expect(redo_button(editor)).to_be_disabled()
        expect(undo_button(editor)).to_have_attribute("title", "Workflow history is unavailable while saving.")
        editor.get_by_role("button", name="Close", exact=True).focus()
        ui.page.keyboard.press("Control+z")
        expect(editor.get_by_label("Description", exact=True)).to_have_value("Saved description")
        assert len([entry for entry in ui.writes if entry.path in authoring.SAVE_PATHS]) == 1
    finally:
        ui.release_save_responses()
    expect(editor).to_have_count(0)
    ui.page.get_by_role("button", name="Edit Authoring seed", exact=True).click()
    editor = ui.page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(undo_button(editor)).to_be_disabled()
    expect(redo_button(editor)).to_be_disabled()


def test_explicit_conversion_starts_empty_history_but_keeps_unsaved_change_protection(authoring_ui):
    ui = authoring_ui
    ui.open("/workspace/workflows")
    ui.page.get_by_role("button", name="Create workflow", exact=True).click()
    editor = ui.page.get_by_role("dialog", name="Create workflow", exact=True)
    editor.get_by_label("Workflow name", exact=True).fill("Before conversion")
    expect(undo_button(editor)).to_have_count(0)
    editor.get_by_role("button", name="Enable structured control flow", exact=True).click()
    ui.page.get_by_role("dialog", name="Enable structured control flow?", exact=True).get_by_role(
        "button", name="Convert draft", exact=True,
    ).click()
    expect(undo_button(editor)).to_be_disabled()
    editor.get_by_label("Workflow name", exact=True).fill("After conversion")
    replay(ui, editor, "Undo")
    expect(editor.get_by_label("Workflow name", exact=True)).to_have_value("Before conversion")
    expect(undo_button(editor)).to_be_disabled()
    expect(editor.get_by_role("button", name="Enable structured control flow", exact=True)).to_have_count(0)
    editor.get_by_role("button", name="Cancel", exact=True).click()
    confirmation = ui.page.get_by_role("dialog", name="Discard unsaved workflow changes?", exact=True)
    expect(confirmation).to_be_visible()
    confirmation.get_by_role("button", name="Discard changes", exact=True).click()
    assert not ui.workflow_writes


def test_history_evicts_only_the_oldest_complete_step_at_one_hundred_actions(authoring_ui):
    ui = authoring_ui
    _, editor = open_seed(ui)
    name = editor.get_by_label("Workflow name", exact=True)
    for index in range(101):
        name.fill(f"History {index}")
        name.press("Tab")
    expect(editor.get_by_role("status").filter(has_text="Older workflow history steps")).to_be_visible()
    expect(name).to_have_value("History 100")
    for _ in range(100):
        undo_button(editor).click()
    expect(name).to_have_value("History 0")
    expect(undo_button(editor)).to_be_disabled()
    expect(redo_button(editor)).to_be_enabled()
    assert not ui.workflow_writes


def test_single_oversized_buffer_requires_confirmation_and_is_never_truncated(authoring_ui):
    ui = authoring_ui
    _, editor = open_seed(ui)
    editor.get_by_label("Workflow name", exact=True).fill("Keep prior history")
    fields = seed_fields(editor)
    authoring.open_details(fields, "Optional JSON schema")
    schema = fields.get_by_label("Optional JSON schema", exact=True)
    initial = schema.input_value()
    oversized = "{" + "x" * (16 * 1024 * 1024)
    schema.fill(oversized)
    confirmation = ui.page.get_by_role("dialog", name="Apply edit and clear history?", exact=True)
    expect(confirmation).to_be_visible()
    confirmation.get_by_role("button", name="Keep draft unchanged", exact=True).click()
    expect(schema).to_have_value(initial)
    expect(editor.get_by_role("alert").filter(has_text="Finish or cancel the current confirmation")).to_have_count(0)
    expect(undo_button(editor)).to_be_enabled()
    schema.fill(oversized)
    expect(confirmation).to_be_visible()
    confirmation.get_by_role("button", name="Apply and clear history", exact=True).click()
    assert schema.evaluate("element => element.value.length") == len(oversized)
    expect(undo_button(editor)).to_be_disabled()
    expect(redo_button(editor)).to_be_disabled()
    expect(editor.get_by_role("status").filter(has_text="history was cleared")).to_be_visible()
    assert not ui.workflow_writes


@pytest.mark.parametrize("status", [401, 403, 404])
def test_confirmed_access_loss_cannot_restore_protected_history(authoring_ui, status):
    ui = authoring_ui
    _, editor = open_seed(ui)
    editor.get_by_label("Workflow name", exact=True).fill("Protected unsaved name")
    ui.reject_next("POST", "/api/user/workflows", status=status, error="Fictional access loss.")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(editor.get_by_role("alert").filter(has_text="Cached authoring details were removed")).to_be_visible()
    expect(undo_button(editor)).to_have_count(0)
    expect(redo_button(editor)).to_have_count(0)
    expect(editor.get_by_label("Workflow name", exact=True)).to_have_count(0)
    ui.page.keyboard.press("Control+z")
    expect(editor.get_by_label("Workflow name", exact=True)).to_have_count(0)
    assert not ui.workflow_writes
