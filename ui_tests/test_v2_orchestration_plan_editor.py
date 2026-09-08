# test_v2_orchestration_plan_editor.py
"""
Focused real-component browser tests for conversational orchestration plan editing.
Version: 0.261.102
Implemented in: 0.261.102

Only HTTP boundaries are mocked. The real store, shared SSE reader, controller,
MessageList, Review drawer, editor, and elicitation inputs run in Chromium with
production CSS. Backend validation/concurrency has separate functional coverage.
Missing tools or built assets fail; no browser check is silently skipped.

Local Chromium is the default. The shared connect_options fixture supports Azure
Playwright using azure-mgmt-playwright and DefaultAzureCredential without creating
resources or persisting credentials.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_orchestration_plan_editor.py -q
"""

import copy
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "ui_tests" / "fixtures"
BUILD = REPO_ROOT / "ui_tests" / "artifacts" / "orchestration-plan-editor"
sys.path.insert(0, str(FIXTURES))
sys.path.insert(0, str(FIXTURES / "orchestration"))

# These shared helpers live outside the test module's import directory.
import harness_build as hb  # noqa: E402
from playwright_connection import connect_options  # noqa: E402, F401


pytestmark = pytest.mark.ui
ORIGIN = "https://simplechat.test"
HARNESS = f"/{hb.HARNESS_HTML_REL}"
RUNS = "/api/v2/orchestration/runs"
RUN = "/api/v2/orchestration/run"


def make_plan(conversation="editor-chat", turn="editor-turn", mode="manual", revision=0):
    return {
        "plan_id": f"{conversation}-plan-{revision}",
        "run_id": f"{conversation}-run-{revision}",
        "turn_id": turn,
        "conversation_id": conversation,
        "revision": revision,
        "user_id": "editor-tester",
        "intent": {"summary": f"Compare quarterly reports for {conversation}", "complexity": "complex"},
        "inputs": {"documents": [
            {"document_id": "doc-a", "display_name": "Report A", "selected_by_user": True},
            {"document_id": "doc-b", "display_name": "Report B", "selected_by_user": True},
        ], "web": False},
        "steps": [
            {"step_id": "read", "capability_id": "search_documents", "title": "Read quarterly reports",
             "arguments": {"document_ids": ["doc-a", "doc-b"]}, "phase": "knowledge",
             "estimated_cost": "low", "enabled": True, "status": "pending"},
            {"step_id": "research", "capability_id": "deep_research", "title": "Investigate context",
             "arguments": {}, "phase": "knowledge", "estimated_cost": "medium",
             "enabled": True, "status": "pending"},
            {"step_id": "answer", "capability_id": "respond", "title": "Write the comparison",
             "arguments": {}, "phase": "reasoning", "estimated_cost": "low",
             "enabled": True, "status": "pending"},
        ],
        "approval": {"mode": mode, "timeout_seconds": 1, "state": "pending"},
        "status": "awaiting_approval",
    }


def empty_edits():
    return {"disabled_step_ids": [], "removed_document_ids": {}}


