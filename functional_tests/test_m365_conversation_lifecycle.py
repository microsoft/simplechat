# test_m365_conversation_lifecycle.py
"""
Functional regressions for Microsoft 365 conversation deletion and copying.
Version: 0.261.038
Implemented in: 0.261.038
Date: 2026-09-19

Real cancellation, fork/copy, Flask deletion, and retention code run against
isolated storage. No Graph request, credential acquisition, or deployment occurs.
"""

from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

from azure.cosmos.exceptions import CosmosHttpResponseError
import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Standalone paths are initialized before the real dependency-light helpers.
import functions_m365_pending_delivery as delivery
from functions_m365_action_cards import strip_pending_action_references
from functions_m365_context import M365PolicyError
from functions_m365_data_lifecycle import strip_m365_runtime_references
from test_support.m365 import CosmosContainer


class PendingContainer(CosmosContainer):
    def __init__(self):
        super().__init__("user_id")
        self.queries = []
        self.before_replace = None

    def query_items(self, query, parameters, enable_cross_partition_query=False, **kwargs):
        if not enable_cross_partition_query:
            raise AssertionError("Conversation lifecycle lookup must include its authorized participants.")
        values = {parameter["name"]: parameter["value"] for parameter in parameters}
        conversation_id = values["@conversation_id"]
        self.queries.append(conversation_id)
        return [
            deepcopy(row) for row in self.items.values()
            if row.get("type") == "msgraph_pending_action"
            and row.get("conversation_id") == conversation_id
            and row.get("status") in {"pending", "scheduled", "review_required"}
        ]

    def replace_item(self, item, body, **kwargs):
        callback, self.before_replace = self.before_replace, None
        if callback is not None:
            callback(item)
        return super().replace_item(item, body, **kwargs)


@pytest.fixture
def pending(monkeypatch):
    container = PendingContainer()
    no_graph = Mock(side_effect=AssertionError("Conversation cleanup must not call Graph."))

    @contextmanager
    def no_credentials(action):
        raise AssertionError("Stopping an intent must not require Microsoft 365 sign-in.")
        yield

    monkeypatch.setattr(delivery, "_dependencies", {})
    delivery.configure_m365_pending_delivery(
        container=container, context_scope=no_credentials,
        transport_factory=no_graph, log_event=Mock(),
    )
    return container, no_graph


def seed_pending(container, identifier, conversation_id="conversation", status="pending", user_id="owner"):
    return container.create_item(body={
        "id": identifier, "user_id": user_id, "conversation_id": conversation_id,
        "type": "msgraph_pending_action", "operation": "send_mail",
        "action_mode": "delayed" if status == "scheduled" else "manual",
        "status": status, "m365_notification_pending": False,
    })


def test_real_cancellation_helper_stops_only_exact_unsent_destination(pending):
    container, no_graph = pending
    for state in ("pending", "scheduled", "review_required", "sending", "sent", "cancelled", "failed"):
        seed_pending(container, state, status=state)
    seed_pending(container, "run-as", user_id="run-as-subject")
    seed_pending(container, "foreign", conversation_id="other", status="scheduled")
    delivery.cancel_m365_conversation_deliveries("conversation")
    delivery.cancel_m365_conversation_deliveries("conversation")
    outcomes = {row["id"]: row["status"] for row in container.items.values()}
    assert outcomes == {
        "pending": "cancelled", "scheduled": "cancelled", "review_required": "cancelled",
        "run-as": "cancelled", "sending": "sending", "sent": "sent",
        "cancelled": "cancelled", "failed": "failed", "foreign": "scheduled",
    }
    assert container.queries == ["conversation", "conversation"]
    no_graph.assert_not_called()


def test_real_cancellation_helper_never_recalls_a_claim_winner(pending):
    container, no_graph = pending
    seed_pending(container, "racing")

    def claim(item):
        current = container.read_item(item, "owner")
        container.upsert_item({**current, "status": "sending"})

    container.before_replace = claim
    delivery.cancel_m365_conversation_deliveries("conversation")
    current = container.read_item("racing", "owner")
    assert current["status"] == "sending"
    assert "cancelled_at" not in current
    no_graph.assert_not_called()


