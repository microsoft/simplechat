# test_v2_workflow_activity.py
"""
Browser regressions for the V2 Workflow Activity page (/v2/workflow-activity).
Version: 0.261.445
Implemented in: 0.261.445

Exercises the real page, its timeline, detail panel and Microsoft 365 action card, the chat
header's activity link and a workflow's run history, bundled by fixtures/workflow_activity. Only
HTTP answers are replaced: the snapshot endpoint, its event stream, the cancel call and the saved
Microsoft 365 action routes. The snapshots are built by the server's own
`build_workflow_activity_snapshot` (fixtures/v2_workflow_activity_stubs.py), and the event stream is
answered the way a browser meets one: a response of `data:` frames that ends, after which the page
reconnects, held open between frames so a test decides when the next one arrives. Snapshot reads and
the cancel call can be held too, so a test decides which of two requests is answered first: that is
how a cancel that outlasts the run it was for is shown not to stop the next run's read. Keyboard
focus after Refresh and Cancel run, and text with no spaces in it at 390 and 360 px, are measured in
the browser as drawn. The existing Azure Playwright connection fixture also supports a local
browser; no live application data is read or modified.
"""

import json
import re
import sys
import time
from collections import namedtuple
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT, ROOT / "functional_tests"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

# Imported through the package: a bare `harness_build` would collide with the orchestration
# fixture module of the same name when both suites run in one session.
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from ui_tests.fixtures.agent_delegation.harness_build import ensure_bundle  # noqa: E402
from ui_tests.fixtures.color_contrast import CONTRAST_RATIO_SCRIPT  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401
from ui_tests.fixtures.v2_workflow_activity_stubs import (  # noqa: E402
    ACTIVITY_PATH,
    CONVERSATION_ID,
    GROUP_ACTIVITY_PATH,
    GROUP_ID,
    RESPONSE_PREVIEW,
    RUN_ID,
    RUNNER,
    WORKFLOW_ID,
    WORKFLOW_NAME,
    XSS_TEXT,
    conversation_only_snapshot,
    event_stream,
    many_tools_snapshot,
    pending_action,
    run_snapshot,
    stream_refusal,
)


pytestmark = pytest.mark.ui

IMPLEMENTED_IN = "0.261.445"
FIXTURE = ROOT / "ui_tests" / "fixtures" / "workflow_activity"
BUNDLE = FIXTURE / "harness.bundle.js"
V2_SOURCE = ROOT / "application" / "v2_ui" / "src"
STATIC = ROOT / "application" / "single_app" / "static"
# Only the files the page is made of are held to the build's age; the rest of V2 belongs to others.
OWN_SOURCES = (
    "pages/WorkflowActivityPage.tsx",
    "components/workflowActivity/*",
    "lib/workflowActivity*.ts",
)
ORIGIN = "https://simplechat.test"
STREAM = f"{ACTIVITY_PATH}/stream"
GROUP_STREAM = f"{GROUP_ACTIVITY_PATH}/stream"

RUN_LINK = f"/workflow-activity?conversationId={CONVERSATION_ID}&workflowId={WORKFLOW_ID}&runId={RUN_ID}"
GROUP_LINK = f"/workflow-activity?workflowId={WORKFLOW_ID}&runId={RUN_ID}&scope=group&groupId={GROUP_ID}"
RUN_QUERY = {"conversation_id": CONVERSATION_ID, "workflow_id": WORKFLOW_ID, "run_id": RUN_ID}
CANCEL_PATH = f"/api/user/workflows/{WORKFLOW_ID}/runs/{RUN_ID}/cancel"
GROUP_CANCEL_PATH = f"/api/group/workflows/{WORKFLOW_ID}/runs/{RUN_ID}/cancel"
PENDING_PATH = "/api/msgraph/pending-actions"
CSRF_TOKEN = "c" * 40

EMPTY_STATE = "Open this page from a workflow conversation or a workflow run history entry."
INVALID_LINK = "This workflow activity link is not valid."
OFFLINE = "Unable to load workflow activity. Check your connection and try again."
# The page is drawn in a fixed locale and zone, so a time reads the same on every machine.
STARTED = re.compile(r"Jan 1, 2025, 12:00\s+AM")

SEEN = namedtuple("Seen", "method path query")

# Records every EventSource the page opens, so a test can count the ones it still holds.
TRACK_STREAMS = r"""
() => {
    const Original = window.EventSource;
    window.__streams = [];
    window.EventSource = class extends Original {
        constructor(url, init) {
            super(url, init);
            window.__streams.push(this);
        }
    };
}
"""

SEED = r"""
(seed) => {
    const H = window.ActivityHarness;
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            version: '0.261.445',
            user: {id: 'user-1', display_name: 'Riley Chen', roles: []},
            features: seed.features,
            branding: {app_title: 'Contoso Chat'},
            settings: {},
            scope: {groups: [], public_workspaces: []},
            catalogs: {models: [], agents: [], prompts: []},
        },
        loading: false,
        error: null,
    });
    H.stores.ui.useUiStore.setState({mobileNavOpen: false, theme: seed.theme});
    document.documentElement.classList.toggle('dark', seed.theme === 'dark');
    document.documentElement.style.colorScheme = seed.theme;
    H.stores.chat.useChatStore.setState({
        activeConversationId: seed.active,
        activeConversationKind: 'personal',
        conversations: seed.conversations,
        messages: [],
        streaming: false,
        messagesLoading: false,
    });
    H.workflow = seed.workflow;
    H.mount(seed.path, {strict: seed.strict});
}
"""


@pytest.fixture(scope="module")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "locale": "en-US", "timezone_id": "UTC"}


@pytest.fixture(scope="module")
def harness_assets():
    index = STATIC / "v2" / "index.html"
    assert index.is_file(), "Build the V2 SPA first: cd application/v2_ui; npx vite build"
    built = index.stat().st_mtime
    own = [path for pattern in OWN_SOURCES for path in V2_SOURCE.glob(pattern) if path.is_file()]
    assert own, "The page's sources were not found."
    stale = [path for path in own if path.stat().st_mtime > built]
    if stale:
        pytest.fail(
            f"The V2 bundle is stale ({stale[0].relative_to(ROOT)} changed after it was built). "
            "Run: cd application/v2_ui; npx vite build",
        )
    hrefs = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', index.read_text(encoding="utf-8"))
    stylesheets = [STATIC / href.removeprefix("/static/") for href in hrefs]
    assert stylesheets and all(sheet.is_file() for sheet in stylesheets), stylesheets
    ensure_bundle(entry=FIXTURE / "harness_entry.tsx", bundle=BUNDLE)
    yield stylesheets
    BUNDLE.unlink(missing_ok=True)


def fulfill(route, status, body):
    """Answer as the server does: JSON for a body that is data, and a page for a body that is text."""
    if isinstance(body, str):
        route.fulfill(status=status, content_type="text/html", body=body)
    else:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


