# test_conversation_handoffs.py
#!/usr/bin/env python3
"""
Functional test for durable private-conversation handoffs and execution admission (issue #1835).
Version: 0.261.381
Implemented in: 0.261.381

This test ensures deterministic handoff IDs and idempotent duplicate request_id
handling, private-owner authorization on source/destination/references, FIFO
queueing and automatic dispatch after active destination work releases its lease,
parallel worker contention and lease loss/expiration transitioning to
needs_attention without repeating uncertain model effects, queued vs running
cancellation, loop/hop bounds, and Flask route contracts.
"""

import copy
import json
import re
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from azure.core import MatchConditions
from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict
from flask import Blueprint, Flask
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from functions_conversation_handoffs import (
    CONTROL_ID,
    LEASE_SECONDS,
    ConversationHandoffError,
    ConversationHandoffService,
    ConversationHandoffStore,
    digest,
    held_destination,
    public_handoff,
)
from functions_conversation_references import (
    ConversationReferenceError,
    ConversationReferenceService,
    normalize_conversation_references,
)
from test_support.m365 import CosmosContainer
from test_support.offline_bootstrap import offline_app_imports


class HandoffContainer(CosmosContainer):
    """SDK-default point responses, conditional replace, atomic batch, and bounded SQL."""

    def __init__(self, partition_field="destination_conversation_id"):
        super().__init__(partition_field)

    def query_items(self, query, parameters=None, partition_key=None, enable_cross_partition_query=False, max_item_count=100):
        with self.lock:
            values = {item["name"]: item["value"] for item in parameters or []}
            rows = copy.deepcopy(list(self.items.values()))
            if partition_key is not None:
                rows = [row for row in rows if row.get(self.partition_field) == partition_key]
            elif not enable_cross_partition_query:
                raise AssertionError("Cross-partition query required")
            if "@kind" in values:
                rows = [row for row in rows if row.get("kind") == values["@kind"]]
            if "@user" in values:
                rows = [row for row in rows if row.get("user_id") == values["@user"]]
            if "@conversation" in values:
                target = values["@conversation"]
                if "source_conversation_id" in query and "destination_conversation_id" in query:
                    rows = [
                        row for row in rows
                        if row.get("source_conversation_id") == target
                        or row.get("destination_conversation_id") == target
                    ]
                else:
                    rows = [row for row in rows if row.get("conversation_id") == target]
            if "@role" in values:
                rows = [row for row in rows if row.get("role") == values["@role"]]
            if "@id" in values:
                rows = [row for row in rows if row.get("conversation_id") == values["@id"]]
            if "@message_ids" in values:
                rows = [row for row in rows if row.get("id") in values["@message_ids"]]
            if "ARRAY_LENGTH(c.queue) > 0" in query:
                rows = [row for row in rows if len(row.get("queue") or []) > 0]
            if "ORDER BY c.created_at DESC" in query:
                rows.sort(key=lambda row: row.get("created_at", 0), reverse=True)
            elif "ORDER BY c.timestamp DESC" in query:
                rows.sort(key=lambda row: row.get("timestamp", ""), reverse=True)
            top = re.search(r"SELECT TOP (\d+)", query)
            if top:
                rows = rows[:int(top.group(1))]
            elif "@limit" in values:
                rows = rows[:int(values["@limit"])]
            if "SELECT TOP @limit c.destination_conversation_id" in query:
                return [{"destination_conversation_id": row["destination_conversation_id"]} for row in rows]
            return rows


