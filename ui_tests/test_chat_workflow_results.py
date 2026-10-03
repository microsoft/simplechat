# test_chat_workflow_results.py
"""
Browser regressions for asking chat about a finished workflow run's stored result.
Version: 0.261.214
Implemented in: 0.261.214

Exercises the real V2 chat page, composer, chat store, run history and workflow alert card,
bundled by fixtures/workflow_results, against a fake server. The fake answers with the real
reader's and Follow up's fixed wording, codes, statuses and disclosure line
(functions_workflow_result_reader, functions_workflow_result_followup), and replaces every
error text with a private diagnostic the page must never show. Covered: Ask in chat on
personal runs only, the composer chip, a follow-up turn that inherits the run, refusals on
the descriptor read and on the stream (including a result changed by resume-failed), a
question sent while Ask in chat is still opening, the alert card's Ask about this, the
setting turned off, reopening a chat whose latest answer used a result or was masked, and a
user-authored workflow name that must stay text. No live application data is read or
modified; the existing Azure Playwright connection fixture also supports a local browser.
"""

import copy
import hashlib
import json
import mimetypes
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
APP = ROOT / "application" / "single_app"
if str(APP) not in sys.path:
    # Appended, so the application's modules never shadow the test packages.
    sys.path.append(str(APP))

from ui_tests.fixtures.agent_delegation.harness_build import ensure_bundle  # noqa: E402
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: E402,F401
from ui_tests.fixtures.v2_notification_stubs import (  # noqa: E402
    conversation_mark_read_payload,
    notification_count_payload,
    workflow_alert_document,
)
import functions_workflow_result_followup as followup  # noqa: E402
import functions_workflow_result_masking as masking  # noqa: E402
import functions_workflow_result_reader as reader  # noqa: E402
from functions_chat_stream_events import build_user_message_persisted_stream_event  # noqa: E402


# The reader's zone and locale decide how the run's time is written, on the chip and in the
# server's disclosure alike.
pytestmark = [
    pytest.mark.ui,
    pytest.mark.browser_context_args(
        timezone_id="America/Chicago", locale="en-US", viewport={"width": 1280, "height": 900},
    ),
]

FIXTURE = ROOT / "ui_tests" / "fixtures" / "workflow_results"
BUNDLE = FIXTURE / "harness.bundle.js"
BUNDLE_CSS = FIXTURE / "harness.bundle.css"
V2_SOURCE = ROOT / "application" / "v2_ui" / "src"
STATIC = APP / "static"
ORIGIN = "https://simplechat.test"
USER_ID = "user-1"
WORKFLOW_ID = "wf-digest"
WORKFLOW_NAME = "Weekly digest"
GROUP_ID = "g1"
GROUP_WORKFLOW_ID = "wf-team"
SHA_V1 = hashlib.sha256(b"weekly digest result as first stored").hexdigest()
SHA_V2 = hashlib.sha256(b"weekly digest result after resume-failed").hexdigest()
SHA_RUN_5 = hashlib.sha256(b"weekly digest result of a partial run").hexdigest()
# What a server error's own text would reveal. Every refusal carries it; the page must show
# the fixed wording for the refusal's code instead.
PRIVATE_DIAGNOSTIC = "PRIVATE-DIAGNOSTIC results/wf-digest/run-1/task-1.json"
XSS_NAME = '<img src=x onerror="window.__xss=1">'
LAUNCH_PATH = f"/chat?result_workflow_id={WORKFLOW_ID}&result_run_id=run-1&new=1"
NO_STORE = {"Cache-Control": "no-store, private"}

CHIP = "Answering from the Weekly digest run of Mon, May 4, 9:02 AM — not re-running the workflow"
RESULT_PLACEHOLDER = "Ask about the workflow results…"
DEFAULT_PLACEHOLDER = "Send a message, or type # to add a document…"
OPENING = "Opening the workflow result…"
LAUNCH_PENDING = "The workflow result is still opening. Send your question again once it is selected."
INVALID_LINK = "That workflow result link is not valid."
SIGN_IN_AGAIN = "Sign in again to ask about this workflow result."
DISCLOSURE_RUN_1 = (
    "This answer uses the stored result of the Weekly digest run of Mon May 4, 2026, 9:02 AM CDT. "
    "The workflow was not re-run."
)


def reason(code):
    """The server's fixed wording for a closed reason."""
    return reader.WorkflowResultUnavailable(code).message


def run_row(run_id, status, *, started_at=None, completed_at=None, definition_version=2,
            workflow_id=WORKFLOW_ID):
    """A run history row as /api/user/workflows/<id>/runs lists it."""
    return {
        "id": run_id, "workflow_id": workflow_id, "status": status, "trigger_source": "manual",
        "started_at": started_at, "completed_at": completed_at, "definition_version": definition_version,
    }


# Newest first, as the history lists them. Only the two finished v2 runs offer Ask in chat.
RUNS = [
    run_row("run-3", "running", started_at="2026-05-11T14:00:00+00:00"),
    run_row("run-1", "completed", started_at="2026-05-04T14:00:00+00:00",
            completed_at="2026-05-04T14:02:00+00:00"),
    run_row("run-2", "failed", started_at="2026-04-30T14:00:00+00:00",
            completed_at="2026-04-30T14:01:00+00:00"),
    run_row("run-5", "completed_partial", started_at="2026-04-27T14:00:00+00:00",
            completed_at="2026-04-27T14:05:00+00:00"),
    run_row("run-4", "completed", started_at="2026-04-20T14:00:00+00:00",
            completed_at="2026-04-20T14:03:00+00:00", definition_version=3),
]
GROUP_RUNS = [
    run_row("run-g1", "completed", started_at="2026-05-04T13:00:00+00:00",
            completed_at="2026-05-04T13:02:00+00:00", workflow_id=GROUP_WORKFLOW_ID),
]

