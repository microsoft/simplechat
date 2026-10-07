# test_v2_orchestration_workflow_handoff_run_status.py
"""
UI test for the live run status of an accepted workflow hand-off in V2.
Version: 0.261.253
Implemented in: 0.261.293
Refs: microsoft/simplechat#1549, microsoft/simplechat#1543

This test ensures that the run an accepted hand-off queued is followed through the tab's workflow
run tracker (6b-2) and settled like any run a plan started. It mounts the real app shell, chat
list and chat page with the real stores and the real run tracker, from the same harness as
`ui_tests/test_v2_workflow_run_card.py`, and stubs every server route at the network layer:

- The hand-off list follows `handoff_status` and `_describe` in
  `functions_orchestration_workflow_handoff_decisions.py`: a queued item carries `workflow`, `run`
  and `chat_delivery`; a closed settings gate gives `unavailable` with nothing disclosed. The
  disclosure is the server builder's own, and the answer is the server's hand-off note.
- The status rows follow `functions_workflow_chat_delivery_status.py`. A hand-off run's
  `orchestration_run_id` is the run that prepared the hand-off, which can be an earlier attempt
  than the run the answer is mounted on, so the rows here carry a different id on purpose. An
  over-limit pause projects as `waiting` with the reason `paused`; a pause past the deadline
  projects as `expired`.
- The decorators' refusal when personal workflows are off carries no code, as the route sends it.

It checks:

- the live row under the hand-off card, joined by the run id the list names and checked against
  the chat, step and workflow, never by the plan's run id; Check now, Cancel and Open run;
- the over-limit pause's own text and controls, and that a deadline reads as timed out instead;
- that a hand-off answer shows its run once, and never reads or shows the proposal card or the
  started-run card, even when its metadata names those capabilities too;
- that nothing reads run status while the run tracker's flags are off, and what the card shows;
- the running tag in the chat list, the bell and desktop notification for a result posted to
  another chat, and the delivered message's footer for a result posted to the open chat.

Build the V2 SPA first; this test reads its stylesheets from the default build:
npm --prefix .\\application\\v2_ui run build
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_workflow_handoff_run_status.py -q
"""

import copy
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONAL_TESTS = ROOT / "functional_tests"
APP_ROOT = ROOT / "application" / "single_app"
for _entry in (ROOT, FUNCTIONAL_TESTS, APP_ROOT):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

import functions_orchestration_workflow_handoffs as handoffs  # noqa: E402  (the answer's hand-off note)
import functions_workflow_handoff_builder as builder  # noqa: E402  (the disclosure the card shows)
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401
from ui_tests.test_v2_notifications_bell import Harness  # noqa: E402
from ui_tests.test_v2_workflow_run_card import (  # noqa: E402,F401
    ALIAS,
    CHAT,
    CHAT_TITLE,
    COMPLETED_AT,
    FEATURES,
    H,
    HOSTILE,
    LINKS,
    ORUN,
    OTHER,
    OTHER_TITLE,
    PROPOSALS,
    REQUESTED_AT,
    RUN,
    RUN_HREF,
    SETTINGS,
    STATIC_FOOTNOTE,
    TURN,
    WORKFLOW,
    RunHarness,
    delivered,
    delivery_id,
    merge,
    run_assets,
    status_row,
)


pytestmark = pytest.mark.ui

IMPLEMENTED_IN = "0.261.253"

HANDOFF_ID = "f1712e2d-af01-5e8a-af14-f7b4911c9bc8"
HANDOFF_STEP = "handoff"
HANDOFF_NAME = "Contract renewal review"
# The run that prepared the hand-off: an earlier attempt than the run the answer is mounted on.
PRODUCER = "orun-0"
HANDOFFS = f"/api/v2/orchestration/runs/{ORUN}/workflow-handoffs"
HANDOFF_QUESTION = "Review every contract in my Legal workspace and list the renewal terms."
CREATED_AT = "2026-01-05T09:00:00+00:00"
EXPIRES_AT = "2026-01-19T09:00:00+00:00"
LEGAL_HANDLE = "scope-legal-3f2a91"

HANDOFF_FEATURES = {**FEATURES, "enable_chat_orchestration_workflow_handoff": True}

