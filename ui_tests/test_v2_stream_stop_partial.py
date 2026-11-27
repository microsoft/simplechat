# test_v2_stream_stop_partial.py
"""
UI regression for retaining V2 partial output after the reader stops a stream.
Version: 0.261.430
Implemented in: 0.261.429

Drives the real V2 store, SSE reader, and MessageList with a local stream that
never emits its terminal event. Stopping must retain the accumulated text
without relying on a late cancelled frame.
"""

from copy import deepcopy
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.orchestration import harness_build
from ui_tests.fixtures.chat_stop_runtime import stop_modules, stop_world  # noqa: F401


pytestmark = pytest.mark.ui


@pytest.fixture
def stopped_stream_page(page):
    harness_build.ensure_bundle()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    with harness_build.start_static_server() as origin:
        response = page.goto(f"{origin}/{harness_build.HARNESS_HTML_REL}")
        assert response is not None and response.ok
        page.wait_for_function("() => Boolean(window.OrchHarness)")
        yield page
    assert not errors, errors


@pytest.mark.parametrize("cancel_status", [200, 404, 503])
def test_v2_stop_preserves_partial_output_without_terminal_event(stopped_stream_page, cancel_status):
    page = stopped_stream_page
    page.evaluate(
        """(cancelStatus) => {
            const H = window.OrchHarness;
            H.reset();
            window.stopRequests = [];
            window.fetch = async (url, init = {}) => {
                const path = new URL(String(url), window.location.origin).pathname;
                if (path === '/api/chat/stream') {
                    const body = new ReadableStream({
                        start(controller) {
                            controller.enqueue(new TextEncoder().encode(
                                'data: ' + JSON.stringify({
                                    conversation_id: 'stop-chat',
                                    content: 'Partial answer',
                                }) + '\\n\\n'
                            ));
                        },
                    });
                    return new Response(body, {
                        headers: { 'Content-Type': 'text/event-stream' },
                    });
                }
                if (path === '/api/chat/stream/cancel/stop-chat') {
                    window.stopRequests.push({ path, method: init.method || 'GET' });
                    return new Response(JSON.stringify({ success: cancelStatus === 200, outcome: cancelStatus === 200 ? 'accepted' : 'unconfirmed' }), {
                        status: cancelStatus,
                        headers: { 'Content-Type': 'application/json' },
                    });
                }
                return new Response(JSON.stringify({
                    success: true,
                    messages: [],
                    pending_actions: [],
                }), {
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            H.stores.bootstrap.useBootstrapStore.setState({
                data: {
                    features: {},
                    settings: {},
                    catalogs: { models: [], agents: [], prompts: [] },
                    user: { id: 'owner', display_name: 'Tester' },
                    scope: {},
                },
            });
            H.stores.chat.useChatStore.setState({
                activeConversationId: 'stop-chat',
                activeConversationKind: 'personal',
                messages: [],
                streaming: false,
                streamingContent: '',
                retryPresentation: null,
                thoughts: [],
            });
            H.mount('mount-a', 'MessageList');
            void H.stores.chat.useChatStore.getState().sendMessage('Keep this partial answer.', {});
        }""",
        cancel_status,
    )
    page.wait_for_function(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().streamingContent === 'Partial answer'"
    )

    page.evaluate(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().stopStreaming()"
    )
    page.wait_for_function(
        """() => {
            const state = window.OrchHarness.stores.chat.useChatStore.getState();
            return !state.streaming && state.messages.some(message =>
                message.role === 'assistant'
                && message.content === 'Partial answer'
                && ['stopped', 'stop_unconfirmed'].includes(message.metadata?.stream_status)
            );
        }"""
    )
    page.wait_for_timeout(500)

    state = page.evaluate(
        """() => {
            const state = window.OrchHarness.stores.chat.useChatStore.getState();
            const reply = state.messages.find(message =>
                message.role === 'assistant' && message.content === 'Partial answer'
            );
            return {
                requests: window.stopRequests,
                streaming: state.streaming,
                streamingContent: state.streamingContent,
                metadata: reply?.metadata,
            };
        }"""
    )
    assert state["requests"] == [{"path": "/api/chat/stream/cancel/stop-chat", "method": "POST"}]
    assert state["streaming"] is False
    assert state["streamingContent"] == ""
    assert state["metadata"]["complete"] is False
    assert state["metadata"]["stop_reason"] == ("user_cancelled" if cancel_status == 200 else "cancellation_unconfirmed")
    assert page.get_by_text("Partial answer", exact=True).count() == 1
    assert page.get_by_text("Stopped by you. Response may be incomplete.", exact=True).count() == (1 if cancel_status == 200 else 0)
    if cancel_status != 200:
        expect(page.get_by_role("status").filter(has_text="Stopping is not confirmed. Refresh to check saved work.")).to_be_visible()