class ActivityApi:
    """The HTTP the page talks to, answered from what a test sets, and the page it drives."""

    def __init__(self, page, stylesheets):
        self.page = page
        self.stylesheets = stylesheets
        self.requests = []
        self.new_tabs = []
        self.unexpected = []
        self.errors = []
        self.expected_failures = set()
        # What the snapshot endpoint answers, unless an answer is queued: (status, body) or "abort".
        self.snapshot = run_snapshot()
        self.activity_answers = []
        # Stream connections the page has open and nobody has answered yet, oldest first.
        self.held_streams = []
        self.cancel_answer = (200, {"success": True})
        self.hold_cancel = False
        self.held_cancel = None
        self.on_cancel = None
        # How many of the next snapshot reads to leave unanswered, and the ones left, oldest first.
        self.hold_reads = 0
        self.held_reads = []
        self.runs = []
        self.metadata = {}
        # Saved Microsoft 365 actions, by id, and what a change to one does to the snapshot.
        self.actions = {}
        self.on_action_change = None

    # Routing ----------------------------------------------------------------------------------

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(f"{request.method} {request.url}")
            route.abort()
            return
        path = parsed.path
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        self.requests.append(SEEN(request.method, path, query))
        for answer in (self.page_route, self.activity_route, self.workflow_route, self.action_route, self.chat_route):
            if answer(route, request.method, path, query):
                return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def page_route(self, route, method, path, query):
        if method != "GET":
            return False
        if path == "/harness.html":
            route.fulfill(path=str(FIXTURE / "harness.html"), content_type="text/html")
        elif path == "/harness.bundle.js":
            route.fulfill(path=str(BUNDLE), content_type="application/javascript")
        elif path == "/favicon.ico":
            route.fulfill(status=204, body="")
        else:
            return False
        return True

    def activity_route(self, route, method, path, query):
        if method != "GET":
            return False
        if path in (ACTIVITY_PATH, GROUP_ACTIVITY_PATH):
            if self.hold_reads:
                self.hold_reads -= 1
                self.held_reads.append(route)
                return True
            answer = self.activity_answers.pop(0) if self.activity_answers else (200, self.snapshot)
            if answer == "abort":
                self.expected_failures.add((path, 0))
                route.abort("failed")
                return True
            status, body = answer
            if status != 200:
                self.expected_failures.add((path, status))
            fulfill(route, status, body)
        elif path in (STREAM, GROUP_STREAM):
            self.held_streams.append(route)
        else:
            return False
        return True

    def workflow_route(self, route, method, path, query):
        if method == "POST" and re.fullmatch(r"/api/(user|group)/workflows/[^/]+/runs/[^/]+/cancel", path):
            if self.hold_cancel:
                self.held_cancel = route
            else:
                self.answer_cancel(route)
        elif method == "GET" and (match := re.fullmatch(r"/api/(user|group)/workflows/([^/]+)/runs", path)):
            route.fulfill(json=self.runs)
        else:
            return False
        return True

    def answer_cancel(self, route):
        status, body = self.cancel_answer
        if status != 200:
            self.expected_failures.add((urlsplit(route.request.url).path, status))
        elif self.on_cancel:
            self.on_cancel()
        fulfill(route, status, body)

    def action_route(self, route, method, path, query):
        if method == "GET" and path == "/api/m365/preferences":
            route.fulfill(json={"success": True, "csrf_token": CSRF_TOKEN})
        elif method == "GET" and (match := re.fullmatch(rf"{PENDING_PATH}/([^/]+)", path)):
            action = self.actions.get(unquote(match.group(1)))
            if action is None:
                self.expected_failures.add((path, 404))
                route.fulfill(status=404, json={"success": False, "error": "not_found", "message": "Not found."})
            else:
                route.fulfill(json={"success": True, "pending_action": action})
        elif method == "POST" and (match := re.fullmatch(rf"{PENDING_PATH}/([^/]+)/(send-now|approve|cancel)", path)):
            action_id = unquote(match.group(1))
            current = self.actions[action_id]
            changed = {
                **current,
                "version": "v2",
                "status": "cancelled" if match.group(2) == "cancel" else "sent",
                "can_cancel": False,
                "can_send_now": False,
                "updated_at": "2025-01-01T00:00:30+00:00",
            }
            self.actions[action_id] = changed
            if self.on_action_change:
                self.on_action_change(changed)
            route.fulfill(json={"success": True, "pending_action": changed})
        else:
            return False
        return True

    def chat_route(self, route, method, path, query):
        if method != "GET":
            return False
        if match := re.fullmatch(r"/api/conversations/([^/]+)/metadata", path):
            route.fulfill(json=self.metadata.get(unquote(match.group(1)), {}))
        elif match := re.fullmatch(r"/api/conversations/([^/]+)/kind", path):
            route.fulfill(json={"conversation_id": unquote(match.group(1)), "kind": "personal"})
        elif path == "/api/get_messages":
            route.fulfill(json={"messages": []})
        elif re.fullmatch(r"/api/chat/stream/status/[^/]+", path):
            route.fulfill(json={"active": False, "pending": False, "reattachable": False})
        elif path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
        elif path == "/api/v2/orchestration/questions":
            route.fulfill(json={"questions": []})
        elif path == "/api/action-credentials/pending":
            route.fulfill(json={"requests": []})
        elif path == "/api/v2/user-input/pending":
            route.fulfill(json={"requests": [], "csrf_token": CSRF_TOKEN})
        elif path == PENDING_PATH:
            route.fulfill(json={"success": True, "pending_actions": [], "continuation_token": ""})
        else:
            return False
        return True

    # Driving the page ---------------------------------------------------------------------------

    def open(self, path, *, features=None, conversations=None, active="", workflow=None, strict=False,
             theme="light", viewport=None):
        if viewport:
            self.page.set_viewport_size(viewport)
        self.page.add_init_script(script=f"({TRACK_STREAMS})()")
        # A link that opens a tab lands in a page of its own, which only the context can answer.
        self.page.context.route(f"{ORIGIN}/**", self.answer_new_tab)
        self.page.route("**/*", self.handle)
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", self.record_console)
        self.page.goto(f"{ORIGIN}/harness.html")
        for stylesheet in self.stylesheets:
            self.page.add_style_tag(path=str(stylesheet))
        self.page.evaluate(SEED, {
            "path": path,
            "features": {"allow_user_workflows": True, "enable_group_workspaces": True, **(features or {})},
            "conversations": conversations or [],
            "active": active,
            "workflow": workflow,
            "strict": strict,
            "theme": theme,
        })

    def answer_new_tab(self, route):
        self.new_tabs.append(route.request.url)
        route.fulfill(content_type="text/html", body="<!doctype html><title>Opened in a new tab</title>")

    def follow(self, link):
        """Click a link that opens a tab, and return the tab it opened."""
        with self.page.context.expect_page() as opened:
            link.click()
        tab = opened.value
        tab.wait_for_load_state()
        return tab

    def record_console(self, message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        failed = re.search(r"^Failed to load resource: (?:the server responded with a status of (\d+)|net::ERR_FAILED)", message.text)
        if failed and (path, int(failed.group(1) or 0)) in self.expected_failures:
            return
        self.errors.append(message.text)

    def wait_for(self, predicate, message, timeout=5.0):
        """Poll from the test thread, so held routes keep being answered meanwhile."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(message)
            self.page.wait_for_timeout(50)

    def push(self, *snapshots, retry_ms=100):
        """Answer the oldest open stream connection the way the server does: frames, then the end."""
        body = event_stream(*snapshots, retry_ms=retry_ms)
        while True:
            self.wait_for(lambda: self.held_streams, "The page did not open the activity stream.")
            route = self.held_streams.pop(0)
            try:
                route.fulfill(status=200, headers={"Cache-Control": "no-cache"}, content_type="text/event-stream", body=body)
                return
            except PlaywrightError:
                # The page had already closed that connection.
                continue

    def refuse_stream(self):
        self.wait_for(lambda: self.held_streams, "The page did not open the activity stream.")
        self.held_streams.pop(0).fulfill(
            status=200, headers={"Cache-Control": "no-cache"}, content_type="text/event-stream", body=stream_refusal(),
        )

    def finish_cancel(self, status=200, body=None):
        self.wait_for(lambda: self.held_cancel, "The cancel request was not made.")
        self.cancel_answer = (status, body if body is not None else {"success": True})
        route, self.held_cancel, self.hold_cancel = self.held_cancel, None, False
        self.answer_cancel(route)

    def release_read(self, snapshot=None):
        """Answer the oldest snapshot read that was held, with a snapshot or the page's current one."""
        self.wait_for(lambda: self.held_reads, "No snapshot read was waiting to be answered.")
        route = self.held_reads.pop(0)
        try:
            fulfill(route, 200, snapshot if snapshot is not None else self.snapshot)
        except PlaywrightError:
            # The page had already dropped that read. What it shows is for the test to assert.
            pass

    def navigate(self, path):
        """Follow a link inside the mounted page, as a notification does: the page stays, its address changes."""
        self.page.evaluate("(path) => window.ActivityHarness.navigate(path)", path)

    def go(self, delta):
        """The Back (-1) and Forward (1) buttons."""
        self.page.evaluate("(delta) => window.ActivityHarness.go(delta)", delta)

    def focused(self):
        """What holds keyboard focus: its test id, else its tag. The page itself reads as BODY."""
        return self.page.evaluate(
            "() => { const held = document.activeElement; return held ? (held.dataset.testid || held.tagName) : ''; }"
        )

    # Reading what happened ------------------------------------------------------------------------

    def seen(self, method, path):
        return [item for item in self.requests if item.method == method and item.path == path]

    def reads(self):
        return self.seen("GET", ACTIVITY_PATH) + self.seen("GET", GROUP_ACTIVITY_PATH)

    def streams_requested(self):
        return self.seen("GET", STREAM) + self.seen("GET", GROUP_STREAM)

    def open_streams(self):
        return self.page.evaluate("() => window.__streams.filter((stream) => stream.readyState !== 2).length")

    def route(self):
        return self.page.get_by_role("status", name="Current route").text_content()

    # Places on the page -------------------------------------------------------------------------

    def by_id(self, name):
        return self.page.get_by_test_id(f"v2-workflow-activity-{name}")

    @property
    def title(self):
        return self.by_id("title")

    @property
    def status(self):
        return self.by_id("status")

    @property
    def caption(self):
        return self.by_id("caption")

    @property
    def cards(self):
        return self.by_id("card")

    @property
    def detail(self):
        return self.by_id("detail")

    @property
    def viewport(self):
        return self.by_id("timeline-viewport")

    @property
    def cancel_button(self):
        return self.by_id("cancel")

    @property
    def problem(self):
        return self.by_id("problem")

    @property
    def notice(self):
        return self.by_id("notice")

    def stat(self, name):
        return self.by_id(f"stat-{name}")

    def scroll_state(self):
        return self.viewport.evaluate(
            "(element) => ({top: element.scrollTop, height: element.scrollHeight, client: element.clientHeight})"
        )

    def at_bottom(self):
        state = self.scroll_state()
        return state["height"] - state["top"] - state["client"] <= 24


@pytest.fixture
def tab(page, harness_assets):
    api = ActivityApi(page, harness_assets)
    yield api
    # The requests nobody stubbed come first: they are why the console reports a 404.
    assert not api.unexpected, api.unexpected
    assert not api.errors, api.errors


def running(**overrides):
    return run_snapshot(status="running", finished_tools=1, running_tools=1, response_preview="", **overrides)


# Version ------------------------------------------------------------------------------------------


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


# The page's states ----------------------------------------------------------------------------------


def test_a_page_opened_without_a_run_says_where_to_open_it_from(tab):
    tab.open("/workflow-activity")
    page = tab.page

    expect(page.get_by_role("heading", level=1, name="Workflow activity")).to_be_visible()
    expect(tab.by_id("empty")).to_contain_text(EMPTY_STATE)
    # Nothing to ask the server, and nothing to listen for.
    page.wait_for_timeout(300)
    assert tab.reads() == []
    assert tab.open_streams() == 0


@pytest.mark.parametrize(
    "query",
    [
        "runId=a%2Fb",
        "workflowId=wf-1&scope=public",
        "workflowId=wf-1&scope=group&groupId=%20grp",
        "conversationId=..",
        "runId=run%0A1",
    ],
)
def test_a_link_with_an_id_or_scope_it_cannot_carry_is_refused_without_asking_the_server(tab, query):
    tab.open(f"/workflow-activity?{query}")

    expect(tab.problem).to_contain_text(INVALID_LINK)
    expect(tab.problem).to_have_attribute("role", "alert")
    tab.page.wait_for_timeout(300)
    assert tab.reads() == []
    assert tab.open_streams() == 0


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (400, {"error": "Workflow run not found."}, "Workflow run not found."),
        (
            400,
            {"error": "A workflow activity request needs a conversation, workflow, or run identifier."},
            "A workflow activity request needs a conversation, workflow, or run identifier.",
        ),
        (
            403,
            {"error": "Forbidden", "message": "Workflows are not enabled for your account."},
            "Workflows are not enabled for your account.",
        ),
        (403, {"error": "Group workflows are disabled for this tenant."}, "Group workflows are disabled for this tenant."),
        # A body with nothing in it, or one that is not JSON at all, is not the server's sentence.
        (404, {}, "This workflow activity was not found."),
        (502, "<html><h1>Bad gateway</h1></html>", "Unable to load workflow activity right now."),
        (403, "Denied by policy", "You do not have access to this workflow activity."),
        (500, {"error": "Unable to load workflow activity right now."}, "Unable to load workflow activity right now."),
    ],
)
def test_a_refused_read_says_what_the_server_said_and_can_be_tried_again(tab, status, body, message):
    tab.activity_answers.append((status, body))
    tab.open(RUN_LINK)

    expect(tab.problem).to_contain_text("Workflow activity unavailable")
    expect(tab.problem).to_contain_text(message)
    expect(tab.problem).to_have_attribute("role", "alert")
    if isinstance(body, str):
        expect(tab.problem).not_to_contain_text(body)
    assert tab.open_streams() == 0

    tab.problem.get_by_role("button", name="Try again").click()
    expect(tab.title).to_have_text(WORKFLOW_NAME)
    expect(tab.problem).to_have_count(0)