# V2's own copy.
PAUSED_TEXT = (
    "Paused before reviewing any documents because more matched than one hand-off can review. "
    "Cancel it, then ask again with a narrower request."
)
GENERIC_PAUSE = "Paused. Open the run to continue."
DELIVERY_TEXT = "The run's outcome is posted in this chat when it ends."
READ_ERROR = "Couldn't check the run status right now. Try again."
GATE_TEXT = "Handing work off to a workflow is turned off, so this hand-off is not available."
WORKFLOWS_OFF = "Personal workflows are turned off in SimpleChat right now."
WORKFLOWS_OFF_REFUSAL = (400, {"error": "Allow User Workflows is disabled."})

# An over-limit pause, as the status route projects a paused run that isn't past its deadline.
PAUSE = {"reason": "paused", "action": "open_run", "gate_id": "gate-1"}
DEADLINE = {"reason": "deadline_exceeded", "action": "open_run", "gate_id": "gate-1"}
REPORT = "Three contracts renew in March: Northwind, Contoso and Fabrikam."

SUMMARY = {
    "name": HANDOFF_NAME,
    "description": "Lists the renewal terms of every contract in the Legal workspace.",
    "tasks": [
        {"title": "Find the renewal terms", "runner": "model", "agent_name": ""},
        {"title": "Report", "runner": "model", "agent_name": ""},
    ],
    "alerts": {"mode": "every_run", "severity": "info"},
    "durable": True,
    "one_time": True,
}


def all_matches_disclosure():
    """The server's disclosure for a search of every match in one group workspace."""
    loop = {"source": builder.HANDOFF_LOOP_SOURCE_QUERY, "scopes": [LEGAL_HANDLE],
            "selection": builder.HANDOFF_SELECTION_ALL}
    handles = {"scopes": {
        LEGAL_HANDLE: {"scope_type": "group", "scope_id": "group-legal", "name": f"{HOSTILE} Legal"},
    }}
    return builder.handoff_disclosure({"loop": loop}, handles, max_items=500)


DISCLOSURE = all_matches_disclosure()


def queued_item(**overrides):
    """An accepted hand-off whose run is queued, as `_describe` gives it."""
    item = {
        "handoff_id": HANDOFF_ID, "step_id": HANDOFF_STEP, "state": "queued", "reason": None,
        "created_at": CREATED_AT, "expires_at": EXPIRES_AT, "actions": [],
        "summary": copy.deepcopy(SUMMARY), "disclosure": copy.deepcopy(DISCLOSURE),
        "workflow": {"id": WORKFLOW, "name": HANDOFF_NAME, "is_enabled": False},
        "run": {"id": RUN, "status": "queued"},
        "chat_delivery": True,
    }
    return merge(item, copy.deepcopy(overrides))


def pending_item():
    """A hand-off still awaiting its decision: no workflow and no run yet."""
    item = queued_item(state="pending", actions=["accept", "edit", "deny"])
    for key in ("workflow", "run", "chat_delivery"):
        item.pop(key)
    return item


def closed_item(reason="workflow_handoff_disabled"):
    """A closed settings gate: the list discloses nothing and offers nothing (`handoff_status`)."""
    return {
        "handoff_id": HANDOFF_ID, "step_id": HANDOFF_STEP, "state": "unavailable", "reason": reason,
        "created_at": CREATED_AT, "expires_at": EXPIRES_AT, "actions": [],
        "summary": None, "disclosure": None,
    }


def hrow(status, *, step=HANDOFF_STEP, orun=PRODUCER, name=HANDOFF_NAME, **overrides):
    """A status row for the hand-off's run, from the run that prepared it."""
    return status_row(status, step=step, orun=orun, name=name, **overrides)


def handoff_messages(conversation=CHAT, capabilities=("compose", "workflow_handoff")):
    """The question and the plan's saved answer, which prepared the hand-off."""
    return [
        {"id": "user-1", "conversation_id": conversation, "role": "user",
         "content": HANDOFF_QUESTION, "metadata": {"orchestration_turn_id": TURN}},
        {"id": "answer-1", "conversation_id": conversation, "role": "assistant",
         "content": handoffs.WORKFLOW_HANDOFF_NOTE,
         "metadata": {"orchestration": {
             "run_id": ORUN, "turn_id": TURN, "outcome": "completed", "finalization_status": "saved",
             "message_saved": True,
             "plan_summary": {
                 "plan_id": "plan-1", "turn_id": TURN, "status": "completed",
                 "intent_summary": "Review every contract in my Legal workspace", "step_count": 2,
                 "capabilities_used": list(capabilities),
             },
         }}},
    ]


