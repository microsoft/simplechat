# test_v2_workflow_status_freshness.py
"""
UI regressions for authoritative workflow status reconciliation.
Version: 0.261.356
Implemented in: 0.261.356

Runs the real built SPA with the existing closed API fixture and local/Azure
Playwright connection. No live workflow, credential, or external harness is used.
Covers personal/group summaries, background transitions, final polling cleanup,
retained selection/focus, read failures, superseded responses and scope changes.
"""

import copy
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui_tests"))
sys.path.insert(0, str(ROOT / "ui_tests" / "fixtures"))

from ui_tests.fixtures.workflow_editor import (  # noqa: E402
    DURABLE_WORKFLOW_ID,
    GROUP_ID,
    SECOND_GROUP_ID,
    connect_options,  # noqa: F401
    workflow_ui,  # noqa: F401
)
from ui_tests.fixtures.workflow_workbench import (  # noqa: E402
    select_workflow,
    workflow_row,
)

pytestmark = pytest.mark.ui
NAME = "Durable approval workflow"
RUN_ID = "freshness-run"
CLOCK_START = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
TERMINAL = {"failed", "completed", "completed_partial", "cancelled", "invalid", "incomplete"}


def seed(ui, scope="user"):
    workflow = copy.deepcopy(ui.personal_workflows[DURABLE_WORKFLOW_ID])
    ui.personal_workflows = {DURABLE_WORKFLOW_ID: workflow}
    ui.group_workflows[GROUP_ID] = {
        DURABLE_WORKFLOW_ID: {**copy.deepcopy(workflow), "group_id": GROUP_ID},
    }
    advance(ui, "queued", scope=scope)


def advance(ui, status, *, scope="user", version=1):
    store = ui.personal_workflows if scope == "user" else ui.group_workflows[GROUP_ID]
    workflow = store[DURABLE_WORKFLOW_ID]
    workflow.update(status="idle" if status in TERMINAL else status,
                    active_run_id="" if status in TERMINAL else RUN_ID)
    if status in TERMINAL:
        workflow.update(last_run_status=status, last_run_at="2026-10-20T12:00:00Z")
    gate = {"id": "recovery-gate", "kind": "recovery", "unit_id": "approval-task",
            "input_digest": "sha256:fixture", "reason": "Review the failed task before retrying.",
            "choices": ["retry", "cancel"]} if status == "waiting_recovery" else None
    runtime = ui.runtime_projection(state=status, version=version, **({"gate": gate} if gate else {}))
    ui.set_runtime(DURABLE_WORKFLOW_ID, RUN_ID, runtime, scope_type=scope)


def open_workbench(ui, scope="user", *, width=1440, theme="light"):
    ui.page.clock.install(time=CLOCK_START)
    ui.page.clock.pause_at(CLOCK_START + timedelta(seconds=1))
    ui.open(f"/groups/{GROUP_ID}/workflows" if scope == "group" else "/workspace/workflows",
            width=width, theme=theme)
    return select_workflow(ui.page, NAME)


def collection_path(scope="user"):
    return f"/api/{scope}/workflows"


def reads(ui, path):
    return [entry for entry in ui.requests if entry.method == "GET" and entry.path == path]


def tick(page, milliseconds=2600):
    page.clock.fast_forward(milliseconds)
    # Flush browser/route messages after the virtual timer, not a fixed wall-clock sleep.
    page.evaluate("() => document.readyState")


def expect_state(ui, detail, label):
    expect(workflow_row(ui.page, NAME)).to_contain_text(f"{label} · Manual")
    expect(detail.locator("header").get_by_text(label, exact=True)).to_be_visible()