def test_a_read_that_never_gets_an_answer_asks_for_the_connection_to_be_checked(tab):
    tab.activity_answers.append("abort")
    tab.open(RUN_LINK)

    expect(tab.problem).to_contain_text(OFFLINE)
    tab.problem.get_by_role("button", name="Try again").click()
    expect(tab.title).to_have_text(WORKFLOW_NAME)


# A finished run -----------------------------------------------------------------------------------


def test_a_finished_personal_run_is_drawn_as_the_classic_page_draws_it(tab):
    tab.snapshot = run_snapshot()
    tab.open(RUN_LINK)
    page = tab.page

    expect(page.get_by_role("heading", level=1, name="Workflow activity")).to_be_visible()
    expect(tab.title).to_have_text(WORKFLOW_NAME)
    expect(tab.status).to_have_text("Completed")
    expect(tab.status).to_have_attribute("data-tone", "ok")
    expect(tab.caption).to_have_text(f"manual run completed using {RUNNER}.")
    expect(tab.stat("run")).to_have_text(RUN_ID[:8])
    expect(tab.stat("total")).to_have_text("3")
    expect(tab.stat("tools")).to_have_text("2")
    expect(tab.stat("started")).to_have_text(STARTED)

    # The read carries the ids the link did, under the names the server reads.
    assert [item.query for item in tab.reads()][-1] == RUN_QUERY
    # A finished run has nothing to listen for.
    page.wait_for_timeout(400)
    assert tab.streams_requested() == []
    assert tab.open_streams() == 0
    expect(tab.cancel_button).to_have_count(0)

    cards = tab.cards
    expect(cards).to_have_count(3)
    assert cards.evaluate_all("(items) => items.map((item) => item.dataset.activityId)") == [
        f"run:{RUN_ID}", f"tool-{RUN_ID}-0", f"tool-{RUN_ID}-1",
    ]
    # Each tool sits in a lane of its own, further from the workflow's.
    lanes = page.get_by_test_id("v2-workflow-activity-timeline").locator("li").evaluate_all(
        "(items) => items.map((item) => item.style.getPropertyValue('--lane-index'))"
    )
    assert lanes == ["0", "1", "2"]
    expect(cards.nth(1)).to_contain_text("SecurityPlugin.fetch_events")
    expect(cards.nth(1)).to_contain_text("450 ms")
    expect(cards.nth(1)).to_contain_text("SecurityPlugin")

    # The newest activity is the one selected, and the one the detail panel describes.
    expect(cards.nth(2)).to_have_attribute("aria-current", "true")
    expect(tab.by_id("detail-title")).to_have_text("ReportPlugin.compile_report")

    cards.nth(0).click()
    expect(cards.nth(0)).to_have_attribute("aria-current", "true")
    expect(cards.nth(2)).not_to_have_attribute("aria-current", "true")
    expect(tab.by_id("detail-title")).to_have_text("Workflow run")
    events = tab.by_id("events").locator("li")
    expect(events).to_have_count(2)
    expect(events.nth(0)).to_contain_text("Workflow run started")
    expect(events.nth(0)).to_contain_text("trigger_source=manual")
    expect(events.nth(1)).to_contain_text("Workflow run completed")

    cards.nth(1).click()
    expect(tab.by_id("detail-text")).to_contain_text("severity=high")
    expect(tab.detail.get_by_role("heading", name="Event History")).to_be_visible()

    # Refresh reads the snapshot again, and says it is doing so while it does.
    reads = len(tab.reads())
    tab.by_id("refresh").click()
    tab.wait_for(lambda: len(tab.reads()) == reads + 1, "Refresh did not read the snapshot again.")


def test_the_cards_are_buttons_that_the_keyboard_can_pick(tab):
    tab.snapshot = run_snapshot()
    tab.open(RUN_LINK)
    expect(tab.cards).to_have_count(3)

    first = tab.cards.nth(0)
    first.focus()
    tab.page.keyboard.press("Enter")
    expect(first).to_have_attribute("aria-current", "true")
    expect(tab.by_id("detail-title")).to_have_text("Workflow run")
    expect(tab.page.get_by_role("list", name="Workflow activity timeline")).to_be_visible()