def delivered_handoff_message(*, conversation=CHAT, run=RUN, orun=PRODUCER, step=HANDOFF_STEP, generation=1):
    """The result 6b-1 posts for a hand-off run: its chat invocation names the producing run."""
    metadata = {
        "workflow_delivery": {
            "version": 1, "kind": "result", "workflow_id": WORKFLOW, "workflow_scope": "personal",
            "run_id": run, "generation": generation, "run_status": "completed",
            "orchestration_run_id": orun, "step_id": step, "requested_at": REQUESTED_AT,
        },
        "workflow_result": {
            "version": "workflow-result-v1", "workflow_id": WORKFLOW, "run_id": run,
            "result_sha256": "b" * 64, "status": "completed", "workflow_name": HANDOFF_NAME,
            "completed_at": COMPLETED_AT, "available": True,
        },
    }
    label = f"Results from `{HANDOFF_NAME}` · you asked on Mon Jan 5, 2026, 9:00 AM UTC"
    return {
        "id": delivery_id(run, conversation, generation), "conversation_id": conversation,
        "role": "assistant", "content": f"{label}\n\n{REPORT}", "metadata": metadata,
        "citations": [], "user_message": None,
    }


class HandoffRunHarness(RunHarness):
    """The run card harness, with the plan's answer handing work off and the hand-off list route."""

    def __init__(self, page, stylesheets):
        super().__init__(page, stylesheets)
        self.messages_by_chat[CHAT] = handoff_messages()
        # Phase 5's run list names only workflow_run steps, and a hand-off plan has none.
        self.link_items.clear()
        self.handoff_items = [queued_item()]
        self.handoff_error = None
        self.handoff_queries = []

    def other_route(self, route, method, path, query):
        if method == "GET" and path == HANDOFFS:
            conversation = query.get("conversation_id")
            self.handoff_queries.append(conversation)
            if conversation != CHAT:
                self.unexpected.append(f"{method} {path} for {conversation!r}")
                return self.answer(route, path, 404, {"error": "Run not found.", "code": "run_not_found"})
            if self.handoff_error:
                status, payload = self.handoff_error
                return self.answer(route, path, status, payload)
            route.fulfill(json={"run_id": ORUN, "handoffs": copy.deepcopy(self.handoff_items)})
            return True
        return super().other_route(route, method, path, query)

    def open(self, *, features=None, settings=None, browser=None, wait_card=True, wait_tracker=True):
        self.page.add_init_script(script=ALIAS)
        Harness.open(
            self, "/chat", browser=browser, active=CHAT,
            features=dict(HANDOFF_FEATURES if features is None else features),
            settings=dict(SETTINGS if settings is None else settings),
        )
        self.js(f"""() => {{
            const boot = {H}.stores.bootstrap.useBootstrapStore;
            boot.setState({{ data: {{ ...boot.getState().data, orchestration: {{ enabled: true, capabilities: [] }} }} }});
        }}""")
        self.js(f"(id) => {H}.stores.chat.useChatStore.getState().selectConversation(id)", CHAT)
        expect(self.page.get_by_text(HANDOFF_QUESTION, exact=True)).to_be_visible()
        if wait_card:
            expect(self.card).to_be_visible()
        if wait_tracker:
            self.wait_for(lambda: bool(self.tracker_checked()), "the tracker read every chat's runs")

    @property
    def card(self):
        return self.page.get_by_role("region", name="Workflow hand-offs")

    @property
    def live_row(self):
        # The tasks are an ordered list, so the only unordered list item is the live run row.
        return self.card.locator("ul > li")

    @property
    def card_state(self):
        return self.card.locator("article").get_by_role("status").first

    def deliver(self, conversation=CHAT, *, run=RUN, at=None):
        """6b-1 posts the hand-off run's result: the message, the unread mark and the delivered row."""
        index = next(i for i, row in enumerate(self.status_rows) if row["run_id"] == run)
        previous = self.status_rows[index]
        message = delivered_handoff_message(
            conversation=conversation, run=run, orun=previous["orchestration_run_id"], step=previous["step_id"],
        )
        self.messages_by_chat.setdefault(conversation, []).append(message)
        self.conversations[conversation]["unread"] = True
        self.status_rows[index] = hrow(
            "completed", conversation=conversation, run=run, step=previous["step_id"],
            orun=previous["orchestration_run_id"],
            delivery=delivered(run=run, conversation=conversation, at=at or self.peek()),
        )
        return message["id"]


