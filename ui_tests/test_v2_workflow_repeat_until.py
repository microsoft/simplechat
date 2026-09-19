# test_v2_workflow_repeat_until.py
"""
Local closed-browser regressions for typed Repeat until and manual continuation.
Version: 0.261.120
Implemented in: 0.261.120

Exercises the actual built V2 SPA, strict guards, scoped API requests and production
definition normalization. Fixtures intercept every request; no live workflow runs.
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

# Shared fixtures configure isolated production imports after local path setup.
from ui_tests.fixtures.workflow_repeat_until import (
    GROUP_ID,
    REPEAT_EXECUTION_ID,
    REPEAT_ID,
    REPEAT_RUN_ID,
    REPEAT_WORKFLOW_ID,
    connect_options,  # noqa: F401
    flow_binding,
    repeat_workflow_record,
    state_binding,
    workflow_repeat_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui


def repeat_block(page):
    return page.get_by_role("region", name="Repeat until block", exact=True)


def task_block(page, name):
    return page.get_by_role("region", name=f"{name} block", exact=True)


def details(block):
    block.get_by_text("Runner, inputs, references and outputs", exact=True).click()


def open_repeat(ui, *, group=False, **kwargs):
    if group:
        ui.open("/groups", **kwargs)
        ui.page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
        ui.page.get_by_role("button", name="Edit Group Repeat review", exact=True).click()
    else:
        ui.open(f"/workspace/workflows?workflow_id={REPEAT_WORKFLOW_ID}", **kwargs)
    return repeat_block(ui.page)


def test_author_repeat_with_explicit_maximum_next_state_and_typed_condition(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui.open("/workspace/workflows")
    page.get_by_role("button", name="Create workflow", exact=True).click()
    page.get_by_label("Workflow name", exact=True).fill("Authored Repeat review")
    page.get_by_label("Model", exact=True).select_option(label="Workspace GPT \u00b7 aoai")
    page.get_by_role("button", name="Enable structured control flow", exact=True).click()
    page.get_by_role("button", name="Convert draft", exact=True).click()
    page.get_by_label("Task name", exact=True).fill("Seed review")
    seed = task_block(page, "Seed review")
    seed.get_by_label("Instructions", exact=True).fill("Return ready false in the declared JSON schema.")
    details(seed)
    seed.get_by_label("Output contract for Seed review", exact=True).select_option("json")
    seed.get_by_label("Decision field name", exact=True).fill("ready")
    seed.get_by_role("button", name="Add decision field", exact=True).click()
    page.get_by_role("button", name="Add Repeat until to Main", exact=True).click()
    repeat = repeat_block(page)
    maximum = repeat.get_by_label("Maximum rounds before manual continuation", exact=True)
    expect(maximum).to_have_value("")
    expect(maximum).to_be_focused()
    expect(repeat.get_by_role("alert")).to_contain_text("Choose an explicit maximum")
    maximum.fill("2")
    repeat.get_by_role("button", name="Add state slot", exact=True).click()
    expect(repeat.get_by_label("State 1 name", exact=True)).to_be_focused()
    repeat.get_by_label("State 1 name", exact=True).fill("review")
    repeat.get_by_label("State 1 kind", exact=True).select_option("json")
    repeat.get_by_label("State 1 initial producer", exact=True).select_option(label="Seed review")
    repeat.get_by_label("State 1 initial output", exact=True).select_option("json")
    repeat.get_by_role("button", name="State 1 use initial schema", exact=True).click()
    repeat.get_by_role("button", name="Add task to Repeat body", exact=True).click()
    repeat.get_by_label("Task name", exact=True).fill("Review again")
    review = task_block(page, "Review again")
    review.get_by_label("Instructions", exact=True).fill("Review the current saved decision and produce the next ready Boolean.")
    details(review)
    review.get_by_role("button", name="Add review again inputs input", exact=True).click()
    review.get_by_label("Review again inputs input 1 name", exact=True).fill("review")
    review.get_by_label("Review again inputs input 1 source", exact=True).select_option("repeat_state")
    expect(review.get_by_label("Review again inputs input 1 state", exact=True)).to_have_value("review")
    expect(review.get_by_label("Review again inputs input 1 allow partial", exact=True)).not_to_be_checked()
    review.get_by_label("Output contract for Review again", exact=True).select_option("json")
    review.get_by_label("Decision field name", exact=True).fill("ready")
    review.get_by_role("button", name="Add decision field", exact=True).click()
    outputs = repeat.get_by_role("group", name="Repeat body outputs", exact=True)
    outputs.get_by_role("button", name="Add repeat body outputs input", exact=True).click()
    outputs.get_by_label("Repeat body outputs input 1 name", exact=True).fill("next_review")
    outputs.get_by_label("Repeat body outputs input 1 producer", exact=True).select_option(label="Review again")
    outputs.get_by_label("Repeat body outputs input 1 output", exact=True).select_option("json")
    repeat.get_by_label("State 1 next body output", exact=True).select_option("next_review")
    repeat.get_by_label("Stop after a round when left input", exact=True).select_option("review")
    repeat.get_by_label("Stop after a round when left field", exact=True).select_option("/ready")
    repeat.get_by_role("button", name="Add Repeat export", exact=True).click()
    repeat.get_by_label("Repeat export 1 name", exact=True).fill("review")
    repeat.get_by_label("Repeat export 1 output", exact=True).select_option("next_review")
    ui.assert_no_overflow()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_have_count(0)
    payload = ui.workflow_writes[-1].body
    node = payload["flow"]["nodes"][1]
    assert node["kind"] == "repeat_until" and node["max_iterations"] == 2
    assert set(node) == {"id", "kind", "max_iterations", "state", "body", "until", "exports"}
    assert node["state"][0]["initial"] == {
        "kind": "node_output", "node_id": payload["flow"]["nodes"][0]["id"], "output": "json", "scope": "current",
    }
    assert node["state"][0]["next"] == "next_review"
    assert node["state"][0]["output_contract"]["schema"]["properties"]["ready"] == {"type": "boolean"}
    assert node["state"][0]["output_contract"]["allow_partial"] is False
    assert payload["tasks"][1]["inputs"][0]["source"] == {
        "kind": "repeat_state", "loop_id": node["id"], "state_name": "review", "scope": "current",
    }
    assert node["until"] == {"op": "eq", "left": {"input": "review", "path": "/ready"}, "right": {"literal": True}}
    assert node["exports"] == [{"name": "review", "output": "next_review"}]
    page.get_by_role("button", name="Edit Authored Repeat review", exact=True).click()
    expect(page.get_by_label("Maximum rounds before manual continuation", exact=True)).to_have_value("2")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["flow"] == payload["flow"]
    assert not any(request.path.endswith("/run") for request in ui.writes)


@pytest.mark.parametrize("group", [False, True])
def test_personal_group_mobile_keyboard_roundtrip_preserves_all_typed_state(workflow_repeat_ui, group):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    record = repeat_workflow_record(group=group, collections=True)
    (ui.group_workflows[GROUP_ID] if group else ui.personal_workflows)[REPEAT_WORKFLOW_ID] = record
    repeat = open_repeat(ui, group=group, theme="dark", width=390, height=844)
    ui.assert_no_overflow()
    expect(repeat.get_by_label("State 3 kind", exact=True)).to_have_value("records")
    expect(repeat.get_by_label("State 4 kind", exact=True)).to_have_value("document_results")
    expect(repeat.get_by_label("Repeat body outputs input 3 source", exact=True)).to_have_value("repeat_state")
    expect(repeat.get_by_label("State 3 allow partial", exact=True)).not_to_be_checked()
    maximum = repeat.get_by_label("Maximum rounds before manual continuation", exact=True)
    maximum.focus()
    maximum.press("ArrowUp")
    expect(maximum).to_have_value("3")
    save = page.get_by_role("button", name="Save workflow", exact=True)
    save.focus()
    save.press("Enter")
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    expected = copy.deepcopy(record["flow"])
    expected["nodes"][-1]["max_iterations"] = 3
    assert ui.workflow_writes[-1].body["flow"] == expected
    request = ui.workflow_writes[-1]
    assert request.path == ("/api/group/workflows" if group else "/api/user/workflows")
    assert request.query.get("group_id") == ([GROUP_ID] if group else None)
    assert not any(request.path == "/api/user/settings" and request.method != "GET" for request in ui.requests)
    ui.assert_no_overflow()


@pytest.mark.parametrize("maximum", ["", "0", "-1", "1.5", "1001", "26"])
def test_invalid_or_over_policy_maximum_is_not_clamped_or_saved(workflow_repeat_ui, maximum):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    original = copy.deepcopy(ui.personal_workflows[REPEAT_WORKFLOW_ID])
    repeat = open_repeat(ui)
    repeat.get_by_label("Maximum rounds before manual continuation", exact=True).fill(maximum)
    expect(repeat.get_by_role("alert")).to_contain_text("administrator ceiling" if maximum == "26" else "whole number from 1 to 1,000")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_be_visible()
    assert not ui.workflow_writes
    assert ui.personal_workflows[REPEAT_WORKFLOW_ID] == original


def open_repeat_run(ui, *, group=False, **kwargs):
    page = ui.page
    ui.open("/groups" if group else "/workspace/workflows", **kwargs)
    if group:
        page.get_by_label("Group workspace", exact=True).select_option(GROUP_ID)
    row = page.get_by_role("listitem").filter(has_text="Group Repeat review" if group else "Repeat review").first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    return row


def open_rounds(ui):
    ui.page.get_by_role("button", name=f"Show Repeat rounds for {REPEAT_EXECUTION_ID}", exact=True).click()
    return ui.page.get_by_role("region", name="Repeat round inspection", exact=True)


def runtime_key(group=False):
    return ("group" if group else "user", REPEAT_WORKFLOW_ID, REPEAT_RUN_ID)


def decision_writes(ui):
    return [request for request in ui.writes if request.path.endswith("/runtime/decision")]


def confirm_repeat(page, size=2):
    page.get_by_role("button", name="Continue Repeat", exact=True).click()
    dialog = page.get_by_role("dialog", name="Continue Repeat?", exact=True)
    dialog.get_by_role("button", name=f"Continue Repeat for up to another {size} rounds", exact=True).click()
    return dialog


@pytest.mark.parametrize("group", [False, True])
def test_manual_continue_is_explicit_scoped_and_preserves_all_frozen_budgets(workflow_repeat_ui, group):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui.repeat_ceiling = 1
    ui.workflow_runtimes[runtime_key(group)]["can_resume"] = True
    frozen = copy.deepcopy(ui.workflow_runtimes[runtime_key(group)]["limits"])
    open_repeat_run(ui, group=group, width=390 if group else 1440, height=844 if group else 900)
    progress = page.get_by_role("region", name="Repeat progress", exact=True)
    expect(progress).to_contain_text("Automatic batch 1: 2 of 2 rounds admitted")
    expect(page.get_by_text("The stop condition is still unmet. Saved state is retained.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Resume run", exact=True)).to_have_count(0)
    assert not decision_writes(ui)
    button = page.get_by_role("button", name="Continue Repeat", exact=True)
    button.focus()
    button.press("Enter")
    dialog = page.get_by_role("dialog", name="Continue Repeat?", exact=True)
    expect(dialog).to_contain_text("original deadline are unchanged")
    assert not decision_writes(ui)
    ui.assert_no_overflow()
    confirm = dialog.get_by_role("button", name="Continue Repeat for up to another 2 rounds", exact=True)
    confirm.focus()
    confirm.press("Enter")
    expect(dialog).to_have_count(0)
    expect(progress).to_contain_text("Automatic batch 2: 0 of 2 rounds admitted")
    expect(progress).to_contain_text("Next lifetime round: 3")
    assert len(ui.repeat_grants) == 1
    request = ui.repeat_grants[0]
    assert request.path == f"/api/{'group' if group else 'user'}/workflows/{REPEAT_WORKFLOW_ID}/runs/{REPEAT_RUN_ID}/runtime/decision"
    assert request.query.get("group_id") == ([GROUP_ID] if group else None)
    assert set(request.body) == {"expected_version", "gate_id", "choice", "request_id"}
    assert request.body["expected_version"] == 10
    assert request.body["gate_id"] == "repeat-limit-gate-1"
    assert request.body["choice"] == "continue_repeat"
    assert re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", request.body["request_id"])
    updated = ui.workflow_runtimes[runtime_key(group)]
    assert updated["limits"] == frozen
    assert updated["repeat_progress"]["completed_iteration"] == 1
    assert updated["repeat_progress"]["next_iteration"] == 2
    assert not any(request.path.endswith("/runtime/resume") for request in ui.writes)
    audit = page.locator("details").filter(has=page.get_by_text("Runtime decision history", exact=True))
    audit.get_by_role("button", name="Refresh", exact=True).click()
    expect(audit.get_by_role("list", name="Runtime decisions", exact=True)).to_contain_text("fixture-committed-repeat-grant")
    expect(audit).to_contain_text("Explicit grant by workspace-editor-user")


@pytest.mark.parametrize("group", [False, True])
def test_repeat_manual_decisions_use_server_permission_without_hiding_read_views(workflow_repeat_ui, group):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui.runtime_can_decide[runtime_key(group)] = False
    open_repeat_run(ui, group=group)
    expect(page.get_by_role("region", name="Repeat progress", exact=True)).to_be_visible()
    expect(page.get_by_text("you do not have permission", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Continue Repeat", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Resume run", exact=True)).to_have_count(0)
    open_rounds(ui)
    expect(page.get_by_role("list", name="Repeat rounds", exact=True)).to_contain_text("Round 1")
    assert not decision_writes(ui)


def test_stale_repeat_decision_refreshes_real_gate_and_requires_another_confirmation(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    open_repeat_run(ui)
    ui.stale_next_runtime_decision()
    confirm_repeat(page)
    expect(page.get_by_role("alert").filter(has_text="Runtime changed before your decision")).to_be_visible()
    assert not ui.repeat_grants
    assert len(decision_writes(ui)) == 1
    confirm_repeat(page)
    expect(page.get_by_role("dialog", name="Continue Repeat?", exact=True)).to_have_count(0)
    writes = decision_writes(ui)
    assert len(writes) == 2 and len(ui.repeat_grants) == 1
    assert writes[0].body["request_id"] != writes[1].body["request_id"]
    assert writes[1].body["expected_version"] == 11 and writes[1].body["gate_id"] == "repeat-limit-refreshed"
    assert ui.workflow_runtimes[runtime_key()]["repeat_counts"]["continuation_count"] == 1


def test_transient_repeat_failure_reuses_request_uuid_without_double_grant(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    open_repeat_run(ui)
    ui.fail_next_decision_status = 503
    confirm_repeat(page)
    expect(page.get_by_role("alert").filter(has_text="Retry uses the same request id for this gate")).to_be_visible()
    assert not ui.repeat_grants
    confirm_repeat(page)
    expect(page.get_by_role("dialog", name="Continue Repeat?", exact=True)).to_have_count(0)
    writes = decision_writes(ui)
    assert len(writes) == 2 and len(ui.repeat_grants) == 1
    assert writes[0].body["request_id"] == writes[1].body["request_id"]


def test_repeat_confirmation_cannot_transfer_to_a_changed_gate(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    open_repeat_run(ui)
    page.get_by_role("button", name="Continue Repeat", exact=True).click()
    changed = copy.deepcopy(ui.workflow_runtimes[runtime_key()])
    changed["version"] += 1
    changed["gate"]["id"] = "new-repeat-exhaustion"
    ui.transition_runtime_on_get(REPEAT_WORKFLOW_ID, REPEAT_RUN_ID, ui.runtime_get_count[runtime_key()] + 1, changed)
    expect(page.get_by_text("Version 11", exact=True)).to_be_visible(timeout=10000)
    page.get_by_role("dialog", name="Continue Repeat?", exact=True).get_by_role(
        "button", name="Continue Repeat for up to another 2 rounds", exact=True,
    ).click()
    expect(page.get_by_role("alert").filter(has_text="Repeat gate changed while you were reviewing")).to_be_visible()
    assert not decision_writes(ui)
    assert not ui.repeat_grants


@pytest.mark.parametrize("blocker", ["admissions", "deadline"])
def test_repeat_grant_cannot_extend_global_admissions_or_deadline(workflow_repeat_ui, blocker):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    limits = ui.workflow_runtimes[runtime_key()]["limits"]
    if blocker == "admissions":
        limits["admitted_count"] = limits["max_executions"]
    else:
        limits["deadline_at"] = "2000-01-01T00:00:00Z"
    open_repeat_run(ui)
    expect(page.get_by_role("button", name="Continue Repeat", exact=True)).to_be_disabled()
    expect(page.get_by_role("alert").filter(has_text="exhausted" if blocker == "admissions" else "expired")).to_be_visible()
    expect(page.get_by_role("button", name="Resume run", exact=True)).to_have_count(0)
    assert not decision_writes(ui)


@pytest.mark.parametrize("code", ["deadline_exceeded", "execution_budget_exceeded"])
def test_returned_cancel_only_budget_gate_overrides_retained_repeat_progress(workflow_repeat_ui, code):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    runtime = ui.workflow_runtimes[runtime_key()]
    runtime["gate"] = {
        "id": "global-budget-gate", "kind": "pause", "unit_id": REPEAT_ID, "reason_code": code,
        "choices": ["cancel"], "reason": "The global run budget is exhausted. Cancel and start a new run.",
    }
    if code == "deadline_exceeded":
        runtime["limits"]["deadline_at"] = "2000-01-01T00:00:00Z"
    else:
        runtime["limits"]["admitted_count"] = 5000
    open_repeat_run(ui)
    expect(page.get_by_role("region", name="Repeat progress", exact=True)).to_contain_text("waiting manual continue")
    expect(page.get_by_role("button", name="Continue Repeat", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Resume run", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Cancel run", exact=True).click()
    expect(page.get_by_role("region", name="Repeat progress", exact=True)).to_contain_text("State: cancelled")
    request = decision_writes(ui)[-1]
    assert request.body["gate_id"] == "global-budget-gate"
    assert request.body["choice"] == "cancel"
    assert not ui.repeat_grants


@pytest.mark.parametrize("malformed", [
    "hybrid_path", "private_summary", "oversized_batch", "missing_policy", "resume_choice", "missing_summary",
    "wrong_kind", "boolean_count", "missing_gate_id", "boolean_version", "lifetime_reset",
])
def test_unsupported_repeat_gate_shapes_never_enable_decisions(workflow_repeat_ui, malformed):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    runtime = ui.workflow_runtimes[runtime_key()]
    if malformed == "hybrid_path":
        runtime["gate"]["iteration_path"] = [{"loop_id": REPEAT_ID, "iteration": 1, "item_id": "a" * 64}]
    elif malformed == "private_summary":
        runtime["gate"]["repeat"]["state_ref"] = "private-state-reference-must-not-render"
    elif malformed == "oversized_batch":
        runtime["gate"]["repeat"]["batch_size"] = 1001
    elif malformed == "missing_policy":
        runtime["limits"].pop("max_repeat_iterations")
    elif malformed == "resume_choice":
        runtime["gate"]["choices"] = ["continue_repeat", "resume", "cancel"]
    elif malformed == "missing_summary":
        runtime["gate"].pop("repeat")
    elif malformed == "wrong_kind":
        runtime["gate"]["kind"] = "approval"
    elif malformed == "boolean_count":
        runtime["gate"]["repeat"]["completed_count"] = True
    elif malformed == "missing_gate_id":
        runtime["gate"].pop("id")
    elif malformed == "boolean_version":
        runtime["version"] = True
    else:
        runtime["gate"]["repeat"].update(completed_count=1001, completed_iteration=1000, next_iteration=1001)
    open_repeat_run(ui)
    expect(page.get_by_role("alert").filter(has_text=re.compile("unsupported|invalid frozen Repeat limits"))).to_be_visible()
    expect(page.get_by_role("button", name="Continue Repeat", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Resume run", exact=True)).to_have_count(0)
    expect(page.get_by_text("private-state-reference-must-not-render", exact=False)).to_have_count(0)
    assert not decision_writes(ui)


@pytest.mark.parametrize("group", [False, True])
def test_repeat_round_and_state_paging_reads_only_exact_selected_producers(workflow_repeat_ui, group):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui._seed_repeat_run("group" if group else "user", partial=True)
    open_repeat_run(ui, group=group)
    rounds = open_rounds(ui)
    expect(rounds.get_by_role("list", name="Repeat rounds", exact=True).get_by_role("listitem")).to_have_count(1)
    expect(rounds).to_contain_text("false (unmet)")
    assert not any(request.path.endswith(("/state", "/records", "/result")) for request in ui.requests)
    rounds.get_by_role("button", name="State after round 1", exact=True).click()
    state = page.get_by_role("region", name="State after round 1", exact=True)
    expect(state).to_contain_text("review-round-0 · attempt 2 · output json")
    state.get_by_role("button", name="Load json output excerpt", exact=True).click()
    expect(state).to_contain_text("Retained exact review")
    result = [request for request in ui.requests if request.path.endswith("/result")][-1]
    assert result.path.endswith("/executions/review-round-0/attempts/2/result")
    assert result.query["output"] == ["json"] and result.query["limit"] == ["2000"]
    assert result.query.get("group_id") == ([GROUP_ID] if group else None)
    state.get_by_role("button", name="Next state page", exact=True).click()
    expect(state).not_to_contain_text("Retained exact review")
    expect(state).to_contain_text("accepted_partial")
    expect(state).to_contain_text("original accepted records are retained")
    expect(state.get_by_label("Retained prior coverage for state records", exact=True)).to_contain_text("complete: false")
    records_slot = state.get_by_role("list", name="Saved state after round 1", exact=True).get_by_role("listitem").filter(has_text="records (records)").first
    records_slot.get_by_role("button", name="Load complete records", exact=True).click()
    saved = records_slot.get_by_role("list", name="Complete saved records", exact=True)
    expect(saved.get_by_role("listitem")).to_have_count(100)
    expect(saved).to_contain_text("Original finding 0")
    records_slot.get_by_role("button", name="Next records page", exact=True).click()
    expect(saved.get_by_role("listitem")).to_have_count(100)
    expect(saved).to_contain_text("Original finding 100")
    expect(saved).not_to_contain_text('"Original finding 0"')
    records_slot.get_by_role("button", name="Inspect contributors", exact=True).click()
    expect(records_slot.get_by_role("list", name="Saved collection contributors", exact=True)).to_contain_text("seed-records")
    record_reads = [request for request in ui.requests if request.path.endswith("/records")]
    assert len(record_reads) == 2
    assert all(request.query["limit"] == ["100"] and request.query["output"] == ["records"] for request in record_reads)
    rounds.get_by_role("button", name="Next rounds page", exact=True).click()
    expect(page.get_by_role("region", name="State after round 1", exact=True)).to_have_count(0)
    expect(rounds.get_by_role("list", name="Repeat rounds", exact=True)).to_contain_text("Round 2")
    assert not decision_writes(ui)


def test_lifetime_round_1001_remains_distinct_and_uncommitted_after_state_is_not_empty_success(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui._seed_repeat_run("user", completed_count=1000, batch_size=1000, running_round=True, partial=True)
    open_repeat_run(ui, width=390, height=844, theme="dark")
    progress = page.get_by_role("region", name="Repeat progress", exact=True)
    expect(progress).to_contain_text("Lifetime completed rounds: 1000")
    expect(progress).to_contain_text("Automatic batch 2: 1 of 1000 rounds admitted")
    expect(progress).to_contain_text("Next lifetime round: 1001")
    rounds = open_rounds(ui)
    for _ in range(20):
        rounds.get_by_role("button", name="Next rounds page", exact=True).click()
    expect(rounds.get_by_role("list", name="Repeat rounds", exact=True).get_by_role("listitem")).to_have_count(1)
    expect(rounds).to_contain_text("Round 1001")
    expect(rounds).to_contain_text("Not evaluated")
    rounds.get_by_role("button", name="State after round 1001", exact=True).click()
    state = page.get_by_role("region", name="State after round 1001", exact=True)
    expect(state).to_contain_text("not committed or available yet")
    expect(state).to_contain_text("not an empty eligible result")
    expect(state.get_by_role("button", name=re.compile("^Load .* output excerpt$"))).to_have_count(0)
    decisions = page.get_by_role("list", name="Runtime decisions", exact=True)
    expect(decisions).to_contain_text("Manual continuation")
    expect(decisions).to_contain_text("workspace-editor-user")
    expect(decisions).to_contain_text("fixture-repeat-grant")
    assert len([request for request in ui.requests if request.path.endswith("/iterations")]) == 21
    assert all(request.query["limit"] == ["50"] for request in ui.requests if request.path.endswith("/iterations"))
    assert not decision_writes(ui)
    ui.assert_no_overflow()


@pytest.mark.parametrize("malformed", [
    "hybrid_path", "predicate_string", "batch_reset", "private_ref", "too_many",
    "summary_state", "state_array", "missing_snapshot_flag",
])
def test_repeat_iteration_metadata_is_strict_and_never_loads_saved_values_on_failure(workflow_repeat_ui, malformed):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    pages = ui.repeat_iteration_pages[runtime_key()]
    rows = pages[""]["items"]
    if malformed == "hybrid_path":
        rows[0]["iteration_path"][0]["index"] = 0
    elif malformed == "predicate_string":
        rows[0]["condition_result"] = "false"
    elif malformed == "batch_reset":
        rows[0]["iteration"] = 1000
        rows[0]["iteration_path"][0]["iteration"] = 1000
    elif malformed == "private_ref":
        rows[0]["after_state_ref"] = "private-state-reference"
    elif malformed == "summary_state":
        rows[0]["state"] = "waiting_manual_continue"
    elif malformed == "state_array":
        rows[0]["state"] = ["completed"]
    elif malformed == "missing_snapshot_flag":
        ui.repeat_iterations_override = {
            "repeat_execution_id": REPEAT_EXECUTION_ID,
            "repeat": copy.deepcopy(ui.workflow_runtimes[runtime_key()]["repeat_progress"]),
            "iterations": copy.deepcopy(rows), "next_cursor": pages[""]["next_cursor"],
            "total_count": sum(len(value["items"]) for value in pages.values()),
        }
    else:
        rows.extend(copy.deepcopy(rows[0]) for _ in range(50))
    open_repeat_run(ui)
    rounds = open_rounds(ui)
    expect(rounds.get_by_role("alert").filter(has_text="unsupported response")).to_be_visible()
    expect(rounds.get_by_role("list", name="Repeat rounds", exact=True).get_by_role("listitem")).to_have_count(0)
    assert not any(request.path.endswith(("/state", "/result", "/records")) for request in ui.requests)


@pytest.mark.parametrize("malformed", [
    "phase", "execution", "private_ref", "any_kind", "validation", "prior_coverage", "duplicate",
    "missing_partial_flag", "missing_snapshot_flag", "per_slot_partial", "unavailable_before",
])
def test_state_slot_metadata_rejects_wrong_selectors_and_unsupported_shapes(workflow_repeat_ui, malformed):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    states = ui._state_slots(0, "before", False)[:2]
    response = {
        "iteration": 0, "phase": "before", "repeat_execution_id": REPEAT_EXECUTION_ID,
        "available": True, "total_count": 4, "states": states, "next_cursor": "offset-2",
        "partial": False, "source_snapshot_changed": False,
    }
    if malformed == "phase":
        response["phase"] = "after"
    elif malformed == "execution":
        response["repeat_execution_id"] = "another-execution"
    elif malformed == "private_ref":
        states[0]["source"]["result_ref"] = "private-result-reference"
    elif malformed == "any_kind":
        states[0]["kind"] = "any"
    elif malformed == "validation":
        states[0]["workflow_validation"]["eligible"] = "true"
    elif malformed == "prior_coverage":
        states[0]["prior_coverage"] = {"result_ref": {"id": "private-result-reference"}}
    elif malformed == "missing_partial_flag":
        response.pop("partial")
    elif malformed == "missing_snapshot_flag":
        response.pop("source_snapshot_changed")
    elif malformed == "per_slot_partial":
        states[0]["partial"] = True
    elif malformed == "unavailable_before":
        response.update({"available": False, "states": [], "total_count": 0, "next_cursor": None})
        response.pop("partial")
        response.pop("source_snapshot_changed")
    else:
        states[1] = copy.deepcopy(states[0])
    ui.repeat_state_override = response
    open_repeat_run(ui)
    rounds = open_rounds(ui)
    rounds.get_by_role("button", name="State before round 1", exact=True).click()
    state = page.get_by_role("region", name="State before round 1", exact=True)
    expect(state.get_by_role("alert").filter(has_text=re.compile("unsupported|conflicting identities"))).to_be_visible()
    expect(state.get_by_role("list", name="Saved state before round 1", exact=True).get_by_role("listitem")).to_have_count(0)
    assert not any(request.path.endswith(("/result", "/records")) for request in ui.requests)


@pytest.mark.parametrize("flag", ["partial", "source_snapshot_changed"])
def test_uncommitted_after_state_rejects_committed_only_flags(workflow_repeat_ui, flag):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui._seed_repeat_run("user", completed_count=1, batch_size=2, running_round=True)
    ui.repeat_state_override = {
        "repeat_execution_id": REPEAT_EXECUTION_ID, "iteration": 1, "phase": "after",
        "available": False, "states": [], "next_cursor": None, "total_count": 0, flag: False,
    }
    open_repeat_run(ui)
    rounds = open_rounds(ui)
    rounds.get_by_role("button", name="Next rounds page", exact=True).click()
    rounds.get_by_role("button", name="State after round 2", exact=True).click()
    state = page.get_by_role("region", name="State after round 2", exact=True)
    expect(state.get_by_role("alert").filter(has_text="unsupported response")).to_be_visible()
    expect(state.get_by_role("button", name=re.compile("^Load .* output excerpt$"))).to_have_count(0)
    assert not any(request.path.endswith(("/result", "/records")) for request in ui.requests)


def test_revoked_repeat_state_refresh_clears_cached_metadata_and_content(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    open_repeat_run(ui)
    open_rounds(ui).get_by_role("button", name="State before round 1", exact=True).click()
    state = page.get_by_role("region", name="State before round 1", exact=True)
    state.get_by_role("button", name="Load text output excerpt", exact=True).click()
    expect(state).to_contain_text("Retained exact draft")
    ui.reject_next(
        "GET", f"/api/user/workflows/{REPEAT_WORKFLOW_ID}/runs/{REPEAT_RUN_ID}/executions/{REPEAT_EXECUTION_ID}/iterations/0/state",
        status=403, error="Source access could not be confirmed.",
    )
    state.get_by_role("button", name="Refresh", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="no longer have access")).to_be_visible()
    expect(page.get_by_text("Retained exact draft", exact=False)).to_have_count(0)
    expect(page.get_by_role("list", name="Saved state before round 1", exact=True)).to_have_count(0)


def test_repeat_final_named_records_use_existing_exact_reader(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui.complete_with_records_export()
    open_repeat_run(ui)
    rounds = open_rounds(ui)
    rounds.get_by_role("button", name="Next rounds page", exact=True).click()
    expect(rounds).to_contain_text("true (satisfied)")
    rounds.get_by_role("button", name="Inspect Repeat final outputs", exact=True).click()
    records = rounds.get_by_role("region", name="Complete record inspection", exact=True)
    expect(records.get_by_label("Complete records output", exact=True)).to_have_value("findings")
    records.get_by_role("button", name="Load complete records", exact=True).click()
    expect(records.get_by_role("list", name="Complete saved records", exact=True)).to_contain_text("Original finding 0")
    request = [request for request in ui.requests if request.path.endswith("/records")][-1]
    assert request.path.endswith(f"/executions/{REPEAT_EXECUTION_ID}/attempts/1/records")
    assert request.query["output"] == ["findings"]
    assert not ui.writes


@pytest.mark.parametrize("kind", ["records", "document_results"])
def test_current_repeat_collection_can_be_selected_for_saved_record_reporting(workflow_repeat_ui, kind):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui.personal_workflows[REPEAT_WORKFLOW_ID] = repeat_workflow_record(collections=True)
    open_repeat(ui)
    revise = task_block(page, "Revise draft")
    details(revise)
    revise.get_by_role("button", name="Add revise draft inputs input", exact=True).click()
    revise.get_by_label("Revise draft inputs input 3 source", exact=True).select_option("repeat_state")
    revise.get_by_label("Revise draft inputs input 3 state", exact=True).select_option(kind)
    revise.get_by_label("Large saved inputs", exact=True).select_option("saved_record_report")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    saved = ui.workflow_writes[-1].body["tasks"][2]
    assert saved["input_processing"] == "saved_record_report"
    assert saved["inputs"][2]["source"] == state_binding("unused", kind, kind)["source"]
    assert saved["inputs"][2]["expected_kind"] == kind
    assert not any(request.path.endswith("/run") for request in ui.writes)


@pytest.mark.parametrize("kind", ["records", "document_results"])
def test_for_each_freezes_current_repeat_collection_with_typed_item_fields(workflow_repeat_ui, kind):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    record = repeat_workflow_record(collections=True)
    loop_id = "review-saved-items"
    output = "documents" if kind == "document_results" else "records"
    record["flow"]["nodes"][-1]["body"]["nodes"].insert(0, {
        "id": loop_id, "kind": "for_each", "item_key": "source_identity", "max_items": 5,
        "iterable": {"kind": "input", "name": "rows"},
        "inputs": [flow_binding("rows", f"seed-{kind}", output, kind=kind)],
        "body": {"id": "saved-item-body", "outputs": [], "nodes": [{
            "id": "row-filter", "kind": "if",
            "inputs": [{
                "name": "item", "source": {"kind": "loop_item", "loop_id": loop_id, "scope": "current"},
                "required": True, "expected_kind": "json", "allow_partial": False,
            }],
            "condition": {"op": "eq", "left": {"input": "item", "path": "/value/finding"}, "right": {"literal": "review"}},
            "then": {"id": "matching-items", "nodes": []},
            "else": {"id": "other-items", "nodes": []},
            "join": {"id": "row-filter-join", "exports": []},
        }]},
    })
    ui.personal_workflows[REPEAT_WORKFLOW_ID] = record
    open_repeat(ui)
    loop = page.get_by_role("region", name="For each block", exact=True)
    loop.get_by_label("Saved collection output", exact=True).select_option(
        label=f"Current Repeat {REPEAT_ID} state {kind} ({kind.replace('_', ' ')})",
    )
    expect(loop).to_contain_text("start of this Repeat round")
    expect(loop.get_by_label("If / else condition left field", exact=True)).to_have_value("/value/finding")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    saved_loop = ui.workflow_writes[-1].body["flow"]["nodes"][-1]["body"]["nodes"][0]
    assert saved_loop["inputs"] == [state_binding("rows", kind, kind)]
    assert saved_loop["body"]["nodes"][0]["condition"]["left"]["path"] == "/value/finding"


def test_nested_repeat_initial_state_is_explicitly_named_outer_state(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    record = repeat_workflow_record()
    outer = record["flow"]["nodes"][-1]
    inner = copy.deepcopy(outer)
    inner["id"] = "nested-refinement"
    inner["body"]["id"] = "nested-refinement-body"
    for slot in inner["state"]:
        slot["initial"] = state_binding(slot["name"], slot["name"], slot["output_contract"]["kind"])["source"]
    for binding in record["tasks"][2]["inputs"]:
        binding["source"]["loop_id"] = inner["id"]
    outer["body"]["nodes"] = [inner]
    outer["body"]["outputs"] = [
        flow_binding("next_draft", inner["id"], "report", kind="text"),
        flow_binding("next_review", inner["id"], "review", kind="json"),
    ]
    ui.personal_workflows[REPEAT_WORKFLOW_ID] = record
    open_repeat(ui)
    nested = repeat_block(page).last
    expect(nested.get_by_label("State 1 initial source", exact=True)).to_have_value("repeat_state")
    expect(nested.get_by_label("State 1 initial Repeat", exact=True)).to_have_value(REPEAT_ID)
    expect(nested.get_by_label("State 1 initial state", exact=True)).to_have_value("draft")
    nested.get_by_label("Maximum rounds before manual continuation", exact=True).fill("3")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    inner["max_iterations"] = 3
    assert ui.workflow_writes[-1].body["flow"] == record["flow"]


def test_permission_loss_closes_open_repeat_confirmation_without_a_grant(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    open_repeat_run(ui, group=True)
    page.get_by_role("button", name="Continue Repeat", exact=True).click()
    dialog = page.get_by_role("dialog", name="Continue Repeat?", exact=True)
    expect(dialog).to_be_visible()
    ui.runtime_can_decide[runtime_key(True)] = False
    expect(dialog).to_have_count(0, timeout=10000)
    expect(page.get_by_role("button", name="Continue Repeat", exact=True)).to_have_count(0)
    assert not decision_writes(ui)
    assert not ui.repeat_grants


def test_repeat_body_attempt_inspection_keeps_round_and_retry_identity(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    open_repeat_run(ui)
    rounds = open_rounds(ui)
    rounds.get_by_role("button", name="Inspect round execution review-round-0", exact=True).click()
    attempts = rounds.get_by_role("list", name="Attempts for execution review-round-0", exact=True)
    expect(attempts).to_contain_text("Attempt 1")
    expect(attempts).to_contain_text("Attempt 2")
    expect(attempts).to_contain_text(f"{REPEAT_ID} (round 1)")
    expect(attempts.get_by_text("No result was committed for this attempt.", exact=True)).to_be_visible()
    attempts.get_by_role("button", name="Load authoritative output excerpt", exact=True).click()
    expect(attempts).to_contain_text("Retained exact review")
    request = [request for request in ui.requests if request.path.endswith("/result")][-1]
    assert request.path.endswith("/executions/review-round-0/attempts/2/result")
    assert request.query["output"] == ["authoritative"]
    assert not decision_writes(ui)


@pytest.mark.parametrize("group", [False, True])
def test_repeat_body_instances_drill_into_nested_rounds_and_frozen_items(workflow_repeat_ui, group):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui.add_nested_inspection("group" if group else "user")
    open_repeat_run(ui, group=group)
    outer = open_rounds(ui)
    outer.get_by_role("button", name="Inspect round execution nested-repeat-execution", exact=True).click()
    expect(page.get_by_role("list", name="Attempts for execution nested-repeat-execution", exact=True)).to_be_visible()
    assert not any("/nested-repeat-execution/iterations" in request.path for request in ui.requests)
    outer.get_by_role("button", name="Show Repeat rounds for nested-repeat-execution", exact=True).click()
    nested = page.get_by_role("region", name="Repeat round inspection", exact=True).last
    expect(nested).to_contain_text(f"{REPEAT_ID} (round 1)")
    expect(nested).to_contain_text("nested-refinement (round 1)")
    expect(nested).to_contain_text("true (satisfied)")
    nested.get_by_role("button", name="State before round 1", exact=True).click()
    expect(nested.get_by_role("region", name="State before round 1", exact=True)).to_contain_text("seed-draft")
    outer.get_by_role("button", name="Inspect round execution nested-each-execution", exact=True).click()
    expect(page.get_by_role("region", name="Repeat round inspection", exact=True)).to_have_count(1)
    assert not any("/nested-each-execution/items" in request.path for request in ui.requests)
    outer.get_by_role("button", name="Show frozen items for nested-each-execution", exact=True).click()
    items = outer.get_by_role("region", name="Frozen item inspection", exact=True)
    expect(items).to_contain_text("Exact saved finding")
    expect(items).to_contain_text(f"{REPEAT_ID} (round 1)")
    reads = [request for request in ui.requests if
             "/nested-repeat-execution/iterations" in request.path or "/nested-each-execution/items" in request.path]
    assert len(reads) == 3
    assert all(request.query["limit"] == ["50"] for request in reads)
    assert all(request.query.get("group_id") == ([GROUP_ID] if group else None) for request in reads)
    assert not any(request.path.endswith(("/result", "/records")) for request in ui.requests)
    assert not ui.writes


def test_invalid_repeat_poll_removes_previous_summary_and_confirmation(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    open_repeat_run(ui)
    page.get_by_role("button", name="Continue Repeat", exact=True).click()
    dialog = page.get_by_role("dialog", name="Continue Repeat?", exact=True)
    expect(dialog).to_be_visible()
    ui.workflow_runtimes[runtime_key()]["gate"]["repeat"]["batch_usage"] = "2"
    expect(dialog).to_have_count(0, timeout=10000)
    expect(page.get_by_role("alert").filter(has_text="unsupported Repeat")).to_be_visible()
    expect(page.get_by_role("region", name="Repeat progress", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Continue Repeat", exact=True)).to_have_count(0)
    assert not decision_writes(ui)


def test_mixed_repeat_and_item_body_gate_keeps_exact_identity_without_granting_another_batch(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui._seed_repeat_run("user", completed_count=1000, batch_size=1000, running_round=True)
    runtime = ui.workflow_runtimes[runtime_key()]
    before = copy.deepcopy(runtime["repeat_progress"])
    runtime["state"] = "waiting_approval"
    runtime["gate"] = {
        "id": "repeat-body-approval", "kind": "approval", "unit_id": "review", "node_id": "review",
        "execution_id": "review-round-1000", "attempt": 2, "choices": ["approve", "reject"],
        "iteration_path": [
            {"loop_id": REPEAT_ID, "iteration": 1000},
            {"loop_id": "each-finding", "item_id": "d" * 64, "index": 7},
        ],
    }
    ui.workflow_runs[REPEAT_WORKFLOW_ID][0]["status"] = "waiting_approval"
    open_repeat_run(ui)
    expect(page.get_by_text(re.compile(r"Execution review-round-1000.*round 1001"))).to_be_visible()
    expect(page.get_by_role("button", name="Continue Repeat", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Approve task", exact=True).click()
    expect(page.get_by_role("button", name="Approve task", exact=True)).to_have_count(0)
    request = decision_writes(ui)[-1]
    assert request.body["gate_id"] == "repeat-body-approval" and request.body["choice"] == "approve"
    assert request.body["expected_version"] == 10
    assert ui.workflow_runtimes[runtime_key()]["repeat_progress"] == before
    assert not ui.repeat_grants


@pytest.mark.parametrize("invalid", ["initial_kind", "next_kind", "optional_next"])
def test_repeat_state_contracts_cannot_coerce_or_silently_omit_atomic_next_slots(workflow_repeat_ui, invalid):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    record = ui.personal_workflows[REPEAT_WORKFLOW_ID]
    node = record["flow"]["nodes"][-1]
    if invalid == "initial_kind":
        node["state"][1]["initial"] = copy.deepcopy(node["state"][0]["initial"])
    elif invalid == "next_kind":
        node["state"][1]["next"] = "next_draft"
    else:
        node["body"]["outputs"][1]["required"] = False
    original = copy.deepcopy(record)
    open_repeat(ui)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="required, declared next body output" if invalid == "optional_next" else "exactly kind json")).to_be_visible()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_be_visible()
    assert not ui.workflow_writes
    assert ui.personal_workflows[REPEAT_WORKFLOW_ID] == original


@pytest.mark.parametrize("maximum", [1, 1000])
def test_explicit_supported_batch_boundaries_save_exactly(workflow_repeat_ui, maximum):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui.repeat_ceiling = 1000
    repeat = open_repeat(ui)
    repeat.get_by_label("Maximum rounds before manual continuation", exact=True).fill(str(maximum))
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["flow"]["nodes"][-1]["max_iterations"] == maximum


def test_partial_current_state_pass_through_requires_explicit_opt_in(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui.personal_workflows[REPEAT_WORKFLOW_ID] = repeat_workflow_record(collections=True)
    repeat = open_repeat(ui)
    expect(repeat.get_by_label("State 3 allow partial", exact=True)).not_to_be_checked()
    repeat.get_by_label("State 3 allow partial", exact=True).check()
    repeat.get_by_label("Repeat body outputs input 3 allow partial", exact=True).check()
    expect(repeat.get_by_text("Partial coverage and limitations stay attached", exact=False)).to_be_visible()
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    node = ui.workflow_writes[-1].body["flow"]["nodes"][-1]
    assert node["state"][2]["output_contract"]["allow_partial"] is True
    assert node["body"]["outputs"][2]["source"] == {
        "kind": "repeat_state", "loop_id": REPEAT_ID, "state_name": "records", "scope": "current",
    }
    assert node["body"]["outputs"][2]["allow_partial"] is True
    assert node["state"][3]["output_contract"]["allow_partial"] is False


@pytest.mark.parametrize("unsupported", ["missing_maximum", "literal_initial", "any_state", "future_field", "future_predicate", "state_source_field"])
def test_unsupported_repeat_definitions_stay_intact_and_read_only(workflow_repeat_ui, unsupported):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    record = ui.personal_workflows[REPEAT_WORKFLOW_ID]
    node = record["flow"]["nodes"][-1]
    if unsupported == "missing_maximum":
        del node["max_iterations"]
    elif unsupported == "literal_initial":
        node["state"][0]["initial"] = {"kind": "literal", "value": "not an admitted saved output"}
    elif unsupported == "any_state":
        node["state"][0]["output_contract"]["kind"] = "any"
    elif unsupported == "future_field":
        node["automatic_continue"] = True
    elif unsupported == "future_predicate":
        node["until"]["expression"] = "unsupported control language"
    else:
        record["tasks"][2]["inputs"][0]["source"]["iteration"] = 42
    original = copy.deepcopy(record)
    ui.open(f"/workspace/workflows?workflow_id={REPEAT_WORKFLOW_ID}")
    expect(page.get_by_role("alert").filter(has_text="cannot safely save")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    assert ui.personal_workflows[REPEAT_WORKFLOW_ID] == original
    assert not ui.workflow_writes


@pytest.mark.parametrize("missing", ["all", "policy", "hard_ceiling"])
def test_missing_repeat_capabilities_preserve_saved_definition_read_only(workflow_repeat_ui, missing):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    original = copy.deepcopy(ui.personal_workflows[REPEAT_WORKFLOW_ID])
    if missing == "all":
        ui.repeat_capabilities = False
    elif missing == "policy":
        ui.repeat_ceiling = None
    else:
        ui.repeat_hard_ceiling = None
    ui.open(f"/workspace/workflows?workflow_id={REPEAT_WORKFLOW_ID}")
    expect(page.get_by_role("alert").filter(has_text="cannot safely save")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Add Repeat until to Main", exact=True)).to_have_count(0)
    assert ui.personal_workflows[REPEAT_WORKFLOW_ID] == original
    assert not ui.workflow_writes


@pytest.mark.parametrize("hard_ceiling", [0, 999, 1001, "1000", True])
def test_invalid_advertised_repeat_hard_ceiling_never_enables_authoring(workflow_repeat_ui, hard_ceiling):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    original = copy.deepcopy(ui.personal_workflows[REPEAT_WORKFLOW_ID])
    ui.repeat_hard_ceiling = hard_ceiling
    ui.open(f"/workspace/workflows?workflow_id={REPEAT_WORKFLOW_ID}")
    expect(page.get_by_role("alert").filter(has_text="invalid loop capabilities or limits")).to_be_visible()
    expect(page.get_by_role("button", name="Save workflow", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Add Repeat until to Main", exact=True)).to_have_count(0)
    assert ui.personal_workflows[REPEAT_WORKFLOW_ID] == original
    assert not ui.workflow_writes


def test_lowered_repeat_policy_preserves_schema_valid_authored_maximum(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    ui.personal_workflows[REPEAT_WORKFLOW_ID]["flow"]["nodes"][-1]["max_iterations"] = 30
    original = copy.deepcopy(ui.personal_workflows[REPEAT_WORKFLOW_ID])
    repeat = open_repeat(ui)
    maximum = repeat.get_by_label("Maximum rounds before manual continuation", exact=True)
    expect(maximum).to_have_value("30")
    expect(maximum).to_be_enabled()
    expect(page.get_by_role("alert").filter(has_text="cannot safely save")).to_have_count(0)
    expect(repeat.get_by_role("alert")).to_contain_text("administrator ceiling of 25 for new runs")
    expect(repeat.get_by_role("alert")).to_contain_text("authored value is preserved")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(maximum).to_have_value("30")
    assert ui.personal_workflows[REPEAT_WORKFLOW_ID] == original
    assert not ui.workflow_writes
    maximum.fill("25")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Edit workflow", exact=True)).to_have_count(0)
    assert ui.workflow_writes[-1].body["flow"]["nodes"][-1]["max_iterations"] == 25


def test_repeat_inherited_runner_and_body_tasks_disallow_hosted_without_hiding_outside_choices(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    open_repeat(ui)
    page.get_by_label("Runner type", exact=True).select_option("agent")
    hosted = page.get_by_label("Agent", exact=True).locator("option").filter(has_text="Hosted reviewer")
    expect(hosted).to_have_attribute("disabled", "")
    body = task_block(page, "Revise draft")
    details(body)
    body.get_by_label("Task runner", exact=True).select_option("agent")
    expect(body.get_by_label("Task agent", exact=True).locator("option").filter(has_text="Hosted reviewer")).to_have_attribute("disabled", "")
    outside = task_block(page, "Seed draft")
    details(outside)
    outside.get_by_label("Task runner", exact=True).select_option("agent")
    expect(outside.get_by_label("Task agent", exact=True).locator("option").filter(has_text="Hosted reviewer")).not_to_have_attribute("disabled", "")
    assert not ui.workflow_writes


def test_state_rename_retains_dependent_bindings_and_reports_missing_slot(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    repeat = open_repeat(ui)
    repeat.get_by_label("State 1 name", exact=True).fill("renamed")
    revise = task_block(page, "Revise draft")
    details(revise)
    expect(revise.get_by_label("Revise draft inputs input 1 state", exact=True)).to_have_value("draft")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="named current state slot")).to_be_visible()
    assert not ui.workflow_writes


def test_stale_save_keeps_repeat_draft_and_exact_next_state(workflow_repeat_ui):
    ui, page = workflow_repeat_ui, workflow_repeat_ui.page
    repeat = open_repeat(ui)
    repeat.get_by_label("Maximum rounds before manual continuation", exact=True).fill("7")
    ui.mutate_revision(REPEAT_WORKFLOW_ID)
    page.get_by_role("button", name="Save workflow", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="draft has been retained")).to_be_visible()
    expect(repeat.get_by_label("Maximum rounds before manual continuation", exact=True)).to_have_value("7")
    expect(repeat.get_by_label("State 1 next body output", exact=True)).to_have_value("next_draft")
    assert not ui.workflow_writes