@pytest.fixture
def handoff_env():
    clock = [1000.0]
    conversations = HandoffContainer("id")
    messages = HandoffContainer("conversation_id")
    handoffs = HandoffContainer("destination_conversation_id")

    for conv_id in ("source", "target", "third"):
        conversations.create_item({
            "id": conv_id,
            "user_id": "owner",
            "title": f"Conversation {conv_id}",
            "chat_type": "personal_single_user",
            "last_updated": "2026-01-01T00:00:00Z",
            "tags": [{"category": "participant", "user_id": "owner"}],
        })
    messages.create_item({
        "id": "src-msg-1",
        "conversation_id": "source",
        "role": "user",
        "timestamp": "2026-01-01T00:00:01Z",
        "content": "The quarterly launch target is Q3 with a budget of 9000.",
    })
    messages.create_item({
        "id": "target-seed-user",
        "conversation_id": "target",
        "role": "user",
        "timestamp": "2026-01-01T00:00:02Z",
        "content": "Initial target question",
        "metadata": {
            "model_selection": {
                "selected_model": "gpt-4o",
                "model_id": "model-1",
                "model_endpoint_id": "endpoint-1",
                "model_provider": "aoai",
                "reasoning_effort": "medium",
            }
        },
    })

    reference_service = ConversationReferenceService(
        conversations,
        messages,
        project_messages=lambda rows: rows,
    )
    store = ConversationHandoffStore(handoffs, clock=lambda: clock[0])

    model_calls = []
    unread_marks = []
    approval_checks = []
    model_hook = [None]

    def resolve_destination(user_id, conversation_id):
        reference_service.authorize(user_id, conversation_id)
        rows = messages.query_items(
            query="SELECT TOP 1 c.metadata FROM c WHERE c.conversation_id = @conversation AND c.role = @role ORDER BY c.timestamp DESC",
            parameters=[{"name": "@conversation", "value": conversation_id}, {"name": "@role", "value": "user"}],
            partition_key=conversation_id,
        )
        metadata = rows[0].get("metadata") or {} if rows else {}
        if metadata.get("agent_selection"):
            raise ConversationHandoffError(
                "destination_configuration_unavailable",
                "This destination uses an agent requiring interactive execution.",
            )
        saved = metadata.get("model_selection") or {}
        deployment = saved.get("selected_model") or saved.get("model_deployment")
        if not deployment:
            raise ConversationHandoffError(
                "destination_configuration_unavailable",
                "Send a model-based message in the destination first.",
            )
        config = {
            "conversation_id": conversation_id,
            "model_deployment": deployment,
            "model_id": saved.get("model_id", "model-1"),
            "model_endpoint_id": saved.get("model_endpoint_id", "endpoint-1"),
            "model_provider": saved.get("model_provider", "aoai"),
            "model_name": deployment,
            "reasoning_effort": saved.get("reasoning_effort", ""),
        }
        config["revision"] = digest(config)
        return config

    def generate_turn(job, evidence, before_effect):
        before_effect()
        dest_cfg = job.get("destination_config") or {}
        user_msg = {
            "id": job["destination_user_message_id"],
            "conversation_id": job["destination_conversation_id"],
            "role": "user",
            "content": job["instruction"],
            "timestamp": "2026-01-01T00:01:00Z",
            "metadata": {
                "conversation_references": evidence["references"],
                "conversation_handoff": {
                    "id": job["id"],
                    "source_conversation_id": job["source_conversation_id"],
                    "destination_conversation_id": job["destination_conversation_id"],
                },
                "model_selection": {
                    "selected_model": dest_cfg.get("model_deployment", "gpt-4o"),
                    "model_deployment": dest_cfg.get("model_deployment", "gpt-4o"),
                    "model_id": dest_cfg.get("model_id", "model-1"),
                    "model_endpoint_id": dest_cfg.get("model_endpoint_id", "endpoint-1"),
                    "model_provider": dest_cfg.get("model_provider", "aoai"),
                    "reasoning_effort": dest_cfg.get("reasoning_effort", "medium"),
                },
            },
        }
        try:
            messages.create_item(user_msg)
        except exceptions.CosmosResourceExistsError:
            pass
        before_effect()
        model_calls.append({"job_id": job["id"], "instruction": job["instruction"], "evidence": evidence})
        if model_hook[0] is not None:
            model_hook[0](job, evidence, before_effect)
        before_effect()
        reply = {
            "id": job["destination_message_id"],
            "conversation_id": job["destination_conversation_id"],
            "role": "assistant",
            "content": f"Completed handoff for: {job['instruction']}",
            "reply_to_message_id": user_msg["id"],
            "timestamp": "2026-01-01T00:01:01Z",
            "metadata": user_msg["metadata"],
        }
        return messages.upsert_item(reply)

    def validate_approval(job):
        approval_checks.append(job["approval"])
        return bool(job.get("approval", {}).get("approved", True))

    def mark_unread(job):
        unread_marks.append(job["id"])

    service = ConversationHandoffService(
        store,
        authorize=reference_service.authorize,
        normalize_references=normalize_conversation_references,
        resolve_references=reference_service.resolve,
        resolve_destination=resolve_destination,
        generate=generate_turn,
        validate_approval=validate_approval,
        mark_unread=mark_unread,
    )
    return SimpleNamespace(
        clock=clock,
        conversations=conversations,
        messages=messages,
        handoffs=handoffs,
        reference_service=reference_service,
        store=store,
        service=service,
        resolve_destination=resolve_destination,
        model_calls=model_calls,
        unread_marks=unread_marks,
        approval_checks=approval_checks,
        model_hook=model_hook,
    )