@pytest.fixture
def ui(page, run_assets):  # noqa: F811
    api = HandoffRunHarness(page, run_assets)
    yield api
    assert not api.errors, api.errors
    assert not api.unexpected, api.unexpected
    injected = api.page.evaluate("() => window.__xss")
    assert injected is None
    assert not [entry for entry in api.requests if "resume-failed" in entry[1]]


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


# The live run -----------------------------------------------------------------------------------


def test_the_queued_handoff_run_shows_live_from_the_run_that_prepared_it(ui):
    ui.status_rows = [hrow("running")]
    ui.open()
    expect(ui.card_state).to_have_text("Run queued")
    row = ui.live_row
    expect(row).to_have_count(1)
    expect(row).to_contain_text("Handed-off workflow")
    expect(row.get_by_role("status").first).to_contain_text("Running")
    expect(row).to_contain_text("Step 2 of 4")
    expect(row.get_by_role("button", name=f"Cancel run of {HANDOFF_NAME}", exact=True)).to_be_visible()
    expect(row.get_by_role("link", name=f"Open run of {HANDOFF_NAME}", exact=True)).to_have_attribute("href", RUN_HREF)
    expect(ui.card.get_by_text(DELIVERY_TEXT, exact=True)).to_be_visible()
    checked = ui.card.get_by_text(re.compile(r"^Checked "))
    expect(checked).to_have_text(f"Checked {ui.local_time('2026-01-05T09:07:00Z')}")
    expect(checked).to_have_attribute("aria-live", "polite")
    # Live, so neither the list's own status nor the static footnote, and no second way to the workflow.
    expect(ui.card.get_by_text("Run: Queued", exact=True)).to_have_count(0)
    expect(ui.card.get_by_text(STATIC_FOOTNOTE, exact=True)).to_have_count(0)
    expect(ui.card.get_by_role("link", name="Open workflow", exact=True)).to_have_count(0)
    # The harness selects the chat again after loading it, so the list can be read more than once.
    assert ui.handoff_queries
    assert set(ui.handoff_queries) == {CHAT}

    ui.status_error = 503
    ui.check_now()
    expect(ui.card.get_by_text(READ_ERROR, exact=True)).to_be_visible()
    expect(row.get_by_role("status").first).to_contain_text("Running")

    ui.status_error = None
    ui.status_rows = [hrow("completed", delivery={"status": "pending", "generation": 1})]
    ui.check_now()
    expect(row.get_by_role("status").first).to_contain_text("Completed")
    expect(row).to_contain_text("Posting results…")
    expect(ui.card.get_by_text(READ_ERROR, exact=True)).to_have_count(0)
    expect(row.get_by_role("button", name=f"Cancel run of {HANDOFF_NAME}", exact=True)).to_have_count(0)

    row.get_by_role("link", name=f"Open run of {HANDOFF_NAME}", exact=True).click()
    expect(ui.page.locator("[data-workflows-page]")).to_contain_text(f"?workflow_id={WORKFLOW}&run_id={RUN}")