SEED = """(seed) => {
    const H = window.WorkflowResultsHarness;
    H.stores.bootstrap.useBootstrapStore.setState({
        data: {
            version: '0.261.214',
            user: {id: 'user-1', display_name: 'Riley Chen', roles: []},
            features: {enable_chat_workflow_results: seed.enabled, enable_chat_orchestration: true},
            orchestration: {
                enabled: true, show_manual_controls: true, default_approval_mode: 'manual',
                allow_user_approval_override: false,
            },
            branding: {app_title: 'Contoso Chat'},
            settings: {},
            scope: {groups: [], public_workspaces: []},
            catalogs: {models: [], agents: [], prompts: []},
        },
        loading: false,
        error: null,
    });
    H.stores.userSettings.useUserSettingsStore.setState({settings: {}, loading: false, error: null});
    H.mount(seed.path);
}"""

CHAT_STATE = """() => {
    const state = window.WorkflowResultsHarness.stores.chat.useChatStore.getState();
    return {
        activeConversationId: state.activeConversationId,
        workflowResultContext: state.workflowResultContext,
        launching: Boolean(state.workflowResultLaunch),
        streamError: state.streamError,
        streaming: state.streaming,
    };
}"""


class ResultsServer:
    """The HTTP answers the chat page, the run history and the alert card need, and a record of what was asked."""

    def __init__(self, stylesheets):
        self.stylesheets = stylesheets
        self.enabled = True
        self.signed_out = False
        self.storage_down = False
        self.holding = False
        self.workflow_name = WORKFLOW_NAME
        self.deleted = set()
        self.access_lost = set()
        self.result_sha = {"run-1": SHA_V1, "run-5": SHA_RUN_5, "run-4": SHA_V1}
        self.stream_failures = []
        self.runs = {run["id"]: run for run in RUNS}
        self.conversations = {}
        self.titles = {}
        self.held = []
        self.creates = []
        self.stream_bodies = []
        self.descriptor_reads = []
        self.notification_changes = []
        self.requests = []
        self.unexpected = []
        self.errors = []
        self.expected_http_failures = set()
        self.answers = 0

    # Routing ----------------------------------------------------------------------------------

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        method = request.method
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(f"{method} {request.url}")
            route.abort()
            return
        path = parsed.path
        self.requests.append((method, f"{path}?{parsed.query}" if parsed.query else path))
        query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        for answer in (self.page_route, self.workflow_route, self.chat_route, self.conversation_route,
                       self.other_route):
            if answer(route, method, path, query):
                return
        self.unexpected.append(f"{method} {path}")
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
        elif path.startswith("/static/"):
            asset = (STATIC / path.removeprefix("/static/")).resolve()
            if not (asset.is_relative_to(STATIC.resolve()) and asset.is_file()):
                return False
            route.fulfill(path=str(asset), content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
        else:
            return False
        return True

    def workflow_route(self, route, method, path, query):
        if method != "GET":
            return False
        if match := re.fullmatch(r"/api/user/workflows/([^/]+)/runs/([^/]+)/result-context", path):
            self.answer_descriptor(route, path, unquote(match.group(1)), unquote(match.group(2)))
        elif path == f"/api/user/workflows/{WORKFLOW_ID}/runs":
            route.fulfill(json={"runs": copy.deepcopy(RUNS)})
        elif path == f"/api/group/workflows/{GROUP_WORKFLOW_ID}/runs" and query.get("group_id") == GROUP_ID:
            route.fulfill(json={"runs": copy.deepcopy(GROUP_RUNS)})
        else:
            return False
        return True

    def chat_route(self, route, method, path, query):
        if method != "POST":
            return False
        if path == "/api/create_conversation":
            self.creates.append(route.request.post_data_json)
            conversation_id = f"conv-new-{len(self.creates)}"
            self.conversations[conversation_id] = []
            self.titles[conversation_id] = "New Conversation"
            route.fulfill(json={"conversation_id": conversation_id, "title": self.titles[conversation_id]})
        elif path == "/api/chat/stream":
            self.answer_stream(route, path, route.request.post_data_json or {})
        else:
            return False
        return True

    def conversation_route(self, route, method, path, query):
        if method == "GET" and path == "/api/conversations/feed":
            route.fulfill(json={
                "success": True, "conversations": [], "has_more": False, "next_cursor": None,
                "page_size": int(query.get("page_size", 50)), "hidden_count": 0, "priority_count": 0,
                "recent_count": 0, "source_offsets": {},
            })
        elif method == "GET" and (match := re.fullmatch(r"/api/conversations/([^/]+)/kind", path)):
            conversation_id = unquote(match.group(1))
            if conversation_id in self.conversations:
                route.fulfill(json={"conversation_id": conversation_id, "kind": "personal"})
            else:
                self.expected_http_failures.add((path, 404))
                route.fulfill(status=404, json={"error": "Conversation not found"})
        elif method == "GET" and (match := re.fullmatch(r"/api/conversations/([^/]+)/metadata", path)):
            conversation_id = unquote(match.group(1))
            route.fulfill(json={"conversation_id": conversation_id, "title": self.titles.get(conversation_id, "")})
        elif method == "GET" and path == "/api/get_messages":
            route.fulfill(json={"messages": copy.deepcopy(self.conversations.get(query.get("conversation_id"), []))})
        elif method == "POST" and (match := re.fullmatch(r"/api/conversations/([^/]+)/mark-read", path)):
            route.fulfill(json=conversation_mark_read_payload(unquote(match.group(1))))
        else:
            return False
        return True

    def other_route(self, route, method, path, query):
        if method == "GET" and re.fullmatch(r"/api/chat/stream/status/[^/]+", path):
            route.fulfill(json={"active": False, "pending": False, "reattachable": False})
        elif method == "GET" and path == "/api/notifications/count":
            route.fulfill(json=notification_count_payload(0))
        elif method == "GET" and path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
        elif method == "POST" and (match := re.fullmatch(r"/api/notifications/([^/]+)/read", path)):
            self.notification_changes.append(("read", unquote(match.group(1))))
            route.fulfill(json={"success": True})
        elif method == "DELETE" and (match := re.fullmatch(r"/api/notifications/([^/]+)/dismiss", path)):
            self.notification_changes.append(("dismiss", unquote(match.group(1))))
            route.fulfill(json={"success": True})
        else:
            return False
        return True

    # Answers ----------------------------------------------------------------------------------

    def closed_reason(self, workflow_id, run_id):
        """What the reader would refuse this run with, checked in the reader's order."""
        run = self.runs.get(run_id)
        if workflow_id != WORKFLOW_ID or run is None or run_id in self.deleted:
            return "workflow_result_not_found"
        if self.storage_down:
            return "workflow_result_storage_unavailable"
        if run["status"] in ("queued", "running"):
            return "workflow_result_in_progress"
        if run["status"] not in reader.READABLE_RUN_STATUSES:
            return "workflow_result_not_finished"
        if run.get("definition_version") == 3:
            return "workflow_result_unsupported"
        if run_id in self.access_lost:
            return "workflow_result_access_denied"
        return None

    def descriptor(self, run_id):
        """The public descriptor: all the browser is ever told about a result."""
        run = self.runs[run_id]
        return {
            "version": masking.WORKFLOW_RESULT_VERSION, "workflow_id": WORKFLOW_ID, "run_id": run_id,
            "workflow_name": self.workflow_name, "status": run["status"], "completed_at": run["completed_at"],
            "result_sha256": self.result_sha[run_id], "available": True,
        }

    def refuse(self, route, path, code):
        """The reader's JSON refusal for `code`, carrying a server text the page must not show."""
        payload, status = reader.workflow_result_error_payload(reader.WorkflowResultUnavailable(code))
        self.expected_http_failures.add((path, status))
        route.fulfill(status=status, json={**payload, "error": PRIVATE_DIAGNOSTIC}, headers=NO_STORE)

    def answer_descriptor(self, route, path, workflow_id, run_id):
        """GET /api/user/workflows/<id>/runs/<run_id>/result-context, read by every entry point."""
        self.descriptor_reads.append(run_id)
        if self.signed_out:
            self.expected_http_failures.add((path, 401))
            route.fulfill(status=401, json={"error": PRIVATE_DIAGNOSTIC})
            return
        code = self.closed_reason(workflow_id, run_id) if self.enabled else "workflow_results_disabled"
        if code:
            self.refuse(route, path, code)
        elif self.holding:
            self.held.append((route, run_id))
        else:
            route.fulfill(json={"workflow_result": self.descriptor(run_id)}, headers=NO_STORE)

    def release(self):
        """Answer the descriptor reads held back, with the result as it stands now."""
        self.holding = False
        held, self.held = self.held, []
        for route, run_id in held:
            route.fulfill(json={"workflow_result": self.descriptor(run_id)}, headers=NO_STORE)

    def answer_stream(self, route, path, body):
        """POST /api/chat/stream carrying a workflow result, as route_backend_chats handles it."""
        self.stream_bodies.append(copy.deepcopy(body))
        if body.get("workflow_result_context") is None:
            self.unexpected.append("A question went out as an ordinary chat turn.")
            self.expected_http_failures.add((path, 400))
            route.fulfill(status=400, json={"error": "Unexpected ordinary chat turn."})
            return
        refusal = followup.workflow_result_request_precheck(
            body, {}, [], gate=lambda settings, user_roles=None: self.enabled,
        )
        if refusal is not None:
            payload, status = refusal
            self.expected_http_failures.add((path, status))
            route.fulfill(status=status, json={**payload, "error": PRIVATE_DIAGNOSTIC})
            return
        conversation_id = body.get("conversation_id")
        if conversation_id not in self.conversations:
            self.unexpected.append(f"A question was sent to an unknown conversation: {conversation_id}")
            self.expected_http_failures.add((path, 404))
            route.fulfill(status=404, json={"error": "Conversation not found"})
            return
        context = body["workflow_result_context"]
        code = (
            self.stream_failures.pop(0) if self.stream_failures
            else self.closed_reason(context["workflow_id"], context["run_id"])
        )
        if code is None and self.result_sha.get(context["run_id"]) != context["result_sha256"]:
            code = "workflow_result_changed"
        if code:
            frame = {
                "error": PRIVATE_DIAGNOSTIC, "conversation_id": conversation_id,
                "warning_type": followup.WORKFLOW_RESULT_WARNING_TYPE, "error_code": code,
                "status_code": reader.WorkflowResultUnavailable(code).status,
            }
            route.fulfill(status=200, headers={"Content-Type": "text/event-stream"},
                          body=f"data: {json.dumps(frame)}\n\n")
            return
        self.answer_question(route, conversation_id, body)

    def answer_question(self, route, conversation_id, body):
        """A Follow up turn, saved and streamed as run_workflow_result_follow_up does."""
        context = {key: body["workflow_result_context"][key] for key in ("workflow_id", "run_id", "result_sha256")}
        stored = self.conversations[conversation_id]
        turn = sum(1 for message in stored if message["role"] == "user") + 1
        user_message_id = f"{conversation_id}_user_{turn}"
        assistant_id = f"{conversation_id}_assistant_{turn}"
        inherited = []
        for message in stored:
            metadata = message.get("metadata") or {}
            if message["role"] != "assistant" or (metadata.get("workflow_result") or {}).get("available") is False:
                continue
            for item in metadata.get("workflow_result_contexts") or []:
                if item not in inherited and item != context:
                    inherited.append(item)
        descriptor = self.descriptor(context["run_id"])
        disclosure = reader.format_workflow_result_disclosure(
            descriptor, body.get("time_zone"), partial=descriptor["status"] == "completed_partial",
        )
        self.answers += 1
        content = f"Answer {self.answers} from the stored result.\n\n{disclosure}"
        thread = {"thread_id": f"{conversation_id}-thread-{turn}", "previous_thread_id": None,
                  "active_thread": True, "thread_attempt": 1}
        metadata = {
            "workflow_result": descriptor, "workflow_result_contexts": [*inherited, context], "thread_info": thread,
        }
        stored.append({
            "id": user_message_id, "conversation_id": conversation_id, "role": "user",
            "content": body.get("message"), "timestamp": f"2026-05-12T15:{turn:02d}:00Z",
            "metadata": {"workflow_result_context": context, "thread_info": thread},
        })
        stored.append({
            "id": assistant_id, "conversation_id": conversation_id, "role": "assistant", "content": content,
            "timestamp": f"2026-05-12T15:{turn:02d}:05Z", "model_deployment_name": "gpt-4o", "augmented": False,
            "hybrid_citations": [], "web_search_citations": [], "agent_citations": [], "metadata": metadata,
        })
        # normalize_terminal_chat_payload's frame.
        frame = {
            "done": True, "conversation_id": conversation_id,
            "conversation_title": self.titles.get(conversation_id, ""), "classification": [],
            "model_deployment_name": "gpt-4o", "message_id": assistant_id, "user_message_id": user_message_id,
            "augmented": False, "hybrid_citations": [], "web_search_citations": [],
            "citation_tracking_version": None, "cited_hybrid_citations": [], "cited_web_search_citations": [],
            "agent_citations": [], "agent_display_name": None, "agent_name": None, "full_content": content,
            "image_url": None, "reload_messages": False, "kernel_fallback_notice": None,
            "thoughts_enabled": False, "blocked": False, "context": [], "chat_type": None,
            "scope_locked": None, "locked_contexts": [], "analysis_coverage": {}, "document_action": {},
            "metadata": copy.deepcopy(metadata),
        }
        events = build_user_message_persisted_stream_event(conversation_id, user_message_id)
        route.fulfill(status=200, headers={"Content-Type": "text/event-stream"},
                      body=f"{events}data: {json.dumps(frame)}\n\n")


class ResultsTab:
    """The harness page, and what a person sees and does on it."""

    def __init__(self, page, server):
        self.page = page
        self.server = server

    def open(self, path="/chat", *, enabled=None):
        """Mount `path`. `enabled` is the bootstrap flag; it follows the server's setting unless given."""
        self.page.route("**/*", self.server.handle)
        self.page.on("pageerror", lambda error: self.server.errors.append(f"pageerror: {error}"))
        self.page.on("console", self.record_console)
        self.page.goto(f"{ORIGIN}/harness.html")
        for stylesheet in self.server.stylesheets:
            self.page.add_style_tag(path=str(stylesheet))
        flag = self.server.enabled if enabled is None else enabled
        self.page.evaluate(SEED, {"path": path, "enabled": flag})
        return self

    def record_console(self, message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        status = re.search(r"^Failed to load resource: the server responded with a status of (\d+)", message.text)
        if status and (path, int(status.group(1))) in self.server.expected_http_failures:
            return
        self.server.errors.append(f"console: {message.text}")

    def navigate(self, path):
        """Move within the mounted router, as the rail does."""
        self.page.evaluate("(path) => window.WorkflowResultsHarness.navigate(path)", path)

    def show_alerts(self, alerts):
        return self.page.evaluate("(alerts) => window.WorkflowResultsHarness.showAlertCard(alerts)", alerts)

    def state(self):
        return self.page.evaluate(CHAT_STATE)

    def wait_for(self, predicate, message, timeout=5.0):
        """Poll from the test thread, so routes keep being answered meanwhile."""
        deadline = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() > deadline:
                raise AssertionError(message)
            self.page.wait_for_timeout(50)

    def ask(self, question):
        self.composer.fill(question)
        self.send_button.click()

    def offered_rows(self):
        """How many Ask in chat buttons each run row has, in the order shown."""
        return self.run_rows.evaluate_all(
            "(rows) => rows.map((row) => row.querySelectorAll('[data-workflow-run-ask-in-chat]').length)",
        )

    def ask_labels(self):
        labels = self.ask_in_chat.evaluate_all("(buttons) => buttons.map((button) => button.getAttribute('aria-label'))")
        # The time is written by Intl, which may put a narrow no-break space before AM.
        return [" ".join((label or "").split()) for label in labels]

    @property
    def chip(self):
        return self.page.locator("[data-workflow-result-chip]")

    @property
    def chip_text(self):
        return self.chip.locator("span")

    @property
    def remove_chip(self):
        return self.page.get_by_role("button", name="Remove workflow result context", exact=True)

    @property
    def composer(self):
        return self.page.locator("textarea#composer-input")

    @property
    def send_button(self):
        return self.page.get_by_role("button", name="Send message", exact=True)

    @property
    def orchestrate(self):
        return self.page.locator('button[title="Orchestrate"]')

    @property
    def toasts(self):
        return self.page.locator('div.fixed[aria-live="polite"] > [role="alert"]')

    @property
    def stream_error(self):
        return self.page.locator('div[role="alert"]:not(.glass-modal)')

    def message(self, message_id):
        return self.page.locator(f'[id="message-{message_id}"]')

    def messages_with(self, text):
        return self.page.locator('[id^="message-"]', has_text=text)

    @property
    def route(self):
        return self.page.locator("[data-current-route]")

    @property
    def run_rows(self):
        return self.page.get_by_role("list", name="Workflow run history").locator(":scope > li")

    @property
    def ask_in_chat(self):
        return self.page.locator("[data-workflow-run-ask-in-chat]")

    @property
    def alert_card(self):
        return self.page.locator("[data-workflow-alert-card]")

    @property
    def follow_up(self):
        return self.page.locator("[data-workflow-alert-follow-up]")


@pytest.fixture(scope="module")
def harness_assets():
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
    BUNDLE_CSS.unlink(missing_ok=True)


@pytest.fixture
def server(harness_assets):
    api = ResultsServer(harness_assets)
    yield api
    assert not api.held, "A test left a descriptor read held back."
    assert not api.errors, api.errors
    assert not api.unexpected, api.unexpected


@pytest.fixture
def tab(page, server):
    results = ResultsTab(page, server)
    yield results
    if page.url.startswith(ORIGIN):
        shown = page.evaluate("() => document.body.innerText")
        assert PRIVATE_DIAGNOSTIC not in shown, "A server's error text reached the page."


def result_context(run_id="run-1", sha=SHA_V1):
    return {"workflow_id": WORKFLOW_ID, "run_id": run_id, "result_sha256": sha}


def seed_conversation(server, conversation_id, *, answered_from=None, masked=False):
    """
    A chat with one earlier turn: an ordinary one, one answered from a run's stored result, or
    that answer as sanitize_saved_analysis_messages returns it once the result can't be read.
    """
    thread = {"thread_id": f"{conversation_id}-thread-1", "previous_thread_id": None,
              "active_thread": True, "thread_attempt": 1}
    question = {
        "id": f"{conversation_id}_user_1", "conversation_id": conversation_id, "role": "user",
        "content": "What changed this week?", "timestamp": "2026-05-05T15:00:00Z",
        "metadata": {"thread_info": thread},
    }
    reply = {
        "id": f"{conversation_id}_assistant_1", "conversation_id": conversation_id, "role": "assistant",
        "content": "Three items changed this week.", "timestamp": "2026-05-05T15:00:05Z",
        "model_deployment_name": "gpt-4o", "augmented": False, "hybrid_citations": [],
        "web_search_citations": [], "agent_citations": [], "metadata": {"thread_info": thread},
    }
    if masked:
        # Only the question's own text is kept; the answer keeps no trace of the result.
        reply = {
            **{key: reply[key] for key in ("id", "conversation_id", "role", "timestamp", "model_deployment_name")},
            "content": masking.WORKFLOW_RESULT_UNAVAILABLE_MESSAGE,
            "metadata": {
                "thread_info": thread,
                "workflow_result": {"version": masking.WORKFLOW_RESULT_VERSION, "available": False},
            },
            "agent_citations": [], "hybrid_citations": [], "web_search_citations": [], "thoughts": [],
        }
    elif answered_from:
        descriptor = server.descriptor(answered_from)
        context = result_context(answered_from, descriptor["result_sha256"])
        disclosure = reader.format_workflow_result_disclosure(descriptor, "America/Chicago")
        question["metadata"]["workflow_result_context"] = context
        reply["content"] = f"Three items changed this week.\n\n{disclosure}"
        reply["metadata"].update(workflow_result=descriptor, workflow_result_contexts=[context])
    server.conversations[conversation_id] = [question, reply]
    server.titles[conversation_id] = "Earlier chat"


def alert(notification_id, **fields):
    """A personal workflow alert about run-1 of the digest, raised a minute ago."""
    fields = {"workflow_id": WORKFLOW_ID, "workflow_name": WORKFLOW_NAME, "run_id": "run-1", **fields}
    raised = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return workflow_alert_document(notification_id, created_at=raised, **fields)


# Every source a turn could otherwise read; a question about a stored result turns them all off.
SOURCE_FLAGS = (
    "hybrid_search", "document_context_requested", "user_workspace_context_enabled", "web_search_enabled",
    "url_access_enabled", "source_review_enabled", "deep_research_enabled", "image_generation",
)


def select_run_1(tab):
    """Ask in chat on the digest's run of Mon May 4, from the run history."""
    tab.open("/workspace/workflows")
    expect(tab.ask_in_chat).to_have_count(2)
    tab.ask_in_chat.first.click()
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "selected")
    expect(tab.chip_text).to_have_text(CHIP)


def assert_nothing_sent(server):
    assert server.creates == [], server.creates
    assert server.stream_bodies == [], server.stream_bodies


# Ask in chat and a follow-up turn -------------------------------------------------------------


def test_ask_in_chat_answers_from_the_run_and_the_next_question_inherits_it(tab, server):
    tab.open("/workspace/workflows")
    expect(tab.ask_in_chat).to_have_count(2)
    # Running, failed and v3 runs offer nothing; only the finished runs the reader supports do.
    assert tab.offered_rows() == [0, 1, 0, 1, 0]
    assert tab.ask_labels() == [
        "Ask in chat about the run of Mon, May 4, 9:02 AM",
        "Ask in chat about the run of Mon, Apr 27, 9:05 AM",
    ]
    assert server.descriptor_reads == [], "Listing runs must not read their results."

    tab.ask_in_chat.first.click()
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "selected")
    expect(tab.chip_text).to_have_text(CHIP)
    expect(tab.route).to_have_text("/chat")
    assert server.descriptor_reads == ["run-1"]
    expect(tab.composer).to_have_attribute("placeholder", RESULT_PLACEHOLDER)
    # Orchestration would plan its own sources, so it is off while the chip is there.
    expect(tab.orchestrate).to_have_attribute("aria-pressed", "false")

    question = "What did the digest find?"
    tab.ask(question)
    answer = tab.message("conv-new-1_assistant_1")
    expect(answer).to_contain_text("Answer 1 from the stored result.")
    expect(answer.locator("em")).to_have_text(DISCLOSURE_RUN_1)
    assert server.creates == [{"initial_message": question}]
    body = server.stream_bodies[-1]
    assert body["conversation_id"] == "conv-new-1"
    assert body["message"] == question
    assert body["workflow_result_context"] == result_context("run-1", SHA_V1)
    assert body["time_zone"] == "America/Chicago"
    assert [flag for flag in SOURCE_FLAGS if body.get(flag) is not False] == []
    assert [key for key in ("analysis_result_context", "orchestration", "document_action") if key in body] == []
    expect(tab.route).to_have_text("/chat?conversationId=conv-new-1")
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "selected")

    # The next question inherits the run without choosing it again.
    tab.ask("Which item mattered most?")
    expect(tab.message("conv-new-1_assistant_2")).to_contain_text("Answer 2 from the stored result.")
    assert len(server.creates) == 1
    assert server.stream_bodies[-1]["conversation_id"] == "conv-new-1"
    assert server.stream_bodies[-1]["workflow_result_context"] == result_context("run-1", SHA_V1)
    assert server.descriptor_reads == ["run-1"]

    tab.remove_chip.click()
    expect(tab.chip).to_have_count(0)
    expect(tab.composer).to_have_attribute("placeholder", DEFAULT_PLACEHOLDER)
    expect(tab.orchestrate).to_have_attribute("aria-pressed", "true")

    # Group workflows aren't in this phase: their finished runs offer nothing.
    tab.navigate(f"/groups/{GROUP_ID}/workflows")
    expect(tab.run_rows).to_have_count(1)
    expect(tab.ask_in_chat).to_have_count(0)
    group_runs = f"/api/group/workflows/{GROUP_WORKFLOW_ID}/runs"
    assert any(path.startswith(group_runs) for method, path in server.requests)
    assert server.descriptor_reads == ["run-1"]