def test_the_response_preview_starts_closed_and_opens_and_closes_from_its_button(tab):
    tab.snapshot = run_snapshot()
    tab.open(RUN_LINK)

    toggle = tab.by_id("response-toggle")
    region = tab.by_id("response")
    expect(toggle).to_have_text("Show response preview")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(region).to_be_hidden()
    assert toggle.get_attribute("aria-controls") == region.get_attribute("id")

    toggle.click()
    expect(toggle).to_have_text("Hide response preview")
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(region).to_be_visible()
    expect(region).to_contain_text("Response Preview")
    expect(region).to_contain_text(RESPONSE_PREVIEW)

    toggle.click()
    expect(toggle).to_have_text("Show response preview")
    expect(region).to_be_hidden()


def test_a_failed_run_offers_its_error_where_the_preview_would_be(tab):
    tab.snapshot = run_snapshot(
        status="failed", finished_tools=1, response_preview="Never shown", error="Workflow agent timed out.",
    )
    tab.open(RUN_LINK)

    expect(tab.status).to_have_text("Failed")
    expect(tab.status).to_have_attribute("data-tone", "danger")
    expect(tab.caption).to_have_text(f"manual run failed using {RUNNER}.")
    expect(tab.cancel_button).to_have_count(0)
    toggle = tab.by_id("response-toggle")
    expect(toggle).to_have_text("Show run error")
    toggle.click()
    expect(toggle).to_have_text("Hide run error")
    expect(tab.by_id("response")).to_contain_text("Run Error")
    expect(tab.by_id("response")).to_contain_text("Workflow agent timed out.")
    expect(tab.by_id("response")).not_to_contain_text("Never shown")


def test_the_answer_checks_a_task_saved_are_drawn_in_the_response_panel(tab):
    tab.snapshot = run_snapshot(
        task_results=[
            {"task_name": "Collect events", "workflow_result": {"task_completeness": {"version": 1, "status": "checked"}}},
            {"task_name": "Unchecked", "workflow_result": {}},
        ],
    )
    tab.open(RUN_LINK)

    tab.by_id("response-toggle").click()
    checks = tab.by_id("checks")
    expect(checks).to_contain_text("Collect events")
    expect(checks.get_by_test_id("task-completeness")).to_have_count(1)
    expect(checks.get_by_test_id("task-completeness")).to_contain_text("Answer checked")


def test_a_conversation_with_no_run_yet_waits_for_one_and_picks_it_up(tab):
    tab.snapshot = conversation_only_snapshot()
    tab.open(f"/workflow-activity?conversationId={CONVERSATION_ID}")

    expect(tab.title).to_have_text(f"Workflow: {WORKFLOW_NAME}")
    expect(tab.caption).to_have_text("Waiting for a captured workflow run.")
    expect(tab.stat("run")).to_have_text("Pending")
    expect(tab.stat("started")).to_have_text("--")
    expect(tab.page.get_by_text("No activity yet")).to_be_visible()
    # The run may be about to start, so the page listens for it.
    tab.wait_for(lambda: tab.open_streams() == 1, "The page did not listen for the run to begin.")
    assert tab.streams_requested()[0].query == {"conversation_id": CONVERSATION_ID}

    tab.push(running())
    expect(tab.title).to_have_text(WORKFLOW_NAME)
    expect(tab.status).to_have_text("Running")
    expect(tab.stat("total")).to_have_text("3")


# A live run ---------------------------------------------------------------------------------------


def test_a_live_run_follows_its_stream_and_lets_go_of_it_when_it_settles(tab):
    tab.snapshot = running()
    tab.open(RUN_LINK)
    page = tab.page

    expect(tab.status).to_have_text("Running")
    expect(tab.status).to_have_attribute("data-tone", "accent")
    expect(tab.stat("total")).to_have_text("3")
    expect(tab.cancel_button).to_have_text("Cancel run")
    live = page.get_by_role("status").filter(has_text="Run status")
    expect(live).to_have_text("3 activities, 2 tool calls. Run status: Running.")

    # One connection, with the query the read carried.
    tab.wait_for(lambda: len(tab.held_streams) == 1, "The page did not open the activity stream.")
    assert tab.open_streams() == 1
    assert tab.streams_requested()[0].query == RUN_QUERY

    tab.push(run_snapshot(status="running", finished_tools=2, running_tools=1, response_preview=""))
    expect(tab.stat("total")).to_have_text("4")
    expect(tab.stat("tools")).to_have_text("3")
    expect(live).to_have_text("4 activities, 3 tool calls. Run status: Running.")
    expect(tab.cards).to_have_count(4)
    # The newest activity, which the detail panel follows until the reader picks another.
    expect(tab.by_id("detail-title")).to_have_text("SecurityPlugin.fetch_events")

    tab.push(run_snapshot(status="completed", finished_tools=3))
    expect(tab.status).to_have_text("Completed")
    expect(tab.caption).to_have_text(f"manual run completed using {RUNNER}.")
    expect(tab.cancel_button).to_have_count(0)
    expect(live).to_have_text("4 activities, 3 tool calls. Run status: Completed.")

    # Settled: the stream is closed, and does not come back.
    tab.wait_for(lambda: tab.open_streams() == 0, "The page kept the stream open after the run completed.")
    requested = len(tab.streams_requested())
    page.wait_for_timeout(500)
    assert len(tab.streams_requested()) == requested == 2
    assert tab.open_streams() == 0


def test_a_run_waiting_on_a_person_keeps_listening_and_can_still_be_cancelled(tab):
    tab.snapshot = running()
    tab.snapshot["run"]["status"] = "awaiting_approval"
    tab.snapshot["live"] = True
    tab.open(RUN_LINK)

    expect(tab.status).to_have_text("Awaiting approval")
    expect(tab.status).to_have_attribute("data-tone", "warn")
    expect(tab.caption).to_have_text(f"manual run awaiting approval using {RUNNER}.")
    expect(tab.cancel_button).to_be_enabled()
    tab.wait_for(lambda: tab.open_streams() == 1, "The page did not listen while the run waited.")


def test_the_server_ending_the_stream_with_a_refusal_is_said_and_the_snapshot_stays(tab):
    tab.snapshot = running()
    tab.open(RUN_LINK)
    expect(tab.stat("total")).to_have_text("3")

    tab.refuse_stream()
    expect(tab.notice).to_contain_text("Workflow activity is no longer available.")
    expect(tab.stat("total")).to_have_text("3")
    # The page does not keep knocking on a stream the server has closed.
    tab.wait_for(lambda: tab.open_streams() == 0, "The page kept a refused stream open.")
    requested = len(tab.streams_requested())
    tab.page.wait_for_timeout(500)
    assert len(tab.streams_requested()) == requested

    # Asking for a refresh reads the run again and listens again.
    tab.by_id("refresh").click()
    expect(tab.notice).to_have_count(0)
    tab.wait_for(lambda: tab.open_streams() == 1, "Refresh did not listen again after a refused stream.")
    tab.push(run_snapshot(status="running", finished_tools=2, running_tools=1, response_preview=""))
    expect(tab.stat("total")).to_have_text("4")


def test_the_timeline_follows_the_newest_activity_only_while_the_reader_is_at_the_bottom(tab):
    tab.snapshot = many_tools_snapshot(14, status="running", running_tools=1, response_preview="")
    tab.open(RUN_LINK, viewport={"width": 1280, "height": 640})
    expect(tab.cards).to_have_count(16)
    state = tab.scroll_state()
    assert state["height"] > state["client"] + 200, f"The timeline does not scroll: {state}"

    # Opened live and unscrolled, it sits on the newest card.
    tab.wait_for(tab.at_bottom, "A live timeline did not open at its newest activity.")

    tab.push(many_tools_snapshot(15, status="running", running_tools=1, response_preview=""))
    expect(tab.cards).to_have_count(17)
    tab.wait_for(tab.at_bottom, "The timeline did not follow a new activity.")
    expect(tab.cards.last).to_have_attribute("aria-current", "true")

    # A reader who has scrolled up to read is left where they are.
    tab.viewport.evaluate("(element) => { element.scrollTop = 0; }")
    tab.page.wait_for_timeout(100)
    tab.push(many_tools_snapshot(16, status="running", running_tools=1, response_preview=""))
    expect(tab.cards).to_have_count(18)
    tab.page.wait_for_timeout(300)
    assert tab.scroll_state()["top"] < 4, tab.scroll_state()

    # Back within 24 px of the bottom, it follows again.
    tab.viewport.evaluate("(element) => { element.scrollTop = element.scrollHeight - element.clientHeight - 10; }")
    tab.page.wait_for_timeout(100)
    tab.push(many_tools_snapshot(17, status="running", running_tools=1, response_preview=""))
    expect(tab.cards).to_have_count(19)
    tab.wait_for(tab.at_bottom, "The timeline did not follow once the reader came back to the bottom.")


