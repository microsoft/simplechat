# test_v2_workflow_run_wait.py
"""
UI test for a chat plan that waits for a quick saved workflow it started (Phase 6c).
Version: 0.261.309
Implemented in: 0.261.309

This test ensures that, in the real V2 components with every server route stubbed:

- a running plan the server let wait for a quick saved workflow says so in its one-line status,
  naming the workflow and how long the plan waits exactly as the server wrote it, both live from
  the run stream and after a reload from the saved run, and the Review drawer shows the same line;
- a waiting workflow step without a line, and any other kind of wait, keep the generic
  "Waiting for results";
- the 6b-2 run card says a run whose result the plan used in its answer had its results used in a
  chat answer, never that they were posted or are posting, offers no jump to a posted message,
  and is never announced, marked read or reloaded as a delivery. A run 6b posted back instead is
  the control: it is announced and reloads the chat.

Hostile workflow names render as text and never run.

Build first (both outputs are git-ignored):
    npm --prefix application/v2_ui run build
    npm --prefix application/v2_ui run build -- --outDir ../../ui_tests/artifacts/orchestration-plan-editor

Refs #1546 (Phase 6), #1543 (Chat Orchestration Workflows).
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
for _entry in (ROOT, ROOT / "functional_tests"):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

import test_v2_orchestration_plan_editor as editor_tests  # noqa: E402
import test_v2_orchestration_recovery as recovery_tests  # noqa: E402
import test_v2_workflow_run_card as card_tests  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_v2_orchestration_plan_editor import (  # noqa: E402, F401
    connect_options,
    editor_assets,
    editor_browser,
)
from test_v2_workflow_run_card import run_assets  # noqa: E402, F401


pytestmark = pytest.mark.ui
IMPLEMENTED_IN = "0.261.309"
HANDLE = "workflow-sales-digest-4f1c2a"
HOSTILE_NAME = '<img src=x onerror="window.__xss = 1"> Sales <b>digest</b>'
# The server's line while the step waits (_waiting_summary): the saved name as plain text, quoted.
WAITING_LINE = f'Waiting for "{HOSTILE_NAME}" to finish (up to 5 min).'
DEPENDENT_LINE = "Waiting for required results."
USED_TEXT = "Its results were used in a chat answer."


def binding(step_id, output_name):
    return {"version": "orchestration-input-binding-v1", "step_id": step_id, "output_name": output_name,
            "existing_result": None}


def wait_plan(*, workflow_step=True):
    """Run a saved workflow, then compare its result with a workspace report.

    With ``workflow_step`` off, the waiting step is an ordinary step instead: the control for
    "only a waiting saved workflow run step names what it waits for".
    """
    plan = editor_tests.make_plan(recovery_tests.CONVERSATION, recovery_tests.TURN)
    read = plan["steps"][0]
    if workflow_step:
        run = {"step_id": "run_digest", "capability_id": "workflow_run", "title": "Run the sales digest",
               "arguments": {"workflow": HANDLE}, "role": "gather", "depends_on": [],
               "outputs": [{"name": "run", "kind": "structured-v1"}],
               "estimated_cost": "low", "enabled": True, "status": "pending"}
    else:
        run = {"step_id": "run_digest", "capability_id": "deep_research", "title": "Investigate context",
               "arguments": {}, "role": "gather", "depends_on": [],
               "outputs": [{"name": "run", "kind": "text-v1"}],
               "estimated_cost": "medium", "enabled": True, "status": "pending"}
    compare = {
        "step_id": "compare", "capability_id": "compose", "title": "Compare the digest with the Q3 report",
        "arguments": {}, "role": "reason", "depends_on": ["read", "run_digest"],
        "inputs": {"findings": {"binding": binding("read", "findings")},
                   "run": {"binding": binding("run_digest", "run")}},
        "outputs": [{"name": "answer", "kind": "markdown-v1"}],
        "delivers": ["answer"], "estimated_cost": "low", "enabled": True, "status": "pending",
    }
    plan["steps"] = [read, run, compare]
    plan["intent"]["summary"] = "Run my sales digest, then compare its totals with the Q3 report"
    plan["final_response"] = binding("compare", "answer")
    if workflow_step:
        plan["inputs"]["workflows"] = [
            {"handle": HANDLE, "name": HOSTILE_NAME, "trigger_summary": "On demand", "paused": False},
        ]
        plan["approval"]["floor"] = {"mode": "manual", "reason": "workflow_run"}
        # The server's marker: it, never the model, decided this step waits for its run.
        plan["workflow_run_waits"] = {"run_digest": {"version": 1, "workflow": HANDLE}}
    return plan


class WaitApi(recovery_tests.RecoveryApi):
    """Saved and streamed reads of a plan waiting for a quick saved workflow it started."""

    def __init__(self, assets):
        super().__init__(assets)
        self.use_plan(wait_plan())

    def use_plan(self, plan):
        self.plan = plan
        self.records = {}
        self.steps = {}
        record = self.add_record(plan)
        record["plan_summary"]["step_count"] = len(plan["steps"])

    def wait_for_run(self, run_id, summary=WAITING_LINE):
        """The attempt as the executor saves it while the run step waits and its consumer waits on it."""
        record = self.records[run_id]
        record.update(status="waiting", outcome="waiting", started_at="2026-09-21T19:00:00Z")
        record["plan"]["status"] = "waiting"
        record["plan_summary"]["status"] = "waiting"
        progress = {
            "read": ("completed", "Saved results"),
            "run_digest": ("waiting", summary),
            "compare": ("waiting", DEPENDENT_LINE),
        }
        self.steps[run_id] = [
            {"step_id": step["step_id"], "step_index": index, "title": step["title"],
             "capability_id": step["capability_id"], "status": progress[step["step_id"]][0],
             "summary": progress[step["step_id"]][1]}
            for index, step in enumerate(self.plan["steps"])
        ]

    def handle(self, route):
        path = urlsplit(route.request.url).path
        if path.endswith(("/workflow-runs", "/workflow-proposals")):
            # A waiting plan has saved no answer, so nothing may ask for the runs an answer lists.
            self.errors.append(f"{route.request.method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected test request"})
            return
        if path == editor_tests.RUN:
            body = route.request.post_data_json
            self.requests.append({"path": path, "method": route.request.method, "body": body})
            self.wait_for_run(body["run_id"])
            events = [{"type": "orchestration_step", **step} for step in self.steps[body["run_id"]]]
            events.append({
                "type": "orchestration_done", "done": True, "status": "waiting", "outcome": "waiting",
                "run_id": body["run_id"], "turn_id": recovery_tests.TURN, "attempt_index": 1,
            })
            self.stream(route, events)
            return
        super().handle(route)


@pytest.fixture
def wait_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = WaitApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
        assert page.evaluate("() => window.__xss ?? null") is None
    finally:
        api.release()
        context.close()
    assert not api.errors, api.errors


@pytest.fixture
def card_ui(editor_browser, run_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = card_tests.RunHarness(page, run_assets)
    try:
        yield api
        assert page.evaluate("() => window.__xss ?? null") is None
    finally:
        context.close()
    assert not api.errors, api.errors
    assert not api.unexpected, api.unexpected
    assert not [entry for entry in api.requests if "resume-failed" in entry[1]]


def expect_markup_free(page, scope):
    """The hostile name stayed text: no element it names exists, in the scope or anywhere."""
    for tag in ("img", "b", "script"):
        expect(scope.locator(tag)).to_have_count(0)
    expect(page.locator("img[src='x']")).to_have_count(0)
    expect(page.locator("b").filter(has_text=re.compile(r"^digest$"))).to_have_count(0)


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


# The waiting plan card ---------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["live", "saved"])
def test_a_plan_waiting_for_a_quick_workflow_names_it_and_how_long_it_waits(wait_ui, source):
    page, api = wait_ui
    if source == "live":
        recovery_tests.mount_recovery(page, api)
        page.get_by_role("button", name="Approve and run the plan").click()
    else:
        api.wait_for_run(api.plan["run_id"])
        recovery_tests.mount_recovery(page, api, saved=True)

    line = page.get_by_role("status").filter(has_text=WAITING_LINE)
    expect(line).to_have_count(1)
    expect(line).to_have_text(WAITING_LINE)
    expect_markup_free(page, line)
    # The generic waiting notice stays, and a wait is never offered as a retry.
    expect(page.get_by_role("status").filter(has_text=re.compile("^Waiting for required results")).first) \
        .to_be_visible()
    expect(page.get_by_role("button", name="Retry from failed step")).to_have_count(0)
    expect(page.get_by_role("status").filter(has_text=re.compile("^Waiting for results$"))).to_have_count(0)

    page.get_by_role("button", name="Review the running plan").click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    step = drawer.locator("[data-step-id='run_digest']")
    expect(step).to_contain_text(WAITING_LINE)
    expect(drawer.locator("[data-step-id='compare']")).to_contain_text(DEPENDENT_LINE)
    expect_markup_free(page, step)
    # The browser started the plan once, live, and never on a reload.
    assert len(api.calls("/run")) == (1 if source == "live" else 0)


@pytest.mark.parametrize("case", ["workflow-step-without-a-line", "another-kind-of-wait"])
def test_other_waits_keep_the_generic_line(wait_ui, case):
    page, api = wait_ui
    if case == "another-kind-of-wait":
        # The same hostile line on a step that is not a saved workflow run is never promoted.
        api.use_plan(wait_plan(workflow_step=False))
        api.wait_for_run(api.plan["run_id"])
    else:
        api.wait_for_run(api.plan["run_id"], summary="   ")
    recovery_tests.mount_recovery(page, api, saved=True)

    generic = page.get_by_role("status").filter(has_text=re.compile("^Waiting for results$"))
    expect(generic).to_have_count(1)
    expect(page.get_by_role("status").filter(has_text="to finish (up to")).to_have_count(0)
    expect(page.locator("img[src='x']")).to_have_count(0)


# The run card under the plan's answer ----------------------------------------------------------


def used_in_answer(at):
    """The delivery a plan that used the run's result leaves: delivered, with no message to point at."""
    return {"status": "delivered", "generation": 1, "message_id": None, "delivered_at": at,
            "reason": "used_in_answer"}


