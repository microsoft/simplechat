# test_v2_workflow_m365_runtime.py
"""
Closed-browser compatibility tests for Microsoft 365 workflow authorization waits.
Version: 0.261.127
Implemented in: 0.261.122

The production SPA must retain nonterminal states, keep polling, lock active
authoring, and permit cancellation without exposing generic approval or resume.
Use existing local/Azure Playwright fixtures; every application API is synthetic.
"""

import copy
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

# Shared fixtures configure isolated production imports after local path setup.
from ui_tests.fixtures.workflow_editor import (
    DURABLE_WORKFLOW_ID,
    GROUP_ID,
    connect_options,  # noqa: F401
    workflow_ui,  # noqa: F401
)
from ui_tests.fixtures.workflow_flow import (
    FLOW_NAME,
    FLOW_RUN_ID,
    FLOW_WORKFLOW_ID,
    workflow_flow_ui,  # noqa: F401
)


pytestmark = pytest.mark.ui
AUTHORIZATION_STATES = [
    "awaiting_approval",
    "awaiting_sharing_approval",
    "awaiting_analysis_approval",
    "awaiting_run_as_approval",
    "awaiting_sign_in",
]
AUTHORIZATION_REASON = "Complete the required step in Approvals or Microsoft 365 connection settings."
RUN_ID = "m365-waiting-run"


def authorization_gate():
    return {
        "id": "m365-authorization",
        "kind": "pause",
        "reason_code": "m365_authorization",
        "reason": AUTHORIZATION_REASON,
        "unit_id": "approval-task",
        "choices": ["cancel"],
    }


def open_runtime(ui, name, *, group=False, structured=False):
    ui.open("/groups" if group else "/workspace/workflows")
    if group:
        ui.select_group(GROUP_ID)
    row = ui.page.get_by_role("listitem").filter(has_text=name).first
    row.get_by_role("button", name="Show run history", exact=True).click()
    row.get_by_role("button", name="Show run task results", exact=True).click()
    memory_label = "Runtime memory summary" if structured else "Run memory"
    expect(row.get_by_text(memory_label, exact=True)).to_be_visible()
    expect(row.get_by_text(AUTHORIZATION_REASON, exact=True)).to_be_visible()
    return row


def assert_no_generic_continuation(page):
    for name in ("Approve task", "Reject task", "Retry task", "Resume run", "Continue Repeat"):
        expect(page.get_by_role("button", name=name, exact=True)).to_have_count(0)


@pytest.mark.parametrize(
    "state,group",
    [(state, False) for state in AUTHORIZATION_STATES] + [("awaiting_run_as_approval", True)],
    ids=AUTHORIZATION_STATES + ["group-run-as-approval"],
)
def test_authorization_waits_lock_authoring_poll_history_and_only_offer_cancel(workflow_ui, state, group):
    ui, page = workflow_ui, workflow_ui.page
    workflow_id = "group-workflow" if group else DURABLE_WORKFLOW_ID
    workflow = ui.group_workflows[GROUP_ID][workflow_id] if group else ui.personal_workflows[workflow_id]
    workflow.update(active_run_id=RUN_ID, durable_execution=True, status=state)
    scope_type = "group" if group else "user"
    runtime = ui.runtime_projection(state=state, version=7, gate=authorization_gate(), can_resume=True)
    ui.set_runtime(workflow_id, RUN_ID, runtime, scope_type=scope_type)
    next_runtime = copy.deepcopy(runtime)
    next_runtime["version"] = 8
    ui.transition_runtime_on_get(workflow_id, RUN_ID, 2, next_runtime, scope_type=scope_type)
    row = open_runtime(ui, workflow["name"], group=group)
    expect(row.get_by_role(
        "button", name=f"{workflow['name']} is running; cancel or wait before editing", exact=True
    )).to_be_disabled()
    expect(row.get_by_role("button", name=f"Run {workflow['name']}", exact=True)).to_have_count(0)
    expect(row.get_by_role("button", name=f"Cancel {workflow['name']}", exact=True)).to_be_enabled()
    expect(row.get_by_text(state, exact=True).first).to_be_visible()
    expect(row.get_by_text(AUTHORIZATION_REASON, exact=True)).to_be_visible()
    expect(row.get_by_text("Version 8", exact=True)).to_be_visible(timeout=10000)
    assert ui.runtime_get_count[(scope_type, workflow_id, RUN_ID)] >= 2
    assert_no_generic_continuation(page)
    assert not ui.non_navigation_writes

    runs_path = f"/api/{scope_type}/workflows/{workflow_id}/runs"
    with page.expect_response(
        lambda response: response.status == 200
        and response.request.method == "GET"
        and response.url.split("?")[0].endswith(runs_path)
    ):
        expect(row.get_by_role("button", name="Cancel run", exact=True)).to_be_enabled()
    assert sum(request.path == runs_path for request in ui.requests) >= 2
    row.get_by_role("button", name="Cancel run", exact=True).click()
    expect(row.get_by_text("cancelled", exact=True).first).to_be_visible()
    decisions = [request for request in ui.writes if request.path.endswith("/runtime/decision")]
    assert len(decisions) == 1
    assert decisions[0].body["choice"] == "cancel"
    assert decisions[0].body["gate_id"] == "m365-authorization"
    assert decisions[0].body["expected_version"] == 8
    assert decisions[0].query == ({"group_id": [GROUP_ID]} if group else {})
    assert not any(request.path.endswith("/runtime/resume") for request in ui.writes)


def test_stale_failure_flags_do_not_offer_resume_through_a_m365_gate(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    runtime = ui.runtime_projection(
        state="failed", version=11, gate=authorization_gate(), can_resume=True
    )
    ui.set_runtime(DURABLE_WORKFLOW_ID, RUN_ID, runtime)
    open_runtime(ui, "Durable approval workflow")
    expect(page.get_by_text("Version 11", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Cancel run", exact=True)).to_be_enabled()
    assert_no_generic_continuation(page)
    assert not ui.non_navigation_writes


def test_flow_describes_m365_authorization_instead_of_a_repeat_limit(workflow_flow_ui):
    ui, page = workflow_flow_ui, workflow_flow_ui.page
    key = ("user", FLOW_WORKFLOW_ID, FLOW_RUN_ID)
    ui.workflow_runtimes[key].update(
        state="awaiting_sign_in",
        gate={**authorization_gate(), "unit_id": "evaluate", "node_id": "evaluate"},
    )
    ui.workflow_runs[FLOW_WORKFLOW_ID][0]["status"] = "awaiting_sign_in"
    open_runtime(ui, FLOW_NAME, structured=True)
    page.get_by_role("button", name="Show Flow for this run", exact=True).click()
    view = page.get_by_role("region", name="Workflow Flow", exact=True)
    expect(view.get_by_text("Run's frozen definition", exact=True)).to_be_visible()
    notice = view.get_by_text("Current run gate:", exact=False)
    expect(notice).to_contain_text("m365_authorization")
    expect(notice).to_contain_text("Approvals or Microsoft 365 connection settings")
    expect(notice).not_to_contain_text("Retained Repeat progress")
    expect(notice).to_have_class("text-xs text-warn")
    assert_no_generic_continuation(page)
    assert not ui.non_navigation_writes
