# test_v2_chat_message_scroll.py
"""
Real-component browser regression for V2 chat message reading positions.
Version: 0.261.318
Implemented in: 0.261.318

Production MessageList, chat store, completion handling and CSS run in Chromium.
Only HTTP boundaries are stubbed. Measure message starts, reading offsets and
live-following geometry rather than using the arrow's presence as a proxy.
The shared browser fixture supports local and Azure Playwright connections.

Build: npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_chat_message_scroll.py -q
"""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)
from v2_pending_action_stubs import is_pending_actions_list, pending_actions_payload
from test_v2_orchestration_streaming_bubble import INSTALL_STREAMS


pytestmark = pytest.mark.ui
CHAT = "reading-chat"
ARROW = "Go to the beginning of the newest message"
LONG = "\n\n".join(f"Reading paragraph {index}. " + "Detailed content for reading. " * 8 for index in range(35))


def message(message_id, content=LONG, role="assistant", **extra):
    return {"id": message_id, "role": role, "conversation_id": CHAT, "content": content, **extra}


class ScrollApi:
    def __init__(self, assets):
        self.assets = assets
        self.errors = []

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
        elif is_pending_actions_list(request.method, path):
            route.fulfill(json=pending_actions_payload())
        elif path == "/favicon.ico":
            route.fulfill(status=204)
        else:
            self.errors.append(f"Unexpected request: {request.method} {path}")
            route.fulfill(status=404, json={"error": "Unexpected test request."})


@pytest.fixture
def scroll_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="reduce")
    page = context.new_page()
    api = ScrollApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    page.on("console", lambda entry: api.errors.append(entry.text) if entry.type == "error" else None)
    try:
        yield page, api
    finally:
        context.close()
        assert not api.errors, api.errors


