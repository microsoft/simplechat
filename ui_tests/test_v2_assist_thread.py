# test_v2_assist_thread.py
"""
Browser tests for the shared AI-assist thread in the diagram and chart editors.
Version: 0.261.195
Implemented in: 0.261.195

This test ensures that a request sent from a diagram or chart editor's Ask AI tab joins the
thread and clears the input at once, can be cancelled, retried, or edited and resent, is refused
rather than cut when it is too long, and is never shown twice when the stored chat (including a
shared conversation's broadcast) arrives before the reply. It also checks that the editors'
restricted composer hides uploads, prompts and context while the main composer keeps them.

The real MessageList, MermaidDiagram, InlineChart, editors, chat store and assist thread run in
Chromium with the production CSS and the vendored diagram and chart libraries. Only HTTP is
stubbed: the assist endpoints emulate the server's stored chat, submission-id replay and
revision conflicts. The image and plan editors are covered in test_image_editor_capabilities.py,
test_v2_image_editor.py and test_v2_orchestration_plan_editor.py; the question card's composer
in test_v2_elicitation_composer.py.

Build the V2 SPA first: npm --prefix .\\application\\v2_ui run build
Run: python -m pytest .\\ui_tests\\test_v2_assist_thread.py -q
"""

import copy
import json
import mimetypes
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "single_app" / "static"
VENDOR = ROOT / "application" / "v2_ui" / "public" / "vendor"
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures" / "orchestration"))

import harness_build as hb  # noqa: E402
from playwright_connection import connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui
ORIGIN = "https://simplechat.test"
CONVERSATION = "assist-thread-chat"
SUBMISSION_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
PERSONAL_ASSIST = re.compile(r"^/api/message/([^/]+)/block-revision/assist$")
SHARED_ASSIST = re.compile(
    r"^/api/collaboration/conversations/([^/]+)/messages/([^/]+)/block-revision/assist$"
)
CANCELLED = "Cancelled. The change may still be applied if the server had already started it."
EARLIER_APPLIED = "Your earlier request finished after you cancelled it."
HINT = "Enter to send · Shift+Enter for a new line"

DIAGRAM_SOURCE = "flowchart TD\n    A[Draft] --> B[Review]"
CHART_SOURCE = json.dumps({
    "kind": "bar",
    "title": "Quarterly revenue",
    "data": {"labels": ["Q1", "Q2"], "datasets": [{"label": "Revenue", "data": [10, 20]}]},
})

EDITORS = {
    "diagram": {
        "message": "diagram-reply",
        "kind": "mermaid",
        "edit": "Edit this diagram",
        "dialog": "Editing flowchart TD",
        "log": "Changes to this diagram",
        "send": "Update diagram",
        "updated": "Updated the diagram.",
    },
    "chart": {
        "message": "chart-reply",
        "kind": "simplechart",
        "edit": "Edit this chart",
        "dialog": "Editing Quarterly revenue",
        "log": "Changes to this chart",
        "send": "Update chart",
        "updated": "Updated the chart.",
    },
}


def content_type(asset):
    # The Windows registry can map .js to text/plain, so the script types are fixed here.
    known = {".js": "application/javascript", ".css": "text/css"}
    return known.get(asset.suffix) or mimetypes.guess_type(asset.name)[0] or "application/octet-stream"


def conversation_messages():
    return [
        {
            "id": "question", "conversation_id": CONVERSATION, "role": "user",
            "content": "Show the review process and the quarterly revenue.",
            "timestamp": "2026-10-01T12:00:00Z",
        },
        {
            "id": "diagram-reply", "conversation_id": CONVERSATION, "role": "assistant",
            "content": f"Here is the process.\n\n```mermaid\n{DIAGRAM_SOURCE}\n```\n",
            "timestamp": "2026-10-01T12:00:01Z", "metadata": {},
        },
        {
            "id": "chart-reply", "conversation_id": CONVERSATION, "role": "assistant",
            "content": f"Here is the revenue.\n\n```simplechart\n{CHART_SOURCE}\n```\n",
            "timestamp": "2026-10-01T12:00:02Z", "metadata": {},
        },
    ]


