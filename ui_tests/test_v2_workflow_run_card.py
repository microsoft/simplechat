# test_v2_workflow_run_card.py
"""
UI test for the V2 workflow run card, the app-shell run tracker and delivered-message footers.
Version: 0.261.237
Implemented in: 0.261.237

This test ensures that a saved workflow run a chat-orchestration plan started is shown and settled
correctly in V2. It mounts the real app shell, chat list and chat page with the real stores and the
real run tracker, stubs every server route at the network layer, and checks:

- the live run card under the plan's answer: each state the status route reports, Check now and
  its time, Cancel behind a confirmation, Retry as the durable runtime resume from a fresh
  runtime read with a fresh request id (never /resume-failed), and Review and approve held while
  another action on the same run is under way;
- that the tracker's runs for the answer still show, live, when the plan's own run list failed to
  load or names none of them, that they wait for the list to answer, that a step the list says
  can't be opened stays closed, and that a plan run that is gone shows no card at all;
- the running tag in the chat list, and how it gives way to the unread dot;
- how a delivery that lands during the page session is settled: in another chat, and in the open
  chat after any active stream or orchestration turn ends, without overriding the user's choice
  of source, and without replacing a question the user sent while the chat was being re-read;
- the footer on each delivered message (Follow up, Retry workflow run, Open run), and that the
  plain chat Retry and Edit are absent on delivered messages;
- that nothing reads run status when the feature flags are off, that one tracker tick is one
  request, and that deliveries already in the first read stay quiet.

Refs #1546 (Phase 6), #1543 (Chat Orchestration Workflows), #1610 (6b-1, the server half).
"""

import copy
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONAL_TESTS = ROOT / "functional_tests"
for _entry in (ROOT, FUNCTIONAL_TESTS):
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from test_support.versioning import assert_app_version_at_least  # noqa: E402
from ui_tests.fixtures.agent_delegation.harness_build import ensure_bundle  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401
from ui_tests.test_v2_notifications_bell import Harness, STATIC, V2_SOURCE  # noqa: E402


pytestmark = pytest.mark.ui

IMPLEMENTED_IN = "0.261.237"
FIXTURE = ROOT / "ui_tests" / "fixtures" / "workflow_run_tracking"
BUNDLE = FIXTURE / "harness.bundle.js"

CHAT = "chat-1"
CHAT_TITLE = "Weekly planning"
OTHER = "chat-2"
OTHER_TITLE = "Budget review"
ORUN = "orun-1"
TURN = "turn-1"
WORKFLOW = "wf-digest"
RUN = "wrun-1"
STEP = "step-1"
NAME = "Weekly digest"
HOSTILE = '<img src=x onerror="window.__xss=1">'

STATUS = "/api/v2/orchestration/workflow-runs/status"
LINKS = f"/api/v2/orchestration/runs/{ORUN}/workflow-runs"
PROPOSALS = f"/api/v2/orchestration/runs/{ORUN}/workflow-proposals"
RUN_BASE = f"/api/user/workflows/{WORKFLOW}/runs/{RUN}"
RUN_HREF = f"/workspace/workflows?workflow_id={WORKFLOW}&run_id={RUN}"
M365_HREF = "/profile?tab=settings#m365-connection-status"

FEATURES = {
    "enable_desktop_notifications": True,
    "enable_chat_orchestration": True,
    "allow_user_workflows": True,
    "enable_chat_orchestration_workflow_runs": True,
    "enable_chat_workflow_results": True,
}
SETTINGS = {"desktopNotificationsEnabled": True}

CLOCK_START = datetime(2026, 1, 5, 9, 7, 0, tzinfo=timezone.utc)
REQUESTED_AT = "2026-01-05T09:00:00Z"
STARTED_AT = "2026-01-05T09:00:05Z"
COMPLETED_AT = "2026-01-05T09:05:00Z"

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
STATIC_FOOTNOTE = "Status when this message loaded. Open the run for its progress and results."
READ_ERROR = "Couldn't check the run status right now. Try again."
LOAD_ERROR = "Could not load the workflow runs this plan started."
QUESTION = "What changed since last week?"
RETRY_REFUSAL = (
    "A workflow run posted this message, so it can't be retried here. "
    "To run the workflow again, open the run in Workflows."
)
RUNTIME_FAILED = {
    "runtime": {"schema_version": 1, "version": 9, "state": "failed", "can_resume": True},
    "can_decide": False,
}
RUNTIME_RESUMED = {
    "runtime": {"schema_version": 1, "version": 10, "state": "running", "can_resume": False},
    "can_decide": False,
}

# The one tracker the harness's app shell starts; a test reads its state and kicks it directly.
ALIAS = (
    "Object.defineProperty(window, 'NotificationHarness', "
    "{ configurable: true, get: () => window.WorkflowRunTrackingHarness });"
)
H = "window.WorkflowRunTrackingHarness"

PHASES = {
    "queued": "running", "running": "running", "waiting": "needs_you",
    "completed": "finished", "completed_partial": "finished",
    "failed": "failed", "expired": "failed", "cancelled": "cancelled",
}
ACTIVE = {"queued", "running", "waiting"}
FAILURES = {
    "failed": ("The run stopped before it finished.", "failed"),
    "expired": ("It reached its time limit.", "deadline_exceeded"),
}
APPROVAL = {"reason": "approval", "action": "approve", "gate_id": "gate-1"}


def merge(base, overrides):
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge(base[key], value)
        else:
            base[key] = value
    return base


def status_row(status, *, conversation=CHAT, run=RUN, step=STEP, orun=ORUN, name=NAME, **overrides):
    """One row as GET /api/v2/orchestration/workflow-runs/status projects it (6b-1)."""
    active = status in ACTIVE
    error, code = FAILURES.get(status, (None, None))
    row = {
        "workflow_id": WORKFLOW, "workflow_scope": "personal", "run_id": run,
        "conversation_id": conversation, "orchestration_run_id": orun, "step_id": step,
        "workflow_name": name,
        "status": status, "phase": PHASES.get(status, "running"),
        "runtime_version": 7, "step_index": 1, "step_count": 4, "step_label": None,
        "waiting": None, "live": active,
        "requested_at": REQUESTED_AT, "started_at": STARTED_AT,
        "completed_at": None if active or status == "expired" else COMPLETED_AT,
        "elapsed_seconds": 95,
        "delivery": {"status": "not_applicable", "generation": None, "message_id": None,
                     "delivered_at": None, "reason": None},
        "error": error, "error_code": code, "retry_blocked": None,
        "actions": {"cancel": active, "retry": False, "approve": False, "open_run": True},
    }
    return merge(row, copy.deepcopy(overrides))