def test_a_reader_who_picked_an_activity_is_not_moved_by_the_next_snapshot(tab):
    tab.snapshot = running()
    tab.open(RUN_LINK)
    expect(tab.cards).to_have_count(3)

    tab.cards.nth(0).click()
    expect(tab.by_id("detail-title")).to_have_text("Workflow run")
    tab.push(run_snapshot(status="running", finished_tools=2, running_tools=1, response_preview=""))
    expect(tab.cards).to_have_count(4)
    expect(tab.cards.nth(0)).to_have_attribute("aria-current", "true")
    expect(tab.by_id("detail-title")).to_have_text("Workflow run")

    # Choosing the newest card, or asking for a refresh, hands the choice back.
    tab.by_id("refresh").click()
    expect(tab.cards.last).to_have_attribute("aria-current", "true")


# Cancelling ----------------------------------------------------------------------------------------


def test_cancel_run_asks_the_server_shows_it_is_working_and_reads_the_run_again(tab):
    tab.snapshot = running()
    tab.open(RUN_LINK)
    cancel = tab.cancel_button
    expect(cancel).to_have_text("Cancel run")

    tab.hold_cancel = True
    cancel.click()
    expect(cancel).to_have_attribute("aria-disabled", "true")
    expect(cancel).to_have_attribute("aria-busy", "true")
    tab.snapshot = running()
    tab.snapshot["run"]["status"] = "cancelling"
    reads = len(tab.reads())
    tab.finish_cancel()

    tab.wait_for(lambda: len(tab.reads()) == reads + 1, "The run was not read again after it was cancelled.")
    expect(tab.status).to_have_text("Cancelling")
    expect(cancel).to_have_text("Cancelling")
    expect(cancel).to_have_attribute("aria-disabled", "true")
    assert len(tab.seen("POST", CANCEL_PATH)) == 1

    tab.push(run_snapshot(status="cancelled", finished_tools=1, response_preview=""))
    expect(tab.status).to_have_text("Cancelled")
    expect(tab.status).to_have_attribute("data-tone", "neutral")
    expect(cancel).to_have_count(0)
    tab.wait_for(lambda: tab.open_streams() == 0, "The page kept the stream open after the run was cancelled.")


@pytest.mark.parametrize(
    ("status", "body", "message"),
    [
        (500, {"error": "The run could not be cancelled right now."}, "The run could not be cancelled right now."),
        (200, {"success": False, "error": "This run already finished."}, "This run already finished."),
        (
            403,
            {"error": "Forbidden", "message": "You do not have permission to cancel this run."},
            "You do not have permission to cancel this run.",
        ),
    ],
)
def test_a_cancel_the_server_refuses_is_said_and_leaves_the_run_as_it_was(tab, status, body, message):
    tab.snapshot = running()
    tab.cancel_answer = (status, body)
    tab.open(RUN_LINK)
    expect(tab.status).to_have_text("Running")

    reads = len(tab.reads())
    tab.cancel_button.click()
    expect(tab.notice).to_contain_text(message)
    expect(tab.notice).to_have_attribute("role", "alert")
    expect(tab.cancel_button).to_be_enabled()
    expect(tab.status).to_have_text("Running")
    tab.page.wait_for_timeout(300)
    assert len(tab.reads()) == reads


# Keyboard focus ------------------------------------------------------------------------------------

SCREENS = {"desktop": {"width": 1280, "height": 800}, "phone": {"width": 390, "height": 844}}


@pytest.mark.parametrize("screen", SCREENS)
def test_refresh_keeps_keyboard_focus_while_it_reads_and_ignores_a_second_press(tab, screen):
    tab.snapshot = run_snapshot()
    tab.open(RUN_LINK, viewport=SCREENS[screen])
    expect(tab.cards).to_have_count(3)
    refresh = tab.by_id("refresh")

    refresh.focus()
    tab.hold_reads = 1
    tab.page.keyboard.press("Enter")
    tab.wait_for(lambda: tab.held_reads, "Refresh did not read the run again.")
    # Busy, yet still the control that was pressed: a disabled button would hand focus to the page.
    expect(refresh).to_have_attribute("aria-disabled", "true")
    expect(refresh).to_have_attribute("aria-busy", "true")
    assert refresh.evaluate("(button) => button.disabled") is False
    assert tab.focused() == "v2-workflow-activity-refresh"

    # Pressing it again while it reads asks for nothing more.
    tab.page.keyboard.press("Enter")
    tab.page.keyboard.press("Space")
    tab.page.wait_for_timeout(150)
    assert len(tab.held_reads) == 1
    assert len(tab.reads()) == 2

    tab.release_read()
    expect(refresh).not_to_have_attribute("aria-disabled", "true")
    expect(refresh).not_to_have_attribute("aria-busy", "true")
    assert tab.focused() == "v2-workflow-activity-refresh"


@pytest.mark.parametrize("screen", SCREENS)
def test_cancel_run_keeps_keyboard_focus_while_it_works_and_hands_it_to_refresh_when_it_goes(tab, screen):
    tab.snapshot = running()
    tab.open(RUN_LINK, viewport=SCREENS[screen])
    cancel, refresh = tab.cancel_button, tab.by_id("refresh")
    expect(cancel).to_have_text("Cancel run")

    cancel.focus()
    tab.hold_cancel = True
    tab.page.keyboard.press("Enter")
    tab.wait_for(lambda: tab.held_cancel, "The cancel request was not made.")
    expect(cancel).to_have_attribute("aria-disabled", "true")
    expect(cancel).to_have_attribute("aria-busy", "true")
    assert cancel.evaluate("(button) => button.disabled") is False
    assert tab.focused() == "v2-workflow-activity-cancel"

    # A second press while the request is under way does not make another.
    tab.page.keyboard.press("Enter")
    tab.page.wait_for_timeout(150)
    assert len(tab.seen("POST", CANCEL_PATH)) == 1

    tab.snapshot = running()
    tab.snapshot["run"]["status"] = "cancelling"
    tab.finish_cancel()
    expect(cancel).to_have_text("Cancelling")
    expect(cancel).to_have_attribute("aria-disabled", "true")
    assert tab.focused() == "v2-workflow-activity-cancel"

    # The run settles and the button goes. Focus goes to Refresh beside it, not to the page.
    tab.push(run_snapshot(status="cancelled", finished_tools=1, response_preview=""))
    expect(cancel).to_have_count(0)
    assert tab.focused() == "v2-workflow-activity-refresh"


# A cancel that outlasts the run it was for ----------------------------------------------------------

OTHER_RUN = "run-other-0001"
OTHER_LINK = f"/workflow-activity?conversationId={CONVERSATION_ID}&workflowId={WORKFLOW_ID}&runId={OTHER_RUN}"


def test_a_cancel_that_finishes_after_the_reader_moved_to_another_run_leaves_that_run_to_load(tab):
    tab.snapshot = running()
    tab.open(RUN_LINK)
    expect(tab.stat("run")).to_have_text(RUN_ID[:8])

    # Cancel this run, and leave its request unanswered.
    tab.hold_cancel = True
    tab.cancel_button.click()
    tab.wait_for(lambda: tab.held_cancel, "The cancel request was not made.")

    # The reader follows a link to another run, whose first read is not answered yet either.
    tab.hold_reads = 1
    tab.navigate(OTHER_LINK)
    tab.wait_for(lambda: tab.held_reads, "The page did not read the other run.")
    expect(tab.page.get_by_role("status", name="Loading workflow activity")).to_be_visible()

    # The first run's cancel finishes while the other run is still loading. Reading the first run
    # again would stop the other run's read, which nothing would then start again.
    tab.finish_cancel()
    tab.page.wait_for_timeout(300)
    assert [item.query["run_id"] for item in tab.reads()] == [RUN_ID, OTHER_RUN]

    other = running(run_id=OTHER_RUN)
    tab.snapshot = other
    tab.release_read(other)
    expect(tab.stat("run")).to_have_text(OTHER_RUN[:8])
    expect(tab.cards).to_have_count(3)
    expect(tab.page.get_by_role("status", name="Loading workflow activity")).to_have_count(0)
    # It is not the run that was cancelled, so its own button is free.
    expect(tab.cancel_button).to_have_text("Cancel run")
    expect(tab.cancel_button).not_to_have_attribute("aria-disabled", "true")
    assert len(tab.seen("POST", CANCEL_PATH)) == 1


