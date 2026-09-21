# test_v2_workflow_control_runtime.py
"""
UI tests for V2 workflow control-runtime run inspection.
Version: 0.261.127
Implemented in: 0.261.116

These tests use the real V2 SPA bundle with a closed API fixture. They cover
definition v3 execution inspection, scoped runtime decisions, authoritative
attempt output excerpts, and preservation of legacy v1/v2 task-result
inspection.
"""

import re
import sys
import copy
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.workflow_control_runtime import (  # noqa: E402
    GROUP_ID,
    GROUP_V3_RUN_ID,
    GROUP_V3_WORKFLOW_ID,
    V3_RUN_ID,
    V3_WORKFLOW_ID,
    execution_id,
    connect_options,  # noqa: F401
    workflow_control_ui,  # noqa: F401
)
from ui_tests.fixtures.workflow_editor import WORKFLOW_ID  # noqa: E402


pytestmark = pytest.mark.ui


def expand_run_history(page, workflow_name):
    row = page.get_by_role("listitem").filter(has_text=workflow_name).first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    return row


def result_requests(ui):
    return [request for request in ui.requests if request.path.endswith("/result")]


def test_v3_execution_history_uses_exact_attempt_result_endpoint(workflow_control_ui):
    ui, page = workflow_control_ui, workflow_control_ui.page
    key = ("user", V3_WORKFLOW_ID, V3_RUN_ID)
    # Deliberately unexpected provider fields must never become a debug dump.
    ui.execution_pages[key][""]["items"][1]["decision"]["operands"] = {"private": "raw-secret-token"}
    ui.workflow_runtimes[key]["memory"]["private_journal"] = "private-journal"
    producer_id = execution_id(V3_WORKFLOW_ID, V3_RUN_ID, "evaluate")
    ui.open("/workspace/workflows")
    expand_run_history(page, "Structured branch workflow")

    expect(page.get_by_text("Workflow execution history", exact=True)).to_be_visible()
    expect(page.get_by_text(f"Execution: {producer_id}", exact=True)).to_be_visible()
    expect(page.get_by_text("Reason code: branch_not_selected", exact=True)).to_be_visible()
    expect(page.get_by_text("Selected branch or route: choice then \u00b7 branch then", exact=True)).to_be_visible()
    receipts = page.get_by_role("list", name="Consumed producer references", exact=True)
    expect(receipts).to_contain_text(f"execution {producer_id}")
    expect(receipts).to_contain_text("decision from json")
    expect(receipts).to_contain_text("attempt 2")
    expect(receipts).to_contain_text("Consumed output ref")
    expect(page.get_by_text("raw-secret-token", exact=True)).to_have_count(0)
    expect(page.get_by_text("private-journal", exact=True)).to_have_count(0)

    page.get_by_role("button", name=f"Show execution attempts for {producer_id}", exact=True).click()
    attempts = page.get_by_role("list", name=f"Attempts for execution {producer_id}", exact=True)
    attempt = attempts.get_by_role("listitem").filter(has_text="Attempt 2")
    attempt.get_by_role("button", name="Load authoritative output excerpt", exact=True).click()
    expect(page.get_by_text(f"Authoritative output excerpt from execution {producer_id} attempt 2", exact=False)).to_be_visible()
    expect(attempts.get_by_text("No result was committed for this attempt.", exact=True)).to_be_visible()

    exact_result_path = (
        f"/api/user/workflows/{V3_WORKFLOW_ID}/runs/{V3_RUN_ID}"
        f"/executions/{producer_id}/attempts/2/result"
    )
    assert any(
        request.path == exact_result_path and request.query.get("output") == ["authoritative"]
        for request in result_requests(ui)
    )
    assert not any(
        request.path.startswith(f"/api/user/workflows/{V3_WORKFLOW_ID}/runs/{V3_RUN_ID}/tasks/")
        for request in result_requests(ui)
    )


