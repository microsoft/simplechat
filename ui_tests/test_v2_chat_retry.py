# test_v2_chat_retry.py
"""
Browser coverage for saved model, agent, and orchestration retry attempts.
Version: 0.261.319
Implemented in: 0.261.317

Runs the real message list, composer, stores, and controller with production CSS.
Only HTTP and streaming provider responses are replaced. No live service is called.
"""

import copy
import json
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
from test_v2_orchestration_plan_editor import connect_options, editor_assets, editor_browser  # noqa: F401
from test_v2_orchestration_planning_retry import CONVERSATION, PLAN, PlanningApi, mount


pytestmark = pytest.mark.ui
THREAD = "saved-retry-thread"
FAILURE = "This retry's provider could not complete."
WORDING = "Use the wording of this viewed edited attempt."
MODEL = {
    "model_deployment": "original-model", "model_id": "original-model-id",
    "model_endpoint_id": "original-endpoint", "model_provider": "aoai",
}


def message(identifier, role, content, attempt=1, *, kind="chat", state=None):
    metadata = {
        "thread_info": {
            "thread_id": THREAD, "thread_attempt": attempt, "active_thread": True,
            "root_timestamp": "2026-01-01T00:00:01Z",
        },
    }
    if role == "user":
        metadata["model_selection"] = {"selected_model": MODEL["model_deployment"], **MODEL}
        if state:
            metadata["response_attempt"] = {"kind": kind, "state": state}
        if kind == "orchestration":
            metadata["orchestration"] = {"turn_id": f"saved-turn-{attempt}"}
    return {
        "id": identifier, "conversation_id": CONVERSATION, "role": role,
        "content": content, "timestamp": "2026-01-01T00:00:01Z", "metadata": metadata,
    }


