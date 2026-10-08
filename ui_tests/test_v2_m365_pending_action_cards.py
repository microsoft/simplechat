# test_v2_m365_pending_action_cards.py
"""
UI test for Microsoft 365 pending-action cards in the V2 chat.
Version: 0.261.307
Implemented in: 0.261.307

This test ensures that a saved outgoing Microsoft 365 email or calendar action is drawn in the V2
chat the way the classic chat draws it: live under the streaming reply and then under the saved
reply that created it, inline under that reply when the conversation is reopened, and in a
conversation-level section when no visible message claims it. It also ensures that Send and Cancel
act on the exact saved version through the CSRF-protected endpoints and report what the server
says, that a conflicting send is reported and never retried, that opening a card never sends it,
that a notification's deep link scrolls to, highlights and focuses its card exactly once, that a
card only reachable by id is still found, that a link to a card the viewer cannot see says so, and
that a failed list is shown and can be read again.

It drives the real bundled V2 components over a local static server with a synthetic HTTP
boundary, so no Azure credentials or network access are needed.
"""

import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401
from ui_tests.fixtures.orchestration import harness_build

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


pytestmark = pytest.mark.ui
IMPLEMENTED_IN = "0.261.307"
CONVERSATION_ID = "conversation-m365"
LIST_PATH = "/api/msgraph/pending-actions"
USER_TEXT = "Email Ann the quarterly numbers"
REPLY_TEXT = "I saved a draft email to Ann. Review it below before it goes out."
PENDING_STATUS = "Pending \u2014 not sent."
SENT_STATUS = "Accepted for sending \u2014 recipient delivery is not confirmed."
CANCELLED_STATUS = "Cancelled \u2014 no further delivery is scheduled for this action."
SEND_NOTICE = "Send request checked. Review the server status and delivery note below."
CANCEL_NOTICE = (
    "Cancellation checked. The server status below is authoritative; "
    "this does not recall an already sent item."
)
CONFLICT_NOTICE = (
    "This action changed or is already being processed. "
    "Review its current status and details before making another choice."
)
UNAVAILABLE = (
    "That Microsoft 365 action is not available in this conversation. "
    "It may have been removed, or you may not have access to it."
)
OWNER_ONLY = "Only the action owner can send or cancel this action. This view is read-only."
SECTION_NAME = "Microsoft 365 outgoing actions for this conversation"

# Replaces window.fetch with a backend for the endpoints the cards use. Every request is logged on
# window.requests, so a test can say exactly what the page asked for and what it posted.
STUB_BACKEND = r"""(config) => {
    const encoder = new TextEncoder();
    const json = (body, status = 200) => new Response(JSON.stringify(body), {
        status, headers: { 'Content-Type': 'application/json' },
    });
    window.requests = [];
    window.listFails = Boolean(config.listFails);
    window.changeStatus = 200;
    window.listedActions = config.list;
    window.actionsById = Object.fromEntries(config.byId.map((action) => [action.id, action]));
    window.fetch = async (url, init = {}) => {
        const target = new URL(String(url), window.location.origin);
        const path = target.pathname;
        const method = String(init.method || 'GET').toUpperCase();
        window.requests.push({
            method, path, search: target.search, headers: { ...(init.headers || {}) },
            body: typeof init.body === 'string' ? JSON.parse(init.body) : null,
        });
        if (path === '/api/chat/stream') {
            return new Response(new ReadableStream({
                start(controller) {
                    window.pushChatFrame = (frame) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
                    window.closeChatFrames = () => controller.close();
                },
            }), { headers: { 'Content-Type': 'text/event-stream' } });
        }
        if (path === '/api/m365/preferences') {
            return json({ success: true, csrf_token: 'c'.repeat(40) });
        }
        if (path === '/api/msgraph/pending-actions' && method === 'GET') {
            if (window.listFails) {
                return json({ success: false, message: 'The list is unavailable.' }, 500);
            }
            return json({ success: true, pending_actions: window.listedActions, continuation_token: '' });
        }
        const detail = path.match(/^\/api\/msgraph\/pending-actions\/([^/]+)$/);
        if (detail && method === 'GET') {
            const action = window.actionsById[decodeURIComponent(detail[1])];
            return action
                ? json({ success: true, pending_action: action })
                : json({ success: false, error: 'not_found', message: 'Not found.' }, 404);
        }
        const change = path.match(/^\/api\/msgraph\/pending-actions\/([^/]+)\/(send-now|approve|cancel)$/);
        if (change && method === 'POST') {
            const id = decodeURIComponent(change[1]);
            const current = window.actionsById[id];
            if (!current) {
                return json({ success: false, error: 'not_found', message: 'Not found.' }, 404);
            }
            if (window.changeStatus !== 200) {
                return json({ success: false, error: 'version_conflict', message: 'The action changed.' }, window.changeStatus);
            }
            const next = {
                ...current, version: 'v2', status: change[2] === 'cancel' ? 'cancelled' : 'sent',
                can_cancel: false, can_send_now: false, updated_at: '2026-10-07T16:05:00Z',
            };
            window.actionsById[id] = next;
            return json({ success: true, pending_action: next });
        }
        return json({ success: true, messages: [] });
    };
}"""