def test_a_cancel_still_under_way_shows_on_its_own_run_and_on_no_other(tab):
    tab.snapshot = running()
    tab.open(RUN_LINK)
    tab.hold_cancel = True
    tab.cancel_button.click()
    tab.wait_for(lambda: tab.held_cancel, "The cancel request was not made.")
    expect(tab.cancel_button).to_have_attribute("aria-busy", "true")

    # Another run is not being cancelled.
    tab.snapshot = running(run_id=OTHER_RUN)
    tab.navigate(OTHER_LINK)
    expect(tab.stat("run")).to_have_text(OTHER_RUN[:8])
    expect(tab.cancel_button).to_have_text("Cancel run")
    expect(tab.cancel_button).not_to_have_attribute("aria-busy", "true")
    expect(tab.cancel_button).not_to_have_attribute("aria-disabled", "true")

    # Back on the first, its request is still under way, and the page does not ask a second time.
    tab.snapshot = running()
    tab.go(-1)
    expect(tab.stat("run")).to_have_text(RUN_ID[:8])
    expect(tab.cancel_button).to_have_attribute("aria-busy", "true")
    expect(tab.cancel_button).to_have_attribute("aria-disabled", "true")
    tab.cancel_button.focus()
    tab.page.keyboard.press("Enter")
    tab.page.wait_for_timeout(150)
    assert len(tab.seen("POST", CANCEL_PATH)) == 1

    # When it finishes, the run it was for is read again.
    tab.snapshot = running()
    tab.snapshot["run"]["status"] = "cancelling"
    reads = len(tab.reads())
    tab.finish_cancel()
    tab.wait_for(lambda: len(tab.reads()) > reads, "The run was not read again after its cancel finished.")
    expect(tab.status).to_have_text("Cancelling")
    expect(tab.cancel_button).to_have_text("Cancelling")


# Group workspaces -----------------------------------------------------------------------------------


def test_a_group_run_reads_the_group_endpoints_and_links_back_into_its_workspace(tab):
    tab.snapshot = running()
    tab.open(GROUP_LINK)

    expect(tab.title).to_have_text(WORKFLOW_NAME)
    reads = tab.seen("GET", GROUP_ACTIVITY_PATH)
    assert tab.seen("GET", ACTIVITY_PATH) == []
    assert reads[-1].query == {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "group_id": GROUP_ID}
    expect(tab.by_id("open-run")).to_have_attribute(
        "href", f"/groups/{GROUP_ID}/workflows?workflow_id={WORKFLOW_ID}&run_id={RUN_ID}",
    )
    expect(tab.by_id("open-workflow")).to_have_attribute("href", f"/chat?conversationId={CONVERSATION_ID}")

    tab.wait_for(lambda: len(tab.held_streams) == 1, "The page did not open the group activity stream.")
    stream = tab.streams_requested()[0]
    assert stream.path == GROUP_STREAM
    assert stream.query == {"workflow_id": WORKFLOW_ID, "run_id": RUN_ID, "group_id": GROUP_ID}

    tab.cancel_button.click()
    tab.wait_for(lambda: tab.seen("POST", GROUP_CANCEL_PATH), "The group run was not cancelled.")
    assert tab.seen("POST", GROUP_CANCEL_PATH)[0].query == {"group_id": GROUP_ID}
    assert tab.seen("POST", CANCEL_PATH) == []


def test_a_group_link_without_its_group_still_reads_and_offers_no_guessed_run_link(tab):
    tab.snapshot = run_snapshot()
    tab.open(f"/workflow-activity?runId={RUN_ID}&scope=group")

    expect(tab.title).to_have_text(WORKFLOW_NAME)
    assert tab.seen("GET", GROUP_ACTIVITY_PATH)[-1].query == {"run_id": RUN_ID}
    expect(tab.by_id("open-run")).to_have_count(0)
    expect(tab.by_id("open-workflow")).to_have_count(1)


def test_the_two_links_beside_the_title_go_to_the_chat_and_to_the_run_in_workflows(tab):
    tab.snapshot = run_snapshot()
    tab.open(RUN_LINK)

    expect(tab.by_id("open-workflow")).to_have_attribute("href", f"/chat?conversationId={CONVERSATION_ID}")
    run_link = tab.by_id("open-run")
    expect(run_link).to_have_attribute("href", f"/workspace/workflows?workflow_id={WORKFLOW_ID}&run_id={RUN_ID}")
    run_link.click()
    expect(tab.page.get_by_text("Another page")).to_be_visible()
    assert tab.route() == f"/workspace/workflows?workflow_id={WORKFLOW_ID}&run_id={RUN_ID}"


# A Microsoft 365 action beside its run --------------------------------------------------------------


def test_a_saved_microsoft_365_action_is_drawn_beside_its_run_and_never_sent_by_opening_the_page(tab):
    action = pending_action()
    tab.actions[action["id"]] = action
    tab.snapshot = run_snapshot(status="running", finished_tools=1, pending_actions=[action], response_preview="")

    def changed(next_action):
        tab.snapshot = run_snapshot(status="running", finished_tools=1, pending_actions=[next_action], response_preview="")

    tab.on_action_change = changed
    tab.open(RUN_LINK)
    page = tab.page

    # The action's own activity is the newest, so the detail panel opens on it with its card.
    card = page.get_by_test_id("v2-pending-action-card")
    expect(card).to_be_visible()
    expect(card).to_have_attribute("data-pending-action-id", action["id"])
    expect(card.get_by_test_id("v2-pending-action-status")).to_contain_text("Ready to review")
    expect(card.get_by_test_id("v2-pending-action-send")).to_be_enabled()
    expect(card.get_by_test_id("v2-pending-action-cancel")).to_be_enabled()
    expect(tab.cards.last).to_contain_text("Mail message review")
    expect(tab.cards.last).to_contain_text("Microsoft Graph")

    # Opening the page, reading the card and waiting around change nothing at Microsoft.
    page.wait_for_timeout(500)
    assert [item for item in tab.requests if item.method == "POST"] == []

    reads = len(tab.reads())
    card.get_by_test_id("v2-pending-action-cancel").click()
    expect(card.get_by_test_id("v2-pending-action-status")).to_contain_text("Cancelled")
    post = tab.seen("POST", f"{PENDING_PATH}/{action['id']}/cancel")
    assert len(post) == 1
    assert post[0].query == {}
    # The card tells the page, which reads the run again once, and does not loop.
    tab.wait_for(lambda: len(tab.reads()) > reads, "The page did not read the run again after the card changed.")
    page.wait_for_timeout(500)
    assert len(tab.reads()) == reads + 1
    # The server draws a cancelled action as a failed activity, as it does for the classic page; the
    # card beside it says what happened.
    expect(tab.cards.last).to_have_attribute("data-status", "failed")
    expect(card.get_by_test_id("v2-pending-action-status")).to_contain_text("Cancelled")


def test_an_action_card_follows_the_activity_that_stands_for_it(tab):
    action = pending_action()
    tab.actions[action["id"]] = action
    tab.snapshot = run_snapshot(status="running", finished_tools=1, pending_actions=[action], response_preview="")
    tab.open(RUN_LINK)

    card = tab.page.get_by_test_id("v2-pending-action-card")
    expect(card).to_be_visible()
    # Another activity has no card, and picking the action's again brings it back.
    tab.cards.nth(1).click()
    expect(card).to_have_count(0)
    tab.cards.last.click()
    expect(card).to_be_visible()


# What a workflow wrote is only ever text -------------------------------------------------------------