def test_a_result_changed_by_resume_failed_is_refused_and_can_be_selected_again(tab, server):
    select_run_1(tab)
    # resume-failed re-ran a failed task inside the same run, so its result is different now.
    server.result_sha["run-1"] = SHA_V2

    question = "What did the digest find?"
    tab.ask(question)
    expect(tab.stream_error).to_contain_text(reason("workflow_result_changed"))
    expect(tab.chip).to_have_count(0)
    expect(tab.composer).to_have_attribute("placeholder", DEFAULT_PLACEHOLDER)
    expect(tab.messages_with(question)).to_have_count(1)
    assert server.answers == 0
    assert server.stream_bodies[-1]["workflow_result_context"] == result_context("run-1", SHA_V1)

    tab.navigate("/workspace/workflows")
    expect(tab.ask_in_chat).to_have_count(2)
    tab.ask_in_chat.first.click()
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "selected")
    expect(tab.route).to_have_text("/chat")
    tab.ask(question)
    expect(tab.message("conv-new-2_assistant_1")).to_contain_text("Answer 1 from the stored result.")
    assert server.stream_bodies[-1]["workflow_result_context"] == result_context("run-1", SHA_V2)
    assert server.descriptor_reads == ["run-1", "run-1"]


@pytest.mark.parametrize(("change", "code"), [
    ("deleted", "workflow_result_not_found"),
    ("access_lost", "workflow_result_access_denied"),
    ("disabled", "workflow_results_disabled"),
])
def test_a_question_the_server_refuses_clears_the_chip_and_is_not_answered(tab, server, change, code):
    select_run_1(tab)
    if change == "deleted":
        server.deleted.add("run-1")
    elif change == "access_lost":
        server.access_lost.add("run-1")
    else:
        # Turned off after the page loaded: the route's precheck refuses before streaming.
        server.enabled = False

    question = "What did the digest find?"
    tab.ask(question)
    expect(tab.stream_error).to_contain_text(reason(code))
    expect(tab.chip).to_have_count(0)
    expect(tab.composer).to_have_attribute("placeholder", DEFAULT_PLACEHOLDER)
    # Kept on screen, so the reader still has what they asked.
    expect(tab.messages_with(question)).to_have_count(1)
    assert server.answers == 0
    assert len(server.stream_bodies) == 1


