# test_v2_workflow_loops.py
"""
Closed browser regressions for serial For each, exact Collect and explicit saved-record reporting.
Version: 0.261.120
Implemented in: 0.261.117

Loads the real built local SPA and validates authoring payloads with production
normalization. Source previews and immutable paged history are fake network
responses; the tests never invoke paid services, a model, or a live workspace.
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

# Shared fixtures import isolated production normalization after path setup.
from ui_tests.fixtures.workflow_loops import (
    COLLECT_EXECUTION_ID,
    GROUP_ID,
    ITEM_A_EXECUTION_ID,
    ITEM_B_EXECUTION_ID,
    LOOP_EXECUTION_ID,
    LOOP_ID,
    LOOP_RUN_ID,
    LOOP_WORKFLOW_ID,
    REPORT_EXECUTION_ID,
    connect_options,  # noqa: F401
    loop_workflow_record,
    nested_loop_workflow_record,
    reporting_loop_workflow_record,
    query_selection_metadata,
    workflow_loops_ui,  # noqa: F401
)
from ui_tests.fixtures.workflow_control_definitions import flow_binding, structured_workflow_record


pytestmark = pytest.mark.ui


def task_block(page, name):
    return page.get_by_role("region", name=f"{name} block", exact=True)


def details(block):
    block.get_by_text("Runner, inputs, references and outputs", exact=True).click()


def open_loop(ui, **kwargs):
    ui.open(f"/workspace/workflows?workflow_id={LOOP_WORKFLOW_ID}", **kwargs)
    return ui.page.get_by_role("region", name="For each block", exact=True).first


def expand_history(ui, *, group=False):
    page = ui.page
    ui.open("/groups" if group else "/workspace/workflows")
    if group:
        page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
    row = page.get_by_role("listitem").filter(has_text="Group source loop" if group else "Source loop review").first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    return row


def test_author_selected_documents_current_analyze_exports_and_collect(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Create workflow", exact=True).click()
    page.get_by_label("Workflow name", exact=True).fill("Authored source review")
    page.get_by_label("Model", exact=True).select_option(label="Workspace GPT \u00b7 aoai")
    page.get_by_label("Task name", exact=True).fill("Analyze one source")
    page.get_by_label("Instructions", exact=True).fill("Return exact records for the current source.")
    page.get_by_role("button", name="Enable structured control flow", exact=True).click()
    page.get_by_role("button", name="Convert draft", exact=True).click()
    page.get_by_role("button", name="Add For each to Main", exact=True).click()
    loop = page.get_by_role("region", name="For each block", exact=True)
    loop.get_by_label("For each maximum items", exact=True).fill("2")
    available = loop.get_by_role("list", name="Available loop documents", exact=True)
    available.get_by_role("listitem").filter(has_text="Private brief").get_by_role("button", name="Add", exact=True).click()
    available.get_by_role("listitem").filter(has_text="Second brief").get_by_role("button", name="Add", exact=True).click()
    expect(available.get_by_role("button", name="Added", exact=True)).to_have_count(2)
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    expect(loop.get_by_text("Selected count: 2. Effective ceiling: 2. Within the limit.", exact=True)).to_be_visible()
    move = task_block(page, "Analyze one source").get_by_label("Move Analyze one source to region", exact=True)
    destination = move.locator("option").filter(has_text="/ Body").get_attribute("value")
    move.select_option(destination)
    task = task_block(page, "Analyze one source")
    details(task)
    task.get_by_label("Document action", exact=True).select_option("current_item")
    task.get_by_label("Output contract for Analyze one source", exact=True).select_option("records")
    task.get_by_label("Record field name", exact=True).fill("finding_id")
    task.get_by_label("Record field type", exact=True).select_option("string")
    task.get_by_role("button", name="Add record field", exact=True).click()
    task.get_by_role("button", name="Add analyze one source inputs input", exact=True).click()
    task.get_by_label("Analyze one source inputs input 1 name", exact=True).fill("item")
    expect(task.get_by_label("Analyze one source inputs input 1 source", exact=True)).to_have_value("loop_item")
    body_outputs = loop.get_by_role("group", name="Body outputs", exact=True)
    body_outputs.get_by_role("button", name="Add body outputs input", exact=True).click()
    body_outputs.get_by_label("Body outputs input 1 name", exact=True).fill("findings")
    body_outputs.get_by_label("Body outputs input 1 producer", exact=True).select_option(label="Analyze one source")
    body_outputs.get_by_label("Body outputs input 1 output", exact=True).select_option("records")
    page.get_by_role("button", name="Add Collect to Main", exact=True).click()
    collect = page.get_by_role("region", name="Collect block", exact=True)
    loop_value = collect.get_by_label("Collect source loop", exact=True).locator("option").last.get_attribute("value")
    collect.get_by_label("Collect source loop", exact=True).select_option(loop_value)
    collect.get_by_label("Collect body output", exact=True).select_option("findings")
    collect.get_by_label("Collect identity field", exact=True).fill("finding_id")
    collect.get_by_label("Record field name", exact=True).fill("finding_id")
    collect.get_by_label("Record field type", exact=True).select_option("string")
    collect.get_by_role("button", name="Add record field", exact=True).click()
    final = page.get_by_role("group", name="Final outputs", exact=True)
    final.get_by_role("button", name="Add final outputs input", exact=True).click()
    final.get_by_label("Final outputs input 1 name", exact=True).fill("all_findings")
    final.get_by_label("Final outputs input 1 producer", exact=True).select_option(label="Collect findings")
    final.get_by_label("Final outputs input 1 output", exact=True).select_option("records")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    payload = ui.workflow_writes[-1].body
    loop_node, collect_node = payload["flow"]["nodes"]
    assert loop_node["kind"] == "for_each"
    assert loop_node["item_key"] == "source_identity"
    assert loop_node["max_items"] == 2
    assert loop_node["iterable"] == {"kind": "documents", "documents": [
        {"document_id": "personal-brief", "scope_type": "personal"},
        {"document_id": "personal-second", "scope_type": "personal"},
    ]}
    assert payload["tasks"][0]["document_action"] == {
        "type": "analyze", "target_mode": "current_item",
        "loop_id": loop_node["id"], "analysis_mode": "combined",
    }
    assert payload["tasks"][0]["inputs"][0]["source"] == {
        "kind": "loop_item", "loop_id": loop_node["id"], "scope": "current",
    }
    assert collect_node["source"] == {"loop_id": loop_node["id"], "output": "findings"}
    assert collect_node["output_contract"]["kind"] == "records"
    assert collect_node["output_contract"]["schema"] == payload["tasks"][0]["output_contract"]["schema"]
    assert not any(request.path.endswith("/run") for request in ui.writes)
    page.get_by_role("button", name="Edit Authored source review", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="cannot safely save")).to_have_count(0)
    expect(page.get_by_label("For each maximum items", exact=True)).to_have_value("2")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["flow"] == payload["flow"]
    assert ui.workflow_writes[-1].body["tasks"][0]["document_action"] == payload["tasks"][0]["document_action"]


def test_saved_collection_source_is_typed_complete_and_run_count_unknown(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.personal_workflows[LOOP_WORKFLOW_ID] = loop_workflow_record(saved_collection=True)
    loop = open_loop(ui)
    expect(loop.get_by_text("Selected count is known only", exact=False)).to_be_visible()
    expect(loop.get_by_role("button", name="Preview loop selection", exact=True)).to_have_count(0)
    body_output = loop.get_by_role("group", name="Body outputs", exact=True)
    expect(body_output.get_by_label("Body outputs input 1 producer", exact=True).locator('option[value="seed"]')).to_have_count(0)
    loop.get_by_label("Collection input name", exact=True).fill("saved_findings")
    loop.get_by_label("Saved collection output", exact=True).select_option(label="Prepare saved rows / records (records)")
    task = task_block(page, "Analyze current source")
    details(task)
    expect(task.get_by_label("Document action", exact=True).locator('option[value="current_item"]')).to_have_count(0)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    node = ui.workflow_writes[-1].body["flow"]["nodes"][1]
    assert node["iterable"] == {"kind": "input", "name": "saved_findings"}
    assert node["inputs"][0] == {
        "name": "saved_findings", "source": {"kind": "node_output", "node_id": "seed", "output": "records", "scope": "current"},
        "required": True, "expected_kind": "records", "allow_partial": False,
    }


def test_query_all_matches_best_n_and_excess_lower_bound(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.query_count, ui.query_exact = 501, False
    loop = open_loop(ui)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    loop.get_by_label("Query search", exact=True).fill("retention")
    loop.get_by_label("Query author", exact=True).fill("Policy owner")
    loop.get_by_label("Query classification", exact=True).fill("Internal")
    loop.get_by_label("Query keywords", exact=True).fill("review")
    loop.get_by_label("Query abstract", exact=True).fill("Retention obligations")
    loop.get_by_label("Query tags", exact=True).fill("review, audit")
    loop.get_by_label("Query content mode", exact=True).select_option("keyword")
    loop.get_by_label("Query content", exact=True).fill("retention policy")
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    expect(loop.get_by_role("alert").filter(has_text="at least 501")).to_be_visible()
    expect(loop.get_by_role("alert").filter(has_text="Narrow the query")).to_be_visible()
    ui.query_count = 50000
    loop.get_by_label("Query content mode", exact=True).select_option("hybrid")
    expect(loop.get_by_label("Query selection", exact=True)).to_have_value("best_n")
    expect(loop.get_by_label("Query selection", exact=True).locator('option[value="all_matches"]')).to_have_attribute("disabled", "")
    loop.get_by_label("Best N documents", exact=True).fill("2")
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    expect(loop.get_by_text("Selected count: 2. Effective ceiling: 500. Within the limit.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    iterable = ui.workflow_writes[-1].body["flow"]["nodes"][0]["iterable"]
    assert iterable["selection"] == {"mode": "best_n", "count": 2}
    assert iterable["content"] == {"mode": "hybrid", "query": "retention policy"}
    assert iterable["filters"]["tags"] == ["review", "audit"]
    assert iterable["scopes"] == [{"scope_type": "personal"}]
    previews = [request.body for request in ui.writes if request.path.endswith("/preview")]
    assert previews[0]["iterable"]["selection"] == {"mode": "all_matches"}
    assert previews[0]["iterable"]["content"]["mode"] == "keyword"
    assert not any("max_total_tokens" in str(write.body) for write in ui.writes)


def test_known_selection_excess_uses_effective_admin_ceiling(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.ceiling = 1
    loop = open_loop(ui)
    expect(loop.get_by_text("Administrator ceiling: 1", exact=False)).to_be_visible()
    expect(loop.get_by_role("alert").filter(has_text="This selection has 2 documents")).to_be_visible()
    expect(loop.get_by_role("button", name="Preview loop selection", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    assert not ui.workflow_writes
    assert ui.personal_workflows[LOOP_WORKFLOW_ID]["flow"]["nodes"][0]["max_items"] == 500


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("count_exact", [False, True])
def test_http_422_preview_preserves_count_precision_and_clears_previous_items(workflow_loops_ui, group, count_exact):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    if group:
        ui.open("/groups")
        page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
        page.get_by_role("button", name="Edit Group source loop", exact=True).click()
        loop = page.get_by_role("region", name="For each block", exact=True)
    else:
        loop = open_loop(ui)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    ui.query_count = 1
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    preview = loop.get_by_role("list", name="Loop preview documents", exact=True)
    expect(preview).to_contain_text("Group brief" if group else "Private brief")
    ui.query_count, ui.query_exact = 501, count_exact
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    error = loop.get_by_role("alert").filter(has_text="exceeds this loop's admitted item limit")
    expect(error).to_be_visible()
    expect(error).to_contain_text("Selected count: 501." if count_exact else "Selected count (lower bound): at least 501.")
    expect(error).to_contain_text("Effective ceiling: 500.")
    expect(error).to_contain_text("Narrow the query or select 500 or fewer documents")
    expect(preview.get_by_role("listitem")).to_have_count(0)
    expect(loop.get_by_label("Query selection", exact=True)).to_have_value("all_matches")
    assert any("/loop-inputs/preview" in url and status == 422 for url, status in ui.expected_http_errors)
    calls = [request for request in ui.requests if request.path.endswith("/loop-inputs/preview")]
    assert all(call.query.get("group_id") == ([GROUP_ID] if group else None) for call in calls)
    assert not ui.workflow_writes


def test_http_422_malformed_metadata_uses_only_the_safe_error_message(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    loop = open_loop(ui)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    message = 'Selection cannot be admitted. <img src="https://invalid.example/preview" onerror="window.bad=true">'
    ui.reject_next(
        "POST", "/api/user/workflows/loop-inputs/preview", status=422, error=message,
        code="workflow_loop_item_limit_exceeded", count="501", count_exact=False,
        limit=500, within_limit=False, private_debug="must-not-render-preview-debug",
    )
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    error = loop.get_by_role("alert").filter(has_text="Selection cannot be admitted")
    expect(error).to_be_visible()
    expect(error).to_contain_text("<img src=")
    expect(error.locator("img")).to_have_count(0)
    expect(loop.get_by_role("list", name="Loop preview documents", exact=True)).to_have_count(0)
    expect(page.get_by_text("must-not-render-preview-debug", exact=False)).to_have_count(0)
    assert not ui.workflow_writes


@pytest.mark.parametrize("group", [False, True])
def test_hybrid_preview_discloses_candidate_reranking_and_backfill_limits(workflow_loops_ui, group):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    if group:
        ui.open("/groups")
        page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
        page.get_by_role("button", name="Edit Group source loop", exact=True).click()
        loop = page.get_by_role("region", name="For each block", exact=True)
    else:
        loop = open_loop(ui)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    loop.get_by_label("Query content mode", exact=True).select_option("hybrid")
    loop.get_by_label("Query content", exact=True).fill("retention obligations")
    loop.get_by_label("Best N documents", exact=True).fill("2")
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    selection = page.get_by_role("region", name="Preview selection details", exact=True)
    expect(selection).to_contain_text("Selection: Best N documents")
    expect(selection).to_contain_text("Candidate window: 1000 chunks per round")
    expect(selection).to_contain_text("Semantic reranking window: 50 chunks")
    expect(selection).to_contain_text("Distinct-document backfill excludes previously processed candidate documents")
    expect(selection).to_contain_text("Reported candidate expansion rounds: 2")
    expect(selection).to_contain_text("not exhaustive relevance across the corpus")
    expect(selection.get_by_role("note", name="Candidate limitations", exact=True)).to_contain_text("1,000-chunk candidate windows")
    if not group:
        page.set_viewport_size({"width": 390, "height": 844})
        ui.assert_no_overflow()
    assert all(request.query.get("group_id") == ([GROUP_ID] if group else None)
               for request in ui.requests if request.path.endswith("/loop-inputs/preview"))


@pytest.mark.parametrize("group", [False, True])
def test_frozen_selection_limitations_survive_paging_and_later_policy_changes(workflow_loops_ui, group):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    key = ("group" if group else "user", LOOP_WORKFLOW_ID, LOOP_RUN_ID)
    ui.item_selections[key] = query_selection_metadata()
    ui.item_selections[key].update(
        raw_query="private-frozen-query", private_journal={"value": "private-frozen-journal"},
    )
    ui.ceiling = 1
    ui.preview_selection = query_selection_metadata(mode="all_matches", hybrid=False)
    expand_history(ui, group=group)
    page.get_by_role("button", name=f"Show frozen items for {LOOP_EXECUTION_ID}", exact=True).click()
    selection = page.get_by_role("region", name="Frozen selection details", exact=True)
    expect(selection).to_contain_text("Best N documents")
    expect(selection).to_contain_text("Candidate window: 1000")
    expect(selection).to_contain_text("later query or administrator changes do not rewrite them")
    expect(page.get_by_text("Frozen admission ceiling: 500", exact=True)).to_be_visible()
    if not group:
        page.get_by_role("button", name="Next items page", exact=True).click()
        expect(page.get_by_role("list", name="Frozen loop items", exact=True)).to_contain_text("Second brief")
        expect(selection).to_contain_text("Semantic reranking window: 50")
    expect(page.get_by_text("private-frozen-query", exact=False)).to_have_count(0)
    expect(page.get_by_text("private-frozen-journal", exact=False)).to_have_count(0)


def test_all_matches_preview_distinguishes_exhaustive_eligible_coverage(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    loop = open_loop(ui)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    selection = page.get_by_role("region", name="Preview selection details", exact=True)
    expect(selection).to_contain_text("Selection: All matches")
    expect(selection).to_contain_text("Exhaustive eligible matches")
    expect(selection).to_contain_text("does not claim that unindexed content was searched")
    expect(selection.get_by_role("note", name="Candidate limitations", exact=True)).to_have_count(0)


def test_selection_notices_are_inert_and_unknown_payload_fields_stay_hidden(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.preview_selection = query_selection_metadata()
    ui.preview_selection.update(
        ranking="constructor", raw_query="private-preview-query", private_journal="private-selection-journal",
        candidate_limitations=['<img src="https://invalid.example/selection" onerror="window.bad=true"> Candidate notice.'],
    )
    loop = open_loop(ui)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    loop.get_by_label("Query content mode", exact=True).select_option("hybrid")
    loop.get_by_label("Query content", exact=True).fill("retention obligations")
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    selection = page.get_by_role("region", name="Preview selection details", exact=True)
    expect(selection).to_contain_text("Ordering / ranking: constructor")
    expect(selection.get_by_role("note", name="Candidate limitations", exact=True)).to_contain_text("<img src=")
    expect(selection.locator("img")).to_have_count(0)
    expect(page.get_by_text("private-preview-query", exact=False)).to_have_count(0)
    expect(page.get_by_text("private-selection-journal", exact=False)).to_have_count(0)


def test_malformed_selection_metadata_never_claims_exhaustive_preview(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.preview_selection = {"query_mode": "all_matches", "exhaustive": "true"}
    loop = open_loop(ui)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    expect(loop.get_by_role("alert").filter(has_text="selection details returned an unsupported response")).to_be_visible()
    expect(page.get_by_role("region", name="Preview selection details", exact=True)).to_have_count(0)
    expect(loop.get_by_role("list", name="Loop preview documents", exact=True)).to_have_count(0)


def test_nested_current_items_branch_controls_and_body_exports_round_trip(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = nested_loop_workflow_record()
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    open_loop(ui)
    branch = page.get_by_role("region", name="If / else block", exact=True)
    expect(branch.get_by_label("If / else inputs input 1 source", exact=True)).to_have_value("loop_item")
    expect(branch.get_by_label("If / else condition left field", exact=True)).to_have_value("/index")
    leaf = task_block(page, "Review first-task")
    details(leaf)
    expect(leaf.get_by_label("Review first-task inputs input 1 loop", exact=True)).to_have_value("each-finding")
    expect(leaf.get_by_label("Review first-task inputs input 2 loop", exact=True)).to_have_value(LOOP_ID)
    expect(leaf.get_by_label("Review first-task inputs input 1 loop", exact=True).locator("option")).to_have_count(2)
    then = page.get_by_role("group", name="Then region", exact=True)
    expect(then.get_by_role("button", name="Add For each to Then", exact=True)).to_be_disabled()
    expect(then.get_by_role("button", name="Add If/else to Then", exact=True)).to_be_disabled()
    page.get_by_label("Workflow name", exact=True).fill("Nested exact review")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["flow"] == record["flow"]
    assert ui.workflow_writes[-1].body["tasks"][1]["inputs"] == record["tasks"][1]["inputs"]


def test_move_and_delete_keep_invalid_consumers_in_the_draft(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = loop_workflow_record(saved_collection=True)
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    loop = open_loop(ui)
    task = task_block(page, "Analyze current source")
    task.get_by_label("Move Analyze current source to region", exact=True).select_option("root")
    details(task_block(page, "Analyze current source"))
    expect(page.get_by_label("Analyze current source inputs input 1 loop", exact=True)).to_have_value(LOOP_ID)
    expect(page.get_by_label("Analyze current source inputs input 1 loop", exact=True)).to_contain_text("Unavailable")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="enclosing For each")).to_be_visible()
    loop.get_by_role("button", name="Remove For each block", exact=True).click()
    page.get_by_role("button", name="Remove block", exact=True).click()
    expect(page.get_by_label("Collect source loop", exact=True)).to_have_value(LOOP_ID)
    expect(page.get_by_label("Collect body output", exact=True)).to_have_value("findings")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="select an existing loop")).to_be_visible()
    assert not ui.workflow_writes
    assert ui.personal_workflows[LOOP_WORKFLOW_ID] == record


@pytest.mark.parametrize("unsupported", [
    "server_capabilities", "unknown_iterable", "repeat_field", "future_output", "future_runner",
    "missing_root_outputs", "missing_body_outputs",
])
def test_unsupported_loop_definitions_are_preserved_read_only(workflow_loops_ui, unsupported):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = ui.personal_workflows[LOOP_WORKFLOW_ID]
    if unsupported == "server_capabilities":
        ui.loop_capabilities = False
    elif unsupported == "unknown_iterable":
        record["flow"]["nodes"][0]["iterable"] = {"kind": "future_source"}
    elif unsupported == "repeat_field":
        record["flow"]["nodes"][0]["repeat_until"] = {"op": "future_predicate"}
    elif unsupported == "future_output":
        record["tasks"][0]["output_contract"]["kind"] = "future_records"
    elif unsupported == "missing_root_outputs":
        record["flow"].pop("outputs")
    elif unsupported == "missing_body_outputs":
        record["flow"]["nodes"][0]["body"].pop("outputs")
    else:
        record["tasks"][0]["runner"]["type"] = "future_runtime"
    original = copy.deepcopy(record)
    open_loop(ui)
    expect(page.get_by_role("alert").filter(has_text="cannot safely save")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert ui.personal_workflows[LOOP_WORKFLOW_ID] == original
    assert not ui.workflow_writes


def test_all_matches_query_save_preserves_metadata_keyword_semantics(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    loop = open_loop(ui)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    loop.get_by_label("Query content mode", exact=True).select_option("keyword")
    loop.get_by_label("Query content", exact=True).fill("retention policy")
    loop.get_by_label("Query search", exact=True).fill("remove this filter")
    loop.get_by_label("Query search", exact=True).fill("")
    loop.get_by_label("Query classification", exact=True).fill("Internal")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    iterable = ui.workflow_writes[-1].body["flow"]["nodes"][0]["iterable"]
    assert iterable["selection"] == {"mode": "all_matches"}
    assert iterable["content"] == {"mode": "keyword", "query": "retention policy"}
    assert iterable["filters"] == {"classification": "Internal"}


def test_saved_document_results_preserve_kind_through_export_and_collect(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = loop_workflow_record(saved_collection=True)
    for task in record["tasks"]:
        task["output_contract"]["kind"] = "document_results"
    loop = record["flow"]["nodes"][1]
    for binding in (loop["inputs"][0], loop["body"]["outputs"][0], record["flow"]["outputs"][0]):
        binding["expected_kind"] = "document_results"
        binding["source"]["output"] = "documents"
    record["flow"]["nodes"][2]["output_contract"]["kind"] = "document_results"
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    open_loop(ui)
    page.get_by_label("Saved collection output", exact=True).select_option(label="Prepare saved rows / documents (document results)")
    page.get_by_label("Collect body output", exact=True).select_option("findings")
    expect(page.get_by_text("Preserved output kind: document results", exact=True)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    saved = ui.workflow_writes[-1].body["flow"]
    assert saved == record["flow"]


@pytest.mark.parametrize("expected_kind", ["any", "json"])
def test_collection_kind_is_not_coerced_by_a_wider_binding(workflow_loops_ui, expected_kind):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = loop_workflow_record(saved_collection=True)
    loop = record["flow"]["nodes"][1]
    loop["inputs"][0]["expected_kind"] = expected_kind
    loop["body"]["outputs"][0]["expected_kind"] = expected_kind
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    open_loop(ui)
    expect(page.get_by_label("Collect body output", exact=True)).to_contain_text("findings (records)")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["flow"] == record["flow"]


def test_current_item_any_binding_round_trips_as_json_data(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = loop_workflow_record()
    record["tasks"][0]["inputs"][0]["expected_kind"] = "any"
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    open_loop(ui)
    task = task_block(page, "Analyze current source")
    details(task)
    expect(task.get_by_label("Analyze current source inputs input 1 source", exact=True)).to_have_value("loop_item")
    expect(task.get_by_label("Analyze current source inputs input 1 kind", exact=True)).to_have_value("any")
    expect(page.get_by_role("alert").filter(has_text="cannot safely save")).to_have_count(0)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["tasks"][0]["inputs"] == record["tasks"][0]["inputs"]


def test_optional_body_exports_require_explicit_partial_collect_policy(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    loop = open_loop(ui)
    loop.get_by_label("Body outputs input 1 required", exact=True).uncheck()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="explicit partial acceptance")).to_be_visible()
    assert not ui.workflow_writes
    page.get_by_label("Collect allow partial", exact=True).check()
    page.get_by_label("Collect require complete coverage", exact=True).uncheck()
    page.get_by_label("Final outputs input 1 allow partial", exact=True).check()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    nodes = ui.workflow_writes[-1].body["flow"]["nodes"]
    assert not nodes[0]["body"]["outputs"][0]["required"]
    assert nodes[1]["output_contract"]["allow_partial"]


def test_hosted_runner_is_unavailable_only_inside_loop_work(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    open_loop(ui)
    task = task_block(page, "Analyze current source")
    details(task)
    task.get_by_label("Task runner", exact=True).select_option("agent")
    hosted = task.get_by_label("Task agent", exact=True).locator("option").filter(has_text="Hosted reviewer")
    expect(hosted).to_have_attribute("disabled", "")
    expect(task.get_by_text("Hosted agents are unavailable", exact=False)).to_be_visible()
    task.get_by_label("Move Analyze current source to region", exact=True).select_option("root")
    task = task_block(page, "Analyze current source")
    details(task)
    expect(task.get_by_label("Task agent", exact=True).locator("option").filter(has_text="Hosted reviewer")).not_to_have_attribute("disabled", "")


@pytest.mark.parametrize("collection_kind", ["records", "document_results"])
def test_author_explicit_saved_record_report_without_json(workflow_loops_ui, collection_kind):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = reporting_loop_workflow_record(collection_kind=collection_kind)
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    open_loop(ui)
    report = task_block(page, "Explain saved findings")
    details(report)
    mode = report.get_by_label("Large saved inputs", exact=True)
    expect(mode).to_have_value("full")
    mode.select_option(label="Saved-record report (bounded batches)")
    expect(report.get_by_text("reads all records", exact=False)).to_be_visible()
    expect(report.get_by_text("arbitrary transforms or quantitative tasks", exact=False)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    saved = ui.workflow_writes[-1].body
    assert saved["tasks"][1]["input_processing"] == "saved_record_report"
    assert "input_processing" not in saved["tasks"][0]
    assert saved["tasks"][1]["inputs"] == record["tasks"][1]["inputs"]
    assert saved["flow"] == record["flow"]
    page.get_by_role("button", name="Edit Source loop review", exact=True).click()
    report = task_block(page, "Explain saved findings")
    details(report)
    expect(report.get_by_label("Large saved inputs", exact=True)).to_have_value("saved_record_report")
    report.get_by_label("Large saved inputs", exact=True).select_option("full")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["tasks"][1]["input_processing"] == "full"


def test_add_saved_record_report_task_from_list_controls(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    open_loop(ui)
    page.get_by_role("button", name="Add task to Main", exact=True).click()
    page.get_by_label("Task name", exact=True).last.fill("Report all saved findings")
    report = task_block(page, "Report all saved findings")
    report.get_by_label("Instructions", exact=True).fill("Explain all saved findings qualitatively and link each conclusion to its source records.")
    details(report)
    report.get_by_role("button", name="Add report all saved findings inputs input", exact=True).click()
    report.get_by_label("Report all saved findings inputs input 1 producer", exact=True).select_option(label="Collect findings")
    report.get_by_label("Report all saved findings inputs input 1 output", exact=True).select_option("records")
    report.get_by_label("Output contract for Report all saved findings", exact=True).select_option("text")
    report.get_by_label("Large saved inputs", exact=True).select_option("saved_record_report")
    final = page.get_by_role("group", name="Final outputs", exact=True)
    final.get_by_label("Final outputs input 1 name", exact=True).fill("report")
    final.get_by_label("Final outputs input 1 producer", exact=True).select_option(label="Report all saved findings")
    final.get_by_label("Final outputs input 1 output", exact=True).select_option("text")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    task = ui.workflow_writes[-1].body["tasks"][-1]
    assert task["input_processing"] == "saved_record_report"
    assert task["document_action"] == {"type": "none"}
    assert task["output_contract"]["kind"] == "text"
    assert task["inputs"][0]["source"]["node_id"] == "collect-findings"


def test_saved_record_report_accepts_a_join_of_collection_kinds(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = structured_workflow_record(LOOP_WORKFLOW_ID, name="Source loop review")
    record["tasks"][1]["output_contract"]["kind"] = "records"
    record["tasks"][2]["output_contract"]["kind"] = "document_results"
    export = record["flow"]["nodes"][1]["join"]["exports"][0]
    export.update(expected_kind="any", then={"node_id": "accept", "output": "records"},
                  **{"else": {"node_id": "review", "output": "documents"}})
    record["tasks"][-1].update(
        input_processing="saved_record_report",
        inputs=[flow_binding("findings", "decision-join", "report", kind="any")],
    )
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    open_loop(ui)
    finish = task_block(page, "Finish")
    details(finish)
    expect(finish.get_by_label("Large saved inputs", exact=True)).to_have_value("saved_record_report")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["tasks"][-1]["input_processing"] == "saved_record_report"


@pytest.mark.parametrize("original_mode", [None, "full"])
def test_report_wording_never_opts_an_existing_task_into_batches(workflow_loops_ui, original_mode):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.personal_workflows[LOOP_WORKFLOW_ID] = reporting_loop_workflow_record(input_processing=original_mode)
    open_loop(ui)
    report = task_block(page, "Explain saved findings")
    details(report)
    expect(report.get_by_label("Large saved inputs", exact=True)).to_have_value("full")
    report.get_by_label("Large saved inputs", exact=True).select_option("full")
    report.get_by_label("Instructions", exact=True).fill("Explain all saved findings with source-linked qualitative details.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    task = ui.workflow_writes[-1].body["tasks"][1]
    if original_mode is None:
        assert "input_processing" not in task
        assert "input_processing" not in ui.personal_workflows[LOOP_WORKFLOW_ID]["tasks"][1]
    else:
        assert task["input_processing"] == "full"
        assert ui.personal_workflows[LOOP_WORKFLOW_ID]["tasks"][1]["input_processing"] == "full"
    assert "input_processing" not in ui.workflow_writes[-1].body["tasks"][0]
    assert "input_processing" not in ui.personal_workflows[LOOP_WORKFLOW_ID]["tasks"][0]


@pytest.mark.parametrize("incompatible", [
    "missing_collection", "current_item_only", "nontext_output", "document_action", "missing_action", "publication", "hosted_runner",
])
def test_saved_record_report_rejects_incompatible_task_without_rewriting_it(workflow_loops_ui, incompatible):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = reporting_loop_workflow_record(input_processing="saved_record_report")
    task = record["tasks"][1]
    if incompatible == "missing_collection":
        task["inputs"] = []
        expected = "at least one saved records or document-results"
    elif incompatible == "current_item_only":
        loop = record["flow"]["nodes"][0]
        loop["body"]["nodes"].append(record["flow"]["nodes"].pop())
        task["inputs"] = [{
            "name": "item", "source": {"kind": "loop_item", "loop_id": LOOP_ID, "scope": "current"},
            "required": True, "expected_kind": "json", "allow_partial": False,
        }]
        record["flow"]["outputs"] = [flow_binding("findings", "collect-findings", "records", kind="records")]
        expected = "at least one saved records or document-results"
    elif incompatible == "nontext_output":
        task["output_contract"]["kind"] = "json"
        expected = "require a text output contract"
    elif incompatible == "document_action":
        task["document_action"] = {"type": "search", "doc_scope": "all", "document_ids": []}
        expected = "require No document action"
    elif incompatible == "missing_action":
        task.pop("document_action")
        expected = "require No document action"
    elif incompatible == "publication":
        task["publication"] = {"artifact_format": "md", "workspace_scope": "personal"}
        expected = "cannot publish artifacts"
    else:
        task["runner"] = {
            "type": "agent",
            "selected_agent": {"id": "hosted-reviewer", "name": "hosted-reviewer", "is_global": True, "is_group": False},
        }
        expected = "require a locally metered model or local agent"
    original = copy.deepcopy(record)
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    open_loop(ui)
    report = task_block(page, "Explain saved findings")
    details(report)
    expect(report.get_by_role("alert").filter(has_text=expected)).to_be_visible()
    if incompatible == "hosted_runner":
        expect(report.get_by_label("Task agent", exact=True).locator("option").filter(has_text="Hosted reviewer")).to_have_attribute("disabled", "")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(report.get_by_label("Large saved inputs", exact=True)).to_have_value("saved_record_report")
    assert not ui.workflow_writes
    assert ui.personal_workflows[LOOP_WORKFLOW_ID] == original
    if incompatible == "missing_action":
        report.get_by_role("button", name="Use no document action", exact=True).click()
        page.get_by_role("button", name="Save workflow", exact=True).click()
        expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
        assert ui.workflow_writes[-1].body["tasks"][1]["document_action"] == {"type": "none"}


def test_report_mode_preserves_conflict_draft_and_rejects_future_modes(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = reporting_loop_workflow_record()
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    open_loop(ui)
    report = task_block(page, "Explain saved findings")
    details(report)
    report.get_by_label("Large saved inputs", exact=True).select_option("saved_record_report")
    ui.mutate_revision(LOOP_WORKFLOW_ID)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="draft has been retained")).to_be_visible()
    expect(report.get_by_label("Large saved inputs", exact=True)).to_have_value("saved_record_report")
    assert not ui.workflow_writes
    record["tasks"][1]["input_processing"] = "future_reducer"
    page.reload(wait_until="networkidle")
    expect(page.get_by_role("alert").filter(has_text="cannot safely save")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert record["tasks"][1]["input_processing"] == "future_reducer"


def test_report_mode_requires_explicit_v3_conversion(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = reporting_loop_workflow_record(input_processing="saved_record_report")
    record["definition_version"] = 2
    record.pop("flow")
    record.pop("limits")
    record["tasks"][0].update(inputs=[], document_action={"type": "none"})
    record["tasks"][1]["inputs"] = [{
        "name": "findings", "task_id": "analyze-task", "output": "records",
        "required": True, "expected_kind": "records",
    }]
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    open_loop(ui)
    report = page.locator("details").filter(has=page.get_by_label("Large saved inputs", exact=True)).last
    page.get_by_text("Runner, inputs, references and outputs", exact=True).last.click()
    expect(report.get_by_role("alert").filter(has_text="structured definition v3")).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    assert not ui.workflow_writes
    page.get_by_role("button", name="Enable structured control flow", exact=True).click()
    page.get_by_role("button", name="Convert draft", exact=True).click()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["definition_version"] == 3
    assert ui.workflow_writes[-1].body["tasks"][1]["input_processing"] == "saved_record_report"


def test_saved_record_report_is_read_only_when_server_capability_is_missing(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    record = reporting_loop_workflow_record(input_processing="saved_record_report")
    ui.personal_workflows[LOOP_WORKFLOW_ID] = record
    ui.input_processing_modes = []
    original = copy.deepcopy(record)
    open_loop(ui)
    expect(page.get_by_role("alert").filter(has_text="cannot safely save")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert not ui.workflow_writes
    assert ui.personal_workflows[LOOP_WORKFLOW_ID] == original


def test_group_query_preview_and_save_keep_explicit_group_scope(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.open("/groups")
    page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
    page.get_by_role("button", name="Edit Group source loop", exact=True).click()
    loop = page.get_by_role("region", name="For each block", exact=True)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    expect(loop.get_by_role("group", name="Query workspaces", exact=True).get_by_role("checkbox")).to_have_count(1)
    loop.get_by_label("Query search", exact=True).fill("Group briefing")
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    expect(loop.get_by_text("Selected count: 2. Effective ceiling: 500. Within the limit.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    write = ui.workflow_writes[-1]
    assert write.query["group_id"] == [GROUP_ID]
    assert write.body["group_id"] == GROUP_ID
    assert write.body["flow"]["nodes"][0]["iterable"]["scopes"] == [{"scope_type": "group", "scope_id": GROUP_ID}]
    assert all(request.query.get("group_id") == [GROUP_ID] for request in ui.requests if request.path.endswith("/preview"))
    assert not any(request.path == "/api/user/settings" and request.method != "GET" for request in ui.requests)


@pytest.mark.parametrize("group_workflow", [False, True])
def test_selected_shared_group_document_keeps_recipient_scope(workflow_loops_ui, group_workflow):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    owner_group = "owner-group-without-membership"
    ui.group_documents[GROUP_ID].append({
        "id": "shared-brief", "document_id": "shared-brief", "title": "Shared recipient brief",
        "file_name": "shared-brief.pdf", "group_id": owner_group, "owner_group_id": owner_group,
        "shared_group_ids": [GROUP_ID], "shared_group_active_id": GROUP_ID, "shared_approval_status": "approved",
    })
    if group_workflow:
        ui.open("/groups")
        page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
        page.get_by_role("button", name="Edit Group source loop", exact=True).click()
        loop = page.get_by_role("region", name="For each block", exact=True)
    else:
        loop = open_loop(ui)
        loop.get_by_label("Source", exact=True).select_option(f"group:{GROUP_ID}")
    shared = loop.get_by_role("list", name="Available loop documents", exact=True).get_by_role("listitem").filter(has_text="Shared recipient brief")
    shared.get_by_role("button", name="Add", exact=True).click()
    expect(shared.get_by_role("button", name="Added", exact=True)).to_be_disabled()
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    expected_count = 2 if group_workflow else 3
    expect(loop.get_by_text(f"Selected count: {expected_count}. Effective ceiling: 500. Within the limit.", exact=True)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    documents = ui.workflow_writes[-1].body["flow"]["nodes"][0]["iterable"]["documents"]
    selected = next(document for document in documents if document["document_id"] == "shared-brief")
    assert selected == {"document_id": "shared-brief", "scope_type": "group", "scope_id": GROUP_ID}
    preview = next(request for request in ui.requests if request.path.endswith("/loop-inputs/preview"))
    assert selected in preview.body["iterable"]["documents"]
    assert owner_group not in str(preview.body)
    group_reads = [request for request in ui.requests if request.path == "/api/group_documents"]
    assert group_reads and all(request.query.get("group_ids") == [GROUP_ID] for request in group_reads)


def test_mobile_keyboard_conflict_and_close_retain_loop_draft(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    loop = open_loop(ui, theme="dark", width=390, height=844)
    limit = loop.get_by_label("For each maximum items", exact=True)
    limit.focus()
    limit.press("ArrowDown")
    expect(limit).to_have_value("499")
    ui.mutate_revision(LOOP_WORKFLOW_ID)
    save = page.get_by_role("button", name="Save workflow", exact=True)
    save.focus()
    save.press("Enter")
    expect(page.get_by_role("alert").filter(has_text="draft has been retained")).to_be_visible()
    expect(limit).to_have_value("499")
    ui.assert_no_overflow()
    page.get_by_role("button", name="Cancel", exact=True).click()
    confirmation = page.get_by_role("dialog", name=re.compile("Discard")).last
    confirmation.get_by_role("button", name=re.compile("Keep editing")).click()
    expect(limit).to_have_value("499")
    assert not ui.workflow_writes


def test_paged_items_and_complete_records_replace_pages_without_latest_task(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    expand_history(ui)
    progress = page.get_by_role("region", name="Frozen loop progress", exact=True)
    expect(progress).to_contain_text("Frozen selected count: 2")
    expect(progress).to_contain_text("admitted limit: 500")
    page.get_by_role("button", name=f"Show frozen items for {LOOP_EXECUTION_ID}", exact=True).click()
    items = page.get_by_role("list", name="Frozen loop items", exact=True)
    expect(items).to_contain_text("Private brief")
    expect(items).not_to_contain_text("Second brief")
    page.get_by_role("button", name=f"Inspect item execution {ITEM_A_EXECUTION_ID}", exact=True).click()
    attempts = page.get_by_role("list", name=f"Attempts for execution {ITEM_A_EXECUTION_ID}", exact=True)
    attempts.get_by_role("button", name="Load complete records", exact=True).click()
    records = page.get_by_role("list", name="Complete saved records", exact=True)
    expect(records).to_contain_text("Finding from Private brief")
    page.get_by_role("button", name="Next records page", exact=True).click()
    expect(records).to_contain_text("Second finding from Private brief")
    expect(records).not_to_contain_text('"finding": "Finding from Private brief"')
    page.get_by_role("button", name="Next items page", exact=True).click()
    expect(items).to_contain_text("Second brief")
    expect(items).not_to_contain_text("Private brief")
    expect(page.get_by_role("list", name=f"Attempts for execution {ITEM_A_EXECUTION_ID}", exact=True)).to_have_count(0)
    page.get_by_role("button", name=f"Inspect item execution {ITEM_B_EXECUTION_ID}", exact=True).click()
    expect(page.get_by_role("list", name=f"Attempts for execution {ITEM_B_EXECUTION_ID}", exact=True)).to_contain_text("index 1")
    assert not any("/tasks/" in request.path or request.path.endswith("/result") for request in ui.requests if "/runs/loop-run/" in request.path)
    assert all(request.query.get("limit") == ["100"] for request in ui.requests if request.path.endswith("/records"))

@pytest.mark.parametrize("group", [False, True])
def test_collect_records_and_provenance_are_bounded_scoped_and_escape_data(workflow_loops_ui, group):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    key = ("group" if group else "user", LOOP_WORKFLOW_ID, LOOP_RUN_ID, COLLECT_EXECUTION_ID, 1)
    ui.record_pages[key][""]["items"][0]["finding"] = '<img src="https://invalid.example/x" onerror="window.bad=true">'
    expand_history(ui, group=group)
    page.get_by_role("button", name=f"Show execution attempts for {COLLECT_EXECUTION_ID}", exact=True).click()
    attempts = page.get_by_role("list", name=f"Attempts for execution {COLLECT_EXECUTION_ID}", exact=True)
    attempts.get_by_role("button", name="Load complete records", exact=True).click()
    records = page.get_by_role("list", name="Complete saved records", exact=True)
    expect(records).to_contain_text('<img src=')
    expect(records.locator("img")).to_have_count(0)
    attempts.get_by_role("button", name="Inspect contributors", exact=True).click()
    contributors = page.get_by_role("list", name="Saved collection contributors", exact=True)
    expect(contributors).to_contain_text(ITEM_A_EXECUTION_ID)
    expect(contributors).to_contain_text("Collected record offset: 0")
    expect(page.get_by_text("must-not-render-private-journal", exact=False)).to_have_count(0)
    if not group:
        page.get_by_role("button", name="Next contributors page", exact=True).click()
        expect(contributors).to_contain_text(ITEM_B_EXECUTION_ID)
        expect(contributors).not_to_contain_text(ITEM_A_EXECUTION_ID)
        expect(contributors).to_contain_text("Collected record offset: 2")
    reads = [request for request in ui.requests if request.path.endswith(("/records", "/provenance"))]
    assert reads
    assert all(request.query.get("group_id") == ([GROUP_ID] if group else None) for request in reads)
    assert not any(request.path.endswith("/result") for request in reads)


def test_revoked_record_refresh_clears_the_previous_page(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    expand_history(ui)
    page.get_by_role("button", name=f"Show execution attempts for {COLLECT_EXECUTION_ID}", exact=True).click()
    page.get_by_role("button", name="Load complete records", exact=True).click()
    expect(page.get_by_role("list", name="Complete saved records", exact=True)).to_contain_text("Private brief")
    ui.reject_next("GET", f"/api/user/workflows/{LOOP_WORKFLOW_ID}/runs/{LOOP_RUN_ID}/executions/{COLLECT_EXECUTION_ID}/attempts/1/records",
                   status=403, error="Source access could not be confirmed.")
    panel = page.get_by_role("region", name="Complete record inspection", exact=True)
    panel.get_by_role("button", name="Refresh", exact=True).click()
    expect(panel.get_by_role("alert").filter(has_text="no longer have access")).to_be_visible()
    expect(page.get_by_role("list", name="Complete saved records", exact=True)).to_have_count(0)


@pytest.mark.parametrize("group", [False, True])
def test_reporting_diagnostics_project_only_safe_invocation_and_stage_fields(workflow_loops_ui, group):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    attempt = ui.add_reporting_history(group=group, partial=True)
    reporting = attempt["workflow_result"]["reporting"]
    assert "checkpoints" not in reporting
    assert "supported_conclusions" not in reporting
    assert "input_coverage" not in reporting
    reporting["checkpoints"] = {"prefix": "injected-private-checkpoint"}
    reporting["supported_conclusions"] = [{"text": "injected-private-conclusion"}]
    reporting["original_values"] = ["injected-private-original"]
    reporting["context_budget"]["raw_unit_payload"] = "injected-private-unit"
    attempt["workflow_result"]["analysis_consumption"] = {"checkpoints": {"prefix": "raw-consumption-not-public"}}
    expand_history(ui, group=group)
    page.get_by_role("button", name=f"Show execution attempts for {REPORT_EXECUTION_ID}", exact=True).click()
    diagnostics = page.get_by_role("region", name="Saved-record reporting diagnostics", exact=True)
    expect(diagnostics).to_contain_text("Processing mode: Bounded record pages")
    expect(diagnostics).to_contain_text(f"Saved input objects read: {reporting['record_count']}")
    expect(diagnostics).to_contain_text("New model calls (this invocation): 0")
    expect(diagnostics).to_contain_text(f"Reused checkpoint stages: {reporting['checkpoint_replays']}")
    expect(diagnostics).to_contain_text("Estimated request input tokens: 2048")
    expect(diagnostics).to_contain_text("Peak estimated request tokens: 5280")
    expect(diagnostics).to_contain_text("Last completed or replayed stage context")
    expect(diagnostics).to_contain_text("Accepted subset only")
    expect(diagnostics).to_contain_text("complete document-result objects, not their flattened findings")
    expect(diagnostics).to_contain_text("not billed usage or total-run spend")
    expect(diagnostics).to_contain_text("There is no total-run token or spending cap")
    expect(page.get_by_text("injected-private", exact=False)).to_have_count(0)
    expect(page.get_by_text("raw-consumption-not-public", exact=False)).to_have_count(0)
    reads = [request for request in ui.requests if request.path.endswith(f"/{REPORT_EXECUTION_ID}/attempts")]
    assert len(reads) == 1
    assert reads[0].query.get("group_id") == ([GROUP_ID] if group else None)


def test_reporting_diagnostics_never_present_unknown_capacity_as_unlimited(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.add_reporting_history(mode="complete_input", known_limits=False)
    expand_history(ui)
    page.get_by_role("button", name=f"Show execution attempts for {REPORT_EXECUTION_ID}", exact=True).click()
    diagnostics = page.get_by_role("region", name="Saved-record reporting diagnostics", exact=True)
    expect(diagnostics).to_contain_text("Complete saved input (no batching)")
    expect(diagnostics).to_contain_text("Model-sized record pages: 0")
    expect(diagnostics).to_contain_text("New model calls (this invocation): 1")
    expect(diagnostics).to_contain_text("Limit status: unverified")
    expect(diagnostics).to_contain_text("Limit source: compatibility_policy")
    expect(diagnostics).to_contain_text("Context window capacity: Unknown")
    expect(diagnostics).to_contain_text("Unknown limits are not unlimited")


def test_reporting_diagnostics_support_mobile_keyboard_inspection(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    attempt = ui.add_reporting_history()
    attempt["workflow_result"]["reporting"]["context_budget"]["model_id"] = "model-" + "a" * 110
    expand_history(ui)
    page.set_viewport_size({"width": 390, "height": 844})
    toggle = page.get_by_role("button", name=f"Show execution attempts for {REPORT_EXECUTION_ID}", exact=True)
    toggle.focus()
    toggle.press("Enter")
    expect(page.get_by_role("region", name="Saved-record reporting diagnostics", exact=True)).to_be_visible()
    ui.assert_no_overflow()


@pytest.mark.parametrize("malformed", ["negative_count", "array_mode", "stage_array"])
def test_malformed_reporting_diagnostics_do_not_hide_exact_result_inspection(workflow_loops_ui, malformed):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    reporting = ui.add_reporting_history()["workflow_result"]["reporting"]
    if malformed == "negative_count":
        reporting["model_calls"] = -1
    elif malformed == "array_mode":
        reporting["mode"] = ["record_pages"]
    else:
        reporting["context_budget"] = [{"input_tokens": 42}, {"input_tokens": 99}]
    expand_history(ui)
    page.get_by_role("button", name=f"Show execution attempts for {REPORT_EXECUTION_ID}", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="processing diagnostics are unsupported")).to_be_visible()
    expect(page.get_by_role("region", name="Saved-record reporting diagnostics", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Load authoritative output excerpt", exact=True)).to_be_visible()


def test_changing_query_invalidates_an_inflight_preview(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    ui.query_count = 99
    loop = open_loop(ui)
    loop.get_by_label("For each source", exact=True).select_option("workspace_query")
    loop.get_by_label("Query search", exact=True).fill("first query")
    ui.defer_preview = True
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    expect(loop.get_by_role("button", name="Preview loop selection", exact=True)).to_be_disabled()
    loop.get_by_label("Query search", exact=True).fill("new query")
    expect(loop.get_by_role("button", name="Preview loop selection", exact=True)).to_be_enabled()
    ui.release_preview()
    expect(loop.get_by_role("list", name="Loop preview documents", exact=True)).to_have_count(0)
    ui.query_count = 1
    loop.get_by_role("button", name="Preview loop selection", exact=True).click()
    expect(loop.get_by_text("Selected count: 1. Effective ceiling: 500. Within the limit.", exact=True)).to_be_visible()


@pytest.mark.parametrize("malformed", [
    "repeat_path", "wrong_item", "oversize", "invalid_digest", "uppercase_digest", "invalid_index", "too_deep",
])
def test_malformed_frozen_item_pages_fail_closed(workflow_loops_ui, malformed):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    rows = ui.item_pages[("user", LOOP_WORKFLOW_ID, LOOP_RUN_ID)][""]["items"]
    if malformed == "repeat_path":
        rows[0]["iteration_path"] = [{"loop_id": LOOP_ID, "iteration": 1}]
    elif malformed == "wrong_item":
        rows[0]["iteration_path"][0]["item_id"] = "f" * 64
    elif malformed in {"invalid_digest", "uppercase_digest"}:
        digest = "not-a-digest" if malformed == "invalid_digest" else rows[0]["item_id"].upper()
        rows[0]["item_id"] = digest
        rows[0]["iteration_path"][0]["item_id"] = digest
    elif malformed == "invalid_index":
        rows[0]["index"] = 5000
        rows[0]["iteration_path"][0]["index"] = 5000
    elif malformed == "too_deep":
        frame = rows[0]["iteration_path"][0]
        rows[0]["iteration_path"] = [
            {**frame, "loop_id": f"outer-{depth}"} for depth in range(3)
        ] + [frame]
    else:
        rows.extend([copy.deepcopy(rows[0]) for _ in range(50)])
    expand_history(ui)
    page.get_by_role("button", name=f"Show frozen items for {LOOP_EXECUTION_ID}", exact=True).click()
    expect(page.get_by_role("region", name="Frozen item inspection", exact=True).get_by_role("alert").filter(has_text="unsupported response")).to_be_visible()
    expect(page.get_by_role("list", name="Frozen loop items", exact=True)).to_have_count(0)
    assert not any(request.path.endswith("/records") for request in ui.requests)


def test_hybrid_repeat_and_item_runtime_gate_identity_is_not_actionable(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    runtime = ui.workflow_runtimes[("user", LOOP_WORKFLOW_ID, LOOP_RUN_ID)]
    runtime.update(state="waiting_approval", gate={
        "id": "invalid-repeat-gate", "kind": "approval", "unit_id": "task:analyze-task",
        "execution_id": ITEM_A_EXECUTION_ID, "node_id": "analyze-one", "attempt": 1,
        "iteration_path": [{"loop_id": LOOP_ID, "iteration": 1, "item_id": "a" * 64, "index": 1}],
        "choices": ["approve", "reject"],
    })
    expand_history(ui)
    expect(page.get_by_role("alert").filter(has_text="unsupported iteration identity")).to_be_visible()
    expect(page.get_by_role("button", name="Approve task", exact=True)).to_have_count(0)
    assert not any(request.path.endswith("/runtime/decision") for request in ui.writes)


def test_current_item_gate_recheck_does_not_transfer_retry_to_next_item(workflow_loops_ui):
    ui, page = workflow_loops_ui, workflow_loops_ui.page
    key = ("user", LOOP_WORKFLOW_ID, LOOP_RUN_ID)
    runtime = ui.workflow_runtimes[key]
    frame = ui.item_pages[key][""]["items"][0]["iteration_path"]
    runtime.update(state="waiting_recovery", gate={
        "id": "item-a-recovery", "kind": "recovery", "unit_id": "task:analyze-task",
        "execution_id": ITEM_A_EXECUTION_ID, "node_id": "analyze-one", "attempt": 1,
        "iteration_path": copy.deepcopy(frame), "choices": ["retry", "cancel"],
        "input_digest": "first-item-input", "reason": "Inspect this exact failed visit before retrying.",
    })
    expand_history(ui)
    page.get_by_role("button", name="Retry task", exact=True).click()
    confirmation = page.get_by_role("dialog", name="Retry task?", exact=True)
    expect(confirmation).to_contain_text(ITEM_A_EXECUTION_ID)
    runtime["version"] += 1
    runtime["gate"].update(
        id="item-b-recovery", execution_id=ITEM_B_EXECUTION_ID,
        iteration_path=copy.deepcopy(ui.item_pages[key]["page-2"]["items"][0]["iteration_path"]),
        input_digest="second-item-input",
    )
    expect(page.get_by_text(f"Execution {ITEM_B_EXECUTION_ID}", exact=False)).to_be_visible(timeout=6000)
    confirmation.get_by_role("button", name="Retry task", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="recovery gate changed")).to_be_visible()
    assert not any(request.path.endswith("/runtime/decision") for request in ui.writes)