def test_everything_a_workflow_wrote_is_drawn_as_text(tab):
    tab.snapshot = run_snapshot(
        status="failed",
        workflow_name=XSS_TEXT,
        runner=XSS_TEXT,
        response_preview=XSS_TEXT,
        error=XSS_TEXT,
        tool_detail=XSS_TEXT,
    )
    tab.open(RUN_LINK)
    page = tab.page

    expect(tab.title).to_have_text(XSS_TEXT)
    expect(tab.caption).to_contain_text(XSS_TEXT)
    tab.by_id("response-toggle").click()
    expect(tab.by_id("response")).to_contain_text(XSS_TEXT)
    tab.cards.nth(1).click()
    expect(tab.by_id("detail-text")).to_contain_text(XSS_TEXT)
    page.wait_for_timeout(200)
    assert page.evaluate("() => window.__xss") is None
    assert page.locator("#root img").count() == 0
    assert page.locator("#root b").count() == 0


# Layout, theme and contrast ------------------------------------------------------------------------


def box(locator):
    result = locator.bounding_box()
    assert result is not None
    return result


def test_the_timeline_and_the_detail_sit_side_by_side_on_a_wide_screen_and_stack_below_992_px(tab):
    tab.snapshot = run_snapshot()
    tab.open(RUN_LINK, viewport={"width": 1280, "height": 760})
    panel = tab.by_id("timeline-panel")
    expect(panel).to_be_visible()

    wide_timeline, wide_detail = box(panel), box(tab.detail)
    assert wide_detail["x"] >= wide_timeline["x"] + wide_timeline["width"] - 1
    assert abs(wide_detail["y"] - wide_timeline["y"]) < 4

    tab.page.set_viewport_size({"width": 992, "height": 760})
    tab.page.wait_for_timeout(100)
    edge_timeline, edge_detail = box(panel), box(tab.detail)
    assert edge_detail["x"] >= edge_timeline["x"] + edge_timeline["width"] - 1

    tab.page.set_viewport_size({"width": 991, "height": 760})
    tab.page.wait_for_timeout(100)
    narrow_timeline, narrow_detail = box(panel), box(tab.detail)
    assert narrow_detail["y"] >= narrow_timeline["y"] + narrow_timeline["height"] - 1
    assert abs(narrow_detail["x"] - narrow_timeline["x"]) < 4


@pytest.mark.parametrize("snapshot", ["finished", "live"])
def test_a_phone_sized_screen_scrolls_vertically_and_nothing_reaches_past_its_edge(tab, snapshot):
    tab.snapshot = run_snapshot() if snapshot == "finished" else running()
    tab.open(RUN_LINK, viewport={"width": 390, "height": 844})
    expect(tab.cards).to_have_count(3)
    # The response panel is the widest thing the hero can hold, and a live run has Cancel run as well.
    buttons = ("refresh", "response-toggle") if snapshot == "finished" else ("refresh", "cancel")
    if snapshot == "finished":
        tab.by_id("response-toggle").click()

    overflow = tab.page.evaluate(
        """() => ({
            width: document.documentElement.scrollWidth,
            client: document.documentElement.clientWidth,
            wide: [...document.querySelectorAll('#root *')]
                .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1
                    && !element.closest('[data-testid="v2-workflow-activity-timeline-viewport"]'))
                .slice(0, 8)
                .map((element) => {
                    const rect = element.getBoundingClientRect();
                    return `${element.tagName}.${String(element.className).slice(0, 48)} right=${Math.round(rect.right)} width=${Math.round(rect.width)}`;
                }),
        })"""
    )
    assert overflow["width"] <= overflow["client"], overflow
    assert overflow["wide"] == [], overflow

    # Every card has the same indent, because there is no room to spend on lanes.
    lefts = tab.cards.evaluate_all("(items) => items.map((item) => Math.round(item.getBoundingClientRect().left))")
    assert len(set(lefts)) == 1, lefts
    # The timeline is capped so the detail is reachable without losing the page.
    assert box(tab.viewport)["height"] <= 844 * 0.5 + 2
    for name in buttons:
        assert box(tab.by_id(name))["height"] >= 28


UNBROKEN_NAME = "weekly_customer_feedback_digest_report_for_q4_2026"
UNBROKEN_TEXT = "segment" + "abcdefghij" * 14
UNBROKEN_RUN_ID = "run-" + "0123456789abcdef" * 4

# What reaches past the edge of the screen or of the box that holds it, anywhere on the page. The
# page scrolls inside its own scroller, so the document alone cannot say that something spilled.
MEASURE_OVERFLOW = r"""
() => {
    const page = document.querySelector('[data-testid="v2-workflow-activity-page"]');
    const named = (id) => document.querySelector(`[data-testid="v2-workflow-activity-${id}"]`);
    const boxes = {
        scroller: page.lastElementChild,
        hero: named('hero'),
        title: named('title'),
        caption: named('caption'),
        panel: named('timeline-panel'),
        viewport: named('timeline-viewport'),
        detail: named('detail'),
        response: named('response'),
    };
    const overflow = {};
    for (const [name, element] of Object.entries(boxes)) {
        overflow[name] = element ? element.scrollWidth - element.clientWidth : null;
    }
    const outside = [...document.querySelectorAll('#root *')]
        .filter((element) => !element.closest('.sr-only'))
        .filter((element) => {
            const rect = element.getBoundingClientRect();
            return rect.width > 0 && (rect.right > window.innerWidth + 1 || rect.left < -1);
        })
        .slice(0, 8)
        .map((element) => {
            const rect = element.getBoundingClientRect();
            const id = element.dataset.testid || '';
            return `${element.tagName}[${id}] ${String(element.className).slice(0, 40)} left=${Math.round(rect.left)} right=${Math.round(rect.right)}`;
        });
    const hero = boxes.hero.getBoundingClientRect();
    const title = boxes.title.getBoundingClientRect();
    return {
        overflow,
        outside,
        titleInsideHero: title.right <= hero.right + 1,
        document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
}
"""


def unbroken_snapshot(*, named=True):
    """A failed run in which every text is one long word, so no line has a place to break."""
    action = pending_action(
        run_id=UNBROKEN_RUN_ID,
        subject=UNBROKEN_TEXT,
        summary={
            "subject": UNBROKEN_TEXT,
            "body_preview": UNBROKEN_TEXT,
            "body_preview_truncated": False,
            "to_recipients": [f"{UNBROKEN_TEXT}@example.com"],
        },
    )
    snapshot = run_snapshot(
        status="failed",
        run_id=UNBROKEN_RUN_ID,
        workflow_name=UNBROKEN_NAME if named else "",
        runner=UNBROKEN_TEXT,
        response_preview=UNBROKEN_TEXT,
        error=UNBROKEN_TEXT,
        tool_detail=UNBROKEN_TEXT,
        pending_actions=[action],
    )
    if not named:
        snapshot["conversation"]["title"] = UNBROKEN_TEXT
    for index, activity in enumerate(snapshot["activities"]):
        for field in ("title", "summary", "detail", "lane_label"):
            activity[field] = f"{UNBROKEN_TEXT}{index}"
        for event in activity["events"]:
            event["content"] = UNBROKEN_TEXT
            event["detail"] = UNBROKEN_TEXT
    return snapshot


@pytest.mark.parametrize("width", [390, 360])
@pytest.mark.parametrize("named", [True, False], ids=["workflow-name", "conversation-title"])
def test_a_long_name_with_no_spaces_in_it_wraps_and_never_widens_the_page(tab, width, named):
    tab.snapshot = unbroken_snapshot(named=named)
    tab.open(RUN_LINK, viewport={"width": width, "height": 800})
    expect(tab.title).to_have_text(UNBROKEN_NAME if named else UNBROKEN_TEXT)
    expect(tab.cards.first).to_be_visible()
    tab.by_id("response-toggle").click()
    expect(tab.by_id("response")).to_contain_text(UNBROKEN_TEXT)

    # Every activity in turn: its card on the timeline, and its detail with the technical detail,
    # the event history and, for the saved email, its card.
    for index in range(tab.cards.count()):
        tab.cards.nth(index).click()
        expect(tab.cards.nth(index)).to_have_attribute("aria-current", "true")
        measured = tab.page.evaluate(MEASURE_OVERFLOW)
        assert measured["document"] <= 0, (index, measured)
        assert all(value is None or value <= 1 for value in measured["overflow"].values()), (index, measured)
        assert measured["outside"] == [], (index, measured)
        assert measured["titleInsideHero"], (index, measured)
    expect(tab.page.get_by_test_id("v2-pending-action-card")).to_be_visible()


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_page_reads_clearly_in_both_themes(tab, theme):
    tab.snapshot = run_snapshot()
    tab.open(RUN_LINK, theme=theme)
    expect(tab.cards).to_have_count(3)
    tab.by_id("response-toggle").click()

    targets = {
        "heading": tab.page.get_by_role("heading", level=1, name="Workflow activity"),
        "title": tab.title,
        "caption": tab.caption,
        "status": tab.status.locator("span.min-w-0"),
        "stat": tab.stat("total"),
        "card title": tab.cards.nth(1).locator("span.font-semibold"),
        "card summary": tab.cards.nth(1).locator("span.text-sm").nth(1),
        "detail title": tab.by_id("detail-title"),
        "detail summary": tab.by_id("detail-summary"),
        "detail text": tab.by_id("detail-text"),
        "response": tab.by_id("response").locator("p.text-sm"),
    }
    failing = {}
    for name, locator in targets.items():
        ratio = locator.first.evaluate(CONTRAST_RATIO_SCRIPT, "color")
        if ratio < 4.5:
            failing[name] = round(ratio, 2)
    assert not failing, f"{theme}: {failing}"
    for status in ("completed", "failed"):
        badge = tab.page.locator(f'[data-testid="v2-workflow-activity-card"] [data-status="{status}"]').first
        if badge.count():
            assert badge.evaluate(CONTRAST_RATIO_SCRIPT, "color") >= 4.5, f"{theme} {status} badge"


