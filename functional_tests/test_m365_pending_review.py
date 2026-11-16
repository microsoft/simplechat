# test_m365_pending_review.py
"""Functional tests for owner-scoped email/calendar review, assist and draft delivery.

Version: 0.261.326
Implemented in: 0.261.325

Real services/routes use SDK-default Cosmos storage and entirely mocked Graph/model
I/O. No mail is sent, Azure clients initialized, or calendar invitations created.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import ast
import json
from pathlib import Path
import sys
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# The shared fixture supplies SDK CosmosDict responses with ETags and atomic batches.
from test_m365_action_card_api import cards
from test_m365_routes import module_stub
from test_m365_pending_delivery import pending
from test_m365_provider_core import execution, graph_plugins, FakeResponse
from functions_editor_assist import EditorAssistError, EditorAssistServices
from content_screening.policies import STARTER_RULE_TEMPLATES, default_policy
from functions_chat_content_checks import evaluate_chat_content
import functions_m365_pending_delivery as delivery
import functions_m365_pending_review as review
from functions_m365_review_history import history_id, read_review_history
from functions_m365_transport import M365CloudConfig, M365ProviderError, M365Transport


@pytest.fixture
def editable(cards, monkeypatch):
    def create(kind="email"):
        created = cards.create("send_mail" if kind == "email" else "create_calendar_invite")
        action = cards.container.read_item(created["id"], "owner")
        if kind == "email":
            action.update(graph_send_strategy="draft_send_v1", web_link="https://outlook.example.test/draft")
        else:
            action["graph_payload"] = {
                "subject": "Review me", "body": {"contentType": "Text", "content": "Meeting notes"},
                "attendees": [{"emailAddress": {"address": "reviewed@example.test"}, "type": "optional"}],
                "start": {"dateTime": "2026-10-12T09:00:00", "timeZone": "Eastern Standard Time"},
                "end": {"dateTime": "2026-10-12T10:00:00", "timeZone": "Eastern Standard Time"},
                "location": {"displayName": "Room A"}, "isOnlineMeeting": False,
            }
        action["material_fingerprint"] = delivery.pending_delivery_fingerprint(action)
        return cards.container.upsert_item(body=action)

    state = SimpleNamespace(calls=[], patch_error=None, post_error=None, sent_visible=True, patch_hook=None, post_hook=None)
    action = create()
    state.draft = {
        **deepcopy(action["graph_payload"]["message"]), "isDraft": True,
        "id": "draft", "changeKey": "draft-version", "@odata.etag": 'W/"draft-version"',
        "webLink": "https://outlook.example.test/draft",
    }

    class Transport:
        def __init__(self, source, action_id, **kwargs):
            self.before_request = None

        @contextmanager
        def operation_context(self, operation):
            yield

        @contextmanager
        def callback_context(self, before_request, on_progress):
            self.before_request = before_request
            try:
                yield
            finally:
                self.before_request = None

        def get_token(self, scopes):
            return "offline", scopes

        def request_json(self, method, path, scopes, **kwargs):
            state.calls.append((method, path, deepcopy(kwargs)))
            if method == "GET":
                if state.draft["isDraft"] is False and not state.sent_visible:
                    raise M365ProviderError("not_found", "Copy not visible yet.", status_code=404)
                return deepcopy(state.draft)
            if method == "PATCH":
                if state.patch_hook:
                    state.patch_hook()
                if state.patch_error:
                    raise state.patch_error
                if kwargs["additional_headers"].get("If-Match") != state.draft["@odata.etag"]:
                    raise M365ProviderError("precondition_failed", "Draft changed.", status_code=412)
                state.draft.update(deepcopy(kwargs["json_body"]))
                state.draft.update(changeKey="saved-draft", **{"@odata.etag": 'W/"saved-draft"'})
                return deepcopy(state.draft)
            if self.before_request:
                self.before_request()
            if state.post_hook:
                state.post_hook()
            if state.post_error:
                raise state.post_error
            if path.endswith("/send"):
                state.draft.update(isDraft=False, webLink="https://outlook.example.test/sent")
                return {}
            return {"id": "event", "webLink": "https://outlook.example.test/event"}

    monkeypatch.setitem(delivery._dependencies, "transport_factory", Transport)
    state.action, state.create, state.cards = action, create, cards
    return state


def _save(state, fields, **kwargs):
    latest = state.cards.container.read_item(state.action["id"], "owner")
    return review.save_pending_review(
        state.cards.container, "owner", latest["id"], expected_version=latest["_etag"], fields=fields, **kwargs,
    )


@pytest.fixture
def sent_link_clock(monkeypatch):
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(delivery, "_sent_link_now", lambda: clock[0])
    return clock


def _services(result=None, *, hook=None):
    calls, leases = [], []

    class Limiter:
        def acquire(self, user_id):
            leases.append(("acquire", user_id))
            return "lease"

        def release(self, lease, refund=False):
            leases.append(("release", lease, refund))

    def model(messages, timeout):
        calls.append(messages)
        if hook:
            hook()
        return json.dumps(result or {
            "reply": "Suggested a clearer subject.",
            "operations": [{"op": "set", "path": "/subject", "value": "Clearer subject"}],
        }), "stop"

    return EditorAssistServices(limiter=Limiter(), call_model=model), calls, leases


def _assist(state, services, **overrides):
    action = state.cards.container.read_item(state.action["id"], "owner")
    body = {
        "submission_id": str(uuid.uuid4()), "instruction": "Clarify the subject",
        "expected_version": action["_etag"], "fields": review.review_fields(action), **overrides,
    }
    return review.assist_pending_review(state.cards.container, "owner", action["id"], body, services=services)


def test_email_save_patches_actual_draft_reopens_and_preserves_history(editable):
    state = editable
    result = _save(state, {"subject": "Edited subject", "bcc_recipients": ["hidden@example.test"]})
    reopened = review.get_pending_review(state.cards.container, "owner", state.action["id"])
    assert reopened["fields"]["subject"] == state.draft["subject"] == "Edited subject"
    assert reopened["fields"]["bcc_recipients"] == ["hidden@example.test"]
    assert reopened["history"]["items"][0]["from_fields"]["subject"] == "Review me"
    assert reopened["history"]["items"][0]["saved"]
    assert result["action"]["material_fingerprint"] == delivery.pending_delivery_fingerprint(result["action"])
    patch = next(item for item in state.calls if item[0] == "PATCH")
    assert patch[1] == "/v1.0/me/messages/draft"
    assert patch[2]["additional_headers"] == {"Prefer": 'IdType="ImmutableId"', "If-Match": 'W/"draft-version"'}
    assert not any(item[0] == "POST" for item in state.calls)
    assert "items" not in result["action"]


def test_calendar_save_is_local_until_explicit_approval_and_preserves_optional_attendees(editable):
    state = editable
    state.action = state.create("calendar")
    result = _save(state, {"subject": "Meeting edited", "teams_meeting_requested": True})
    action = result["action"]
    assert action["review_provenance_version"] == 1
    assert state.calls == []
    assert action["graph_payload"]["attendees"][0]["type"] == "optional"
    assert action["graph_payload"]["onlineMeetingProvider"] == "teamsForBusiness"
    sent, error = delivery.dispatch_m365_pending_delivery("owner", action["id"], expected_version=action["_etag"])
    assert error is None and sent["graph_event_id"] == "event"
    assert len(state.calls) == 1 and state.calls[0][1] == "/v1.0/me/events"
    assert state.calls[0][2]["json_body"]["transactionId"] == action["id"]
    history = read_review_history(state.cards.container, sent)
    assert history is None


@pytest.mark.parametrize("fields", [
    {"to_recipients": []}, {"cc_recipients": ["not-an-address"]},
    {"subject": ""}, {"body": "bad\x00text"}, {"owner": "attacker"},
    {"content_type": "script"}, {"to_recipients": ["newline@example.test\nbcc@example.test"]},
])
def test_invalid_email_edits_make_no_remote_call(editable, fields):
    with pytest.raises(ValueError):
        _save(editable, fields)
    assert editable.calls == []


@pytest.mark.parametrize("fields", [
    {"timezone": "Invented/Zone"}, {"end_datetime": "2026-10-12T08:00:00"},
    {"start_datetime": "not-a-date"}, {"teams_meeting_requested": "true"},
    {"attendee_recipients": []},
    {"start_datetime": "2026-03-08T02:30:00", "end_datetime": "2026-03-08T03:30:00"},
])
def test_invalid_calendar_edits_make_no_remote_call(editable, fields):
    editable.action = editable.create("calendar")
    with pytest.raises(ValueError):
        _save(editable, fields)
    assert editable.calls == []


@pytest.mark.parametrize("status,mode", [
    ("sent", "manual"), ("cancelled", "manual"), ("sending", "manual"),
    ("editing", "manual"), ("scheduled", "delayed"), ("pending", "delayed"),
])
def test_editing_is_manual_and_not_terminal_or_claimed(editable, status, mode):
    action = editable.action
    action.update(status=status, action_mode=mode)
    action["material_fingerprint"] = delivery.pending_delivery_fingerprint(action)
    editable.cards.container.upsert_item(body=action)
    with pytest.raises(delivery.M365PolicyError):
        _save(editable, {"subject": "No"})
    assert editable.calls == []


def test_stale_save_and_cross_owner_review_history_assist_denied(editable):
    state = editable
    with pytest.raises(delivery.M365PolicyError):
        review.save_pending_review(state.cards.container, "owner", state.action["id"], expected_version="stale", fields={"subject": "No"})
    for operation in (
        lambda: review.get_pending_review(state.cards.container, "viewer", state.action["id"]),
        lambda: review.save_pending_review(state.cards.container, "viewer", state.action["id"], expected_version=state.action["_etag"], fields={"subject": "No"}),
        lambda: review.assist_pending_review(state.cards.container, "viewer", state.action["id"], {}, services=_services()[0]),
    ):
        with pytest.raises(LookupError):
            operation()
    assert state.calls == []


def test_ai_suggests_without_saving_and_history_survives_reopen_then_save(editable):
    services, model_calls, leases = _services()
    result = _assist(editable, services)
    assert result["candidate_fields"]["subject"] == "Clearer subject"
    assert editable.draft["subject"] == "Review me"
    assert editable.calls == []
    reopened = review.get_pending_review(editable.cards.container, "owner", editable.action["id"])
    assert reopened["history"]["items"][0]["id"] == result["assist_turn_id"]
    assert reopened["history"]["items"][0]["from_fields"]["subject"] == "Review me"
    assert reopened["history"]["items"][0]["warnings"] == result["warnings"]
    saved = _save(editable, result["candidate_fields"], origin="ai", assist_turn_id=result["assist_turn_id"])
    assert saved["fields"]["subject"] == editable.draft["subject"] == "Clearer subject"
    assert saved["history"]["items"][0]["assist_turn_id"] == result["assist_turn_id"]
    assert len(model_calls) == 1 and len(leases) == 2


@pytest.mark.parametrize("path", ["/owner", "/action_mode", "/graph_message_id", "/send", "/approval"])
def test_ai_cannot_change_identity_policy_or_send(editable, path):
    services, model_calls, _ = _services({"reply": "Change.", "operations": [{"op": "set", "path": path, "value": "bad"}]})
    with pytest.raises(EditorAssistError) as failed:
        _assist(editable, services)
    assert failed.value.code == "assistant_output_invalid"
    assert len(model_calls) == 2
    assert editable.calls == []


def test_stale_ai_response_cannot_save_over_a_newer_revision(editable):
    services, _, _ = _services(hook=lambda: _save(editable, {"subject": "Owner saved meanwhile"}))
    with pytest.raises(delivery.M365PolicyError) as failed:
        _assist(editable, services)
    assert failed.value.code == "pending_action_changed"
    reopened = review.get_pending_review(editable.cards.container, "owner", editable.action["id"])
    assert reopened["fields"]["subject"] == "Owner saved meanwhile"
    assert all(item["kind"] == "revision" for item in reopened["history"]["items"])


def test_known_outlook_change_refreshes_instead_of_overwriting(editable):
    state = editable
    state.draft.update(subject="Edited in Outlook", changeKey="outside", **{"@odata.etag": 'W/"outside"'})
    with pytest.raises(delivery.M365PolicyError) as conflict:
        _save(state, {"subject": "Overwrite"})
    assert conflict.value.code == "pending_action_changed"
    reopened = review.get_pending_review(state.cards.container, "owner", state.action["id"])
    assert reopened["fields"]["subject"] == "Edited in Outlook"
    assert reopened["history"]["items"][0]["origin"] == "outlook"
    assert not any(item[0] == "PATCH" for item in state.calls)


def test_partial_graph_cosmos_save_blocks_send_until_read_only_reconciliation(editable, monkeypatch):
    state = editable
    batch = state.cards.container.execute_item_batch

    def fail_batch(*args, **kwargs):
        raise CosmosHttpResponseError(status_code=503, message="Injected offline failure.")

    monkeypatch.setattr(state.cards.container, "execute_item_batch", fail_batch)
    with pytest.raises(CosmosHttpResponseError):
        _save(state, {"subject": "Persisted in Outlook only"})
    latest = state.cards.container.read_item(state.action["id"], "owner")
    blocked, error = delivery.dispatch_m365_pending_delivery("owner", latest["id"], expected_version=latest["_etag"])
    assert error["error"] == "pending_action_changed" and blocked["status"] in {"editing", "review_required"}
    card = state.cards.service.sanitize_msgraph_pending_action_for_client(blocked, viewer_user_id="owner", include_full_review=True)
    assert not card["can_approve"] and not card["requires_recreation"]
    if blocked["status"] == "review_required":
        assert card["can_edit"] and card["review_refresh_required"]
    assert not any(item[0] == "POST" for item in state.calls)
    latest["review_edit_expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    state.cards.container.upsert_item(body=latest)
    monkeypatch.setattr(state.cards.container, "execute_item_batch", batch)
    restored = review.get_pending_review(state.cards.container, "owner", latest["id"])
    assert restored["fields"]["subject"] == "Persisted in Outlook only"
    assert restored["action"]["status"] == "pending" and not restored["action"]["review_sync_required"]
    assert restored["action"]["material_fingerprint"] == delivery.pending_delivery_fingerprint(restored["action"])


def test_lost_batch_acknowledgement_does_not_overwrite_the_committed_save(editable, monkeypatch):
    state = editable
    batch = state.cards.container.execute_item_batch

    def committed_then_failed(*args, **kwargs):
        batch(*args, **kwargs)
        raise CosmosHttpResponseError(status_code=503, message="Injected lost acknowledgement.")

    monkeypatch.setattr(state.cards.container, "execute_item_batch", committed_then_failed)
    with pytest.raises(CosmosHttpResponseError):
        _save(state, {"subject": "Actually committed"})
    latest = state.cards.container.read_item(state.action["id"], "owner")
    assert latest["status"] == "pending" and not latest["review_sync_required"]
    assert review.review_fields(latest)["subject"] == state.draft["subject"] == "Actually committed"
    assert any("Draft save recovery marker" in str(call.args[0]) for call in state.cards.log.call_args_list)


def test_graph_patch_failure_requires_refresh_not_successful_save(editable):
    editable.patch_error = M365ProviderError("transport_error", "Injected failure.")
    with pytest.raises(M365ProviderError):
        _save(editable, {"subject": "Never saved"})
    latest = editable.cards.container.read_item(editable.action["id"], "owner")
    assert latest["review_sync_required"] and latest["status"] == "review_required"
    reopened = review.get_pending_review(editable.cards.container, "owner", latest["id"])
    assert reopened["fields"]["subject"] == "Review me"
    assert not reopened["action"]["review_sync_required"]


def test_outlook_change_between_read_and_patch_is_a_conflict_not_an_overwrite(editable):
    def outside_edit():
        editable.draft.update(subject="Concurrent Outlook edit", changeKey="outside", **{"@odata.etag": 'W/"outside"'})

    editable.patch_hook = outside_edit
    with pytest.raises(M365ProviderError) as failed:
        _save(editable, {"subject": "Must not overwrite"})
    assert failed.value.status_code == 412
    editable.patch_hook = None
    reopened = review.get_pending_review(editable.cards.container, "owner", editable.action["id"])
    assert reopened["fields"]["subject"] == "Concurrent Outlook edit"

def test_expired_edit_claim_can_reopen_review_but_never_send_before_reconciliation(editable):
    state = editable
    action = state.cards.container.read_item(state.action["id"], "owner")
    action.update(
        status="editing", review_sync_required=True,
        review_edit_expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    )
    saved = state.cards.container.upsert_item(body=action)
    card = state.cards.service.sanitize_msgraph_pending_action_for_client(saved, viewer_user_id="owner", include_full_review=True)
    assert card["can_edit"] and not card["can_approve"] and not card["can_send_now"]
    reopened = review.get_pending_review(state.cards.container, "owner", saved["id"])
    assert reopened["action"]["status"] == "pending"

def test_parallel_save_send_cancel_have_no_delivery_during_edit_claim(editable):
    entered, release = Event(), Event()

    def wait():
        entered.set()
        if not release.wait(10):
            raise AssertionError("Edit not released.")

    editable.patch_hook = wait
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_save, editable, {"subject": "Saved once"})
        started = entered.wait(10)
        assert started
        for cancel in (False, True):
            blocked, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"], cancel=cancel)
            assert blocked["status"] == "editing" and error["error"] == "pending_action_changed"
        release.set()
        result = future.result(10)
    assert result["fields"]["subject"] == "Saved once"
    assert not any(item[0] == "POST" for item in editable.calls)


def test_new_email_sends_draft_once_and_looks_up_only_current_sent_link(editable, sent_link_clock):
    editable.sent_visible = False
    result = _save(editable, {"subject": "Final saved draft"})
    sent, error = delivery.dispatch_m365_pending_delivery("owner", result["action"]["id"], expected_version=result["action"]["_etag"])
    assert error is None and sent["status"] == "sent"
    assert sent["web_link"] == "" and sent["sent_link_pending"]
    repeated, repeat_error = delivery.dispatch_m365_pending_delivery("owner", sent["id"])
    assert repeat_error is None and repeated["status"] == "sent"
    posts = [call for call in editable.calls if call[0] == "POST"]
    assert len(posts) == 1 and posts[0][1] == "/v1.0/me/messages/draft/send"
    assert posts[0][2]["json_body"] is None
    assert posts[0][2]["additional_headers"]["Prefer"] == 'IdType="ImmutableId"'
    editable.sent_visible = True
    sent_link_clock[0] = datetime.fromisoformat(sent["sent_link_next_lookup_at"])
    refreshed = delivery.refresh_m365_sent_link("owner", sent["id"])
    assert refreshed["web_link"] == "https://outlook.example.test/sent"
    assert not refreshed["sent_link_pending"]
    history = read_review_history(editable.cards.container, refreshed)
    assert history is None


def test_external_outlook_edits_are_sent_without_extra_safety_pause(editable):
    editable.draft.update(subject="External current draft", changeKey="external-version")
    sent, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"], expected_version=editable.action["_etag"])
    assert error is None and sent["status"] == "sent"
    assert sent["summary"]["subject"] == "External current draft"
    assert any(call[1].endswith("/draft/send") for call in editable.calls)


def test_unknown_draft_send_outcome_never_replays(editable):
    editable.post_error = M365ProviderError("timeout", "Injected interrupted response.")
    sent, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    repeated, repeat_error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    assert sent["status"] == repeated["status"] == "recovery_required"
    assert error["error"] == "timeout" and repeat_error["error"] == "delivery_outcome_unknown"
    assert len([call for call in editable.calls if call[0] == "POST"]) == 1


def test_sent_link_visibility_is_bounded_and_cannot_reenable_send(editable, sent_link_clock):
    editable.sent_visible = False
    sent, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    for _ in range(10):
        sent = delivery.refresh_m365_sent_link("owner", sent["id"])
    assert sent["sent_link_lookup_attempts"] == 1 and sent["sent_link_pending"]
    for _ in range(4):
        sent_link_clock[0] = datetime.fromisoformat(sent["sent_link_next_lookup_at"])
        sent = delivery.refresh_m365_sent_link("owner", sent["id"])
    assert error is None and sent["status"] == "sent"
    assert sent["sent_link_lookup_attempts"] == 5 and not sent["sent_link_pending"]
    projected = editable.cards.service.sanitize_msgraph_pending_action_for_client(sent, viewer_user_id="owner")
    assert projected["link_status"] == "unavailable" and not projected["link_pending"]
    assert projected["link_next_lookup_at"] == "" and not projected["can_send_now"]
    assert "unavailable" in projected["delivery_note"]
    calls = len(editable.calls)
    delivery.refresh_m365_sent_link("owner", sent["id"])
    assert len(editable.calls) == calls
    assert len([call for call in editable.calls if call[0] == "POST"]) == 1
    assert any("Sent-message link lookup remains pending" in str(call.args[0]) for call in editable.cards.log.call_args_list)


def test_sent_link_delayed_visibility_survives_rapid_detail_refreshes(editable, sent_link_clock):
    editable.sent_visible = False
    sent, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    assert error is None
    path = f"/api/msgraph/pending-actions/{sent['id']}"
    calls = len(editable.calls)
    for _ in range(10):
        response = editable.cards.client.get(path)
        projected = response.get_json()["pending_action"]
        assert response.status_code == 200 and projected["link_status"] == "pending"
        assert projected["link_next_lookup_at"] == sent["sent_link_next_lookup_at"]
        assert projected["link_lookup_deadline_at"] == sent["sent_link_lookup_deadline_at"]
    assert len(editable.calls) == calls
    sent_link_clock[0] += timedelta(seconds=5)
    sent = delivery.refresh_m365_sent_link("owner", sent["id"])
    assert sent["sent_link_lookup_attempts"] == 2 and sent["sent_link_pending"]
    editable.sent_visible = True
    sent_link_clock[0] += timedelta(seconds=14)
    waiting = delivery.refresh_m365_sent_link("owner", sent["id"])
    assert waiting["sent_link_lookup_attempts"] == 2 and waiting["sent_link_pending"]
    sent_link_clock[0] += timedelta(seconds=1)
    sent = delivery.refresh_m365_sent_link("owner", sent["id"])
    projected = editable.cards.service.sanitize_msgraph_pending_action_for_client(sent, viewer_user_id="owner")
    assert sent["sent_link_lookup_attempts"] == 3 and projected["link_status"] == "available"
    assert not projected["link_pending"] and projected["web_link"] == "https://outlook.example.test/sent"
    assert len([call for call in editable.calls if call[0] == "POST"]) == 1


def test_sent_link_deadline_expires_without_another_remote_lookup(editable, sent_link_clock):
    editable.sent_visible = False
    sent, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    calls = len(editable.calls)
    sent_link_clock[0] = datetime.fromisoformat(sent["sent_link_lookup_deadline_at"])
    sent = delivery.refresh_m365_sent_link("owner", sent["id"])
    projected = editable.cards.service.sanitize_msgraph_pending_action_for_client(sent, viewer_user_id="owner")
    assert error is None and sent["status"] == "sent" and sent["sent_link_lookup_attempts"] == 1
    assert not projected["link_pending"] and projected["link_status"] == "unavailable"
    assert len(editable.calls) == calls and not projected["can_send_now"]


@pytest.mark.parametrize("attempt", [2, 5])
def test_sent_link_claim_blocks_refresh_while_lookup_is_in_flight(editable, sent_link_clock, monkeypatch, attempt):
    editable.sent_visible = False
    sent, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    for _ in range(attempt - 2):
        sent_link_clock[0] = datetime.fromisoformat(sent["sent_link_next_lookup_at"])
        sent = delivery.refresh_m365_sent_link("owner", sent["id"])
    sent_link_clock[0] = datetime.fromisoformat(sent["sent_link_next_lookup_at"])
    editable.sent_visible = True
    original = delivery._dependencies["transport_factory"]
    nested = []

    class Transport(original):
        def request_json(self, method, path, scopes, **kwargs):
            nested.append(delivery.refresh_m365_sent_link("owner", sent["id"]))
            return super().request_json(method, path, scopes, **kwargs)

    monkeypatch.setitem(delivery._dependencies, "transport_factory", Transport)
    calls = len(editable.calls)
    refreshed = delivery.refresh_m365_sent_link("owner", sent["id"])
    assert error is None and refreshed["sent_link_lookup_attempts"] == attempt
    assert len(nested) == 1 and nested[0]["sent_link_lookup_attempts"] == attempt
    assert len(editable.calls) == calls + 1
    assert refreshed["web_link"] == "https://outlook.example.test/sent" and not refreshed["sent_link_pending"]


def _configured_output_checker(captured, *, settings=None):
    baseline = default_policy()
    baseline["enabled"] = True
    rule = deepcopy(STARTER_RULE_TEMPLATES["confidentiality_markers"])
    rule["values"] = ["BLOCKED-CONTENT", "blocked@example.test"]
    baseline["rules"] = [rule]
    configured = settings if settings is not None else {
        "enable_content_screening": True, "enable_content_screening_chat_output": True,
        "chat_content_scan_failure_action": "block",
    }

    def checker(text, checkpoint, *, user_id):
        captured.append((text, checkpoint, user_id))
        return evaluate_chat_content(text, checkpoint, configured, baseline_loader=lambda: baseline)

    return checker


@pytest.mark.parametrize("fields", [
    {"body": "BLOCKED-CONTENT"}, {"subject": "BLOCKED-CONTENT"},
    {"to_recipients": ["blocked@example.test"]},
])
def test_configured_screening_checks_edited_body_subject_and_recipients_before_draft_patch(editable, monkeypatch, fields):
    captured = []
    monkeypatch.setitem(delivery._dependencies, "content_checker", _configured_output_checker(captured))
    with pytest.raises(delivery.M365PolicyError) as failed:
        _save(editable, fields)
    assert failed.value.code == "m365_content_blocked"
    assert captured[0][1:] == ("chat_output", "owner")
    assert editable.calls == []


@pytest.mark.parametrize("field", ["body", "recipient"])
def test_draft_send_screens_actual_outlook_content_even_with_no_post_json_body(editable, monkeypatch, field):
    captured = []
    monkeypatch.setitem(delivery._dependencies, "content_checker", _configured_output_checker(captured))
    editable.draft["changeKey"] = "external-change"
    if field == "body":
        editable.draft["body"]["content"] = "BLOCKED-CONTENT"
    else:
        editable.draft["toRecipients"] = [{"emailAddress": {"address": "blocked@example.test"}}]
    saved, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    assert saved["status"] == "review_required" and error["error"] == "m365_content_blocked"
    assert captured[0][1:] == ("chat_output", "owner")
    assert not any(call[0] == "POST" for call in editable.calls)


def test_disabled_output_screening_keeps_normal_draft_send_without_extra_gate(editable, monkeypatch):
    captured = []
    monkeypatch.setitem(delivery._dependencies, "content_checker", _configured_output_checker(captured, settings={}))
    editable.draft["changeKey"] = "external-change"
    editable.draft["body"]["content"] = "BLOCKED-CONTENT"
    saved, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    assert saved["status"] == "sent" and error is None
    assert len([call for call in editable.calls if call[0] == "POST"]) == 1


def test_calendar_content_screening_blocks_local_save_without_sending(editable, monkeypatch):
    editable.action = editable.create("calendar")
    monkeypatch.setitem(delivery._dependencies, "content_checker", _configured_output_checker([]))
    with pytest.raises(delivery.M365PolicyError) as failed:
        _save(editable, {"body": "BLOCKED-CONTENT"})
    assert failed.value.code == "m365_content_blocked" and editable.calls == []


def test_calendar_approval_screens_saved_material_before_remote_creation(editable, monkeypatch):
    editable.action = editable.create("calendar")
    _save(editable, {"body": "BLOCKED-CONTENT", "attendee_recipients": ["blocked@example.test"]})
    captured = []
    monkeypatch.setitem(delivery._dependencies, "content_checker", _configured_output_checker(captured))
    saved, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    assert saved["status"] == "review_required" and error["error"] == "m365_content_blocked"
    assert "blocked@example.test" in captured[0][0]
    assert "BLOCKED-CONTENT" in captured[0][0] and editable.calls == []


def test_missing_content_checker_cannot_bypass_configured_policy(editable, monkeypatch):
    monkeypatch.setitem(delivery._dependencies, "content_checker", None)
    saved, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    assert saved["status"] == "review_required" and error["error"] == "m365_content_check_unavailable"
    assert not any(call[0] == "POST" for call in editable.calls)


def test_restored_sharing_authorization_is_required_before_screening_or_send(editable, monkeypatch):
    captured = []
    monkeypatch.setitem(delivery._dependencies, "content_checker", _configured_output_checker(captured, settings={}))

    @contextmanager
    def revoked_context(action, **kwargs):
        raise delivery.M365PolicyError("m365_sharing_not_authorized", "Shared access was revoked.")
        yield

    monkeypatch.setitem(delivery._dependencies, "context_scope", revoked_context)
    saved, error = delivery.dispatch_m365_pending_delivery("owner", editable.action["id"])
    assert error["error"] == "m365_sharing_not_authorized" and saved["status"] == "review_required"
    assert captured == [] and editable.calls == []


def test_history_is_bounded_paged_and_cleared_on_cancel(editable):
    state = editable
    state.action = state.create("calendar")
    for index in range(45):
        _save(state, {"subject": f"Revision {index}"})
    page = review.get_pending_review(state.cards.container, "owner", state.action["id"], limit=10)
    assert len(page["history"]["items"]) == 10
    second = review.get_pending_review(
        state.cards.container, "owner", state.action["id"], limit=40, cursor=page["history"]["next_cursor"],
    )
    assert len(second["history"]["items"]) == 30
    history = read_review_history(state.cards.container, page["action"])
    assert len(history["items"]) == 40
    cancelled, error = delivery.dispatch_m365_pending_delivery("owner", state.action["id"], cancel=True)
    assert error is None and cancelled["status"] == "cancelled"
    remaining = read_review_history(state.cards.container, cancelled)
    assert remaining is None
    assert history_id(state.action["id"]) not in cancelled
    assert state.calls == []


def test_workflow_run_cancellation_uses_saved_owned_records_without_remote_calls(pending):
    container, calls, _events = pending
    delivery.cancel_m365_run_deliveries("workflow", "another-run")
    before = container.read_item("delivery", "consenting-reader")
    assert before["status"] == "scheduled"
    delivery.cancel_m365_run_deliveries("workflow", "run")
    after = container.read_item("delivery", "consenting-reader")
    assert after["status"] == "cancelled" and calls == []

def test_full_unicode_revision_history_fits_bounded_cosmos_document(editable):
    state = editable
    state.action = state.create("calendar")
    body = "\U0001f600" * 50000
    first = _save(state, {"body": body})
    second = _save(state, {"subject": "Full body retained"})
    history = read_review_history(state.cards.container, second["action"])
    assert len(json.dumps(history).encode()) < 2 * 1024 * 1024
    assert history["items"][-1]["from_fields"]["body"] == body
    assert history["items"][-1]["fields"]["body"] == first["fields"]["body"] == body


def test_calendar_offset_times_and_windows_zones_are_normalized_locally(editable):
    editable.action = editable.create("calendar")
    saved = _save(editable, {
        "timezone": "New Zealand Standard Time",
        "start_datetime": "2026-10-12T09:00:00+00:00", "end_datetime": "2026-10-12T10:00:00+00:00",
    })
    assert saved["fields"]["start_datetime"] == "2026-10-12T22:00:00"
    assert saved["fields"]["end_datetime"] == "2026-10-12T23:00:00"
    assert editable.calls == []


def test_ai_calendar_candidate_does_not_create_event_or_save_until_owner_saves(editable):
    editable.action = editable.create("calendar")
    services, _, _ = _services({
        "reply": "Suggest a new location.", "operations": [{"op": "set", "path": "/location", "value": "Room B"}],
    })
    result = _assist(editable, services)
    reopened = review.get_pending_review(editable.cards.container, "owner", editable.action["id"])
    assert result["candidate_fields"]["location"] == "Room B"
    assert reopened["fields"]["location"] == "Room A"
    assert editable.calls == []
    saved = _save(editable, result["candidate_fields"], origin="ai", assist_turn_id=result["assist_turn_id"])
    assert saved["history"]["items"][1]["saved"] and saved["history"]["items"][1]["applied"]
    restored = _save(editable, saved["history"]["items"][0]["from_fields"])
    assert restored["fields"]["location"] == "Room A" and editable.calls == []


def test_assist_reopen_retains_exact_unsaved_source_fields_for_safe_undo(editable):
    action = editable.cards.container.read_item(editable.action["id"], "owner")
    working = review.review_fields(action)
    working.update(subject="Unsaved working subject", body="Unsaved owner notes")
    services, _, _ = _services()
    result = _assist(editable, services, fields=working)
    reopened = review.get_pending_review(editable.cards.container, "owner", editable.action["id"])
    turn = reopened["history"]["items"][0]
    assert turn["from_fields"] == working
    assert turn["candidate_fields"] == result["candidate_fields"]
    assert turn["warnings"] == result["warnings"]
    assert reopened["fields"]["subject"] == "Review me"
    assert reopened["fields"]["body"] != "Unsaved owner notes"
    assert editable.calls[-1][0] == "GET"
    assert not any(call[0] in {"PATCH", "POST"} for call in editable.calls)


def test_assist_limits_and_submission_validation_survive_history_reopen(editable):
    services, model_calls, _ = _services()
    _assist(editable, services)
    for overrides in (
        {"instruction": "x" * 2001},
        {"conversation": [{"role": "user", "text": "x" * 4001}]},
        {"submission_id": "not/a/submission"},
        {"submission_id": None},
    ):
        with pytest.raises(EditorAssistError):
            _assist(editable, services, **overrides)
    assert len(model_calls) == 1 and editable.calls == []


def test_assist_submission_replay_is_bound_to_instruction_and_material(editable):
    services, model_calls, _ = _services()
    submission = str(uuid.uuid4())
    first = _assist(editable, services, submission_id=submission)
    replayed = _assist(editable, services, submission_id=submission)
    assert replayed["assist_turn_id"] == first["assist_turn_id"]
    assert replayed["candidate_fields"] == first["candidate_fields"] and len(model_calls) == 1
    with pytest.raises(delivery.M365PolicyError):
        _assist(editable, services, submission_id=submission, instruction="Send something else")


def test_assist_lost_response_replays_original_version_without_model_or_history_append(editable, monkeypatch):
    services, model_calls, _ = _services()
    state = editable
    monkeypatch.setattr(state.cards.routes, "_pending_review_assist_services", lambda: services)
    body = {
        "submission_id": str(uuid.uuid4()), "instruction": "Clarify the subject",
        "expected_version": state.action["_etag"], "fields": review.review_fields(state.action),
    }
    path = f"/api/msgraph/pending-actions/{state.action['id']}/assist"
    first = state.cards.client.post(path, json=body, headers=state.cards.headers)
    first_result = first.get_json()
    assert first.status_code == 200
    assert first_result["expected_version"] != body["expected_version"]
    replayed = state.cards.client.post(path, json=body, headers=state.cards.headers)
    result = replayed.get_json()
    assert replayed.status_code == 200
    assert result["expected_version"] == first_result["expected_version"]
    assert result["assist_turn_id"] == first_result["assist_turn_id"]
    assert result["reply"] == first_result["reply"] and result["candidate"] == first_result["candidate"]
    assert result["history"] == first_result["history"] and len(model_calls) == 1
    assert len(result["history"]["items"]) == 1
    changed = state.cards.client.post(path, json={**body, "instruction": "Different request"}, headers=state.cards.headers)
    assert changed.status_code == 409 and len(model_calls) == 1
    unknown = state.cards.client.post(path, json={**body, "submission_id": str(uuid.uuid4())}, headers=state.cards.headers)
    assert unknown.status_code == 409 and len(model_calls) == 1


@pytest.mark.parametrize("mode", ["draft_manual", "draft_delayed", "auto_send"])
def test_real_email_preparation_uses_immutable_ids_only_for_new_manual_drafts(execution, graph_plugins, mode):
    modules, pending = graph_plugins
    response = FakeResponse(
        {"id": "draft-1", "subject": "Subject", "changeKey": "draft-v1", "isDraft": True}, status=201,
    ) if mode != "auto_send" else FakeResponse(body=b"", status=202)
    request = Mock(return_value=response)
    client = M365Transport(
        "email", "email",
        cloud=M365CloudConfig("https://graph.microsoft.com/v1.0", "https://login.microsoftonline.com/tenant"),
        request=request, token_provider=lambda *args: {"access_token": "offline"},
    )
    plugin = modules["m365_email_plugin"].M365EmailPlugin({
        "id": "email", "m365_capabilities": {"send_mail": True},
        "additionalFields": {"msgraph_mail_send_mode": mode},
    })
    plugin._transports["email"] = plugin._transports[None] = client
    result = plugin.send_mail("person@example.test", "Subject", "Body")
    if mode == "draft_manual":
        assert request.call_args.kwargs["headers"]["Prefer"] == 'IdType="ImmutableId"'
        assert pending.create_msgraph_pending_action.call_args.kwargs["graph_send_strategy"] == "draft_send_v1"
        assert result["pending_user_action"]
    elif mode == "draft_delayed":
        assert "Prefer" not in request.call_args.kwargs["headers"]
        assert pending.create_msgraph_pending_action.call_args.kwargs["graph_send_strategy"] == ""
    else:
        assert result["mail_send_status"] == "sent"
        assert pending.create_msgraph_pending_action.call_count == 0


def test_review_routes_require_owner_csrf_version_and_return_no_cache(editable, monkeypatch):
    state = editable
    path = f"/api/msgraph/pending-actions/{state.action['id']}"
    response = state.cards.client.get(path + "/review")
    assert response.status_code == 200 and response.headers["Cache-Control"] == "no-store, private"
    assert response.get_json()["fields"]["bcc_recipients"] == ["private@example.test"]
    denied = state.cards.client.patch(path + "/review", json={"expected_version": state.action["_etag"], "fields": {"subject": "No"}})
    assert denied.status_code == 403
    stale = state.cards.client.patch(path + "/review", json={"expected_version": "stale", "fields": {"subject": "No"}}, headers=state.cards.headers)
    assert stale.status_code == 409
    services, _, _ = _services()
    monkeypatch.setattr(state.cards.routes, "_pending_review_assist_services", lambda: services)
    assisted = state.cards.client.post(path + "/assist", json={
        "expected_version": state.action["_etag"], "fields": response.get_json()["fields"],
        "submission_id": str(uuid.uuid4()), "instruction": "Clarify the subject",
    }, headers=state.cards.headers)
    assert assisted.status_code == 200
    assert assisted.get_json()["candidate_fields"]["subject"] == "Clearer subject"
    state.cards.sign_in("viewer")
    for suffix in ("/review", "/history"):
        denied = state.cards.client.get(path + suffix)
        assert denied.status_code == 404 and "fields" not in denied.get_json()


def test_review_routes_expose_fixed_timezone_aliases_without_mutating_saved_instants(editable, monkeypatch):
    state = editable
    state.action = state.create("calendar")
    saved = state.cards.container.read_item(state.action["id"], "owner")
    instant = "2026-10-12T13:00:00.1234567Z"
    saved["graph_payload"]["start"]["dateTime"] = instant
    saved["graph_payload"]["end"]["dateTime"] = "2026-10-12T14:00:00.1234567Z"
    saved["material_fingerprint"] = delivery.pending_delivery_fingerprint(saved)
    state.action = state.cards.container.upsert_item(body=saved)
    path = f"/api/msgraph/pending-actions/{state.action['id']}"
    response = state.cards.client.get(path + "/review")
    payload = response.get_json()
    assert response.status_code == 200 and payload["fields"]["start_datetime"] == instant
    assert payload["timezone_aliases"] == review._WINDOWS_ZONES
    assert payload["timezone_aliases"]["Eastern Standard Time"] == "America/New_York"
    assert payload["timezone_aliases"]["India Standard Time"] == "Asia/Kolkata"
    assert "timezone_aliases" not in payload["fields"]
    history = state.cards.client.get(path + "/history")
    assert history.status_code == 200 and history.get_json()["timezone_aliases"] == review._WINDOWS_ZONES
    unchanged = state.cards.container.read_item(state.action["id"], "owner")
    assert unchanged["graph_payload"]["start"]["dateTime"] == instant
    rejected = state.cards.client.patch(path + "/review", json={
        "expected_version": payload["expected_version"], "fields": {"timezone_aliases": {"UTC": "invalid"}},
    }, headers=state.cards.headers)
    assert rejected.status_code == 400 and state.calls == []
    edited = state.cards.client.patch(path + "/review", json={
        "expected_version": payload["expected_version"], "fields": {"subject": "Calendar update"},
    }, headers=state.cards.headers)
    edited_payload = edited.get_json()
    assert edited.status_code == 200 and edited_payload["timezone_aliases"] == review._WINDOWS_ZONES
    services, _, _ = _services()
    monkeypatch.setattr(state.cards.routes, "_pending_review_assist_services", lambda: services)
    assisted = state.cards.client.post(path + "/assist", json={
        "expected_version": edited_payload["expected_version"], "fields": edited_payload["fields"],
        "submission_id": str(uuid.uuid4()), "instruction": "Clarify the subject",
    }, headers=state.cards.headers)
    assert assisted.status_code == 200 and assisted.get_json()["timezone_aliases"] == review._WINDOWS_ZONES
    state.cards.sign_in("viewer")
    denied = state.cards.client.get(path + "/review")
    assert denied.status_code == 404 and "timezone_aliases" not in denied.get_json()


@pytest.mark.parametrize("settings", [
    {"enable_semantic_kernel": True, "enable_action_ai_assistant": False},
    {"enable_semantic_kernel": False, "enable_action_ai_assistant": True},
])
def test_assist_route_enforces_existing_action_assistant_setting(editable, monkeypatch, settings):
    configured = []

    def enabled(values):
        configured.append(values)
        return values.get("enable_semantic_kernel") is True and values.get("enable_action_ai_assistant", True) is not False

    monkeypatch.setitem(sys.modules, "functions_settings", module_stub(
        "functions_settings", get_settings=lambda: settings, is_action_assistant_enabled=enabled,
    ))
    # Disabled assistance must not resolve clients or reach model/Graph services.
    monkeypatch.setitem(sys.modules, "route_backend_agents", module_stub("route_backend_agents"))
    state = editable
    response = state.cards.client.post(f"/api/msgraph/pending-actions/{state.action['id']}/assist", json={
        "expected_version": state.action["_etag"], "fields": review.review_fields(state.action),
        "submission_id": str(uuid.uuid4()), "instruction": "Clarify the subject",
    }, headers=state.cards.headers)
    assert response.status_code == 403
    assert response.get_json()["code"] == "action_assistant_disabled"
    assert configured == [settings] and state.calls == []
    history = read_review_history(state.cards.container, state.action)
    assert history is None


def test_review_route_swagger_and_blueprint_security_contract():
    source = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_msgraph_pending_actions.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for name in ("get_user_msgraph_pending_review", "save_user_msgraph_pending_review", "get_user_msgraph_pending_history", "assist_user_msgraph_pending_review"):
        decorators = [ast.unparse(item) for item in functions[name].decorator_list]
        assert decorators[0].startswith("bp.route(")
        assert decorators[1] == "swagger_route(security=get_auth_security())"
        assert "login_required" in decorators and "user_required" in decorators


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
