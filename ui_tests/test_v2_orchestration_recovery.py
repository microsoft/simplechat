# test_v2_orchestration_recovery.py
"""
Real-component browser coverage for orchestration failure and checkpoint recovery.
Version: 0.261.105
Implemented in: 0.261.105

The production controller, SSE reader, stores, message list, and Run drawer execute
in the existing local/Azure Playwright harness. Only API responses are deterministic.
The companion backend test forwards those requests to the actual Flask routes.
"""

import copy
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
CONVERSATION = "recovery-chat"
TURN = "recovery-turn"
FAILURE = "The selected agent did not finish before this step's time limit."


class RecoveryApi:
    """Saved attempts plus explicit gates for stream loss and concurrent requests."""

    def __init__(self, assets):
        self.assets = assets
        self.plan = editor_tests.make_plan(CONVERSATION, TURN)
        self.plan["steps"][1].update(capability_id="agent", title="Ask the selected agent")
        self.records = {}
        self.steps = {}
        self.messages = [{
            "id": "user-original", "conversation_id": CONVERSATION, "role": "user",
            "content": "Compare quarterly reports.", "metadata": {"orchestration_turn_id": TURN},
        }]
        self.requests = []
        self.errors = []
        self.preparations = {}
        self.prepare_mode = "success"
        self.stream_mode = "failure"
        self.waiting = []
        self.add_record(self.plan)

    def add_record(self, plan, attempt=1, retry_of=None):
        record = {
            "run_id": plan["run_id"], "conversation_id": CONVERSATION, "turn_id": TURN,
            "status": plan["status"], "plan": copy.deepcopy(plan), "turn_index": 0,
            "created_at": f"2026-09-08T12:00:0{attempt}Z", "started_at": None, "completed_at": None,
            "user_message_id": "user-original", "user_message": "Compare quarterly reports.",
            "assistant_message_id": None, "attempt_index": attempt, "retry_of_run_id": retry_of,
            "plan_summary": {
                "plan_id": plan["plan_id"], "turn_id": TURN, "step_count": 3,
                "intent_summary": plan["intent"]["summary"], "status": plan["status"],
            }, "capabilities_used": [], "artifact_count": 0, "approval": plan["approval"], "revision": 0,
        }
        self.records[plan["run_id"]] = record
        self.steps[plan["run_id"]] = []
        return record

    def recovery(self, run_id):
        return {
            "eligible": True, "reason_code": None, "message": "Completed steps were saved.",
            "expected_version": "recovery-v1", "source_run_id": run_id,
            "retry_step_ids": ["research", "answer"], "reused_step_ids": ["read"],
            "requires_confirmation": True,
        }

    def finish(self, run_id, status="failed"):
        record = self.records[run_id]
        record.update(
            status=status, outcome=status, completed_at="2026-09-08T12:01:00Z",
            finalization_status="saved", message_saved=True,
        )
        record["plan"]["status"] = status
        record["plan_summary"]["status"] = status
        failure = {"code": "step_timeout", "message": FAILURE, "step_id": "research"}
        record["failure"] = failure if status == "failed" else None
        record["failures"] = [failure] if status == "failed" else []
        record["recovery"] = self.recovery(run_id)
        if status == "completed":
            record["recovery"].update(
                eligible=False, reason_code="already_completed", message="This request is already complete.",
            )
        self.steps[run_id] = [
            {"step_id": "read", "step_index": 0, "status": "completed", "summary": "Read saved reports",
             "reused": bool(record["retry_of_run_id"]), "checkpoint_available": True},
            {"step_id": "research", "step_index": 1, "status": status, "summary": "",
             "failure": record["failure"]},
            {"step_id": "answer", "step_index": 2,
             "status": "completed" if status == "completed" else "skipped", "summary": ""},
        ]
        content = "Comparison from saved reports and the recovered agent." if status == "completed" else (
            "This run was stopped. Available partial results were kept." if status == "cancelled" else FAILURE)
        metadata = {"orchestration": {
            key: record[key] for key in ("run_id", "turn_id", "attempt_index", "retry_of_run_id",
                                        "outcome", "failure", "failures", "recovery",
                                        "finalization_status", "message_saved") if key in record
        }}
        message_id = f"assistant-{run_id}"
        record["assistant_message_id"] = message_id
        message = {
            "id": message_id, "conversation_id": CONVERSATION, "role": "assistant", "content": content,
            "metadata": metadata, "model_deployment_name": "original-model",
            "hybrid_citations": [{"document_id": "doc-a", "title": "Saved Report A"}],
        }
        self.messages = [message for message in self.messages if message["id"] != message_id] + [message]
        return {
            **metadata["orchestration"], "status": status, "done": True, "type": "orchestration_done",
            "message_id": message_id, "user_message_id": "user-original", "full_content": content,
            "metadata": metadata, "model_deployment_name": "original-model",
            "hybrid_citations": message["hybrid_citations"],
        }

    def begin_finalization(self, run_id, status):
        self.finish(run_id, status)
        record = self.records[run_id]
        self.messages = [message for message in self.messages if message["id"] != record["assistant_message_id"]]
        record.update(assistant_message_id=None, finalization_status="pending")
        record.pop("message_saved", None)
        record["recovery"].update(
            eligible=False, reason_code="execution_live",
            message="This attempt is still running. Wait for it to finish or stop it.",
        )

    @staticmethod
    def stream(route, events):
        route.fulfill(content_type="text/event-stream",
                      body="".join(f"data: {json.dumps(event)}\n\n" for event in events))

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        body = request.post_data_json if request.post_data else None
        self.requests.append({"path": path, "method": request.method, "body": body})
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        if path == editor_tests.RUN:
            record = self.records[body["run_id"]]
            if record["retry_of_run_id"]:
                assert "edits" not in body, "Recovery must execute the immutable saved plan."
                assert body.get("expected_version") == record["plan"]["edit_version"], (
                    "Recovery must use the new child's approval version, not the source recovery token."
                )
            if self.stream_mode == "reject" and record["retry_of_run_id"]:
                route.fulfill(status=409, json={"code": "recovery_unavailable"})
                return
            record.update(status="running", started_at="2026-09-08T12:00:30Z")
            if self.stream_mode == "transport":
                self.stream(route, [{"type": "content", "content": "Partial result before disconnect."}])
            else:
                status = "completed" if record["retry_of_run_id"] else "failed"
                event = self.finish(body["run_id"], status)
                events = [{"type": "orchestration_step", **step} for step in self.steps[body["run_id"]]]
                self.stream(route, events + [event])
            return
        if path.endswith("/retry"):
            run_id = path.split("/")[-2]
            if self.prepare_mode == "confirmation":
                self.records[run_id]["recovery"]["requires_confirmation"] = True
                route.fulfill(status=409, json={
                    "code": "confirmation_required", "recovery": self.records[run_id]["recovery"],
                })
                return
            if self.prepare_mode == "conflict":
                self.records[run_id]["recovery"].update(eligible=False, current_run_id="other-attempt")
                route.fulfill(status=409, json={"code": "recovery_changed", "current_run_id": "other-attempt"})
                return
            if body["submission_id"] in self.preparations:
                assert self.preparations[body["submission_id"]][0] == body
                route.fulfill(json={"run": self.preparations[body["submission_id"]][1]})
                return
            assert body["confirm_external_effects"], "Uncertain effects require explicit consent."
            child_plan = copy.deepcopy(self.records[run_id]["plan"])
            child_plan.update(
                run_id="retry-attempt", plan_id="retry-plan", status="awaiting_approval",
                edit_version="retry-plan-version",
            )
            child_plan["approval"] = {"mode": "manual", "timeout_seconds": 0, "state": "pending"}
            child = self.add_record(child_plan, 2, run_id)
            self.preparations[body["submission_id"]] = (body, copy.deepcopy(child))
            self.records[run_id].update(latest_attempt_run_id=child["run_id"])
            self.records[run_id]["recovery"].update(eligible=False, current_run_id=child["run_id"])
            if self.prepare_mode == "lost":
                route.abort()
            elif self.prepare_mode == "delayed":
                self.waiting.append(lambda: route.fulfill(json={"run": child}))
            else:
                route.fulfill(json={"run": child})
            return
        if path.startswith("/api/v2/orchestration/cancel/"):
            self.finish(path.rsplit("/", 1)[-1], "cancelled")
            route.fulfill(json={"cancelled": True})
            return
        if path == editor_tests.RUNS:
            route.fulfill(json={"runs": list(self.records.values())})
            return
        if path.startswith(editor_tests.RUNS + "/"):
            run_id = path.split("/")[5]
            if path.endswith("/steps"):
                route.fulfill(json={"steps": self.steps.get(run_id, [])})
            elif run_id in self.records:
                route.fulfill(json={"run": self.records[run_id]})
            else:
                route.fulfill(status=404, json={"code": "not_found"})
            return
        if path in ("/api/get_messages", "/api/v2/chat/messages"):
            route.fulfill(json={"messages": self.messages})
            return
        self.errors.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test request"})

    def calls(self, suffix):
        return [request for request in self.requests if request["path"].endswith(suffix)]

    def release(self):
        waiting, self.waiting = self.waiting, []
        for callback in waiting:
            callback()