def test_v3_group_runtime_decisions_keep_scope_and_replace_pages(workflow_control_ui):
    ui, page = workflow_control_ui, workflow_control_ui.page
    review_id = execution_id(GROUP_V3_WORKFLOW_ID, GROUP_V3_RUN_ID, "review")
    producer_id = execution_id(GROUP_V3_WORKFLOW_ID, GROUP_V3_RUN_ID, "evaluate")
    ui.open("/groups")
    ui.select_group(GROUP_ID)
    expect(page.get_by_role("heading", name="Workflows", exact=True)).to_be_visible()
    expand_run_history(page, "Group structured branch workflow")

    expect(page.get_by_text(f"Execution {review_id} \u00b7 Node review \u00b7 Attempt 1", exact=True)).to_be_visible()
    decisions = page.get_by_role("list", name="Runtime decisions", exact=True)
    expect(decisions).to_contain_text("evaluate-recovery-gate")
    expect(page.get_by_text("raw-secret-token", exact=True)).to_have_count(0)

    page.get_by_role("button", name="Next executions page", exact=True).click()
    expect(page.get_by_text(f"Execution: {review_id}", exact=True)).to_be_visible()
    expect(page.get_by_text(f"Execution: {producer_id}", exact=True)).to_have_count(0)

    page.get_by_role("button", name="Next decision page", exact=True).click()
    expect(decisions).to_contain_text("choice else")
    expect(decisions).not_to_contain_text("evaluate-recovery-gate")

    scoped_requests = [
        request for request in ui.requests
        if request.path.startswith(f"/api/group/workflows/{GROUP_V3_WORKFLOW_ID}/runs/{GROUP_V3_RUN_ID}")
    ]
    assert scoped_requests
    assert all(request.query.get("group_id") == [GROUP_ID] for request in scoped_requests)
    assert not any(request.path == "/api/user/settings" and request.method != "GET" for request in ui.requests)


def test_v2_runs_keep_legacy_task_result_inspection(workflow_control_ui):
    ui, page = workflow_control_ui, workflow_control_ui.page
    ui.open("/workspace/workflows")
    expand_run_history(page, "Quarterly review workflow")

    expect(page.get_by_text("Workflow execution history", exact=True)).to_have_count(0)
    expect(page.get_by_text("Collect evidence", exact=True)).to_be_visible()
    page.get_by_role("button", name="Load result excerpt", exact=True).first.click()
    expect(page.get_by_text("First transport excerpt page for the authoritative output.", exact=True)).to_be_visible()

    assert any(
        request.path == f"/api/user/workflows/{WORKFLOW_ID}/runs/run-1/tasks/task-a/result"
        for request in result_requests(ui)
    )
    assert not any(
        request.path.startswith(f"/api/user/workflows/{WORKFLOW_ID}/runs/run-1/executions")
        for request in ui.requests
    )


def test_failed_refresh_clears_cached_execution_receipts(workflow_control_ui):
    ui, page = workflow_control_ui, workflow_control_ui.page
    ui.open("/workspace/workflows")
    expand_run_history(page, "Structured branch workflow")
    expect(page.get_by_role("list", name="Consumed producer references", exact=True)).to_be_visible()
    path = f"/api/user/workflows/{V3_WORKFLOW_ID}/runs/{V3_RUN_ID}/executions"
    ui.failures.append(("GET", path, 403, {"error": "Source access could not be confirmed."}))
    page.get_by_role("button", name="Refresh", exact=True).first.click()
    expect(page.get_by_role("alert").filter(has_text="no longer have access")).to_be_visible()
    expect(page.get_by_role("list", name="Workflow node executions", exact=True)).to_have_count(0)
    expect(page.get_by_role("list", name="Consumed producer references", exact=True)).to_have_count(0)