def test_real_cancellation_helper_retries_or_fails_closed_on_an_unsent_revision_race(pending):
    container, no_graph = pending
    seed_pending(container, "notification-race", status="scheduled")

    def refresh_notification(item):
        current = container.read_item(item, "owner")
        container.upsert_item({**current, "m365_notification_pending": False})

    container.before_replace = refresh_notification
    failed_closed = False
    try:
        delivery.cancel_m365_conversation_deliveries("conversation")
    except (M365PolicyError, CosmosHttpResponseError):
        failed_closed = True
    current = container.read_item("notification-race", "owner")
    assert current["status"] == "cancelled" or failed_closed, (
        "The helper reported success after an ETag conflict left an unclaimed scheduled "
        "intent active. Retry active records or raise so lifecycle callers keep the destination."
    )
    no_graph.assert_not_called()


def test_message_copy_strips_only_delivery_references_and_dtos_without_mutating_source():
    card = {"id": "pending", "type": "msgraph_pending_action", "can_approve": True}
    source = {
        "id": "message", "conversation_id": "source", "role": "assistant",
        "content": 'Historical prose: {"pending_action": "not executable"}.',
        "metadata": {"m365_pending_action_ids": ["pending"], "thread_info": {"thread_id": "thread"}},
        "m365_pending_actions": [card],
        "agent_citations": [{
            "function_result": {"pending_action": card, "pending_user_action": True, "message": "Prepared"},
        }],
        "other_records": [card, {"type": "m365_approval_required", "id": "approval"}],
    }
    before = deepcopy(source)
    copied = strip_pending_action_references(source)
    transferred = strip_m365_runtime_references(source)
    assert source == before
    assert copied == transferred
    assert copied["content"] == source["content"]
    assert copied["metadata"] == {"thread_info": {"thread_id": "thread"}}
    assert copied["agent_citations"][0]["function_result"] == {"message": "Prepared"}
    assert copied["other_records"] == [{"type": "m365_approval_required", "id": "approval"}]
    assert "m365_pending_actions" not in copied