class EditorApi:
    """A deterministic planner boundary, with explicit response-loss and race gates."""

    def __init__(self, assets):
        self.assets = assets
        self.editors = {}
        self.records = {}
        self.requests = []
        self.unexpected = []
        self.expected_errors = set()
        self.submissions = {}
        self.waiting = []
        self.next_revision = "success"
        self.hold_response = "success"
        self.delay_preview = False
        self.run_conflict = None
        self.successful_runs = []
        self.sequence = 0

    def add(self, conversation="editor-chat", turn="editor-turn", mode="manual"):
        plan = make_plan(conversation, turn, mode)
        editor = {
            "plan": plan, "version": "", "edits": empty_edits(), "chat": [],
            "history": [self.history(plan, "original", "As planned")],
            "next_before_revision": None, "pending": None, "busy": False,
        }
        self.editors[conversation] = editor
        self.records[plan["run_id"]] = copy.deepcopy(plan)
        return plan

    @staticmethod
    def history(plan, origin, note):
        return {
            "run_id": plan["run_id"], "plan_id": plan["plan_id"], "revision": plan["revision"],
            "created_at": f"2026-09-07T15:00:{plan['revision']:02d}Z", "origin": origin, "note": note,
        }

    def touch(self, editor):
        self.sequence += 1
        editor["version"] = f"saved-{self.sequence}"
        editor["plan"]["edit_version"] = editor["version"]
        editor["plan"]["approval"] = {"mode": "manual", "timeout_seconds": 0, "state": "pending"}
        self.records[editor["plan"]["run_id"]] = copy.deepcopy(editor["plan"])

    def projection(self, editor, before=None):
        result = copy.deepcopy(editor)
        history = [entry for entry in result["history"] if before is None or entry["revision"] < before]
        result["history"] = history[:2]
        result["next_before_revision"] = history[1]["revision"] if len(history) > 2 else None
        return result

    def publish(self, editor, instruction="Focus on pricing", source=None):
        old = copy.deepcopy(editor["plan"])
        plan = copy.deepcopy(source or old)
        edits = editor["edits"] if source is None else empty_edits()
        plan["steps"] = [step for step in plan["steps"] if step["step_id"] not in edits["disabled_step_ids"]]
        for step in plan["steps"]:
            if "document_ids" in step["arguments"]:
                removed = edits["removed_document_ids"].get(step["step_id"], [])
                step["arguments"]["document_ids"] = [
                    value for value in step["arguments"]["document_ids"] if value not in removed
                ]
        if source is None:
            if "add" in instruction.lower():
                plan["steps"].insert(-1, {
                    "step_id": f"web-{old['revision'] + 1}", "capability_id": "web_search",
                    "title": "Search the web", "arguments": {"query": instruction},
                    "phase": "knowledge", "enabled": True, "estimated_cost": "low", "status": "pending",
                })
            if "remove" in instruction.lower():
                plan["steps"] = [step for step in plan["steps"] if step["capability_id"] != "web_search"]
            plan["intent"]["summary"] = f"Revised: {instruction}"
        plan["revision"] = old["revision"] + 1
        plan["run_id"] = f"{old['conversation_id']}-run-{plan['revision']}"
        plan["plan_id"] = f"{old['conversation_id']}-plan-{plan['revision']}"
        plan["status"] = "awaiting_approval"
        self.records[old["run_id"]]["status"] = "superseded"
        editor["plan"] = plan
        editor["edits"] = empty_edits()
        editor["pending"] = None
        editor["busy"] = False
        note = f"Restored revision {source['revision']}." if source else instruction
        editor["history"].insert(0, self.history(plan, "restore" if source else "ai", note))
        self.touch(editor)

    def error(self, route, status, message, code, current=None):
        self.expected_errors.add((urlsplit(route.request.url).path, status))
        payload = {"error": message, "code": code}
        if current:
            payload["current_run_id"] = current
        route.fulfill(status=status, json=payload)

    @staticmethod
    def stream(route, event):
        route.fulfill(
            content_type="text/event-stream",
            body='data: {"type":"thought","content":"Editor-only planner progress"}\n\n'
            + f"data: {json.dumps(event)}\n\n",
        )

    def result(self, editor):
        pending = editor["pending"]
        return {
            "type": "orchestration_elicitation" if pending else "orchestration_plan",
            "elicitation" if pending else "plan": copy.deepcopy(pending or editor["plan"]),
            "editor": self.projection(editor), "done": True,
        }

    def revise(self, route, editor, body, behavior):
        submission = body["submission_id"]
        if submission in self.submissions:
            saved_body, event = self.submissions[submission]
            assert saved_body == body, "An idempotency token must not identify changed input."
            self.stream(route, event)
            return
        if body["expected_version"] != editor["version"]:
            self.error(route, 409, "The plan changed. Review its current saved revision.",
                       "plan_changed", editor["plan"]["run_id"])
            return
        assert "plan" not in body and "elicitation" not in body, "Only server-owned identities may be submitted."
        if behavior == "error":
            self.error(route, 503, "Planner unavailable. Your last saved plan is unchanged.", "unavailable")
            return
        if behavior in ("invalid", "foreign"):
            event = {"type": "orchestration_plan", "plan": make_plan("unrelated"), "done": True}
            if behavior == "foreign":
                event["editor"] = {**self.projection(editor), "plan": make_plan("unrelated")}
            self.stream(route, event)
            return
        action = body["action"]
        if "edits" in body:
            editor["edits"] = copy.deepcopy(body["edits"])
        if action == "ask":
            instruction = body["instruction"]
            editor["chat"].append({"role": "user", "content": instruction, "timestamp": "2026-09-07T15:00:00Z"})
            if behavior == "question":
                editor["pending"] = {
                    "elicitation_id": f"question-{self.sequence}", "contract_version": 1,
                    "run_id": editor["plan"]["run_id"], "turn_id": editor["plan"]["turn_id"],
                    "revision": editor["plan"]["revision"] + 1, "message": "Which focus should the revised plan use?",
                    "requested_schema": {"type": "object", "properties": {
                        "focus": {"type": "string", "title": "Plan focus", "enum": ["Pricing", "Delivery"]},
                    }, "required": ["focus"]},
                    "ui_hints": {"order": ["focus"], "pages": [["focus"]]},
                }
                self.touch(editor)
            elif behavior == "explain":
                editor["chat"].append({
                    "role": "assistant", "content": f"Kept the saved plan. Your request was: {instruction}",
                    "timestamp": "2026-09-07T15:00:01Z",
                })
                self.touch(editor)
            else:
                self.publish(editor, instruction)
        elif action == "restore":
            self.publish(editor, source=self.records[body["source_run_id"]])
        elif action == "answer":
            assert body["elicitation_id"] == editor["pending"]["elicitation_id"]
            assert body["elicitation_revision"] == editor["pending"]["revision"]
            response = body["elicitation_response"]
            self.publish(editor, f"Focus on {response['content'].get('focus', 'the original request')}")
        elif action == "discard":
            if editor["pending"]:
                assert body["elicitation_id"] == editor["pending"]["elicitation_id"]
                assert body["elicitation_revision"] == editor["pending"]["revision"]
            editor["pending"] = None
            editor["busy"] = False
            self.touch(editor)
        if behavior != "question" and behavior != "explain":
            editor["chat"].append({
                "role": "assistant",
                "content": "Kept the current plan." if action == "discard" else editor["history"][0]["note"],
                "timestamp": "2026-09-07T15:00:02Z",
            })
        event = self.result(editor)
        self.submissions[submission] = (copy.deepcopy(body), event)
        if behavior == "lost":
            self.expected_errors.add((urlsplit(route.request.url).path, "net::ERR_FAILED"))
            route.abort("failed")
        else:
            self.stream(route, event)

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        body = request.post_data_json if request.method == "POST" else {}
        self.requests.append({"path": path, "method": request.method, "body": body, "query": parsed.query})
        if path == RUN:
            editor = self.editors[body["conversation_id"]]
            code = self.run_conflict
            if editor["busy"] or editor["pending"]:
                code = "edit_in_progress"
            elif editor["version"] and body.get("expected_version") != editor["version"]:
                code = "plan_changed"
            if code:
                self.error(route, 409, f"Approval refused: {code}. Refresh the saved plan.",
                           code, editor["plan"]["run_id"])
                return
            assert body["run_id"] == editor["plan"]["run_id"]
            self.successful_runs.append(copy.deepcopy(body))
            editor["plan"]["status"] = "completed"
            self.stream(route, {
                "done": True, "message_id": "saved-answer", "content": f"Ran: {editor['plan']['intent']['summary']}",
            })
            return
        if path == "/api/v2/orchestration/plan":
            plan = self.add(body["conversation_id"], body["turn_id"], body["approval_mode"])
            if body["approval_mode"] == "auto":
                plan["approval"]["state"] = "approved"
                plan["status"] = "approved"
            self.stream(route, {"type": "orchestration_plan", "plan": plan, "done": True})
            return
        if path == RUNS:
            conversation = parse_qs(parsed.query)["conversation_id"][0]
            runs = [{
                "run_id": plan["run_id"], "turn_id": plan["turn_id"], "status": plan["status"],
                "user_message_id": f"user-{conversation}", "user_message": "Compare quarterly reports.",
                "created_at": f"2026-09-07T15:00:{plan['revision']:02d}Z",
                "plan_summary": {
                    "plan_id": plan["plan_id"], "turn_id": plan["turn_id"], "status": plan["status"],
                    "intent_summary": plan["intent"]["summary"], "step_count": len(plan["steps"]),
                },
            } for plan in self.records.values() if plan["conversation_id"] == conversation]
            route.fulfill(json={"runs": runs})
            return
        match = re.fullmatch(re.escape(RUNS) + r"/([^/]+)(?:/(edit|editor|revisions|steps))?", path)
        if match:
            run_id, operation = unquote(match[1]), match[2]
            record = self.records[run_id]
            conversation = body.get("conversation_id") or parse_qs(parsed.query)["conversation_id"][0]
            assert record["conversation_id"] == conversation
            editor = self.editors[conversation]
            if operation == "edit":
                if self.hold_response == "delay":
                    self.waiting.append(lambda: self.fulfill_hold(route, editor, body))
                    return
                if self.hold_response == "error":
                    self.hold_response = "success"
                    self.error(route, 503, "The manual hold could not be saved.", "unavailable")
                    return
                self.fulfill_hold(route, editor, body)
            elif operation == "editor":
                before = parse_qs(parsed.query).get("before_revision", [None])[0]
                route.fulfill(json={"editor": self.projection(editor, int(before) if before is not None else None)})
            elif operation == "revisions":
                behavior, self.next_revision = self.next_revision, "success"
                if behavior == "delay":
                    editor["busy"] = True
                    if "edits" in body:
                        editor["edits"] = copy.deepcopy(body["edits"])
                    self.waiting.append(lambda: self.revise(route, editor, body, "success"))
                else:
                    self.revise(route, editor, body, behavior)
            elif operation == "steps":
                route.fulfill(json={"steps": []})
            elif self.delay_preview:
                self.waiting.append(lambda: route.fulfill(json={"run": {"plan": record}}))
            else:
                route.fulfill(json={"run": {"plan": record}})
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})

    def fulfill_hold(self, route, editor, body):
        if not editor["version"]:
            editor["edits"] = copy.deepcopy(body.get("edits", empty_edits()))
            self.touch(editor)
        route.fulfill(json={"editor": self.projection(editor)})

    def release(self):
        waiting, self.waiting = self.waiting, []
        for callback in waiting:
            callback()

    def calls(self, suffix):
        return [request for request in self.requests if request["path"].endswith(suffix)]