# Opens the conversation in a real MessageList. With `send`, the message is sent over the stubbed
# chat stream, which the test then drives frame by frame.
SEED_THREAD = r"""({ messages, send }) => {
    const H = window.OrchHarness;
    H.reset();
    H.stores.bootstrap.useBootstrapStore.setState({
        data: { features: {}, settings: {}, catalogs: { models: [], agents: [], prompts: [] },
            user: { id: 'owner', display_name: 'Tester' }, scope: {} },
    });
    H.stores.chat.useChatStore.setState({
        activeConversationId: 'conversation-m365', activeConversationKind: 'personal',
        messages, streaming: false, messagesLoading: false,
    });
    H.mount('mount-a', 'MessageList');
    if (send) {
        void H.stores.chat.useChatStore.getState().sendMessage(send, {});
    }
}"""

REQUEST_FOCUS = r"""({ id, conversationId }) => {
    window.OrchHarness.stores.pendingActions.chatPendingActionsStore.getState().requestFocus(id, conversationId);
}"""

# Records every change to a card's highlight, so a test sees the highlight come and go however
# quickly it does.
WATCH_HIGHLIGHT = r"""() => {
    window.highlightLog = [];
    new MutationObserver((records) => {
        for (const record of records) {
            window.highlightLog.push(record.target.getAttribute('data-highlighted'));
        }
    }).observe(document.body, { subtree: true, attributes: true, attributeFilter: ['data-highlighted'] });
}"""

# Records the scroll the deep link asks for, without depending on the page being tall enough to move.
WATCH_SCROLL = r"""() => {
    window.scrollCalls = [];
    const original = Element.prototype.scrollTo;
    Element.prototype.scrollTo = function (...args) {
        window.scrollCalls.push(args[0]);
        return original.apply(this, args);
    };
}"""


def pending_action(action_id, subject="Quarterly numbers", **overrides):
    """A saved outgoing email in the shape the server sends it."""
    action = {
        "type": "msgraph_pending_action",
        "id": action_id,
        "version": "v1",
        "status": "pending",
        "operation": "send_mail",
        "graph_resource_type": "mail",
        "subject": subject,
        "summary": {
            "subject": subject,
            "body_preview": f"Hello Ann, here is {subject.lower()}.",
            "body_preview_truncated": False,
            "to_recipients": ["ann@example.com"],
        },
        "can_cancel": True,
        "can_send_now": True,
        "viewer_is_owner": True,
        "review_details_required": False,
        "conversation_id": CONVERSATION_ID,
        "updated_at": "2026-10-07T16:00:00Z",
    }
    action.update(overrides)
    return action


def thread(*cards, request_id="req-hist"):
    """A saved thread whose assistant reply carries the given cards."""
    return [
        {"id": "u-1", "conversation_id": CONVERSATION_ID, "role": "user", "content": USER_TEXT},
        {
            "id": "a-1", "conversation_id": CONVERSATION_ID, "role": "assistant", "content": REPLY_TEXT,
            "metadata": {"m365_request_id": request_id},
            "m365_pending_actions": list(cards),
        },
    ]


def _require_bundle():
    try:
        harness_build.ensure_bundle()
    except harness_build.HarnessUnavailable as exc:
        pytest.skip(str(exc))


