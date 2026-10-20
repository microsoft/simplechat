# test_v2_first_agent_message.py
"""
Real-composer regressions for the first agent message in a new V2 conversation.
Version: 0.261.355
Implemented in: 0.261.355

Only HTTP responses are synthetic. Production React, conversation creation,
action preflight, stores, and the SSE reader execute in Chromium. No live model,
connector, or external acceptance harness is used or changed.
"""

import copy
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_new_chat_reset as new_chat
import test_v2_orchestration_plan_editor as editor_tests


connect_options = editor_tests.connect_options
editor_assets = editor_tests.editor_assets
editor_browser = editor_tests.editor_browser
pytestmark = pytest.mark.ui

QUESTION = "Look up the requested record using the selected agent."
ANSWER = "The synthetic agent response completed."
CREATED = "first-agent-chat"
AGENTS = [
    {"id": "records-agent", "name": "records-agent", "display_name": "Records agent"},
    {"id": "calendar-agent", "name": "calendar-agent", "display_name": "Calendar agent"},
]


class FirstMessageApi(new_chat.NewChatApi):
    def __init__(self, assets):
        super().__init__(assets)
        self.next_created = (CREATED, "Agent conversation")
        self.agent_requests = []
        self.hold_context = True
        self.contexts = []
        self.hold_health = False
        self.health_checks = []

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/api/action-credentials/pending":
            route.fulfill(json={"requests": [], "csrf_token": "synthetic-csrf"})
            return
        if path == "/api/action-recovery/context":
            self.agent_requests.append({"path": path, "body": None})
            if self.hold_context:
                self.contexts.append(route)
            else:
                route.fulfill(json={"csrf_token": "synthetic-csrf"})
            return
        if path in ("/api/chat/action-health", "/api/chat/stream"):
            body = request.post_data_json
            self.agent_requests.append({"path": path, "body": copy.deepcopy(body),
                                        "headers": request.headers})
            if path.endswith("action-health"):
                if self.hold_health:
                    self.health_checks.append(route)
                else:
                    route.fulfill(json={"state": "ready"})
                return
            conversation = body["conversation_id"]
            user_id, answer_id = "saved-question", "saved-answer"
            self.messages[conversation] = [
                {"id": user_id, "conversation_id": conversation, "role": "user", "content": body["message"]},
                {"id": answer_id, "conversation_id": conversation, "role": "assistant", "content": ANSWER},
            ]
            events = [
                {"type": "user_message_persisted", "conversation_id": conversation, "message_id": user_id},
                {"done": True, "conversation_id": conversation, "user_message_id": user_id,
                 "message_id": answer_id, "full_content": ANSWER},
            ]
            route.fulfill(content_type="text/event-stream",
                          body="".join(f"data: {json.dumps(event)}\n\n" for event in events))
            return
        super().handle(route)

    def release_context(self):
        pending, self.contexts = self.contexts, []
        for route in pending:
            route.fulfill(json={"csrf_token": "synthetic-csrf"})

    def release_health(self):
        pending, self.health_checks = self.health_checks, []
        for route in pending:
            route.fulfill(json={"state": "ready"})

    def calls(self, path):
        return [request for request in self.agent_requests if request["path"] == path]


@pytest.fixture
def first_message_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    api = FirstMessageApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    page.on("console", lambda message: api.errors.append(message.text) if message.type == "error" else None)
    try:
        yield page, api
    finally:
        api.release()
        api.release_context()
        api.release_health()
        context.close()
        assert not api.errors, api.errors


