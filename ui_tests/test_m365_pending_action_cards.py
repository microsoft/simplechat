# test_m365_pending_action_cards.py
"""
Azure Playwright-ready chat, workflow, and Approvals pending-delivery regressions.

Version: 0.261.038
Implemented in: 0.261.038

Reuses the M365 suite's DefaultAzureCredential / azure-mgmt-playwright workspace
fixture, or its identical local Chromium fallback. Real local chat modules consume
structured tool-shaped DTOs through the SSE/JSON response handler; only APIs are
faked. These tests never access Graph, send mail, or create calendar events.
"""

import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from playwright.sync_api import expect

from test_m365_lifecycle_and_approvals import (
    CSRF_TOKEN,
    ORIGIN,
    approval,
    initialize_chat,
    m365_browser,
    start_chat_stream,
    ui,
)


pytestmark = pytest.mark.ui
PENDING_PATH = "/api/msgraph/pending-actions"


@pytest.fixture(scope="module")
def real_tool_transcript():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "functional_tests" / "test_m365_chat_action_cards.py"), "--offline", "--ui-transcript"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=150,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-6000:]
    prefix = "M365_UI_TRANSCRIPT="
    transcript = next((line[len(prefix):] for line in result.stdout.splitlines() if line.startswith(prefix)), None)
    assert transcript is not None, "The real typed-tool route did not emit a browser transcript."
    return json.loads(transcript)


def pending_action(action_id="calendar-one", resource="calendar", **changes):
    summary = {
        "subject": "Review the project plan",
        "body_preview": "Review the milestones before sending.",
        "content_type": "text",
    }
    if resource == "calendar":
        summary.update({
            "attendee_recipients": ["reviewer@example.test"],
            "start_datetime": "2026-09-21T10:00:00",
            "end_datetime": "2026-09-21T10:30:00",
            "timezone": "Eastern Standard Time",
            "location": "Planning room",
            "teams_meeting_requested": True,
        })
    else:
        summary.update({
            "to_recipients": ["reviewer@example.test"],
            "cc_recipients": ["copy@example.test"],
            "bcc_recipients": ["private@example.test"],
        })
    return {
        "id": action_id, "type": "msgraph_pending_action",
        "operation": "create_calendar_invite" if resource == "calendar" else "send_mail",
        "graph_resource_type": resource, "version": "opaque-version-1",
        "viewer_is_owner": True, "auth_required": False,
        "status": "pending", "action_mode": "manual",
        "subject": summary["subject"], "summary": summary,
        "conversation_id": "visible-conversation", "workflow_id": None, "run_id": None,
        "message_id": "graph-draft-id-not-a-chat-message" if resource == "mail" else None,
        "event_id": None, "web_link": None,
        "created_at": "2026-09-19T22:10:00Z", "updated_at": "2026-09-19T22:10:00Z",
        "auto_send_at_utc": None, "delay_seconds": 0, "error": None, "delivery_note": None,
        "can_approve": True, "can_send_now": True, "can_cancel": True,
        "will_auto_send": False, "requires_review": False, "requires_recreation": False,
        "review_details_required": False,
        **changes,
    }


def long_body_action(resource="mail"):
    complete = pending_action(resource=resource)
    body = "Frozen reviewed content. " * 230 + '<img src=x onerror="window.fullReviewXss=true">'
    complete["summary"].update({
        "body_preview": body, "content_type": "html",
        "body_preview_truncated": False, "body_length": len(body),
    })
    preview = copy.deepcopy(complete)
    preview.update(review_details_required=True, can_send_now=False, can_approve=False)
    preview["summary"].update(body_preview=body[:4000], body_preview_truncated=True)
    return preview, complete


def shared_action(action_id="shared-action", **changes):
    record = pending_action(
        action_id, "mail", viewer_is_owner=False,
        can_approve=False, can_send_now=False, can_cancel=False, **changes,
    )
    for key in ("body_preview", "content_type", "bcc_recipients"):
        record["summary"].pop(key, None)
    return record


def action_event(action):
    tool_result = {
        "success": True, "operation": action["operation"],
        "pending_user_action": True, "pending_action": copy.deepcopy(action),
    }
    return {
        "type": "m365_pending_action", "pending_action": tool_result["pending_action"],
        "conversation_id": "visible-conversation", "request_id": "saved-request",
        "user_message_id": "saved-user-message",
    }


def final_event(actions=None):
    return {
        "done": True, "conversation_id": "visible-conversation",
        "message_id": "saved-assistant-message", "user_message_id": "saved-user-message",
        "full_content": "An ordinary answer, with no delivery instructions.",
        **({"m365_pending_actions": copy.deepcopy(actions)} if actions is not None else {}),
    }