def test_v2_stop_before_first_token_marks_user_turn_without_blank_assistant(stopped_stream_page):
    page = stopped_stream_page
    page.evaluate(
        """() => {
            const H = window.OrchHarness;
            H.reset();
            window.fetch = async (url, init = {}) => {
                const path = new URL(String(url), window.location.origin).pathname;
                if (path === '/api/chat/stream') {
                    return new Response(new ReadableStream({ start() {} }), {
                        headers: { 'Content-Type': 'text/event-stream' },
                    });
                }
                return new Response(JSON.stringify({ success: true, outcome: 'accepted', messages: [], pending_actions: [] }), {
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            H.stores.bootstrap.useBootstrapStore.setState({
                data: {
                    features: {},
                    settings: {},
                    catalogs: { models: [], agents: [], prompts: [] },
                    user: { id: 'owner', display_name: 'Tester' },
                    scope: {},
                },
            });
            H.stores.chat.useChatStore.setState({
                activeConversationId: 'stop-before-token',
                activeConversationKind: 'personal',
                messages: [],
                streaming: false,
                streamingContent: '',
                retryPresentation: null,
                thoughts: [],
            });
            H.mount('mount-a', 'MessageList');
            void H.stores.chat.useChatStore.getState().sendMessage('Stop this request.', {});
        }"""
    )
    page.wait_for_function(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().streaming === true"
    )
    page.evaluate(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().stopStreaming()"
    )
    page.wait_for_function(
        """() => {
            const state = window.OrchHarness.stores.chat.useChatStore.getState();
            return !state.streaming
                && state.messages.some(message =>
                    message.role === 'user'
                    && message.metadata?.response_attempt?.state === 'interrupted'
                );
        }"""
    )
    state = page.evaluate(
        """() => {
            const state = window.OrchHarness.stores.chat.useChatStore.getState();
            return {
                assistants: state.messages.filter(message => message.role === 'assistant').length,
                user: state.messages.find(message => message.role === 'user'),
            };
        }"""
    )
    assert state["assistants"] == 0
    assert state["user"]["metadata"]["response_attempt"]["state"] == "interrupted"