@pytest.fixture
def recovery_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = RecoveryApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


def mount_recovery(page, api, *, saved=False):
    page.goto(editor_tests.ORIGIN + editor_tests.HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=editor_tests.ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.105', settings: {}, branding: { app_title: 'SimpleChat' },
                features: { enable_chat_orchestration: true },
                user: { id: 'editor-tester', display_name: 'Tester' },
                scope: { groups: [], public_workspaces: [] },
                orchestration: { enabled: true, capabilities: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: 'personal',
                messagesLoading: false, streaming: false, streamingContent: '', thoughts: [],
                streamError: null, messages: spec.messages, conversations: [],
            });
            if (!spec.saved) {
                const S = H.stores.orchestration.useOrchestrationStore.getState();
                S.setPlan(spec.conversation, spec.turn, spec.plan);
                S.setActiveTurn(spec.conversation, spec.turn);
            }
            H.mount('mount-a', 'PlanEditorExperience', {}, { strictMode: true });
        }""",
        {"plan": api.plan, "messages": api.messages, "conversation": api.plan["conversation_id"],
         "turn": api.plan["turn_id"], "saved": saved},
    )
    if saved:
        page.evaluate("(id) => window.OrchHarness.resume.resumeOrchestrationForConversation(id)", api.plan["conversation_id"])


def start_failure(page, api):
    mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_text(FAILURE, exact=True).first).to_be_visible()
    expect(page.get_by_role("button", name="Retry from failed step").first).to_be_enabled()


def main_state(page):
    return page.evaluate("""() => {
        const H = window.OrchHarness;
        return { messages: H.stores.chat.useChatStore.getState().messages,
            history: H.stores.orchestration.useOrchestrationStore.getState().history,
            inFlight: H.stores.orchestration.useOrchestrationStore.getState().inFlight };
    }""")


@pytest.mark.parametrize("edit_version", [None, "saved-plan-edit"])
def test_failure_persists_in_main_and_drawer_and_confirmed_retry_reuses_progress(recovery_ui, edit_version):
    page, api = recovery_ui
    start_failure(page, api)
    if edit_version:
        api.records[api.plan["run_id"]]["plan"]["edit_version"] = edit_version
    assert main_state(page)["history"][CONVERSATION][0]["status"] == "failed"
    failed_message = main_state(page)["messages"][-1]
    assert failed_message["metadata"]["orchestration"]["outcome"] == "failed"
    assert failed_message["hybrid_citations"][0]["document_id"] == "doc-a"
    page.get_by_role("button", name="Review saved attempt").first.click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    expect(drawer.get_by_text(FAILURE, exact=True)).to_be_visible()
    expect(drawer.locator("p").filter(has_text="Reuse saved results:")).to_contain_text("Read quarterly reports")
    drawer.get_by_role("button", name="Retry from failed step").click()
    dialog = page.get_by_role("dialog", name="Retry this failed step?")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_text("Previously completed plan steps", exact=False)).to_be_visible()
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    assert not api.calls("/retry")
    drawer.get_by_role("button", name="Retry from failed step").click()
    page.get_by_role("dialog").get_by_role("button", name="Confirm retry").click()
    expect(page.get_by_text("Comparison from saved reports and the recovered agent.", exact=True)).to_be_visible()
    expect(drawer.get_by_text("Reused saved result", exact=True)).to_be_visible()
    assert len(api.calls("/retry")) == 1
    assert [entry["body"]["run_id"] for entry in api.calls("/run")] == [api.plan["run_id"], "retry-attempt"]
    assert api.calls("/run")[1]["body"]["expected_version"] == "retry-plan-version"
    state = main_state(page)
    assert len([message for message in state["messages"] if message["role"] == "user"]) == 1
    assert len([message for message in state["messages"] if message["role"] == "assistant"]) == 2
    assert state["messages"][-1]["model_deployment_name"] == "original-model"


def test_reload_keeps_failure_without_automatic_retry_and_message_retry_is_not_plain_chat(recovery_ui):
    page, api = recovery_ui
    api.finish(api.plan["run_id"])
    api.plan["approval"]["mode"] = "auto"
    mount_recovery(page, api, saved=True)
    expect(page.get_by_role("button", name="Retry from failed step").first).to_be_enabled()
    assert not api.calls("/run") and not api.calls("/retry")
    page.get_by_role("button", name="Review orchestration recovery").click(force=True)
    expect(page.get_by_role("complementary", name="Review drawer")).to_be_visible()
    assert not any("/api/message/" in request["path"] for request in api.requests)


def test_duplicate_confirmation_click_and_context_change_never_run_wrong_turn(recovery_ui):
    page, api = recovery_ui
    start_failure(page, api)
    api.prepare_mode = "delayed"
    page.get_by_role("button", name="Retry from failed step").click()
    dialog = page.get_by_role("dialog")
    with page.expect_request("**/retry"):
        dialog.get_by_role("button", name="Confirm retry").dblclick()
    expect(dialog.get_by_role("button", name="Confirm retry")).to_be_disabled()
    page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.setState({
        activeConversationId: 'different-conversation'
    })""")
    api.release()
    page.wait_for_function("""() => !window.OrchHarness.stores.orchestration.useOrchestrationStore
        .getState().runRecovery['recovery-chat-run-0'].busy""")
    assert len(api.calls("/retry")) == 1
    assert len(api.calls("/run")) == 1
    assert len([message for message in main_state(page)["messages"] if message["role"] == "user"]) == 1