def delivery_id(run=RUN, conversation=CHAT, generation=1):
    """6b-1's delivered message id: a hash of the run, the chat and the generation."""
    canonical = json.dumps([run, conversation, generation], ensure_ascii=False, separators=(",", ":"))
    return "assistant_workflow_delivery_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:40]


def delivered(*, run=RUN, conversation=CHAT, generation=1, at="2026-01-05T09:05:30Z"):
    return {"status": "delivered", "generation": generation,
            "message_id": delivery_id(run, conversation, generation), "delivered_at": at, "reason": None}


def answer_messages(conversation=CHAT):
    """The plan's question and its saved answer, which started the workflow."""
    return [
        {"id": "user-1", "conversation_id": conversation, "role": "user",
         "content": "Run my weekly digest now.", "metadata": {"orchestration_turn_id": TURN}},
        {"id": "answer-1", "conversation_id": conversation, "role": "assistant",
         "content": "Started `Weekly digest`. I'll post the results here when the run finishes.",
         "metadata": {"orchestration": {
             "run_id": ORUN, "turn_id": TURN, "outcome": "completed", "finalization_status": "saved",
             "message_saved": True,
             "plan_summary": {
                 "plan_id": "plan-1", "turn_id": TURN, "status": "completed",
                 "intent_summary": "Run my weekly digest now", "step_count": 2,
                 "capabilities_used": ["compose", "workflow_run"],
             },
         }}},
    ]


NOTE_TEXT = {
    "result": "The digest found three new files.",
    "failed": f"`{NAME}` failed: the run stopped before it finished.",
    "cancelled": f"`{NAME}` was cancelled.",
    "status": f"`{NAME}` finished. Open the run to see its results.",
}


def delivered_message(kind="result", *, conversation=CHAT, run=RUN, generation=1, available=True):
    """A message 6b-1 posts into the chat, with its workflow_delivery metadata."""
    metadata = {"workflow_delivery": {
        "version": 1, "kind": kind, "workflow_id": WORKFLOW, "workflow_scope": "personal",
        "run_id": run, "generation": generation,
        "run_status": {"result": "completed", "failed": "failed", "cancelled": "cancelled"}.get(kind, "completed"),
        "orchestration_run_id": ORUN, "step_id": STEP, "requested_at": REQUESTED_AT,
    }}
    if kind in ("result", "analysis"):
        metadata["workflow_result"] = {
            "version": "workflow-result-v1", "workflow_id": WORKFLOW, "run_id": run,
            "result_sha256": "a" * 64, "status": "completed", "workflow_name": NAME,
            "completed_at": COMPLETED_AT, "available": available,
        }
    label = f"Results from `{NAME}` · you asked on Mon Jan 5, 2026, 9:00 AM UTC"
    return {
        "id": delivery_id(run, conversation, generation), "conversation_id": conversation,
        "role": "assistant", "content": f"{label}\n\n{NOTE_TEXT[kind]}", "metadata": metadata,
        "citations": [], "user_message": None,
    }


