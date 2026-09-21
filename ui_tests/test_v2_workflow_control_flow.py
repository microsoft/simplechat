# test_v2_workflow_control_flow.py
"""
UI regressions for structured If/else, Run when and forward routing.
Version: 0.261.127
Implemented in: 0.261.116

The real local SPA uses the existing closed API fixture and production definition
validation. No model, source service, publication or live workspace is invoked.
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

# Shared fixture imports follow its local module-path setup.
from ui_tests.fixtures.workflow_editor import (
    GROUP_ID,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    workflow_ui,  # noqa: F401
)
from ui_tests.fixtures.workflow_control_definitions import (
    STRUCTURED_ID,
    flow_condition as condition,
    structured_workflow_record as structured_record,
)


pytestmark = pytest.mark.ui


def task_block(page, name):
    return page.get_by_role("region", name=f"{name} block", exact=True)


def add_task(page, region, region_name, name):
    region.get_by_role("button", name=f"Add task to {region_name}", exact=True).click()
    region.get_by_label("Task name", exact=True).last.fill(name)
    block = task_block(page, name)
    block.get_by_label("Instructions", exact=True).fill(f"Produce {name.lower()}.")
    return block


def open_details(block):
    block.get_by_text("Runner, inputs, references and outputs", exact=True).click()


def add_input(block, label, producer, alias, index=1, output=None):
    block.get_by_role("button", name=f"Add {label.lower()} input", exact=True).click()
    block.get_by_label(f"{label} input {index} name", exact=True).fill(alias)
    block.get_by_label(f"{label} input {index} producer", exact=True).select_option(label=producer)
    if output:
        block.get_by_label(f"{label} input {index} output", exact=True).select_option(output)


def select_condition(block, label, field):
    block.get_by_label(f"{label} left input", exact=True).select_option("decision")
    block.get_by_label(f"{label} left field", exact=True).select_option(field)


def test_create_branches_skip_route_and_join_without_raw_json(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Create workflow", exact=True).click()
    page.get_by_label("Workflow name", exact=True).fill("Authored structured flow")
    page.get_by_label("Model", exact=True).select_option(label="Workspace GPT \u00b7 aoai")
    page.get_by_role("button", name="Enable structured control flow", exact=True).click()
    page.get_by_role("button", name="Convert draft", exact=True).click()
    main = page.get_by_role("group", name="Main region", exact=True)
    main.get_by_label("Task name", exact=True).fill("Evaluate")
    evaluate = task_block(page, "Evaluate")
    evaluate.get_by_label("Instructions", exact=True).fill("Return a JSON object with Boolean pass and add_note fields.")
    open_details(evaluate)
    evaluate.get_by_label("Output contract for Evaluate", exact=True).select_option("json")
    for field in ("pass", "add_note"):
        evaluate.get_by_label("Decision field name", exact=True).fill(field)
        evaluate.get_by_role("button", name="Add decision field", exact=True).click()
    main.get_by_role("button", name="Add If/else to Main", exact=True).click()
    branch = page.get_by_role("region", name="If / else block", exact=True)
    add_input(branch, "If / else inputs", "Evaluate", "decision")
    select_condition(branch, "If / else condition", "/pass")
    add_task(page, page.get_by_role("group", name="Then region", exact=True), "Then", "Accept")
    add_task(page, page.get_by_role("group", name="Else region", exact=True), "Else", "Review")
    branch.get_by_role("button", name="Add joined output", exact=True).click()
    branch.get_by_label("Join output 1 Then producer", exact=True).select_option(label="Accept")
    branch.get_by_label("Join output 1 Then output", exact=True).select_option("text")
    branch.get_by_label("Join output 1 Else producer", exact=True).select_option(label="Review")
    branch.get_by_label("Join output 1 Else output", exact=True).select_option("text")
    branch.get_by_label("Join output 1 kind", exact=True).select_option("text")

    main.get_by_role("button", name="Add forward route to Main", exact=True).click()
    route = page.get_by_role("region", name="Forward route block", exact=True)
    add_input(route, "Forward route inputs", "Evaluate", "decision")
    select_condition(route, "Forward route condition", "/pass")
    note = add_task(page, main, "Main", "Optional note")
    open_details(note)
    add_input(note, "Optional note inputs", "Evaluate", "decision")
    note.get_by_text("Run when", exact=True).click()
    expect(note.get_by_role("checkbox", name=re.compile("^Run when"))).to_be_checked()
    select_condition(note, "Run when for Optional note", "/add_note")
    finish = add_task(page, main, "Main", "Finish")
    open_details(finish)
    finish.get_by_role("button", name="Add finish inputs input", exact=True).click()
    producer = finish.get_by_label("Finish inputs input 1 producer", exact=True)
    join_id = producer.locator("option").filter(has_text=re.compile("^Join ")).get_attribute("value")
    assert join_id
    producer.select_option(join_id)
    finish.get_by_label("Finish inputs input 1 name", exact=True).fill("report")
    finish.get_by_label("Finish inputs input 1 output", exact=True).select_option("report")
    add_input(finish, "Finish inputs", "Optional note", "note", index=2, output="text")
    finish.get_by_label("Finish inputs input 2 required", exact=True).uncheck()
    route.get_by_label("Forward route target", exact=True).select_option(label="Finish")
    final_outputs = page.get_by_role("group", name="Final outputs", exact=True)
    add_input(final_outputs, "Final outputs", "Finish", "report", output="text")
    ui.assert_no_overflow()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)

    assert len(ui.workflow_writes) == 1
    body = ui.workflow_writes[0].body
    assert body["definition_version"] == 3
    assert body["durable_execution"] is True
    assert all(isinstance(task["inputs"], list) for task in body["tasks"])
    nodes = body["flow"]["nodes"]
    assert [node["kind"] for node in nodes] == ["task", "if", "route", "task", "task"]
    assert nodes[1]["condition"]["left"] == {"input": "decision", "path": "/pass"}
    assert nodes[1]["join"]["exports"][0]["name"] == "report"
    assert nodes[2]["target"]["node_id"] == nodes[4]["id"]
    assert nodes[3]["run_when"]["left"]["path"] == "/add_note"
    assert body["tasks"][0]["output_contract"]["schema"]["properties"]["pass"] == {"type": "boolean"}
    assert body["flow"]["outputs"][0]["source"]["node_id"] == nodes[4]["id"]
    assert not any("/run" in request.path or "publication" in request.path for request in ui.writes)


def test_skip_dependency_is_rejected_and_stale_save_retains_flow(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    record = structured_record()
    ui.personal_workflows[STRUCTURED_ID] = record
    ui.open(f"/workspace/workflows?workflow_id={STRUCTURED_ID}")
    finish = task_block(page, "Finish")
    open_details(finish)
    finish.get_by_label("Finish inputs input 2 required", exact=True).check()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="can be skipped")).to_be_visible()
    assert not ui.workflow_writes
    finish.get_by_label("Finish inputs input 2 required", exact=True).uncheck()
    page.get_by_label("Workflow name", exact=True).fill("Retained structured draft")
    ui.mutate_revision(STRUCTURED_ID)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="draft has been retained")).to_be_visible()
    expect(page.get_by_label("Workflow name", exact=True)).to_have_value("Retained structured draft")
    expect(page.get_by_label("Forward route target", exact=True)).to_have_value("node:finish")
    expect(page.get_by_role("group", name="Then region", exact=True)).to_be_visible()
    assert not ui.workflow_writes
    assert record["flow"]["nodes"][3]["run_when"] == condition("add_note")


@pytest.mark.parametrize("unsupported", ["node_kind", "executable_field", "input_kind", "runner_field"])
def test_unknown_structured_semantics_are_read_only(workflow_ui, unsupported):
    ui, page = workflow_ui, workflow_ui.page
    record = structured_record()
    if unsupported == "node_kind":
        record["flow"]["nodes"][1]["kind"] = "for_each"
    elif unsupported == "executable_field":
        record["flow"]["nodes"][1]["condition"]["expression"] = "unrecognized executable field"
    elif unsupported == "input_kind":
        record["tasks"][3]["inputs"][0]["source"]["kind"] = "future_item"
    else:
        record["tasks"][3]["runner"]["future_tool_policy"] = "new executor semantics"
    original = copy.deepcopy(record)
    ui.personal_workflows[STRUCTURED_ID] = record
    ui.open(f"/workspace/workflows?workflow_id={STRUCTURED_ID}")
    expect(page.get_by_role("alert").filter(has_text="cannot safely save")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert not ui.workflow_writes
    assert ui.personal_workflows[STRUCTURED_ID] == original


def test_structured_mobile_keyboard_edit_preserves_identity(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    record = structured_record()
    ui.personal_workflows[STRUCTURED_ID] = record
    ui.open(f"/workspace/workflows?workflow_id={STRUCTURED_ID}", theme="dark", width=390, height=844)
    ui.assert_no_overflow()
    limit = page.get_by_label("Maximum execution admissions", exact=True)
    limit.focus()
    limit.press("ArrowDown")
    expect(limit).to_have_value("4999")
    save = page.get_by_role("button", name="Save workflow", exact=True)
    save.focus()
    save.press("Enter")
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["limits"]["max_executions"] == 4999
    assert ui.workflow_writes[-1].body["flow"] == record["flow"]
    assert [task["id"] for task in ui.workflow_writes[-1].body["tasks"]] == [task["id"] for task in record["tasks"]]
    ui.assert_no_overflow()


def test_group_structured_save_keeps_explicit_group_scope(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    record = structured_record(group_id=GROUP_ID)
    ui.group_workflows[GROUP_ID] = {STRUCTURED_ID: record}
    ui.open("/groups")
    ui.select_group(GROUP_ID)
    expect(page.get_by_role("heading", name="Workflows", exact=True)).to_be_visible()
    page.get_by_role("button", name=re.compile("Edit Structured review")).click()
    page.get_by_label("Workflow name", exact=True).fill("Group structured review")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    write = ui.workflow_writes[-1]
    assert write.path == "/api/group/workflows"
    assert write.query["group_id"] == [GROUP_ID]
    assert write.body["group_id"] == GROUP_ID
    assert write.body["flow"] == record["flow"]
    assert not any(request.path == "/api/user/settings" and request.method != "GET" for request in ui.requests)


def test_conversion_never_silently_changes_continue_on_error_inputs(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.personal_workflows[WORKFLOW_ID]["error_handling"]["strategy"] = "continue"
    ui.open(f"/workspace/workflows?workflow_id={WORKFLOW_ID}")
    page.get_by_role("button", name="Enable structured control flow", exact=True).click()
    page.get_by_role("button", name="Convert draft", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="explicit task inputs")).to_be_visible()
    expect(page.get_by_role("button", name="Enable structured control flow", exact=True)).to_be_visible()
    assert ui.personal_workflows[WORKFLOW_ID]["definition_version"] == 2
    assert not ui.workflow_writes


def test_structured_publication_uses_one_explicit_input_and_destination(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    record = structured_record()
    record["tasks"][1]["document_action"] = {"type": "analyze", "document_ids": ["personal-brief"]}
    ui.personal_workflows[STRUCTURED_ID] = record
    ui.open(f"/workspace/workflows?workflow_id={STRUCTURED_ID}")
    finish = task_block(page, "Finish")
    open_details(finish)
    finish.get_by_text("Publish an existing analysis artifact", exact=True).click()
    finish.get_by_label("Publication scope for Finish", exact=True).select_option("group")
    finish.get_by_label("Publication workspace ID for Finish", exact=True).fill("explicit-destination")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="exactly one explicit native Analyze input")).to_be_visible()
    assert not ui.workflow_writes
    finish.get_by_role("button", name="Finish inputs remove input 2", exact=True).click()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    task = ui.workflow_writes[-1].body["tasks"][-1]
    assert task["publication"] == {
        "artifact_format": "md", "workspace_scope": "group", "group_id": "explicit-destination",
    }
    assert len(task["inputs"]) == 1 and task["inputs"][0]["source"]["node_id"] == "decision-join"
    assert task["runner"]["type"] == "inherit" and task["document_action"]["type"] == "none"
    assert not any(request.path.endswith("/run") or request.path.endswith("/promote") for request in ui.writes)