def run_lifecycle_scenarios(runtime):
    # These real modules import inside the existing external-I/O-only bootstrap.
    import inspect
    from threading import Event
    from uuid import uuid4

    from flask import session
    import background_tasks
    import functions_collaboration as collaboration
    import functions_retention_policy as retention
    from collaboration_models import build_personal_collaboration_conversation
    from functions_settings import update_settings

    def require(condition, message):
        if not condition:
            raise AssertionError(message)

    config = runtime.config
    client = runtime.client
    owner = {"user_id": "owner", "display_name": "Owner", "email": "owner@example.test"}

    def seed(conversation_id, status="pending", user_id="owner"):
        identifier = uuid4().hex
        runtime.pending.create_item(body={
            "id": identifier, "user_id": user_id, "conversation_id": conversation_id,
            "type": "msgraph_pending_action", "operation": "create_calendar_invite",
            "status": status, "action_mode": "manual", "m365_notification_pending": False,
        })
        return identifier

    def state(identifier):
        return runtime.pending.items[identifier]["status"]

    def has_live_reference(value):
        if isinstance(value, dict):
            return (
                value.get("type") == "msgraph_pending_action"
                or any(key in value for key in ("m365_pending_actions", "m365_pending_action_ids", "m365_pending_action_id"))
                or any(has_live_reference(item) for item in value.values())
            )
        if isinstance(value, list):
            return any(has_live_reference(item) for item in value)
        return False

    response = client.post("/api/chat", json=runtime.prepare("fork-source"))
    payload = response.get_json()
    require(response.status_code == 200 and len(payload.get("m365_pending_actions", [])) == 2, f"Typed preparation failed: {payload}")
    message = config.cosmos_messages_container.read_item(payload["message_id"], "fork-source")
    message["m365_pending_actions"] = payload["m365_pending_actions"]
    message.setdefault("agent_citations", []).append({
        "function_result": {"pending_user_action": True, "pending_action": payload["m365_pending_actions"][0]},
    })
    config.cosmos_messages_container.upsert_item(message)
    source_snapshot = config.cosmos_messages_container.read_item(payload["message_id"], "fork-source")
    original_states = {row["id"]: row["status"] for row in runtime.records("fork-source")}
    calls_before_cleanup = len(runtime.graph_calls)
    fork = client.post("/api/conversations/fork-source/fork", json={"message_id": payload["message_id"]})
    require(fork.status_code == 201, f"Real fork failed: {fork.get_json()}")
    fork_id = fork.get_json()["conversation_id"]
    fork_messages = [
        row for row in config.cosmos_messages_container.items.values() if row.get("conversation_id") == fork_id
    ]
    require(bool(fork_messages) and not has_live_reference(fork_messages), "A fork retained executable delivery references/DTOs.")
    require(config.cosmos_messages_container.read_item(payload["message_id"], "fork-source") == source_snapshot, "Forking mutated the source message.")
    require({row["id"]: row["status"] for row in runtime.records("fork-source")} == original_states, "Forking cancelled or recreated the source delivery.")

    for copy_function, target in (
        (collaboration._copy_legacy_personal_messages_to_collaboration, "copied-personal"),
        (collaboration._copy_legacy_group_messages_to_collaboration, "copied-group"),
    ):
        copies = copy_function("fork-source", target, owner, raw_messages=[source_snapshot])
        require(bool(copies) and not has_live_reference(copies), "A copied collaboration history retained delivery controls.")

    require(len(runtime.graph_calls) == calls_before_cleanup, "Forking or copying history called Graph.")
    request_payload = runtime.prepare("delete-inflight")
    runtime.model.release, runtime.model.waiting = Event(), Event()
    stream_response = client.post("/api/chat/stream", json=request_payload, buffered=False)
    live = []
    try:
        for chunk in stream_response.response:
            event = runtime.chats._extract_sse_event_payload(chunk.decode() if isinstance(chunk, bytes) else chunk)
            if event and event.get("type") == "m365_pending_action":
                live.append(event)
            if len(live) == 2:
                break
        require(len(live) == 2, "The in-flight request did not create its real pending actions.")
        calls_before_delete = len(runtime.graph_calls)
        response = client.delete("/api/conversations/delete-inflight")
        require(response.status_code == 200, f"In-flight destination deletion failed: {response.get_json()}")
    finally:
        runtime.model.release.set()
        list(stream_response.response)
        stream_response.close()
    require("delete-inflight" not in config.cosmos_conversations_container.items, "A completing chat request resurrected its deleted delivery destination.")
    require(all(row["status"] == "cancelled" for row in runtime.records("delete-inflight")), "In-flight completion reactivated a retired intent.")
    require(len(runtime.graph_calls) == calls_before_delete, "Destination deletion or stream completion delivered an outgoing action.")
    calls_before_cleanup = len(runtime.graph_calls)

    runtime.prepare("delete-one")
    active = [seed("delete-one", state) for state in ("pending", "scheduled", "review_required")]
    claimed = seed("delete-one", "sending")
    sent = seed("delete-one", "sent")
    response = client.delete("/api/conversations/delete-one")
    require(response.status_code == 200, f"Deletion failed: {response.get_json()}")
    require(all(state(identifier) == "cancelled" for identifier in active), "Deletion left an unsent intent active.")
    require(state(claimed) == "sending" and state(sent) == "sent", "Deletion claimed a send was recalled.")
    require("delete-one" not in config.cosmos_conversations_container.items, "The cancelled destination was not deleted.")

    runtime.prepare("bulk-owned")
    runtime.prepare("bulk-foreign")
    config.cosmos_conversations_container.items["bulk-foreign"]["user_id"] = "other"
    owned_intent = seed("bulk-owned", "scheduled")
    foreign_intent = seed("bulk-foreign", "scheduled", "other")
    response = client.post("/api/delete_multiple_conversations", json={
        "conversation_ids": ["bulk-owned", "bulk-foreign"],
    })
    require(response.status_code == 200 and response.get_json()["deleted_count"] == 1, f"Bulk result is incorrect: {response.get_json()}")
    require(response.get_json()["failed_ids"] == ["bulk-foreign"], "Bulk deletion lost its authorization boundary.")
    require(state(owned_intent) == "cancelled" and state(foreign_intent) == "scheduled", "Bulk cancellation touched an unauthorized destination.")

    runtime.prepare("unavailable")
    unavailable_intent = seed("unavailable", "scheduled")
    runtime.pending.unavailable_queries = True
    try:
        response = client.delete("/api/conversations/unavailable")
    finally:
        runtime.pending.unavailable_queries = False
    require(response.status_code == 503 and "unavailable" in config.cosmos_conversations_container.items, "Storage failure did not preserve the destination for recovery.")
    require(state(unavailable_intent) == "scheduled", "A failed cancellation was reported as cancelled.")
    require("private storage detail" not in response.get_data(as_text=True), "Deletion exposed a provider error.")

    shared = build_personal_collaboration_conversation("Shared", owner, conversation_id="shared")
    shared["source_conversation_id"] = "shared-source"
    runtime.prepare("shared-source")
    config.cosmos_conversations_container.items["shared-source"]["collaboration_conversation_id"] = "shared"
    config.cosmos_collaboration_conversations_container.upsert_item(shared)
    shared_intent = seed("shared", "scheduled")
    source_intent = seed("shared-source", "pending")
    with runtime.web.test_request_context():
        session["user"] = {"oid": "owner", "tid": "tenant", "roles": ["User"]}
        try:
            collaboration.delete_personal_collaboration_conversation("shared", "other")
        except PermissionError:
            pass
        else:
            raise AssertionError("A non-owner could delete a shared destination.")
        require(state(shared_intent) == "scheduled" and state(source_intent) == "pending", "Unauthorized deletion cancelled shared deliveries.")
        collaboration.delete_personal_collaboration_conversation("shared", "owner")
    require(state(shared_intent) == state(source_intent) == "cancelled", "Shared deletion missed its canonical source.")

    shared = build_personal_collaboration_conversation("Co-owned", owner, conversation_id="co-owned")
    shared["owner_user_ids"] = ["owner", "other"]
    shared["source_conversation_id"] = "retained-source"
    runtime.prepare("retained-source")
    config.cosmos_conversations_container.items["retained-source"]["collaboration_conversation_id"] = "co-owned"
    config.cosmos_collaboration_conversations_container.upsert_item(shared)
    retained_intent = seed("retained-source", "scheduled")
    with runtime.web.test_request_context():
        session["user"] = {"oid": "other", "tid": "tenant", "roles": ["User"]}
        collaboration.delete_personal_collaboration_conversation("co-owned", "other")
    require("retained-source" in config.cosmos_conversations_container.items, "A co-owner deleted another user's retained source history.")
    require(state(retained_intent) == "cancelled", "A removed shared destination kept its creator's intent active.")

    shared = build_personal_collaboration_conversation("Unrelated link", owner, conversation_id="unrelated-link")
    shared["source_conversation_id"] = "unrelated-source"
    runtime.prepare("unrelated-source")
    config.cosmos_conversations_container.items["unrelated-source"]["collaboration_conversation_id"] = "a-different-shared-conversation"
    config.cosmos_collaboration_conversations_container.upsert_item(shared)
    unrelated_intent = seed("unrelated-source", "scheduled")
    with runtime.web.test_request_context():
        session["user"] = {"oid": "owner", "tid": "tenant", "roles": ["User"]}
        collaboration.delete_personal_collaboration_conversation("unrelated-link", "owner")
    require(state(unrelated_intent) == "scheduled", "A one-way source pointer cancelled an unrelated conversation.")

    runtime.prepare("retention-personal")
    config.cosmos_conversations_container.items["retention-personal"]["last_updated"] = "2000-01-01T00:00:00Z"
    retention_intent = seed("retention-personal", "review_required")
    with runtime.web.test_request_context():
        session["user"] = {"oid": "owner", "tid": "tenant", "roles": ["User"]}
        result = retention.delete_aged_conversations(30, workspace_type="personal", user_id="owner")
    require(any(item["id"] == "retention-personal" for item in result["details"]), "Eligible personal retention did not run.")
    require(state(retention_intent) == "cancelled", "Retention left its pending review active.")

    shared = build_personal_collaboration_conversation(
        "Old shared", owner, conversation_id="retention-shared", created_at="2000-01-01T00:00:00Z",
    )
    shared["chat_type"] = "group_multi_user"
    shared["scope"] = {"type": "group", "group_id": "group", "visibility_mode": "invited_members"}
    shared["legacy_source_conversation_id"] = "retention-group-source"
    config.cosmos_collaboration_conversations_container.upsert_item(shared)
    config.cosmos_group_conversations_container.upsert_item({
        "id": "retention-group-source", "user_id": "owner", "group_id": "group",
        "collaboration_conversation_id": "retention-shared", "last_updated": "2000-01-01T00:00:00Z",
    })
    group_intent = seed("retention-group-source", "scheduled")
    with runtime.web.test_request_context():
        session["user"] = {"oid": "owner", "tid": "tenant", "roles": ["User"]}
        collaboration.delete_collaboration_conversation_for_retention(shared, "group", False)
    require(state(group_intent) == "cancelled", "Collaboration retention missed its legacy group source.")

    runtime.prepare("retention-first-tick")
    config.cosmos_conversations_container.items["retention-first-tick"]["last_updated"] = "2000-01-01T00:00:00Z"
    first_tick_intent = seed("retention-first-tick", "scheduled")
    owner_settings = config.cosmos_user_settings_container.read_item("owner", "owner")
    owner_settings["settings"]["retention_policy"] = {
        "conversation_retention_days": 30, "document_retention_days": "none",
    }
    config.cosmos_user_settings_container.upsert_item(owner_settings)
    settings_saved = update_settings({
        "enable_retention_policy_personal": True,
        "retention_policy_next_run": None, "retention_policy_last_run": None,
    })
    require(settings_saved, "Scheduler test settings were not saved.")
    with patch.object(delivery, "_dependencies", {}):
        result = background_tasks.check_retention_policy_once()
        require(delivery._dependencies.get("container") is runtime.pending, "Retention depended on the workflow loop initializing delivery first.")
    require(result is not None and result["success"], f"First retention tick failed: {result}")
    require(state(first_tick_intent) == "cancelled", "First-tick scheduler cleanup left an executable intent.")
    require("retention-first-tick" not in config.cosmos_conversations_container.items, "First-tick retention did not delete its authorized destination.")

    runtime.prepare("archived")
    archived_intent = seed("archived", "scheduled")
    settings_saved = update_settings({"enable_conversation_archiving": True})
    require(settings_saved, "Archival test settings were not saved.")
    response = client.delete("/api/conversations/archived")
    require(response.status_code == 200, f"Archival deletion failed: {response.get_json()}")
    require(state(archived_intent) == "cancelled", "Archiving preserved an automatically executable intent.")
    require("archived" in config.cosmos_archived_conversations_container.items, "Archival behavior was lost.")

    # Invoke the real internal operation reached after approval authorization.
    approve = inspect.unwrap(runtime.web.view_functions["backend_control_center.api_approve_request"])
    execute = inspect.getclosurevars(approve).nonlocals["_execute_approved_action"]
    delete_group = inspect.getclosurevars(execute).nonlocals["_execute_delete_group"]
    config.cosmos_group_conversations_container.upsert_item({
        "id": "admin-group-conversation", "group_id": "admin-group", "user_id": "owner",
    })
    admin_intent = seed("admin-group-conversation", "scheduled")
    runtime.pending.unavailable_queries = True
    try:
        with runtime.web.test_request_context():
            session["user"] = {"oid": "admin", "tid": "tenant", "roles": ["Admin"]}
            result = delete_group({"group_id": "admin-group"}, "admin", "admin@example.test", "Admin")
    finally:
        runtime.pending.unavailable_queries = False
    require(result["success"] is False, "Approved group deletion ignored a delivery cancellation outage.")
    require(state(admin_intent) == "scheduled", "A failed group deletion misreported a cancellation.")
    require("admin-group-conversation" in config.cosmos_group_conversations_container.items, "Group cleanup deleted records before stopping their intents.")
    require(len(runtime.graph_calls) == calls_before_cleanup, "Copying, cancellation, archival, or retention called Graph.")


def test_real_conversation_deletion_fork_copy_and_retention_routes():
    result = subprocess.run(
        [sys.executable, str(ROOT / "functional_tests" / "test_m365_chat_action_cards.py"), "--offline", "--lifecycle"],
        cwd=ROOT, capture_output=True, text=True, timeout=150,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-6500:]


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
