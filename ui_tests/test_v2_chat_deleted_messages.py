# test_v2_chat_deleted_messages.py
"""
UI test for deleted messages in the V2 chat.
Version: 0.261.256
Implemented in: 0.261.256

With conversation archiving enabled, deleting a message keeps its stored document with
`metadata.is_deleted` set and masks it as a fail-safe. The V2 chat rendered those documents
as "This message is masked" both when a conversation opened and in the re-read that follows a
delete (#1649). This test ensures that:

- a deleted message never renders, on load or after the re-read that follows deleting one;
- deleting an answer sends `delete_thread: false`, and the answer stays gone afterwards;
- the attempt control counts the attempts that remain by position ("2/2"), rather than by
  attempt number ("3/2") once a deleted attempt is left out of the reported set.

The production MessageList, Composer and chat store run in Chromium with production CSS. Only
HTTP is stubbed, and the stub answers `/api/get_messages` the way the server did before the
fix, deleted messages included, so the test proves the client never renders one on its own.

Build CSS with the existing V2 build, keeping outputs in UI test artifacts:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_chat_deleted_messages.py -q
"""

import copy
import time
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import expect

import test_v2_orchestration_plan_editor as editor_tests
from test_v2_orchestration_plan_editor import (  # noqa: F401
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
CHAT = "budget-review"
TITLE = "Budget review"
MASKED_NOTICE = "This message is masked"
TRAVEL_QUESTION = "What is the travel budget?"
TRAVEL_ANSWER = "The travel budget is 12,000."
DELETED_QUESTION = "Share the old pricing sheet."
DELETED_ANSWER = "Here is the old pricing sheet."
TRAINING_QUESTION = "And the training budget?"
TRAINING_ANSWER = "The training budget is 4,000."


def message(message_id, role, content, thread=None, attempt=1, deleted=False):
    metadata = {}
    if thread:
        metadata["thread_info"] = {"thread_id": thread, "thread_attempt": attempt, "active_thread": True}
    if deleted:
        soft_delete(metadata)
    return {"id": message_id, "conversation_id": CHAT, "role": role, "content": content, "metadata": metadata}


def soft_delete(metadata):
    """What the delete route stores when archiving is enabled."""
    metadata.update({
        "is_deleted": True,
        "deleted_by_user_id": "tester",
        "masked": True,
        "masked_by_user_id": "tester",
    })


class DeletedMessagesApi:
    """Serves the harness and answers the chat's reads; anything else fails the test."""

    def __init__(self, assets):
        self.assets = assets
        self.errors = []
        self.reads = 0
        self.deletes = []
        self.switches = []
        self.messages = []
        self.attempts = {}
        self.active_attempt = None

    def visible_messages(self):
        """The conversation as the server returned it before the fix: deleted messages included."""
        messages = list(self.messages)
        if self.attempts:
            messages.extend(self.attempts[self.active_attempt])
        return copy.deepcopy(messages)

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        if path == "/api/get_messages":
            self.reads += 1
            route.fulfill(json={"messages": self.visible_messages()})
            return
        if request.method == "DELETE" and path.startswith("/api/message/"):
            message_id = unquote(path.rsplit("/", 1)[-1])
            self.deletes.append((message_id, request.post_data_json or {}))
            for stored in self.messages:
                if stored["id"] == message_id:
                    soft_delete(stored["metadata"])
            route.fulfill(json={"success": True, "deleted_message_ids": [message_id], "archived": True})
            return
        if request.method == "POST" and path.endswith("/switch-attempt"):
            direction = (request.post_data_json or {}).get("direction")
            available = sorted(self.attempts)
            step = -1 if direction == "prev" else 1
            self.active_attempt = available[(available.index(self.active_attempt) + step) % len(available)]
            self.switches.append(direction)
            route.fulfill(json={
                "success": True, "target_attempt": self.active_attempt, "available_attempts": available,
            })
            return
        if path.startswith("/api/conversations/") and path.endswith("/metadata"):
            route.fulfill(json={"conversation_id": CHAT, "title": TITLE})
            return
        if path.startswith("/api/chat/stream/status/"):
            route.fulfill(json={"active": False, "pending": False, "reattachable": False})
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
        self.errors.append(f"Unexpected request: {request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test request."})


@pytest.fixture
def chat_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    api = DeletedMessagesApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    page.on("console", lambda entry: api.errors.append(entry.text) if entry.type == "error" else None)
    try:
        yield page, api
    finally:
        context.close()
        assert not api.errors, api.errors