class RunHarness(Harness):
    """The bell harness's network stubs, with the run status, run links and run action routes."""

    def __init__(self, page, stylesheets):
        super().__init__(page, stylesheets, {CHAT: CHAT_TITLE, OTHER: OTHER_TITLE})
        self.messages_by_chat = {CHAT: answer_messages(), OTHER: []}
        self.link_items = [{"step_id": STEP, "name": NAME, "state": "running", "reason": None,
                            "workflow_id": WORKFLOW, "workflow_run_id": RUN}]
        self.status_rows = []
        self.available = True
        self.truncated = False
        self.status_error = None
        self.clock = CLOCK_START
        self.global_checked = []
        self.runtime_status = 200
        self.runtime_payload = copy.deepcopy(RUNTIME_FAILED)
        self.resume_status = 200
        self.resume_code = None
        self.resume_bodies = []
        self.hold_resume = False
        self.held_resumes = []
        self.cancel_status = 200
        self.cancel_calls = 0
        self.retry_calls = []
        self.links_status = 200
        self.hold_links = False
        self.held_links = []
        self.hold_messages = False
        self.held_messages = []
        # Above the seeded chat's ids, so a question sent here and its reply never reuse them.
        self.streams = 100

    # Routes -----------------------------------------------------------------------------------

    def page_route(self, route, method, path, query):
        if method == "GET" and path == "/harness.html":
            route.fulfill(path=str(FIXTURE / "harness.html"), content_type="text/html")
            return True
        if method == "GET" and path == "/harness.bundle.js":
            route.fulfill(path=str(BUNDLE), content_type="application/javascript")
            return True
        return super().page_route(route, method, path, query)

    def conversation_route(self, route, method, path, query):
        if method == "GET" and path == "/api/get_messages":
            messages = copy.deepcopy(self.messages_by_chat.get(query.get("conversation_id", ""), []))
            if self.hold_messages:
                # Read now and answered on release, as a slow server would.
                self.held_messages.append((route, messages))
            else:
                route.fulfill(json={"messages": messages})
            return True
        return super().conversation_route(route, method, path, query)

    def other_route(self, route, method, path, query):
        if method == "GET" and path == STATUS:
            return self.answer_status(route, path, query)
        if method == "GET" and path == LINKS:
            if self.hold_links:
                self.held_links.append(route)
                return True
            return self.answer_links(route)
        if method == "GET" and path == PROPOSALS:
            route.fulfill(json={"run_id": ORUN, "proposals": []})
            return True
        if method == "GET" and path == f"{RUN_BASE}/runtime":
            return self.answer(route, path, self.runtime_status, self.runtime_payload)
        if method == "POST" and path == f"{RUN_BASE}/runtime/resume":
            self.resume_bodies.append(route.request.post_data_json)
            if self.hold_resume:
                self.held_resumes.append(route)
                return True
            if self.resume_status == 200:
                return self.answer(route, path, 200, RUNTIME_RESUMED)
            payload = {"error": "Raw server text that must not be shown."}
            if self.resume_code:
                payload["code"] = self.resume_code
            return self.answer(route, path, self.resume_status, payload)
        if method == "POST" and path == f"{RUN_BASE}/cancel":
            self.cancel_calls += 1
            if self.cancel_status == 200:
                return self.answer(route, path, 200, {"success": True})
            return self.answer(route, path, self.cancel_status, {"error": "Raw server text that must not be shown."})
        retry = re.fullmatch(r"/api/message/([^/]+)/retry", path)
        if method == "POST" and retry:
            self.retry_calls.append(retry.group(1))
            return self.answer(route, path, 400, {"error": RETRY_REFUSAL, "code": "workflow_delivery_retry_unsupported"})
        return super().other_route(route, method, path, query)

    def answer(self, route, path, status, payload):
        if status >= 400:
            self.expected_http_failures.add((path, status))
        route.fulfill(status=status, json=payload)
        return True

    def release_resumes(self):
        """Answer the held resumes the way the server accepts one."""
        assert self.held_resumes, "No resume was held."
        held, self.held_resumes = self.held_resumes, []
        for route in held:
            self.answer(route, f"{RUN_BASE}/runtime/resume", 200, RUNTIME_RESUMED)

    def answer_links(self, route):
        if self.links_status != 200:
            return self.answer(route, LINKS, self.links_status, {"error": "Raw server text that must not be shown."})
        route.fulfill(json={"run_id": ORUN, "workflow_runs": copy.deepcopy(self.link_items)})
        return True

    def release_links(self):
        """Answer the held reads of the plan's runs with the list as it is now."""
        assert self.held_links, "No read of the plan's runs was held."
        held, self.held_links = self.held_links, []
        for route in held:
            self.answer_links(route)

    def release_messages(self):
        """Answer the held message reads with the messages each one was cut from when it arrived."""
        assert self.held_messages, "No message read was held."
        held, self.held_messages = self.held_messages, []
        for route, messages in held:
            route.fulfill(json={"messages": messages})

    def answer_stream(self, route, body):
        """Save the question and its reply, as the server does, then finish the reply."""
        conversation = body.get("conversation_id") or CHAT
        number = self.streams + 1
        self.messages_by_chat.setdefault(conversation, []).extend([
            {"id": f"user-{number}", "conversation_id": conversation, "role": "user",
             "content": body.get("message", ""), "metadata": {}},
            {"id": f"reply-{number}", "conversation_id": conversation, "role": "assistant",
             "content": "Here is the plan.", "metadata": {}},
        ])
        super().answer_stream(route, body)

    def answer_status(self, route, path, query):
        if self.status_error:
            return self.answer(route, path, self.status_error, {
                "error": "Workflow run status isn't available right now. Try again later.",
                "code": "workflow_run_status_unavailable",
            })
        conversation = query.get("conversation_id")
        rows = [row for row in self.status_rows if conversation is None or row["conversation_id"] == conversation]
        checked_at = self.peek()
        self.clock += timedelta(seconds=1)
        if conversation is None:
            self.global_checked.append(checked_at)
        return self.answer(route, path, 200, {
            "available": self.available, "runs": copy.deepcopy(rows),
            "checked_at": checked_at, "truncated": self.truncated,
        })

    def peek(self):
        """The checked_at the next status response carries."""
        return self.clock.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Opening ----------------------------------------------------------------------------------

    def open(self, *, features=None, settings=None, browser=None, wait_card=True, wait_tracker=True):
        self.page.add_init_script(script=ALIAS)
        super().open(
            "/chat", browser=browser, active=CHAT,
            features=dict(FEATURES if features is None else features),
            settings=dict(SETTINGS if settings is None else settings),
        )
        self.js(f"""() => {{
            const boot = {H}.stores.bootstrap.useBootstrapStore;
            boot.setState({{ data: {{ ...boot.getState().data, orchestration: {{ enabled: true, capabilities: [] }} }} }});
        }}""")
        self.js(f"(id) => {H}.stores.chat.useChatStore.getState().selectConversation(id)", CHAT)
        expect(self.page.get_by_text("Run my weekly digest now.", exact=True)).to_be_visible()
        if wait_card:
            expect(self.card).to_be_visible()
        if wait_tracker:
            self.wait_for(lambda: bool(self.tracker_checked()), "the tracker read every chat's runs once")

    # Reading ----------------------------------------------------------------------------------

    @property
    def card(self):
        return self.page.get_by_role("region", name="Started workflows")

    @property
    def live_row(self):
        return self.card.get_by_role("listitem")

    def footer(self, message_id):
        return self.page.locator(f"#workflow-delivery-{message_id}")

    def expect_no_plain_retry(self, message_id):
        """The delivered message keeps its own actions, but not the plain chat Retry or Edit."""
        message = self.page.locator(f"#message-{message_id}")
        expect(message.get_by_role("button", name="Copy", exact=True)).to_have_count(1)
        expect(message.get_by_role("button", name="Retry", exact=True)).to_have_count(0)
        expect(message.get_by_role("button", name="Review orchestration recovery")).to_have_count(0)
        # The question in the same chat still offers Edit, so its absence below is not a closed menu.
        self.expect_edit_offered("user-1", True)
        self.expect_edit_offered(message_id, False)

    def expect_edit_offered(self, message_id, offered):
        """Open the message's More actions menu, check it opened, and look for Edit."""
        message = self.page.locator(f"#message-{message_id}")
        more = message.get_by_role("button", name="More actions", exact=True)
        copy_with_sources = message.get_by_role("button", name="Copy with sources", exact=True)
        more.click()
        expect(copy_with_sources).to_be_visible()
        expect(message.get_by_role("button", name="Edit", exact=True)).to_have_count(1 if offered else 0)
        more.click()
        expect(copy_with_sources).to_have_count(0)

    def tag(self, label=f"Running {NAME}"):
        return self.page.get_by_role("img", name=label, exact=True)

    def rail_row(self, title):
        return self.page.locator("li", has_text=title).last

    def unread_dot(self, title):
        return self.rail_row(title).locator('span[aria-label="Unread"]')

    def tracker_checked(self):
        return self.js(f"() => {H}.stores.workflowRunTracker.useWorkflowRunTrackerStore.getState().snapshot.globalCheckedAt")

    def replies(self):
        return self.js(f"() => {H}.completedReplies.map((reply) => ({{ ...reply }}))")

    def workflow_replies(self):
        return [reply for reply in self.replies() if reply.get("source") == "workflow"]

    def tracked_runs(self):
        return self.js(f"""() => Object.values(
            {H}.stores.workflowRunTracker.useWorkflowRunTrackerStore.getState().snapshot.runs,
        ).map((tracked) => tracked.row.run_id)""")

    def chat_state(self, key):
        return self.js(f"(key) => {H}.stores.chat.useChatStore.getState()[key]", key)

    def local_time(self, iso):
        return self.js("(iso) => new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })", iso)

    def status_queries(self):
        """The chat each status read asked about, in order; None for a read of every chat."""
        found = []
        for entry in self.requests:
            parts = urlsplit(entry[1])
            if entry[0] == "GET" and parts.path == STATUS:
                found.append(parse_qs(parts.query).get("conversation_id", [None])[-1])
        return found

    def global_reads(self):
        return self.status_queries().count(None)

    def message_reads(self, conversation=CHAT):
        count = 0
        for entry in self.requests:
            parts = urlsplit(entry[1])
            if entry[0] == "GET" and parts.path == "/api/get_messages" \
                    and parse_qs(parts.query).get("conversation_id", [None])[-1] == conversation:
                count += 1
        return count

    def mark_reads(self, conversation):
        return self.count_requests("POST", f"/api/conversations/{conversation}/mark-read")

    def count_reads(self):
        return sum(
            1 for entry in self.requests
            if entry[0] == "GET" and urlsplit(entry[1]).path == "/api/notifications/count"
        )

    # Acting -----------------------------------------------------------------------------------

    def check_now(self):
        button = self.card.get_by_role("button", name="Check now")
        expect(button).not_to_have_attribute("aria-disabled", "true")
        reads = self.status_queries().count(CHAT)
        button.click()
        self.wait_for(lambda: self.status_queries().count(CHAT) > reads, "Check now read this chat's runs")

    def global_check(self):
        """One tracker tick, as its timer would run it."""
        reads = self.global_reads()
        checked = self.tracker_checked()
        self.js(f"() => {H}.tracker.kickWorkflowRunTracker({{ immediate: true }})")
        self.wait_for(lambda: self.global_reads() > reads, "the tracker read every chat's runs")
        self.wait_for(lambda: self.tracker_checked() != checked, "the tracker took in its read")

    def deliver(self, conversation=CHAT, *, run=RUN, kind="result", at=None):
        """6b-1 posts a run's result: the message, the unread mark and the delivered row."""
        message = delivered_message(kind, conversation=conversation, run=run)
        self.messages_by_chat.setdefault(conversation, []).append(message)
        self.conversations[conversation]["unread"] = True
        index = next(i for i, row in enumerate(self.status_rows) if row["run_id"] == run)
        previous = self.status_rows[index]
        self.status_rows[index] = status_row(
            "completed" if kind != "failed" else "failed", conversation=conversation, run=run,
            step=previous["step_id"], orun=previous["orchestration_run_id"],
            delivery=delivered(run=run, conversation=conversation, at=at or self.peek()),
        )
        return message["id"]

    def hold_stream(self, held):
        self.js(f"(held) => {H}.stores.chat.useChatStore.setState({{ streaming: held }})", held)

    def orchestrate_off(self):
        """Switch the composer to plain chat, so Send streams a reply rather than starting a plan."""
        toggle = self.page.get_by_role("button", name="Orchestrate", exact=True)
        expect(toggle).to_have_attribute("aria-pressed", "true")
        toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", "false")

    def hold_orchestration(self, held):
        self.js(f"""(held) => {H}.stores.orchestration.useOrchestrationStore.setState({{ inFlight: held ? {{
            'orun-x': {{ conversationId: '{CHAT}', turnId: 't', runId: 'orun-x', planId: 'p',
                         startedAt: Date.now(), resumed: false }},
        }} : {{}} }})""", held)