class PendingApi:
    def __init__(self, api):
        self.api = api
        self.delegate = api.handle_api
        self.records = {}
        self.include_in_list = False
        self.page_size = 30
        self.queries = []
        self.detail_reads = []
        self.detail_requests = []
        self.readable_conversations = {}
        self.writes = []
        self.failures = []
        self.list_failure = None
        self.detail_failure = None
        self.network_outcome = None
        self.delivery_note = None
        self.hold_stream = False
        self.held_stream = None
        self.hold_next_list = False
        self.held_list = None
        self.revision = 1

    def update(self, action_id, **changes):
        self.revision += 1
        self.records[action_id].update({
            "version": f"opaque-version-{self.revision}",
            "updated_at": f"2026-09-19T22:10:{self.revision:02d}Z",
            **changes,
        })

    def handle_api(self, route, path):
        if path == "/api/chat/stream" and self.hold_stream:
            self.api.chat_requests.append(route.request.post_data_json)
            self.held_stream = route
            return
        if not path.startswith(PENDING_PATH):
            self.delegate(route, path)
            return
        request = route.request
        if path == PENDING_PATH:
            query = parse_qs(urlsplit(request.url).query)
            self.queries.append(query)
            if self.hold_next_list:
                self.hold_next_list = False
                self.held_list = route
                return
            if self.list_failure:
                payload, status = self.list_failure
                self.api.respond(route, payload, status)
                return
            records = list(self.records.values()) if self.include_in_list else []
            if "conversation_id" in query:
                records = [
                    item for item in records
                    if query["conversation_id"][0] in self.readable_conversations.get(
                        item["id"], {item["conversation_id"]},
                    )
                ]
            if query.get("active_only") == ["1"]:
                records = [item for item in records if item["status"] in ("pending", "scheduled", "sending", "review_required", "recovery_required")]
            start = int(query.get("continuation_token", ["0"])[0])
            stop = start + self.page_size
            self.api.respond(route, {
                "success": True, "pending_actions": records[start:stop],
                "continuation_token": str(stop) if stop < len(records) else None,
            })
            return
        suffix = path[len(PENDING_PATH) + 1:].split("/")
        action_id = unquote(suffix[0])
        action = self.records.get(action_id)
        if not action:
            self.api.respond(route, {"success": False, "message": "Action not found."}, 404)
            return
        if request.method == "GET":
            self.detail_reads.append(action_id)
            query = parse_qs(urlsplit(request.url).query)
            self.detail_requests.append({"id": action_id, "query": query})
            allowed_contexts = self.readable_conversations.get(action_id, {action["conversation_id"]})
            if ("conversation_id" in query and query["conversation_id"][0] not in allowed_contexts) or (
                action.get("viewer_is_owner") is False and "conversation_id" not in query
            ):
                self.api.respond(route, {"success": False, "message": "Action not found."}, 404)
                return
            if self.detail_failure:
                payload, status = self.detail_failure
                self.api.respond(route, payload, status)
            else:
                self.api.respond(route, {"success": True, "pending_action": action})
            return
        body = request.post_data_json
        self.writes.append({
            "id": action_id, "operation": suffix[-1], "body": body,
            "csrf": request.headers.get("x-m365-csrf-token"),
        })
        if action.get("viewer_is_owner") is False:
            self.api.respond(route, {"success": False, "error": "access_denied"}, 403)
            return
        if request.headers.get("x-m365-csrf-token") != CSRF_TOKEN:
            self.api.respond(route, {"success": False, "error": "m365_csrf_invalid"}, 403)
            return
        if self.network_outcome:
            outcome = self.network_outcome
            self.network_outcome = None
            self.update(action_id, status=outcome,
                        can_send_now=outcome == "pending", can_approve=outcome == "pending",
                        can_cancel=outcome == "pending")
            route.abort("failed")
            return
        if self.failures:
            payload, status = self.failures.pop(0)
            self.api.respond(route, payload, status)
            return
        if body != {"expected_version": action["version"]}:
            self.api.respond(route, {
                "success": False, "error": "pending_action_changed",
                "message": "Review the current version.", "pending_action": action,
            }, 409)
            return
        self.update(action_id, status="cancelled" if suffix[-1] == "cancel" else "sent",
                    can_send_now=False, can_approve=False, can_cancel=False, will_auto_send=False,
                    delivery_note=self.delivery_note or action.get("delivery_note"))
        self.api.respond(route, {"success": True, "pending_action": action})


@pytest.fixture
def pending_ui(ui, monkeypatch):
    page, api = ui
    api.include_chat_styles = True
    pending = PendingApi(api)
    monkeypatch.setattr(api, "handle_api", pending.handle_api)
    return page, api, pending


def open_chat(page, api, actions):
    api.stream_events = [*[action_event(action) for action in actions], final_event()]
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    start_chat_stream(page)


def card(page, action_id="calendar-one"):
    return page.locator(f'.m365-pending-action-card[data-pending-action-id="{action_id}"]')


def test_real_typed_tools_and_flask_stream_produce_usable_browser_cards(real_tool_transcript, pending_ui, monkeypatch):
    page, api, pending = pending_ui
    actions = real_tool_transcript["cards"]
    pending.records = {action["id"]: copy.deepcopy(action) for action in actions}
    api.stream_events = copy.deepcopy(real_tool_transcript["events"])
    original_update = pending.update

    def update(action_id, **changes):
        prior = datetime.fromisoformat(pending.records[action_id]["updated_at"].replace("Z", "+00:00"))
        original_update(action_id, **changes)
        pending.records[action_id]["updated_at"] = (prior + timedelta(seconds=1)).isoformat()

    monkeypatch.setattr(pending, "update", update)
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    start_chat_stream(page)
    expect(page.locator(".m365-pending-action-card")).to_have_count(2)
    assert not pending.writes
    for action in actions:
        current = card(page, action["id"])
        expect(current.get_by_role("button", name="Send", exact=True)).to_be_visible()
        expect(current.get_by_role("button", name="Cancel", exact=True)).to_be_visible()
        expect(current).to_contain_text("recipient@example.test")
        if action["graph_resource_type"] == "mail":
            expect(current).to_contain_text("private@example.test")
        current.get_by_role("button", name="Cancel", exact=True).click()
        expect(current).to_contain_text("Cancelled")
    assert [write["body"] for write in pending.writes] == [
        {"expected_version": action["version"]} for action in actions
    ]
    assert all(write["operation"] == "cancel" and write["csrf"] == CSRF_TOKEN for write in pending.writes)
    assert len(api.chat_requests) == 1 and not api.errors


def require_delivery_sharing(api, pending, action):
    record = approval("delivery-sharing")
    record["context"]["conversation_id"] = action["conversation_id"]
    record["sources"] = {"calendar": record["sources"]["calendar"]}
    api.records[record["id"]] = record
    pending.failures = [({
        "success": False, "error": "m365_sharing_required", "approval_required": True,
        "approvals": [{"id": record["id"]}],
    }, 403)]
    return record


def guard_original_resume(page):
    page.evaluate("""() => {
        window.unwantedResumeCalls = 0;
        window.SimpleChatM365Approvals.setResumeHandler(async () => {
            window.unwantedResumeCalls += 1;
            await window.SimpleChatM365Approvals.requestJson('/api/m365/requests/original/resume',
                { method: 'POST', body: {} });
        });
    }""")


def activate_collaboration_events(page):
    page.evaluate("""() => {
        window.collaborationSources = [];
        window.EventSource = class {
            constructor(url) {
                this.url = url;
                this.closed = false;
                window.collaborationSources.push(this);
            }
            close() { this.closed = true; }
        };
    }""")
    initialize_chat(page, shared=True)
    page.evaluate("() => window.chatCollaboration.activateConversation('visible-conversation')")
    page.evaluate("() => { window.pendingEventTime = new Date().toISOString(); }")


def emit_collaboration_action_refs(page, action_ids, conversation_id="visible-conversation"):
    page.evaluate("""({ actionIds, conversationId }) => {
        const source = window.collaborationSources[window.collaborationSources.length - 1];
        source.onmessage({ data: JSON.stringify({
            event_type: 'collaboration.m365.pending_action',
            conversation_id: conversationId,
            occurred_at: window.pendingEventTime,
            payload: {
                conversation_id: conversationId,
                metadata: {
                    m365_pending_action_ids: actionIds,
                    m365_request_id: 'collaboration-pending-request'
                }
            }
        }) });
    }""", {"actionIds": action_ids, "conversationId": conversation_id})