def test_deterministic_ids_and_idempotent_duplicate_request_id(handoff_env):
    raw_point = handoff_env.conversations.read_item("source", "source")
    assert isinstance(raw_point, CosmosDict)

    first = handoff_env.service.enqueue(
        "owner",
        "source",
        "target",
        "Summarize the Q3 launch budget.",
        request_id="req-deterministic-1",
    )
    expected_id = "handoff-" + digest(["owner", "target", "req-deterministic-1"])
    assert first["id"] == expected_id
    assert first["destination_user_message_id"] == f"{expected_id}-user"
    assert first["destination_message_id"] == f"{expected_id}-assistant"
    assert first["sequence"] == 1

    duplicate = handoff_env.service.enqueue(
        "owner",
        "source",
        "target",
        "Summarize the Q3 launch budget.",
        request_id="req-deterministic-1",
    )
    assert duplicate["id"] == first["id"]
    assert duplicate["sequence"] == 1
    control = handoff_env.store.control("target")
    assert control["queue"] == [first["id"]]

    with pytest.raises(ConversationHandoffError) as conflict:
        handoff_env.service.enqueue(
            "owner",
            "source",
            "target",
            "Different instruction with same request_id",
            request_id="req-deterministic-1",
        )
    assert conflict.value.code == "request_conflict"
    assert conflict.value.status_code == 409


@pytest.mark.parametrize("target_conv,mutation", [
    ("source", {"user_id": "other-user"}),
    ("target", {"user_id": "other-user"}),
    ("source", {"is_shared": True}),
    ("target", {"chat_type": "group"}),
    ("target", {"collaboration_conversation_id": "collab-1"}),
    ("third", {"user_id": "intruder"}),
])
def test_destination_and_source_private_owner_authorization(handoff_env, target_conv, mutation):
    existing = handoff_env.conversations.read_item(target_conv, target_conv)
    handoff_env.conversations.upsert_item({**existing, **mutation})
    references = [{"kind": "conversation", "id": "source"}]
    if target_conv == "third":
        references.append({"kind": "conversation", "id": "third"})

    with pytest.raises(ConversationReferenceError) as err:
        handoff_env.service.enqueue(
            "owner",
            "source",
            "target",
            "Check private authorization.",
            references=references,
        )
    assert err.value.code == "conversation_unavailable"
    assert err.value.status_code == 404


def test_busy_destination_fifo_queueing_and_dispatch_after_lease_release(handoff_env):
    with held_destination(handoff_env.store, "owner", "target", "active-chat-stream", kind="chat"):
        job1 = handoff_env.service.enqueue(
            "owner", "source", "target", "First queued task", request_id="fifo-1",
        )
        job2 = handoff_env.service.enqueue(
            "owner", "source", "target", "Second queued task", request_id="fifo-2",
        )
        assert (job1["sequence"], job2["sequence"]) == (1, 2)
        assert handoff_env.service.dispatch("target") is None
        assert handoff_env.model_calls == []

        with pytest.raises(ConversationHandoffError) as busy_chat:
            handoff_env.store.acquire("owner", "target", "second-chat", kind="chat")
        assert busy_chat.value.code == "destination_busy"

    # Even after active stream releases, normal chat yields to queued FIFO handoffs first.
    with pytest.raises(ConversationHandoffError) as queued_first:
        handoff_env.store.acquire("owner", "target", "chat-while-queued", kind="chat")
    assert queued_first.value.code == "destination_busy"

    completed1 = handoff_env.service.dispatch("target")
    assert completed1["id"] == job1["id"]
    assert completed1["status"] == "completed"

    completed2 = handoff_env.service.dispatch("target")
    assert completed2["id"] == job2["id"]
    assert completed2["status"] == "completed"
    assert [call["job_id"] for call in handoff_env.model_calls] == [job1["id"], job2["id"]]
    assert handoff_env.unread_marks == [job1["id"], job2["id"]]
    assert handoff_env.store.control("target")["queue"] == []

    # Destination is now free for normal chat again.
    lease = handoff_env.store.acquire("owner", "target", "chat-after-queue", kind="chat")
    lease.close()