def test_an_over_limit_pause_says_why_and_offers_cancel_rather_than_approve(ui):
    ui.status_rows = [hrow("waiting", waiting=PAUSE)]
    ui.open()
    row = ui.live_row
    expect(row.get_by_role("status").first).to_contain_text("Needs you")
    expect(row).to_contain_text(PAUSED_TEXT)
    expect(row).not_to_contain_text(GENERIC_PAUSE)
    expect(row).not_to_contain_text("Step 2 of 4")
    expect(row.get_by_role("link", name=f"Review and approve {HANDOFF_NAME}", exact=True)).to_have_count(0)
    expect(row.get_by_role("button", name=f"Retry run of {HANDOFF_NAME}", exact=True)).to_have_count(0)
    expect(row.get_by_role("link", name=f"Open run of {HANDOFF_NAME}", exact=True)).to_have_attribute("href", RUN_HREF)

    # The disabled one-time workflow can't be resumed, so cancelling is the way forward.
    cancel = row.get_by_role("button", name=f"Cancel run of {HANDOFF_NAME}", exact=True)
    dialog = ui.page.get_by_role("dialog").or_(ui.page.get_by_role("alertdialog"))
    cancel.click()
    expect(dialog).to_contain_text("Cancel this run?")
    expect(dialog).to_contain_text(f"This asks {HANDOFF_NAME} to stop.")
    ui.page.wait_for_timeout(300)
    assert ui.cancel_calls == 0
    dialog.get_by_role("button", name="Cancel run", exact=True).click()
    ui.wait_for(lambda: ui.cancel_calls == 1, "Cancel sent one request")
    expect(row).to_contain_text("Cancel requested.")


def test_a_pause_past_the_deadline_reads_as_timed_out_not_as_the_over_limit_pause(ui):
    ui.status_rows = [hrow("expired", waiting=DEADLINE)]
    ui.open()
    row = ui.live_row
    expect(row.get_by_role("status").first).to_contain_text("Timed out")
    expect(row).to_contain_text("It reached its time limit.")
    expect(row).not_to_contain_text(PAUSED_TEXT)
    expect(row).not_to_contain_text(GENERIC_PAUSE)
    expect(row.get_by_role("button", name=f"Cancel run of {HANDOFF_NAME}", exact=True)).to_have_count(0)
    expect(row.get_by_role("link", name=f"Open run of {HANDOFF_NAME}", exact=True)).to_have_attribute("href", RUN_HREF)


@pytest.mark.parametrize("orun", [ORUN, PRODUCER], ids=["mounted-run", "earlier-attempt"])
def test_a_handoff_answer_shows_its_run_once_and_never_the_proposal_or_run_cards(ui, orun):
    # The server refuses a plan that mixes these steps; the card must not rely on that alone.
    ui.messages_by_chat[CHAT] = handoff_messages(
        capabilities=("compose", "workflow_handoff", "workflow_run", "workflow_propose"),
    )
    ui.status_rows = [hrow("running", orun=orun)]
    ui.open()
    expect(ui.live_row).to_have_count(1)
    expect(ui.live_row.get_by_role("status").first).to_contain_text("Running")
    ui.page.wait_for_timeout(500)
    assert ui.count_requests("GET", LINKS) == 0
    assert ui.count_requests("GET", PROPOSALS) == 0
    expect(ui.page.locator('[aria-label="Started workflows"]')).to_have_count(0)
    expect(ui.page.locator('[aria-label="Workflow proposals"]')).to_have_count(0)
    expect(ui.page.get_by_role("button", name=f"Cancel run of {HANDOFF_NAME}", exact=True)).to_have_count(1)
    expect(ui.page.get_by_role("link", name=f"Open run of {HANDOFF_NAME}", exact=True)).to_have_count(1)


UNTRACKED = [
    pytest.param({"step": "step-other"}, id="other-step"),
    pytest.param({"workflow_id": "wf-other"}, id="other-workflow"),
    # Same plan run as the answer, but not the run the hand-off queued.
    pytest.param({"run": "wrun-other", "orun": ORUN}, id="other-run-of-the-same-plan"),
    pytest.param({"conversation": OTHER}, id="other-chat"),
]


@pytest.mark.parametrize("overrides", UNTRACKED)
def test_a_tracked_run_the_handoff_did_not_queue_is_not_shown_as_its_run(ui, overrides):
    ui.status_rows = [hrow("running", **overrides)]
    ui.open()
    ui.wait_for(lambda: CHAT in ui.status_queries(), "the card read this chat's runs")
    ui.page.wait_for_timeout(300)
    expect(ui.live_row).to_have_count(0)
    expect(ui.card.get_by_text("Run: Queued", exact=True)).to_be_visible()
    expect(ui.card.get_by_text(STATIC_FOOTNOTE, exact=True)).to_be_visible()
    expect(ui.card.get_by_role("link", name=f"Open run of {HANDOFF_NAME}", exact=True)).to_have_attribute("href", RUN_HREF)
    expect(ui.card.get_by_role("button", name=f"Cancel run of {HANDOFF_NAME}", exact=True)).to_have_count(0)

    # The same harness shows the run live once the tracker reports the run the hand-off queued.
    ui.status_rows = [hrow("running")]
    ui.check_now()
    expect(ui.live_row).to_have_count(1)
    expect(ui.card.get_by_text("Run: Queued", exact=True)).to_have_count(0)