@pytest.mark.parametrize("resource,decision", [
    ("calendar", "Send"), ("calendar", "Cancel"), ("mail", "Send"), ("mail", "Cancel"),
])
def test_live_tool_card_survives_model_failure_and_needs_a_user_click(pending_ui, resource, decision):
    page, api, pending = pending_ui
    action = pending_action(resource=resource)
    pending.records[action["id"]] = copy.deepcopy(action)
    api.stream_events = [
        {"content": "Independent model prose."},
        action_event(action),
        {"error": "Model response stopped after the tool completed.", "done": True},
    ]
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    start_chat_stream(page)
    current = card(page)
    expect(current.get_by_role("button", name="Send", exact=True)).to_be_visible()
    expect(current.get_by_role("button", name="Cancel", exact=True)).to_be_visible()
    expect(current).to_contain_text("reviewer@example.test")
    expect(current).to_contain_text("Pending — not sent")
    expect(page.locator('[data-message-id="temp_user_m365"] .m365-pending-action-card')).to_have_count(1)
    assert not pending.writes
    assert not pending.include_in_list
    assert not api.m365_posts
    current.get_by_role("button", name=decision, exact=True).click()
    expected_status = "Accepted for sending" if resource == "mail" else "Sent — calendar invitation created"
    expect(current).to_contain_text(expected_status if decision == "Send" else "Cancelled")
    assert pending.writes == [{
        "id": action["id"], "operation": "send-now" if decision == "Send" else "cancel",
        "body": {"expected_version": "opaque-version-1"}, "csrf": CSRF_TOKEN,
    }]
    assert len(api.chat_requests) == 1
    assert not api.errors


@pytest.mark.parametrize("decision", ["Send", "Cancel"])
def test_mail_confirmation_keeps_the_draft_note_without_claiming_recipient_delivery(pending_ui, decision):
    page, api, pending = pending_ui
    action = pending_action("mail-receipt", "mail")
    pending.records[action["id"]] = copy.deepcopy(action)
    pending.delivery_note = "The original Outlook draft remains in Outlook and was not deleted."
    open_chat(page, api, [action])
    current = card(page, action["id"])
    current.get_by_role("button", name=decision, exact=True).click()
    expect(current).to_contain_text(pending.delivery_note)
    if decision == "Send":
        expect(current).to_contain_text("Accepted for sending")
        expect(current).to_contain_text("recipient delivery is not confirmed")
    else:
        expect(current).to_contain_text("Cancelled")
    expect(current).not_to_contain_text("delivery completed")
    expect(current.get_by_role("button", name="Send", exact=True)).to_have_count(0)
    expect(current.get_by_role("button", name="Cancel", exact=True)).to_have_count(0)
    assert len(pending.writes) == 1
    assert pending.writes[0]["body"] == {"expected_version": "opaque-version-1"}
    assert not api.errors


@pytest.mark.parametrize("resource", ["mail", "calendar"])
def test_explicit_full_review_gets_complete_safe_content_without_sending(pending_ui, resource):
    page, api, pending = pending_ui
    preview, complete = long_body_action(resource)
    pending.records[complete["id"]] = complete
    open_chat(page, api, [preview])
    current = card(page)
    name = "Review full invitation" if resource == "calendar" else "Review full message"
    expect(current.get_by_role("button", name=name, exact=True)).to_be_visible()
    expect(current.get_by_role("button", name="Send", exact=True)).to_have_count(0)
    expect(current).to_contain_text("shortened preview")
    expect(current).not_to_contain_text("This view is read-only")
    current.locator("summary").click()
    expect(current.locator("pre")).to_have_text(preview["summary"]["body_preview"])
    assert not pending.detail_reads
    current.get_by_role("button", name=name, exact=True).click()
    expect(current.locator("pre")).to_have_text(complete["summary"]["body_preview"])
    expect(current.locator("details")).to_have_attribute("open", "")
    expect(current.get_by_role("button", name="Send", exact=True)).to_be_enabled()
    expect(current.get_by_role("button", name=name, exact=True)).to_have_count(0)
    expect(current.locator("img,script")).to_have_count(0)
    injected = page.evaluate("Boolean(window.fullReviewXss)")
    assert not injected
    assert pending.detail_reads == [complete["id"]]
    assert not pending.writes
    current.get_by_role("button", name="Send", exact=True).click()
    expect(current.get_by_role("button", name="Send", exact=True)).to_have_count(0)
    assert pending.writes[0]["body"] == {"expected_version": "opaque-version-1"}
    assert len(pending.writes) == 1
    assert not api.errors