def test_a_storage_failure_keeps_the_chip_so_the_question_can_be_sent_again(tab, server):
    select_run_1(tab)
    server.stream_failures.append("workflow_result_storage_unavailable")

    tab.ask("What did the digest find?")
    expect(tab.stream_error).to_contain_text(reason("workflow_result_storage_unavailable"))
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "selected")
    expect(tab.composer).to_have_attribute("placeholder", RESULT_PLACEHOLDER)
    assert server.answers == 0

    tab.ask("What did the digest find?")
    expect(tab.message("conv-new-1_assistant_1")).to_contain_text("Answer 1 from the stored result.")
    assert len(server.creates) == 1
    assert [body["conversation_id"] for body in server.stream_bodies] == ["conv-new-1", "conv-new-1"]
    assert server.stream_bodies[-1]["workflow_result_context"] == result_context("run-1", SHA_V1)


# Opening a result that can't be asked about ---------------------------------------------------


@pytest.mark.parametrize(("change", "run_id", "expected"), [
    ("deleted", "run-1", reason("workflow_result_not_found")),
    ("access_lost", "run-1", reason("workflow_result_access_denied")),
    ("none", "run-3", reason("workflow_result_in_progress")),
    ("storage_down", "run-1", reason("workflow_result_storage_unavailable")),
    ("disabled", "run-1", reason("workflow_results_disabled")),
    ("signed_out", "run-1", SIGN_IN_AGAIN),
])
def test_a_run_that_cannot_be_opened_is_reported_and_nothing_is_selected(tab, server, change, run_id, expected):
    if change == "deleted":
        server.deleted.add(run_id)
    elif change == "access_lost":
        server.access_lost.add(run_id)
    elif change == "storage_down":
        server.storage_down = True
    elif change == "disabled":
        server.enabled = False
    elif change == "signed_out":
        server.signed_out = True

    # The bootstrap still says the feature is on: only the server decides.
    tab.open(f"/chat?result_workflow_id={WORKFLOW_ID}&result_run_id={run_id}&new=1", enabled=True)
    expect(tab.toasts.locator("p")).to_have_text(expected)
    expect(tab.chip).to_have_count(0)
    expect(tab.route).to_have_text("/chat")
    expect(tab.composer).to_have_attribute("placeholder", DEFAULT_PLACEHOLDER)
    assert server.descriptor_reads == [run_id]
    assert_nothing_sent(server)