@pytest.fixture(scope="module")
def run_assets():
    index = STATIC / "v2" / "index.html"
    assert index.is_file(), "Build the V2 SPA first: npm --prefix application/v2_ui run build"
    built = index.stat().st_mtime
    stale = [item for item in V2_SOURCE.rglob("*") if item.is_file() and item.stat().st_mtime > built]
    if stale:
        pytest.fail(
            f"The V2 bundle is stale ({stale[0].relative_to(ROOT)} changed after it was built). "
            "Run npm --prefix application/v2_ui run build",
        )
    hrefs = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', index.read_text(encoding="utf-8"))
    stylesheets = [STATIC / href.removeprefix("/static/") for href in hrefs]
    assert stylesheets and all(sheet.is_file() for sheet in stylesheets), stylesheets
    ensure_bundle(entry=FIXTURE / "harness_entry.tsx", bundle=BUNDLE)
    yield stylesheets
    BUNDLE.unlink(missing_ok=True)
    # esbuild writes the entry's imported CSS beside the bundle.
    BUNDLE.with_suffix(".css").unlink(missing_ok=True)


@pytest.fixture
def ui(page, run_assets):
    api = RunHarness(page, run_assets)
    yield api
    assert not api.errors, api.errors
    assert not api.unexpected, api.unexpected
    injected = api.page.evaluate("() => window.__xss")
    assert injected is None
    assert not [entry for entry in api.requests if "resume-failed" in entry[1]]


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


# The run card -----------------------------------------------------------------------------------