def mount(page, api, *, agent=0, strict=False, conversation=None):
    page.goto(editor_tests.ORIGIN + editor_tests.HARNESS)
    page.wait_for_function("Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=editor_tests.ORIGIN + url)
    page.evaluate(
        """spec => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {
                features: {}, settings: {}, user: {id: 'tester', display_name: 'Tester'},
                catalogs: {models: [], agents: spec.agents, prompts: []},
                scope: {groups: [], public_workspaces: []},
            }});
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation,
                activeConversationKind: spec.conversation ? 'personal' : null,
                messages: [], messagesLoading: false, streaming: false,
                streamError: null, conversations: [],
            });
            H.mount('mount-a', 'Composer', {initialAgentSelection: spec.agent},
                {strictMode: spec.strict});
            H.mount('mount-b', 'MessageList');
        }""",
        {"agents": AGENTS, "agent": AGENTS[agent]["id"], "strict": strict, "conversation": conversation},
    )
    expect(page.get_by_role("status").filter(has_text="Actions are checked")).to_be_visible()


def submit(page):
    editor = page.get_by_role("textbox", name="Message")
    editor.fill(QUESTION)
    page.get_by_role("button", name="Send message", exact=True).click()


def wait_for_context(page, api):
    new_chat.wait_until(page, lambda: bool(api.contexts), "Recovery context was never requested.")
    # An observable store adoption and a browser paint let the creation-triggered
    # React effects run while the actual HTTP response is deliberately held.
    page.wait_for_function("""() =>
        window.OrchHarness.stores.chat.useChatStore.getState().activeConversationId !== null""")
    page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


@pytest.mark.parametrize("held", [False, True])
@pytest.mark.parametrize("strict,agent", [(False, 0), (True, 1)])
def test_new_conversation_first_agent_send_survives_id_adoption(first_message_ui, strict, agent, held):
    page, api = first_message_ui
    api.hold_context = held
    mount(page, api, agent=agent, strict=strict)
    submit(page)
    if held:
        wait_for_context(page, api)
        api.release_context()
    page.wait_for_function("!window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    error = page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().streamError")
    assert error is None, error
    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()
    assert len(api.created()) == 1
    health = api.calls("/api/chat/action-health")
    sends = api.calls("/api/chat/stream")
    assert len(health) == len(sends) == 1
    sent = sends[0]
    assert health[0]["body"]["request"] == sent["body"]
    assert sent["body"]["conversation_id"] == CREATED
    assert sent["body"]["message"] == QUESTION
    assert sent["body"]["agent_info"]["id"] == AGENTS[agent]["id"]
    assert sent["headers"]["x-csrftoken"] == "synthetic-csrf"
    expect(page.locator("#message-saved-question")).to_be_visible()
    expect(page.locator("#message-saved-answer")).to_be_visible()
    expect(page.get_by_text("The selected chat context changed. Recheck before sending.")).to_have_count(0)
    expect(page.get_by_role("button", name="Recheck and send preserved request")).to_have_count(0)
    expect(page.get_by_role("dialog")).to_have_count(0)


def test_existing_conversation_agent_send_is_unchanged(first_message_ui):
    page, api = first_message_ui
    api.hold_context = False
    mount(page, api, conversation=CREATED)
    submit(page)
    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()
    assert api.created() == []
    assert len(api.calls("/api/chat/stream")) == 1


@pytest.mark.parametrize("stage", ["context", "health"])
@pytest.mark.parametrize("change", ["agent", "actor", "conversation", "new-chat"])
def test_genuine_context_change_during_preflight_cannot_submit(first_message_ui, stage, change):
    page, api = first_message_ui
    api.hold_context = stage == "context"
    api.hold_health = stage == "health"
    mount(page, api)
    submit(page)
    pending = api.contexts if stage == "context" else api.health_checks
    new_chat.wait_until(page, lambda: bool(pending), f"{stage} request was never held.")
    if change == "agent":
        page.get_by_role("button", name="Records agent", exact=True).click()
        page.get_by_role("option", name="Calendar agent", exact=True).click()
    elif change == "actor":
        page.evaluate("""() => {
            const store = window.OrchHarness.stores.bootstrap.useBootstrapStore;
            store.setState({data: {...store.getState().data, user: {id: 'other-actor'}}});
        }""")
    elif change == "conversation":
        page.evaluate("""() => window.OrchHarness.stores.chat.useChatStore.getState()
            .selectConversation('other-conversation', {kind: 'personal'})""")
    else:
        page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().startNewConversation()")
    # Wait for the changed selection/identity to commit before releasing old I/O.
    page.evaluate("new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    api.release_context()
    api.release_health()
    page.wait_for_function("!window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    assert api.calls("/api/chat/stream") == []
    expect(page.get_by_role("region", name="Unavailable actions")).to_have_count(0)


def test_upload_created_conversation_adopted_in_send_event_uses_one_request(first_message_ui):
    page, api = first_message_ui
    mount(page, api)
    page.get_by_role("textbox", name="Message").fill(QUESTION)
    # Exercise the upload adoption boundary: Composer.dispatch installs the
    # upload-owned ID synchronously before calling sendMessage, in the same event.
    page.evaluate("""conversation => {
        window.OrchHarness.stores.chat.useChatStore.setState({
            activeConversationId: conversation, activeConversationKind: 'personal'
        });
        document.querySelector('button[aria-label="Send message"]').click();
    }""", CREATED)
    wait_for_context(page, api)
    api.release_context()
    expect(page.get_by_text(ANSWER, exact=True)).to_be_visible()
    assert api.created() == []
    sends = api.calls("/api/chat/stream")
    assert len(sends) == 1
    assert sends[0]["body"]["conversation_id"] == CREATED


def test_new_chat_during_creation_does_not_adopt_the_previous_draft(first_message_ui):
    page, api = first_message_ui
    api.hold_create = True
    mount(page, api)
    submit(page)
    new_chat.wait_until(page, lambda: bool(api.pending), "Conversation creation was never held.")
    page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().startNewConversation()")
    api.release()
    new_chat.wait_until(page, lambda: bool(api.contexts), "The original send never reached preflight.")
    api.release_context()
    new_chat.wait_until(page, lambda: bool(api.calls("/api/chat/stream")), "The original background send was lost.")
    page.wait_for_function("!window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    state = page.evaluate("""() => {
        const state = window.OrchHarness.stores.chat.useChatStore.getState();
        return {conversation: state.activeConversationId, messages: state.messages};
    }""")
    assert state == {"conversation": None, "messages": []}
    assert len(api.calls("/api/chat/stream")) == 1