@pytest.mark.parametrize("mode", ["conflict", "lost"])
def test_recovery_conflict_and_lost_preparation_keep_previous_failure(recovery_ui, mode):
    page, api = recovery_ui
    start_failure(page, api)
    api.prepare_mode = mode
    page.get_by_role("button", name="Retry from failed step").click()
    with page.expect_request("**/retry"):
        page.get_by_role("dialog").get_by_role("button", name="Confirm retry").click()
    expect(page.get_by_role("alert").filter(has_text="Recovery").first).to_be_visible()
    assert len(api.calls("/run")) == 1
    assert main_state(page)["messages"][-1]["content"] == FAILURE
    if mode == "conflict":
        expect(page.get_by_role("button", name="View current attempt").first).to_be_visible()
    else:
        api.prepare_mode = "success"
        page.get_by_role("button", name="Retry from failed step").click()
        expect(page.get_by_text("Comparison from saved reports and the recovered agent.", exact=True)).to_be_visible()
        assert api.calls("/retry")[0]["body"] == api.calls("/retry")[1]["body"]
        assert len(api.preparations) == 1


def test_transport_loss_is_unknown_until_explicit_stop_calls_backend(recovery_ui):
    page, api = recovery_ui
    api.stream_mode = "transport"
    mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_text("Checking execution status", exact=False).first).to_be_visible()
    expect(page.get_by_role("button", name="Retry from failed step")).to_have_count(0)
    assert not api.calls("/retry")
    assert not any("/cancel/" in request["path"] for request in api.requests)
    assert not main_state(page)["history"].get(CONVERSATION)
    page.get_by_role("button", name="Stop execution").first.click()
    expect(page.get_by_text("This attempt was stopped", exact=False).first).to_be_visible()
    assert len([request for request in api.requests if "/cancel/" in request["path"]]) == 1
    assert main_state(page)["history"][CONVERSATION][0]["status"] == "cancelled"