class RetryApi(PlanningApi):
    def __init__(self, assets):
        super().__init__(assets)
        self.kind = "chat"
        self.prepare_mode = "ready"
        self.stream_mode = "success"
        self.held_preparations = []
        self.selected = 1
        self.attempts = {1: [
            message("question-1", "user", WORDING),
            message("answer-1", "assistant", "The previous successful answer."),
        ]}
        self.later = [
            {"id": "later-question", "conversation_id": CONVERSATION, "role": "user", "content": "A later question."},
            {"id": "later-answer", "conversation_id": CONVERSATION, "role": "assistant", "content": "A later answer."},
        ]
        self.mode = "plan"
        self.pending_stream = False

    def rows(self):
        return copy.deepcopy(self.attempts[self.selected] + self.later)

    def prepared(self):
        if 2 not in self.attempts:
            question = message("question-2", "user", WORDING, 2, kind=self.kind, state="prepared")
            if self.attempts[1][0]["metadata"].get("agent_selection"):
                question["metadata"]["agent_selection"] = copy.deepcopy(self.attempts[1][0]["metadata"]["agent_selection"])
            self.attempts[2] = [question]
        question = self.attempts[2][0]
        self.selected = 2
        body = {
            "conversation_id": CONVERSATION, "message": question["content"], **MODEL,
            "retry_user_message_id": question["id"], "retry_thread_id": THREAD, "retry_thread_attempt": 2,
            "web_search_enabled": True, "selected_document_ids": ["original-document"],
        }
        if question["metadata"].get("agent_selection"):
            for key in MODEL:
                body.pop(key)
            body["agent_info"] = {"id": "agent-original", "name": "original-agent", "is_global": True}
        payload = {
            "success": True, "user_message": copy.deepcopy(question), "user_message_id": question["id"],
            "thread_id": THREAD, "new_attempt": 2, "available_attempts": sorted(self.attempts),
            "attempt_state": "prepared",
        }
        if self.kind == "orchestration":
            payload.update({
                "turn_id": "saved-turn-2", "requires_fresh_review": True,
                "plan_request": {**body, "turn_id": "saved-turn-2", "approval_mode": "manual"},
            })
        else:
            payload["chat_request"] = body
        return payload

    def release_preparations(self):
        pending, self.held_preparations = self.held_preparations, []
        for route in pending:
            route.fulfill(json=self.prepared())

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        preparation = path.endswith("/retry") or path.endswith("/regenerate")
        if preparation and (path.startswith("/api/message/") or "/orchestration/messages/" in path):
            self.requests.append({"path": path, "method": request.method, "body": request.post_data_json})
            if self.prepare_mode == "held":
                self.held_preparations.append(route)
            elif self.prepare_mode == "refuse":
                route.fulfill(status=403, json={"error": "The original model is no longer available."})
            else:
                route.fulfill(json=self.prepared())
            return
        if path == "/api/get_messages":
            route.fulfill(json={"messages": self.rows()})
            return
        if path.endswith("/switch-attempt"):
            self.requests.append({"path": path, "method": request.method, "body": request.post_data_json})
            self.selected = 1 if request.post_data_json["direction"] == "prev" else max(self.attempts)
            route.fulfill(json={
                "success": True, "target_attempt": self.selected, "available_attempts": sorted(self.attempts),
            })
            return
        if path.startswith("/api/chat/stream/status/"):
            route.fulfill(json={
                "pending": self.pending_stream, "active": self.pending_stream, "user_message_id": "question-2",
            })
            return
        if path.startswith("/api/chat/stream/cancel/"):
            self.requests.append({"path": path, "method": request.method, "body": None})
            self.attempts[2][0]["metadata"]["response_attempt"]["state"] = "interrupted"
            route.fulfill(json={"success": True})
            return
        if path == "/api/chat/stream" or path.startswith("/api/chat/stream/reattach/"):
            self.requests.append({"path": path, "method": request.method,
                                  "body": request.post_data_json if request.post_data else None})
            question = self.attempts[2][0]
            if self.stream_mode == "failure":
                question["metadata"]["response_attempt"].update({"state": "failed", "error": FAILURE})
                event = {"error": FAILURE, "done": True, "conversation_id": CONVERSATION}
            elif self.stream_mode == "blocked":
                question["metadata"]["response_attempt"]["state"] = "failed"
                reply = message("answer-2", "safety", "The content check blocked this response.", 2)
                self.attempts[2].append(reply)
                event = {
                    "done": True, "blocked": True, "replace_content": True,
                    "conversation_id": CONVERSATION, "user_message_id": question["id"],
                    "message_id": reply["id"], "full_content": reply["content"],
                    "metadata": reply["metadata"],
                }
            else:
                question["metadata"]["response_attempt"]["state"] = "completed"
                reply = message("answer-2", "assistant", "The regenerated answer.", 2)
                self.attempts[2].append(reply)
                event = {
                    "done": True, "conversation_id": CONVERSATION, "user_message_id": question["id"],
                    "message_id": reply["id"], "full_content": reply["content"],
                    "metadata": reply["metadata"],
                }
            self.pending_stream = False
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(event)}\n\n")
            return
        if path == PLAN:
            self.requests.append({"path": path, "method": request.method, "body": request.post_data_json})
            plan = editor_tests.make_plan(CONVERSATION, "saved-turn-2", "auto")
            plan["requires_fresh_review"] = True
            self.attempts[2][0]["metadata"]["response_attempt"]["state"] = "awaiting_review"
            event = {"type": "orchestration_plan", "plan": plan, "done": True}
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(event)}\n\n")
            return
        if path == editor_tests.RUN:
            self.requests.append({"path": path, "method": request.method, "body": request.post_data_json})
            self.attempts[2][0]["metadata"]["response_attempt"]["state"] = "completed"
            event = {
                "done": True, "status": "completed", "conversation_id": CONVERSATION,
                "turn_id": "saved-turn-2", "run_id": request.post_data_json["run_id"],
                "user_message_id": "question-2", "message_id": "answer-2", "full_content": "A fresh orchestrated answer.",
                "metadata": {"thread_info": {"thread_id": THREAD, "thread_attempt": 2, "active_thread": True}},
            }
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(event)}\n\n")
            return
        if path.startswith("/api/conversations/") and path.endswith("/read"):
            route.fulfill(json={"success": True})
            return
        super().handle(route)


@pytest.fixture
def retry_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 1100})
    page = context.new_page()
    api = RetryApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        api.release_preparations()
        api.release()
        context.close()
        assert not api.errors, api.errors


