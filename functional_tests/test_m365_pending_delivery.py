# test_m365_pending_delivery.py
"""
Durable Microsoft 365 workflow delivery and Run as principal regression tests.
Version: 0.261.029
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
        now = datetime.now(timezone.utc)
        return [
            self.read_item(item["id"], item["user_id"])
            for item in list(self.items.values())
            if item.get("status") in {"scheduled", "sending"}
            and datetime.fromisoformat(item["auto_send_at_utc"]) <= now
        ]


@pytest.fixture
def pending(monkeypatch):
    container = PendingContainer("user_id")
    calls = []
    events = []
    context = M365ExecutionContext(
        actor_user_id="workflow-author", data_user_id="consenting-reader", tenant_id="tenant",
        conversation_id="conversation", request_id="run", workflow_id="workflow", run_id="run",
        connection_id="connection", binding_id="binding", workflow_fingerprint="revision",
    )
    with m365_execution_context(context):
        snapshot = delivery.capture_workflow_delivery("consenting-reader", "action", "workflow", "run")
    container.create_item(body={
        "id": "delivery", "user_id": "consenting-reader", "type": "msgraph_pending_action",
        "workflow_id": "workflow", "run_id": "run", "m365_execution": snapshot,
        "operation": "send_mail", "graph_message_id": "draft/id",
        "status": "scheduled",
        "auto_send_at_utc": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    })

    @contextmanager
    def context_scope(action):
        with m365_execution_context(M365ExecutionContext(**action["m365_execution"]["context"])):
            yield

    class Transport:
        def __init__(self, source, action_id):
            self.source, self.action_id = source, action_id

        def request_json(self, method, path, scopes, **kwargs):
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
    assert calls[0]["path"] == "/v1.0/me/messages/draft%2Fid/send"
    assert calls[0]["expect_json"] is False
    assert "token" not in str(saved["m365_execution"]).lower()


def test_calendar_delivery_records_created_event(pending):
    container, calls, _ = pending
    action = container.read_item("delivery", "consenting-reader")
    action.update(operation="create_calendar_invite", graph_payload={"subject": "Meeting"})
    container.upsert_item(body=action)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    assert error is None
    assert saved["graph_event_id"] == "event"
    assert calls[0]["scopes"] == ["Calendars.ReadWrite"]
    assert calls[0]["expect_json"] is True


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
    def denied_scope(action):
        raise PermissionError("Revoked")
        yield

    monkeypatch.setitem(delivery._dependencies, "context_scope", denied_scope)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    assert saved["status"] == "failed"
    assert error is not None
    assert calls == []
    assert events


def test_parallel_send_now_and_scheduler_have_one_external_effect(pending, monkeypatch):
    container, calls, _ = pending
    entered, release = Event(), Event()
    original = delivery._dependencies["transport_factory"]

    class BlockingTransport(original):
        def request_json(self, *args, **kwargs):
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
            super().request_json(*args, **kwargs)
            raise M365ProviderError("request_failed", "Remote response was interrupted.")

    monkeypatch.setitem(delivery._dependencies, "transport_factory", InterruptedTransport)
    saved, error = delivery.dispatch_m365_pending_delivery("consenting-reader", "delivery")
    delivery.dispatch_due_m365_deliveries()
    assert saved["status"] == "recovery_required"
    assert error is not None
    assert len(calls) == 1


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