def test_legacy_history_explains_cannot_resume_without_inventing_reason(recovery_ui):
    page, api = recovery_ui
    api.finish(api.plan["run_id"], "cancelled")
    record = api.records[api.plan["run_id"]]
    for key in ("recovery", "outcome", "failure", "failures"):
        record.pop(key, None)
    api.messages = api.messages[:1]
    mount_recovery(page, api, saved=True)
    expect(page.get_by_text("This historical attempt has no verified recovery checkpoint.", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Retry from failed step")).to_have_count(0)
    assert not api.calls("/run") and not api.calls("/retry")


def test_server_confirmation_required_is_a_gate_not_an_automatic_retry(recovery_ui):
    page, api = recovery_ui
    api.finish(api.plan["run_id"])
    api.records[api.plan["run_id"]]["recovery"]["requires_confirmation"] = False
    api.prepare_mode = "confirmation"
    mount_recovery(page, api, saved=True)
    page.get_by_role("button", name="Retry from failed step").click()
    dialog = page.get_by_role("dialog", name="Retry this failed step?")
    expect(dialog).to_be_visible()
    assert len(api.calls("/retry")) == 1
    assert api.calls("/retry")[0]["body"]["confirm_external_effects"] is False
    assert not api.preparations and not api.calls("/run")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    assert not api.preparations


def test_transport_terminal_reconciliation_keeps_saved_failure_and_no_stop(recovery_ui):
    page, api = recovery_ui
    api.stream_mode = "transport"
    mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_text("Checking execution status", exact=False).first).to_be_visible()
    api.finish(api.plan["run_id"])
    page.get_by_role("button", name="Check saved status").first.click()
    expect(page.get_by_role("button", name="Retry from failed step").first).to_be_enabled()
    assert main_state(page)["history"][CONVERSATION][0]["status"] == "failed"
    assert main_state(page)["messages"][-1]["id"] == f"assistant-{api.plan['run_id']}"
    assert not any("/cancel/" in request["path"] for request in api.requests)
    assert not api.calls("/retry")


@pytest.mark.parametrize("pending_contract", ["explicit", "lease-only"])
@pytest.mark.parametrize("status", ["failed", "completed", "cancelled"])
def test_terminal_status_waits_for_final_publication_after_transport_loss(recovery_ui, status, pending_contract):
    page, api = recovery_ui
    api.stream_mode = "transport"
    page.clock.install()
    mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_text("Checking execution status", exact=False).first).to_be_visible()

    run_id = api.plan["run_id"]
    api.begin_finalization(run_id, status)
    if pending_contract == "lease-only":
        api.records[run_id].pop("finalization_status")
    page.get_by_role("button", name="Check saved status").first.click()
    try:
        expect(page.get_by_text("Checking execution status", exact=False).first).to_be_visible()
    except AssertionError as error:
        raise AssertionError({
            "state": main_state(page),
            "recovery": page.evaluate("""() => window.OrchHarness.stores.orchestration
                .useOrchestrationStore.getState().runRecovery"""),
            "visible": page.locator("body").inner_text(),
        }) from error
    expect(page.get_by_text("The server is saving the final response.", exact=False).first).to_be_visible()
    assert run_id in main_state(page)["inFlight"]
    assert not main_state(page)["history"].get(CONVERSATION)
    expect(page.get_by_text("message was not saved", exact=False)).to_have_count(0)
    expect(page.get_by_role("button", name="Retry from failed step")).to_have_count(0)
    page.evaluate("""(record) => {
        const S = window.OrchHarness.stores.orchestration.useOrchestrationStore;
        S.setState({ inFlight: { ...S.getState().inFlight,
            [record.run_id]: { ...S.getState().inFlight[record.run_id], resumed: true } } });
        S.getState().hydrateConversationRuns(record.conversation_id, [record]);
    }""", api.records[run_id])
    assert run_id in main_state(page)["inFlight"]

    api.finish(run_id, status)
    page.clock.fast_forward(5001)
    page.wait_for_function("""(id) => window.OrchHarness.stores.chat.useChatStore
        .getState().messages.some(message => message.id === id)""", arg=f"assistant-{run_id}")
    assert not main_state(page)["inFlight"]
    assert main_state(page)["history"][CONVERSATION][0]["status"] == status
    if status == "failed":
        expect(page.get_by_role("button", name="Retry from failed step").first).to_be_enabled()
    assert len(api.calls("/run")) == 1
    assert not api.calls("/retry")
    assert not any("/cancel/" in request["path"] for request in api.requests)