def start(page, api):
    mount(page, api, api.rows())
    page.evaluate("""({thread, attempts}) => window.OrchHarness.stores.chat.useChatStore.setState({
        attemptsByThread: {[thread]: attempts}, retryPresentation: null,
    })""", {"thread": THREAD, "attempts": sorted(api.attempts)})


def chat_state(page):
    return page.evaluate("""() => {
        const S = window.OrchHarness.stores.chat.useChatStore.getState();
        return {messages: S.messages, streaming: S.streaming, error: S.streamError,
            retry: S.retryPresentation, attempts: S.attemptsByThread};
    }""")


@pytest.mark.parametrize("agent", [False, True])
def test_retry_hides_answer_immediately_and_reuses_saved_selections_in_place(retry_ui, agent):
    page, api = retry_ui
    if agent:
        api.attempts[1][0]["metadata"]["agent_selection"] = {
            "selected_agent": "original-agent", "agent_id": "agent-original", "is_global": True,
        }
    api.prepare_mode = "held"
    start(page, api)
    page.get_by_role("button", name="Retry", exact=True).first.click()
    expect(page.get_by_text("The previous successful answer.", exact=True)).not_to_be_visible()
    expect(page.get_by_text(re.compile("Preparing retry"))).to_be_visible()
    assert chat_state(page)["attempts"][THREAD] == sorted(api.attempts)
    page.evaluate("""() => {
        void window.OrchHarness.stores.chat.useChatStore.getState().retryMessage('question-1');
    }""")
    assert len(api.held_preparations) == 1
    api.release_preparations()
    expect(page.get_by_text("The regenerated answer.", exact=True)).to_be_visible()
    state = chat_state(page)
    assert [row["id"] for row in state["messages"]] == ["question-2", "answer-2", "later-question", "later-answer"]
    request = api.calls("/api/chat/stream")[0]["body"]
    assert request["message"] == WORDING
    assert request["retry_user_message_id"] == "question-2"
    if agent:
        assert request["agent_info"]["id"] == "agent-original"
    else:
        for key, value in MODEL.items():
            assert request[key] == value
    assert request["web_search_enabled"] is True
    assert request["selected_document_ids"] == ["original-document"]


def test_earlier_retry_does_not_follow_the_conversation_tail(retry_ui):
    page, api = retry_ui
    api.later[1]["content"] = "\n\n".join("Later answer paragraph. " * 30 for _ in range(30))
    api.prepare_mode = "held"
    start(page, api)
    page.get_by_role("button", name="Retry", exact=True).first.click()
    expect(page.get_by_text(re.compile("Preparing retry"))).to_be_visible()
    before = page.locator('[data-tour="message-list"]').evaluate("(node) => node.scrollTop")
    api.release_preparations()
    expect(page.get_by_text("The regenerated answer.", exact=True)).to_be_visible()
    geometry = page.locator('[data-tour="message-list"]').evaluate(
        "(node) => ({top: node.scrollTop, remaining: node.scrollHeight - node.clientHeight - node.scrollTop})")
    assert abs(geometry["top"] - before) < 100
    assert geometry["remaining"] > 300


def test_refused_preparation_restores_old_answer_without_a_phantom_attempt(retry_ui):
    page, api = retry_ui
    api.prepare_mode = "refuse"
    start(page, api)
    page.get_by_role("button", name="Retry", exact=True).first.click()
    expect(page.get_by_text("The original model is no longer available.", exact=True)).to_be_visible()
    expect(page.get_by_text("The previous successful answer.", exact=True)).to_be_visible()
    state = chat_state(page)
    assert [row["id"] for row in state["messages"]][:2] == ["question-1", "answer-1"]
    assert state["attempts"][THREAD] == [1]
    assert not api.calls("/api/chat/stream")


def test_failed_attempt_error_follows_carousel_and_survives_reload(retry_ui):
    page, api = retry_ui
    api.stream_mode = "failure"
    start(page, api)
    page.get_by_role("button", name="Retry", exact=True).first.click()
    expect(page.get_by_text(FAILURE, exact=True)).to_be_visible()
    expect(page.get_by_text("The previous successful answer.", exact=True)).not_to_be_visible()
    page.get_by_role("button", name="Previous attempt", exact=True).first.click()
    expect(page.get_by_text("The previous successful answer.", exact=True)).to_be_visible()
    expect(page.get_by_text(FAILURE, exact=True)).not_to_be_visible()
    page.get_by_role("button", name="Next attempt", exact=True).first.click()
    expect(page.get_by_text(FAILURE, exact=True)).to_be_visible()
    start(page, api)
    expect(page.get_by_text(FAILURE, exact=True)).to_be_visible()
    assert chat_state(page)["error"] is None


