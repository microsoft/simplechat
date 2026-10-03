# test_v2_new_chat_reset.py
"""
Browser regressions for starting a new chat in V2 while the open conversation is busy.
Version: 0.261.226
Implemented in: 0.261.226

Clicking New chat while an orchestration turn was planning or running kept the old turn's
"Thinking" bubble and a Stop button with nothing to stop, hid the new chat's empty state,
and refused to send until the page was reloaded. A first message still creating its
conversation could take the new chat over, a conversation still loading left its loading
placeholders in the new chat, and Home's Start chatting reopened whichever conversation
was last open (issue #1617).

The production AppShell, Sidebar, HomePage, ChatPage, Composer, MessageList, stores,
orchestration controller and SSE reader run in Chromium with production CSS. Only HTTP is
deterministic: plan, run and chat streams are held open and fed one server-shaped frame at
a time, and conversation creation and message loading can be held, so New chat lands
inside exactly the round trip each defect needed. No live model, deployment or workspace
content is used.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_new_chat_reset.py -q
"""

from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
BUSY = "busy-review"
BUSY_TITLE = "Busy review"
OTHER = "other-review"
OTHER_TITLE = "Other review"
CREATED = "fresh-chat"
BACKGROUND = "background-chat"
BACKGROUND_TITLE = "Background question"
PLAN = "/api/v2/orchestration/plan"
RUN = editor_tests.RUN
CHAT = "/api/chat/stream"
QUESTION = "Compare the quarterly reports and summarise how revenue changed."
FOLLOW_UP = "Draft a one-line status update for the team."
EARLIER_QUESTION = "Which reports are in this review?"
EARLIER_ANSWER = "Last quarter's report is attached to this review."
OTHER_ANSWER = "The other review is about supplier contracts."
DECIDING = "Deciding what this question needs."
ANSWER = "Revenue rose 12% between the two quarters."
UPDATE = "Revenue is up 12% quarter on quarter."
EMPTY_STATE = "Start a conversation with SimpleChat"

# Plan, run and chat responses stay open until the test ends them, keyed by path and the
# conversation the request names, so the turn that was left and the new chat's own turn can
# be fed separately. Like a real fetch, an aborted request fails its body, which is how a
# detached chat reader stops. Other requests go to the page router.
INSTALL_STREAMS = r"""
(paths) => {
    const encoder = new TextEncoder();
    const passThrough = window.fetch.bind(window);
    const key = (path, conversation) => path + '|' + conversation;
    window.__streams = {};
    window.emitFrame = (path, conversation, event) => {
        window.__streams[key(path, conversation)].enqueue(
            encoder.encode('data: ' + JSON.stringify(event) + '\n\n'),
        );
    };
    window.endStream = (path, conversation) => {
        try {
            window.__streams[key(path, conversation)].close();
        } catch (error) {
            // The reader already stopped at the terminal frame or was aborted.
        }
    };
    window.fetch = (input, init = {}) => {
        const url = new URL(input instanceof Request ? input.url : String(input), location.href);
        if (!paths.includes(url.pathname)) {
            return passThrough(input, init);
        }
        let body = {};
        try {
            body = JSON.parse(init.body || '{}');
        } catch (error) {
            body = {};
        }
        const conversation = String(body.conversation_id || '');
        const stream = new ReadableStream({
            start(controller) {
                window.__streams[key(url.pathname, conversation)] = controller;
                init.signal?.addEventListener('abort', () => {
                    try {
                        controller.error(new DOMException('The operation was aborted.', 'AbortError'));
                    } catch (error) {
                        // Already closed.
                    }
                });
            },
        });
        return Promise.resolve(new Response(stream, {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
        }));
    };
}
"""


