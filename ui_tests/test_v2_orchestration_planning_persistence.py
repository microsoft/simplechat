# test_v2_orchestration_planning_persistence.py
"""
Browser regressions for durable initial Orchestrate turns.
Version: 0.261.415
Implemented in: 0.261.415

The production controller, stores, SSE reader, message list, composer, and CSS run
unchanged. A deterministic HTTP boundary retains accepted turns independently of
browser contexts. The shared Azure Playwright connection uses DefaultAzureCredential
when configured; no cloud resources or production conversations are modified.
"""

import copy
import json
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
import test_v2_orchestration_planning_retry as planning_tests
from test_v2_orchestration_plan_editor import connect_options, editor_assets, editor_browser  # noqa: F401


pytestmark = pytest.mark.ui
CONVERSATION = planning_tests.CONVERSATION
PROMPT = planning_tests.PROMPT
PLAN = planning_tests.PLAN
QUESTION_ID = "saved-planning-question"
ANSWER = "The original request completed while its browser was away."
FAILURE = "The request could not be planned. Your question was saved; retry to create a new plan."
SEEDS = {key: copy.deepcopy(value) for key, value in planning_tests.SEEDS.items() if key != "prompt_info"}


class DurablePlanningApi(planning_tests.PlanningApi):
    def __init__(self, assets):
        super().__init__(assets)
        self.outcome = "planning"
        self.turn = None
        self.request = None
        self.plan = None
        self.records = {}
        self.status_reads = []
        self.status_failure = False
        self.conversations = [
            {"id": CONVERSATION, "title": "Original planning request"},
            {"id": "another-chat", "title": "Another conversation"},
        ]

    def save_question(self):
        metadata = {
            "orchestration_turn_id": self.turn["turn_id"],
            "orchestration": {
                "turn_id": self.turn["turn_id"], "planning_status": self.turn["status"],
                "planning_submission_id": self.turn["submission_id"],
                **({"run_id": self.turn["run_id"]} if self.turn.get("run_id") else {}),
                **({"planning_error": self.turn["error"]} if self.turn.get("error") else {}),
                **({"planning_run_started": self.turn["run_started"]} if "run_started" in self.turn else {}),
            },
        }
        question = {
            "id": QUESTION_ID, "conversation_id": CONVERSATION, "role": "user", "content": PROMPT,
            "timestamp": "2026-11-05T20:55:24Z", "metadata": metadata,
        }
        self.messages = [question, *[message for message in self.messages if message["id"] != QUESTION_ID]]

    def accept(self, body):
        if self.request is None:
            self.request = copy.deepcopy(body)
            self.request.pop("planning_submission_id", None)
            if self.request.get("active_group_id"):
                self.request["active_group_ids"] = [self.request.pop("active_group_id")]
        self.request["approval_mode"] = body.get("approval_mode", "manual")
        self.request["revision"] = body.get("revision", 0)
        self.turn = {
            "conversation_id": CONVERSATION, "turn_id": body["turn_id"], "user_message_id": QUESTION_ID,
            "submission_id": body["planning_submission_id"], "status": "planning",
            "updated_at": "2026-11-05T20:55:25Z", "request": copy.deepcopy(self.request),
        }
        events = [{
            "type": "user_message_persisted", "conversation_id": CONVERSATION,
            "turn_id": body["turn_id"], "user_message_id": QUESTION_ID,
            "planning_submission_id": self.turn["submission_id"],
            "message_persisted": True, "server_managed": True,
        }]
        if self.outcome in ("failed", "interrupted"):
            self.turn.update(status=self.outcome, error=FAILURE, error_code="planning_failed")
            events.append({"error": FAILURE, "code": "planning_failed", "done": True})
        elif self.outcome == "clarification":
            question = {
                "elicitation_id": "saved-style-question", "contract_version": 2, "run_id": "",
                "conversation_id": CONVERSATION, "turn_id": body["turn_id"], "revision": 0,
                "message": "What response style should I use?",
                "requested_schema": {
                    "type": "object",
                    "properties": {"style": {"type": "string", "title": "Response style"}},
                    "required": ["style"],
                },
                "ui_hints": {"pages": [["style"]], "order": ["style"]},
            }
            self.turn.update(status="awaiting_clarification", elicitation=question)
            events.append({"type": "orchestration_elicitation", "elicitation": question, "done": True})
        elif self.outcome == "plan":
            self.make_record(body.get("approval_mode", "manual"))
            events.append({
                "type": "orchestration_plan", "plan": copy.deepcopy(self.plan),
                "server_managed": True, "done": True,
                "turn_identity": {
                    "conversation_id": CONVERSATION, "turn_id": self.turn["turn_id"],
                    "user_message_id": QUESTION_ID, "run_id": self.plan["run_id"],
                },
            })
        else:
            # A dropped observer after durable acknowledgement, while the independent
            # server-side attempt remains in planning. Only GET status follows it.
            events.append({"type": "thought", "content": "Planning the saved request."})
        self.save_question()
        return events

    def make_record(self, mode="auto"):
        self.plan = editor_tests.make_plan(CONVERSATION, self.turn["turn_id"], mode)
        if mode in ("auto", "timed"):
            self.plan["approval"]["state"] = "approved"
            self.plan["status"] = "approved"
        running = mode == "auto"
        self.turn.update(
            status="running" if running else "awaiting_review",
            run_id=self.plan["run_id"], run_started=running,
        )
        self.records[self.plan["run_id"]] = {
            "run_id": self.plan["run_id"], "conversation_id": CONVERSATION,
            "turn_id": self.turn["turn_id"], "plan": copy.deepcopy(self.plan),
            "status": "running" if running else self.plan["status"],
            "created_at": "2026-11-05T20:55:30Z",
            "started_at": "2026-11-05T20:55:31Z" if running else None,
            "user_message_id": QUESTION_ID, "user_message": PROMPT, "assistant_message_id": None,
            "attempt_index": 1, "turn_index": 0, "outputs": [],
            "plan_summary": {
                "plan_id": self.plan["plan_id"], "turn_id": self.turn["turn_id"],
                "step_count": len(self.plan["steps"]), "status": self.plan["status"],
                "intent_summary": self.plan["intent"]["summary"],
            },
        }

    def complete(self):
        if self.turn["status"] == "cancelled":
            return False
        if not self.plan:
            self.make_record()
        record = self.records[self.plan["run_id"]]
        record.update(
            status="completed", outcome="completed", finalization_status="saved", message_saved=True,
            assistant_message_id="saved-answer", completed_at="2026-11-05T20:56:00Z",
        )
        record["plan"]["status"] = record["plan_summary"]["status"] = "completed"
        self.turn.update(status="completed", run_started=True)
        self.save_question()
        if not any(message["id"] == "saved-answer" for message in self.messages):
            self.messages.append({
                "id": "saved-answer", "conversation_id": CONVERSATION,
                "role": "assistant", "content": ANSWER, "timestamp": "2026-11-05T20:56:00Z",
                "metadata": {"orchestration": {
                    "turn_id": self.turn["turn_id"], "run_id": self.plan["run_id"],
                    "outcome": "completed", "finalization_status": "saved", "message_saved": True,
                }},
            })
        return True

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        body = request.post_data_json if request.post_data else None
        if path == PLAN:
            self.requests.append({"path": path, "method": request.method, "body": copy.deepcopy(body)})
            events = self.accept(body)
            route.fulfill(content_type="text/event-stream", body="".join(
                f"data: {json.dumps(event)}\n\n" for event in events
            ))
            return
        if path.startswith("/api/v2/orchestration/turns/"):
            self.requests.append({"path": path, "method": request.method, "body": copy.deepcopy(body)})
            if request.method == "GET":
                self.status_reads.append(parse_qs(parsed.query))
            if request.method == "POST" and path.endswith("/cancel"):
                if self.turn["status"] != "completed":
                    self.turn.update(status="cancelled")
                self.save_question()
                route.fulfill(json={
                    "success": True, "turn_id": self.turn["turn_id"],
                    "submission_id": body["submission_id"], "turn": copy.deepcopy(self.turn),
                })
            elif self.status_failure:
                route.fulfill(status=503, json={"error": "Saved planning status is temporarily unavailable."})
            else:
                route.fulfill(json={"turn": copy.deepcopy(self.turn)})
            return
        if path == "/api/get_messages":
            conversation = parse_qs(parsed.query).get("conversation_id", [""])[0]
            route.fulfill(json={"messages": copy.deepcopy(self.messages) if conversation == CONVERSATION else []})
            return
        if path.startswith("/api/chat/stream/status/"):
            route.fulfill(json={"is_streaming": False, "active": False, "status": "idle"})
            return
        if path.startswith("/api/conversations/") and path.endswith("/metadata"):
            route.fulfill(json={"conversation_id": unquote(path.split("/")[3]), "title": "Saved conversation"})
            return
        if path == editor_tests.RUNS:
            route.fulfill(json={"runs": list(self.records.values())})
            return
        if path.startswith(editor_tests.RUNS + "/"):
            run_id = unquote(path.split("/")[5])
            if path.endswith("/steps"):
                record = self.records[run_id]
                route.fulfill(json={"steps": [
                    {"step_id": step["step_id"], "step_index": index,
                     "status": "completed" if record["status"] == "completed" else "pending", "summary": ""}
                    for index, step in enumerate(record["plan"]["steps"])
                ]})
            else:
                route.fulfill(json={"run": copy.deepcopy(self.records[run_id])})
            return
        super().handle(route)