@pytest.fixture(scope="module")
def editor_assets():
    bundle = hb.ensure_bundle()
    index = BUILD / "index.html"
    assert index.is_file(), "Build the V2 UI into ui_tests/artifacts/orchestration-plan-editor first."
    urls = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', index.read_text("utf-8"))
    assert urls, "Production styles, not approximated harness CSS, are required."
    return {
        HARNESS: hb.HERE / "harness.html",
        "/ui_tests/fixtures/orchestration/harness.bundle.js": bundle,
        **{url: BUILD / "assets" / url.rsplit("/", 1)[-1] for url in urls},
    }


@pytest.fixture(scope="module")
def editor_browser(connect_options):
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect(**connect_options) if connect_options else playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def editor_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = EditorApi(editor_assets)
    errors = []
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: errors.append(str(error)))

    def console_error(message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        if any(path == expected_path and str(status) in message.text for expected_path, status in api.expected_errors):
            return
        errors.append(message.text)

    page.on("console", console_error)
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not errors, f"Unexpected browser errors: {errors}"


def mount(page, api, conversation="editor-chat", turn="editor-turn", *, mode="manual", resume=False, reset=True):
    plan = api.editors.get(conversation, {}).get("plan") or api.add(conversation, turn, mode)
    if page.url != ORIGIN + HARNESS:
        page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            if (spec.reset) H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.102', settings: {}, branding: { app_title: 'SimpleChat' },
                features: { enable_chat_orchestration: true },
                user: { id: 'editor-tester', display_name: 'Editor Tester' },
                scope: { groups: [], public_workspaces: [] },
                orchestration: { enabled: true, allow_user_approval_override: false, capabilities: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: 'personal',
                messagesLoading: false, messagesError: null, streaming: false,
                streamingContent: '', streamError: null, thoughts: [],
                conversations: [{ id: spec.conversation, title: 'Quarterly comparison' }],
                messages: [{ id: 'user-' + spec.conversation, role: 'user',
                    content: 'Compare quarterly reports.', metadata: { orchestration_turn_id: spec.turn } }],
            });
            const store = H.stores.orchestration.useOrchestrationStore.getState();
            if (!spec.resume) {
                if (!H.stores.orchestration.selectPlan(store, spec.conversation, spec.turn)) {
                    store.setPlan(spec.conversation, spec.turn, spec.plan);
                }
                store.setActiveTurn(spec.conversation, spec.turn);
            }
            H.mount('mount-a', 'PlanEditorExperience', {}, { strictMode: true });
        }""",
        {"conversation": conversation, "turn": turn, "plan": plan, "resume": resume, "reset": reset},
    )
    if resume:
        page.evaluate("(conversation) => window.OrchHarness.resume.resumeOrchestrationForConversation(conversation)",
                      conversation)
    expect(page.get_by_role("button", name="Edit the plan", exact=True).first).to_be_visible()


def open_editor(page):
    page.get_by_role("button", name="Edit the plan", exact=True).first.click()
    dialog = page.get_by_role("dialog", name="Edit orchestration plan")
    expect(dialog).to_be_visible()
    return dialog


def ask(page, instruction):
    dialog = page.get_by_role("dialog", name="Edit orchestration plan")
    dialog.get_by_role("tab", name="Ask planner", exact=True).click()
    dialog.get_by_role("textbox", name="Ask planner", exact=True).fill(instruction)
    dialog.get_by_role("button", name="Send planner request").click()


def state(page, conversation="editor-chat", turn="editor-turn"):
    return page.evaluate(
        """({conversation, turn}) => {
            const H = window.OrchHarness, store = H.stores.orchestration.useOrchestrationStore.getState();
            return {
                plan: H.stores.orchestration.selectPlan(store, conversation, turn),
                editor: H.stores.orchestration.selectPlanEditor(store, conversation, turn),
                edits: H.stores.orchestration.selectEdits(store, conversation, turn),
                history: store.history[conversation] || [],
                mainQuestions: Object.keys(store.elicitations),
                active: store.activeTurns[conversation],
                messages: H.stores.chat.useChatStore.getState().messages,
                thoughts: H.stores.chat.useChatStore.getState().thoughts,
                streamError: H.stores.chat.useChatStore.getState().streamError,
            };
        }""", {"conversation": conversation, "turn": turn},
    )


def wait_revision(page, revision, conversation="editor-chat", turn="editor-turn"):
    page.wait_for_function(
        """(spec) => window.OrchHarness.stores.orchestration.selectPlan(
            window.OrchHarness.stores.orchestration.useOrchestrationStore.getState(),
            spec.conversation, spec.turn)?.revision === spec.revision""",
        arg={"conversation": conversation, "turn": turn, "revision": revision},
    )


def test_review_entry_preserves_narrowing_and_stable_modal(editor_ui):
    page, api = editor_ui
    mount(page, api)
    page.get_by_role("button", name="Review the plan in the drawer").click()
    review = page.get_by_role("complementary", name="Review drawer")
    review.get_by_role("button", name="Remove document doc-a from this step").click()
    review.locator("ol > li").filter(has_text="Investigate context").locator("label").click()
    review.get_by_role("button", name="Edit the plan", exact=True).click()
    dialog = page.get_by_role("dialog", name="Edit orchestration plan")
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    assert api.calls("/edit")[0]["body"]["edits"] == {
        "disabled_step_ids": ["research"], "removed_document_ids": {"read": ["doc-a"]},
    }
    assert state(page)["edits"] == api.editors["editor-chat"]["edits"]
    expect(dialog.get_by_text("Report A", exact=True)).to_have_count(0)
    page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.setState(
        (value) => ({ messages: value.messages.map(message => ({ ...message })) }))""")
    expect(dialog).to_be_visible()
    assert len(state(page)["messages"]) == 1
    ask(page, "Add web search before the comparison")
    wait_revision(page, 1)
    effective = state(page)
    assert effective["edits"] == empty_edits()
    assert "research" not in [step["step_id"] for step in effective["plan"]["steps"]]
    assert effective["plan"]["steps"][0]["arguments"]["document_ids"] == ["doc-b"]


