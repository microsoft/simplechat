# test_m365_pending_delivery.py
"""
Durable Microsoft 365 workflow delivery and Run as principal regression tests.
Version: 0.261.038
Implemented in: 0.261.029

Conditional writes, concurrent sends, cancellation, revocation, and uncertain
delivery recovery use real dispatcher code with isolated storage and Graph I/O.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from threading import Event

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Standalone source paths are set before importing the application modules.
import functions_m365_pending_delivery as delivery
from functions_m365_execution import M365ExecutionContext, get_m365_execution_context, m365_execution_context
from functions_m365_transport import M365ProviderError
from functions_workflow_activity import build_workflow_activity_snapshot
from test_support.m365 import CosmosContainer


class PendingContainer(CosmosContainer):
    def query_items(self, **kwargs):
        parameters = {item["name"]: item["value"] for item in kwargs.get("parameters", [])}
        rows = [self.read_item(item["id"], item["user_id"]) for item in list(self.items.values())]
        for field in ("conversation_id", "workflow_id", "run_id"):
            if f"@{field}" in parameters:
                rows = [
                    row for row in rows
                    if row.get(field) == parameters[f"@{field}"]
                    and row.get("status") in {"pending", "scheduled", "review_required"}
                ]
        if "@now" in parameters:
            now = datetime.fromisoformat(parameters["@now"])
            rows = [
                row for row in rows if (
                    row.get("status") == "scheduled"
                    and datetime.fromisoformat(row["auto_send_at_utc"]) <= now
                ) or (
                    row.get("status") == "sending"
                    and (
                        not row.get("delivery_claim_expires_at")
                        or datetime.fromisoformat(row["delivery_claim_expires_at"]) <= now
                    )
                ) or (
                    row.get("m365_notification_pending")
                    and row.get("status") in {"pending", "review_required", "failed", "recovery_required"}
                )
            ]
        return rows[:parameters.get("@limit", len(rows))]


@pytest.fixture
def pending(monkeypatch):
    container = PendingContainer("user_id")
    calls = []
    events = []
    context = M365ExecutionContext(
        actor_user_id="workflow-author", data_user_id="consenting-reader", tenant_id="tenant",
        conversation_id="conversation", request_id="run", workflow_id="workflow", run_id="run",
        connection_id="connection", binding_id="binding", workflow_fingerprint="revision",
        action_configs={"action": {"type": "m365_email", "source": "email"}},
    )
    with m365_execution_context(context):
        snapshot = delivery.capture_workflow_delivery("consenting-reader", "action", "workflow", "run")
    action = {
        "id": "delivery", "user_id": "consenting-reader", "type": "msgraph_pending_action",
        "workflow_id": "workflow", "run_id": "run", "m365_execution": snapshot,
        "conversation_id": "conversation", "request_id": "run", "action_mode": "delayed",
        "operation": "send_mail", "graph_message_id": "draft/id",
        "graph_draft_version": "draft-v1",
        "graph_payload": {"message": {"subject": "Reviewed email"}, "saveToSentItems": True},
        "status": "scheduled",
        "auto_send_at_utc": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    action["material_fingerprint"] = delivery.pending_delivery_fingerprint(action)
    container.create_item(body=action)

    @contextmanager
    def context_scope(action, **kwargs):
        with m365_execution_context(M365ExecutionContext(**action["m365_execution"]["context"])):
            yield

    class Transport:
        def __init__(self, source, action_id, **kwargs):
            self.source, self.action_id = source, action_id
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
            if method == "GET":
                return {"id": "draft/id", "changeKey": "draft-v1", "isDraft": True}
            if self.before_request is not None:
                self.before_request()
            calls.append({
                "principal": get_m365_execution_context().data_user_id,
                "source": self.source, "method": method, "path": path, "scopes": scopes, **kwargs,
            })
            return {"id": "event", "webLink": "https://outlook.example.test/event"}

    monkeypatch.setattr(delivery, "_dependencies", {})
    delivery.configure_m365_pending_delivery(
        container=container, context_scope=context_scope, transport_factory=Transport,
        log_event=lambda *args, **kwargs: events.append(args),
        notification_sender=lambda action: events.append(("notification", action["user_id"])) or {"id": "notice"},
    )
    return container, calls, events


def test_due_delivery_uses_saved_run_as_not_workflow_author_and_never_replays(pending):
    container, calls, _ = pending
    delivery.dispatch_due_m365_deliveries()
    delivery.dispatch_due_m365_deliveries()
    saved = container.read_item("delivery", "consenting-reader")
    assert saved["status"] == "sent"
    assert len(calls) == 1
    assert calls[0]["principal"] == "consenting-reader"
    assert calls[0]["path"] == "/v1.0/me/sendMail"
    assert calls[0]["json_body"]["message"]["subject"] == "Reviewed email"
    assert calls[0]["expect_json"] is False
    assert "token" not in str(saved["m365_execution"]).lower()


def test_calendar_delivery_records_created_event(pending):
    container, calls, _ = pending
    action = container.read_item("delivery", "consenting-reader")
    action.update(operation="create_calendar_invite", graph_payload={"subject": "Meeting"})
    action["m365_execution"]["action_type"] = "m365_calendar"
    action["material_fingerprint"] = delivery.pending_delivery_fingerprint(action)
    container.upsert_item(body=action)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    assert error is None
    assert saved["graph_event_id"] == "event"
    assert calls[0]["scopes"] == ["Calendars.ReadWrite"]
    assert calls[0]["expect_json"] is True
    assert calls[0]["json_body"]["transactionId"] == "delivery"


def test_calendar_success_without_event_id_requires_recovery_not_replay(pending, monkeypatch):
    container, calls, _ = pending
    action = container.read_item("delivery", "consenting-reader")
    action.update(operation="create_calendar_invite", graph_payload={"subject": "Meeting"})
    action["m365_execution"]["action_type"] = "m365_calendar"
    action["material_fingerprint"] = delivery.pending_delivery_fingerprint(action)
    container.upsert_item(body=action)
    original = delivery._dependencies["transport_factory"]

    class IncompleteCalendar(original):
        def request_json(self, *args, **kwargs):
            super().request_json(*args, **kwargs)
            return {}

    monkeypatch.setitem(delivery._dependencies, "transport_factory", IncompleteCalendar)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    repeated, repeated_error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    assert saved["status"] == repeated["status"] == "recovery_required"
    assert error["error"] == "incomplete_response"
    assert repeated_error["error"] == "delivery_outcome_unknown"
    assert len(calls) == 1


def test_pending_delivery_notice_targets_run_as_and_is_acknowledged(pending):
    container, calls, events = pending
    action = container.read_item("delivery", "consenting-reader")
    action.update(status="pending", m365_notification_pending=True)
    container.upsert_item(body=action)
    delivery.notify_m365_pending_delivery(action)
    saved = container.read_item("delivery", "consenting-reader")
    delivery.notify_m365_pending_delivery(saved)
    assert events == [("notification", "consenting-reader")]
    assert saved["m365_notification_pending"] is False
    assert calls == []

def test_cancel_stops_delivery_without_remote_permissions(pending):
    container, calls, _ = pending
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery", cancel=True)
    delivery.dispatch_due_m365_deliveries()
    assert error is None
    assert saved["status"] == "cancelled"
    assert "not deleted" in saved["delivery_note"]
    assert calls == []


def test_revoked_authorization_fails_before_graph(pending, monkeypatch):
    container, calls, events = pending

    @contextmanager
    def denied_scope(action, **kwargs):
        raise PermissionError("Revoked")
        yield

    monkeypatch.setitem(delivery._dependencies, "context_scope", denied_scope)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    assert saved["status"] == "review_required"
    assert error is not None
    assert calls == []
    assert events


def test_parallel_send_now_and_scheduler_have_one_external_effect(pending, monkeypatch):
    container, calls, _ = pending
    entered, release = Event(), Event()
    original = delivery._dependencies["transport_factory"]

    class BlockingTransport(original):
        def request_json(self, *args, **kwargs):
            if args[0] == "POST":
                entered.set()
                if not release.wait(timeout=5):
                    raise AssertionError("The test did not release the claimed operation.")
            return super().request_json(*args, **kwargs)

    monkeypatch.setitem(delivery._dependencies, "transport_factory", BlockingTransport)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(delivery.dispatch_m365_pending_delivery, "consenting-reader", "delivery")
        started = entered.wait(timeout=5)
        assert started
        second, conflict = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
        release.set()
        completed, error = first.result(timeout=5)
    assert conflict["error"] == "delivery_in_progress"
    assert second["status"] == "sending"
    assert completed["status"] == "sent" and error is None
    assert len(calls) == 1


def test_unknown_external_outcome_is_not_automatically_retried(pending, monkeypatch):
    container, calls, _ = pending
    original = delivery._dependencies["transport_factory"]

    class InterruptedTransport(original):
        def request_json(self, *args, **kwargs):
            result = super().request_json(*args, **kwargs)
            if args[0] == "POST":
                raise M365ProviderError("request_failed", "Remote response was interrupted.")
            return result

    monkeypatch.setitem(delivery._dependencies, "transport_factory", InterruptedTransport)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    delivery.dispatch_due_m365_deliveries()
    assert saved["status"] == "recovery_required"
    assert error is not None
    assert len(calls) == 1


def test_stale_review_version_does_not_acquire_or_send(pending):
    container, calls, _ = pending
    before = container.read_item("delivery", "consenting-reader")
    saved, error = delivery.dispatch_m365_pending_delivery(
        "consenting-reader", "delivery", expected_version="stale",
    )
    after = container.read_item("delivery", "consenting-reader")
    assert error["error"] == "pending_action_changed"
    assert saved["_etag"] == before["_etag"] == after["_etag"]
    assert calls == []


def test_wrong_owner_cannot_read_or_send_a_pending_action(pending):
    _, calls, _ = pending
    saved, error = delivery.dispatch_m365_pending_delivery("someone-else", "delivery")
    assert saved is None
    assert error["error"] == "not_found"
    assert calls == []


def test_changed_material_requires_review_without_graph_access(pending):
    container, calls, _ = pending
    action = container.read_item("delivery", "consenting-reader")
    action["graph_payload"]["message"]["subject"] = "Unreviewed replacement"
    container.upsert_item(body=action)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    assert error["error"] == "m365_action_material_changed"
    assert saved["status"] == "scheduled"
    assert calls == []


def test_changed_outlook_draft_is_not_sent_or_overwritten(pending, monkeypatch):
    container, calls, _ = pending
    original = delivery._dependencies["transport_factory"]

    class ChangedDraft(original):
        def request_json(self, method, *args, **kwargs):
            if method == "GET":
                return {"changeKey": "draft-v2", "isDraft": True}
            return super().request_json(method, *args, **kwargs)

    monkeypatch.setitem(delivery._dependencies, "transport_factory", ChangedDraft)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    assert error["error"] == "m365_action_material_changed"
    assert saved["status"] == "review_required"
    assert calls == []
    stored = container.read_item("delivery", "consenting-reader")
    assert stored["graph_payload"]["message"]["subject"] == "Reviewed email"


def test_authentication_repair_keeps_the_same_unsent_action(pending, monkeypatch):
    container, calls, _ = pending
    original = delivery._dependencies["transport_factory"]

    class ExpiredSignIn(original):
        def get_token(self, scopes):
            raise M365ProviderError(
                "interactive_auth_required", "Sign in required.",
                details={"scopes": list(scopes)},
            )

    monkeypatch.setitem(delivery._dependencies, "transport_factory", ExpiredSignIn)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    assert error["auth_required"] is True
    assert saved["id"] == "delivery" and saved["status"] == "pending"
    assert calls == []
    assert len(container.items) == 1
    monkeypatch.setitem(delivery._dependencies, "transport_factory", original)
    completed, send_error = delivery.dispatch_m365_pending_delivery(
        "consenting-reader", "delivery", expected_version=saved["_etag"],
    )
    assert completed["status"] == "sent" and send_error is None
    assert len(calls) == 1


def test_cancel_does_not_need_a_working_token_provider(pending, monkeypatch):
    _, calls, _ = pending

    def forbidden_transport(*args, **kwargs):
        raise AssertionError("Cancellation must stop delivery without Graph authentication.")

    monkeypatch.setitem(delivery._dependencies, "transport_factory", forbidden_transport)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery", cancel=True)
    assert error is None and saved["status"] == "cancelled"
    assert calls == []


def test_unbound_historical_records_are_visible_but_cannot_be_sent(pending):
    container, calls, _ = pending
    action = container.read_item("delivery", "consenting-reader")
    action.pop("m365_execution")
    container.upsert_item(body=action)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    assert error["error"] == "m365_action_review_required"
    assert calls == []
    cancelled, cancel_error = delivery.dispatch_m365_pending_delivery(
        "consenting-reader", "delivery", cancel=True, expected_version=saved["_etag"],
    )
    assert cancel_error is None and cancelled["status"] == "cancelled"


def test_interactive_restart_recovery_does_not_send_overdue_actions(pending):
    container, calls, _ = pending
    action = container.read_item("delivery", "consenting-reader")
    action["m365_execution"]["kind"] = "chat"
    action["auto_send_at_utc"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    action["material_fingerprint"] = delivery.pending_delivery_fingerprint(action)
    container.upsert_item(body=action)
    delivery.dispatch_due_m365_deliveries()
    saved = container.read_item("delivery", "consenting-reader")
    assert saved["status"] == "review_required"
    assert saved["error_code"] == "delivery_schedule_expired"
    assert calls == []


def test_manual_inflight_claim_is_recovered_without_a_due_time(pending):
    container, calls, _ = pending
    action = container.read_item("delivery", "consenting-reader")
    action.update(
        status="sending", action_mode="manual", auto_send_at_utc="",
        delivery_claim_expires_at=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
    )
    container.upsert_item(body=action)
    delivery.dispatch_due_m365_deliveries()
    saved = container.read_item("delivery", "consenting-reader")
    assert saved["status"] == "recovery_required"
    assert calls == []


def test_old_unbound_schedule_is_paused_without_a_remote_write(pending):
    container, calls, _ = pending
    action = container.read_item("delivery", "consenting-reader")
    action.pop("m365_execution")
    container.upsert_item(body=action)
    delivery.dispatch_due_m365_deliveries()
    saved = container.read_item("delivery", "consenting-reader")
    assert saved["status"] == "review_required"
    assert calls == []


def test_review_required_notifications_retry_without_sending(pending):
    container, calls, events = pending
    action = container.read_item("delivery", "consenting-reader")
    action.update(status="review_required", m365_notification_pending=True)
    container.upsert_item(body=action)
    delivery.dispatch_due_m365_deliveries()
    saved = container.read_item("delivery", "consenting-reader")
    assert saved["status"] == "review_required"
    assert saved["m365_notification_pending"] is False
    assert events == [("notification", "consenting-reader")]
    assert calls == []


def test_deleted_conversation_cancels_only_its_unsent_actions(pending):
    container, calls, _ = pending
    original = container.read_item("delivery", "consenting-reader")
    container.create_item(body={**original, "id": "other", "conversation_id": "unrelated"})
    container.create_item(body={**original, "id": "already-claimed", "status": "sending"})
    delivery.cancel_m365_conversation_deliveries("conversation")
    cancelled = container.read_item("delivery", "consenting-reader")
    unrelated = container.read_item("other", "consenting-reader")
    claimed = container.read_item("already-claimed", "consenting-reader")
    assert cancelled["status"] == "cancelled"
    assert unrelated["status"] == "scheduled"
    assert claimed["status"] == "sending"
    assert calls == []


@pytest.mark.parametrize("status_code,code", [(401, "authentication_required"), (429, "throttled")])
def test_definitive_provider_rejection_can_be_manually_retried(pending, monkeypatch, status_code, code):
    _, calls, _ = pending
    original = delivery._dependencies["transport_factory"]

    class RejectedTransport(original):
        def request_json(self, *args, **kwargs):
            result = super().request_json(*args, **kwargs)
            if args[0] == "POST":
                raise M365ProviderError(code, "Rejected.", status_code=status_code)
            return result

    monkeypatch.setitem(delivery._dependencies, "transport_factory", RejectedTransport)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    delivery.dispatch_due_m365_deliveries()
    assert saved["status"] == "pending" and error["error"] == code
    assert len(calls) == 1
    monkeypatch.setitem(delivery._dependencies, "transport_factory", original)
    completed, error = delivery.dispatch_m365_pending_delivery(
        "consenting-reader", "delivery", expected_version=saved["_etag"],
    )
    assert completed["status"] == "sent" and error is None
    assert len(calls) == 2


def test_approval_wait_and_pending_delivery_remain_live():
    waiting = build_workflow_activity_snapshot(run_record={"id": "run", "status": "awaiting_approval"})
    sending = build_workflow_activity_snapshot(
        run_record={"id": "run", "status": "completed"},
        pending_actions=[{"id": "delivery", "status": "sending", "operation": "send_mail"}],
    )
    failed = build_workflow_activity_snapshot(
        run_record={"id": "run", "status": "completed"},
        pending_actions=[{"id": "delivery", "status": "recovery_required", "operation": "send_mail"}],
    )
    assert waiting["live"] is True
    assert sending["live"] is True
    assert sending["activities"][-1]["status"] == "running"
    assert failed["live"] is False
    assert failed["activities"][-1]["status"] == "failed"


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