def test_full_review_failure_remains_get_only_and_can_be_retried(pending_ui):
    page, api, pending = pending_ui
    preview, complete = long_body_action()
    pending.records[complete["id"]] = complete
    pending.detail_failure = ({"success": False, "error": "storage_unavailable"}, 503)
    open_chat(page, api, [preview])
    current = card(page)
    current.get_by_role("button", name="Review full message", exact=True).click()
    expect(current).to_contain_text("current action status could not be checked")
    expect(current.get_by_role("button", name="Send", exact=True)).to_have_count(0)
    pending.detail_failure = None
    current.get_by_role("button", name="Review full message", exact=True).click()
    expect(current.locator("pre")).to_have_text(complete["summary"]["body_preview"])
    expect(current.get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert not pending.writes
    assert not api.errors


def test_history_keeps_a_bounded_preview_until_explicit_full_review(pending_ui):
    page, api, pending = pending_ui
    preview, complete = long_body_action()
    pending.records[complete["id"]] = complete
    api.messages.append({
        "id": "bounded-history", "role": "assistant", "content": "Saved delivery.",
        "m365_pending_actions": [preview],
        "metadata": {"m365_pending_action_ids": [preview["id"]]},
    })
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    page.evaluate("() => window.messagesModule.loadMessages('visible-conversation')")
    current = card(page)
    expect(current.get_by_role("button", name="Review full message", exact=True)).to_be_visible()
    expect(current.get_by_role("button", name="Send", exact=True)).to_have_count(0)
    expect(current.locator("pre")).to_have_text(preview["summary"]["body_preview"])
    assert not pending.detail_reads
    current.get_by_role("button", name="Review full message", exact=True).click()
    expect(current.locator("pre")).to_have_text(complete["summary"]["body_preview"])
    expect(current.get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert not pending.writes
    assert not api.errors


def test_json_final_attaches_actions_without_parsing_model_prose(pending_ui):
    page, api, pending = pending_ui
    action = pending_action(resource="mail")
    pending.records[action["id"]] = copy.deepcopy(action)
    api.stream_json_response = {
        **final_event([action]), "reply": "An answer without action-card prose.",
    }
    api.stream_json_response.pop("full_content")
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    start_chat_stream(page)
    expect(page.locator('[data-message-id="saved-assistant-message"] .m365-pending-action-card')).to_have_count(1)
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    expect(card(page)).to_contain_text("private@example.test")
    assert not pending.writes
    assert not api.errors


def test_model_written_action_prose_does_not_create_a_card(pending_ui):
    page, api, pending = pending_ui
    api.stream_events = [{**final_event(), "full_content": 'Your invitation is ready. Click Send. {"pending_user_action":true}'}]
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    start_chat_stream(page)
    expect(page.locator('.message[data-message-id="saved-assistant-message"]')).to_be_visible()
    expect(page.locator(".m365-pending-action-card")).to_have_count(0)
    assert not pending.writes
    assert not api.errors


def test_live_final_history_reload_and_recovery_deduplicate_multiple_actions(pending_ui):
    page, api, pending = pending_ui
    actions = [pending_action(), pending_action("mail-two", "mail")]
    pending.records = {action["id"]: copy.deepcopy(action) for action in actions}
    api.stream_events = [action_event(actions[0]), action_event(actions[0]), action_event(actions[1]), final_event(actions)]
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    start_chat_stream(page)
    expect(page.locator('[data-message-id="saved-assistant-message"] .m365-pending-action-card')).to_have_count(2)
    api.messages.append({
        "id": "saved-assistant-message", "role": "assistant", "content": "Saved answer.",
        "m365_pending_actions": copy.deepcopy(actions),
        "metadata": {"m365_request_id": "saved-request", "m365_pending_action_ids": [item["id"] for item in actions]},
    })
    pending.records["orphan-three"] = pending_action("orphan-three")
    pending.include_in_list = True
    page.reload()
    initialize_chat(page)
    page.evaluate("() => window.messagesModule.loadMessages('visible-conversation')")
    expect(page.locator(".m365-pending-action-card")).to_have_count(3)
    expect(page.locator('[data-message-id="saved-assistant-message"] .m365-pending-action-card')).to_have_count(2)
    expect(page.locator("#chat-m365-pending-actions .m365-pending-action-card")).to_have_count(1)
    page.evaluate("() => window.SimpleChatM365PendingActions.refreshConversation('visible-conversation')")
    expect(page.locator(".m365-pending-action-card")).to_have_count(3)
    assert len(api.chat_requests) == 1
    assert not pending.writes
    assert not api.errors


def test_recovery_query_surfaces_storage_errors_and_paginates(pending_ui):
    page, api, pending = pending_ui
    pending.records = {str(index): pending_action(str(index)) for index in range(3)}
    pending.include_in_list = True
    pending.page_size = 1
    pending.list_failure = ({"success": False, "error": "storage_unavailable"}, 503)
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    page.evaluate("() => window.messagesModule.loadMessages('visible-conversation')")
    expect(page.locator("#chat-m365-pending-actions")).to_contain_text("not an empty inbox")
    pending.list_failure = None
    page.get_by_role("button", name="Refresh outgoing actions").click()
    expect(page.locator(".m365-pending-action-card")).to_have_count(1)
    page.get_by_role("button", name="Load more outgoing actions").click()
    expect(page.locator(".m365-pending-action-card")).to_have_count(2)
    page.get_by_role("button", name="Load more outgoing actions").click()
    expect(page.locator(".m365-pending-action-card")).to_have_count(3)
    assert all(query["conversation_id"] == ["visible-conversation"] for query in pending.queries)
    assert pending.queries[-1]["continuation_token"] == ["2"]
    assert not pending.writes
    assert not api.chat_requests
    assert not api.errors


def test_history_reference_fetches_authoritative_completed_receipt(pending_ui):
    page, api, pending = pending_ui
    pending.records["receipt"] = pending_action("receipt", status="sent", can_send_now=False, can_approve=False, can_cancel=False)
    api.messages.append({
        "id": "history-assistant", "role": "assistant", "content": "Historical response.",
        "metadata": {"m365_pending_action_ids": ["receipt"], "m365_request_id": "old-request"},
    })
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    page.evaluate("() => window.messagesModule.loadMessages('visible-conversation')")
    expect(page.locator('[data-message-id="history-assistant"] .m365-pending-action-card')).to_contain_text("Sent")
    expect(card(page, "receipt").get_by_role("button", name="Send", exact=True)).to_have_count(0)
    assert pending.detail_reads == ["receipt"]
    assert not pending.writes
    assert not api.errors


def test_collaborative_history_keeps_shared_viewer_cards_read_only(pending_ui):
    page, api, pending = pending_ui
    action = pending_action(viewer_is_owner=False, can_send_now=False, can_approve=False, can_cancel=False)
    action["summary"].pop("body_preview")
    pending.records[action["id"]] = copy.deepcopy(action)
    api.messages.append({
        "id": "shared-assistant", "role": "assistant", "content": "Shared conversation response.",
        "conversation_id": "visible-conversation", "m365_pending_actions": [action],
        "metadata": {"m365_pending_action_ids": [action["id"]]},
    })
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page, shared=True)
    page.evaluate("() => window.chatCollaboration.loadConversationMessages('visible-conversation')")
    expect(page.locator('.message[data-message-id="shared-assistant"] .m365-pending-action-card')).to_have_count(1)
    expect(card(page)).to_contain_text("This view is read-only")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_have_count(0)
    expect(card(page).get_by_role("button", name="Cancel", exact=True)).to_have_count(0)
    assert not pending.writes
    assert not api.errors


@pytest.mark.parametrize("snapshot", [True, False])
def test_shared_history_and_reference_reads_use_the_visible_conversation(pending_ui, snapshot):
    page, api, pending = pending_ui
    action = shared_action(conversation_id="canonical-storage-conversation")
    pending.records[action["id"]] = action
    pending.readable_conversations[action["id"]] = {"visible-conversation"}
    api.messages.append({
        "id": "shared-reference-message", "role": "assistant", "content": "Shared saved action.",
        "conversation_id": "visible-conversation",
        "metadata": {"m365_pending_action_ids": [action["id"]]},
        **({"m365_pending_actions": [action]} if snapshot else {}),
    })
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page, shared=True)
    page.evaluate("() => window.chatCollaboration.loadConversationMessages('visible-conversation')")
    current = card(page, action["id"])
    expect(current).to_be_visible()
    current.get_by_role("button", name="Refresh status", exact=True).click()
    expect(current).to_contain_text("Current server status loaded")
    expect(current.get_by_role("button", name="Send", exact=True)).to_have_count(0)
    expect(current.get_by_role("button", name="Cancel", exact=True)).to_have_count(0)
    expect(current).not_to_contain_text("private@example.test")
    assert pending.detail_requests
    assert all(item["query"] == {"conversation_id": ["visible-conversation"]} for item in pending.detail_requests)
    assert not pending.writes
    assert not api.errors