def test_blocked_retry_keeps_safety_notice_and_failed_state_on_its_own_attempt(retry_ui):
    page, api = retry_ui
    api.stream_mode = "blocked"
    start(page, api)
    page.get_by_role("button", name="Retry", exact=True).first.click()
    notice = page.get_by_text("The content check blocked this response.", exact=True)
    expect(notice).to_be_visible()
    state = chat_state(page)
    assert state["messages"][0]["metadata"]["response_attempt"]["state"] == "failed"
    assert state["messages"][1]["role"] == "safety"
    expect(page.get_by_text("This attempt could not complete. You can retry this question.", exact=True)).not_to_be_visible()
    page.get_by_role("button", name="Previous attempt", exact=True).first.click()
    expect(page.get_by_text("The previous successful answer.", exact=True)).to_be_visible()
    expect(notice).not_to_be_visible()
    page.get_by_role("button", name="Next attempt", exact=True).first.click()
    expect(notice).to_be_visible()
    start(page, api)
    expect(notice).to_be_visible()
    assert len(api.calls("/api/chat/stream")) == 1


@pytest.mark.parametrize("deleted_answer", [False, True])
def test_orchestration_retry_makes_a_fresh_manual_plan_even_when_auto_is_selected(retry_ui, deleted_answer):
    page, api = retry_ui
    api.kind = "orchestration"
    api.attempts[1][0] = message("question-1", "user", WORDING, kind="orchestration")
    if deleted_answer:
        api.attempts[1] = api.attempts[1][:1]
    start(page, api)
    page.get_by_role("button", name="Retry", exact=True).first.click()
    approve = page.get_by_role("button", name="Approve and run the plan").first
    expect(approve).to_be_visible()
    expect(page.get_by_text("Fresh plan: review before running. Earlier completed actions are not undone and may be repeated.")).to_be_visible()
    assert len(api.calls(PLAN)) == 1
    assert not api.calls(editor_tests.RUN)
    assert not api.calls("/api/chat/stream")
    state = chat_state(page)
    assert [row["id"] for row in state["messages"]] == ["question-2", "later-question", "later-answer"]
    assert state["messages"][0]["metadata"]["response_attempt"]["state"] == "awaiting_review"
    approve.click()
    expect(page.get_by_text("A fresh orchestrated answer.", exact=True)).to_be_visible()
    assert api.calls(editor_tests.RUN)[0]["body"]["reviewed_regeneration"] is True
    assert [row["id"] for row in chat_state(page)["messages"]][:2] == ["question-2", "answer-2"]


def test_stop_before_preparation_ignores_late_response_and_reconciles_next_retry(retry_ui):
    page, api = retry_ui
    api.prepare_mode = "held"
    start(page, api)
    page.get_by_role("button", name="Retry", exact=True).first.click()
    expect(page.get_by_text(re.compile("Preparing retry"))).to_be_visible()
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().stopStreaming()")
    expect(page.get_by_text("The previous successful answer.", exact=True)).to_be_visible()
    api.release_preparations()
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    assert not api.calls("/api/chat/stream")
    api.prepare_mode = "ready"
    page.get_by_role("button", name="Retry", exact=True).first.click()
    expect(page.get_by_text("The regenerated answer.", exact=True)).to_be_visible()
    assert len(api.attempts) == 2
    assert len(api.calls("/api/chat/stream")) == 1


def test_fresh_plan_card_follows_its_selected_orchestration_attempt(retry_ui):
    page, api = retry_ui
    api.kind = "orchestration"
    api.attempts[1][0] = message("question-1", "user", WORDING, kind="orchestration")
    start(page, api)
    page.get_by_role("button", name="Retry", exact=True).first.click()
    approve = page.get_by_role("button", name="Approve and run the plan")
    expect(approve).to_be_visible()
    page.get_by_role("button", name="Previous attempt", exact=True).first.click()
    expect(page.get_by_text("The previous successful answer.", exact=True)).to_be_visible()
    expect(approve).not_to_be_visible()
    page.get_by_role("button", name="Next attempt", exact=True).first.click()
    expect(approve).to_be_visible()
    assert len(api.calls(PLAN)) == 1
    assert not api.calls(editor_tests.RUN)