@pytest.mark.parametrize("malformed", ["null_record", "invalid_cursor", "duplicate_identity"])
def test_malformed_execution_pages_fail_explicitly(workflow_control_ui, malformed):
    ui, page = workflow_control_ui, workflow_control_ui.page
    first = ui.execution_pages[("user", V3_WORKFLOW_ID, V3_RUN_ID)][""]
    if malformed == "null_record":
        first["items"][0] = None
    elif malformed == "invalid_cursor":
        first["next_cursor"] = 123
    else:
        first["items"].append(copy.deepcopy(first["items"][0]))
    ui.open("/workspace/workflows")
    expand_run_history(page, "Structured branch workflow")
    expect(page.get_by_role("alert").filter(has_text=re.compile("unsupported response|conflicting identities"))).to_be_visible()
    expect(page.get_by_role("list", name="Workflow node executions", exact=True)).to_have_count(0)
    assert not result_requests(ui)


def test_attempt_response_cannot_retarget_the_selected_execution(workflow_control_ui):
    ui, page = workflow_control_ui, workflow_control_ui.page
    eid = execution_id(V3_WORKFLOW_ID, V3_RUN_ID, "evaluate")
    attempts = ui.attempt_pages[("user", V3_WORKFLOW_ID, V3_RUN_ID, eid)][""]["items"]
    attempts[-1]["execution_id"] = execution_id(V3_WORKFLOW_ID, V3_RUN_ID, "review")
    ui.open("/workspace/workflows")
    expand_run_history(page, "Structured branch workflow")
    page.get_by_role("button", name=f"Show execution attempts for {eid}", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="unsupported response")).to_be_visible()
    expect(page.get_by_role("button", name="Load authoritative output excerpt", exact=True)).to_have_count(0)
    assert not result_requests(ui)


def test_recovery_confirmation_does_not_transfer_to_a_new_attempt(workflow_control_ui):
    ui, page = workflow_control_ui, workflow_control_ui.page
    key = ("group", GROUP_V3_WORKFLOW_ID, GROUP_V3_RUN_ID)
    eid = execution_id(GROUP_V3_WORKFLOW_ID, GROUP_V3_RUN_ID, "review")
    runtime = ui.workflow_runtimes[key]
    runtime["state"] = "waiting_recovery"
    runtime["gate"].update(
        id="review-recovery-1", kind="recovery", choices=["retry", "cancel"],
        reason="The selected Review task failed after it started.",
    )
    ui.workflow_runs[GROUP_V3_WORKFLOW_ID][0]["status"] = "waiting_recovery"
    execution = ui.execution_pages[key]["page-2"]["items"][0]
    execution["state"] = "waiting_recovery"
    attempts = ui.attempt_pages[(*key, eid)][""]["items"]
    attempts[0]["state"] = "failed"
    ui.open("/groups")
    ui.select_group(GROUP_ID)
    expand_run_history(page, "Group structured branch workflow")
    page.get_by_role("button", name="Retry task", exact=True).click()
    confirmation = page.get_by_role("dialog", name="Retry task?", exact=True)
    expect(confirmation).to_contain_text(f"Execution {eid}")
    expect(confirmation).to_contain_text("Attempt 1")

    # Another reviewer retries the task; that second attempt fails and gets its
    # own recovery gate while this browser still holds the first confirmation.
    runtime["version"] += 5
    runtime["gate"].update(id="review-recovery-2", attempt=2)
    execution["attempt"] = 2
    attempts.append({**copy.deepcopy(attempts[0]), "attempt": 2})
    ui.decision_pages[key]["page-2"]["items"].extend([
        {"execution_id": eid, "node_id": "review", "attempt": 1, "choice": "retry", "gate_id": "review-recovery-1"},
        {"execution_id": eid, "node_id": "review", "attempt": 2, "choice": "approve", "gate_id": "review-approval-2"},
    ])
    expect(page.get_by_text(f"Execution {eid} \u00b7 Node review \u00b7 Attempt 2", exact=True)).to_be_visible()
    confirmation.get_by_role("button", name="Retry task", exact=True).click()
    expect(confirmation).to_have_count(0)
    expect(page.get_by_role("alert").filter(has_text="recovery gate changed")).to_be_visible()
    assert not any(request.path.endswith("/runtime/decision") and request.method == "POST" for request in ui.requests)