def revise(kind, source, number):
    """A deterministic model edit that keeps the dialog's title stable."""
    if kind == "mermaid":
        return f"{source.rstrip()}\n    B --> S{number}[Step {number}]\n"
    spec = json.loads(source)
    dataset = spec["data"]["datasets"][0]
    dataset["data"] = [value + number for value in dataset["data"]]
    return json.dumps(spec)


class AssistApi:
    """The assist endpoints, storing each block's revisions and chat the way the server does."""

    def __init__(self, page):
        self.page = page
        self.block_revisions = {}
        self.requests = []
        self.held = []
        # None answers at once. "request" holds it before the server starts; "response" lets the
        # server finish and holds only the reply, as when a broadcast overtakes it.
        self.hold = None
        self.fail_next = None
        self.sequence = 0
        self.errors = []
        self.unexpected = []
        self.expected_http_failures = set()
        self.dropped_paths = set()

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET":
            if path == "/harness.html":
                route.fulfill(path=str(hb.HERE / "harness.html"), content_type="text/html")
                return
            if path == "/harness.bundle.js":
                route.fulfill(path=str(hb.BUNDLE), content_type="application/javascript")
                return
            if path.startswith("/vendor/"):
                # The vendored diagram and chart libraries, served as the SPA serves them.
                asset = (VENDOR / unquote(path.removeprefix("/vendor/"))).resolve()
                if asset.is_relative_to(VENDOR.resolve()) and asset.is_file():
                    route.fulfill(path=str(asset), content_type=content_type(asset))
                    return
            if path == "/api/user/settings":
                route.fulfill(json={"settings": {}})
                return
            if path in ("/api/documents/tags", "/api/group_documents/tags", "/api/public_workspace_documents/tags"):
                route.fulfill(json={"tags": []})
                return
            if path in ("/api/documents", "/api/group_documents", "/api/public_workspace_documents"):
                route.fulfill(json={"documents": [], "total_count": 0})
                return
            if path == "/api/v2/orchestration/runs":
                route.fulfill(json={"runs": []})
                return
            if path == "/favicon.ico":
                route.fulfill(status=204)
                return
        personal = PERSONAL_ASSIST.fullmatch(path)
        shared = SHARED_ASSIST.fullmatch(path)
        if request.method == "POST" and (personal or shared):
            body = request.post_data_json
            message_id = unquote(personal[1] if personal else shared[2])
            conversation = unquote(shared[1]) if shared else body.get("conversation_id")
            if conversation != CONVERSATION:
                self.unexpected.append(f"assist request for {conversation}")
            self.requests.append({"path": path, "message_id": message_id, "shared": bool(shared), "body": body})
            if self.fail_next:
                status, payload = self.fail_next
                self.fail_next = None
                self.respond(route, path, status, payload)
                return
            item = {"route": route, "path": path, "message_id": message_id, "body": body}
            if self.hold == "request":
                self.held.append(item)
                return
            item["status"], item["payload"] = self.apply(message_id, body)
            if self.hold == "response":
                self.held.append(item)
                return
            self.respond(route, path, item["status"], item["payload"])
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected fixture request."})

    def respond(self, route, path, status, payload):
        if status != 200:
            self.expected_http_failures.add((path, status))
        route.fulfill(status=status, json=payload)

    def stamp(self):
        self.sequence += 1
        return f"2026-10-01T12:{self.sequence // 60:02d}:{self.sequence % 60:02d}Z"

    def apply(self, message_id, body):
        """What the assist route does: replay a known id, refuse a stale count, or store an edit."""
        kind, index = body["block_kind"], str(body["block_index"])
        stored = self.block_revisions.setdefault(message_id, {})
        entry = stored.get(kind, {}).get(index)
        submission = body.get("submission_id")
        if entry and submission and any(turn.get("submission_id") == submission for turn in entry["chat"]):
            return 200, self.reply(message_id, entry, stored, replayed=True)
        expected = body.get("expected_revision_count")
        if expected is not None and expected != len(entry["revisions"] if entry else []):
            return 409, {
                "error": "This diagram was changed by someone else",
                "block_revisions": copy.deepcopy(stored),
            }
        if entry is None:
            entry = {
                "source_hash": body["source_hash"], "current": 0, "chat": [],
                "revisions": [{
                    "id": "original", "source": body["original_source"], "origin": "original",
                    "note": "", "timestamp": self.stamp(),
                }],
            }
            stored.setdefault(kind, {})[index] = entry
        number = len(entry["revisions"])
        source = revise(kind, entry["revisions"][entry["current"]]["source"], number)
        entry["revisions"].append({
            "id": f"revision-{number}", "source": source, "origin": "ai",
            "note": body["instruction"], "timestamp": self.stamp(),
        })
        entry["current"] = number
        for role, content in (("user", body["instruction"]), ("assistant", source)):
            turn = {"role": role, "content": content, "timestamp": self.stamp()}
            if submission:
                turn["submission_id"] = submission
            entry["chat"].append(turn)
        return 200, self.reply(message_id, entry, stored)

    @staticmethod
    def reply(message_id, entry, stored, replayed=False):
        payload = {
            "success": True,
            "message_id": message_id,
            "source": entry["revisions"][entry["current"]]["source"],
            "block_revisions": copy.deepcopy(stored),
        }
        if replayed:
            payload["replayed"] = True
        return payload

    def release(self):
        """Answer every held request, running the server's work for those it had not started."""
        held, self.held = self.held, []
        for item in held:
            if "status" not in item:
                item["status"], item["payload"] = self.apply(item["message_id"], item["body"])
            self.respond(item["route"], item["path"], item["status"], item["payload"])

    def finish_held_on_server(self):
        """The server finishes held requests after the page has stopped waiting for them."""
        held, self.held = self.held, []
        for item in held:
            if "status" not in item:
                self.apply(item["message_id"], item["body"])
            self.drop(item)

    def drop_held(self):
        """Held requests the server never started."""
        held, self.held = self.held, []
        for item in held:
            self.drop(item)

    def drop(self, item):
        self.dropped_paths.add(item["path"])
        try:
            item["route"].abort()
        except Exception:  # noqa: BLE001 - the page already cancelled this request.
            pass

    def broadcast(self, message_id):
        """What the collaboration stream's message_block_revised event does in the page."""
        self.page.evaluate(
            """({ messageId, blockRevisions }) => {
                window.OrchHarness.stores.chat.useChatStore.setState((state) => ({
                    messages: state.messages.map((message) => message.id === messageId
                        ? { ...message, metadata: { ...(message.metadata || {}), block_revisions: blockRevisions } }
                        : message),
                }));
            }""",
            {"messageId": message_id, "blockRevisions": copy.deepcopy(self.block_revisions.get(message_id, {}))},
        )

    def chat(self, name):
        editor = EDITORS[name]
        return self.block_revisions[editor["message"]][editor["kind"]]["0"]["chat"]

    def wait_for_requests(self, count, timeout=10):
        deadline = time.monotonic() + timeout
        while len(self.requests) < count:
            assert time.monotonic() < deadline, f"Expected {count} assist requests, saw {len(self.requests)}."
            self.page.wait_for_timeout(50)

    def record_console(self, message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        status = re.search(r"^Failed to load resource: the server responded with a status of (\d+)", message.text)
        if status and (path, int(status.group(1))) in self.expected_http_failures:
            return
        if "net::" in message.text and path in self.dropped_paths:
            return
        self.errors.append(message.text)


class Editor:
    """One editor dialog and its Ask AI tab."""

    def __init__(self, page, name):
        self.page = page
        self.spec = EDITORS[name]
        self.dialog = page.get_by_role("dialog", name=self.spec["dialog"])
        self.input = self.dialog.get_by_role("textbox", name="Describe the change you want")
        self.log = self.dialog.get_by_role("log", name=self.spec["log"])
        self.exchanges = self.log.get_by_test_id("assist-exchange")
        self.submit = self.dialog.locator('form button[type="submit"]')
        self.ask_tab = self.dialog.get_by_role("tab", name="Ask AI")

    def open(self):
        self.page.get_by_title(self.spec["edit"], exact=True).click(timeout=30_000)
        expect(self.dialog).to_be_visible()
        self.ask_tab.click()
        expect(self.input).to_be_enabled()
        return self

    def said(self, text):
        return self.log.get_by_text(text, exact=True)

    def send(self, text):
        self.input.fill(text)
        self.input.press("Enter")


def mount(api, *, shared=False, component="MessageList"):
    page = api.page
    page.goto(f"{ORIGIN}/harness.html")
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    styles = sorted((STATIC / "v2" / "assets").glob("*.css"))
    assert styles, "Build the V2 SPA before running these browser checks."
    for stylesheet in styles:
        page.add_style_tag(path=str(stylesheet))
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.195',
                user: { id: 'assist-tester', display_name: 'Assist Tester', roles: [] },
                features: { enable_user_workspace: true, enable_chat_file_uploads: true },
                settings: { max_file_size_mb: 25 },
                scope: { groups: [], public_workspaces: [] },
                catalogs: { models: [], agents: [], prompts: [
                    { id: 'summary-prompt', name: 'Summary', content: 'Summarize {{composer}}.', scope_type: 'personal' },
                ] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation,
                activeConversationKind: spec.shared ? 'collaborative' : 'personal',
                messagesLoading: false, messagesError: null, streaming: false,
                streamingContent: '', streamError: null, thoughts: [],
                conversations: [{ id: spec.conversation, title: 'Assist thread' }],
                messages: spec.messages,
            });
            const layout = document.getElementById('mount-a');
            layout.style.height = '100dvh';
            layout.style.display = 'flex';
            layout.style.flexDirection = 'column';
            H.mount('mount-a', spec.component, {}, { strictMode: true });
        }""",
        {"conversation": CONVERSATION, "shared": shared, "component": component, "messages": conversation_messages()},
    )


@pytest.fixture
def assist(page):
    hb.ensure_bundle()
    api = AssistApi(page)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    page.on("console", api.record_console)
    try:
        yield api
        assert not api.errors, f"Unexpected browser errors: {api.errors}"
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
    finally:
        api.drop_held()


@pytest.mark.parametrize("name", ["diagram", "chart"])
def test_a_sent_request_joins_the_thread_at_once_and_the_answer_fills_it_in(assist, name):
    api = assist
    mount(api)
    editor = Editor(api.page, name).open()
    expect(editor.log).to_have_attribute("aria-live", "polite")
    api.hold = "request"
    editor.send("Add a review step")

    # Nothing has been answered yet, so all of this happened without the server.
    expect(editor.input).to_have_value("")
    expect(editor.exchanges).to_have_count(1)
    pending = editor.exchanges.first
    expect(pending).to_have_attribute("data-status", "pending")
    expect(pending).to_contain_text("Add a review step")
    expect(pending).to_contain_text("Working…")
    expect(pending.get_by_test_id("assist-elapsed")).to_have_text(re.compile(r"^\d+ s$"))
    expect(pending.get_by_role("button", name="Cancel this request")).to_be_enabled()
    expect(editor.submit).to_have_text("Updating…")
    expect(editor.submit).to_be_disabled()
    api.wait_for_requests(1)
    sent = api.requests[0]
    assert not sent["shared"]
    assert sent["body"]["instruction"] == "Add a review step"
    assert sent["body"]["block_kind"] == EDITORS[name]["kind"]
    assert SUBMISSION_ID.fullmatch(sent["body"]["submission_id"])

    # Typing on while it works is kept, and is not sent with it.
    editor.input.fill("Next idea")
    api.release()
    expect(editor.exchanges).to_have_count(0)
    expect(editor.said("Add a review step")).to_have_count(1)
    expect(editor.said(EDITORS[name]["updated"])).to_have_count(1)
    expect(editor.ask_tab).to_have_attribute("aria-selected", "true")
    expect(editor.submit).to_have_text(EDITORS[name]["send"])
    expect(editor.input).to_have_value("Next idea")
    assert [turn["submission_id"] for turn in api.chat(name)] == [sent["body"]["submission_id"]] * 2


@pytest.mark.parametrize("name", ["diagram", "chart"])
def test_cancel_then_retry_resends_under_the_same_submission_id(assist, name):
    api = assist
    mount(api)
    editor = Editor(api.page, name).open()
    api.hold = "request"
    editor.input.fill("Use a darker palette")
    editor.submit.click()
    api.wait_for_requests(1)
    first = api.requests[0]["body"]["submission_id"]

    editor.exchanges.first.get_by_role("button", name="Cancel this request").click()
    cancelled = editor.exchanges.first
    expect(cancelled).to_have_attribute("data-status", "cancelled")
    expect(cancelled).to_contain_text(CANCELLED)
    expect(cancelled.get_by_role("button", name="Edit and resend")).to_be_enabled()
    expect(editor.submit).to_have_text(EDITORS[name]["send"])
    expect(editor.input).to_have_value("")
    api.drop_held()

    api.hold = None
    cancelled.get_by_role("button", name="Retry").click()
    api.wait_for_requests(2)
    assert api.requests[1]["body"]["submission_id"] == first
    expect(editor.exchanges).to_have_count(0)
    expect(editor.said("Use a darker palette")).to_have_count(1)
    expect(editor.said(EDITORS[name]["updated"])).to_have_count(1)


def test_a_failure_offers_retry_and_edit_and_resend_and_shows_the_error_as_text(assist):
    api = assist
    mount(api)
    editor = Editor(api.page, "chart").open()
    markup = 'The model returned an unusable chart: <img src=x onerror="window.__assistXss=1">'
    api.fail_next = (502, {"error": markup})
    editor.send("Stack the bars")
    failed = editor.exchanges.first
    expect(failed).to_have_attribute("data-status", "failed")
    expect(failed.get_by_role("alert")).to_have_text(markup)
    expect(editor.log.locator("img")).to_have_count(0)
    assert api.page.evaluate("() => window.__assistXss === undefined")
    expect(editor.input).to_have_value("")

    failed.get_by_role("button", name="Retry").click()
    api.wait_for_requests(2)
    assert api.requests[1]["body"]["submission_id"] == api.requests[0]["body"]["submission_id"]
    expect(editor.exchanges).to_have_count(0)
    expect(editor.said("Stack the bars")).to_have_count(1)

    api.fail_next = (502, {"error": "The model is busy. Try again."})
    editor.send("Label each bar")
    expect(editor.exchanges.first.get_by_role("alert")).to_have_text("The model is busy. Try again.")
    editor.exchanges.first.get_by_role("button", name="Edit and resend").click()
    expect(editor.exchanges).to_have_count(0)
    expect(editor.input).to_have_value("Label each bar")
    expect(editor.input).to_be_focused()
    editor.send("Label each bar with its value")
    api.wait_for_requests(4)
    assert api.requests[3]["body"]["instruction"] == "Label each bar with its value"
    assert api.requests[3]["body"]["submission_id"] != api.requests[2]["body"]["submission_id"]
    expect(editor.said("Label each bar with its value")).to_have_count(1)
    expect(editor.said("Label each bar")).to_have_count(0)
    expect(editor.exchanges).to_have_count(0)


def test_enter_sends_shift_enter_adds_a_line_and_an_overlong_request_is_refused(assist):
    api = assist
    mount(api)
    editor = Editor(api.page, "diagram").open()
    counter = editor.dialog.get_by_text(re.compile(r"^\d+/2000 · "))
    expect(counter).to_have_text(f"0/2000 · {HINT}")
    editor.input.press_sequentially("First line")
    editor.input.press("Shift+Enter")
    editor.input.press_sequentially("Second line")
    expect(editor.input).to_have_value("First line\nSecond line")
    expect(counter).to_have_text(f"22/2000 · {HINT}")
    assert not api.requests

    too_long = "x" * 2001
    editor.input.fill(too_long)
    expect(editor.input).to_have_attribute("aria-invalid", "true")
    expect(editor.dialog.get_by_text("This is 1 character over the limit. Shorten it to send.")).to_be_visible()
    expect(counter).to_have_text(f"2001/2000 · {HINT}")
    expect(editor.submit).to_be_disabled()
    editor.input.press("Enter")
    editor.input.press("Control+Enter")
    api.page.wait_for_timeout(300)
    assert not api.requests
    expect(editor.exchanges).to_have_count(0)
    # Refused, not cut down to fit.
    expect(editor.input).to_have_value(too_long)

    editor.input.fill("Group the reviewers")
    expect(editor.input).not_to_have_attribute("aria-invalid", "true")
    editor.input.press("Control+Enter")
    api.wait_for_requests(1)
    assert api.requests[0]["body"]["instruction"] == "Group the reviewers"
    expect(editor.said("Group the reviewers")).to_have_count(1)
    expect(editor.input).to_have_value("")


@pytest.mark.parametrize("name", ["diagram", "chart"])
def test_a_shared_chat_broadcast_before_the_reply_is_not_shown_twice(assist, name):
    api = assist
    mount(api, shared=True)
    editor = Editor(api.page, name).open()
    api.hold = "response"
    editor.send("Highlight the approval step")
    api.wait_for_requests(1)
    sent = api.requests[0]
    assert sent["shared"]
    assert "conversation_id" not in sent["body"]
    submission = sent["body"]["submission_id"]
    expect(editor.exchanges).to_have_count(1)

    # The collaboration stream delivers the stored chat before this page's own reply returns.
    api.broadcast(EDITORS[name]["message"])
    expect(editor.said(EDITORS[name]["updated"])).to_have_count(1)
    expect(editor.said("Highlight the approval step")).to_have_count(1)
    expect(editor.exchanges).to_have_count(0)
    expect(editor.submit).to_have_text("Updating…")

    api.release()
    expect(editor.submit).to_have_text(EDITORS[name]["send"])
    expect(editor.said("Highlight the approval step")).to_have_count(1)
    expect(editor.said(EDITORS[name]["updated"])).to_have_count(1)
    expect(editor.exchanges).to_have_count(0)
    assert [turn["submission_id"] for turn in api.chat(name)] == [submission] * 2


def test_a_cancelled_request_the_server_finished_is_recognised_on_the_next_send(assist):
    api = assist
    mount(api)
    editor = Editor(api.page, "diagram").open()
    editor.send("Add a start node")
    expect(editor.said("Add a start node")).to_have_count(1)
    expect(editor.exchanges).to_have_count(0)

    api.hold = "request"
    editor.send("Make it left to right")
    api.wait_for_requests(2)
    editor.exchanges.first.get_by_role("button", name="Cancel this request").click()
    expect(editor.exchanges.first).to_have_attribute("data-status", "cancelled")
    api.hold = None
    api.finish_held_on_server()

    editor.send("Add a legend")
    api.wait_for_requests(3)
    assert api.requests[2]["body"]["expected_revision_count"] == 2
    notice = editor.dialog.get_by_role("status").filter(has_text=EARLIER_APPLIED)
    expect(notice).to_be_visible()
    expect(editor.input).to_have_value("Add a legend")
    expect(editor.exchanges).to_have_count(0)
    expect(editor.said("Make it left to right")).to_have_count(1)
    expect(editor.said("Add a legend")).to_have_count(0)

    editor.input.press("Enter")
    api.wait_for_requests(4)
    assert api.requests[3]["body"]["expected_revision_count"] == 3
    expect(editor.said("Add a legend")).to_have_count(1)
    expect(notice).to_have_count(0)
    expect(editor.said(EDITORS["diagram"]["updated"])).to_have_count(3)


def test_the_editor_composer_is_restricted_while_the_main_composer_keeps_its_tools(assist):
    api = assist
    mount(api, component="PromptExperience")
    page = api.page
    main = page.get_by_role("textbox", name="Message", exact=True)
    expect(page.get_by_role("button", name="Attach a file")).to_have_count(1)
    main.fill("/Summ")
    expect(page.get_by_role("listbox", name="Prompt suggestions")).to_be_visible()
    main.fill("")
    expect(page.get_by_role("listbox", name="Prompt suggestions")).to_have_count(0)

    editor = Editor(page, "diagram").open()
    expect(editor.dialog.get_by_role("button", name="Attach a file")).to_have_count(0)
    expect(editor.dialog.get_by_role("button", name="Add context")).to_have_count(0)
    expect(editor.dialog.locator('input[type="file"]')).to_have_count(0)
    editor.input.fill("/Summ")
    page.wait_for_timeout(200)
    expect(page.get_by_role("listbox", name="Prompt suggestions")).to_have_count(0)
    editor.input.fill("#report")
    page.wait_for_timeout(200)
    expect(page.get_by_role("listbox", name="Context suggestions")).to_have_count(0)
    editor.input.press("Enter")
    api.wait_for_requests(1)
    assert api.requests[0]["body"]["instruction"] == "#report"
    expect(editor.said("#report")).to_have_count(1)