@pytest.mark.parametrize("status", ["failed", "completed", "cancelled"])
def test_reload_keeps_polling_until_terminal_publication_is_saved(recovery_ui, status):
    page, api = recovery_ui
    run_id = api.plan["run_id"]
    api.records[run_id]["started_at"] = "2026-09-08T12:00:30Z"
    api.begin_finalization(run_id, status)
    page.clock.install()
    mount_recovery(page, api, saved=True)
    expect(page.get_by_text("Checking execution status", exact=False).first).to_be_visible()
    assert run_id in main_state(page)["inFlight"]
    expect(page.get_by_role("button", name="Retry from failed step")).to_have_count(0)

    api.finish(run_id, status)
    page.clock.fast_forward(5001)
    page.wait_for_function("""(id) => window.OrchHarness.stores.chat.useChatStore
        .getState().messages.some(message => message.id === id)""", arg=f"assistant-{run_id}")
    assert not main_state(page)["inFlight"]
    assert not api.calls("/run") and not api.calls("/retry")
    assert not any("/cancel/" in request["path"] for request in api.requests)


def test_expired_publication_reports_uncertainty_instead_of_an_unsaved_claim(recovery_ui):
    page, api = recovery_ui
    api.stream_mode = "transport"
    mount_recovery(page, api)
    page.get_by_role("button", name="Approve and run the plan").click()
    expect(page.get_by_text("Checking execution status", exact=False).first).to_be_visible()
    run_id = api.plan["run_id"]
    api.begin_finalization(run_id, "failed")
    api.records[run_id]["finalization_status"] = "interrupted"
    api.records[run_id]["recovery"] = api.recovery(run_id)
    page.get_by_role("button", name="Check saved status").first.click()
    expect(page.get_by_text("before a final conversation message could be confirmed", exact=False).first).to_be_visible()
    expect(page.get_by_text("message was not saved", exact=False)).to_have_count(0)
    assert not main_state(page)["inFlight"]
    assert not api.calls("/retry")