@pytest.mark.parametrize("outcome", ["used_in_answer", "posted"])
def test_a_result_the_plan_used_reads_as_used_and_is_never_announced(card_ui, outcome):
    ui = card_ui
    hostile = card_tests.HOSTILE
    ui.link_items[0]["name"] = hostile
    ui.status_rows = [card_tests.status_row("running", name=hostile)]
    # Unfocused, so an announced result would also raise a desktop notification.
    ui.open(browser={"focused": False})
    row = ui.live_row
    expect(row.get_by_role("status").first).to_contain_text("Running")
    reads, marks = ui.message_reads(), ui.mark_reads(card_tests.CHAT)

    if outcome == "posted":
        # The control: the same run posted back by 6b is announced and reloads the open chat.
        ui.deliver()
        ui.global_check()
        ui.wait_for(lambda: len(ui.workflow_replies()) == 1, "the posted result was announced")
        ui.wait_for(lambda: len(ui.notifications()) == 1, "the posted result raised a notification")
        assert ui.message_reads() == reads + 1
        expect(row).to_contain_text("Results posted below")
        return

    # Stamped as new, so only the delivery itself keeps it from being announced.
    ui.status_rows = [card_tests.status_row("completed", name=hostile, delivery=used_in_answer(ui.peek()))]
    ui.global_check()
    expect(row.get_by_role("status").first).to_contain_text("Completed")
    expect(row).to_contain_text(USED_TEXT)
    expect(row).not_to_contain_text(re.compile(r"posted|posting", re.I))
    expect(row.get_by_role("button", name=re.compile("Results posted below"))).to_have_count(0)
    expect(row.get_by_role("link", name=f"Open run of {hostile}", exact=True)) \
        .to_have_attribute("href", card_tests.RUN_HREF)
    expect(ui.card.get_by_text(hostile, exact=True).first).to_be_visible()
    expect(ui.page.locator("img[src='x']")).to_have_count(0)

    ui.global_check()
    ui.page.wait_for_timeout(500)
    replies, notifications = ui.replies(), ui.notifications()
    assert replies == []
    assert notifications == []
    assert ui.message_reads() == reads
    assert ui.mark_reads(card_tests.CHAT) == marks