class NewChatApi:
    """Serves the harness and answers the chat page's reads; anything else fails the test.

    Conversation creation and message loading can be held, so New chat can be clicked while
    either round trip is still open.
    """

    def __init__(self, assets):
        self.assets = assets
        self.errors = []
        self.requests = []
        self.conversations = [{"id": BUSY, "title": BUSY_TITLE}]
        self.messages = {BUSY: earlier_messages()}
        self.next_created = (CREATED, "New chat")
        self.hold_create = False
        self.hold_messages = False
        self.pending = []

    def handle(self, route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.requests.append((request.method, path))
        if path == "/api/create_conversation" and request.method == "POST":
            if self.hold_create:
                self.pending.append(("create", route))
            else:
                self.create(route)
            return
        if path == "/api/get_messages":
            conversation = parse_qs(url.query).get("conversation_id", [""])[0]
            if self.hold_messages:
                self.pending.append(("messages", route, conversation))
            else:
                route.fulfill(json={"messages": self.messages.get(conversation, [])})
            return
        if path in ("/api/conversations/feed", "/api/get_conversations"):
            route.fulfill(json={"conversations": self.conversations, "has_more": False, "next_cursor": None})
            return
        if path.startswith("/api/conversations/") and path.endswith("/metadata"):
            conversation = unquote(path.split("/")[3])
            title = next(
                (item["title"] for item in self.conversations if item["id"] == conversation),
                "New chat",
            )
            route.fulfill(json={"conversation_id": conversation, "title": title})
            return
        if path.startswith("/api/chat/stream/status/"):
            route.fulfill(json={"active": False, "pending": False, "reattachable": False})
            return
        if path.startswith("/api/chat/stream/cancel/"):
            # Answered so a regression shows up as an assertion, not a hung request.
            route.fulfill(json={"success": True})
            return
        if path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
            return
        if path == "/api/collaboration/file-approvals":
            route.fulfill(json={"approvals": []})
            return
        if path == "/api/user/settings":
            route.fulfill(json={"settings": {}})
            return
        if path == "/api/user/collaboration-suggestions":
            route.fulfill(json={"results": []})
            return
        self.errors.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test request."})

    def create(self, route):
        conversation, title = self.next_created
        self.conversations = [{"id": conversation, "title": title}, *self.conversations]
        route.fulfill(json={"conversation_id": conversation, "title": title})

    def release(self):
        pending, self.pending = self.pending, []
        for held in pending:
            if held[0] == "create":
                self.create(held[1])
            else:
                held[1].fulfill(json={"messages": self.messages.get(held[2], [])})

    def created(self):
        return [request for request in self.requests if request == ("POST", "/api/create_conversation")]


def earlier_messages():
    return [
        {"id": "busy-q0", "conversation_id": BUSY, "role": "user", "content": EARLIER_QUESTION},
        {"id": "busy-a0", "conversation_id": BUSY, "role": "assistant", "content": EARLIER_ANSWER},
    ]


def planning_thought(content, status="running"):
    """A planner reasoning step, shaped as build_planning_thought serializes it."""
    return {
        "type": "thought",
        "message_id": None,
        "step_index": 1,
        "step_type": "orchestration_planning",
        "content": content,
        "activity": {
            "lane_key": "orchestration",
            "kind": "orchestration_planning",
            "title": "Building a plan",
            "status": status,
        },
    }


def run_done(plan, turn, conversation=BUSY):
    """A run's terminal frame, shaped as build_run_done_event serializes a completed run."""
    return {
        "done": True,
        "type": "orchestration_done",
        "conversation_id": conversation,
        "message_id": f"{conversation}-answer",
        "run_id": plan["run_id"],
        "full_content": ANSWER,
        "hybrid_citations": [],
        "web_search_citations": [],
        "agent_citations": [],
        "augmented": False,
        "generated_artifacts": [],
        "orchestration": {},
        "status": "completed",
        "outcome": "completed",
        "turn_id": turn,
        "attempt_index": 1,
        "retry_of_run_id": None,
        "failure": None,
        "failures": [],
        "recovery": None,
        "message_saved": True,
        "reasoning_adjustments": [],
    }


@pytest.fixture
def chat_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    api = NewChatApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    page.on("console", lambda message: api.errors.append(message.text) if message.type == "error" else None)
    try:
        yield page, api
    finally:
        api.release()
        context.close()
        assert not api.errors, api.errors


def mount(page, api, *, conversation=BUSY, orchestration=True, experience="ChatExperience", entry="/chat"):
    page.goto(editor_tests.ORIGIN + editor_tests.HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=editor_tests.ORIGIN + url)
    page.evaluate(INSTALL_STREAMS, [PLAN, RUN, CHAT])
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {
                features: {enable_chat_orchestration: spec.orchestration},
                settings: {}, user: {id: 'tester', display_name: 'Tester'},
                catalogs: {models: [], agents: [], prompts: []},
                scope: {groups: [], public_workspaces: []},
                orchestration: {
                    enabled: spec.orchestration, capabilities: [], default_approval_mode: 'manual',
                },
            }});
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation,
                activeConversationKind: spec.conversation ? 'personal' : null,
                messages: spec.messages, messagesLoading: false, messagesError: null,
                streaming: false, streamError: null, streamingContent: '', thoughts: [],
                conversations: spec.conversations,
            });
            H.mount('mount-a', spec.experience, {}, {initialEntries: [spec.entry]});
        }""",
        {
            "conversation": conversation,
            "orchestration": orchestration,
            "experience": experience,
            "entry": entry,
            "messages": api.messages.get(conversation, []) if conversation else [],
            "conversations": api.conversations,
        },
    )
    if experience == "ChatExperience":
        expect(page.get_by_title("Start a new chat", exact=True)).to_be_visible()


def chat_state(page):
    return page.evaluate(
        """() => {
            const S = window.OrchHarness.stores.chat.useChatStore.getState();
            return {
                active: S.activeConversationId, streaming: S.streaming, loading: S.messagesLoading,
                messages: S.messages.map((message) => message.content),
            };
        }"""
    )


def wait_until(page, predicate, message):
    """Let Playwright dispatch held routes until a Python-side condition holds."""
    for _ in range(200):
        if predicate():
            return
        page.wait_for_timeout(25)
    raise AssertionError(message)


def emit(page, path, conversation, event):
    page.evaluate(
        "([path, conversation, event]) => window.emitFrame(path, conversation, event)",
        [path, conversation, event],
    )


def end_stream(page, path, conversation):
    page.evaluate("([path, conversation]) => window.endStream(path, conversation)", [path, conversation])


def wait_for_stream(page, path, conversation):
    page.wait_for_function(
        "([path, conversation]) => Boolean(window.__streams[path + '|' + conversation])",
        arg=[path, conversation],
    )


def wait_for_plan(page, conversation, turn):
    """The plan is stored for its own conversation, which proves its frames were all read."""
    page.wait_for_function(
        """([conversation, turn]) => {
            const H = window.OrchHarness;
            return Boolean(H.stores.orchestration.selectPlan(
                H.stores.orchestration.useOrchestrationStore.getState(), conversation, turn));
        }""",
        arg=[conversation, turn],
    )


def thinking(page):
    return page.get_by_text("Thinking", exact=True)


def stop_button(page):
    return page.get_by_role("button", name="Stop generating", exact=True)


def send_button(page):
    return page.get_by_role("button", name="Send message", exact=True)


def draft(page):
    return page.get_by_role("textbox", name="Message", exact=True)


def approve_button(page):
    return page.get_by_role("button", name="Approve and run the plan")


def click_new_chat(page):
    # Matched on the title, which the button keeps whether the rail is expanded or collapsed.
    page.get_by_title("Start a new chat", exact=True).click()


def open_from_rail(page, title):
    page.get_by_role("navigation", name="Primary").get_by_role("button", name=title, exact=True).click()
    expect(page.get_by_role("heading", name=title, level=1)).to_be_visible()


def expect_clean_new_chat(page, *absent):
    """Everything a new chat shows, and nothing the conversation that was left showed."""
    expect(page.get_by_role("heading", name="New chat", level=1)).to_be_visible()
    expect(page.get_by_text(EMPTY_STATE, exact=True)).to_be_visible()
    expect(thinking(page)).to_have_count(0)
    expect(stop_button(page)).to_have_count(0)
    expect(send_button(page)).to_be_visible()
    for text in absent:
        expect(page.get_by_text(text, exact=True)).to_have_count(0)
    state = chat_state(page)
    assert state == {"active": None, "streaming": False, "loading": False, "messages": []}, state


def start_plan(page, conversation=BUSY, message=QUESTION):
    page.evaluate(
        """(spec) => { void window.OrchHarness.controller.startOrchestrationPlan(spec); }""",
        {"conversationId": conversation, "message": message, "approvalMode": "manual", "seeds": {}},
    )
    wait_for_stream(page, PLAN, conversation)
    return page.evaluate(
        "(conversation) => window.OrchHarness.stores.orchestration.useOrchestrationStore"
        ".getState().activeTurns[conversation]",
        conversation,
    )


def finish_plan(page, turn, conversation=BUSY):
    plan = editor_tests.make_plan(conversation, turn)
    emit(page, PLAN, conversation, planning_thought("Plan ready.", status="completed"))
    emit(page, PLAN, conversation, {"type": "orchestration_plan", "plan": plan, "done": True})
    end_stream(page, PLAN, conversation)
    wait_for_plan(page, conversation, turn)
    return plan


def persist_question(api, turn):
    """What the server holds for the conversation once its question has been asked."""
    api.messages[BUSY] = [
        *earlier_messages(),
        {
            "id": "busy-question", "conversation_id": BUSY, "role": "user", "content": QUESTION,
            "metadata": {"orchestration_turn_id": turn},
        },
    ]


def test_new_chat_while_planning_starts_clean_and_returning_restores_the_turn(chat_ui):
    page, api = chat_ui
    mount(page, api)
    turn = start_plan(page)
    persist_question(api, turn)
    expect(thinking(page)).to_be_visible()
    expect(stop_button(page)).to_be_visible()
    expect(page.get_by_text(QUESTION, exact=True)).to_be_visible()

    click_new_chat(page)
    expect_clean_new_chat(page, QUESTION, EARLIER_ANSWER)

    # The plan is still being written for the conversation that was left. Going back shows it
    # working, with Stop, and its next reasoning step lands there as usual.
    open_from_rail(page, BUSY_TITLE)
    expect(page.get_by_text(QUESTION, exact=True)).to_be_visible()
    expect(thinking(page)).to_be_visible()
    expect(stop_button(page)).to_be_visible()
    emit(page, PLAN, BUSY, planning_thought(DECIDING))
    expect(page.get_by_role("button", name="1 reasoning step", exact=True)).to_be_visible()

    # Leave again and let the plan finish out of sight: it must not appear in the new chat.
    click_new_chat(page)
    expect_clean_new_chat(page, QUESTION, EARLIER_ANSWER)
    finish_plan(page, turn)
    expect(approve_button(page)).to_have_count(0)
    expect_clean_new_chat(page, QUESTION, EARLIER_ANSWER)

    # Its turn settled while the reader was away, so coming back shows the plan, not Thinking.
    open_from_rail(page, BUSY_TITLE)
    expect(approve_button(page).first).to_be_visible()
    expect(thinking(page)).to_have_count(0)
    expect(stop_button(page)).to_have_count(0)
    expect(send_button(page)).to_be_visible()
    assert chat_state(page)["streaming"] is False


def test_new_chat_while_a_plan_runs_keeps_the_answer_in_its_own_chat_and_can_send(chat_ui):
    page, api = chat_ui
    mount(page, api)
    turn = start_plan(page)
    plan = finish_plan(page, turn)
    approve_button(page).first.click()
    wait_for_stream(page, RUN, BUSY)
    expect(thinking(page)).to_be_visible()
    expect(stop_button(page)).to_be_visible()

    click_new_chat(page)
    expect_clean_new_chat(page, QUESTION, EARLIER_ANSWER)

    emit(page, RUN, BUSY, {"content": ANSWER})
    emit(page, RUN, BUSY, run_done(plan, turn))
    end_stream(page, RUN, BUSY)
    page.wait_for_function(
        """(conversation) => !Object.values(window.OrchHarness.stores.orchestration
            .useOrchestrationStore.getState().inFlight)
            .some((run) => run.conversationId === conversation)""",
        arg=BUSY,
    )
    expect_clean_new_chat(page, QUESTION, EARLIER_ANSWER, ANSWER)

    # The composer is usable straight away: the new chat's own first question goes out.
    draft(page).fill(FOLLOW_UP)
    send_button(page).click()
    wait_for_stream(page, PLAN, CREATED)
    expect(page.get_by_text(FOLLOW_UP, exact=True)).to_be_visible()
    expect(thinking(page)).to_be_visible()
    assert chat_state(page)["active"] == CREATED
    assert len(api.created()) == 1
    expect(page.get_by_text(QUESTION, exact=True)).to_have_count(0)

    # Stop now belongs to the new chat's turn, and ends it.
    stop_button(page).click()
    expect(thinking(page)).to_have_count(0)
    expect(send_button(page)).to_be_visible()


def test_new_chat_while_a_chat_reply_streams_detaches_without_cancelling(chat_ui):
    page, api = chat_ui
    mount(page, api, orchestration=False)
    draft(page).fill(QUESTION)
    send_button(page).click()
    wait_for_stream(page, CHAT, BUSY)
    expect(thinking(page)).to_be_visible()
    expect(stop_button(page)).to_be_visible()

    click_new_chat(page)
    expect_clean_new_chat(page, QUESTION, EARLIER_ANSWER)
    # Leaving stops reading; only Stop may end the answer being written.
    assert ("POST", f"/api/chat/stream/cancel/{BUSY}") not in api.requests

    draft(page).fill(FOLLOW_UP)
    send_button(page).click()
    wait_for_stream(page, CHAT, CREATED)
    expect(page.get_by_text(FOLLOW_UP, exact=True)).to_be_visible()
    emit(page, CHAT, CREATED, {"content": UPDATE})
    emit(page, CHAT, CREATED, {
        "done": True, "conversation_id": CREATED, "message_id": "fresh-answer", "full_content": UPDATE,
    })
    end_stream(page, CHAT, CREATED)
    expect(page.get_by_text(UPDATE, exact=True)).to_be_visible()
    expect(thinking(page)).to_have_count(0)
    expect(page.get_by_text(QUESTION, exact=True)).to_have_count(0)


@pytest.mark.parametrize("mode", ["chat", "plan"])
def test_new_chat_while_the_first_message_creates_its_conversation_stays_empty(chat_ui, mode):
    page, api = chat_ui
    api.next_created = (BACKGROUND, BACKGROUND_TITLE)
    api.hold_create = True
    mount(page, api, conversation=None, orchestration=mode == "plan")
    draft(page).fill(QUESTION)
    send_button(page).click()
    wait_until(page, lambda: api.pending, "The new chat never asked to create its conversation")

    click_new_chat(page)
    api.release()

    # The question is still sent, from the conversation it created...
    path = CHAT if mode == "chat" else PLAN
    wait_for_stream(page, path, BACKGROUND)
    # ...but the chat the reader opened since stays theirs.
    expect_clean_new_chat(page, QUESTION)

    if mode == "chat":
        emit(page, CHAT, BACKGROUND, {
            "done": True, "conversation_id": BACKGROUND, "message_id": "background-answer",
            "full_content": ANSWER,
        })
        end_stream(page, CHAT, BACKGROUND)
    else:
        turn = page.evaluate(
            "(conversation) => window.OrchHarness.stores.orchestration.useOrchestrationStore"
            ".getState().activeTurns[conversation]",
            BACKGROUND,
        )
        finish_plan(page, turn, BACKGROUND)
    # The answer is kept with its own conversation, which the rail lists.
    expect(
        page.get_by_role("navigation", name="Primary").get_by_role("button", name=BACKGROUND_TITLE, exact=True)
    ).to_be_visible()
    expect(approve_button(page)).to_have_count(0)
    expect_clean_new_chat(page, QUESTION, ANSWER)


def test_new_chat_while_a_conversation_loads_shows_the_empty_state(chat_ui):
    page, api = chat_ui
    api.conversations = [{"id": BUSY, "title": BUSY_TITLE}, {"id": OTHER, "title": OTHER_TITLE}]
    api.messages[OTHER] = [
        {"id": "other-a0", "conversation_id": OTHER, "role": "assistant", "content": OTHER_ANSWER},
    ]
    mount(page, api)
    api.hold_messages = True
    page.get_by_role("navigation", name="Primary").get_by_role("button", name=OTHER_TITLE, exact=True).click()
    wait_until(page, lambda: api.pending, "Opening the conversation never asked for its messages")
    assert chat_state(page)["loading"] is True

    click_new_chat(page)
    with page.expect_response(lambda response: urlsplit(response.url).path == "/api/get_messages"):
        api.release()
    expect_clean_new_chat(page, OTHER_ANSWER, EARLIER_ANSWER)


def test_home_start_chatting_opens_a_new_chat_not_the_busy_one(chat_ui):
    page, api = chat_ui
    mount(page, api, experience="HomeExperience", entry="/")
    turn = start_plan(page)
    assert chat_state(page)["streaming"] is True

    page.get_by_role("link", name="Start chatting", exact=True).click()
    expect_clean_new_chat(page, QUESTION, EARLIER_ANSWER)

    # The turn that was left carries on and finishes where it belongs.
    finish_plan(page, turn)
    expect(approve_button(page)).to_have_count(0)
    expect_clean_new_chat(page, QUESTION, EARLIER_ANSWER)