@pytest.mark.parametrize("path", [
    f"/chat?result_workflow_id={WORKFLOW_ID}&result_run_id=run%20bad&new=1",
    f"/chat?result_workflow_id={WORKFLOW_ID}&result_run_id=run-1",
])
def test_an_invalid_ask_in_chat_link_reads_nothing(tab, server, path):
    tab.open(path)
    expect(tab.toasts.locator("p")).to_have_text(INVALID_LINK)
    expect(tab.chip).to_have_count(0)
    expect(tab.route).to_have_text("/chat")
    assert server.descriptor_reads == []
    assert_nothing_sent(server)


def test_a_question_written_while_the_result_is_opening_waits_for_it(tab, server):
    server.holding = True
    tab.open(LAUNCH_PATH)
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "opening")
    expect(tab.chip_text).to_have_text(OPENING)
    expect(tab.composer).to_have_attribute("placeholder", RESULT_PLACEHOLDER)
    tab.wait_for(lambda: len(server.held) == 1, "The descriptor read was not made once.")

    question = "What did the digest find?"
    tab.composer.fill(question)
    expect(tab.send_button).to_be_disabled()
    tab.composer.press("Enter")
    tab.page.wait_for_timeout(300)
    # Sent now, it would go out as an ordinary turn a moment before the chip appeared.
    assert_nothing_sent(server)
    expect(tab.composer).to_have_value(question)

    server.release()
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "selected")
    expect(tab.chip_text).to_have_text(CHIP)
    expect(tab.send_button).to_be_enabled()
    tab.composer.press("Enter")
    expect(tab.message("conv-new-1_assistant_1")).to_contain_text("Answer 1 from the stored result.")
    assert server.creates == [{"initial_message": question}]
    assert server.stream_bodies[-1]["workflow_result_context"] == result_context("run-1", SHA_V1)
    assert server.descriptor_reads == ["run-1"]