def test_owner_workflow_refresh_does_not_require_hidden_conversation_access(pending_ui):
    page, api, pending = pending_ui
    action = pending_action(workflow_id="workflow", conversation_id="hidden-output-conversation")
    pending.records[action["id"]] = action
    pending.readable_conversations[action["id"]] = set()
    page.goto(f"{ORIGIN}/workflow-controls")
    page.add_script_tag(url=f"{ORIGIN}/static/js/workflow/workflow-activity.js")
    page.evaluate("action => renderPendingActionControls({ pending_action: action })", action)
    card(page).get_by_role("button", name="Refresh status", exact=True).click()
    expect(card(page)).to_contain_text("Current server status loaded")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert pending.detail_requests
    assert all(item["query"] == {} for item in pending.detail_requests)
    assert not pending.writes
    assert not api.errors


def test_collaboration_reference_events_refresh_active_cards_after_inflight_reads(pending_ui):
    page, api, pending = pending_ui
    pending.include_in_list = True
    page.goto(f"{ORIGIN}/chats")
    activate_collaboration_events(page)
    page.evaluate("() => window.SimpleChatM365PendingActions.refreshConversation('visible-conversation')")
    guard_original_resume(page)
    reads_before = len(pending.queries)
    emit_collaboration_action_refs(page, ["unrelated"], "another-conversation")
    assert len(pending.queries) == reads_before
    pending.hold_next_list = True
    with page.expect_request(lambda request: urlsplit(request.url).path == PENDING_PATH):
        page.evaluate("() => { void window.SimpleChatM365PendingActions.refreshConversation('visible-conversation'); }")
    first = shared_action("event-one")
    pending.records[first["id"]] = first
    emit_collaboration_action_refs(page, [first["id"]])
    assert pending.held_list is not None
    pending.held_list.fulfill(
        content_type="application/json",
        body=json.dumps({"success": True, "pending_actions": []}),
    )
    expect(card(page, first["id"])).to_be_visible()
    second = shared_action("event-two")
    pending.records[second["id"]] = second
    emit_collaboration_action_refs(page, [second["id"]])
    expect(page.locator(".m365-pending-action-card")).to_have_count(2)
    reads_before = len(pending.queries)
    emit_collaboration_action_refs(page, [second["id"]])
    assert len(pending.queries) == reads_before
    page.evaluate("() => window.chatCollaboration.deactivateConversation()")
    emit_collaboration_action_refs(page, ["late-after-deactivation"])
    assert len(pending.queries) == reads_before
    expect(card(page, first["id"]).get_by_role("button", name="Send", exact=True)).to_have_count(0)
    assert not pending.writes
    assert not api.chat_requests
    assert not api.resume_requests
    resumed = page.evaluate("window.unwantedResumeCalls")
    assert resumed == 0
    assert not api.errors