@pytest.fixture
def durable_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    api = DurablePlanningApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        open_saved(page, api)
        yield page, api
    finally:
        context.close()
        assert not api.errors, api.errors


def open_saved(page, api):
    planning_tests.mount(page, api)
    page.evaluate(
        "(id) => window.OrchHarness.stores.chat.useChatStore.getState().selectConversation(id, {kind: 'personal'})",
        CONVERSATION,
    )


def submit(page, mode="auto"):
    page.evaluate(
        "(spec) => { void window.OrchHarness.controller.startOrchestrationPlan(spec); }",
        {"conversationId": CONVERSATION, "message": PROMPT, "approvalMode": mode, "seeds": SEEDS},
    )
    expect(page.locator(f'[id="message-{QUESTION_ID}"]')).to_be_visible()


@pytest.mark.parametrize("width", [1280, 390])
def test_navigate_back_recovers_question_and_background_auto_answer(durable_ui, width):
    page, api = durable_ui
    page.set_viewport_size({"width": width, "height": 900})
    submit(page)
    expect(page.get_by_text("No messages in this conversation yet", exact=True)).to_have_count(0)
    page.evaluate(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().selectConversation('another-chat', {kind: 'personal'})",
    )
    expect(page.get_by_text(PROMPT, exact=True)).to_have_count(0)
    completed = api.complete()
    assert completed
    page.evaluate(
        "(id) => window.OrchHarness.stores.chat.useChatStore.getState().selectConversation(id, {kind: 'personal'})",
        CONVERSATION,
    )
    expect(page.get_by_text(PROMPT, exact=True)).to_have_count(1)
    expect(page.get_by_text(ANSWER, exact=True)).to_have_count(1)
    assert len(api.calls(PLAN)) == 1
    assert api.calls(editor_tests.RUN) == []
    overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow


def test_fresh_browser_context_restores_planning_and_follows_the_original_run(durable_ui, editor_browser):
    page, api = durable_ui
    submit(page)
    page.close()
    fresh = editor_browser.new_context(viewport={"width": 1280, "height": 900})
    try:
        restored = fresh.new_page()
        restored.route("**/*", api.handle)
        restored.on("pageerror", lambda error: api.errors.append(str(error)))
        open_saved(restored, api)
        expect(restored.get_by_text(PROMPT, exact=True)).to_have_count(1)
        expect(restored.get_by_role("button", name="Stop generating", exact=True)).to_be_visible()
        completed = api.complete()
        assert completed
        expect(restored.get_by_text(ANSWER, exact=True)).to_have_count(1, timeout=15000)
        assert len(api.calls(PLAN)) == 1
        assert api.calls(editor_tests.RUN) == []
    finally:
        fresh.close()


@pytest.mark.parametrize("failure", ["failed", "interrupted"])
def test_failure_survives_reload_and_retry_keeps_canonical_selections(durable_ui, failure):
    page, api = durable_ui
    api.outcome = failure
    submit(page, "manual")
    expect(page.get_by_role("alert").filter(has_text=FAILURE)).to_have_count(1)
    open_saved(page, api)
    expect(page.get_by_text(PROMPT, exact=True)).to_have_count(1)
    expect(page.get_by_role("alert").filter(has_text=FAILURE)).to_have_count(1)
    api.outcome = "plan"
    page.get_by_role("button", name="Retry", exact=True).click()
    expect(page.get_by_role("button", name="Approve and run the plan").first).to_be_visible()
    expect(page.get_by_text(PROMPT, exact=True)).to_have_count(1)
    original, retried = [request["body"] for request in api.calls(PLAN)]
    for field in ("selected_document_ids", "model_deployment", "model_endpoint_id", "doc_scope"):
        assert retried[field] == original[field]
    assert retried["active_group_ids"] == [original["active_group_id"]]
    assert retried["planning_submission_id"] != original["planning_submission_id"]
    assert retried["requires_fresh_review"] is True
    assert retried["approval_mode"] == "manual"
    assert api.calls(editor_tests.RUN) == []