def test_reload_reattaches_earlier_running_retry_to_its_question(retry_ui):
    page, api = retry_ui
    api.prepared()
    api.attempts[2][0]["metadata"]["response_attempt"]["state"] = "running"
    api.pending_stream = True
    start(page, api)
    page.evaluate("(conversation) => window.OrchHarness.stores.chat.useChatStore.getState().selectConversation(conversation)",
                  CONVERSATION)
    expect(page.get_by_text("The regenerated answer.", exact=True)).to_be_visible()
    state = chat_state(page)
    assert [row["id"] for row in state["messages"]] == ["question-2", "answer-2", "later-question", "later-answer"]
    assert state["retry"]["userMessageId"] == "question-2"
    assert not api.calls("/api/chat/stream")


def test_stop_keeps_partial_native_output_with_correct_attempt(retry_ui):
    page, api = retry_ui
    start(page, api)
    page.evaluate("""() => {
        const realFetch = window.fetch.bind(window);
        window.fetch = (input, options) => {
            if (new URL(typeof input === 'string' ? input : input.url, location.href).pathname !== '/api/chat/stream') {
                return realFetch(input, options);
            }
            return Promise.resolve(new Response(new ReadableStream({start(controller) {
                controller.enqueue(new TextEncoder().encode('data: {"content":"Partial retry output."}\\n\\n'));
                options.signal.addEventListener('abort', () => controller.error(new DOMException('Stopped', 'AbortError')));
            }}), {headers: {'Content-Type': 'text/event-stream'}}));
        };
    }""")
    page.get_by_role("button", name="Retry", exact=True).first.click()
    expect(page.get_by_text("Partial retry output.", exact=True)).to_be_visible()
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().stopStreaming()")
    expect(page.get_by_text("Partial retry output.", exact=True)).to_be_visible()
    state = chat_state(page)
    assert not state["streaming"]
    assert state["messages"][1]["metadata"]["thread_info"]["thread_attempt"] == 2
    assert state["messages"][1]["id"].startswith("cancelled-")
    assert state["messages"][0]["metadata"]["response_attempt"]["state"] == "interrupted"
    assert [row["id"] for row in state["messages"]][-2:] == ["later-question", "later-answer"]


def test_late_preparation_cannot_repopulate_a_new_chat(retry_ui):
    page, api = retry_ui
    api.prepare_mode = "held"
    start(page, api)
    page.get_by_role("button", name="Retry", exact=True).first.click()
    expect(page.get_by_text(re.compile("Preparing retry"))).to_be_visible()
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().startNewConversation()")
    api.release_preparations()
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    assert chat_state(page)["messages"] == []
    assert chat_state(page)["retry"] is None
    assert not api.calls("/api/chat/stream")


def test_late_orchestration_callbacks_cannot_settle_a_newer_turn(retry_ui):
    page, api = retry_ui
    start(page, api)
    page.evaluate("""(conversation) => {
        const chat = window.OrchHarness.stores.chat.useChatStore.getState();
        chat.beginOrchestrationTurn(conversation, 'Newer planning question', undefined, true, 'current-turn');
        chat.pushOrchestrationThought(conversation, {turn_id: 'earlier-turn', content: 'Stale thought'});
        chat.pushOrchestrationContent(conversation, 'Stale content', 'earlier-turn');
        chat.settleOrchestrationTurn(conversation, {turnId: 'earlier-turn', status: 'failed', error: 'Stale failure'});
    }""", CONVERSATION)
    state = chat_state(page)
    assert state["streaming"]
    assert state["error"] is None
    expect(page.get_by_text("Stale thought", exact=True)).not_to_be_visible()
    expect(page.get_by_text("Stale content", exact=True)).not_to_be_visible()
    expect(page.get_by_text("Stale failure", exact=True)).not_to_be_visible()