# The workflow alert card ----------------------------------------------------------------------


@pytest.mark.parametrize("start", ["/work", "/chat?conversationId=conv-old"])
def test_ask_about_this_on_a_personal_alert_opens_a_chat_about_its_run(tab, server, start):
    seed_conversation(server, "conv-old")
    tab.open(start)
    if start.startswith("/chat"):
        expect(tab.message("conv-old_assistant_1")).to_contain_text("Three items changed this week.")

    shown = tab.show_alerts([alert("n-1")])
    assert shown == 1
    expect(tab.alert_card).to_have_count(1)
    expect(tab.follow_up).to_have_text("Ask about this")
    tab.alert_card.locator("[data-workflow-alert-show-more]").click()
    tab.follow_up.click()
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "selected")
    expect(tab.chip_text).to_have_text(CHIP)
    expect(tab.route).to_have_text("/chat")
    expect(tab.alert_card).to_have_count(0)
    # A new chat: the one that was open keeps its messages and is not asked about the run.
    expect(tab.message("conv-old_assistant_1")).to_have_count(0)
    assert tab.state()["activeConversationId"] is None
    assert server.descriptor_reads == ["run-1"]
    # Asking about an alert doesn't settle it; it stays in the reader's notifications.
    assert server.notification_changes == []
    assert_nothing_sent(server)