def test_v2_real_persisted_history_survives_fresh_reload_and_later_turn(stopped_stream_page, stop_world):
    page, world = stopped_stream_page, stop_world
    old_question = deepcopy(world.question)
    old_question.update(id="older-question", content="Older question", timestamp="2026-11-16T19:00:00Z")
    old_question["metadata"]["thread_info"]["thread_id"] = "older-thread"
    old_answer = deepcopy(world.reply)
    old_answer.update(id="older-reply", content="Original older answer", timestamp="2026-11-16T19:00:01Z")
    old_answer["metadata"]["thread_info"]["thread_id"] = "older-thread"
    world.messages.create_item(body=old_question)
    world.messages.create_item(body=old_answer)
    store = world.store()
    store.begin({"message": "Question A"}, world.question)
    assert store.dispatch()
    canceled = world.app.test_client().post("/api/chat/stream/cancel/chat", json={"submission_id": "submission-a"})
    assert canceled.status_code == 200 and canceled.json["outcome"] == "accepted"
    partial = deepcopy(world.reply)
    partial["metadata"].update(incomplete=True, canceled=True, cancel_reason="user_requested")
    store.commit(partial)

    def api_request(route):
        parsed = urlsplit(route.request.url)
        if parsed.path == "/api/get_messages":
            response = world.app.test_client().get(f"{parsed.path}?{parsed.query}")
            route.fulfill(status=response.status_code, content_type="application/json", body=response.get_data())
        else:
            route.fulfill(status=200, json={"success": True, "pending_actions": []})

    page.route("**/api/**", api_request)

    def open_saved_history():
        page.wait_for_function("() => Boolean(window.OrchHarness)")
        page.evaluate("""async () => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                features: {}, settings: {}, catalogs: { models: [], agents: [], prompts: [] },
                user: { id: 'owner', display_name: 'Tester' }, scope: {},
            }});
            H.stores.chat.useChatStore.setState({
                activeConversationId: 'chat', activeConversationKind: 'personal', messages: [],
                streaming: false, streamingContent: '', retryPresentation: null, thoughts: [],
            });
            H.mount('mount-a', 'MessageList');
            await H.stores.chat.useChatStore.getState().reloadMessages();
        }""")

    open_saved_history()
    expect(page.get_by_text("Safe partial answer", exact=True)).to_have_count(1)
    expect(page.get_by_text("Stopped by you. Response may be incomplete.", exact=True)).to_have_count(1)
    page.reload()
    open_saved_history()
    expect(page.get_by_text("Stopped by you. Response may be incomplete.", exact=True)).to_have_count(1)
    expect(page.get_by_text("Original older answer", exact=True)).to_have_count(1)

    later = world.store("submission-b")
    question = deepcopy(world.question)
    question.update(id="question-b", content="Later question", timestamp="2026-11-16T20:00:02Z")
    question["metadata"]["thread_info"]["thread_id"] = "thread-b"
    later.begin({"message": "Later question"}, question)
    assert later.dispatch()
    answer = deepcopy(world.reply)
    answer.update(id="reply-b", content="Later completed answer", timestamp="2026-11-16T20:00:03Z")
    later.commit(answer)
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().reloadMessages()")
    expect(page.get_by_text("Later completed answer", exact=True)).to_have_count(1)
    expect(page.get_by_text("Safe partial answer", exact=True)).to_have_count(1)
    expect(page.get_by_text("Stopped by you. Response may be incomplete.", exact=True)).to_have_count(1)
    rows = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().messages")
    assert [row["id"] for row in rows] == ["older-question", "older-reply", "question-a", "reply-a", "question-b", "reply-b"]
    assert rows[1]["timestamp"] == old_answer["timestamp"]


