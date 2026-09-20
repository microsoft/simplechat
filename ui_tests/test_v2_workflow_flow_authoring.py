# test_v2_workflow_flow_authoring.py
"""
Offline real-bundle browser regressions for M5B workflow Flow authoring.
Version: 0.261.122
Implemented in: 0.261.122

Uses the existing fictional, closed API harness and real Python compiler.
Only explicit scoped Save and data-only compiler previews may write requests.
Run with PLAYWRIGHT_SERVICE_URL='' in the same pytest process; no live browser,
model, workflow admission, approval, continuation, publication or readiness call.
"""

import copy
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

# Shared fixtures and pure production imports require this local path setup.
from ui_tests.fixtures.workflow_flow import (
    FLOW_NAME,
    FLOW_RUN_ID,
    FLOW_WORKFLOW_ID,
    GROUP_ID,
    MALICIOUS_LABEL,
    SECOND_GROUP_ID,
    WorkflowFlowFixture,
    connect_options,  # noqa: F401
    flow_binding,
    flow_workflow_record,
)
from ui_tests.fixtures.workflow_loops import record_contract
from ui_tests.fixtures.workflow_repeat_until import WorkflowRepeatFixture
from functions_workflow_definitions import workflow_definition_revision
from functions_workflow_flow import compile_workflow_flow


pytestmark = pytest.mark.ui
AUTHORING_ID = "flow-authoring-draft"
SAVE_PATHS = {"/api/user/workflows", "/api/group/workflows"}
PREVIEW_PATHS = {f"{path}/flow-preview" for path in SAVE_PATHS}


class WorkflowAuthoringFixture(WorkflowFlowFixture):
    """Permit only explicit authoring saves in the otherwise read-only harness."""

    def __init__(self, page):
        super().__init__(page)
        self.max_tasks = 20
        self.hold_save_response = False
        self.held_save_responses = []

    def _dispatch(self, route, entry):
        if entry.method == "POST" and entry.path in SAVE_PATHS:
            group_id = entry.query.get("group_id", [None])[0]
            if entry.path == "/api/group/workflows":
                assert group_id in self.group_workflows, entry
                if not self.group_can_manage:
                    self._json(route, {"error": "Workflow management access is required."}, 403)
                    return
                self._workflow_collection(route, entry, self.group_workflows[group_id], "group", group_id)
            else:
                assert not entry.query, entry
                self._workflow_collection(route, entry, self.personal_workflows, "personal")
        elif entry.method == "GET" and entry.path in {
            "/api/user/workflows/editor-options", "/api/group/workflows/editor-options",
        }:
            group = entry.path.startswith("/api/group/")
            group_id = entry.query.get("group_id", [None])[0]
            assert group_id in self.group_workflows if group else not entry.query, entry
            options = self._options(group)
            options["max_tasks"] = self.max_tasks
            options["can_manage"] = self.group_can_manage if group else True
            if group:
                options["scope"] = {"type": "group", "id": group_id}
                for agent in options["agents"]:
                    if agent.get("is_group"):
                        agent["group_id"] = group_id
            self._json(route, options)
        elif entry.method == "GET" and entry.path == "/api/group_documents":
            group_ids = entry.query.get("group_ids", [])
            assert group_ids and all(group_id in self.group_workflows for group_id in group_ids), entry
            documents = [document for group_id in group_ids for document in self.group_documents.get(group_id, [])]
            self._json(route, {"documents": documents, "total_count": len(documents)})
        else:
            super()._dispatch(route, entry)

    def _json(self, route, payload, status=200):
        if self.hold_save_response and route.request.method == "POST" and urlsplit(route.request.url).path in SAVE_PATHS:
            self.hold_save_response = False
            self.held_save_responses.append((route, copy.deepcopy(payload), status))
            return
        super()._json(route, payload, status)

    def release_save_responses(self):
        held, self.held_save_responses = self.held_save_responses, []
        for route, payload, status in held:
            super()._json(route, payload, status)

    def assert_authoring_only(self):
        assert all(
            entry.method == "POST" and entry.path in SAVE_PATHS | PREVIEW_PATHS for entry in self.writes
        ), self.writes
        forbidden = re.compile(
            r"/(?:run|approve|retry|resume|continue|publish|readiness)(?:/|$)|/runtime/decision(?:/|$)|/publication(?:/|$)"
        )
        assert not [entry for entry in self.requests if forbidden.search(entry.path)]
        assert all(asset.startswith("/static/") for asset in self.loaded_assets)

    def assert_clean(self):
        assert not self.held_flow_responses, "A compiler response gate was not released."
        assert not self.flow_response_gates, "An expected compiler request was not made."
        assert not self.held_save_responses and not self.hold_save_response
        self.assert_authoring_only()
        WorkflowRepeatFixture.assert_clean(self)


@pytest.fixture
def authoring_ui(page):
    fixture = WorkflowAuthoringFixture(page)
    yield fixture
    try:
        fixture.assert_clean()
    finally:
        fixture.release_flow_responses()
        fixture.release_save_responses()
        fixture.flow_response_gates.clear()


def seed_record(*, kind="json"):
    record = flow_workflow_record(name="Authoring seed")
    seed = copy.deepcopy(next(task for task in record["tasks"] if task["id"] == "evaluate"))
    seed.update(id="catalogue-seed", name="Seed decision" if kind == "json" else "Seed records", order=1)
    if kind == "records":
        seed["output_contract"] = record_contract()
    record.update(
        id=AUTHORING_ID,
        tasks=[seed],
        flow={"id": "root", "nodes": [{"id": "seed", "kind": "task", "task_id": seed["id"]}], "outputs": []},
    )
    record["definition_revision"] = workflow_definition_revision(record)
    compile_workflow_flow(record)
    return record


def install_seed(ui, *, kind="json"):
    record = seed_record(kind=kind)
    ui.personal_workflows[AUTHORING_ID] = record
    return copy.deepcopy(record)