@pytest.mark.parametrize("fields", [
    {"scope": "group", "group_id": GROUP_ID, "workflow_id": GROUP_WORKFLOW_ID, "run_id": "run-g1"},
    {"category": "failure"},
    {"run_id": None},
], ids=["group", "failed-run", "no-run"])
def test_alerts_that_name_no_readable_personal_run_offer_no_follow_up(tab, server, fields):
    tab.open("/work")
    shown = tab.show_alerts([alert("n-2", **fields)])
    assert shown == 1
    expect(tab.alert_card).to_have_count(1)
    expect(tab.alert_card.locator("[data-workflow-alert-links]")).to_have_count(1)
    expect(tab.follow_up).to_have_count(0)
    assert server.descriptor_reads == []


def test_with_the_setting_off_nothing_offers_a_workflow_result(tab, server):
    server.enabled = False
    tab.open("/workspace/workflows")
    expect(tab.run_rows).to_have_count(len(RUNS))
    expect(tab.ask_in_chat).to_have_count(0)

    # A link made while it was on is refused by the server rather than trusted.
    tab.navigate(LAUNCH_PATH)
    expect(tab.toasts.locator("p")).to_have_text(reason("workflow_results_disabled"))
    expect(tab.chip).to_have_count(0)
    expect(tab.route).to_have_text("/chat")
    assert server.descriptor_reads == ["run-1"]

    shown = tab.show_alerts([alert("n-1")])
    assert shown == 1
    expect(tab.alert_card).to_have_count(1)
    expect(tab.alert_card.locator("[data-workflow-alert-links]")).to_have_count(1)
    expect(tab.follow_up).to_have_count(0)
    assert_nothing_sent(server)