def _collect_page_errors(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    return errors


def _open_chat(page, origin, *, messages, listed=(), by_id=(), send=None, listing_fails=False):
    response = page.goto(f"{origin}/{harness_build.HARNESS_HTML_REL}")
    assert response is not None and response.ok
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    page.evaluate(STUB_BACKEND, {"list": list(listed), "byId": list(by_id), "listFails": listing_fails})
    page.evaluate(SEED_THREAD, {"messages": messages, "send": send})
    return page.locator("#mount-a")


def _requests(page):
    return page.evaluate("() => window.requests")


def _posts(page):
    return [request for request in _requests(page) if request["method"] == "POST"]


def _posts_to_actions(page):
    return [request for request in _posts(page) if request["path"].startswith(LIST_PATH + "/")]


def _wait_for_list(page):
    page.wait_for_function(
        "(path) => window.requests.some((request) => request.method === 'GET' && request.path === path)",
        arg=LIST_PATH,
    )


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


def test_card_follows_its_reply_from_streaming_to_saved(page):
    _require_bundle()
    errors = _collect_page_errors(page)
    action = pending_action("act-live", request_id="req-live")
    with harness_build.start_static_server() as origin:
        root = _open_chat(page, origin, messages=[], send=USER_TEXT)
        page.wait_for_function("() => typeof window.pushChatFrame === 'function'")

        # Saved while the reply is still being written: it appears at once, under the turn that
        # caused it, ready to be used.
        page.evaluate(
            """(action) => window.pushChatFrame({
                type: 'm365_pending_action', request_id: 'req-live', pending_action: action,
            })""",
            action,
        )
        card = root.get_by_test_id("v2-pending-action-card")
        expect(card).to_have_count(1)
        expect(card).to_have_attribute("data-pending-action-id", "act-live")
        expect(card.get_by_test_id("v2-pending-action-status")).to_have_text(PENDING_STATUS)
        expect(card.get_by_test_id("v2-pending-action-send")).to_be_enabled()
        expect(card.get_by_test_id("v2-pending-action-cancel")).to_be_enabled()
        expect(root.get_by_test_id("v2-pending-action-slot")).to_have_count(1)
        expect(root.get_by_test_id("v2-pending-actions-section")).to_have_count(0)
        user_box = root.get_by_text(USER_TEXT, exact=True).first.bounding_box()
        assert user_box is not None
        assert card.bounding_box()["y"] >= user_box["y"] + user_box["height"] - 1

        # The server saves the user's message under its own id part-way through: the card must
        # not lose its place.
        page.evaluate(
            "() => window.pushChatFrame({type: 'user_message_persisted', user_message_id: 'u-live'})"
        )
        expect(card).to_have_count(1)
        expect(root.get_by_test_id("v2-pending-action-slot")).to_have_count(1)

        # The reply is saved and the finishing frame lists the action again: still one card, now
        # under the reply rather than loose at the end of the thread.
        page.evaluate(
            """({action, reply}) => {
                window.pushChatFrame({
                    done: true, role: 'assistant', replace_content: true, content: reply, full_content: reply,
                    message_id: 'reply-1', conversation_id: 'conversation-m365', metadata: {},
                    m365_pending_actions: [action],
                });
                window.closeChatFrames();
            }""",
            {"action": action, "reply": REPLY_TEXT},
        )
        reply = root.get_by_text(REPLY_TEXT, exact=True).first
        expect(reply).to_be_visible()
        expect(card).to_have_count(1)
        expect(root.get_by_test_id("v2-pending-action-slot")).to_have_count(1)
        expect(root.get_by_test_id("v2-pending-actions-section")).to_have_count(0)
        reply_box = reply.bounding_box()
        assert reply_box is not None
        assert card.bounding_box()["y"] >= reply_box["y"] + reply_box["height"] - 1
        assert not _posts_to_actions(page)
    assert errors == []


def test_reopened_conversation_draws_cards_under_their_reply_or_in_the_section(page):
    _require_bundle()
    errors = _collect_page_errors(page)
    claimed = pending_action("act-hist", subject="Budget approval", request_id="req-hist")
    unclaimed = pending_action("act-orphan", subject="Unrelated draft", request_id="req-other")
    shared = pending_action(
        "act-other", subject="Shared draft", request_id="req-shared",
        viewer_is_owner=False, can_cancel=False, can_send_now=False,
    )
    with harness_build.start_static_server() as origin:
        root = _open_chat(
            page, origin,
            messages=thread(claimed),
            listed=[claimed, unclaimed, shared],
            by_id=[claimed, unclaimed, shared],
        )

        slot = root.get_by_test_id("v2-pending-action-slot")
        expect(slot).to_have_count(1)
        expect(slot).to_have_attribute("aria-label", "Microsoft 365 actions for this message")
        inline = slot.get_by_test_id("v2-pending-action-card")
        expect(inline).to_have_count(1)
        expect(inline).to_have_attribute("data-pending-action-id", "act-hist")
        expect(inline).to_have_attribute("aria-label", "Microsoft 365 email: Budget approval")
        expect(inline).to_contain_text("ann@example.com")
        expect(inline.get_by_role("link", name="Open conversation")).to_have_count(0)
        # A card opened from history is not usable until the server has confirmed its state.
        expect(inline.get_by_test_id("v2-pending-action-send")).to_be_enabled()
        expect(inline.get_by_test_id("v2-pending-action-cancel")).to_be_enabled()

        reply_box = root.get_by_text(REPLY_TEXT, exact=True).first.bounding_box()
        assert reply_box is not None
        assert inline.bounding_box()["y"] >= reply_box["y"] + reply_box["height"] - 1

        section = root.get_by_role("region", name=SECTION_NAME)
        expect(section).to_be_visible()
        expect(section.get_by_test_id("v2-pending-action-card")).to_have_count(2)
        expect(section.locator("[data-pending-action-id='act-orphan']")).to_have_count(1)
        expect(section.locator("[data-pending-action-id='act-other']")).to_have_count(1)
        expect(section.locator("[data-pending-action-id='act-hist']")).to_have_count(0)
        expect(section.get_by_test_id("v2-pending-actions-refresh")).to_be_enabled()

        # Someone else's action in a shared conversation can be read but not changed.
        read_only = section.locator("[data-pending-action-id='act-other']")
        expect(read_only).to_contain_text(OWNER_ONLY)
        expect(read_only.get_by_test_id("v2-pending-action-send")).to_have_count(0)
        expect(read_only.get_by_test_id("v2-pending-action-cancel")).to_have_count(0)

        # Looking at cards never sends or cancels anything.
        assert not _posts_to_actions(page)
        requests = _requests(page)
        listed = [r for r in requests if r["method"] == "GET" and r["path"] == LIST_PATH]
        assert listed and all(f"conversation_id={CONVERSATION_ID}" in r["search"] for r in listed)
        confirmed = [r for r in requests if r["path"] == f"{LIST_PATH}/act-hist"]
        assert confirmed and all(f"conversation_id={CONVERSATION_ID}" in r["search"] for r in confirmed)
    assert errors == []


def test_conversation_without_saved_actions_shows_no_card_or_section(page):
    _require_bundle()
    errors = _collect_page_errors(page)
    with harness_build.start_static_server() as origin:
        root = _open_chat(page, origin, messages=thread(), listed=[], by_id=[])
        _wait_for_list(page)
        expect(root.get_by_text(REPLY_TEXT, exact=True).first).to_be_visible()
        page.wait_for_timeout(300)
        expect(root.get_by_test_id("v2-pending-action-card")).to_have_count(0)
        expect(root.get_by_test_id("v2-pending-action-slot")).to_have_count(0)
        expect(root.get_by_test_id("v2-pending-actions-section")).to_have_count(0)
    assert errors == []


def test_send_and_cancel_act_on_the_saved_version_and_report_the_servers_answer(page):
    _require_bundle()
    errors = _collect_page_errors(page)
    to_send = pending_action("act-send", subject="Send me")
    to_cancel = pending_action("act-cancel", subject="Cancel me")
    with harness_build.start_static_server() as origin:
        root = _open_chat(
            page, origin,
            messages=thread(to_send, to_cancel),
            listed=[to_send, to_cancel],
            by_id=[to_send, to_cancel],
        )
        send_card = root.locator("[data-pending-action-id='act-send']")
        cancel_card = root.locator("[data-pending-action-id='act-cancel']")
        expect(send_card.get_by_test_id("v2-pending-action-send")).to_be_enabled()
        expect(cancel_card.get_by_test_id("v2-pending-action-cancel")).to_be_enabled()
        page.evaluate("() => { window.requests.length = 0; }")

        send_card.get_by_test_id("v2-pending-action-send").click()
        expect(send_card.get_by_test_id("v2-pending-action-status")).to_have_text(SENT_STATUS)
        expect(send_card.get_by_test_id("v2-pending-action-notice")).to_have_text(SEND_NOTICE)
        expect(send_card.get_by_test_id("v2-pending-action-send")).to_have_count(0)
        expect(send_card.get_by_test_id("v2-pending-action-cancel")).to_have_count(0)
        # The other card is untouched by it.
        expect(cancel_card.get_by_test_id("v2-pending-action-status")).to_have_text(PENDING_STATUS)
        expect(cancel_card.get_by_test_id("v2-pending-action-send")).to_be_enabled()

        cancel_card.get_by_test_id("v2-pending-action-cancel").click()
        expect(cancel_card.get_by_test_id("v2-pending-action-status")).to_have_text(CANCELLED_STATUS)
        expect(cancel_card.get_by_test_id("v2-pending-action-notice")).to_have_text(CANCEL_NOTICE)
        expect(cancel_card.get_by_test_id("v2-pending-action-send")).to_have_count(0)
        expect(cancel_card.get_by_test_id("v2-pending-action-cancel")).to_have_count(0)

        posts = _posts(page)
        assert [(post["path"], post["body"]) for post in posts] == [
            (f"{LIST_PATH}/act-send/send-now", {"expected_version": "v1"}),
            (f"{LIST_PATH}/act-cancel/cancel", {"expected_version": "v1"}),
        ]
        for post in posts:
            assert post["headers"]["X-M365-CSRF-Token"] == "c" * 40
            assert post["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert errors == []


def test_a_conflicting_send_is_reported_and_never_retried(page):
    _require_bundle()
    errors = _collect_page_errors(page)
    action = pending_action("act-conflict", subject="Changed elsewhere")
    with harness_build.start_static_server() as origin:
        root = _open_chat(page, origin, messages=thread(action), listed=[action], by_id=[action])
        card = root.locator("[data-pending-action-id='act-conflict']")
        expect(card.get_by_test_id("v2-pending-action-send")).to_be_enabled()
        page.evaluate("() => { window.changeStatus = 409; window.requests.length = 0; }")

        card.get_by_test_id("v2-pending-action-send").click()
        expect(card.get_by_test_id("v2-pending-action-notice")).to_have_text(CONFLICT_NOTICE)
        # Nothing was sent, so the card still says so and is read again from the server.
        expect(card.get_by_test_id("v2-pending-action-status")).to_have_text(PENDING_STATUS)
        expect(card.get_by_test_id("v2-pending-action-send")).to_be_enabled()
        page.wait_for_timeout(300)
        assert len(_posts(page)) == 1
        refreshed = [r for r in _requests(page) if r["method"] == "GET" and r["path"] == f"{LIST_PATH}/act-conflict"]
        assert refreshed
    assert errors == []


def test_deep_link_scrolls_to_highlights_and_focuses_the_card_once(page):
    _require_bundle()
    errors = _collect_page_errors(page)
    action = pending_action("act-hist", subject="Budget approval")
    with harness_build.start_static_server() as origin:
        root = _open_chat(page, origin, messages=thread(action), listed=[action], by_id=[action])
        page.evaluate(WATCH_HIGHLIGHT)
        page.evaluate(WATCH_SCROLL)
        card = root.locator("[data-pending-action-id='act-hist']")
        expect(card).to_have_count(1)
        expect(card.get_by_test_id("v2-pending-action-send")).to_be_enabled()

        page.evaluate(REQUEST_FOCUS, {"id": "act-hist", "conversationId": CONVERSATION_ID})
        expect(card).to_be_focused()
        expect(card).to_have_attribute("data-highlighted", "true")
        scrolls = page.evaluate("() => window.scrollCalls")
        assert len(scrolls) == 1
        assert isinstance(scrolls[0]["top"], (int, float)) and scrolls[0]["top"] >= 0
        assert scrolls[0]["behavior"] in ("smooth", "auto")

        # The highlight is a moment's cue, not a permanent state, and focus stays where it was put.
        page.wait_for_function("() => window.highlightLog.length >= 2", timeout=10000)
        assert page.evaluate("() => window.highlightLog") == ["true", None]
        expect(card).to_be_focused()
        # The request was spent, so nothing scrolls or highlights again by itself.
        assert page.evaluate(
            "() => window.OrchHarness.stores.pendingActions.chatPendingActionsStore.getState().focusRequest"
        ) is None
        page.wait_for_timeout(300)
        assert len(page.evaluate("() => window.scrollCalls")) == 1
        assert not _posts_to_actions(page)
    assert errors == []


def test_deep_link_finds_a_card_that_only_exists_by_id(page):
    _require_bundle()
    errors = _collect_page_errors(page)
    older = pending_action("act-old", subject="Older draft", request_id="req-old")
    with harness_build.start_static_server() as origin:
        root = _open_chat(page, origin, messages=thread(), listed=[], by_id=[older])
        _wait_for_list(page)
        expect(root.get_by_test_id("v2-pending-action-card")).to_have_count(0)

        page.evaluate(REQUEST_FOCUS, {"id": "act-old", "conversationId": CONVERSATION_ID})
        card = root.locator("[data-pending-action-id='act-old']")
        expect(card).to_have_count(1)
        expect(card).to_be_focused()
        expect(card).to_have_attribute("data-highlighted", "true")
        expect(root.get_by_role("region", name=SECTION_NAME).locator("[data-pending-action-id='act-old']")).to_have_count(1)
        expect(root.get_by_test_id("v2-pending-action-focus-unavailable")).to_have_count(0)
        fetched = [r for r in _requests(page) if r["path"] == f"{LIST_PATH}/act-old"]
        assert fetched and f"conversation_id={CONVERSATION_ID}" in fetched[0]["search"]
    assert errors == []


def test_deep_link_to_a_card_the_viewer_cannot_open_says_so(page):
    _require_bundle()
    errors = _collect_page_errors(page)
    action = pending_action("act-hist", subject="Budget approval")
    with harness_build.start_static_server() as origin:
        root = _open_chat(page, origin, messages=thread(action), listed=[action], by_id=[action])
        expect(root.locator("[data-pending-action-id='act-hist']")).to_have_count(1)

        page.evaluate(REQUEST_FOCUS, {"id": "act-gone", "conversationId": CONVERSATION_ID})
        notice = root.get_by_test_id("v2-pending-action-focus-unavailable")
        expect(notice).to_be_visible()
        expect(notice).to_have_attribute("role", "status")
        expect(notice).to_contain_text(UNAVAILABLE)
        # The cards that are there stay usable, and nothing was highlighted by mistake.
        expect(root.locator("[data-pending-action-id='act-hist']")).not_to_have_attribute("data-highlighted", "true")
        asked = [r for r in _requests(page) if r["path"] == f"{LIST_PATH}/act-gone"]
        assert asked and f"conversation_id={CONVERSATION_ID}" in asked[0]["search"]

        notice.get_by_role("button", name="Dismiss").click()
        expect(notice).to_have_count(0)
        assert not _posts_to_actions(page)
    assert errors == []


def test_failed_list_is_shown_and_can_be_read_again(page):
    _require_bundle()
    errors = _collect_page_errors(page)
    unclaimed = pending_action("act-orphan", subject="Unrelated draft", request_id="req-other")
    with harness_build.start_static_server() as origin:
        root = _open_chat(
            page, origin, messages=thread(), listed=[unclaimed], by_id=[unclaimed], listing_fails=True,
        )
        error = root.get_by_test_id("v2-pending-actions-error")
        expect(error).to_be_visible()
        expect(root.get_by_role("region", name=SECTION_NAME)).to_be_visible()
        expect(root.get_by_test_id("v2-pending-action-card")).to_have_count(0)

        page.evaluate("() => { window.listFails = false; }")
        root.get_by_test_id("v2-pending-actions-refresh").click()
        expect(root.get_by_test_id("v2-pending-action-card")).to_have_count(1)
        expect(root.locator("[data-pending-action-id='act-orphan']")).to_have_count(1)
        expect(error).to_have_count(0)
        assert not _posts_to_actions(page)
    assert errors == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