# Flags off --------------------------------------------------------------------------------------


def tracked_elsewhere_rows():
    return [hrow("running"), hrow("running", conversation=OTHER, run="wrun-2", orun="orun-2")]


def expect_no_status_reads(ui):
    ui.page.wait_for_timeout(1000)
    assert ui.status_queries() == []
    expect(ui.page.get_by_role("img", name=re.compile(r"^Running "))).to_have_count(0)


def test_with_workflow_runs_off_the_list_says_unavailable_and_nothing_reads_status(ui):
    # The hand-off gate needs workflow runs on, so the list discloses nothing.
    ui.handoff_items = [closed_item()]
    ui.status_rows = tracked_elsewhere_rows()
    ui.open(features={**HANDOFF_FEATURES, "enable_chat_orchestration_workflow_runs": False}, wait_tracker=False)
    expect(ui.card_state).to_have_text("Unavailable")
    expect(ui.card).to_contain_text(GATE_TEXT)
    expect(ui.card.get_by_role("link", name=re.compile(r"^Open run"))).to_have_count(0)
    expect(ui.card.get_by_role("button", name="Check now")).to_have_count(0)
    expect(ui.card.get_by_role("button", name="Accept", exact=True)).to_have_count(0)
    expect(ui.live_row).to_have_count(0)
    expect_no_status_reads(ui)


def test_with_personal_workflows_off_the_card_says_so_and_nothing_reads_status(ui):
    ui.handoff_error = WORKFLOWS_OFF_REFUSAL
    ui.status_rows = tracked_elsewhere_rows()
    ui.open(features={**HANDOFF_FEATURES, "allow_user_workflows": False}, wait_tracker=False)
    expect(ui.card.get_by_role("status").filter(has_text=WORKFLOWS_OFF)).to_be_visible()
    expect(ui.card.get_by_role("button", name="Try again", exact=True)).to_be_visible()
    expect(ui.card.locator("article")).to_have_count(0)
    expect(ui.card).not_to_contain_text(WORKFLOWS_OFF_REFUSAL[1]["error"])
    expect_no_status_reads(ui)


@pytest.mark.parametrize("flag", ["allow_user_workflows", "enable_chat_orchestration_workflow_runs"])
def test_a_page_loaded_with_a_tracker_flag_off_shows_the_queued_run_statically(ui, flag):
    # The flag was turned on after this page loaded, so the list already reports the queued run.
    ui.status_rows = tracked_elsewhere_rows()
    ui.open(features={**HANDOFF_FEATURES, flag: False}, wait_tracker=False)
    expect(ui.card_state).to_have_text("Run queued")
    expect(ui.card.get_by_text("Run: Queued", exact=True)).to_be_visible()
    expect(ui.card.get_by_text(STATIC_FOOTNOTE, exact=True)).to_be_visible()
    expect(ui.card.get_by_role("button", name="Check now")).to_have_count(0)
    expect(ui.card.get_by_role("link", name=f"Open run of {HANDOFF_NAME}", exact=True)).to_have_attribute("href", RUN_HREF)
    expect(ui.live_row).to_have_count(0)
    expect_no_status_reads(ui)


# The chat list, the bell and the delivered result -----------------------------------------------


def test_the_running_tag_names_the_handoff_workflow_and_gives_way_to_the_unread_dot(ui):
    ui.handoff_items = [pending_item()]
    ui.status_rows = [hrow("running", conversation=OTHER, run="wrun-2", orun="orun-2")]
    ui.open()
    tag = ui.tag(f"Running {HANDOFF_NAME}")
    expect(tag).to_be_visible()
    expect(tag).to_have_attribute("title", f"Running {HANDOFF_NAME}")
    row_text = tag.evaluate("(element) => element.closest('li')?.textContent || ''")
    assert OTHER_TITLE in row_text
    expect(ui.unread_dot(OTHER_TITLE)).to_have_count(0)

    ui.conversations[OTHER]["unread"] = True
    ui.js(f"() => {H}.stores.chat.useChatStore.getState().loadConversations({{ reset: true }})")
    expect(ui.unread_dot(OTHER_TITLE)).to_be_visible()
    expect(tag).to_have_count(0)