def open_conversation(page, api):
    """Mount the real message list and composer, then open the conversation through the store."""
    page.goto(editor_tests.ORIGIN + editor_tests.HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=editor_tests.ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {
                features: {enable_chat_orchestration: false},
                settings: {}, user: {id: 'tester', display_name: 'Tester'},
                catalogs: {models: [], agents: [], prompts: []},
                scope: {groups: [], public_workspaces: []},
                orchestration: {enabled: false, capabilities: [], default_approval_mode: 'manual'},
            }});
            H.stores.chat.useChatStore.setState({
                activeConversationId: null, activeConversationKind: null, messages: [],
                messagesLoading: false, messagesError: null, streaming: false,
                streamError: null, streamingContent: '', thoughts: [], attemptsByThread: {},
                conversations: [{id: spec.chat, title: spec.title}],
            });
            H.mount('mount-a', 'PromptExperience', {}, {initialEntries: ['/chat']});
        }""",
        {"chat": CHAT, "title": TITLE},
    )
    page.evaluate("(id) => window.OrchHarness.stores.chat.useChatStore.getState().selectConversation(id)", CHAT)


def stored_message_ids(page):
    return page.evaluate(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().messages.map((item) => item.id)"
    )


def wait_until(page, predicate, description, timeout=10):
    """Let Playwright dispatch routes and renders until a Python-side condition holds."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"Timed out waiting for {description}")
        page.wait_for_timeout(50)


def open_actions(page, message_id):
    row = page.locator(f"#message-{message_id}")
    row.hover()
    row.get_by_role("button", name="More actions", exact=True).click()
    return row


def test_deleted_messages_never_render_on_load_or_after_a_delete(chat_ui):
    """A deleted message is never shown, not even as a masked one."""
    page, api = chat_ui
    api.messages = [
        message("q0", "user", TRAVEL_QUESTION),
        message("a0", "assistant", TRAVEL_ANSWER),
        message("q9", "user", DELETED_QUESTION, deleted=True),
        message("a9", "assistant", DELETED_ANSWER, deleted=True),
        message("q1", "user", TRAINING_QUESTION),
        message("a1", "assistant", TRAINING_ANSWER),
    ]

    open_conversation(page, api)

    expect(page.get_by_text(TRAINING_ANSWER, exact=True)).to_be_visible()
    expect(page.get_by_text(TRAVEL_QUESTION, exact=True)).to_be_visible()
    expect(page.get_by_text(MASKED_NOTICE)).to_have_count(0)
    expect(page.get_by_text(DELETED_QUESTION)).to_have_count(0)
    expect(page.get_by_text(DELETED_ANSWER)).to_have_count(0)
    assert stored_message_ids(page) == ["q0", "a0", "q1", "a1"]

    row = open_actions(page, "a1")
    row.get_by_role("button", name="Delete", exact=True).click()

    # The delete is followed by a re-read, which comes back with the answer marked deleted.
    wait_until(page, lambda: api.reads >= 2, "the re-read after the delete")
    wait_until(
        page,
        lambda: page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().metadata === null"),
        "the re-read to finish",
    )
    assert api.deletes == [("a1", {"delete_thread": False})]
    expect(page.get_by_text(TRAINING_QUESTION, exact=True)).to_be_visible()
    expect(page.get_by_text(TRAINING_ANSWER)).to_have_count(0)
    expect(page.get_by_text(MASKED_NOTICE)).to_have_count(0)
    assert stored_message_ids(page) == ["q0", "a0", "q1"]


def test_attempt_control_counts_remaining_attempts_by_position(chat_ui):
    """With attempt 2 deleted, attempts 1 and 3 read as 1/2 and 2/2, never 3/2."""
    page, api = chat_ui
    api.attempts = {
        1: [
            message("q1", "user", "Summarise the budget.", thread="t1", attempt=1),
            message("a1", "assistant", "First summary of the budget.", thread="t1", attempt=1),
        ],
        3: [
            message("q3", "user", "Summarise the budget.", thread="t1", attempt=3),
            message("a3", "assistant", "Third summary of the budget.", thread="t1", attempt=3),
        ],
    }
    api.active_attempt = 3

    open_conversation(page, api)
    expect(page.get_by_text("Third summary of the budget.", exact=True)).to_be_visible()

    page.locator("#message-a3").hover()
    page.locator("#message-a3").get_by_role("button", name="Next attempt", exact=True).click()
    expect(page.get_by_text("First summary of the budget.", exact=True)).to_be_visible()
    first = page.locator("#message-a1").get_by_title("Attempt 1 of 2", exact=True)
    expect(first).to_have_text("1/2")

    page.locator("#message-a1").hover()
    page.locator("#message-a1").get_by_role("button", name="Next attempt", exact=True).click()
    expect(page.get_by_text("Third summary of the budget.", exact=True)).to_be_visible()
    third = page.locator("#message-a3").get_by_title("Attempt 2 of 2", exact=True)
    expect(third).to_have_text("2/2")
    expect(page.get_by_text("3/2", exact=True)).to_have_count(0)
    assert api.switches == ["next", "next"]