# Reopening a chat -----------------------------------------------------------------------------


def test_reopening_a_chat_answered_from_a_run_asks_about_it_again(tab, server):
    seed_conversation(server, "conv-old", answered_from="run-1")
    tab.open("/chat?conversationId=conv-old")
    expect(tab.message("conv-old_assistant_1")).to_contain_text("Three items changed this week.")
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "selected")
    expect(tab.chip_text).to_have_text(CHIP)
    expect(tab.composer).to_have_attribute("placeholder", RESULT_PLACEHOLDER)
    # Taken from the answer the server already checked on this read; nothing else is read.
    assert server.descriptor_reads == []

    tab.ask("And what about the week before?")
    expect(tab.message("conv-old_assistant_2")).to_contain_text("Answer 1 from the stored result.")
    assert server.creates == []
    body = server.stream_bodies[-1]
    assert body["conversation_id"] == "conv-old"
    assert body["workflow_result_context"] == result_context("run-1", SHA_V1)


def test_reopening_a_chat_whose_answer_was_withheld_selects_nothing(tab, server):
    seed_conversation(server, "conv-old", masked=True)
    tab.open("/chat?conversationId=conv-old")
    answer = tab.message("conv-old_assistant_1")
    expect(answer).to_contain_text(masking.WORKFLOW_RESULT_UNAVAILABLE_MESSAGE)
    expect(answer).not_to_contain_text("Three items changed this week.")
    expect(tab.chip).to_have_count(0)
    expect(tab.composer).to_have_attribute("placeholder", DEFAULT_PLACEHOLDER)
    expect(tab.orchestrate).to_have_attribute("aria-pressed", "true")
    assert server.descriptor_reads == []


def test_turning_orchestration_on_gives_up_the_workflow_result(tab, server):
    select_run_1(tab)
    expect(tab.orchestrate).to_have_attribute("aria-pressed", "false")
    tab.orchestrate.click()
    expect(tab.chip).to_have_count(0)
    expect(tab.orchestrate).to_have_attribute("aria-pressed", "true")
    expect(tab.composer).to_have_attribute("placeholder", DEFAULT_PLACEHOLDER)
    assert_nothing_sent(server)


def test_a_workflow_name_is_shown_as_text(tab, server):
    server.workflow_name = XSS_NAME
    tab.open("/workspace/workflows")
    expect(tab.ask_in_chat).to_have_count(2)
    tab.ask_in_chat.first.click()
    expect(tab.chip).to_have_attribute("data-workflow-result-chip", "selected")
    expect(tab.chip_text).to_have_text(
        f"Answering from the {XSS_NAME} run of Mon, May 4, 9:02 AM — not re-running the workflow",
    )

    tab.ask("What did it find?")
    answer = tab.message("conv-new-1_assistant_1")
    expect(answer.locator("em")).to_have_text(
        f"This answer uses the stored result of the {XSS_NAME} run of Mon May 4, 2026, 9:02 AM CDT. "
        "The workflow was not re-run.",
    )
    expect(tab.page.locator('img[src="x"]')).to_have_count(0)
    assert tab.page.evaluate("() => window.__xss") is None