def test_a_handoff_result_posted_to_another_chat_marks_it_unread_and_notifies_once(ui):
    ui.handoff_items = [pending_item()]
    ui.status_rows = [hrow("running", conversation=OTHER, run="wrun-2", orun="orun-2")]
    ui.open()
    tag = ui.tag(f"Running {HANDOFF_NAME}")
    expect(tag).to_be_visible()
    ui.blur()

    message_id = ui.deliver(OTHER, run="wrun-2")
    counts = ui.count_reads()
    ui.global_check()
    ui.wait_for(lambda: len(ui.replies()) == 1, "the delivery was announced")
    reply = ui.replies()[0]
    assert {key: reply.get(key) for key in ("conversationId", "messageId", "runId", "source")} == {
        "conversationId": OTHER, "messageId": message_id, "runId": "wrun-2", "source": "workflow",
    }, reply
    expect(ui.unread_dot(OTHER_TITLE)).to_be_visible()
    expect(tag).to_have_count(0)
    ui.wait_for(lambda: ui.count_reads() > counts, "the bell count was refreshed")
    ui.wait_for(lambda: len(ui.notifications()) == 1, "one desktop notification")
    notifications = ui.notifications()
    assert notifications[0]["tag"] == f"simplechat-conversation-{OTHER}"
    assert ui.mark_reads(OTHER) == 0
    assert ui.message_reads(OTHER) == 0

    ui.global_check()
    ui.page.wait_for_timeout(300)
    replies, notifications = ui.replies(), ui.notifications()
    assert len(replies) == 1
    assert len(notifications) == 1


def test_a_handoff_result_posted_to_the_open_chat_reloads_it_and_names_the_workflow(ui):
    ui.status_rows = [hrow("running")]
    ui.open()
    expect(ui.live_row.get_by_role("status").first).to_contain_text("Running")

    message_id = ui.deliver()
    reads = ui.message_reads()
    ui.global_check()
    expect(ui.page.get_by_text(REPORT)).to_be_visible()
    assert ui.message_reads() == reads + 1
    ui.wait_for(lambda: len(ui.replies()) == 1, "the delivery was announced")
    reply = ui.replies()[0]
    assert (reply["conversationId"], reply["messageId"], reply["runId"], reply["source"]) == (
        CHAT, message_id, RUN, "workflow")
    ui.wait_for(lambda: ui.mark_reads(CHAT) == 1, "the watched reply was marked read")
    expect(ui.unread_dot(CHAT_TITLE)).to_have_count(0)

    # The footer finds the run by the producing plan run the delivery names, not the answer's.
    expect(ui.card.get_by_role("button", name=f"Results posted below for {HANDOFF_NAME}", exact=True)) \
        .to_be_visible()
    footer = ui.footer(message_id)
    expect(footer.get_by_role("link", name=f"Open run of {HANDOFF_NAME}", exact=True)).to_have_attribute("href", RUN_HREF)
    expect(footer.get_by_role("button", name=f"Follow up on {HANDOFF_NAME}", exact=True)).to_be_visible()
    ui.expect_no_plain_retry(message_id)
    expect(ui.page.locator('[data-workflow-result-chip="selected"]')).to_be_visible()
    expect(ui.live_row).to_have_count(1)


def test_handoff_and_run_names_render_as_text(ui):
    ui.handoff_items = [queued_item(workflow={"name": HOSTILE})]
    ui.status_rows = [hrow("running", name=HOSTILE)]
    ui.open()
    expect(ui.card.locator("article h4")).to_have_text(HOSTILE)
    expect(ui.live_row).to_contain_text(HOSTILE)
    expect(ui.live_row.get_by_role("button", name=f"Cancel run of {HOSTILE}", exact=True)).to_be_visible()
    expect(ui.card).to_contain_text(f"{HOSTILE} Legal")
    expect(ui.card.locator("img")).to_have_count(0)
