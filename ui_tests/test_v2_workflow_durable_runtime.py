# test_v2_workflow_durable_runtime.py
"""
UI tests for native V2 durable workflow runtime controls.
Version: 0.261.111
Implemented in: 0.261.111

These tests use the real V2 SPA bundle with a closed API fixture. They cover
durable authoring defaults, pre-task approval payloads, queued run responses,
runtime gates, stale decisions, recovery confirmation, read-only runtime views,
cancel/resume controls, and polling cleanup.
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


pytestmark = pytest.mark.ui


def labelled(page, name):
    return page.get_by_label(re.compile(rf"^{re.escape(name)}(?:\s*\*)?\s*$"))


def open_task_details(page, index=0):
    page.get_by_text("Runner, inputs, references and outputs", exact=True).nth(index).click()


def durable_toggle(page):
    return page.get_by_label(re.compile(r"^Durable execution"))


def approval_toggle(page):
    return page.get_by_label(re.compile(r"^Require approval before this task"))


def workflow_post(ui):
    writes = [
        request for request in ui.workflow_writes
        if request.method == "POST" and request.path in {"/api/user/workflows", "/api/group/workflows"}
    ]
    assert writes, "Expected a workflow save request."
    return writes[-1]


def runtime_decisions(ui):
    return [
        request for request in ui.writes
        if request.path.endswith("/runtime/decision")
    ]


def expand_durable_history(page):
    row = page.get_by_role("listitem").filter(has_text="Durable approval workflow").first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    expect(page.get_by_text("Run memory", exact=True)).to_be_visible()
    page.get_by_text("Run memory", exact=True).click()
    expect(page.get_by_text("Checkpoint units and attempts", exact=True)).to_be_visible()


def test_durable_default_existing_preservation_and_task_approval_payload(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")

    page.get_by_role("button", name="Create workflow", exact=True).click()
    expect(page.get_by_role("dialog", name="Create workflow", exact=True)).to_be_visible()
    expect(durable_toggle(page)).to_be_checked()
    labelled(page, "Workflow name").fill("Durable default workflow")
    labelled(page, "Model").select_option(label="Workspace GPT · aoai")
    labelled(page, "Instructions").first.fill("Run durably by default.")
    page.get_by_role("button", name="Save workflow", exact=True).click()

    body = workflow_post(ui).body
    assert body["durable_execution"] is True
    assert "approval" not in body["tasks"][0]

    page.get_by_role("button", name=re.compile(r"Edit Quarterly review workflow")).click()
    expect(durable_toggle(page)).not_to_be_checked()
    labelled(page, "Description").first.fill("Legacy workflow stays non-durable unless opted in.")
    page.get_by_role("button", name="Save workflow", exact=True).click()
    legacy_body = workflow_post(ui).body
    assert legacy_body["id"] == WORKFLOW_ID
    assert "durable_execution" not in legacy_body

    page.get_by_role("button", name="Create workflow", exact=True).click()
    durable_toggle(page).uncheck(force=True)
    open_task_details(page)
    approval_toggle(page).check(force=True)
    expect(durable_toggle(page)).to_be_checked()
    labelled(page, "Approval message for Task 1").fill("Human approval required before this task.")
    labelled(page, "Workflow name").fill("Approval workflow")
    labelled(page, "Model").select_option(label="Workspace GPT · aoai")
    labelled(page, "Instructions").first.fill("Pause before running.")
    page.get_by_role("button", name="Save workflow", exact=True).click()

    approval_body = workflow_post(ui).body
    assert approval_body["durable_execution"] is True
    assert approval_body["tasks"][0]["approval"] == {
        "required": True,
        "message": "Human approval required before this task.",
    }


def test_queued_run_response_expands_live_runtime_without_blocking(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")

    page.get_by_role("button", name=re.compile(r"Run Durable approval workflow")).click()
    expect(page.get_by_text("queued", exact=True).first).to_be_visible()
    page.get_by_role("button", name="Show run task results", exact=True).first.click()
    expect(page.get_by_text("Version 1", exact=True)).to_be_visible()

    run_posts = [
        request for request in ui.writes
        if request.method == "POST" and request.path == f"/api/user/workflows/{DURABLE_WORKFLOW_ID}/run"
    ]
    assert len(run_posts) == 1


def test_waiting_approval_reload_retry_request_id_and_stale_gate_refresh(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.open("/workspace/workflows")
    expand_durable_history(page)

    expect(page.get_by_text("Approval is required before Approval task starts.", exact=True)).to_be_visible()
    ui.fail_next_runtime_decision(503)
    page.get_by_role("button", name="Approve task", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Retry uses the same request id")).to_be_visible()
    page.get_by_role("button", name="Approve task", exact=True).click()
    expect(page.get_by_text("queued", exact=True).first).to_be_visible()
    decision_writes = runtime_decisions(ui)
    assert len(decision_writes) == 2
    assert decision_writes[0].body["choice"] == "approve"
    assert decision_writes[0].body["request_id"] == decision_writes[1].body["request_id"]

    runtime = ui.runtime_projection(
        state="waiting_approval",
        version=5,
        gate={
            "id": "approval-gate-stale",
            "kind": "approval",
            "unit_id": "approval-task",
            "input_digest": "sha256:stale",
            "reason": "Approval is required before a stale test.",
            "choices": ["approve", "reject"],
        },
    )
    ui.set_runtime(DURABLE_WORKFLOW_ID, "durable-run-1", runtime)
    page.reload()
    expand_durable_history(page)
    before = len(runtime_decisions(ui))
    ui.stale_next_runtime_decision()
    page.get_by_role("button", name="Approve task", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Runtime changed before your decision")).to_be_visible()
    expect(page.get_by_text("Approval is still required for the refreshed gate.", exact=True)).to_be_visible()
    assert len(runtime_decisions(ui)) == before + 1

    forbidden_runtime = ui.runtime_projection(
        state="waiting_approval",
        version=13,
        gate={
            "id": "approval-gate-forbidden",
            "kind": "approval",
            "unit_id": "approval-task",
            "input_digest": "sha256:forbidden",
            "reason": "Approval is required before a permission test.",
            "choices": ["approve", "reject"],
        },
    )
    ui.set_runtime(DURABLE_WORKFLOW_ID, "durable-run-1", forbidden_runtime)
    page.reload()
    expand_durable_history(page)
    ui.fail_next_runtime_decision(403)
    page.get_by_role("button", name="Approve task", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="no longer have access")).to_be_visible()
    expect(page.get_by_role("button", name="Approve task", exact=True)).to_have_count(0)


def test_output_recovery_and_readonly_gates_show_correct_controls(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    output_runtime = ui.runtime_projection(
        state="waiting_output",
        version=8,
        gate={
            "id": "output-gate",
            "kind": "output",
            "unit_id": "approval-task",
            "input_digest": "sha256:output",
            "reason": "The task has not produced the required output yet.",
            "choices": ["approve", "retry"],
        },
    )
    ui.set_runtime(DURABLE_WORKFLOW_ID, "output-run", output_runtime)
    ui.open("/workspace/workflows")
    expand_durable_history(page)
    expect(page.get_by_text("Waiting for required output.", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Approve task", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Retry task", exact=True)).to_have_count(0)

    recovery_runtime = ui.runtime_projection(
        state="waiting_recovery",
        version=3,
        gate={
            "id": "recovery-gate",
            "kind": "recovery",
            "unit_id": "approval-task",
            "input_digest": "sha256:recovery",
            "reason": "The task failed and can be retried.",
            "choices": ["retry", "cancel"],
        },
    )
    ui.set_runtime(DURABLE_WORKFLOW_ID, "recovery-run", recovery_runtime)
    page.reload()
    expand_durable_history(page)
    page.get_by_role("button", name="Retry task", exact=True).click()
    expect(page.get_by_role("dialog", name="Retry task?", exact=True)).to_be_visible()
    assert not runtime_decisions(ui)
    page.get_by_role("dialog", name="Retry task?", exact=True).get_by_role("button", name="Retry task", exact=True).click()
    expect(page.get_by_text("queued", exact=True).first).to_be_visible()
    assert runtime_decisions(ui)[-1].body["choice"] == "retry"

    readonly_runtime = ui.runtime_projection(
        state="waiting_approval",
        version=4,
        gate={
            "id": "readonly-gate",
            "kind": "approval",
            "unit_id": "approval-task",
            "input_digest": "sha256:readonly",
            "reason": "Another approver owns this gate.",
            "choices": ["approve", "reject"],
        },
    )
    ui.set_runtime(DURABLE_WORKFLOW_ID, "readonly-run", readonly_runtime, can_decide=False)
    page.reload()
    expand_durable_history(page)
    expect(page.get_by_text("you do not have permission to approve", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Approve task", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Reject task", exact=True)).to_have_count(0)

    pause_runtime = ui.runtime_projection(
        state="paused",
        version=7,
        gate={
            "id": "pause-cancel-gate",
            "kind": "pause",
            "unit_id": "file_sync",
            "input_digest": "sha256:changed-input",
            "reason": "The source changed since this checkpoint.",
            "choices": ["cancel"],
        },
    )
    ui.set_runtime(DURABLE_WORKFLOW_ID, "pause-run", pause_runtime)
    page.reload()
    expand_durable_history(page)
    expect(page.get_by_text("The source changed since this checkpoint.", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Resume run", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Cancel run", exact=True).click()
    expect(page.get_by_text("cancelled", exact=True).first).to_be_visible()
    assert runtime_decisions(ui)[-1].body["choice"] == "cancel"


def test_cancel_resume_controls_and_polling_cleanup(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    running_runtime = ui.runtime_projection(state="running", version=6)
    ui.set_runtime(DURABLE_WORKFLOW_ID, "running-run", running_runtime)
    ui.open("/workspace/workflows")
    expand_durable_history(page)

    page.get_by_role("button", name="Cancel run", exact=True).click()
    expect(page.get_by_text("cancelled", exact=True).first).to_be_visible()
    cancel_writes = [
        request for request in ui.writes
        if request.method == "POST" and request.path == f"/api/user/workflows/{DURABLE_WORKFLOW_ID}/cancel"
    ]
    assert cancel_writes

    failed_runtime = ui.runtime_projection(state="failed", version=9, can_resume=True)
    ui.set_runtime(DURABLE_WORKFLOW_ID, "failed-run", failed_runtime)
    page.reload()
    expand_durable_history(page)
    ui.stale_next_runtime_resume()
    page.get_by_role("button", name="Resume run", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Runtime changed before your resume request")).to_be_visible()
    expect(page.get_by_text("Review the refreshed checkpoint before resuming.", exact=True)).to_be_visible()
    first_resume_writes = [
        request for request in ui.writes
        if request.method == "POST" and request.path.endswith("/runtime/resume")
    ]
    assert first_resume_writes[-1].body["expected_version"] == 9
    page.get_by_role("button", name="Resume run", exact=True).click()
    expect(page.get_by_text("queued", exact=True).first).to_be_visible()
    resume_writes = [
        request for request in ui.writes
        if request.method == "POST" and request.path.endswith("/runtime/resume")
    ]
    assert resume_writes[-1].body["expected_version"] == 10
    assert resume_writes[-1].body["request_id"] != first_resume_writes[-1].body["request_id"]

    forbidden_resume = ui.runtime_projection(state="failed", version=12, can_resume=True)
    ui.set_runtime(DURABLE_WORKFLOW_ID, "forbidden-resume-run", forbidden_resume)
    page.reload()
    expand_durable_history(page)
    ui.fail_next_runtime_resume(403)
    page.get_by_role("button", name="Resume run", exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="no longer have access")).to_be_visible()
    expect(page.get_by_role("button", name="Resume run", exact=True)).to_have_count(0)

    polling_runtime = ui.runtime_projection(state="running", version=11)
    polling_gate = ui.runtime_projection(
        state="waiting_approval",
        version=11,
        gate={
            "id": "heartbeat-gate",
            "kind": "approval",
            "unit_id": "task:extract",
            "input_digest": "sha256:heartbeat",
            "reason": "Heartbeat polling reached a new approval gate.",
            "choices": ["approve", "reject"],
        },
    )
    ui.set_runtime(DURABLE_WORKFLOW_ID, "polling-run", polling_runtime)
    ui.transition_runtime_on_get(DURABLE_WORKFLOW_ID, "polling-run", 3, polling_gate)
    page.reload()
    expand_durable_history(page)
    key = ("user", DURABLE_WORKFLOW_ID, "polling-run")
    expect(page.get_by_text("Heartbeat polling reached a new approval gate.", exact=True)).to_be_visible(timeout=7000)
    assert 3 <= ui.runtime_get_count[key] <= 5
    page.get_by_role("button", name="Hide run history", exact=True).click()
    stopped_at = ui.runtime_get_count[key]
    page.wait_for_timeout(2600)
    assert ui.runtime_get_count[key] == stopped_at