@pytest.mark.parametrize("scope,view,outcome,width,theme", [
    ("user", "overview", "failed", 1440, "light"),
    ("user", "collapsed", "completed", 390, "dark"),
    ("user", "expanded", "completed_partial", 1440, "dark"),
    ("group", "overview", "completed", 390, "light"),
    ("group", "collapsed", "cancelled", 1440, "light"),
    ("group", "expanded", "failed", 1440, "dark"),
    ("user", "overview", "invalid", 1440, "light"),
    ("group", "collapsed", "incomplete", 1440, "light"),
])
def test_workbench_tracks_active_and_terminal_states_without_remounting(
    workflow_ui, scope, view, outcome, width, theme,
):
    ui, page = workflow_ui, workflow_ui.page
    seed(ui, scope)
    detail = open_workbench(ui, scope, width=width, theme=theme)
    expect_state(ui, detail, "Queued")
    focus = detail.get_by_role("tab", name="Overview", exact=True)
    if view != "overview":
        detail.get_by_role("tab", name="Runs", exact=True).click()
        expect(detail.get_by_role("list", name="Workflow run history")).to_be_visible()
        focus = detail.get_by_role("button", name="Show run task results", exact=True)
        if view == "expanded":
            focus.click()
            focus = detail.get_by_role("button", name="Hide run task results", exact=True)
            expect(detail.get_by_text("Version 1", exact=True)).to_be_visible()
    focus.focus()
    detail.evaluate("element => element.dataset.freshnessProbe = 'same-node'")

    for version, (status, label) in enumerate([
        ("running", "Running"), ("waiting_recovery", "Waiting for recovery"),
        ("paused", "Paused"),
    ], start=2):
        advance(ui, status, scope=scope, version=version)
        tick(page)
        expect_state(ui, detail, label)
        expect(focus).to_be_focused()
        expect(detail).to_have_attribute("data-freshness-probe", "same-node")
        expect(detail.get_by_role("button", name=f"Cancel {NAME}", exact=True)).to_be_enabled()
        expect(detail.get_by_role("button", name=re.compile("cancel or wait before editing"))).to_be_disabled()
        if view != "overview":
            expect(detail.get_by_role("list", name="Workflow run history").get_by_text(label, exact=True)).to_be_visible()
        if status in {"waiting_recovery", "paused"}:
            expect(page.get_by_text("1 needs attention", exact=True)).to_be_visible()

    advance(ui, outcome, scope=scope, version=5)
    tick(page)
    label = {"completed_partial": "Completed with task errors"}.get(outcome, outcome.capitalize())
    expect_state(ui, detail, label)
    expect(detail.get_by_role("button", name=f"Run {NAME}", exact=True)).to_be_enabled()
    expect(detail.get_by_role("button", name=f"Edit {NAME}", exact=True)).to_be_enabled()
    expect(focus).to_be_focused()
    if view == "expanded":
        expect(detail.get_by_text("Version 5", exact=True)).to_be_visible()
        expect(detail.get_by_role("button", name="Hide run task results", exact=True)).to_be_visible()
    if outcome == "completed":
        expect(page.get_by_text("1 needs attention", exact=True)).to_have_count(0)
    else:
        expect(page.get_by_text("1 needs attention", exact=True)).to_be_visible()
    before = len(reads(ui, collection_path(scope)))
    run_reads = len(reads(ui, f"{collection_path(scope)}/{DURABLE_WORKFLOW_ID}/runs"))
    tick(page, 10000)
    assert len(reads(ui, collection_path(scope))) == before
    assert len(reads(ui, f"{collection_path(scope)}/{DURABLE_WORKFLOW_ID}/runs")) == run_reads
    assert not ui.non_navigation_writes
    ui.assert_no_overflow()
    if scope == "user" and outcome in {"failed", "completed"}:
        artifacts = ROOT / "ui_tests" / "artifacts" / "workflow-freshness-preview"
        artifacts.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(artifacts / f"workbench-{width}-{theme}.png"), full_page=True)