def mount(page, api, *, kind="personal", messages=None, loading=False):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {
                features: {}, settings: {}, branding: {app_title: 'SimpleChat'},
                user: {id: 'tester', display_name: 'Tester'}, catalogs: {models: [], agents: [], prompts: []},
                scope: {groups: [], public_workspaces: []}, orchestration: {enabled: false, capabilities: []},
            }});
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.chat, activeConversationKind: spec.kind,
                messages: spec.messages, messagesLoading: spec.loading, messagesError: null,
                streaming: false, streamingContent: '', completedReply: null, streamError: null, thoughts: [],
                orchestrationSurface: null, metadata: null, attemptsByThread: {},
            });
            H.mount('mount-a', 'PromptExperience', {}, {strictMode: true, initialEntries: ['/chat']});
        }""",
        {"chat": CHAT, "kind": kind, "messages": messages or [message("history")], "loading": loading},
    )
    frames(page)


def frames(page):
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")


def root(page):
    return page.locator('[data-tour="message-list"]')


def geometry(page, message_id=None):
    return root(page).evaluate(
        """(node, id) => {
            const box = node.getBoundingClientRect();
            const item = Array.from(node.querySelectorAll('[data-scroll-message-id]'))
                .find(item => item.dataset.scrollMessageId === id);
            return {top: node.scrollTop, remaining: node.scrollHeight - node.scrollTop - node.clientHeight,
                height: node.clientHeight, offset: item ? item.getBoundingClientRect().top - box.top : null,
                pageTop: document.scrollingElement.scrollTop};
        }""",
        message_id,
    )


def update(page, changes):
    page.evaluate("(changes) => window.OrchHarness.stores.chat.useChatStore.setState(changes)", changes)
    frames(page)


def append(page, incoming):
    page.evaluate(
        """(message) => {
            const H = window.OrchHarness;
            H.stores.chat.useChatStore.setState(state => ({
                messages: H.stores.chat.mergeCollaborationMessage(state.messages, message),
            }));
        }""",
        incoming,
    )
    frames(page)


def scroll_back(page, top=100):
    root(page).evaluate("(node, top) => { node.scrollTop = top; }", top)
    frames(page)


def start_stream(page):
    update(page, {"streaming": True, "streamingContent": ""})


def push_content(page, content):
    page.evaluate(
        "([id, content]) => window.OrchHarness.stores.chat.useChatStore.getState().pushOrchestrationContent(id, content)",
        [CHAT, content],
    )
    frames(page)


def complete(page, content=LONG, message_id="reply"):
    page.evaluate(
        """(spec) => window.OrchHarness.stores.chat.useChatStore.getState().settleOrchestrationTurn(
            spec.chat, {status: 'completed', accumulated: spec.content,
                event: {message_id: spec.id, full_content: spec.content, role: 'assistant'}})""",
        {"chat": CHAT, "content": content, "id": message_id},
    )
    frames(page)


def assert_start(page, message_id):
    measured = geometry(page, message_id)
    assert measured["offset"] == pytest.approx(24, abs=2), measured
    assert measured["remaining"] > measured["height"], measured
    assert measured["pageTop"] == 0, measured


@pytest.mark.parametrize("kind", ["personal", "collaborative"])
@pytest.mark.parametrize("mobile", [False, True])
@pytest.mark.parametrize("role", ["assistant", "user"])
def test_long_arrival_opens_at_start(scroll_ui, kind, mobile, role):
    page, api = scroll_ui
    if mobile:
        page.set_viewport_size({"width": 390, "height": 740})
    mount(page, api, kind=kind)
    append(page, message("new-long", role=role))
    assert_start(page, "new-long")
    expect(page.get_by_role("button", name=ARROW)).to_have_count(0)


def test_stream_follows_then_returns_to_the_completed_reply_once(scroll_ui):
    page, api = scroll_ui
    mount(page, api)
    start_stream(page)
    for paragraphs in (10, 20, 35):
        push_content(page, "\n\n".join(LONG.split("\n\n")[:paragraphs]))
        measured = geometry(page)
        assert measured["remaining"] == pytest.approx(0, abs=2), measured
    complete(page)
    assert_start(page, "reply")
    scroll_back(page, geometry(page)["top"] + 300)
    before = geometry(page)["top"]
    append(page, message("reply"))
    assert geometry(page)["top"] == pytest.approx(before, abs=2)
    expect(page.get_by_role("button", name=ARROW)).to_have_count(0)


@pytest.mark.parametrize("broadcast_first", [False, True])
def test_shared_terminal_and_broadcast_do_not_double_jump(scroll_ui, broadcast_first):
    page, api = scroll_ui
    mount(page, api, kind="collaborative")
    start_stream(page)
    push_content(page, LONG)
    if broadcast_first:
        append(page, message("reply"))
    complete(page)
    assert_start(page, "reply")
    before = geometry(page)["top"]
    append(page, message("shared-reply", metadata={"source_message_id": "reply"}))
    assert geometry(page)["top"] == pytest.approx(before, abs=2)
    expect(page.get_by_role("button", name=ARROW)).to_have_count(0)
    page.locator("#message-history").evaluate("(node) => { node.style.paddingTop = '300px'; }")
    frames(page)
    assert_start(page, "shared-reply")


def test_personal_sse_frames_use_the_actual_completed_reply(scroll_ui):
    page, api = scroll_ui
    mount(page, api)
    endpoint = "/api/chat/stream"
    page.evaluate(INSTALL_STREAMS, [endpoint])
    page.evaluate(
        "() => { void window.OrchHarness.stores.chat.useChatStore.getState()"
        ".sendMessage('A new question', {modelDeployment: 'test-model'}); }"
    )
    page.wait_for_function("(path) => Boolean(window.__streams[path])", arg=endpoint)
    page.evaluate(
        "([path, event]) => window.emitFrame(path, event)",
        [endpoint, {"type": "user_message_persisted", "user_message_id": "saved-question"}],
    )
    for content in (LONG[:len(LONG) // 2], LONG[len(LONG) // 2:]):
        page.evaluate(
            "([path, content]) => window.emitFrame(path, {content})", [endpoint, content]
        )
        frames(page)
        assert geometry(page)["remaining"] == pytest.approx(0, abs=2)
    page.evaluate(
        "([path, event]) => window.emitFrame(path, event)",
        [endpoint, {"done": True, "message_id": "actual-sse-reply", "full_content": LONG}],
    )
    page.wait_for_function("() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming")
    frames(page)
    assert_start(page, "actual-sse-reply")
    page.evaluate("(path) => window.endStream(path)", endpoint)


def test_manual_reading_survives_streaming_and_completion(scroll_ui):
    page, api = scroll_ui
    mount(page, api)
    start_stream(page)
    push_content(page, LONG[:len(LONG) // 2])
    scroll_back(page)
    before = geometry(page, "history")
    push_content(page, LONG)
    complete(page)
    after = geometry(page, "history")
    assert after["offset"] == pytest.approx(before["offset"], abs=2), (before, after)
    expect(page.get_by_role("button", name=ARROW)).to_be_visible()
    page.get_by_role("button", name=ARROW).click()
    assert_start(page, "reply")
    expect(page.get_by_role("button", name=ARROW)).to_have_count(0)


def test_arrow_chooses_the_most_current_message_and_supports_keyboard(scroll_ui):
    page, api = scroll_ui
    mount(page, api, kind="collaborative")
    scroll_back(page)
    before = geometry(page, "history")
    append(page, message("first-unseen"))
    append(page, message("most-current"))
    assert geometry(page, "history")["offset"] == pytest.approx(before["offset"], abs=2)
    arrow = page.get_by_role("button", name=ARROW)
    arrow.focus()
    arrow.press("Enter")
    assert_start(page, "most-current")
    expect(arrow).to_have_count(0)
    append(page, message("another-arrival"))
    expect(arrow).to_be_visible()


def test_jump_to_live_start_does_not_resume_following_or_announce_each_token(scroll_ui):
    page, api = scroll_ui
    mount(page, api)
    scroll_back(page)
    start_stream(page)
    push_content(page, LONG[:len(LONG) // 2])
    arrow = page.get_by_role("button", name=ARROW)
    arrow.click()
    before = geometry(page)["top"]
    push_content(page, LONG)
    assert geometry(page)["top"] == pytest.approx(before, abs=2)
    expect(arrow).to_have_count(0)
    complete(page)
    assert geometry(page)["top"] == pytest.approx(before, abs=2)
    expect(arrow).to_have_count(0)


def test_even_a_small_manual_upward_scroll_overrides_live_following(scroll_ui):
    page, api = scroll_ui
    mount(page, api)
    start_stream(page)
    push_content(page, LONG[:len(LONG) // 2])
    scroll_back(page, geometry(page)["top"] - 10)
    before = geometry(page)["top"]
    push_content(page, LONG)
    complete(page)
    assert geometry(page)["top"] == pytest.approx(before, abs=2)
    expect(page.get_by_role("button", name=ARROW)).to_be_visible()


def test_scrolling_back_down_resumes_following_and_later_upward_reading_gets_an_arrow(scroll_ui):
    page, api = scroll_ui
    mount(page, api)
    start_stream(page)
    push_content(page, LONG[:len(LONG) // 2])
    scroll_back(page)
    root(page).evaluate("(node) => { node.scrollTop = node.scrollHeight; }")
    frames(page)
    push_content(page, LONG)
    assert geometry(page)["remaining"] == pytest.approx(0, abs=2)
    scroll_back(page)
    push_content(page, LONG + "\n\nAnother live paragraph.")
    expect(page.get_by_role("button", name=ARROW)).to_be_visible()


def test_shared_arrivals_are_indicated_even_when_a_stream_has_not_emitted_another_frame(scroll_ui):
    page, api = scroll_ui
    mount(page, api, kind="collaborative")
    start_stream(page)
    scroll_back(page)
    append(page, message("human-during-stream", role="user"))
    expect(page.get_by_role("button", name=ARROW)).to_be_visible()


def test_delayed_growth_keeps_the_message_beginning_and_manual_anchor(scroll_ui):
    page, api = scroll_ui
    mount(page, api)
    append(page, message("new-long"))
    assert_start(page, "new-long")
    page.locator("#message-history").evaluate(
        "(node) => { const delayed = document.createElement('div'); delayed.style.height = '400px'; node.prepend(delayed); }"
    )
    page.locator("#message-new-long").evaluate(
        "(node) => { const delayed = document.createElement('div'); delayed.style.height = '500px'; node.append(delayed); }"
    )
    frames(page)
    assert_start(page, "new-long")
    scroll_back(page, geometry(page)["top"] + 200)
    before = geometry(page, "new-long")["offset"]
    page.locator("#message-history").evaluate("(node) => { node.firstElementChild.style.height = '700px'; }")
    frames(page)
    assert geometry(page, "new-long")["offset"] == pytest.approx(before, abs=2)


def test_loading_and_conversation_resets_are_not_new_arrivals(scroll_ui):
    page, api = scroll_ui
    mount(page, api, loading=True)
    update(page, {"messagesLoading": False, "messages": [message("loaded-history")]})
    assert geometry(page)["remaining"] == pytest.approx(0, abs=2)
    scroll_back(page)
    append(page, message("unseen"))
    expect(page.get_by_role("button", name=ARROW)).to_be_visible()
    update(page, {"activeConversationId": "other", "messages": [message("other-history")]})
    assert geometry(page)["remaining"] == pytest.approx(0, abs=2)
    expect(page.get_by_role("button", name=ARROW)).to_have_count(0)
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().startNewConversation()")
    frames(page)
    expect(page.get_by_role("button", name=ARROW)).to_have_count(0)
    expect(page.get_by_text("Start a conversation with SimpleChat")).to_be_visible()


def test_delayed_growth_does_not_leave_a_stale_caught_up_state(scroll_ui):
    page, api = scroll_ui
    mount(page, api)
    append(page, message("short", "A short reply with delayed content."))
    page.locator("#message-short").evaluate(
        "(node) => { const delayed = document.createElement('div'); delayed.style.height = '2000px'; node.append(delayed); }"
    )
    frames(page)
    before = geometry(page, "short")["offset"]
    append(page, message("next-reply"))
    assert geometry(page, "short")["offset"] == pytest.approx(before, abs=2)
    expect(page.get_by_role("button", name=ARROW)).to_be_visible()


def test_short_arrivals_and_identity_updates_do_not_create_fake_space_or_badges(scroll_ui):
    page, api = scroll_ui
    mount(page, api, messages=[message("pending-user-1", "A question", "user")])
    append(page, message("saved-user", "A question", "user", sender={"user_id": "tester"}))
    append(page, message("short", "A short answer"))
    measured = geometry(page)
    assert measured["top"] == 0 and measured["remaining"] <= 0, measured
    expect(page.get_by_role("button", name=ARROW)).to_have_count(0)
    append(page, message("short", "Updated answer"))
    expect(page.get_by_role("button", name=ARROW)).to_have_count(0)


@pytest.mark.parametrize("terminal", ["failed", "cancelled", "planned"])
def test_non_answer_terminal_states_do_not_jump_to_a_previous_reply(scroll_ui, terminal):
    page, api = scroll_ui
    mount(page, api)
    start_stream(page)
    push_content(page, LONG)
    scroll_back(page)
    before = geometry(page, "history")["offset"]
    outcome = {"status": terminal, "accumulated": LONG, "error": "Unable to finish this reply."}
    page.evaluate(
        "([id, outcome]) => window.OrchHarness.stores.chat.useChatStore.getState().settleOrchestrationTurn(id, outcome)",
        [CHAT, outcome],
    )
    frames(page)
    assert geometry(page, "history")["offset"] == pytest.approx(before, abs=2)
    if terminal != "cancelled":
        expect(page.get_by_role("button", name=ARROW)).to_have_count(0)


def test_first_conversation_id_assignment_preserves_manual_position(scroll_ui):
    page, api = scroll_ui
    mount(page, api, messages=[message("pending-user-1", role="user")])
    update(page, {"activeConversationId": None, "streaming": True})
    push_content(page, LONG)
    scroll_back(page)
    before = geometry(page)["top"]
    update(page, {"activeConversationId": CHAT})
    assert geometry(page)["top"] == pytest.approx(before, abs=2)
    complete(page)
    assert geometry(page)["top"] == pytest.approx(before, abs=2)


@pytest.mark.parametrize("mobile", [False, True])
def test_indicator_theme_layout_and_composer_clearance(scroll_ui, mobile):
    page, api = scroll_ui
    if mobile:
        page.set_viewport_size({"width": 390, "height": 740})
    mount(page, api)
    if mobile:
        page.evaluate("() => document.documentElement.classList.add('dark')")
    scroll_back(page)
    append(page, message("newest"))
    arrow = page.get_by_role("button", name=ARROW)
    expect(arrow).to_be_visible()
    button_box = arrow.bounding_box()
    pane_box = root(page).bounding_box()
    assert button_box["y"] + button_box["height"] <= pane_box["y"] + pane_box["height"]
    assert button_box["x"] >= 0 and button_box["x"] + button_box["width"] <= page.viewport_size["width"]
    assert geometry(page)["pageTop"] == 0
    artifacts = Path(__file__).parent / "artifacts" / "chat-message-scroll"
    artifacts.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifacts / ("mobile.png" if mobile else "desktop.png")))