@pytest.mark.parametrize("inference_api", ["chat_completions", "responses"])
def test_v2_provider_interruption_retains_persisted_partial_without_user_stop_label(
    stopped_stream_page, stop_world, inference_api,
):
    page, world = stopped_stream_page, stop_world

    def request_api(route):
        parsed = urlsplit(route.request.url)
        if parsed.path == "/api/chat/stream":
            body = route.request.post_data_json
            store = world.store(body["submission_id"])
            store.begin({"message": body["message"]}, world.question, assistant_message_id="reply-a")
            assert store.dispatch()
            partial = deepcopy(world.reply)
            partial["metadata"].update(incomplete=True, model_selection={"inference_api": inference_api})
            saved = store.commit(partial)
            frames = [
                {"type": "user_message_persisted", "conversation_id": "chat", "user_message_id": "question-a", "message_persisted": True},
                {"conversation_id": "chat", "content": saved["content"]},
                {"error": "Provider response interrupted.", "interrupted": True, "message_persisted": True,
                 "conversation_id": "chat", "message_id": saved["id"], "user_message_id": "question-a",
                 "partial_content": saved["content"], "metadata": saved["metadata"]},
            ]
            route.fulfill(status=200, content_type="text/event-stream",
                          body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames))
        elif parsed.path == "/api/get_messages" or parsed.path.startswith("/api/chat/stream/status/"):
            response = world.app.test_client().get(f"{parsed.path}?{parsed.query}")
            route.fulfill(status=response.status_code, content_type="application/json", body=response.get_data())
        else:
            route.fulfill(status=200, json={"success": True, "pending_actions": []})

    page.route("**/api/**", request_api)
    page.evaluate("""async () => {
        const H = window.OrchHarness;
        H.reset();
        H.stores.bootstrap.useBootstrapStore.setState({ data: {
            features: {}, settings: {}, catalogs: { models: [], agents: [], prompts: [] },
            user: { id: 'owner', display_name: 'Tester' }, scope: {},
        }});
        H.stores.chat.useChatStore.setState({
            activeConversationId: 'chat', activeConversationKind: 'personal', messages: [],
            streaming: false, streamingContent: '', retryPresentation: null, thoughts: [],
        });
        H.mount('mount-a', 'MessageList');
        await H.stores.chat.useChatStore.getState().sendMessage('Question A', {});
    }""")
    expect(page.get_by_text("Safe partial answer", exact=True)).to_have_count(1)
    expect(page.get_by_text("This response was interrupted. Response may be incomplete.", exact=True)).to_have_count(1)
    expect(page.get_by_text("Stopped by you. Response may be incomplete.", exact=True)).to_have_count(0)
    rows = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().messages")
    assert [row["id"] for row in rows] == ["question-a", "reply-a"]
    assert rows[-1]["metadata"]["complete"] is False
    assert rows[-1]["metadata"]["canceled"] is False


def test_v2_reconcile_unconfirmed_partial_uses_submission_when_user_ack_was_lost(stopped_stream_page, stop_world):
    page, world = stopped_stream_page, stop_world
    first = world.store()
    first.begin({"message": "Question A"}, world.question)
    assert first.dispatch()
    first.cancel()
    later = world.store("submission-b")
    question = deepcopy(world.question)
    question.update(id="question-b", content="Later question", timestamp="2026-11-16T20:00:02Z")
    question["metadata"]["thread_info"]["thread_id"] = "thread-b"
    later.begin({"message": "Later question"}, question)
    assert later.dispatch()
    answer = deepcopy(world.reply)
    answer.update(id="reply-b", content="Later completed answer", timestamp="2026-11-16T20:00:03Z")
    later.commit(answer)

    def history_request(route):
        response = world.app.test_client().get("/api/get_messages?conversation_id=chat")
        route.fulfill(status=response.status_code, content_type="application/json", body=response.get_data())

    page.route("**/api/get_messages?**", history_request)
    page.evaluate("""async () => {
        const H = window.OrchHarness;
        H.reset();
        H.stores.bootstrap.useBootstrapStore.setState({ data: {
            features: {}, settings: {}, catalogs: { models: [], agents: [], prompts: [] },
            user: { id: 'owner', display_name: 'Tester' }, scope: {},
        }});
        H.stores.chat.useChatStore.setState({
            activeConversationId: 'chat', activeConversationKind: 'personal', streaming: false,
            streamingContent: '', retryPresentation: null, thoughts: [],
            messages: [{
                id: 'cancelled-chat-submission-a', conversation_id: 'chat', role: 'assistant',
                content: 'Retained local partial', timestamp: '2026-11-16T20:00:01Z',
                metadata: {
                    submission_id: 'submission-a', stopped_user_message_id: 'pending-user-before-ack',
                    stream_status: 'stop_unconfirmed', complete: false,
                    response_attempt: { submission_id: 'submission-a' },
                },
            }],
        });
        H.mount('mount-a', 'MessageList');
        await H.stores.chat.useChatStore.getState().reloadMessages();
    }""")
    rows = page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().messages")
    assert [row["id"] for row in rows] == ["question-a", "cancelled-chat-submission-a", "question-b", "reply-b"]
    expect(page.get_by_text("Retained local partial", exact=True)).to_have_count(1)
