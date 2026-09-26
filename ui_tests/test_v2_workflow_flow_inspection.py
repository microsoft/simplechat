# test_v2_workflow_flow_inspection.py
"""
Offline browser regressions for approved M5A read-only workflow Flow inspection.
Version: 0.261.178
Implemented in: 0.261.121
Group saved Flow opens through the group route only: 0.261.178

Uses the real local SPA, compiler-derived projections and closed fictional APIs.
Run with PLAYWRIGHT_SERVICE_URL='' in this same pytest process. No live app,
Azure browser, workflow save/run, runtime decision or publication is permitted.
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

# Shared fixtures require their existing local import-path setup.
from ui_tests.fixtures.workflow_flow import (
    FLOW_NAME,
    FLOW_RUN_ID,
    FLOW_WORKFLOW_ID,
    GROUP_ID,
    MALICIOUS_LABEL,
    MIXED_NAME,
    MIXED_RUN_ID,
    MIXED_WORKFLOW_ID,
    SECOND_GROUP_ID,
    WORKFLOW_ID,
    connect_options,  # noqa: F401
    flow_binding,
    workflow_flow_ui,  # noqa: F401
)
from functions_workflow_definitions import workflow_definition_revision
from functions_workflow_identity import workflow_execution_id


pytestmark = pytest.mark.ui


def flow_region(page):
    return page.get_by_role("region", name="Workflow Flow", exact=True)


def node_button(view, node_id):
    return view.locator(f"button[data-workflow-node-id='{node_id}']")


def select_node(view, node_id):
    node = node_button(view, node_id)
    node.focus()
    node.press("Enter")
    expect(node).to_have_attribute("aria-pressed", "true")
    inspector = view.get_by_role("region", name="Flow node inspection", exact=True)
    expect(inspector).to_be_visible()
    expect(inspector.get_by_role("button", name="Refresh node details", exact=True)).to_be_enabled()
    return inspector


def open_saved(ui, name=FLOW_NAME, *, group_id=None, **options):
    ui.open("/groups" if group_id else "/workspace/workflows", **options)
    if group_id:
        ui.select_group(group_id)
    ui.page.get_by_role("button", name=f"View Flow for {name}", exact=True).click()
    expect(ui.page.get_by_role("dialog", name="Workflow Flow", exact=True)).to_be_visible()
    view = flow_region(ui.page)
    expect(view.get_by_role("heading", name="Read-only Flow", exact=True)).to_be_visible()
    expect(view.get_by_role("button", name="Refresh Flow", exact=True)).to_be_enabled()
    return view


def open_editor(ui, workflow_id=FLOW_WORKFLOW_ID, **options):
    ui.open(f"/workspace/workflows?workflow_id={workflow_id}", **options)
    editor = ui.page.get_by_role("dialog", name="Edit workflow", exact=True)
    expect(editor).to_be_visible()
    surface = editor.get_by_role("group", name="Workflow authoring surface", exact=True)
    expect(surface.get_by_role("button", name="List authoring", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(surface.get_by_role("button", name="Flow authoring", exact=True)).to_be_visible()
    assert not ui.preview_requests, "Flow preview must remain opt-in for existing List users."
    return editor


def show_preview(editor):
    editor.get_by_role("button", name="Flow authoring", exact=True).click()
    view = editor.get_by_role("region", name="Workflow Flow authoring", exact=True)
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Compiler-validated draft\."))).to_be_visible()
    expect(node_button(view, "root")).to_be_visible()
    return view


def select_authoring_node(view, node_id):
    node = node_button(view, node_id)
    node.focus()
    node.press("Enter")
    expect(node).to_have_attribute("aria-pressed", "true")
    fields = view.get_by_role("region", name="Selected block configuration", exact=True)
    expect(fields.get_by_text(f"Canonical ID: {node_id}", exact=True)).to_be_visible()
    return fields


def open_run_flow(ui, *, workflow_name=FLOW_NAME, workflow_id=FLOW_WORKFLOW_ID, run_id=FLOW_RUN_ID, group=False):
    ui.open("/groups" if group else "/workspace/workflows")
    if group:
        ui.select_group(GROUP_ID)
    row = ui.page.get_by_role("listitem").filter(has=ui.page.get_by_role(
        "button", name=f"View Flow for {workflow_name}", exact=True,
    )).first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    expect(row.get_by_role("list", name="Workflow node executions", exact=True)).to_be_visible()
    before = len([entry for entry in ui.requests if entry.path.endswith("/executions")])
    row.get_by_role("button", name="Show Flow for this run", exact=True).click()
    view = flow_region(ui.page)
    expect(view.get_by_text("Run's frozen definition", exact=True)).to_be_visible()
    expect(view.get_by_role("button", name="Refresh Flow", exact=True)).to_be_enabled()
    expect(view.get_by_text("Loading bounded execution overlay...", exact=True)).to_have_count(0)
    expect(row.get_by_role("list", name="Workflow node executions", exact=True)).to_have_count(0)
    pages = [entry for entry in ui.requests if entry.path.endswith("/executions")][before:]
    assert len(pages) == 1 and pages[0].query == {
        "limit": ["50"], **({"group_id": [GROUP_ID]} if group else {}),
    }, pages
    assert pages[0].path == f"/api/{'group' if group else 'user'}/workflows/{workflow_id}/runs/{run_id}/executions"
    return view


def close_saved(page):
    page.get_by_role("dialog", name="Workflow Flow", exact=True).get_by_role("button", name="Close", exact=True).click()
    expect(page.get_by_role("dialog", name="Workflow Flow", exact=True)).to_have_count(0)


def assert_no_eager_content(ui):
    assert not ui.evidence_requests, ui.evidence_requests
    assert not ui.detail_requests, ui.detail_requests
    assert not ui.exact_requests, ui.exact_requests


def test_saved_topology_uses_canonical_control_boundaries_and_lazy_typed_bindings(workflow_flow_ui):
    ui = workflow_flow_ui
    view = open_saved(ui)
    expect(view.get_by_text("Saved definition", exact=True)).to_be_visible()
    expected = ui.inspection.workflow_flow_inspection(ui.personal_workflows[FLOW_WORKFLOW_ID])
    expect(view.locator("[data-workflow-node-id]")).to_have_count(len(expected["nodes"]))
    assert_no_eager_content(ui)
    assert len(ui.topology_requests) == 1
    topology = next(payload for payload in ui.flow_payloads if "nodes" in payload)
    assert all(field not in json.dumps(topology) for field in ("LIVE_ONLY_INSTRUCTIONS", "output_contract", "selected_agent"))
    for node_id, name in (
        ("root", "Select Workflow (Region)"), ("choose", "Select If (If / else)"),
        ("decision-join", "Select Join (Join)"), ("bypass-note", "Select Route (Forward route)"),
        ("accepted-path", "Select Then (Region)"), ("review-path", "Select Else (Region)"),
    ):
        expect(node_button(view, node_id)).to_have_accessible_name(name)
    expect(view).to_contain_text("Solid arrows show control flow")
    expect(view).to_contain_text("Dashed arrows show only the selected page of typed bindings")
    expect(view.locator(".workflow-flow-data-edge")).to_have_count(0)

    inspector = select_node(view, "bypass-note")
    inspector.get_by_text(re.compile(r"^Control-flow relationships \(")).click()
    relationships = inspector.get_by_role("list", name="Control-flow relationships", exact=True)
    expect(relationships).to_contain_text("True: route forward")
    expect(relationships).to_contain_text("False: Next")
    inspector = select_node(view, "note")
    inspector.get_by_label("Inspection section", exact=True).select_option("condition")
    expect(inspector).to_contain_text("decision.add_note equals true")
    inspector = select_node(view, "finish")
    inspector.get_by_label("Inspection section", exact=True).select_option("inputs")
    expect(inspector).to_contain_text("Showing 2 of 2 typed inputs entries")
    expect(inspector).to_contain_text("report: text. Required.")
    expect(inspector).to_contain_text("note: text. Optional.")
    expect(view.locator(".workflow-flow-data-edge")).to_have_count(2)
    assert view.locator(".workflow-flow-data-edge path").first.evaluate(
        "element => getComputedStyle(element).strokeDasharray"
    ) != "none"
    assert ui.detail_requests[-1].query == {
        "node_id": ["finish"], "section": ["inputs"],
        "revision": [topology["source"]["definition_revision"]], "limit": ["50"],
    }
    inspector.get_by_role("button", name="Inspect producer decision-join", exact=True).click()
    expect(node_button(view, "decision-join")).to_have_attribute("aria-pressed", "true")
    inspector = select_node(view, "root")
    inspector.get_by_label("Inspection section", exact=True).select_option("outputs")
    expect(inspector.get_by_role("button", name="Inspect producer finish", exact=True)).to_be_visible()
    assert not ui.evidence_requests


def test_nested_condition_summary_preserves_grouping_and_exact_normalized_data(workflow_flow_ui):
    ui = workflow_flow_ui
    definition = ui.personal_workflows[FLOW_WORKFLOW_ID]
    branch = next(node for node in definition["flow"]["nodes"] if node["id"] == "choose")
    branch["condition"] = {
        "op": "all", "conditions": [
            {"op": "any", "conditions": [
                {"op": "eq", "left": {"input": "decision", "path": "/pass"}, "right": {"literal": True}},
                {"op": "eq", "left": {"input": "decision", "path": "/add_note"}, "right": {"literal": True}},
            ]},
            {"op": "not", "condition": {
                "op": "eq", "left": {"input": "decision", "path": "/pass"}, "right": {"literal": False},
            }},
        ],
    }
    definition["definition_revision"] = workflow_definition_revision(definition)
    original = copy.deepcopy(definition)
    view = open_saved(ui)
    inspector = select_node(view, "choose")
    inspector.get_by_label("Inspection section", exact=True).select_option("condition")
    expect(inspector).to_contain_text(
        "(decision.pass equals true OR decision.add_note equals true) AND NOT (decision.pass equals false)"
    )
    disclosure = inspector.locator("details").filter(
        has=ui.page.get_by_text("Exact normalized condition", exact=True),
    )
    expect(disclosure.locator("pre")).to_be_hidden()
    disclosure.get_by_text("Exact normalized condition", exact=True).click()
    expect(disclosure.locator("pre")).to_be_visible()
    expected = ui.inspection.workflow_flow_inspection(
        definition, node_id="choose", section="condition", revision=definition["definition_revision"], limit=50,
    )["items"][0]["value"]
    assert json.loads(disclosure.locator("pre").inner_text()) == expected
    assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original
    assert not ui.exact_requests and not ui.evidence_requests


def test_v1_v2_have_no_implicit_flow_conversion_or_preview_request(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    original = copy.deepcopy({key: ui.personal_workflows[key] for key in (WORKFLOW_ID, ui.legacy_workflow["id"])})
    ui.open("/workspace/workflows")
    for name in ("Quarterly review workflow", "Legacy version one"):
        expect(page.get_by_role("button", name=f"View Flow for {name}", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Edit Quarterly review workflow", exact=True).click()
    expect(page.get_by_role("button", name="Flow authoring", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Enable structured control flow", exact=True)).to_be_visible()
    page.get_by_role("dialog", name="Edit workflow", exact=True).get_by_role("button", name="Close", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert not ui.topology_requests and not ui.preview_requests
    assert {key: ui.personal_workflows[key] for key in original} == original


def test_group_saved_flow_uses_group_route_and_read_only_dialog(workflow_flow_ui):
    ui = workflow_flow_ui
    view = open_saved(ui, name="Alpha read-only Flow", group_id=GROUP_ID)
    expect(view.get_by_text("Saved definition", exact=True)).to_be_visible()
    expect(view.get_by_role("button", name="Add block in Flow", exact=True)).to_have_count(0)
    expect(view.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    group_flow_reads = [
        entry for entry in ui.requests
        if entry.method == "GET" and entry.path == f"/api/group/workflows/{FLOW_WORKFLOW_ID}/flow"
    ]
    assert len(group_flow_reads) == 1
    assert group_flow_reads[0].query == {"group_id": [GROUP_ID]}
    assert not [
        entry for entry in ui.requests
        if entry.path.startswith("/api/user/workflows")
    ], "A group Flow view must not read personal workflow routes."
    ui.assert_read_only()


def test_saved_flow_is_available_while_editing_is_disabled_by_an_active_run(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    record = ui.personal_workflows[FLOW_WORKFLOW_ID]
    record.update(active_run_id=FLOW_RUN_ID, status="running")
    view = open_saved(ui)
    expect(node_button(view, "evaluate")).to_be_visible()
    expect(view.get_by_role("button", name=re.compile(r"^(Save|Run|Approve|Retry|Resume|Publish|Continue Repeat)$"))).to_have_count(0)
    close_saved(page)
    expect(page.get_by_role(
        "button", name=f"{FLOW_NAME} is running; cancel or wait before editing", exact=True,
    )).to_be_disabled()
    ui.assert_read_only()


@pytest.mark.parametrize(("width", "node_id"), [(1440, "root"), (390, "evaluate")])
def test_non_draggable_canvas_nodes_remain_pointer_selectable(workflow_flow_ui, width, node_id):
    ui = workflow_flow_ui
    view = open_saved(ui, width=width, height=844)
    if width < 640:
        view.get_by_role("button", name="Flow diagram", exact=True).click()
    node = node_button(view, node_id)
    node.click(timeout=5000)
    expect(node).to_have_attribute("aria-pressed", "true")
    expect(view.get_by_role("region", name="Flow node inspection", exact=True)).to_be_visible()
    assert not ui.exact_requests and not ui.evidence_requests


def test_constructor_id_has_finite_resettable_temporary_positions(workflow_flow_ui):
    ui = workflow_flow_ui
    definition = ui.personal_workflows[FLOW_WORKFLOW_ID]
    definition["flow"]["nodes"][0]["id"] = "constructor"
    for owner in [*definition["flow"]["nodes"], *definition["tasks"]]:
        for binding in owner.get("inputs", []):
            if binding["source"].get("node_id") == "evaluate":
                binding["source"]["node_id"] = "constructor"
    definition["definition_revision"] = workflow_definition_revision(definition)
    original = copy.deepcopy(definition)
    view = open_saved(ui)
    expect(node_button(view, "constructor")).to_have_accessible_name("Select Later live evaluation (Task)")
    select_node(view, "constructor")
    assert ui.detail_requests[-1].query["node_id"] == ["constructor"]
    wrapper = view.locator(".react-flow__node[data-id='constructor']")
    assert wrapper.evaluate("""element => {
        const matrix = new DOMMatrixReadOnly(getComputedStyle(element).transform);
        return Number.isFinite(matrix.m41) && Number.isFinite(matrix.m42);
    }""")
    original_transform = wrapper.evaluate("element => getComputedStyle(element).transform")
    view.get_by_role("button", name="Move box right", exact=True).click()
    expect(wrapper).not_to_have_css("transform", original_transform)
    view.get_by_role("button", name="Reset layout", exact=True).click()
    expect(wrapper).to_have_css("transform", original_transform)
    expect(view.get_by_role("alert")).to_have_count(0)
    assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original


@pytest.mark.browser_context_args(has_touch=True)
def test_coarse_pointer_diagram_uses_explicit_pan_without_capturing_browser_gestures(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    view = open_saved(ui, width=1024, height=900)
    assert page.evaluate("matchMedia('(pointer: coarse)').matches")
    canvas = view.locator(".workflow-flow-canvas")
    expect(canvas).to_be_visible()
    expect(view.locator(".react-flow__node.draggable")).to_have_count(0)
    expect(view.locator(".react-flow__pane")).not_to_have_class(re.compile(r"\bdraggable\b"))
    for element in (canvas, view.locator(".react-flow__pane")):
        action = element.evaluate("element => getComputedStyle(element).touchAction")
        assert action == "manipulation" or {"pan-x", "pan-y", "pinch-zoom"} <= set(action.split())
    viewport = view.locator(".react-flow__viewport")
    original = viewport.evaluate("element => getComputedStyle(element).transform")
    view.get_by_role("button", name="Pan view left", exact=True).click()
    expect(viewport).not_to_have_css("transform", original)
    view.get_by_role("button", name="Pan view right", exact=True).click()
    expect(viewport).to_have_css("transform", original)
    view.get_by_role("button", name="Pan view up", exact=True).click()
    expect(viewport).not_to_have_css("transform", original)
    view.get_by_role("button", name="Pan view down", exact=True).click()
    expect(viewport).to_have_css("transform", original)
    assert_no_eager_content(ui)
    ui.assert_no_overflow()


def test_layout_collapse_and_keyboard_focus_do_not_change_definition_revision_or_storage(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    original = copy.deepcopy(ui.personal_workflows[MIXED_WORKFLOW_ID])
    view = open_saved(ui, MIXED_NAME)
    storage = page.evaluate("JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})")
    expect(node_button(view, "loop-0")).to_be_visible()
    expect(node_button(view, "loop-1")).to_have_count(0)
    view.get_by_role("button", name="Expand Repeat until", exact=True).click()
    expect(node_button(view, "loop-1")).to_have_count(1)
    select_node(view, "loop-1")
    for name in ("Zoom in", "Zoom out", "Fit Flow", "Move box right", "Move box down", "Reset layout"):
        view.get_by_role("button", name=name, exact=True).click()
    node_button(view, "loop-1").focus()
    node_button(view, "loop-1").press("Delete")
    expect(node_button(view, "loop-1")).to_have_count(1)
    view.get_by_role("button", name="Collapse Repeat until", exact=True).click()
    expect(node_button(view, "loop-1")).to_have_count(0)
    expect(node_button(view, "loop-0")).to_have_attribute("aria-pressed", "true")
    expect(node_button(view, "loop-0")).to_be_focused()
    assert page.evaluate("JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})") == storage
    assert ui.personal_workflows[MIXED_WORKFLOW_ID] == original
    assert workflow_definition_revision(ui.personal_workflows[MIXED_WORKFLOW_ID]) == original["definition_revision"]
    close_saved(page)
    expect(page.get_by_role("dialog")).to_have_count(0)


def test_list_flow_authoring_updates_without_save_or_cas_changes_and_uses_desktop_columns(workflow_flow_ui):
    ui = workflow_flow_ui
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    view = show_preview(editor)
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Later live evaluation (Task)")
    select_authoring_node(view, "evaluate")
    wrapper = view.locator(".react-flow__node[data-id='evaluate']")
    original_transform = wrapper.evaluate("element => getComputedStyle(element).transform")
    requests_before_move = len(ui.preview_requests)
    view.get_by_role("button", name="Move box right", exact=True).click()
    expect(wrapper).not_to_have_css("transform", original_transform)
    moved_transform = wrapper.evaluate("element => getComputedStyle(element).transform")
    assert len(ui.preview_requests) == requests_before_move
    editor.get_by_role("button", name="List authoring", exact=True).click()
    task = editor.get_by_role("region", name="Later live evaluation block", exact=True)
    task.get_by_label("Task name", exact=True).fill("Edited only in List")
    view = show_preview(editor)
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Edited only in List (Task)")
    expect(wrapper).to_have_css("transform", moved_transform)
    assert ui.preview_requests[-1].body["definition"]["definition_revision"] == original["definition_revision"]
    assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original
    assert not ui.workflow_writes
    flow_box = view.locator(".workflow-flow-canvas").bounding_box()
    fields_box = view.get_by_role("region", name="Selected block configuration", exact=True).bounding_box()
    assert flow_box and fields_box and flow_box["x"] + flow_box["width"] <= fields_box["x"] + 1
    expect(editor.get_by_role("button", name="List authoring", exact=True)).to_be_visible()


def test_opening_and_layout_of_unchanged_preview_does_not_make_editor_dirty(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    view = show_preview(editor)
    for name in ("Zoom in", "Zoom out", "Fit Flow", "Reset layout"):
        view.get_by_role("button", name=name, exact=True).click()
    editor.get_by_role("button", name="List authoring", exact=True).click()
    expect(editor.get_by_role("region", name="Workflow Flow authoring", exact=True)).to_have_count(0)
    editor.get_by_role("button", name="Close", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original


def test_invalid_authoring_draft_retains_blocks_without_stale_control_paths(workflow_flow_ui):
    ui = workflow_flow_ui
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    editor = open_editor(ui)
    view = show_preview(editor)
    expect(node_button(view, "evaluate")).to_have_count(1)
    instructions = select_authoring_node(view, "evaluate").get_by_label("Instructions", exact=True)
    instructions.fill("")
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Unvalidated draft\."))).to_be_visible()
    expect(editor.get_by_role("status").filter(
        has_text="Resolve these validation issues before saving:",
    )).to_contain_text("Later live evaluation needs instructions.")
    expect(node_button(view, "evaluate")).to_have_count(1)
    expect(view.locator(".workflow-flow-control-edge")).to_have_count(0)
    expect(instructions).to_have_value("")
    assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original
    instructions.fill("A repaired but still unsaved instruction.")
    expect(node_button(view, "evaluate")).to_have_count(1)
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Compiler-validated draft\."))).to_be_visible()
    expect(editor.get_by_role("status").filter(has_text="needs instructions.")).to_have_count(0)
    expect(view.get_by_role("alert")).to_have_count(0)
    assert ui.preview_requests[-1].body["definition"]["definition_revision"] == original["definition_revision"]


def test_delayed_draft_projection_cannot_replace_a_newer_list_edit(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    editor = open_editor(ui)
    view = show_preview(editor)
    fields = select_authoring_node(view, "evaluate")
    ui.hold_next_flow(source_kind="draft")
    with page.expect_request(lambda request: request.url.endswith("/flow-preview")):
        fields.get_by_label("Task name", exact=True).fill("Older queued draft")
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Validating draft\."))).to_be_visible()
    expect(view.locator(".workflow-flow-control-edge")).to_have_count(0)
    fields.get_by_label("Task name", exact=True).fill("Newest retained draft")
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Newest retained draft (Task)")
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Compiler-validated draft\."))).to_be_visible()
    assert len(ui.held_flow_responses) == 1
    ui.release_flow_responses()
    page.wait_for_load_state("networkidle")
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Newest retained draft (Task)")
    expect(view.get_by_text("Older queued draft", exact=True)).to_have_count(0)


def test_delayed_valid_preview_cannot_resurrect_a_graph_for_an_invalid_draft(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    editor = open_editor(ui)
    view = show_preview(editor)
    fields = select_authoring_node(view, "evaluate")
    ui.hold_next_flow(source_kind="draft")
    with page.expect_request(lambda request: request.url.endswith("/flow-preview")):
        fields.get_by_label("Task name", exact=True).fill("Pending valid draft")
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Validating draft\."))).to_be_visible()
    expect(view.locator(".workflow-flow-control-edge")).to_have_count(0)
    instructions = fields.get_by_label("Instructions", exact=True)
    instructions.fill("")
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Unvalidated draft\."))).to_be_visible()
    expect(editor.get_by_role("status").filter(
        has_text="Resolve these validation issues before saving:",
    )).to_contain_text("Pending valid draft needs instructions.")
    expect(node_button(view, "evaluate")).to_have_count(1)
    expect(view.locator(".workflow-flow-control-edge")).to_have_count(0)
    assert len(ui.held_flow_responses) == 1
    ui.release_flow_responses()
    page.wait_for_load_state("networkidle")
    expect(view.get_by_role("status").filter(has_text=re.compile(r"^Unvalidated draft\."))).to_be_visible()
    expect(editor.get_by_role("status").filter(
        has_text="Resolve these validation issues before saving:",
    )).to_contain_text("Pending valid draft needs instructions.")
    expect(node_button(view, "evaluate")).to_have_count(1)
    expect(view.locator(".workflow-flow-control-edge")).to_have_count(0)
    expect(instructions).to_have_value("")


def test_delayed_node_details_cannot_replace_a_new_selection(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    view = open_saved(ui)
    ui.hold_next_flow(source_kind="saved", node_id="evaluate")
    node_button(view, "evaluate").focus()
    node_button(view, "evaluate").press("Enter")
    inspector = view.get_by_role("region", name="Flow node inspection", exact=True)
    expect(inspector.get_by_text("Loading selected configuration...", exact=True)).to_be_visible()
    inspector = select_node(view, "finish")
    expect(inspector.get_by_role("heading", name="Finish", exact=True)).to_be_visible()
    expect(inspector).to_contain_text("Produce the finish result.")
    assert len(ui.held_flow_responses) == 1
    ui.release_flow_responses()
    page.wait_for_load_state("networkidle")
    expect(node_button(view, "finish")).to_have_attribute("aria-pressed", "true")
    expect(inspector).to_contain_text("Produce the finish result.")
    expect(inspector).not_to_contain_text("LIVE_ONLY_INSTRUCTIONS")


def test_changed_saved_revision_clears_stale_inspection_before_explicit_refresh(workflow_flow_ui):
    ui = workflow_flow_ui
    view = open_saved(ui)
    inspector = select_node(view, "evaluate")
    original_revision = ui.detail_requests[-1].query["revision"][0]
    definition = ui.personal_workflows[FLOW_WORKFLOW_ID]
    task = next(task for task in definition["tasks"] if task["id"] == "evaluate")
    task.update(name="Saved replacement evaluation", instructions="NEW_SAVED_INSTRUCTIONS")
    definition["definition_revision"] = workflow_definition_revision(definition)
    assert definition["definition_revision"] != original_revision
    inspector.get_by_role("button", name="Refresh node details", exact=True).click()
    expect(view.get_by_role("alert")).to_contain_text("source changed")
    expect(view.locator("[data-workflow-node-id]")).to_have_count(0)
    expect(view.get_by_role("region", name="Flow node inspection", exact=True)).to_have_count(0)
    expect(view.get_by_text("NEW_SAVED_INSTRUCTIONS", exact=True)).to_have_count(0)
    assert ui.detail_requests[-1].query["revision"] == [original_revision]
    view.get_by_role("button", name="Refresh Flow", exact=True).click()
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Saved replacement evaluation (Task)")
    expect(view).to_contain_text(definition["definition_revision"])
    select_node(view, "evaluate")
    assert ui.detail_requests[-1].query["revision"] == [definition["definition_revision"]]


def test_run_uses_frozen_revision_with_reused_live_ids_and_truthful_unknown_status(workflow_flow_ui):
    ui = workflow_flow_ui
    view = open_run_flow(ui)
    frozen = ui.flow_definitions[("user", FLOW_WORKFLOW_ID, FLOW_RUN_ID)]
    expect(view).to_contain_text(frozen["definition_revision"])
    expect(view).to_contain_text(FLOW_RUN_ID)
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Frozen evaluation (Task)")
    expect(node_button(view, "finish")).to_contain_text("Not loaded")
    expect(view.get_by_text("Later live evaluation", exact=True)).to_have_count(0)
    assert_no_eager_content(ui)
    inspector = select_node(view, "evaluate")
    expect(inspector).to_contain_text("FROZEN_INSTRUCTIONS")
    expect(inspector).not_to_contain_text("LIVE_ONLY_INSTRUCTIONS")
    exact_id = workflow_execution_id(frozen, FLOW_RUN_ID, "evaluate", [])
    expect(inspector.get_by_role("list", name=f"Attempts for execution {exact_id}", exact=True)).to_contain_text("Attempt 2")
    assert exact_id != workflow_execution_id(ui.personal_workflows[FLOW_WORKFLOW_ID], FLOW_RUN_ID, "evaluate", [])
    assert ui.exact_requests[-1].query == {"node_id": ["evaluate"], "iteration_path": ["[]"], "limit": ["1"]}
    assert ui.detail_requests[-1].query["revision"] == [frozen["definition_revision"]]
    assert not any(entry.path.endswith(("/result", "/records", "/iterations", "/state")) for entry in ui.requests)
    inspector = select_node(view, "finish")
    expect(inspector).to_contain_text("No execution recorded for this node in the selected instance")
    expect(inspector).to_contain_text("not a successful or empty result")
    expect(inspector).to_contain_text("Produce the finish result.")
    expect(inspector.get_by_role("list", name=re.compile("^Attempts for execution "))).to_have_count(0)
    expect(view.get_by_role("alert")).to_have_count(0)
    expect(node_button(view, "finish")).to_contain_text("No execution recorded")
    expect(node_button(view, "finish")).not_to_contain_text("completed")
    assert ui.exact_requests[-1].query == {"node_id": ["finish"], "iteration_path": ["[]"], "limit": ["1"]}


@pytest.mark.parametrize("region_id", ["accepted-path", "review-path"], ids=["then", "else"])
def test_frozen_branch_regions_inspect_configuration_without_execution_lookups(workflow_flow_ui, region_id):
    ui = workflow_flow_ui
    key = ("user", FLOW_WORKFLOW_ID, FLOW_RUN_ID)
    with pytest.raises(AssertionError, match="no execution identity"):
        ui._add_execution(key, region_id, [])
    with pytest.raises(AssertionError, match="no execution identity"):
        ui.execution_for(FLOW_WORKFLOW_ID, FLOW_RUN_ID, region_id, [])
    view = open_run_flow(ui)
    inspector = select_node(view, region_id)
    expect(node_button(view, region_id)).to_contain_text("Region grouping; no separate execution")
    expect(inspector).to_contain_text("This region groups nodes; it has no separate execution record.")
    expect(inspector.get_by_role("button", name="Refresh selected execution", exact=True)).to_have_count(0)
    expect(inspector.get_by_role("list", name=re.compile("^Attempts for execution "))).to_have_count(0)
    assert not ui.exact_requests and not ui.evidence_requests
    assert ui.detail_requests[-1].query == {
        "node_id": [region_id], "section": ["configuration"],
        "revision": [ui.flow_definitions[key]["definition_revision"]], "limit": ["50"],
    }

    inspector.get_by_role("button", name="Inspect enclosing control If", exact=True).click()
    expect(node_button(view, "choose")).to_have_attribute("aria-pressed", "true")
    expect(inspector).to_contain_text("No execution recorded for this node in the selected instance")
    assert len(ui.exact_requests) == 1
    assert ui.exact_requests[0].query == {"node_id": ["choose"], "iteration_path": ["[]"], "limit": ["1"]}
    assert not ui.evidence_requests


@pytest.mark.parametrize("group", [False, True], ids=["personal", "group"])
def test_frozen_root_keeps_its_real_engine_execution(workflow_flow_ui, group):
    ui = workflow_flow_ui
    scope = "group" if group else "user"
    key = (scope, FLOW_WORKFLOW_ID, FLOW_RUN_ID)
    execution = ui._add_execution(key, "root", [])
    assert execution["node_kind"] == "root" and execution["region_id"] == "root"
    view = open_run_flow(ui, workflow_name="Alpha read-only Flow" if group else FLOW_NAME, group=group)
    inspector = select_node(view, "root")
    expect(inspector.get_by_role(
        "list", name=f"Attempts for execution {execution['execution_id']}", exact=True,
    )).to_contain_text("Attempt 1")
    expect(node_button(view, "root")).to_contain_text("completed; attempt 1")
    expect(inspector.get_by_role("button", name="Refresh selected execution", exact=True)).to_be_visible()
    expect(inspector).not_to_contain_text("This region groups nodes")
    assert len(ui.exact_requests) == 1
    assert ui.exact_requests[0].query == {
        "node_id": ["root"], "iteration_path": ["[]"], "limit": ["1"],
        **({"group_id": [GROUP_ID]} if group else {}),
    }
    assert [entry.path for entry in ui.evidence_requests] == [
        f"/api/{scope}/workflows/{FLOW_WORKFLOW_ID}/runs/{FLOW_RUN_ID}"
        f"/executions/{execution['execution_id']}/attempts",
    ]


def test_execution_overlay_pages_replace_old_evidence_without_auto_draining(workflow_flow_ui):
    ui = workflow_flow_ui
    view = open_run_flow(ui)
    expect(node_button(view, "evaluate")).to_contain_text("completed; attempt 2")
    expect(node_button(view, "review")).to_contain_text("Not loaded")
    count = len([entry for entry in ui.requests if entry.path.endswith("/executions")])
    view.get_by_role("button", name="Next execution overlay page", exact=True).click()
    expect(node_button(view, "review")).to_contain_text("skipped; attempt 0")
    expect(node_button(view, "evaluate")).to_contain_text("Not loaded")
    expect(view.get_by_role("button", name="Next execution overlay page", exact=True)).to_be_disabled()
    pages = [entry for entry in ui.requests if entry.path.endswith("/executions")][count:]
    assert len(pages) == 1 and pages[0].query == {
        "limit": ["50"], "cursor": ["later-unloaded-executions"],
    }
    assert_no_eager_content(ui)
    view.get_by_role("button", name="Previous execution overlay page", exact=True).click()
    expect(node_button(view, "evaluate")).to_contain_text("completed; attempt 2")
    expect(node_button(view, "review")).to_contain_text("Not loaded")
    assert_no_eager_content(ui)


def test_delayed_exact_lookup_cannot_attach_to_a_different_selected_node(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    view = open_run_flow(ui)
    path = f"/api/user/workflows/{FLOW_WORKFLOW_ID}/runs/{FLOW_RUN_ID}/executions"
    ui.hold_next_read(path, query={"node_id": ["evaluate"], "iteration_path": ["[]"]})
    select_node(view, "evaluate")
    expect(view.get_by_text("Reading exact execution...", exact=True)).to_be_visible()
    inspector = select_node(view, "finish")
    expect(inspector).to_contain_text("No execution recorded for this node")
    assert len(ui.held_flow_responses) == 1
    ui.release_flow_responses()
    page.wait_for_load_state("networkidle")
    expect(node_button(view, "finish")).to_have_attribute("aria-pressed", "true")
    expect(inspector).to_contain_text("No execution recorded for this node")
    expect(inspector.get_by_role("list", name=re.compile("^Attempts for execution "))).to_have_count(0)
    assert not any(entry.path.endswith("/attempts") for entry in ui.requests)


@pytest.mark.parametrize("status", [403, 404])
def test_access_loss_cannot_be_reversed_by_an_older_overlay_response(workflow_flow_ui, status):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    view = open_run_flow(ui)
    inspector = select_node(view, "evaluate")
    path = f"/api/user/workflows/{FLOW_WORKFLOW_ID}/runs/{FLOW_RUN_ID}"
    ui.hold_next_read(f"{path}/executions", query={"cursor": ["later-unloaded-executions"]})
    view.get_by_role("button", name="Next execution overlay page", exact=True).click()
    expect(view.get_by_text("Loading bounded execution overlay...", exact=True)).to_be_visible()
    ui.reject_next("GET", f"{path}/flow", status=status, error="The fictional source is no longer readable.")
    inspector.get_by_role("button", name="Refresh node details", exact=True).click()
    expect(page.locator("[data-workflow-node-id]")).to_have_count(0)
    assert len(ui.held_flow_responses) == 1
    ui.release_flow_responses()
    page.wait_for_load_state("networkidle")
    expect(page.locator("[data-workflow-node-id]")).to_have_count(0)
    expect(page.get_by_role("region", name="Flow node inspection", exact=True)).to_have_count(0)
    expect(page.get_by_role("list", name=re.compile("^Attempts for execution "))).to_have_count(0)
    expect(page.get_by_role("alert").filter(has_text=re.compile("access|available|readable", re.I)).first).to_be_visible()


@pytest.mark.parametrize("kinds", [
    ("repeat_until", "for_each", "repeat_until"),
    ("for_each", "repeat_until", "for_each"),
])
@pytest.mark.parametrize("reorder_frame_keys", [False, True], ids=["original-keys", "reordered-keys"])
def test_nested_instances_keep_exact_mixed_path_lifetime_round_and_attempt_requests(
    workflow_flow_ui, kinds, reorder_frame_keys,
):
    ui = workflow_flow_ui
    ui.seed_mixed(kinds)
    if reorder_frame_keys:
        for key, execution in ui.exact_executions.items():
            if key[:3] == ("user", MIXED_WORKFLOW_ID, MIXED_RUN_ID):
                execution["iteration_path"] = [dict(reversed(list(frame.items()))) for frame in execution["iteration_path"]]
    view = open_run_flow(ui, workflow_name=MIXED_NAME, workflow_id=MIXED_WORKFLOW_ID, run_id=MIXED_RUN_ID)
    assert_no_eager_content(ui)
    assert view.locator("[data-workflow-node-id]").count() <= 5
    for index, kind in enumerate(kinds):
        inspector = select_node(view, f"loop-{index}")
        frame = ui.mixed_frames[index]
        name = f"Use round {frame['iteration'] + 1} in Flow" if kind == "repeat_until" else f"Use item {frame['index'] + 1} in Flow"
        expect(inspector.get_by_role("button", name=name, exact=True)).to_be_visible()
        latest = ui.exact_requests[-1]
        assert latest.query["node_id"] == [f"loop-{index}"]
        assert json.loads(latest.query["iteration_path"][0]) == ui.mixed_frames[:index]
        assert latest.query["limit"] == ["1"]
        inspector.get_by_role("button", name=name, exact=True).click()
    inspector = select_node(view, "inspect-record")
    execution_id = ui.execution_for(MIXED_WORKFLOW_ID, MIXED_RUN_ID, "inspect-record", ui.mixed_frames)
    attempts = inspector.get_by_role("list", name=f"Attempts for execution {execution_id}", exact=True)
    expect(attempts).to_contain_text("Attempt 2")
    expect(node_button(view, "inspect-record")).to_contain_text("completed; attempt 2")
    assert json.loads(ui.exact_requests[-1].query["iteration_path"][0]) == ui.mixed_frames
    if reorder_frame_keys:
        recorded = ui.exact_executions[("user", MIXED_WORKFLOW_ID, MIXED_RUN_ID, execution_id)]["iteration_path"]
        assert recorded == ui.mixed_frames and json.dumps(recorded) != json.dumps(ui.mixed_frames)
    assert any(frame.get("iteration") == 1000 for frame in ui.mixed_frames)
    expect(inspector).to_contain_text("1001")
    assert not any(entry.path.endswith(("/records", "/result", "/state")) for entry in ui.requests)
    attempts.get_by_role("listitem").filter(has_text="Attempt 2").get_by_role("button", name="Load complete records", exact=True).click()
    records = inspector.get_by_role("list", name="Complete saved records", exact=True)
    expect(records.get_by_role("listitem")).to_have_count(2)
    expect(records).to_contain_text('"zero": 0')
    expect(records).to_contain_text('"flag": false')
    expect(records).to_contain_text('"nil": null')
    record_requests = [entry for entry in ui.requests if entry.path.endswith("/records")]
    assert len(record_requests) == 1
    assert record_requests[0].path == (
        f"/api/user/workflows/{MIXED_WORKFLOW_ID}/runs/{MIXED_RUN_ID}"
        f"/executions/{execution_id}/attempts/2/records"
    )
    assert record_requests[0].query == {"output": ["records"], "limit": ["100"]}
    assert not any(entry.query.get("cursor") for entry in ui.evidence_requests)
    assert view.locator("[data-workflow-node-id]").count() < 20
    count = len(ui.exact_requests)
    view.get_by_role("button", name="Return to root instance", exact=True).click()
    expect(view.get_by_role("list", name="Complete saved records", exact=True)).to_have_count(0)
    expect(view.get_by_role("list", name=re.compile("^Attempts for execution "))).to_have_count(0)
    expect(inspector).to_contain_text("Choose an exact frozen item or Repeat round")
    expect(node_button(view, "inspect-record")).to_contain_text("Not loaded")
    assert len(ui.exact_requests) == count


def test_expanded_loop_template_does_not_invent_an_instance_or_fetch_results(workflow_flow_ui):
    ui = workflow_flow_ui
    view = open_run_flow(ui, workflow_name=MIXED_NAME, workflow_id=MIXED_WORKFLOW_ID, run_id=MIXED_RUN_ID)
    for node_id, label in (("loop-0", "Repeat until"), ("loop-1", "For each"), ("loop-2", "Repeat until")):
        control = node_button(view, node_id).locator("..").locator("button[aria-expanded]")
        expect(control).to_have_accessible_name(f"Expand {label}")
        control.click()
        expect(control).to_have_attribute("aria-expanded", "true")
    inspector = select_node(view, "inspect-record")
    expect(inspector).to_contain_text("Choose an exact frozen item or Repeat round")
    expect(node_button(view, "inspect-record")).to_contain_text("Not loaded")
    assert not ui.exact_requests and not ui.evidence_requests


@pytest.mark.parametrize("kinds", [
    ("repeat_until", "for_each", "repeat_until"),
    ("for_each", "repeat_until", "for_each"),
], ids=["repeat-body", "for-each-body"])
def test_frozen_body_region_remains_configuration_only_with_a_complete_mixed_path(workflow_flow_ui, kinds):
    ui = workflow_flow_ui
    ui.seed_mixed(kinds)
    key = ("user", MIXED_WORKFLOW_ID, MIXED_RUN_ID)
    root_execution = ui._add_execution(key, "root", [])
    with pytest.raises(AssertionError, match="no execution identity"):
        ui._add_execution(key, "body-2", ui.mixed_frames)
    with pytest.raises(AssertionError, match="no execution identity"):
        ui.execution_for(MIXED_WORKFLOW_ID, MIXED_RUN_ID, "body-2", ui.mixed_frames)
    view = open_run_flow(ui, workflow_name=MIXED_NAME, workflow_id=MIXED_WORKFLOW_ID, run_id=MIXED_RUN_ID)
    for index, kind in enumerate(kinds):
        inspector = select_node(view, f"loop-{index}")
        frame = ui.mixed_frames[index]
        label = f"Use round {frame['iteration'] + 1} in Flow" if kind == "repeat_until" else f"Use item {frame['index'] + 1} in Flow"
        inspector.get_by_role("button", name=label, exact=True).click()
    leaf_id = ui.execution_for(MIXED_WORKFLOW_ID, MIXED_RUN_ID, "inspect-record", ui.mixed_frames)
    expect(view.get_by_role("list", name=f"Attempts for execution {leaf_id}", exact=True)).to_contain_text("Attempt 2")
    ui.page.wait_for_load_state("networkidle")
    exact_count, evidence_count = len(ui.exact_requests), len(ui.evidence_requests)

    inspector = select_node(view, "body-2")
    expect(node_button(view, "body-2")).to_contain_text("Region grouping; no separate execution")
    expect(inspector).to_contain_text("This region groups nodes; it has no separate execution record.")
    expect(inspector.get_by_role("button", name="Refresh selected execution", exact=True)).to_have_count(0)
    expect(inspector.get_by_role("list", name=re.compile("^Attempts for execution "))).to_have_count(0)
    assert len(ui.exact_requests) == exact_count and len(ui.evidence_requests) == evidence_count
    assert ui.detail_requests[-1].query == {
        "node_id": ["body-2"], "section": ["configuration"],
        "revision": [ui.flow_definitions[key]["definition_revision"]], "limit": ["50"],
    }

    control = "Repeat until" if kinds[2] == "repeat_until" else "For each"
    inspector.get_by_role("button", name=f"Inspect enclosing control {control}", exact=True).click()
    control_id = ui.execution_for(MIXED_WORKFLOW_ID, MIXED_RUN_ID, "loop-2", ui.mixed_frames[:2])
    expect(node_button(view, "loop-2")).to_have_attribute("aria-pressed", "true")
    panel = "Repeat round inspection" if kinds[2] == "repeat_until" else "Frozen item inspection"
    expect(inspector.get_by_role("region", name=panel, exact=True)).to_be_visible()
    expect(inspector.get_by_role("button", name=label, exact=True)).to_be_visible()
    assert len(ui.exact_requests) == exact_count + 1
    assert ui.exact_requests[-1].query == {
        "node_id": ["loop-2"], "iteration_path": [json.dumps(ui.mixed_frames[:2], separators=(",", ":"))], "limit": ["1"],
    }
    resource = "iterations" if kinds[2] == "repeat_until" else "items"
    assert len(ui.evidence_requests) == evidence_count + 1
    assert ui.evidence_requests[-1].path == (
        f"/api/user/workflows/{MIXED_WORKFLOW_ID}/runs/{MIXED_RUN_ID}/executions/{control_id}/{resource}"
    )
    assert ui.evidence_requests[-1].query == {"limit": ["50"]}
    assert not any(entry.query["node_id"] == ["body-2"] for entry in ui.exact_requests)

    inspector = select_node(view, "root")
    attempts = inspector.get_by_role("list", name=f"Attempts for execution {root_execution['execution_id']}", exact=True)
    expect(attempts).to_contain_text("Attempt 1")
    expect(node_button(view, "root")).to_contain_text("completed; attempt 1")
    assert ui.exact_requests[-1].query == {"node_id": ["root"], "iteration_path": ["[]"], "limit": ["1"]}
    exact_count, evidence_count = len(ui.exact_requests), len(ui.evidence_requests)
    view.get_by_role("button", name="Return to root instance", exact=True).click()
    expect(node_button(view, "root")).to_have_attribute("aria-pressed", "true")
    expect(node_button(view, "root")).to_contain_text("completed; attempt 1")
    expect(attempts).to_contain_text("Attempt 1")
    assert len(ui.exact_requests) == exact_count and len(ui.evidence_requests) == evidence_count


def test_repeat_state_is_read_only_and_loaded_only_after_explicit_round_selection(workflow_flow_ui):
    ui = workflow_flow_ui
    view = open_run_flow(ui, workflow_name=MIXED_NAME, workflow_id=MIXED_WORKFLOW_ID, run_id=MIXED_RUN_ID)
    inspector = select_node(view, "loop-0")
    expect(inspector.get_by_role("button", name="Use round 1001 in Flow", exact=True)).to_be_visible()
    assert not any(entry.path.endswith("/state") for entry in ui.requests)
    inspector.get_by_role("button", name="State after round 1001", exact=True).click()
    state = inspector.get_by_role("region", name="State after round 1001", exact=True)
    expect(state).to_contain_text("review")
    state_requests = [entry for entry in ui.requests if entry.path.endswith("/state")]
    execution_id = ui.execution_for(MIXED_WORKFLOW_ID, MIXED_RUN_ID, "loop-0", [])
    assert len(state_requests) == 1
    assert state_requests[0].path == (
        f"/api/user/workflows/{MIXED_WORKFLOW_ID}/runs/{MIXED_RUN_ID}"
        f"/executions/{execution_id}/iterations/1000/state"
    )
    assert state_requests[0].query == {"phase": ["after"], "limit": ["50"]}
    assert not any(entry.path.endswith(("/records", "/result")) for entry in ui.requests)


@pytest.mark.parametrize("status", [403, 404])
def test_exact_lookup_access_or_admission_failure_clears_cached_evidence(workflow_flow_ui, status):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    view = open_run_flow(ui)
    inspector = select_node(view, "evaluate")
    execution_id = ui.execution_for(FLOW_WORKFLOW_ID, FLOW_RUN_ID, "evaluate", [])
    expect(inspector.get_by_role(
        "list", name=f"Attempts for execution {execution_id}", exact=True,
    )).to_contain_text("Attempt 2")
    ui.reject_next(
        "GET", f"/api/user/workflows/{FLOW_WORKFLOW_ID}/runs/{FLOW_RUN_ID}/executions",
        status=status, error="Current access or admission for this instance could not be confirmed.",
    )
    inspector.get_by_role("button", name="Refresh selected execution", exact=True).click()
    expect(page.locator("[data-workflow-node-id]")).to_have_count(0)
    expect(page.get_by_role("region", name="Flow node inspection", exact=True)).to_have_count(0)
    expect(page.get_by_role("list", name=re.compile("^Attempts for execution "))).to_have_count(0)
    expect(page.get_by_text(re.compile("^No execution recorded"))).to_have_count(0)
    expect(page.get_by_role("alert").filter(has_text=re.compile("access|available|readable", re.I)).first).to_be_visible()
    assert ui.exact_requests[-1].query == {"node_id": ["evaluate"], "iteration_path": ["[]"], "limit": ["1"]}


@pytest.mark.parametrize("status", [403, 404])
@pytest.mark.parametrize("source", ["saved", "run"])
def test_access_loss_clears_graph_details_and_execution_evidence(workflow_flow_ui, status, source):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    view = open_run_flow(ui) if source == "run" else open_saved(ui)
    inspector = select_node(view, "evaluate")
    expect(inspector).to_contain_text("INSTRUCTIONS")
    path = f"/api/user/workflows/{FLOW_WORKFLOW_ID}"
    path += f"/runs/{FLOW_RUN_ID}/flow" if source == "run" else "/flow"
    ui.reject_next("GET", path, status=status, error="The fictional definition is no longer readable.")
    inspector.get_by_role("button", name="Refresh node details", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text=re.compile("access|available|readable", re.I)).first).to_be_visible()
    expect(page.locator("[data-workflow-node-id]")).to_have_count(0)
    expect(page.get_by_role("region", name="Flow node inspection", exact=True)).to_have_count(0)
    expect(page.get_by_text(re.compile("FROZEN_INSTRUCTIONS|LIVE_ONLY_INSTRUCTIONS"))).to_have_count(0)
    expect(page.get_by_role("list", name=re.compile("^Attempts for execution "))).to_have_count(0)


def test_read_only_group_source_switch_rejects_delayed_previous_group_projection(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    ui.group_can_manage = False
    alpha = ui.group_workflows[GROUP_ID][FLOW_WORKFLOW_ID]
    beta = ui.group_workflows[SECOND_GROUP_ID][FLOW_WORKFLOW_ID]
    next(task for task in alpha["tasks"] if task["id"] == "evaluate")["name"] = "Alpha-only evaluation"
    next(task for task in beta["tasks"] if task["id"] == "evaluate")["name"] = "Beta-only evaluation"
    ui.hold_next_flow(source_kind="saved", group_id=GROUP_ID)
    ui.open("/groups")
    ui.select_group(GROUP_ID)
    page.get_by_role("button", name="View Flow for Alpha read-only Flow", exact=True).click()
    expect(flow_region(page).get_by_text("Loading authorized Flow definition...", exact=True)).to_be_visible()
    close_saved(page)
    ui.select_group(SECOND_GROUP_ID)
    page.get_by_role("button", name="View Flow for Beta read-only Flow", exact=True).click()
    view = flow_region(page)
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Beta-only evaluation (Task)")
    inspector = select_node(view, "evaluate")
    expect(inspector).to_contain_text("Instructions")
    assert len(ui.held_flow_responses) == 1
    ui.release_flow_responses()
    page.wait_for_load_state("networkidle")
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Beta-only evaluation (Task)")
    expect(view.get_by_text("Alpha-only evaluation", exact=True)).to_have_count(0)
    flows = [entry for entry in ui.requests if entry.path.endswith("/flow")]
    assert all(entry.path.startswith("/api/group/workflows/") for entry in flows)
    assert all(entry.query.get("group_id") in ([GROUP_ID], [SECOND_GROUP_ID]) for entry in flows)
    assert flows[-1].query["group_id"] == [SECOND_GROUP_ID]
    ui.assert_read_only()


def test_group_reader_can_inspect_frozen_run_and_exact_attempt_with_current_scope(workflow_flow_ui):
    ui = workflow_flow_ui
    ui.group_can_manage = False
    view = open_run_flow(ui, workflow_name="Alpha read-only Flow", group=True)
    expect(node_button(view, "evaluate")).to_have_accessible_name("Select Frozen group evaluation (Task)")
    inspector = select_node(view, "evaluate")
    expect(inspector).to_contain_text("FROZEN_GROUP_INSTRUCTIONS")
    execution_id = ui.execution_for(FLOW_WORKFLOW_ID, FLOW_RUN_ID, "evaluate", [], scope="group")
    expect(inspector.get_by_role("list", name=f"Attempts for execution {execution_id}", exact=True)).to_contain_text("Attempt 2")
    requests = [
        entry for entry in ui.requests
        if entry.path.startswith(f"/api/group/workflows/{FLOW_WORKFLOW_ID}/runs/{FLOW_RUN_ID}")
    ]
    assert requests and all(entry.query.get("group_id") == [GROUP_ID] for entry in requests)
    assert ui.exact_requests[-1].query == {
        "node_id": ["evaluate"], "iteration_path": ["[]"], "limit": ["1"], "group_id": [GROUP_ID],
    }
    expect(view.get_by_role("button", name=re.compile(r"^(Approve|Retry|Resume|Continue Repeat)$"))).to_have_count(0)


def test_selected_details_replace_bounded_pages_without_draining_them(workflow_flow_ui):
    ui = workflow_flow_ui
    definition = ui.personal_workflows[FLOW_WORKFLOW_ID]
    task = next(task for task in definition["tasks"] if task["id"] == "finish")
    task["inputs"] = [flow_binding(f"input_{index}", "evaluate") for index in range(100)]
    definition["definition_revision"] = workflow_definition_revision(definition)
    view = open_saved(ui)
    assert_no_eager_content(ui)
    inspector = select_node(view, "finish")
    inspector.get_by_label("Inspection section", exact=True).select_option("inputs")
    expect(inspector).to_contain_text("Showing 50 of 100 typed inputs entries")
    expect(inspector.get_by_text("input_0", exact=True)).to_be_visible()
    expect(inspector.get_by_text("input_50", exact=True)).to_have_count(0)
    expect(view.locator(".workflow-flow-data-edge")).to_have_count(1)
    expect(view.get_by_text("50 declared bindings (this page)", exact=True)).to_have_count(1)
    initial = [entry for entry in ui.detail_requests if entry.query["section"] == ["inputs"]]
    assert len(initial) == 1 and "cursor" not in initial[0].query
    inspector.get_by_role("button", name="Next details page", exact=True).click()
    expect(inspector.get_by_text("input_50", exact=True)).to_be_visible()
    expect(inspector.get_by_text("input_0", exact=True)).to_have_count(0)
    expect(view.get_by_text("50 declared bindings (this page)", exact=True)).to_have_count(1)
    expect(inspector.get_by_role("button", name="Next details page", exact=True)).to_be_disabled()
    pages = [entry for entry in ui.detail_requests if entry.query["section"] == ["inputs"]]
    assert len(pages) == 2 and pages[-1].query.get("cursor")
    assert all(entry.query["limit"] == ["50"] for entry in pages)


def test_reselecting_loaded_node_preserves_its_inspected_bindings(workflow_flow_ui):
    ui = workflow_flow_ui
    view = open_saved(ui)
    inspector = select_node(view, "finish")
    inspector.get_by_label("Inspection section", exact=True).select_option("inputs")
    expect(inspector).to_contain_text("Showing 2 of 2 typed inputs entries")
    expect(view.locator(".workflow-flow-data-edge")).to_have_count(2)
    requests = len(ui.detail_requests)
    inspector = select_node(view, "finish")
    expect(inspector).to_contain_text("Showing 2 of 2 typed inputs entries")
    expect(view.locator(".workflow-flow-data-edge")).to_have_count(2)
    assert len(ui.detail_requests) == requests


@pytest.mark.parametrize("node_id", ["root", "evaluate"])
def test_root_and_task_source_selection_show_only_their_bounded_references(workflow_flow_ui, node_id):
    ui = workflow_flow_ui
    definition = ui.personal_workflows[FLOW_WORKFLOW_ID]
    definition["reference_inputs"] = [{
        "id": f"ref-{index}", "name": f"reference_{index}", "document_id": f"reference-document-{index}",
        "scope_type": "personal",
    } for index in range(60)]
    task = next(task for task in definition["tasks"] if task["id"] == "evaluate")
    task["reference_ids"] = ["ref-0", "ref-59"]
    definition["definition_revision"] = workflow_definition_revision(definition)
    view = open_saved(ui)
    assert_no_eager_content(ui)
    assert "reference-document-" not in json.dumps(ui.flow_payloads)
    inspector = select_node(view, node_id)
    inspector.get_by_label("Inspection section", exact=True).select_option(label="Source selection")
    expect(inspector.get_by_text("reference_0", exact=True)).to_be_visible()
    requests = [entry for entry in ui.detail_requests if entry.query["section"] == ["selection"]]
    assert len(requests) == 1 and "cursor" not in requests[0].query
    if node_id == "root":
        expect(inspector).to_contain_text("Showing 50 of 60 source selection entries")
        expect(inspector.get_by_text("reference_59", exact=True)).to_have_count(0)
        inspector.get_by_role("button", name="Next details page", exact=True).click()
        expect(inspector).to_contain_text("Showing 10 of 60 source selection entries")
        expect(inspector.get_by_text("reference_0", exact=True)).to_have_count(0)
        expect(inspector.get_by_text("reference_59", exact=True)).to_be_visible()
    else:
        expect(inspector).to_contain_text("Showing 2 of 2 source selection entries")
        expect(inspector.get_by_text("reference_59", exact=True)).to_be_visible()
        expect(inspector.get_by_text("reference_1", exact=True)).to_have_count(0)
    expect(inspector.get_by_role("button", name="Next details page", exact=True)).to_be_disabled()
    requests = [entry for entry in ui.detail_requests if entry.query["section"] == ["selection"]]
    assert len(requests) == (2 if node_id == "root" else 1)
    assert all(entry.query["limit"] == ["50"] for entry in requests)
    expect(view.locator(".workflow-flow-data-edge")).to_have_count(0)
    assert not ui.evidence_requests and not ui.exact_requests


def test_for_each_source_selection_accepts_5001_entries_without_expanding_instances(workflow_flow_ui):
    ui = workflow_flow_ui
    ui.seed_mixed(("for_each", "repeat_until", "for_each"))
    definition = ui.personal_workflows[MIXED_WORKFLOW_ID]
    loop = next(node for node in definition["flow"]["nodes"] if node["id"] == "loop-0")
    loop["inputs"] = []
    loop["iterable"] = {"kind": "documents", "documents": [{
        "document_id": f"selection-document-{index:04d}", "scope_type": "personal",
    } for index in range(5000)]}
    definition["definition_revision"] = workflow_definition_revision(definition)
    view = open_saved(ui, MIXED_NAME)
    assert_no_eager_content(ui)
    assert view.locator("[data-workflow-node-id]").count() <= 5
    assert "selection-document-" not in json.dumps(ui.flow_payloads)
    inspector = select_node(view, "loop-0")
    inspector.get_by_label("Inspection section", exact=True).select_option(label="Source selection")
    expect(inspector).to_contain_text("Showing 50 of 5001 source selection entries")
    expect(inspector.get_by_text("Iterable", exact=True)).to_be_visible()
    expect(inspector).to_contain_text("selection-document-0000")
    expect(inspector).not_to_contain_text("selection-document-0049")
    pages = [entry for entry in ui.detail_requests if entry.query["section"] == ["selection"]]
    assert len(pages) == 1 and "cursor" not in pages[0].query
    inspector.get_by_role("button", name="Next details page", exact=True).click()
    expect(inspector).to_contain_text("selection-document-0049")
    expect(inspector).to_contain_text("selection-document-0098")
    expect(inspector).not_to_contain_text("selection-document-0000")
    pages = [entry for entry in ui.detail_requests if entry.query["section"] == ["selection"]]
    assert len(pages) == 2 and pages[-1].query.get("cursor")
    assert all(entry.query["limit"] == ["50"] for entry in pages)
    assert view.locator("[data-workflow-node-id]").count() <= 5
    expect(view.locator(".workflow-flow-data-edge")).to_have_count(0)
    assert not ui.evidence_requests and not ui.exact_requests


def test_malicious_labels_remain_text_and_keyboard_inspection_returns_focus(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    definition = ui.personal_workflows[FLOW_WORKFLOW_ID]
    next(task for task in definition["tasks"] if task["id"] == "evaluate")["name"] = MALICIOUS_LABEL
    view = open_saved(ui)
    root = node_button(view, "root")
    root.focus()
    root.press("ArrowDown")
    chosen = node_button(view, "evaluate")
    expect(chosen).to_be_focused()
    page.wait_for_function(
        "element => new DOMMatrixReadOnly(getComputedStyle(element).transform).a >= 1",
        arg=view.locator(".react-flow__viewport").element_handle(), timeout=5000,
    )
    expect(chosen).to_have_accessible_name(f"Select {MALICIOUS_LABEL} (Task)")
    chosen.press("Enter")
    expect(chosen).to_be_focused()
    view.get_by_role("button", name="Inspect selected node", exact=True).click()
    inspector = view.get_by_role("region", name="Flow node inspection", exact=True)
    expect(inspector).to_be_focused()
    inspector.get_by_role("button", name="Return to selected node", exact=True).click()
    expect(chosen).to_be_focused()
    chosen.press("ArrowLeft")
    expect(root).to_be_focused()
    assert page.evaluate("window.flowLabelExecuted === undefined")
    expect(view.locator("img")).to_have_count(0)
    assert all(not entry.path.endswith("/x") for entry in ui.requests)


def test_keyboard_navigation_follows_regions_without_changing_executable_order(workflow_flow_ui):
    ui = workflow_flow_ui
    original = copy.deepcopy(ui.personal_workflows[FLOW_WORKFLOW_ID])
    view = open_saved(ui)
    branch = node_button(view, "choose")
    branch.focus()
    branch.press("ArrowRight")
    then = node_button(view, "accepted-path")
    expect(then).to_be_focused()
    then.press("ArrowRight")
    task = node_button(view, "accept")
    expect(task).to_be_focused()
    task.press("ArrowLeft")
    expect(then).to_be_focused()
    then.press("ArrowLeft")
    expect(branch).to_be_focused()
    branch.press("End")
    expect(node_button(view, "finish")).to_be_focused()
    node_button(view, "finish").press("Home")
    expect(node_button(view, "root")).to_be_focused()
    assert not ui.detail_requests and not ui.evidence_requests
    assert ui.personal_workflows[FLOW_WORKFLOW_ID] == original


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_saved_mobile_structure_and_diagram_keep_focus_and_fit_the_page(workflow_flow_ui, theme):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    page.emulate_media(reduced_motion="reduce")
    view = open_saved(ui, width=390, height=844, theme=theme)
    expect(view.get_by_role("button", name="Structure list", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(view.get_by_role("list", name="Read-only workflow structure", exact=True)).to_be_visible()
    expect(view.locator(".workflow-flow-canvas")).to_have_count(0)
    inspector = select_node(view, "evaluate")
    view.get_by_role("button", name="Inspect selected node", exact=True).click()
    expect(inspector).to_be_focused()
    inspector.get_by_role("button", name="Return to selected node", exact=True).click()
    expect(node_button(view, "evaluate")).to_be_focused()
    ui.assert_no_overflow()
    view.get_by_role("button", name="Flow diagram", exact=True).click()
    expect(view.locator(".workflow-flow-canvas")).to_be_visible()
    select_node(view, "evaluate")
    view.get_by_role("button", name="Fit Flow", exact=True).click()
    ui.assert_no_overflow()
    dialog = page.get_by_role("dialog", name="Workflow Flow", exact=True)
    assert dialog.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    assert not ui.preview_requests
    assert all(asset.startswith("/static/") for asset in ui.loaded_assets)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_defaults_to_list_and_optional_flow_has_no_page_overflow(workflow_flow_ui, theme):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    page.emulate_media(reduced_motion="reduce")
    editor = open_editor(ui, width=390, height=844, theme=theme)
    main = editor.get_by_role("group", name="Main region", exact=True, include_hidden=True)
    expect(main).to_be_visible()
    assert not ui.preview_requests
    ui.assert_no_overflow()
    view = show_preview(editor)
    expect(main).to_be_hidden()
    expect(view.locator(".workflow-flow-canvas")).to_be_visible()
    fields = select_authoring_node(view, "evaluate")
    view.get_by_role("button", name="Configure selected block", exact=True).click()
    expect(fields.get_by_label("Task name", exact=True)).to_be_focused()
    fields.get_by_role("button", name="Return to selected block", exact=True).click()
    expect(node_button(view, "evaluate")).to_be_focused()
    expect(editor.get_by_label("Task name", exact=True)).to_have_count(1)
    view.get_by_role("button", name="Fit Flow", exact=True).click()
    ui.assert_no_overflow()
    assert editor.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    assert page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    assert all(asset.startswith("/static/") for asset in ui.loaded_assets)
    editor.get_by_role("button", name="List authoring", exact=True).click()
    expect(editor.get_by_role("region", name="Workflow Flow authoring", exact=True)).to_have_count(0)
    expect(main).to_be_visible()