def test_clarification_is_restored_and_answered_after_reload(durable_ui):
    page, api = durable_ui
    api.outcome = "clarification"
    submit(page, "manual")
    expect(page.get_by_role("textbox", name="Response style", exact=True)).to_be_visible()
    open_saved(page, api)
    expect(page.get_by_text(PROMPT, exact=True)).to_have_count(1)
    page.get_by_role("textbox", name="Response style", exact=True).fill("A concise explanation.")
    api.outcome = "plan"
    page.get_by_role("button", name="Review answers", exact=True).click()
    page.get_by_role("button", name="Use these answers", exact=True).click()
    expect(page.get_by_role("button", name="Approve and run the plan").first).to_be_visible()
    submitted = api.calls(PLAN)[1]["body"]
    assert submitted["message"] == PROMPT
    assert submitted["elicitation_id"] == "saved-style-question"
    assert submitted["elicitation_response"]["content"] == {"style": "A concise explanation."}
    expect(page.get_by_text(PROMPT, exact=True)).to_have_count(1)


def test_stop_after_reload_is_durable_without_a_live_stream(durable_ui):
    page, api = durable_ui
    submit(page)
    open_saved(page, api)
    page.get_by_role("button", name="Stop generating", exact=True).click()
    expect(page.get_by_text("Planning stopped. Your question was saved.", exact=True)).to_be_visible()
    completed = api.complete()
    assert not completed
    open_saved(page, api)
    expect(page.get_by_text(PROMPT, exact=True)).to_have_count(1)
    expect(page.get_by_text("Planning stopped. Your question was saved.", exact=True)).to_be_visible()
    assert len(api.calls(PLAN)) == 1
    assert api.calls(editor_tests.RUN) == []


@pytest.mark.parametrize("mode", ["manual", "timed"])
def test_opening_a_saved_review_never_starts_its_countdown_or_execution(durable_ui, mode):
    page, api = durable_ui
    api.outcome = "plan"
    api.accept({
        **SEEDS, "message": PROMPT, "conversation_id": CONVERSATION, "turn_id": "saved-review",
        "planning_submission_id": "saved-review-submission", "approval_mode": mode,
    })
    page.clock.install()
    open_saved(page, api)
    expect(page.get_by_role("button", name="Approve and run the plan").first).to_be_visible()
    page.clock.fast_forward(5000)
    assert api.calls(editor_tests.RUN) == []


def test_server_managed_auto_plan_does_not_send_a_second_run_post(durable_ui):
    page, api = durable_ui
    api.outcome = "plan"
    submit(page)
    page.wait_for_function(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().orchestrationSurface === 'running'",
    )
    completed = api.complete()
    assert completed
    expect(page.get_by_text(ANSWER, exact=True)).to_have_count(1, timeout=15000)
    assert len(api.calls(PLAN)) == 1
    assert api.calls(editor_tests.RUN) == []


def test_stop_racing_with_completion_restores_the_answer_instead_of_claiming_it_stopped(durable_ui):
    page, api = durable_ui
    submit(page)
    stop = page.get_by_role("button", name="Stop generating", exact=True)
    expect(stop).to_be_visible()
    completed = api.complete()
    assert completed
    stop.click()
    expect(page.get_by_text(ANSWER, exact=True)).to_have_count(1, timeout=15000)
    expect(page.get_by_text("Planning stopped. Your question was saved.", exact=True)).to_have_count(0)
    assert len(api.calls(PLAN)) == 1
    assert api.calls(editor_tests.RUN) == []


def test_status_outage_keeps_the_saved_question_without_automatic_retry(durable_ui):
    page, api = durable_ui
    submit(page)
    api.status_failure = True
    open_saved(page, api)
    expect(page.get_by_text(PROMPT, exact=True)).to_have_count(1)
    expect(page.get_by_role("alert").filter(has_text="Saved planning status could not be reached")).to_be_visible()
    assert len(api.calls(PLAN)) == 1
    api.status_failure = False
    completed = api.complete()
    assert completed
    expect(page.get_by_text(ANSWER, exact=True)).to_have_count(1, timeout=15000)
    assert len(api.calls(PLAN)) == 1