def test_failed_history_reference_is_not_hidden_by_an_empty_recovery_page(pending_ui):
    page, api, pending = pending_ui
    pending.records["older-action"] = pending_action("older-action")
    pending.detail_failure = ({"success": False, "error": "storage_unavailable"}, 503)
    api.messages.append({
        "id": "older-message", "role": "assistant", "content": "An older action.",
        "metadata": {"m365_pending_action_ids": ["older-action"]},
    })
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    page.evaluate("() => window.messagesModule.loadMessages('visible-conversation')")
    expect(page.locator("#chat-m365-pending-actions")).to_contain_text("saved Microsoft 365 action could not be recovered")
    page.evaluate("() => window.SimpleChatM365PendingActions.refreshConversation('visible-conversation')")
    expect(page.locator("#chat-m365-pending-actions")).to_contain_text("saved Microsoft 365 action could not be recovered")
    pending.detail_failure = None
    page.get_by_role("button", name="Refresh outgoing actions").click()
    expect(page.locator('.message[data-message-id="older-message"] .m365-pending-action-card')).to_have_count(1)
    expect(card(page, "older-action").get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert not pending.writes
    assert not api.errors


def test_expanding_review_fetches_full_body_without_sending(pending_ui):
    page, api, pending = pending_ui
    action = pending_action()
    action["summary"]["body_preview"] = "Short projection"
    pending.records[action["id"]] = copy.deepcopy(action)
    pending.records[action["id"]]["summary"]["body_preview"] = "Full material beyond the short projection.\n<b>Literal HTML</b>"
    open_chat(page, api, [action])
    expect(card(page).locator("pre")).to_have_text("Short projection")
    card(page).locator("summary").click()
    expect(card(page).locator("pre")).to_contain_text("Full material beyond the short projection")
    expect(card(page).locator("pre")).to_contain_text("<b>Literal HTML</b>")
    expect(card(page).locator("details")).to_have_attribute("open", "")
    assert pending.detail_reads
    assert not pending.writes
    assert not api.errors


def test_late_stream_event_cannot_restore_cards_after_starting_a_new_conversation(pending_ui):
    page, api, pending = pending_ui
    action = pending_action()
    pending.records[action["id"]] = copy.deepcopy(action)
    pending.hold_stream = True
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    with page.expect_request("**/api/chat/stream"):
        start_chat_stream(page)
    page.evaluate("""() => {
        window.dispatchEvent(new CustomEvent('chat:conversation-context-changed',
            { detail: { reason: 'new', conversationId: null } }));
        window.currentConversationId = null;
        document.getElementById('chatbox').replaceChildren();
    }""")
    assert pending.held_stream is not None
    pending.held_stream.fulfill(
        content_type="text/event-stream",
        body="".join(f"data: {json.dumps(event)}\n\n" for event in [action_event(action), final_event([action])]),
    )
    page.wait_for_function("() => window.finishedStreams === 1")
    expect(page.locator(".m365-pending-action-card")).to_have_count(0)
    expect(page.locator("#chat-m365-pending-actions")).to_be_hidden()
    assert not pending.writes
    assert not api.errors


def test_stale_version_refresh_requires_a_new_send_click(pending_ui):
    page, api, pending = pending_ui
    action = pending_action()
    pending.records[action["id"]] = copy.deepcopy(action)
    open_chat(page, api, [action])
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    pending.update(action["id"], subject="Changed meeting details", requires_review=True)
    card(page).get_by_role("button", name="Send", exact=True).click()
    expect(card(page)).to_contain_text("This action changed")
    expect(card(page)).to_contain_text("Changed meeting details")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert len(pending.writes) == 1
    card(page).get_by_role("button", name="Send", exact=True).click()
    expect(card(page)).to_contain_text("Sent — calendar invitation created")
    assert [item["body"] for item in pending.writes] == [
        {"expected_version": "opaque-version-1"}, {"expected_version": "opaque-version-2"},
    ]
    assert not api.errors


@pytest.mark.parametrize("outcome,detail_unavailable", [
    ("pending", False), ("recovery_required", False), ("pending", True),
])
def test_network_failure_checks_state_without_blindly_retrying(pending_ui, outcome, detail_unavailable):
    page, api, pending = pending_ui
    action = pending_action()
    pending.records[action["id"]] = copy.deepcopy(action)
    pending.network_outcome = outcome
    if detail_unavailable:
        pending.detail_failure = ({"success": False, "error": "storage_unavailable"}, 503)
    open_chat(page, api, [action])
    card(page).get_by_role("button", name="Send", exact=True).click()
    if detail_unavailable:
        expect(card(page)).to_contain_text("current action status could not be checked")
        expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_disabled()
    elif outcome == "recovery_required":
        expect(card(page)).to_contain_text("Delivery outcome needs recovery")
        expect(card(page).get_by_role("button", name="Send", exact=True)).to_have_count(0)
    else:
        expect(card(page)).to_contain_text("response was not confirmed")
        expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert pending.detail_reads
    assert len(pending.writes) == 1
    assert not api.errors


def test_denied_action_does_not_offer_an_approval_override(pending_ui):
    page, api, pending = pending_ui
    action = pending_action()
    pending.records[action["id"]] = copy.deepcopy(action)
    pending.failures = [({"success": False, "error": "access_denied", "message": "Denied."}, 403)]
    open_chat(page, api, [action])
    card(page).get_by_role("button", name="Send", exact=True).click()
    expect(card(page)).to_contain_text("do not have permission to change")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_disabled()
    expect(card(page).get_by_role("button", name="Reconnect Microsoft 365")).to_have_count(0)
    assert len(pending.writes) == 1
    assert not api.errors


@pytest.mark.parametrize("surface", ["chat", "workflow"])
def test_send_sharing_approval_refreshes_only_the_same_card(pending_ui, surface):
    page, api, pending = pending_ui
    action = pending_action(workflow_id="workflow" if surface == "workflow" else None)
    pending.records[action["id"]] = copy.deepcopy(action)
    require_delivery_sharing(api, pending, action)
    if surface == "chat":
        open_chat(page, api, [action])
    else:
        page.goto(f"{ORIGIN}/workflow-controls")
        page.add_script_tag(url=f"{ORIGIN}/static/js/workflow/workflow-activity.js")
        page.evaluate("action => renderPendingActionControls({ pending_action: action })", action)
    guard_original_resume(page)
    card(page).get_by_role("button", name="Send", exact=True).click()
    expect(page.locator("#m365ApprovalsModal")).to_be_visible()
    page.get_by_role("group", name="Calendar sharing decision").get_by_role("button", name="Allow this request", exact=True).click()
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    expect(card(page)).to_contain_text("Sharing decisions saved")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert pending.detail_reads
    assert len(pending.writes) == 1
    assert len(api.decisions) == 1
    assert not api.resume_requests
    resumed = page.evaluate("window.unwantedResumeCalls")
    assert resumed == 0
    if surface == "chat":
        assert len(api.chat_requests) == 1
        card(page).get_by_role("button", name="Send", exact=True).click()
        expect(card(page)).to_contain_text("calendar invitation created")
        assert len(pending.writes) == 2
    assert not api.errors


def test_dismissing_sharing_keeps_send_blocked_but_allows_reopening_or_cancel(pending_ui):
    page, api, pending = pending_ui
    action = pending_action()
    pending.records[action["id"]] = copy.deepcopy(action)
    require_delivery_sharing(api, pending, action)
    open_chat(page, api, [action])
    guard_original_resume(page)
    card(page).get_by_role("button", name="Send", exact=True).click()
    expect(page.locator("#m365ApprovalsModal")).to_be_visible()
    page.get_by_role("button", name="Leave pending / close", exact=True).click()
    expect(card(page)).to_contain_text("Sharing review is still pending")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_disabled()
    expect(card(page).get_by_role("button", name="Cancel", exact=True)).to_be_enabled()
    expect(card(page).get_by_role("button", name="Review sharing decision", exact=True)).to_be_enabled()
    api.records["delivery-sharing"].update(status="approved", can_approve=False, can_deny=False)
    card(page).get_by_role("button", name="Review sharing decision", exact=True).click()
    expect(page.locator("#m365ApprovalsModal")).to_be_visible()
    expect(page.locator("#m365-approval-records")).to_contain_text("saved decision is read-only")
    page.get_by_role("button", name="Leave pending / close", exact=True).click()
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert len(pending.writes) == 1
    assert not api.decisions
    assert not api.resume_requests
    assert not api.errors


def test_sharing_refresh_failure_retries_get_without_resaving_or_resuming(pending_ui):
    page, api, pending = pending_ui
    action = pending_action()
    pending.records[action["id"]] = copy.deepcopy(action)
    require_delivery_sharing(api, pending, action)
    open_chat(page, api, [action])
    guard_original_resume(page)
    card(page).get_by_role("button", name="Send", exact=True).click()
    page.get_by_role("group", name="Calendar sharing decision").get_by_role("button", name="Allow this request", exact=True).click()
    pending.detail_failure = ({"success": False, "error": "storage_unavailable"}, 503)
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365-approvals-error")).to_contain_text("action status could not be checked")
    expect(page.locator("#m365-approvals-apply")).to_have_text("Retry refresh")
    assert len(api.decisions) == 1
    assert len(pending.writes) == 1
    pending.detail_failure = None
    page.get_by_role("button", name="Retry refresh", exact=True).click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    assert len(api.decisions) == 1
    assert len(pending.writes) == 1
    assert not api.resume_requests
    assert not api.errors


def test_refresh_only_mode_supersedes_an_existing_resume_callback_for_the_same_approval(pending_ui):
    page, api, pending = pending_ui
    action = pending_action()
    record = require_delivery_sharing(api, pending, action)
    page.goto(f"{ORIGIN}/modal")
    page.evaluate("""record => {
        window.originalCallbackCalls = 0;
        window.savedCardRefreshes = 0;
        window.SimpleChatM365Approvals.openApprovals({ approvals: [record] }, {
            onResume: async () => { window.originalCallbackCalls += 1; }
        });
        window.SimpleChatM365Approvals.openApprovals({ approvals: [record] }, {
            refreshOnly: true,
            onRefresh: async () => { window.savedCardRefreshes += 1; }
        });
    }""", {"id": record["id"]})
    page.get_by_role("group", name="Calendar sharing decision").get_by_role("button", name="Allow this request", exact=True).click()
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    callbacks = page.evaluate("({ original: window.originalCallbackCalls, refresh: window.savedCardRefreshes })")
    assert callbacks == {"original": 0, "refresh": 1}
    assert not api.resume_requests
    assert not pending.writes
    assert not api.errors


@pytest.mark.parametrize("reconnect", [False, True])
def test_expired_sign_in_can_cancel_or_reconnect_without_resuming_agent(pending_ui, reconnect):
    page, api, pending = pending_ui
    action = pending_action()
    pending.records[action["id"]] = copy.deepcopy(action)
    pending.failures = [({
        "success": False, "error": "m365_sign_in_required", "auth_required": True,
        "sources": ["calendar"], "scopes": ["Calendars.ReadWrite"],
    }, 401)]
    open_chat(page, api, [action])
    card(page).get_by_role("button", name="Send", exact=True).click()
    expect(card(page)).to_contain_text("Signing in does not send it")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_disabled()
    expect(card(page).get_by_role("button", name="Cancel", exact=True)).to_be_enabled()
    if not reconnect:
        card(page).get_by_role("button", name="Cancel", exact=True).click()
        expect(card(page)).to_contain_text("Cancelled")
    else:
        with page.expect_popup() as opened:
            card(page).get_by_role("button", name="Reconnect Microsoft 365").click()
        popup = opened.value
        expect(popup.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
        page.evaluate("() => window.postMessage({ type: 'm365-profile-reconnected' }, location.origin)")
        expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_disabled()
        api.chat_connection = {"status": "available", "sources": ["calendar"]}
        popup.evaluate("url => { window.location.href = url; }", f"{ORIGIN}/profile?tab=settings&m365_chat_connection=connected")
        expect(card(page)).to_contain_text("Current server status loaded")
        expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
        assert len(pending.writes) == 1
        assert api.profile_chat_connect_requests == [{"sources": ["calendar"]}]
        card(page).get_by_role("button", name="Send", exact=True).click()
        expect(card(page)).to_contain_text("Sent — calendar invitation created")
    assert len(pending.writes) == 2
    assert len(api.chat_requests) == 1
    assert not api.resume_requests
    assert not api.chat_connect_requests
    assert not api.errors


@pytest.mark.parametrize("surface", ["live", "history", "approvals"])
def test_stored_auth_required_cards_offer_reconnect_before_another_send(pending_ui, surface):
    page, api, pending = pending_ui
    action = pending_action(auth_required=True, sources=["calendar"], scopes=["Calendars.ReadWrite"])
    pending.records[action["id"]] = action
    if surface == "live":
        open_chat(page, api, [action])
    elif surface == "history":
        api.messages.append({
            "id": "auth-history", "role": "assistant", "content": "A saved action needs sign-in.",
            "m365_pending_actions": [action], "metadata": {"m365_pending_action_ids": [action["id"]]},
        })
        page.goto(f"{ORIGIN}/chats")
        initialize_chat(page)
        page.evaluate("() => window.messagesModule.loadMessages('visible-conversation')")
    else:
        pending.include_in_list = True
        page.goto(f"{ORIGIN}/approvals")
    expect(card(page).get_by_role("button", name="Reconnect Microsoft 365", exact=True)).to_be_visible()
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_disabled()
    expect(card(page).get_by_role("button", name="Cancel", exact=True)).to_be_enabled()
    assert not pending.writes
    assert not api.profile_chat_connect_requests
    assert not api.errors


def test_reconnect_acknowledgement_survives_stored_error_echoes_but_not_new_revisions(pending_ui):
    page, api, pending = pending_ui
    action = pending_action(auth_required=True, sources=["calendar"], scopes=["Calendars.ReadWrite"])
    pending.records[action["id"]] = copy.deepcopy(action)
    open_chat(page, api, [action])
    with page.expect_popup() as opened:
        card(page).get_by_role("button", name="Reconnect Microsoft 365", exact=True).click()
    popup = opened.value
    expect(popup.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    api.chat_connection = {"status": "available", "sources": ["calendar"]}
    popup.evaluate("url => { window.location.href = url; }", f"{ORIGIN}/profile?tab=settings&m365_chat_connection=connected")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    pending.include_in_list = True
    api.messages.append({
        "id": "reconnected-history", "role": "assistant", "content": "Saved action.",
        "m365_pending_actions": [action], "metadata": {"m365_pending_action_ids": [action["id"]]},
    })
    page.evaluate("() => window.messagesModule.loadMessages('visible-conversation')")
    page.evaluate("() => window.SimpleChatM365PendingActions.refreshConversation('visible-conversation')")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    expect(card(page).get_by_role("button", name="Reconnect Microsoft 365", exact=True)).to_have_count(0)
    assert not pending.writes
    pending.update(action["id"], auth_required=True)
    page.evaluate("() => window.SimpleChatM365PendingActions.refreshConversation('visible-conversation')")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_disabled()
    expect(card(page).get_by_role("button", name="Reconnect Microsoft 365", exact=True)).to_be_visible()
    assert not pending.writes
    assert len(api.chat_requests) == 1
    assert api.profile_chat_connect_requests == [{"sources": ["calendar"]}]
    assert not api.resume_requests
    assert not api.errors


def test_closed_sign_in_popup_does_not_claim_success_or_send(pending_ui):
    page, api, pending = pending_ui
    action = pending_action()
    pending.records[action["id"]] = copy.deepcopy(action)
    pending.failures = [({"success": False, "auth_required": True, "sources": ["calendar"]}, 401)]
    open_chat(page, api, [action])
    card(page).get_by_role("button", name="Send", exact=True).click()
    with page.expect_popup() as opened:
        card(page).get_by_role("button", name="Reconnect Microsoft 365").click()
    popup = opened.value
    expect(popup.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    popup.close()
    expect(card(page)).to_contain_text("sign-in was not confirmed")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_disabled()
    expect(card(page).get_by_role("link", name="Open Profile connection settings")).to_be_visible()
    assert len(pending.writes) == 1
    assert not api.resume_requests
    assert not api.errors


@pytest.mark.parametrize("changes,cancel_allowed", [
    ({"can_send_now": False, "can_approve": False, "can_cancel": False}, False),
    ({"workflow_id": "workflow", "can_send_now": False, "can_approve": False, "can_cancel": False}, False),
    ({"requires_recreation": True, "requires_review": True, "can_send_now": False, "can_approve": False}, True),
    *[({"status": status}, False) for status in ("sending", "sent", "cancelled", "failed", "recovery_required", "unknown")],
])
def test_chat_owner_run_as_legacy_and_terminal_flags_fail_closed(pending_ui, changes, cancel_allowed):
    page, api, pending = pending_ui
    action = pending_action(**changes)
    pending.records[action["id"]] = copy.deepcopy(action)
    open_chat(page, api, [action])
    expect(card(page)).to_be_visible()
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_have_count(0)
    expect(card(page).get_by_role("button", name="Cancel", exact=True)).to_have_count(1 if cancel_allowed else 0)
    if changes.get("workflow_id"):
        expect(card(page)).to_contain_text("Only the selected Run as user")
    assert not pending.writes
    assert not api.errors


@pytest.mark.parametrize("surface", ["chat", "workflow"])
def test_countdown_only_refreshes_and_tears_down_with_the_view(pending_ui, surface):
    page, api, pending = pending_ui
    page.clock.install()
    now = page.evaluate("Date.now()")
    action = pending_action(status="scheduled", action_mode="delayed", will_auto_send=True, delay_seconds=1)
    action["auto_send_at_utc"] = page.evaluate("now => new Date(now + 1200).toISOString()", now)
    pending.records[action["id"]] = copy.deepcopy(action)
    if surface == "chat":
        open_chat(page, api, [action])
    else:
        page.goto(f"{ORIGIN}/workflow-controls")
        page.add_script_tag(url=f"{ORIGIN}/static/js/workflow/workflow-activity.js")
        page.evaluate("action => renderPendingActionControls({ pending_action: action })", action)
    expect(card(page).get_by_role("button", name="Send now", exact=True)).to_be_visible()
    page.clock.fast_forward(3500)
    expect(card(page)).to_contain_text("Scheduled time reached")
    page.wait_for_function("() => document.querySelector('.m365-pending-action-card').getAttribute('aria-busy') === 'false'")
    assert pending.detail_reads
    assert not pending.writes
    if surface == "chat":
        page.evaluate("""() => {
            window.currentConversationId = 'another-conversation';
            window.dispatchEvent(new CustomEvent('chat:conversation-context-changed',
                { detail: { conversationId: 'another-conversation' } }));
        }""")
    else:
        page.evaluate("() => renderPendingActionControls(null)")
    expect(card(page)).to_have_count(0)
    reads_before = list(pending.detail_reads)
    page.clock.fast_forward(20000)
    assert pending.detail_reads == reads_before
    assert not pending.writes
    assert not api.errors


def test_workflow_focus_refreshes_an_action_changed_elsewhere(pending_ui):
    page, api, pending = pending_ui
    action = pending_action(workflow_id="workflow", run_id="run")
    pending.records[action["id"]] = copy.deepcopy(action)
    page.goto(f"{ORIGIN}/workflow-controls")
    page.add_script_tag(url=f"{ORIGIN}/static/js/workflow/workflow-activity.js")
    page.evaluate("action => renderPendingActionControls({ pending_action: action })", action)
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_be_enabled()
    pending.update(action["id"], status="sent", can_send_now=False, can_approve=False, can_cancel=False)
    page.evaluate("() => window.dispatchEvent(new Event('focus'))")
    expect(card(page)).to_contain_text("Sent — calendar invitation created")
    expect(card(page).get_by_role("button", name="Send", exact=True)).to_have_count(0)
    assert pending.detail_reads
    assert not pending.writes
    assert not api.errors


@pytest.mark.parametrize("width", [1440, 390])
def test_review_details_xss_links_keyboard_and_mobile_layout(pending_ui, width):
    page, api, pending = pending_ui
    page.set_viewport_size({"width": width, "height": 900})
    attack = '<img src=x onerror="window.pendingXss=true">'
    action = pending_action(
        subject=attack,
        web_link="javascript:window.pendingXss=true",  # xss-check: ignore - Negative fixture; execution/link assertions follow.
        error=attack,
    )
    action["summary"].update({
        "location": attack, "attendee_recipients": [attack],
        "body_preview": f"{attack}<script>window.pendingXss=true</script>",
        "content_type": "html",
    })
    pending.records[action["id"]] = copy.deepcopy(action)
    open_chat(page, api, [action])
    expect(card(page)).to_contain_text(attack)
    summary = card(page).locator("summary")
    summary.focus()
    page.keyboard.press("Enter")
    expect(card(page).locator("pre")).to_contain_text("<script>window.pendingXss=true</script>")
    expect(card(page).locator("img,script")).to_have_count(0)
    expect(card(page).get_by_role("link", name="Open in Microsoft 365")).to_have_count(0)
    injected = page.evaluate("Boolean(window.pendingXss)")
    fits = page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert not injected
    assert fits
    assert not pending.writes
    assert not api.errors


def test_approvals_outgoing_section_uses_same_versioned_action(pending_ui):
    page, api, pending = pending_ui
    pending.records = {
        "calendar-one": pending_action(),
        "mail-two": pending_action("mail-two", "mail"),
    }
    pending.include_in_list = True
    pending.page_size = 1
    page.goto(f"{ORIGIN}/approvals")
    expect(page.get_by_role("heading", name="Outgoing email and invitations")).to_be_visible()
    expect(page.locator(".m365-pending-action-card")).to_have_count(1)
    page.get_by_role("button", name="Load more outgoing actions").click()
    expect(page.locator(".m365-pending-action-card")).to_have_count(2)
    expect(card(page).get_by_role("link", name="Open conversation")).to_have_attribute("href", "/chats?conversationId=visible-conversation")
    assert all(query.get("active_only") == ["1"] for query in pending.queries)
    assert not pending.writes
    card(page, "mail-two").get_by_role("button", name="Cancel", exact=True).click()
    expect(card(page, "mail-two")).to_contain_text("Cancelled")
    assert pending.writes[0]["body"] == {"expected_version": "opaque-version-1"}
    assert pending.writes[0]["csrf"] == CSRF_TOKEN
    assert not api.errors


def test_approvals_inbox_includes_recovery_required_without_resend_controls(pending_ui):
    page, api, pending = pending_ui
    pending.records["uncertain-delivery"] = pending_action(
        "uncertain-delivery", "mail", status="recovery_required",
        can_send_now=False, can_approve=False, can_cancel=False,
        delivery_note="Check Microsoft 365 before creating another message.",
    )
    pending.include_in_list = True
    page.goto(f"{ORIGIN}/approvals")
    current = card(page, "uncertain-delivery")
    expect(current).to_be_visible()
    expect(current).to_contain_text("Delivery outcome needs recovery")
    expect(current.get_by_role("button", name="Send", exact=True)).to_have_count(0)
    expect(current.get_by_role("button", name="Cancel", exact=True)).to_have_count(0)
    assert pending.queries[0]["active_only"] == ["1"]
    assert not pending.writes
    assert not api.errors