def test_parallel_worker_contention_and_lease_loss_transitions_to_needs_attention(handoff_env):
    job = handoff_env.service.enqueue(
        "owner", "source", "target", "Run once under contention", request_id="contention-1",
    )
    entered_model = threading.Event()
    proceed_model = threading.Event()

    def slow_hook(_job, _evidence, _before_effect):
        entered_model.set()
        proceed_model.wait(timeout=5)

    handoff_env.model_hook[0] = slow_hook
    results = []
    worker = threading.Thread(target=lambda: results.append(handoff_env.service.dispatch("target")))
    worker.start()
    assert entered_model.wait(timeout=5)

    # A second worker attempting to dispatch while the first holds the lease must be a no-op.
    assert handoff_env.service.dispatch("target") is None
    proceed_model.set()
    worker.join(timeout=5)
    assert len(results) == 1 and results[0]["status"] == "completed"
    assert len(handoff_env.model_calls) == 1

    # Now simulate lease expiration during model execution: status must become needs_attention
    # and the destination must remain blocked until reviewed (no blind replay).
    job_expired = handoff_env.service.enqueue(
        "owner", "source", "target", "Uncertain interrupted call", request_id="lease-expired-1",
    )

    def expire_lease_during_model(_job, _evidence, _before_effect):
        handoff_env.clock[0] += LEASE_SECONDS + 10

    handoff_env.model_hook[0] = expire_lease_during_model
    outcome = handoff_env.service.dispatch("target")
    assert outcome["id"] == job_expired["id"]
    assert outcome["status"] == "needs_attention"
    assert outcome["error_code"] == "lease_lost"
    assert len(handoff_env.model_calls) == 2

    # Subsequent dispatch or chat must not replay the uncertain job or bypass needs_attention.
    assert handoff_env.service.dispatch("target") is None
    assert len(handoff_env.model_calls) == 2
    with pytest.raises(ConversationHandoffError) as blocked:
        handoff_env.store.acquire("owner", "target", "chat-blocked", kind="chat")
    assert blocked.value.code in ("destination_busy", "destination_needs_attention")

    with pytest.raises(ConversationHandoffError) as cancel_uncertain:
        handoff_env.service.cancel("owner", "target", job_expired["id"])
    assert cancel_uncertain.value.code == "uncertain_execution"


def test_expired_active_handoff_lease_is_marked_needs_attention_on_dispatch(handoff_env):
    job = handoff_env.service.enqueue(
        "owner", "source", "target", "Stalled worker task", request_id="stalled-1",
    )
    lease = handoff_env.store.acquire("owner", "target", job["id"], kind="handoff")
    assert lease.token
    handoff_env.clock[0] += LEASE_SECONDS + 5

    with pytest.raises(ConversationHandoffError) as attention_err:
        handoff_env.store.acquire("owner", "target", "chat-after-stall", kind="chat")
    assert attention_err.value.code == "destination_needs_attention"

    assert handoff_env.service.dispatch("target") is None
    updated = handoff_env.service.get("owner", "target", job["id"])
    assert updated["status"] == "needs_attention"
    assert handoff_env.model_calls == []