def test_add_remove_restore_refine_and_run_only_latest_saved_version(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    ask(page, "Add web search before the comparison")
    wait_revision(page, 1)
    expect(dialog.get_by_text("Search the web", exact=True)).to_be_visible()
    ask(page, "Remove web search and focus on pricing")
    wait_revision(page, 2)
    expect(dialog.get_by_text("Search the web", exact=True)).to_have_count(0)
    snapshot = state(page)
    assert len(snapshot["messages"]) == 1 and not snapshot["thoughts"]
    current_run = snapshot["plan"]["run_id"]
    dialog.get_by_role("tab", name="History", exact=True).click()
    dialog.get_by_role("button", name="Load earlier revisions").click()
    dialog.get_by_role("button", name="Preview revision 0", exact=True).click()
    expect(dialog.get_by_text("History preview — revision 0", exact=True)).to_be_visible()
    assert state(page)["plan"]["run_id"] == current_run
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_disabled()
    dialog.get_by_role("button", name="Restore revision 0", exact=True).click()
    wait_revision(page, 3)
    assert api.calls("/revisions")[-1]["body"]["source_run_id"].endswith("-run-0")
    assert state(page)["plan"]["run_id"].endswith("-run-3")
    ask(page, "Focus the comparison on delivery")
    wait_revision(page, 4)
    latest = state(page)["plan"]
    dialog.get_by_role("button", name="Run saved revision").click()
    expect(dialog).to_have_count(0)
    page.wait_for_function("() => window.OrchHarness.stores.chat.useChatStore.getState().messages.length === 2")
    assert api.successful_runs[0]["run_id"] == latest["run_id"]
    assert api.successful_runs[0]["expected_version"] == latest["edit_version"]
    assert len(state(page)["messages"]) == 2
    expect(page.get_by_text("Ran: Revised: Focus the comparison on delivery", exact=True)).to_be_visible()


def test_open_stops_countdown_before_hold_response_and_survives_close_reload(editor_ui):
    page, api = editor_ui
    page.clock.install()
    api.hold_response = "delay"
    mount(page, api, mode="timed")
    dialog = open_editor(page)
    page.clock.fast_forward(10000)
    assert not api.calls(RUN)
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_disabled()
    dialog.get_by_role("button", name="Close the plan editor").click()
    api.release()
    expect(page.get_by_role("button", name="Run the saved plan")).to_be_enabled()
    page.clock.fast_forward(10000)
    assert not api.calls(RUN)
    api.hold_response = "success"
    page.reload()
    mount(page, api, resume=True)
    expect(page.get_by_role("timer")).to_have_count(0)
    expect(page.get_by_role("button", name="Run the saved plan")).to_be_enabled()
    assert api.calls("/editor") and not api.calls(RUN)
    dialog = open_editor(page)
    dialog.get_by_role("button", name="Close the plan editor").click()
    assert not api.calls(RUN)
    page.get_by_role("button", name="Run the saved plan").click()
    expect(page.get_by_role("button", name="Run the saved plan")).to_have_count(0)
    assert len(api.successful_runs) == 1


@pytest.mark.parametrize("failure", ["error", "lost"])
def test_failed_or_lost_response_keeps_instruction_and_idempotent_retry(editor_ui, failure):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    api.next_revision = failure
    ask(page, "Add web search before the comparison")
    expect(dialog.get_by_role("alert")).to_be_visible()
    expect(dialog.get_by_role("textbox", name="Ask planner", exact=True)).to_have_value("Add web search before the comparison")
    assert state(page)["plan"]["revision"] == 0
    assert len(state(page)["messages"]) == 1
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    if failure == "error":
        dialog.get_by_role("button", name="Close the plan editor").click()
        dialog = open_editor(page)
        expect(dialog.get_by_role("alert")).to_have_text("Planner unavailable. Your last saved plan is unchanged.")
        expect(dialog.get_by_role("textbox", name="Ask planner")).to_have_value("Add web search before the comparison")
    dialog.get_by_role("button", name="Send planner request").click()
    wait_revision(page, 1)
    calls = api.calls("/revisions")
    assert len(calls) == 2 and calls[0]["body"] == calls[1]["body"]
    assert api.editors["editor-chat"]["plan"]["revision"] == 1
    assert len(state(page)["messages"]) == 1


def test_editor_question_answer_retry_close_and_discard_keep_live_plan(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    api.next_revision = "question"
    ask(page, "Change the focus")
    question = dialog.get_by_role("region", name="Planner edit questions")
    expect(question).to_be_visible()
    expect(dialog.get_by_role("button", name="Cancel change", exact=True)).to_be_enabled()
    question.get_by_role("radio", name="Pricing", exact=True).check()
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_disabled()
    before = state(page)
    assert before["plan"]["revision"] == 0 and not before["mainQuestions"]
    dialog.get_by_role("button", name="Close the plan editor").click()
    expect(page.get_by_role("button", name="Run the saved plan")).to_be_disabled()
    dialog = open_editor(page)
    expect(dialog.get_by_role("radio", name="Pricing", exact=True)).to_be_checked()
    api.next_revision = "error"
    dialog.get_by_role("button", name="Finish", exact=True).click()
    expect(dialog.get_by_role("alert")).to_be_visible()
    expect(dialog.get_by_role("radio", name="Pricing", exact=True)).to_be_checked()
    dialog.get_by_role("button", name="Finish", exact=True).click()
    wait_revision(page, 1)
    answers = [call["body"] for call in api.calls("/revisions") if call["body"]["action"] == "answer"]
    assert answers[0] == answers[1]
    assert answers[0]["elicitation_response"] == {"action": "accept", "content": {"focus": "Pricing"}}
    api.next_revision = "question"
    ask(page, "Ask about the focus again")
    expect(dialog.get_by_role("region", name="Planner edit questions")).to_be_visible()
    dialog.get_by_role("button", name="Cancel edit request and keep current plan").click()
    expect(dialog.get_by_role("region", name="Planner edit questions")).to_have_count(0)
    assert state(page)["plan"]["revision"] == 1
    assert api.calls("/revisions")[-1]["body"]["action"] == "discard"
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    assert len(state(page)["messages"]) == 1


def test_late_result_updates_only_its_origin_and_preserves_unsent_draft(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    api.next_revision = "delay"
    ask(page, "Add web search to the first plan")
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_disabled()
    dialog.get_by_role("textbox", name="Ask planner", exact=True).fill("Next unsent instruction")
    mount(page, api, "other-chat", "other-turn", reset=False)
    expect(page.get_by_role("dialog")).to_have_count(0)
    other = open_editor(page)
    api.release()
    wait_revision(page, 1)
    expect(other.get_by_text("Compare quarterly reports for other-chat", exact=True)).to_be_visible()
    assert state(page, "other-chat", "other-turn")["plan"]["revision"] == 0
    assert all("first plan" not in entry["content"] for entry in state(page)["messages"])
    other.get_by_role("button", name="Close the plan editor").click()
    mount(page, api, reset=False)
    expect(page.get_by_role("dialog")).to_have_count(0)
    reopened = open_editor(page)
    expect(reopened.get_by_role("textbox", name="Ask planner", exact=True)).to_have_value("Next unsent instruction")
    expect(reopened.get_by_text("Revised: Add web search to the first plan", exact=True)).to_be_visible()


@pytest.mark.parametrize("code", ["plan_changed", "edit_in_progress"])
def test_run_conflict_refreshes_canonical_without_completing_or_removing_plan(editor_ui, code):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    dialog.get_by_role("button", name="Close the plan editor").click()
    editor = api.editors["editor-chat"]
    if code == "plan_changed":
        api.publish(editor, "Focus on the other tab's latest plan")
    else:
        editor["busy"] = True
    page.get_by_role("button", name="Run the saved plan").click()
    expect(page.get_by_role("alert")).to_contain_text(code)
    page.wait_for_function("""() => {
        const H = window.OrchHarness;
        return !H.stores.orchestration.selectPlanEditor(
            H.stores.orchestration.useOrchestrationStore.getState(), 'editor-chat', 'editor-turn')?.loading;
    }""")
    current = state(page)
    assert not current["history"] and current["active"] == "editor-turn"
    assert len(current["messages"]) == 1 and not api.successful_runs
    assert api.calls("/editor")
    if code == "edit_in_progress":
        expect(page.get_by_role("button", name="Run the saved plan")).to_be_disabled()
        api.publish(editor, "Focus on the completed edit")
        dialog = open_editor(page)
        expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
        dialog.get_by_role("button", name="Close the plan editor").click()
    else:
        assert current["plan"]["run_id"] == editor["plan"]["run_id"]
    page.get_by_role("button", name="Run the saved plan").click()
    expect(page.get_by_role("button", name="Run the saved plan")).to_have_count(0)
    assert api.successful_runs[0]["expected_version"] == editor["version"]


def test_failed_hold_stays_paused_and_reports_that_the_server_has_not_confirmed(editor_ui):
    page, api = editor_ui
    page.clock.install()
    api.hold_response = "error"
    mount(page, api, mode="timed")
    dialog = open_editor(page)
    expect(dialog.get_by_role("alert")).to_have_text("The manual hold could not be saved.")
    expect(dialog.get_by_text("Approval is paused in this tab. The server hold is not yet confirmed.")).to_be_visible()
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_disabled()
    dialog.get_by_role("button", name="Close the plan editor").click()
    page.clock.fast_forward(10000)
    assert not api.calls(RUN)
    expect(page.get_by_role("timer")).to_have_count(0)
    expect(page.get_by_role("button", name="Run the saved plan")).to_be_disabled()
    dialog = open_editor(page)
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()


@pytest.mark.parametrize("status", ["running", "completed", "cancelled", "failed", "superseded", "archived"])
def test_nonpending_and_archived_plans_have_no_edit_entry(editor_ui, status):
    page, api = editor_ui
    plan = api.add()
    if status != "archived":
        plan["status"] = status
    page.goto(ORIGIN + HARNESS)
    # Mount manually because the normal setup intentionally waits for an editable card.
    page.evaluate("""(plan) => {
        const H = window.OrchHarness;
        H.reset();
        H.stores.chat.useChatStore.setState({ activeConversationId: 'editor-chat' });
        const store = H.stores.orchestration.useOrchestrationStore.getState();
        store.setPlan('editor-chat', 'editor-turn', plan);
        store.setActiveTurn('editor-chat', 'editor-turn');
        H.mount('mount-a', 'OrchestrationPlanCard', { conversationId: 'editor-chat', turnId: 'editor-turn' });
    }""", plan)
    if status == "archived":
        page.evaluate("""() => window.OrchHarness.stores.orchestration.useOrchestrationStore.setState({
            readOnlyTurns: { ['editor-chat\\u0000editor-turn']: true } })""")
    expect(page.get_by_role("button", name="Edit the plan", exact=True)).to_have_count(0)
    page.evaluate("() => window.OrchHarness.mount('mount-b', 'OrchestrationPlanPanel')")
    expect(page.get_by_role("button", name="Edit the plan", exact=True)).to_have_count(0)


def test_mobile_keyboard_focus_and_inert_planner_text(editor_ui):
    page, api = editor_ui
    page.set_viewport_size({"width": 390, "height": 844})
    mount(page, api)
    opener = page.get_by_role("button", name="Edit the plan", exact=True)
    dialog = open_editor(page)
    expect(dialog.get_by_role("button", name="Close the plan editor")).to_be_focused()
    api.next_revision = "explain"
    payload = '<img src=x onerror="window.editorInjected=true"> Explain this safely.'
    ask(page, payload)
    expect(dialog.get_by_text(f"Kept the saved plan. Your request was: {payload}", exact=True)).to_be_visible()
    assert page.evaluate("() => window.editorInjected") is None
    expect(dialog.locator("img")).to_have_count(0)
    textarea = dialog.get_by_role("textbox", name="Ask planner", exact=True)
    textarea.fill("Keep this draft")
    send = dialog.get_by_role("button", name="Send planner request")
    send.focus()
    page.keyboard.press("Tab")
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_focused()
    page.keyboard.press("Shift+Tab")
    expect(send).to_be_focused()
    preview_box = dialog.get_by_test_id("plan-editor-preview").bounding_box()
    text_box = textarea.bounding_box()
    assert preview_box["width"] <= 390 and preview_box["height"] >= 100
    assert text_box["y"] >= preview_box["y"] + preview_box["height"]
    assert text_box["x"] >= 0 and text_box["x"] + text_box["width"] <= 390
    assert text_box["y"] + text_box["height"] <= 844
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    expect(opener).to_be_focused()
    assert not api.calls(RUN)
    dialog = open_editor(page)
    expect(dialog.get_by_role("textbox", name="Ask planner", exact=True)).to_have_value("Keep this draft")
    assert len(state(page)["messages"]) == 1


def test_late_history_preview_does_not_replace_current_plan(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    ask(page, "Add web search")
    wait_revision(page, 1)
    dialog.get_by_role("tab", name="History", exact=True).click()
    api.delay_preview = True
    dialog.get_by_role("button", name="Preview revision 0", exact=True).click()
    expect(dialog.get_by_text("Loading revision…", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Back to current plan").click()
    api.release()
    expect(dialog.get_by_text("Current saved plan", exact=True)).to_be_visible()
    assert state(page)["plan"]["revision"] == 1
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()


def test_current_review_draft_survives_reopening_but_stale_edits_adopt_server_overlay(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    dialog.get_by_role("button", name="Close the plan editor").click()
    page.get_by_role("button", name="Review the plan in the drawer").click()
    review = page.get_by_role("complementary", name="Review drawer")
    review.get_by_role("button", name="Remove document doc-a from this step").click()
    review.get_by_role("button", name="Edit the plan").click()
    dialog = page.get_by_role("dialog", name="Edit orchestration plan")
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    assert state(page)["edits"]["removed_document_ids"] == {"read": ["doc-a"]}
    expect(dialog.get_by_text("Report A", exact=True)).to_have_count(0)
    dialog.get_by_role("button", name="Close the plan editor").click()
    server = api.editors["editor-chat"]
    api.publish(server, "Focus on the remote revision")
    server["edits"] = {"disabled_step_ids": [], "removed_document_ids": {"read": ["doc-b"]}}
    api.touch(server)
    review.get_by_role("button", name="Edit the plan").click()
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    assert state(page)["edits"] == server["edits"]
    expect(dialog.get_by_text("Report A", exact=True)).to_be_visible()
    expect(dialog.get_by_text("Report B", exact=True)).to_have_count(0)


def test_review_map_can_preview_superseded_revision_without_overwriting_live_plan(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    ask(page, "Add web search")
    wait_revision(page, 1)
    latest = state(page)["plan"]
    dialog.get_by_role("button", name="Close the plan editor").click()
    page.get_by_role("button", name="Review the plan in the drawer").click()
    review = page.get_by_role("complementary", name="Review drawer")
    review.get_by_role("tab", name="Map", exact=True).click()
    review.get_by_role("button").filter(has_text="Compare quarterly reports for editor-chat").click()
    expect(review.get_by_text("Compare quarterly reports for editor-chat", exact=True)).to_be_visible()
    assert state(page)["plan"] == latest
    expect(review.get_by_role("button", name="Edit the plan", exact=True)).to_have_count(0)
    expect(review.get_by_role("checkbox")).to_have_count(0)
    review.get_by_role("button", name="Back to current", exact=True).click()
    expect(review.get_by_text("Search the web", exact=True)).to_be_visible()
    expect(review.get_by_role("button", name="Edit the plan", exact=True)).to_be_visible()
    assert state(page)["plan"] == latest


def test_editor_question_is_hydrated_after_reload_without_becoming_a_main_question(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    api.next_revision = "question"
    ask(page, "Change the plan focus")
    expect(dialog.get_by_role("region", name="Planner edit questions")).to_be_visible()
    saved_pending = copy.deepcopy(api.editors["editor-chat"]["pending"])
    page.reload()
    mount(page, api, resume=True)
    snapshot = state(page)
    assert snapshot["editor"]["state"]["pending"] == saved_pending
    assert snapshot["plan"]["revision"] == 0 and not snapshot["mainQuestions"]
    expect(page.get_by_role("button", name="Run the saved plan")).to_be_disabled()
    dialog = open_editor(page)
    expect(dialog.get_by_text("Change the plan focus", exact=True)).to_be_visible()
    dialog.get_by_role("radio", name="Delivery", exact=True).check()
    dialog.get_by_role("button", name="Finish", exact=True).click()
    wait_revision(page, 1)
    assert api.calls("/revisions")[-1]["body"]["elicitation_id"] == saved_pending["elicitation_id"]
    assert len(state(page)["messages"]) == 1


def test_concurrent_submissions_and_run_are_blocked_and_changed_instruction_gets_new_id(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    api.next_revision = "delay"
    ask(page, "Add web search")
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_disabled()
    page.evaluate("""() => {
        const H = window.OrchHarness;
        const target = { conversationId: 'editor-chat', turnId: 'editor-turn' };
        return Promise.all([
            H.controller.submitPlanRevision(target, { action: 'ask', instruction: 'Add web search' }),
            H.controller.approveAndRunPlan(target),
        ]);
    }""")
    assert len(api.calls("/revisions")) == 1 and not api.calls(RUN)
    api.release()
    wait_revision(page, 1)
    api.next_revision = "error"
    ask(page, "Rework the gathering steps")
    expect(dialog.get_by_role("alert")).to_be_visible()
    failed_id = api.calls("/revisions")[-1]["body"]["submission_id"]
    dialog.get_by_role("textbox", name="Ask planner").fill("Focus on pricing instead")
    page.keyboard.press("Control+Enter")
    wait_revision(page, 2)
    assert api.calls("/revisions")[-1]["body"]["submission_id"] != failed_id
    assert len(state(page)["messages"]) == 1


@pytest.mark.parametrize("response", ["invalid", "foreign"])
def test_unusable_or_wrong_scope_editor_response_keeps_last_good_plan(editor_ui, response):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    api.next_revision = response
    ask(page, "Rework the plan")
    expect(dialog.get_by_role("alert")).to_contain_text("current plan has been kept")
    snapshot = state(page)
    assert snapshot["plan"]["run_id"] == "editor-chat-run-0"
    assert snapshot["plan"]["conversation_id"] == "editor-chat"
    expect(dialog.get_by_role("textbox", name="Ask planner")).to_have_value("Rework the plan")
    assert len(snapshot["messages"]) == 1
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()


def test_cancel_change_revokes_inflight_work_without_closing_or_growing_main_thread(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    original_version = state(page)["plan"]["edit_version"]
    api.next_revision = "delay"
    ask(page, "Add web search before the comparison")
    expect(dialog.get_by_role("button", name="Cancel change", exact=True)).to_be_enabled()
    dialog.get_by_role("button", name="Close the plan editor").click()
    assert [call["body"]["action"] for call in api.calls("/revisions")] == ["ask"]
    assert api.editors["editor-chat"]["busy"] is True
    dialog = open_editor(page)
    dialog.get_by_role("button", name="Cancel change", exact=True).click()
    expect(dialog.get_by_role("button", name="Cancel change", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    snapshot = state(page)
    cancelled_version = snapshot["plan"]["edit_version"]
    assert cancelled_version != original_version
    assert snapshot["plan"]["revision"] == 0 and snapshot["active"] == "editor-turn"
    assert not snapshot["history"] and not snapshot["streamError"]
    assert len(snapshot["messages"]) == 1 and not snapshot["thoughts"]
    expect(dialog.get_by_role("textbox", name="Ask planner")).to_have_value("Add web search before the comparison")
    discard = api.calls("/revisions")[-1]["body"]
    assert discard["action"] == "discard" and discard["expected_version"] == original_version
    assert "edits" not in discard and api.calls("/editor")
    api.release()
    assert api.editors["editor-chat"]["plan"]["revision"] == 0
    assert state(page)["plan"]["edit_version"] == cancelled_version
    expect(dialog.get_by_role("alert")).to_have_count(0)
    dialog.get_by_role("button", name="Run saved revision").click()
    expect(dialog).to_have_count(0)
    assert api.successful_runs[0]["expected_version"] == cancelled_version


def test_cancel_abandoned_busy_change_after_reload_can_retry_without_failing_main_chat(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    dialog.get_by_role("button", name="Close the plan editor").click()
    editor = api.editors["editor-chat"]
    editor["busy"] = True
    api.touch(editor)
    busy_version = editor["version"]
    page.reload()
    mount(page, api, resume=True)
    expect(page.get_by_role("button", name="Run the saved plan")).to_be_disabled()
    dialog = open_editor(page)
    api.next_revision = "error"
    dialog.get_by_role("button", name="Cancel change", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Planner unavailable")
    expect(dialog.get_by_role("button", name="Cancel change", exact=True)).to_have_text("Retry cancel change")
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_disabled()
    failed = state(page)
    assert failed["editor"]["cancellationStatus"] == "failed"
    assert failed["plan"]["revision"] == 0 and len(failed["messages"]) == 1
    assert not failed["streamError"] and not failed["history"]
    dialog.get_by_role("button", name="Cancel change", exact=True).click()
    expect(dialog.get_by_role("button", name="Cancel change", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    discards = [call["body"] for call in api.calls("/revisions") if call["body"]["action"] == "discard"]
    assert len(discards) == 2 and discards[0] == discards[1]
    assert discards[0]["expected_version"] == busy_version
    assert state(page)["plan"]["edit_version"] != busy_version
    assert editor["busy"] is False and len(state(page)["messages"]) == 1
    dialog.get_by_role("button", name="Close the plan editor").click()
    assert not api.calls(RUN)


def test_finished_change_wins_cancel_race_without_cancelling_new_saved_revision(editor_ui):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    api.next_revision = "delay"
    ask(page, "Add web search")
    expect(dialog.get_by_role("button", name="Cancel change", exact=True)).to_be_enabled()
    api.publish(api.editors["editor-chat"], "Add web search")
    dialog.get_by_role("button", name="Cancel change", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("No pending change remains")
    wait_revision(page, 1)
    assert [call["body"]["action"] for call in api.calls("/revisions")] == ["ask"]
    assert len(state(page)["messages"]) == 1 and not state(page)["streamError"]
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    api.release()
    assert state(page)["plan"]["revision"] == 1


@pytest.mark.parametrize("replacement", ["question", "busy"])
def test_stale_cancel_refreshes_without_discarding_a_newer_change(editor_ui, replacement):
    page, api = editor_ui
    mount(page, api)
    dialog = open_editor(page)
    api.next_revision = "question"
    ask(page, "Rework the plan")
    expect(dialog.get_by_role("region", name="Planner edit questions")).to_be_visible()
    editor = api.editors["editor-chat"]
    old_question = copy.deepcopy(editor["pending"])
    api.publish(editor, "A newer plan from another tab")
    if replacement == "question":
        editor["pending"] = {
            **old_question, "elicitation_id": "newer-question", "revision": 2,
            "message": "Which focus should the newer request use?",
        }
    else:
        editor["busy"] = True
    api.touch(editor)
    newest_version = editor["version"]

    dialog.get_by_role("button", name="Cancel change", exact=True).click()
    expect(dialog.get_by_role("alert")).to_contain_text("Review the current change")
    assert not [call for call in api.calls("/revisions") if call["body"]["action"] == "discard"]
    assert editor["pending"] is not None or editor["busy"]
    assert state(page)["plan"]["edit_version"] == newest_version

    dialog.get_by_role("button", name="Cancel change", exact=True).click()
    expect(dialog.get_by_role("button", name="Run saved revision")).to_be_enabled()
    discards = [call["body"] for call in api.calls("/revisions") if call["body"]["action"] == "discard"]
    assert len(discards) == 1 and discards[0]["expected_version"] == newest_version
    if replacement == "question":
        assert discards[0]["elicitation_id"] == "newer-question"
        assert discards[0]["elicitation_revision"] == 2
    assert len(state(page)["messages"]) == 1 and not state(page)["streamError"]


def test_untouched_immediate_auto_plan_still_runs_without_editor_hold(editor_ui):
    page, api = editor_ui
    mount(page, api)
    page.evaluate("""() => {
        const H = window.OrchHarness;
        H.stores.orchestration.useOrchestrationStore.getState().clearPlan('editor-chat', 'editor-turn');
        return H.controller.startOrchestrationPlan({
            conversationId: 'editor-chat', message: 'Compare immediately', approvalMode: 'auto',
        });
    }""")
    page.wait_for_function("() => Object.keys(window.OrchHarness.stores.orchestration.useOrchestrationStore.getState().history).length > 0")
    assert len(api.successful_runs) == 1
    assert not api.calls("/edit") and not api.calls("/revisions")
    assert "expected_version" not in api.successful_runs[0]