def test_the_card_follows_each_live_state_the_status_route_reports(ui):
    ui.status_rows = [status_row("running")]
    ui.open()
    row = ui.live_row
    expect(row.get_by_role("status").first).to_contain_text("Running")
    expect(row).to_contain_text("Step 2 of 4")
    expect(row).to_contain_text("1 min elapsed")
    expect(row.get_by_role("button", name=f"Cancel run of {NAME}", exact=True)).to_be_visible()
    expect(row.get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_attribute("href", RUN_HREF)

    # Recovery is still running: it names the reason without asking anything of the user.
    ui.status_rows = [status_row("running", waiting={"reason": "recovery", "action": "open_run", "gate_id": None})]
    ui.check_now()
    expect(row).to_contain_text("Recovering after an interruption.")
    expect(row.get_by_role("status").first).to_contain_text("Running")
    expect(row).not_to_contain_text("Needs you")

    ui.status_rows = [status_row("waiting", waiting=APPROVAL, actions={"approve": True})]
    ui.check_now()
    expect(row.get_by_role("status").first).to_contain_text("Needs you")
    expect(row).to_contain_text("Waiting for your approval.")
    expect(row).not_to_contain_text("Step 2 of 4")
    approve = row.get_by_role("link", name=f"Review and approve {NAME}", exact=True)
    expect(approve).to_have_attribute("href", RUN_HREF)
    expect(row.get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_count(0)

    ui.status_rows = [status_row("waiting", waiting={
        "reason": "microsoft_365_reconnect", "action": "reconnect", "gate_id": None})]
    ui.check_now()
    expect(row).to_contain_text("Reconnect Microsoft 365 to continue.")
    expect(row.get_by_role("link", name="Reconnect Microsoft 365", exact=True)).to_have_attribute("href", M365_HREF)
    expect(row.get_by_role("link", name=f"Review and approve {NAME}", exact=True)).to_have_count(0)

    row.get_by_role("link", name=f"Open run of {NAME}", exact=True).click()
    expect(ui.page.locator("[data-workflows-page]")).to_contain_text(f"?workflow_id={WORKFLOW}&run_id={RUN}")


TERMINAL_CASES = [
    pytest.param(status_row("completed"), "Completed", "The results are in the workflow's run history.",
                 id="completed-not-applicable"),
    pytest.param(status_row("completed_partial", delivery={
        "status": "undeliverable", "generation": 1, "reason": "chat_unavailable"}),
        "Partly completed", "The results are in the workflow's run history.", id="partial-undeliverable"),
    pytest.param(status_row("completed", delivery={"status": "pending", "generation": 1}),
                 "Completed", "Posting results…", id="posting"),
    pytest.param(status_row("completed", delivery=delivered()), "Completed", "Results were posted to this chat.",
                 id="delivered-not-loaded"),
    pytest.param(status_row("failed"), "Failed", "The run stopped before it finished.", id="failed"),
    pytest.param(status_row("expired", delivery={"status": "expired"}), "Timed out", "It reached its time limit.",
                 id="expired"),
    pytest.param(status_row("cancelled"), "Cancelled", "The run was cancelled.", id="cancelled"),
    pytest.param(status_row("mystery"), "Status unavailable", None, id="unknown-status"),
    pytest.param(status_row("failed", error=None), "Status unavailable", None, id="failed-without-error"),
]


@pytest.mark.parametrize("row_data,label,text", TERMINAL_CASES)
def test_finished_and_unknown_states_read_plainly_and_fail_closed(ui, row_data, label, text):
    ui.status_rows = [row_data]
    ui.open()
    row = ui.live_row
    expect(row.get_by_role("status").first).to_contain_text(label)
    if text:
        expect(row).to_contain_text(text)
    expect(row.get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_attribute("href", RUN_HREF)
    expect(row.get_by_role("button", name=f"Cancel run of {NAME}", exact=True)).to_have_count(0)
    expect(row.get_by_role("button", name=f"Retry run of {NAME}", exact=True)).to_have_count(0)
    expect(row.get_by_role("button", name=re.compile("Results posted below"))).to_have_count(0)


def test_check_now_shows_when_it_checked_and_keeps_the_last_state_on_an_error(ui):
    ui.status_rows = [status_row("running")]
    ui.open()
    checked = ui.card.get_by_text(re.compile(r"^Checked "))
    expect(checked).to_have_text(f"Checked {ui.local_time('2026-01-05T09:07:00Z')}")
    expect(checked).to_have_attribute("aria-live", "polite")

    ui.clock = datetime(2026, 1, 5, 9, 12, 0, tzinfo=timezone.utc)
    ui.check_now()
    expect(checked).to_have_text(f"Checked {ui.local_time('2026-01-05T09:12:00Z')}")

    ui.status_error = 503
    ui.status_rows = [status_row("failed")]
    ui.check_now()
    expect(ui.card.get_by_text(READ_ERROR, exact=True)).to_be_visible()
    expect(ui.live_row.get_by_role("status").first).to_contain_text("Running")
    expect(checked).to_have_text(f"Checked {ui.local_time('2026-01-05T09:12:00Z')}")

    ui.status_error = None
    ui.check_now()
    expect(ui.live_row.get_by_role("status").first).to_contain_text("Failed")
    expect(ui.card.get_by_text(READ_ERROR, exact=True)).to_have_count(0)


def test_cancel_asks_first_and_reports_each_outcome(ui):
    ui.status_rows = [status_row("running")]
    ui.open()
    row = ui.live_row
    cancel = row.get_by_role("button", name=f"Cancel run of {NAME}", exact=True)
    dialog = ui.page.get_by_role("dialog").or_(ui.page.get_by_role("alertdialog"))

    cancel.click()
    expect(dialog).to_contain_text("Cancel this run?")
    expect(dialog).to_contain_text(f"This asks {NAME} to stop. Anything it already did stays done.")
    expect(dialog).to_contain_text("A cancelled run can't be retried.")
    ui.page.wait_for_timeout(300)
    assert ui.cancel_calls == 0
    dialog.get_by_role("button", name="Keep running", exact=True).click()
    expect(dialog).to_have_count(0)
    assert ui.cancel_calls == 0

    outcomes = [
        (200, "Cancel requested."),
        (404, "This run is no longer available."),
        (409, "This run already finished or changed. Check its status."),
        (500, "Couldn't cancel the run. Try again."),
    ]
    for status, text in outcomes:
        ui.cancel_status = status
        calls = ui.cancel_calls
        expect(cancel).not_to_have_attribute("aria-disabled", "true")
        cancel.click()
        dialog.get_by_role("button", name="Cancel run", exact=True).click()
        ui.wait_for(lambda: ui.cancel_calls == calls + 1, f"Cancel sent one request for {status}")
        expect(row).to_contain_text(text)
    assert ui.cancel_calls == len(outcomes)


RESUME_REFUSALS = [
    (409, "stale_version", "The run changed since it was checked. Check its status and try again."),
    (409, "invalid_state", "This run can't be retried in its current state."),
    (409, "request_conflict", "Another request changed this run. Check its status and try again."),
    (409, "workflow_deleting", "The workflow is being deleted, so this run can't be retried."),
    (409, "workflow_definition_changed", "The workflow changed after this run started. Start a new run from Workflows."),
    (409, "workflow_already_running", "Another run of this workflow is in progress. Retry when it finishes."),
    (409, "deadline_exceeded", "This run reached its time limit, so it can't be retried."),
    (409, "workflow_deleted", "The workflow was deleted, so this run can't be retried."),
    (409, "a_new_code", "This run can't be retried right now. Check its status."),
    (400, None, "The retry request wasn't accepted."),
    (403, None, "You don't have access to this run."),
    (404, None, "This run is no longer available."),
    (503, None, "Workflows aren't available right now. Try again later."),
    (500, None, "Couldn't retry the run. Try again."),
]


def test_retry_resumes_from_a_fresh_runtime_read_and_explains_each_refusal(ui):
    ui.status_rows = [status_row("failed", actions={"retry": True})]
    ui.open()
    row = ui.live_row
    retry = row.get_by_role("button", name=f"Retry run of {NAME}", exact=True)

    retry.click()
    ui.wait_for(lambda: len(ui.resume_bodies) == 1, "Retry sent one resume")
    first = ui.resume_bodies[0]
    assert set(first) == {"expected_version", "request_id"}, first
    assert first["expected_version"] == 9, "Retry resumes from the fresh runtime read, not the row's version"
    assert UUID.fullmatch(first["request_id"]), first
    expect(row).to_contain_text("Retry requested.")

    for status, code, text in RESUME_REFUSALS:
        ui.resume_status, ui.resume_code = status, code
        sent = len(ui.resume_bodies)
        expect(retry).not_to_have_attribute("aria-disabled", "true")
        retry.click()
        ui.wait_for(lambda: len(ui.resume_bodies) == sent + 1, f"Retry sent one resume for {status} {code}")
        expect(row).to_contain_text(text)
        shown = row.inner_text()
        assert "Raw server text" not in shown
    request_ids = [body["request_id"] for body in ui.resume_bodies]
    assert len(set(request_ids)) == len(request_ids), "Each Retry sends a fresh request id"

    # A run the runtime says can't be resumed, or a runtime read that's refused, sends nothing.
    sent = len(ui.resume_bodies)
    ui.runtime_payload = {"runtime": {"schema_version": 1, "version": 9, "state": "failed", "can_resume": False},
                          "can_decide": False}
    retry.click()
    expect(row).to_contain_text("This run can't be retried anymore.")
    ui.runtime_status = 403
    retry.click()
    expect(row).to_contain_text("You don't have access to this run.")
    ui.page.wait_for_timeout(300)
    assert len(ui.resume_bodies) == sent


@pytest.mark.parametrize("overrides,available,text", [
    pytest.param({"actions": {"retry": False}}, True, None, id="actions-retry-false"),
    pytest.param({"retry_blocked": "workflow_definition_changed"}, True,
                 "The workflow changed after this run started. Start a new run from Workflows.", id="blocked"),
    pytest.param({"actions": {"retry": True}}, False,
                 "Starting workflows from chat is turned off, so Retry isn't available here.", id="gate-off"),
])
def test_retry_shows_only_where_the_status_row_allows_it(ui, overrides, available, text):
    ui.available = available
    ui.status_rows = [status_row("failed", **overrides)]
    ui.open()
    row = ui.live_row
    expect(row.get_by_role("status").first).to_contain_text("Failed")
    if text:
        expect(row).to_contain_text(text)
    expect(row.get_by_role("button", name=f"Retry run of {NAME}", exact=True)).to_have_count(0)
    assert ui.resume_bodies == []


def test_server_names_render_as_text(ui):
    ui.link_items[0]["name"] = HOSTILE
    ui.status_rows = [
        status_row("running"),
        status_row("running", conversation=OTHER, run="wrun-2", step="step-2", orun="orun-2", name=HOSTILE),
    ]
    ui.open()
    expect(ui.card.get_by_text(HOSTILE, exact=True).first).to_be_visible()
    tag = ui.tag(f"Running {HOSTILE}")
    expect(tag).to_be_visible()
    expect(tag).to_have_attribute("title", f"Running {HOSTILE}")
    expect(ui.page.locator("img[src='x']")).to_have_count(0)


@pytest.mark.parametrize("links_status,link_items", [(500, None), (200, [])], ids=["list-failed", "list-empty"])
def test_runs_the_plans_list_does_not_name_still_show_live(ui, links_status, link_items):
    ui.links_status = links_status
    if link_items is not None:
        ui.link_items = link_items
    ui.status_rows = [
        status_row("running"),
        status_row("queued", run="wrun-0", step="step-0", name=HOSTILE, requested_at="2026-01-05T08:59:00Z"),
    ]
    ui.open()
    expect(ui.card.get_by_text(LOAD_ERROR, exact=True)).to_have_count(1 if links_status != 200 else 0)
    expect(ui.card.get_by_role("button", name="Try again", exact=True)).to_have_count(1 if links_status != 200 else 0)

    # Oldest request first, and the name the status row carries renders as text.
    rows = ui.live_row
    expect(rows).to_have_count(2)
    expect(rows.nth(0)).to_contain_text(HOSTILE)
    expect(rows.nth(0).get_by_role("status").first).to_contain_text("Queued")
    expect(rows.nth(1).get_by_role("status").first).to_contain_text("Running")
    expect(rows.nth(1).get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_attribute("href", RUN_HREF)
    expect(ui.card.get_by_text(re.compile(r"^Checked "))).to_be_visible()
    ui.wait_for(lambda: CHAT in ui.status_queries(), "the card read its chat's runs")
    ui.check_now()


def test_a_plan_run_that_is_gone_shows_nothing_even_with_tracked_runs(ui):
    ui.links_status = 404
    ui.status_rows = [status_row("running")]
    ui.open(wait_card=False)
    ui.wait_for(lambda: ui.count_requests("GET", LINKS) > 0, "the card read the plan's runs")
    assert ui.tracked_runs() == [RUN]
    ui.page.wait_for_timeout(500)
    expect(ui.card).to_have_count(0)
    assert CHAT not in ui.status_queries()


def test_a_step_the_plans_list_says_cannot_open_stays_closed_with_a_tracked_run(ui):
    ui.link_items = [{"step_id": STEP, "name": NAME, "state": "unavailable", "reason": "content_review",
                      "workflow_id": None, "workflow_run_id": None}]
    ui.status_rows = [status_row("running")]
    # The tracked run waits for the list rather than showing, with its link, before the list answers.
    ui.hold_links = True
    ui.open(wait_card=False)
    ui.wait_for(lambda: ui.held_links, "the card asked for the plan's runs")
    assert ui.tracked_runs() == [RUN]
    ui.page.wait_for_timeout(500)
    expect(ui.card).to_have_count(0)

    ui.hold_links = False
    ui.release_links()
    expect(ui.card.get_by_text(
        "This response is in content review, so its workflow link is not available.", exact=True,
    )).to_be_visible()
    expect(ui.live_row).to_have_count(1)
    expect(ui.card.get_by_role("link")).to_have_count(0)
    expect(ui.card.get_by_role("button", name="Check now")).to_have_count(0)
    ui.page.wait_for_timeout(500)
    assert CHAT not in ui.status_queries()


# Flags and the one tracker ----------------------------------------------------------------------


@pytest.mark.parametrize("flag", ["allow_user_workflows", "enable_chat_orchestration_workflow_runs"])
def test_flags_off_keep_the_static_links_and_read_no_status(ui, flag):
    ui.status_rows = [status_row("running"),
                      status_row("running", conversation=OTHER, run="wrun-2", step="step-2", orun="orun-2")]
    ui.open(features={**FEATURES, flag: False}, wait_tracker=False)
    expect(ui.card.get_by_text(STATIC_FOOTNOTE, exact=True)).to_be_visible()
    expect(ui.card.get_by_role("button", name="Check now")).to_have_count(0)
    ui.page.wait_for_timeout(1000)
    assert ui.status_queries() == []
    expect(ui.page.get_by_role("img", name=re.compile(r"^Running "))).to_have_count(0)


def test_one_tracker_tick_reads_every_run_in_one_request(ui):
    ui.status_rows = [
        status_row("running"),
        status_row("running", conversation=OTHER, run="wrun-2", step="step-2", orun="orun-2"),
        status_row("waiting", conversation=OTHER, run="wrun-3", step="step-3", orun="orun-3",
                   waiting=APPROVAL, actions={"approve": True}),
    ]
    ui.open()
    ui.page.wait_for_timeout(500)
    before = len(ui.status_queries())
    ui.global_check()
    ui.page.wait_for_timeout(500)
    assert ui.status_queries()[before:] == [None], "one tick is one read of every chat's runs"


# The running tag --------------------------------------------------------------------------------


def test_the_running_tag_names_the_runs_and_gives_way_to_the_unread_dot(ui):
    ui.status_rows = [
        status_row("running", conversation=OTHER, run="wrun-2", step="step-2", orun="orun-2"),
        status_row("queued", conversation=OTHER, run="wrun-3", step="step-3", orun="orun-3"),
    ]
    ui.open()
    tag = ui.tag("Running 2 workflows")
    expect(tag).to_be_visible()
    expect(tag).to_have_attribute("title", "Running 2 workflows")
    row_text = tag.evaluate("(element) => element.closest('li')?.textContent || ''")
    assert OTHER_TITLE in row_text
    expect(ui.unread_dot(OTHER_TITLE)).to_have_count(0)

    ui.conversations[OTHER]["unread"] = True
    ui.js(f"() => {H}.stores.chat.useChatStore.getState().loadConversations({{ reset: true }})")
    expect(ui.unread_dot(OTHER_TITLE)).to_be_visible()
    expect(tag).to_have_count(0)


# Deliveries -------------------------------------------------------------------------------------


def test_a_delivery_in_another_chat_marks_it_unread_once(ui):
    ui.status_rows = [status_row("running", conversation=OTHER, run="wrun-2", step="step-2", orun="orun-2")]
    ui.open()
    tag = ui.tag()
    expect(tag).to_be_visible()
    row_text = tag.evaluate("(element) => element.closest('li')?.textContent || ''")
    assert OTHER_TITLE in row_text
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


@pytest.mark.parametrize("chose_source", [False, True], ids=["no-source-chosen", "source-cleared"])
def test_a_delivery_in_the_open_chat_reloads_it_and_marks_it_read(ui, chose_source):
    ui.status_rows = [status_row("running")]
    ui.open()
    expect(ui.live_row.get_by_role("status").first).to_contain_text("Running")
    # The plan's answer and the question keep their plain controls; only the delivery loses them.
    expect(ui.page.locator("#message-answer-1").get_by_role("button", name="Review orchestration recovery")) \
        .to_have_count(1)
    expect(ui.page.locator("#message-user-1").get_by_role("button", name="Retry", exact=True)).to_have_count(1)
    if chose_source:
        ui.js(f"() => {H}.stores.chat.useChatStore.getState().clearWorkflowResultContext()")

    message_id = ui.deliver()
    reads = ui.message_reads()
    ui.global_check()
    expect(ui.page.get_by_text(NOTE_TEXT["result"])).to_be_visible()
    assert ui.message_reads() == reads + 1
    ui.wait_for(lambda: len(ui.replies()) == 1, "the delivery was announced")
    reply = ui.replies()[0]
    assert (reply["conversationId"], reply["messageId"], reply["runId"], reply["source"]) == (
        CHAT, message_id, RUN, "workflow")
    ui.wait_for(lambda: ui.mark_reads(CHAT) == 1, "the watched reply was marked read")
    expect(ui.unread_dot(CHAT_TITLE)).to_have_count(0)

    expect(ui.card.get_by_role("button", name=f"Results posted below for {NAME}", exact=True)).to_be_visible()
    footer = ui.footer(message_id)
    expect(footer.get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_attribute("href", RUN_HREF)
    follow_up = footer.get_by_role("button", name=f"Follow up on {NAME}", exact=True)
    expect(follow_up).to_be_visible()
    ui.expect_no_plain_retry(message_id)

    chip = ui.page.locator('[data-workflow-result-chip="selected"]')
    if chose_source:
        expect(chip).to_have_count(0)
        follow_up.click()
        expect(chip).to_be_visible()
        expect(ui.page.locator("#composer-input")).to_be_focused()
    else:
        expect(chip).to_be_visible()


@pytest.mark.parametrize("hold", ["stream", "orchestration"])
def test_the_open_chat_waits_for_its_reply_to_finish_before_reloading(ui, hold):
    ui.status_rows = [status_row("running")]
    ui.open()
    held = ui.hold_stream if hold == "stream" else ui.hold_orchestration
    held(True)
    ui.deliver()
    reads = ui.message_reads()
    ui.global_check()
    ui.page.wait_for_timeout(2600)
    assert ui.message_reads() == reads, "the open chat must not reload while its reply is still coming"
    replies = ui.replies()
    assert replies == []

    held(False)
    expect(ui.page.get_by_text(NOTE_TEXT["result"])).to_be_visible(timeout=5000)
    assert ui.message_reads() == reads + 1
    ui.wait_for(lambda: len(ui.replies()) == 1, "the delivery was announced after the reply finished")


@pytest.mark.parametrize("reply", ["still-coming", "finished"])
def test_a_question_sent_during_the_re_read_stays_and_the_result_lands_once_after_its_reply(ui, reply):
    ui.status_rows = [status_row("running")]
    ui.open()
    ui.orchestrate_off()
    message_id = ui.deliver()
    ui.hold_messages = True
    reads = ui.message_reads()
    ui.global_check()
    ui.wait_for(lambda: ui.held_messages, "the open chat was re-read for the result")

    # The reader sends a question while that re-read is still out.
    ui.hold_streams = True
    ui.send(QUESTION)
    ui.wait_for(lambda: ui.held_streams, "the question was sent")
    question = ui.page.get_by_text(QUESTION, exact=True)
    answer = ui.page.get_by_text("Here is the plan.", exact=True)
    note = ui.page.get_by_text(NOTE_TEXT["result"], exact=True)
    expect(question).to_have_count(1)
    ui.hold_messages = False

    if reply == "finished":
        # A quick reply can finish first. The re-read that comes back after it is older than both.
        ui.release_stream()
        expect(answer).to_have_count(1)
        ui.wait_for(lambda: ui.chat_state("streaming") is False, "the reply finished")
        assert ui.message_reads() == reads + 1

    # The re-read comes back without the question, so it must not replace what is on screen.
    ui.release_messages()
    if reply == "still-coming":
        ui.page.wait_for_timeout(1000)
        expect(question).to_have_count(1)
        expect(note).to_have_count(0)
        assert ui.chat_state("streaming") is True
        assert ui.message_reads() == reads + 1, "nothing is re-read again while the reply is still coming"
        assert ui.workflow_replies() == []
        ui.release_stream()

    expect(note).to_have_count(1, timeout=5000)
    ui.wait_for(lambda: len(ui.workflow_replies()) == 1, "the result was announced once the reply finished")
    expect(question).to_have_count(1)
    expect(answer).to_have_count(1)
    assert ui.message_reads() == reads + 2
    assert ui.workflow_replies()[0]["messageId"] == message_id

    ui.global_check()
    ui.page.wait_for_timeout(300)
    assert len(ui.workflow_replies()) == 1
    expect(note).to_have_count(1)


def test_deliveries_already_in_the_first_read_stay_quiet(ui):
    ui.status_rows = [
        status_row("completed", conversation=OTHER, run="wrun-2", step="step-2", orun="orun-2",
                   delivery=delivered(run="wrun-2", conversation=OTHER, at="2026-01-05T09:06:30Z")),
        status_row("completed", conversation=OTHER, run="wrun-3", step="step-3", orun="orun-3",
                   delivery=delivered(run="wrun-3", conversation=OTHER, at="2026-01-05T09:07:00Z")),
        status_row("running", conversation=OTHER, run="wrun-4", step="step-4", orun="orun-4"),
    ]
    ui.open(browser={"focused": False})
    ui.global_check()
    ui.page.wait_for_timeout(300)
    replies, notifications = ui.replies(), ui.notifications()
    assert replies == []
    assert notifications == []

    # A delivery in the same second as the first read, but absent from it, is new.
    message_id = ui.deliver(OTHER, run="wrun-4", at=ui.global_checked[0])
    ui.global_check()
    ui.wait_for(lambda: len(ui.replies()) == 1, "the new delivery was announced")
    replies = ui.replies()
    assert replies[0]["messageId"] == message_id
    ui.global_check()
    ui.page.wait_for_timeout(300)
    replies, notifications = ui.replies(), ui.notifications()
    assert [reply["messageId"] for reply in replies] == [message_id]
    assert len(notifications) == 1


# Delivered-message footers ----------------------------------------------------------------------


@pytest.mark.parametrize("row_generation,offered", [(1, True), (2, False)], ids=["same-generation", "older-note"])
def test_a_failed_note_offers_retry_only_for_its_own_generation(ui, row_generation, offered):
    note = delivered_message("failed")
    ui.messages_by_chat[CHAT].append(note)
    ui.status_rows = [status_row("failed", actions={"retry": True},
                                 delivery=delivered(generation=row_generation))]
    ui.open()
    footer = ui.footer(note["id"])
    expect(footer.get_by_role("link", name=f"Open run of {NAME}", exact=True)).to_have_attribute("href", RUN_HREF)
    expect(footer.get_by_role("button", name=re.compile("^Follow up"))).to_have_count(0)
    ui.expect_no_plain_retry(note["id"])
    retry = footer.get_by_role("button", name=f"Retry workflow run of {NAME}", exact=True)
    if not offered:
        ui.page.wait_for_timeout(500)
        expect(retry).to_have_count(0)
        return
    expect(retry).to_be_visible()
    retry.click()
    ui.wait_for(lambda: len(ui.resume_bodies) == 1, "the footer's Retry sent one resume")
    assert ui.resume_bodies[0]["expected_version"] == 9
    expect(footer).to_contain_text("Retry requested.")


@pytest.mark.parametrize("results_in_chat,available,offered", [
    (True, True, True),
    (False, True, False),
    (True, False, False),
], ids=["on", "flag-off", "descriptor-unavailable"])
def test_follow_up_needs_the_flag_and_an_available_result(ui, results_in_chat, available, offered):
    message = delivered_message("result", available=available)
    ui.messages_by_chat[CHAT].append(message)
    ui.status_rows = [status_row("completed", delivery=delivered())]
    ui.open(features={**FEATURES, "enable_chat_workflow_results": results_in_chat})
    footer = ui.footer(message["id"])
    expect(footer.get_by_role("link", name=re.compile("^Open run"))).to_have_attribute("href", RUN_HREF)
    expect(footer.get_by_role("button", name=re.compile("^Follow up"))).to_have_count(1 if offered else 0)
    expect(footer.get_by_role("button", name=re.compile("^Retry workflow run"))).to_have_count(0)


def test_a_plain_retry_that_gets_through_shows_the_servers_refusal(ui):
    note = delivered_message("failed")
    ui.messages_by_chat[CHAT].append(note)
    ui.status_rows = [status_row("failed", delivery=delivered())]
    ui.open()
    expect(ui.footer(note["id"])).to_be_visible()
    ui.js(f"(id) => {{ void {H}.stores.chat.useChatStore.getState().retryMessage(id); }}", note["id"])
    ui.wait_for(lambda: ui.chat_state("streamError") == RETRY_REFUSAL, "the server's refusal was shown")
    assert ui.retry_calls == [note["id"]]
    expect(ui.page.get_by_text(RETRY_REFUSAL)).to_be_visible()


def test_review_and_approve_waits_while_a_retry_is_under_way(ui):
    """A read that lands mid-Retry and finds a gate can't open it until the Retry is answered."""
    ui.status_rows = [status_row("failed", actions={"retry": True})]
    ui.open()
    row = ui.live_row
    ui.hold_resume = True
    row.get_by_role("button", name=f"Retry run of {NAME}", exact=True).click()
    ui.wait_for(lambda: ui.held_resumes, "Retry sent its resume")

    ui.status_rows = [status_row("waiting", waiting=APPROVAL, actions={"approve": True})]
    ui.check_now()
    expect(row.get_by_role("status").first).to_contain_text("Needs you")
    approve = row.get_by_role("link", name=f"Review and approve {NAME}", exact=True)
    expect(approve).to_have_attribute("aria-disabled", "true")
    expect(approve).to_have_attribute("href", RUN_HREF)
    cancel = row.get_by_role("button", name=f"Cancel run of {NAME}", exact=True)
    expect(cancel).to_have_attribute("aria-disabled", "true")

    # Neither a click nor Enter opens the run while the Retry is under way.
    workflows_page = ui.page.locator("[data-workflows-page]")
    approve.click(force=True)
    ui.page.wait_for_timeout(300)
    expect(workflows_page).to_have_count(0)
    approve.focus()
    ui.page.keyboard.press("Enter")
    ui.page.wait_for_timeout(300)
    expect(workflows_page).to_have_count(0)
    expect(approve).to_be_visible()

    ui.hold_resume = False
    ui.release_resumes()
    expect(row).to_contain_text("Retry requested.")
    expect(approve).not_to_have_attribute("aria-disabled", "true")
    expect(cancel).not_to_have_attribute("aria-disabled", "true")
    assert len(ui.resume_bodies) == 1
    approve.click()
    expect(workflows_page).to_contain_text(f"?workflow_id={WORKFLOW}&run_id={RUN}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