@pytest.mark.parametrize("viewer", ["tester", "guest"])
def test_shared_owner_recovers_using_the_source_question_without_querying_for_other_participants(durable_ui, viewer):
    page, api = durable_ui
    api.outcome = "failed"
    api.accept({
        **SEEDS, "message": PROMPT, "conversation_id": CONVERSATION, "turn_id": "shared-planning-turn",
        "planning_submission_id": "shared-planning-submission", "approval_mode": "manual",
    })
    mirrored = copy.deepcopy(api.messages[0])
    mirrored.update(id="shared-question-copy", message_kind="ai_request", sender={"user_id": "tester"})
    mirrored["metadata"].update(source_message_id=QUESTION_ID, sender={"user_id": "tester"})
    mirrored["metadata"]["orchestration"].update(planning_status="planning")
    mirrored["metadata"]["orchestration"].pop("planning_error", None)
    page.evaluate(
        """async (spec) => {
            const H = window.OrchHarness;
            const bootstrap = H.stores.bootstrap.useBootstrapStore.getState().data;
            H.stores.bootstrap.useBootstrapStore.setState({
                data: {...bootstrap, user: {...bootstrap.user, id: spec.viewer}},
            });
            H.stores.chat.useChatStore.setState({
                activeConversationKind: 'collaborative', messages: [spec.message],
            });
            await H.controller.resumeOrchestrationPlanning(spec.conversation);
        }""",
        {"message": mirrored, "viewer": viewer, "conversation": CONVERSATION},
    )
    expect(page.locator('[id="message-shared-question-copy"]')).to_have_count(1)
    if viewer == "tester":
        expect(page.get_by_role("alert").filter(has_text=FAILURE)).to_have_count(1)
        assert api.status_reads[0]["message_id"] == [QUESTION_ID]
    else:
        expect(page.get_by_role("alert").filter(has_text=FAILURE)).to_have_count(0)
        assert api.status_reads == []


def test_saved_acknowledgement_merges_an_already_mirrored_question(durable_ui):
    page, _api = durable_ui
    page.evaluate(
        """(spec) => {
            const store = window.OrchHarness.stores.chat.useChatStore;
            const pendingId = store.getState().beginOrchestrationTurn(
                spec.conversation, spec.message, true, 'mirrored-turn',
            );
            store.setState((state) => ({messages: [...state.messages, {
                id: 'public-question', conversation_id: spec.conversation, role: 'user',
                content: spec.message, metadata: {
                    orchestration_turn_id: 'mirrored-turn', source_message_id: 'source-question',
                },
            }]}));
            store.getState().reconcileOrchestrationUserMessage({
                conversationId: spec.conversation, turnId: 'mirrored-turn',
                optimisticId: pendingId, savedId: 'source-question',
            });
        }""",
        {"conversation": CONVERSATION, "message": PROMPT},
    )
    expect(page.get_by_text(PROMPT, exact=True)).to_have_count(1)
    expect(page.locator('[id="message-public-question"]')).to_have_count(1)


def test_restored_waiting_run_does_not_take_the_composer_stream(durable_ui):
    page, api = durable_ui
    api.outcome = "plan"
    api.accept({
        **SEEDS, "message": PROMPT, "conversation_id": CONVERSATION, "turn_id": "waiting-turn",
        "planning_submission_id": "waiting-submission", "approval_mode": "auto",
    })
    api.turn["status"] = "waiting"
    api.records[api.plan["run_id"]]["status"] = "waiting"
    api.records[api.plan["run_id"]]["plan"]["status"] = "waiting"
    api.save_question()
    open_saved(page, api)
    expect(page.get_by_text("Waiting for results", exact=True).first).to_be_visible()
    expect(page.get_by_role("button", name="Send message", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Stop generating", exact=True)).to_have_count(0)
    current = page.evaluate(
        "() => {const s = window.OrchHarness.stores.chat.useChatStore.getState(); "
        "return {streaming: s.streaming, phase: s.orchestrationSurface};}",
    )
    assert current == {"streaming": False, "phase": None}
    assert api.calls(editor_tests.RUN) == []


def test_background_planning_does_not_steal_an_ordinary_stream_or_its_stop(durable_ui):
    page, api = durable_ui
    api.accept({
        **SEEDS, "message": PROMPT, "conversation_id": CONVERSATION, "turn_id": "background-turn",
        "planning_submission_id": "background-submission", "approval_mode": "auto",
    })
    page.evaluate(
        """async (spec) => {
            const H = window.OrchHarness;
            H.stores.chat.useChatStore.setState({
                messages: spec.messages, streaming: true, orchestrationSurface: null,
                streamingContent: 'An ordinary reply is being read.',
            });
            await H.controller.resumeOrchestrationPlanning(spec.conversation);
        }""",
        {"messages": api.messages, "conversation": CONVERSATION},
    )
    current = page.evaluate(
        "() => {const s = window.OrchHarness.stores.chat.useChatStore.getState(); "
        "return {phase: s.orchestrationSurface, content: s.streamingContent};}",
    )
    assert current == {"phase": None, "content": "An ordinary reply is being read."}
    page.get_by_role("button", name="Stop generating", exact=True).click()
    assert not [request for request in api.requests if request["path"].endswith("/cancel")]
    assert api.turn["status"] == "planning"