def test_cancellation_while_queued_vs_running(handoff_env):
    queued_job = handoff_env.service.enqueue(
        "owner", "source", "target", "Cancel before start", request_id="cancel-queued",
    )
    cancelled = handoff_env.service.cancel("owner", "target", queued_job["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancel_requested"] is True
    assert handoff_env.store.control("target")["queue"] == []
    assert handoff_env.service.dispatch("target") is None
    assert handoff_env.model_calls == []

    # Cancel while running (before external model effect completes):
    running_job = handoff_env.service.enqueue(
        "owner", "source", "target", "Cancel during execution", request_id="cancel-running",
    )

    def cancel_during_run(job, _evidence, _before_effect):
        handoff_env.service.cancel("owner", "target", job["id"])

    handoff_env.model_hook[0] = cancel_during_run
    finished = handoff_env.service.dispatch("target")
    assert finished["status"] == "cancelled"
    assert finished["error_code"] == "cancelled"
    assert handoff_env.store.control("target")["queue"] == []


def test_loop_and_hop_bounds_refuse_self_send_cycles_and_second_hop(handoff_env):
    with pytest.raises(ConversationHandoffError) as self_send:
        handoff_env.service.enqueue("owner", "source", "source", "Self send")
    assert self_send.value.code == "handoff_cycle"
    assert self_send.value.status_code == 400

    with pytest.raises(ConversationHandoffError) as dest_ref:
        handoff_env.service.enqueue(
            "owner",
            "source",
            "target",
            "Destination referenced as external source",
            references=[{"kind": "conversation", "id": "target"}],
        )
    assert dest_ref.value.code == "handoff_cycle"

    with pytest.raises(ConversationHandoffError) as missing_approval:
        handoff_env.service.enqueue(
            "owner",
            "source",
            "target",
            "Automated origin without approval",
            origin={"kind": "orchestration", "visited_conversation_ids": ["source"], "hop_count": 0},
        )
    assert missing_approval.value.code == "approval_required"

    with pytest.raises(ConversationHandoffError) as cycle_visited:
        handoff_env.service.enqueue(
            "owner",
            "source",
            "target",
            "Target already visited",
            approval={"approved": True},
            origin={"kind": "orchestration", "visited_conversation_ids": ["source", "target"], "hop_count": 0},
        )
    assert cycle_visited.value.code == "handoff_cycle"

    with pytest.raises(ConversationHandoffError) as hop_exceeded:
        handoff_env.service.enqueue(
            "owner",
            "source",
            "target",
            "Second hop attempt",
            approval={"approved": True},
            origin={"kind": "orchestration", "visited_conversation_ids": ["third", "source"], "hop_count": 1},
        )
    assert hop_exceeded.value.code == "handoff_cycle"


def test_flask_route_contracts_and_chat_handoff_integration(handoff_env, monkeypatch):
    import werkzeug

    if not hasattr(werkzeug, "__version__"):
        werkzeug.__version__ = "3"

    with offline_app_imports():
        import route_backend_conversation_handoffs as handoff_routes
        import route_backend_chats as chats
        register_route_backend_conversation_handoffs = handoff_routes.register_route_backend_conversation_handoffs

    monkeypatch.setattr(handoff_routes, "get_current_user_id", lambda: "owner")
    monkeypatch.setattr(handoff_routes, "log_event", lambda *args, **kwargs: None)

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    bp = Blueprint("backend_conversation_handoffs", __name__)
    register_route_backend_conversation_handoffs(
        bp,
        service_factory=lambda: handoff_env.service,
        destination_resolver=handoff_env.resolve_destination,
    )
    app.register_blueprint(bp)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = {"oid": "owner", "name": "Owner", "roles": ["User"]}

        preview_res = client.get("/api/conversation-handoffs/destination/target")
        assert preview_res.status_code == 200
        assert preview_res.headers.get("Cache-Control") == "no-store"
        dest_cfg = preview_res.get_json()["destination_config"]
        assert dest_cfg["conversation_id"] == "target"
        assert dest_cfg["model_deployment"] == "gpt-4o"

        # Hold destination lease to verify POST enqueues as 'queued' when busy,
        # and releasing via chat stream completion dispatches automatically.
        active_lease = handoff_env.store.acquire("owner", "target", "active-stream", kind="chat")

        post_queued = client.post(
            "/api/conversation-handoffs",
            json={
                "source_conversation_id": "source",
                "destination_conversation_id": "target",
                "instruction": "Queued via HTTP route",
                "conversation_references": [{"kind": "conversation", "id": "source"}],
                "request_id": "http-req-1",
                "destination_config_revision": dest_cfg["revision"],
            },
        )
        assert post_queued.status_code == 200
        queued_payload = post_queued.get_json()["handoff"]
        assert queued_payload["status"] == "queued"
        assert "fingerprint" not in queued_payload
        handoff_id = queued_payload["id"]

        get_res = client.get(f"/api/conversation-handoffs/{handoff_id}?destination_conversation_id=target")
        assert get_res.status_code == 200
        assert get_res.get_json()["handoff"]["id"] == handoff_id

        list_res = client.get("/api/conversation-handoffs?conversation_id=source&destination_preview_id=target")
        assert list_res.status_code == 200
        list_json = list_res.get_json()
        assert [item["id"] for item in list_json["handoffs"]] == [handoff_id]
        assert list_json["destination_config"]["revision"] == dest_cfg["revision"]

        # Release the active chat lease and trigger route_backend_chats post-chat release hook:
        monkeypatch.setattr(chats, "cosmos_conversation_handoffs_container", handoff_env.handoffs)
        monkeypatch.setattr(chats, "release_destination", lambda lease: lease.close())
        monkeypatch.setattr(chats, "dispatch_conversation_handoffs_once", lambda: [handoff_env.service.dispatch("target")])
        chats._release_chat_destination_lease(active_lease, "target")

        after_release = client.get(f"/api/conversation-handoffs/{handoff_id}?destination_conversation_id=target")
        assert after_release.status_code == 200
        assert after_release.get_json()["handoff"]["status"] == "completed"

        # Enqueue and cancel a second queued handoff via HTTP route:
        with held_destination(handoff_env.store, "owner", "target", "busy-2", kind="chat"):
            second = client.post(
                "/api/conversation-handoffs",
                json={
                    "source_conversation_id": "source",
                    "destination_conversation_id": "target",
                    "instruction": "Cancel me via HTTP",
                    "request_id": "http-req-2",
                },
            ).get_json()["handoff"]
            assert second["status"] == "queued"
            cancel_res = client.post(
                f"/api/conversation-handoffs/{second['id']}/cancel",
                json={"destination_conversation_id": "target"},
            )
            assert cancel_res.status_code == 200
            assert cancel_res.get_json()["handoff"]["status"] == "cancelled"

        # Error mapping never exposes internal exception strings:
        cycle_res = client.post(
            "/api/conversation-handoffs",
            json={
                "source_conversation_id": "source",
                "destination_conversation_id": "source",
                "instruction": "Cycle attempt",
            },
        )
        assert cycle_res.status_code == 400
        assert cycle_res.get_json() == {
            "error": "Choose a different destination conversation.",
            "code": "handoff_cycle",
        }


def test_chat_reference_resolution_and_replay_do_not_enable_workspace_search(handoff_env, monkeypatch):
    with offline_app_imports():
        import route_backend_chats as chats
        from route_backend_conversations import _build_replayed_document_context

    monkeypatch.setattr(
        chats,
        "resolve_conversation_references",
        lambda user_id, refs, query="", destination_id=None: handoff_env.reference_service.resolve(
            user_id, refs, query=query, destination_id=destination_id,
        ),
    )
    app = Flask(__name__)
    with app.test_request_context():
        resolved = chats._resolve_chat_conversation_references(
            "owner",
            {"conversation_references": [{"kind": "conversation", "id": "source"}]},
            query="launch budget",
            destination_id="target",
        )
        assert resolved["references"][0]["id"] == "source"
        assert resolved["references"][0]["revision"]
        assert "9000" in resolved["prompt"]

        history_meta = chats._analysis_history_metadata()
        assert history_meta["conversation_references"] == resolved["references"]
        assert history_meta["conversation_reference_revision"] == resolved["revision"]

        replayed = _build_replayed_document_context({
            "workspace_search": {"search_enabled": False},
            "conversation_references": resolved["references"],
        })
        assert replayed["hybrid_search"] is False
        assert replayed["document_context_requested"] is False
        assert replayed["selected_document_ids"] == []
        assert replayed["conversation_references"] == [{"kind": "conversation", "id": "source"}]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
