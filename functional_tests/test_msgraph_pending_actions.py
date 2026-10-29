# test_msgraph_pending_actions.py
"""
Functional tests for pending Microsoft Graph summaries, selection and timers.
Version: 0.261.038
Implemented in: 0.241.179

The shared API harness executes the real pending store and dispatcher with scoped
external I/O seams. Assertions fail both pytest and standalone runs; obsolete
unclaimed-send and token-helper mocks are deliberately not retained.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parent))

# Reuse the scoped external-I/O fixture rather than mocking the delivery boundary.
from test_m365_action_card_api import cards


def test_owner_summary_matches_saved_material_and_anonymous_projection_is_read_only(cards):
    created = cards.create("send_mail")
    owner = cards.service.sanitize_msgraph_pending_action_for_client(created, viewer_user_id="owner")
    anonymous = cards.service.sanitize_msgraph_pending_action_for_client(created)
    model = cards.service.sanitize_msgraph_pending_action_for_client(
        created, viewer_user_id="owner", include_preview=False,
    )
    assert owner["summary"]["to_recipients"] == ["reviewed@example.test"]
    assert owner["summary"]["bcc_recipients"] == ["private@example.test"]
    assert owner["summary"]["body_preview"] == created["graph_payload"]["message"]["body"]["content"]
    assert owner["can_send_now"] and owner["can_cancel"]
    assert not anonymous["can_send_now"] and not anonymous["can_cancel"]
    assert "body_preview" not in anonymous["summary"] and "bcc_recipients" not in anonymous["summary"]
    assert "body_preview" not in model["summary"] and "bcc_recipients" not in model["summary"]
    assert "graph_payload" not in owner and "m365_execution" not in owner


def test_owner_filters_and_limits_are_applied_in_storage(cards):
    created = cards.create()
    selected = cards.service.list_msgraph_pending_actions("owner", conversation_id="conversation", limit=1)
    other_owner = cards.service.list_msgraph_pending_actions("viewer")
    other_run = cards.service.list_msgraph_pending_actions("owner", run_id="unrelated")
    assert [item["id"] for item in selected] == [created["id"]]
    assert other_owner == other_run == []
    assert all("TOP @limit" in query and "ORDER BY c.created_at DESC" in query for query in cards.container.queries)
    with pytest.raises(cards.service.M365PolicyError):
        cards.service.list_msgraph_pending_actions("owner", limit=101)


def test_cancellation_removes_local_timer_without_deleting_outlook_draft(cards, monkeypatch):
    created = cards.create("send_mail")
    cancelled_timers = []
    timer = type("Timer", (), {"cancel": lambda self: cancelled_timers.append(created["id"])})()
    monkeypatch.setattr(cards.service, "_scheduled_timers", {created["id"]: timer})
    stopped, error = cards.service.cancel_msgraph_pending_action(
        "owner", created["id"], expected_version=created["version"],
    )
    assert error is None and stopped["status"] == "cancelled"
    assert cancelled_timers == [created["id"]]
    assert cards.service._scheduled_timers == {}
    assert cards.writes == []


def test_short_timer_is_ephemeral_and_never_runs_when_rendering_a_card(cards, monkeypatch):
    created = cards.create()
    scheduled = {
        **created, "status": "scheduled", "action_mode": "delayed", "delay_seconds": 10,
        "auto_send_at_utc": (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat(),
    }
    timers = []

    class Timer:
        def __init__(self, seconds, callback):
            self.seconds = seconds
            self.callback = callback
            self.daemon = False

        def start(self):
            timers.append(self)

        def cancel(self):
            self.cancelled = True

    monkeypatch.setattr(cards.service.threading, "Timer", Timer)
    monkeypatch.setattr(cards.service, "_scheduled_timers", {})
    scheduled_ok = cards.service.schedule_msgraph_pending_action_auto_commit(scheduled, "ephemeral-test-token")
    card = cards.service.sanitize_msgraph_pending_action_for_client(scheduled, viewer_user_id="owner")
    assert scheduled_ok and len(timers) == 1
    assert 0 < timers[0].seconds <= 10 and timers[0].daemon
    assert card["status"] == "scheduled"
    assert "ephemeral-test-token" not in str(cards.container.items)
    assert cards.writes == []


def test_shared_pagination_uses_a_streamable_cross_partition_query(cards):
    for _ in range(3):
        cards.create(shared=True)
    cards.sign_in("viewer")
    first = cards.client.get("/api/msgraph/pending-actions?conversation_id=conversation&limit=2")
    payload = first.get_json()
    second = cards.client.get("/api/msgraph/pending-actions", query_string={
        "conversation_id": "conversation", "limit": 2, "continuation_token": payload["continuation_token"],
    })
    assert len(payload["pending_actions"]) == 2
    assert len(second.get_json()["pending_actions"]) == 1
    assert all("ORDER BY" not in query for query in cards.container.queries)
    assert all(not card["can_send_now"] for card in payload["pending_actions"])


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