# Where the page is opened from ------------------------------------------------------------------------


def run_row(run_id, **extra):
    return {"id": run_id, "status": "completed", "started_at": "2025-01-01T00:00:00+00:00", **extra}


def test_each_run_in_a_workflows_history_opens_its_activity_in_a_new_tab_in_the_right_workspace(tab):
    tab.runs = [run_row(RUN_ID, conversation_id=CONVERSATION_ID), run_row("run-2")]
    tab.open(f"/probe/run-history?workflowId={WORKFLOW_ID}")

    links = tab.page.get_by_test_id("v2-workflow-run-activity-link")
    expect(links).to_have_count(2)
    expect(links.nth(0)).to_have_attribute("href", RUN_LINK)
    expect(links.nth(1)).to_have_attribute("href", f"/workflow-activity?workflowId={WORKFLOW_ID}&runId=run-2")
    expect(links.nth(0)).to_have_accessible_name(
        re.compile(r"Open activity for the run of Jan 1, 2025.* \(opens in a new tab\)")
    )
    for link in (links.nth(0), links.nth(1)):
        expect(link).to_have_attribute("target", "_blank")
        expect(link).to_have_attribute("rel", "noopener noreferrer")

    # It opens a tab of its own and leaves the history where it is, as the classic Activity button does.
    popup = tab.follow(links.nth(1))
    assert popup.url == f"{ORIGIN}/workflow-activity?workflowId={WORKFLOW_ID}&runId=run-2"
    assert tab.route() == f"/probe/run-history?workflowId={WORKFLOW_ID}"
    assert tab.reads() == []


def test_a_group_workflows_history_links_to_the_groups_activity(tab):
    tab.runs = [run_row(RUN_ID, conversation_id=CONVERSATION_ID)]
    tab.open(f"/probe/run-history?workflowId={WORKFLOW_ID}&groupId={GROUP_ID}")

    link = tab.page.get_by_test_id("v2-workflow-run-activity-link")
    expect(link).to_have_attribute("href", f"{RUN_LINK}&scope=group&groupId={GROUP_ID}")
    expect(link).to_have_attribute("target", "_blank")
    assert tab.seen("GET", f"/api/group/workflows/{WORKFLOW_ID}/runs")[0].query == {"group_id": GROUP_ID}
    popup = tab.follow(link)
    assert popup.url == f"{ORIGIN}{RUN_LINK}&scope=group&groupId={GROUP_ID}"


@pytest.mark.parametrize(
    ("workflow", "href"),
    [
        (
            {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "conversation_id": CONVERSATION_ID, "last_run_status": "completed"},
            f"/workflow-activity?conversationId={CONVERSATION_ID}&workflowId={WORKFLOW_ID}",
        ),
        (
            {"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "conversation_id": CONVERSATION_ID, "last_run_at": "2025-01-01T00:00:00Z"},
            f"/workflow-activity?conversationId={CONVERSATION_ID}&workflowId={WORKFLOW_ID}",
        ),
        # No run yet, or no conversation to read one from: nothing to open.
        ({"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "conversation_id": CONVERSATION_ID}, None),
        ({"id": WORKFLOW_ID, "name": WORKFLOW_NAME, "last_run_status": "completed"}, None),
    ],
)
def test_a_workflow_header_links_to_its_activity_in_a_new_tab_once_it_has_run(tab, workflow, href):
    tab.open("/probe/workflow-link", workflow=workflow)

    link = tab.page.get_by_test_id("v2-workflow-activity-link")
    if href is None:
        expect(link).to_have_count(0)
        return
    expect(link).to_have_attribute("href", href)
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    expect(link).to_have_accessible_name(f"Open activity for {WORKFLOW_NAME} (opens in a new tab)")
    assert tab.follow(link).url == f"{ORIGIN}{href}"


def workflow_conversation(**extra):
    return {"id": CONVERSATION_ID, "title": f"Workflow: {WORKFLOW_NAME}", "chat_type": "workflow", "workflow_id": WORKFLOW_ID, **extra}


def test_the_chat_header_offers_activity_for_a_workflow_conversation_in_a_new_tab(tab):
    tab.open("/chat", conversations=[workflow_conversation()], active=CONVERSATION_ID)

    link = tab.page.get_by_test_id("v2-chat-workflow-activity")
    href = f"/workflow-activity?conversationId={CONVERSATION_ID}&workflowId={WORKFLOW_ID}"
    expect(link).to_have_attribute("href", href)
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    expect(link).to_have_accessible_name("Open workflow activity (opens in a new tab)")
    # The chat, and whatever is being typed in it, stays where it is.
    popup = tab.follow(link)
    assert popup.url == f"{ORIGIN}{href}"
    assert tab.route().startswith("/chat")


def test_the_chat_header_reads_the_conversations_own_metadata_when_the_list_has_no_row(tab):
    # A conversation opened from a link may have no row in the list yet; its metadata says what it is.
    tab.metadata[CONVERSATION_ID] = {"chat_type": "workflow", "workflow_id": WORKFLOW_ID, "title": "Weekly digest"}
    tab.open(f"/chat?conversationId={CONVERSATION_ID}")

    expect(tab.page.get_by_test_id("v2-chat-workflow-activity")).to_have_attribute(
        "href", f"/workflow-activity?conversationId={CONVERSATION_ID}&workflowId={WORKFLOW_ID}",
    )


def test_a_group_workflow_conversation_opens_the_groups_activity(tab):
    tab.open(
        "/chat",
        conversations=[workflow_conversation(workspace_type="group", group_id=GROUP_ID)],
        active=CONVERSATION_ID,
    )

    expect(tab.page.get_by_test_id("v2-chat-workflow-activity")).to_have_attribute(
        "href",
        f"/workflow-activity?conversationId={CONVERSATION_ID}&workflowId={WORKFLOW_ID}&scope=group&groupId={GROUP_ID}",
    )


@pytest.mark.parametrize(
    ("conversations", "features"),
    [
        # Not a workflow's conversation.
        ([{"id": CONVERSATION_ID, "title": "Planning", "chat_type": "personal"}], {}),
        # Workflows are switched off for the reader.
        ([workflow_conversation()], {"allow_user_workflows": False}),
        # Group workspaces are switched off for a group workflow's conversation.
        ([workflow_conversation(workspace_type="group", group_id=GROUP_ID)], {"enable_group_workspaces": False}),
    ],
)
def test_the_chat_header_offers_no_activity_where_classic_offers_none(tab, conversations, features):
    tab.open("/chat", conversations=conversations, active=CONVERSATION_ID, features=features)

    expect(tab.page.get_by_role("button", name="View conversation details")).to_be_visible()
    expect(tab.page.get_by_test_id("v2-chat-workflow-activity")).to_have_count(0)


# Development builds run effects twice -------------------------------------------------------------------


def test_a_development_render_does_not_leave_two_streams_open(tab):
    tab.snapshot = running()
    tab.open(RUN_LINK, strict=True)

    expect(tab.stat("total")).to_have_text("3")
    tab.wait_for(lambda: tab.open_streams() >= 1, "The page did not listen for updates.")
    tab.page.wait_for_timeout(300)
    assert tab.open_streams() == 1
    expect(tab.cards).to_have_count(3)