def test_filtered_out_active_workflow_still_reconciles(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    seed(ui)
    open_workbench(ui)
    page.get_by_label("Status", exact=True).select_option("attention")
    expect(workflow_row(page, NAME)).to_have_count(0)
    advance(ui, "waiting_recovery")
    tick(page)
    expect(workflow_row(page, NAME)).to_be_visible()
    advance(ui, "completed")
    tick(page)
    expect(workflow_row(page, NAME)).to_have_count(0)
    expect(page.get_by_label("Status", exact=True)).to_have_value("attention")
    expect(page.get_by_text("No workflows match these filters", exact=True)).to_be_visible()


@pytest.mark.parametrize("failed_read", ["workflows", "history"])
def test_failed_read_keeps_view_but_disables_actions_until_successful_retry(workflow_ui, failed_read):
    ui, page = workflow_ui, workflow_ui.page
    seed(ui)
    advance(ui, "waiting_recovery")
    detail = open_workbench(ui)
    detail.get_by_role("tab", name="Runs", exact=True).click()
    detail.get_by_role("button", name="Show run task results", exact=True).click()
    retry = detail.get_by_role("button", name="Retry task", exact=True)
    retry.click()
    expect(page.get_by_role("dialog", name="Retry task?", exact=True)).to_be_visible()
    assert not ui.non_navigation_writes
    path = collection_path()
    if failed_read == "history":
        path += f"/{DURABLE_WORKFLOW_ID}/runs"
    ui.reject_next("GET", path, error="Unreviewed provider error must not become UI text.")
    tick(page)
    expect(page.get_by_role("alert").filter(has_text="Could not refresh")).to_be_visible()
    expect(page.get_by_role("dialog", name="Retry task?", exact=True)).to_have_count(0)
    expect(retry).to_have_count(0)
    expect(detail.get_by_role("button", name="Hide run task results", exact=True)).to_be_visible()
    expect(page.get_by_text("Unreviewed provider error", exact=False)).to_have_count(0)
    if failed_read == "workflows":
        expect(detail.get_by_role("button", name=f"Cancel {NAME}", exact=True)).to_be_disabled()
    stopped = len(reads(ui, path))
    tick(page, 10000)
    assert len(reads(ui, path)) == stopped, "Failed reads must stop rather than silently retry forever."
    retry_label = "Retry workflows" if failed_read == "workflows" else "Retry run history"
    page.get_by_role("button", name=retry_label, exact=True).click()
    expect(page.get_by_role("alert").filter(has_text="Could not refresh")).to_have_count(0)
    expect(retry).to_be_visible()
    retry.click()
    dialog = page.get_by_role("dialog", name="Retry task?", exact=True)
    expect(dialog).to_be_visible()
    assert not ui.non_navigation_writes
    dialog.get_by_role("button", name="Keep waiting", exact=True).click()


def test_accepted_run_keeps_server_state_while_summary_read_is_pending(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    seed(ui)
    advance(ui, "completed")
    detail = open_workbench(ui)
    run_path = f"{collection_path()}/{DURABLE_WORKFLOW_ID}/run"
    ui.defer_next("POST", run_path)
    with page.expect_request(lambda request: request.url.endswith(run_path) and request.method == "POST"):
        detail.get_by_role("button", name=f"Run {NAME}", exact=True).click()
    history = detail.get_by_role("list", name="Workflow run history", exact=True)
    expect(history.get_by_text("Completed", exact=True)).to_be_visible()
    ui.defer_next("GET", collection_path())
    with page.expect_request(lambda request: request.url.endswith(collection_path())):
        ui.release_responses()
    expect_state(ui, detail, "Queued")
    expect(detail.get_by_role("button", name=f"Cancel {NAME}", exact=True)).to_be_disabled()
    expect(detail.get_by_role("button", name=f"Run {NAME}", exact=True)).to_have_count(0)
    ui.release_responses()
    expect(detail.get_by_role("button", name=f"Cancel {NAME}", exact=True)).to_be_enabled()
    starts = [entry for entry in ui.non_navigation_writes if entry.path == run_path]
    assert len(starts) == 1


def test_slow_and_superseded_collection_response_cannot_restore_queued(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    seed(ui)
    detail = open_workbench(ui)
    stale = {"workflows": copy.deepcopy(list(ui.personal_workflows.values()))}
    path = collection_path()
    ui.defer_next("GET", path)
    with page.expect_request(lambda request: request.url.endswith(path)):
        tick(page)
    held_count = len(reads(ui, path))
    tick(page, 10000)
    assert len(reads(ui, path)) == held_count, "Slow polls must not overlap."
    advance(ui, "failed")
    # Opening history discovers the terminal run and invalidates the in-flight summary read.
    detail.get_by_role("tab", name="Runs", exact=True).click()
    expect_state(ui, detail, "Failed")
    pending, ui.pending_responses = ui.pending_responses, []
    assert len(pending) == 1
    route, _entry = pending[0]
    ui._json(route, stale)
    tick(page, 10000)
    expect_state(ui, detail, "Failed")
    expect(detail.get_by_role("button", name=f"Run {NAME}", exact=True)).to_be_enabled()


@pytest.mark.parametrize("status", [403, 404])
def test_access_loss_removes_cached_workflows(workflow_ui, status):
    ui, page = workflow_ui, workflow_ui.page
    seed(ui, "group")
    open_workbench(ui, "group")
    ui.reject_next("GET", "/api/group/workflows", status=status)
    tick(page)
    expect(page.get_by_role("alert").filter(has_text="Could not refresh workflows")).to_be_visible()
    expect(workflow_row(page, NAME)).to_have_count(0)
    expect(page.get_by_role("article", name=NAME, exact=True)).to_have_count(0)
    expect(page.get_by_text("No workflows yet", exact=True)).to_have_count(0)
    before = len(reads(ui, "/api/group/workflows"))
    tick(page, 10000)
    assert len(reads(ui, "/api/group/workflows")) == before
    page.get_by_role("button", name="Retry workflows", exact=True).click()
    expect(workflow_row(page, NAME)).to_be_visible()


def test_timed_out_read_stops_and_ignores_its_late_response(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    seed(ui)
    detail = open_workbench(ui)
    ui.defer_next("GET", collection_path())
    with page.expect_request(lambda request: request.url.endswith(collection_path())):
        tick(page)
    tick(page, 30000)
    expect(page.get_by_role("alert").filter(has_text="Could not refresh workflows")).to_be_visible()
    expect(detail.get_by_role("button", name=f"Cancel {NAME}", exact=True)).to_be_disabled()
    pending, ui.pending_responses = ui.pending_responses, []
    assert len(pending) == 1
    advance(ui, "failed")
    ui._dispatch(*pending[0])
    before = len(reads(ui, collection_path()))
    tick(page, 10000)
    assert len(reads(ui, collection_path())) == before
    expect_state(ui, detail, "Queued")
    page.get_by_role("button", name="Retry workflows", exact=True).click()
    expect_state(ui, detail, "Failed")


def test_leaving_workbench_cancels_pending_collection_and_polling(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    seed(ui)
    open_workbench(ui)
    ui.defer_next("GET", collection_path())
    with page.expect_request(lambda request: request.url.endswith(collection_path())):
        tick(page)
    page.get_by_role("navigation", name="Workspace sections", exact=True).get_by_role(
        "link", name="Prompts", exact=True,
    ).click()
    expect(page).to_have_url(re.compile(r"/workspace/prompts$"))
    pending, ui.pending_responses = ui.pending_responses, []
    assert len(pending) == 1
    ui._dispatch(*pending[0])
    before = len(reads(ui, collection_path()))
    tick(page, 10000)
    assert len(reads(ui, collection_path())) == before
    expect(page.get_by_role("article", name=NAME, exact=True)).to_have_count(0)


def test_scope_switch_discards_old_group_response_and_stops_its_polling(workflow_ui, monkeypatch):
    ui, page = workflow_ui, workflow_ui.page
    seed(ui, "group")
    beta = copy.deepcopy(ui.group_workflows[GROUP_ID][DURABLE_WORKFLOW_ID])
    beta.update(name="Beta workflow", group_id=SECOND_GROUP_ID, status="idle", active_run_id="")
    dispatch = ui._dispatch

    def scoped_dispatch(route, entry):
        if entry.path == "/api/group/workflows" and entry.query.get("group_id") == [SECOND_GROUP_ID]:
            assert entry.method == "GET"
            ui._json(route, {"workflows": [beta]})
            return
        dispatch(route, entry)

    monkeypatch.setattr(ui, "_dispatch", scoped_dispatch)
    open_workbench(ui, "group")
    stale = {"workflows": copy.deepcopy(list(ui.group_workflows[GROUP_ID].values()))}
    ui.defer_next("GET", "/api/group/workflows")
    with page.expect_request(lambda request: "/api/group/workflows?" in request.url):
        tick(page)
    ui.select_group(SECOND_GROUP_ID)
    expect(workflow_row(page, "Beta workflow")).to_be_visible()
    pending, ui.pending_responses = ui.pending_responses, []
    assert len(pending) == 1
    ui._json(pending[0][0], stale)
    before = len(reads(ui, "/api/group/workflows"))
    tick(page, 10000)
    expect(workflow_row(page, NAME)).to_have_count(0)
    expect(workflow_row(page, "Beta workflow")).to_be_visible()
    assert len(reads(ui, "/api/group/workflows")) == before
    assert not reads(ui, "/api/user/workflows")
    assert not ui.non_navigation_writes