def test_failure_text_is_inert_and_confirmation_is_keyboard_accessible_on_mobile(recovery_ui):
    page, api = recovery_ui
    api.finish(api.plan["run_id"])
    sentinel = '<img src=x onerror="window.recoveryExecuted=true">'
    api.records[api.plan["run_id"]]["failure"]["message"] = sentinel
    page.set_viewport_size({"width": 390, "height": 844})
    mount_recovery(page, api, saved=True)
    expect(page.get_by_text(sentinel, exact=True)).to_be_visible()
    expect(page.locator('[onerror]')).to_have_count(0)
    assert page.evaluate("window.recoveryExecuted") is None
    retry = page.get_by_role("button", name="Retry from failed step")
    retry.focus()
    page.keyboard.press("Enter")
    dialog = page.get_by_role("dialog", name="Retry this failed step?")
    expect(dialog).to_be_visible()
    assert dialog.evaluate("(node) => node.contains(document.activeElement)")
    page.keyboard.press("Escape")
    expect(dialog).to_have_count(0)
    assert not api.calls("/retry")


@pytest.mark.parametrize("edit_version", [None, "saved-plan-edit"])
def test_prepared_child_after_navigation_requires_manual_run_even_after_reload(recovery_ui, edit_version):
    page, api = recovery_ui
    start_failure(page, api)
    if edit_version:
        api.records[api.plan["run_id"]]["plan"]["edit_version"] = edit_version
    api.prepare_mode = "delayed"
    page.get_by_role("button", name="Retry from failed step").click()
    with page.expect_request("**/retry"):
        page.get_by_role("dialog").get_by_role("button", name="Confirm retry").click()
    page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.setState({
        activeConversationId: 'different-conversation'
    })""")
    api.release()
    page.wait_for_function("""() => !window.OrchHarness.stores.orchestration.useOrchestrationStore
        .getState().runRecovery['recovery-chat-run-0'].busy""")
    mount_recovery(page, api, saved=True)
    expect(page.get_by_role("button", name="View current attempt").first).to_be_visible()
    assert len(api.calls("/run")) == 1
    page.get_by_role("button", name="View current attempt").first.click()
    drawer = page.get_by_role("complementary", name="Review drawer")
    drawer.get_by_role("button", name="Run prepared retry").click()
    expect(page.get_by_text("Comparison from saved reports and the recovered agent.", exact=True)).to_be_visible()
    assert len(api.calls("/retry")) == 1
    assert len(api.calls("/run")) == 2
    assert api.calls("/run")[-1]["body"]["expected_version"] == "retry-plan-version"


def test_prepared_run_rejection_reports_error_without_false_success_or_polling(recovery_ui):
    page, api = recovery_ui
    start_failure(page, api)
    api.stream_mode = "reject"
    page.get_by_role("button", name="Retry from failed step").click()
    page.get_by_role("dialog").get_by_role("button", name="Confirm retry").click()
    expect(page.get_by_text("The saved attempt was not started.", exact=False).first).to_be_visible()
    state = main_state(page)
    assert not state["inFlight"]
    assert state["history"][CONVERSATION][0]["status"] == "failed"
    assert state["messages"][-1]["content"] == FAILURE