def open_editor(ui, workflow_id=FLOW_WORKFLOW_ID, *, group_id=None, **options):
    if group_id:
        ui.open("/groups", **options)
        ui.page.get_by_label("Group workspace", exact=True).select_option(group_id)
        name = ui.group_workflows[group_id][workflow_id]["name"]
        ui.page.get_by_role("button", name=f"Edit {name}", exact=True).click()
    else:
        ui.open(f"/workspace/workflows?workflow_id={workflow_id}", **options)
    editor = ui.page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(editor).to_be_visible()
    switch = editor.get_by_role("group", name="Workflow authoring surface", exact=True)
    expect(switch.get_by_role("button", name="List authoring", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(editor.get_by_role("group", name="Main region", exact=True)).to_be_visible()
    assert not ui.preview_requests, "Opening the default List must not request a compiler preview."
    return editor


def switch_surface(editor, name):
    button = editor.get_by_role("group", name="Workflow authoring surface", exact=True).get_by_role(
        "button", name=f"{name} authoring", exact=True,
    )
    button.focus()
    button.press("Enter")
    expect(button).to_have_attribute("aria-pressed", "true")
    if name == "Flow":
        view = editor.get_by_role("region", name="Workflow Flow authoring", exact=True)
        expect(view).to_be_visible()
        expect(view.get_by_role("region", name="Selected block configuration", exact=True)).to_be_visible()
        return view
    expect(editor.get_by_role("group", name="Main region", exact=True)).to_be_visible()
    expect(editor.get_by_role("region", name="Workflow Flow authoring", exact=True)).to_have_count(0)
    return editor


def node_button(view, node_id):
    return view.locator(f"button[data-workflow-node-id='{node_id}']")


def configuration(view):
    return view.get_by_role("region", name="Selected block configuration", exact=True)


def select_node(view, node_id):
    button = node_button(view, node_id)
    button.focus()
    button.press("Enter")
    expect(button).to_have_attribute("aria-pressed", "true")
    fields = configuration(view)
    expect(fields.get_by_text(f"Canonical ID: {node_id}", exact=True)).to_be_visible()
    return fields


def list_block(editor, node_id):
    return editor.locator(f"section[data-workflow-authoring-id='{node_id}']")


def open_details(fields, title="Runner, inputs, references and outputs"):
    summary = fields.get_by_text(title, exact=True)
    details = summary.locator("..")
    if details.get_attribute("open") is None:
        summary.click()


def selected_id(view):
    return view.locator("button[data-workflow-node-id][aria-pressed='true']").get_attribute("data-workflow-node-id")


def child_region(view, owner_id, label):
    view.get_by_role("button", name="Add block in Flow", exact=True).click()
    placement = view.get_by_role("group", name="Add workflow block", exact=True)
    option = placement.get_by_label("Destination region", exact=True).locator("option").filter(
        has_text=re.compile(rf" / {re.escape(owner_id)} / {re.escape(label)}$"),
    )
    expect(option).to_have_count(1)
    region_id = option.get_attribute("value")
    placement.get_by_role("button", name="Cancel block placement", exact=True).click()
    return region_id


def add_block(view, kind, *, region_id="root", before_id=""):
    view.get_by_role("button", name="Add block in Flow", exact=True).click()
    placement = view.get_by_role("group", name="Add workflow block", exact=True)
    expect(placement.get_by_label("Block kind", exact=True)).to_be_focused()
    placement.get_by_label("Block kind", exact=True).select_option(kind)
    placement.get_by_label("Destination region", exact=True).select_option(region_id)
    placement.get_by_label("Insert before", exact=True).select_option(before_id)
    placement.get_by_role("button", name="Add block", exact=True).click()
    expect(placement).to_have_count(0)
    return selected_id(view), configuration(view)


def add_task(view, name, *, region_id="root", before_id="", kind="text"):
    node_id, fields = add_block(view, "task", region_id=region_id, before_id=before_id)
    expect(fields.get_by_label("Task name", exact=True)).to_be_focused()
    fields.get_by_label("Task name", exact=True).fill(name)
    fields.get_by_label("Instructions", exact=True).fill(f"Produce the {name.lower()} result without running this fixture.")
    open_details(fields)
    fields.get_by_label(f"Output contract for {name}", exact=True).select_option(kind)
    return node_id, fields


def add_input(fields, label, node_id, alias, *, index=1, output=None):
    fields.get_by_role("button", name=f"Add {label.lower()} input", exact=True).click()
    fields.get_by_label(f"{label} input {index} name", exact=True).fill(alias)
    fields.get_by_label(f"{label} input {index} producer", exact=True).select_option(node_id)
    if output:
        fields.get_by_label(f"{label} input {index} output", exact=True).select_option(output)


def move_block(view, node_id, *, region_id, before_id=""):
    select_node(view, node_id)
    view.get_by_role("button", name="Move selected block", exact=True).click()
    placement = view.get_by_role("group", name="Move workflow block", exact=True)
    expect(placement.get_by_label("Destination region", exact=True)).to_be_focused()
    placement.get_by_label("Destination region", exact=True).select_option(region_id)
    placement.get_by_label("Insert before", exact=True).select_option(before_id)
    placement.get_by_role("button", name="Apply block move", exact=True).click()
    expect(placement).to_have_count(0)


def expect_compiled(view):
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Compiler-validated draft\."))).to_be_visible()
    expect(view.locator(".workflow-flow-control-edge").first).to_be_attached()


def expect_unvalidated(view):
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Unvalidated draft\."))).to_be_visible()
    expect(view.locator(".workflow-flow-control-edge")).to_have_count(0)


def save(ui, editor):
    before = len(ui.workflow_writes)
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(editor).to_have_count(0)
    assert len(ui.workflow_writes) == before + 1
    ui.assert_authoring_only()
    return ui.workflow_writes[-1].body


def expected_saved_payload(record):
    """The existing editor's explicit wire defaults, not a graph serializer."""
    expected = copy.deepcopy(record)
    expected["tasks"].sort(key=lambda task: task["order"])
    for index, task in enumerate(expected["tasks"], 1):
        task["order"] = index
        task["runner"] = {**task["runner"], "model_endpoint_id": "", "model_id": ""}
    expected["task_prompt"] = expected["tasks"][0]["instructions"].strip()
    return expected


@pytest.mark.parametrize("edit_surface", ["List", "Flow"])
def test_equivalent_list_flow_list_edits_save_exact_payload_and_original_revision(authoring_ui, edit_surface):
    ui = authoring_ui
    record = ui.personal_workflows[FLOW_WORKFLOW_ID]
    task = next(task for task in record["tasks"] if task["id"] == "evaluate")
    task["id"] = "catalogue-evaluation"
    record["flow"]["nodes"][0]["task_id"] = task["id"]
    record["untouched_integration"] = {"nested": [False, 0, None, {"name": "preserve exactly"}]}
    record["definition_revision"] = workflow_definition_revision(record)
    original = copy.deepcopy(record)
    editor = open_editor(ui)
    editor.get_by_label("Workflow name", exact=True).fill("Round-trip authoring")
    editor.get_by_label("Description", exact=True).fill("Preserve the exact envelope and typed selectors.")
    list_block(editor, "evaluate").get_by_label("Task name", exact=True).focus()
    if edit_surface == "Flow":
        view = switch_surface(editor, "Flow")
        expect(node_button(view, "evaluate")).to_have_attribute("aria-pressed", "true")
        fields = select_node(view, "evaluate")
    else:
        fields = list_block(editor, "evaluate")
    fields.get_by_label("Task name", exact=True).fill("Authored evaluation")
    fields.get_by_label("Instructions", exact=True).fill("Produce a typed decision for the declared fields.")
    open_details(fields)
    approval = fields.get_by_role("checkbox", name=re.compile("^Require approval before this task"))
    approval.focus()
    approval.press("Space")
    expect(approval).to_be_checked()
    fields.get_by_label("Approval message for Authored evaluation", exact=True).fill("Review the declared decision.")
    if edit_surface == "List":
        view = switch_surface(editor, "Flow")
    expect_compiled(view)
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Authored evaluation (Task)")
    switch_surface(editor, "List")
    fields = list_block(editor, "evaluate")
    expect(fields.get_by_label("Task name", exact=True)).to_have_value("Authored evaluation")
    expect(fields.get_by_label("Instructions", exact=True)).to_have_value("Produce a typed decision for the declared fields.")
    open_details(fields)
    expect(fields.get_by_label("Approval message for Authored evaluation", exact=True)).to_have_value("Review the declared decision.")
    assert not ui.workflow_writes
    assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original
    assert ui.preview_requests
    assert all(
        request.body["definition"]["definition_revision"] == original["definition_revision"]
        for request in ui.preview_requests
    )
    assert any(payload["source"]["definition_revision"].startswith("DRAFT:") for payload in ui.flow_payloads)

    expected = expected_saved_payload(original)
    expected.update(name="Round-trip authoring", description="Preserve the exact envelope and typed selectors.")
    expected_task = next(task for task in expected["tasks"] if task["id"] == "catalogue-evaluation")
    expected_task.update(
        name="Authored evaluation",
        instructions="Produce a typed decision for the declared fields.",
        approval={"required": True, "message": "Review the declared decision."},
    )
    payload = save(ui, editor)
    assert payload == expected
    assert payload["definition_revision"] == original["definition_revision"]
    assert not payload["definition_revision"].startswith("DRAFT:")
    assert compile_workflow_flow(payload)["flow"] == compile_workflow_flow(expected)["flow"]
    assert len([request for request in ui.writes if request.path in SAVE_PATHS]) == 1


def test_flow_authors_tasks_if_join_forward_route_run_when_and_root_output(authoring_ui):
    ui = authoring_ui
    install_seed(ui)
    editor = open_editor(ui, AUTHORING_ID)
    view = switch_surface(editor, "Flow")
    branch_id, fields = add_block(view, "if")
    add_input(fields, "If / else inputs", "seed", "decision", output="json")
    fields.get_by_label("If / else condition left input", exact=True).select_option("decision")
    fields.get_by_label("If / else condition left field", exact=True).select_option("/pass")
    then_id, else_id = child_region(view, branch_id, "Then"), child_region(view, branch_id, "Else")
    accepted_id, _ = add_task(view, "Accepted report", region_id=then_id)
    reviewed_id, _ = add_task(view, "Reviewed report", region_id=else_id)
    fields = select_node(view, branch_id)
    fields.get_by_role("button", name="Add joined output", exact=True).click()
    fields.get_by_label("Join output 1 Then producer", exact=True).select_option(accepted_id)
    fields.get_by_label("Join output 1 Then output", exact=True).select_option("text")
    fields.get_by_label("Join output 1 Else producer", exact=True).select_option(reviewed_id)
    fields.get_by_label("Join output 1 Else output", exact=True).select_option("text")
    fields.get_by_label("Join output 1 kind", exact=True).select_option("text")
    join_id = view.get_by_role("button", name="Select Join (Join)", exact=True).get_attribute("data-workflow-node-id")
    route_id, fields = add_block(view, "route")
    add_input(fields, "Forward route inputs", "seed", "decision", output="json")
    fields.get_by_label("Forward route condition left input", exact=True).select_option("decision")
    fields.get_by_label("Forward route condition left field", exact=True).select_option("/pass")
    note_id, fields = add_task(view, "Optional draft note")
    add_input(fields, "Optional draft note inputs", "seed", "decision", output="json")
    run_when = fields.get_by_role("checkbox", name=re.compile("^Run when"))
    run_when.focus()
    run_when.press("Space")
    expect(run_when).to_be_checked()
    fields.get_by_label("Run when for Optional draft note left input", exact=True).select_option("decision")
    fields.get_by_label("Run when for Optional draft note left field", exact=True).select_option("/add_note")
    finish_id, fields = add_task(view, "Final report")
    add_input(fields, "Final report inputs", join_id, "report", output="report")
    fields = select_node(view, route_id)
    fields.get_by_label("Forward route target", exact=True).select_option(f"node:{finish_id}")
    fields = select_node(view, "root")
    add_input(fields, "Final outputs", finish_id, "report", output="text")
    expect_compiled(view)
    switch_surface(editor, "List")
    expect(editor.get_by_role("group", name="Then region", exact=True)).to_contain_text("Accepted report")
    expect(editor.get_by_role("group", name="Else region", exact=True)).to_contain_text("Reviewed report")
    payload = save(ui, editor)
    nodes = payload["flow"]["nodes"]
    assert [node["kind"] for node in nodes] == ["task", "if", "route", "task", "task"]
    assert [node["id"] for node in nodes] == ["seed", branch_id, route_id, note_id, finish_id]
    assert nodes[1]["then"]["id"] == then_id and nodes[1]["else"]["id"] == else_id
    assert nodes[1]["join"]["id"] == join_id
    assert nodes[1]["join"]["exports"] == [{
        "name": "report", "expected_kind": "text", "required": True,
        "then": {"node_id": accepted_id, "output": "text"},
        "else": {"node_id": reviewed_id, "output": "text"},
    }]
    assert nodes[2]["target"] == {"node_id": finish_id}
    assert nodes[3]["run_when"]["left"] == {"input": "decision", "path": "/add_note"}
    assert payload["flow"]["outputs"] == [flow_binding("report", finish_id, "text", kind="text")]
    assert len(payload["tasks"]) == 5


def test_flow_authors_saved_collection_for_each_body_binding_and_exact_collect(authoring_ui):
    ui = authoring_ui
    install_seed(ui, kind="records")
    editor = open_editor(ui, AUTHORING_ID)
    view = switch_surface(editor, "Flow")
    loop_id, fields = add_block(view, "for_each")
    fields.get_by_label("For each source", exact=True).select_option("input")
    fields.get_by_label("For each maximum items", exact=True).fill("3")
    fields.get_by_label("Collection input name", exact=True).fill("rows")
    fields.get_by_label("Saved collection output", exact=True).select_option(label="Seed records / records (records)")
    body_id = child_region(view, loop_id, "Body")
    item_id, fields = add_task(view, "Inspect record", region_id=body_id, kind="records")
    fields.get_by_label("Record field name", exact=True).fill("finding")
    fields.get_by_label("Record field type", exact=True).select_option("string")
    fields.get_by_role("button", name="Add record field", exact=True).click()
    fields.get_by_role("button", name="Add inspect record inputs input", exact=True).click()
    fields.get_by_label("Inspect record inputs input 1 name", exact=True).fill("item")
    fields.get_by_label("Inspect record inputs input 1 source", exact=True).select_option("loop_item")
    expect(fields.get_by_label("Inspect record inputs input 1 loop", exact=True)).to_have_value(loop_id)
    fields = select_node(view, body_id)
    add_input(fields, "Body outputs", item_id, "findings", output="records")
    collect_id, fields = add_block(view, "collect")
    fields.get_by_label("Collect source loop", exact=True).select_option(loop_id)
    fields.get_by_label("Collect body output", exact=True).select_option("findings")
    fields.get_by_label("Collect expected count", exact=True).fill("3")
    fields.get_by_label("Collect require complete coverage", exact=True).check()
    fields = select_node(view, "root")
    add_input(fields, "Final outputs", collect_id, "findings", output="records")
    expect_compiled(view)
    payload = save(ui, editor)
    loop, collect = payload["flow"]["nodes"][1:]
    assert loop["id"] == loop_id and loop["max_items"] == 3
    assert loop["iterable"] == {"kind": "input", "name": "rows"}
    assert loop["inputs"] == [flow_binding("rows", "seed", "records", kind="records")]
    assert loop["body"]["id"] == body_id
    assert loop["body"]["outputs"] == [flow_binding("findings", item_id, "records", kind="records")]
    task = next(task for task in payload["tasks"] if task["id"] == loop["body"]["nodes"][0]["task_id"])
    assert task["inputs"][0]["source"] == {"kind": "loop_item", "loop_id": loop_id, "scope": "current"}
    assert collect["id"] == collect_id
    assert collect["source"] == {"loop_id": loop_id, "output": "findings"}
    assert collect["output_contract"]["expected_count"] == 3
    assert collect["output_contract"]["require_complete_coverage"] is True
    assert not [request for request in ui.requests if request.path.endswith("/loop-preview")]


def test_flow_authors_repeat_with_unset_maximum_typed_next_state_until_and_exports(authoring_ui):
    ui = authoring_ui
    install_seed(ui)
    editor = open_editor(ui, AUTHORING_ID)
    view = switch_surface(editor, "Flow")
    repeat_id, fields = add_block(view, "repeat_until")
    maximum = fields.get_by_label("Maximum rounds before manual continuation", exact=True)
    expect(maximum).to_have_value("")
    expect(maximum).to_be_focused()
    expect_unvalidated(view)
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    assert not ui.workflow_writes
    expect(node_button(view, repeat_id)).to_be_visible()
    maximum.fill("2")
    fields.get_by_role("button", name="Add state slot", exact=True).click()
    expect(fields.get_by_label("State 1 name", exact=True)).to_be_focused()
    fields.get_by_label("State 1 name", exact=True).fill("review")
    fields.get_by_label("State 1 kind", exact=True).select_option("json")
    fields.get_by_label("State 1 initial producer", exact=True).select_option("seed")
    fields.get_by_label("State 1 initial output", exact=True).select_option("json")
    fields.get_by_role("button", name="State 1 use initial schema", exact=True).click()
    body_id = child_region(view, repeat_id, "Body")
    next_id, fields = add_task(view, "Next decision", region_id=body_id, kind="json")
    for name in ("pass", "add_note"):
        fields.get_by_label("Decision field name", exact=True).fill(name)
        fields.get_by_role("button", name="Add decision field", exact=True).click()
    fields.get_by_role("button", name="Add next decision inputs input", exact=True).click()
    fields.get_by_label("Next decision inputs input 1 name", exact=True).fill("current")
    fields.get_by_label("Next decision inputs input 1 source", exact=True).select_option("repeat_state")
    expect(fields.get_by_label("Next decision inputs input 1 state", exact=True)).to_have_value("review")
    fields = select_node(view, body_id)
    add_input(fields, "Repeat body outputs", next_id, "next_review", output="json")
    fields = select_node(view, repeat_id)
    fields.get_by_label("State 1 next body output", exact=True).select_option("next_review")
    fields.get_by_label("Stop after a round when left input", exact=True).select_option("review")
    fields.get_by_label("Stop after a round when left field", exact=True).select_option("/pass")
    fields.get_by_role("button", name="Add Repeat export", exact=True).click()
    fields.get_by_label("Repeat export 1 name", exact=True).fill("review")
    fields.get_by_label("Repeat export 1 output", exact=True).select_option("next_review")
    fields = select_node(view, "root")
    add_input(fields, "Final outputs", repeat_id, "review", output="review")
    expect_compiled(view)
    payload = save(ui, editor)
    repeat = payload["flow"]["nodes"][1]
    assert repeat["id"] == repeat_id and repeat["max_iterations"] == 2
    assert set(repeat) == {"id", "kind", "max_iterations", "state", "body", "until", "exports"}
    assert repeat["state"][0]["initial"] == {
        "kind": "node_output", "node_id": "seed", "output": "json", "scope": "current",
    }
    assert repeat["state"][0]["next"] == "next_review"
    assert repeat["state"][0]["output_contract"]["schema"] == payload["tasks"][0]["output_contract"]["schema"]
    assert repeat["until"] == {
        "op": "eq", "left": {"input": "review", "path": "/pass"}, "right": {"literal": True},
    }
    assert repeat["exports"] == [{"name": "review", "output": "next_review"}]
    assert repeat["body"]["nodes"][0]["id"] == next_id


def test_same_and_cross_region_moves_preserve_ids_and_catalogue_order(authoring_ui):
    ui = authoring_ui
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    moved_id, _ = add_task(view, "Movable report")
    move_block(view, moved_id, region_id="root", before_id="note")
    expect(node_button(view, moved_id)).to_be_focused()
    switch_surface(editor, "List")
    root = editor.get_by_role("group", name="Main region", exact=True)
    assert root.locator(":scope > section").evaluate_all(
        "elements => elements.map(element => element.dataset.workflowAuthoringId)"
    ) == ["evaluate", "choose", "bypass-note", moved_id, "note", "finish"]
    view = switch_surface(editor, "Flow")
    move_block(view, moved_id, region_id="accepted-path", before_id="accept")
    expect(node_button(view, moved_id)).to_have_attribute("aria-pressed", "true")
    expect(node_button(view, moved_id)).to_be_focused()
    expect(ui.page.get_by_role("dialog", name="Move this flow block?", exact=True)).to_have_count(0)
    switch_surface(editor, "List")
    moved = list_block(editor, moved_id)
    assert moved.evaluate("element => element.contains(document.activeElement) || element === document.activeElement")
    payload = save(ui, editor)
    branch = payload["flow"]["nodes"][1]
    assert [node["id"] for node in branch["then"]["nodes"]] == [moved_id, "accept"]
    assert branch["then"]["nodes"][1] == original["flow"]["nodes"][1]["then"]["nodes"][0]
    assert branch["else"] == original["flow"]["nodes"][1]["else"]
    assert branch["join"] == original["flow"]["nodes"][1]["join"]
    assert [task["id"] for task in payload["tasks"][:-1]] == [task["id"] for task in original["tasks"]]
    assert branch["then"]["nodes"][0]["task_id"] == payload["tasks"][-1]["id"]


def test_remove_confirmation_preserves_dangling_selector_until_explicit_repair(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    select_node(view, "note")
    view.get_by_role("button", name="Remove selected block", exact=True).click()
    confirmation = page.get_by_role("dialog", name="Remove this flow block?", exact=True)
    expect(confirmation).to_contain_text("finish")
    expect(confirmation).to_contain_text("inputs[1] (note)")
    expect(confirmation).to_contain_text("note")
    confirmation.get_by_role("button", name="Keep draft unchanged", exact=True).click()
    expect(node_button(view, "note")).to_have_count(1)
    expect_compiled(view)
    assert not ui.workflow_writes
    select_node(view, "note")
    view.get_by_role("button", name="Remove selected block", exact=True).click()
    confirmation.get_by_role("button", name="Remove block", exact=True).click()
    expect(confirmation).to_have_count(0)
    expect(node_button(view, "note")).to_have_count(0)
    expect(node_button(view, "finish")).to_be_focused()
    expect_unvalidated(view)
    fields = select_node(view, "finish")
    open_details(fields)
    expect(fields.get_by_label("Finish inputs input 2 producer", exact=True)).to_have_value("note")
    expect(fields.get_by_label("Finish inputs input 2 output", exact=True)).to_have_value("text")
    expect(fields.get_by_label("Finish inputs input 2 required", exact=True)).not_to_be_checked()
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(editor.get_by_role("alert").filter(has_text=re.compile("missing producer|undeclared output")).first).to_be_visible()
    assert not [entry for entry in ui.writes if entry.path in SAVE_PATHS]
    assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original
    fields.get_by_role("button", name="Finish inputs remove input 2", exact=True).click()
    expect_compiled(view)
    payload = save(ui, editor)
    assert [node["id"] for node in payload["flow"]["nodes"]] == ["evaluate", "choose", "bypass-note", "finish"]
    assert [task["id"] for task in payload["tasks"]] == ["finish", "review", "accept", "evaluate"]
    assert next(task for task in payload["tasks"] if task["id"] == "finish")["inputs"] == original["tasks"][0]["inputs"][:1]
    assert payload["flow"]["nodes"][2]["target"] == {"node_id": "finish"}


def test_cross_region_move_confirmation_retains_exact_join_reference_and_can_be_repaired(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    move_block(view, "accept", region_id="root")
    confirmation = page.get_by_role("dialog", name="Move this flow block?", exact=True)
    expect(confirmation).to_contain_text("decision-join")
    expect(confirmation).to_contain_text("exports[0] (report).then")
    confirmation.get_by_role("button", name="Keep draft unchanged", exact=True).click()
    switch_surface(editor, "List")
    expect(editor.get_by_role("group", name="Then region", exact=True)).to_contain_text("Accept")
    view = switch_surface(editor, "Flow")
    move_block(view, "accept", region_id="root")
    confirmation.get_by_role("button", name="Move block", exact=True).click()
    expect(confirmation).to_have_count(0)
    expect_unvalidated(view)
    fields = select_node(view, "decision-join")
    expect(fields.get_by_label("Join output 1 Then producer", exact=True)).to_have_value("accept")
    expect(fields.get_by_label("Join output 1 Then output", exact=True)).to_have_value("text")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(editor.get_by_role("alert").filter(has_text=re.compile("earlier|reachable|scope")).first).to_be_visible()
    assert not [entry for entry in ui.writes if entry.path in SAVE_PATHS]
    move_block(view, "accept", region_id="accepted-path")
    expect(confirmation).to_contain_text("exports[0] (report).then")
    confirmation.get_by_role("button", name="Move block", exact=True).click()
    expect(confirmation).to_have_count(0)
    expect_compiled(view)
    payload = save(ui, editor)
    assert payload["flow"] == original["flow"]
    assert [task["id"] for task in payload["tasks"]] == [task["id"] for task in original["tasks"]]


def test_escape_cancels_impact_confirmation_without_closing_or_changing_authoring(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    description = "Keep this unsaved description when an impact dialog is canceled."
    editor.get_by_label("Description", exact=True).fill(description)
    view = switch_surface(editor, "Flow")
    expect_compiled(view)
    candidate = copy.deepcopy(ui.preview_requests[-1].body["definition"])

    for action, node_id, reference in (
        ("Move", "accept", "exports[0] (report).then"),
        ("Remove", "note", "inputs[1] (note)"),
    ):
        select_node(view, node_id)
        preview_count = len(ui.preview_requests)
        if action == "Move":
            move_block(view, node_id, region_id="root")
        else:
            button = view.get_by_role("button", name="Remove selected block", exact=True)
            button.focus()
            button.press("Enter")
        confirmation = page.get_by_role("dialog", name=f"{action} this flow block?", exact=True)
        expect(confirmation.get_by_role("list", name="Affected draft references", exact=True)).to_contain_text(reference)
        page.keyboard.press("Escape")
        expect(confirmation).to_have_count(0)
        expect(editor).to_be_visible()
        expect(page.get_by_role("dialog", name="Discard unsaved workflow changes?", exact=True)).to_have_count(0)
        expect(node_button(view, node_id)).to_have_attribute("aria-pressed", "true")
        expect(node_button(view, node_id)).to_be_focused()
        expect(editor.get_by_label("Description", exact=True)).to_have_value(description)
        expect_compiled(view)
        assert len(ui.preview_requests) == preview_count
        assert ui.preview_requests[-1].body["definition"] == candidate
        assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original
        assert not ui.workflow_writes

    expected = expected_saved_payload(original)
    expected["description"] = description
    assert save(ui, editor) == expected


def test_invalid_schema_and_unfinished_decision_fields_survive_surface_and_node_switches(authoring_ui):
    ui = authoring_ui
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    fields = select_node(view, "evaluate")
    open_details(fields)
    fields.get_by_label("Decision field name", exact=True).fill("pending_choice")
    fields.get_by_label("Decision field type", exact=True).select_option("enum")
    fields.get_by_label("Decision enum values", exact=True).fill("first\nsecond\n")
    open_details(fields, "Optional JSON schema")
    fields.get_by_label("Optional JSON schema", exact=True).fill("{")
    expect(fields.get_by_role("alert").filter(has_text="JSON schema must be valid JSON.")).to_be_visible()
    expect_unvalidated(view)
    select_node(view, "finish")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(editor.get_by_role("alert").filter(has_text="JSON schema must be valid JSON.").first).to_be_visible()
    assert not ui.workflow_writes
    fields = select_node(view, "evaluate")
    open_details(fields)
    open_details(fields, "Optional JSON schema")
    expect(fields.get_by_label("Optional JSON schema", exact=True)).to_have_value("{")
    expect(fields.get_by_label("Decision field name", exact=True)).to_have_value("pending_choice")
    expect(fields.get_by_label("Decision field type", exact=True)).to_have_value("enum")
    expect(fields.get_by_label("Decision enum values", exact=True)).to_have_value("first\nsecond\n")
    switch_surface(editor, "List")
    fields = list_block(editor, "evaluate")
    open_details(fields)
    open_details(fields, "Optional JSON schema")
    expect(fields.get_by_label("Optional JSON schema", exact=True)).to_have_value("{")
    expect(fields.get_by_label("Decision enum values", exact=True)).to_have_value("first\nsecond\n")
    expect(fields.get_by_role("alert").filter(has_text="JSON schema must be valid JSON.")).to_be_visible()
    view = switch_surface(editor, "Flow")
    fields = select_node(view, "evaluate")
    open_details(fields)
    open_details(fields, "Optional JSON schema")
    fields.get_by_label("Optional JSON schema", exact=True).fill(
        '{"type":"object","properties":{"pass":{"type":"boolean"},"add_note":{"type":"boolean"}},"required":["pass","add_note"]}'
    )
    fields.get_by_role("button", name="Add decision field", exact=True).click()
    expect_compiled(view)
    payload = save(ui, editor)
    task = next(task for task in payload["tasks"] if task["id"] == "evaluate")
    assert task["output_contract"]["schema"]["properties"]["pending_choice"] == {
        "type": "string", "enum": ["first", "second"],
    }
    assert payload["definition_revision"] == original["definition_revision"]
    assert all(key not in payload for key in ("field_buffers", "schemaText", "positions", "selectedId"))


def test_query_tag_buffer_survives_node_and_surface_switch_without_source_preview(authoring_ui):
    ui = authoring_ui
    install_seed(ui)
    editor = open_editor(ui, AUTHORING_ID)
    view = switch_surface(editor, "Flow")
    loop_id, fields = add_block(view, "for_each")
    fields.get_by_label("For each source", exact=True).select_option("workspace_query")
    fields.get_by_label("Query tags", exact=True).fill("finance, quarterly, ")
    select_node(view, "seed")
    fields = select_node(view, loop_id)
    expect(fields.get_by_label("Query tags", exact=True)).to_have_value("finance, quarterly, ")
    switch_surface(editor, "List")
    expect(list_block(editor, loop_id).get_by_label("Query tags", exact=True)).to_have_value("finance, quarterly, ")
    view = switch_surface(editor, "Flow")
    fields = select_node(view, loop_id)
    expect(fields.get_by_label("Query tags", exact=True)).to_have_value("finance, quarterly, ")
    expect_compiled(view)
    payload = save(ui, editor)
    loop = payload["flow"]["nodes"][1]
    assert loop["iterable"]["filters"]["tags"] == ["finance", "quarterly"]
    assert not [request for request in ui.writes if request.path not in SAVE_PATHS | PREVIEW_PATHS]


def test_unfinished_field_builder_alone_participates_in_unsaved_change_protection(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    fields = select_node(view, "evaluate")
    open_details(fields)
    fields.get_by_label("Decision field name", exact=True).fill("unfinished")
    fields.get_by_label("Decision field type", exact=True).select_option("enum")
    fields.get_by_label("Decision enum values", exact=True).fill("one\none\n")
    switch_surface(editor, "List")
    editor.get_by_role("button", name="Close", exact=True).click()
    confirmation = page.get_by_role("dialog", name="Discard unsaved workflow changes?", exact=True)
    expect(confirmation).to_be_visible()
    confirmation.get_by_role("button", name="Keep editing", exact=True).click()
    view = switch_surface(editor, "Flow")
    fields = select_node(view, "evaluate")
    open_details(fields)
    expect(fields.get_by_label("Decision enum values", exact=True)).to_have_value("one\none\n")
    expect(fields.get_by_role("button", name="Add decision field", exact=True)).to_be_disabled()
    assert not ui.workflow_writes


@pytest.mark.parametrize("group", [False, True])
def test_delayed_preview_cannot_cross_closed_editor_workflow_or_group_scope(authoring_ui, group):
    ui, page = authoring_ui, authoring_ui.page
    if group:
        editor = open_editor(ui, group_id=GROUP_ID)
    else:
        install_seed(ui)
        editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    expect_compiled(view)
    fields = select_node(view, "evaluate")
    ui.hold_next_flow(source_kind="draft", group_id=GROUP_ID if group else None)
    with page.expect_request(lambda request: "/flow-preview" in request.url):
        fields.get_by_label("Task name", exact=True).fill("Old editor private draft")
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Validating draft\."))).to_be_visible()
    expect(view.locator(".workflow-flow-control-edge")).to_have_count(0)
    assert len(ui.held_flow_responses) == 1
    editor.get_by_role("button", name="Close", exact=True).click()
    page.get_by_role("dialog", name="Discard unsaved workflow changes?", exact=True).get_by_role(
        "button", name="Discard changes", exact=True,
    ).click()
    if group:
        page.get_by_label("Group workspace", exact=True).select_option(SECOND_GROUP_ID)
        page.get_by_role("button", name="Edit Beta read-only Flow", exact=True).click()
    else:
        page.get_by_role("button", name="Edit Authoring seed", exact=True).click()
    editor = page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(editor.get_by_role("button", name="List authoring", exact=True)).to_have_attribute("aria-pressed", "true")
    view = switch_surface(editor, "Flow")
    expect_compiled(view)
    expected_id, expected_name = ("evaluate", "Evaluate") if group else ("seed", "Seed decision")
    expect(node_button(view, expected_id)).to_have_accessible_name(f"Select {expected_name} (Task)")
    ui.release_flow_responses()
    page.wait_for_load_state("networkidle")
    expect(node_button(view, expected_id)).to_have_accessible_name(f"Select {expected_name} (Task)")
    expect(editor.get_by_text("Old editor private draft", exact=True)).to_have_count(0)
    editor.get_by_label("Workflow name", exact=True).fill("Only the current scope is saved")
    payload = save(ui, editor)
    if group:
        request = ui.workflow_writes[-1]
        assert request.path == "/api/group/workflows"
        assert request.query == {"group_id": [SECOND_GROUP_ID]}
        assert payload["group_id"] == SECOND_GROUP_ID
        assert all(request.query.get("group_id") in ([GROUP_ID], [SECOND_GROUP_ID]) for request in ui.preview_requests)
    else:
        assert payload["id"] == AUTHORING_ID
    assert not any(request.path == "/api/user/settings" and request.method != "GET" for request in ui.requests)


@pytest.mark.parametrize("status", [400, 409, 503])
def test_save_failures_retain_flow_fields_and_never_replace_the_original_cas_revision(authoring_ui, status):
    ui = authoring_ui
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    fields = select_node(view, "evaluate")
    fields.get_by_label("Task name", exact=True).fill("Retained after save failure")
    fields.get_by_label("Instructions", exact=True).fill("Retain this exact unsaved instruction.")
    expect_compiled(view)
    if status == 409:
        ui.mutate_revision(FLOW_WORKFLOW_ID)
    else:
        ui.reject_next("POST", "/api/user/workflows", status=status, error="Fictional authoring save was rejected.")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(editor.get_by_role("alert").first).to_be_visible()
    expect(fields.get_by_label("Task name", exact=True)).to_have_value("Retained after save failure")
    expect(fields.get_by_label("Instructions", exact=True)).to_have_value("Retain this exact unsaved instruction.")
    assert not ui.workflow_writes
    requests = [request for request in ui.writes if request.path in SAVE_PATHS]
    assert len(requests) == 1
    assert requests[0].body["definition_revision"] == original["definition_revision"]
    switch_surface(editor, "List")
    expect(list_block(editor, "evaluate").get_by_label("Task name", exact=True)).to_have_value("Retained after save failure")
    if status != 409:
        payload = save(ui, editor)
        assert payload["definition_revision"] == original["definition_revision"]
    else:
        expect(editor.get_by_role("alert").filter(has_text=re.compile("changed|reload|retained", re.I)).first).to_be_visible()
        assert ui.personal_workflows[FLOW_WORKFLOW_ID]["definition_revision"] != original["definition_revision"]


def test_pending_save_disables_semantic_edits_and_cannot_issue_a_second_write(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    fields = select_node(view, "evaluate")
    fields.get_by_label("Task name", exact=True).fill("One explicit save")
    ui.hold_save_response = True
    with page.expect_request(lambda request: urlsplit(request.url).path == "/api/user/workflows" and request.method == "POST"):
        editor.get_by_role("button", name="Save workflow", exact=True).click()
    try:
        expect(editor.get_by_role("button", name="Saving…", exact=True)).to_be_disabled()
        expect(fields.get_by_label("Task name", exact=True)).to_be_disabled()
        for name in ("Add block in Flow", "Move selected block", "Remove selected block"):
            expect(view.get_by_role("button", name=name, exact=True)).to_be_disabled()
        close = editor.get_by_role("button", name="Close", exact=True)
        if close.is_enabled():
            close.click()
        expect(page.get_by_role("dialog", name="Discard unsaved workflow changes?", exact=True)).to_have_count(0)
        expect(editor).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.get_by_role("dialog", name="Discard unsaved workflow changes?", exact=True)).to_have_count(0)
        expect(editor).to_be_visible()
        assert len([request for request in ui.writes if request.path in SAVE_PATHS]) == 1
    finally:
        ui.release_save_responses()
    expect(editor).to_have_count(0)
    assert len(ui.workflow_writes) == 1


def test_active_run_race_rejects_save_without_losing_the_authored_draft(authoring_ui):
    ui = authoring_ui
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    fields = select_node(view, "evaluate")
    fields.get_by_label("Instructions", exact=True).fill("Keep this draft when an active run wins the race.")
    expect_compiled(view)
    ui.personal_workflows[FLOW_WORKFLOW_ID].update(active_run_id=FLOW_RUN_ID, status="running")
    editor.get_by_role("button", name="Save workflow", exact=True).click()
    expect(editor.get_by_role("alert").filter(has_text=re.compile("active run|running|cancel or wait", re.I)).first).to_be_visible()
    expect(fields.get_by_label("Instructions", exact=True)).to_have_value("Keep this draft when an active run wins the race.")
    assert not ui.workflow_writes
    assert len([request for request in ui.writes if request.path in SAVE_PATHS]) == 1


def test_layout_selection_collapse_and_surface_switches_never_dirty_or_save(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    storage = page.evaluate("JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})")
    view = switch_surface(editor, "Flow")
    expect_compiled(view)
    select_node(view, "evaluate")
    requests = len(ui.preview_requests)
    wrapper = view.locator(".react-flow__node[data-id='evaluate']")
    before = wrapper.evaluate("element => getComputedStyle(element).transform")
    view.get_by_role("button", name="Move box right", exact=True).click()
    expect(wrapper).not_to_have_css("transform", before)
    for name in ("Move box down", "Zoom in", "Zoom out", "Fit Flow", "Reset layout"):
        view.get_by_role("button", name=name, exact=True).click()
    expect(wrapper).to_have_css("transform", before)
    view.get_by_role("button", name="Collapse If", exact=True).click()
    view.get_by_role("button", name="Expand If", exact=True).click()
    select_node(view, "finish")
    view.get_by_role("button", name="Configure selected block", exact=True).click()
    expect(configuration(view).get_by_label("Task name", exact=True)).to_be_focused()
    configuration(view).get_by_role("button", name="Return to selected block", exact=True).click()
    expect(node_button(view, "finish")).to_be_focused()
    assert len(ui.preview_requests) == requests
    switch_surface(editor, "List")
    view = switch_surface(editor, "Flow")
    expect(node_button(view, "finish")).to_have_attribute("aria-pressed", "true")
    editor.get_by_role("button", name="Close", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert not ui.workflow_writes
    assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original
    assert page.evaluate("JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})") == storage


@pytest.mark.browser_context_args(has_touch=True)
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_keyboard_add_move_remove_focus_and_scroll_zoom_remain_usable(authoring_ui, theme):
    ui, page = authoring_ui, authoring_ui.page
    page.emulate_media(reduced_motion="reduce")
    install_seed(ui)
    editor = open_editor(ui, AUTHORING_ID, width=390, height=844, theme=theme)
    ui.assert_no_overflow()
    view = switch_surface(editor, "Flow")
    node_id, fields = add_task(view, MALICIOUS_LABEL)
    expect(node_button(view, node_id)).to_have_accessible_name(f"Select {MALICIOUS_LABEL} (Task)")
    assert not page.evaluate("Boolean(window.flowLabelExecuted)")
    expect(view.locator("img[src='x']")).to_have_count(0)
    move_block(view, node_id, region_id="root", before_id="seed")
    expect(node_button(view, node_id)).to_be_focused()
    switch_surface(editor, "List")
    block = list_block(editor, node_id)
    assert block.evaluate("element => element === document.activeElement || element.contains(document.activeElement)")
    view = switch_surface(editor, "Flow")
    expect(node_button(view, node_id)).to_have_attribute("aria-pressed", "true")
    view.get_by_role("button", name="Configure selected block", exact=True).click()
    expect(configuration(view).get_by_label("Task name", exact=True)).to_be_focused()
    configuration(view).get_by_role("button", name="Return to selected block", exact=True).click()
    expect(node_button(view, node_id)).to_be_focused()
    for element in (view.locator(".workflow-flow-canvas"), view.locator(".react-flow__pane")):
        action = element.evaluate("element => getComputedStyle(element).touchAction")
        assert action == "manipulation" or {"pan-x", "pan-y", "pinch-zoom"} <= set(action.split())
    expect(view.locator(".react-flow__node.draggable")).to_have_count(0)
    pane = view.locator(".react-flow__pane")
    viewport = view.locator(".react-flow__viewport")
    expect(pane).not_to_have_class(re.compile(r"\bdraggable\b"))
    native_transform = viewport.evaluate("""async element => {
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        return getComputedStyle(element).transform;
    }""")
    assert pane.evaluate("""element => {
        const event = new WheelEvent('wheel', {deltaY: 100, ctrlKey: true, bubbles: true, cancelable: true});
        element.dispatchEvent(event);
        return !event.defaultPrevented;
    }""")
    expect(viewport).to_have_css("transform", native_transform)
    native_pinch = pane.evaluate("""async element => {
        const bounds = element.getBoundingClientRect();
        const centerX = bounds.left + bounds.width / 2;
        const centerY = bounds.top + bounds.height / 2;
        const touchesAt = distance => [-distance, distance].map((offset, index) => new Touch({
            identifier: index + 1, target: element,
            clientX: centerX + offset, clientY: centerY,
            pageX: centerX + offset + window.scrollX, pageY: centerY + window.scrollY,
            radiusX: 4, radiusY: 4, force: 0.5,
        }));
        const initialTouches = touchesAt(24);
        const start = new TouchEvent('touchstart', {
            touches: initialTouches, targetTouches: initialTouches, changedTouches: initialTouches,
            bubbles: true, cancelable: true,
        });
        element.dispatchEvent(start);
        await new Promise(resolve => requestAnimationFrame(resolve));
        const movedTouches = touchesAt(48);
        const move = new TouchEvent('touchmove', {
            touches: movedTouches, targetTouches: movedTouches, changedTouches: movedTouches,
            bubbles: true, cancelable: true,
        });
        element.dispatchEvent(move);
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        element.dispatchEvent(new TouchEvent('touchend', {
            touches: [], targetTouches: [], changedTouches: movedTouches,
            bubbles: true, cancelable: true,
        }));
        return {startPrevented: start.defaultPrevented, movePrevented: move.defaultPrevented};
    }""")
    assert native_pinch == {"startPrevented": False, "movePrevented": False}
    expect(viewport).to_have_css("transform", native_transform)
    canvas = view.locator(".workflow-flow-canvas")
    canvas.scroll_into_view_if_needed()
    scroll = canvas.evaluate("""element => {
        for (let parent = element.parentElement; parent; parent = parent.parentElement) {
            if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight + 1) {
                return {top: parent.scrollTop, delta: parent.scrollTop + parent.clientHeight < parent.scrollHeight - 1 ? 160 : -160};
            }
        }
        return null;
    }""")
    assert scroll, "The narrow editor must retain a scrollable container around the diagram."
    bounds = canvas.bounding_box()
    assert bounds
    page.mouse.move(bounds["x"] + bounds["width"] / 2, max(1, min(800, bounds["y"] + bounds["height"] / 2)))
    page.mouse.wheel(0, scroll["delta"])
    page.wait_for_function("""previous => {
        const element = document.querySelector('.workflow-flow-canvas');
        for (let parent = element?.parentElement; parent; parent = parent.parentElement) {
            if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY) && parent.scrollHeight > parent.clientHeight + 1) {
                return Math.abs(parent.scrollTop - previous) > 1;
            }
        }
        return false;
    }""", arg=scroll["top"])
    pan_transform = viewport.evaluate("element => getComputedStyle(element).transform")
    view.get_by_role("button", name="Pan view left", exact=True).click()
    expect(viewport).not_to_have_css("transform", pan_transform)
    view.get_by_role("button", name="Pan view right", exact=True).click()
    expect(viewport).to_have_css("transform", pan_transform)
    view.get_by_role("button", name="Zoom in", exact=True).click()
    expect(viewport).not_to_have_css("transform", pan_transform)
    zoomed_transform = viewport.evaluate("element => getComputedStyle(element).transform")
    view.get_by_role("button", name="Zoom out", exact=True).click()
    expect(viewport).not_to_have_css("transform", zoomed_transform)
    view.get_by_role("button", name="Fit Flow", exact=True).click()
    ui.assert_no_overflow()
    assert editor.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    view.get_by_role("button", name="Remove selected block", exact=True).focus()
    view.get_by_role("button", name="Remove selected block", exact=True).press("Enter")
    confirmation = page.get_by_role("dialog", name="Remove this flow block?", exact=True)
    confirmation.get_by_role("button", name="Remove block", exact=True).focus()
    confirmation.get_by_role("button", name="Remove block", exact=True).press("Enter")
    expect(node_button(view, node_id)).to_have_count(0)
    expect(node_button(view, "seed")).to_be_focused()
    expect(view.get_by_role("button", name="Remove selected block", exact=True)).to_be_disabled()
    ui.assert_no_overflow()
    assert not ui.workflow_writes


def test_task_limit_rejects_add_atomically_without_dirtying_the_draft(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    original = install_seed(ui)
    ui.max_tasks = 1
    editor = open_editor(ui, AUTHORING_ID)
    view = switch_surface(editor, "Flow")
    expect_compiled(view)
    before = view.locator("[data-workflow-node-id]").count()
    selection = selected_id(view)
    preview_count = len(ui.preview_requests)
    view.get_by_role("button", name="Add block in Flow", exact=True).click()
    placement = view.get_by_role("group", name="Add workflow block", exact=True)
    placement.get_by_label("Block kind", exact=True).select_option("task")
    placement.get_by_label("Destination region", exact=True).select_option("root")
    placement.get_by_role("button", name="Add block", exact=True).click()
    expect(editor.get_by_role("alert")).to_have_text("The edit exceeds the workspace task limit.")
    expect(placement).to_be_visible()
    expect(view.locator("[data-workflow-node-id]")).to_have_count(before)
    assert selected_id(view) == selection
    assert len(ui.preview_requests) == preview_count
    assert ui.personal_workflows[AUTHORING_ID] == original
    placement.get_by_role("button", name="Cancel block placement", exact=True).click()
    expect(placement).to_have_count(0)
    editor.get_by_role("button", name="Close", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert not ui.workflow_writes


@pytest.mark.parametrize("restriction", ["reader", "active_run", "unsupported"])
def test_read_only_access_boundaries_never_offer_flow_authoring(authoring_ui, restriction):
    ui, page = authoring_ui, authoring_ui.page
    if restriction == "reader":
        ui.group_can_manage = False
        ui.open("/groups")
        page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
        page.get_by_role("button", name="Edit Alpha read-only Flow", exact=True).click()
        reader = page.get_by_role("dialog", name="Edit workflow", exact=True)
        expect(reader).to_contain_text("This workflow is read-only.")
        expect(reader.get_by_label("Workflow name", exact=True)).to_be_disabled()
        for field in reader.get_by_label("Task name", exact=True).all():
            expect(field).to_be_disabled()
        expect(reader.get_by_role("button", name="Add task to Main", exact=True)).to_be_disabled()
        expect(reader.get_by_role("button", name="Remove Accept block", exact=True)).to_be_disabled()
        expect(reader.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
        expect(reader.get_by_role("group", name="Workflow authoring surface", exact=True)).to_have_count(0)
        reader.get_by_role("button", name="Close", exact=True).last.click()
        expect(reader).to_have_count(0)
        page.get_by_role("button", name="View Flow for Alpha read-only Flow", exact=True).click()
    elif restriction == "active_run":
        ui.personal_workflows[FLOW_WORKFLOW_ID].update(active_run_id=FLOW_RUN_ID, status="running")
        ui.open("/workspace/workflows")
        expect(page.get_by_role(
            "button", name=f"{FLOW_NAME} is running; cancel or wait before editing", exact=True,
        )).to_be_disabled()
        page.get_by_role("button", name=f"View Flow for {FLOW_NAME}", exact=True).click()
    else:
        ui.personal_workflows[FLOW_WORKFLOW_ID]["flow"]["nodes"][0]["future_executor"] = {"unchanged": True}
        ui.open(f"/workspace/workflows?workflow_id={FLOW_WORKFLOW_ID}")
        expect(page.get_by_role("alert").filter(has_text=re.compile("cannot safely save|unsupported", re.I)).first).to_be_visible()
        expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    expect(page.get_by_role("group", name="Workflow authoring surface", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Add block in Flow", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Move selected block", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Remove selected block", exact=True)).to_have_count(0)
    assert not ui.workflow_writes and not ui.preview_requests


@pytest.mark.parametrize("status", [401, 403, 404])
def test_authoring_source_access_loss_clears_projection_and_blocks_further_edits(authoring_ui, status):
    ui, page = authoring_ui, authoring_ui.page
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    expect_compiled(view)
    fields = select_node(view, "evaluate")
    ui.hold_next_flow(source_kind="draft")
    with page.expect_request(lambda request: request.url.endswith("/flow-preview")):
        fields.get_by_label("Task name", exact=True).fill("Protected pending draft")
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Validating draft\."))).to_be_visible()
    expect(view.locator(".workflow-flow-control-edge")).to_have_count(0)
    assert len(ui.held_flow_responses) == 1
    try:
        ui.reject_next("POST", "/api/user/workflows/flow-preview", status=status, error="Workflow source access is no longer available.")
        fields.get_by_label("Task name", exact=True).fill("Access check draft")
        expect(page.get_by_role("alert").filter(has_text=re.compile("access|available|permission|sign in", re.I)).first).to_be_visible()
        expect(page.locator("[data-workflow-node-id]")).to_have_count(0)
        expect(editor.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    finally:
        ui.release_flow_responses()
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-workflow-node-id]")).to_have_count(0)
    expect(editor.get_by_role("button", name="Add block in Flow", exact=True)).to_have_count(0)
    expect(page.get_by_text("Protected pending draft", exact=True)).to_have_count(0)
    assert not ui.workflow_writes


def test_saved_and_frozen_run_flow_remain_inspection_only_after_authoring_save(authoring_ui):
    ui, page = authoring_ui, authoring_ui.page
    key = ("user", FLOW_WORKFLOW_ID, FLOW_RUN_ID)
    frozen = copy.deepcopy(ui.flow_definitions[key])
    editor = open_editor(ui)
    view = switch_surface(editor, "Flow")
    select_node(view, "evaluate").get_by_label("Task name", exact=True).fill("Saved authored evaluation")
    save(ui, editor)
    page.get_by_role("button", name=f"View Flow for {FLOW_NAME}", exact=True).click()
    saved = page.get_by_role("dialog", name="Workflow Flow", exact=True)
    expect(saved.get_by_role("heading", name="Read-only Flow", exact=True)).to_be_visible()
    expect(node_button(saved, "evaluate")).to_have_accessible_name("Select Saved authored evaluation (Task)")
    expect(saved.get_by_role("button", name="Add block in Flow", exact=True)).to_have_count(0)
    expect(saved.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    saved.get_by_role("button", name="Close", exact=True).click()
    row = page.get_by_role("listitem").filter(has=page.get_by_role(
        "button", name=f"View Flow for {FLOW_NAME}", exact=True,
    )).first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    row.get_by_role("button", name="Show Flow for this run", exact=True).click()
    run = page.get_by_role("region", name="Workflow Flow", exact=True)
    expect(run.get_by_text("Run's frozen definition", exact=True)).to_be_visible()
    expect(node_button(run, "evaluate")).to_have_accessible_name("Select Frozen evaluation (Task)")
    expect(run.get_by_role("button", name="Add block in Flow", exact=True)).to_have_count(0)
    expect(run.get_by_role("group", name="Workflow authoring surface", exact=True)).to_have_count(0)
    assert ui.flow_definitions[key] == frozen
    projections = [payload for payload in ui.flow_payloads if payload["source"]["kind"] == "run"]
    assert projections
    assert projections[-1]["source"]["definition_revision"] == frozen["definition_revision"]
    assert len(ui.workflow_writes) == 1
